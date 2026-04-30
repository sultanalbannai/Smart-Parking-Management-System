"""
Database models and setup for SPMS
Implements the entity-relationship diagram from the design document
"""

from datetime import datetime
from enum import Enum
from typing import Optional
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Enum as SQLEnum, ForeignKey, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, sessionmaker, scoped_session

Base = declarative_base()


# Enums based on system design
class BayState(str, Enum):
    """Bay occupancy states"""
    AVAILABLE = "AVAILABLE"
    PENDING = "PENDING"
    UNAVAILABLE = "UNAVAILABLE"
    UNKNOWN = "UNKNOWN"


class PriorityClass(str, Enum):
    """Driver priority categories"""
    POD = "POD"  # People of Determination
    FAMILY = "FAMILY"
    STAFF = "STAFF"
    GENERAL = "GENERAL"


class ConfirmationStatus(str, Enum):
    """Confirmation result states"""
    CONFIRMED = "CONFIRMED"
    UNCONFIRMED = "UNCONFIRMED"
    TIMEOUT = "TIMEOUT"


class SuggestionStatus(str, Enum):
    """Suggestion lifecycle states"""
    ACTIVE = "ACTIVE"
    FULFILLED = "FULFILLED"
    DEVIATED = "DEVIATED"
    EXPIRED = "EXPIRED"


