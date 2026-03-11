"""
Core utilities and infrastructure for SPMS
"""

import os
from .clock import Clock
from .config import config, Config

# Use simple message bus by default (no MQTT broker needed)
# Set environment variable USE_MQTT=1 to use real MQTT broker
if os.getenv('USE_MQTT', '0') == '1':
    try:
        from .message_bus import MessageBus
        print("Using real MQTT message bus")
    except ImportError:
        from .simple_message_bus import MessageBus
        print("MQTT not available, using simple message bus")
else:
    from .simple_message_bus import MessageBus

__all__ = ['Clock', 'config', 'Config', 'MessageBus']
