"""
Camera Demo Web Server - Single Entrance
Serves camera_dashboard and camera_kiosk views.
Adds 'alpr_scanning' event so the kiosk can show the live scanning state.
"""

import logging
import time
import numpy as np
import cv2
from flask import Flask, render_template, jsonify, request, Response
from flask_socketio import SocketIO, emit
from sqlalchemy.orm import Session

from src.core import Clock
from src.models.database import Bay, BayState
from src.services.alert_service import AlertService

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

app = Flask(__name__)
app.config['SECRET_KEY'] = 'spms-camera-demo-secret'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')


@app.teardown_appcontext
def _release_db_session(exc=None):
    """
    After each Flask request, remove the per-thread session from the
    scoped_session registry. If the request raised, roll back first so the
    session isn't left in a 'prepared' state that poisons future queries.
    """
    try:
        if db_session is None:
            return
        if exc is not None:
            try:
                db_session.rollback()
            except Exception:
                pass
        # scoped_session has .remove(); plain Session does not.
        if hasattr(db_session, 'remove'):
            db_session.remove()
    except Exception:
        pass

db_session: Session = None
message_bus = None
_priority_queue = None          # shared queue – filled when kiosk sends priority_selected
alert_service = AlertService()  # SMS / email notification engine

# ── Camera services (registered after startup) ────────────────────────────────
_gate_camera = None
_bay_cameras  = []
_camera_rebuild_fn = None    # callable() -> (gate, [bay_services]) – restarts cameras

def register_cameras(gate_camera, bay_cameras, rebuild_fn=None):
    """
    Called from run_camera_demo once cameras are initialised.
    ``rebuild_fn`` is an optional callable that stops existing camera services,
    re-reads the config, and returns freshly started ones. The /calibrate page
    invokes it via /api/cameras/restart so users don't have to bounce the
    process when they re-assign physical camera indexes.
    """
    global _gate_camera, _bay_cameras, _camera_rebuild_fn
    _gate_camera = gate_camera
    _bay_cameras  = bay_cameras or []
    if rebuild_fn is not None:
        _camera_rebuild_fn = rebuild_fn
    logger.info(f"Cameras registered – gate: {gate_camera is not None}, "
                f"bay: {len(_bay_cameras)}")

# ── MJPEG helpers ─────────────────────────────────────────────────────────────
_STREAM_W   = 320
_STREAM_H   = 240
_STREAM_FPS = 8
_STREAM_Q   = 60   # JPEG quality 0-100

