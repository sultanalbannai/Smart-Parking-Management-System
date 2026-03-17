"""
Bay Camera Service
==================
Monitors a group of parking bays using one USB camera.
- YOLOv8  → detects whether a vehicle is present in each bay's ROI
- EasyOCR → reads the plate inside each occupied ROI for logging

One BayCameraService instance per physical camera.
Run each in its own daemon thread (see run_camera_demo.py).

Dependencies:
    pip install ultralytics easyocr opencv-python
"""

import re
import time
import threading
import logging
import yaml
import cv2
import numpy as np
import easyocr
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── Tuning constants ──────────────────────────────────────────────────────────
YOLO_CONF           = 0.45   # minimum YOLO detection confidence
VEHICLE_CLASSES     = {2, 5, 7}   # COCO: car=2, bus=5, truck=7
OCR_EVERY_N_FRAMES  = 30     # run plate OCR every N frames (~1 s at 30 fps)
DEBOUNCE_COUNT      = 4      # consecutive same-state frames to commit a change
MIN_PLATE_LEN       = 2
MAX_PLATE_LEN       = 10
# ─────────────────────────────────────────────────────────────────────────────


def _normalize(text: str) -> str:
    return re.sub(r'[^A-Z0-9]', '', text.upper())


def _vehicle_in_roi(results, roi: Tuple[int, int, int, int]) -> Tuple[bool, float]:
    """
    Return (occupied, confidence) by checking whether any YOLO vehicle
    detection box overlaps the ROI by at least 20 %.
    roi = (x1, y1, x2, y2) in pixel coordinates.
    """
    rx1, ry1, rx2, ry2 = roi
    roi_area = max(1, (rx2 - rx1) * (ry2 - ry1))

    best_conf = 0.0
    for box in results[0].boxes:
        cls = int(box.cls[0])
        if cls not in VEHICLE_CLASSES:
            continue
        conf = float(box.conf[0])
        bx1, by1, bx2, by2 = map(int, box.xyxy[0])

        # Intersection area
        ix1, iy1 = max(rx1, bx1), max(ry1, by1)
        ix2, iy2 = min(rx2, bx2), min(ry2, by2)
        inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)

        overlap = inter / roi_area
        if overlap >= 0.20 and conf > best_conf:
            best_conf = conf

    return best_conf >= YOLO_CONF, best_conf


