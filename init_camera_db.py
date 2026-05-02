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

import math


def _euclid_distance(bx, by, ex, ey, scale=0.1):
    """
    Map-pixel distance from (bx, by) to (ex, ey), scaled to a friendlier
    'metres' figure. The default ``scale=0.1`` turns pixel distances of
    ~200-400 (typical for the 1200x850 map) into 20-40 m, matching the
    rough magnitudes the recommendation engine has been tuned for.
    """
    return round(math.hypot(bx - ex, by - ey) * scale, 1)


total_bays = 0
category_counts = {'GENERAL': 0, 'POD': 0, 'STAFF': 0, 'FAMILY': 0}

for zone in cfg['parking_zones']:
    zone_id        = zone['zone_id']
    zone_name      = zone['zone_name']
    entrance_id    = zone['entrance_id']
    entrance_name  = zone['entrance_name']
    entrance_color = zone['entrance_color']
    ex             = zone.get('entrance_x')
    ey             = zone.get('entrance_y')

    for bay_cfg in zone['bays']:
        cat = bay_cfg['category']

        # Compute distance from the bay's (x,y) to the entrance position.
        # This always reflects the actual map geometry; the optional
        # 'distance' field in the YAML is used as a fallback only when the
        # coordinates aren't supplied.
        if ex is not None and ey is not None \
                and bay_cfg.get('x') is not None and bay_cfg.get('y') is not None:
            distance = _euclid_distance(bay_cfg['x'], bay_cfg['y'], ex, ey)
        else:
            distance = bay_cfg.get('distance', 0)

        bay = Bay(
            id=bay_cfg['id'],
            state=BayState.AVAILABLE,
            category=PriorityClass[cat],
            distance_from_gate=distance,
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

# ── Pre-fill demo scenario: mark select bays as already occupied ──────────────
# All POD and STAFF bays start free so the recommendation engine can offer
# them when a vehicle arrives. Only some GENERAL bays are pre-occupied.
DEMO_OCCUPIED = {'G-01', 'G-02', 'G-05', 'G-06', 'G-07', 'G-08'}

for bay in session.query(Bay).all():
    if bay.id in DEMO_OCCUPIED:
        bay.state = BayState.UNAVAILABLE

session.commit()

print(f"\n[OK] Database initialized!")
print(f"\n[*] Summary:")
print(f"   Total bays : {total_bays}")
for cat, count in category_counts.items():
    if count > 0:
        pct = count / total_bays * 100
        print(f"   {cat:8} : {count:2} bays ({pct:.0f}%)")

print(f"   Pre-occupied: {', '.join(sorted(DEMO_OCCUPIED))}")
print(f"\n[*] Entrance: {cfg['parking_zones'][0]['entrance_name']}")

# Show the computed bay-to-entrance distances, sorted nearest-first
print(f"\n[*] Bay distances from entrance (computed from coordinates):")
for bay in sorted(session.query(Bay).all(),
                  key=lambda b: b.distance_from_gate or 0):
    print(f"   {bay.id:7}  {bay.distance_from_gate:5}  ({bay.category.value})")
print(f"\n[OK] Ready for camera demo!")
print("   Run: python run_camera_demo.py")
print("="*60 + "\n")

session.close()
