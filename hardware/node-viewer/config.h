// config.h for the heatmap node. dedicated signal viewer, not on the dashboard.
#pragma once

#define ZONE_ID          'D'          // 'D' so it can't collide with zones A/B/C
// each node runs its own AP and its paired sender must join with the same ssid
#define NODE_AP_SSID     "GHOST-N-D"
#define NODE_AP_CHANNEL  11           // off channel 6 so it doesn't fight the dashboard zones
#define SENDER_PASSWORD  ""           // "" = open network. if set, must be 8+ chars

// 1 = skip LoRa and stream one JSON line per CSI packet over USB for the laptop
// heatmap. this board is only ever used this way.
#define SIGNAL_VIEW      1

#define LORA_FREQUENCY_MHZ 915.0f
#define LORA_SYNC_WORD     0x12
#define LORA_TX_POWER_DBM  14

// motion thresholds, see README "Tuning"
#define PRESENCE_ON_THRESHOLD   0.20f
#define PRESENCE_ON_HOLD_MS     1000
#define PRESENCE_OFF_THRESHOLD  0.15f
#define PRESENCE_OFF_HOLD_MS    1500
#define MOVING_THRESHOLD        0.35f

#define BASELINE_SECONDS        15
#define NOISE_SCALE             4.0f
#define MOTION_EMA_TAU_S        0.5f
#define ADAPT_TAU_S             60.0f

#define AUDIO_DB_OFFSET         0

// usually leave these alone
#define LORA_BANDWIDTH_KHZ      125.0f
#define LORA_SPREADING_FACTOR   7
#define LORA_CODING_RATE        5
#define LORA_UPLINK_INTERVAL_MS 500
#define LORA_LISTEN_MS          150
#define LORA_MISSES_BEFORE_RETRY  3
#define LORA_MISSES_BEFORE_REINIT 20

#define AUDIO_SAMPLE_RATE       16000
#define AUDIO_WINDOW_MS         250

#define DISPLAY_INTERVAL_MS     200
#define BATTERY_INTERVAL_MS     5000
// bumped from 20. the python viewer reads over USB so it can take the extra rate,
// and more frames per second means a smoother heatmap.
#define SIGNAL_VIEW_MAX_LINES_PER_S 40

#define WIFI_CONNECT_TIMEOUT_MS 15000
#define WIFI_RETRY_INTERVAL_MS  3000
#define NO_CSI_TIMEOUT_MS       60000
#define WDT_TIMEOUT_S           10