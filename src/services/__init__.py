"""
Service components for SPMS
"""

from .recommendation import RecommendationService
from .occupancy import OccupancyService
from .confirmation import ConfirmationService

# GateALPRService omitted here to avoid circular import:
#   services/__init__ -> gate_alpr -> simulation -> parking_simulation -> services/gate_alpr
# Import directly when needed: from src.services.gate_alpr import GateALPRService

__all__ = [
    'RecommendationService',
    'OccupancyService',
    'ConfirmationService'
]
