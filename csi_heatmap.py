import os
import threading
import time
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.animation import FuncAnimation
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.widgets import Button

from csi_processing import CSIHeatmapProcessor
from railway_client import fetch_latest

# Retrieve configuration params from environment variables, with defaults if not set.
baseline_samples = int(os.environ.get("CSI_BASELINE_SAMPLES", "40"))
deviation_scale = float(os.environ.get("CSI_DEVIATION_SCALE", "0.35"))
smoothing_alpha = float(os.environ.get("CSI_SMOOTHING_ALPHA", "0.4"))
median_window = int(os.environ.get("CSI_SUBCARRIER_MEDIAN_WINDOW", "3"))
history_samples = int(os.environ.get("CSI_HISTORY_SAMPLES", "160"))
noise_sigma = float(os.environ.get("CSI_NOISE_SIGMA", "3.0"))
relative_noise_floor = float(os.environ.get("CSI_RELATIVE_NOISE_FLOOR", "0.005"))
change_threshold = float(os.environ.get("CSI_CHANGE_THRESHOLD", "0.25"))
poll_interval = float(os.environ.get("RAILWAY_POLL_INTERVAL", "0.25"))

# Feed params into processing object that maintains the baseline, history, and computes the heatmap of scores.
processor = CSIHeatmapProcessor(
    baseline_samples=baseline_samples,
    deviation_scale=deviation_scale,
    smoothing_alpha=smoothing_alpha,
    median_window=median_window,
    history_samples=history_samples,
    noise_sigma=noise_sigma,
    relative_noise_floor=relative_noise_floor,
)

# Use a lock to protect shared state between the polling thread and the animation update thread.
state_lock = threading.Lock()
stop_polling = threading.Event()
feed_status = "Waiting for CSI feed..."
update_rate = 0.0
paused = False
pause_button: Any | None = None

# Attempt to poll the backend for new CSI packets at a regular interval, updating the processor with each new packet.
def poll_feed() -> None:
    global feed_status, update_rate
    while not stop_polling.is_set():
        started = time.monotonic()
        try:
            payload = fetch_latest(timeout=5.0)
            with state_lock:
                accepted = processor.process_payload(payload)
                update_rate = 0.8 * update_rate + 0.2 * accepted / max(
                    time.monotonic() - started, 1e-6
                )
                feed_status = "Connected"
        except Exception as error:
            with state_lock:
                feed_status = f"Feed error: {error}"
        stop_polling.wait(poll_interval)

# update the heatmap display with the latest data from the processor, including status and details.
def update_heatmap(
    _frame: int,
    image: Any,
    axes: Any,
    status: Any,
    details: Any,
) -> None:
    global paused
    # Use a lock to safely read the shared state from the polling thread and the processor.
    with state_lock:
        if paused:
            status.set_text("PAUSED | FEED STILL PROCESSING")
            status.set_color("#64748b")
            return
        calibrated = processor.calibrated
        calibration_progress = processor.calibration_progress
        processed_samples = processor.processed_samples
        score = processor.current_score
        values = processor.heatmap()
        subcarrier_count = processor.subcarrier_count
        current_status = feed_status
        current_rate = update_rate

    # if the processor is calibrated display the heatmap of scores, otherwise display a placeholder and show calibration progress.
    if calibrated:
        display = np.zeros((subcarrier_count, history_samples), dtype=float)
        if values.size:
            row_count = min(values.shape[1], history_samples)
            display[:, :row_count] = values[:, -row_count:]
        image.set_data(display)
        image.set_extent((0, history_samples, 0, subcarrier_count))
        axes.set_ylim(0, subcarrier_count)
        baseline_label = "BASELINE ESTABLISHED"
    else:
        image.set_data(np.full((1, history_samples), np.nan))
        image.set_extent((0, history_samples, 0, 1))
        axes.set_ylim(0, 1)
        baseline_label = f"CALIBRATING ENVIRONMENT  {calibration_progress}/{baseline_samples}"

    # Display current status and details about the feed
    if current_status != "Connected":
        status.set_text(current_status.upper())
        status.set_color("#c24136")
    elif paused:
        status.set_text("PAUSED | FEED STILL PROCESSING")
        status.set_color("#64748b")
    else:
        status.set_text("CONNECTED")
        status.set_color("#177e69")

    score_state = (
        "CHANGE ABOVE THRESHOLD"
        if score >= change_threshold
        else "WITHIN THRESHOLD"
    )
    details.set_text(
        f"{baseline_label}  |  CSI samples: {processed_samples}  |  "
        f"Client ingest: {current_rate:.1f} CSI samples/s\n"
        f"Mean deviation: {score:.2f}  |  {score_state} ({change_threshold:.2f})  |  "
        f"Median filter: {median_window}  |  EMA alpha: {smoothing_alpha:.2f}"
    )

