// PHASE sender firmware for the HiLetgo ESP32-WROOM-32.
// joins the node's AP as a client and blasts UDP at 100 Hz. those uplink frames
// are what the node measures CSI on.
#include <Arduino.h>
#include <WiFi.h>
#include <WiFiUdp.h>
#include <esp_wifi.h>
#include "config.h"

static WiFiUDP  udp;
static uint32_t seq = 0, lastUdpMicros = 0, lastLedMillis = 0, lastReportMs = 0;
static uint32_t sentSinceReport = 0;
static bool     ledOn = false;
static const IPAddress NODE_IP(192, 168, 4, 1);   // the node's soft-AP address

static void connectToNode() {
  Serial.printf("[SENDER] connecting to \"%s\"...\n", NODE_AP_SSID);
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);
  WiFi.begin(NODE_AP_SSID, strlen(AP_PASSWORD) ? AP_PASSWORD : nullptr);
  uint32_t t0 = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - t0 < 15000) delay(100);
  if (WiFi.status() == WL_CONNECTED) {
    esp_wifi_set_bandwidth(WIFI_IF_STA, WIFI_BW_HT20);
    esp_wifi_set_protocol(WIFI_IF_STA, WIFI_PROTOCOL_11G | WIFI_PROTOCOL_11N);
    udp.begin(4211);
    Serial.printf("[SENDER] connected, channel %d, my MAC %s, RSSI %d\n",
                  WiFi.channel(), WiFi.macAddress().c_str(), WiFi.RSSI());
  } else {
    Serial.println("[SENDER] connect timed out");
  }
}

void setup() {
  Serial.begin(115200);
  delay(200);
  pinMode(LED_PIN, OUTPUT);
  Serial.println("\n[SENDER] booting (client mode)");
  connectToNode();
}

void loop() {
  if (WiFi.status() != WL_CONNECTED) {
    delay(2000);
    connectToNode();
    return;
  }

  uint32_t now = micros();
  if (now - lastUdpMicros >= (uint32_t)UDP_INTERVAL_MS * 1000UL) {
    lastUdpMicros = now;
    uint8_t payload[8];
    memcpy(payload, &seq, 4);
    memset(payload + 4, 0xA5, 4);
    udp.beginPacket(NODE_IP, UDP_PORT);
    udp.write(payload, sizeof(payload));
    udp.endPacket();
    seq++;
    sentSinceReport++;
  }

  uint32_t ms = millis();
  if (ms - lastLedMillis >= LED_BLINK_MS / 2) {
    lastLedMillis = ms;
    ledOn = !ledOn;
    digitalWrite(LED_PIN, ledOn ? HIGH : LOW);
  }
  if (ms - lastReportMs >= 1000) {
    lastReportMs = ms;
    Serial.printf("[SENDER] pkts/s=%lu rssi=%d\n",
                  (unsigned long)sentSinceReport, WiFi.RSSI());
    sentSinceReport = 0;
  }
}
