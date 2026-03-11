// Dashboard JavaScript - Real-time Updates

const socket = io();

let bays = {};
let stats = {};

// Initialize
document.addEventListener('DOMContentLoaded', function() {
    console.log('Dashboard initialized');
    
    // Update clock
    updateClock();
    setInterval(updateClock, 1000);
    
    // Load initial data
    loadBays();
    loadStats();
    
    // Refresh stats periodically
    setInterval(loadStats, 2000);
});

// Update clock
function updateClock() {
    const now = new Date();
    const timeStr = now.toLocaleTimeString('en-US', { hour12: false });
    document.getElementById('currentTime').textContent = timeStr;
}

// Load all bays
async function loadBays() {
    try {
        const response = await fetch('/api/bays');
        const bayList = await response.json();
        
        bayList.forEach(bay => {
            bays[bay.id] = bay;
        });
        
        renderBayGrid();
    } catch (error) {
        console.error('Error loading bays:', error);
    }
}

// Load stats
async function loadStats() {
    try {
        const response = await fetch('/api/stats');
        stats = await response.json();
        updateStats();
    } catch (error) {
        console.error('Error loading stats:', error);
    }
}

// Render bay grid
function renderBayGrid() {
    const grid = document.getElementById('bayGrid');
    grid.innerHTML = '';
    
    // Sort bays by distance
    const sortedBays = Object.values(bays).sort((a, b) => a.distance - b.distance);
    
    sortedBays.forEach(bay => {
        const card = createBayCard(bay);
        grid.appendChild(card);
    });
}

// Create bay card
function createBayCard(bay) {
    const card = document.createElement('div');
    card.className = `bay-card ${bay.state.toLowerCase()}`;
    card.id = `bay-${bay.id}`;
    
    card.innerHTML = `
        <div class="bay-number">${bay.id}</div>
        <div class="bay-category-badge ${bay.category}">${bay.category}</div>
        <div class="bay-status">${bay.state}</div>
        <div class="bay-distance">${bay.distance}m from entrance</div>
    `;
    
    return card;
}

// Update bay card
function updateBayCard(bayId, newState) {
    const card = document.getElementById(`bay-${bayId}`);
    if (!card) return;
    
    // Remove old state classes
    card.classList.remove('available', 'pending', 'occupied');
    
    // Add new state class
    card.classList.add(newState.toLowerCase());
    
    // Update status text
    const statusEl = card.querySelector('.bay-status');
    if (statusEl) {
        statusEl.textContent = newState;
    }
    
    // Update in memory
    if (bays[bayId]) {
        bays[bayId].state = newState;
    }
}

// Update stats display
function updateStats() {
    document.getElementById('totalBays').textContent = stats.total || '-';
    document.getElementById('availableBays').textContent = stats.available || '-';
    document.getElementById('pendingBays').textContent = stats.pending || '-';
    document.getElementById('occupiedBays').textContent = stats.occupied || '-';
    
    const occupancy = stats.occupancyRate || 0;
    document.getElementById('occupancyFill').style.width = occupancy + '%';
    document.getElementById('occupancyText').textContent = occupancy.toFixed(1) + '%';
}

// Add activity
function addActivity(type, message) {
    const feed = document.getElementById('activityFeed');
    
    const item = document.createElement('div');
    item.className = `activity-item ${type}`;
    
    const now = new Date();
    const timeStr = now.toLocaleTimeString('en-US', { hour12: false });
    
    item.innerHTML = `
        <span class="time">${timeStr}</span>
        <span>${message}</span>
    `;
    
    feed.insertBefore(item, feed.firstChild);
    
    // Keep only last 20 items
    while (feed.children.length > 20) {
        feed.removeChild(feed.lastChild);
    }
}

// Socket.IO event listeners
socket.on('connect', () => {
    console.log('✅ Connected to server');
    console.log('Socket ID:', socket.id);
    document.getElementById('status').className = 'status online';
    addActivity('info', 'Connected to parking system');
});

socket.on('disconnect', () => {
    console.log('❌ Disconnected from server');
    document.getElementById('status').className = 'status offline';
    addActivity('info', 'Disconnected from server');
});

socket.on('connect_error', (error) => {
    console.error('❌ Connection error:', error);
});

socket.on('initial_state', (bayList) => {
    console.log('📊 Received initial state:', bayList.length, 'bays');
    bayList.forEach(bay => {
        bays[bay.id] = bay;
    });
    renderBayGrid();
    loadStats();
});

socket.on('bay_update', (bay) => {
    console.log('🔄 Bay update received:', bay);
    
    const oldState = bays[bay.id] ? bays[bay.id].state : null;
    updateBayCard(bay.id, bay.state);
    loadStats();
    
    if (oldState && oldState !== bay.state) {
        const emoji = {
            'AVAILABLE': '🟢',
            'PENDING': '🟡',
            'UNAVAILABLE': '🔴'
        };
        addActivity('parking', `${emoji[bay.state]} Bay ${bay.id}: ${oldState} → ${bay.state}`);
    }
});

socket.on('vehicle_arrival', (data) => {
    console.log('🚗 Vehicle arrival received:', data);
    addActivity('arrival', `🚗 Vehicle arrived (Priority: ${data.priority})`);
});

socket.on('suggestion_issued', (data) => {
    console.log('💡 Suggestion received:', data);
    addActivity('suggestion', `💡 Suggested bay ${data.primaryBay} for vehicle`);
});

socket.on('confirmation', (data) => {
    console.log('✅ Confirmation received:', data);
    const emoji = data.status === 'CONFIRMED' ? '✅' : '⚠️';
    addActivity('confirmation', `${emoji} ${data.status} in bay ${data.bayId}`);
});
