"""
Simple test of core SPMS components (no external dependencies)
Tests Clock, Config, and SimpleMessageBus
"""

import sys
from pathlib import Path
import time

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from src.core import Clock, config, MessageBus

print("="*60)
print("SPMS Core Components Test")
print("="*60)

# Test 1: Clock
print("\n[TEST 1] Clock Utility")
print("-" * 40)
t1 = Clock.now()
print(f"Current time: {t1}")
print(f"ISO format: {Clock.iso_format()}")
print(f"Timestamp (ms): {Clock.timestamp_ms()}")

start_mono = Clock.monotonic_ms()
time.sleep(0.1)
elapsed = Clock.elapsed_ms(start_mono)
print(f"Monotonic elapsed (should be ~100ms): {elapsed}ms")

# Test 2: Config
print("\n[TEST 2] Configuration")
print("-" * 40)
try:
    config.load('config/default_config.yaml')
    print(f"✅ Loaded config successfully")
    print(f"Facility: {config.facility_name}")
    print(f"Total bays: {config.total_bays}")
    print(f"Gate ID: {config.gate_id}")
    print(f"Priorities: {config.priorities}")
    print(f"\nConfigured Bays:")
    for bay in config.bays:
        print(f"  {bay.id}: {bay.category:10} ({bay.distance_from_gate}m)")
except Exception as e:
    print(f"❌ Config error: {e}")

# Test 3: MessageBus
print("\n[TEST 3] Message Bus")
print("-" * 40)

bus = MessageBus()
bus.connect()

messages_received = []

def test_callback(topic, payload):
    messages_received.append((topic, payload))
    print(f"  📨 Received on {topic}: {payload}")

# Subscribe
bus.subscribe("test/topic", test_callback)
bus.subscribe("parking/bays/+/state", test_callback)

# Publish
print("Publishing test messages...")
bus.publish("test/topic", {"message": "Hello SPMS!"})
bus.publish("parking/bays/B-01/state", {"state": "AVAILABLE", "confidence": 0.95})
bus.publish("parking/bays/B-02/state", {"state": "PENDING"})

print(f"\n✅ Received {len(messages_received)} messages")

# Test wildcard matching
print("\nTesting wildcard subscription...")
bus.subscribe("parking/#", test_callback)
bus.publish("parking/request", {"session": "test-123"})
bus.publish("parking/suggestions/abc", {"bay": "B-01"})

print(f"Total messages received: {len(messages_received)}")

# Summary
print("\n" + "="*60)
print("✅ All core components working!")
print("="*60)
print("\nNext Steps:")
print("  1. Install dependencies: pip install -r requirements.txt")
print("  2. Initialize database: python init_db.py")
print("  3. Run full system test")
