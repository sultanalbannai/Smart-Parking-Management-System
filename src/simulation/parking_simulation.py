"""
Parking Simulation - Orchestrates the complete simulation
Manages vehicle arrivals, parking behavior, and system interaction
"""

import logging
import time
import random
from typing import Optional, Dict
from datetime import datetime, timedelta
from sqlalchemy.orm import Session

from ..core import Clock, config, MessageBus
from ..models.database import Bay, BayState, VehicleSession, Suggestion, SuggestionStatus
from ..services.recommendation import RecommendationService
from ..services.occupancy import OccupancyService
from ..services.gate_alpr import GateALPRService
from ..services.confirmation import ConfirmationService
from .vehicle_generator import VehicleGenerator, SimulatedVehicle

logger = logging.getLogger(__name__)


class ParkingSimulation:
    """
    Complete parking system simulation.
    Generates vehicles, processes them through the system, and simulates parking.
    """
    
    def __init__(self, db_session: Session, message_bus: MessageBus, 
                 speed: float = 1.0, seed: Optional[int] = None):
        """
        Initialize parking simulation.
        
        Args:
            db_session: Database session
            message_bus: Message bus
            speed: Simulation speed multiplier (1.0 = real-time, 2.0 = 2x faster)
            seed: Random seed for reproducibility
        """
        self.db = db_session
        self.bus = message_bus
        self.speed = speed
        
        # Initialize services
        self.gate_alpr = GateALPRService(db_session, message_bus)
        self.occupancy = OccupancyService(db_session, message_bus)
        self.recommendation = RecommendationService(db_session)
        self.confirmation = ConfirmationService(db_session, message_bus)
        self.vehicle_gen = VehicleGenerator(seed=seed)
        
        # Simulation state
        self.running = False
        self.vehicles_processed = 0
        self.active_vehicles: Dict[str, SimulatedVehicle] = {}
        
        # Timing
        self.arrival_interval = 3.0  # Base interval between arrivals (seconds)
        self.parking_delay = 2.0     # Time to reach bay after suggestion (seconds)
    
    def process_vehicle_arrival(self, vehicle: SimulatedVehicle) -> Optional[Suggestion]:
        """
        Process a vehicle arriving at the gate.
        
        Args:
            vehicle: Simulated vehicle
            
        Returns:
            Suggestion: Bay suggestion, or None if no bays available
        """
        logger.info(f"\n{'='*60}")
        logger.info(f"🚗 Vehicle Arrival: {vehicle.plate_number} ({vehicle.priority_class.value})")
        logger.info(f"{'='*60}")
        
        # Step 1: Gate ALPR - create session
        session = self.gate_alpr.process_vehicle_arrival(vehicle)
        
        # Step 2: Recommendation - get bay suggestion
        suggestion = self.recommendation.generate_suggestion(
            session=session,
            gate_id=self.gate_alpr.gate_id,
            num_alternatives=2
        )
        
        if suggestion:
            # Get bay details for zone information
            suggested_bay = self.db.query(Bay).filter(Bay.id == suggestion.primary_bay_id).first()
            
            # Publish suggestion to kiosk
            alternatives = suggestion.alternative_bay_ids.split(',') if suggestion.alternative_bay_ids else []
            
            self.bus.publish(
                topic=f"parking/suggestions/{session.session_id}",
                payload={
                    "sessionId": session.session_id,
                    "primaryBayId": suggestion.primary_bay_id,
                    "alternativeBayIds": alternatives,
                    "priorityClass": session.priority_class.value,
                    "zone": suggested_bay.zone_name if suggested_bay else "UNKNOWN",
                    "entranceName": suggested_bay.entrance_name if suggested_bay else "Unknown",
                    "distance": suggested_bay.distance_from_gate if suggested_bay else 0,
                    "issuedAt": Clock.iso_format(suggestion.issued_at),
                    "expiresAt": Clock.iso_format(suggestion.expires_at)
                }
            )
            
            # Also publish to general suggestion topic for web server
            self.bus.publish(
                topic="parking/suggestion",
                payload={
                    "sessionId": session.session_id,
                    "primaryBayId": suggestion.primary_bay_id,
                    "zone": suggested_bay.zone_name if suggested_bay else "UNKNOWN",
                    "priorityClass": session.priority_class.value
                }
            )
            
            logger.info(f"✅ Suggested bay: {suggestion.primary_bay_id} in {suggested_bay.zone_name if suggested_bay else 'UNKNOWN'} "
                       f"(alternatives: {alternatives if alternatives else 'none'})")
        else:
            logger.warning(f"❌ No available bays for {vehicle.plate_number}")
        
        return suggestion
    
    def simulate_parking(self, vehicle: SimulatedVehicle, suggestion: Optional[Suggestion]):
        """
        Simulate a vehicle parking in a bay.
        Determines if driver follows suggestion or parks elsewhere.
        
        Args:
            vehicle: Simulated vehicle
            suggestion: Bay suggestion (may be None)
        """
        if not suggestion:
            logger.info(f"Vehicle {vehicle.plate_number} cannot park (lot full)")
            return
        
        # Decide which bay to use
        will_comply = random.random() < vehicle.compliance_rate
        
        if will_comply:
            # Park in suggested bay
            chosen_bay_id = suggestion.primary_bay_id
            logger.info(f"✓ Driver follows suggestion → {chosen_bay_id}")
        else:
            # Park in a different available bay
            available_bays = self.db.query(Bay).filter(
                Bay.state == BayState.AVAILABLE,
                Bay.id != suggestion.primary_bay_id
            ).all()
            
            if available_bays:
                chosen_bay = random.choice(available_bays)
                chosen_bay_id = chosen_bay.id
                logger.info(f"⚠ Driver deviates → {chosen_bay_id} (instead of {suggestion.primary_bay_id})")
            else:
                # No other bays available, must use suggested
                chosen_bay_id = suggestion.primary_bay_id
                logger.info(f"✓ Driver uses suggested bay (no alternatives) → {chosen_bay_id}")
        
        # Simulate parking (occupancy detection)
        self.occupancy.mark_bay_occupied(
            bay_id=chosen_bay_id,
            plate_hash=vehicle.plate_hash
        )
        
        # Simulate per-bay ALPR confirmation
        confirmation_status = self.confirmation.confirm_bay_occupancy(
            bay_id=chosen_bay_id,
            plate_hash=vehicle.plate_hash,
            confidence=0.95
        )
        
        # Resolve suggestion based on actual parking
        self.recommendation.assign_plate_to_bay(
            plate_hash=vehicle.plate_hash,
            bay_id=chosen_bay_id
        )
        
        logger.info(f"🅿️ Vehicle parked in {chosen_bay_id} - {confirmation_status.value}")
        
        self.vehicles_processed += 1
    
    def run_scenario(self, num_vehicles: int, arrival_interval: Optional[float] = None):
        """
        Run a complete simulation scenario.
        
        Args:
            num_vehicles: Number of vehicles to simulate
            arrival_interval: Time between arrivals in seconds (None = use default)
        """
        if arrival_interval is None:
            arrival_interval = self.arrival_interval / self.speed
        
        logger.info(f"\n{'#'*60}")
        logger.info(f"# Starting Simulation: {num_vehicles} vehicles")
        logger.info(f"# Arrival interval: {arrival_interval:.1f}s")
        logger.info(f"# Speed: {self.speed}x")
        logger.info(f"{'#'*60}\n")
        
        self.running = True
        self.vehicles_processed = 0
        
        for i in range(num_vehicles):
            if not self.running:
                break
            
            # Generate vehicle
            vehicle = self.vehicle_gen.generate_vehicle()
            
            # Process arrival and get suggestion
            suggestion = self.process_vehicle_arrival(vehicle)
            
            if not suggestion:
                logger.info(f"⚠️ No bays available! Stopping simulation.")
                break
            
            # Wait to give user time to see the suggestion
            logger.info(f"⏱️  Waiting {self.parking_delay / self.speed:.1f}s for driver to reach bay...")
            time.sleep(self.parking_delay / self.speed)
            
            # Park the vehicle
            self.simulate_parking(vehicle, suggestion)
            
            # Small delay after parking to show the update
            time.sleep(0.5)
            
            # Expire any PENDING bays that timed out
            self.recommendation.expire_pending_bays()
            
            # Wait before next arrival (unless last vehicle)
            if i < num_vehicles - 1:
                logger.info(f"⏱️  Waiting {arrival_interval:.1f}s until next vehicle...")
                time.sleep(arrival_interval)
        
        logger.info(f"\n{'#'*60}")
        logger.info(f"# Simulation Complete!")
        logger.info(f"# Vehicles processed: {self.vehicles_processed}")
        logger.info(f"{'#'*60}\n")
        
        self.running = False
    
    def run_until_full(self, arrival_interval: Optional[float] = None, max_vehicles: int = 100):
        """
        Run simulation until parking lot is full.
        
        Args:
            arrival_interval: Time between arrivals in seconds (None = use default)
            max_vehicles: Safety limit to prevent infinite loop
        """
        if arrival_interval is None:
            arrival_interval = self.arrival_interval / self.speed
        
        logger.info(f"\n{'#'*60}")
        logger.info(f"# Starting Simulation: RUN UNTIL FULL")
        logger.info(f"# Arrival interval: {arrival_interval:.1f}s")
        logger.info(f"# Speed: {self.speed}x")
        logger.info(f"# Max vehicles: {max_vehicles}")
        logger.info(f"{'#'*60}\n")
        
        self.running = True
        self.vehicles_processed = 0
        
        for i in range(max_vehicles):
            if not self.running:
                break
            
            # Check if any bays are available
            available_bays = self.db.query(Bay).filter(Bay.state == BayState.AVAILABLE).count()
            
            if available_bays == 0:
                logger.info(f"\n🅿️ PARKING LOT FULL! No more available bays.")
                logger.info(f"✅ Successfully parked {self.vehicles_processed} vehicles")
                break
            
            logger.info(f"\n[Vehicle {i+1}] {available_bays} bays still available")
            
            # Generate vehicle
            vehicle = self.vehicle_gen.generate_vehicle()
            
            # Process arrival and get suggestion
            suggestion = self.process_vehicle_arrival(vehicle)
            
            if not suggestion:
                logger.info(f"⚠️ No bays available! Stopping simulation.")
                break
            
            # Wait to give user time to see the suggestion
            logger.info(f"⏱️  Waiting {self.parking_delay / self.speed:.1f}s for driver to reach bay...")
            time.sleep(self.parking_delay / self.speed)
            
            # Park the vehicle
            logger.info(f"\n{'='*60}")
            logger.info(f"🅿️ PARKING: Vehicle entering bay...")
            logger.info(f"{'='*60}")
            self.simulate_parking(vehicle, suggestion)
            logger.info(f"✅ Bay should now show as OCCUPIED on dashboard")
            logger.info(f"{'='*60}\n")
            
            # Small delay after parking to show the update
            time.sleep(1.0)  # Increased from 0.5 to 1.0 second
            
            # Expire any PENDING bays that timed out
            self.recommendation.expire_pending_bays()
            
            # Wait before next arrival
            logger.info(f"⏱️  Waiting {arrival_interval:.1f}s until next vehicle...")
            time.sleep(arrival_interval)
        
        logger.info(f"\n{'#'*60}")
        logger.info(f"# Simulation Complete!")
        logger.info(f"# Vehicles processed: {self.vehicles_processed}")
        logger.info(f"# Final occupancy: {self.vehicles_processed} vehicles parked")
        logger.info(f"{'#'*60}\n")
        
        self.running = False
    
    def stop(self):
        """Stop the simulation"""
        self.running = False
        logger.info("Simulation stopped")
    
    def get_system_status(self) -> Dict:
        """
        Get current system status.
        
        Returns:
            dict: System status information
        """
        bay_states = self.occupancy.get_all_bay_states()
        
        available = sum(1 for state in bay_states.values() if state == BayState.AVAILABLE)
        pending = sum(1 for state in bay_states.values() if state == BayState.PENDING)
        occupied = sum(1 for state in bay_states.values() if state == BayState.UNAVAILABLE)
        
        active_sessions = len(self.gate_alpr.get_active_sessions())
        
        return {
            "total_bays": len(bay_states),
            "available": available,
            "pending": pending,
            "occupied": occupied,
            "active_sessions": active_sessions,
            "vehicles_processed": self.vehicles_processed,
        }
