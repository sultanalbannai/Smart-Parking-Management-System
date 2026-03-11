# 🚀 SMART PARKING SYSTEM - QUICK GUIDE

## 🎯 What This System Does

A complete 40-bay mall parking system with:
- 🎨 Real-time visual parking map
- 🚗 Automatic license plate recognition (ALPR)
- 📱 Driver kiosk with zone selection
- 🅿️ Multi-entrance smart routing
- ✅ All bays update colors when occupied

---

## ⚡ QUICK START (3 Steps)

### Step 1: Initialize Fresh Database
```powershell
cd C:\Users\LENOVO\Desktop\spms\[YOUR_FOLDER]\spms
.\venv\Scripts\Activate.ps1
python init_production_db.py
```

**You should see:**
```
🗑️  Dropping all existing tables...
✅ All tables dropped
🔧 Creating fresh database tables...
✅ Fresh database created

✅ Created 40 bays across 4 zones
```

### Step 2: Run Demo
```powershell
python run_production_demo.py
```

### Step 3: Press Enter
- Dashboard opens at http://127.0.0.1:5000
- Kiosk opens at http://127.0.0.1:5000/kiosk
- **Press Enter** to start simulation!

---

## 🎬 What Happens

1. **Vehicle arrives** every 8 seconds
2. **Kiosk shows** zone selection (Fashion/Shopping/Food/Entertainment)
3. **Bay suggested** - closest available bay in selected zone
4. **Car parks** - bay turns RED on dashboard
5. **Statistics update** - available count decreases
6. **Repeat** until parking lot is FULL! 🅿️

---

## 🔧 If Something Looks Wrong

### Problem: Old vehicles still showing / Bays already occupied

**Solution: Fresh Start**
```powershell
# 1. Close browser windows
# 2. Stop server (Ctrl+C)
# 3. Delete database
Remove-Item data\spms.db -Force

# 4. Reinitialize
python init_production_db.py

# 5. Run demo
python run_production_demo.py

# 6. Hard refresh browser (Ctrl+Shift+R)
```

### Problem: Bays not updating colors

**Solution: Hard Refresh Browser**
- Press **Ctrl + Shift + R** (Windows)
- Or **Ctrl + F5**
- This clears browser cache

---

## 📊 System Features

### Dashboard (Admin View)
- **Visual SVG Map** with 40 positioned bays
- **Real-time updates** - bays change color
- **Statistics** - Total / Available / Occupied
- **Zone breakdown** - Fashion / Shopping / Food / Entertainment
- **Activity feed** - Live log of events
- **Entrance markers** - 👗🛍️🍕🎬 at actual locations

### Kiosk (Driver View)
- **5 large buttons** for zone selection
- **Real-time availability** per zone
- **Suggested bay** with alternatives
- **8 seconds** to view before next vehicle

### Simulation Settings
- **Mode:** Run until parking is FULL
- **Interval:** 8 seconds between vehicles
- **Speed:** 1.0x (real-time)
- **Total bays:** 40 across 4 zones
- **Max vehicles:** 50 (safety limit)

---

## 🎨 Bay Colors

| Color | Meaning |
|-------|---------|
| 🟢 Green | **Available** - Ready for parking |
| 🔴 Red | **Occupied** - Car parked here |

---

## 📍 Zone Layout

```
        👗 Fashion (North)
        10 bays (FA-01 to FA-10)
              ↓
🎬 Entertainment ← [MALL] → Shopping 🛍️
   (West)                    (East)
   9 bays                    9 bays

              ↑
        🍕 Food Court (South)
        9 bays (FC-01 to FC-09)
```

---

## 🛠️ Files Structure

```
spms/
├── run_production_demo.py    # Main demo script
├── init_production_db.py     # Database initialization
├── config/
│   └── production_config.yaml  # 40-bay layout
├── data/
│   └── spms.db               # SQLite database (delete to reset)
├── templates/
│   ├── production_dashboard.html  # Admin map view
│   └── production_kiosk.html      # Driver view
├── static/
│   ├── js/
│   │   ├── production_dashboard.js  # Map updates
│   │   └── production_kiosk.js      # Kiosk logic
│   └── css/
│       ├── production.css           # Dashboard styling
│       └── production_kiosk.css     # Kiosk styling
└── src/
    ├── models/
    │   └── database.py       # Bay, VehicleSession models
    ├── services/
    │   ├── recommendation.py # Bay assignment
    │   ├── occupancy.py      # Bay state updates
    │   └── gate_alpr.py      # Plate recognition
    └── simulation/
        └── parking_simulation.py  # Vehicle generator
```

---

## 💡 Tips

1. **Always initialize database first** before running demo
2. **Hard refresh browser** (Ctrl+Shift+R) if UI doesn't update
3. **Close all browser tabs** of dashboard/kiosk before restarting
4. **Check terminal logs** for detailed simulation progress
5. **Open browser console** (F12) to see bay update messages

---

## 📊 Simulation Output

```
============================================================
🅿️ PARKING: Vehicle entering bay...
============================================================
Bay FA-03: AVAILABLE → UNAVAILABLE (conf: 0.95)
✅ Bay should now show as OCCUPIED on dashboard
============================================================

⏱️  Waiting 8.0s until next vehicle...

[Vehicle 2] 39 bays still available
🚗 Vehicle Arrival: ABC123 (GENERAL)
💡 Suggested bay: FA-04 in FASHION
⏱️  Waiting 2.0s for driver to reach bay...
🅿️ Vehicle parked in FA-04 - confirmed
```

---

## ✅ Success Checklist

- [ ] Database initialized with 40 bays
- [ ] Dashboard shows green bays (all available)
- [ ] Kiosk shows 4 zone buttons
- [ ] Simulation starts when you press Enter
- [ ] Bays turn red when cars park
- [ ] Statistics decrease (40 → 39 → 38...)
- [ ] Continues until "PARKING LOT FULL!"

---

## 🎊 That's It!

Your smart parking system is ready to demo! Watch as the entire parking lot fills up with real-time visual feedback. Perfect for presentations! 🚀

**Questions?** Check terminal logs or browser console (F12) for details.

**Made with:** Python, Flask, Socket.IO, SQLite, JavaScript, SVG
**Optimized for:** Jetson Nano deployment
**License:** Senior Project - AUS 2026
