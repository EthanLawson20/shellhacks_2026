from collections import deque
from typing import Any

import numpy as np

# Get CSI amplitude matrix from a JSON payload, validating the shape and values.
def _amplitude_matrix(payload: Any) -> np.ndarray:
    if isinstance(payload, dict) and "data" in payload:
        payload = payload["data"]

    if isinstance(payload, dict) and "samples" in payload:
        samples = payload["samples"]
        if samples and isinstance(samples[0], dict):
            rows = [_extract_amplitudes(sample) for sample in samples]
            return _validated_matrix(rows)
        payload = samples
    elif isinstance(payload, dict):
        return _validated_matrix([_extract_amplitudes(payload)])

    return _validated_matrix(payload)


# If amplitude is in the payload, return it. If real and imaginary are present, compute amplitude.
def _extract_amplitudes(payload: Any) -> Any:
    if not isinstance(payload, dict):
        return payload

    csi = payload.get("csi", payload)
    if isinstance(csi, dict):
        if "amplitude" in csi:
            return csi["amplitude"]
        if "real" in csi and "imag" in csi:
            real = np.asarray(csi["real"], dtype=float)
            imaginary = np.asarray(csi["imag"], dtype=float)
            if real.shape != imaginary.shape:
                raise ValueError("CSI real and imaginary arrays must have equal lengths.")
            return np.hypot(real, imaginary)

    for key in ("csi_amplitude", "amplitude"):
        if key in payload:
            return payload[key]
    raise ValueError(
        "CSI JSON must include csi_amplitude, csi.amplitude, or csi real/imag arrays."
    )

# Validate that the values are a 1D or 2D array of finite, nonnegative numbers.
def _validated_matrix(values: Any) -> np.ndarray:
    try:
        matrix = np.asarray(values, dtype=float)
    except (TypeError, ValueError) as error:
        raise ValueError("CSI amplitudes must be numeric arrays.") from error

    if matrix.ndim == 1:
        matrix = matrix[np.newaxis, :]
    if matrix.ndim != 2 or matrix.shape[1] == 0:
        raise ValueError("CSI amplitudes must be a subcarrier vector or sample matrix.")
    if not np.isfinite(matrix).all() or np.any(matrix < 0):
        raise ValueError("CSI amplitudes must be finite, nonnegative values.")
    if matrix.shape[0] == 0:
        raise ValueError("CSI feed contained no samples.")
    return matrix

