# Smart Parking Management System (SPMS)

Edge-deployed parking management system that runs entirely on an NVIDIA
Jetson Orin Nano. License-plate recognition at the gate, per-bay
occupancy detection, real-time dashboard, kiosk display, and live camera
streams - no cloud round-trip required.

## Features

- **Gate ALPR** - Detects vehicles at the entrance, captures and OCRs the
  license plate when the car settles in front of the camera
- **Per-bay occupancy** - One USB camera per bay (or shared field of view)
  uses YOLOv8 to detect vehicles inside a configurable region of interest
- **License-plate logging** - EasyOCR runs continuously on each occupied
  bay until a confident plate is captured; result is persisted to SQLite
- **Web dashboard** - Real-time parking map with bay state and plates,
  served via Flask + Socket.IO on port 5000
- **Kiosk display** - Driver-facing screen that shows the suggested bay
  immediately after the gate ALPR fires
- **Browser-based calibration** - `/calibrate` page lets the operator
  assign physical USB cameras to roles (gate / each bay) and draw ROIs
  with click-and-drag, all without a monitor on the Jetson
- **Manual override** - Bay-info modal includes "Mark Occupied" / "Mark
  Free" buttons for demos and manual corrections

## Stack

| Layer        | Component                                    |
|--------------|----------------------------------------------|
| Hardware     | NVIDIA Jetson Orin Nano + USB cameras        |
| Detection    | YOLOv8n exported to TensorRT (FP16, imgsz=320) |
| OCR          | EasyOCR (CUDA-enabled)                       |
| Backend      | Python 3.10, Flask, Flask-SocketIO           |
| Persistence  | SQLite via SQLAlchemy (scoped_session)       |
| Frontend     | Vanilla HTML/CSS/JS, Socket.IO client        |

## Layout

```
.
├── run_camera_demo.py        # Entry point
├── init_camera_db.py         # Initialize the SQLite database
├── camera_alpr_service.py    # Gate camera + ALPR pipeline
├── bay_camera_service.py     # Per-bay YOLO + OCR service
├── web_server_camera.py      # Flask + Socket.IO server, all endpoints
├── alerts.cfg                # Email / SMS alert configuration
├── config/
│   ├── camera_demo_config.yaml   # Facility layout, bay positions, camera roles
│   └── bay_rois.yaml             # ROI rectangles per bay
├── data/
│   └── spms.db               # SQLite database (created by init script)
├── src/
│   ├── core/                 # Clock, config, message bus
│   ├── models/               # SQLAlchemy models
│   └── services/             # Recommendation, occupancy, confirmation, alerts
├── templates/                # Jinja2 templates (dashboard, kiosk, calibrate)
├── static/                   # CSS + JavaScript
└── yolov8n.engine            # TensorRT engine (built from yolov8n.pt)
```

## Quick start

Tested on Jetson Orin Nano with JetPack 6.2 (CUDA 12.6, Python 3.10).

```bash
# 1. Install dependencies
pip3 install -r requirements.txt

# 2. Initialize the database
python3 init_camera_db.py

# 3. Build the TensorRT engine (one-time, ~10 minutes)
python3 -c "from ultralytics import YOLO; \
            YOLO('yolov8n.pt').export(format='engine', half=True, imgsz=320)"

# 4. Set the Jetson to maximum performance and run headless
sudo nvpmodel -m 0
sudo jetson_clocks
export SPMS_HEADLESS=1
python3 run_camera_demo.py
```

Open `http://<jetson-ip>:5000` for the dashboard,
`http://<jetson-ip>:5000/calibrate` to assign cameras and draw ROIs.

## Configuration

- `config/camera_demo_config.yaml` - facility layout, bay coordinates,
  entrance position, camera-to-role assignments
- `config/bay_rois.yaml` - per-camera ROI rectangles (managed by the
  web calibrator; no need to edit by hand)
- `alerts.cfg` - SMTP / Twilio credentials for email and SMS alerts
- Environment variables:
  - `SPMS_HEADLESS=1` - disable all OpenCV preview windows
  - `USE_MQTT=1` - use a real MQTT broker instead of the in-process bus

## Performance notes

The default tuning on Jetson Orin Nano:

- 640x480 capture at 10 fps for bay cameras, 15 fps for the gate camera
- YOLO runs at most every 5th frame and is gated by background-subtraction
  motion detection - idle cameras burn near-zero GPU time
- OCR runs only when a bay transitions to OCCUPIED, then continuously
  every ~1.5 s while the bay stays OCCUPIED until a plate of at least
  4 digits is captured
- Web server stays on port 5000 reachable over LAN or USB-Ethernet
  (192.168.55.1 by default on Jetson)
