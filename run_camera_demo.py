"""
Camera ALPR Demo - Single Entrance
====================================
Replaces the plate generator with a real USB camera.
Flow for each car:
  1. Camera window opens → wait for license plate detection
  2. Plate detected → session created → best bay recommended
  3. Kiosk shows the suggestion
  4. After a short delay the bay is marked occupied
  5. Camera window re-opens for the next car

Usage:
  1. python init_camera_db.py        # First time only
  2. python run_camera_demo.py

Press 'c' in the camera window to confirm detected plate.
Press 'q' in the camera window to quit the demo.
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

# Camera ALPR (lives at project root)
from camera_alpr_service import CameraALPRService

import yaml

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s  %(levelname)-7s  %(name)s  %(message)s'
)
logging.getLogger('werkzeug').setLevel(logging.WARNING)
logging.getLogger('socketio').setLevel(logging.WARNING)
logging.getLogger('engineio').setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

CONFIG_PATH = 'config/camera_demo_config.yaml'
GATE_ID     = 'GATE_MAIN'

# Seconds to wait after a suggestion before marking the bay occupied
# (simulates the driver walking to the bay)
PARK_DELAY = 5.0


# ── Web server thread ─────────────────────────────────────────────────────────

def run_web_server(db_session, bus):
    import web_server_camera
    web_server_camera.init_system(external_db=db_session, external_bus=bus)
    web_server_camera.run_server(host='0.0.0.0', port=5000)


# ── Single-vehicle ALPR → park cycle ─────────────────────────────────────────

def process_one_vehicle(camera: CameraALPRService,
                        db_session,
                        bus: MessageBus,
                        recommendation: RecommendationService,
                        occupancy: OccupancyService,
                        confirmation: ConfirmationService,
                        vehicle_number: int) -> bool:
    """
    Wait for one plate, assign a bay, simulate parking.

    Returns True to keep running, False to stop (user pressed 'q').
    """
    print(f"\n{'='*60}")
    print(f"  Vehicle #{vehicle_number} – waiting for license plate...")
    print(f"  Press 'c' to capture | 'q' to quit")
    print(f"{'='*60}\n")

    # Notify kiosk that we are scanning
    bus.publish('alpr/scanning', {'status': 'scanning', 'vehicle': vehicle_number})

    # ── Camera detection ──────────────────────────────────────────────────────
    plate_number, _frame = camera.wait_for_vehicle(timeout=300)

    if plate_number is None:
        # User pressed 'q' or timeout
        logger.info("Camera scan ended (quit or timeout)")
        return False

    logger.info(f"✅ Plate detected: {plate_number}")
    print(f"\n🚗 Plate detected: {plate_number}")

    # ── Create vehicle session ────────────────────────────────────────────────
    session_id  = str(uuid.uuid4())
    plate_hash  = hash_plate(plate_number, session_id)
    now         = Clock.now()

    session = VehicleSession(
        session_id      = session_id,
        gate_id         = GATE_ID,
        plate_hash      = plate_hash,
        priority_class  = PriorityClass.GENERAL,  # Real ALPR → default GENERAL
        selected_entrance = 'ENTRANCE_ANY',
        selected_zone   = 'ANY',
        created_at      = now,
        expires_at      = now + timedelta(hours=4)
    )
    db_session.add(session)
    db_session.commit()

    # Publish arrival event (web dashboard shows it)
    bus.publish('parking/request', {
        'sessionId':     session_id,
        'gateId':        GATE_ID,
        'priorityClass': PriorityClass.GENERAL.value,
        'timestamp':     Clock.timestamp_ms()
    })

    # ── Bay recommendation ────────────────────────────────────────────────────
    suggestion = recommendation.generate_suggestion(
        session       = session,
        gate_id       = GATE_ID,
        num_alternatives = 2
    )

    if not suggestion:
        print("⚠️  No available bays – parking lot may be full!")
        bus.publish('parking/full', {'sessionId': session_id})
        return True  # keep looping; maybe a bay frees up

    primary_bay = db_session.query(Bay).filter(Bay.id == suggestion.primary_bay_id).first()
    alt_ids     = suggestion.alternative_bay_ids.split(',') if suggestion.alternative_bay_ids else []

    print(f"💡 Suggested bay : {suggestion.primary_bay_id}"
          f"  ({primary_bay.distance_from_gate}m)"
          if primary_bay else f"💡 Suggested bay : {suggestion.primary_bay_id}")
    if alt_ids:
        print(f"   Alternatives  : {', '.join(alt_ids)}")

    # Publish suggestion – kiosk + dashboard receive this
    bus.publish('parking/suggestion', {
        'sessionId':       session_id,
        'primaryBayId':    suggestion.primary_bay_id,
        'alternativeBayIds': alt_ids,
        'priorityClass':   PriorityClass.GENERAL.value,
        'plate':           plate_number,          # shown on kiosk plate badge
        'distance':        primary_bay.distance_from_gate if primary_bay else 0,
        'category':        primary_bay.category.value if primary_bay else 'GENERAL',
    })

    # ── Wait then mark occupied ───────────────────────────────────────────────
    print(f"\n⏳ Waiting {PARK_DELAY:.0f}s (driver walking to bay)...")
    time.sleep(PARK_DELAY)

    # Mark bay occupied (occupancy sensor event)
    occupancy.mark_bay_occupied(
        bay_id     = suggestion.primary_bay_id,
        plate_hash = plate_hash
    )

    # Per-bay ALPR confirmation
    confirmation.confirm_bay_occupancy(
        bay_id     = suggestion.primary_bay_id,
        plate_hash = plate_hash,
        confidence = 0.95
    )

    # Resolve suggestion as fulfilled
    recommendation.assign_plate_to_bay(
        plate_hash = plate_hash,
        bay_id     = suggestion.primary_bay_id
    )

    # Check remaining availability
    db_session.expire_all()
    available = db_session.query(Bay).filter(Bay.state == BayState.AVAILABLE).count()
    total     = db_session.query(Bay).count()

    print(f"\n✅ Bay {suggestion.primary_bay_id} now OCCUPIED")
    print(f"   Remaining: {available}/{total} bays available")

    if available == 0:
        print("\n🅿️  Parking lot FULL")
        return False

    return True


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("\n" + "="*60)
    print(" SMART PARKING – CAMERA ALPR DEMO ".center(60))
    print("="*60 + "\n")

    # Load config
    with open(CONFIG_PATH) as f:
        cfg = yaml.safe_load(f)

    print(f"🏬 Facility : {cfg['facility_name']}")
    print(f"🗄️  Database : {cfg['database_path']}\n")

    # Initialize database
    db = Database(f"sqlite:///{cfg['database_path']}")
    session = db.get_session()

    # Verify DB has bays (prompt to init if empty)
    bay_count = session.query(Bay).count()
    if bay_count == 0:
        print("⚠️  No bays found in database.")
        print("   Please run:  python init_camera_db.py\n")
        session.close()
        return

    print(f"✅ {bay_count} bays loaded from database")

    # Initialize message bus
    bus = MessageBus()
    bus.connect()

    # Initialize services
    recommendation = RecommendationService(session)
    occupancy      = OccupancyService(session, bus)
    confirmation   = ConfirmationService(session, bus)

    # Start web server in background thread
    print("\n🌐 Starting web server...")
    server_thread = threading.Thread(
        target=run_web_server,
        args=(session, bus),
        daemon=True
    )
    server_thread.start()
    time.sleep(2)  # Let Flask start

    # Open browser tabs
    print("📊 Dashboard : http://127.0.0.1:5000")
    print("🖥️  Kiosk     : http://127.0.0.1:5000/kiosk")
    try:
        webbrowser.open('http://127.0.0.1:5000')
        time.sleep(0.5)
        webbrowser.open('http://127.0.0.1:5000/kiosk')
    except Exception:
        print("   (Could not open browser automatically)")

    # Initialize camera
    print("\n📷 Initializing camera...")
    camera = CameraALPRService(
        db_session   = session,
        message_bus  = bus,
        gate_id      = GATE_ID,
        camera_index = 0
    )

    if not camera.start_camera():
        print("❌ Camera not available – check connection (camera_index=0)")
        print("   Exiting.\n")
        bus.disconnect()
        session.close()
        return

    print("✅ Camera ready\n")
    print("="*60)
    print(" HOW TO USE ".center(60))
    print("="*60)
    print("  1. A camera window will open showing the live feed")
    print("  2. Show a license plate to the camera")
    print("  3. When the plate appears on-screen, press 'c' to capture")
    print("  4. The kiosk will show the assigned parking bay")
    print("  5. After the delay the bay is marked occupied")
    print("  6. Repeat for the next car")
    print("  7. Press 'q' in the camera window to quit")
    print("="*60 + "\n")

    input("Press Enter to start scanning...\n")

    # ── Main ALPR loop ────────────────────────────────────────────────────────
    vehicle_number = 1
    try:
        while True:
            keep_going = process_one_vehicle(
                camera         = camera,
                db_session     = session,
                bus            = bus,
                recommendation = recommendation,
                occupancy      = occupancy,
                confirmation   = confirmation,
                vehicle_number = vehicle_number
            )

            if not keep_going:
                break

            vehicle_number += 1
            # Brief pause so the camera window properly closes/reopens
            time.sleep(1)

    except KeyboardInterrupt:
        print("\n\n👋 Interrupted by user")

    finally:
        camera.stop_camera()
        bus.disconnect()
        session.close()

    print("\n" + "="*60)
    print(f"  Session complete – {vehicle_number - 1} vehicle(s) processed")
    print("  Web dashboard still accessible at http://127.0.0.1:5000")
    print("  Press Ctrl+C to stop the server")
    print("="*60 + "\n")

    # Keep server alive for viewing
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n👋 Goodbye!\n")


if __name__ == '__main__':
    main()
