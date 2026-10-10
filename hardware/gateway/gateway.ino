// PHASE gateway. Picks up node packets over LoRa, prints them as JSON on USB.
// Type "B A" or "R A" in the serial monitor to re-baseline or reboot a zone.
#include <Arduino.h>
#include <RadioLib.h>
#include <SSD1306Wire.h>
#include <esp_task_wdt.h>
#include "config.h"
#include "pins.h"
#include "ghost_protocol.h"

#define MAX_ZONES 8
struct ZoneInfo {
  bool     seen;
  uint32_t lastMillis;
  uint8_t  state;
  int16_t  rssi;
  uint16_t seq;
  uint32_t packets;
  uint8_t  pendingCmd;
};
static ZoneInfo zones[MAX_ZONES];

static int zoneIndex(uint8_t z) {
  if (z >= 'A' && z < 'A' + MAX_ZONES) return z - 'A';
  if (z >= 'a' && z < 'a' + MAX_ZONES) return z - 'a';
  return -1;
}

static const char* stateName(uint8_t s) {
  switch (s) {
    case GHOST_STATE_CLEAR:    return "CLEAR";
    case GHOST_STATE_PRESENCE: return "PRESENCE";
    case GHOST_STATE_MOVING:   return "MOVING";
    default:                   return "BASELINE";
  }
}

static SX1262 radio = new Module(GH_LORA_NSS, GH_LORA_DIO1, GH_LORA_RST, GH_LORA_BUSY, SPI);
static volatile bool radioFlag = false;
static uint32_t totalPackets = 0;
static uint32_t crcErrors    = 0;
static uint32_t ledOffAtMs   = 0;

static void IRAM_ATTR onRadioIrq() { radioFlag = true; }

static bool loraInit() {
  SPI.begin(GH_LORA_SCK, GH_LORA_MISO, GH_LORA_MOSI, GH_LORA_NSS);
  // The 1.8 (TCXO) and the DIO2 line are Heltec V3 quirks. Miss either and the
  // radio looks fine but never hears anything.
  int st = radio.begin(LORA_FREQUENCY_MHZ, LORA_BANDWIDTH_KHZ, LORA_SPREADING_FACTOR,
                       LORA_CODING_RATE, LORA_SYNC_WORD, LORA_TX_POWER_DBM, 8, 1.8f, false);
  if (st != RADIOLIB_ERR_NONE) {
    Serial.printf("# LoRa init failed, code %d\n", st);
    return false;
  }
  radio.setDio2AsRfSwitch(true);
  radio.setCRC(2);
  radio.setPacketReceivedAction(onRadioIrq);
  radio.startReceive();
  Serial.printf("# LoRa ready: %.1f MHz SF%d BW%.0f CR4/%d sync 0x%02X\n",
                LORA_FREQUENCY_MHZ, LORA_SPREADING_FACTOR, LORA_BANDWIDTH_KHZ,
                LORA_CODING_RATE, LORA_SYNC_WORD);
  return true;
}

static void ledPulse() {
  digitalWrite(GH_LED, HIGH);
  ledOffAtMs = millis() + LED_FLASH_MS;
}

static void handleRadioPacket() {
  uint8_t buf[32];
  size_t  len = radio.getPacketLength();
  int st = (len <= sizeof(buf)) ? radio.readData(buf, len) : RADIOLIB_ERR_PACKET_TOO_LONG;
  int rssi = (int)radio.getRSSI();

  if (st == RADIOLIB_ERR_CRC_MISMATCH) {
    crcErrors++;
  } else if (st == RADIOLIB_ERR_NONE && len >= 4 && buf[0] == GHOST_MAGIC) {
    if (buf[1] == GHOST_PKT_DATA && len == sizeof(GhostDataPacket)) {
      GhostDataPacket pkt;
      memcpy(&pkt, buf, sizeof(pkt));
      totalPackets++;
      ledPulse();

      Serial.printf("{\"id\":\"%c\",\"p\":%u,\"m\":%.2f,\"a\":%u,\"b\":%u,\"r\":%d,\"t\":%lu}\n",
                    (char)pkt.zone, (unsigned)pkt.presence, pkt.motion_x100 / 100.0f,
                    (unsigned)pkt.audio_db, (unsigned)pkt.battery_pct, rssi,
                    (unsigned long)(millis() / 1000));

      uint8_t cmd = GHOST_CMD_NONE;
      int zi = zoneIndex(pkt.zone);
      if (zi >= 0) {
        ZoneInfo& z = zones[zi];
        z.seen = true;
        z.lastMillis = millis();
        z.state = pkt.state;
        z.rssi = rssi;
        z.seq = pkt.seq;
        z.packets++;
        cmd = z.pendingCmd;
        z.pendingCmd = GHOST_CMD_NONE;
      }

      // Node only listens for ~150ms after it sends, so reply right now.
      GhostReplyPacket rep = { GHOST_MAGIC, GHOST_PKT_REPLY, pkt.zone, cmd };
      radio.transmit((uint8_t*)&rep, sizeof(rep));
      radioFlag = false;
      if (cmd != GHOST_CMD_NONE) Serial.printf("# sent command '%c' to zone %c\n", cmd, (char)pkt.zone);

    } else if (buf[1] == GHOST_PKT_ACK && len == sizeof(GhostAckPacket)) {
      Serial.printf("{\"ack\":\"%c\",\"cmd\":\"%c\"}\n", (char)buf[2], (char)buf[3]);
      ledPulse();
    }
  }
  radio.startReceive();
}

