// PHASE node firmware for the Heltec WiFi LoRa 32 V3.
// node runs its own AP, the paired sender joins and transmits 100/s, and we read the
// CSI of those frames to spot motion. it's the AP because a listening ESP32-S3 barely gets any CSI.
#include <Arduino.h>
#include <WiFi.h>
#include <WiFiUdp.h>
#include <esp_wifi.h>
#include <esp_task_wdt.h>
#include <driver/i2s.h>
#include <math.h>
#include <string.h>
#include <SSD1306Wire.h>
#include "config.h"
#include "pins.h"
#include "ghost_protocol.h"
#if !SIGNAL_VIEW
  #include <RadioLib.h>
#endif

// 1 = print what the CSI callback receives (len, src mac). back to 0 once it works,
// it costs serial time.
#define CSI_DIAGNOSTIC 1

// 52 usable subcarriers (-26..-1 and +1..+26), handed to us as (I,Q) int8 pairs in
// FFT order: pair k is subcarrier k for k=0..31 and k-64 for k=32..63. len is 128
// for LLTF only, 256 when the HT-LTF set follows it.
#define NUM_SUBCARRIERS  52
#define CSI_QUEUE_LENGTH 64
#define CSI_MIN_LEN      128

struct CsiFrame {
  float    amp[NUM_SUBCARRIERS];
  int8_t   rssi;
  uint32_t stampUs;
};

static QueueHandle_t     csiQueue       = nullptr;
static uint8_t           senderMac[6]   = {0};
static volatile bool     senderMacKnown = false;
static volatile uint32_t csiReceived    = 0;   // passed every filter, queued
static volatile uint32_t csiDropped     = 0;   // queue was full
static volatile uint32_t lastCsiMillis  = 0;
static volatile uint32_t csiRaw         = 0;   // every callback, pre-filter
static volatile uint32_t csiWrongMac    = 0;   // rejected: not from our sender
static volatile uint32_t csiTooShort    = 0;   // right sender, but too few bytes

// Called by the WiFi driver (in its own task, not an interrupt) for every frame
// with CSI. Must be quick: filter, convert I/Q to amplitude, queue, leave.
static void csiCallback(void* ctx, wifi_csi_info_t* info) {
  (void)ctx;
  if (!info || !info->buf) return;

  csiRaw++;
  lastCsiMillis = millis();

#if CSI_DIAGNOSTIC
  // Print one sample every 2 s so we can see what is actually arriving.
  static uint32_t lastDiagMs = 0;
  if (millis() - lastDiagMs > 2000) {
    lastDiagMs = millis();
    Serial.printf("[CSI] len=%d rssi=%d src=%02X:%02X:%02X:%02X:%02X:%02X want=%02X:%02X:%02X:%02X:%02X:%02X\n",
                  info->len, info->rx_ctrl.rssi,
                  info->mac[0], info->mac[1], info->mac[2],
                  info->mac[3], info->mac[4], info->mac[5],
                  senderMac[0], senderMac[1], senderMac[2],
                  senderMac[3], senderMac[4], senderMac[5]);
  }
#endif

  if (!senderMacKnown) return;
  if (memcmp(info->mac, senderMac, 6) != 0) { csiWrongMac++; return; }
  if (info->len < CSI_MIN_LEN)             { csiTooShort++; return; }

  const int8_t* iq = info->buf;

  CsiFrame f;
  int n = 0;
  for (int sc = -26; sc <= -1; sc++) {                // negative subcarriers: pairs 38..63
    int k = 64 + sc;
    float i = iq[2 * k], q = iq[2 * k + 1];
    f.amp[n++] = sqrtf(i * i + q * q);
  }
  for (int sc = 1; sc <= 26; sc++) {                  // positive subcarriers: pairs 1..26
    float i = iq[2 * sc], q = iq[2 * sc + 1];
    f.amp[n++] = sqrtf(i * i + q * q);
  }
  f.rssi    = info->rx_ctrl.rssi;
  f.stampUs = micros();

  csiReceived++;
  if (xQueueSend(csiQueue, &f, 0) != pdTRUE) csiDropped++;   // never block the WiFi task
}

