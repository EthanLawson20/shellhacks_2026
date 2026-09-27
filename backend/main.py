# Gateway is USB only so the laptop bridge has to relay everything up.

import asyncio
import json
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

import db

INGEST_TOKEN = os.environ.get("GHOST_INGEST_TOKEN", "")
STALE_SECONDS = 5
FLUSH_INTERVAL = 1.0

# leaving this as * until vercel gives me a domain
ALLOWED_ORIGINS = os.environ.get("ALLOWED_ORIGINS", "*").split(",")

latest: dict[str, dict[str, Any]] = {}
browsers: set[WebSocket] = set()
pending_rows: list[tuple] = []
current_session: Optional[int] = None


async def broadcast(message: dict) -> None:
    if not browsers:
        return
    payload = json.dumps(message)
    dead = []
    for ws in browsers:
        try:
            await ws.send_text(payload)
        except Exception:
            dead.append(ws)
    for ws in dead:
        browsers.discard(ws)


async def flush_loop() -> None:
    # batching these so a slow insert can't stall the live feed
    global pending_rows
    while True:
        await asyncio.sleep(FLUSH_INTERVAL)
        if not pending_rows:
            continue
        rows, pending_rows = pending_rows, []
        try:
            await db.insert_readings(rows)
        except Exception as e:
            print(f"[db] insert failed, dropped {len(rows)} rows: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.connect()
    task = asyncio.create_task(flush_loop())
    yield
    task.cancel()
    await db.close()


app = FastAPI(title="PHASE backend", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")


@app.get("/dashboard", include_in_schema=False)
async def dashboard():
    return RedirectResponse(url="/static/dashboard.html")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.websocket("/ws/ingest")
async def ws_ingest(ws: WebSocket, token: str = ""):
    if INGEST_TOKEN and token != INGEST_TOKEN:
        await ws.close(code=4401)
        return
    await ws.accept()
    print("[ingest] bridge connected")
    try:
        while True:
            reading = json.loads(await ws.receive_text())
            zone = reading.get("zone")
            if not zone:
                continue

            reading["received_at"] = datetime.now(timezone.utc).isoformat()
            latest[zone] = reading
            await broadcast({"type": "reading", "data": reading})

            if current_session is not None:
                pending_rows.append((
                    current_session,
                    zone,
                    datetime.fromisoformat(reading["ts"]),
                    bool(reading.get("presence")),
                    float(reading.get("motion", 0.0)),
                    reading.get("state_code"),
                    reading.get("audio_db"),
                    reading.get("battery_pct"),
                    reading.get("rssi"),
                ))
    except WebSocketDisconnect:
        print("[ingest] bridge disconnected")
    except Exception as e:
        print(f"[ingest] error: {e}")


@app.websocket("/ws/live")
async def ws_live(ws: WebSocket):
    await ws.accept()
    browsers.add(ws)
    # dump current state right away, otherwise a fresh page sits blank until
    # the next packet
    await ws.send_text(json.dumps({
        "type": "snapshot",
        "zones": list(latest.values()),
        "session": current_session,
    }))
    try:
        while True:
            await ws.receive_text()   # don't expect anything, just holding it open
    except Exception:
        pass
    finally:
        browsers.discard(ws)


@app.get("/api/health")
async def health():
    return {"ok": True, "db": db.available(), "zones": len(latest)}


@app.get("/api/data")
async def api_data():
    now = datetime.now(timezone.utc)
    zones = []
    for z in latest.values():
        age = (now - datetime.fromisoformat(z["received_at"])).total_seconds()
        zones.append({**z, "stale": age > STALE_SECONDS, "age_seconds": round(age, 1)})
    return {"zones": zones, "session": current_session, "db": db.available()}


@app.post("/api/session/start")
async def session_start(body: dict | None = None):
    global current_session
    if current_session is not None:
        raise HTTPException(409, "a session is already running")
    current_session = await db.start_session((body or {}).get("label"))
    if current_session is None:
        raise HTTPException(503, "no database configured")
    await broadcast({"type": "session", "session": current_session})
    return {"session": current_session}


@app.post("/api/session/stop")
async def session_stop():
    global current_session, pending_rows
    if current_session is None:
        raise HTTPException(409, "no session running")
    if pending_rows:   # flush the tail or I lose the last second of the run
        rows, pending_rows = pending_rows, []
        await db.insert_readings(rows)
    await db.stop_session(current_session)
    ended, current_session = current_session, None
    await broadcast({"type": "session", "session": None})
    return {"stopped": ended}


@app.get("/api/sessions")
async def api_sessions():
    return {"sessions": await db.list_sessions()}


@app.get("/api/sessions/{session_id}")
async def api_session(session_id: int):
    rows = await db.session_readings(session_id)
    if not rows:
        raise HTTPException(404, "no readings for that session")
    return {"session": session_id, "readings": rows}
