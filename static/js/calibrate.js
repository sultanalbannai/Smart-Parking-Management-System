/**
 * Bay ROI Calibration page
 * - Each .cal-card has an MJPEG <img> and an overlay <canvas>
 * - User clicks + drags on the canvas to draw a rectangle
 * - Coordinates are converted from canvas-pixel space to capture-frame
 *   pixel space (640x480 by default) and POSTed to /api/rois
 * - The currently-saved ROI is drawn in green; the in-progress rect in orange
 */

let frameW = 640, frameH = 480;
let serverROIs = {};      // { camera_index: { bay_id: [x1,y1,x2,y2] } }

document.addEventListener('DOMContentLoaded', async () => {
    try {
        const res = await fetch('/api/rois');
        const data = await res.json();
        frameW = data.frame_width  || 640;
        frameH = data.frame_height || 480;
        for (const cam of data.cameras) {
            serverROIs[cam.camera_index] = {};
            for (const b of cam.bays) {
                serverROIs[cam.camera_index][b.bay_id] = b.roi;
            }
        }
    } catch (e) {
        console.warn('Could not load existing ROIs:', e);
    }

    document.querySelectorAll('.cal-card').forEach(setupCard);
});

function setupCard(card) {
    const camIdx  = parseInt(card.dataset.cameraIndex, 10);
    const stage   = card.querySelector('.cal-stage');
    const img     = stage.querySelector('img');
    const canvas  = stage.querySelector('canvas');
    const ctx     = canvas.getContext('2d');
    const select  = card.querySelector('.bay-select');
    const saveBtn = card.querySelector('.btn-save');
    const clearBtn= card.querySelector('.btn-clear');
    const coordsEl= card.querySelector('.cal-coords');
    const statusEl= card.querySelector('.cal-status');

    let drag = null;          // {x1,y1,x2,y2} in canvas-px while drawing
    let pending = null;       // {x1,y1,x2,y2} in frame-px after release

    function fitCanvas() {
        const r = img.getBoundingClientRect();
        canvas.width  = r.width;
        canvas.height = r.height;
        redraw();
    }

    function getPos(evt) {
        const r = canvas.getBoundingClientRect();
        return {
            x: Math.max(0, Math.min(r.width,  evt.clientX - r.left)),
            y: Math.max(0, Math.min(r.height, evt.clientY - r.top)),
        };
    }

    function canvasToFrame(x, y) {
        return {
            fx: Math.round(x * frameW / canvas.width),
            fy: Math.round(y * frameH / canvas.height),
        };
    }

    function frameToCanvas(fx, fy) {
        return {
            x: fx * canvas.width  / frameW,
            y: fy * canvas.height / frameH,
        };
    }

    function redraw() {
        ctx.clearRect(0, 0, canvas.width, canvas.height);

        // Existing saved ROIs for this camera in green
        const cams = serverROIs[camIdx] || {};
        ctx.lineWidth = 2;
        ctx.font = '12px sans-serif';
        for (const [bayId, roi] of Object.entries(cams)) {
            const a = frameToCanvas(roi[0], roi[1]);
            const b = frameToCanvas(roi[2], roi[3]);
            ctx.strokeStyle = 'rgba(34,197,94,0.95)';
            ctx.fillStyle   = 'rgba(34,197,94,0.10)';
            ctx.fillRect(a.x, a.y, b.x - a.x, b.y - a.y);
            ctx.strokeRect(a.x, a.y, b.x - a.x, b.y - a.y);
            ctx.fillStyle = 'rgba(34,197,94,0.95)';
            ctx.fillText(bayId, a.x + 4, a.y + 14);
        }

        // In-progress drag rectangle in orange
        if (drag) {
            const x1 = Math.min(drag.x1, drag.x2);
            const y1 = Math.min(drag.y1, drag.y2);
            const w  = Math.abs(drag.x2 - drag.x1);
            const h  = Math.abs(drag.y2 - drag.y1);
            ctx.strokeStyle = 'rgba(249,115,22,0.95)';
            ctx.fillStyle   = 'rgba(249,115,22,0.18)';
            ctx.fillRect(x1, y1, w, h);
            ctx.strokeRect(x1, y1, w, h);
        }
    }

    // ── Mouse / pointer ───────────────────────────────────────────────
    canvas.addEventListener('pointerdown', (e) => {
        e.preventDefault();
        canvas.setPointerCapture(e.pointerId);
        const p = getPos(e);
        drag = { x1: p.x, y1: p.y, x2: p.x, y2: p.y };
        pending = null;
        saveBtn.disabled = true;
        coordsEl.textContent = '';
        redraw();
    });
    canvas.addEventListener('pointermove', (e) => {
        if (!drag) return;
        const p = getPos(e);
        drag.x2 = p.x;
        drag.y2 = p.y;
        redraw();
    });
    canvas.addEventListener('pointerup', (e) => {
        if (!drag) return;
        const p = getPos(e);
        drag.x2 = p.x;
        drag.y2 = p.y;
        const wpx = Math.abs(drag.x2 - drag.x1);
        const hpx = Math.abs(drag.y2 - drag.y1);
        if (wpx < 8 || hpx < 8) {
            drag = null;
            redraw();
            return;
        }
        const a = canvasToFrame(Math.min(drag.x1, drag.x2),
                                Math.min(drag.y1, drag.y2));
        const b = canvasToFrame(Math.max(drag.x1, drag.x2),
                                Math.max(drag.y1, drag.y2));
        pending = { x1: a.fx, y1: a.fy, x2: b.fx, y2: b.fy };
        coordsEl.textContent = `[${pending.x1}, ${pending.y1}, ${pending.x2}, ${pending.y2}]  (frame ${frameW}x${frameH})`;
        saveBtn.disabled = false;
        redraw();
    });

    clearBtn.addEventListener('click', () => {
        drag = null;
        pending = null;
        coordsEl.textContent = '';
        statusEl.textContent = '';
        saveBtn.disabled = true;
        redraw();
    });

    saveBtn.addEventListener('click', async () => {
        if (!pending) return;
        const bayId = select.value;
        saveBtn.disabled = true;
        statusEl.style.color = '#475569';
        statusEl.textContent = `Saving ${bayId}…`;
        try {
            const res = await fetch('/api/rois', {
                method:  'POST',
                headers: { 'Content-Type': 'application/json' },
                body:    JSON.stringify({
                    camera_index: camIdx,
                    bay_id:       bayId,
                    roi:          [pending.x1, pending.y1, pending.x2, pending.y2],
                }),
            });
            const body = await res.json();
            if (body.ok) {
                serverROIs[camIdx] = serverROIs[camIdx] || {};
                serverROIs[camIdx][bayId] = body.roi;
                drag = null;
                pending = null;
                statusEl.style.color = '#16a34a';
                statusEl.textContent = `Saved ROI for ${bayId} → [${body.roi.join(', ')}]`;
                coordsEl.textContent = '';
                redraw();
            } else {
                statusEl.style.color = '#dc2626';
                statusEl.textContent = body.error || 'Save failed';
                saveBtn.disabled = false;
            }
        } catch (err) {
            statusEl.style.color = '#dc2626';
            statusEl.textContent = 'Save failed: ' + err;
            saveBtn.disabled = false;
        }
    });

    // Resize / image load → re-fit canvas
    img.addEventListener('load', fitCanvas);
    window.addEventListener('resize', fitCanvas);
    if (img.complete) fitCanvas();
    else fitCanvas();   // canvas still gets sized; redraw happens on load
}
