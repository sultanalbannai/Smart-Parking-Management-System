"""
Camera Demo Web Server - Single Entrance
Serves camera_dashboard and camera_kiosk views.
Adds 'alpr_scanning' event so the kiosk can show the live scanning state.
"""

import logging
from flask import Flask, render_template, jsonify
from flask_socketio import SocketIO, emit
from sqlalchemy.orm import Session

from src.core import Clock
from src.models.database import Bay, BayState

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

app = Flask(__name__)
app.config['SECRET_KEY'] = 'spms-camera-demo-secret'
socketio = SocketIO(app, cors_allowed_origins="*")

db_session: Session = None
message_bus = None


def init_system(external_db=None, external_bus=None):
    """Initialize with shared DB + message bus instances."""
    global db_session, message_bus

    if external_db:
        db_session = external_db
    if external_bus:
        message_bus = external_bus

        message_bus.subscribe('parking/bays/+/state',         on_bay_state_update)
        message_bus.subscribe('parking/request',              on_parking_request)
        message_bus.subscribe('parking/suggestion',           on_suggestion)
        message_bus.subscribe('parking/bays/+/confirmation',  on_confirmation)
        message_bus.subscribe('alpr/scanning',                on_alpr_scanning)
        message_bus.subscribe('parking/bays/plate_logged',    on_plate_logged)

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
        'bayId':      bay_id,
        'sessionId':  payload.get('sessionId'),
        'priority':   payload.get('priorityClass'),
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
                'y':           bay.coordinates_y
            }
            for bay in bays
        },
        'timestamp': Clock.now().isoformat()
    })


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
    logger.info('Client connected')

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
                        'y':           bay.coordinates_y
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
