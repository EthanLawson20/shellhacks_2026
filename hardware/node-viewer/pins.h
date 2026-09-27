// pins.h, Heltec WiFi LoRa 32 V3 pin map. fixed by the board, nothing to edit here.
#pragma once

// SX1262 LoRa radio (SPI)
#define GH_LORA_NSS   8
#define GH_LORA_SCK   9
#define GH_LORA_MOSI  10
#define GH_LORA_MISO  11
#define GH_LORA_RST   12
#define GH_LORA_BUSY  13
#define GH_LORA_DIO1  14

// 0.96" SSD1306 OLED (I2C)
#define GH_OLED_SDA   17
#define GH_OLED_SCL   18
#define GH_OLED_RST   21
#define GH_VEXT       36   // Vext power control, ACTIVE LOW: LOW = OLED powered

// Battery measurement
#define GH_BATT_ADC   1    // ADC input, behind a 390k/100k divider
#define GH_BATT_CTRL  37   // pull LOW to connect the divider to the battery
#define GH_BATT_DIVIDER_RATIO 4.9f   // (390k + 100k) / 100k

#define GH_LED        35   // white LED
#define GH_PRG_BUTTON 0    // PRG button (also BOOT)

// INMP441 microphone (I2S)
// WS -> GPIO 5, SCK -> GPIO 6, SD -> GPIO 7, L/R -> GND, VDD -> 3V3, GND -> GND
#define GH_I2S_WS     5
#define GH_I2S_SCK    6
#define GH_I2S_SD     7