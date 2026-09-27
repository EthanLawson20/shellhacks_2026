// LoRa packet layouts. Copy of this file lives in both node and gateway, so if
// you change one you have to change the other.
#pragma once
#include <stdint.h>

#define GHOST_MAGIC 0x47

#define GHOST_PKT_DATA  'D'   // node -> gateway, every 500ms
#define GHOST_PKT_REPLY 'K'   // gateway -> node, sent back after every DATA
#define GHOST_PKT_ACK   'A'   // node -> gateway, confirms a command

#define GHOST_CMD_NONE     0
#define GHOST_CMD_BASELINE 'B'
#define GHOST_CMD_REBOOT   'R'

#define GHOST_STATE_BASELINING 0
#define GHOST_STATE_CLEAR      1
#define GHOST_STATE_PRESENCE   2
#define GHOST_STATE_MOVING     3

// packed so there's no padding, comes out to 10 bytes on the air
struct __attribute__((packed)) GhostDataPacket {
  uint8_t  magic;
  uint8_t  type;
  uint8_t  zone;         // 'A', 'B', 'C'
  uint16_t seq;
  uint8_t  presence;
  uint8_t  motion_x100;  // 0.82 becomes 82, capped at 255
  uint8_t  audio_db;
  uint8_t  battery_pct;
  uint8_t  state;
};

struct __attribute__((packed)) GhostReplyPacket {
  uint8_t magic;
  uint8_t type;
  uint8_t zone;
  uint8_t cmd;
};

struct __attribute__((packed)) GhostAckPacket {
  uint8_t magic;
  uint8_t type;
  uint8_t zone;
  uint8_t cmd;
};