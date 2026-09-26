import warnings
from pathlib import Path
from typing import Iterator

import kagglehub
import numpy as np
import tensorflow as tf

dataset_dir = "C:/Users/brady/.cache/kagglehub/datasets/whats2000/human-screaming-detection-dataset/versions/2"
STFT_FRAME_LENGTH = 1024
STFT_FRAME_STEP = 256
STFT_FREQUENCY_BINS = STFT_FRAME_LENGTH // 2 + 1
SPECTROGRAM_DB_FLOOR = -80.0
TARGET_FRAMES = 256
FOLDER_LABELS = {"notscreaming": 0, "screaming": 1}

def decode_wav_file(path: str | Path) -> tuple[np.ndarray, int]:
	# Decode WAV audio and convert its mono mix to a single-sided dBFS spectrogram.
	path = Path(path)
	contents = tf.io.read_file(str(path))
	audio, sample_rate = tf.audio.decode_wav(contents, desired_channels=-1)

	if audio.shape.rank != 2 or tf.shape(audio)[0].numpy() == 0:
		raise ValueError(f"Audio file is empty or has an invalid shape: {path}")

	mono_audio = tf.reduce_mean(audio, axis=1)
	window = tf.signal.hann_window(STFT_FRAME_LENGTH, periodic=True)
	complex_spectrogram = tf.signal.stft(
		mono_audio,
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
		raise ValueError(f"Audio file contains non-finite values: {path}")

	return spectrogram, int(sample_rate.numpy())


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
		except (OSError, ValueError, tf.errors.OpError) as error:
			warnings.warn(f"Skipping {path}: {error}", RuntimeWarning)
			continue
		yield path, path.parent.name, spectrogram, sample_rate

def build_model(input_shape, learning_rate=0.001):
    # Build a simple CNN model for audio classification.
    model = tf.keras.Sequential([
        tf.keras.layers.Input(shape=input_shape),
        tf.keras.layers.Conv1D(16, kernel_size=3, activation='relu'), # Detects local patterns in the waveform
        tf.keras.layers.MaxPooling1D(pool_size=2), # Downsamples the feature maps according to the pool size by taking the maximum value in each pool size window
        tf.keras.layers.Conv1D(32, kernel_size=3, activation='relu'),
        tf.keras.layers.MaxPooling1D(pool_size=2),
        tf.keras.layers.Flatten(),
        tf.keras.layers.Dense(64, activation='relu'),
        tf.keras.layers.Dense(1, activation='sigmoid')  # Binary classification
    ])

    optimizer = tf.keras.optimizers.Adam(learning_rate=learning_rate)
    
    model.compile(optimizer=optimizer,
                  loss='binary_crossentropy',
                  metrics=['accuracy'])
    return model

def preprocess_spectrogram(spectrogram, target_frames):
	# Pad or truncate frames while retaining the fixed frequency-bin dimension.
	if len(spectrogram) < target_frames:
		spectrogram = np.pad(
			spectrogram,
			((0, target_frames - len(spectrogram)), (0, 0)),
			constant_values=SPECTROGRAM_DB_FLOOR,
		)
	else:
		spectrogram = spectrogram[:target_frames]
	return spectrogram


def prepare_dataset(
	dataset_dir: str | Path,
	target_frames: int = TARGET_FRAMES,
	validation_split: float = 0.2,
	random_seed: int = 42,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
	if target_frames < 1:
		raise ValueError("target_frames must be at least 1")
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

	rng.shuffle(train_examples)
	rng.shuffle(validation_examples)
	train_data = np.empty(
		(len(train_examples), target_frames, STFT_FREQUENCY_BINS), dtype=np.float32
	)
	train_labels = np.empty(len(train_examples), dtype=np.int32)
	val_data = np.empty(
		(len(validation_examples), target_frames, STFT_FREQUENCY_BINS), dtype=np.float32
	)
	val_labels = np.empty(len(validation_examples), dtype=np.int32)

	def load_examples(
		examples: list[tuple[Path, int]], data: np.ndarray, output_labels: np.ndarray
	) -> tuple[np.ndarray, np.ndarray]:
		loaded_count = 0
		for path, class_label in examples:
			try:
				spectrogram, _ = decode_wav_file(path)
			except (OSError, ValueError, tf.errors.OpError) as error:
				warnings.warn(f"Skipping {path}: {error}", RuntimeWarning)
				continue
			data[loaded_count] = preprocess_spectrogram(spectrogram, target_frames)
			output_labels[loaded_count] = class_label
			loaded_count += 1
		return data[:loaded_count], output_labels[:loaded_count]

	train_data, train_labels = load_examples(train_examples, train_data, train_labels)
	val_data, val_labels = load_examples(validation_examples, val_data, val_labels)
	if set(train_labels.tolist()) != set(FOLDER_LABELS.values()) or set(
		val_labels.tolist()
	) != set(FOLDER_LABELS.values()):
		raise ValueError("Both classes must have valid WAV files in each split")
	return train_data, train_labels, val_data, val_labels


def train_model(model, train_data, train_labels, val_data, val_labels, epochs=10, batch_size=32):
	pass # Placeholder for training logic, to be implemented using Digital Ocean Gradient API


def main() -> None:
	train_data, train_labels, val_data, val_labels = prepare_dataset(dataset_dir)
	print(f"Training data: {train_data.shape}; labels: {train_labels.shape}")
	print(f"Validation data: {val_data.shape}; labels: {val_labels.shape}")
	for folder_name, class_label in FOLDER_LABELS.items():
		print(
			f"{folder_name}: train={np.count_nonzero(train_labels == class_label)}, "
			f"validation={np.count_nonzero(val_labels == class_label)}"
		)


if __name__ == "__main__":
	main()


