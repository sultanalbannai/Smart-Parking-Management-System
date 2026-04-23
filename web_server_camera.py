"""
Camera Demo Web Server - Single Entrance
Serves camera_dashboard and camera_kiosk views.
Adds 'alpr_scanning' event so the kiosk can show the live scanning state.
"""

import logging
from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO, emit
from sqlalchemy.orm import Session

from src.core import Clock
from src.models.database import Bay, BayState
from src.services.alert_service import AlertService

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

app = Flask(__name__)
app.config['SECRET_KEY'] = 'spms-camera-demo-secret'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

db_session: Session = None
message_bus = None
_priority_queue = None          # shared queue – filled when kiosk sends priority_selected
alert_service = AlertService()  # SMS / email notification engine


def init_system(external_db=None, external_bus=None, priority_queue=None):
    """Initialize with shared DB + message bus instances."""
    global db_session, message_bus, _priority_queue

    if external_db:
        db_session = external_db
    if priority_queue is not None:
        _priority_queue = priority_queue
    if external_bus:
        message_bus = external_bus

        message_bus.subscribe('parking/bays/+/state',         on_bay_state_update)
        message_bus.subscribe('parking/request',              on_parking_request)
        message_bus.subscribe('parking/suggestion',           on_suggestion)
        message_bus.subscribe('parking/bays/+/confirmation',  on_confirmation)
        message_bus.subscribe('alpr/scanning',                on_alpr_scanning)
        message_bus.subscribe('alpr/plate_detected',          on_plate_detected)
        message_bus.subscribe('parking/bays/plate_logged',    on_plate_logged)

        alert_service.start()
        logger.info("✅ Camera web server initialized")


# ── Message bus handlers ──────────────────────────────────────────────────────

def on_bay_state_update(topic, payload):
    bay_id = payload.get('bayId')
    state  = payload.get('state')
    logger.info(f"Bay update: {bay_id} → {state}")
    socketio.emit('bay_update', {
        'id':        bay_id,
        'state':     state,
        'timestamp': Clock.now().isoformat()
    }, namespace='/')

    # Check occupancy thresholds and fire alerts if needed
    if db_session:
        try:
            db_session.expire_all()
            bays      = db_session.query(Bay).all()
            total     = len(bays)
            available = sum(1 for b in bays if b.state == BayState.AVAILABLE)
            alert_service.check_occupancy(total=total, available=available)
        except Exception as e:
            logger.warning(f"Alert occupancy check failed: {e}")


def on_parking_request(topic, payload):
    session_id = payload.get('sessionId')
    logger.info(f"Parking request: {session_id}")
    socketio.emit('vehicle_arrival', {
        'sessionId': session_id,
        'priority':  payload.get('priorityClass')
    }, namespace='/')


def on_suggestion(topic, payload):
    bay_id = payload.get('primaryBayId')
    logger.info(f"Suggestion: {bay_id}")

    # Enrich with bay details from DB if available
    extra = {}
    if db_session and bay_id:
        try:
            db_session.expire_all()
            bay = db_session.query(Bay).filter(Bay.id == bay_id).first()
            if bay:
                extra = {
                    'distance': bay.distance_from_gate,
                    'category': bay.category.value if bay.category else 'GENERAL',
                }
        except Exception:
            pass

    socketio.emit('suggestion_issued', {
        'bayId':        bay_id,
        'sessionId':    payload.get('sessionId'),
        'priority':     payload.get('priorityClass'),
        'plate':        payload.get('plate', ''),
        'alternatives': payload.get('alternativeBayIds', []),
        **extra
    }, namespace='/')


def on_confirmation(topic, payload):
    logger.info(f"Confirmation: {payload.get('bayId')} - {payload.get('status')}")
    socketio.emit('confirmation', {
        'bayId':  payload.get('bayId'),
        'status': payload.get('status')
    }, namespace='/')


def on_alpr_scanning(topic, payload):
    """Relayed to kiosk so it can show the 'scanning plate...' state."""
    socketio.emit('alpr_scanning', payload, namespace='/')


def on_plate_detected(topic, payload):
    """Plate confirmed at gate – tell kiosk to show priority selection screen."""
    logger.info(f"Plate detected: {payload.get('plate')}")
    socketio.emit('plate_detected', {'plate': payload.get('plate')}, namespace='/')


@socketio.on('priority_selected')
def handle_priority_selected(data):
    """Kiosk sends the driver's chosen priority; unblock run_camera_demo."""
    priority = data.get('priority', 'GENERAL').upper()
    logger.info(f"Priority selected by driver: {priority}")
    if _priority_queue is not None:
        _priority_queue.put(priority)


def on_plate_logged(topic, payload):
    """Relayed to dashboard activity feed when a bay camera logs a plate."""
    logger.info(f"Plate logged: {payload.get('plate')} at bay {payload.get('bayId')}")
    socketio.emit('plate_logged', {
        'bayId':  payload.get('bayId'),
        'plate':  payload.get('plate'),
        'camera': payload.get('camera'),
        'conf':   payload.get('conf'),
    }, namespace='/')


# ── Flask routes ──────────────────────────────────────────────────────────────

@app.route('/')
def dashboard():
    return render_template('camera_dashboard.html')


@app.route('/kiosk')
def kiosk():
    return render_template('camera_kiosk.html')


@app.route('/search')
def search():
    return render_template('camera_search.html')


