"""
RecommendationService - Priority-aware bay suggestion algorithm
Implements the scoring and assignment logic from Section 4.1.7
"""

import logging
import uuid
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Tuple
from sqlalchemy.orm import Session

from ..core import Clock, config
from ..models.database import Bay, VehicleSession, Suggestion, BayState, PriorityClass, SuggestionStatus

logger = logging.getLogger(__name__)


class RecommendationService:
    """
    Generates priority-aware parking bay suggestions.
    Selects optimal bay based on distance, health, priority compatibility.
    """
    
    # Scoring weights (from design document)
    W_DISTANCE = 1.0
    W_HEALTH = 0.5
    W_AGE = 0.3
    W_ZONE_LOAD = 0.2
    
    def __init__(self, db_session: Session):
        """
        Initialize recommendation service.
        
        Args:
            db_session: Database session for querying bays
        """
        self.db = db_session
        
    def generate_suggestion(
        self,
        session: VehicleSession,
        gate_id: str,
        num_alternatives: int = 3
    ) -> Optional[Suggestion]:
        """
        Generate bay suggestion for a vehicle session.
        Supports multi-entrance zone-based filtering.
        
        Args:
            session: Vehicle session requesting parking
            gate_id: Gate where vehicle entered
            num_alternatives: Number of alternative bays to suggest
            
        Returns:
            Suggestion object with primary and alternative bays, or None if no bays available
        """
        now = Clock.now()
        
        # Step 1: Get candidate bays (hard constraints + zone filter if selected)
        candidates = self._get_candidate_bays(
            session.priority_class, 
            now,
            selected_entrance=session.selected_entrance,
            selected_zone=session.selected_zone
        )
        
        if not candidates:
            logger.warning(f"No available bays for session {session.session_id} "
                         f"(entrance: {session.selected_entrance}, zone: {session.selected_zone})")
            return None
        
        # Step 2: Score and rank candidates
        scored_bays = []
        for bay in candidates:
            score = self._score_bay(bay, session.priority_class, gate_id, now)
            scored_bays.append((score, bay))
        
        # Sort by score (lower is better)
        scored_bays.sort(key=lambda x: x[0])
        
        # Step 3: Select primary bay
        primary_bay = scored_bays[0][1]
        
        # Step 4: SUGGESTION-ONLY MODE - DO NOT MARK AS PENDING
        # Bay stays AVAILABLE for first-come-first-served
        
        # Step 5: Select alternative bays
        alternatives = [bay for score, bay in scored_bays[1:num_alternatives+1]]
        alternative_ids = [bay.id for bay in alternatives]
        
        # Step 6: Create suggestion record
        suggestion = Suggestion(
            suggestion_id=str(uuid.uuid4()),
            session_id=session.session_id,
            primary_bay_id=primary_bay.id,
            alternative_bay_ids=','.join(alternative_ids) if alternative_ids else None,
            issued_at=now,
            expires_at=now + timedelta(seconds=config.incoming_ttl),
            status=SuggestionStatus.ACTIVE
        )
        
        self.db.add(suggestion)
        self.db.commit()
        
        logger.info(f"Suggested bay {primary_bay.id} for session {session.session_id} "
                   f"(zone: {session.selected_zone or 'ANY'}, "
                   f"priority: {session.priority_class}, alternatives: {alternative_ids})")
        
        return suggestion
    
    def _get_candidate_bays(
        self, 
        priority: PriorityClass, 
        now: datetime,
        selected_entrance: Optional[str] = None,
        selected_zone: Optional[str] = None
    ) -> List[Bay]:
        """
        Get list of candidate bays that satisfy hard constraints.
        Filters by zone if entrance/zone is selected.
        
        Args:
            priority: Driver's priority class
            now: Current timestamp
            selected_entrance: Selected entrance ID (e.g., "ENTRANCE_A")
            selected_zone: Selected zone name (e.g., "FASHION")
            
        Returns:
            List of available bays
        """
        # Query all AVAILABLE bays
        query = self.db.query(Bay).filter(Bay.state == BayState.AVAILABLE)
        
        # Filter by zone if selected
        if selected_zone and selected_zone != "ANY":
            query = query.filter(Bay.zone_name == selected_zone)
            logger.info(f"Filtering bays for zone: {selected_zone}")
        elif selected_entrance and selected_entrance != "ENTRANCE_ANY":
            query = query.filter(Bay.entrance_id == selected_entrance)
            logger.info(f"Filtering bays for entrance: {selected_entrance}")
        
        candidates = query.all()
        
        # Filter by category compatibility
        eligible = []
        for bay in candidates:
            if self._category_allowed(priority, bay.category, now):
                eligible.append(bay)
        
        logger.info(f"Found {len(eligible)} eligible bays (from {len(candidates)} available)")
        return eligible
    
    def _category_allowed(self, priority: PriorityClass, bay_category: PriorityClass, now: datetime) -> bool:
        """
        Check if a priority class can use a bay category.
        Implements policy rules from design document.
        
        Args:
            priority: Driver's priority class
            bay_category: Bay's category restriction
            now: Current timestamp
            
        Returns:
            bool: True if allowed
        """
        # POD can only use POD bays
        if priority == PriorityClass.POD:
            return bay_category == PriorityClass.POD
        
        # STAFF can use STAFF or GENERAL bays
        if priority == PriorityClass.STAFF:
            return bay_category in [PriorityClass.STAFF, PriorityClass.GENERAL]
        
        # GENERAL can only use GENERAL bays (no overflow to restricted)
        if priority == PriorityClass.GENERAL:
            return bay_category == PriorityClass.GENERAL
        
        return False
    
    def _score_bay(self, bay: Bay, priority: PriorityClass, gate_id: str, now: datetime) -> float:
        """
        Compute score for a candidate bay (lower is better).
        
        Args:
            bay: Bay to score
            priority: Driver's priority class
            gate_id: Entry gate ID
            now: Current timestamp
            
        Returns:
            float: Bay score
        """
        # Distance component
        distance_score = self.W_DISTANCE * bay.distance_from_gate
        
        # Health component (1 - health because lower score is better)
        health_score = self.W_HEALTH * (1.0 - bay.health_score)
        
        # Age penalty (debounce - penalize recently changed bays)
        # Handle timezone-aware/naive datetime comparison
        bay_time = bay.last_update_time
        if bay_time.tzinfo is None:
            # Make bay_time timezone-aware (assume UTC)
            from datetime import timezone
            bay_time = bay_time.replace(tzinfo=timezone.utc)
        
        age_seconds = (now - bay_time).total_seconds()
        debounce_window = config.debounce_window
        age_penalty = self.W_AGE * max(0, debounce_window - age_seconds)
        
        # Zone load balancing (placeholder - could track zone occupancy)
        zone_load_score = self.W_ZONE_LOAD * 0  # Not implemented yet
        
        total_score = distance_score + health_score + age_penalty + zone_load_score
        
        return total_score
    
    def _mark_bay_pending(self, bay: Bay, session_id: str, incoming_until: datetime) -> bool:
        """
        Atomically mark a bay as PENDING if it's AVAILABLE.
        Simulates CAS (Compare-And-Swap) operation.
        
        Args:
            bay: Bay to mark
            session_id: Vehicle session ID
            incoming_until: Expiration time for PENDING state
            
        Returns:
            bool: True if successfully marked, False if bay was taken
        """
        # Refresh bay state from database
        self.db.refresh(bay)
        
        # Check if still AVAILABLE
        if bay.state != BayState.AVAILABLE:
            return False
        
        # Mark as PENDING
        bay.state = BayState.PENDING
        bay.incoming_session_id = session_id
        bay.incoming_until = incoming_until
        bay.last_update_time = Clock.now()
        
        self.db.commit()
        
        return True
    
    def expire_pending_bays(self, now: Optional[datetime] = None):
        """
        Release PENDING bays that have exceeded their TTL.
        
        Args:
            now: Current time (defaults to Clock.now())
        """
        if now is None:
            now = Clock.now()
        
        # Find expired PENDING bays
        expired_bays = self.db.query(Bay).filter(
            Bay.state == BayState.PENDING,
            Bay.incoming_until <= now
        ).all()
        
        for bay in expired_bays:
            logger.info(f"Expiring PENDING bay {bay.id} (session: {bay.incoming_session_id})")
            
            # Revert to AVAILABLE
            bay.state = BayState.AVAILABLE
            bay.incoming_session_id = None
            bay.incoming_until = None
            bay.last_update_time = now
            
            # Mark suggestion as expired
            suggestions = self.db.query(Suggestion).filter(
                Suggestion.primary_bay_id == bay.id,
                Suggestion.status == SuggestionStatus.ACTIVE
            ).all()
            
            for suggestion in suggestions:
                suggestion.status = SuggestionStatus.EXPIRED
        
        self.db.commit()
    
    def assign_plate_to_bay(self, plate_hash: str, bay_id: str, now: Optional[datetime] = None):
        """
        Assign a detected plate to a bay and resolve suggestion status.
        Called when per-bay ALPR confirms a vehicle has parked.
        
        Args:
            plate_hash: Hashed license plate
            bay_id: Bay where vehicle parked
            now: Current timestamp
        """
        if now is None:
            now = Clock.now()
        
        # Get the bay
        bay = self.db.query(Bay).filter(Bay.id == bay_id).first()
        if not bay:
            logger.error(f"Bay {bay_id} not found")
            return
        
        # Mark bay as UNAVAILABLE
        bay.state = BayState.UNAVAILABLE
        bay.occupied_plate_hash = plate_hash
        bay.occupied_since = now
        bay.last_update_time = now
        
        # Find active suggestion with this plate hash
        suggestion = self.db.query(Suggestion).join(VehicleSession).filter(
            VehicleSession.plate_hash == plate_hash,
            Suggestion.status == SuggestionStatus.ACTIVE
        ).order_by(Suggestion.issued_at.desc()).first()
        
        if suggestion:
            suggestion.actual_bay_id = bay_id
            
            if suggestion.primary_bay_id == bay_id:
                # Driver parked in suggested bay
                suggestion.status = SuggestionStatus.FULFILLED
                suggestion.fulfilled_at = now
                logger.info(f"Suggestion {suggestion.suggestion_id} fulfilled: parked in {bay_id}")
            else:
                # Driver parked in different bay
                suggestion.status = SuggestionStatus.DEVIATED
                logger.info(f"Suggestion {suggestion.suggestion_id} deviated: parked in {bay_id} instead of {suggestion.primary_bay_id}")
                
                # Release the originally suggested bay if it's still PENDING
                original_bay = self.db.query(Bay).filter(
                    Bay.id == suggestion.primary_bay_id,
                    Bay.state == BayState.PENDING,
                    Bay.incoming_session_id == suggestion.session_id
                ).first()
                
                if original_bay:
                    logger.info(f"Releasing PENDING bay {original_bay.id}")
                    original_bay.state = BayState.AVAILABLE
                    original_bay.incoming_session_id = None
                    original_bay.incoming_until = None
                    original_bay.last_update_time = now
        
        self.db.commit()
