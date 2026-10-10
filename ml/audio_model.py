import argparse
import json
import os
import warnings
import wave
from pathlib import Path
from typing import Iterator

import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from sklearn.metrics import confusion_matrix
from sklearn.model_selection import GroupShuffleSplit
from tensorflow.keras.callbacks import EarlyStopping, ModelCheckpoint
import tensorflow as tf

# repo-relative esp dataset. the wav folder comes from --wav-dir / SCREAM_DATASET_DIR now.
DEFAULT_DATASET = Path(__file__).resolve().parent.parent / "data" / "dataset.json"
STFT_FRAME_LENGTH = 1024
STFT_FRAME_STEP = 256
TARGET_SAMPLE_RATE = 44100
TARGET_DURATION_SECONDS = 10
STFT_FREQUENCY_BINS = STFT_FRAME_LENGTH // 2 + 1
SPECTROGRAM_DB_FLOOR = -80.0
TARGET_FRAMES = (
	TARGET_SAMPLE_RATE * TARGET_DURATION_SECONDS + STFT_FRAME_STEP - 1
) // STFT_FRAME_STEP
FOLDER_LABELS = {"notscreaming": 0, "screaming": 1}
TARGET_SAMPLES = TARGET_SAMPLE_RATE * TARGET_DURATION_SECONDS
DB_WINDOW_READINGS = 20
DB_CONTEXT_READINGS = 8


def waveform_to_spectrogram(mono_audio: np.ndarray) -> np.ndarray:
	# Keep WAV training and live microphone inference on the same dBFS transform.
	window = tf.signal.hann_window(STFT_FRAME_LENGTH, periodic=True)
	complex_spectrogram = tf.signal.stft(
		tf.convert_to_tensor(mono_audio, dtype=tf.float32),
		frame_length=STFT_FRAME_LENGTH,
		frame_step=STFT_FRAME_STEP,
		fft_length=STFT_FRAME_LENGTH,
		window_fn=tf.signal.hann_window,
		pad_end=True,
	)
	magnitude = tf.abs(complex_spectrogram)
	single_sided_scale = tf.concat(
		[
			tf.ones((1,), dtype=magnitude.dtype),
			tf.fill((STFT_FREQUENCY_BINS - 2,), 2.0),
			tf.ones((1,), dtype=magnitude.dtype),
		],
		axis=0,
	)
	amplitude = magnitude * single_sided_scale / tf.reduce_sum(window)
	spectrogram_db = 20.0 * tf.math.log(
		tf.maximum(amplitude, 10.0 ** (SPECTROGRAM_DB_FLOOR / 20.0))
	) / tf.math.log(10.0)
	spectrogram = np.asarray(spectrogram_db.numpy(), dtype=np.float32)
	if not np.isfinite(spectrogram).all():
		raise ValueError("Audio contains non-finite values")
	return spectrogram