static void csiStart() {
  wifi_csi_config_t cfg;
  memset(&cfg, 0, sizeof(cfg));
  cfg.lltf_en           = true;   // legacy long training field, in every OFDM frame
  cfg.htltf_en          = true;   // HT (802.11n) training field, when present
  cfg.stbc_htltf2_en    = false;
  cfg.ltf_merge_en      = true;
  cfg.channel_filter_en = true;
  cfg.manu_scale        = false;
  cfg.shift             = 0;

  esp_err_t e1 = esp_wifi_set_csi_config(&cfg);
  esp_err_t e2 = esp_wifi_set_csi_rx_cb(csiCallback, nullptr);
  esp_err_t e3 = esp_wifi_set_csi(true);

  Serial.printf("[NODE] CSI setup: config=%d cb=%d enable=%d  (0 = OK)\n",
                (int)e1, (int)e2, (int)e3);
}

// radar engine, same idea as esp-radar: learn a baseline then score how far off it is
enum NodeState : uint8_t {
  ST_BASELINING = GHOST_STATE_BASELINING,
  ST_CLEAR      = GHOST_STATE_CLEAR,
  ST_PRESENCE   = GHOST_STATE_PRESENCE,
  ST_MOVING     = GHOST_STATE_MOVING
};

struct Radar {
  enum Phase { LEARN_MEAN, LEARN_NOISE, RUN } phase;
  uint32_t phaseStartMs;

  // Baseline: the average *shape* of the amplitude vector in an empty room.
  float    base[NUM_SUBCARRIERS];
  float    baseSum[NUM_SUBCARRIERS];
  uint32_t baseCount;

  // Noise model: how far a still room normally deviates from that baseline.
  float    noiseMean, noiseSd;
  double   noiseSum, noiseSq;
  uint32_t noiseCount;

  float     raw;        // this packet's motion score (0 = identical to baseline)
  float     smooth;     // EMA-smoothed motion score, this is what the thresholds act on
  float     breath;     // slow-band (0.1-0.5 Hz) energy indicator, optional extra
  NodeState state;
  uint32_t  lastUs;
  uint32_t  aboveSinceMs, belowSinceMs;   // hysteresis timers (0 = not running)

  // Breathing-band helpers: a cheap band-pass made from two EMAs of the deviation
  float bpFast, bpSlow;

  void reset() {
    phase = LEARN_MEAN;
    phaseStartMs = millis();
    memset(baseSum, 0, sizeof(baseSum));
    baseCount = 0;
    noiseSum = noiseSq = 0;
    noiseCount = 0;
    noiseMean = 0; noiseSd = 0;
    raw = smooth = breath = 0;
    bpFast = bpSlow = 0;
    state = ST_BASELINING;
    lastUs = 0;
    aboveSinceMs = belowSinceMs = 0;
  }

  bool learning() const { return phase != RUN; }

  // Deviation of a normalised amplitude vector from the baseline: mean absolute
  // difference across subcarriers. Scale-free thanks to the normalisation.
  float deviation(const float* an) const {
    float d = 0;
    for (int i = 0; i < NUM_SUBCARRIERS; i++) d += fabsf(an[i] - base[i]);
    return d / NUM_SUBCARRIERS;
  }

