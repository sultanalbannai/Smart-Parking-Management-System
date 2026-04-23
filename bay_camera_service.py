"""
Bay Camera Service
==================
Monitors a parking bay using one USB camera.
- YOLOv8  → detects whether a vehicle is present in the bay's ROI
- EasyOCR → reads the plate number when a car parks

The plate is saved to Bay.parked_plate in the database so it can be
looked up later (e.g. "which bay is plate 12345 in?").

One BayCameraService instance per physical camera.

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
from typing import Dict, List, Optional, Tuple

def _cuda_available():
    try:
        import torch
        return torch.cuda.is_available()
    except ImportError:
        return False

# ── Shared singleton resources (loaded once, reused across all cameras) ───────

_shared_yolo = None
_shared_ocr  = None
_model_lock  = threading.Lock()

def _get_yolo():
    global _shared_yolo
    with _model_lock:
        if _shared_yolo is None:
            from ultralytics import YOLO
            _shared_yolo = YOLO("yolov8n.pt")
    return _shared_yolo

def _get_ocr():
    global _shared_ocr
    with _model_lock:
        if _shared_ocr is None:
            _shared_ocr = easyocr.Reader(['en'], gpu=_cuda_available(), verbose=False)
    return _shared_ocr

logger = logging.getLogger(__name__)

# ── Tuning ────────────────────────────────────────────────────────────────────
YOLO_CONF          = 0.45        # minimum YOLO detection confidence
VEHICLE_CLASSES    = {2, 5, 7}  # COCO: car=2, bus=5, truck=7
DEBOUNCE_COUNT     = 4           # consecutive same-state frames to commit
MIN_CONF           = 0.30        # minimum EasyOCR confidence
OCR_RETRY_FRAMES   = 150         # keep retrying OCR for this many frames (~5 s)
OCR_RETRY_INTERVAL = 15          # attempt OCR every N frames during retry window

# Background-subtraction fallback (catches toy/model cars YOLO misses)
BG_FG_THRESHOLD    = 0.10        # fraction of ROI pixels that must change
BG_PIXEL_THRESH    = 25          # grayscale diff threshold per pixel
# ─────────────────────────────────────────────────────────────────────────────


def _normalize(text: str) -> str:
    """Keep digits only (matching gate ALPR behaviour)."""
    return re.sub(r'[^0-9]', '', text)


def _vehicle_in_roi(results, roi: Tuple[int, int, int, int]) -> Tuple[bool, float]:
    """
    Return (occupied, confidence) – True when a YOLO vehicle box overlaps
    the ROI by at least 20 %.
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

        ix1, iy1 = max(rx1, bx1), max(ry1, by1)
        ix2, iy2 = min(rx2, bx2), min(ry2, by2)
        inter    = max(0, ix2 - ix1) * max(0, iy2 - iy1)

        if inter / roi_area >= 0.20 and conf > best_conf:
            best_conf = conf

    return best_conf >= YOLO_CONF, best_conf


