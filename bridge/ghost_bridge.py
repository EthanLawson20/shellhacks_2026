"""GHOST bridge — reads the gateway's USB serial and forwards to the backend.

The gateway prints one JSON line per LoRa packet. Its "t" field is seconds
since the gateway booted, which is useless upstream, so we replace it with a
real UTC timestamp here. Lines starting with '#' are human chatter; ignored.

    pip install pyserial websockets
    python ghost_bridge.py --port COM5 --url wss://<your-app>.up.railway.app
"""
import argparse
import asyncio
import json
from datetime import datetime, timezone

import serial
import websockets

ZONE_NAMES = {          # edit these to match where you physically place nodes
    "A": "Zone A",
    "B": "Zone B",
    "C": "Zone C",
}

STATE_NAMES = {0: "BASELINING", 1: "CLEAR", 2: "PRESENCE", 3: "MOVING"}


def translate(line: dict) -> dict | None:
    """Gateway JSON -> backend JSON. Returns None for non-reading lines."""
    if "id" not in line:
        return None                     # e.g. {"ack":...} or {"gw":"ready"}
    zone = line["id"]
    motion = float(line.get("m", 0.0))
    presence = bool(line.get("p", 0))
    # The firmware's own state isn't in the packet's JSON, so derive a label
    # from presence + motion for display purposes.
    if not presence:
        state = "CLEAR"
    elif motion > 0.35:
        state = "MOVING"
    else:
        state = "PRESENCE"
    return {
        "zone": zone,
        "name": ZONE_NAMES.get(zone, f"Zone {zone}"),
        "ts": datetime.now(timezone.utc).isoformat(),
        "presence": presence,
        "motion": motion,
        "state": state,
        "audio_db": int(line.get("a", 0)),
        "battery_pct": int(line.get("b", 0)),
        "rssi": int(line.get("r", 0)),
        "uptime_s": int(line.get("t", 0)),
    }


async def run(port: str, baud: int, url: str, token: str) -> None:
    ser = serial.Serial(port, baud, timeout=1)
    print(f"[bridge] reading {port} at {baud}")
    ws_url = f"{url.rstrip('/')}/ws/ingest" + (f"?token={token}" if token else "")

    while True:
        try:
            async with websockets.connect(ws_url) as ws:
                print(f"[bridge] connected to {url}")
                while True:
                    raw = await asyncio.to_thread(ser.readline)
                    text = raw.decode("utf-8", errors="replace").strip()
                    if not text or text.startswith("#"):
                        continue
                    try:
                        parsed = json.loads(text)
                    except json.JSONDecodeError:
                        continue          # partial line, ignore
                    reading = translate(parsed)
                    if reading:
                        await ws.send(json.dumps(reading))
        except Exception as e:
            print(f"[bridge] connection lost ({e}) — retrying in 3 s")
            await asyncio.sleep(3)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--port", required=True, help="gateway COM port, e.g. COM5")
    p.add_argument("--baud", type=int, default=115200)
    p.add_argument("--url", required=True, help="wss://<app>.up.railway.app")
    p.add_argument("--token", default="", help="must match GHOST_INGEST_TOKEN")
    a = p.parse_args()
    asyncio.run(run(a.port, a.baud, a.url, a.token))