  void process(const float* amp, uint32_t stampUs) {
    // Normalise by the packet's mean amplitude. The WiFi chip's automatic gain
    // control rescales every packet, so absolute amplitude is meaningless; the
    // *shape* across subcarriers is what the room changes.
    float mean = 0;
    for (int i = 0; i < NUM_SUBCARRIERS; i++) mean += amp[i];
    mean /= NUM_SUBCARRIERS;
    if (mean < 1e-3f) return;
    float an[NUM_SUBCARRIERS];
    for (int i = 0; i < NUM_SUBCARRIERS; i++) an[i] = amp[i] / mean;

    const uint32_t meanMs  = (uint32_t)BASELINE_SECONDS * 1000UL * 2 / 3;  // first 2/3: learn shape
    const uint32_t noiseMs = (uint32_t)BASELINE_SECONDS * 1000UL / 3;      // last 1/3: learn jitter
    uint32_t nowMs = millis();

    switch (phase) {
      case LEARN_MEAN:
        for (int i = 0; i < NUM_SUBCARRIERS; i++) baseSum[i] += an[i];
        baseCount++;
        if (nowMs - phaseStartMs >= meanMs) {
          if (baseCount < 20) { phaseStartMs = nowMs; return; }   // too few packets, keep going
          for (int i = 0; i < NUM_SUBCARRIERS; i++) base[i] = baseSum[i] / baseCount;
          phase = LEARN_NOISE;
          phaseStartMs = nowMs;
        }
        return;

      case LEARN_NOISE: {
        float d = deviation(an);
        noiseSum += d; noiseSq += (double)d * d; noiseCount++;
        if (nowMs - phaseStartMs >= noiseMs) {
          if (noiseCount < 20) { phaseStartMs = nowMs; return; }
          noiseMean = (float)(noiseSum / noiseCount);
          double var = noiseSq / noiseCount - (double)noiseMean * noiseMean;
          noiseSd = (float)sqrt(var > 0 ? var : 0);
          if (noiseSd < 1e-4f) noiseSd = 1e-4f;
          phase  = RUN;
          state  = ST_CLEAR;
          smooth = 0;
          bpFast = bpSlow = noiseMean;
          lastUs = stampUs;
        }
        return;
      }

      case RUN:
        break;
    }

    float d = deviation(an);
    // Motion score: how many NOISE_SCALE-sigmas above the still-room jitter we are.
    // 0.0 = indistinguishable from empty room. 1.0 = NOISE_SCALE sigmas out.
    raw = (d - noiseMean) / (NOISE_SCALE * noiseSd);
    if (raw < 0) raw = 0;
    if (raw > 2.0f) raw = 2.0f;

    // Time step from packet timestamps (CSI rate is ~100/s but can hiccup).
    float dt = (stampUs - lastUs) * 1e-6f;
    lastUs = stampUs;
    if (dt <= 0 || dt > 1.0f) dt = 0.01f;

    // Exponential moving average with a fixed time constant regardless of rate.
    float a = 1.0f - expf(-dt / MOTION_EMA_TAU_S);
    smooth += a * (raw - smooth);

    // Breathing-band indicator: chest movement wobbles the channel slowly
    // (0.1-0.5 Hz). Band-pass = fast EMA (0.5 s) minus slow EMA (5 s) of the
    // deviation; report the EMA of its magnitude. Three multiplies per packet.
    float af = 1.0f - expf(-dt / 0.5f);
    float as = 1.0f - expf(-dt / 5.0f);
    bpFast += af * (d - bpFast);
    bpSlow += as * (d - bpSlow);
    float band = fabsf(bpFast - bpSlow) / (NOISE_SCALE * noiseSd);
    float ab = 1.0f - expf(-dt / 10.0f);
    breath += ab * (band - breath);

    bool present = (state == ST_PRESENCE || state == ST_MOVING);
    if (!present) {
      if (smooth > PRESENCE_ON_THRESHOLD) {
        if (aboveSinceMs == 0) aboveSinceMs = nowMs;
        if (nowMs - aboveSinceMs >= PRESENCE_ON_HOLD_MS) { state = ST_PRESENCE; present = true; belowSinceMs = 0; }
      } else {
        aboveSinceMs = 0;
      }
    }
    if (present) {
      if (smooth < PRESENCE_OFF_THRESHOLD) {
        if (belowSinceMs == 0) belowSinceMs = nowMs;
        if (nowMs - belowSinceMs >= PRESENCE_OFF_HOLD_MS) { state = ST_CLEAR; present = false; aboveSinceMs = 0; }
      } else {
        belowSinceMs = 0;
      }
      if (present) state = (smooth > MOVING_THRESHOLD) ? ST_MOVING : ST_PRESENCE;
    }

    // a still, empty room drifts (temperature, the wifi chip warming up). while
    // we're CLEAR and quiet, nudge the baseline and noise model toward what we see,
    // very slowly, so the score re-centres on 0.
    if (state == ST_CLEAR && raw < PRESENCE_OFF_THRESHOLD) {
      float aa = 1.0f - expf(-dt / ADAPT_TAU_S);
      for (int i = 0; i < NUM_SUBCARRIERS; i++) base[i] += aa * (an[i] - base[i]);
      noiseMean += aa * (d - noiseMean);
      // Mean absolute deviation ~ 0.8 sigma for Gaussian noise, so x1.25 to track sigma.
      noiseSd   += aa * (fabsf(d - noiseMean) * 1.25f - noiseSd);
      if (noiseSd < 1e-4f) noiseSd = 1e-4f;
    }
  }
};

