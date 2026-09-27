// ghost_protocol.h, the LoRa packet formats. identical copy lives in node and
// gateway, so change one and you change the other.
#pragma once
#include <stdint.h>

#define GHOST_MAGIC 0x47  // ASCII 'G', first byte of every packet so we can ignore other traffic

// Packet types (second byte)
#define GHOST_PKT_DATA  'D'   // node -> gateway : sensor report, sent every 500 ms
#define GHOST_PKT_REPLY 'K'   // gateway -> node : "got it" + optional command, sent right after every DATA
#define GHOST_PKT_ACK   'A'   // node -> gateway : "command received and executing"

// Commands carried in GhostReplyPacket.cmd
#define GHOST_CMD_NONE     0
#define GHOST_CMD_BASELINE 'B'  // re-learn the empty-room baseline
#define GHOST_CMD_REBOOT   'R'  // restart the node

// Node state codes carried in GhostDataPacket.state
#define GHOST_STATE_BASELINING 0
#define GHOST_STATE_CLEAR      1
#define GHOST_STATE_PRESENCE   2
#define GHOST_STATE_MOVING     3

// "packed" = no padding bytes, so the struct is exactly 10 bytes on the air.
struct __attribute__((packed)) GhostDataPacket {
  uint8_t  magic;        // GHOST_MAGIC
  uint8_t  type;         // GHOST_PKT_DATA
  uint8_t  zone;         // 'A', 'B', 'C'
  uint16_t seq;          // increments every packet; wraps at 65535
  uint8_t  presence;     // 0 = nobody, 1 = somebody
  uint8_t  motion_x100;  // motion score * 100 (0.82 -> 82). Capped at 255.
  uint8_t  audio_db;     // latest 250 ms audio level, relative dB
  uint8_t  battery_pct;  // 0..100
  uint8_t  state;        // GHOST_STATE_*
};

struct __attribute__((packed)) GhostReplyPacket {
  uint8_t magic;  // GHOST_MAGIC
  uint8_t type;   // GHOST_PKT_REPLY
  uint8_t zone;   // which node this is for
  uint8_t cmd;    // GHOST_CMD_*
};

struct __attribute__((packed)) GhostAckPacket {
  uint8_t magic;  // GHOST_MAGIC
  uint8_t type;   // GHOST_PKT_ACK
  uint8_t zone;
  uint8_t cmd;    // the command being acknowledged
};