def _make_blank():
    img = np.zeros((_STREAM_H, _STREAM_W, 3), dtype=np.uint8)
    cv2.putText(img, 'No feed', (_STREAM_W // 2 - 40, _STREAM_H // 2),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (70, 70, 70), 1)
    return img

_BLANK_FRAME = None

def _mjpeg_stream(get_frame_fn):
    """Generator: yields MJPEG boundary chunks at _STREAM_FPS."""
    global _BLANK_FRAME
    if _BLANK_FRAME is None:
        _BLANK_FRAME = _make_blank()

    interval = 1.0 / _STREAM_FPS
    enc_params = [cv2.IMWRITE_JPEG_QUALITY, _STREAM_Q]

    while True:
        t0 = time.time()
        try:
            frame = get_frame_fn()
            if frame is None:
                frame = _BLANK_FRAME
            else:
                frame = cv2.resize(frame, (_STREAM_W, _STREAM_H))
            _, buf = cv2.imencode('.jpg', frame, enc_params)
            jpg = buf.tobytes()
        except Exception:
            _, buf = cv2.imencode('.jpg', _BLANK_FRAME, enc_params)
            jpg = buf.tobytes()

        yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + jpg + b'\r\n')

        elapsed = time.time() - t0
        rem = interval - elapsed
        if rem > 0:
            time.sleep(rem)


def init_system(external_db=None, external_bus=None, priority_queue=None):
    """Initialize with shared DB + message bus instances."""
    global db_session, message_bus, _priority_queue

    if external_db:
        db_session = external_db
    if priority_queue is not None:
        _priority_queue = priority_queue
    if external_bus:
        message_bus = external_bus

        message_bus.subscribe('parking/bays/+/state',         on_bay_state_update)
        message_bus.subscribe('parking/request',              on_parking_request)
        message_bus.subscribe('parking/suggestion',           on_suggestion)
        message_bus.subscribe('parking/bays/+/confirmation',  on_confirmation)
        message_bus.subscribe('alpr/scanning',                on_alpr_scanning)
        message_bus.subscribe('alpr/plate_detected',          on_plate_detected)
        message_bus.subscribe('parking/bays/plate_logged',    on_plate_logged)

        alert_service.start()
        logger.info("✅ Camera web server initialized")


# ── Message bus handlers ──────────────────────────────────────────────────────

def on_bay_state_update(topic, payload):
    bay_id = payload.get('bayId')
    state  = payload.get('state')
    logger.info(f"Bay update: {bay_id} → {state}")
    socketio.emit('bay_update', {
        'id':        bay_id,
        'state':     state,
        'timestamp': Clock.now().isoformat()
    }, namespace='/')

    # Check occupancy thresholds and fire alerts if needed
    if db_session:
        try:
            db_session.expire_all()
            bays      = db_session.query(Bay).all()
            total     = len(bays)
            available = sum(1 for b in bays if b.state == BayState.AVAILABLE)
            alert_service.check_occupancy(total=total, available=available)
        except Exception as e:
            logger.warning(f"Alert occupancy check failed: {e}")


def on_parking_request(topic, payload):
    session_id = payload.get('sessionId')
    logger.info(f"Parking request: {session_id}")
    socketio.emit('vehicle_arrival', {
        'sessionId': session_id,
        'priority':  payload.get('priorityClass')
    }, namespace='/')


def on_suggestion(topic, payload):
    bay_id = payload.get('primaryBayId')
    logger.info(f"Suggestion: {bay_id}")

    # Enrich with bay details from DB if available
    extra = {}
    if db_session and bay_id:
        try:
            db_session.expire_all()
            bay = db_session.query(Bay).filter(Bay.id == bay_id).first()
            if bay:
                extra = {
                    'distance': bay.distance_from_gate,
                    'category': bay.category.value if bay.category else 'GENERAL',
                }
        except Exception:
            pass

    socketio.emit('suggestion_issued', {
        'bayId':        bay_id,
        'sessionId':    payload.get('sessionId'),
        'priority':     payload.get('priorityClass'),
        'plate':        payload.get('plate', ''),
        'alternatives': payload.get('alternativeBayIds', []),
        **extra
    }, namespace='/')


def on_confirmation(topic, payload):
    logger.info(f"Confirmation: {payload.get('bayId')} - {payload.get('status')}")
    socketio.emit('confirmation', {
        'bayId':  payload.get('bayId'),
        'status': payload.get('status')
    }, namespace='/')


def on_alpr_scanning(topic, payload):
    """Relayed to kiosk so it can show the 'scanning plate...' state."""
    socketio.emit('alpr_scanning', payload, namespace='/')


def on_plate_detected(topic, payload):
    """Plate confirmed at gate – tell kiosk to show priority selection screen."""
    logger.info(f"Plate detected: {payload.get('plate')}")
    socketio.emit('plate_detected', {'plate': payload.get('plate')}, namespace='/')


@socketio.on('priority_selected')
def handle_priority_selected(data):
    """Kiosk sends the driver's chosen priority; unblock run_camera_demo."""
    priority = data.get('priority', 'GENERAL').upper()
    logger.info(f"Priority selected by driver: {priority}")
    if _priority_queue is not None:
        _priority_queue.put(priority)


def on_plate_logged(topic, payload):
    """Relayed to dashboard activity feed when a bay camera logs a plate."""
    logger.info(f"Plate logged: {payload.get('plate')} at bay {payload.get('bayId')}")
    socketio.emit('plate_logged', {
        'bayId':  payload.get('bayId'),
        'plate':  payload.get('plate'),
        'camera': payload.get('camera'),
        'conf':   payload.get('conf'),
    }, namespace='/')


# ── Flask routes ──────────────────────────────────────────────────────────────

@app.route('/')
def dashboard():
    return render_template('camera_dashboard.html')


@app.route('/kiosk')
def kiosk():
    return render_template('camera_kiosk.html')


@app.route('/search')
def search():
    return render_template('camera_search.html')


@app.route('/cameras')
def cameras_page():
    cams = []
    if _gate_camera is not None:
        cams.append({'label': 'Gate Camera – ALPR', 'url': '/video/gate'})
    for svc in _bay_cameras:
        cams.append({'label': svc.label, 'url': f'/video/bay/{svc.camera_index}'})
    return render_template('camera_feed.html', cameras=cams)


# ── Camera assignment helpers (used by the /calibrate page) ──────────────────

def _enumerate_cameras():
    """
    Enumerate cameras and return the indexes that should appear in the
    calibration dropdowns.

    Strategy:
      1. On Linux, prefer parsing ``v4l2-ctl --list-devices``: each USB
         camera shows a *group* with several /dev/videoN entries; only the
         FIRST one in each group is the actual capture stream (the others
         are metadata streams that won't return frames). This avoids the
         odd-numbered "ghost" indexes and is robust against probe failures
         right after a hot-restart.
      2. Fallback: glob /dev/video* and probe each.
      3. Indexes currently held by a running service are reported as
         ``in_use=True`` without re-probing (USB drivers don't allow two
         opens at once and the probe would lie).
    """
    import os, glob, subprocess

    busy = set()
    if _gate_camera is not None and _gate_camera.is_camera_ready:
        busy.add(_gate_camera.camera_index)
    for svc in _bay_cameras:
        busy.add(svc.camera_index)

    primary = None        # list[int] – preferred indexes when v4l2-ctl works

    if os.name != 'nt':
        try:
            out = subprocess.check_output(
                ['v4l2-ctl', '--list-devices'],
                stderr=subprocess.DEVNULL, timeout=3
            ).decode('utf-8', errors='ignore')
            primary = []
            current_group_is_usb = False
            current_group_taken  = False
            for line in out.splitlines():
                if line and not line.startswith('\t'):
                    # New group header (e.g. "USB Camera (usb-...):" or
                    # "NVIDIA Tegra Video Input Device (...):")
                    current_group_is_usb = ('usb' in line.lower()
                                             or 'camera' in line.lower())
                    current_group_taken  = False
                elif line.startswith('\t/dev/video') and current_group_is_usb \
                        and not current_group_taken:
                    try:
                        idx = int(line.strip().replace('/dev/video', ''))
                        primary.append(idx)
                        current_group_taken = True   # only first per group
                    except ValueError:
                        pass
        except (FileNotFoundError, subprocess.SubprocessError, OSError):
            primary = None

    if primary is None:
        # Fallback: enumerate by file or numeric range
        if os.name == 'nt':
            primary = list(range(8))
        else:
            primary = []
            for path in sorted(glob.glob('/dev/video*')):
                try:
                    primary.append(int(path.replace('/dev/video', '')))
                except ValueError:
                    pass

    available = []
    for idx in primary:
        if idx in busy:
            available.append({'index': idx, 'in_use': True})
            continue
        # Probe – may fail right after a release, but we still report the
        # index because v4l2-ctl told us it's a real capture device.
        cap = cv2.VideoCapture(idx)
        ok = cap.isOpened()
        if ok:
            ok2, _frm = cap.read()
            cap.release()
            available.append({'index': idx, 'in_use': False,
                              'probe_ok': bool(ok2)})
        else:
            available.append({'index': idx, 'in_use': False,
                              'probe_ok': False, 'note': 'busy or unavailable'})
    return available


def _snapshot_for_index(cam_idx: int):
    """
    Return a BGR frame for ``cam_idx``. Always prefers live services so the
    calibrate-page thumbnail reflects what the running pipeline actually sees.
    Only falls back to opening the camera directly when *no* service holds it,
    which avoids hiding a silently-broken service behind a fresh open.
    """
    held_by_service = False
    if _gate_camera is not None and _gate_camera.camera_index == cam_idx:
        held_by_service = True
        if _gate_camera.is_camera_ready:
            f = _gate_camera.get_latest_frame()
            if f is not None:
                return f
    for svc in _bay_cameras:
        if svc.camera_index == cam_idx:
            held_by_service = True
            f = svc.get_latest_frame()
            if f is not None:
                return f
    if held_by_service:
        # A service claims this index but isn't producing frames – don't
        # paper over it with a direct open; let the UI show 'no preview'.
        return None
    cap = cv2.VideoCapture(cam_idx)
    if not cap.isOpened():
        return None
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    for _ in range(5):
        cap.read()
    ok, frame = cap.read()
    cap.release()
    return frame if ok else None


@app.route('/api/cameras/available')
def api_cameras_available():
    return jsonify({'cameras': _enumerate_cameras()})


@app.route('/api/cameras/<int:cam_idx>/snapshot.jpg')
def api_camera_snapshot(cam_idx):
    frame = _snapshot_for_index(cam_idx)
    if frame is None:
        return ('', 404)
    frame = cv2.resize(frame, (320, 240))
    ok, buf = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
    if not ok:
        return ('', 500)
    return Response(buf.tobytes(), mimetype='image/jpeg',
                    headers={'Cache-Control': 'no-store'})


@app.route('/api/assignments', methods=['GET'])
def api_get_assignments():
    """Return the current gate + bay-camera assignments from the YAML config."""
    import yaml, os
    cfg_path = os.path.join('config', 'camera_demo_config.yaml')
    try:
        with open(cfg_path, encoding='utf-8') as f:
            cfg = yaml.safe_load(f) or {}
    except FileNotFoundError:
        cfg = {}
    return jsonify({
        'gate_camera':  cfg.get('gate_camera', {}),
        'bay_cameras':  cfg.get('bay_cameras', []),
    })


@app.route('/api/assignments', methods=['POST'])
def api_save_assignments():
    """
    Save camera assignments from the calibration page.
    Body: {
        gate_camera_index: int,
        bay_cameras: [{camera_index, label, bays: [...]}]
    }
    Persists to camera_demo_config.yaml. Does NOT restart the cameras –
    the client should follow up with POST /api/cameras/restart.
    """
    import yaml, os
    data = request.get_json(silent=True) or {}
    gate_idx = data.get('gate_camera_index')
    bay_assignments = data.get('bay_cameras') or []

    cfg_path = os.path.join('config', 'camera_demo_config.yaml')
    try:
        with open(cfg_path, encoding='utf-8') as f:
            cfg = yaml.safe_load(f) or {}
    except FileNotFoundError:
        cfg = {}

    if gate_idx is not None:
        cfg.setdefault('gate_camera', {})
        cfg['gate_camera']['camera_index'] = int(gate_idx)
        cfg['gate_camera'].setdefault('label', 'Gate Camera - ALPR')

    if bay_assignments:
        cfg['bay_cameras'] = [
            {
                'camera_index': int(b.get('camera_index')),
                'label':        b.get('label') or f"Camera {b.get('camera_index')}",
                'bays':         list(b.get('bays') or []),
            }
            for b in bay_assignments
            if b.get('camera_index') is not None
        ]

    with open(cfg_path, 'w', encoding='utf-8') as f:
        yaml.safe_dump(cfg, f, sort_keys=False)

    return jsonify({'ok': True, 'restart_required': True})


@app.route('/api/cameras/restart', methods=['POST'])
def api_cameras_restart():
    """Stop running cameras, re-read config, start fresh services."""
    global _gate_camera, _bay_cameras
    if _camera_rebuild_fn is None:
        return jsonify({'ok': False,
                        'error': 'Hot-restart not supported by this build. '
                                 'Stop and re-run python3 run_camera_demo.py.'}), 501
    try:
        gate, bays = _camera_rebuild_fn()
        _gate_camera = gate
        _bay_cameras = bays or []
        return jsonify({
            'ok': True,
            'gate_index':   gate.camera_index if gate else None,
            'bay_indexes':  [c.camera_index for c in _bay_cameras],
        })
    except Exception as exc:
        logger.exception("Camera restart failed")
        return jsonify({'ok': False, 'error': str(exc)}), 500


@app.route('/calibrate')
def calibrate_page():
    """ROI calibration UI – click-and-drag a rectangle on each bay camera."""
    cams = []
    for svc in _bay_cameras:
        cams.append({
            'camera_index': svc.camera_index,
            'label':        svc.label,
            'bays':         list(svc.bay_ids),
            'stream_url':   f'/video/bay/{svc.camera_index}',
        })
    # All bays in the system – used to populate the calibration dropdown so
    # any bay can be assigned to any camera (not just pre-configured ones).
    all_bays = []
    if db_session is not None:
        try:
            all_bays = sorted(b.id for b in db_session.query(Bay).all())
        except Exception:
            pass
    return render_template('calibrate.html', cameras=cams, all_bays=all_bays)


@app.route('/api/rois', methods=['GET'])
def get_rois():
    """Return the live in-memory ROI map plus the capture frame dimensions."""
    try:
        from bay_camera_service import CAPTURE_WIDTH, CAPTURE_HEIGHT
    except Exception:
        CAPTURE_WIDTH, CAPTURE_HEIGHT = 640, 480
    cams = []
    for svc in _bay_cameras:
        cams.append({
            'camera_index': svc.camera_index,
            'label':        svc.label,
            'bays':         [
                {'bay_id': bid, 'roi': list(svc.rois[bid])}
                for bid in svc.bay_ids if bid in svc.rois
            ],
        })
    return jsonify({
        'frame_width':  CAPTURE_WIDTH,
        'frame_height': CAPTURE_HEIGHT,
        'cameras':      cams,
    })


@app.route('/api/rois', methods=['POST'])
def save_roi():
    """
    Save a single bay's ROI – called from the calibration page.
    Body: { camera_index, bay_id, roi: [x1,y1,x2,y2] }   (capture-frame pixels)
    Updates config/bay_rois.yaml AND hot-reloads the running camera service.
    """
    import yaml, os
    data = request.get_json(silent=True) or {}
    cam_idx = data.get('camera_index')
    bay_id  = data.get('bay_id')
    roi     = data.get('roi')
    if cam_idx is None or not bay_id or not roi or len(roi) != 4:
        return jsonify({'ok': False, 'error': 'Missing camera_index/bay_id/roi'}), 400

    # 1. Hot-update the running BayCameraService
    target = next((c for c in _bay_cameras if c.camera_index == cam_idx), None)
    if target is None:
        return jsonify({'ok': False, 'error': f'No camera with index {cam_idx}'}), 404
    bay_added = bay_id not in target.bay_ids
    try:
        target.update_roi(bay_id, roi)   # auto-adds the bay if new
    except Exception as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 500

    # 1b. If this is a new bay-camera mapping, also persist it to
    # camera_demo_config.yaml so the assignment survives a restart.
    if bay_added:
        cfg_path = os.path.join('config', 'camera_demo_config.yaml')
        try:
            with open(cfg_path, encoding='utf-8') as f:
                main_cfg = yaml.safe_load(f) or {}
            cams = main_cfg.setdefault('bay_cameras', [])
            entry = next((c for c in cams if c.get('camera_index') == cam_idx), None)
            if entry is None:
                entry = {'camera_index': cam_idx,
                         'label': target.label,
                         'bays': []}
                cams.append(entry)
            entry.setdefault('bays', [])
            if bay_id not in entry['bays']:
                entry['bays'].append(bay_id)
            with open(cfg_path, 'w', encoding='utf-8') as f:
                yaml.safe_dump(main_cfg, f, sort_keys=False)
        except Exception as exc:
            logger.warning(f"Could not persist bay assignment to config: {exc}")

    # 2. Persist to disk
    rois_path = os.path.join('config', 'bay_rois.yaml')
    try:
        with open(rois_path, encoding='utf-8') as f:
            cfg = yaml.safe_load(f) or {}
    except FileNotFoundError:
        cfg = {}
    cfg.setdefault('cameras', [])

    cam_entry = next((c for c in cfg['cameras']
                      if c.get('camera_index') == cam_idx), None)
    if cam_entry is None:
        cam_entry = {'camera_index': cam_idx, 'bays': []}
        cfg['cameras'].append(cam_entry)
    cam_entry.setdefault('bays', [])

    bay_entry = next((b for b in cam_entry['bays']
                      if b.get('bay_id') == bay_id), None)
    if bay_entry is None:
        bay_entry = {'bay_id': bay_id}
        cam_entry['bays'].append(bay_entry)
    bay_entry['roi'] = [int(v) for v in roi]

    os.makedirs(os.path.dirname(rois_path), exist_ok=True)
    with open(rois_path, 'w', encoding='utf-8') as f:
        yaml.safe_dump(cfg, f, sort_keys=False)

    return jsonify({'ok': True, 'camera_index': cam_idx,
                    'bay_id': bay_id, 'roi': bay_entry['roi']})


@app.route('/video/gate')
def video_gate():
    def _get():
        return _gate_camera.get_latest_frame() if _gate_camera else None
    return Response(_mjpeg_stream(_get),
                    mimetype='multipart/x-mixed-replace; boundary=frame')


@app.route('/video/bay/<int:cam_idx>')
def video_bay(cam_idx):
    def _get():
        for svc in _bay_cameras:
            if svc.camera_index == cam_idx:
                return svc.get_latest_frame()
        return None
    return Response(_mjpeg_stream(_get),
                    mimetype='multipart/x-mixed-replace; boundary=frame')


@app.route('/api/bays')
def get_bays():
    if not db_session:
        return jsonify({'error': 'DB not ready'}), 500

    db_session.expire_all()
    bays = db_session.query(Bay).all()
    return jsonify({
        'bays': {
            bay.id: {
                'id':          bay.id,
                'state':       bay.state.value if bay.state else 'UNKNOWN',
                'category':    bay.category.value if bay.category else 'GENERAL',
                'distance':    bay.distance_from_gate,
                'zone':        bay.zone,
                'zone_name':   bay.zone_name,
                'entrance_id': bay.entrance_id,
                'entrance_name': bay.entrance_name,
                'entrance_color': bay.entrance_color,
                'x':           bay.coordinates_x,
                'y':           bay.coordinates_y,
                'plate':       bay.parked_plate,
            }
            for bay in bays
        },
        'timestamp': Clock.now().isoformat()
    })


@app.route('/api/bay/<bay_id>')
def get_bay(bay_id):
    """Return full detail for one bay (used by dashboard bay-click popup)."""
    if not db_session:
        return jsonify({'error': 'DB not ready'}), 500

    db_session.expire_all()
    bay = db_session.query(Bay).filter(Bay.id == bay_id).first()
    if not bay:
        return jsonify({'error': 'Bay not found'}), 404

    return jsonify({
        'id':             bay.id,
        'state':          bay.state.value if bay.state else 'UNKNOWN',
        'category':       bay.category.value if bay.category else 'GENERAL',
        'distance':       bay.distance_from_gate,
        'plate':          bay.parked_plate,
        'last_update':    bay.last_update_time.isoformat() if bay.last_update_time else None,
        'occupied_since': bay.occupied_since.isoformat() if bay.occupied_since else None,
    })


@app.route('/api/bay/<bay_id>/read_plate', methods=['POST'])
def read_bay_plate(bay_id):
    """On-demand plate scan for a specific bay – fired by dashboard button."""
    if not _bay_cameras:
        return jsonify({'ok': False, 'error': 'No bay cameras registered'}), 503

    target = next((c for c in _bay_cameras if bay_id in c.bay_ids), None)
    if target is None:
        return jsonify({'ok': False, 'error': f'No camera watches bay {bay_id}'}), 404

    try:
        plate = target.read_plate_now(bay_id)
    except Exception as exc:
        logger.error(f"read_plate_now failed for {bay_id}: {exc}")
        return jsonify({'ok': False, 'error': str(exc)}), 500

    if plate:
        return jsonify({'ok': True, 'plate': plate, 'bayId': bay_id})
    return jsonify({'ok': False, 'plate': None, 'bayId': bay_id,
                    'error': 'No plate detected'}), 200


@app.route('/api/find_plate/<plate>')
def find_plate(plate):
    """Search which bay a given plate number is currently parked in."""
    if not db_session:
        return jsonify({'error': 'DB not ready'}), 500

    plate = plate.strip().upper()
    db_session.expire_all()
    bay = db_session.query(Bay).filter(Bay.parked_plate == plate).first()

    if bay:
        return jsonify({
            'found':    True,
            'plate':    plate,
            'bayId':    bay.id,
            'category': bay.category.value if bay.category else 'GENERAL',
            'distance': bay.distance_from_gate,
        })
    return jsonify({'found': False, 'plate': plate})


@app.route('/api/alerts/status')
def get_alert_status():
    """Return current alert configuration status (no credentials exposed)."""
    import configparser
    from pathlib import Path
    cfg = configparser.ConfigParser()
    cfg.read(Path(__file__).parent / 'alerts.cfg', encoding='utf-8')

    def gb(section, key):
        try: return cfg.getboolean(section, key)
        except: return False

    return jsonify({
        'email_enabled':        gb('email', 'enabled'),
        'sms_enabled':          gb('sms', 'enabled'),
        'daily_report_enabled': gb('daily_report', 'enabled'),
        'high_threshold':       cfg.getint('thresholds', 'high_occupancy', fallback=80),
        'critical_threshold':   cfg.getint('thresholds', 'critical_occupancy', fallback=90),
        'cooldown_minutes':     cfg.getint('thresholds', 'cooldown_minutes', fallback=30),
    })


@app.route('/api/alerts/test', methods=['POST'])
def test_alert():
    """Send a test alert to verify email/SMS is working."""
    if not db_session:
        return jsonify({'error': 'DB not ready'}), 500

    try:
        bays      = db_session.query(Bay).all()
        total     = len(bays)
        available = sum(1 for b in bays if b.state == BayState.AVAILABLE)
        alert_service.send_daily_report(total=total, available=available)
        return jsonify({'success': True, 'message': 'Test alert sent — check your inbox/phone.'})
    except Exception as e:
        logger.error(f"Test alert failed: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/stats')
def get_stats():
    if not db_session:
        return jsonify({'error': 'DB not ready'}), 500

    bays = db_session.query(Bay).all()
    total     = len(bays)
    available = sum(1 for b in bays if b.state == BayState.AVAILABLE)
    occupied  = total - available

    return jsonify({
        'total':        total,
        'available':    available,
        'occupied':     occupied,
        'occupancy_pct': round((occupied / total * 100) if total > 0 else 0, 1),
        'timestamp':    Clock.now().isoformat()
    })


# ── SocketIO events ───────────────────────────────────────────────────────────

@socketio.on('connect')
def handle_connect():
    logger.info(f'Client connected  (sid={request.sid})')

    if db_session:
        try:
            db_session.expire_all()
            bays = db_session.query(Bay).all()
            emit('initial_state', {
                'bays': {
                    bay.id: {
                        'id':          bay.id,
                        'state':       bay.state.value if bay.state else 'UNKNOWN',
                        'category':    bay.category.value if bay.category else 'GENERAL',
                        'distance':    bay.distance_from_gate,
                        'zone':        bay.zone,
                        'zone_name':   bay.zone_name,
                        'entrance_id': bay.entrance_id,
                        'entrance_name': bay.entrance_name,
                        'entrance_color': bay.entrance_color,
                        'x':           bay.coordinates_x,
                        'y':           bay.coordinates_y,
                        'plate':       bay.parked_plate,
                    }
                    for bay in bays
                },
                'timestamp': Clock.now().isoformat()
            })
        except Exception as e:
            logger.error(f"Error sending initial state: {e}")


@socketio.on('disconnect')
def handle_disconnect():
    logger.info('Client disconnected')


def run_server(host='0.0.0.0', port=5000):
    logger.info(f"🌐 Camera demo web server on {host}:{port}")
    socketio.run(app, host=host, port=port, debug=False, allow_unsafe_werkzeug=True)