static Radar radar;

// audio: INMP441 over I2S, runs in its own task on core 0
static volatile float audioDb = 0;   // latest 250 ms window, relative dB

static void audioTask(void* arg) {
  (void)arg;
  i2s_config_t cfg = {};
  cfg.mode                 = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_RX);
  cfg.sample_rate          = AUDIO_SAMPLE_RATE;
  cfg.bits_per_sample      = I2S_BITS_PER_SAMPLE_32BIT;   // INMP441 outputs 24-bit in a 32-bit slot
  cfg.channel_format       = I2S_CHANNEL_FMT_ONLY_LEFT;   // L/R pin tied to GND = left channel
  cfg.communication_format = I2S_COMM_FORMAT_STAND_I2S;
  cfg.intr_alloc_flags     = ESP_INTR_FLAG_LEVEL1;
  cfg.dma_buf_count        = 4;
  cfg.dma_buf_len          = 256;
  cfg.use_apll             = false;
  cfg.tx_desc_auto_clear   = false;
  cfg.fixed_mclk           = 0;

  i2s_pin_config_t pins = {};
  pins.mck_io_num   = I2S_PIN_NO_CHANGE;
  pins.bck_io_num   = GH_I2S_SCK;
  pins.ws_io_num    = GH_I2S_WS;
  pins.data_out_num = I2S_PIN_NO_CHANGE;
  pins.data_in_num  = GH_I2S_SD;

  if (i2s_driver_install(I2S_NUM_0, &cfg, 0, nullptr) != ESP_OK ||
      i2s_set_pin(I2S_NUM_0, &pins) != ESP_OK) {
    Serial.println("[NODE] I2S init failed, audio disabled");
    vTaskDelete(nullptr);
    return;
  }
  i2s_zero_dma_buffer(I2S_NUM_0);

  static int32_t buf[256];
  const uint32_t windowSamples = (uint32_t)AUDIO_SAMPLE_RATE * AUDIO_WINDOW_MS / 1000;  // 4000
  double   sumSq = 0;
  uint32_t n     = 0;

  for (;;) {
    size_t bytes = 0;
    if (i2s_read(I2S_NUM_0, buf, sizeof(buf), &bytes, portMAX_DELAY) != ESP_OK) continue;
    size_t count = bytes / sizeof(int32_t);
    for (size_t i = 0; i < count; i++) {
      int32_t s = buf[i] >> 8;              // 24-bit sample, sign preserved
      sumSq += (double)s * (double)s;
    }
    n += count;
    if (n >= windowSamples) {
      float rms = sqrt(sumSq / n);
      float db  = (rms > 1.0f) ? 20.0f * log10f(rms) : 0.0f;   // 0 dB = 1 LSB
      db += AUDIO_DB_OFFSET;
      if (db < 0) db = 0;
      if (db > 255) db = 255;
      audioDb = db;
      sumSq = 0;
      n = 0;
    }
  }
}

static uint8_t batteryPct = 0;

