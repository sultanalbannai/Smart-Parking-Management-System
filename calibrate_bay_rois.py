"""
Bay ROI Calibration Tool
=========================
Interactively draw bounding-box ROIs for each bay on each bay camera.
Results are saved to  config/bay_rois.yaml  which is read by bay_camera_service.py.

NEW: Camera assignment step — at startup, the tool detects all connected cameras,
     shows a live preview and lets you choose which physical camera index to assign
     to each camera group.  The choice is saved back to camera_demo_config.yaml.

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

def mouse_cb(event, x, y, flags, param):
    global drawing, start_pt, end_pt
    if event == cv2.EVENT_LBUTTONDOWN:
        drawing  = True
        start_pt = (x, y)
        end_pt   = (x, y)
    elif event == cv2.EVENT_MOUSEMOVE and drawing:
        end_pt = (x, y)
    elif event == cv2.EVENT_LBUTTONUP:
        drawing = False
        end_pt  = (x, y)

# ── Helpers ───────────────────────────────────────────────────────────────────

def normalise_rect(p1, p2):
    x1, y1 = min(p1[0], p2[0]), min(p1[1], p2[1])
    x2, y2 = max(p1[0], p2[0]), max(p1[1], p2[1])
    return x1, y1, x2, y2

def rect_valid(p1, p2, min_size=20):
    x1, y1, x2, y2 = normalise_rect(p1, p2)
    return (x2 - x1) >= min_size and (y2 - y1) >= min_size

def draw_text_bg(img, text, pos, font_scale=0.6, thickness=1,
                 fg=(255, 255, 255), bg=(0, 0, 0)):
    """Draw text with a dark background for readability."""
    font = cv2.FONT_HERSHEY_SIMPLEX
    (tw, th), baseline = cv2.getTextSize(text, font, font_scale, thickness)
    x, y = pos
    cv2.rectangle(img, (x - 2, y - th - 4), (x + tw + 2, y + baseline), bg, -1)
    cv2.putText(img, text, pos, font, font_scale, fg, thickness, cv2.LINE_AA)

# ── Camera detection ──────────────────────────────────────────────────────────

def detect_cameras(max_index=8):
    """
    Return list of unique available camera indexes.
    Deduplicates cameras that appear under multiple indexes on Windows
    by comparing frames — identical frames = same physical camera.
    """
    print("\nScanning for connected cameras...")
    candidates = []
    for i in range(max_index):
        cap = cv2.VideoCapture(i, cv2.CAP_DSHOW)
        if not cap.isOpened():
            cap = cv2.VideoCapture(i)
        if cap.isOpened():
            # Grab a few frames to let auto-exposure settle
            frame = None
            for _ in range(3):
                ret, f = cap.read()
                if ret:
                    frame = f
            cap.release()
            if frame is not None:
                candidates.append((i, frame))

    # Deduplicate: drop indexes whose frame is near-identical to an earlier one
    unique = []
    seen_frames = []
    for idx, frame in candidates:
        small = cv2.resize(frame, (64, 36))
        is_dup = False
        for seen in seen_frames:
            diff = np.mean(np.abs(small.astype(float) - seen.astype(float)))
            if diff < 8.0:   # very similar → same physical camera
                print(f"  [index {idx}] duplicate of earlier camera — skipped")
                is_dup = True
                break
        if not is_dup:
            unique.append(idx)
            seen_frames.append(small)
            print(f"  [index {idx}] Camera found")

    print(f"\n  Found {len(unique)} unique camera(s): {unique}")
    return unique

# ── Camera assignment UI ──────────────────────────────────────────────────────

def assign_cameras(available_cams):
    """
    For each camera group in the config, show a live preview of all available
    cameras and let the user press a number key to assign one.

    Returns a dict: group_label → chosen_camera_index
                    None if user chose to keep the existing index.
    """
    if not available_cams:
        print("\n⚠️  No cameras detected — keeping existing config indexes.")
        return {}

    assignments = {}   # cam_cfg original index → new chosen index

    print("\n" + "="*60)
    print(" CAMERA ASSIGNMENT ".center(60))
    print("="*60)
    print(" For each camera group, a preview window will open.")
    print(f" Press  1–{len(available_cams)}  to pick the camera for that group.")
    print(" Press  K  to keep the existing index and skip assignment.")
    print(" Press  Q  to quit assignment (all groups keep existing).")
    print("="*60)

    for cam_cfg in bay_cameras:
        group_idx = cam_cfg["camera_index"]
        label     = cam_cfg.get("label", f"Camera {group_idx}")
        bays      = cam_cfg["bays"]

        print(f"\n──────────────────────────────────────────")
        print(f"  Assigning: {label}")
        print(f"  Bays      : {bays}")
        print(f"  Current index in config: {group_idx}")
        print(f"  Available cameras: {available_cams}")
        print(f"  Press 1-{len(available_cams)} to select  |  K = keep  |  Q = quit")

        # Open all available cameras
        caps = {}
        for idx in available_cams:
            cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW)
            if not cap.isOpened():
                cap = cv2.VideoCapture(idx)
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 360)
            caps[idx] = cap

        win_name = f"Assign camera - {label}"
        cv2.namedWindow(win_name, cv2.WINDOW_NORMAL)

        chosen = None
        aborted = False

        while True:
            frames = []
            for idx in available_cams:
                ret, frame = caps[idx].read()
                if not ret or frame is None:
                    frame = np.zeros((360, 640, 3), dtype=np.uint8)

                # Resize each preview to consistent size
                frame = cv2.resize(frame, (640, 360))

                # Label overlay
                num = available_cams.index(idx) + 1
                draw_text_bg(frame, f"[{num}] Camera index {idx}", (10, 32),
                             font_scale=0.8, thickness=2,
                             fg=(0, 255, 255), bg=(0, 0, 0))

                frames.append(frame)

            # Tile previews side by side (up to 4 per row)
            cols     = min(len(frames), 3)
            rows     = (len(frames) + cols - 1) // cols
            # pad to fill grid
            while len(frames) < rows * cols:
                frames.append(np.zeros((360, 640, 3), dtype=np.uint8))

            grid_rows = []
            for r in range(rows):
                grid_rows.append(np.hstack(frames[r * cols:(r + 1) * cols]))
            grid = np.vstack(grid_rows)

            # Header bar
            header_h = 56
            header   = np.zeros((header_h, grid.shape[1], 3), dtype=np.uint8)
            draw_text_bg(header,
                         f"Assigning: {label}  |  Bays: {', '.join(bays)}",
                         (10, 22), font_scale=0.7, thickness=2,
                         fg=(255, 255, 255), bg=(0, 0, 0))
            draw_text_bg(header,
                         f"Press 1-{len(available_cams)} to select   K = keep current ({group_idx})   Q = quit",
                         (10, 48), font_scale=0.55, thickness=1,
                         fg=(180, 220, 255), bg=(0, 0, 0))

            display = np.vstack([header, grid])
            cv2.imshow(win_name, display)

            key = cv2.waitKey(1) & 0xFF

            # Number keys 1–9
            for n, cam_idx in enumerate(available_cams, start=1):
                if key == ord(str(n)):
                    chosen = cam_idx
                    print(f"  → Selected camera index {cam_idx} for '{label}'")
                    break

            if chosen is not None:
                break

            if key in (ord('k'), ord('K')):
                chosen = group_idx   # keep existing
                print(f"  → Keeping existing index {group_idx} for '{label}'")
                break

            if key in (ord('q'), ord('Q')):
                print("  ⚠️  Assignment aborted — keeping all existing indexes.")
                aborted = True
                break

        # Release all caps for this group
        for cap in caps.values():
            cap.release()
        cv2.destroyWindow(win_name)

        if aborted:
            break

        assignments[group_idx] = chosen

    return assignments


def apply_assignments(assignments: dict):
    """
    Update camera_demo_config.yaml with the chosen camera indexes
    and return the updated bay_cameras list.
    """
    if not assignments:
        return bay_cameras

    updated = False
    for cam_cfg in bay_cameras:
        old_idx = cam_cfg["camera_index"]
        new_idx = assignments.get(old_idx)
        if new_idx is not None and new_idx != old_idx:
            print(f"  Config updated: '{cam_cfg.get('label')}' "
                  f"index {old_idx} → {new_idx}")
            cam_cfg["camera_index"] = new_idx
            updated = True

    if updated:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            yaml.dump(cfg, f, default_flow_style=False, sort_keys=False,
                      allow_unicode=True)
        print(f"  ✅ Saved updated config → {CONFIG_PATH}")
    else:
        print("  No config changes needed.")

    return bay_cameras


# ── Main calibration loop ─────────────────────────────────────────────────────

def calibrate():
    # ── Step 1: Detect cameras and let user assign them ───────────────────────
    available = detect_cameras()
    if len(available) > 1 or (len(available) == 1 and available[0] != bay_cameras[0].get("camera_index")):
        assignments = assign_cameras(available)
        apply_assignments(assignments)
    else:
        print("\nOnly one camera found or indexes already match — skipping assignment step.")

    # ── Step 2: ROI drawing ───────────────────────────────────────────────────
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

    output = {}

    for cam_cfg in bay_cameras:
        cam_idx = cam_cfg["camera_index"]
        label   = cam_cfg.get("label", f"Camera {cam_idx}")
        bays    = cam_cfg["bays"]

        print(f"\n{'='*60}")
        print(f" {label}  [camera index {cam_idx}]")
        print(f" Bays to calibrate: {bays}")
        print(f"{'='*60}")

        cap = cv2.VideoCapture(cam_idx, cv2.CAP_DSHOW)
        if not cap.isOpened():
            cap = cv2.VideoCapture(cam_idx)
        if not cap.isOpened():
            print(f"  ❌ Cannot open camera {cam_idx} — skipping")
            continue

        cap.set(cv2.CAP_PROP_FRAME_WIDTH,  1280)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

        win_name = f"Calibrate - {label}"
        cv2.namedWindow(win_name)
        cv2.setMouseCallback(win_name, mouse_cb)

        cam_rois = dict(existing.get(cam_idx, {}))

        for bay_id in bays:
            global start_pt, end_pt, drawing

            if bay_id in cam_rois:
                print(f"  {bay_id} already has ROI {cam_rois[bay_id]} — ENTER=keep  R=redo  S=skip")

            print(f"\n  → Draw ROI for  {bay_id}  (ENTER=confirm  R=redo  S=skip  Q=quit)")
            start_pt = end_pt = (0, 0)

            while True:
                ret, frame = cap.read()
                if not ret:
                    break

                display = frame.copy()

                # Existing ROIs (grey)
                for bid, roi in cam_rois.items():
                    x1, y1, x2, y2 = roi
                    cv2.rectangle(display, (x1, y1), (x2, y2), (100, 100, 100), 1)
                    draw_text_bg(display, bid, (x1 + 4, y1 + 16),
                                 font_scale=0.45, fg=(180, 180, 180), bg=(30, 30, 30))

                # Active rectangle
                if start_pt != end_pt:
                    colour = (0, 255, 0) if drawing else (0, 220, 255)
                    x1, y1, x2, y2 = normalise_rect(start_pt, end_pt)
                    cv2.rectangle(display, (x1, y1), (x2, y2), colour, 2)
                    # Show size
                    size_txt = f"{x2-x1} x {y2-y1}px"
                    draw_text_bg(display, size_txt, (x1, y2 + 18),
                                 font_scale=0.45, fg=(0, 220, 255), bg=(0, 0, 0))

                # Header instructions
                draw_text_bg(display,
                             f"Bay: {bay_id}   ENTER=confirm   R=redo   S=skip   Q=quit",
                             (10, 30), font_scale=0.7, thickness=2,
                             fg=(0, 255, 255), bg=(0, 0, 0))
                draw_text_bg(display,
                             f"Camera index {cam_idx}  |  {label}",
                             (10, 58), font_scale=0.5, thickness=1,
                             fg=(180, 180, 180), bg=(0, 0, 0))

                cv2.imshow(win_name, display)
                key = cv2.waitKey(1) & 0xFF

                if key in (13, 32):   # ENTER or SPACE
                    if rect_valid(start_pt, end_pt):
                        roi = list(normalise_rect(start_pt, end_pt))
                        cam_rois[bay_id] = roi
                        print(f"    ✅ {bay_id} → {roi}")
                        break
                    else:
                        print("    ⚠️  Rectangle too small — draw again")

                elif key == ord('r'):
                    start_pt = end_pt = (0, 0)
                    print(f"    🔄 Redoing {bay_id}")

                elif key == ord('s'):
                    print(f"    ⏭  Skipped {bay_id}")
                    break

                elif key == ord('q'):
                    print("\n  ⚠️  Quit — saving collected ROIs")
                    output[cam_idx] = cam_rois
                    cap.release()
                    cv2.destroyAllWindows()
                    _save(output)
                    return

        output[cam_idx] = cam_rois
        cap.release()
        cv2.destroyWindow(win_name)
        print(f"\n  Camera {cam_idx} done — {len(cam_rois)} ROIs saved")

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
    print("   You can now run:  python run_camera_demo.py\n")


if __name__ == "__main__":
    print("\n" + "="*60)
    print(" BAY ROI CALIBRATION TOOL ".center(60))
    print("="*60)
    print(f" Config : {CONFIG_PATH}")
    print(f" Output : {ROIS_PATH}")
    print("="*60)
    calibrate()
