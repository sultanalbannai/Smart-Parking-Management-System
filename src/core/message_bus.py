"""
MessageBus - Event-driven communication backbone
Provides MQTT-based publish/subscribe messaging between system components
"""

import json
import logging
from typing import Callable, Dict, List, Any, Optional
from threading import Lock
import paho.mqtt.client as mqtt

from .clock import Clock
from .config import config


logger = logging.getLogger(__name__)


class MessageBus:
    """
    MQTT-based message bus for asynchronous communication.
    Implements publish/subscribe pattern for system-wide events.
    """
    
    def __init__(self, broker: str = "localhost", port: int = 1883):
        """
        Initialize message bus.
        
        Args:
            broker: MQTT broker address
            port: MQTT broker port
        """
        self.broker = broker
        self.port = port
        self.client: Optional[mqtt.Client] = None
        self.subscribers: Dict[str, List[Callable]] = {}
        self.lock = Lock()
        self.connected = False
        
    def connect(self):
        """Establish connection to MQTT broker"""
        try:
            self.client = mqtt.Client(client_id=f"spms_{Clock.monotonic_ms()}")
            
            # Set callbacks
            self.client.on_connect = self._on_connect
            self.client.on_message = self._on_message
            self.client.on_disconnect = self._on_disconnect
            
            # Connect to broker
            self.client.connect(self.broker, self.port, keepalive=60)
            self.client.loop_start()
            
            logger.info(f"MessageBus connecting to {self.broker}:{self.port}")
            
        except Exception as e:
            logger.error(f"Failed to connect to MQTT broker: {e}")
            raise
    
    def disconnect(self):
        """Disconnect from MQTT broker"""
        if self.client:
            self.client.loop_stop()
            self.client.disconnect()
            self.connected = False
            logger.info("MessageBus disconnected")
    
    def publish(self, topic: str, payload: Dict[str, Any], retained: bool = False):
        """
        Publish a message to a topic.
        
        Args:
            topic: MQTT topic
            payload: Message payload (will be JSON serialized)
            retained: Whether message should be retained by broker
        """
        if not self.connected:
            logger.warning(f"Cannot publish to {topic}: not connected")
            return
        
        try:
            # Add timestamp if not present
            if 'timestamp' not in payload:
                payload['timestamp'] = Clock.timestamp_ms()
            
            # Serialize to JSON
            message = json.dumps(payload)
            
            # Publish
            result = self.client.publish(topic, message, qos=1, retain=retained)
            
            if result.rc == mqtt.MQTT_ERR_SUCCESS:
                logger.debug(f"Published to {topic}: {payload}")
            else:
                logger.error(f"Failed to publish to {topic}: {result.rc}")
                
        except Exception as e:
            logger.error(f"Error publishing to {topic}: {e}")
    
    def subscribe(self, topic: str, callback: Callable[[str, Dict[str, Any]], None]):
        """
        Subscribe to a topic with a callback function.
        
        Args:
            topic: MQTT topic (supports wildcards)
            callback: Function to call when message received
                      Signature: callback(topic: str, payload: dict)
        """
        with self.lock:
            if topic not in self.subscribers:
                self.subscribers[topic] = []
                
                # Subscribe to MQTT topic
                if self.connected and self.client:
                    self.client.subscribe(topic, qos=1)
                    logger.info(f"Subscribed to topic: {topic}")
            
            self.subscribers[topic].append(callback)
    
    def unsubscribe(self, topic: str, callback: Optional[Callable] = None):
        """
        Unsubscribe from a topic.
        
        Args:
            topic: MQTT topic
            callback: Specific callback to remove (if None, removes all)
        """
        with self.lock:
            if topic in self.subscribers:
                if callback:
                    self.subscribers[topic].remove(callback)
                    if not self.subscribers[topic]:
                        del self.subscribers[topic]
                        if self.client:
                            self.client.unsubscribe(topic)
                else:
                    del self.subscribers[topic]
                    if self.client:
                        self.client.unsubscribe(topic)
                
                logger.info(f"Unsubscribed from topic: {topic}")
    
    def _on_connect(self, client, userdata, flags, rc):
        """Callback when connected to broker"""
        if rc == 0:
            self.connected = True
            logger.info("MessageBus connected successfully")
            
            # Resubscribe to all topics
            with self.lock:
                for topic in self.subscribers.keys():
                    client.subscribe(topic, qos=1)
                    logger.info(f"Resubscribed to {topic}")
        else:
            logger.error(f"Connection failed with code {rc}")
    
    def _on_disconnect(self, client, userdata, rc):
        """Callback when disconnected from broker"""
        self.connected = False
        if rc != 0:
            logger.warning(f"Unexpected disconnection (code {rc})")
        else:
            logger.info("Disconnected from broker")
    
    def _on_message(self, client, userdata, msg):
        """Callback when message received"""
        try:
            # Decode payload
            payload = json.loads(msg.payload.decode())
            topic = msg.topic
            
            logger.debug(f"Received message on {topic}: {payload}")
            
            # Find matching subscribers
            with self.lock:
                for sub_topic, callbacks in self.subscribers.items():
                    if self._topic_matches(sub_topic, topic):
                        for callback in callbacks:
                            try:
                                callback(topic, payload)
                            except Exception as e:
                                logger.error(f"Error in callback for {topic}: {e}")
        
        except json.JSONDecodeError as e:
            logger.error(f"Failed to decode message on {msg.topic}: {e}")
        except Exception as e:
            logger.error(f"Error processing message: {e}")
    
    @staticmethod
    def _topic_matches(subscription: str, topic: str) -> bool:
        """
        Check if a topic matches a subscription pattern.
        Supports MQTT wildcards: + (single level), # (multi level)
        
        Args:
            subscription: Subscription pattern
            topic: Actual topic
            
        Returns:
            bool: True if topic matches subscription
        """
        sub_parts = subscription.split('/')
        topic_parts = topic.split('/')
        
        if '#' in sub_parts:
            # Multi-level wildcard
            hash_idx = sub_parts.index('#')
            if hash_idx != len(sub_parts) - 1:
                return False  # # must be last
            return sub_parts[:hash_idx] == topic_parts[:hash_idx]
        
        if len(sub_parts) != len(topic_parts):
            return False
        
        for sub, top in zip(sub_parts, topic_parts):
            if sub != '+' and sub != top:
                return False
        
        return True
