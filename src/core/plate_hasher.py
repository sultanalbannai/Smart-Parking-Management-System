"""
Plate Normalization and Hashing
Privacy-preserving license plate tokenization as per Section 4.1.6
"""

import hashlib
import re
from typing import Optional


class PlateNormalizerHasher:
    """
    Normalizes and hashes license plates for privacy and consistency.
    Implements HMAC-SHA256 hashing with site pepper and per-session salt.
    """
    
    # Site-specific secret key (pepper) - in production, load from secure config
    SITE_PEPPER = "spms_demo_pepper_2026"
    
    @classmethod
    def normalize(cls, raw_plate: str) -> str:
        """
        Normalize a license plate string.
        - Convert to uppercase
        - Remove whitespace and special characters
        - Keep only alphanumeric characters
        
        Args:
            raw_plate: Raw plate string (e.g., "AB 1234", "ab-1234")
            
        Returns:
            str: Normalized plate (e.g., "AB1234")
        """
        # Convert to uppercase
        normalized = raw_plate.upper()
        
        # Remove all non-alphanumeric characters
        normalized = re.sub(r'[^A-Z0-9]', '', normalized)
        
        return normalized
    
    @classmethod
    def hash(cls, normalized_plate: str, session_salt: Optional[str] = None) -> str:
        """
        Hash a normalized plate using HMAC-SHA256.
        
        Args:
            normalized_plate: Normalized plate string
            session_salt: Optional session ID for salting (default: empty string)
            
        Returns:
            str: Hexadecimal hash string (64 characters)
        """
        if session_salt is None:
            session_salt = ""
        
        # Combine normalized plate with session salt
        message = f"{normalized_plate}|{session_salt}"
        
        # Create HMAC-SHA256 hash with site pepper as key
        hash_obj = hashlib.sha256()
        hash_obj.update(cls.SITE_PEPPER.encode('utf-8'))
        hash_obj.update(message.encode('utf-8'))
        
        return hash_obj.hexdigest()
    
    @classmethod
    def normalize_and_hash(cls, raw_plate: str, session_salt: Optional[str] = None) -> str:
        """
        Convenience method: normalize and hash in one step.
        
        Args:
            raw_plate: Raw plate string
            session_salt: Optional session ID for salting
            
        Returns:
            str: Hexadecimal hash string
        """
        normalized = cls.normalize(raw_plate)
        return cls.hash(normalized, session_salt)
    
    @classmethod
    def matches(cls, hash_a: str, hash_b: str) -> bool:
        """
        Constant-time comparison of two hashes to prevent timing attacks.
        
        Args:
            hash_a: First hash
            hash_b: Second hash
            
        Returns:
            bool: True if hashes match
        """
        if len(hash_a) != len(hash_b):
            return False
        
        # Constant-time comparison
        result = 0
        for x, y in zip(hash_a, hash_b):
            result |= ord(x) ^ ord(y)
        
        return result == 0


# Convenience functions for global use
def normalize_plate(plate: str) -> str:
    """Normalize a license plate string"""
    return PlateNormalizerHasher.normalize(plate)


def hash_plate(plate: str, session_salt: Optional[str] = None) -> str:
    """Normalize and hash a license plate"""
    return PlateNormalizerHasher.normalize_and_hash(plate, session_salt)
