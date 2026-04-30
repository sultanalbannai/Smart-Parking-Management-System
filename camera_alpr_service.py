"""
Real Camera ALPR Service - USB Camera Integration
Captures frames from USB camera and performs license plate recognition using EasyOCR.

Detection strategy:
  1. Captures a reference of the empty scene at startup.
  2. Compares every live frame against that reference – car is detected
     even when completely stationary (no background adaption issue).
  3. Waits for the car to stop moving, then snaps ONE frame.
  4. EasyOCR runs once on that snapshot and the plate is returned.
"""

import os
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

def _cuda_available():
    try:
        import torch
        return torch.cuda.is_available()
    except ImportError:
        return False

logger = logging.getLogger(__name__)

# ── Display helpers (self-disabling on first error) ───────────────────────────
# Start optimistic: show windows if DISPLAY is set.  The first cv2.imshow()
# that raises (e.g. SSH session where DISPLAY=:0 is set but not reachable)
# flips _HAS_DISPLAY to False and all subsequent calls become no-ops.
def _headless_forced() -> bool:
    """SPMS_HEADLESS=1 forces all cv2.imshow windows off (production / kiosk)."""
    return os.environ.get('SPMS_HEADLESS', '').strip().lower() in ('1', 'true', 'yes', 'on')


_HAS_DISPLAY: bool = (
    not _headless_forced()
    and (
        os.name == 'nt'
        or bool(os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY'))
    )
)
_display_warned = False


def _imshow(win: str, frame) -> None:
    """cv2.imshow that silently disables itself on the first GTK/display error."""
    global _HAS_DISPLAY, _display_warned
    if not _HAS_DISPLAY:
        return
    try:
        cv2.imshow(win, frame)
    except Exception as exc:
        _HAS_DISPLAY = False
        if not _display_warned:
            _display_warned = True
            logger.warning(f"Display unavailable ({exc}) – switching to headless mode")
        try:
            cv2.destroyAllWindows()
        except Exception:
            pass


def _waitkey(ms: int = 1) -> int:
    """cv2.waitKey that returns –1 (no key pressed) when headless."""
    global _HAS_DISPLAY
    if not _HAS_DISPLAY:
        if ms > 0:
            time.sleep(ms / 1000.0)
        return -1
    try:
        return cv2.waitKey(ms) & 0xFF
    except Exception:
        _HAS_DISPLAY = False
        return -1


def _destroy_all() -> None:
    try:
        cv2.destroyAllWindows()
    except Exception:
        pass
# ─────────────────────────────────────────────────────────────────────────────

# ── Tuning ────────────────────────────────────────────────────────────────────
MIN_CONF            = 0.35   # minimum EasyOCR confidence to accept
TRIGGER_COOLDOWN_SEC = 4.0   # seconds to ignore triggers after one fires

# Centre trigger zone as fractions of (width, height)
ZONE_LEFT   = 0.20
ZONE_RIGHT  = 0.80
ZONE_TOP    = 0.25
ZONE_BOTTOM = 0.75

# Fraction of the zone that must be foreground to fire the snapshot
FG_THRESHOLD = 0.12

# Frames to wait after presence is first detected before snapping
# (lets the car settle into position)
SETTLE_FRAMES = 8
# ─────────────────────────────────────────────────────────────────────────────


def _normalize(text: str) -> str:
    """Strip to digits only."""
    return re.sub(r'[^0-9]', '', text)


def _is_plausible_plate(text: str) -> bool:
    """Accept only pure numeric plates, 2–10 digits."""
    return 2 <= len(text) <= 10 and text.isdigit()


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

        # Latest frame buffer – read by the MJPEG streaming endpoint
        import threading as _t
        self._latest_frame = None
        self._frame_lock   = _t.Lock()

        logger.info("Loading EasyOCR model (first run may take a minute)...")
        _use_gpu = _cuda_available()
        logger.info(f"EasyOCR GPU: {'enabled' if _use_gpu else 'disabled (no CUDA)'}")
        self.reader = easyocr.Reader(['en'], gpu=_use_gpu)
        logger.info(f"Camera ALPR (EasyOCR) initialised for gate {gate_id}")

    # ── Camera lifecycle ──────────────────────────────────────────────────────

    def start_camera(self) -> bool:
        try:
            self.camera = cv2.VideoCapture(self.camera_index)
            if not self.camera.isOpened():
                logger.error(f"Failed to open camera {self.camera_index}")
                return False

            # Low-res / low-FPS capture to minimise CPU on Jetson.
            # Plate OCR is run on a single settled snapshot – high FPS/resolution
            # for the live loop just burns USB bandwidth and decode cycles.
            self.camera.set(cv2.CAP_PROP_FRAME_WIDTH,  640)
            self.camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            self.camera.set(cv2.CAP_PROP_FPS, 15)

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
        if ret and frame is not None:
            with self._frame_lock:
                self._latest_frame = frame
        return frame if ret else None

    def get_latest_frame(self) -> Optional[np.ndarray]:
        """Return a copy of the most recent captured frame (thread-safe)."""
        with self._frame_lock:
            return self._latest_frame.copy() if self._latest_frame is not None else None

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

    def wait_for_vehicle(self, timeout: int = 300,
                         get_bay_frame=None) -> Tuple[Optional[str], Optional[np.ndarray]]:
        """
        Show live camera feed.
        Captures a reference of the empty scene, then compares every frame
        against it – so a stationary car is always detected regardless of
        how long it stays still.
        Snaps ONE frame once the car has stopped moving, runs OCR once.
        Returns (plate_text, frame) or (None, None) if 'q' pressed / timeout.

        get_bay_frame: optional callable() -> np.ndarray
            If provided, its result is shown in a separate window every frame
            so bay cameras and gate camera are both pumped from the main thread.
        """
        if not self.is_camera_ready:
            logger.error("Camera not ready")
            return None, None

        logger.info("Capturing empty-scene reference...")

        # Warm up camera and capture a clean reference of the empty zone
        for _ in range(20):
            self.capture_frame()
        ref_frame = self.capture_frame()
        if ref_frame is None:
            logger.error("Could not capture reference frame")
            return None, None

        h, w = ref_frame.shape[:2]
        zx1  = int(w * ZONE_LEFT)
        zx2  = int(w * ZONE_RIGHT)
        zy1  = int(h * ZONE_TOP)
        zy2  = int(h * ZONE_BOTTOM)
        zone_area = max(1, (zx2 - zx1) * (zy2 - zy1))

        ref_gray = cv2.cvtColor(ref_frame[zy1:zy2, zx1:zx2], cv2.COLOR_BGR2GRAY)
        ref_gray = cv2.GaussianBlur(ref_gray, (5, 5), 0)

        logger.info("Waiting for vehicle – centre-snap mode  |  'q' to quit")

        start_time   = datetime.now()
        last_trigger = 0.0
        settle_count = 0       # frames where car is present AND not moving
        prev_gray    = None    # previous frame's zone (for motion detection)
        snap_frame   = None
        snapped      = False

        # OCR runs in a background thread so the display loop never freezes
        _ocr_result  = [None]   # [plate_or_None]
        _ocr_conf    = [0.0]
        _ocr_running = [False]
        _ocr_done    = [False]

        import threading as _threading

        def _run_ocr(frame_to_read):
            plate, conf = self.read_license_plate(frame_to_read)
            _ocr_result[0] = plate
            _ocr_conf[0]   = conf if conf else 0.0
            _ocr_done[0]   = True
            _ocr_running[0] = False

        BAY_WIN = "Bay Cameras - Live Monitor  |  q = quit"

        while True:
            if (datetime.now() - start_time).seconds > timeout:
                logger.warning("Vehicle detection timeout")
                _destroy_all()
                return None, None

            frame = self.capture_frame()
            if frame is None:
                continue

            display = frame.copy()

            if not snapped:
                zone     = frame[zy1:zy2, zx1:zx2]
                curr_gray = cv2.cvtColor(zone, cv2.COLOR_BGR2GRAY)
                curr_gray = cv2.GaussianBlur(curr_gray, (5, 5), 0)

                # ── 1. Car presence: compare against empty reference ──────
                diff_ref = cv2.absdiff(ref_gray, curr_gray)
                _, thr_ref = cv2.threshold(diff_ref, 25, 255, cv2.THRESH_BINARY)
                fg_ratio = np.count_nonzero(thr_ref) / zone_area

                car_present = fg_ratio >= FG_THRESHOLD

                # ── 2. Motion: compare against previous frame ─────────────
                car_moving = False
                if prev_gray is not None:
                    diff_motion = cv2.absdiff(prev_gray, curr_gray)
                    _, thr_mot  = cv2.threshold(diff_motion, 15, 255, cv2.THRESH_BINARY)
                    motion_ratio = np.count_nonzero(thr_mot) / zone_area
                    car_moving   = motion_ratio >= 0.03   # >3 % pixels changed

                prev_gray = curr_gray

                # Increment settle only when car is present AND still
                if car_present and not car_moving:
                    settle_count += 1
                elif not car_present:
                    settle_count = 0   # car left
                # (keep settle_count if car present but briefly moving)

                now = time.time()
                if settle_count >= SETTLE_FRAMES and (now - last_trigger) >= TRIGGER_COOLDOWN_SEC:
                    snap_frame   = frame.copy()
                    snapped      = True
                    settle_count = 0
                    logger.info("Vehicle settled – snapping frame for OCR...")

                # ── Overlay ───────────────────────────────────────────────
                colour = (0, 220, 0) if car_present else (0, 120, 255)
                cv2.rectangle(display, (zx1, zy1), (zx2, zy2), colour, 2)

                bar_w = int(min(fg_ratio / FG_THRESHOLD, 1.0) * (zx2 - zx1))
                cv2.rectangle(display, (zx1, zy2 + 8), (zx2, zy2 + 20), (40, 40, 40), -1)
                cv2.rectangle(display, (zx1, zy2 + 8), (zx1 + bar_w, zy2 + 20), colour, -1)

                cv2.putText(display, "Drive into the box  |  'q' to quit",
                            (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 220, 0), 2)

                if car_present:
                    status = "Moving..." if car_moving else f"Settling... ({settle_count}/{SETTLE_FRAMES})"
                    cv2.putText(display, status,
                                (10, h - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 220, 0), 2)
                else:
                    cv2.putText(display, "Scanning...",
                                (10, h - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 120, 255), 2)

            else:
                # ── Show frozen snapshot while OCR runs in background ─────
                display = snap_frame.copy()
                cv2.rectangle(display, (zx1, zy1), (zx2, zy2), (0, 200, 255), 3)

                if not _ocr_running[0] and not _ocr_done[0]:
                    # Start OCR thread once
                    _ocr_running[0] = True
                    _threading.Thread(
                        target=_run_ocr, args=(snap_frame.copy(),), daemon=True
                    ).start()

                if _ocr_running[0]:
                    # Animate dots while waiting — window stays responsive
                    dots = '.' * (int(time.time() * 2) % 4)
                    cv2.putText(display, f"Reading plate{dots}",
                                (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0, 200, 255), 2)

                elif _ocr_done[0]:
                    plate = _ocr_result[0]
                    conf  = _ocr_conf[0]
                    if plate:
                        last_trigger = time.time()
                        logger.info(f"Plate detected: {plate}  conf={conf:.2f}")
                        _destroy_all()
                        return plate, snap_frame
                    else:
                        logger.info("Snap: no plate found – resuming scan")
                        cv2.putText(display, "No plate found – reposition",
                                    (10, h - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 60, 255), 2)
                        _imshow('Gate Camera - ALPR', display)
                        if get_bay_frame:
                            try:
                                _imshow(BAY_WIN, get_bay_frame())
                            except Exception:
                                pass
                        _waitkey(800)
                        snapped        = False
                        snap_frame     = None
                        _ocr_done[0]   = False
                        _ocr_result[0] = None
                        last_trigger   = time.time()
                        continue

            # ── Per-frame display ─────────────────────────────────────────
            _imshow('Gate Camera - ALPR', display)
            if get_bay_frame:
                try:
                    _imshow(BAY_WIN, get_bay_frame())
                except Exception:
                    pass
            key = _waitkey(1)
            if key == ord('q'):
                logger.info("User quit camera")
                _destroy_all()
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
