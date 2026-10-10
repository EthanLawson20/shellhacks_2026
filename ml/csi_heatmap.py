import argparse
import json
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
# feed_ok tracks whether the current feed is healthy, independent of the status text
# (which may name a serial port rather than the literal word "Connected").
feed_ok = False
# When reading from a live node, keep the firmware's own radar readings from the latest line.
serial_mode = False
node_m: float | None = None
node_p: float | None = None

# Attempt to poll the backend for new CSI packets at a regular interval, updating the processor with each new packet.
def poll_feed() -> None:
    global feed_status, update_rate, feed_ok
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
                feed_ok = True
        except Exception as error:
            with state_lock:
                feed_status = f"Feed error: {error}"
                feed_ok = False
        stop_polling.wait(poll_interval)

# Read CSI packets from a live node over USB serial. Each line is one JSON packet
# ({"csi":[...],"m":..,"p":..}); "csi" is renamed to the "csi_amplitude" key the
# processor expects, then passed to process_payload exactly like the HTTP payload.
def poll_serial_feed(port: str, baud: int) -> None:
    global feed_status, update_rate, feed_ok, node_m, node_p
    import serial  # lazy import so the default HTTP path doesn't require pyserial

    while not stop_polling.is_set():
        # Retry opening the port every 2 seconds so the viewer can start before the board is plugged in.
        try:
            connection = serial.Serial(port, baud, timeout=1.0)
        except Exception as error:
            with state_lock:
                feed_status = f"Waiting for {port} ({error})"
                feed_ok = False
            stop_polling.wait(2.0)
            continue

        with state_lock:
            feed_status = f"Reading {port} @ {baud} baud"
            feed_ok = True

        # Track observed lines/s over a rolling one-second window to catch dropped or truncated lines.
        line_count = 0
        window_start = time.monotonic()
        try:
            with connection:
                while not stop_polling.is_set():
                    raw = connection.readline()
                    if not raw:
                        continue  # readline timeout with no data

                    # Lines that fail to parse (partial writes, boot garbage after a
                    # reset) are skipped silently rather than killing the reader thread.
                    try:
                        text = raw.decode("utf-8").strip()
                        if not text:
                            continue
                        payload = json.loads(text)
                        if not isinstance(payload, dict) or "csi" not in payload:
                            continue
                        payload["csi_amplitude"] = payload.pop("csi")
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        continue

                    try:
                        with state_lock:
                            accepted = processor.process_payload(payload)
                            node_m = payload.get("m")
                            node_p = payload.get("p")
                            feed_ok = True
                    except Exception:
                        continue  # malformed amplitudes; skip without dropping the reader

                    line_count += 1
                    elapsed = time.monotonic() - window_start
                    if elapsed >= 1.0:
                        lines_per_second = line_count / elapsed
                        with state_lock:
                            update_rate = lines_per_second
                        if lines_per_second < 10:
                            print(
                                f"WARNING: serial feed at {lines_per_second:.1f} lines/s "
                                f"(<10) on {port}; dropped or truncated lines likely."
                            )
                        line_count = 0
                        window_start = time.monotonic()
        except Exception as error:
            with state_lock:
                feed_status = f"Serial error on {port}: {error}"
                feed_ok = False
            stop_polling.wait(2.0)

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
            status.set_color("#8b949e")
            return
        calibrated = processor.calibrated
        calibration_progress = processor.calibration_progress
        processed_samples = processor.processed_samples
        score = processor.current_score
        values = processor.heatmap()
        subcarrier_count = processor.subcarrier_count
        current_status = feed_status
        current_rate = update_rate
        current_feed_ok = feed_ok
        current_node_m = node_m
        current_node_p = node_p

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

    # Display current status about the feed. The status text names the active feed
    # (a serial port, or "Connected" for the HTTP feed); feed_ok drives the color.
    status.set_text(current_status.upper())
    status.set_color("#3fb950" if current_feed_ok else "#f85149")

    score_state = (
        "CHANGE ABOVE THRESHOLD"
        if score >= change_threshold
        else "WITHIN THRESHOLD"
    )
    detail_text = (
        f"{baseline_label}  |  CSI samples: {processed_samples}  |  "
        f"Client ingest: {current_rate:.1f} CSI samples/s\n"
        f"Mean deviation: {score:.2f}  |  {score_state} ({change_threshold:.2f})  |  "
        f"Median filter: {median_window}  |  EMA alpha: {smoothing_alpha:.2f}"
    )
    # In serial mode, show the node's own radar readings (m, p) alongside this app's
    # score. They come from different engines (firmware radar vs CSIHeatmapProcessor),
    # so they're two separate numbers and are not expected to agree.
    if serial_mode:
        node_m_text = "n/a" if current_node_m is None else f"{current_node_m:.3f}"
        node_p_text = "n/a" if current_node_p is None else f"{current_node_p}"
        detail_text += (
            f"\nNode radar (firmware) m: {node_m_text}  |  p: {node_p_text}"
            f"   vs   this app's score: {score:.2f}"
        )
    details.set_text(detail_text)

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
    global pause_button, serial_mode
    parser = argparse.ArgumentParser(
        description="CSI heatmap visualizer. Reads from the Railway HTTP feed by "
        "default, or from a live node over USB serial when --serial is given."
    )
    parser.add_argument(
        "--serial",
        metavar="COMx",
        default=None,
        help="Serial port of a node flashed with SIGNAL_VIEW (e.g. COM3). "
        "When omitted, the Railway HTTP feed is used.",
    )
    parser.add_argument(
        "--baud",
        type=int,
        default=115200,
        help="Serial baud rate (default: 115200).",
    )
    args = parser.parse_args()

    if poll_interval <= 0:
        raise ValueError("RAILWAY_POLL_INTERVAL must be greater than zero.")
    if not 0 <= change_threshold <= 1:
        raise ValueError("CSI_CHANGE_THRESHOLD must be between 0 and 1.")

    # Dark theme: quiet room reads as a near-black field, deviation as bright color.
    background = "#0d1117"
    text_color = "#c9d1d9"
    muted_text = "#8b949e"

    figure, axes = plt.subplots(figsize=(11, 7))
    figure.subplots_adjust(bottom=0.30, top=0.88)
    figure.patch.set_facecolor(background)
    axes.set_facecolor(background)
    axes.set_title("CSI Environmental Change", fontsize=16, color=text_color, pad=14)
    axes.set_xlabel("Recent CSI packets (older to newer)", color=muted_text)
    axes.set_ylabel("CSI subcarrier index", color=muted_text)
    axes.set_xlim(0, history_samples)
    axes.set_xticks(np.linspace(0, history_samples, 5, dtype=int))
    axes.tick_params(colors=muted_text, labelsize=9)
    axes.grid(False)

    # Thin, subtle frame instead of a heavy black border.
    for spine in axes.spines.values():
        spine.set_color("#30363d")
        spine.set_linewidth(0.6)

    # Inverted colormap: 0 (quiet) is near-black and recessive, 1 (strongest
    # deviation) is bright yellow, so a person walking through reads as a bright streak.
    gradient = LinearSegmentedColormap.from_list(
        "csi_environmental_change",
        [
            (0.0, "#0d1117"),
            (0.25, "#1f4a5c"),
            (0.5, "#2d9c8f"),
            (0.75, "#7dd87a"),
            (1.0, "#fcd34d"),
        ],
    )
    gradient.set_bad(background)
    image = axes.imshow(
        np.full((1, history_samples), np.nan),
        origin="lower",
        aspect="auto",
        extent=(0, history_samples, 0, 1),
        cmap=gradient,
        vmin=0,
        vmax=1,
        interpolation="nearest",
        resample=False,
    )
    status = axes.text(
        0.99,
        1.04,
        "WAITING FOR CSI FEED",
        transform=axes.transAxes,
        ha="right",
        va="bottom",
        color="#f0883e",
        fontweight="bold",
    )
    details = figure.text(
        0.12,
        0.13,
        "",
        color=text_color,
        fontsize=10,
        family="monospace",
        linespacing=1.8,
        va="center",
    )
    colorbar = figure.colorbar(
        image, ax=axes, orientation="horizontal", pad=0.20, fraction=0.035, aspect=45
    )
    colorbar.set_ticks([0, 0.25, 0.5, 0.75, 1])
    colorbar.set_ticklabels(
        ["Clear", "Small change", "Moderate", "Strong", "Largest deviation"]
    )
    colorbar.ax.tick_params(colors=muted_text, labelsize=8, length=2)
    colorbar.set_label(
        "CSI change from calibrated baseline", color=muted_text, fontsize=9
    )
    colorbar.outline.set_edgecolor("#30363d")
    colorbar.outline.set_linewidth(0.6)

    # Buttons pulled in from the bottom-right corner and styled for the dark theme.
    pause_axes = figure.add_axes([0.55, 0.05, 0.12, 0.055])
    recalibrate_axes = figure.add_axes([0.69, 0.05, 0.16, 0.055])
    pause_button = Button(
        pause_axes, "Pause", color="#21262d", hovercolor="#30363d"
    )
    recalibrate_button = Button(
        recalibrate_axes, "Recalibrate", color="#21262d", hovercolor="#30363d"
    )
    for button, button_axes in (
        (pause_button, pause_axes),
        (recalibrate_button, recalibrate_axes),
    ):
        button.label.set_color(text_color)
        button.label.set_fontsize(10)
        for spine in button_axes.spines.values():
            spine.set_color("#30363d")
            spine.set_linewidth(0.6)
    pause_button.on_clicked(toggle_pause)
    recalibrate_button.on_clicked(recalibrate)

    if args.serial:
        serial_mode = True
        poller = threading.Thread(
            target=poll_serial_feed, args=(args.serial, args.baud), daemon=True
        )
    else:
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