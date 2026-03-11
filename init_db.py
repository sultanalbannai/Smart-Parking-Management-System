"""
Initialize SPMS database with default configuration
"""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from src.core import config, Clock
from src.models.database import Database, Bay, BayState
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def initialize_database():
    """Initialize database and populate with configured bays"""
    
    # Load configuration
    config.load('config/default_config.yaml')
    logger.info(f"Loaded configuration for: {config.facility_name}")
    
    # Create database
    db = Database(f"sqlite:///{config.database_path}")
    logger.info(f"Database path: {config.database_path}")
    
    # Create tables
    logger.info("Creating database tables...")
    db.create_tables()
    
    # Get session
    session = db.get_session()
    
    try:
        # Check if bays already exist
        existing_count = session.query(Bay).count()
        
        if existing_count > 0:
            logger.info(f"Database already initialized with {existing_count} bays")
            response = input("Do you want to reinitialize? (yes/no): ")
            if response.lower() != 'yes':
                logger.info("Skipping initialization")
                return
            
            # Drop and recreate
            logger.info("Dropping existing tables...")
            db.drop_tables()
            db.create_tables()
        
        # Add bays from configuration
        now = Clock.now()
        logger.info(f"Adding {len(config.bays)} bays...")
        
        for bay_config in config.bays:
            bay = Bay(
                id=bay_config.id,
                state=BayState.AVAILABLE,
                category=bay_config.category,
                distance_from_gate=bay_config.distance_from_gate,
                zone=bay_config.zone,
                last_update_time=now,
                health_score=1.0
            )
            session.add(bay)
            logger.info(f"  Added bay {bay.id} ({bay.category}, {bay.distance_from_gate}m from gate)")
        
        session.commit()
        logger.info("✅ Database initialized successfully!")
        
        # Print summary
        total_bays = session.query(Bay).count()
        available_bays = session.query(Bay).filter(Bay.state == BayState.AVAILABLE).count()
        
        print("\n" + "="*50)
        print(f"Facility: {config.facility_name}")
        print(f"Total Bays: {total_bays}")
        print(f"Available: {available_bays}")
        print("="*50)
        
        print("\nBay Layout:")
        bays = session.query(Bay).order_by(Bay.distance_from_gate).all()
        for bay in bays:
            print(f"  {bay.id}: {bay.category.value:10} - {bay.distance_from_gate:5.1f}m - {bay.state.value}")
        
    except Exception as e:
        logger.error(f"Error initializing database: {e}")
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    initialize_database()
