// ═══════════════════════════════════════════════════════════════════════════
//  SPMS Dashboard — Camera ALPR  (enhanced with timeline + animations)
// ═══════════════════════════════════════════════════════════════════════════

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
        addActivity('arrival', `Vehicle arrived (${data.priority || 'GENERAL'})`, '\u{1F6A8}');
    });

    socket.on('suggestion_issued', (data) => {
        const plate = data.plate ? ` \u2014 ${data.plate}` : '';
        addActivity('suggestion', `Suggested ${data.bayId}${plate}`, '\u{1F4CD}');
        flashBay(data.bayId);
        setAlprDetected(data.plate || null);
    });

    socket.on('confirmation', (data) => {
        addActivity('confirmation', `${data.bayId} confirmed`, '\u2705');
    });

    socket.on('alpr_scanning', () => { setAlprScanning(); });

    socket.on('plate_logged', (data) => {
        const label = data.plate && data.plate !== 'SCANNING\u2026' ? data.plate : 'scanning';
        addActivity('confirmation', `Bay cam: ${label} at ${data.bayId}`, '\u{1F4F7}');
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

        // Category icon
        if (bay.category && bay.category !== 'GENERAL') {
            const badge = document.createElementNS('http://www.w3.org/2000/svg', 'text');
            badge.setAttribute('x', bay.x + BAY_W / 2);
            badge.setAttribute('y', bay.y + 42);
            badge.setAttribute('text-anchor', 'middle');
            badge.setAttribute('font-size', '11');
            badge.textContent = categoryIcon(bay.category);
            g.appendChild(badge);
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

    const icon = document.createElementNS('http://www.w3.org/2000/svg', 'text');
    icon.setAttribute('x', eX);
    icon.setAttribute('y', eY + 7);
    icon.setAttribute('text-anchor', 'middle');
    icon.setAttribute('font-size', '20');
    icon.textContent = '\u{1F697}';

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
    if (cat === 'POD')   return '\u267F';
    if (cat === 'STAFF') return 'S';
    return '';
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
    el.innerHTML = Object.entries(cats).map(([cat, data]) => `
        <div class="cat-row">
            <span class="cat-badge ${cat}">${categoryIcon(cat) || ''} ${cat}</span>
            <span style="color:var(--text-3); font-size:0.8rem;">${data.available}/${data.total} free</span>
        </div>
    `).join('');
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
