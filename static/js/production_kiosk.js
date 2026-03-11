// Production Kiosk - Entrance Selector & Suggestions
let socket;
let zonesAvailability = {};
let currentScreen = 'welcome';

document.addEventListener('DOMContentLoaded', () => {
    initSocket();
    initEntranceButtons();
    updateClock();
    setInterval(updateClock, 1000);
});

function initSocket() {
    socket = io('http://localhost:5000');
    
    socket.on('connect', () => console.log('✅ Kiosk connected'));
    
    socket.on('initial_state', (data) => {
        updateZoneAvailability(data.bays);
    });
    
    socket.on('bay_update', (data) => {
        // Update availability counts
        socket.emit('get_state', {}, (state) => {
            if (state && state.bays) {
                updateZoneAvailability(state.bays);
            }
        });
    });
    
    socket.on('suggestion_issued', (data) => {
        // Only show suggestion if we're on the welcome screen
        // This prevents overwriting a current suggestion with a new one
        if (currentScreen === 'welcome') {
            showSuggestion(data);
        } else {
            console.log('Suggestion queued (user still viewing current suggestion):', data.bayId);
        }
    });
}

function updateZoneAvailability(bays) {
    const zones = {};
    Object.values(bays).forEach(bay => {
        if (!zones[bay.zone_name]) zones[bay.zone_name] = 0;
        if (bay.state === 'AVAILABLE') zones[bay.zone_name]++;
    });
    
    zonesAvailability = zones;
    
    // Update display
    Object.keys(zones).forEach(zone => {
        const elem = document.getElementById(`avail-${zone}`);
        if (elem) {
            const count = zones[zone] || 0;
            elem.textContent = `${count} space${count !== 1 ? 's' : ''}`;
        }
    });
    
    // Update total
    const total = Object.values(zones).reduce((a, b) => a + b, 0);
    const totalElem = document.getElementById('totalAvailable');
    if (totalElem) totalElem.textContent = total;
    
    const anyElem = document.getElementById('avail-ANY');
    if (anyElem) anyElem.textContent = `${total} spaces`;
}

function initEntranceButtons() {
    document.querySelectorAll('.entrance-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const entrance = btn.dataset.entrance;
            const zone = btn.dataset.zone;
            requestParking(entrance, zone);
        });
    });
    
    document.getElementById('btnBackToSelection')?.addEventListener('click', () => {
        // Clear the auto-return timeout when user manually goes back
        if (suggestionTimeout) {
            clearTimeout(suggestionTimeout);
            suggestionTimeout = null;
        }
        showScreen('welcome');
    });
}

function requestParking(entrance, zone) {
    // Emit parking request to backend
    socket.emit('request_parking', {
        entrance: entrance,
        zone: zone,
        priority: 'GENERAL'
    });
    
    // Show loading state
    document.getElementById('selectedZoneName').textContent = 
        zone === 'ANY' ? 'Finding Closest Bay...' : `${zone} Zone`;
}

function selectAlternativeBay(bayId) {
    // When user selects an alternative bay, send confirmation
    console.log(`User selected alternative bay: ${bayId}`);
    
    // Clear auto-return timeout since user is interacting
    if (suggestionTimeout) {
        clearTimeout(suggestionTimeout);
        suggestionTimeout = null;
    }
    
    // Emit bay selection to backend
    socket.emit('bay_selected', {
        bayId: bayId
    });
    
    // Show confirmation
    document.getElementById('suggestedBay').textContent = bayId;
    
    // Auto-return after 5 seconds
    suggestionTimeout = setTimeout(() => {
        showScreen('welcome');
        suggestionTimeout = null;
    }, 5000);
}

// Store the current suggestion timeout so we can clear it
let suggestionTimeout = null;
let currentSuggestionData = null;

function showSuggestion(data) {
    // Store the suggestion data
    currentSuggestionData = data;
    
    // Clear any existing timeout first
    if (suggestionTimeout) {
        clearTimeout(suggestionTimeout);
        suggestionTimeout = null;
    }
    
    const bayId = data.bayId || data.primaryBayId;
    const distance = data.distance || (data.bayData ? data.bayData.distance_from_gate : 0);
    
    document.getElementById('suggestedBay').textContent = bayId;
    document.getElementById('bayDistance').textContent = `${distance} meters`;
    document.getElementById('bayWalkTime').textContent = 
        `${Math.ceil(distance / 1.4)} seconds walk`;
    
    // Show alternatives if available
    if (data.alternatives && data.alternatives.length > 0) {
        const grid = document.getElementById('alternativesGrid');
        grid.innerHTML = data.alternatives.slice(0, 3).map(alt => {
            const altBayId = alt.bayId || alt;
            return `<div class="alternative-bay" onclick="selectAlternativeBay('${altBayId}')">${altBayId}</div>`;
        }).join('');
    }
    
    showScreen('suggestion');
    
    // Auto-return to welcome after 2 minutes (120 seconds) - gives user plenty of time to interact
    suggestionTimeout = setTimeout(() => {
        showScreen('welcome');
        suggestionTimeout = null;
    }, 120000);
}

function showScreen(screenName) {
    document.querySelectorAll('.screen').forEach(s => s.classList.add('hidden'));
    document.getElementById(`${screenName}Screen`).classList.remove('hidden');
    currentScreen = screenName;
}

function updateClock() {
    const now = new Date();
    document.getElementById('kioskTime').textContent = now.toLocaleTimeString();
}
