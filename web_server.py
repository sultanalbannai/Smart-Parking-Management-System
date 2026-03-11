"""
Web Server for SPMS GUI
Provides modern web-based interface with real-time updates
"""

import sys
import logging
from pathlib import Path
from flask import Flask, render_template, jsonify
from flask_socketio import SocketIO, emit
from threading import Thread
import time

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from src.core import config, Clock, MessageBus
from src.models.database import Database, Bay, BayState

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize Flask app
app = Flask(__name__)
app.config['SECRET_KEY'] = 'spms_secret_key_2026'
socketio = SocketIO(app, cors_allowed_origins="*")

# Global state
db_session = None
message_bus = None
bay_states = {}


def init_system(external_db=None, external_bus=None):
    """Initialize database and message bus"""
    global db_session, message_bus
    
    # Use external instances if provided
    if external_db:
        db_session = external_db
        logger.info("Using external database session")
    else:
        # Load config
        config.load('config/default_config.yaml')
        logger.info(f"Config loaded: {config.facility_name}")
        
        # Initialize database
        db = Database(f"sqlite:///{config.database_path}")
        db_session = db.get_session()
        logger.info("Database connected")
    
    if external_bus:
        message_bus = external_bus
        logger.info("Using external message bus")
    else:
        # Initialize message bus
        message_bus = MessageBus()
        message_bus.connect()
        logger.info("Message bus connected")
    
    # Subscribe to events
    message_bus.subscribe("parking/bays/+/state", on_bay_state_update)
    message_bus.subscribe("parking/request", on_parking_request)
    message_bus.subscribe("parking/suggestions/#", on_suggestion)
    message_bus.subscribe("parking/bays/+/confirmation", on_confirmation)
    
    logger.info("Web server subscribed to message bus events")
    
    # Load initial bay states
    load_bay_states()


def load_bay_states():
    """Load current bay states from database"""
    global bay_states
    
    bays = db_session.query(Bay).all()
    for bay in bays:
        bay_states[bay.id] = {
            'id': bay.id,
            'state': bay.state.value,
            'category': bay.category.value,
            'distance': bay.distance_from_gate,
            'zone': bay.zone,
            'occupiedPlate': bay.occupied_plate_hash[:8] + '...' if bay.occupied_plate_hash else None,
            'lastUpdate': Clock.iso_format(bay.last_update_time) if bay.last_update_time else None
        }
    
    logger.info(f"Loaded {len(bay_states)} bay states")


# Message bus event handlers
def on_bay_state_update(topic, payload):
    """Handle bay state update"""
    bay_id = payload.get('bayId')
    logger.info(f"Bay state update received: {bay_id} -> {payload.get('state')}")
    
    if bay_id in bay_states:
        bay_states[bay_id]['state'] = payload.get('state')
        bay_states[bay_id]['lastUpdate'] = payload.get('updatedAt')
        
        # Broadcast to all connected clients
        socketio.emit('bay_update', bay_states[bay_id], namespace='/')
        logger.info(f"Emitted bay_update for {bay_id} to clients")
    else:
        logger.warning(f"Bay {bay_id} not found in bay_states")


def on_parking_request(topic, payload):
    """Handle parking request"""
    logger.info(f"Parking request received: {payload.get('sessionId')}")
    
    socketio.emit('vehicle_arrival', {
        'sessionId': payload.get('sessionId'),
        'priority': payload.get('priorityClass'),
        'timestamp': payload.get('timestamp')
    }, namespace='/')
    logger.info("Emitted vehicle_arrival to clients")


def on_suggestion(topic, payload):
    """Handle bay suggestion"""
    logger.info(f"Suggestion received: {payload.get('primaryBayId')}")
    
    socketio.emit('suggestion_issued', {
        'sessionId': payload.get('sessionId'),
        'primaryBay': payload.get('primaryBayId'),
        'alternatives': payload.get('alternativeBayIds', []),
        'priority': payload.get('priorityClass')
    }, namespace='/')
    logger.info("Emitted suggestion_issued to clients")


def on_confirmation(topic, payload):
    """Handle confirmation event"""
    logger.info(f"Confirmation received: {payload.get('bayId')} - {payload.get('status')}")
    
    socketio.emit('confirmation', {
        'bayId': payload.get('bayId'),
        'status': payload.get('status')
    }, namespace='/')
    logger.info("Emitted confirmation to clients")


# Flask routes
@app.route('/')
def index():
    """Main dashboard view"""
    return render_template('dashboard.html')


@app.route('/kiosk')
def kiosk():
    """Driver kiosk view"""
    return render_template('kiosk.html')


@app.route('/api/bays')
def get_bays():
    """Get current bay states"""
    return jsonify(list(bay_states.values()))


@app.route('/api/stats')
def get_stats():
    """Get system statistics"""
    total = len(bay_states)
    available = sum(1 for b in bay_states.values() if b['state'] == 'AVAILABLE')
    pending = sum(1 for b in bay_states.values() if b['state'] == 'PENDING')
    occupied = sum(1 for b in bay_states.values() if b['state'] == 'UNAVAILABLE')
    
    return jsonify({
        'total': total,
        'available': available,
        'pending': pending,
        'occupied': occupied,
        'occupancyRate': (occupied / total * 100) if total > 0 else 0
    })


# SocketIO events
@socketio.on('connect')
def handle_connect():
    """Handle client connection"""
    logger.info('Client connected')
    # Send initial bay states
    emit('initial_state', list(bay_states.values()))


@socketio.on('disconnect')
def handle_disconnect():
    """Handle client disconnection"""
    logger.info('Client disconnected')


@socketio.on('request_refresh')
def handle_refresh():
    """Handle refresh request"""
    load_bay_states()
    emit('initial_state', list(bay_states.values()))


def run_server(host='127.0.0.1', port=5000, debug=False):
    """Run the Flask server"""
    init_system()
    logger.info(f"Starting web server on http://{host}:{port}")
    socketio.run(app, host=host, port=port, debug=debug, allow_unsafe_werkzeug=True)


if __name__ == '__main__':
    run_server(debug=True)
