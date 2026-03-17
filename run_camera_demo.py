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

import yaml

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
GATE_CAM_IDX  = 3   # Use camera index 3 for the gate (entrance) camera
                     # so it does not clash with bay cameras 0/1/2.
                     # Change to 0 if you only have one camera.
PARK_DELAY    = 5.0  # seconds after suggestion before confirming park


# ── Web server ────────────────────────────────────────────────────────────────

def run_web_server(db_session, bus):
    import web_server_camera
    web_server_camera.init_system(external_db=db_session, external_bus=bus)
    web_server_camera.run_server(host='0.0.0.0', port=5000)


# ── Gate-camera: one vehicle cycle ───────────────────────────────────────────

def process_one_vehicle(camera, db_session, bus, recommendation,
                        occupancy, confirmation, vehicle_number) -> bool:
    """
    Auto-detect one plate at the gate, assign best bay, park after delay.
    Returns True to keep running, False to stop.
    """
    print(f"\n{'='*60}")
    print(f"  Vehicle #{vehicle_number} – waiting for plate at gate…")
    print(f"  (auto-detect active  |  'q' to quit)")
    print(f"{'='*60}\n")

    bus.publish('alpr/scanning', {'status': 'scanning', 'vehicle': vehicle_number})

    plate_number, _frame = camera.wait_for_vehicle(timeout=300)

    if plate_number is None:
        logger.info("Gate camera: quit or timeout")
        return False

    print(f"\n🚗 Gate plate: {plate_number}")

    # Session
    session_id = str(uuid.uuid4())
    plate_hash = hash_plate(plate_number, session_id)
    now        = Clock.now()

    session = VehicleSession(
        session_id        = session_id,
        gate_id           = GATE_ID,
        plate_hash        = plate_hash,
        priority_class    = PriorityClass.GENERAL,
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
        'priorityClass': PriorityClass.GENERAL.value,
        'timestamp':     Clock.timestamp_ms()
    })

    # Recommendation
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
        'priorityClass':     PriorityClass.GENERAL.value,
        'plate':             plate_number,
        'distance':          primary_bay.distance_from_gate if primary_bay else 0,
        'category':          primary_bay.category.value if primary_bay else 'GENERAL',
    })

    # Wait, then confirm parking (bay cameras will also detect this independently)
    print(f"\n⏳ {PARK_DELAY:.0f}s delay (driver walking to bay)…")
    time.sleep(PARK_DELAY)

    occupancy.mark_bay_occupied(bay_id=suggestion.primary_bay_id, plate_hash=plate_hash)
    confirmation.confirm_bay_occupancy(
        bay_id=suggestion.primary_bay_id, plate_hash=plate_hash, confidence=0.95
    )
    recommendation.assign_plate_to_bay(plate_hash=plate_hash, bay_id=suggestion.primary_bay_id)

    db_session.expire_all()
    available = db_session.query(Bay).filter(Bay.state == BayState.AVAILABLE).count()
    total     = db_session.query(Bay).count()

    print(f"\n✅ {suggestion.primary_bay_id} OCCUPIED   remaining: {available}/{total}")

    if available == 0:
        print("\n🅿️  Parking lot FULL")
        return False

    return True


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("\n" + "="*60)
    print(" SMART PARKING – CAMERA ALPR DEMO ".center(60))
    print("="*60 + "\n")

    with open(CONFIG_PATH, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    print(f"🏬 {cfg['facility_name']}")
    print(f"🗄️  DB: {cfg['database_path']}\n")

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

    # Web server
    print("\n🌐 Starting web server…")
    threading.Thread(target=run_web_server, args=(session, bus), daemon=True).start()
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
                camera         = gate_cam,
                db_session     = session,
                bus            = bus,
                recommendation = recommendation,
                occupancy      = occupancy,
                confirmation   = confirmation,
                vehicle_number = vehicle_number,
            )
            if not keep_going:
                break
            vehicle_number += 1
            time.sleep(1)

    except KeyboardInterrupt:
        print("\n\n👋 Interrupted")

    finally:
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
