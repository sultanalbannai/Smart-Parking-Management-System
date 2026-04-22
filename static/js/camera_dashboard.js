// ═══════════════════════════════════════════════════════════════════════════
//  SPMS Dashboard — Camera ALPR  (enhanced with timeline + animations)
// ═══════════════════════════════════════════════════════════════════════════

// ── Icon library (inline SVG, Lucide-style stroke icons) ────────────────────

const ICON = {
    arrival:      '<svg class="icon icon-sm" viewBox="0 0 24 24" aria-hidden="true"><path d="M5 17h-2v-6l2-5h10l2 5h2a2 2 0 0 1 2 2v4h-2"/><circle cx="7" cy="17" r="2"/><circle cx="17" cy="17" r="2"/></svg>',
    suggestion:   '<svg class="icon icon-sm" viewBox="0 0 24 24" aria-hidden="true"><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/><circle cx="12" cy="10" r="3"/></svg>',
    confirmation: '<svg class="icon icon-sm" viewBox="0 0 24 24" aria-hidden="true"><polyline points="20 6 9 17 4 12"/></svg>',
    camera:       '<svg class="icon icon-sm" viewBox="0 0 24 24" aria-hidden="true"><path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="4"/></svg>',
    system:       '<svg class="icon icon-sm" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>',
    accessible:   '<svg class="cat-icon-inline" viewBox="0 0 24 24" aria-hidden="true" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="4" r="2"/><path d="M19 13v-2a7 7 0 0 0-14 0v2"/><path d="M12 10v6"/><path d="M8 22a6 6 0 0 1 8 0"/></svg>',
    staff:        '<svg class="cat-icon-inline" viewBox="0 0 24 24" aria-hidden="true" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="7" width="18" height="13" rx="2"/><path d="M8 7V5a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><path d="M3 13h18"/></svg>',
};

let socket;
let baysData = {};

document.addEventListener('DOMContentLoaded', () => {
    initSocket();
    updateClock();
    setInterval(updateClock, 1000);
    initZoomControls();
    initBayModal();
});

// ── Socket.IO ────────────────────────────────────────────────────────────────

function initSocket() {
    socket = io(location.origin);

    socket.on('connect', () => {
        console.log('Dashboard connected');
        document.getElementById('status').className = 'status online';
    });
    socket.on('disconnect', () => {
        document.getElementById('status').className = 'status offline';
    });

    socket.on('initial_state', (data) => {
        baysData = data.bays || {};
        renderMap();
        updateStatistics();
        updateCategoryList();
    });

    socket.on('bay_update', (data) => {
        if (baysData[data.id]) {
            baysData[data.id].state = data.state;
            if (data.state === 'AVAILABLE') baysData[data.id].plate = null;
            updateBayVisual(data.id, data.state);
            updateStatistics();
            updateCategoryList();
        }
    });

    socket.on('vehicle_arrival', (data) => {
        addActivity('arrival', `Vehicle arrived (${data.priority || 'GENERAL'})`, ICON.arrival);
    });

    socket.on('suggestion_issued', (data) => {
        const plate = data.plate ? ` \u2014 ${data.plate}` : '';
        addActivity('suggestion', `Suggested ${data.bayId}${plate}`, ICON.suggestion);
        flashBay(data.bayId);
        setAlprDetected(data.plate || null);
    });

    socket.on('confirmation', (data) => {
        addActivity('confirmation', `${data.bayId} confirmed`, ICON.confirmation);
    });

    socket.on('alpr_scanning', () => { setAlprScanning(); });

    socket.on('plate_logged', (data) => {
        const label = data.plate && data.plate !== 'SCANNING\u2026' ? data.plate : 'scanning';
        addActivity('confirmation', `Bay cam: ${label} at ${data.bayId}`, ICON.camera);
        if (baysData[data.bayId]) {
            baysData[data.bayId].plate = data.plate || null;
        }
        // Refresh modal if open on this bay
        const modal = document.getElementById('bayModalBackdrop');
        if (modal && modal.classList.contains('open') &&
            document.getElementById('bmBayId').textContent === data.bayId) {
            openBayModal(data.bayId);
        }
    });

    // Periodic DB sync
    setInterval(() => {
        fetch('/api/bays').then(r => r.json()).then(data => {
            const bays = data.bays || {};
            let changed = false;
            Object.values(bays).forEach(bay => {
                if (baysData[bay.id] && baysData[bay.id].state !== bay.state) {
                    baysData[bay.id].state = bay.state;
                    updateBayVisual(bay.id, bay.state);
                    changed = true;
                }
            });
            if (changed) { updateStatistics(); updateCategoryList(); }
        }).catch(() => {});
    }, 3000);
}

