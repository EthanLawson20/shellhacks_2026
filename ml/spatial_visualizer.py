import math
import os
import threading
import time
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.animation import FuncAnimation
from matplotlib.colors import LinearSegmentedColormap

from railway_client import fetch_latest

PATH_SAMPLES = 180
OFFSET_SAMPLES = 100
MAX_OFFSET_M = 1.25
LINK_SPREAD_M = 0.42
POLL_INTERVAL = float(os.environ.get("RAILWAY_POLL_INTERVAL", "0.25"))
CROSS_SECTION_LINK_ID = os.environ.get("CSI_CROSS_SECTION_LINK")

lock = threading.Lock()
stop_polling = threading.Event()
latest_packet: dict[str, Any] | None = None
last_error = "Waiting for CSI feed..."


def build_path_cross_section(
    packet: dict[str, Any],
    link_id: str | None = CROSS_SECTION_LINK_ID,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict[str, Any], float]:
    nodes = {node["id"]: node for node in packet["nodes"]}
    links = packet["links"]
    if not links:
        raise ValueError("CSI feed contains no links.")
    if link_id is None:
        link = links[0]
    else:
        link = next((candidate for candidate in links if candidate["id"] == link_id), None)
        if link is None:
            raise ValueError(f"CSI link '{link_id}' is not present in the feed.")

    baseline = np.asarray(link["baseline_amplitude"], dtype=float)
    current = np.asarray(link["current_amplitude"], dtype=float)
    if baseline.ndim != 1 or baseline.size == 0 or baseline.shape != current.shape:
        raise ValueError(f"CSI link '{link['id']}' has invalid amplitude arrays.")
    finite = np.isfinite(baseline) & np.isfinite(current)
    if not finite.any():
        raise ValueError(f"CSI link '{link['id']}' has no finite subcarrier values.")

    baseline = baseline[finite]
    current = current[finite]
    relative_change = np.abs(current - baseline) / np.maximum(np.abs(baseline), 1e-8)
    link_score = float(np.clip(np.median(relative_change) / 0.82, 0, 1))

    tx = nodes[link["tx"]]
    rx = nodes[link["rx"]]
    path_length = math.hypot(
        float(rx["x_m"]) - float(tx["x_m"]),
        float(rx["y_m"]) - float(tx["y_m"]),
    )
    if path_length <= 0:
        raise ValueError(f"CSI link '{link['id']}' has zero path length.")

    distance_along_path = np.linspace(0, path_length, PATH_SAMPLES)
    offset_from_path = np.linspace(-MAX_OFFSET_M, MAX_OFFSET_M, OFFSET_SAMPLES)
    cross_track_profile = np.exp(-0.5 * (offset_from_path / LINK_SPREAD_M) ** 2)
    cross_section = np.repeat(
        (link_score * cross_track_profile)[:, np.newaxis], PATH_SAMPLES, axis=1
    )
    return distance_along_path, offset_from_path, cross_section, link, link_score


def poll_feed() -> None:
    global latest_packet, last_error
    while not stop_polling.is_set():
        try:
            packet = fetch_latest(timeout=5.0)
            if not isinstance(packet, dict) or not packet.get("links"):
                raise ValueError("CSI feed must contain room, nodes, and links.")
            build_path_cross_section(packet)
            with lock:
                latest_packet = packet
                last_error = "Connected"
        except Exception as error:
            with lock:
                last_error = f"Feed interrupted: {error}"
        stop_polling.wait(POLL_INTERVAL)


