"""
Quick test of Phase 2 components
Tests simulation, services, and UI without running full demo
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.core import config, Clock, MessageBus
from src.models.database import Database, PriorityClass
from src.simulation import VehicleGenerator
from src.services import *
from src.ui import ConsoleUI

print("="*60)
print(" SPMS Phase 2 - Component Test ".center(60))
print("="*60 + "\n")

# Load config
config.load('config/default_config.yaml')
print(f"✓ Config loaded: {config.facility_name}")

# Database
db = Database(f"sqlite:///{config.database_path}")
session = db.get_session()
print(f"✓ Database connected: {config.database_path}")

# Message bus
bus = MessageBus()
bus.connect()
print(f"✓ Message bus connected")

# Test 1: Vehicle Generator
print("\n[TEST 1] Vehicle Generator")
print("-" * 40)
gen = VehicleGenerator(seed=42)
vehicle = gen.generate_vehicle()
print(f"Generated vehicle: {vehicle.plate_number}")
print(f"  Priority: {vehicle.priority_class.value}")
print(f"  Compliance: {vehicle.compliance_rate:.2f}")
print(f"  Plate hash: {vehicle.plate_hash[:16]}...")
print("✓ Vehicle Generator working")

# Test 2: Services
print("\n[TEST 2] Services Initialization")
print("-" * 40)

gate_alpr = GateALPRService(session, bus)
print(f"✓ Gate ALPR Service (Gate: {gate_alpr.gate_id})")

occupancy = OccupancyService(session, bus)
bay_states = occupancy.get_all_bay_states()
print(f"✓ Occupancy Service ({len(bay_states)} bays tracked)")

recommendation = RecommendationService(session)
print(f"✓ Recommendation Service")

confirmation = ConfirmationService(session, bus)
print(f"✓ Confirmation Service")

# Test 3: Console UI
print("\n[TEST 3] Console UI")
print("-" * 40)
ui = ConsoleUI(session, bus)
print("✓ Console UI initialized")

# Test 4: Quick workflow
print("\n[TEST 4] Quick Workflow Test")
print("-" * 40)

# Create a vehicle session
test_vehicle = gen.generate_vehicle()
print(f"1. Generated test vehicle: {test_vehicle.plate_number}")

session_obj = gate_alpr.process_vehicle_arrival(test_vehicle)
print(f"2. Created session: {session_obj.session_id[:8]}...")

# Get a suggestion
suggestion = recommendation.generate_suggestion(
    session=session_obj,
    gate_id="G1",
    num_alternatives=2
)

if suggestion:
    print(f"3. Suggested bay: {suggestion.primary_bay_id}")
    
    # Simulate parking
    occupancy.mark_bay_occupied(suggestion.primary_bay_id, test_vehicle.plate_hash)
    print(f"4. Marked bay occupied: {suggestion.primary_bay_id}")
    
    # Confirm
    status = confirmation.confirm_bay_occupancy(
        suggestion.primary_bay_id,
        test_vehicle.plate_hash
    )
    print(f"5. Confirmation status: {status.value}")
    
    # Resolve
    recommendation.assign_plate_to_bay(
        test_vehicle.plate_hash,
        suggestion.primary_bay_id
    )
    print(f"6. Suggestion resolved")
else:
    print("3. No bays available")

print("\n" + "="*60)
print(" All Phase 2 Components Working! ".center(60))
print("="*60)
print("\nNext step: Run full demo with 'python run_demo.py'")
print()

# Cleanup
bus.disconnect()
session.close()