// ── Map Rendering ────────────────────────────────────────────────────────────

const BAY_W = 80, BAY_H = 48;

function renderMap() {
    const baysGroup     = document.getElementById('parkingBays');
    const entranceGroup = document.getElementById('entranceMarker');
    baysGroup.innerHTML     = '';
    entranceGroup.innerHTML = '';

    Object.values(baysData).forEach(bay => {
        const g = document.createElementNS('http://www.w3.org/2000/svg', 'g');
        g.setAttribute('class', `parking-bay ${bay.state.toLowerCase()}`);
        g.setAttribute('data-bay-id', bay.id);

        const rect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
        rect.setAttribute('x', bay.x);
        rect.setAttribute('y', bay.y);
        rect.setAttribute('width', BAY_W);
        rect.setAttribute('height', BAY_H);
        rect.setAttribute('rx', 6);
        applyBayColor(rect, bay.state);

        const label = document.createElementNS('http://www.w3.org/2000/svg', 'text');
        label.setAttribute('x', bay.x + BAY_W / 2);
        label.setAttribute('y', bay.y + 28);
        label.setAttribute('text-anchor', 'middle');
        label.setAttribute('font-size', '11');
        label.setAttribute('fill', '#e2e8f0');
        label.textContent = bay.id;

        g.appendChild(rect);
        g.appendChild(label);

        // Category icon (inline stroke glyph so no emoji)
        if (bay.category && bay.category !== 'GENERAL') {
            const glyph = buildCategoryGlyph(bay.category, bay.x + BAY_W / 2, bay.y + 40);
            if (glyph) g.appendChild(glyph);
        }

        g.style.cursor = 'pointer';
        g.addEventListener('click', () => openBayModal(bay.id));
        baysGroup.appendChild(g);
    });

    // Entrance marker
    const eX = 600, eY = 760;

    const arrow = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    arrow.setAttribute('d', `M ${eX - 12} ${eY - 30} L ${eX} ${eY - 50} L ${eX + 12} ${eY - 30} Z`);
    arrow.setAttribute('fill', '#3b82f6');
    arrow.setAttribute('opacity', '0.8');

    const circle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
    circle.setAttribute('cx', eX);
    circle.setAttribute('cy', eY);
    circle.setAttribute('r', 28);
    circle.setAttribute('fill', '#3b82f6');
    circle.setAttribute('opacity', '0.85');
    circle.setAttribute('stroke', 'rgba(255,255,255,0.3)');
    circle.setAttribute('stroke-width', '2');

    // Lucide-style "log-in" glyph as entrance marker
    const icon = document.createElementNS('http://www.w3.org/2000/svg', 'g');
    icon.setAttribute('transform', `translate(${eX - 11}, ${eY - 11}) scale(0.92)`);
    icon.innerHTML =
        '<path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>' +
        '<polyline points="10 17 15 12 10 7" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>' +
        '<line x1="15" y1="12" x2="3" y2="12" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>';

    const lbl = document.createElementNS('http://www.w3.org/2000/svg', 'text');
    lbl.setAttribute('x', eX);
    lbl.setAttribute('y', eY + 50);
    lbl.setAttribute('text-anchor', 'middle');
    lbl.setAttribute('fill', '#60a5fa');
    lbl.setAttribute('font-size', '12');
    lbl.setAttribute('font-weight', 'bold');
    lbl.setAttribute('font-family', 'Inter, sans-serif');
    lbl.textContent = 'ENTRANCE';

    const sublbl = document.createElementNS('http://www.w3.org/2000/svg', 'text');
    sublbl.setAttribute('x', eX);
    sublbl.setAttribute('y', eY + 65);
    sublbl.setAttribute('text-anchor', 'middle');
    sublbl.setAttribute('fill', '#64748b');
    sublbl.setAttribute('font-size', '9');
    sublbl.setAttribute('font-family', 'Inter, sans-serif');
    sublbl.textContent = 'Camera ALPR';

    entranceGroup.appendChild(arrow);
    entranceGroup.appendChild(circle);
    entranceGroup.appendChild(icon);
    entranceGroup.appendChild(lbl);
    entranceGroup.appendChild(sublbl);
}