static uint8_t readBatteryPercent() {
  digitalWrite(GH_BATT_CTRL, LOW);     // connect the divider
  delay(20);                           // was 5, high-impedance divider needs longer
  uint32_t mv = 0, raw = 0;
  for (int i = 0; i < 16; i++) {
    mv  += analogReadMilliVolts(GH_BATT_ADC);
    raw += analogRead(GH_BATT_ADC);
  }
  mv /= 16;
  raw /= 16;
  digitalWrite(GH_BATT_CTRL, HIGH);    // disconnect to save current

  float volts = (mv / 1000.0f) * GH_BATT_DIVIDER_RATIO;
  float pct   = (volts - 3.3f) / (4.2f - 3.3f) * 100.0f;

  static uint32_t lastBattDbg = 0;
  if (millis() - lastBattDbg > 5000) {
    lastBattDbg = millis();
    Serial.printf("[BATT] raw=%lu mv=%lu volts=%.2f pct=%.0f\n",
                  (unsigned long)raw, (unsigned long)mv, volts, pct);
  }

  if (pct < 0) pct = 0;
  if (pct > 100) pct = 100;
  return (uint8_t)(pct + 0.5f);
}

static SSD1306Wire display(0x3c, GH_OLED_SDA, GH_OLED_SCL);
static float    packetsPerSecond = 0;
static bool     wifiUp   = false;
static bool     loraUp   = false;
static uint32_t loraMisses = 0;

static const char* stateName(uint8_t s) {
  switch (s) {
    case ST_CLEAR:    return "CLEAR";
    case ST_PRESENCE: return "PRESENCE";
    case ST_MOVING:   return "MOVING";
    default:          return "BASELINING";
  }
}

static void displayInit() {
  pinMode(GH_VEXT, OUTPUT);
  digitalWrite(GH_VEXT, LOW);          // power the OLED
  delay(50);
  pinMode(GH_OLED_RST, OUTPUT);
  digitalWrite(GH_OLED_RST, LOW);
  delay(20);
  digitalWrite(GH_OLED_RST, HIGH);
  delay(20);
  display.init();
  display.flipScreenVertically();
  display.setTextAlignment(TEXT_ALIGN_LEFT);
}

static void displayUpdate() {
  char line[32];
  display.clear();

  display.setFont(ArialMT_Plain_16);
  snprintf(line, sizeof(line), "%c  %s", ZONE_ID, stateName(radar.state));
  display.drawString(0, 0, line);

  display.setFont(ArialMT_Plain_10);
  snprintf(line, sizeof(line), "motion %.2f   %.0f pkt/s", radar.smooth, packetsPerSecond);
  display.drawString(0, 20, line);
  snprintf(line, sizeof(line), "audio %.0f dB   batt %u%%", audioDb, batteryPct);
  display.drawString(0, 32, line);
#if SIGNAL_VIEW
  snprintf(line, sizeof(line), "sender %s   SIGNAL_VIEW", senderMacKnown ? "ok" : "--");
#else
  snprintf(line, sizeof(line), "sender %s   lora %s%s", senderMacKnown ? "ok" : "--",
           loraUp ? "ok" : "--", (loraUp && loraMisses >= LORA_MISSES_BEFORE_RETRY) ? " (no gw)" : "");
#endif
  display.drawString(0, 44, line);
  if (radar.learning()) {
    display.drawString(0, 54, "learning empty room...");
  } else {
    snprintf(line, sizeof(line), "breath %.2f", radar.breath);
    display.drawString(0, 54, line);
  }
  display.display();
}

// LoRa, compiled out in SIGNAL_VIEW mode
#if !SIGNAL_VIEW
static SX1262 radio = new Module(GH_LORA_NSS, GH_LORA_DIO1, GH_LORA_RST, GH_LORA_BUSY, SPI);
static volatile bool radioFlag = false;
static uint16_t      loraSeq   = 0;
static GhostDataPacket lastPacket;

static void IRAM_ATTR onRadioIrq() { radioFlag = true; }

