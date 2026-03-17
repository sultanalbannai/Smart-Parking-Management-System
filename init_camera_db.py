"""
Camera Demo Database Initialization - Single Entrance, 16 Bays
Run this once before starting run_camera_demo.py
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from src.core import Clock
from src.models.database import Database, Bay, BayState, PriorityClass
import yaml

print("\n" + "="*60)
print(" CAMERA DEMO - SINGLE ENTRANCE 16 BAYS ".center(60))
print("="*60 + "\n")

config_path = 'config/camera_demo_config.yaml'
print(f"[*] Loading: {config_path}")

with open(config_path, 'r', encoding='utf-8') as f:
    cfg = yaml.safe_load(f)

print(f"[*] Facility: {cfg['facility_name']}")
print(f"[*] Database: {cfg['database_path']}\n")

db = Database(f"sqlite:///{cfg['database_path']}")
session = db.get_session()

print("[*] Dropping existing tables...")
db.drop_tables()
print("[*] Creating fresh tables...")
db.create_tables()

total_bays = 0
category_counts = {'GENERAL': 0, 'POD': 0, 'STAFF': 0, 'FAMILY': 0}

for zone in cfg['parking_zones']:
    zone_id       = zone['zone_id']
    zone_name     = zone['zone_name']
    entrance_id   = zone['entrance_id']
    entrance_name = zone['entrance_name']
    entrance_color = zone['entrance_color']

    for bay_cfg in zone['bays']:
        cat = bay_cfg['category']
        bay = Bay(
            id=bay_cfg['id'],
            state=BayState.AVAILABLE,
            category=PriorityClass[cat],
            distance_from_gate=bay_cfg['distance'],
            zone=1,
            zone_name=zone_id,
            entrance_id=entrance_id,
            entrance_name=entrance_name,
            entrance_color=entrance_color,
            coordinates_x=bay_cfg['x'],
            coordinates_y=bay_cfg['y'],
            last_update_time=Clock.now(),
            health_score=1.0
        )
        session.add(bay)
        category_counts[cat] = category_counts.get(cat, 0) + 1
        total_bays += 1

session.commit()

print(f"\n[OK] Database initialized!")
print(f"\n[*] Summary:")
print(f"   Total bays : {total_bays}")
for cat, count in category_counts.items():
    if count > 0:
        pct = count / total_bays * 100
        print(f"   {cat:8} : {count:2} bays ({pct:.0f}%)")

print(f"\n[*] Entrance: {cfg['parking_zones'][0]['entrance_name']}")
print(f"\n[OK] Ready for camera demo!")
print("   Run: python run_camera_demo.py")
print("="*60 + "\n")

session.close()
