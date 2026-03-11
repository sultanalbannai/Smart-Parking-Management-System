"""
GateALPRService - Simulates gate camera license plate recognition
Creates vehicle sessions when vehicles arrive at the gate
"""

import logging
import random
import uuid
from datetime import datetime, timedelta
from typing import Optional
from sqlalchemy.orm import Session

from ..core import Clock, config, MessageBus
from ..core.plate_hasher import hash_plate
from ..models.database import VehicleSession, PriorityClass
from ..simulation.vehicle_generator import SimulatedVehicle

logger = logging.getLogger(__name__)


class GateALPRService:
    """
    Simulates ALPR at the gate.
    In real system: would capture camera frames and run PaddleOCR
    In simulation: processes SimulatedVehicle arrivals
    """
    
    def __init__(self, db_session: Session, message_bus: MessageBus, gate_id: str = "G1"):
        """
        Initialize gate ALPR service.
        
        Args:
            db_session: Database session
            message_bus: Message bus for publishing events
            gate_id: Gate identifier
        """
        self.db = db_session
        self.bus = message_bus
        self.gate_id = gate_id
        
        # ALPR simulation parameters
        self.recognition_confidence = config.get('simulation.plate_recognition_confidence', 0.92)
        self.processing_delay = 1.0  # Simulated ALPR processing time (seconds)
    
    def process_vehicle_arrival(self, vehicle: SimulatedVehicle, 
                                 selected_entrance: Optional[str] = None,
                                 selected_zone: Optional[str] = None) -> VehicleSession:
        """
        Process a vehicle arrival at the gate.
        Simulates ALPR detection and creates a vehicle session.
        
        Args:
            vehicle: Simulated vehicle arriving at gate
            selected_entrance: Driver's selected entrance (e.g., "ENTRANCE_A" or "ENTRANCE_ANY")
            selected_zone: Driver's selected zone (e.g., "FASHION", "SHOPPING", "FOOD", "ENTERTAINMENT", or "ANY")
            
        Returns:
            VehicleSession: Created session
        """
        now = Clock.now()
        
        # If no zone selected, pick randomly
        if not selected_zone:
            zones = ["FASHION", "SHOPPING", "FOOD", "ENTERTAINMENT", "ANY"]
            selected_zone = random.choice(zones)
        
        # Map zone to entrance
        if not selected_entrance:
            zone_to_entrance = {
                "FASHION": "ENTRANCE_A",
                "SHOPPING": "ENTRANCE_B",
                "FOOD": "ENTRANCE_C",
                "ENTERTAINMENT": "ENTRANCE_D",
                "ANY": "ENTRANCE_ANY"
            }
            selected_entrance = zone_to_entrance.get(selected_zone, "ENTRANCE_ANY")
        
        # Create vehicle session
        session = VehicleSession(
            session_id=vehicle.session_id,
            gate_id=self.gate_id,
            plate_hash=vehicle.plate_hash,
            priority_class=vehicle.priority_class,
            selected_entrance=selected_entrance,
            selected_zone=selected_zone,
            created_at=now,
            expires_at=now + timedelta(hours=4)  # Sessions expire after 4 hours
        )
        
        self.db.add(session)
        self.db.commit()
        
        # Publish session creation event
        self.bus.publish(
            topic="parking/sessions/created",
            payload={
                "sessionId": session.session_id,
                "gateId": self.gate_id,
                "plateHash": session.plate_hash,
                "priorityClass": session.priority_class.value,
                "selectedEntrance": selected_entrance,
                "selectedZone": selected_zone,
                "createdAt": Clock.iso_format(now)
            }
        )
        
        # Publish parking request (triggers recommendation)
        self.bus.publish(
            topic="parking/request",
            payload={
                "sessionId": session.session_id,
                "gateId": self.gate_id,
                "priorityClass": session.priority_class.value,
                "selectedEntrance": selected_entrance,
                "selectedZone": selected_zone,
                "timestamp": Clock.timestamp_ms()
            }
        )
        
        logger.info(f"Vehicle session created: {session.session_id[:8]}... "
                   f"(Zone: {selected_zone}, Priority: {session.priority_class.value}, "
                   f"Plate: {vehicle.plate_number})")
        
        return session
    
    def create_session(self, plate_hash: str, priority_class: PriorityClass,
                      session_id: Optional[str] = None) -> VehicleSession:
        """
        Create a vehicle session manually (for testing).
        
        Args:
            plate_hash: Hashed license plate
            priority_class: Driver priority
            session_id: Optional session ID (generated if not provided)
            
        Returns:
            VehicleSession: Created session
        """
        if session_id is None:
            session_id = str(uuid.uuid4())
        
        now = Clock.now()
        
        session = VehicleSession(
            session_id=session_id,
            gate_id=self.gate_id,
            plate_hash=plate_hash,
            priority_class=priority_class,
            created_at=now,
            expires_at=now + timedelta(hours=4)
        )
        
        self.db.add(session)
        self.db.commit()
        
        # Publish events
        self.bus.publish(
            topic="parking/sessions/created",
            payload={
                "sessionId": session.session_id,
                "gateId": self.gate_id,
                "plateHash": session.plate_hash,
                "priorityClass": session.priority_class.value,
                "createdAt": Clock.iso_format(now)
            }
        )
        
        self.bus.publish(
            topic="parking/request",
            payload={
                "sessionId": session.session_id,
                "gateId": self.gate_id,
                "priorityClass": session.priority_class.value,
                "timestamp": Clock.timestamp_ms()
            }
        )
        
        return session
    
    def get_active_sessions(self) -> list[VehicleSession]:
        """
        Get all active (non-expired) vehicle sessions.
        
        Returns:
            list: Active VehicleSession objects
        """
        now = Clock.now()
        
        sessions = self.db.query(VehicleSession).filter(
            VehicleSession.expires_at > now
        ).all()
        
        return sessions