# Database Models
class Bay(Base):
    """
    Parking bay entity
    Represents a physical parking space with state and metadata
    """
    __tablename__ = 'bays'
    
    id = Column(String, primary_key=True)  # e.g., "B-01"
    state = Column(SQLEnum(BayState), nullable=False, default=BayState.AVAILABLE)
    category = Column(SQLEnum(PriorityClass), nullable=False, default=PriorityClass.GENERAL)
    
    # Spatial attributes
    distance_from_gate = Column(Float, nullable=False)
    zone = Column(Integer, nullable=False, default=1)
    
    # Entrance zone information (for multi-entrance malls)
    entrance_id = Column(String, nullable=True)  # e.g., "ENTRANCE_A"
    entrance_name = Column(String, nullable=True)  # e.g., "Fashion Entrance"
    entrance_color = Column(String, nullable=True)  # e.g., "#EC4899"
    zone_name = Column(String, nullable=True)  # e.g., "FASHION"
    
    # Visual coordinates for map display
    coordinates_x = Column(Integer, nullable=True)
    coordinates_y = Column(Integer, nullable=True)
    
    # State management
    last_update_time = Column(DateTime, nullable=False)
    health_score = Column(Float, default=1.0)  # 0.0 to 1.0
    
    # PENDING state tracking
    incoming_session_id = Column(String, nullable=True)
    incoming_until = Column(DateTime, nullable=True)
    
    # UNAVAILABLE state tracking
    occupied_plate_hash = Column(String, nullable=True)
    occupied_since = Column(DateTime, nullable=True)
    parked_plate = Column(String, nullable=True)   # raw plate number for search
    
    # Relationships
    occupancy_events = relationship("OccupancyEvent", back_populates="bay", cascade="all, delete-orphan")
    confirmation_events = relationship("ConfirmationEvent", back_populates="bay", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<Bay(id={self.id}, state={self.state}, category={self.category})>"


class VehicleSession(Base):
    """
    Vehicle session entity
    Tracks a vehicle from gate entry through parking and exit
    """
    __tablename__ = 'vehicle_sessions'
    
    session_id = Column(String, primary_key=True)
    gate_id = Column(String, nullable=False)
    
    # Privacy-preserving plate token
    plate_hash = Column(String, nullable=False)
    
    # Priority and preferences
    priority_class = Column(SQLEnum(PriorityClass), nullable=False, default=PriorityClass.GENERAL)
    selected_entrance = Column(String, nullable=True)  # e.g., "ENTRANCE_A" or "ENTRANCE_ANY"
    selected_zone = Column(String, nullable=True)  # e.g., "FASHION", "SHOPPING"
    
    # Timestamps
    created_at = Column(DateTime, nullable=False)
    expires_at = Column(DateTime, nullable=True)
    
    # Relationships
    suggestions = relationship("Suggestion", back_populates="session", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<VehicleSession(id={self.session_id}, priority={self.priority_class})>"


class Suggestion(Base):
    """
    Bay suggestion/recommendation entity
    Links a vehicle session to suggested parking bays
    """
    __tablename__ = 'suggestions'
    
    suggestion_id = Column(String, primary_key=True)
    session_id = Column(String, ForeignKey('vehicle_sessions.session_id'), nullable=False)
    
    # Suggested bays
    primary_bay_id = Column(String, ForeignKey('bays.id'), nullable=False)
    alternative_bay_ids = Column(String, nullable=True)  # JSON string of bay IDs
    
    # Timing
    issued_at = Column(DateTime, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    
    # Status tracking
    status = Column(SQLEnum(SuggestionStatus), nullable=False, default=SuggestionStatus.ACTIVE)
    fulfilled_at = Column(DateTime, nullable=True)
    actual_bay_id = Column(String, nullable=True)  # Where driver actually parked
    
    # Relationships
    session = relationship("VehicleSession", back_populates="suggestions")
    
    def __repr__(self):
        return f"<Suggestion(id={self.suggestion_id}, primary_bay={self.primary_bay_id}, status={self.status})>"


class OccupancyEvent(Base):
    """
    Occupancy detection event
    Logs changes in bay occupancy state
    """
    __tablename__ = 'occupancy_events'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    bay_id = Column(String, ForeignKey('bays.id'), nullable=False)
    
    # Detection result
    detected_state = Column(SQLEnum(BayState), nullable=False)
    confidence = Column(Float, nullable=False)
    
    # Timestamp
    detected_at = Column(DateTime, nullable=False)
    
    # Metadata
    source = Column(String, default="occupancy_service")  # Which component detected this
    
    # Relationships
    bay = relationship("Bay", back_populates="occupancy_events")
    
    def __repr__(self):
        return f"<OccupancyEvent(bay={self.bay_id}, state={self.detected_state}, conf={self.confidence})>"


class ConfirmationEvent(Base):
    """
    ALPR confirmation event
    Records license plate detection at bay level
    """
    __tablename__ = 'confirmation_events'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    bay_id = Column(String, ForeignKey('bays.id'), nullable=False)
    session_id = Column(String, ForeignKey('vehicle_sessions.session_id'), nullable=True)
    
    # ALPR result
    plate_hash = Column(String, nullable=False)
    confidence = Column(Float, nullable=False)
    
    # Confirmation status
    status = Column(SQLEnum(ConfirmationStatus), nullable=False)
    
    # Timestamp
    detected_at = Column(DateTime, nullable=False)
    
    # Metadata
    source = Column(String, default="per_bay_alpr")
    
    # Relationships
    bay = relationship("Bay", back_populates="confirmation_events")
    
    def __repr__(self):
        return f"<ConfirmationEvent(bay={self.bay_id}, status={self.status})>"


# Database management
class Database:
    """Database connection and session management"""
    
    def __init__(self, db_path: str = "sqlite:///data/spms.db"):
        """
        Initialize database connection.
        
        Args:
            db_path: SQLAlchemy database URL
        """
        # SQLite needs check_same_thread=False so the engine can be shared
        # across the bay-camera worker threads, Flask request threads, and the
        # main loop. Concurrency is handled by the scoped_session below: each
        # thread gets its own Session, isolating transaction state.
        connect_args = {'check_same_thread': False} if db_path.startswith('sqlite') else {}
        self.engine = create_engine(db_path, echo=False, connect_args=connect_args)
        self.SessionLocal = sessionmaker(bind=self.engine, expire_on_commit=False)
        # scoped_session: calling it returns a thread-local Session. A failure
        # in one thread no longer poisons sessions used by others.
        self.Session = scoped_session(self.SessionLocal)
        
    def create_tables(self):
        """Create all tables in the database"""
        Base.metadata.create_all(self.engine)
        
    def drop_tables(self):
        """Drop all tables (use with caution!)"""
        Base.metadata.drop_all(self.engine)
        
    def get_session(self):
        """
        Return the thread-local scoped session. Calling .query/.commit/etc.
        on this proxy automatically dispatches to a per-thread Session,
        so each Flask request and each background thread runs an isolated
        transaction. Errors in one thread do not poison the others.
        """
        return self.Session
