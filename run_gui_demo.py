"""
SPMS Demo with Web GUI
Runs the simulation with a modern web-based interface
"""

import sys
import time
import logging
import threading
import webbrowser
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from src.core import config, Clock, MessageBus
from src.models.database import Database
from src.simulation.parking_simulation import ParkingSimulation
from src.ui.web_gui import init_gui, run_server

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('simulation_gui.log'),
        logging.StreamHandler()
    ]
)

# Reduce Flask logging noise
logging.getLogger('werkzeug').setLevel(logging.WARNING)
logging.getLogger('socketio').setLevel(logging.WARNING)
logging.getLogger('engineio').setLevel(logging.WARNING)

logger = logging.getLogger(__name__)


def main():
    """Run the parking simulation with web GUI"""
    
    print("\n" + "="*70)
    print(" SMART PARKING MANAGEMENT SYSTEM - WEB GUI DEMO ".center(70))
    print("="*70 + "\n")
    
    # Load configuration
    config.load('config/default_config.yaml')
    logger.info(f"Loaded configuration: {config.facility_name}")
    
    # Initialize database
    db = Database(f"sqlite:///{config.database_path}")
    session = db.get_session()
    logger.info(f"Connected to database: {config.database_path}")
    
    # Initialize message bus
    bus = MessageBus()
    bus.connect()
    logger.info("Message bus connected")
    
    # Initialize web GUI
    init_gui(session, bus)
    logger.info("Web GUI initialized")
    
    # Start web server in separate thread
    server_thread = threading.Thread(
        target=run_server,
        kwargs={'host': '127.0.0.1', 'port': 5000, 'debug': False},
        daemon=True
    )
    server_thread.start()
    
    # Wait for server to start
    time.sleep(2)
    
    # Open browser
    print("\n" + "="*70)
    print(" WEB DASHBOARD ".center(70))
    print("="*70)
    print("\n🌐 Opening dashboard in your browser...")
    print("📍 URL: http://127.0.0.1:5000")
    print("\nIf browser doesn't open automatically, copy the URL above.")
    print("\n" + "="*70 + "\n")
    
    webbrowser.open('http://127.0.0.1:5000')
    
    # Wait a bit for user to see the dashboard
    time.sleep(3)
    
    # Simulation parameters
    print("\n" + "="*70)
    print(" SIMULATION CONFIGURATION ".center(70))
    print("="*70)
    print(f"\n📊 Parameters:")
    print(f"  • Number of vehicles: 10")
    print(f"  • Arrival interval: 3 seconds")
    print(f"  • Speed multiplier: 2.0x")
    print(f"  • Priority distribution: 10% POD, 20% STAFF, 70% GENERAL")
    print(f"  • Compliance rate: 60% (40% will park in different bay)")
    print("\n" + "="*70)
    
    input("\n👀 Check the web dashboard, then press Enter to start simulation...\n")
    
    # Create simulation
    simulation = ParkingSimulation(
        db_session=session,
        message_bus=bus,
        speed=2.0,  # 2x faster
        seed=42     # For reproducibility
    )
    
    try:
        print("\n🚀 Starting simulation...")
        print("📺 Watch the web dashboard for real-time updates!\n")
        
        # Run simulation
        simulation.run_scenario(
            num_vehicles=10,
            arrival_interval=3.0
        )
        
        # Show final status
        print("\n" + "="*70)
        print(" SIMULATION COMPLETE ".center(70))
        print("="*70)
        
        status = simulation.get_system_status()
        print(f"\n📈 Results:")
        print(f"  • Vehicles processed: {status['vehicles_processed']}")
        print(f"  • Final occupancy: {status['occupied']}/{status['total_bays']} "
              f"({status['occupied']/status['total_bays']*100:.1f}%)")
        print(f"  • Available bays: {status['available']}")
        print(f"  • Pending bays: {status['pending']}")
        
        print("\n" + "="*70)
        print("\n✅ Simulation complete!")
        print("🌐 Web dashboard is still running at http://127.0.0.1:5000")
        print("\nPress Ctrl+C to stop the server and exit.\n")
        
        # Keep server running
        while True:
            time.sleep(1)
        
    except KeyboardInterrupt:
        print("\n\n👋 Shutting down...")
        simulation.stop()
    
    except Exception as e:
        logger.error(f"Error during simulation: {e}", exc_info=True)
    
    finally:
        # Cleanup
        bus.disconnect()
        session.close()
        logger.info("Simulation ended")


if __name__ == "__main__":
    main()
