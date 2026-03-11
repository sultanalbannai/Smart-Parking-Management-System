"""
Quick test for Web GUI WebSocket connectivity
Tests that events flow from simulation to web interface
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.core import config, Clock, MessageBus
from src.models.database import Database, BayState
from src.services.occupancy import OccupancyService

print("\n" + "="*60)
print(" WEB GUI CONNECTIVITY TEST ".center(60))
print("="*60 + "\n")

# Initialize
config.load('config/default_config.yaml')
db = Database(f"sqlite:///{config.database_path}")
session = db.get_session()
bus = MessageBus()
bus.connect()

print("✅ System initialized")
print("✅ Message bus connected")

# Test message bus
test_received = []

def test_callback(topic, payload):
    test_received.append((topic, payload))
    print(f"  📨 Received: {topic} -> {payload.get('bayId', 'N/A')}")

bus.subscribe("parking/bays/+/state", test_callback)
print("✅ Subscribed to bay state updates")

# Create occupancy service and trigger an update
occupancy = OccupancyService(session, bus)
print("✅ Occupancy service created")

print("\n🧪 Testing message bus...")
print("Triggering bay state change: B-01 -> UNAVAILABLE")

occupancy.update_bay_occupancy('B-01', BayState.UNAVAILABLE)

time.sleep(0.5)

if test_received:
    print(f"✅ Message bus working! Received {len(test_received)} messages")
else:
    print("❌ No messages received - message bus may have issues")

print("\n" + "="*60)
print(" TEST COMPLETE ".center(60))
print("="*60)
print("\nIf test passed, the web GUI should update in real-time.")
print("If test failed, check:")
print("  1. Database initialized (python init_db.py)")
print("  2. Message bus implementation")
print("\n")

bus.disconnect()
session.close()