@app.route('/api/bays')
def get_bays():
    if not db_session:
        return jsonify({'error': 'DB not ready'}), 500

    db_session.expire_all()
    bays = db_session.query(Bay).all()
    return jsonify({
        'bays': {
            bay.id: {
                'id':          bay.id,
                'state':       bay.state.value if bay.state else 'UNKNOWN',
                'category':    bay.category.value if bay.category else 'GENERAL',
                'distance':    bay.distance_from_gate,
                'zone':        bay.zone,
                'zone_name':   bay.zone_name,
                'entrance_id': bay.entrance_id,
                'entrance_name': bay.entrance_name,
                'entrance_color': bay.entrance_color,
                'x':           bay.coordinates_x,
                'y':           bay.coordinates_y,
                'plate':       bay.parked_plate,
            }
            for bay in bays
        },
        'timestamp': Clock.now().isoformat()
    })


@app.route('/api/bay/<bay_id>')
def get_bay(bay_id):
    """Return full detail for one bay (used by dashboard bay-click popup)."""
    if not db_session:
        return jsonify({'error': 'DB not ready'}), 500

    db_session.expire_all()
    bay = db_session.query(Bay).filter(Bay.id == bay_id).first()
    if not bay:
        return jsonify({'error': 'Bay not found'}), 404

    return jsonify({
        'id':             bay.id,
        'state':          bay.state.value if bay.state else 'UNKNOWN',
        'category':       bay.category.value if bay.category else 'GENERAL',
        'distance':       bay.distance_from_gate,
        'plate':          bay.parked_plate,
        'last_update':    bay.last_update_time.isoformat() if bay.last_update_time else None,
        'occupied_since': bay.occupied_since.isoformat() if bay.occupied_since else None,
    })


@app.route('/api/find_plate/<plate>')
def find_plate(plate):
    """Search which bay a given plate number is currently parked in."""
    if not db_session:
        return jsonify({'error': 'DB not ready'}), 500

    plate = plate.strip().upper()
    db_session.expire_all()
    bay = db_session.query(Bay).filter(Bay.parked_plate == plate).first()

    if bay:
        return jsonify({
            'found':    True,
            'plate':    plate,
            'bayId':    bay.id,
            'category': bay.category.value if bay.category else 'GENERAL',
            'distance': bay.distance_from_gate,
        })
    return jsonify({'found': False, 'plate': plate})


@app.route('/api/alerts/status')
def get_alert_status():
    """Return current alert configuration status (no credentials exposed)."""
    import configparser
    from pathlib import Path
    cfg = configparser.ConfigParser()
    cfg.read(Path(__file__).parent / 'alerts.cfg', encoding='utf-8')

    def gb(section, key):
        try: return cfg.getboolean(section, key)
        except: return False

    return jsonify({
        'email_enabled':        gb('email', 'enabled'),
        'sms_enabled':          gb('sms', 'enabled'),
        'daily_report_enabled': gb('daily_report', 'enabled'),
        'high_threshold':       cfg.getint('thresholds', 'high_occupancy', fallback=80),
        'critical_threshold':   cfg.getint('thresholds', 'critical_occupancy', fallback=90),
        'cooldown_minutes':     cfg.getint('thresholds', 'cooldown_minutes', fallback=30),
    })


@app.route('/api/alerts/test', methods=['POST'])
def test_alert():
    """Send a test alert to verify email/SMS is working."""
    if not db_session:
        return jsonify({'error': 'DB not ready'}), 500

    try:
        bays      = db_session.query(Bay).all()
        total     = len(bays)
        available = sum(1 for b in bays if b.state == BayState.AVAILABLE)
        alert_service.send_daily_report(total=total, available=available)
        return jsonify({'success': True, 'message': 'Test alert sent — check your inbox/phone.'})
    except Exception as e:
        logger.error(f"Test alert failed: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/stats')
def get_stats():
    if not db_session:
        return jsonify({'error': 'DB not ready'}), 500

    bays = db_session.query(Bay).all()
    total     = len(bays)
    available = sum(1 for b in bays if b.state == BayState.AVAILABLE)
    occupied  = total - available

    return jsonify({
        'total':        total,
        'available':    available,
        'occupied':     occupied,
        'occupancy_pct': round((occupied / total * 100) if total > 0 else 0, 1),
        'timestamp':    Clock.now().isoformat()
    })


# ── SocketIO events ───────────────────────────────────────────────────────────

@socketio.on('connect')
def handle_connect():
    logger.info(f'Client connected  (sid={request.sid})')

    if db_session:
        try:
            db_session.expire_all()
            bays = db_session.query(Bay).all()
            emit('initial_state', {
                'bays': {
                    bay.id: {
                        'id':          bay.id,
                        'state':       bay.state.value if bay.state else 'UNKNOWN',
                        'category':    bay.category.value if bay.category else 'GENERAL',
                        'distance':    bay.distance_from_gate,
                        'zone':        bay.zone,
                        'zone_name':   bay.zone_name,
                        'entrance_id': bay.entrance_id,
                        'entrance_name': bay.entrance_name,
                        'entrance_color': bay.entrance_color,
                        'x':           bay.coordinates_x,
                        'y':           bay.coordinates_y,
                        'plate':       bay.parked_plate,
                    }
                    for bay in bays
                },
                'timestamp': Clock.now().isoformat()
            })
        except Exception as e:
            logger.error(f"Error sending initial state: {e}")


@socketio.on('disconnect')
def handle_disconnect():
    logger.info('Client disconnected')


def run_server(host='0.0.0.0', port=5000):
    logger.info(f"🌐 Camera demo web server on {host}:{port}")
    socketio.run(app, host=host, port=port, debug=False, allow_unsafe_werkzeug=True)
