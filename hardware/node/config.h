// config.h for the node. the file a teammate edits.
#pragma once

#define ZONE_ID          'A'          // 'A', 'B' or 'C', must be unique per node
// each node runs its own AP and its paired sender must join with the same ssid
#define NODE_AP_SSID     "GHOST-N-A"  // "GHOST-N-B" for zone B, "GHOST-N-C" for zone C
#define NODE_AP_CHANNEL  6            // keep all zones on the same channel
#define SENDER_PASSWORD  ""           // "" = open network. if set, must be 8+ chars
// 1 = skip LoRa and stream one JSON line per CSI packet over USB for the laptop
// heatmap page. 0 = normal LoRa node.
#define SIGNAL_VIEW      0

#define LORA_FREQUENCY_MHZ 915.0f
#define LORA_SYNC_WORD     0x12
#define LORA_TX_POWER_DBM  14

// motion thresholds, see README "Tuning"
#define PRESENCE_ON_THRESHOLD   0.20f   // smoothed motion score must stay above this...
#define PRESENCE_ON_HOLD_MS     1000    // ...for this long to declare PRESENCE
#define PRESENCE_OFF_THRESHOLD  0.15f   // and stay below this...
#define PRESENCE_OFF_HOLD_MS    1500    // ...for this long to go back to CLEAR
#define MOVING_THRESHOLD        0.35f   // above this (while present) = MOVING

#define BASELINE_SECONDS        15      // empty-room learning window after boot / 'B' command
#define NOISE_SCALE             4.0f    // how many "still-room sigmas" of deviation = motion score 1.0.
                                        // Lower = more sensitive, higher = less sensitive.
#define MOTION_EMA_TAU_S        0.5f    // smoothing time constant for the motion score
#define ADAPT_TAU_S             60.0f   // how slowly a still room re-centres the baseline

#define AUDIO_DB_OFFSET         0       // add/subtract to line up the mic reading with a phone dB meter

// usually leave these alone
#define LORA_BANDWIDTH_KHZ      125.0f
#define LORA_SPREADING_FACTOR   7
#define LORA_CODING_RATE        5       // 4/5
#define LORA_UPLINK_INTERVAL_MS 500
#define LORA_LISTEN_MS          150     // how long to wait for the gateway's reply after each uplink
#define LORA_MISSES_BEFORE_RETRY  3     // consecutive unanswered uplinks before an immediate retransmit
#define LORA_MISSES_BEFORE_REINIT 20    // consecutive unanswered uplinks before re-initialising the radio

#define AUDIO_SAMPLE_RATE       16000
#define AUDIO_WINDOW_MS         250

#define DISPLAY_INTERVAL_MS     200     // 5 Hz OLED refresh
#define BATTERY_INTERVAL_MS     5000
#define SIGNAL_VIEW_MAX_LINES_PER_S 20

#define WIFI_CONNECT_TIMEOUT_MS 15000
#define WIFI_RETRY_INTERVAL_MS  3000
#define NO_CSI_TIMEOUT_MS       60000
#define WDT_TIMEOUT_S           10      // hardware watchdog on the main loop
