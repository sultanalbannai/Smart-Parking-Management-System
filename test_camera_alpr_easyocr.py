"""
Test Camera ALPR - Standalone test with EasyOCR
Run this to test your USB camera and plate detection before integrating with SPMS
"""
import time
import re
import cv2
import sys
import easyocr

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

# Step 2: Initialize EasyOCR
print("\n2. Loading EasyOCR...")
print("   (This may take a minute on first run - downloading models)")

try:
    reader = easyocr.Reader(['en'], gpu=False)
    print("✅ EasyOCR loaded successfully!")
except Exception as e:
    print(f"❌ ERROR loading EasyOCR: {e}")
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

# -------------------------------
# AUTO-DETECT CONFIG + STATE
# -------------------------------
OCR_EVERY_N_FRAMES = 2      # Run OCR almost every frame
MIN_CONF = 0.40             # Slightly lower threshold
STREAK_TO_TRIGGER = 2       # Only need 2 consistent reads
TRIGGER_COOLDOWN_SEC = 2.0  # Shorter cooldown

last_candidate = None
streak = 0
last_trigger_time = 0.0

def normalize_plate(text: str) -> str:
    # Keep only letters/numbers, uppercase
    return re.sub(r'[^A-Z0-9]', '', text.upper())

def is_plausible_plate(t: str) -> bool:
    # Generic plate rule: 4–10 alphanumeric chars (adjust later for UAE format if you want)
    return 4 <= len(t) <= 10

while True:
    ret, frame = cap.read()
    if not ret:
        break

    frame_count += 1
    display_frame = frame.copy()

    # Show instructions
    cv2.putText(display_frame, "AUTO plate detect | 's' save | 'q' quit",
               (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

    # Show previously detected plates
    if detected_plates:
        y_offset = 60
        cv2.putText(display_frame, "Detected:",
                   (10, y_offset), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
        for plate in enumerate(detected_plates[-5:]):  # Show last 5
            y_offset += 25
            cv2.putText(display_frame, f"  {plate[1]}",
                       (10, y_offset), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 1)

    # -------------------------------
    # AUTO OCR (every N frames)
    # -------------------------------
    if frame_count % OCR_EVERY_N_FRAMES == 0:
        try:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            results = reader.readtext(gray)

            best_text = None
            best_conf = 0.0

            for (bbox, text, conf) in results:
                t = normalize_plate(text)
                if conf >= MIN_CONF and is_plausible_plate(t):
                    if conf > best_conf:
                        best_text, best_conf = t, conf

            if best_text:
                # streak / debounce
                if best_text == last_candidate:
                    streak += 1
                else:
                    last_candidate = best_text
                    streak = 1

                # overlay candidate info
                cv2.putText(display_frame, f"Candidate: {best_text} ({best_conf:.2f}) streak={streak}",
                            (10, frame.shape[0] - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

                # trigger if stable + not cooling down
                now = time.time()
                if streak >= STREAK_TO_TRIGGER and (now - last_trigger_time) >= TRIGGER_COOLDOWN_SEC:
                    last_trigger_time = now
                    streak = 0

                    print(f"\n✅ AUTO PLATE DETECTED: {best_text} (conf: {best_conf:.2f})")
                    detected_plates.append(f"{best_text} ({best_conf:.2f})")

                    # Optional: auto-save a frame when it triggers
                    filename = f"auto_plate_{best_text}_{int(now)}.jpg"
                    cv2.imwrite(filename, frame)
                    print(f"💾 Saved trigger frame: {filename}")

            else:
                # reset when nothing plausible is found
                last_candidate = None
                streak = 0

        except Exception as e:
            print(f"   ❌ OCR Error: {e}")

    cv2.imshow('Camera ALPR Test', display_frame)

    key = cv2.waitKey(1) & 0xFF

    if key == ord('q'):
        print("\nQuitting...")
        break

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
