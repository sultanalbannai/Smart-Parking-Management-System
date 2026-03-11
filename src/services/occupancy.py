"""
OccupancyService - Manages bay occupancy state detection
Simulates camera-based occupancy detection with realistic timing
"""

import logging
from typing import Dict, Optional
from datetime import datetime, timedelta
from sqlalchemy.orm import Session

from ..core import Clock, config, MessageBus
from ..models.database import Bay, BayState, OccupancyEvent

logger = logging.getLogger(__name__)


class OccupancyService:
    """
    Simulates occupancy detection for parking bays.
    In real system: would process camera feeds with YOLO
    In simulation: updates bay states based on parking events
    """
    
    def __init__(self, db_session: Session, message_bus: MessageBus):
        """
        Initialize occupancy service.
        
        Args:
            db_session: Database session
            message_bus: Message bus for publishing updates
        """
        self.db = db_session
        self.bus = message_bus
        
        # Bay state cache
        self.bay_states: Dict[str, BayState] = {}
        self.bay_confidences: Dict[str, float] = {}
        
        # Load initial bay states
        self._load_bay_states()
        
        # Detection parameters
        self.detection_confidence = config.get('simulation.occupancy_confidence', 0.95)
        self.detection_delay = 0.5  # Simulated detection delay in seconds
    
    def _load_bay_states(self):
        """Load current bay states from database into cache"""
        bays = self.db.query(Bay).all()
        for bay in bays:
            self.bay_states[bay.id] = bay.state
            self.bay_confidences[bay.id] = bay.health_score
        
        logger.info(f"Loaded {len(bays)} bay states")
    
    def detect_occupancy(self, bay_id: str, actual_state: BayState, 
                        confidence: Optional[float] = None) -> BayState:
        """
        Simulate occupancy detection for a bay.
        
        Args:
            bay_id: Bay identifier
            actual_state: True state of the bay
            confidence: Detection confidence (default: from config)
            
        Returns:
            BayState: Detected state (may differ from actual due to noise)
        """
        if confidence is None:
            confidence = self.detection_confidence
        
        # In simulation, we assume high accuracy
        # Add small chance of misdetection
        detected_state = actual_state
        
        # Update cache
        self.bay_states[bay_id] = detected_state
        self.bay_confidences[bay_id] = confidence
        
        return detected_state
    
    def update_bay_occupancy(self, bay_id: str, new_state: BayState, 
                            confidence: Optional[float] = None,
                            now: Optional[datetime] = None):
        """
        Update bay occupancy state and publish to message bus.
        
        Args:
            bay_id: Bay identifier
            new_state: New occupancy state
            confidence: Detection confidence
            now: Current timestamp (default: Clock.now())
        """
        if now is None:
            now = Clock.now()
        
        if confidence is None:
            confidence = self.detection_confidence
        
        # Get bay from database
        bay = self.db.query(Bay).filter(Bay.id == bay_id).first()
        if not bay:
            logger.error(f"Bay {bay_id} not found")
            return
        
        # Check if state actually changed
        old_state = bay.state
        if old_state == new_state:
            return  # No change, skip update
        
        # Update bay in database
        bay.state = new_state
        bay.last_update_time = now
        
        # If transitioning to AVAILABLE, clear occupancy data
        if new_state == BayState.AVAILABLE:
            bay.occupied_plate_hash = None
            bay.occupied_since = None
            bay.incoming_session_id = None
            bay.incoming_until = None
        
        # Create occupancy event
        event = OccupancyEvent(
            bay_id=bay_id,
            detected_state=new_state,
            confidence=confidence,
            detected_at=now,
            source="occupancy_service"
        )
        
        self.db.add(event)
        self.db.commit()
        
        # Update cache
        self.bay_states[bay_id] = new_state
        
        # Publish state change to message bus
        self.bus.publish(
            topic=f"parking/bays/{bay_id}/state",
            payload={
                "bayId": bay_id,
                "state": new_state.value,
                "previousState": old_state.value if old_state else None,
                "confidence": confidence,
                "updatedAt": Clock.iso_format(now)
            },
            retained=True  # Retain for new subscribers
        )
        
        logger.info(f"Bay {bay_id}: {old_state.value} → {new_state.value} (conf: {confidence:.2f})")
    
    def mark_bay_occupied(self, bay_id: str, plate_hash: str, 
                         now: Optional[datetime] = None):
        """
        Mark a bay as occupied by a specific vehicle.
        Called when a vehicle physically parks.
        
        Args:
            bay_id: Bay identifier
            plate_hash: Hashed plate of parked vehicle
            now: Current timestamp
        """
        if now is None:
            now = Clock.now()
        
        # Update bay state
        self.update_bay_occupancy(bay_id, BayState.UNAVAILABLE, now=now)
        
        # Update bay with plate info
        bay = self.db.query(Bay).filter(Bay.id == bay_id).first()
        if bay:
            bay.occupied_plate_hash = plate_hash
            bay.occupied_since = now
            self.db.commit()
            
            logger.info(f"Bay {bay_id} occupied by vehicle (hash: {plate_hash[:8]}...)")
    
    def mark_bay_vacant(self, bay_id: str, now: Optional[datetime] = None):
        """
        Mark a bay as vacant (vehicle left).
        
        Args:
            bay_id: Bay identifier
            now: Current timestamp
        """
        if now is None:
            now = Clock.now()
        
        self.update_bay_occupancy(bay_id, BayState.AVAILABLE, now=now)
        logger.info(f"Bay {bay_id} now vacant")
    
    def get_bay_state(self, bay_id: str) -> Optional[BayState]:
        """
        Get current state of a bay.
        
        Args:
            bay_id: Bay identifier
            
        Returns:
            BayState or None if bay not found
        """
        return self.bay_states.get(bay_id)
    
    def get_all_bay_states(self) -> Dict[str, BayState]:
        """
        Get states of all bays.
        
        Returns:
            dict: Mapping of bay_id to BayState
        """
        return self.bay_states.copy()
    
    def refresh_from_db(self):
        """Refresh bay state cache from database"""
        self._load_bay_states()
