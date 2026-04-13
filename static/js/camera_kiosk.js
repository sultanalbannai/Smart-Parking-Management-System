// ═══════════════════════════════════════════════════════════════════════════
//  SPMS Kiosk — Animated flow with step progress
// ═══════════════════════════════════════════════════════════════════════════

let socket;
let currentScreen = 'scanning';
let suggestionTimeout = null;
let countdownInterval = null;

const SUGGESTION_DISPLAY_SEC = 25;

document.addEventListener('DOMContentLoaded', () => {
    initSocket();
    updateClock();
    setInterval(updateClock, 1000);
    setInterval(refreshAvailability, 5000);
    setProgress(1);   // start at step 1
});

// ── Socket.IO ────────────────────────────────────────────────────────────────

function initSocket() {
    socket = io(location.origin);

    socket.on('connect', () => console.log('Kiosk connected'));

    socket.on('initial_state', (data) => updateAvailability(data.bays));

    socket.on('bay_update', () => refreshAvailability());

    socket.on('alpr_scanning', () => {
        if (currentScreen !== 'suggestion' && currentScreen !== 'priority') {
            showScreen('scanning');
            setProgress(1);
        }
    });

    socket.on('plate_detected', (data) => {
        const el = document.getElementById('priorityPlateText');
        if (el) el.textContent = data.plate || '------';
        showScreen('priority');
        setProgress(3);  // step 2 (detect) done, step 3 (priority) active
    });

    socket.on('suggestion_issued', (data) => {
        showSuggestion(data);
    });
}

// ── Availability ─────────────────────────────────────────────────────────────

function refreshAvailability() {
    fetch('/api/stats').then(r => r.json()).then(data => {
        const el = document.getElementById('totalAvailable');
        if (el) el.textContent = data.available ?? '-';

        if (data.available === 0 && currentScreen !== 'suggestion') {
            showScreen('full');
        } else if (data.available > 0 && currentScreen === 'full') {
            showScreen('scanning');
            setProgress(1);
        }
    }).catch(() => {});
}

function updateAvailability(bays) {
    if (!bays) return;
    const available = Object.values(bays).filter(b => b.state === 'AVAILABLE').length;
    const el = document.getElementById('totalAvailable');
    if (el) el.textContent = available;
}

// ── Show Suggestion ──────────────────────────────────────────────────────────

function showSuggestion(data) {
    if (suggestionTimeout) { clearTimeout(suggestionTimeout); suggestionTimeout = null; }
    if (countdownInterval) { clearInterval(countdownInterval); countdownInterval = null; }

    const bayId    = data.bayId || data.primaryBayId || '---';
    const plate    = data.plate || '';
    const distance = data.distance || 0;
    const category = data.category || 'GENERAL';
    const alts     = data.alternatives || [];

    // Plate badge
    const plateLabel = document.getElementById('detectedPlateLabel');
    const plateText  = document.getElementById('detectedPlateText');
    if (plate) {
        if (plateLabel) plateLabel.textContent = `Plate: ${plate}`;
        if (plateText)  plateText.textContent  = plate;
    } else {
        if (plateLabel) plateLabel.textContent = 'Plate Detected';
        if (plateText)  plateText.textContent  = '------';
    }

    // Bay info
    const bayEl   = document.getElementById('suggestedBay');
    const distEl  = document.getElementById('bayDistance');
    const walkEl  = document.getElementById('bayWalkTime');
    const badgeEl = document.getElementById('bayCategoryBadge');

    if (bayEl)   bayEl.textContent   = bayId;
    if (distEl)  distEl.textContent  = `${distance} meters`;
    if (walkEl)  walkEl.textContent  = `${Math.ceil(distance / 1.4)} seconds walk`;
    if (badgeEl) badgeEl.textContent = categoryBadge(category);

    // Alternatives
    const grid    = document.getElementById('alternativesGrid');
    const section = document.getElementById('alternativesSection');
    if (grid && alts.length > 0) {
        grid.innerHTML = alts.slice(0, 3).map(a => {
            const id = typeof a === 'string' ? a : (a.bayId || a);
            return `<div class="alternative-bay">${id}</div>`;
        }).join('');
        if (section) section.style.display = '';
    } else {
        if (section) section.style.display = 'none';
    }

    showScreen('suggestion');
    setProgress(4);   // all steps done, step 4 active

    // Countdown bar animation
    startCountdown();

    // Auto-return
    suggestionTimeout = setTimeout(() => {
        showScreen('scanning');
        setProgress(1);
        suggestionTimeout = null;
    }, SUGGESTION_DISPLAY_SEC * 1000);
}

// ── Countdown bar ────────────────────────────────────────────────────────────

function startCountdown() {
    const fill = document.getElementById('countdownFill');
    if (!fill) return;
    fill.style.transition = 'none';
    fill.style.width = '100%';

    // Force reflow before starting transition
    void fill.offsetWidth;

    let remaining = SUGGESTION_DISPLAY_SEC;
    fill.style.transition = 'width 1s linear';

    countdownInterval = setInterval(() => {
        remaining--;
        const pct = Math.max(0, (remaining / SUGGESTION_DISPLAY_SEC) * 100);
        fill.style.width = pct + '%';
        if (remaining <= 0) clearInterval(countdownInterval);
    }, 1000);
}

// ── Priority Selection ───────────────────────────────────────────────────────

function selectPriority(priority) {
    socket.emit('priority_selected', { priority });
    // Brief processing state
    showScreen('scanning');
    setProgress(3, true);  // step 3 completing
}

function categoryBadge(cat) {
    if (cat === 'POD')   return '\u267F POD Reserved';
    if (cat === 'STAFF') return '\uD83D\uDC54 Staff';
    return '';
}

// ── Screen Transitions ───────────────────────────────────────────────────────

function showScreen(name) {
    document.querySelectorAll('.screen').forEach(s => s.classList.add('hidden'));
    const target = document.getElementById(`${name}Screen`);
    if (target) target.classList.remove('hidden');
    currentScreen = name;
}

// ── Step Progress ────────────────────────────────────────────────────────────

function setProgress(activeStep, processing) {
    // Steps 1-4, lines 1-3
    for (let i = 1; i <= 4; i++) {
        const step = document.getElementById(`step${i}`);
        if (!step) continue;

        step.classList.remove('active', 'done');
        if (i < activeStep) {
            step.classList.add('done');
        } else if (i === activeStep) {
            step.classList.add(processing ? 'done' : 'active');
        }
    }

    for (let i = 1; i <= 3; i++) {
        const line = document.getElementById(`line${i}`);
        if (!line) continue;
        line.classList.toggle('done', i < activeStep);
    }
}

// ── Clock ────────────────────────────────────────────────────────────────────

function updateClock() {
    const el = document.getElementById('kioskTime');
    if (el) el.textContent = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}
