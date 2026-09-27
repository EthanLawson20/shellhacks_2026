// config.h for the heatmap node's sender. must match GHOST-N-D exactly.
#pragma once

#define NODE_AP_SSID   "GHOST-N-D"
#define AP_PASSWORD    ""
#define UDP_INTERVAL_MS   10       // 100 packets/s, one CSI measurement each
#define UDP_PORT          4210
#define LED_PIN           2
#define LED_BLINK_MS      1000