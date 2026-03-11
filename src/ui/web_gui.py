"""
Web GUI Server - Modern parking system interface
Serves a real-time web dashboard showing parking status
"""

from flask import Flask, render_template, jsonify
from flask_socketio import SocketIO, emit
import threading
import time
import logging
from typing import Dict
from sqlalchemy.orm import Session

from src.core import config, Clock, MessageBus
from src.models.database import Database, Bay, BayState

logger = logging.getLogger(__name__)

# Initialize Flask app
app = Flask(__name__)
app.config['SECRET_KEY'] = 'spms_secret_key_2026'
socketio = SocketIO(app, cors_allowed_origins="*")

# Global state
db_session = None
message_bus = None
gui_running = False


def init_gui(session: Session, bus: MessageBus):
    """Initialize the GUI with database and message bus"""
    global db_session, message_bus
    db_session = session
    message_bus = bus
    
    # Subscribe to system events
    message_bus.subscribe("parking/request", on_vehicle_arrival)
    message_bus.subscribe("parking/suggestions/#", on_suggestion)
    message_bus.subscribe("parking/bays/+/state", on_bay_state_change)
    message_bus.subscribe("parking/bays/+/confirmation", on_confirmation)
    
    logger.info("Web GUI initialized")


# Event handlers
def on_vehicle_arrival(topic: str, payload: Dict):
    """Handle vehicle arrival event"""
    socketio.emit('vehicle_arrival', payload)
    logger.debug(f"Vehicle arrival: {payload}")


def on_suggestion(topic: str, payload: Dict):
    """Handle suggestion event"""
    socketio.emit('suggestion', payload)
    logger.debug(f"Suggestion: {payload}")


def on_bay_state_change(topic: str, payload: Dict):
    """Handle bay state change"""
    socketio.emit('bay_state', payload)
    logger.debug(f"Bay state: {payload}")


def on_confirmation(topic: str, payload: Dict):
    """Handle confirmation event"""
    socketio.emit('confirmation', payload)
    logger.debug(f"Confirmation: {payload}")


# Routes
@app.route('/')
def index():
    """Main dashboard page"""
    return render_template('dashboard.html')


@app.route('/api/bays')
def get_bays():
    """API endpoint to get all bay statuses"""
    if db_session is None:
        return jsonify({'error': 'Database not initialized'}), 500
    
    bays = db_session.query(Bay).order_by(Bay.distance_from_gate).all()
    
    bay_data = []
    for bay in bays:
        bay_data.append({
            'id': bay.id,
            'state': bay.state.value,
            'category': bay.category.value,
            'distance': bay.distance_from_gate,
            'zone': bay.zone,
            'lastUpdate': Clock.iso_format(bay.last_update_time) if bay.last_update_time else None,
            'healthScore': bay.health_score
        })
    
    return jsonify(bay_data)


@app.route('/api/stats')
def get_stats():
    """API endpoint to get system statistics"""
    if db_session is None:
        return jsonify({'error': 'Database not initialized'}), 500
    
    bays = db_session.query(Bay).all()
    
    total = len(bays)
    available = sum(1 for b in bays if b.state == BayState.AVAILABLE)
    pending = sum(1 for b in bays if b.state == BayState.PENDING)
    occupied = sum(1 for b in bays if b.state == BayState.UNAVAILABLE)
    
    # Category breakdown
    categories = {}
    for bay in bays:
        cat = bay.category.value
        if cat not in categories:
            categories[cat] = {'total': 0, 'available': 0, 'occupied': 0}
        categories[cat]['total'] += 1
        if bay.state == BayState.AVAILABLE:
            categories[cat]['available'] += 1
        elif bay.state == BayState.UNAVAILABLE:
            categories[cat]['occupied'] += 1
    
    return jsonify({
        'total': total,
        'available': available,
        'pending': pending,
        'occupied': occupied,
        'occupancyRate': round((occupied / total * 100) if total > 0 else 0, 1),
        'categories': categories,
        'timestamp': Clock.iso_format()
    })


@socketio.on('connect')
def handle_connect():
    """Handle client connection"""
    logger.info('Client connected')
    emit('connected', {'data': 'Connected to SPMS'})


@socketio.on('disconnect')
def handle_disconnect():
    """Handle client disconnection"""
    logger.info('Client disconnected')


def run_server(host='127.0.0.1', port=5000, debug=False):
    """Run the Flask web server"""
    global gui_running
    gui_running = True
    logger.info(f"Starting web GUI server at http://{host}:{port}")
    socketio.run(app, host=host, port=port, debug=debug, allow_unsafe_werkzeug=True)


def stop_server():
    """Stop the web server"""
    global gui_running
    gui_running = False
    logger.info("Web GUI server stopped")
