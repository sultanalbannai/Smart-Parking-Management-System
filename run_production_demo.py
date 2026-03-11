"""
Production Mall Parking System - Complete Demo
40 bays, 4 entrance zones, multi-entrance routing
"""

import os
import sys
import time
import threading
import webbrowser
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from src.core import config, Clock
from src.core.simple_message_bus import MessageBus
from src.models.database import Database
from src.simulation.parking_simulation import ParkingSimulation

def banner():
    print("\n" + "="*70)
    print(" PRODUCTION MALL PARKING SYSTEM - 40 BAYS ".center(70))
    print("="*70)

def run_web_server(db_session, bus):
    """Run web server in separate thread"""
    import web_server_production
    web_server_production.init_system(external_db=db_session, external_bus=bus)
    web_server_production.run_server(host='0.0.0.0', port=5000)

def main():
    banner()
    
    print("🔧 Initializing system...")
    
    # Load config
    config.load('config/mall_config.yaml')
    
    # Initialize database
    db = Database(f"sqlite:///{config.database_path}")
    session = db.get_session()
    
    # Initialize message bus
    bus = MessageBus()
    bus.connect()
    
    print("✅ System initialized\n")
    
    # Start web server in background
    print("🌐 Starting web server...")
    server_thread = threading.Thread(
        target=run_web_server,
        args=(session, bus),
        daemon=True
    )
    server_thread.start()
    time.sleep(2)  # Let server start
    
    # Open browsers
    print("📊 Opening Dashboard at http://127.0.0.1:5000")
    print("🖥️  Opening Kiosk View at http://127.0.0.1:5000/kiosk")
    
    try:
        webbrowser.open('http://127.0.0.1:5000')
        time.sleep(1)
        webbrowser.open('http://127.0.0.1:5000/kiosk')
    except:
        print("⚠️  Could not open browsers automatically")
        print("   Please open http://127.0.0.1:5000 manually")
    
    print("\nTip: Arrange windows side-by-side to see both views!")
    
    # Simulation configuration
    print("\n" + "="*70)
    print(" SIMULATION CONFIGURATION ".center(70))
    print("="*70)
    
    run_until_full = True  # Run until parking is full
    interval = 8.0  # 8 seconds between vehicles (gives time to see kiosk selection)
    speed = 1.0     # Real-time speed (not accelerated)
    
    print(f"📋 Settings:")
    print(f"  • Mode: {'🅿️ RUN UNTIL PARKING FULL' if run_until_full else f'{num_vehicles} vehicles'}")
    print(f"  • Interval: {interval} seconds between arrivals")
    print(f"  • Speed: {speed}x (real-time)")
    print(f"  • Zones: 4 (Fashion, Shopping, Food, Entertainment)")
    print(f"  • Total Bays: 40")
    print(f"  • Priority: 10% POD, 10% FAMILY, 10% STAFF, 70% GENERAL")
    print(f"  • Entrance Selection: Random zone preference")
    print(f"  • NOTE: Slower timing allows viewing kiosk selection process")
    print(f"  • Max vehicles: 50 (safety limit)")
    print("="*70)
    
    input("\n✅ Web GUI ready! Press Enter to start simulation...\n")
    
    # Create and run simulation
    simulation = ParkingSimulation(
        db_session=session,
        message_bus=bus,
        speed=speed
    )
    
    print("\n🚗 Starting vehicle simulation...")
    print("="*70 + "\n")
    
    if run_until_full:
        simulation.run_until_full(arrival_interval=interval, max_vehicles=50)
    else:
        simulation.run_scenario(num_vehicles=15, arrival_interval=interval)
    
    print("\n" + "="*70)
    print(" SIMULATION COMPLETE ".center(70))
    print("="*70)
    print("\n📊 Dashboard will remain open for viewing")
    print("Press Ctrl+C to exit\n")
    
    # Keep server running
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n\n👋 Shutting down...")
        bus.disconnect()

if __name__ == "__main__":
    main()