function applyBayColor(rect, state) {
    if (state === 'AVAILABLE') {
        rect.style.fill   = 'rgba(16,185,129,0.18)';
        rect.style.stroke = '#10b981';
        rect.setAttribute('stroke-width', '1.5');
    } else if (state === 'UNAVAILABLE') {
        rect.style.fill   = 'rgba(244,63,94,0.22)';
        rect.style.stroke = '#f43f5e';
        rect.setAttribute('stroke-width', '1.5');
    } else {
        rect.style.fill   = 'rgba(100,116,139,0.12)';
        rect.style.stroke = '#334155';
        rect.setAttribute('stroke-width', '1');
    }
}

function updateBayVisual(bayId, state) {
    const g = document.querySelector(`[data-bay-id="${bayId}"]`);
    if (!g) return;
    const rect = g.querySelector('rect');
    if (rect) applyBayColor(rect, state);
}

function flashBay(bayId) {
    const g = document.querySelector(`[data-bay-id="${bayId}"]`);
    if (!g) return;
    const rect = g.querySelector('rect');
    if (!rect) return;
    rect.style.fill = 'rgba(245,158,11,0.6)';
    rect.style.stroke = '#f59e0b';
    rect.setAttribute('stroke-width', '3');
    setTimeout(() => applyBayColor(rect, baysData[bayId]?.state || 'AVAILABLE'), 2000);
}

function categoryIcon(cat) {
    if (cat === 'POD')   return ICON.accessible;
    if (cat === 'STAFF') return ICON.staff;
    return '';
}

function buildCategoryGlyph(category, cx, cy) {
    const ns = 'http://www.w3.org/2000/svg';
    const size = 12;
    const x = cx - size / 2;
    const y = cy - size / 2;

    const g = document.createElementNS(ns, 'g');
    g.setAttribute('transform', `translate(${x}, ${y})`);
    g.setAttribute('fill', 'none');
    g.setAttribute('stroke', '#cbd5e1');
    g.setAttribute('stroke-width', '1.4');
    g.setAttribute('stroke-linecap', 'round');
    g.setAttribute('stroke-linejoin', 'round');

    if (category === 'POD') {
        // Lucide-style "accessibility / person in wheelchair" mark (12×12)
        g.innerHTML =
            '<circle cx="6" cy="2" r="1"/>' +
            '<path d="M9.5 6.5L6 5v2.5h3"/>' +
            '<path d="M6 7.5v2.5"/>' +
            '<circle cx="7" cy="10.5" r="1.2"/>';
        return g;
    }
    if (category === 'STAFF') {
        // Lucide "briefcase" in 12×12
        g.innerHTML =
            '<rect x="1.5" y="4" width="9" height="6.5" rx="1"/>' +
            '<path d="M4.25 4V3a1 1 0 0 1 1-1h1.5a1 1 0 0 1 1 1v1"/>' +
            '<line x1="1.5" y1="7" x2="10.5" y2="7"/>';
        return g;
    }
    return null;
}

// ── Statistics ───────────────────────────────────────────────────────────────

function updateStatistics() {
    const total     = Object.keys(baysData).length;
    const available = Object.values(baysData).filter(b => b.state === 'AVAILABLE').length;
    const occupied  = total - available;
    const pct       = total > 0 ? Math.round((occupied / total) * 100) : 0;

    animateCounter('totalBays', total);
    animateCounter('availableBays', available);
    animateCounter('occupiedBays', occupied);
    document.getElementById('occupancyText').textContent = pct + '%';
    document.getElementById('occupancyFill').style.width = pct + '%';
}

function animateCounter(id, target) {
    const el = document.getElementById(id);
    if (!el) return;
    const current = parseInt(el.textContent) || 0;
    if (current === target) return;
    el.textContent = target;
    el.style.transform = 'scale(1.15)';
    el.style.transition = 'transform 0.25s cubic-bezier(0.4,0,0.2,1)';
    setTimeout(() => { el.style.transform = 'scale(1)'; }, 250);
}

