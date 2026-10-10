"""Live activity classification from the Railway backend.

Polls GET /api/data about twice a second, keeps a per-zone rolling window of the
most recent readings, and runs each full window through the trained CSI activity
model (csi_model.keras + csi_model_meta.joblib). A terminal display shows, per
zone, the predicted class, the per-class probabilities, and the node's own
firmware state for comparison.

Feature extraction is imported from train_activity (_features) rather than
reimplemented, so the live path can't drift from how the model was trained. The
windowing/gap rules mirror fetch_dataset.py (same window size and MAX_GAP_SECONDS).

    python classify_live.py
    python classify_live.py --url http://localhost:8000 --window 20 --threshold 0.6

The classify_zone(readings) -> (label, probabilities) function is exposed for a
fusion script to reuse without the polling loop.
"""
import argparse
import os
import sys
import time
from collections import deque
from datetime import datetime

import numpy as np

# Import feature extraction and the gap/window rules from the existing scripts so
# they can't diverge from training / dataset construction.
from train_activity import _features
from fetch_dataset import _parse_ts, MAX_GAP_SECONDS
from railway_client import fetch_json

DEFAULT_URL = "https://shellhacks2026-production.up.railway.app"
MODEL_PATH = "csi_model.keras"
META_PATH = "csi_model_meta.joblib"

# Loaded lazily on the first classify_zone() call and cached, so importing this
# module (e.g. from a fusion script) doesn't pull TensorFlow into memory until a
# prediction is actually requested.
_model = None
_scaler = None
_classes = None


def _ensure_loaded():
    # Load and cache the model, scaler, and class order. Raises on missing files.
    global _model, _scaler, _classes
    if _model is None:
        import joblib
        from tensorflow import keras

        model = keras.models.load_model(MODEL_PATH)
        meta = joblib.load(META_PATH)
        _model = model
        _scaler = meta["scaler"]
        _classes = list(meta["classes"])
    return _model, _scaler, _classes


def classify_zone(readings):
    """Classify one window of zone readings.

    readings is a list of the raw per-packet dicts (each with motion, audio_db,
    presence, rssi, ...). Returns (label, probabilities) where probabilities is a
    dict mapping each class name to its softmax probability. No thresholding is
    applied here. Callers decide what to do with a low-confidence top class.
    """
    model, scaler, classes = _ensure_loaded()
    features = np.asarray(_features(readings), dtype=float).reshape(1, -1)
    scaled = scaler.transform(features)
    probabilities = model.predict(scaled, verbose=0)[0]
    top_index = int(np.argmax(probabilities))
    label = classes[top_index]
    return label, {c: float(p) for c, p in zip(classes, probabilities)}


def _enable_ansi() -> None:
    """On Windows, calling os.system('') flips the console into VT-processing mode
    so the ANSI clear/home escapes below actually render."""
    if os.name == "nt":
        os.system("")


def _update_buffer(buffer: deque, zone: dict) -> None:
    """Append one reading to a zone's rolling window, applying the same gap rule
    fetch_dataset.py uses: a jump of more than MAX_GAP_SECONDS between consecutive
    ts values drops the window and starts over. Duplicate ts (no new packet since
    the last poll) and out-of-order/clock-reset readings are handled too."""
    ts = _parse_ts(zone["ts"])
    if buffer:
        previous = _parse_ts(buffer[-1]["ts"])
        if ts == previous:
            return  # same packet re-served by /api/data; nothing new to add
        if ts < previous or (ts - previous).total_seconds() > MAX_GAP_SECONDS:
            buffer.clear()
    buffer.append(zone)


def _format_zone_line(zone: dict, buffer: deque, window: int,
                      threshold: float, classes) -> str:
    # Build the one-line status for a single zone.
    zone_id = zone.get("zone")
    name = zone.get("name") or f"Zone {zone_id}"
    firmware = str(zone.get("state", "?"))
    stale = " (stale)" if zone.get("stale") else ""

    filled = len(buffer)
    if filled < window:
        prediction = f"warming up {filled}/{window}"
        probability_text = ""
    else:
        label, probabilities = classify_zone(list(buffer))
        top = probabilities[label]
        if top < threshold:
            prediction = f"UNCERTAIN (best: {label} {top:.0%})"
        else:
            prediction = f"{label} {top:.0%}"
        order = classes if classes is not None else sorted(probabilities)
        probability_text = "  ".join(
            f"{c}:{probabilities[c]:.2f}" for c in order
        )

    return (
        f"  {name:<14} pred: {prediction:<30} "
        f"firmware: {firmware:<9}{stale}   {probability_text}"
    )


def _render(url: str, status: str, zones, buffers, window, threshold, classes) -> None:
    """Clear the screen and print the current frame."""
    now = datetime.now().strftime("%H:%M:%S")
    lines = [
        "\033[2J\033[H",  # clear screen + cursor home
        f"CSI live activity classifier   {now}",
        f"backend: {url}",
        f"window: {window} readings   threshold: {threshold:.2f}",
        f"status: {status}",
        "-" * 78,
    ]
    if not zones:
        lines.append("  (no zones reporting)")
    else:
        for zone in sorted(zones, key=lambda z: str(z.get("zone"))):
            zone_id = zone.get("zone")
            buffer = buffers.get(zone_id, deque())
            lines.append(
                _format_zone_line(zone, buffer, window, threshold, classes)
            )
    lines.append("")
    lines.append("Ctrl+C to quit.")
    print("\n".join(lines), flush=True)


def run(url: str, window: int, threshold: float, interval: float) -> None:
    """Poll the backend and refresh the display until interrupted."""
    _, _, classes = _ensure_loaded()
    buffers: dict = {}
    _enable_ansi()

    while True:
        try:
            payload = fetch_json("/api/data", base_url=url, timeout=5.0)
            zones = payload.get("zones", []) if isinstance(payload, dict) else []
        except Exception as error:  # unreachable backend, timeout, bad JSON, etc.
            _render(
                url,
                f"backend unreachable ({error}); retrying in 2s",
                [], {}, window, threshold, classes,
            )
            time.sleep(2.0)
            continue

        for zone in zones:
            zone_id = zone.get("zone")
            if zone_id is None or zone.get("ts") is None:
                continue
            buffer = buffers.setdefault(zone_id, deque(maxlen=window))
            _update_buffer(buffer, zone)

        _render(url, "connected", zones, buffers, window, threshold, classes)
        time.sleep(interval)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Live activity classification from the Railway /api/data feed."
    )
    parser.add_argument("--url", default=DEFAULT_URL,
                        help=f"Railway base URL (default: {DEFAULT_URL})")
    parser.add_argument("--window", type=int, default=20,
                        help="readings per window; must match fetch_dataset --window (default: 20)")
    parser.add_argument("--threshold", type=float, default=0.6,
                        help="predictions below this top probability are flagged uncertain (default: 0.6)")
    parser.add_argument("--interval", type=float, default=0.5,
                        help="seconds between polls (default: 0.5, ~twice a second)")
    args = parser.parse_args()

    if args.window < 2:
        parser.error("--window must be at least 2")
    if not 0.0 <= args.threshold <= 1.0:
        parser.error("--threshold must be between 0 and 1")

    try:
        _ensure_loaded()
    except (OSError, KeyError) as error:
        print(
            f"could not load model artifacts ({MODEL_PATH} + {META_PATH}): {error}\n"
            "Run csi_model.py to train and save them first.",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        run(args.url, args.window, args.threshold, args.interval)
    except KeyboardInterrupt:
        print("\nstopped.")


if __name__ == "__main__":
    main()