static bool loraInit() {
  SPI.begin(GH_LORA_SCK, GH_LORA_MISO, GH_LORA_MOSI, GH_LORA_NSS);
  // begin(freq, bw, sf, cr, syncWord, power, preambleLen, tcxoVoltage, useLDO)
  // Heltec V3 feeds the SX1262 a 1.8V TCXO from DIO3 and uses DIO2 for the RF
  // switch. tell RadioLib both or the radio stays deaf.
  int st = radio.begin(LORA_FREQUENCY_MHZ, LORA_BANDWIDTH_KHZ, LORA_SPREADING_FACTOR,
                       LORA_CODING_RATE, LORA_SYNC_WORD, LORA_TX_POWER_DBM, 8, 1.8f, false);
  if (st != RADIOLIB_ERR_NONE) {
    Serial.printf("[NODE] LoRa init failed, code %d\n", st);
    return false;
  }
  radio.setDio2AsRfSwitch(true);
  radio.setCRC(2);   // 2-byte CRC on every packet
  radio.setPacketReceivedAction(onRadioIrq);
  Serial.printf("[NODE] LoRa ready: %.1f MHz SF%d BW%.0f CR4/%d sync 0x%02X %d dBm\n",
                LORA_FREQUENCY_MHZ, LORA_SPREADING_FACTOR, LORA_BANDWIDTH_KHZ,
                LORA_CODING_RATE, LORA_SYNC_WORD, LORA_TX_POWER_DBM);
  return true;
}

// Executes a command from the gateway after acknowledging it.
static void loraHandleCommand(uint8_t cmd) {
  GhostAckPacket ack = { GHOST_MAGIC, GHOST_PKT_ACK, (uint8_t)ZONE_ID, cmd };
  radio.transmit((uint8_t*)&ack, sizeof(ack));
  radioFlag = false;
  Serial.printf("[NODE] command '%c' from gateway, acked\n", cmd);
  if (cmd == GHOST_CMD_BASELINE) {
    radar.reset();
  } else if (cmd == GHOST_CMD_REBOOT) {
    Serial.println("[NODE] rebooting");
    delay(50);
    ESP.restart();
  }
}

// Sends one packet, then listens LORA_LISTEN_MS for the gateway's reply.
// Returns true if the gateway answered.
static bool loraSendAndListen(const GhostDataPacket& pkt) {
  int st = radio.transmit((uint8_t*)&pkt, sizeof(pkt));
  radioFlag = false;                       // TX-done also pulses DIO1; ignore it
  if (st != RADIOLIB_ERR_NONE) {
    Serial.printf("[NODE] LoRa TX error %d\n", st);
    return false;
  }
  radio.startReceive();
  uint32_t t0 = millis();
  while (!radioFlag && millis() - t0 < LORA_LISTEN_MS) delay(1);
  bool answered = false;
  if (radioFlag) {
    radioFlag = false;
    uint8_t buf[16];
    size_t len = radio.getPacketLength();
    if (len <= sizeof(buf) && radio.readData(buf, len) == RADIOLIB_ERR_NONE &&
        len == sizeof(GhostReplyPacket) && buf[0] == GHOST_MAGIC &&
        buf[1] == GHOST_PKT_REPLY && buf[2] == (uint8_t)ZONE_ID) {
      answered = true;
      uint8_t cmd = buf[3];
      radio.standby();
      if (cmd != GHOST_CMD_NONE) loraHandleCommand(cmd);
    }
  }
  radio.standby();
  return answered;
}

static void loraUplink() {
  GhostDataPacket pkt;
  pkt.magic       = GHOST_MAGIC;
  pkt.type        = GHOST_PKT_DATA;
  pkt.zone        = (uint8_t)ZONE_ID;
  pkt.seq         = loraSeq++;
  pkt.presence    = (radar.state == ST_PRESENCE || radar.state == ST_MOVING) ? 1 : 0;
  float m100      = radar.smooth * 100.0f;
  pkt.motion_x100 = (uint8_t)(m100 > 255 ? 255 : m100 + 0.5f);
  pkt.audio_db    = (uint8_t)audioDb;
  pkt.battery_pct = batteryPct;
  pkt.state       = (uint8_t)radar.state;
  lastPacket = pkt;

  bool ok = loraSendAndListen(pkt);
  if (ok) {
    loraMisses = 0;
  } else {
    loraMisses++;
    if (loraMisses == LORA_MISSES_BEFORE_RETRY) {
      Serial.printf("[NODE] no gateway reply for %u packets, retrying last packet\n", (unsigned)loraMisses);
      if (loraSendAndListen(lastPacket)) loraMisses = 0;
    }
    if (loraMisses >= LORA_MISSES_BEFORE_REINIT) {
      Serial.println("[NODE] gateway silent for a long time, re-initialising LoRa radio");
      loraUp = loraInit();
      loraMisses = LORA_MISSES_BEFORE_RETRY;   // keep the "(no gw)" hint on the OLED
    }
  }
}
#endif  // !SIGNAL_VIEW

