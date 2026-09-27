import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from csi_processing import _amplitude_matrix
from railway_client import fetch_latest


# Get the current UTC time in ISO 8601 format 
def _utc_now() -> str:
	return datetime.now(timezone.utc).isoformat()

# Convert payload data into a list of records with the specified label and collection timestamp
def _records_from_payload(
	payload: Any, label: str, collected_at: str
) -> list[dict[str, Any]]:
	if isinstance(payload, dict) and "data" in payload:
		payload = payload["data"]

	if not isinstance(payload, dict):
		payload = {"csi_amplitude": payload}

	source_timestamp = payload.get("timestamp")
	device_id = payload.get("device_id", payload.get("esp_id"))
	records: list[dict[str, Any]] = []

    # Helper to add a sample to the records list, extracting relevant information and applying any extra fields
	def add_sample(sample: Any, extra: dict[str, Any] | None = None) -> None:
		sample_timestamp = (
			sample.get("timestamp", source_timestamp)
			if isinstance(sample, dict)
			else source_timestamp
		)

        # Determine the device ID for the sample, falling back to the overall device ID if not present.
		sample_device = (
			sample.get("device_id", sample.get("esp_id", device_id))
			if isinstance(sample, dict)
			else device_id
		)

        # Get the amplitude matrix from the sample and create a record for each set of amplitudes
		matrix = _amplitude_matrix(sample)
		for amplitudes in matrix:
			record: dict[str, Any] = {
				"timestamp": sample_timestamp,
				"collected_at": collected_at,
				"label": label,
				"amplitudes": amplitudes.tolist(),
			}
			if sample_device is not None:
				record["device_id"] = sample_device
			if extra:
				record.update(extra)
			records.append(record)

    # Get the list of links or samples from the payload and add them to the records list.
	if isinstance(payload.get("links"), list):
		for link in payload["links"]:
			if not isinstance(link, dict):
				continue
			amplitudes = link.get("current_amplitude")
			if amplitudes is None:
				amplitudes = link
			add_sample(
				{"csi_amplitude": amplitudes},
				{
					key: link[key]
					for key in ("id", "tx", "rx")
					if key in link
				},
			)

    # If payload contains a list of samples, add each sample to the records list.
	elif isinstance(payload.get("samples"), list):
		for sample in payload["samples"]:
			add_sample(sample)
	
    # If payload is a single sample, add it to the records list.
	else:
		add_sample(payload)

	return records

# Compile all collected samples into a json dataset and save it to the specified output path.
def collect_dataset(
	output_path: Path,
	label: str,
	duration: float,
	interval: float,
	max_samples: int | None,
) -> int:
	samples: list[dict[str, Any]] = []
	started_at = _utc_now()
	stop_at = time.monotonic() + duration

	print(f"Collecting CSI for {duration:g} seconds; label={label!r}")
	try:
		while time.monotonic() < stop_at:
			try:
				payload = fetch_latest(timeout=5.0)
				rows = _records_from_payload(payload, label, _utc_now())
				if max_samples is not None:
					rows = rows[: max_samples - len(samples)]
				samples.extend(rows)
				if rows:
					print(f"Collected {len(samples)} sample(s)", end="\r")
				if max_samples is not None and len(samples) >= max_samples:
					break
			except (OSError, ValueError, TypeError) as error:
				print(f"CSI poll failed: {error}")
			time.sleep(min(interval, max(0, stop_at - time.monotonic())))
	except KeyboardInterrupt:
		print("\nCollection interrupted; saving collected samples.")

	dataset = {
		"format": "shellhacks-csi-dataset",
		"version": 1,
		"created_at": started_at,
		"label": label,
		"sample_count": len(samples),
		"samples": samples,
	}
	output_path.parent.mkdir(parents=True, exist_ok=True)
	with output_path.open("w", encoding="utf-8") as output_file:
		json.dump(dataset, output_file, indent=2)
		output_file.write("\n")
	print(f"\nSaved {len(samples)} sample(s) to {output_path}")
	return len(samples)

# Runs the dataset collection process based on command-line arguments, handling any errors and saving collected samples.
def main() -> None:
	parser = argparse.ArgumentParser(
		description="Collect ESP CSI packets from the configured Railway endpoint into JSON."
	)
	parser.add_argument("--output", type=Path, default=Path("csi_dataset.json"))
	parser.add_argument("--label", default="unlabeled")
	parser.add_argument("--duration", type=float, default=60.0, help="collection time in seconds")
	parser.add_argument(
		"--interval",
		type=float,
		default=float(os.environ.get("RAILWAY_POLL_INTERVAL", "0.25")),
		help="seconds between endpoint polls",
	)
	parser.add_argument("--max-samples", type=int)
	args = parser.parse_args()

	if args.duration <= 0 or args.interval <= 0:
		parser.error("--duration and --interval must be greater than zero")
	if args.max_samples is not None and args.max_samples < 1:
		parser.error("--max-samples must be at least one")

	collect_dataset(args.output, args.label, args.duration, args.interval, args.max_samples)


if __name__ == "__main__":
	main()

