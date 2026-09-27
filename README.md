# shellhacks_2026

## Live ESP32 display from Railway

The Python app polls a Railway HTTP GET endpoint and displays a stationary frequency spectrum. The frequency and amplitude axes stay fixed while the spectrum shape updates in place; the status indicator changes to `FEED INTERRUPTED` when a request fails. The selected sample channel is configured with `RAILWAY_SIGNAL_CHANNEL`, or defaults to the first numeric channel. Configure the service URL and route in PowerShell:

```powershell
$env:RAILWAY_API_URL = "https://your-service.up.railway.app"
$env:RAILWAY_DATA_ENDPOINT = "/api/data"
& '.\.venv\Scripts\python.exe' '.\shellhacks_2026\vizualizer.py'
```

Use your actual Railway URL and API route. The route should return JSON containing numeric fields, for example:

```json
{"timestamp": "2026-09-26T12:00:00Z", "ecg": 512, "temperature": 24.8}
```

Numeric arrays are also supported for batches, such as `{"ecg": [510, 512, 508]}`. The chart labels each numeric field as a separate channel. The poll interval defaults to 0.25 seconds and can be changed with `RAILWAY_POLL_INTERVAL`.

The Railway backend needs to expose the ESP32 readings through that GET route. If the ESP32 sends data to Railway using POST, the GET route should return the latest reading or a batch of recent readings. This project also needs Matplotlib installed in its selected Python environment.

## Run a local feed simulation

To view the live chart without Railway or an ESP32, run the local JSON feed simulator:

```powershell
& '.\.venv\Scripts\python.exe' '.\shellhacks_2026\simulate_feed.py'
```

It serves a changing ECG-like sample batch on a temporary local HTTP endpoint and opens the same visualizer. The simulator adds a 60 Hz interference burst after four seconds and brief HTTP outages, visible as a distinct spectrum peak and a `FEED INTERRUPTED` status. Close the chart window to stop the simulator.

The spectrum analyzes numeric samples; it does not identify Wi-Fi radio interference by itself. It currently assumes 512 samples per second and needs at least one second of uninterrupted samples to draw a spectrum. To diagnose RF link quality specifically, have the ESP32/backend also send RSSI and a packet sequence number or sample timestamp so actual packet loss can be distinguished from ordinary sensor changes.

## Live CSI environmental-change heatmap

The optional `csi_heatmap.py` view uses the existing Railway JSON client and leaves `vizualizer.py` and its spectrum processing unchanged. The node firmware captures CSI, but its normal LoRa packet sends only a scalar motion score; this view still requires a backend route that returns amplitude values per CSI subcarrier. It displays **CSI Environmental Change**, not a person classification.

Supported response shapes include one CSI vector:

```json
{"timestamp": 123456, "csi_amplitude": [0.82, 0.91, 1.04, 1.12]}
```

or a batch of vectors:

```json
{"samples": [{"csi_amplitude": [0.82, 0.91, 1.04]}, {"csi_amplitude": [0.80, 0.93, 1.02]}]}
```

Explicit complex components are also accepted as `{"csi": {"real": [...], "imag": [...]}}`; the client converts those to magnitude. Raw interleaved ESP-IDF byte buffers are intentionally not guessed or decoded because their layout depends on the ESP model and firmware. The subcarrier count must remain constant during a calibration/run.

Set `RAILWAY_API_URL` and `RAILWAY_DATA_ENDPOINT` to the CSI-serving Railway route, make sure the monitored area is clear, then launch:

```powershell
$env:RAILWAY_API_URL = "https://your-service.up.railway.app"
$env:RAILWAY_DATA_ENDPOINT = "/api/csi"
& '.\.venv\Scripts\python.exe' '.\shellhacks_2026\csi_heatmap.py'
```

The first 40 CSI samples establish a per-subcarrier median baseline; keep the area clear until the UI says `BASELINE ESTABLISHED`. `Recalibrate` starts that process again. `Pause` freezes the display while feed processing continues. The horizontal dimension is recent CSI packets and the vertical dimension is the actual subcarrier index; this project has no node geometry in its real feed, so it does not claim to localize a disturbance in physical space.

The baseline deviation for each subcarrier is the current amplitude's absolute difference from its calibrated median, less a noise allowance based on three scaled median absolute deviations and a 0.5% baseline-relative floor. The remaining relative change is divided by the configured deviation scale and clipped to 0-1. A subcarrier median filter and exponential moving average then reduce speckle and jitter. Color runs continuously from clear orange (`0`) through yellow, green, and teal to blue-grey (`1`, largest measured deviation). The score reports environmental change only; it does not infer that the cause is a person.

Tuning variables: `CSI_BASELINE_SAMPLES` (40), `CSI_DEVIATION_SCALE` (0.35 relative change for full-scale color), `CSI_NOISE_SIGMA` (3.0), `CSI_RELATIVE_NOISE_FLOOR` (0.005), `CSI_SUBCARRIER_MEDIAN_WINDOW` (3, odd values only), `CSI_SMOOTHING_ALPHA` (0.4; lower is smoother), `CSI_HISTORY_SAMPLES` (160), and `CSI_CHANGE_THRESHOLD` (0.25 for the UI indicator). The color score itself remains continuous; the threshold only labels the current mean score.

The existing generic `/api/data` and `simulate_feed.py` provide ECG-like numeric samples, not CSI. Pointing the CSI heatmap at that route will show a feed error until the backend returns one of the CSI shapes above. `simulate_spatial_feed.py` remains an explicitly synthetic spatial-map demo and is not used as evidence of real CSI localization.