class BayCameraService:
    """
    Monitors one camera watching one (or more) specific bays.
    Updates occupancy and saves the detected plate to the database.
    """

    def __init__(self, camera_index: int, bay_ids: List[str],
                 rois: Dict[str, Tuple[int, int, int, int]],
                 occupancy_service, bus, db_session, label: str = ""):
        self.camera_index = camera_index
        self.bay_ids      = bay_ids
        self.rois         = rois
        self.occupancy    = occupancy_service
        self.bus          = bus
        self.db           = db_session
        self.label        = label or f"BayCam-{camera_index}"

        self._stop_event  = threading.Event()
        self._thread: Optional[threading.Thread] = None

        # Per-bay debounce counters
        self._occ_streak:    Dict[str, int]  = {b: 0 for b in bay_ids}
        self._free_streak:   Dict[str, int]  = {b: 0 for b in bay_ids}
        self._current_state: Dict[str, bool] = {b: False for b in bay_ids}

        # Latest frame buffer (for external preview)
        self._latest_frame: Optional[np.ndarray] = None
        self._frame_lock = threading.Lock()

        # One-shot callbacks: bay_id → callable, fired once on occupied
        self._occupied_callbacks: Dict[str, callable] = {}

        # Per-bay OCR retry budget (frames remaining to keep trying after occupancy)
        self._ocr_retry: Dict[str, int] = {b: 0 for b in bay_ids}

        logger.info(f"[{self.label}] Loading YOLOv8n …")
        self._yolo = _get_yolo()

        logger.info(f"[{self.label}] Loading EasyOCR …")
        self._ocr = _get_ocr()

        logger.info(f"[{self.label}] Ready – watching bays: {bay_ids}")

    # ── Public API ────────────────────────────────────────────────────────────

    def start(self):
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name=self.label)
        self._thread.start()
        logger.info(f"[{self.label}] Started")

    def stop(self):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
        logger.info(f"[{self.label}] Stopped")

    def get_latest_frame(self) -> Optional[np.ndarray]:
        """Return the most recent captured frame (thread-safe copy)."""
        with self._frame_lock:
            return self._latest_frame.copy() if self._latest_frame is not None else None

    def notify_when_occupied(self, bay_id: str, callback) -> None:
        """Register a one-shot callback fired the next time bay_id becomes occupied."""
        self._occupied_callbacks[bay_id] = callback

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

        # Capture empty-scene reference for background-diff fallback
        for _ in range(20):
            cap.read()
        ret0, ref_frame = cap.read()
        ref_grays: Dict[str, np.ndarray] = {}
        if ret0 and ref_frame is not None:
            for bay_id in self.bay_ids:
                roi = self.rois.get(bay_id)
                if roi:
                    x1, y1, x2, y2 = roi
                    g = cv2.cvtColor(ref_frame[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY)
                    ref_grays[bay_id] = cv2.GaussianBlur(g, (5, 5), 0)
            logger.info(f"[{self.label}] Reference frames captured")

        while not self._stop_event.is_set():
            ret, frame = cap.read()
            if not ret:
                logger.warning(f"[{self.label}] Frame read failed – retrying …")
                time.sleep(0.5)
                continue

            frame_count += 1
            with self._frame_lock:
                self._latest_frame = frame.copy()

            results = self._yolo(frame, verbose=False, conf=YOLO_CONF)

            for bay_id in self.bay_ids:
                roi = self.rois.get(bay_id)
                if roi is None:
                    continue

                yolo_hit, conf = _vehicle_in_roi(results, roi)

                # Background-diff fallback: catches toy/model cars YOLO misses
                bg_hit = False
                ref_g  = ref_grays.get(bay_id)
                if ref_g is not None:
                    x1, y1, x2, y2 = roi
                    curr_g = cv2.GaussianBlur(
                        cv2.cvtColor(frame[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY), (5, 5), 0)
                    diff   = cv2.absdiff(ref_g, curr_g)
                    _, thr = cv2.threshold(diff, BG_PIXEL_THRESH, 255, cv2.THRESH_BINARY)
                    roi_area = max(1, (x2 - x1) * (y2 - y1))
                    bg_hit = np.count_nonzero(thr) / roi_area >= BG_FG_THRESHOLD

                occupied = yolo_hit or bg_hit
                if occupied and not conf:
                    conf = 0.5   # synthetic confidence for bg-based detection

                self._update_state(bay_id, occupied, conf, frame, frame_count)

            # ── Plate retry loop ───────────────────────────────────────────
            # If occupancy was confirmed but plate not yet read, keep trying
            # every OCR_RETRY_INTERVAL frames for up to OCR_RETRY_FRAMES frames.
            for bay_id in self.bay_ids:
                if self._ocr_retry.get(bay_id, 0) <= 0:
                    continue
                self._ocr_retry[bay_id] -= 1
                if frame_count % OCR_RETRY_INTERVAL != 0:
                    continue
                roi = self.rois.get(bay_id)
                if roi is None:
                    continue
                plate = self._read_plate_crop(frame, roi)
                if plate:
                    self._ocr_retry[bay_id] = 0
                    logger.info(f"[{self.label}] {bay_id} plate (retry): {plate}")
                    self._save_plate(bay_id, plate)

        cap.release()
        logger.info(f"[{self.label}] Camera released")

    def _update_state(self, bay_id: str, occupied: bool, conf: float,
                      frame, frame_count: int):
        """Apply debounce and commit occupancy transitions."""
        if occupied:
            self._occ_streak[bay_id]  += 1
            self._free_streak[bay_id]  = 0
        else:
            self._free_streak[bay_id] += 1
            self._occ_streak[bay_id]   = 0

        currently_occupied = self._current_state[bay_id]

        if not currently_occupied and self._occ_streak[bay_id] >= DEBOUNCE_COUNT:
            self._current_state[bay_id] = True
            # Always attempt OCR immediately at the transition (no frame-count gate)
            plate = self._read_plate_crop(frame, self.rois[bay_id])
            if not plate:
                # Arm retry: keep trying for ~5 s after occupancy confirmed
                self._ocr_retry[bay_id] = OCR_RETRY_FRAMES
            self._on_occupied(bay_id, plate, conf)

        elif currently_occupied and self._free_streak[bay_id] >= DEBOUNCE_COUNT:
            self._current_state[bay_id] = False
            self._ocr_retry[bay_id] = 0   # cancel any pending retry
            self._on_vacant(bay_id)

    def _on_occupied(self, bay_id: str, plate: Optional[str], conf: float):
        from src.core.plate_hasher import hash_plate
        from src.models.database import Bay
        from src.core import Clock

        plate_hash = hash_plate(plate or f"CAM{self.camera_index}_{bay_id}")
        logger.info(f"[{self.label}] {bay_id} OCCUPIED  plate={plate or '?'}  conf={conf:.2f}")

        try:
            self.occupancy.mark_bay_occupied(bay_id=bay_id, plate_hash=plate_hash)
        except Exception as e:
            logger.error(f"[{self.label}] mark_bay_occupied failed: {e}")

        # Save raw plate number (if already detected at transition)
        if plate:
            self._save_plate(bay_id, plate)

        # Fire one-shot occupied callback if registered
        cb = self._occupied_callbacks.pop(bay_id, None)
        if cb:
            cb(bay_id)

        # If no plate yet, still notify dashboard so activity feed shows occupancy
        if not plate:
            self.bus.publish("parking/bays/plate_logged", {
                "bayId":  bay_id,
                "plate":  "SCANNING…",
                "camera": self.camera_index,
                "conf":   round(conf, 3),
            })

    def _on_vacant(self, bay_id: str):
        from src.models.database import Bay
        from src.core import Clock

        logger.info(f"[{self.label}] {bay_id} VACANT")
        try:
            self.occupancy.mark_bay_vacant(bay_id=bay_id)
        except Exception as e:
            logger.error(f"[{self.label}] mark_bay_vacant failed: {e}")

        # Clear the stored plate when the car leaves
        try:
            bay = self.db.query(Bay).filter(Bay.id == bay_id).first()
            if bay:
                bay.parked_plate = None
                bay.last_update_time = Clock.now()
                self.db.commit()
        except Exception as e:
            logger.error(f"[{self.label}] Failed to clear plate from DB: {e}")

    def _read_plate_crop(self, frame, roi: Tuple[int, int, int, int]) -> Optional[str]:
        """
        Crop the ROI, enhance contrast, and run EasyOCR.
        Always runs (no frame-count gate) – callers decide when to invoke.
        """
        x1, y1, x2, y2 = roi
        crop = frame[y1:y2, x1:x2]
        if crop.size == 0:
            return None

        try:
            gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)

            # CLAHE contrast enhancement – helps on dim / uneven lighting
            clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
            gray  = clahe.apply(gray)

            # Mild sharpening
            kernel = np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]], dtype=np.float32)
            gray   = cv2.filter2D(gray, -1, kernel)

            # Run OCR on original size AND 2× upscale for better small-text accuracy
            best_text, best_conf = None, 0.0
            for img in [gray, cv2.resize(gray, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)]:
                for (_bbox, text, c) in self._ocr.readtext(img):
                    t = _normalize(text)
                    if 2 <= len(t) <= 10 and c >= MIN_CONF and c > best_conf:
                        best_text, best_conf = t, c

            if best_text:
                logger.debug(f"[{self.label}] OCR result: {best_text}  conf={best_conf:.2f}")
            return best_text

        except Exception as e:
            logger.warning(f"[{self.label}] OCR error: {e}")
            return None

    def _save_plate(self, bay_id: str, plate: str):
        """Persist a newly-read plate to the bay row and broadcast the event."""
        from src.models.database import Bay
        from src.core import Clock
        try:
            bay = self.db.query(Bay).filter(Bay.id == bay_id).first()
            if bay:
                bay.parked_plate     = plate
                bay.last_update_time = Clock.now()
                self.db.commit()
                logger.info(f"[{self.label}] Saved plate {plate} → {bay_id}")
        except Exception as e:
            logger.error(f"[{self.label}] Failed to save plate to DB: {e}")

        self.bus.publish("parking/bays/plate_logged", {
            "bayId":  bay_id,
            "plate":  plate,
            "camera": self.camera_index,
            "conf":   0.0,
        })


# ── Loader helper (used by run_camera_demo.py) ────────────────────────────────

def load_bay_cameras(config_path: str, rois_path: str,
                     occupancy_service, bus, db_session) -> List[BayCameraService]:
    """
    Build BayCameraService instances from config + ROI yaml files.
    Returns one service per camera entry that has bays assigned.
    """
    with open(config_path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    rois_data: Dict[int, Dict] = {}
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
        logger.warning(f"ROI file not found: {rois_path} – run calibrate_bay_rois.py first")

    services = []
    for cam_cfg in cfg.get("bay_cameras", []):
        idx     = cam_cfg["camera_index"]
        bay_ids = cam_cfg.get("bays") or []
        if not bay_ids:
            logger.info(f"Camera {idx}: no bays assigned – skipped")
            continue

        svc = BayCameraService(
            camera_index      = idx,
            bay_ids           = bay_ids,
            rois              = rois_data.get(idx, {}),
            occupancy_service = occupancy_service,
            bus               = bus,
            db_session        = db_session,
            label             = cam_cfg.get("label", f"BayCam-{idx}"),
        )
        services.append(svc)

    return services
