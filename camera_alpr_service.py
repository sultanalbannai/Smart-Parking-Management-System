"""
Real Camera ALPR Service - USB Camera Integration
Captures frames from USB camera and performs license plate recognition
"""

import cv2
import logging
import uuid
from datetime import datetime, timedelta
from typing import Optional, Tuple
import numpy as np
from paddleocr import PaddleOCR
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class CameraALPRService:
    """
    Real ALPR using USB camera.
    Replaces simulated gate_alpr with actual camera + OCR.
    """
    
    def __init__(self, db_session: Session, message_bus, gate_id: str = "G1", 
                 camera_index: int = 0):
        """
        Initialize camera ALPR service.
        
        Args:
            db_session: Database session
            message_bus: Message bus for publishing events
            gate_id: Gate identifier
            camera_index: USB camera index (0 = first camera, 1 = second, etc.)
        """
        self.db = db_session
        self.bus = message_bus
        self.gate_id = gate_id
        self.camera_index = camera_index
        
        # Initialize camera
        self.camera = None
        self.is_camera_ready = False
        
        # Initialize PaddleOCR for license plate reading
        # use_angle_cls=True helps with rotated plates
        # lang='en' for English, use 'ch' for Chinese
        self.ocr = PaddleOCR(
            use_angle_cls=True, 
            lang='en',
            use_gpu=False,  # Set to True if you have CUDA
            show_log=False
        )
        
        logger.info(f"Camera ALPR initialized for gate {gate_id}")
    
    def start_camera(self) -> bool:
        """
        Start the USB camera.
        
        Returns:
            bool: True if camera started successfully
        """
        try:
            self.camera = cv2.VideoCapture(self.camera_index)
            
            if not self.camera.isOpened():
                logger.error(f"Failed to open camera {self.camera_index}")
                return False
            
            # Set camera properties for better quality
            self.camera.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
            self.camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
            self.camera.set(cv2.CAP_PROP_FPS, 30)
            
            # Test read
            ret, frame = self.camera.read()
            if not ret:
                logger.error("Camera opened but cannot read frames")
                return False
            
            self.is_camera_ready = True
            logger.info(f"Camera {self.camera_index} started successfully")
            return True
            
        except Exception as e:
            logger.error(f"Error starting camera: {e}")
            return False
    
    def stop_camera(self):
        """Stop and release the camera."""
        if self.camera is not None:
            self.camera.release()
            self.is_camera_ready = False
            logger.info("Camera stopped")
    
    def capture_frame(self) -> Optional[np.ndarray]:
        """
        Capture a single frame from the camera.
        
        Returns:
            np.ndarray: Captured frame, or None if failed
        """
        if not self.is_camera_ready:
            logger.warning("Camera not ready")
            return None
        
        ret, frame = self.camera.read()
        if not ret:
            logger.error("Failed to capture frame")
            return None
        
        return frame
    
    def preprocess_frame(self, frame: np.ndarray) -> np.ndarray:
        """
        Preprocess frame for better OCR results.
        
        Args:
            frame: Raw camera frame
            
        Returns:
            Preprocessed frame
        """
        # Convert to grayscale
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        
        # Apply histogram equalization for better contrast
        enhanced = cv2.equalizeHist(gray)
        
        # Convert back to BGR for PaddleOCR
        enhanced_bgr = cv2.cvtColor(enhanced, cv2.COLOR_GRAY2BGR)
        
        return enhanced_bgr
    
    def read_license_plate(self, frame: np.ndarray) -> Tuple[Optional[str], float]:
        """
        Read license plate from frame using PaddleOCR.
        
        Args:
            frame: Image frame containing license plate
            
        Returns:
            Tuple of (plate_text, confidence)
        """
        try:
            # Preprocess frame
            processed = self.preprocess_frame(frame)
            
            # Run OCR
            result = self.ocr.ocr(processed, cls=True)
            
            if result is None or len(result) == 0 or result[0] is None:
                logger.debug("No text detected in frame")
                return None, 0.0
            
            # Extract text with highest confidence
            best_text = None
            best_confidence = 0.0
            
            for line in result[0]:
                text = line[1][0]  # Detected text
                confidence = line[1][1]  # Confidence score
                
                # Filter: license plates are usually 4-10 characters
                # and contain letters/numbers only
                text_clean = ''.join(filter(str.isalnum, text))
                
                if 4 <= len(text_clean) <= 10 and confidence > best_confidence:
                    best_text = text_clean.upper()
                    best_confidence = confidence
            
            if best_text and best_confidence > 0.7:  # Minimum confidence threshold
                logger.info(f"Detected plate: {best_text} (conf: {best_confidence:.2f})")
                return best_text, best_confidence
            else:
                logger.debug(f"Low confidence detection: {best_text} ({best_confidence:.2f})")
                return None, 0.0
                
        except Exception as e:
            logger.error(f"Error during OCR: {e}")
            return None, 0.0
    
    def wait_for_vehicle(self, timeout: int = 30) -> Tuple[Optional[str], Optional[np.ndarray]]:
        """
        Wait for a vehicle to arrive and read its plate.
        Shows live camera feed with detection overlay.
        
        Args:
            timeout: Maximum wait time in seconds
            
        Returns:
            Tuple of (plate_number, frame_with_detection)
        """
        if not self.is_camera_ready:
            logger.error("Camera not ready")
            return None, None
        
        logger.info("Waiting for vehicle... (Press 'c' to capture, 'q' to quit)")
        
        start_time = datetime.now()
        best_plate = None
        best_frame = None
        best_confidence = 0.0
        
        while True:
            # Check timeout
            if (datetime.now() - start_time).seconds > timeout:
                logger.warning("Vehicle detection timeout")
                break
            
            # Capture frame
            frame = self.capture_frame()
            if frame is None:
                continue
            
            # Try to read plate
            plate, confidence = self.read_license_plate(frame)
            
            # Update best detection
            if plate and confidence > best_confidence:
                best_plate = plate
                best_confidence = confidence
                best_frame = frame.copy()
            
            # Display frame
            display_frame = frame.copy()
            
            # Add overlay text
            if best_plate:
                cv2.putText(display_frame, f"Plate: {best_plate}", 
                           (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
                cv2.putText(display_frame, f"Conf: {best_confidence:.2f}", 
                           (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
            else:
                cv2.putText(display_frame, "Waiting for plate...", 
                           (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
            
            cv2.putText(display_frame, "Press 'c' to capture | 'q' to quit", 
                       (10, display_frame.shape[0] - 20), 
                       cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
            
            cv2.imshow('Gate Camera - ALPR', display_frame)
            
            # Handle key presses
            key = cv2.waitKey(1) & 0xFF
            
            if key == ord('c'):  # Capture
                if best_plate:
                    logger.info(f"Manual capture: {best_plate}")
                    cv2.destroyAllWindows()
                    return best_plate, best_frame
                else:
                    logger.warning("No plate detected yet, keep camera pointed at plate")
            
            elif key == ord('q'):  # Quit
                logger.info("Manual quit")
                cv2.destroyAllWindows()
                return None, None
        
        cv2.destroyAllWindows()
        return best_plate, best_frame
    
    def create_session_from_camera(self, priority_class, selected_zone: str = "ANY"):
        """
        Create a vehicle session by reading plate from camera.
        This replaces the simulated gate_alpr process_vehicle_arrival().
        
        Args:
            priority_class: PriorityClass enum (GENERAL, FAMILY, POD, STAFF)
            selected_zone: Driver's selected zone
            
        Returns:
            VehicleSession object or None if detection failed
        """
        from ..core.plate_hasher import hash_plate
        from ..core import Clock
        from ..models.database import VehicleSession
        
        logger.info("Reading license plate from camera...")
        
        plate_number, frame = self.wait_for_vehicle(timeout=60)
        
        if not plate_number:
            logger.error("Failed to read license plate")
            return None
        
        # Hash the plate for privacy
        plate_hash = hash_plate(plate_number)
        
        # Create session
        session_id = str(uuid.uuid4())
        now = Clock.now()
        
        # Map zone to entrance
        zone_to_entrance = {
            "FASHION": "ENTRANCE_A",
            "SHOPPING": "ENTRANCE_B",
            "FOOD": "ENTRANCE_C",
            "ENTERTAINMENT": "ENTRANCE_D",
            "ANY": "ENTRANCE_ANY"
        }
        selected_entrance = zone_to_entrance.get(selected_zone, "ENTRANCE_ANY")
        
        session = VehicleSession(
            session_id=session_id,
            gate_id=self.gate_id,
            plate_hash=plate_hash,
            priority_class=priority_class,
            selected_entrance=selected_entrance,
            selected_zone=selected_zone,
            created_at=now,
            expires_at=now + timedelta(hours=4)
        )
        
        self.db.add(session)
        self.db.commit()
        
        # Publish events to message bus
        self.bus.publish(
            topic="parking/sessions/created",
            payload={
                "sessionId": session.session_id,
                "gateId": self.gate_id,
                "plateHash": session.plate_hash,
                "priorityClass": session.priority_class.value,
                "selectedEntrance": selected_entrance,
                "selectedZone": selected_zone,
                "createdAt": Clock.iso_format(now)
            }
        )
        
        self.bus.publish(
            topic="parking/request",
            payload={
                "sessionId": session.session_id,
                "gateId": self.gate_id,
                "priorityClass": session.priority_class.value,
                "selectedEntrance": selected_entrance,
                "selectedZone": selected_zone,
                "timestamp": Clock.timestamp_ms()
            }
        )
        
        logger.info(f"✅ Session created for plate: {plate_number} → {session_id[:8]}...")
        
        return session
