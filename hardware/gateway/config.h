// Gateway config. These have to match the nodes or nothing gets through.
#pragma once

#define LORA_FREQUENCY_MHZ 915.0f
#define LORA_SYNC_WORD     0x12
#define LORA_TX_POWER_DBM  14

#define LORA_BANDWIDTH_KHZ    125.0f
#define LORA_SPREADING_FACTOR 7
#define LORA_CODING_RATE      5        // 4/5

#define DISPLAY_INTERVAL_MS   200
#define LED_FLASH_MS          40
#define ZONE_STALE_MS         3000     // no packet for 3s and the OLED calls the zone lost
#define WDT_TIMEOUT_S         10