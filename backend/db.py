"""Postgres access for GHOST. Railway injects DATABASE_URL automatically."""
import os
from typing import Any, Optional

import asyncpg

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id         SERIAL PRIMARY KEY,
    label      TEXT,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    ended_at   TIMESTAMPTZ
);
CREATE TABLE IF NOT EXISTS readings (
    id          BIGSERIAL PRIMARY KEY,
    session_id  INTEGER REFERENCES sessions(id) ON DELETE CASCADE,
    zone        TEXT        NOT NULL,
    ts          TIMESTAMPTZ NOT NULL,
    presence    BOOLEAN     NOT NULL,
    motion      REAL        NOT NULL,
    state       SMALLINT,
    audio_db    SMALLINT,
    battery_pct SMALLINT,
    rssi        SMALLINT
);
CREATE INDEX IF NOT EXISTS readings_session_ts ON readings (session_id, ts);
"""

_pool: Optional[asyncpg.Pool] = None


async def connect() -> None:
    """Open the pool and make sure the tables exist. Called once at startup."""
    global _pool
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("[db] DATABASE_URL not set, running without persistence")
        return
    # Railway hands out postgres:// ; asyncpg wants postgresql://
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    _pool = await asyncpg.create_pool(url, min_size=1, max_size=5)
    async with _pool.acquire() as conn:
        await conn.execute(SCHEMA)
    print("[db] connected")


async def close() -> None:
    if _pool:
        await _pool.close()


def available() -> bool:
    return _pool is not None


async def start_session(label: Optional[str]) -> Optional[int]:
    if not _pool:
        return None
    async with _pool.acquire() as conn:
        return await conn.fetchval(
            "INSERT INTO sessions (label) VALUES ($1) RETURNING id", label
        )


async def stop_session(session_id: int) -> None:
    if not _pool:
        return
    async with _pool.acquire() as conn:
        await conn.execute(
            "UPDATE sessions SET ended_at = now() WHERE id = $1 AND ended_at IS NULL",
            session_id,
        )


async def insert_readings(rows: list[tuple]) -> None:
    """Bulk insert. rows: (session_id, zone, ts, presence, motion, state,
    audio_db, battery_pct, rssi)"""
    if not _pool or not rows:
        return
    async with _pool.acquire() as conn:
        await conn.executemany(
            """INSERT INTO readings
               (session_id, zone, ts, presence, motion, state, audio_db, battery_pct, rssi)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)""",
            rows,
        )


async def list_sessions(limit: int = 50) -> list[dict[str, Any]]:
    if not _pool:
        return []
    async with _pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT s.id, s.label, s.started_at, s.ended_at,
                      COUNT(r.id) AS reading_count
               FROM sessions s LEFT JOIN readings r ON r.session_id = s.id
               GROUP BY s.id ORDER BY s.started_at DESC LIMIT $1""",
            limit,
        )
    return [dict(r) for r in rows]


async def session_readings(session_id: int) -> list[dict[str, Any]]:
    if not _pool:
        return []
    async with _pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT zone, ts, presence, motion, state, audio_db, battery_pct, rssi
               FROM readings WHERE session_id = $1 ORDER BY ts""",
            session_id,
        )
    return [dict(r) for r in rows]