"""
SPMS Demo - Main demonstration script
Runs a complete parking simulation with visualization
"""

import sys
import time
import logging
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from src.core import config, Clock, MessageBus
from src.models.database import Database
from src.simulation.parking_simulation import ParkingSimulation
from src.ui.console_ui import ConsoleUI

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('simulation.log'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)


def main():
    """Run the parking simulation demo"""
    
    print("\n" + "="*70)
    print(" SMART PARKING MANAGEMENT SYSTEM - DEMO ".center(70))
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
    
    # Initialize console UI
    ui = ConsoleUI(session, bus)
    logger.info("Console UI initialized")
    
    # Show initial status
    ui.print_full_status()
    
    # Simulation parameters
    print("\n" + "="*70)
    print(" SIMULATION CONFIGURATION ".center(70))
    print("="*70)
    print(f"\nNumber of vehicles: 10")
    print(f"Arrival interval: 3 seconds (fast mode)")
    print(f"Speed: 2.0x")
    print(f"\nPriority Distribution:")
    print(f"  - POD (People of Determination): 10%")
    print(f"  - STAFF: 20%")
    print(f"  - GENERAL: 70%")
    print(f"\nCompliance Rate: 60% (40% will park in different bay)")
    print("\n" + "="*70)
    
    input("\nPress Enter to start simulation...")
    
    # Create simulation
    simulation = ParkingSimulation(
        db_session=session,
        message_bus=bus,
        speed=2.0,  # 2x faster
        seed=42     # For reproducibility
    )
    
    try:
        # Run simulation
        simulation.run_scenario(
            num_vehicles=10,
            arrival_interval=3.0
        )
        
        # Show final status
        print("\n" + "="*70)
        print(" FINAL STATUS ".center(70))
        print("="*70)
        
        time.sleep(1)
        ui.print_full_status()
        
        # Print summary
        status = simulation.get_system_status()
        print("\n" + "="*70)
        print(" SIMULATION RESULTS ".center(70))
        print("="*70)
        print(f"\nVehicles Processed: {status['vehicles_processed']}")
        print(f"Final Occupancy: {status['occupied']}/{status['total_bays']} "
              f"({status['occupied']/status['total_bays']*100:.1f}%)")
        print(f"Available Bays: {status['available']}")
        print(f"Pending Bays: {status['pending']}")
        print("\n" + "="*70 + "\n")
        
    except KeyboardInterrupt:
        print("\n\nSimulation interrupted by user")
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
