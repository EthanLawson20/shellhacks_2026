"""Run live scream classification from the computer's microphone.

The classifier uses overlapping 10-second, 44.1 kHz windows to match the
audio model's training input. Install the ML requirements and run:

    python classify_audio_live.py
    python classify_audio_live.py --threshold 0.7 --device 1
"""
import argparse
import json
import os
import sys
import threading
import time
from collections import deque
from pathlib import Path

import numpy as np

from audio_model import (
	DB_CONTEXT_READINGS,
	DB_WINDOW_READINGS,
	TARGET_SAMPLE_RATE,
	TARGET_SAMPLES,
	TARGET_FRAMES,
	STFT_FREQUENCY_BINS,
	preprocess_db_readings,
	preprocess_spectrogram,
	waveform_to_spectrogram,
)
from fetch_dataset import MAX_GAP_SECONDS, _parse_ts
from railway_client import fetch_json

MIC_MODEL_PATH = "audio_classification_model.keras"
ESP_MODEL_PATH = "audio_model.keras"
DEFAULT_URL = "https://shellhacks2026-production.up.railway.app"


def _enable_ansi() -> None:
	if os.name == "nt":
		os.system("")


def _load_model(model_path: str):
	from tensorflow import keras

	return keras.models.load_model(model_path)


def _load_db_model(model_path: str):
	metadata_path = Path(model_path).with_name(f"{Path(model_path).stem}_meta.json")
	with metadata_path.open(encoding="utf-8") as metadata_file:
		metadata = json.load(metadata_file)
	if metadata.get("input") != "audio_db temporal patches":
		raise ValueError(f"unsupported ESP model metadata: {metadata_path}")
	model = _load_model(model_path)
	window = int(metadata["window_readings"])
	context = int(metadata["context_readings"])
	expected_shape = (window - context + 1, context, 1)
	if tuple(model.input_shape[1:]) != expected_shape:
		raise ValueError(
			f"model input shape {model.input_shape[1:]} does not match metadata "
			f"{expected_shape}"
		)
	return model, metadata


def _append_zone_reading(buffer: deque, zone: dict) -> None:
	if zone.get("ts") is None or zone.get("audio_db") is None:
		return
	ts = _parse_ts(zone["ts"])
	if buffer:
		previous = _parse_ts(buffer[-1]["ts"])
		if ts == previous:
			return
		if ts < previous or (ts - previous).total_seconds() > MAX_GAP_SECONDS:
			buffer.clear()
	buffer.append(zone)


def run_esp_db(
	model_path: str,
	url: str,
	threshold: float,
	interval: float,
) -> None:
	model, metadata = _load_db_model(model_path)
	window = int(metadata["window_readings"])
	context = int(metadata["context_readings"])
	db_threshold = float(metadata["threshold_db"])
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
			if zone_id is None:
				continue
			buffer = buffers.setdefault(zone_id, deque(maxlen=window))
			_append_zone_reading(buffer, zone)

		lines = [
			"\033[2J\033[H",
			"Live audio loudness classifier (ESP feed)",
			f"model: {model_path}",
			f"backend: {url}",
			f"window: {window} readings   dB label rule: >= {db_threshold:g} dB",
			f"decision threshold: {threshold:.2f}   status: {status}",
			"-" * 78,
		]
		if not zones:
			lines.append("  (no zones reporting)")
		else:
			for zone in sorted(zones, key=lambda item: str(item.get("zone"))):
				zone_id = zone.get("zone")
				buffer = buffers.get(zone_id, deque())
				name = zone.get("name") or f"Zone {zone_id}"
				if zone.get("stale"):
					prediction = "FEED STALE"
				elif len(buffer) < window:
					prediction = f"warming up {len(buffer)}/{window}"
				else:
					features = preprocess_db_readings(
						list(buffer), db_threshold, window, context
					).reshape(1, window - context + 1, context, 1)
					loud_probability = float(model.predict(features, verbose=0)[0][0])
					label = "LOUD" if loud_probability >= threshold else "not loud"
					prediction = f"{label} {loud_probability:.0%}"
				level = zone.get("audio_db", "?")
				lines.append(f"  {name:<14} pred: {prediction:<24} audio_db: {level}")
		lines.extend(("", "Ctrl+C to quit."))
		print("\n".join(lines), flush=True)
		time.sleep(2.0 if status != "connected" else interval)


