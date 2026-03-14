// Camera Kiosk - ALPR-driven (no zone buttons)
// Screens: scanning → suggestion → (auto-return to scanning)

let socket;
let currentScreen = 'scanning';
let suggestionTimeout = null;

document.addEventListener('DOMContentLoaded', () => {
    initSocket();
    updateClock();
    setInterval(updateClock, 1000);
    // Periodic availability refresh
    setInterval(refreshAvailability, 5000);
});

function initSocket() {
    socket = io('http://localhost:5000');

    socket.on('connect', () => {
        console.log('✅ Kiosk connected');
    });

    socket.on('initial_state', (data) => {
        updateAvailability(data.bays);
    });

    socket.on('bay_update', () => {
        // Re-fetch stats to update availability count
        refreshAvailability();
    });

    // Camera is actively scanning (sent by run_camera_demo.py via bus)
    socket.on('alpr_scanning', (data) => {
        console.log('📷 ALPR scanning');
        if (currentScreen !== 'suggestion') {
            // Only update to scanning if we're not already showing a suggestion
            showScreen('scanning');
        }
    });

    // Plate detected + suggestion ready
    socket.on('suggestion_issued', (data) => {
        console.log('💡 Suggestion received:', data);
        showSuggestion(data);
    });
}

function refreshAvailability() {
    fetch('/api/stats')
        .then(r => r.json())
        .then(data => {
            const el = document.getElementById('totalAvailable');
            if (el) el.textContent = data.available ?? '-';

            // If no bays available, show full screen (only if not in suggestion)
            if (data.available === 0 && currentScreen !== 'suggestion') {
                showScreen('full');
            } else if (data.available > 0 && currentScreen === 'full') {
                showScreen('scanning');
            }
        })
        .catch(() => {});
}

function updateAvailability(bays) {
    if (!bays) return;
    const available = Object.values(bays).filter(b => b.state === 'AVAILABLE').length;
    const el = document.getElementById('totalAvailable');
    if (el) el.textContent = available;
}

function showSuggestion(data) {
    // Clear any pending auto-return
    if (suggestionTimeout) {
        clearTimeout(suggestionTimeout);
        suggestionTimeout = null;
    }

    const bayId    = data.bayId || data.primaryBayId || '---';
    const plate    = data.plate || '';
    const distance = data.distance || 0;
    const category = data.category || 'GENERAL';
    const alts     = data.alternatives || [];

    // Populate plate badge
    const plateLabel = document.getElementById('detectedPlateLabel');
    const plateText  = document.getElementById('detectedPlateText');
    if (plate) {
        if (plateLabel) plateLabel.textContent = `Plate: ${plate}`;
        if (plateText)  plateText.textContent  = plate;
    } else {
        if (plateLabel) plateLabel.textContent = 'Plate Detected';
        if (plateText)  plateText.textContent  = '------';
    }

    // Populate bay info
    const bayEl   = document.getElementById('suggestedBay');
    const distEl  = document.getElementById('bayDistance');
    const walkEl  = document.getElementById('bayWalkTime');
    const badgeEl = document.getElementById('bayCategoryBadge');

    if (bayEl)   bayEl.textContent   = bayId;
    if (distEl)  distEl.textContent  = `${distance} meters`;
    if (walkEl)  walkEl.textContent  = `${Math.ceil(distance / 1.4)} seconds walk`;
    if (badgeEl) badgeEl.textContent = categoryBadge(category);

    // Alternatives
    const grid = document.getElementById('alternativesGrid');
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

    // Auto-return to scanning after 25 seconds
    suggestionTimeout = setTimeout(() => {
        showScreen('scanning');
        suggestionTimeout = null;
    }, 25000);
}

function categoryBadge(cat) {
    if (cat === 'POD')    return '♿ POD Reserved';
    if (cat === 'STAFF')  return '👔 Staff';
    if (cat === 'FAMILY') return '👨‍👩‍👧 Family';
    return '';
}

function showScreen(name) {
    document.querySelectorAll('.screen').forEach(s => s.classList.add('hidden'));
    const target = document.getElementById(`${name}Screen`);
    if (target) target.classList.remove('hidden');
    currentScreen = name;
}

function updateClock() {
    const el = document.getElementById('kioskTime');
    if (el) el.textContent = new Date().toLocaleTimeString();
}
