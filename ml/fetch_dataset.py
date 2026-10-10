"""Pull labelled PHASE sessions from the Railway backend and slice them into
fixed-size, single-zone windows for activity classification.

There is no raw CSI in the backend (LoRa can't carry it), so a "sample" here is
a short run of the per-packet readings a node reports about twice a second:
zone, ts, presence, motion, state, audio_db, battery_pct, rssi. The session
label (set by hand in the dashboard) is the ground-truth class.

    python fetch_dataset.py --url https://<app>.up.railway.app --all
    python fetch_dataset.py --url http://localhost:8000 --session 3 --label walking

Standard library + numpy only. Does not touch the backend or compile_dataset.py.
"""
import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

MAX_GAP_SECONDS = 2.0   # a window spanning a longer bridge dropout is garbage


def _get_json(base_url: str, path: str, timeout: float = 20.0):
    """GET a JSON document from the backend."""
    url = base_url.rstrip("/") + path
    request = Request(url, headers={"Accept": "application/json"})
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _parse_ts(ts: str) -> datetime:
    """Backend emits ISO 8601 with a timezone offset; tolerate a trailing Z."""
    if isinstance(ts, str) and ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    return datetime.fromisoformat(ts)


def _windows_for_session(readings, window, step):
    """Slice one session's readings into single-zone windows.

    Readings are grouped by zone and sorted by ts so a window never mixes zones.
    Any window whose consecutive readings are more than MAX_GAP_SECONDS apart is
    dropped, because it straddles a bridge dropout.
    """
    by_zone = defaultdict(list)
    for reading in readings:
        by_zone[reading.get("zone")].append(reading)

    out = []
    for zone, rows in sorted(by_zone.items(), key=lambda kv: str(kv[0])):
        rows.sort(key=lambda r: _parse_ts(r["ts"]))
        stamps = [_parse_ts(r["ts"]) for r in rows]
        for start in range(0, len(rows) - window + 1, step):
            end = start + window
            chunk = rows[start:end]
            span = stamps[start:end]
            if any((span[i + 1] - span[i]).total_seconds() > MAX_GAP_SECONDS
                   for i in range(len(span) - 1)):
                continue
            out.append({"zone": zone, "start_ts": chunk[0]["ts"], "readings": chunk})
    return out


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Slice labelled PHASE sessions into windows for activity training."
    )
    parser.add_argument("--url", required=True,
                        help="Railway base URL, e.g. https://<app>.up.railway.app")
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--session", type=int, help="a single session id")
    target.add_argument("--all", action="store_true", help="every labelled session")
    parser.add_argument("--output", default="dataset.json")
    parser.add_argument("--window", type=int, default=20, help="readings per window")
    parser.add_argument("--overlap", type=float, default=0.5,
                        help="fractional overlap between consecutive windows [0, 1)")
    parser.add_argument("--label", help="override the session label for every window")
    args = parser.parse_args()

    if args.window < 2:
        parser.error("--window must be at least 2")
    if not 0.0 <= args.overlap < 1.0:
        parser.error("--overlap must be in [0.0, 1.0)")

    step = max(1, round(args.window * (1.0 - args.overlap)))
    min_readings = args.window * 2

    try:
        sessions = _get_json(args.url, "/api/sessions")["sessions"]
    except (HTTPError, URLError, ValueError, KeyError, TypeError) as error:
        print(f"failed to fetch /api/sessions from {args.url}: {error}", file=sys.stderr)
        sys.exit(1)

    if args.session is not None:
        sessions = [s for s in sessions if s.get("id") == args.session]
        if not sessions:
            print(f"session {args.session} not found on the backend", file=sys.stderr)
            sys.exit(1)

    windows = []
    kept_sessions = 0
    for session in sorted(sessions, key=lambda s: s.get("id", 0)):
        sid = session.get("id")
        raw_label = args.label if args.label else session.get("label")
        label = raw_label.strip() if isinstance(raw_label, str) else raw_label
        count = session.get("reading_count", 0) or 0

        if not label:
            print(f"skip session {sid}: no label")
            continue
        if count < min_readings:
            print(f"skip session {sid} ({label!r}): only {count} readings, "
                  f"need >= {min_readings} (window*2)")
            continue

        try:
            readings = _get_json(args.url, f"/api/sessions/{sid}")["readings"]
        except (HTTPError, URLError, ValueError, KeyError, TypeError) as error:
            print(f"skip session {sid} ({label!r}): could not fetch readings: {error}")
            continue

        session_windows = _windows_for_session(readings, args.window, step)
        session_windows = [
            {"label": label, "session_id": sid, "zone": w["zone"],
             "start_ts": w["start_ts"], "readings": w["readings"]}
            for w in session_windows
        ]

        if not session_windows:
            print(f"session {sid} ({label!r}): 0 usable windows "
                  f"(dropped by >{MAX_GAP_SECONDS:g}s gaps or too few per-zone readings)")
            continue

        windows.extend(session_windows)
        kept_sessions += 1
        print(f"session {sid} ({label!r}): {len(session_windows)} windows")

    dataset = {"format": "phase-activity-dataset", "windows": windows}
    with open(args.output, "w", encoding="utf-8") as output_file:
        json.dump(dataset, output_file)

    print()
    print(f"wrote {len(windows)} windows from {kept_sessions} session(s) to {args.output}")
    per_class = Counter(w["label"] for w in windows)
    if per_class:
        print("windows per class:")
        for label, n in sorted(per_class.items(), key=lambda kv: (-kv[1], kv[0])):
            print(f"  {label:<20} {n}")
    else:
        print("no windows produced, nothing to train on")


if __name__ == "__main__":
    main()
