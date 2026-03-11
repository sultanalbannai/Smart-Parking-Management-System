"""
Configuration management for SPMS
Loads and provides access to system configuration
"""

import yaml
from pathlib import Path
from typing import Dict, Any, List, Optional
from dataclasses import dataclass


@dataclass
class BayConfig:
    """Configuration for a single parking bay"""
    id: str
    category: str
    distance_from_gate: float
    zone: int


@dataclass
class MQTTConfig:
    """MQTT broker configuration"""
    broker: str
    port: int
    keepalive: int
    topics: Dict[str, str]


class Config:
    """
    Singleton configuration manager for SPMS.
    Loads settings from YAML and provides typed access.
    """
    
    _instance: Optional['Config'] = None
    _config: Dict[str, Any] = {}
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def load(self, config_path: str = "config/default_config.yaml"):
        """
        Load configuration from YAML file.
        
        Args:
            config_path: Path to configuration file
        """
        path = Path(config_path)
        if not path.exists():
            raise FileNotFoundError(f"Configuration file not found: {config_path}")
        
        with open(path, 'r') as f:
            self._config = yaml.safe_load(f)
    
    @property
    def facility_name(self) -> str:
        return self._config.get('facility', {}).get('name', 'SPMS')
    
    @property
    def total_bays(self) -> int:
        return self._config.get('facility', {}).get('total_bays', 7)
    
    @property
    def gate_id(self) -> str:
        return self._config.get('facility', {}).get('gate_id', 'G1')
    
    @property
    def bays(self) -> List[BayConfig]:
        """Get list of bay configurations"""
        bay_configs = []
        for bay_data in self._config.get('bays', []):
            bay_configs.append(BayConfig(
                id=bay_data['id'],
                category=bay_data['category'],
                distance_from_gate=bay_data['distance_from_gate'],
                zone=bay_data['zone']
            ))
        return bay_configs
    
    @property
    def priorities(self) -> List[str]:
        return self._config.get('priorities', ['POD', 'STAFF', 'GENERAL'])
    
    @property
    def incoming_ttl(self) -> int:
        """Time-to-live for PENDING bay reservations (seconds)"""
        return self._config.get('timing', {}).get('incoming_ttl', 300)
    
    @property
    def confirmation_timeout(self) -> int:
        """Timeout for bay confirmation (seconds)"""
        return self._config.get('timing', {}).get('confirmation_timeout', 120)
    
    @property
    def debounce_window(self) -> float:
        """Debounce window for occupancy detection (seconds)"""
        return self._config.get('timing', {}).get('debounce_window', 2.0)
    
    @property
    def ui_refresh_rate(self) -> float:
        """UI refresh rate in Hz"""
        return self._config.get('timing', {}).get('ui_refresh_rate', 2.0)
    
    @property
    def mqtt(self) -> MQTTConfig:
        """Get MQTT configuration"""
        mqtt_config = self._config.get('mqtt', {})
        return MQTTConfig(
            broker=mqtt_config.get('broker', 'localhost'),
            port=mqtt_config.get('port', 1883),
            keepalive=mqtt_config.get('keepalive', 60),
            topics=mqtt_config.get('topics', {})
        )
    
    @property
    def database_path(self) -> str:
        return self._config.get('database', {}).get('path', 'data/spms.db')
    
    def get(self, key: str, default: Any = None) -> Any:
        """
        Get configuration value by dot-notation key.
        
        Args:
            key: Configuration key (e.g., 'simulation.enable_noise')
            default: Default value if key not found
            
        Returns:
            Configuration value
        """
        keys = key.split('.')
        value = self._config
        
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
                if value is None:
                    return default
            else:
                return default
        
        return value if value is not None else default


# Global configuration instance
config = Config()
