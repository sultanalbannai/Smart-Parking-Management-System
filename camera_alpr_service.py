"""
Real Camera ALPR Service - USB Camera Integration
Captures frames from USB camera and performs license plate recognition using EasyOCR.

Detection strategy:
  1. Background subtractor watches the centre zone of the frame.
  2. When a vehicle fills that zone, ONE snapshot is taken.
  3. EasyOCR runs once on that snapshot and the plate is returned.
  No streak / repeated-frame logic – a single sharp photo is used.
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

# ── Tuning ────────────────────────────────────────────────────────────────────
MIN_CONF            = 0.35   # minimum EasyOCR confidence to accept
TRIGGER_COOLDOWN_SEC = 4.0   # seconds to ignore triggers after one fires

# Centre trigger zone as fractions of (width, height)
ZONE_LEFT   = 0.15
ZONE_RIGHT  = 0.85
ZONE_TOP    = 0.25
ZONE_BOTTOM = 0.75

# Fraction of the zone that must be foreground to fire the snapshot
FG_THRESHOLD = 0.12

# Frames to wait after presence is first detected before snapping
# (lets the car settle into position)
SETTLE_FRAMES = 8
# ─────────────────────────────────────────────────────────────────────────────


def _normalize(text: str) -> str:
    return re.sub(r'[^A-Z0-9]', '', text.upper())


def _is_plausible_plate(text: str) -> bool:
    return 2 <= len(text) <= 10


class CameraALPRService:
    """
    Real ALPR using USB camera + EasyOCR.
    Fires once when a vehicle appears in the centre of the frame,
    OCRs that single snapshot, and returns the plate.
    """

    def __init__(self, db_session: Session, message_bus, gate_id: str = "G1",
                 camera_index: int = 0):
        self.db           = db_session
        self.bus          = message_bus
        self.gate_id      = gate_id
        self.camera_index = camera_index

        self.camera          = None
        self.is_camera_ready = False

        logger.info("Loading EasyOCR model (first run may take a minute)...")
        self.reader = easyocr.Reader(['en'], gpu=False)
        logger.info(f"Camera ALPR (EasyOCR) initialised for gate {gate_id}")

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
        """Run EasyOCR on a single frame. Returns (plate_text, confidence)."""
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

    # ── Main detection loop ───────────────────────────────────────────────────

    def wait_for_vehicle(self, timeout: int = 300) -> Tuple[Optional[str], Optional[np.ndarray]]:
        """
        Show live camera feed.
        When a vehicle fills the centre zone, snap ONE frame and run OCR.
        Returns (plate_text, frame) or (None, None) if 'q' pressed / timeout.
        """
        if not self.is_camera_ready:
            logger.error("Camera not ready")
            return None, None

        logger.info("Waiting for vehicle – centre-snap mode  |  'q' to quit")

        # Background subtractor – adapts to the empty scene quickly
        bg_sub = cv2.createBackgroundSubtractorMOG2(
            history=100, varThreshold=40, detectShadows=False
        )

        start_time    = datetime.now()
        last_trigger  = 0.0
        settle_count  = 0      # counts frames with presence detected
        snap_frame    = None   # frozen frame waiting for OCR
        snapped       = False  # True while we are processing a snapshot

        while True:
            if (datetime.now() - start_time).seconds > timeout:
                logger.warning("Vehicle detection timeout")
                cv2.destroyAllWindows()
                return None, None

            frame = self.capture_frame()
            if frame is None:
                continue

            h, w = frame.shape[:2]

            # Compute centre zone pixel coordinates
            zx1 = int(w * ZONE_LEFT)
            zx2 = int(w * ZONE_RIGHT)
            zy1 = int(h * ZONE_TOP)
            zy2 = int(h * ZONE_BOTTOM)

            display = frame.copy()

            if not snapped:
                # ── Check for vehicle presence in centre zone ─────────────
                fg_mask  = bg_sub.apply(frame)
                zone_fg  = fg_mask[zy1:zy2, zx1:zx2]
                zone_area = max(1, (zx2 - zx1) * (zy2 - zy1))
                fg_ratio  = np.count_nonzero(zone_fg) / zone_area

                vehicle_present = fg_ratio >= FG_THRESHOLD

                if vehicle_present:
                    settle_count += 1
                else:
                    settle_count = 0

                now = time.time()
                if settle_count >= SETTLE_FRAMES and (now - last_trigger) >= TRIGGER_COOLDOWN_SEC:
                    # Car is centred and steady – take the snapshot
                    snap_frame = frame.copy()
                    snapped    = True
                    settle_count = 0
                    logger.info("Vehicle centred – snapping frame for OCR...")

                # ── Overlay: zone box + presence indicator ────────────────
                colour = (0, 220, 0) if vehicle_present else (0, 120, 255)
                cv2.rectangle(display, (zx1, zy1), (zx2, zy2), colour, 2)

                bar_w = int(min(fg_ratio / FG_THRESHOLD, 1.0) * (zx2 - zx1))
                cv2.rectangle(display, (zx1, zy2 + 8), (zx2, zy2 + 20), (40, 40, 40), -1)
                cv2.rectangle(display, (zx1, zy2 + 8), (zx1 + bar_w, zy2 + 20), colour, -1)

                cv2.putText(display, "Drive into the box  |  'q' to quit",
                            (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 220, 0), 2)

                if vehicle_present:
                    cv2.putText(display,
                                f"Vehicle detected – steadying... ({settle_count}/{SETTLE_FRAMES})",
                                (10, h - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 220, 0), 2)
                else:
                    cv2.putText(display, "Scanning...",
                                (10, h - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 120, 255), 2)

            else:
                # ── Show the frozen snapshot and run OCR ──────────────────
                display = snap_frame.copy()
                cv2.rectangle(display, (zx1, zy1), (zx2, zy2), (0, 200, 255), 3)
                cv2.putText(display, "SNAP – reading plate...",
                            (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0, 200, 255), 2)
                cv2.imshow('Gate Camera – ALPR', display)
                cv2.waitKey(1)

                plate, conf = self.read_license_plate(snap_frame)

                if plate:
                    last_trigger = time.time()
                    logger.info(f"Plate detected: {plate}  conf={conf:.2f}")
                    cv2.destroyAllWindows()
                    return plate, snap_frame
                else:
                    # OCR found nothing – show feedback and resume scanning
                    logger.info("Snap: no plate found – resuming scan")
                    cv2.putText(display, "No plate found – reposition",
                                (10, h - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 60, 255), 2)
                    cv2.imshow('Gate Camera – ALPR', display)
                    cv2.waitKey(800)
                    snapped    = False
                    snap_frame = None
                    last_trigger = time.time()  # brief cooldown before next snap
                    continue

            cv2.imshow('Gate Camera – ALPR', display)
            key = cv2.waitKey(1) & 0xFF
            if key == ord('q'):
                logger.info("User quit camera")
                cv2.destroyAllWindows()
                return None, None

    # ── Legacy helper ─────────────────────────────────────────────────────────

    def create_session_from_camera(self, priority_class, selected_zone: str = "ANY"):
        from src.core.plate_hasher import hash_plate
        from src.core import Clock
        from src.models.database import VehicleSession

        plate_number, _frame = self.wait_for_vehicle(timeout=60)
        if not plate_number:
            logger.error("Failed to read license plate")
            return None

        plate_hash = hash_plate(plate_number)
        session_id = str(uuid.uuid4())
        now        = Clock.now()

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

        logger.info(f"Session created for plate {plate_number} -> {session_id[:8]}...")
        return session
