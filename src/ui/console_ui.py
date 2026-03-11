"""
Console UI - Displays parking system status in terminal
Shows bay states, vehicle arrivals, and system events
"""

import logging
from typing import Dict, Optional
from datetime import datetime
from sqlalchemy.orm import Session

from ..core import Clock, MessageBus
from ..models.database import Bay, BayState, PriorityClass
from ..services.occupancy import OccupancyService

logger = logging.getLogger(__name__)


class ConsoleUI:
    """
    Console-based user interface for the parking system.
    Displays bay status and events in formatted tables.
    """
    
    # Color codes for terminal (ANSI)
    COLORS = {
        'AVAILABLE': '\033[92m',    # Green
        'PENDING': '\033[93m',       # Yellow
        'UNAVAILABLE': '\033[91m',   # Red
        'UNKNOWN': '\033[90m',       # Gray
        'RESET': '\033[0m',          # Reset
        'BOLD': '\033[1m',           # Bold
        'POD': '\033[96m',           # Cyan
        'STAFF': '\033[95m',         # Magenta
        'GENERAL': '\033[97m',       # White
    }
    
    def __init__(self, db_session: Session, message_bus: MessageBus):
        """
        Initialize console UI.
        
        Args:
            db_session: Database session
            message_bus: Message bus for subscribing to events
        """
        self.db = db_session
        self.bus = message_bus
        
        # Subscribe to events
        self._setup_subscriptions()
        
        # Event counters
        self.events = {
            'arrivals': 0,
            'suggestions': 0,
            'parkings': 0,
            'confirmations': 0,
        }
    
    def _setup_subscriptions(self):
        """Subscribe to system events"""
        self.bus.subscribe("parking/request", self._on_arrival)
        self.bus.subscribe("parking/suggestions/#", self._on_suggestion)
        self.bus.subscribe("parking/bays/+/state", self._on_bay_state)
        self.bus.subscribe("parking/bays/+/confirmation", self._on_confirmation)
    
    def _on_arrival(self, topic: str, payload: Dict):
        """Handle vehicle arrival event"""
        self.events['arrivals'] += 1
    
    def _on_suggestion(self, topic: str, payload: Dict):
        """Handle bay suggestion event"""
        self.events['suggestions'] += 1
    
    def _on_bay_state(self, topic: str, payload: Dict):
        """Handle bay state change event"""
        if payload.get('state') == 'UNAVAILABLE':
            self.events['parkings'] += 1
    
    def _on_confirmation(self, topic: str, payload: Dict):
        """Handle confirmation event"""
        self.events['confirmations'] += 1
    
    def print_header(self, title: str):
        """Print section header"""
        print(f"\n{self.COLORS['BOLD']}{'='*70}{self.COLORS['RESET']}")
        print(f"{self.COLORS['BOLD']}{title:^70}{self.COLORS['RESET']}")
        print(f"{self.COLORS['BOLD']}{'='*70}{self.COLORS['RESET']}\n")
    
    def print_bay_status(self):
        """Display current status of all bays in a table"""
        bays = self.db.query(Bay).order_by(Bay.distance_from_gate).all()
        
        self.print_header("PARKING BAY STATUS")
        
        # Table header
        print(f"{'Bay ID':<10} {'Category':<12} {'Distance':<10} {'State':<15} {'Last Updated':<20}")
        print("-" * 70)
        
        # Table rows
        for bay in bays:
            # Color based on state
            state_color = self.COLORS.get(bay.state.value, '')
            category_color = self.COLORS.get(bay.category.value, '')
            
            # Format state with color
            state_str = f"{state_color}{bay.state.value:<15}{self.COLORS['RESET']}"
            category_str = f"{category_color}{bay.category.value:<12}{self.COLORS['RESET']}"
            
            # Format time
            time_str = bay.last_update_time.strftime("%H:%M:%S") if bay.last_update_time else "N/A"
            
            print(f"{bay.id:<10} {category_str} {bay.distance_from_gate:<10.1f} "
                  f"{state_str} {time_str:<20}")
        
        print()
    
    def print_summary(self):
        """Display system summary statistics"""
        bays = self.db.query(Bay).all()
        
        total = len(bays)
        available = sum(1 for b in bays if b.state == BayState.AVAILABLE)
        pending = sum(1 for b in bays if b.state == BayState.PENDING)
        occupied = sum(1 for b in bays if b.state == BayState.UNAVAILABLE)
        
        self.print_header("SYSTEM SUMMARY")
        
        print(f"Total Bays:       {total}")
        print(f"{self.COLORS['AVAILABLE']}Available:        {available}{self.COLORS['RESET']}")
        print(f"{self.COLORS['PENDING']}Pending:          {pending}{self.COLORS['RESET']}")
        print(f"{self.COLORS['UNAVAILABLE']}Occupied:         {occupied}{self.COLORS['RESET']}")
        print(f"\nOccupancy Rate:   {(occupied/total*100):.1f}%")
        print()
    
    def print_events(self):
        """Display event statistics"""
        self.print_header("EVENT STATISTICS")
        
        print(f"Vehicle Arrivals:      {self.events['arrivals']}")
        print(f"Suggestions Issued:    {self.events['suggestions']}")
        print(f"Vehicles Parked:       {self.events['parkings']}")
        print(f"Confirmations:         {self.events['confirmations']}")
        print()
    
    def print_category_breakdown(self):
        """Display bay breakdown by category"""
        bays = self.db.query(Bay).all()
        
        categories = {}
        for bay in bays:
            cat = bay.category.value
            state = bay.state.value
            
            if cat not in categories:
                categories[cat] = {'total': 0, 'available': 0, 'pending': 0, 'occupied': 0}
            
            categories[cat]['total'] += 1
            if state == 'AVAILABLE':
                categories[cat]['available'] += 1
            elif state == 'PENDING':
                categories[cat]['pending'] += 1
            elif state == 'UNAVAILABLE':
                categories[cat]['occupied'] += 1
        
        self.print_header("BREAKDOWN BY CATEGORY")
        
        print(f"{'Category':<12} {'Total':<8} {'Available':<12} {'Pending':<10} {'Occupied':<10}")
        print("-" * 70)
        
        for cat, stats in sorted(categories.items()):
            color = self.COLORS.get(cat, '')
            category_str = f"{color}{cat:<12}{self.COLORS['RESET']}"
            
            print(f"{category_str} {stats['total']:<8} "
                  f"{self.COLORS['AVAILABLE']}{stats['available']:<12}{self.COLORS['RESET']} "
                  f"{self.COLORS['PENDING']}{stats['pending']:<10}{self.COLORS['RESET']} "
                  f"{self.COLORS['UNAVAILABLE']}{stats['occupied']:<10}{self.COLORS['RESET']}")
        
        print()
    
    def print_full_status(self):
        """Print complete system status"""
        print("\n" * 2)
        print(f"{self.COLORS['BOLD']}{'#'*70}{self.COLORS['RESET']}")
        print(f"{self.COLORS['BOLD']}# SMART PARKING MANAGEMENT SYSTEM - LIVE STATUS{' '*21}#{self.COLORS['RESET']}")
        print(f"{self.COLORS['BOLD']}# {Clock.iso_format():<66} #{self.COLORS['RESET']}")
        print(f"{self.COLORS['BOLD']}{'#'*70}{self.COLORS['RESET']}")
        
        self.print_summary()
        self.print_bay_status()
        self.print_category_breakdown()
        self.print_events()
    
    def clear_screen(self):
        """Clear the console screen"""
        import os
        os.system('cls' if os.name == 'nt' else 'clear')
