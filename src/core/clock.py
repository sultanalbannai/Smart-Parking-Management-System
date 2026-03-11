"""
Clock - System-wide time synchronization utility
Provides consistent timestamps and monotonic timing for the SPMS
"""

import time
from datetime import datetime, timezone
from typing import Optional


class Clock:
    """
    Centralized time source for the Smart Parking Management System.
    Ensures all components use consistent timestamps.
    """
    
    _start_time: Optional[float] = None
    
    @classmethod
    def now(cls) -> datetime:
        """
        Returns the current system timestamp in UTC.
        
        Returns:
            datetime: Current UTC timestamp
        """
        return datetime.now(timezone.utc)
    
    @classmethod
    def monotonic_ms(cls) -> int:
        """
        Returns a monotonically increasing millisecond value.
        Useful for measuring elapsed time and timing logic.
        
        Returns:
            int: Milliseconds since program start
        """
        if cls._start_time is None:
            cls._start_time = time.monotonic()
        
        elapsed = time.monotonic() - cls._start_time
        return int(elapsed * 1000)
    
    @classmethod
    def timestamp_ms(cls) -> int:
        """
        Returns current timestamp in milliseconds since epoch.
        
        Returns:
            int: Milliseconds since Unix epoch
        """
        return int(cls.now().timestamp() * 1000)
    
    @classmethod
    def iso_format(cls, dt: Optional[datetime] = None) -> str:
        """
        Formats a datetime as ISO 8601 string.
        
        Args:
            dt: Datetime to format (defaults to now)
            
        Returns:
            str: ISO 8601 formatted timestamp
        """
        if dt is None:
            dt = cls.now()
        return dt.isoformat()
    
    @classmethod
    def elapsed_ms(cls, start_ms: int) -> int:
        """
        Calculate elapsed time from a monotonic timestamp.
        
        Args:
            start_ms: Starting monotonic millisecond value
            
        Returns:
            int: Elapsed milliseconds
        """
        return cls.monotonic_ms() - start_ms