function updateCategoryList() {
    const cats = {};
    Object.values(baysData).forEach(bay => {
        if (!cats[bay.category]) cats[bay.category] = { total: 0, available: 0 };
        cats[bay.category].total++;
        if (bay.state === 'AVAILABLE') cats[bay.category].available++;
    });

    const el = document.getElementById('categoryList');
    if (!el) return;
    el.innerHTML = Object.entries(cats).map(([cat, data]) => {
        const glyph = categoryIcon(cat);
        return `
        <div class="cat-row">
            <span class="cat-badge ${cat}">${glyph ? glyph + ' ' : ''}${cat}</span>
            <span style="color:var(--text-3); font-size:0.8rem;">${data.available}/${data.total} free</span>
        </div>`;
    }).join('');
}

// ── ALPR Status ──────────────────────────────────────────────────────────────

function setAlprScanning() {
    const dot  = document.getElementById('alprDot');
    const text = document.getElementById('alprStatusText');
    const disp = document.getElementById('alprPlateDisplay');
    if (dot)  dot.className = 'alpr-status-dot scanning';
    if (text) text.textContent = 'Scanning\u2026';
    if (disp) disp.style.display = 'none';
}

function setAlprDetected(plate) {
    const dot  = document.getElementById('alprDot');
    const text = document.getElementById('alprStatusText');
    const disp = document.getElementById('alprPlateDisplay');
    const chip = document.getElementById('alprPlateChip');

    if (dot)  dot.className = 'alpr-status-dot detected';
    if (text) text.textContent = 'Plate Detected';
    if (plate && chip) chip.textContent = plate;
    if (disp) disp.style.display = plate ? 'block' : 'none';

    setTimeout(() => {
        if (dot)  dot.className = 'alpr-status-dot';
        if (text) text.textContent = 'Idle';
        if (disp) disp.style.display = 'none';
    }, 5000);
}

// ── Activity Feed (timeline-style) ──────────────────────────────────────────

function addActivity(type, message, icon) {
    const feed = document.getElementById('activityFeed');
    const item = document.createElement('div');
    item.className = `activity-item ${type}`;
    item.innerHTML = `
        <span class="act-icon">${icon || '\u2022'}</span>
        <div class="act-body">
            <div class="act-text">${message}</div>
            <div class="act-time">${relativeTime(new Date())}</div>
        </div>`;
    feed.insertBefore(item, feed.firstChild);
    while (feed.children.length > 60) feed.removeChild(feed.lastChild);

    // Update relative times every minute
    clearTimeout(window._relTimeTimer);
    window._relTimeTimer = setTimeout(updateRelativeTimes, 60000);
}

