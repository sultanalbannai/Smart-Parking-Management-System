// Camera Dashboard - Single-entrance parking map
let socket;
let baysData = {};

document.addEventListener('DOMContentLoaded', () => {
    initSocket();
    updateClock();
    setInterval(updateClock, 1000);
    initZoomControls();
});

// ── Socket.IO ─────────────────────────────────────────────────────────────────

function initSocket() {
    socket = io('http://localhost:5000');

    socket.on('connect', () => {
        console.log('✅ Dashboard connected');
        document.getElementById('status').className = 'status online';
    });

    socket.on('disconnect', () => {
        console.log('❌ Disconnected');
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
            updateBayVisual(data.id, data.state);
            updateStatistics();
            updateCategoryList();
        }
    });

    socket.on('vehicle_arrival', (data) => {
        addActivity('arrival', `Vehicle arrived (${data.priority || 'GENERAL'})`);
    });

    socket.on('suggestion_issued', (data) => {
        const plate = data.plate ? ` [${data.plate}]` : '';
        addActivity('suggestion', `Suggested bay ${data.bayId}${plate}`);
        // Flash the suggested bay
        flashBay(data.bayId);
        // Update ALPR status panel
        setAlprDetected(data.plate || null);
    });

    socket.on('confirmation', (data) => {
        addActivity('confirmation', `${data.bayId} confirmed`);
    });

    socket.on('alpr_scanning', () => {
        setAlprScanning();
    });

    socket.on('plate_logged', (data) => {
        const conf = data.conf ? ` (${Math.round(data.conf * 100)}%)` : '';
        addActivity('confirmation', `Bay cam: ${data.plate || 'UNKNOWN'} at ${data.bayId}${conf}`);
    });

    // Periodic sync to stay in step with DB
    setInterval(() => {
        fetch('/api/bays')
            .then(r => r.json())
            .then(data => {
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
            })
            .catch(() => {});
    }, 3000);
}

// ── Map rendering ─────────────────────────────────────────────────────────────

const BAY_W = 80;
const BAY_H = 48;

function renderMap() {
    const baysGroup    = document.getElementById('parkingBays');
    const entranceGroup = document.getElementById('entranceMarker');

    baysGroup.innerHTML    = '';
    entranceGroup.innerHTML = '';

    // Render each bay
    Object.values(baysData).forEach(bay => {
        const g = document.createElementNS('http://www.w3.org/2000/svg', 'g');
        g.setAttribute('class', `parking-bay ${bay.state.toLowerCase()}`);
        g.setAttribute('data-bay-id', bay.id);

        const rect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
        rect.setAttribute('x', bay.x);
        rect.setAttribute('y', bay.y);
        rect.setAttribute('width', BAY_W);
        rect.setAttribute('height', BAY_H);
        rect.setAttribute('rx', 4);
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

        // Category badge for non-general bays
        if (bay.category && bay.category !== 'GENERAL') {
            const badge = document.createElementNS('http://www.w3.org/2000/svg', 'text');
            badge.setAttribute('x', bay.x + BAY_W / 2);
            badge.setAttribute('y', bay.y + 42);
            badge.setAttribute('text-anchor', 'middle');
            badge.setAttribute('font-size', '11');
            badge.textContent = categoryIcon(bay.category);
            g.appendChild(badge);
        }

        baysGroup.appendChild(g);
    });

    // Single entrance marker at bottom-center (x≈600, y≈760 from config)
    const entranceX = getEntranceX();
    const entranceY = getEntranceY();

    // Arrow pointing up into parking area
    const arrow = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    arrow.setAttribute('d',
        `M ${entranceX - 12} ${entranceY - 30} L ${entranceX} ${entranceY - 50} L ${entranceX + 12} ${entranceY - 30} Z`
    );
    arrow.setAttribute('fill', '#3b82f6');
    arrow.setAttribute('opacity', '0.85');

    const circle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
    circle.setAttribute('cx', entranceX);
    circle.setAttribute('cy', entranceY);
    circle.setAttribute('r', 30);
    circle.setAttribute('fill', '#3b82f6');
    circle.setAttribute('opacity', '0.9');
    circle.setAttribute('stroke', 'white');
    circle.setAttribute('stroke-width', '3');

    const icon = document.createElementNS('http://www.w3.org/2000/svg', 'text');
    icon.setAttribute('x', entranceX);
    icon.setAttribute('y', entranceY + 8);
    icon.setAttribute('text-anchor', 'middle');
    icon.setAttribute('font-size', '22');
    icon.textContent = '🚗';

    const lbl = document.createElementNS('http://www.w3.org/2000/svg', 'text');
    lbl.setAttribute('x', entranceX);
    lbl.setAttribute('y', entranceY + 52);
    lbl.setAttribute('text-anchor', 'middle');
    lbl.setAttribute('fill', '#60a5fa');
    lbl.setAttribute('font-size', '13');
    lbl.setAttribute('font-weight', 'bold');
    lbl.textContent = 'ENTRANCE';

    const sublbl = document.createElementNS('http://www.w3.org/2000/svg', 'text');
    sublbl.setAttribute('x', entranceX);
    sublbl.setAttribute('y', entranceY + 67);
    sublbl.setAttribute('text-anchor', 'middle');
    sublbl.setAttribute('fill', '#94a3b8');
    sublbl.setAttribute('font-size', '10');
    sublbl.textContent = 'Camera ALPR';

    entranceGroup.appendChild(arrow);
    entranceGroup.appendChild(circle);
    entranceGroup.appendChild(icon);
    entranceGroup.appendChild(lbl);
    entranceGroup.appendChild(sublbl);
}