static char   lineBuf[32];
static size_t lineLen = 0;

static void handleSerialLine(const char* line) {
  while (*line == ' ' || *line == '\t') line++;
  char cmd = toupper(*line);
  if (cmd != GHOST_CMD_BASELINE && cmd != GHOST_CMD_REBOOT) {
    Serial.printf("# unknown command \"%s\" (use: B <zone> | R <zone>)\n", line);
    return;
  }
  line++;
  while (*line == ' ' || *line == '\t') line++;
  int zi = zoneIndex((uint8_t)*line);
  if (zi < 0) {
    Serial.println("# missing/invalid zone letter (A-H)");
    return;
  }
  zones[zi].pendingCmd = cmd;
  Serial.printf("# queued '%c' for zone %c, goes out on its next packet\n", cmd, 'A' + zi);
}

static void serialService() {
  while (Serial.available()) {
    char c = (char)Serial.read();
    if (c == '\n' || c == '\r') {
      if (lineLen > 0) {
        lineBuf[lineLen] = 0;
        handleSerialLine(lineBuf);
        lineLen = 0;
      }
    } else if (lineLen < sizeof(lineBuf) - 1) {
      lineBuf[lineLen++] = c;
    }
  }
}

static SSD1306Wire display(0x3c, GH_OLED_SDA, GH_OLED_SCL);

static void displayInit() {
  pinMode(GH_VEXT, OUTPUT);
  digitalWrite(GH_VEXT, LOW);   // Vext is active low
  delay(50);
  pinMode(GH_OLED_RST, OUTPUT);
  digitalWrite(GH_OLED_RST, LOW);
  delay(20);
  digitalWrite(GH_OLED_RST, HIGH);
  delay(20);
  display.init();
  display.flipScreenVertically();
  display.setTextAlignment(TEXT_ALIGN_LEFT);
  display.setFont(ArialMT_Plain_10);
}

static void displayUpdate() {
  char line[32];
  display.clear();
  snprintf(line, sizeof(line), "GHOST gw  pkts %lu  crc %lu",
           (unsigned long)totalPackets, (unsigned long)crcErrors);
  display.drawString(0, 0, line);

  int y = 14, shown = 0;
  for (int i = 0; i < MAX_ZONES && shown < 4; i++) {
    if (!zones[i].seen) continue;
    uint32_t age = (millis() - zones[i].lastMillis) / 1000;
    if (millis() - zones[i].lastMillis > ZONE_STALE_MS) {
      snprintf(line, sizeof(line), "%c  lost %lus ago  %ddBm",
               'A' + i, (unsigned long)age, zones[i].rssi);
    } else {
      snprintf(line, sizeof(line), "%c  %-8s  %ddBm  %lus",
               'A' + i, stateName(zones[i].state), zones[i].rssi, (unsigned long)age);
    }
    display.drawString(0, y, line);
    y += 12;
    shown++;
  }
  if (shown == 0) display.drawString(0, 28, "waiting for nodes...");
  display.display();
}

static uint32_t lastDisplayMs = 0;
static bool     loraUp = false;

void setup() {
  Serial.begin(115200);
  delay(300);
  Serial.println();
  Serial.println("# GHOST gateway booting");

  pinMode(GH_LED, OUTPUT);
  digitalWrite(GH_LED, LOW);
  memset(zones, 0, sizeof(zones));

// Core 3.x changed this API and sometimes starts the watchdog on its own.
#if ESP_ARDUINO_VERSION_MAJOR >= 3
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
  display.drawString(0, 0, "GHOST gateway");
  display.setFont(ArialMT_Plain_10);
  display.drawString(0, 24, "starting radio...");
  display.display();

  loraUp = loraInit();
  if (!loraUp) {
    display.drawString(0, 40, "LORA INIT FAILED");
    display.display();
  }
  Serial.println("{\"gw\":\"ready\"}");
}

void loop() {
  esp_task_wdt_reset();

  if (!loraUp) {
    static uint32_t lastTry = 0;
    if (millis() - lastTry > 3000) { lastTry = millis(); loraUp = loraInit(); }
  }

  if (radioFlag) {
    radioFlag = false;
    handleRadioPacket();
  }

  serialService();

  if (ledOffAtMs && (int32_t)(millis() - ledOffAtMs) >= 0) {
    digitalWrite(GH_LED, LOW);
    ledOffAtMs = 0;
  }

  // Redraw is slow over I2C, skip it if a packet just landed.
  if (millis() - lastDisplayMs >= DISPLAY_INTERVAL_MS && !radioFlag) {
    lastDisplayMs = millis();
    displayUpdate();
  }

  delay(1);
}