"""
Production Web Server - Multi-Entrance Mall Parking
Serves dashboard and kiosk interfaces for 40-bay system
"""

import logging
import yaml
from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO, emit
from sqlalchemy.orm import Session

from src.core import Clock
from src.models.database import Bay, BayState, VehicleSession, ConfirmationEvent

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

app = Flask(__name__)
app.config['SECRET_KEY'] = 'spms-production-secret'
socketio = SocketIO(app, cors_allowed_origins="*")

# Shared database session and message bus (passed from main)
db_session: Session = None
message_bus = None


def init_system(external_db=None, external_bus=None):
    """Initialize system with shared instances"""
    global db_session, message_bus
    
    if external_db:
        db_session = external_db
    if external_bus:
        message_bus = external_bus
        
        # Subscribe to message bus events
        message_bus.subscribe('parking/bays/+/state', on_bay_state_update)
        message_bus.subscribe('parking/request', on_parking_request)
        message_bus.subscribe('parking/suggestion', on_suggestion)
        message_bus.subscribe('parking/confirmation/+', on_confirmation)
        
        logger.info("✅ Web server initialized with shared bus")


def on_bay_state_update(topic, payload):
    """Handle bay state update"""
    bay_id = payload.get('bayId')
    state = payload.get('state')
    
    logger.info(f"Bay state update received: {bay_id} -> {state}")
    
    socketio.emit('bay_update', {
        'id': bay_id,
        'state': state,
        'timestamp': Clock.now().isoformat()
    }, namespace='/')
    
    logger.info(f"Emitted bay_update for {bay_id} to clients")


def on_parking_request(topic, payload):
    """Handle parking request"""
    session_id = payload.get('sessionId')
    logger.info(f"Parking request received: {session_id}")
    
    socketio.emit('vehicle_arrival', {
        'sessionId': session_id,
        'priority': payload.get('priorityClass')
    }, namespace='/')
    
    logger.info("Emitted vehicle_arrival to clients")


