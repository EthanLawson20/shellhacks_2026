<h1 align="center">Phase — See Beyond the Horizon</h1>

<h4 align="left">
Phase is a network of microcontrollers that combines Wi-Fi sensing and audio analysis to help rescuers identify possible signs of life.
</h4>

Built in 36 hours at ShellHacks 2026 (FIU, Miami)

</p>

## Features

- CSI-based motion detection
- On-device audio classification
- Dynamic rescue priority list
- Real-time dashboard

## Network Architecture

<p align="center">
  <img src="docs/network_architecture.png" alt="Network Architecture">
</p>

1. **Sender** (connected to the computer) transmits packets continuously so nodes always have a signal to measure. A second sender can be added for more coverage.
2. **Nodes** capture CSI per packet and compute motion and breathing features. The onboard mic runs a small classifier and sends only the label and confidence. Each node also reports its battery level.
3. **Gateway** (connected to the computer) collects data from all nodes and passes it to the computer over [serial / USB — confirm].
4. **Fusion engine** on the computer combines CSI and audio per zone into a priority score.
5. **Dashboard** visualize detections and rescue priorities. 

## Tech Stack

| Layer | Technology |
|--------|------------|
| Hardware | ESP32 |
| RF Sensing | Espressif ESP-CSI |
| Audio AI | Edge Impulse / TensorFlow Lite Micro |
| Firmware | ESP-IDF |
| Backend | Python |
| Frontend | React |

---

## Project Structure


---

## Getting Started

### Hardware

- ESP32 Sender
- ESP32 Gateway
- Two or more ESP32 Sensor Nodes
- USB cables or power banks
- Laptop

### Flash Firmware

```bash
cd firmware/sender
idf.py build flash monitor
```

Repeat for gateway and sensor nodes.

### Start Backend

```bash
cd backend
pip install -r requirements.txt
python gateway.py
```

### Launch Dashboard

```bash
cd dashboard
npm install
npm run dev
```
---

## Use Cases

- Collapsed structure search and rescue
- Barricade and hostage situations: know where people are in a room before entry
- Firefighting: RF sensing works through smoke, where cameras can't see
- Disaster recovery

---

## Roadmap
- Drone-deployed nodes that are dropped into position to form the network automatically
- Mesh networking so nodes relay data through each other, extending range and removing the single point of failure
- Ruggedized, battery-powered nodes lasting a full operational period

---

## References

- https://github.com/espressif/esp-csi

