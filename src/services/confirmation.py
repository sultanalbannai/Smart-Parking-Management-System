"""
ConfirmationService - Per-bay ALPR confirmation
Verifies that the correct vehicle parked in a bay
"""

import logging
from datetime import datetime
from typing import Optional
from sqlalchemy.orm import Session

from ..core import Clock, config, MessageBus
from ..models.database import Bay, VehicleSession, Suggestion, ConfirmationEvent, ConfirmationStatus, SuggestionStatus
from ..core.plate_hasher import PlateNormalizerHasher

logger = logging.getLogger(__name__)


class ConfirmationService:
    """
    Handles per-bay ALPR confirmation.
    Verifies plate matches and resolves suggestion outcomes.
    """
    
    def __init__(self, db_session: Session, message_bus: MessageBus):
        """
        Initialize confirmation service.
        
        Args:
            db_session: Database session
            message_bus: Message bus for publishing events
        """
        self.db = db_session
        self.bus = message_bus
        
        # Confirmation parameters
        self.confirmation_timeout = config.confirmation_timeout
        self.min_confidence = 0.85
    
    def confirm_bay_occupancy(self, bay_id: str, plate_hash: str, 
                             confidence: float = 0.95,
                             now: Optional[datetime] = None) -> ConfirmationStatus:
        """
        Confirm vehicle in bay by matching plate hash.
        
        Args:
            bay_id: Bay where vehicle is detected
            plate_hash: Hashed plate detected at bay
            confidence: ALPR confidence
            now: Current timestamp
            
        Returns:
            ConfirmationStatus: Result of confirmation
        """
        if now is None:
            now = Clock.now()
        
        # Find active suggestion with this plate hash
        suggestion = self.db.query(Suggestion).join(VehicleSession).filter(
            VehicleSession.plate_hash == plate_hash,
            Suggestion.status == SuggestionStatus.ACTIVE
        ).order_by(Suggestion.issued_at.desc()).first()
        
        if not suggestion:
            # No matching suggestion found
            status = ConfirmationStatus.UNCONFIRMED
            logger.warning(f"No active suggestion found for plate in bay {bay_id}")
        elif confidence < self.min_confidence:
            # Low confidence detection
            status = ConfirmationStatus.UNCONFIRMED
            logger.warning(f"Low confidence ({confidence:.2f}) for bay {bay_id}")
        else:
            # Plate matches a suggestion
            status = ConfirmationStatus.CONFIRMED
            logger.info(f"Confirmed: vehicle in bay {bay_id} matches suggestion {suggestion.suggestion_id[:8]}...")
        
        # Create confirmation event
        event = ConfirmationEvent(
            bay_id=bay_id,
            session_id=suggestion.session_id if suggestion else None,
            plate_hash=plate_hash,
            confidence=confidence,
            status=status,
            detected_at=now,
            source="per_bay_alpr"
        )
        
        self.db.add(event)
        self.db.commit()
        
        # Publish confirmation event
        self.bus.publish(
            topic=f"parking/bays/{bay_id}/confirmation",
            payload={
                "bayId": bay_id,
                "status": status.value,
                "plateHash": plate_hash,
                "confidence": confidence,
                "sessionId": suggestion.session_id if suggestion else None,
                "timestamp": Clock.timestamp_ms()
            }
        )
        
        return status
    
    def resolve_timeout(self, bay_id: str, now: Optional[datetime] = None):
        """
        Mark a bay confirmation as timed out.
        Called when ALPR cannot read plate after multiple attempts.
        
        Args:
            bay_id: Bay identifier
            now: Current timestamp
        """
        if now is None:
            now = Clock.now()
        
        # Create timeout event
        event = ConfirmationEvent(
            bay_id=bay_id,
            session_id=None,
            plate_hash="TIMEOUT",
            confidence=0.0,
            status=ConfirmationStatus.TIMEOUT,
            detected_at=now,
            source="per_bay_alpr"
        )
        
        self.db.add(event)
        self.db.commit()
        
        # Publish timeout event
        self.bus.publish(
            topic=f"parking/bays/{bay_id}/confirmation",
            payload={
                "bayId": bay_id,
                "status": ConfirmationStatus.TIMEOUT.value,
                "timestamp": Clock.timestamp_ms()
            }
        )
        
        logger.warning(f"Bay {bay_id} confirmation timed out")
    
    def get_confirmation_status(self, bay_id: str) -> Optional[ConfirmationStatus]:
        """
        Get the most recent confirmation status for a bay.
        
        Args:
            bay_id: Bay identifier
            
        Returns:
            ConfirmationStatus or None if no confirmation exists
        """
        event = self.db.query(ConfirmationEvent).filter(
            ConfirmationEvent.bay_id == bay_id
        ).order_by(ConfirmationEvent.detected_at.desc()).first()
        
        return event.status if event else None