class BayCameraService:
    """
    Monitors one camera covering a fixed set of bays.

    Parameters
    ----------
    camera_index : int
        OpenCV camera device index.
    bay_ids : list[str]
        Bay IDs covered by this camera (e.g. ["G-01", "G-02", ...]).
    rois : dict[str, tuple]
        Mapping bay_id → (x1, y1, x2, y2) pixel rectangle in the camera frame.
    occupancy_service :
        OccupancyService instance (mark_bay_occupied / mark_bay_vacant).
    bus :
        MessageBus instance (for publishing plate_logged events).
    db_session :
        SQLAlchemy session for plate-hash lookups.
    label : str
        Human-readable label for log messages.
    """

    def __init__(self, camera_index: int, bay_ids: List[str],
                 rois: Dict[str, Tuple[int, int, int, int]],
                 occupancy_service, bus, db_session, label: str = ""):
        self.camera_index     = camera_index
        self.bay_ids          = bay_ids
        self.rois             = rois          # bay_id → (x1,y1,x2,y2)
        self.occupancy        = occupancy_service
        self.bus              = bus
        self.db               = db_session
        self.label            = label or f"BayCam-{camera_index}"

        self._stop_event      = threading.Event()
        self._thread: Optional[threading.Thread] = None

        # Per-bay debounce counters
        self._occ_streak:  Dict[str, int] = {b: 0 for b in bay_ids}
        self._free_streak: Dict[str, int] = {b: 0 for b in bay_ids}
        self._current_state: Dict[str, bool] = {b: False for b in bay_ids}

        # Load models (shared across calls)
        logger.info(f"[{self.label}] Loading YOLOv8n …")
        from ultralytics import YOLO
        self._yolo = YOLO("yolov8n.pt")   # downloads on first run (~6 MB)

        logger.info(f"[{self.label}] Loading EasyOCR …")
        self._ocr = easyocr.Reader(['en'], gpu=False, verbose=False)

        logger.info(f"[{self.label}] Ready – bays: {bay_ids}")

    # ── Public API ────────────────────────────────────────────────────────────

    def start(self):
        """Start the monitoring loop in a background daemon thread."""
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name=self.label)
        self._thread.start()
        logger.info(f"[{self.label}] Started")

    def stop(self):
        """Signal the monitoring loop to stop."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
        logger.info(f"[{self.label}] Stopped")

    # ── Internal loop ─────────────────────────────────────────────────────────

    def _run(self):
        cap = cv2.VideoCapture(self.camera_index)
        if not cap.isOpened():
            logger.error(f"[{self.label}] Cannot open camera {self.camera_index}")
            return

        cap.set(cv2.CAP_PROP_FRAME_WIDTH,  1280)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
        cap.set(cv2.CAP_PROP_FPS, 30)

        frame_count = 0
        logger.info(f"[{self.label}] Camera {self.camera_index} open – monitoring …")

        while not self._stop_event.is_set():
            ret, frame = cap.read()
            if not ret:
                logger.warning(f"[{self.label}] Frame read failed – retrying …")
                time.sleep(0.5)
                continue

            frame_count += 1

            # ── YOLO inference on full frame ──────────────────────────────
            results = self._yolo(frame, verbose=False, conf=YOLO_CONF)

            for bay_id in self.bay_ids:
                roi = self.rois.get(bay_id)
                if roi is None:
                    continue   # not yet calibrated

                occupied, conf = _vehicle_in_roi(results, roi)
                self._update_state(bay_id, occupied, conf, frame, frame_count)

        cap.release()
        logger.info(f"[{self.label}] Camera released")

    def _update_state(self, bay_id: str, occupied: bool, conf: float,
                      frame: np.ndarray, frame_count: int):
        """Apply debounce logic and commit state changes."""
        if occupied:
            self._occ_streak[bay_id]  += 1
            self._free_streak[bay_id]  = 0
        else:
            self._free_streak[bay_id] += 1
            self._occ_streak[bay_id]   = 0

        currently_occupied = self._current_state[bay_id]

        # Transition: available → occupied
        if not currently_occupied and self._occ_streak[bay_id] >= DEBOUNCE_COUNT:
            self._current_state[bay_id] = True
            plate = self._read_plate_in_roi(frame, self.rois[bay_id], frame_count)
            self._on_occupied(bay_id, plate, conf)

        # Transition: occupied → available
        elif currently_occupied and self._free_streak[bay_id] >= DEBOUNCE_COUNT:
            self._current_state[bay_id] = False
            self._on_vacant(bay_id)

    def _on_occupied(self, bay_id: str, plate: Optional[str], conf: float):
        logger.info(f"[{self.label}] {bay_id} OCCUPIED  plate={plate or '?'}  conf={conf:.2f}")

        from src.core.plate_hasher import hash_plate
        plate_hash = hash_plate(plate or f"CAM{self.camera_index}_{bay_id}")

        try:
            self.occupancy.mark_bay_occupied(bay_id=bay_id, plate_hash=plate_hash)
        except Exception as e:
            logger.error(f"[{self.label}] mark_bay_occupied failed: {e}")

        # Publish plate-logging event (dashboard activity feed)
        self.bus.publish("parking/bays/plate_logged", {
            "bayId":    bay_id,
            "plate":    plate or "UNKNOWN",
            "camera":   self.camera_index,
            "conf":     round(conf, 3),
        })

    def _on_vacant(self, bay_id: str):
        logger.info(f"[{self.label}] {bay_id} VACANT")
        try:
            self.occupancy.mark_bay_vacant(bay_id=bay_id)
        except Exception as e:
            logger.error(f"[{self.label}] mark_bay_vacant failed: {e}")

    def _read_plate_in_roi(self, frame: np.ndarray,
                           roi: Tuple[int, int, int, int],
                           frame_count: int) -> Optional[str]:
        """Run EasyOCR on the ROI crop every OCR_EVERY_N_FRAMES frames."""
        if frame_count % OCR_EVERY_N_FRAMES != 0:
            return None

        x1, y1, x2, y2 = roi
        crop = frame[y1:y2, x1:x2]
        if crop.size == 0:
            return None

        try:
            gray    = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
            results = self._ocr.readtext(gray)
            best_text, best_conf = None, 0.0
            for (_bbox, text, conf) in results:
                t = _normalize(text)
                if MIN_PLATE_LEN <= len(t) <= MAX_PLATE_LEN and conf > best_conf:
                    best_text, best_conf = t, conf
            return best_text
        except Exception as e:
            logger.warning(f"[{self.label}] OCR error: {e}")
            return None


# ── Loader helper (used by run_camera_demo.py) ────────────────────────────────

def load_bay_cameras(config_path: str, rois_path: str,
                     occupancy_service, bus, db_session) -> List[BayCameraService]:
    """
    Build BayCameraService instances from config + ROI yaml files.

    Returns a list (one per camera).  Cameras whose ROI file entry is missing
    are still created but will skip unresolved bays silently.
    """
    with open(config_path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    # Load ROIs if file exists
    rois_data: Dict[str, Dict] = {}
    if Path(rois_path).exists():
        with open(rois_path, encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
        for cam_entry in raw.get("cameras", []):
            idx = cam_entry["camera_index"]
            rois_data[idx] = {
                b["bay_id"]: tuple(b["roi"])
                for b in cam_entry.get("bays", [])
                if b.get("roi")
            }
    else:
        logger.warning(f"ROI file not found: {rois_path}  – run calibrate_bay_rois.py first")

    services = []
    for cam_cfg in cfg.get("bay_cameras", []):
        idx     = cam_cfg["camera_index"]
        bay_ids = cam_cfg.get("bays") or []
        if not bay_ids:
            logger.info(f"Camera {idx}: no bays assigned – skipped")
            continue
        label   = cam_cfg.get("label", f"BayCam-{idx}")
        rois    = rois_data.get(idx, {})

        svc = BayCameraService(
            camera_index     = idx,
            bay_ids          = bay_ids,
            rois             = rois,
            occupancy_service = occupancy_service,
            bus              = bus,
            db_session       = db_session,
            label            = label,
        )
        services.append(svc)

    return services
