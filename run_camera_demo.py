"""
Camera ALPR Demo - Single Entrance + 3 Bay Cameras
====================================================
Gate camera  (camera_index = 0 by default, separate from bay cameras):
  Reads license plates at the entrance, assigns a bay, shows on kiosk.

Bay cameras  (camera_index 0/1/2 as configured in camera_demo_config.yaml):
  Run in background threads; use YOLOv8 to detect occupancy in each bay's
  ROI and EasyOCR to log the plate at the bay.

Usage:
  1. python init_camera_db.py          # first time only
  2. python calibrate_bay_rois.py      # draw ROIs for each bay camera
  3. python run_camera_demo.py

Press 'q' in the gate-camera window to quit.
"""

import sys
import time
import uuid
import queue
import threading
import webbrowser
import logging
from pathlib import Path
from datetime import timedelta

sys.path.insert(0, str(Path(__file__).parent))

from src.core import Clock
from src.core.plate_hasher import hash_plate
from src.core.simple_message_bus import MessageBus
from src.models.database import Database, Bay, BayState, PriorityClass, VehicleSession
from src.services.recommendation import RecommendationService
from src.services.occupancy import OccupancyService
from src.services.confirmation import ConfirmationService

from camera_alpr_service import CameraALPRService
from bay_camera_service import load_bay_cameras

import os
import cv2
import numpy as np
import yaml

def _has_display() -> bool:
    """
    Return True only when OpenCV can actually open a GUI window.
    Probes for real so that SSH sessions with a stale DISPLAY variable
    (common on Jetson) are correctly treated as headless.
    """
    if os.name == 'nt':
        return True
    if not (os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY')):
        return False
    try:
        cv2.namedWindow('__probe__', cv2.WINDOW_NORMAL)
        cv2.destroyWindow('__probe__')
        return True
    except Exception:
        return False

_HAS_DISPLAY = _has_display()

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s  %(levelname)-7s  %(name)s  %(message)s'
)
logging.getLogger('werkzeug').setLevel(logging.WARNING)
logging.getLogger('socketio').setLevel(logging.WARNING)
logging.getLogger('engineio').setLevel(logging.WARNING)
logging.getLogger('ultralytics').setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

CONFIG_PATH   = 'config/camera_demo_config.yaml'
BAY_ROIS_PATH = 'config/bay_rois.yaml'
GATE_ID       = 'GATE_MAIN'

# Read gate camera index from config (set via calibrate_bay_rois.py)
with open(CONFIG_PATH, encoding='utf-8') as _f:
    _cfg = yaml.safe_load(_f)
GATE_CAM_IDX = _cfg.get('gate_camera', {}).get('camera_index', 0)


# ── Web server ────────────────────────────────────────────────────────────────

def run_web_server(db_session, bus, priority_queue):
    import web_server_camera
    web_server_camera.init_system(external_db=db_session, external_bus=bus,
                                  priority_queue=priority_queue)
    web_server_camera.run_server(host='0.0.0.0', port=5000)


# ── Gate-camera: one vehicle cycle ───────────────────────────────────────────

PRIORITY_MAP = {
    'GENERAL': PriorityClass.GENERAL,
    'POD':     PriorityClass.POD,
    'STAFF':   PriorityClass.STAFF,
}


BAY_MON_WIN = "Bay Cameras - Live Monitor  |  q = quit"
TILE_W, TILE_H = 640, 360


