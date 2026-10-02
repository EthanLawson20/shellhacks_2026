"""Monitor CSI activity and ESP audio loudness predictions together.

Both models consume the same rolling per-zone readings from /api/data, so the
backend is polled once and each view stays aligned to the same sensor window.

    python monitor_live.py
    python monitor_live.py --url http://localhost:8000 --window 20
"""
import argparse
import json
import os
import sys
import time
from collections import deque
from datetime import datetime
from urllib.parse import quote
from urllib.request import Request, urlopen

from audio_model import preprocess_db_readings
from classify_audio_live import _load_db_model
from classify_live import _ensure_loaded, _update_buffer, classify_zone
from railway_client import fetch_json

DEFAULT_URL = "https://shellhacks2026-production.up.railway.app"
CSI_WINDOW = 20
AUDIO_MODEL_PATH = "audio_model.keras"
CSI_THRESHOLD = 0.6
AUDIO_THRESHOLD = 0.5


def fuse_activity_score(csi_probabilities: dict, loud_probability: float) -> float:
	"""Return a heuristic 0-100 score averaging CSI activity and audio loudness."""
	p_empty = float(csi_probabilities.get("empty", 1.0))
	p_active = min(1.0, max(0.0, 1.0 - p_empty))
	p_loud = min(1.0, max(0.0, float(loud_probability)))
	return 100.0 * (0.5 * p_active + 0.5 * p_loud)


def _enable_ansi() -> None:
	if os.name == "nt":
		os.system("")


def _push_prediction(push_url: str, token: str, prediction: dict) -> None:
	"""POST one zone's prediction to the backend; never raise."""
	try:
		url = f"{push_url.rstrip('/')}/api/prediction"
		if token:
			url += f"?token={quote(token)}"
		body = json.dumps(prediction).encode("utf-8")
		request = Request(
			url, data=body, method="POST",
			headers={"Content-Type": "application/json"},
		)
		urlopen(request, timeout=5.0).close()
	except Exception as error:
		print(f"[push] {prediction.get('zone')} failed: {error}", file=sys.stderr)


def _zone_lines(
	zone: dict,
	buffer: deque,
	window: int,
	context: int,
	db_threshold: float,
	csi_threshold: float,
	audio_threshold: float,
) -> tuple[str, dict | None]:
	zone_id = zone.get("zone")
	name = zone.get("name") or f"Zone {zone_id}"
	if zone.get("stale"):
		return f"  {name:<14} CSI: FEED STALE | AUDIO: FEED STALE | ACTIVITY: --", None
	if len(buffer) < window:
		warming = f"warming up {len(buffer)}/{window}"
		return f"  {name:<14} CSI: {warming:<21} | AUDIO: {warming:<21} | ACTIVITY: --", None

	readings = list(buffer)
	activity, probabilities = classify_zone(readings)
	activity_confidence = probabilities[activity]
	p_active = 1.0 - probabilities.get("empty", 1.0)
	if activity_confidence < csi_threshold:
		activity_text = f"uncertain {activity} {activity_confidence:.0%}; active {p_active:.0%}"
	else:
		activity_text = f"{activity} {activity_confidence:.0%}; active {p_active:.0%}"

	prediction = {
		"zone": zone_id,
		"csi_class": str(activity),
		"csi_probs": {str(k): float(v) for k, v in probabilities.items()},
		"audio_class": None,
		"audio_prob": None,
		"activity_score": None,
	}

	audio_readings = sum(item.get("audio_db") is not None for item in readings)
	if audio_readings < window:
		audio_text = f"warming up dB {audio_readings}/{window}"
		level_text = "?"
		activity_score_text = "--"
	else:
		features = preprocess_db_readings(
			readings, db_threshold, window, context
		).reshape(1, window - context + 1, context, 1)
		loud_probability = float(_audio_model.predict(features, verbose=0)[0][0])
		label = "LOUD" if loud_probability >= audio_threshold else "not loud"
		audio_text = f"{label} p(loud)={loud_probability:.0%}"
		level_text = str(zone.get("audio_db", "?"))
		activity_score = fuse_activity_score(probabilities, loud_probability)
		activity_score_text = f"{activity_score:.0f}/100"
		prediction["audio_class"] = label
		prediction["audio_prob"] = loud_probability
		prediction["activity_score"] = activity_score

	line = (
		f"  {name:<14} CSI: {activity_text:<38} "
		f"AUDIO: {audio_text:<23} dB:{level_text:<3} "
		f"ACTIVITY: {activity_score_text}"
	)
	return line, prediction


