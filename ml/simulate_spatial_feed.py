import json
import math
import os
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

"""
Test script to simulate a spatial CSI feed where a hand moves in and out of the signal path between two nodes.

Use to verify the spatial visualizer and heatmap display without requiring a live ESP32 feed.
The simulation uses a sample CSI layout from spatial_csi_sample.json, which defines the positions of
the nodes and the baseline amplitudes for each link. The hand is simulated to move in a repeating pattern,
affecting the CSI amplitudes based on its distance from the signal path.
"""
SAMPLE_PATH = Path(__file__).resolve().parent.parent / "data" / "spatial_csi_sample.json"
SAMPLE_RATE_HZ = 10
HAND_RADIUS_M = 0.35
HAND_CLEAR_OFFSET_M = 1.1
HAND_CYCLE_SECONDS = 10.0


def simulated_hand_offset(elapsed_seconds: float) -> tuple[float, str]:
    phase = elapsed_seconds % HAND_CYCLE_SECONDS
    if phase < 2.0:
        return HAND_CLEAR_OFFSET_M, "clear"
    if phase < 3.0:
        progress = phase - 2.0
        eased_progress = progress * progress * (3 - 2 * progress)
        return HAND_CLEAR_OFFSET_M * (1 - eased_progress), "approaching path"
    if phase < 5.0:
        return 0.0, "hand in signal path"
    if phase < 6.0:
        progress = phase - 5.0
        eased_progress = progress * progress * (3 - 2 * progress)
        return HAND_CLEAR_OFFSET_M * eased_progress, "withdrawing"
    return HAND_CLEAR_OFFSET_M, "clear"


def point_to_segment_distance(
    point_x: float,
    point_y: float,
    start_x: float,
    start_y: float,
    end_x: float,
    end_y: float,
) -> float:
    delta_x = end_x - start_x
    delta_y = end_y - start_y
    length_squared = delta_x * delta_x + delta_y * delta_y
    if length_squared == 0:
        return math.hypot(point_x - start_x, point_y - start_y)

    projection = (
        (point_x - start_x) * delta_x + (point_y - start_y) * delta_y
    ) / length_squared
    projection = min(1.0, max(0.0, projection))
    closest_x = start_x + projection * delta_x
    closest_y = start_y + projection * delta_y
    return math.hypot(point_x - closest_x, point_y - closest_y)


def make_packet(elapsed_seconds: float, sample: dict) -> dict:
    nodes = {node["id"]: node for node in sample["nodes"]}
    links = sample["links"]
    selected_link_id = os.environ.get("CSI_CROSS_SECTION_LINK", links[0]["id"])
    selected_link = next(
        (link for link in links if link["id"] == selected_link_id), None
    )
    if selected_link is None:
        raise ValueError(f"CSI link '{selected_link_id}' is not present in the sample layout.")

    tx = nodes[selected_link["tx"]]
    rx = nodes[selected_link["rx"]]
    delta_x = float(rx["x_m"]) - float(tx["x_m"])
    delta_y = float(rx["y_m"]) - float(tx["y_m"])
    path_length = math.hypot(delta_x, delta_y)
    if path_length <= 0:
        raise ValueError(f"CSI link '{selected_link_id}' has zero path length.")

    hand_offset, hand_state = simulated_hand_offset(elapsed_seconds)
    hand_x = (float(tx["x_m"]) + float(rx["x_m"])) / 2 - delta_y / path_length * hand_offset
    hand_y = (float(tx["y_m"]) + float(rx["y_m"])) / 2 + delta_x / path_length * hand_offset
    packet = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "mode": "simulation",
        "demo_event": hand_state,
        "room": sample["room"],
        "nodes": sample["nodes"],
        "links": [],
    }

    for link in links:
        tx = nodes[link["tx"]]
        rx = nodes[link["rx"]]
        distance = point_to_segment_distance(
            hand_x,
            hand_y,
            tx["x_m"],
            tx["y_m"],
            rx["x_m"],
            rx["y_m"],
        )
        impact = math.exp(-0.5 * (distance / HAND_RADIUS_M) ** 2)
        baseline = link["baseline_amplitude"]
        current = [
            round(
                amplitude
                * max(
                    0.08,
                    1 - 0.82 * impact
                    + 0.035 * impact * math.sin(subcarrier * 1.7 + elapsed_seconds),
                ),
                5,
            )
            for subcarrier, amplitude in enumerate(baseline)
        ]
        packet["links"].append(
            {
                "id": link["id"],
                "tx": link["tx"],
                "rx": link["rx"],
                "baseline_amplitude": baseline,
                "current_amplitude": current,
            }
        )
    return packet


class SpatialFeedHandler(BaseHTTPRequestHandler):
    sample: dict = {}
    started_at = time.monotonic()

    def do_GET(self) -> None:
        if urlsplit(self.path).path != "/api/csi":
            self.send_error(404, "Use GET /api/csi")
            return

        packet = make_packet(time.monotonic() - self.started_at, self.sample)
        body = json.dumps(packet).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *_args: object) -> None:
        pass


def main() -> None:
    with SAMPLE_PATH.open(encoding="utf-8") as sample_file:
        sample = json.load(sample_file)

    selected_link_id = os.environ.get("CSI_CROSS_SECTION_LINK", sample["links"][0]["id"])
    if not any(link["id"] == selected_link_id for link in sample["links"]):
        raise ValueError(f"CSI link '{selected_link_id}' is not present in the sample layout.")
    os.environ["CSI_CROSS_SECTION_LINK"] = selected_link_id

    SpatialFeedHandler.sample = sample
    SpatialFeedHandler.started_at = time.monotonic()
    server = ThreadingHTTPServer(("127.0.0.1", 0), SpatialFeedHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    os.environ["RAILWAY_API_URL"] = f"http://127.0.0.1:{server.server_port}"
    os.environ["RAILWAY_DATA_ENDPOINT"] = "/api/csi"
    os.environ["RAILWAY_POLL_INTERVAL"] = str(1 / SAMPLE_RATE_HZ)

    print(
        f"Faux CSI feed for link {selected_link_id}: clear, approach, enter, "
        "hold, withdraw, repeat."
    )
    print("Close the map window to stop the local JSON feed.")
    try:
        import spatial_visualizer

        spatial_visualizer.main()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=1.0)


if __name__ == "__main__":
    main()