// this node is the access point. the sender associates and transmits at 100 Hz, and
// uplink frames from an associated station are what this chip reliably makes CSI for.
// an AP just stays up, nothing to reconnect.
static bool apUp = false;

static void onWifiEvent(WiFiEvent_t event, WiFiEventInfo_t info) {
  if (event == ARDUINO_EVENT_WIFI_AP_STACONNECTED) {
    memcpy(senderMac, info.wifi_ap_staconnected.mac, 6);
    senderMacKnown = true;
    Serial.printf("[NODE] sender joined: %02X:%02X:%02X:%02X:%02X:%02X\n",
                  senderMac[0], senderMac[1], senderMac[2],
                  senderMac[3], senderMac[4], senderMac[5]);
    radar.reset();
    Serial.println("[NODE] re-baselining");
  } else if (event == ARDUINO_EVENT_WIFI_AP_STADISCONNECTED) {
    senderMacKnown = false;
    Serial.println("[NODE] sender left");
  }
}

static bool wifiStartAP() {
  Serial.printf("[NODE] starting access point \"%s\" on channel %d\n",
                NODE_AP_SSID, NODE_AP_CHANNEL);
  senderMacKnown = false;
  WiFi.mode(WIFI_AP);
  const char* pass = (strlen(SENDER_PASSWORD) >= 8) ? SENDER_PASSWORD : nullptr;
  if (!WiFi.softAP(NODE_AP_SSID, pass, NODE_AP_CHANNEL, 0, 4)) {
    Serial.println("[NODE] softAP failed");
    return false;
  }
  esp_wifi_set_bandwidth(WIFI_IF_AP, WIFI_BW_HT20);
  // Drop 802.11b so every frame carries an OFDM training field to measure.
  esp_wifi_set_protocol(WIFI_IF_AP, WIFI_PROTOCOL_11G | WIFI_PROTOCOL_11N);
  csiStart();
  Serial.printf("[NODE] AP up, IP %s, own MAC %s\n",
                WiFi.softAPIP().toString().c_str(),
                WiFi.softAPmacAddress().c_str());
  return true;
}

// Just reports whether the sender is attached; an AP needs no reconnect logic.
static void wifiService() {
  static uint32_t lastReport = 0;
  if (!apUp) return;
  if (millis() - lastReport > 5000) {
    lastReport = millis();
    Serial.printf("[NODE] stations connected: %d\n", WiFi.softAPgetStationNum());
  }
}

static uint32_t lastDisplayMs = 0, lastBatteryMs = 0, lastPpsMs = 0, lastUplinkMs = 0;
static uint32_t csiAtLastPps = 0;
#if SIGNAL_VIEW
static uint32_t lastLineMs = 0;
#endif