def _render(
	url: str,
	status: str,
	zones: list,
	buffers: dict,
	window: int,
	context: int,
	db_threshold: float,
	csi_threshold: float,
	audio_threshold: float,
	push_url: str,
	token: str,
) -> None:
	now = datetime.now().strftime("%H:%M:%S")
	lines = [
		"\033[2J\033[H",
		f"PHASE live monitor   {now}",
		f"backend: {url}",
		f"window: {window} readings   CSI confidence: {csi_threshold:.2f}   "
		f"audio confidence: {audio_threshold:.2f}",
		f"audio loud-label threshold: {db_threshold:g} dB   status: {status}",
		"fusion index: 50% x P(non-empty CSI) + 50% x P(loud audio)",
		"-" * 120,
	]
	if not zones:
		lines.append("  (no zones reporting)")
	else:
		for zone in sorted(zones, key=lambda item: str(item.get("zone"))):
			zone_id = zone.get("zone")
			buffer = buffers.get(zone_id, deque())
			line, prediction = _zone_lines(
				zone, buffer, window, context, db_threshold,
				csi_threshold, audio_threshold,
			)
			lines.append(line)
			if prediction is not None:
				_push_prediction(push_url, token, prediction)
	lines.extend(("", "Ctrl+C to quit."))
	print("\n".join(lines), flush=True)


def run(
	url: str,
	window: int,
	interval: float,
	csi_threshold: float,
	audio_threshold: float,
	push_url: str,
	token: str,
) -> None:
	global _audio_model
	_, _, classes = _ensure_loaded()
	_audio_model, metadata = _load_db_model(AUDIO_MODEL_PATH)
	audio_window = int(metadata["window_readings"])
	context = int(metadata["context_readings"])
	db_threshold = float(metadata["threshold_db"])
	if audio_window != window:
		raise ValueError(
			f"audio model expects {audio_window} readings but CSI window is {window}"
		)
	buffers: dict = {}
	_enable_ansi()
	while True:
		try:
			payload = fetch_json("/api/data", base_url=url, timeout=5.0)
			zones = payload.get("zones", []) if isinstance(payload, dict) else []
			status = "connected"
		except Exception as error:
			zones = []
			status = f"backend unreachable ({error}); retrying"

		for zone in zones:
			zone_id = zone.get("zone")
			if zone_id is None or zone.get("ts") is None:
				continue
			buffer = buffers.setdefault(zone_id, deque(maxlen=window))
			_update_buffer(buffer, zone)

		_render(
			url, status, zones, buffers, window, context, db_threshold,
			csi_threshold, audio_threshold, push_url, token,
		)
		time.sleep(2.0 if status != "connected" else interval)


_audio_model = None


def main() -> None:
	parser = argparse.ArgumentParser(
		description="Monitor CSI activity and ESP audio loudness predictions together."
	)
	parser.add_argument("--url", default=DEFAULT_URL,
					help=f"backend base URL (default: {DEFAULT_URL})")
	parser.add_argument("--window", type=int, default=CSI_WINDOW,
					help="readings per zone window (default: 20)")
	parser.add_argument("--interval", type=float, default=0.5,
					help="seconds between backend polls (default: 0.5)")
	parser.add_argument("--csi-threshold", type=float, default=CSI_THRESHOLD,
					help="minimum CSI activity confidence (default: 0.6)")
	parser.add_argument("--audio-threshold", type=float, default=AUDIO_THRESHOLD,
					help="minimum loudness probability (default: 0.5)")
	parser.add_argument("--push-url", default=None,
					help="backend base URL to POST predictions to (default: same as --url)")
	parser.add_argument("--token", default=os.environ.get("GHOST_INGEST_TOKEN", ""),
					help="ingest token sent with pushed predictions "
						"(default: $GHOST_INGEST_TOKEN)")
	args = parser.parse_args()
	if args.window < 2:
		parser.error("--window must be at least 2")
	if args.interval <= 0:
		parser.error("--interval must be greater than 0")
	if not 0.0 <= args.csi_threshold <= 1.0:
		parser.error("--csi-threshold must be between 0 and 1")
	if not 0.0 <= args.audio_threshold <= 1.0:
		parser.error("--audio-threshold must be between 0 and 1")
	try:
		run(args.url, args.window, args.interval,
			args.csi_threshold, args.audio_threshold,
			args.push_url or args.url, args.token)
	except (OSError, ValueError, KeyError) as error:
		print(f"could not start combined live monitor: {error}", file=sys.stderr)
		sys.exit(1)
	except KeyboardInterrupt:
		print("\nstopped.")


if __name__ == "__main__":
	main()