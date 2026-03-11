"""
Simple in-memory message bus for testing without MQTT broker
Use this during development when MQTT broker is not available
"""

import json
import logging
from typing import Callable, Dict, List, Any
from threading import Lock

from .clock import Clock

logger = logging.getLogger(__name__)


class SimpleMessageBus:
    """
    Simple in-memory publish/subscribe message bus.
    Useful for testing and development without MQTT broker.
    """
    
    def __init__(self):
        """Initialize simple message bus"""
        self.subscribers: Dict[str, List[Callable]] = {}
        self.lock = Lock()
        self.connected = True
        self.message_log: List[Dict] = []  # For debugging
        
    def connect(self):
        """Simulate connection"""
        self.connected = True
        logger.info("SimpleMessageBus connected (in-memory)")
        
    def disconnect(self):
        """Simulate disconnection"""
        self.connected = False
        logger.info("SimpleMessageBus disconnected")
    
    def publish(self, topic: str, payload: Dict[str, Any], retained: bool = False):
        """
        Publish a message to subscribers.
        
        Args:
            topic: Topic string
            payload: Message payload dict
            retained: Ignored in simple implementation
        """
        if not self.connected:
            logger.warning(f"Cannot publish to {topic}: not connected")
            return
        
        # Add timestamp
        if 'timestamp' not in payload:
            payload['timestamp'] = Clock.timestamp_ms()
        
        # Log message
        self.message_log.append({
            'topic': topic,
            'payload': payload,
            'time': Clock.now()
        })
        
        logger.debug(f"Published to {topic}: {payload}")
        
        # Deliver to subscribers
        with self.lock:
            for sub_topic, callbacks in self.subscribers.items():
                if self._topic_matches(sub_topic, topic):
                    for callback in callbacks:
                        try:
                            callback(topic, payload)
                        except Exception as e:
                            logger.error(f"Error in callback for {topic}: {e}")
    
    def subscribe(self, topic: str, callback: Callable[[str, Dict[str, Any]], None]):
        """
        Subscribe to a topic.
        
        Args:
            topic: Topic pattern (supports wildcards)
            callback: Function to call on message
        """
        with self.lock:
            if topic not in self.subscribers:
                self.subscribers[topic] = []
                logger.info(f"Subscribed to topic: {topic}")
            
            self.subscribers[topic].append(callback)
    
    def unsubscribe(self, topic: str, callback: Callable = None):
        """
        Unsubscribe from a topic.
        
        Args:
            topic: Topic pattern
            callback: Specific callback to remove (None = remove all)
        """
        with self.lock:
            if topic in self.subscribers:
                if callback:
                    if callback in self.subscribers[topic]:
                        self.subscribers[topic].remove(callback)
                    if not self.subscribers[topic]:
                        del self.subscribers[topic]
                else:
                    del self.subscribers[topic]
                
                logger.info(f"Unsubscribed from topic: {topic}")
    
    @staticmethod
    def _topic_matches(subscription: str, topic: str) -> bool:
        """Check if topic matches subscription pattern (MQTT-style wildcards)"""
        sub_parts = subscription.split('/')
        topic_parts = topic.split('/')
        
        # Multi-level wildcard
        if '#' in sub_parts:
            hash_idx = sub_parts.index('#')
            if hash_idx != len(sub_parts) - 1:
                return False
            return sub_parts[:hash_idx] == topic_parts[:hash_idx]
        
        # Must have same number of levels
        if len(sub_parts) != len(topic_parts):
            return False
        
        # Check each level
        for sub, top in zip(sub_parts, topic_parts):
            if sub != '+' and sub != top:
                return False
        
        return True
    
    def get_messages(self, topic_filter: str = None) -> List[Dict]:
        """
        Get logged messages for debugging.
        
        Args:
            topic_filter: Optional topic to filter by
            
        Returns:
            List of message dicts
        """
        if topic_filter:
            return [msg for msg in self.message_log 
                   if self._topic_matches(topic_filter, msg['topic'])]
        return self.message_log.copy()
    
    def clear_log(self):
        """Clear message log"""
        self.message_log.clear()


# Alias for compatibility
MessageBus = SimpleMessageBus
