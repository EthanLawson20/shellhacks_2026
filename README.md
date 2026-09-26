<h1 align="center">Phase — See Beyond the Horizon</h1>

<p align="left">
A low-cost ESP32 sensor network that combines WiFi Channel State Information (CSI) and on-device AI audio classification to help rescuers prioritize where to search first.
</p>

🏆 Built in 36 hours at ShellHacks 2026 (FIU, Miami)

</p>

---

## What is Phase

Several ESP32 sensing nodes are deployed around a collapsed structure or damaged building.

Each node:

1. Detects motion and barriers using WiFi CSI.
2. ***Performs on-device audio classification to distinguish human sounds from environmental noise.***
3. ***Sends only processed information to a central gateway. Raw audio never leaves the device.***

***The fusion engine combines both sensing modalities to estimate the likelihood of human presence and continuously updates a live rescue dashboard.***

---

## ✨ Features

- 📡 CSI-based motion detection
- 🫁 Breathing frequency analysis
- 🔊 On-device audio classification
- 🧠 Multi-sensor fusion
- 🗺️ Blueprint overlay
- 📋 Dynamic rescue priority list
- 🔋 Battery monitoring
- 📈 Real-time dashboard

---

## Network Architecture

<p align="center">
  <img src="docs/network_architecture.png" alt="Network Architecture">
</p>

1. **Sender** (connected to the computer) transmits packets continuously so nodes always have a signal to measure. A second sender can be added for more coverage.
2. **Nodes** capture CSI per packet and compute motion and breathing features. The onboard mic runs a small classifier and sends only the label and confidence. Each node also reports its battery level.
3. **Gateway** (connected to the computer) collects data from all nodes and passes it to the computer over [serial / USB — confirm].
4. **Fusion engine** on the computer combines CSI and audio per zone into a priority score.
5. **Dashboard** visualize detections and rescue priorities. 

---

## 🛠️ Tech Stack

| Layer | Technology |
|--------|------------|
| Hardware | ESP32 |
| RF Sensing | Espressif ESP-CSI |
| Audio AI | Edge Impulse / TensorFlow Lite Micro |
| Firmware | ESP-IDF |
| Backend | Python |
| Frontend | React |

---

## 📂 Project Structure

```text
Phase/
├── firmware/
│   ├── sender/
│   ├── node/
│   └── gateway/
├── backend/
├── frontend/
├── docs/
└── README.md
```

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
- **Drone-deployed nodes** that are dropped into position to form the network automatically
- **Mesh networking** so nodes relay data through each other, extending range and removing the single point of failure
- Ruggedized, battery-powered nodes lasting a full operational period

---

## References

- https://github.com/espressif/esp-csi

