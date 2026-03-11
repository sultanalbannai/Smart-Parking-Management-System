"""
SPMS Web GUI Demo
Runs simulation with modern web interface
"""

import sys
import time
import threading
import webbrowser
import logging
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from src.core import config, Clock, MessageBus
from src.models.database import Database
from src.simulation.parking_simulation import ParkingSimulation

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(message)s'
)

# Reduce Flask/SocketIO logging
logging.getLogger('werkzeug').setLevel(logging.WARNING)
logging.getLogger('socketio').setLevel(logging.WARNING)
logging.getLogger('engineio').setLevel(logging.WARNING)

logger = logging.getLogger(__name__)


def run_web_server(db_session, message_bus):
    """Run the web server with shared message bus"""
    import web_server
    
    # Initialize web server with shared instances
    web_server.init_system(external_db=db_session, external_bus=message_bus)
    
    # Run server
    web_server.socketio.run(
        web_server.app,
        host='127.0.0.1',
        port=5000,
        debug=False,
        allow_unsafe_werkzeug=True
    )


def main():
    """Main demo with web GUI"""
    
    print("\n" + "="*70)
    print(" SMART PARKING MANAGEMENT SYSTEM - WEB GUI ".center(70))
    print("="*70 + "\n")
    
    # Initialize system components FIRST
    print("🔧 Initializing system...")
    config.load('config/default_config.yaml')
    db = Database(f"sqlite:///{config.database_path}")
    session = db.get_session()
    bus = MessageBus()
    bus.connect()
    print("✅ System initialized")
    
    # Start web server with shared message bus
    print("🌐 Starting web server...")
    server_thread = threading.Thread(
        target=run_web_server,
        args=(session, bus),
        daemon=True
    )
    server_thread.start()
    
    # Wait for server to start
    time.sleep(3)
    
    # Open dashboard and kiosk in browser
    print("\n📊 Opening Dashboard at http://127.0.0.1:5000")
    print("🖥️  Opening Kiosk View at http://127.0.0.1:5000/kiosk")
    print("\nTip: Arrange windows side-by-side to see both views!\n")
    
    webbrowser.open('http://127.0.0.1:5000')
    time.sleep(1)
    webbrowser.open('http://127.0.0.1:5000/kiosk')
    
    time.sleep(2)
    
    # Simulation parameters
    print("\n" + "="*70)
    print(" SIMULATION CONFIGURATION ".center(70))
    print("="*70)
    print(f"\n📋 Settings:")
    print(f"  • Vehicles: 10")
    print(f"  • Interval: 3 seconds")
    print(f"  • Speed: 2.0x faster")
    print(f"  • Priority: 10% POD, 20% STAFF, 70% GENERAL")
    print(f"  • Compliance: 60% follow suggestions")
    print("\n" + "="*70)
    
    input("\n✅ Web GUI ready! Press Enter to start simulation...\n")
    
    # Create and run simulation
    simulation = ParkingSimulation(
        db_session=session,
        message_bus=bus,
        speed=2.0,
        seed=42
    )
    
    try:
        print("\n🚀 Simulation starting...")
        print("👀 Watch the web interface for real-time updates!\n")
        
        simulation.run_scenario(
            num_vehicles=10,
            arrival_interval=3.0
        )
        
        # Show results
        status = simulation.get_system_status()
        print("\n" + "="*70)
        print(" SIMULATION COMPLETE ".center(70))
        print("="*70)
        print(f"\n📈 Results:")
        print(f"  • Vehicles processed: {status['vehicles_processed']}")
        print(f"  • Final occupancy: {status['occupied']}/{status['total_bays']} "
              f"({status['occupied']/status['total_bays']*100:.1f}%)")
        print(f"  • Available: {status['available']}")
        print(f"  • Pending: {status['pending']}")
        print("\n" + "="*70)
        print("\n✅ Simulation complete!")
        print("🌐 Web GUI still running at:")
        print("   Dashboard: http://127.0.0.1:5000")
        print("   Kiosk:     http://127.0.0.1:5000/kiosk")
        print("\nPress Ctrl+C to stop\n")
        
        # Keep running
        while True:
            time.sleep(1)
            
    except KeyboardInterrupt:
        print("\n\n👋 Shutting down...")
        simulation.stop()
        
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        
    finally:
        bus.disconnect()
        session.close()
        print("Goodbye!\n")


if __name__ == "__main__":
    main()