def on_suggestion(topic, payload):
    """Handle suggestion event"""
    bay_id = payload.get('primaryBayId')
    zone = payload.get('zone', '')
    
    logger.info(f"Suggestion received: {bay_id} in {zone}")
    
    socketio.emit('suggestion_issued', {
        'bayId': bay_id,
        'zone': zone,
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
def dashboard():
    """Production dashboard view"""
    return render_template('production_dashboard.html')


@app.route('/kiosk')
def kiosk():
    """Production kiosk view"""
    return render_template('production_kiosk.html')


@app.route('/search')
def search():
    """License plate search page for drivers"""
    return render_template('search.html')


@app.route('/api/bays')
def get_bays():
    """Get all bays with current state"""
    if not db_session:
        return jsonify({'error': 'Database not initialized'}), 500
    
    bays = db_session.query(Bay).all()
    
    return jsonify({
        'bays': {
            bay.id: {
                'id': bay.id,
                'state': bay.state.value if bay.state else 'UNKNOWN',
                'category': bay.category.value if bay.category else 'GENERAL',
                'distance': bay.distance_from_gate,
                'zone': bay.zone,
                'zone_name': bay.zone_name,
                'entrance_id': bay.entrance_id,
                'entrance_name': bay.entrance_name,
                'entrance_color': bay.entrance_color,
                'x': bay.coordinates_x,
                'y': bay.coordinates_y
            }
            for bay in bays
        },
        'timestamp': Clock.now().isoformat()
    })


@app.route('/api/stats')
def get_stats():
    """Get overall statistics"""
    if not db_session:
        return jsonify({'error': 'Database not initialized'}), 500
    
    bays = db_session.query(Bay).all()
    total = len(bays)
    available = sum(1 for b in bays if b.state == BayState.AVAILABLE)
    occupied = total - available
    
    return jsonify({
        'total': total,
        'available': available,
        'occupied': occupied,
        'occupancy_pct': round((occupied / total * 100) if total > 0 else 0, 1),
        'timestamp': Clock.now().isoformat()
    })


@app.route('/api/search-plate')
def search_plate():
    """Search for a vehicle by license plate"""
    plate = request.args.get('plate', '').strip().upper()
    
    if not plate:
        return jsonify({'found': False, 'error': 'No plate provided'})
    
    if not db_session:
        return jsonify({'found': False, 'error': 'Database not initialized'}), 500
    
    try:
        # Find all occupied bays
        occupied_bays = db_session.query(Bay).filter(
            Bay.state == BayState.UNAVAILABLE
        ).all()
        
        # In a real system, we'd search by hashed plate token
        # For this demo, let's check if we can find a matching session
        # We'll do a simple search - in production you'd use proper hashing
        
        # Try to find recent vehicle sessions
        from sqlalchemy import desc
        recent_sessions = db_session.query(VehicleSession).order_by(
            desc(VehicleSession.timestamp_created)
        ).limit(50).all()
        
        # Try to find a confirmation event for any of these sessions
        for session in recent_sessions:
            # Check if plate token contains our search (simplified for demo)
            if plate in session.hashed_plate_token.upper():
                # Find confirmation for this session
                confirmation = db_session.query(ConfirmationEvent).filter(
                    ConfirmationEvent.session_id == session.session_id,
                    ConfirmationEvent.status == 'confirmed'
                ).order_by(desc(ConfirmationEvent.timestamp)).first()
                
                if confirmation:
                    bay = db_session.query(Bay).filter(
                        Bay.bay_id == confirmation.bay_id
                    ).first()
                    
                    if bay:
                        return jsonify({
                            'found': True,
                            'bay': {
                                'bay_id': bay.bay_id,
                                'state': bay.state.value,
                                'category': bay.category.value,
                                'entrance_id': bay.entrance_id,
                                'entrance_name': bay.entrance_name,
                                'entrance_color': bay.entrance_color,
                                'zone_name': bay.zone_name,
                                'coordinates_x': bay.coordinates_x,
                                'coordinates_y': bay.coordinates_y,
                                'distance_from_gate': bay.distance_from_gate
                            },
                            'session': {
                                'session_id': session.session_id,
                                'timestamp_created': session.timestamp_created.isoformat(),
                                'priority_class': session.priority_class.value
                            }
                        })
        
        return jsonify({'found': False})
        
    except Exception as e:
        logger.error(f"Search error: {e}")
        return jsonify({'found': False, 'error': str(e)}), 500


@socketio.on('connect')
def handle_connect():
    """Handle client connection"""
    logger.info('Client connected')
    
    # Send initial state (force fresh read from database)
    if db_session:
        try:
            # Force refresh session to get latest data
            db_session.expire_all()
            
            bays = db_session.query(Bay).all()
            bays_data = {
                'bays': {
                    bay.id: {
                        'id': bay.id,
                        'state': bay.state.value if bay.state else 'UNKNOWN',
                        'category': bay.category.value if bay.category else 'GENERAL',
                        'distance': bay.distance_from_gate,
                        'zone': bay.zone,
                        'zone_name': bay.zone_name,
                        'entrance_id': bay.entrance_id,
                        'entrance_name': bay.entrance_name,
                        'entrance_color': bay.entrance_color,
                        'x': bay.coordinates_x,
                        'y': bay.coordinates_y
                    }
                    for bay in bays
                },
                'timestamp': Clock.now().isoformat()
            }
            
            logger.info(f"Sending initial state: {len(bays)} bays")
            emit('initial_state', bays_data)
        except Exception as e:
            logger.error(f"Error sending initial state: {e}")


@socketio.on('disconnect')
def handle_disconnect():
    """Handle client disconnection"""
    logger.info('Client disconnected')


def run_server(host='0.0.0.0', port=5000):
    """Run the web server"""
    logger.info(f"🌐 Starting production web server on {host}:{port}")
    socketio.run(app, host=host, port=port, debug=False, allow_unsafe_werkzeug=True)
