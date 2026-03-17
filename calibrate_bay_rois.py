"""
Bay ROI Calibration Tool
=========================
Interactively draw bounding-box ROIs for each bay on each bay camera.
Results are saved to  config/bay_rois.yaml  which is read by bay_camera_service.py.

Usage:
    python calibrate_bay_rois.py

Controls (OpenCV window):
    Click + drag  →  draw the ROI rectangle for the current bay
    ENTER / SPACE →  confirm and move to the next bay
    R             →  redo the current bay (clear rectangle)
    S             →  skip the current bay (no ROI saved)
    Q             →  quit and save all ROIs collected so far
"""

import sys
import yaml
import cv2
import numpy as np
from pathlib import Path

CONFIG_PATH = "config/camera_demo_config.yaml"
ROIS_PATH   = "config/bay_rois.yaml"

# ── Load config ───────────────────────────────────────────────────────────────
with open(CONFIG_PATH, encoding="utf-8") as f:
    cfg = yaml.safe_load(f)

bay_cameras = cfg.get("bay_cameras", [])
if not bay_cameras:
    print("No bay_cameras defined in config.")
    sys.exit(1)

# ── Drawing state ─────────────────────────────────────────────────────────────
drawing   = False
start_pt  = (0, 0)
end_pt    = (0, 0)
confirmed = False

def mouse_cb(event, x, y, flags, param):
    global drawing, start_pt, end_pt, confirmed

    if event == cv2.EVENT_LBUTTONDOWN:
        drawing   = True
        start_pt  = (x, y)
        end_pt    = (x, y)
        confirmed = False

    elif event == cv2.EVENT_MOUSEMOVE and drawing:
        end_pt = (x, y)

    elif event == cv2.EVENT_LBUTTONUP:
        drawing  = False
        end_pt   = (x, y)

# ── Helper ────────────────────────────────────────────────────────────────────

def normalise_rect(p1, p2):
    """Return (x1, y1, x2, y2) with x1<x2 and y1<y2."""
    x1, y1 = min(p1[0], p2[0]), min(p1[1], p2[1])
    x2, y2 = max(p1[0], p2[0]), max(p1[1], p2[1])
    return x1, y1, x2, y2

def rect_valid(p1, p2, min_size=20):
    x1, y1, x2, y2 = normalise_rect(p1, p2)
    return (x2 - x1) >= min_size and (y2 - y1) >= min_size

# ── Main calibration loop ─────────────────────────────────────────────────────

def calibrate():
    # Try to load existing ROIs so we can resume
    existing: dict = {}
    if Path(ROIS_PATH).exists():
        with open(ROIS_PATH, encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
        for cam in raw.get("cameras", []):
            existing[cam["camera_index"]] = {
                b["bay_id"]: b["roi"]
                for b in cam.get("bays", [])
                if b.get("roi")
            }

    output = {}   # camera_index → {bay_id: [x1,y1,x2,y2]}

    for cam_cfg in bay_cameras:
        cam_idx = cam_cfg["camera_index"]
        label   = cam_cfg.get("label", f"Camera {cam_idx}")
        bays    = cam_cfg["bays"]

        print(f"\n{'='*60}")
        print(f" {label}")
        print(f" Bays to calibrate: {bays}")
        print(f"{'='*60}")

        cap = cv2.VideoCapture(cam_idx)
        if not cap.isOpened():
            print(f"  ❌ Cannot open camera {cam_idx} – skipping")
            continue

        cap.set(cv2.CAP_PROP_FRAME_WIDTH,  1280)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

        win_name = f"Calibrate – {label}"
        cv2.namedWindow(win_name)
        cv2.setMouseCallback(win_name, mouse_cb)

        cam_rois = dict(existing.get(cam_idx, {}))   # start with any saved ROIs

        for bay_id in bays:
            global start_pt, end_pt, drawing

            # If already calibrated, show existing ROI and ask to keep/redo
            if bay_id in cam_rois:
                print(f"  {bay_id} already has ROI {cam_rois[bay_id]} – press ENTER to keep, R to redo, S to skip")
                start_pt = end_pt = (0, 0)

            print(f"\n  → Draw ROI for  {bay_id}  (ENTER=confirm  R=redo  S=skip  Q=quit)")

            start_pt = end_pt = (0, 0)

            while True:
                ret, frame = cap.read()
                if not ret:
                    break

                display = frame.copy()

                # Draw all already-confirmed ROIs for this camera (grey)
                for bid, roi in cam_rois.items():
                    x1, y1, x2, y2 = roi
                    cv2.rectangle(display, (x1, y1), (x2, y2), (100, 100, 100), 1)
                    cv2.putText(display, bid, (x1 + 4, y1 + 14),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (180, 180, 180), 1)

                # Draw active rectangle (green while dragging, cyan when released)
                if start_pt != end_pt:
                    colour = (0, 255, 0) if drawing else (255, 255, 0)
                    x1, y1, x2, y2 = normalise_rect(start_pt, end_pt)
                    cv2.rectangle(display, (x1, y1), (x2, y2), colour, 2)

                # Instructions overlay
                cv2.putText(display,
                            f"Bay: {bay_id}  |  ENTER=confirm  R=redo  S=skip  Q=quit",
                            (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)

                cv2.imshow(win_name, display)
                key = cv2.waitKey(1) & 0xFF

                if key in (13, 32):   # ENTER or SPACE – confirm
                    if rect_valid(start_pt, end_pt):
                        roi = list(normalise_rect(start_pt, end_pt))
                        cam_rois[bay_id] = roi
                        print(f"    ✅ {bay_id} → {roi}")
                        break
                    else:
                        print("    ⚠️  Rectangle too small – draw again")

                elif key == ord('r'):  # Redo
                    start_pt = end_pt = (0, 0)
                    print(f"    🔄 Redoing {bay_id}")

                elif key == ord('s'):  # Skip
                    print(f"    ⏭  Skipped {bay_id}")
                    break

                elif key == ord('q'):  # Quit early
                    print("\n  ⚠️  Quit – saving collected ROIs")
                    output[cam_idx] = cam_rois
                    cap.release()
                    cv2.destroyAllWindows()
                    _save(output)
                    return

        output[cam_idx] = cam_rois
        cap.release()
        cv2.destroyWindow(win_name)
        print(f"\n  Camera {cam_idx} done – {len(cam_rois)} ROIs saved")

    cv2.destroyAllWindows()
    _save(output)


def _save(output: dict):
    cameras_list = []
    for cam_idx, bay_rois in output.items():
        bays_list = [{"bay_id": bid, "roi": roi} for bid, roi in bay_rois.items()]
        cameras_list.append({"camera_index": cam_idx, "bays": bays_list})

    data = {"cameras": cameras_list}
    Path(ROIS_PATH).parent.mkdir(parents=True, exist_ok=True)
    with open(ROIS_PATH, "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)

    total = sum(len(v) for v in output.values())
    print(f"\n✅ Saved {total} ROIs → {ROIS_PATH}")
    print("\nYou can now run:  python run_camera_demo.py\n")


if __name__ == "__main__":
    print("\n" + "="*60)
    print(" BAY ROI CALIBRATION TOOL ".center(60))
    print("="*60)
    print(f" Config : {CONFIG_PATH}")
    print(f" Output : {ROIS_PATH}")
    print("="*60)
    calibrate()
