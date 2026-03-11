"""
Enhanced Database Initialization - Multi-Entrance Mall Parking
Creates parking layout with multiple entrance zones
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from src.core import config, Clock
from src.models.database import Database, Bay, BayState, PriorityClass
import yaml

print("\n" + "="*70)
print(" INITIALIZING ENHANCED MALL PARKING DATABASE ".center(70))
print("="*70 + "\n")

# Load enhanced config
config_path = 'config/mall_config.yaml'
print(f"📋 Loading configuration from: {config_path}")

with open(config_path, 'r') as f:
    mall_config = yaml.safe_load(f)

# Initialize database
db_path = mall_config['database_path']
print(f"🗄️  Database: {db_path}")

db = Database(f"sqlite:///{db_path}")
session = db.get_session()

# Drop all existing tables and recreate fresh
print("🗑️  Dropping all existing tables...")
db.drop_tables()
print("✅ All tables dropped")

# Create fresh tables
print("🔧 Creating fresh database tables...")
db.create_tables()
print("✅ Fresh database created\n")

# Create bays from config
total_bays = 0
zones_summary = {}

for zone_index, zone in enumerate(mall_config['parking_zones'], start=1):
    zone_id = zone['zone_id']
    zone_name = zone['zone_name']
    entrance_id = zone['entrance_id']
    entrance_name = zone['entrance_name']
    entrance_color = zone['entrance_color']
    
    print(f"\n📍 Zone: {zone_name} ({zone_id})")
    print(f"   Entrance: {entrance_name}")
    
    zone_bays = 0
    
    for bay_config in zone['bays']:
        bay = Bay(
            id=bay_config['id'],
            state=BayState.AVAILABLE,
            category=PriorityClass[bay_config['category']],
            distance_from_gate=bay_config['distance_to_entrance'],
            zone=zone_index,
            zone_name=zone_id,
            entrance_id=entrance_id,
            entrance_name=entrance_name,
            entrance_color=entrance_color,
            coordinates_x=bay_config['coordinates']['x'],
            coordinates_y=bay_config['coordinates']['y'],
            last_update_time=Clock.now(),
            health_score=1.0
        )
        session.add(bay)
        zone_bays += 1
        total_bays += 1
    
    zones_summary[zone_name] = zone_bays
    print(f"   ✅ Created {zone_bays} bays")

session.commit()

# Summary
print("\n" + "="*70)
print(" DATABASE INITIALIZED SUCCESSFULLY ".center(70))
print("="*70)
print(f"\n📊 Summary:")
print(f"   Total bays: {total_bays}")
print(f"\n📍 By Zone:")
for zone_name, count in zones_summary.items():
    print(f"   • {zone_name}: {count} bays")

print(f"\n🎯 Entrances:")
for zone in mall_config['parking_zones']:
    print(f"   • {zone['entrance_name']} → {zone['zone_name']}")

print("\n✅ Ready to use!")
print("="*70 + "\n")

session.close()
