"""
Test Camera ALPR - Standalone test
Run this to test your USB camera and plate detection before integrating with SPMS
"""

import cv2
import sys
from paddleocr import PaddleOCR

print("=" * 60)
print("CAMERA ALPR TEST")
print("=" * 60)

# Step 1: Check camera
print("\n1. Testing camera access...")
camera_index = 0  # Change this if you have multiple cameras (0, 1, 2, etc.)

cap = cv2.VideoCapture(camera_index)

if not cap.isOpened():
    print(f"❌ ERROR: Cannot open camera {camera_index}")
    print("Try changing camera_index to 1 or 2 if you have multiple cameras")
    sys.exit(1)

# Set camera resolution
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

ret, frame = cap.read()
if not ret:
    print("❌ ERROR: Camera opened but cannot read frames")
    cap.release()
    sys.exit(1)

print(f"✅ Camera {camera_index} working!")
print(f"   Resolution: {frame.shape[1]}x{frame.shape[0]}")

# Step 2: Initialize PaddleOCR
print("\n2. Loading PaddleOCR...")
print("   (This may take a minute on first run - downloading models)")

try:
    ocr = PaddleOCR(use_textline_orientation=True, lang='en')
    print("✅ PaddleOCR loaded successfully!")
except Exception as e:
    print(f"❌ ERROR loading PaddleOCR: {e}")
    cap.release()
    sys.exit(1)

# Step 3: Live plate detection
print("\n3. Starting live detection...")
print("\n" + "=" * 60)
print("INSTRUCTIONS:")
print("  - Point camera at a license plate")
print("  - Press 'c' to capture and read plate")
print("  - Press 's' to save current frame")
print("  - Press 'q' to quit")
print("=" * 60 + "\n")

frame_count = 0
detected_plates = []

while True:
    ret, frame = cap.read()
    if not ret:
        break
    
    frame_count += 1
    display_frame = frame.copy()
    
    # Show instructions
    cv2.putText(display_frame, "Press 'c' to detect plate | 'q' to quit", 
               (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
    
    # Show previously detected plates
    if detected_plates:
        y_offset = 60
        cv2.putText(display_frame, "Detected:", 
                   (10, y_offset), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
        for i, plate in enumerate(detected_plates[-5:]):  # Show last 5
            y_offset += 25
            cv2.putText(display_frame, f"  {plate}", 
                       (10, y_offset), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 1)
    
    cv2.imshow('Camera ALPR Test', display_frame)
    
    key = cv2.waitKey(1) & 0xFF
    
    if key == ord('q'):
        print("\nQuitting...")
        break
    
    elif key == ord('c'):
        print("\n📸 Capturing and reading plate...")
        
        # Preprocess frame
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        enhanced = cv2.equalizeHist(gray)
        enhanced_bgr = cv2.cvtColor(enhanced, cv2.COLOR_GRAY2BGR)
        
        # Run OCR
        try:
            result = ocr.predict(enhanced_bgr)
            
            if result and result[0]:
                print(f"   Found {len(result[0])} text regions:")
                
                best_text = None
                best_confidence = 0.0
                
                for line in result[0]:
                    text = line[1][0]
                    confidence = line[1][1]
                    print(f"     - '{text}' (confidence: {confidence:.2f})")
                    
                    # Filter for plate-like text (4-10 alphanumeric characters)
                    text_clean = ''.join(filter(str.isalnum, text)).upper()
                    
                    if 4 <= len(text_clean) <= 10 and confidence > best_confidence:
                        best_text = text_clean
                        best_confidence = confidence
                
                if best_text and best_confidence > 0.7:
                    print(f"\n   ✅ PLATE DETECTED: {best_text} (conf: {best_confidence:.2f})")
                    detected_plates.append(f"{best_text} ({best_confidence:.2f})")
                else:
                    print(f"\n   ⚠️  Low confidence or invalid format")
                    if best_text:
                        print(f"      Best guess: {best_text} ({best_confidence:.2f})")
            else:
                print("   ❌ No text detected in frame")
                print("      Try:")
                print("      - Moving closer to the plate")
                print("      - Better lighting")
                print("      - Cleaner plate")
        
        except Exception as e:
            print(f"   ❌ OCR Error: {e}")
    
    elif key == ord('s'):
        filename = f"test_frame_{frame_count}.jpg"
        cv2.imwrite(filename, frame)
        print(f"\n💾 Frame saved: {filename}")

cap.release()
cv2.destroyAllWindows()

print("\n" + "=" * 60)
print("TEST COMPLETE!")
if detected_plates:
    print(f"Total plates detected: {len(detected_plates)}")
    print("Last 5 detections:")
    for plate in detected_plates[-5:]:
        print(f"  - {plate}")
else:
    print("No plates detected.")
    print("\nTroubleshooting tips:")
    print("  1. Make sure there's good lighting on the plate")
    print("  2. Hold the plate steady and fill most of the frame")
    print("  3. Try printing a test plate image and point camera at it")
print("=" * 60)
