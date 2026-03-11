// Kiosk JavaScript - Driver-Facing Display

const socket = io();

let currentState = 'welcome';  // welcome, assigned, full
let availableCount = 0;

// Initialize
document.addEventListener('DOMContentLoaded', function() {
    console.log('Kiosk initialized');
    
    // Update clock
    updateClock();
    setInterval(updateClock, 1000);
    
    // Load initial stats
    loadStats();
    setInterval(loadStats, 2000);
    
    // Show welcome screen
    showState('welcome');
});

// Update clock
function updateClock() {
    const now = new Date();
    const timeStr = now.toLocaleTimeString('en-US', { hour12: false });
    document.getElementById('kioskTime').textContent = timeStr;
}

// Load stats
async function loadStats() {
    try {
        const response = await fetch('/api/stats');
        const stats = await response.json();
        availableCount = stats.available || 0;
        
        document.getElementById('kioskAvailable').textContent = availableCount;
        
        // Auto-switch to full state if no bays available
        if (availableCount === 0 && currentState !== 'assigned') {
            showState('full');
        }
    } catch (error) {
        console.error('Error loading stats:', error);
    }
}

// Show different states
function showState(state) {
    currentState = state;
    
    // Hide all states
    document.getElementById('welcomeState').classList.add('hidden');
    document.getElementById('assignedState').classList.add('hidden');
    document.getElementById('fullState').classList.add('hidden');
    
    // Show selected state
    if (state === 'welcome') {
        document.getElementById('welcomeState').classList.remove('hidden');
    } else if (state === 'assigned') {
        document.getElementById('assignedState').classList.remove('hidden');
    } else if (state === 'full') {
        document.getElementById('fullState').classList.remove('hidden');
    }
}

// Display assignment
function displayAssignment(data) {
    const bayId = data.primaryBay;
    const alternatives = data.alternatives || [];
    const priority = data.priority || 'GENERAL';
    
    // Show assigned state
    showState('assigned');
    
    // Update bay number
    document.getElementById('assignedBay').textContent = bayId;
    
    // Update category
    const categoryEl = document.getElementById('bayCategory');
    categoryEl.textContent = priority;
    categoryEl.className = `bay-category ${priority}`;
    
    // Determine direction arrow (simple logic based on bay number)
    const bayNum = parseInt(bayId.replace(/[^0-9]/g, ''));
    const arrow = bayNum <= 3 ? '←' : '→';
    document.getElementById('directionArrow').textContent = arrow;
    
    // Update location (simplified - based on bay number)
    const zone = bayNum <= 3 ? 'Zone 1' : 'Zone 2';
    document.getElementById('bayLocation').textContent = zone;
    
    // Update distance (would come from API in real system)
    const distances = {
        'B-01': 10, 'B-02': 15, 'B-03': 8,
        'B-04': 25, 'B-05': 20, 'B-06': 30, 'B-07': 35
    };
    const distance = distances[bayId] || 20;
    document.getElementById('bayDistance').textContent = distance + 'm from entrance';
    
    // Show alternatives
    const altList = document.getElementById('alternativesList');
    altList.innerHTML = '';
    
    if (alternatives.length > 0) {
        document.getElementById('alternatives').style.display = 'block';
        alternatives.forEach(alt => {
            const altBay = document.createElement('div');
            altBay.className = 'alt-bay';
            altBay.textContent = alt;
            altList.appendChild(altBay);
        });
    } else {
        document.getElementById('alternatives').style.display = 'none';
    }
    
    // Auto-return to welcome after 15 seconds
    setTimeout(() => {
        if (currentState === 'assigned') {
            showState('welcome');
        }
    }, 15000);
}

// Socket.IO event listeners
socket.on('connect', () => {
    console.log('✅ Kiosk connected to server');
    console.log('Socket ID:', socket.id);
});

socket.on('disconnect', () => {
    console.log('❌ Kiosk disconnected from server');
});

socket.on('connect_error', (error) => {
    console.error('❌ Kiosk connection error:', error);
});

socket.on('vehicle_arrival', (data) => {
    console.log('🚗 Vehicle arrival received (kiosk):', data);
    // Vehicle detected, wait for suggestion
});

socket.on('suggestion_issued', (data) => {
    console.log('💡 Suggestion received (kiosk):', data);
    displayAssignment(data);
});

socket.on('bay_update', (bay) => {
    console.log('🔄 Bay update received (kiosk):', bay);
    // Update available count
    loadStats();
});