function relativeTime(date) {
    const diff = Math.floor((Date.now() - date.getTime()) / 1000);
    if (diff < 5)  return 'just now';
    if (diff < 60) return `${diff}s ago`;
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
    return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

function updateRelativeTimes() {
    // Re-schedule every minute
    const items = document.querySelectorAll('.act-time');
    // We don't store timestamps on DOM elements in this version;
    // new items show "just now" which is good enough for a live demo
}

// ── Clock ────────────────────────────────────────────────────────────────────

function updateClock() {
    const el = document.getElementById('currentTime');
    if (el) el.textContent = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

// ── Zoom ─────────────────────────────────────────────────────────────────────

let currentZoom = 0.7;

function initZoomControls() {
    document.getElementById('btnZoomIn')?.addEventListener('click', () => {
        currentZoom = Math.min(currentZoom + 0.15, 3);
        applyZoom();
    });
    document.getElementById('btnZoomOut')?.addEventListener('click', () => {
        currentZoom = Math.max(currentZoom - 0.15, 0.4);
        applyZoom();
    });
    document.getElementById('btnReset')?.addEventListener('click', () => {
        currentZoom = 0.7;
        applyZoom();
    });
}

function applyZoom() {
    const svg = document.getElementById('parkingMap');
    if (svg) {
        svg.style.transform       = `scale(${currentZoom})`;
        svg.style.transformOrigin = 'top center';
        svg.style.transition      = 'transform 0.25s ease';
    }
}

// ── Bay Detail Modal ─────────────────────────────────────────────────────────

function initBayModal() {
    const backdrop = document.getElementById('bayModalBackdrop');
    const closeBtn = document.getElementById('bmClose');
    if (closeBtn) closeBtn.addEventListener('click', closeBayModal);
    if (backdrop) backdrop.addEventListener('click', e => { if (e.target === backdrop) closeBayModal(); });
    document.addEventListener('keydown', e => { if (e.key === 'Escape') closeBayModal(); });
}

function closeBayModal() {
    document.getElementById('bayModalBackdrop')?.classList.remove('open');
}

function openBayModal(bayId) {
    const backdrop = document.getElementById('bayModalBackdrop');
    if (!backdrop) return;

    const cached = baysData[bayId];
    fillBayModal({
        id:       bayId,
        state:    cached?.state    || 'UNKNOWN',
        category: cached?.category || 'GENERAL',
        distance: cached?.distance,
        plate:    cached?.plate,
    });
    backdrop.classList.add('open');

    fetch(`/api/bay/${encodeURIComponent(bayId)}`)
        .then(r => r.ok ? r.json() : null)
        .then(data => {
            if (!data || data.error) return;
            if (baysData[bayId]) {
                baysData[bayId].state = data.state;
                baysData[bayId].plate = data.plate;
            }
            fillBayModal(data);
        })
        .catch(() => {});
}

function fillBayModal(data) {
    const $ = id => document.getElementById(id);

    $('bmBayId').textContent    = data.id || '--';
    $('bmCategory').textContent = data.category || 'GENERAL';

    const stateEl = $('bmState');
    stateEl.textContent = data.state || 'UNKNOWN';
    stateEl.className   = 'bm-state ' + (data.state || 'UNKNOWN');

    $('bmDistance').textContent = (data.distance != null) ? `${data.distance} m` : '\u2014';

    const upd = data.last_update ? new Date(data.last_update) : null;
    $('bmUpdate').textContent = upd ? upd.toLocaleString() : '\u2014';

    const plateEl = $('bmPlate');
    if (data.plate) {
        plateEl.textContent = data.plate;
        plateEl.classList.remove('empty');
    } else {
        plateEl.textContent = data.state === 'AVAILABLE' ? 'Bay is empty' : 'No plate recorded';
        plateEl.classList.add('empty');
    }
}

// ── Alerts Panel ─────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
    loadAlertStatus();
    document.getElementById('btnTestAlert')?.addEventListener('click', sendTestAlert);
});

function loadAlertStatus() {
    fetch('/api/alerts/status')
        .then(r => r.ok ? r.json() : null)
        .then(data => {
            if (!data) return;
            const el = document.getElementById('alertStatusList');
            if (!el) return;

            const rows = [
                { label: 'Email Alerts',   on: data.email_enabled },
                { label: 'SMS Alerts',     on: data.sms_enabled },
                { label: 'Daily Report',   on: data.daily_report_enabled },
            ];

            el.innerHTML = rows.map(r => `
                <div class="alert-status-row">
                    <span class="alert-status-dot ${r.on ? 'on' : 'off'}"></span>
                    <span>${r.label}</span>
                    <span style="margin-left:auto;color:${r.on ? 'var(--green)' : 'var(--text-3)'}">
                        ${r.on ? 'ON' : 'OFF'}
                    </span>
                </div>`).join('') +
                `<div style="font-size:0.72rem;color:var(--text-3);margin-top:4px;">
                    Thresholds: ${data.high_threshold}% / ${data.critical_threshold}%
                </div>`;
        })
        .catch(() => {});
}

function sendTestAlert() {
    const btn = document.getElementById('btnTestAlert');
    const msg = document.getElementById('alertTestMsg');
    if (!btn) return;

    btn.disabled = true;
    btn.textContent = 'Sending…';

    fetch('/api/alerts/test', { method: 'POST' })
        .then(r => r.json())
        .then(data => {
            if (msg) {
                msg.style.display = 'block';
                msg.style.color = data.success ? 'var(--green)' : 'var(--red)';
                msg.textContent = data.success ? '✓ Test sent successfully' : `✗ ${data.error}`;
                setTimeout(() => { msg.style.display = 'none'; }, 5000);
            }
        })
        .catch(() => {
            if (msg) {
                msg.style.display = 'block';
                msg.style.color = 'var(--red)';
                msg.textContent = '✗ Request failed';
                setTimeout(() => { msg.style.display = 'none'; }, 5000);
            }
        })
        .finally(() => {
            btn.disabled = false;
            btn.textContent = 'Send Test Alert';
        });
}