def run(model_path: str, threshold: float, interval: float, device) -> None:
	try:
		import sounddevice as sd
	except ImportError as error:
		raise RuntimeError(
			"Microphone capture requires sounddevice; install requirements-ml.txt first."
		) from error

	model = _load_model(model_path)
	blocks = deque()
	buffered_samples = 0
	lock = threading.Lock()
	callback_error = None

	def capture_callback(indata, _frames, _time_info, status):
		nonlocal buffered_samples, callback_error
		if status:
			callback_error = str(status)
		block = indata[:, 0].copy()
		with lock:
			blocks.append(block)
			buffered_samples += len(block)
			while buffered_samples > TARGET_SAMPLES and blocks:
				excess = buffered_samples - TARGET_SAMPLES
				oldest = blocks.popleft()
				if len(oldest) > excess:
					blocks.appendleft(oldest[excess:])
					buffered_samples -= excess
				else:
					buffered_samples -= len(oldest)

	_enable_ansi()
	try:
		with sd.InputStream(
			samplerate=TARGET_SAMPLE_RATE,
			channels=1,
			dtype="float32",
			device=device,
			callback=capture_callback,
		):
			while True:
				time.sleep(interval)
				with lock:
					available = buffered_samples
					audio = np.concatenate(tuple(blocks)) if blocks else np.empty(0, dtype=np.float32)

				if available < TARGET_SAMPLES:
					result = f"warming up {available / TARGET_SAMPLE_RATE:.1f}/{TARGET_SAMPLES / TARGET_SAMPLE_RATE:.0f}s"
				else:
					audio = audio[-TARGET_SAMPLES:]
					spectrogram = waveform_to_spectrogram(audio)
					features = preprocess_spectrogram(spectrogram, TARGET_FRAMES)
					batch = features.reshape(
						1, TARGET_FRAMES, STFT_FREQUENCY_BINS, 1
					)
					scream_probability = float(model.predict(batch, verbose=0)[0][0])
					label = "SCREAMING" if scream_probability >= threshold else "not screaming"
					result = f"{label}  scream: {scream_probability:.1%}  quiet: {1 - scream_probability:.1%}"

				print("\033[2J\033[H", end="")
				print("Live audio classifier (microphone)")
				print(f"model: {model_path}")
				print(f"input: {TARGET_SAMPLE_RATE} Hz mono   window: 10s   threshold: {threshold:.2f}")
				print(f"status: {callback_error or 'microphone active'}")
				print("-" * 64)
				print(f"  {result}")
				print("\nCtrl+C to quit.", flush=True)
	except KeyboardInterrupt:
		print("\nstopped.")


def main() -> None:
	parser = argparse.ArgumentParser(
		description="Live audio classification from a microphone or ESP dB feed."
	)
	parser.add_argument("--source", choices=("mic", "esp-db"), default="mic",
					help="audio input source (default: mic)")
	parser.add_argument("--model", help="trained Keras model path")
	parser.add_argument("--url", default=DEFAULT_URL,
					help=f"backend base URL for --source esp-db (default: {DEFAULT_URL})")
	parser.add_argument("--threshold", type=float, default=0.5,
					help="probability needed for a positive label (default: 0.5)")
	parser.add_argument("--interval", type=float, default=0.5,
					help="seconds between predictions (default: 0.5)")
	parser.add_argument("--device", type=int, default=None,
					help="input microphone device index (default: system default)")
	args = parser.parse_args()
	if not 0.0 <= args.threshold <= 1.0:
		parser.error("--threshold must be between 0 and 1")
	if args.interval <= 0:
		parser.error("--interval must be greater than 0")
	model_path = args.model or (
		ESP_MODEL_PATH if args.source == "esp-db" else MIC_MODEL_PATH
	)
	if not os.path.isfile(model_path):
		parser.error(f"model file not found: {model_path}")
	try:
		if args.source == "esp-db":
			run_esp_db(model_path, args.url, args.threshold, args.interval)
		else:
			run(model_path, args.threshold, args.interval, args.device)
	except (OSError, RuntimeError, ValueError, KeyError) as error:
		print(f"could not start live audio classification: {error}", file=sys.stderr)
		sys.exit(1)


if __name__ == "__main__":
	main()