## Preview the spatial CSI map

The spatial demo uses a placeholder 4 m by 3 m room with six nodes and seven crossing links. It serves simulated CSI JSON based on [spatial_csi_sample.json](spatial_csi_sample.json), moves a simulated hand through the room, and paints blue for the unchanged empty-room baseline and red where affected links overlap:

```powershell
& '.\.venv\Scripts\python.exe' '.\shellhacks_2026\simulate_spatial_feed.py'
```

Each link in the feed includes `tx`, `rx`, `baseline_amplitude`, and `current_amplitude` arrays. Replace the placeholder room coordinates and simulated feed with calibrated measurements from the actual ESP Wi-Fi CSI links when the nodes are assembled. The map is a coarse RF disturbance estimate, not a literal image of a hand.
## Website showcase

A ShellHacks 2026 concept exploring human presence sensing with Wi-Fi channel state information (CSI). The website depicts a star network: one sender broadcasts to three ESP32 sensing nodes, which report to a central gateway connected to a display. It includes an interactive 3D illustration and a network architecture diagram; neither displays live device data.

## View the website

Install the dependencies once, then start the local development server:

```sh
npm install
npm run dev
```

Open the local address printed by Vite. The hero uses Three.js and WebGL, so opening `index.html` directly as a file will not load the 3D scene. To create a production build, run `npm run build`; the output is in `dist/`.

The hero loads the 3D scene immediately over a quiet background, then the room assembles in a short sequence; visitors who prefer reduced motion see the complete scene immediately. If WebGL is unavailable, a short message replaces the scene. The furnished room depicts one sender, three sensing nodes, one gateway, a display, and two simplified standing people with green and blue presence areas. The links illustrate the star topology, not live CSI, measured radio paths, recovered body shapes, or validated localization results.

## Customize it

- Replace every occurrence of `[PROJECT NAME]` in `index.html` and this README once the team chooses a name.
- Update the GitHub URL in `index.html` if the project moves.
- Keep the 3D illustration and architecture diagram labeled as examples until actual sensor readings and validation support a live view.

## Files

- `index.html` — content and page structure
- `styles.css` — layout, responsive design, and animation
- `script.js` — mobile navigation and scroll reveals
- `system-architecture.png` — system-flow diagram used in section 01
- `network-architecture.png` — supplied star-network diagram used in section 02
- `scene.js` — interactive Three.js cutaway room and entrance animation
- `favicon.svg` — site icon
- `package.json` / `package-lock.json` — dependencies and reproducible build

## Git quick start

`git status` shows changed files and your current branch. `git diff` shows your edits. `git add <file>` chooses what goes into the next snapshot. `git commit -m "message"` saves that snapshot locally. `git pull --rebase` brings in teammates' commits before yours, and `git push` shares your commits with GitHub.

Before working, run `git pull --rebase`. Before pushing, check `git status` and `git diff` so you know exactly what you are sharing.

## Dashboard audio data

Each dashboard card belongs to the reading's `zone`. The live dashboard accepts two optional fields alongside the existing motion and audio-level fields:

```json
{"zone":"A","ts":"2026-09-27T12:00:00Z","state":"CLEAR","motion":0.06,"audio_db":43,"audio_waveform":[-0.2,0.1,0.4,-0.1],"scream_score":0.82}
```

`audio_waveform` is an array of at least two microphone samples normalized to -1 through 1; it is a display preview, not the model's input. `scream_score` is a model output from 0 through 1. The dashboard shows missing fields as unavailable instead of constructing a waveform or classification from the audio level. Its demo mode generates illustrative values only in the browser.

The computer bridge also accepts optional `w` (waveform) and `sc` (score) fields in a gateway JSON line and forwards them under these names. It caps the waveform preview at 96 points. The current node and gateway firmware transmit only an audio-level number, so real waveforms and scores require firmware/protocol work and a live inference pipeline. The existing `.keras` file and `audio_model.py` are offline model artifacts; they are not called by the node, bridge, or backend. The current model preprocessing expects 44.1 kHz, 10-second WAV input, while node audio capture is 16 kHz. Live classification needs compatible preprocessing and validation before its score can be treated as an actionable signal. These optional fields are broadcast live but are not stored in recording sessions.

## Dashboard spatial heatmap

The dashboard has a spatial heatmap placeholder below the zone cards. In demo mode it shows a synthetic A/B activity illustration. Without a spatial map payload it stays empty; two zone motion scores are not enough to estimate positions inside a room.

The dashboard accepts an optional `spatial_heatmap` object on a zone reading. It contains `width`, `height`, and a row-major `values` array of calibrated CSI-change intensities from 0 to 1. The bridge accepts the same object as `hm` in a gateway JSON line. The backend broadcasts it with the reading. For example, a 4-by-3 map has 12 values:

```json
{"zone":"A","ts":"2026-09-27T12:00:00Z","spatial_heatmap":{"width":4,"height":3,"values":[0,0.1,0.2,0,0.1,0.6,0.8,0.1,0,0.2,0.3,0]}}
```

The dashboard accepts grids from 4-by-3 through 32-by-24 and hides a map after three seconds without a new one. The existing `csi_heatmap.py` plots change by subcarrier and time; `spatial_visualizer.py` can display a link cross-section from the separate synthetic CSI feed. Neither currently produces a live, calibrated spatial grid for this dashboard. The node/gateway protocol and spatial reconstruction need to be extended before real heatmap values can appear. Map values are live-only and are not saved in recording sessions.
