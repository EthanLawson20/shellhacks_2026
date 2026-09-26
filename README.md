<p align="center">
  <img src="docs/banner.png" alt="Phase Banner" width="100%">
</p>

<h1 align="center">Phase — See Beyond the Horizon</h1>

<p align="center">
A low-cost ESP32 sensor network that combines <strong>WiFi Channel State Information (CSI)</strong> and <strong>on-device AI audio classification</strong> to help rescuers prioritize where to search first.
</p>

<p align="center">

🏆 Built in 36 hours at <strong>ShellHacks 2026</strong> (FIU, Miami)

</p>

---

## 🎥 Demo

> **Coming Soon**
>
> Add a GIF or YouTube demo here.

---

## 🚀 At a Glance

- 📡 WiFi CSI motion detection
- 🫁 Breathing-band sensing
- 🔊 Edge AI audio classification
- 🧠 Multi-sensor fusion
- 🗺️ Live blueprint visualization
- 📋 Ranked rescue priorities
- 💰 Built with low-cost ESP32 hardware

---

## The Challenge

In disaster response, every minute matters.

Traditional listening devices cannot reliably distinguish survivors from environmental noise, and they cannot detect unconscious victims who are breathing but unable to call for help.

Specialized breathing radars exist but are expensive and typically scan only one location at a time.

Phase explores whether a network of inexpensive ESP32 devices can continuously monitor multiple zones simultaneously and provide rescuers with a prioritized search map.

---

## Our Solution

Several ESP32 sensing nodes are deployed around a collapsed structure or damaged building.

Each node:

1. Detects motion and breathing using WiFi CSI.
2. Performs on-device audio classification to distinguish human sounds from environmental noise.
3. Sends only processed information to a central gateway. Raw audio never leaves the device.

The fusion engine combines both sensing modalities to estimate the likelihood of human presence and continuously updates a live rescue dashboard.

> [!NOTE]
> Phase is intended to **assist** search-and-rescue teams. It does **not** replace trained responders, rescue dogs, cameras, or specialized radar systems.

---

## Why Sensor Fusion Matters

| Detection | Priority | Interpretation |
|------------|----------|----------------|
| CSI breathing + no human sound | **P1 – Critical** | Possible unconscious survivor |
| CSI + voice/tapping | **P1 – High Confidence** | Responsive survivor |
| CSI only or human sound only | **P2 – Probable** | Verify with another tool |
| Single transient event | **P3 – Low** | Monitor |
| No detection | No signal | Never interpreted as "clear" |

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

## 🏗️ Network Architecture

<p align="center">
  <img src="docs/network_architecture.png" alt="Network Architecture">
</p>

The system follows a **star topology**.

1. A sender ESP32 continuously transmits WiFi packets.
2. Sensor nodes capture CSI and classify nearby sounds.
3. A gateway receives summarized data.
4. The fusion engine combines evidence.
5. The dashboard visualizes detections and rescue priorities.

---

## 🖥️ Dashboard

<p align="center">
  <img src="docs/dashboard.png" alt="Dashboard Screenshot">
</p>

The dashboard displays:

- Live building blueprint
- Node locations
- Heat map
- Rescue priority ranking
- Sensor health

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
├── dashboard/
├── docs/
└── README.md
```

---

## 🚀 Getting Started

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

## ⚙️ Calibration

1. Place all sensor nodes.
2. Keep the monitored area empty for approximately 30 seconds.
3. Record a baseline.
4. Begin monitoring.

Recalibrate whenever the environment changes.

---

## ⚠️ Current Limitations

- Zone-level detection rather than precise localization.
- Performance decreases through dense concrete and metal.
- Requires environmental calibration.
- Continuous CSI sensing increases power consumption.
- Multiple people within one zone may appear as a single detection.
- Indoor prototype only; not yet validated on real disaster sites.

---

## 🔒 Responsible Use

Phase is designed with privacy and safety in mind.

- Human operators always make final decisions.
- No raw audio is transmitted.
- Presence detection only—no identity recognition.
- "No signal" never means "area cleared."
- Intended for authorized emergency response.

---

## 🌎 Potential Applications

- Collapsed structure search and rescue
- Firefighter situational awareness
- Hurricane response
- Disaster recovery
- Emergency building assessment

---

## 🛣️ Roadmap

- [ ] Mesh networking
- [ ] Drone deployment
- [ ] Rugged enclosure
- [ ] Extended battery life
- [ ] Secure communication
- [ ] Field testing with rescue agencies
- [ ] Multi-person tracking research

---

## 📚 References

- https://github.com/espressif/esp-csi

---

## 📄 License

Choose your preferred open-source license (MIT recommended).

