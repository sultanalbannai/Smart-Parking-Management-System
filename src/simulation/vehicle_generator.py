"""
Vehicle Generator - Simulates vehicle arrivals
Generates synthetic vehicles with random plates and priorities
"""

import random
import string
import uuid
from typing import Optional
from dataclasses import dataclass
from datetime import datetime

from ..core import Clock, config
from ..core.plate_hasher import hash_plate
from ..models.database import PriorityClass


@dataclass
class SimulatedVehicle:
    """Represents a simulated vehicle"""
    session_id: str
    plate_number: str  # Raw plate (for simulation only)
    plate_hash: str    # Hashed plate (used by system)
    priority_class: PriorityClass
    arrival_time: datetime
    compliance_rate: float  # 0.0-1.0, likelihood to follow suggestion
    
    def __repr__(self):
        return f"Vehicle({self.plate_number}, {self.priority_class.value})"


class VehicleGenerator:
    """
    Generates simulated vehicles with realistic characteristics.
    Creates random license plates and assigns priority classes.
    """
    
    # UAE plate patterns (simplified)
    PLATE_PATTERNS = [
        ("A", 1, 4),   # A 1234
        ("AA", 2, 4),  # AA 1234
        ("AB", 2, 4),  # AB 1234
    ]
    
    def __init__(self, seed: Optional[int] = None):
        """
        Initialize vehicle generator.
        
        Args:
            seed: Random seed for reproducible simulations
        """
        if seed is not None:
            random.seed(seed)
        
        self.vehicle_count = 0
        
        # Priority distribution (realistic)
        # 70% GENERAL, 20% STAFF, 10% POD
        self.priority_weights = {
            PriorityClass.GENERAL: 0.70,
            PriorityClass.STAFF: 0.20,
            PriorityClass.POD: 0.10,
        }
        
        # Compliance rate (how likely to follow suggestion)
        # 60% compliant, 40% park elsewhere
        self.compliance_mean = 0.60
        self.compliance_std = 0.15
    
    def generate_plate(self) -> str:
        """
        Generate a random license plate.
        
        Returns:
            str: Random plate number (e.g., "AB 1234")
        """
        # Choose random pattern
        letter_prefix, num_letters, num_digits = random.choice(self.PLATE_PATTERNS)
        
        # Generate letters
        letters = ''.join(random.choices(string.ascii_uppercase, k=num_letters))
        
        # Generate digits
        digits = ''.join(random.choices(string.digits, k=num_digits))
        
        return f"{letters} {digits}"
    
    def generate_priority(self) -> PriorityClass:
        """
        Generate a random priority class based on realistic distribution.
        
        Returns:
            PriorityClass: Random priority
        """
        priorities = list(self.priority_weights.keys())
        weights = list(self.priority_weights.values())
        
        return random.choices(priorities, weights=weights)[0]
    
    def generate_compliance_rate(self) -> float:
        """
        Generate compliance rate (likelihood to follow suggestion).
        
        Returns:
            float: Compliance rate between 0.0 and 1.0
        """
        rate = random.gauss(self.compliance_mean, self.compliance_std)
        return max(0.0, min(1.0, rate))  # Clamp to [0, 1]
    
    def generate_vehicle(self) -> SimulatedVehicle:
        """
        Generate a complete simulated vehicle.
        
        Returns:
            SimulatedVehicle: New vehicle with random characteristics
        """
        self.vehicle_count += 1
        
        # Generate characteristics
        plate_number = self.generate_plate()
        priority_class = self.generate_priority()
        compliance_rate = self.generate_compliance_rate()
        
        # Create session ID
        session_id = str(uuid.uuid4())
        
        # Hash the plate
        plate_hash = hash_plate(plate_number, session_id)
        
        # Create vehicle
        vehicle = SimulatedVehicle(
            session_id=session_id,
            plate_number=plate_number,
            plate_hash=plate_hash,
            priority_class=priority_class,
            arrival_time=Clock.now(),
            compliance_rate=compliance_rate
        )
        
        return vehicle
    
    def generate_batch(self, count: int) -> list[SimulatedVehicle]:
        """
        Generate a batch of vehicles.
        
        Args:
            count: Number of vehicles to generate
            
        Returns:
            list: List of SimulatedVehicle objects
        """
        return [self.generate_vehicle() for _ in range(count)]
    
    def set_priority_distribution(self, pod: float, staff: float, general: float):
        """
        Set custom priority distribution.
        
        Args:
            pod: Percentage for POD (0.0-1.0)
            staff: Percentage for STAFF (0.0-1.0)
            general: Percentage for GENERAL (0.0-1.0)
        """
        total = pod + staff + general
        self.priority_weights = {
            PriorityClass.POD: pod / total,
            PriorityClass.STAFF: staff / total,
            PriorityClass.GENERAL: general / total,
        }
    
    def set_compliance_rate(self, mean: float, std: float = 0.15):
        """
        Set compliance rate distribution.
        
        Args:
            mean: Mean compliance rate (0.0-1.0)
            std: Standard deviation
        """
        self.compliance_mean = max(0.0, min(1.0, mean))
        self.compliance_std = std