def update_cross_section(
    _frame: int,
    image: Any,
    axes: Any,
    status: Any,
    overlays: dict[str, Any],
) -> None:
    with lock:
        packet = latest_packet
        message = last_error
    if packet is None:
        status.set_text(message.upper())
        status.set_color("#bd3f4a")
        return

    distance_along_path, offset_from_path, cross_section, link, link_score = (
        build_path_cross_section(packet)
    )
    nodes = {node["id"]: node for node in packet["nodes"]}
    tx = nodes[link["tx"]]
    rx = nodes[link["rx"]]
    image.set_data(cross_section)
    image.set_extent(
        (
            float(distance_along_path[0]),
            float(distance_along_path[-1]),
            float(offset_from_path[0]),
            float(offset_from_path[-1]),
        )
    )
    axes.set_xlim(0, float(distance_along_path[-1]))
    axes.set_ylim(float(offset_from_path[0]), float(offset_from_path[-1]))
    axes.set_title(f"CSI signal-path cross-section | {link['id']}")

    overlays["path"].set_data([0, distance_along_path[-1]], [0, 0])
    overlays["tx"].set_data([0], [0])
    overlays["rx"].set_data([distance_along_path[-1]], [0])
    overlays["tx_label"].set_position((0, 0.09))
    overlays["tx_label"].set_text(f"TX {link['tx']}")
    overlays["rx_label"].set_position((distance_along_path[-1], 0.09))
    overlays["rx_label"].set_text(f"RX {link['rx']}")

    mode_label = "SIMULATED CSI" if packet.get("mode") == "simulation" else "LIVE CSI"
    connected = message == "Connected"
    status_text = "CONNECTED" if connected else "FEED INTERRUPTED"
    demo_event = packet.get("demo_event")
    event_text = f" | {demo_event}" if demo_event else ""
    status.set_text(
        f"{mode_label} | {link['id']} change {link_score:.2f}"
        f"{event_text} | {status_text}"
    )
    status.set_color("#64e6ad" if connected else "#ff7777")


def main() -> None:
    if POLL_INTERVAL <= 0:
        raise ValueError("RAILWAY_POLL_INTERVAL must be greater than zero.")

    figure, axes = plt.subplots(figsize=(11, 6))
    figure.patch.set_facecolor("#081525")
    axes.set_facecolor("#081525")
    axes.set_xlabel("Distance from TX along signal path (m)", color="white")
    axes.set_ylabel("Offset from direct path (m)", color="white")
    axes.tick_params(colors="white")
    axes.grid(color="white", alpha=0.1)
    colors = LinearSegmentedColormap.from_list(
        "clear_to_disturbed_csi",
        ["#F97316", "#FDBA4A", "#84CC16", "#14B8A6", "#64748B"],
    )
    image = axes.imshow(
        np.zeros((OFFSET_SAMPLES, PATH_SAMPLES)),
        origin="lower",
        extent=(0, 1, -MAX_OFFSET_M, MAX_OFFSET_M),
        cmap=colors,
        vmin=0,
        vmax=1,
        interpolation="bilinear",
        zorder=1,
    )
    colorbar = figure.colorbar(image, ax=axes, fraction=0.046, pad=0.04)
    colorbar.set_label("CSI change from baseline (0 = clear, 1 = strong change)", color="white")
    colorbar.ax.tick_params(colors="white")
    status = axes.text(
        0.02,
        0.98,
        "WAITING FOR CSI FEED",
        transform=axes.transAxes,
        va="top",
        color="#ff7777",
        fontweight="bold",
    )
    (path_line,) = axes.plot([], [], color="white", linestyle="--", linewidth=1, alpha=0.8)
    (tx_marker,) = axes.plot([], [], marker="^", color="white", markersize=9, linestyle="None")
    (rx_marker,) = axes.plot([], [], marker="s", color="white", markersize=8, linestyle="None")
    tx_label = axes.text(0, 0, "", color="white", ha="left", va="bottom", fontweight="bold")
    rx_label = axes.text(0, 0, "", color="white", ha="right", va="bottom", fontweight="bold")
    figure.text(
        0.5,
        0.015,
        "Link-level CSI provides no position along the path; the band shows path corridor change, not object location.",
        ha="center",
        color="#d3dbe4",
        fontsize=9,
    )
    overlays = {
        "path": path_line,
        "tx": tx_marker,
        "rx": rx_marker,
        "tx_label": tx_label,
        "rx_label": rx_label,
    }
    poller = threading.Thread(target=poll_feed, daemon=True)
    poller.start()
    figure.canvas.mpl_connect("close_event", lambda _event: stop_polling.set())
    animation = FuncAnimation(
        figure,
        update_cross_section,
        fargs=(image, axes, status, overlays),
        interval=100,
        cache_frame_data=False,
    )
    plt.show()
    stop_polling.set()
    poller.join(timeout=1.0)


if __name__ == "__main__":
    main()