"""
Production Database Initialization - 40 Bay Mall Parking
Optimized for Jetson Nano deployment
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from src.core import config, Clock
from src.models.database import Database, Bay, BayState, PriorityClass
import yaml

print("\n" + "="*70)
print(" PRODUCTION MALL PARKING - 40 BAYS ".center(70))
print("="*70 + "\n")

# Load production config
config_path = 'config/production_config.yaml'
print(f"📋 Loading configuration: {config_path}")

with open(config_path, 'r') as f:
    mall_config = yaml.safe_load(f)

print(f"🏬 Facility: {mall_config['facility_name']}")

# Initialize database
db_path = mall_config['database_path']
print(f"🗄️  Database: {db_path}\n")

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
category_counts = {'GENERAL': 0, 'FAMILY': 0, 'POD': 0, 'STAFF': 0}
zone_summary = {}

for zone_index, zone in enumerate(mall_config['parking_zones'], start=1):
    zone_id = zone['zone_id']
    zone_name = zone['zone_name']
    entrance_id = zone['entrance_id']
    entrance_name = zone['entrance_name']
    entrance_color = zone['entrance_color']
    
    print(f"📍 {zone_name} ({entrance_name})")
    print(f"   Color: {entrance_color}")
    
    zone_bays = []
    
    for bay_config in zone['bays']:
        bay_cat = bay_config['category']
        
        bay = Bay(
            id=bay_config['id'],
            state=BayState.AVAILABLE,
            category=PriorityClass[bay_cat],
            distance_from_gate=bay_config['distance'],
            zone=zone_index,
            zone_name=zone_id,
            entrance_id=entrance_id,
            entrance_name=entrance_name,
            entrance_color=entrance_color,
            coordinates_x=bay_config['x'],
            coordinates_y=bay_config['y'],
            last_update_time=Clock.now(),
            health_score=1.0
        )
        session.add(bay)
        zone_bays.append(bay_config['id'])
        category_counts[bay_cat] += 1
        total_bays += 1
    
    zone_summary[zone_name] = len(zone_bays)
    print(f"   ✅ Created {len(zone_bays)} bays: {', '.join(zone_bays[:4])}...")
    print()

session.commit()

# Summary
print("=" * 70)
print(" DATABASE INITIALIZED SUCCESSFULLY ".center(70))
print("=" * 70)
print(f"\n📊 Summary:")
print(f"   Total Bays: {total_bays}")
print(f"\n📍 By Zone:")
for zone_name, count in zone_summary.items():
    print(f"   • {zone_name:20} {count} bays")

print(f"\n🏷️  By Category:")
for cat, count in category_counts.items():
    pct = (count / total_bays * 100) if total_bays > 0 else 0
    print(f"   • {cat:10} {count:2} bays ({pct:5.1f}%)")

print(f"\n🎯 Entrances:")
for zone in mall_config['parking_zones']:
    print(f"   • {zone['entrance_name']:35} → {zone['zone_name']}")

print(f"\n💡 Configuration:")
print(f"   • Suggestion mode: {mall_config['suggestion_mode']}")
print(f"   • Confirmation timeout: {mall_config['confirmation_timeout_sec']}s")
print(f"   • Map size: {mall_config['map_width']}x{mall_config['map_height']}")

print("\n✅ System ready for Jetson Nano deployment!")
print("="*70 + "\n")

session.close()