def _build_bay_tiles(bay_cam_services) -> np.ndarray:
    """
    Build a tiled image of all bay camera feeds (does NOT call imshow/waitKey).
    Safe to call from any thread; imshow must be called from the main thread only.
    """
    tiles = []
    for svc in bay_cam_services:
        frame = svc.get_latest_frame()
        if frame is None:
            frame = np.zeros((TILE_H, TILE_W, 3), dtype=np.uint8)
            cv2.putText(frame, f"{svc.label} – no feed",
                        (20, TILE_H // 2), cv2.FONT_HERSHEY_SIMPLEX,
                        0.7, (100, 100, 100), 2)
        else:
            frame = cv2.resize(frame, (TILE_W, TILE_H))

        orig_h, orig_w = 720, 1280
        sx, sy = TILE_W / orig_w, TILE_H / orig_h

        for bay_id in svc.bay_ids:
            roi = svc.rois.get(bay_id)
            if roi:
                x1, y1, x2, y2 = roi
                tx1 = int(x1 * sx); ty1 = int(y1 * sy)
                tx2 = int(x2 * sx); ty2 = int(y2 * sy)
                occupied = svc._current_state.get(bay_id, False)
                colour   = (0, 0, 220) if occupied else (0, 220, 0)
                status   = "OCCUPIED" if occupied else "AVAILABLE"
                cv2.rectangle(frame, (tx1, ty1), (tx2, ty2), colour, 3)
                cv2.putText(frame, f"{bay_id}: {status}",
                            (tx1, max(ty1 - 8, 16)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.65, colour, 2)

        cv2.putText(frame, svc.label, (10, 24),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
        tiles.append(frame)

    n = len(tiles)
    if n == 0:
        return np.zeros((TILE_H, TILE_W, 3), dtype=np.uint8)
    if n == 1:
        return tiles[0]
    if n == 2:
        return np.hstack(tiles)
    cols = 2
    while len(tiles) % cols:
        tiles.append(np.zeros((TILE_H, TILE_W, 3), dtype=np.uint8))
    rows = [np.hstack(tiles[i:i+cols]) for i in range(0, len(tiles), cols)]
    return np.vstack(rows)


def process_one_vehicle(camera, db_session, bus, recommendation,
                        occupancy, confirmation, vehicle_number,
                        priority_queue: queue.Queue,
                        bay_cam_services=None) -> bool:
    """
    Auto-detect one plate at the gate, assign best bay, park after delay.
    Returns True to keep running, False to stop.
    """
    print(f"\n{'='*60}")
    print(f"  Vehicle #{vehicle_number} – waiting for plate at gate…")
    print(f"  (auto-detect active  |  'q' to quit)")
    print(f"{'='*60}\n")

    bus.publish('alpr/scanning', {'status': 'scanning', 'vehicle': vehicle_number})

    # Bay frame callback – called by gate camera display loop so bay cams
    # render in the SAME thread (avoids OpenCV multi-thread deadlock on Windows)
    get_bay_frame = (lambda: _build_bay_tiles(bay_cam_services)) if bay_cam_services else None

    plate_number, _frame = camera.wait_for_vehicle(timeout=300, get_bay_frame=get_bay_frame)

    if plate_number is None:
        logger.info("Gate camera: quit or timeout")
        return False

    print(f"\n🚗 Gate plate: {plate_number}")

    print("⏳ Waiting for driver to select priority on kiosk…")

    # Drain any stale value left from a previous round
    while not priority_queue.empty():
        try:
            priority_queue.get_nowait()
        except queue.Empty:
            break

    # Keep re-publishing plate_detected every 2 s so the kiosk always shows
    # the priority screen even if it missed the first event
    stop_repeat = threading.Event()
    def _repeat():
        while not stop_repeat.is_set():
            bus.publish('alpr/plate_detected', {'plate': plate_number, 'vehicle': vehicle_number})
            stop_repeat.wait(timeout=2.0)
    threading.Thread(target=_repeat, daemon=True).start()

    # Poll for priority while pumping bay camera display from the MAIN thread
    priority_str = None
    deadline = time.time() + 180
    try:
        while time.time() < deadline:
            try:
                priority_str = priority_queue.get(timeout=0.033)
                break
            except queue.Empty:
                pass
            if bay_cam_services and _HAS_DISPLAY:
                cv2.imshow(BAY_MON_WIN, _build_bay_tiles(bay_cam_services))
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    stop_repeat.set()
                    return False
    finally:
        stop_repeat.set()

    if priority_str is None:
        priority_str = 'GENERAL'
        print("⚠️  No priority selected in time – defaulting to GENERAL")

    priority_class = PRIORITY_MAP.get(priority_str.upper(), PriorityClass.GENERAL)
    print(f"✅ Priority: {priority_class.value}")

    # Session
    session_id = str(uuid.uuid4())
    plate_hash = hash_plate(plate_number, session_id)
    now        = Clock.now()

    session = VehicleSession(
        session_id        = session_id,
        gate_id           = GATE_ID,
        plate_hash        = plate_hash,
        priority_class    = priority_class,
        selected_entrance = 'ENTRANCE_ANY',
        selected_zone     = 'ANY',
        created_at        = now,
        expires_at        = now + timedelta(hours=4)
    )
    db_session.add(session)
    db_session.commit()

    bus.publish('parking/request', {
        'sessionId':     session_id,
        'gateId':        GATE_ID,
        'priorityClass': priority_class.value,
        'timestamp':     Clock.timestamp_ms()
    })

    # Recommendation – if selected priority is full, fall back to GENERAL
    suggestion = recommendation.generate_suggestion(
        session=session, gate_id=GATE_ID, num_alternatives=2
    )

    if not suggestion and priority_class != PriorityClass.GENERAL:
        print(f"⚠️  No {priority_class.value} bays available – falling back to GENERAL")
        session.priority_class = PriorityClass.GENERAL
        db_session.commit()
        suggestion = recommendation.generate_suggestion(
            session=session, gate_id=GATE_ID, num_alternatives=2
        )

    if not suggestion:
        print("⚠️  No available bays – lot may be full!")
        bus.publish('parking/full', {'sessionId': session_id})
        return True

    primary_bay = db_session.query(Bay).filter(Bay.id == suggestion.primary_bay_id).first()
    alt_ids     = suggestion.alternative_bay_ids.split(',') if suggestion.alternative_bay_ids else []

    print(f"💡 Suggested: {suggestion.primary_bay_id}"
          + (f"  ({primary_bay.distance_from_gate}m)" if primary_bay else ""))
    if alt_ids:
        print(f"   Alternatives: {', '.join(alt_ids)}")

    bus.publish('parking/suggestion', {
        'sessionId':         session_id,
        'primaryBayId':      suggestion.primary_bay_id,
        'alternativeBayIds': alt_ids,
        'priorityClass':     priority_class.value,
        'plate':             plate_number,
        'distance':          primary_bay.distance_from_gate if primary_bay else 0,
        'category':          primary_bay.category.value if primary_bay else 'GENERAL',
    })

    # Bay cameras handle occupancy via the live monitor window.
    print(f"\n✅ Suggestion issued – bay cameras will confirm when car arrives at {suggestion.primary_bay_id}")
    return True


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("\n" + "="*60)
    print(" SMART PARKING – CAMERA ALPR DEMO ".center(60))
    print("="*60 + "\n")

    with open(CONFIG_PATH, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    print(f"🏬 {cfg['facility_name']}")
    print(f"🗄️  DB: {cfg['database_path']}")
    if not _HAS_DISPLAY:
        print("ℹ️  No display detected – running headless (no OpenCV preview windows)\n")
    else:
        print()

    # Database
    db      = Database(f"sqlite:///{cfg['database_path']}")
    session = db.get_session()

    bay_count = session.query(Bay).count()
    if bay_count == 0:
        print("⚠️  No bays in DB – run:  python init_camera_db.py\n")
        session.close()
        return
    print(f"✅ {bay_count} bays loaded")

    # Message bus + services
    bus            = MessageBus()
    bus.connect()
    recommendation = RecommendationService(session)
    occupancy      = OccupancyService(session, bus)
    confirmation   = ConfirmationService(session, bus)

    # Priority queue shared between gate loop and web server
    priority_queue = queue.Queue()

    # Web server
    print("\n🌐 Starting web server…")
    threading.Thread(target=run_web_server, args=(session, bus, priority_queue),
                     daemon=True).start()
    time.sleep(2)

    print("📊 Dashboard : http://127.0.0.1:5000")
    print("🖥️  Kiosk     : http://127.0.0.1:5000/kiosk")
    try:
        webbrowser.open('http://127.0.0.1:5000')
        time.sleep(0.5)
        webbrowser.open('http://127.0.0.1:5000/kiosk')
    except Exception:
        pass

    # ── Bay cameras ───────────────────────────────────────────────────────────
    rois_exist = Path(BAY_ROIS_PATH).exists()
    if not rois_exist:
        print(f"\n⚠️  Bay ROI file not found: {BAY_ROIS_PATH}")
        print("   Bay cameras will start but won't detect bays until calibrated.")
        print("   Run:  python calibrate_bay_rois.py\n")

    print("\n📷 Starting bay cameras…")
    bay_cam_services = []
    try:
        bay_cam_services = load_bay_cameras(
            config_path       = CONFIG_PATH,
            rois_path         = BAY_ROIS_PATH,
            occupancy_service = occupancy,
            bus               = bus,
            db_session        = session,
        )
        for svc in bay_cam_services:
            svc.start()
        print(f"✅ {len(bay_cam_services)} bay camera(s) running in background")
        print("✅ Bay monitor will display alongside gate camera (main thread)")
    except Exception as e:
        print(f"⚠️  Bay cameras failed to start: {e}")
        print("   Continuing without bay cameras…")

    # ── Gate camera (entrance ALPR) ───────────────────────────────────────────
    print(f"\n📷 Initializing gate camera (index {GATE_CAM_IDX})…")
    gate_cam = CameraALPRService(
        db_session   = session,
        message_bus  = bus,
        gate_id      = GATE_ID,
        camera_index = GATE_CAM_IDX,
    )

    if not gate_cam.start_camera():
        print(f"❌ Gate camera (index {GATE_CAM_IDX}) not available.")
        print("   Edit GATE_CAM_IDX at the top of this file if needed.")
        for svc in bay_cam_services:
            svc.stop()
        bus.disconnect()
        session.close()
        return

    print("✅ Gate camera ready\n")
    print("="*60)
    print(" HOW TO USE ".center(60))
    print("="*60)
    print("  • Bay cameras run automatically in the background")
    print("  • Gate camera window: point a plate at it → auto-detects")
    print("  • Kiosk shows suggested bay; dashboard shows live occupancy")
    print("  • Press 'q' in the gate camera window to quit")
    print("="*60 + "\n")

    input("Press Enter to start…\n")

    # ── Gate ALPR loop ────────────────────────────────────────────────────────
    vehicle_number = 1
    try:
        while True:
            keep_going = process_one_vehicle(
                camera            = gate_cam,
                db_session        = session,
                bus               = bus,
                recommendation    = recommendation,
                occupancy         = occupancy,
                confirmation      = confirmation,
                vehicle_number    = vehicle_number,
                priority_queue    = priority_queue,
                bay_cam_services  = bay_cam_services,
            )
            if not keep_going:
                break
            vehicle_number += 1
            time.sleep(1)

    except KeyboardInterrupt:
        print("\n\n👋 Interrupted")

    finally:
        if _HAS_DISPLAY:
            cv2.destroyAllWindows()
        gate_cam.stop_camera()
        for svc in bay_cam_services:
            svc.stop()
        bus.disconnect()
        session.close()

    print(f"\n{'='*60}")
    print(f"  Done – {vehicle_number - 1} vehicle(s) processed")
    print("  Dashboard: http://127.0.0.1:5000   (still running)")
    print("  Ctrl+C to stop server")
    print(f"{'='*60}\n")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n👋 Goodbye!\n")


if __name__ == '__main__':
    main()