void setup() {
  Serial.begin(115200);
  delay(300);
  Serial.println();
  Serial.printf("[NODE] GHOST node zone %c booting (%s)\n", ZONE_ID, SIGNAL_VIEW ? "SIGNAL_VIEW" : "LoRa");

  pinMode(GH_LED, OUTPUT);
  digitalWrite(GH_LED, LOW);
  pinMode(GH_BATT_CTRL, OUTPUT);
  digitalWrite(GH_BATT_CTRL, HIGH);
  pinMode(GH_BATT_ADC, INPUT);
  analogReadResolution(12);

  // Watchdog: if loop() stalls for WDT_TIMEOUT_S the chip resets itself.
#if ESP_ARDUINO_VERSION_MAJOR >= 3
  // ESP-IDF 5.x takes a config struct. The Arduino core may already have started
  // the watchdog, in which case init returns INVALID_STATE and we reconfigure.
  esp_task_wdt_config_t wdtCfg = {};
  wdtCfg.timeout_ms     = WDT_TIMEOUT_S * 1000;
  wdtCfg.idle_core_mask = 0;
  wdtCfg.trigger_panic  = true;
  if (esp_task_wdt_init(&wdtCfg) == ESP_ERR_INVALID_STATE) {
    esp_task_wdt_reconfigure(&wdtCfg);
  }
#else
  esp_task_wdt_init(WDT_TIMEOUT_S, true);
#endif
  esp_task_wdt_add(nullptr);

  displayInit();
  display.setFont(ArialMT_Plain_16);
  display.drawString(0, 0, "GHOST node");
  display.setFont(ArialMT_Plain_10);
  display.drawString(0, 24, String("zone ") + ZONE_ID + "  " + NODE_AP_SSID);
  display.drawString(0, 40, "starting...");
  display.display();

  csiQueue = xQueueCreate(CSI_QUEUE_LENGTH, sizeof(CsiFrame));
  radar.reset();
  batteryPct = readBatteryPercent();

  xTaskCreatePinnedToCore(audioTask, "audio", 4096, nullptr, 1, nullptr, 0);

#if !SIGNAL_VIEW
  loraUp = loraInit();
#endif

  WiFi.onEvent(onWifiEvent);
  apUp   = wifiStartAP();
  wifiUp = apUp;

  lastUplinkMs = millis() + (ZONE_ID - 'A') * 150;   // stagger zones so uplinks don't collide
}

void loop() {
  esp_task_wdt_reset();
  uint32_t now = millis();

  wifiService();

  CsiFrame f;
  while (xQueueReceive(csiQueue, &f, 0) == pdTRUE) {
    radar.process(f.amp, f.stampUs);
#if SIGNAL_VIEW
    if (millis() - lastLineMs >= 1000 / SIGNAL_VIEW_MAX_LINES_PER_S) {
      lastLineMs = millis();
      Serial.print("{\"csi\":[");
      for (int i = 0; i < NUM_SUBCARRIERS; i++) {
        Serial.print(f.amp[i], 1);
        if (i < NUM_SUBCARRIERS - 1) Serial.print(',');
      }
      int presence = (radar.state == ST_PRESENCE || radar.state == ST_MOVING) ? 1 : 0;
      Serial.printf("],\"m\":%.3f,\"p\":%d}\n", radar.smooth, presence);
    }
#endif
  }

  if (now - lastPpsMs >= 1000) {
    packetsPerSecond = (float)(csiReceived - csiAtLastPps) * 1000.0f / (now - lastPpsMs);
    csiAtLastPps = csiReceived;
    lastPpsMs = now;
#if !SIGNAL_VIEW
    Serial.printf("[NODE] %c %s motion=%.2f pps=%.0f raw=%lu badmac=%lu short=%lu audio=%.0fdB batt=%u%% drop=%lu\n",
                  ZONE_ID, stateName(radar.state), radar.smooth, packetsPerSecond,
                  (unsigned long)csiRaw, (unsigned long)csiWrongMac, (unsigned long)csiTooShort,
                  audioDb, batteryPct, (unsigned long)csiDropped);
#endif
  }

  if (now - lastBatteryMs >= BATTERY_INTERVAL_MS) {
    lastBatteryMs = now;
    batteryPct = readBatteryPercent();
  }

  if (now - lastDisplayMs >= DISPLAY_INTERVAL_MS) {
    lastDisplayMs = now;
    displayUpdate();
    digitalWrite(GH_LED, (radar.state == ST_PRESENCE || radar.state == ST_MOVING) ? HIGH : LOW);
  }

#if !SIGNAL_VIEW
  if (loraUp && (int32_t)(now - lastUplinkMs) >= (int32_t)LORA_UPLINK_INTERVAL_MS) {
    lastUplinkMs = now;
    loraUplink();
  }
#endif

  delay(1);
}