function getEntranceX() {
    // Try to derive from first bay's entrance position; fallback to 600
    const first = Object.values(baysData)[0];
    return first ? 600 : 600; // always center for single entrance
}

function getEntranceY() {
    return 760; // below bay grid (row 1 bays at y=560, height 48 → bottom=608; entrance at 760)
}

function applyBayColor(rect, state) {
    if (state === 'AVAILABLE') {
        rect.style.fill   = 'rgba(16,185,129,0.25)';
        rect.style.stroke = '#10b981';
        rect.setAttribute('stroke-width', '1.5');
    } else if (state === 'UNAVAILABLE') {
        rect.style.fill   = 'rgba(239,68,68,0.3)';
        rect.style.stroke = '#ef4444';
        rect.setAttribute('stroke-width', '1.5');
    } else {
        rect.style.fill   = 'rgba(100,116,139,0.2)';
        rect.style.stroke = '#475569';
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
    // Brief gold flash for suggested bay
    const orig = rect.style.fill;
    rect.style.fill = 'rgba(251,191,36,0.7)';
    rect.style.stroke = '#fbbf24';
    setTimeout(() => applyBayColor(rect, baysData[bayId]?.state || 'AVAILABLE'), 1500);
}

function categoryIcon(cat) {
    if (cat === 'POD')    return '♿';
    if (cat === 'STAFF')  return '👔';
    if (cat === 'FAMILY') return '👨‍👩‍👧';
    return '';
}

// ── Statistics ────────────────────────────────────────────────────────────────

function updateStatistics() {
    const total     = Object.keys(baysData).length;
    const available = Object.values(baysData).filter(b => b.state === 'AVAILABLE').length;
    const occupied  = total - available;
    const pct       = total > 0 ? Math.round((occupied / total) * 100) : 0;

    document.getElementById('totalBays').textContent     = total;
    document.getElementById('availableBays').textContent = available;
    document.getElementById('occupiedBays').textContent  = occupied;
    document.getElementById('occupancyText').textContent = pct + '%';
    document.getElementById('occupancyFill').style.width = pct + '%';
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
            <span style="color:#94a3b8; font-size:0.85rem;">${data.available}/${data.total} free</span>
        </div>
    `).join('');
}

// ── ALPR Status card ──────────────────────────────────────────────────────────

function setAlprScanning() {
    const dot  = document.getElementById('alprDot');
    const text = document.getElementById('alprStatusText');
    const disp = document.getElementById('alprPlateDisplay');
    if (dot)  { dot.className = 'alpr-status-dot scanning'; }
    if (text) text.textContent = 'Scanning...';
    if (disp) disp.style.display = 'none';
}

function setAlprDetected(plate) {
    const dot   = document.getElementById('alprDot');
    const text  = document.getElementById('alprStatusText');
    const disp  = document.getElementById('alprPlateDisplay');
    const chip  = document.getElementById('alprPlateChip');

    if (dot)  { dot.className = 'alpr-status-dot detected'; }
    if (text) text.textContent = 'Plate Detected';
    if (plate && chip)  chip.textContent = plate;
    if (disp) disp.style.display = plate ? 'block' : 'none';

    // Revert to idle after 4 s
    setTimeout(() => {
        if (dot)  dot.className = 'alpr-status-dot';
        if (text) text.textContent = 'Waiting for vehicle...';
        if (disp) disp.style.display = 'none';
    }, 4000);
}

// ── Activity feed ─────────────────────────────────────────────────────────────

function addActivity(type, message) {
    const feed = document.getElementById('activityFeed');
    const time = new Date().toLocaleTimeString();
    const item = document.createElement('div');
    item.className = `activity-item ${type}`;
    item.innerHTML = `<span class="time">${time}</span><span>${message}</span>`;
    feed.insertBefore(item, feed.firstChild);
    while (feed.children.length > 50) feed.removeChild(feed.lastChild);
}

// ── Clock ─────────────────────────────────────────────────────────────────────

function updateClock() {
    const el = document.getElementById('currentTime');
    if (el) el.textContent = new Date().toLocaleTimeString();
}

// ── Zoom controls ─────────────────────────────────────────────────────────────

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
        svg.style.transform = `scale(${currentZoom})`;
        svg.style.transformOrigin = 'top center';
        svg.style.transition = 'transform 0.2s ease';
    }
}
