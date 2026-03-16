"""
Real Camera ALPR Service - USB Camera Integration
Captures frames from USB camera and performs license plate recognition using EasyOCR.
Auto-detects plates via streak logic (no keypress needed).
"""

import re
import time
import cv2
import logging
import uuid
from datetime import datetime, timedelta
from typing import Optional, Tuple
import numpy as np
import easyocr
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# ── Auto-detect tuning (matches test_camera_alpr_easyocr.py) ─────────────────
OCR_EVERY_N_FRAMES  = 2      # Run OCR on every 2nd frame for speed
MIN_CONF            = 0.40   # Minimum EasyOCR confidence to consider
STREAK_TO_TRIGGER   = 3      # Consecutive matching reads before confirming
TRIGGER_COOLDOWN_SEC = 3.0   # Seconds to wait before accepting another plate


def _normalize(text: str) -> str:
    """Strip to alphanumeric uppercase."""
    return re.sub(r'[^A-Z0-9]', '', text.upper())


def _is_plausible_plate(text: str) -> bool:
    """Generic plate rule: 4–10 alphanumeric characters."""
    return 4 <= len(text) <= 10


class CameraALPRService:
    """
    Real ALPR using USB camera + EasyOCR.
    Replaces simulated gate_alpr with actual camera detection.
    Plates are auto-confirmed via streak logic – no keypress required.
    """

    def __init__(self, db_session: Session, message_bus, gate_id: str = "G1",
                 camera_index: int = 0):
        self.db           = db_session
        self.bus          = message_bus
        self.gate_id      = gate_id
        self.camera_index = camera_index

        self.camera          = None
        self.is_camera_ready = False

        # Load EasyOCR (downloads model on first run ~1 min)
        logger.info("Loading EasyOCR model (first run may take a minute)...")
        self.reader = easyocr.Reader(['en'], gpu=False)
        logger.info(f"Camera ALPR (EasyOCR) initialized for gate {gate_id}")

    # ── Camera lifecycle ──────────────────────────────────────────────────────

    def start_camera(self) -> bool:
        try:
            self.camera = cv2.VideoCapture(self.camera_index)
            if not self.camera.isOpened():
                logger.error(f"Failed to open camera {self.camera_index}")
                return False

            self.camera.set(cv2.CAP_PROP_FRAME_WIDTH,  1280)
            self.camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
            self.camera.set(cv2.CAP_PROP_FPS, 30)

            ret, _ = self.camera.read()
            if not ret:
                logger.error("Camera opened but cannot read frames")
                return False

            self.is_camera_ready = True
            logger.info(f"Camera {self.camera_index} started")
            return True

        except Exception as e:
            logger.error(f"Error starting camera: {e}")
            return False

    def stop_camera(self):
        if self.camera is not None:
            self.camera.release()
            self.is_camera_ready = False
            logger.info("Camera stopped")

    def capture_frame(self) -> Optional[np.ndarray]:
        if not self.is_camera_ready:
            return None
        ret, frame = self.camera.read()
        return frame if ret else None

    # ── OCR ───────────────────────────────────────────────────────────────────

    def read_license_plate(self, frame: np.ndarray) -> Tuple[Optional[str], float]:
        """
        Run EasyOCR on a single frame.
        Returns (plate_text, confidence) or (None, 0.0).
        """
        try:
            gray    = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            results = self.reader.readtext(gray)

            best_text, best_conf = None, 0.0
            for (_bbox, text, conf) in results:
                t = _normalize(text)
                if conf >= MIN_CONF and _is_plausible_plate(t) and conf > best_conf:
                    best_text, best_conf = t, conf

            if best_text:
                logger.debug(f"OCR: {best_text} ({best_conf:.2f})")
            return best_text, best_conf

        except Exception as e:
            logger.error(f"OCR error: {e}")
            return None, 0.0

    # ── Auto-detect loop ──────────────────────────────────────────────────────

    def wait_for_vehicle(self, timeout: int = 300) -> Tuple[Optional[str], Optional[np.ndarray]]:
        """
        Show live camera feed and auto-detect a license plate.
        Triggers when the same plate is read STREAK_TO_TRIGGER times in a row.

        Press 'q' to quit / skip to the next vehicle.

        Returns:
            (plate_text, captured_frame)  or  (None, None) if user pressed 'q'.
        """
        if not self.is_camera_ready:
            logger.error("Camera not ready")
            return None, None

        logger.info("Waiting for vehicle – auto-detect active  |  'q' to quit")

        start_time     = datetime.now()
        frame_count    = 0
        last_candidate = None
        streak         = 0
        last_trigger   = 0.0
        best_frame     = None

        while True:
            # Timeout
            if (datetime.now() - start_time).seconds > timeout:
                logger.warning("Vehicle detection timeout")
                cv2.destroyAllWindows()
                return None, None

            frame = self.capture_frame()
            if frame is None:
                continue

            frame_count  += 1
            display_frame = frame.copy()
            h, w          = display_frame.shape[:2]

            # Run OCR every N frames
            if frame_count % OCR_EVERY_N_FRAMES == 0:
                plate, conf = self.read_license_plate(frame)

                if plate:
                    if plate == last_candidate:
                        streak += 1
                    else:
                        last_candidate = plate
                        streak         = 1

                    now = time.time()
                    # Auto-trigger when streak reached and cooldown elapsed
                    if streak >= STREAK_TO_TRIGGER and (now - last_trigger) >= TRIGGER_COOLDOWN_SEC:
                        last_trigger = now
                        best_frame   = frame.copy()
                        logger.info(f"✅ Auto-detected plate: {plate} (conf {conf:.2f}, streak {streak})")
                        cv2.destroyAllWindows()
                        return plate, best_frame
                else:
                    last_candidate = None
                    streak         = 0

            # ── Overlay ──────────────────────────────────────────────────────
            cv2.putText(display_frame, "AUTO DETECT | 'q' to quit",
                        (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0, 255, 0), 2)

            if last_candidate:
                bar_w = int((streak / STREAK_TO_TRIGGER) * 200)
                cv2.rectangle(display_frame, (10, h - 50), (210, h - 30), (50, 50, 50), -1)
                cv2.rectangle(display_frame, (10, h - 50), (10 + bar_w, h - 30), (0, 200, 0), -1)
                cv2.putText(display_frame,
                            f"Candidate: {last_candidate}  streak {streak}/{STREAK_TO_TRIGGER}",
                            (10, h - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 255, 0), 2)
            else:
                cv2.putText(display_frame, "Scanning for plate...",
                            (10, h - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 100, 255), 2)

            cv2.imshow('Gate Camera – ALPR', display_frame)

            key = cv2.waitKey(1) & 0xFF
            if key == ord('q'):
                logger.info("User quit camera")
                cv2.destroyAllWindows()
                return None, None

    # ── Legacy helper (kept for compatibility) ────────────────────────────────

    def create_session_from_camera(self, priority_class, selected_zone: str = "ANY"):
        """
        Legacy helper – creates a VehicleSession directly from camera.
        (run_camera_demo.py handles session creation itself; this is kept
        only for any scripts that called it previously.)
        """
        from src.core.plate_hasher import hash_plate
        from src.core import Clock
        from src.models.database import VehicleSession

        plate_number, _frame = self.wait_for_vehicle(timeout=60)
        if not plate_number:
            logger.error("Failed to read license plate")
            return None

        plate_hash  = hash_plate(plate_number)
        session_id  = str(uuid.uuid4())
        now         = Clock.now()

        session = VehicleSession(
            session_id        = session_id,
            gate_id           = self.gate_id,
            plate_hash        = plate_hash,
            priority_class    = priority_class,
            selected_entrance = "ENTRANCE_ANY",
            selected_zone     = selected_zone,
            created_at        = now,
            expires_at        = now + timedelta(hours=4)
        )
        self.db.add(session)
        self.db.commit()

        self.bus.publish("parking/request", {
            "sessionId":     session_id,
            "gateId":        self.gate_id,
            "priorityClass": priority_class.value,
            "selectedZone":  selected_zone,
        })

        logger.info(f"Session created for plate {plate_number} → {session_id[:8]}…")
        return session