# class to process CSI amplitude samples into a heatmap, with baseline calibration and noise filtering.
class CSIHeatmapProcessor:
    def __init__(
        self,
        baseline_samples: int = 40,
        deviation_scale: float = 0.35,
        smoothing_alpha: float = 0.4,
        median_window: int = 3,
        history_samples: int = 160,
        noise_sigma: float = 3.0,
        relative_noise_floor: float = 0.005,
    ) -> None:
        if baseline_samples < 1:
            raise ValueError("Baseline sample count must be at least one.")
        if deviation_scale <= 0:
            raise ValueError("Deviation scale must be greater than zero.")
        if not 0 < smoothing_alpha <= 1:
            raise ValueError("Smoothing alpha must be in the interval (0, 1].")
        if median_window < 1 or median_window % 2 == 0:
            raise ValueError("Median window must be a positive odd number.")
        if history_samples < 1:
            raise ValueError("History length must be at least one sample.")
        if noise_sigma < 0 or relative_noise_floor < 0:
            raise ValueError("Noise filtering settings cannot be negative.")

        self.baseline_samples = baseline_samples # The number of initial samples to use for baseline calibration.
        self.deviation_scale = deviation_scale # The scale factor for converting relative deviation to a score in [0, 1].
        self.smoothing_alpha = smoothing_alpha # The alpha parameter for exponential smoothing of scores, in (0, 1].
        self.median_window = median_window # The size of the median filter window for smoothing scores, must be a positive odd integer. 
        self.history_samples = history_samples # The number of recent samples to retain in the heatmap history, forming the columns of the heatmap.
        self.noise_sigma = noise_sigma # The number of standard deviations above the baseline noise to consider as significant deviation, for noise filtering.
        self.relative_noise_floor = relative_noise_floor # The minimum relative amplitude (as a fraction of the baseline) to consider as significant deviation, for noise filtering.
        self._calibration_rows: list[np.ndarray] = [] # The list of samples collected during baseline calibration, used to compute the median baseline amplitude vector.
        self.baseline: np.ndarray | None = None # The baseline amplitude vector, computed from the median of calibration samples.
        self.baseline_noise: np.ndarray | None = None # The baseline noise vector, computed from the median absolute deviation of calibration samples, scaled to estimate standard deviation.
        self.history: deque[np.ndarray] = deque(maxlen=history_samples) # The deque of recent scored samples, each a vector of scores for each subcarrier, forming the heatmap columns.
        self.processed_samples = 0 # The total number of samples processed by the processor, including calibration and scored samples.
        self._smoothed_scores: np.ndarray | None = None # The current smoothed score vector, updated with each new sample using exponential smoothing, used for the heatmap display.

    # Check methods to determine if the processor is calibrated, and progress of calibration,
    # current score, and number of subcarriers.
    @property
    def calibrated(self) -> bool:
        return self.baseline is not None

    @property
    def calibration_progress(self) -> int:
        return len(self._calibration_rows)

    @property
    def current_score(self) -> float:
        if not self.history:
            return 0.0
        return float(np.mean(self.history[-1]))

    @property
    def subcarrier_count(self) -> int:
        if self.baseline is None:
            return 0
        return int(self.baseline.size)

    # Return the current heatmap as a 2D array of scores, with subcarriers as rows and recent samples as columns.
    def get_heatmap(self) -> np.ndarray:
        if not self.history:
            return np.array([]).reshape(0, 0)
        return np.stack(list(self.history))

    # Reset the processor to an uncalibrated state, clearing history and baseline.
    def reset_baseline(self) -> None:
        self._calibration_rows.clear()
        self.baseline = None
        self.baseline_noise = None
        self.history.clear()
        self._smoothed_scores = None

    # Process a payload of CSI amplitude samples, updating the baseline if needed,
    # and returning the number of accepted samples.
    def process_payload(self, payload: Any) -> int:
        samples = _amplitude_matrix(payload)
        accepted = 0

        # Process each sample, updating the baseline if not yet calibrated, and scoring samples if calibrated.
        for sample in samples:
            if self.baseline is None:
                if self._calibration_rows and sample.size != self._calibration_rows[0].size:
                    raise ValueError("CSI subcarrier count changed during calibration.")
                self._calibration_rows.append(sample.copy())
                self.processed_samples += 1
                accepted += 1
                if len(self._calibration_rows) >= self.baseline_samples:
                    calibration = np.stack(self._calibration_rows)
                    self.baseline = np.median(calibration, axis=0)
                    self.baseline_noise = np.median(
                        np.abs(calibration - self.baseline), axis=0
                    ) * 1.4826
                    self._calibration_rows.clear()
                continue

            if sample.size != self.baseline.size:
                raise ValueError(
                    "CSI subcarrier count changed after calibration; recalibrate "
                    "with a stable CSI configuration."
                )

            self.history.append(self._score_sample(sample))
            self.processed_samples += 1
            accepted += 1

        return accepted

    # Score a single sample against the baseline, applying noise filtering, relative deviation scaling, median filtering, and exponential smoothing.
    def _score_sample(self, sample: np.ndarray) -> np.ndarray:
        assert self.baseline is not None
        assert self.baseline_noise is not None
        noise_floor = np.maximum(
            self.noise_sigma * self.baseline_noise,
            np.maximum(np.abs(self.baseline) * self.relative_noise_floor, 1e-8),
        )

        # Apply relative deviation scoring. Convert each deviation from the baseline into a score in [0, 1]
        deviation = np.maximum(np.abs(sample - self.baseline) - noise_floor, 0)
        relative_deviation = deviation / np.maximum(np.abs(self.baseline), 1e-8)
        raw_scores = np.clip(relative_deviation / self.deviation_scale, 0, 1)

        # apply median filtering if requested. Takes the median of a sliding window of scores to reduce noise spikes.
        if self.median_window > 1:
            radius = self.median_window // 2
            padded = np.pad(raw_scores, (radius, radius), mode="edge")
            windows = np.lib.stride_tricks.sliding_window_view(
                padded, self.median_window
            )
            raw_scores = np.median(windows, axis=1)

        # apply exponential smoothing. Causes heatmap to respond more slowly to sudden changes, reducing flicker.
        if self._smoothed_scores is None:
            self._smoothed_scores = raw_scores
        else:
            self._smoothed_scores = (
                self.smoothing_alpha * raw_scores
                + (1 - self.smoothing_alpha) * self._smoothed_scores
            )
        return self._smoothed_scores.copy()

    # Return the current heatmap as a 2D array of scores, with subcarriers as rows and recent samples as columns.
    def heatmap(self) -> np.ndarray:
        if not self.history:
            return np.empty((self.subcarrier_count, 0), dtype=float)
        return np.stack(self.history, axis=0).T