# Handle pause/resume button click events
def toggle_pause(_event: Any) -> None:
    global paused
    with state_lock:
        paused = not paused
    if pause_button is not None:
        pause_button.label.set_text("Resume" if paused else "Pause")

# Handle the recalibrate button click events, resetting the processor to an uncalibrated state.
def recalibrate(_event: Any) -> None:
    global feed_status
    with state_lock:
        processor.reset_baseline()
        feed_status = "Calibrating environment... keep area clear"

# Demonstration entry point for the CSI heatmap visualizer. Sets up the matplotlib figure, axes, and buttons, starts the polling thread, and runs the animation loop.
def main() -> None:
    global pause_button
    if poll_interval <= 0:
        raise ValueError("RAILWAY_POLL_INTERVAL must be greater than zero.")
    if not 0 <= change_threshold <= 1:
        raise ValueError("CSI_CHANGE_THRESHOLD must be between 0 and 1.")

    figure, axes = plt.subplots(figsize=(11, 7))
    figure.subplots_adjust(bottom=0.27, top=0.88)
    figure.patch.set_facecolor("#f5f3ef")
    axes.set_facecolor("#202b36")
    axes.set_title("CSI Environmental Change", fontsize=16, color="#24323d")
    axes.set_xlabel("Recent CSI packets (older to newer)")
    axes.set_ylabel("CSI subcarrier index")
    axes.set_xlim(0, history_samples)
    axes.set_xticks(np.linspace(0, history_samples, 5, dtype=int))
    axes.grid(False)

    gradient = LinearSegmentedColormap.from_list(
        "csi_environmental_change",
        [
            (0.0, "#F97316"),
            (0.25, "#FDBA4A"),
            (0.5, "#84CC16"),
            (0.75, "#14B8A6"),
            (1.0, "#64748B"),
        ],
    )
    gradient.set_bad("#202b36")
    image = axes.imshow(
        np.full((1, history_samples), np.nan),
        origin="lower",
        aspect="auto",
        extent=(0, history_samples, 0, 1),
        cmap=gradient,
        vmin=0,
        vmax=1,
        interpolation="bilinear",
        resample=False,
    )
    status = axes.text(
        0.99,
        1.04,
        "WAITING FOR CSI FEED",
        transform=axes.transAxes,
        ha="right",
        va="bottom",
        color="#c24136",
        fontweight="bold",
    )
    details = figure.text(0.12, 0.16, "", color="#34434f", fontsize=10)
    colorbar = figure.colorbar(image, ax=axes, orientation="horizontal", pad=0.22)
    colorbar.set_ticks([0, 0.25, 0.5, 0.75, 1])
    colorbar.set_ticklabels(
        ["Clear", "Small change", "Moderate", "Strong", "Largest deviation"]
    )
    colorbar.set_label("CSI change from calibrated baseline")

    pause_axes = figure.add_axes([0.68, 0.045, 0.12, 0.06])
    recalibrate_axes = figure.add_axes([0.82, 0.045, 0.16, 0.06])
    pause_button = Button(pause_axes, "Pause")
    recalibrate_button = Button(recalibrate_axes, "Recalibrate")
    pause_button.on_clicked(toggle_pause)
    recalibrate_button.on_clicked(recalibrate)

    poller = threading.Thread(target=poll_feed, daemon=True)
    poller.start()
    figure.canvas.mpl_connect("close_event", lambda _event: stop_polling.set())
    animation = FuncAnimation(
        figure,
        update_heatmap,
        fargs=(image, axes, status, details),
        interval=100,
        cache_frame_data=False,
    )
    plt.show()
    stop_polling.set()
    poller.join(timeout=1.0)


if __name__ == "__main__":
    main()