def decode_wav_file(path: str | Path) -> tuple[np.ndarray, int]:
	# Read PCM WAV data, mix its channels, and convert to a single-sided dBFS spectrogram.
	path = Path(path)
	with wave.open(str(path), "rb") as wav_file:
		if wav_file.getcomptype() != "NONE":
			raise ValueError(f"Compressed WAV audio is not supported: {path}")
		channel_count = wav_file.getnchannels()
		sample_width = wav_file.getsampwidth()
		sample_rate = wav_file.getframerate()
		frame_count = wav_file.getnframes()
		pcm_data = wav_file.readframes(frame_count)

	if channel_count < 1 or frame_count == 0:
		raise ValueError(f"Audio file is empty or has an invalid shape: {path}")
	if len(pcm_data) != frame_count * channel_count * sample_width:
		raise ValueError(f"Audio file has incomplete PCM data: {path}")

	if sample_width == 1:
		audio = (np.frombuffer(pcm_data, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
	elif sample_width == 2:
		audio = np.frombuffer(pcm_data, dtype="<i2").astype(np.float32) / 32768.0
	elif sample_width == 3:
		bytes_24 = np.frombuffer(pcm_data, dtype=np.uint8).reshape(-1, 3).astype(np.int32)
		samples_24 = bytes_24[:, 0] | (bytes_24[:, 1] << 8) | (bytes_24[:, 2] << 16)
		audio = ((samples_24 ^ 0x800000) - 0x800000).astype(np.float32) / 8388608.0
	elif sample_width == 4:
		audio = np.frombuffer(pcm_data, dtype="<i4").astype(np.float32) / 2147483648.0
	else:
		raise ValueError(f"Unsupported PCM sample width ({sample_width} bytes): {path}")

	mono_audio = np.mean(audio.reshape(-1, channel_count), axis=1, dtype=np.float32)
	try:
		return waveform_to_spectrogram(mono_audio), int(sample_rate)
	except ValueError as error:
		raise ValueError(f"Audio file contains invalid samples: {path}") from error


def iter_decoded_wavs(
	dataset_dir: str | Path,
) -> Iterator[tuple[Path, str, np.ndarray, int]]:
	# Yield path, parent-folder label, float32 dBFS spectrogram, and sample rate.
	dataset_dir = Path(dataset_dir)
	if not dataset_dir.is_dir():
		raise NotADirectoryError(f"Dataset directory does not exist: {dataset_dir}")

	for path in sorted(dataset_dir.rglob("*.wav")):
		try:
			spectrogram, sample_rate = decode_wav_file(path)
		except (OSError, ValueError, wave.Error, tf.errors.OpError) as error:
			warnings.warn(f"Skipping {path}: {error}", RuntimeWarning)
			continue
		yield path, path.parent.name, spectrogram, sample_rate

# Set up Convolutional Neural Network (CNN) model for audio classification using TensorFlow/Keras. 
# The model consists of several convolutional layers followed by pooling layers,
# a global max pooling layer, and dense layers for classification. 
# The model is compiled with the Adam optimizer and binary cross-entropy loss function, 
# suitable for binary classification tasks.
def build_model(input_shape, learning_rate=0.001):
	model = tf.keras.Sequential(
		[
			tf.keras.layers.Input(shape=input_shape),
			tf.keras.layers.Conv2D(16, 5, strides=2, padding="same", activation="relu"),
			tf.keras.layers.MaxPooling2D(pool_size=2),
			tf.keras.layers.Conv2D(32, 3, padding="same", activation="relu"),
			tf.keras.layers.MaxPooling2D(pool_size=2),
			tf.keras.layers.Conv2D(64, 3, strides=2, padding="same", activation="relu"),
			tf.keras.layers.GlobalMaxPooling2D(),
			tf.keras.layers.Dense(64, activation="relu"),
			tf.keras.layers.Dropout(0.3),
			tf.keras.layers.Dense(1, activation="sigmoid"),
		]
	)
	# Compile model with Adam optimizer, Binary Crossentropy loss, accuracy and AUC metrics
	model.compile(
		optimizer=tf.keras.optimizers.Adam(learning_rate=learning_rate),
		loss="binary_crossentropy",
		metrics=["accuracy", tf.keras.metrics.AUC(name="auc")],
	)
	return model

def preprocess_spectrogram(spectrogram, target_frames):
	# Preserve dBFS differences while scaling the fixed range to [0, 1].
	spectrogram = np.clip(spectrogram, SPECTROGRAM_DB_FLOOR, 0.0)
	spectrogram = (spectrogram - SPECTROGRAM_DB_FLOOR) / -SPECTROGRAM_DB_FLOOR
	if len(spectrogram) < target_frames:
		spectrogram = np.pad(
			spectrogram,
			((0, target_frames - len(spectrogram)), (0, 0)),
			constant_values=0.0,
		)
	else:
		spectrogram = spectrogram[:target_frames]
	return spectrogram[..., np.newaxis].astype(np.float32, copy=False)


def preprocess_db_readings(
	readings: list,
	threshold: float = 90.0,
	window_readings: int = DB_WINDOW_READINGS,
	context_readings: int = DB_CONTEXT_READINGS,
) -> np.ndarray:
	if context_readings < 2 or window_readings < context_readings:
		raise ValueError("window_readings must be >= context_readings >= 2")
	audio_db = np.asarray(
		[float(reading["audio_db"]) for reading in readings
		 if reading.get("audio_db") is not None],
		dtype=np.float32,
	)
	if audio_db.size < window_readings:
		raise ValueError(
			f"Expected at least {window_readings} audio_db readings, got {audio_db.size}"
		)
	audio_db = audio_db[-window_readings:]
	if not np.isfinite(audio_db).all():
		raise ValueError("audio_db readings must be finite numbers")
	# Each row represents an overlapping local time patch; this gives the
	# existing 2D CNN temporal structure without fabricating frequency content.
	patches = np.lib.stride_tricks.sliding_window_view(audio_db, context_readings)
	patches = np.clip((patches - threshold) / 20.0, -2.0, 2.0)
	return patches[..., np.newaxis].astype(np.float32, copy=False)


def prepare_db_dataset(
	dataset_path: str | Path,
	threshold: float = 90.0,
	min_loud_fraction: float = 0.2,
	window_readings: int = DB_WINDOW_READINGS,
	context_readings: int = DB_CONTEXT_READINGS,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
	if not 0.0 <= min_loud_fraction <= 1.0:
		raise ValueError("min_loud_fraction must be between 0 and 1")
	with Path(dataset_path).open(encoding="utf-8") as dataset_file:
		windows = json.load(dataset_file).get("windows", [])
	features = []
	labels = []
	groups = []
	for window in windows:
		readings = [
			reading for reading in window.get("readings", [])
			if reading.get("audio_db") is not None
		]
		if len(readings) < window_readings:
			continue
		selected = readings[-window_readings:]
		values = np.asarray([float(reading["audio_db"]) for reading in selected])
		features.append(preprocess_db_readings(
			selected, threshold, window_readings, context_readings
		))
		labels.append(int(np.mean(values >= threshold) >= min_loud_fraction))
		groups.append(window.get("session_id"))
	if not features:
		raise ValueError(f"No windows with {window_readings} audio_db readings in {dataset_path}")
	return np.stack(features), np.asarray(labels, dtype=np.int32), np.asarray(groups)


def train_db_model(
	dataset_path: str | Path,
	output_path: str | Path,
	threshold: float = 90.0,
	min_loud_fraction: float = 0.2,
	window_readings: int = DB_WINDOW_READINGS,
	context_readings: int = DB_CONTEXT_READINGS,
	epochs: int = 30,
) -> None:
	features, labels, groups = prepare_db_dataset(
		dataset_path, threshold, min_loud_fraction, window_readings, context_readings
	)
	counts = np.bincount(labels, minlength=2)
	if np.any(counts == 0):
		raise ValueError("Threshold settings must produce both loud and not-loud windows")
	if len(np.unique(groups)) < 2:
		raise ValueError("At least two separate sessions are needed for validation")
	train_indices, val_indices = next(GroupShuffleSplit(
		n_splits=1, test_size=0.25, random_state=42
	).split(features, labels, groups))
	if len(np.unique(labels[train_indices])) < 2 or len(np.unique(labels[val_indices])) < 2:
		raise ValueError(
			"Session-grouped split needs both classes in train and validation; "
			"try another threshold or collect more sessions"
		)
	train_counts = np.bincount(labels[train_indices], minlength=2)
	class_weights = {
		label: len(train_indices) / (2 * count)
		for label, count in enumerate(train_counts)
	}
	model = build_model(input_shape=features.shape[1:])
	output_path = Path(output_path)
	callbacks = [
		EarlyStopping(
			monitor="val_auc", mode="max", min_delta=0.001,
			patience=5, restore_best_weights=True,
		),
		ModelCheckpoint(
			str(output_path), save_best_only=True, save_weights_only=False,
			monitor="val_auc", mode="max",
		),
	]
	model.fit(
		features[train_indices], labels[train_indices],
		validation_data=(features[val_indices], labels[val_indices]),
		class_weight=class_weights, epochs=epochs, batch_size=32,
		callbacks=callbacks, verbose=1,
	)
	model.save(output_path)
	predictions = model.predict(features[val_indices], verbose=0).reshape(-1)
	confusion = confusion_matrix(labels[val_indices], predictions >= 0.5, labels=[0, 1])
	true_negative, false_positive, false_negative, true_positive = confusion.ravel()
	precision = true_positive / (true_positive + false_positive) if true_positive + false_positive else 0.0
	recall = true_positive / (true_positive + false_negative) if true_positive + false_negative else 0.0
	f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
	accuracy = (true_positive + true_negative) / confusion.sum()
	print("Session-held-out validation diagnostics (pseudo-labels):")
	print(f"  windows: {confusion.sum()}")
	print(f"  accuracy: {accuracy:.4f}")
	print(f"  precision (loud): {precision:.4f}")
	print(f"  recall (loud): {recall:.4f}")
	print(f"  F1 (loud): {f1:.4f}")
	print("Session-held-out validation confusion matrix (rows=true, columns=predicted):")
	print(confusion)
	plt.figure(figsize=(6, 5))
	sns.heatmap(
		confusion,
		annot=True,
		fmt="d",
		cmap="Blues",
		cbar=False,
		xticklabels=["Not loud", "Loud"],
		yticklabels=["Not loud", "Loud"],
	)
	plt.xlabel("Predicted label")
	plt.ylabel("Actual label")
	plt.title("ESP dB validation confusion matrix")
	plt.tight_layout()
	plt.show()
	metadata_path = output_path.with_name(f"{output_path.stem}_meta.json")
	metadata_path.write_text(json.dumps({
		"input": "audio_db temporal patches",
		"threshold_db": threshold,
		"min_loud_fraction": min_loud_fraction,
		"window_readings": window_readings,
		"context_readings": context_readings,
		"normalization_db": 20.0,
		"labels": ["not_loud", "loud"],
	}, indent=2) + "\n", encoding="utf-8")
	print(f"Saved model: {output_path}")
	print(f"Saved preprocessing metadata: {metadata_path}")
	print(f"Pseudo-label counts: not_loud={counts[0]}, loud={counts[1]}")


class SpectrogramSequence(tf.keras.utils.Sequence):
	def __init__(
		self,
		examples: list[tuple[Path, int]],
		batch_size: int = 8,
		shuffle: bool = False,
		random_seed: int = 42,
	) -> None:
		super().__init__()
		self.examples = examples
		self.batch_size = batch_size
		self.shuffle = shuffle
		self.rng = np.random.default_rng(random_seed)
		self.indices = np.arange(len(examples))
		self.on_epoch_end()

	def __len__(self) -> int:
		return (len(self.examples) + self.batch_size - 1) // self.batch_size

	def __getitem__(self, batch_index: int) -> tuple[np.ndarray, np.ndarray]:
		start = batch_index * self.batch_size
		batch_indices = self.indices[start : start + self.batch_size]
		batch_features: list[np.ndarray] = []
		batch_labels: list[int] = []
		for example_index in batch_indices:
			path, label = self.examples[int(example_index)]
			spectrogram, sample_rate = decode_wav_file(path)
			if sample_rate != TARGET_SAMPLE_RATE:
				raise ValueError(
					f"Expected {TARGET_SAMPLE_RATE} Hz audio, got {sample_rate} Hz: {path}"
				)
			batch_features.append(preprocess_spectrogram(spectrogram, TARGET_FRAMES))
			batch_labels.append(label)
		if not batch_features:
			raise IndexError(f"No examples for batch {batch_index}")
		return np.stack(batch_features), np.asarray(batch_labels, dtype=np.float32)

	def on_epoch_end(self) -> None:
		if self.shuffle:
			self.rng.shuffle(self.indices)


def prepare_dataset(
	dataset_dir: str | Path,
	validation_split: float = 0.2,
	random_seed: int = 42,
) -> tuple[SpectrogramSequence, SpectrogramSequence]:
	if not 0.0 < validation_split < 1.0:
		raise ValueError("validation_split must be between 0 and 1")

	dataset_path = Path(dataset_dir)
	if not dataset_path.is_dir():
		raise NotADirectoryError(f"Dataset directory does not exist: {dataset_path}")

	paths_by_label: dict[int, list[Path]] = {label: [] for label in FOLDER_LABELS.values()}
	for path in sorted(dataset_path.rglob("*.wav")):
		folder_name = path.parent.name
		folder_key = folder_name.strip().casefold().replace(" ", "").replace("_", "")
		if folder_key not in FOLDER_LABELS:
			raise ValueError(
				f"Unknown class folder {folder_name!r} for {path}; "
				"expected Screaming or NotScreaming"
			)
		paths_by_label[FOLDER_LABELS[folder_key]].append(path)

	if not any(paths_by_label.values()):
		raise ValueError(f"No valid WAV files found in {dataset_dir}")
	if any(not paths for paths in paths_by_label.values()):
		raise ValueError("Dataset must contain both Screaming and NotScreaming WAV files")

	rng = np.random.default_rng(random_seed)
	train_examples: list[tuple[Path, int]] = []
	validation_examples: list[tuple[Path, int]] = []
	for class_label in FOLDER_LABELS.values():
		class_paths = paths_by_label[class_label]
		if len(class_paths) < 2:
			raise ValueError(
				"Each class needs at least two WAV files for a train/validation split"
			)
		rng.shuffle(class_paths)
		validation_count = int(round(len(class_paths) * validation_split))
		validation_count = min(max(validation_count, 1), len(class_paths) - 1)
		validation_examples.extend((path, class_label) for path in class_paths[:validation_count])
		train_examples.extend((path, class_label) for path in class_paths[validation_count:])

	return (
		SpectrogramSequence(train_examples, shuffle=True, random_seed=random_seed),
		SpectrogramSequence(validation_examples),
	)


def train_model(model, train_data, val_data, epochs=15):
	label_counts = np.bincount(
		[label for _, label in train_data.examples], minlength=len(FOLDER_LABELS)
	)
	if np.any(label_counts == 0):
		raise ValueError("Training split must contain both classes")
	class_weights = {
		class_label: len(train_data.examples) / (len(FOLDER_LABELS) * count)
		for class_label, count in enumerate(label_counts)
	}

	early_stopping = EarlyStopping(
		monitor="val_auc",
		mode="max",
		min_delta=0.001,
		patience=3,
		restore_best_weights=True,
	)

	checkpoint = ModelCheckpoint(
		"audio_classification_model.keras",
		save_best_only=True,
		save_weights_only=False,
		monitor="val_auc",
		mode="max",
	)

	history = model.fit(
		train_data,
		epochs=epochs,
		validation_data=val_data,
		class_weight=class_weights,
		verbose=1,
		callbacks=[early_stopping, checkpoint]
	)
	model.save("audio_model.keras")
	return history

def train_from_checkpoint(train_data, val_data, model, fine_tune_layers, epochs: int = 5, keep_pos_emb: bool = True):

	for layer in model.layers:
		layer.trainable = False

	for i in range(fine_tune_layers):
		model.layers[-i].trainable = True

	
	early_stopping = EarlyStopping(
			monitor="val_auc",
			mode="max",
			min_delta=0.001,
			patience=3,
			restore_best_weights=True,
		)
	
	label_counts = np.bincount(
		[label for _, label in train_data.examples], minlength=len(FOLDER_LABELS)
	)

	if np.any(label_counts == 0):
		raise ValueError("Training split must contain both classes")
	class_weights = {
		class_label: len(train_data.examples) / (len(FOLDER_LABELS) * count)
		for class_label, count in enumerate(label_counts)
	}

	if keep_pos_emb:
		model.fit(
			train_data,
			epochs=epochs,
			validation_data=val_data,
			class_weight=class_weights,
			verbose=1,
			callbacks=[early_stopping]
			)
		return
	
	model.load_weights()
	model.fit(
		train_data,
		epochs=epochs,
		validation_data=val_data,
		class_weight=class_weights,
		verbose=1,
		callbacks=[early_stopping]
	)


def print_model_diagnostics(model, validation_data, threshold=0.5) -> None:
	labels: list[np.ndarray] = []
	probabilities: list[np.ndarray] = []
	for batch_index in range(len(validation_data)):
		batch_features, batch_labels = validation_data[batch_index]
		batch_probabilities = model(batch_features, training=False).numpy().reshape(-1)
		labels.append(batch_labels.astype(np.int32))
		probabilities.append(batch_probabilities)

	true_labels = np.concatenate(labels)
	positive_scores = np.concatenate(probabilities)
	predicted_labels = (positive_scores >= threshold).astype(np.int32)
	confusion = confusion_matrix(true_labels, predicted_labels, labels=[0, 1])
	true_negative, false_positive, false_negative, true_positive = confusion.ravel()
	precision = true_positive / (true_positive + false_positive) if true_positive + false_positive else 0.0
	recall = true_positive / (true_positive + false_negative) if true_positive + false_negative else 0.0
	f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
	accuracy = (true_positive + true_negative) / confusion.sum()
	auc = tf.keras.metrics.AUC()
	auc.update_state(true_labels, positive_scores)
	loss = tf.keras.losses.binary_crossentropy(true_labels, positive_scores).numpy().mean()

	print("Validation diagnostics:")
	print(f"  clips: {confusion.sum()}")
	print(f"  binary cross-entropy: {loss:.4f}")
	print(f"  accuracy: {accuracy:.4f}")
	print(f"  precision (scream): {precision:.4f}")
	print(f"  recall (scream): {recall:.4f}")
	print(f"  F1 (scream): {f1:.4f}")
	print(f"  ROC AUC: {float(auc.result().numpy()):.4f}")
	print(f"  threshold: {threshold:.2f}")
	print("  confusion matrix (rows=actual [not scream, scream]; columns=predicted):")
	print(f"    [[{true_negative}, {false_positive}], [{false_negative}, {true_positive}]]")
	plt.figure(figsize=(6, 5))
	sns.heatmap(
		confusion,
		annot=True,
		fmt="d",
		cmap="Blues",
		cbar=False,
		xticklabels=["Not screaming", "Screaming"],
		yticklabels=["Not screaming", "Screaming"],
	)
	plt.xlabel("Predicted label")
	plt.ylabel("Actual label")
	plt.title("Validation confusion matrix")
	plt.tight_layout()
	plt.show()


def main() -> None:
	parser = argparse.ArgumentParser(description="Train the audio CNN.")
	parser.add_argument(
		"--format", choices=("wav", "esp-db"), default="esp-db",
		help="training data format (default: esp-db)",
	)
	parser.add_argument("--data", default=DEFAULT_DATASET,
					help="ESP dataset JSON path when --format esp-db")
	parser.add_argument("--output", default="audio_model.keras",
					help="output model path for --format esp-db")
	parser.add_argument("--threshold-db", type=float, default=90.0,
					help="provisional loudness threshold for ESP pseudo-labels")
	parser.add_argument("--min-loud-fraction", type=float, default=0.2,
					help="fraction of readings above threshold to label a window loud")
	parser.add_argument("--window-readings", type=int, default=DB_WINDOW_READINGS,
					help="readings per ESP window")
	parser.add_argument("--context-readings", type=int, default=DB_CONTEXT_READINGS,
					help="readings per temporal patch for ESP CNN input")
	parser.add_argument("--epochs", type=int, default=30,
					help="maximum number of training epochs")
	parser.add_argument("--wav-dir", default=os.environ.get("SCREAM_DATASET_DIR"),
					help="folder of labelled WAV files for --format wav (default: $SCREAM_DATASET_DIR)")
	args = parser.parse_args()
	if args.format == "wav":
		if not args.wav_dir:
			parser.error("--format wav needs --wav-dir (or set SCREAM_DATASET_DIR)")
		train_data, val_data = prepare_dataset(args.wav_dir)
		print(f"Training clips: {len(train_data.examples)}")
		print(f"Validation clips: {len(val_data.examples)}")
		for folder_name, class_label in FOLDER_LABELS.items():
			print(
				f"{folder_name}: "
				f"train={sum(label == class_label for _, label in train_data.examples)}, "
				f"validation={sum(label == class_label for _, label in val_data.examples)}"
			)
		model = build_model(input_shape=(TARGET_FRAMES, STFT_FREQUENCY_BINS, 1))
		model.summary()
		train_model(model, train_data, val_data, epochs=args.epochs)
		print_model_diagnostics(model, val_data)
		return

	train_db_model(
		args.data,
		args.output,
		threshold=args.threshold_db,
		min_loud_fraction=args.min_loud_fraction,
		window_readings=args.window_readings,
		context_readings=args.context_readings,
		epochs=args.epochs,
	)

if __name__ == "__main__":
	main()


