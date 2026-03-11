// Production Dashboard - Interactive Parking Map
let socket;
let baysData = {};
let zonesData = {};

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    initSocket();
    updateClock();
    setInterval(updateClock, 1000);
});

// Socket.IO Connection
function initSocket() {
    socket = io('http://localhost:5000');
    
    socket.on('connect', () => {
        console.log('✅ Connected to server');
        document.getElementById('status').className = 'status online';
    });
    
    socket.on('disconnect', () => {
        console.log('❌ Disconnected');
        document.getElementById('status').className = 'status offline';
    });
    
    socket.on('initial_state', (data) => {
        console.log('📊 Initial state received:', data);
        baysData = data.bays || {};
        renderParkingMap();
        
        // Force visual update for all bays after rendering
        Object.values(baysData).forEach(bay => {
            updateBayVisual(bay.id, bay.state);
        });
        
        updateStatistics();
        updateZonesList();
    });
    
    socket.on('bay_update', (data) => {
        console.log('🔄 Bay update:', data);
        if (baysData[data.id]) {
            baysData[data.id].state = data.state;
            updateBayVisual(data.id, data.state);
            updateStatistics();
            updateZonesList();
        }
    });
    
    // Periodic refresh to ensure bay states are in sync
    setInterval(() => {
        fetch('/api/bays')
            .then(res => res.json())
            .then(data => {
                const bays = data.bays || {};
                Object.values(bays).forEach(bay => {
                    if (baysData[bay.id] && baysData[bay.id].state !== bay.state) {
                        console.log(`🔄 Sync update: ${bay.id} -> ${bay.state}`);
                        baysData[bay.id].state = bay.state;
                        updateBayVisual(bay.id, bay.state);
                    }
                });
                updateStatistics();
                updateZonesList();
            })
            .catch(err => console.error('Refresh error:', err));
    }, 2000); // Refresh every 2 seconds
    
    socket.on('vehicle_arrival', (data) => {
        console.log('🚗 Vehicle arrival:', data);
        addActivity('arrival', `Vehicle ${data.sessionId.substr(0,8)} arrived`);
    });
    
    socket.on('suggestion_issued', (data) => {
        console.log('💡 Suggestion:', data);
        addActivity('suggestion', `Suggested ${data.bayId} (${data.zone})`);
    });
    
    socket.on('confirmation', (data) => {
        console.log('✅ Confirmation:', data);
        addActivity('confirmation', `${data.bayId} ${data.status}`);
    });
}

// Render SVG Parking Map
function renderParkingMap() {
    const svg = document.getElementById('parkingMap');
    const baysGroup = document.getElementById('parkingBays');
    const entrancesGroup = document.getElementById('entranceMarkers');
    
    baysGroup.innerHTML = '';
    entrancesGroup.innerHTML = '';
    
    // Render bays
    Object.values(baysData).forEach(bay => {
        const g = document.createElementNS('http://www.w3.org/2000/svg', 'g');
        g.setAttribute('class', `parking-bay ${bay.state.toLowerCase()}`);
        g.setAttribute('data-bay-id', bay.id);
        
        // Bay rectangle
        const rect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
        rect.setAttribute('x', bay.x);
        rect.setAttribute('y', bay.y);
        rect.setAttribute('width', 70);
        rect.setAttribute('height', 50);
        rect.setAttribute('rx', 4);
        
        // Bay label
        const text = document.createElementNS('http://www.w3.org/2000/svg', 'text');
        text.setAttribute('x', bay.x + 35);
        text.setAttribute('y', bay.y + 30);
        text.setAttribute('text-anchor', 'middle');
        text.textContent = bay.id;
        
        g.appendChild(rect);
        g.appendChild(text);
        
        // Category badge
        if (bay.category !== 'GENERAL') {
            const badge = getCategoryBadge(bay.category);
            const badgeText = document.createElementNS('http://www.w3.org/2000/svg', 'text');
            badgeText.setAttribute('x', bay.x + 35);
            badgeText.setAttribute('y', bay.y + 42);
            badgeText.setAttribute('text-anchor', 'middle');
            badgeText.setAttribute('font-size', '12');
            badgeText.textContent = badge;
            g.appendChild(badgeText);
        }
        
        baysGroup.appendChild(g);
    });
    
    // Render entrance markers with directional arrows at exact entrance locations
    const entrances = getUniqueEntrances();
    entrances.forEach(entrance => {
        const marker = document.createElementNS('http://www.w3.org/2000/svg', 'g');
        marker.setAttribute('class', 'entrance-marker');
        
        // Directional arrow (pointing INTO the parking area)
        const arrow = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        let arrowPath;
        if (entrance.id === 'ENTRANCE_A') {
            // North entrance - arrow points down (into parking)
            arrowPath = `M ${entrance.x - 10} ${entrance.y + 35} L ${entrance.x} ${entrance.y + 50} L ${entrance.x + 10} ${entrance.y + 35} Z`;
        } else if (entrance.id === 'ENTRANCE_B') {
            // East entrance - arrow points left (into parking)
            arrowPath = `M ${entrance.x - 35} ${entrance.y - 10} L ${entrance.x - 50} ${entrance.y} L ${entrance.x - 35} ${entrance.y + 10} Z`;
        } else if (entrance.id === 'ENTRANCE_C') {
            // South entrance - arrow points up (into parking)
            arrowPath = `M ${entrance.x - 10} ${entrance.y - 35} L ${entrance.x} ${entrance.y - 50} L ${entrance.x + 10} ${entrance.y - 35} Z`;
        } else if (entrance.id === 'ENTRANCE_D') {
            // West entrance - arrow points right (into parking)
            arrowPath = `M ${entrance.x + 35} ${entrance.y - 10} L ${entrance.x + 50} ${entrance.y} L ${entrance.x + 35} ${entrance.y + 10} Z`;
        }
        arrow.setAttribute('d', arrowPath);
        arrow.setAttribute('fill', entrance.color);
        arrow.setAttribute('opacity', 0.8);
        
        // Entrance circle with icon
        const circle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
        circle.setAttribute('cx', entrance.x);
        circle.setAttribute('cy', entrance.y);
        circle.setAttribute('r', 28);
        circle.setAttribute('fill', entrance.color);
        circle.setAttribute('opacity', 0.9);
        circle.setAttribute('stroke', 'white');
        circle.setAttribute('stroke-width', 3);
        
        const icon = document.createElementNS('http://www.w3.org/2000/svg', 'text');
        icon.setAttribute('x', entrance.x);
        icon.setAttribute('y', entrance.y + 7);
        icon.setAttribute('text-anchor', 'middle');
        icon.setAttribute('font-size', '22');
        icon.textContent = entrance.icon;
        
        // Entrance label
        const label = document.createElementNS('http://www.w3.org/2000/svg', 'text');
        label.setAttribute('x', entrance.x);
        let labelY;
        if (entrance.id === 'ENTRANCE_A') {
            labelY = entrance.y - 40; // Above north entrance
        } else if (entrance.id === 'ENTRANCE_C') {
            labelY = entrance.y + 50; // Below south entrance
        } else if (entrance.id === 'ENTRANCE_B') {
            labelY = entrance.y - 40; // Above east entrance
        } else {
            labelY = entrance.y - 40; // Above west entrance
        }
        label.setAttribute('y', labelY);
        label.setAttribute('text-anchor', 'middle');
        label.setAttribute('fill', entrance.color);
        label.setAttribute('font-size', '13');
        label.setAttribute('font-weight', 'bold');
        label.textContent = entrance.zone.toUpperCase();
        
        // Direction label
        const dirLabel = document.createElementNS('http://www.w3.org/2000/svg', 'text');
        dirLabel.setAttribute('x', entrance.x);
        dirLabel.setAttribute('y', labelY + 14);
        dirLabel.setAttribute('text-anchor', 'middle');
        dirLabel.setAttribute('fill', '#94a3b8');
        dirLabel.setAttribute('font-size', '10');
        const direction = entrance.name.match(/\((.*?)\)/)?.[1] || '';
        dirLabel.textContent = direction;
        
        marker.appendChild(arrow);
        marker.appendChild(circle);
        marker.appendChild(icon);
        marker.appendChild(label);
        marker.appendChild(dirLabel);
        entrancesGroup.appendChild(marker);
    });
}

function getUniqueEntrances() {
    const entrances = [];
    const seen = new Set();
    
    Object.values(baysData).forEach(bay => {
        if (bay.entrance_id && !seen.has(bay.entrance_id)) {
            seen.add(bay.entrance_id);
            entrances.push({
                id: bay.entrance_id,
                name: bay.entrance_name,
                color: bay.entrance_color,
                zone: bay.zone_name,
                // Use actual coordinates from config - stored in first bay of each zone
                x: getEntranceXFromBay(bay.entrance_id),
                y: getEntranceYFromBay(bay.entrance_id),
                icon: getEntranceIcon(bay.zone_name)
            });
        }
    });
    
    return entrances;
}

function getEntranceXFromBay(entranceId) {
    // Return actual entrance coordinates from config - positioned at edges but within viewBox
    if (entranceId === 'ENTRANCE_A') return 600;   // Fashion - North (top center, x remains centered)
    if (entranceId === 'ENTRANCE_B') return 1160;  // Shopping - East (near right edge, within viewBox)
    if (entranceId === 'ENTRANCE_C') return 600;   // Food Court - South (bottom center, x remains centered)
    if (entranceId === 'ENTRANCE_D') return 40;    // Entertainment - West (near left edge, within viewBox)
    return 600;
}

function getEntranceYFromBay(entranceId) {
    // Return actual entrance coordinates from config - positioned at edges but within viewBox
    if (entranceId === 'ENTRANCE_A') return 10;    // Fashion - North (near top, within viewBox, above bays at y: 80)
    if (entranceId === 'ENTRANCE_B') return 400;   // Shopping - East (middle height)
    if (entranceId === 'ENTRANCE_C') return 790;   // Food Court - South (near bottom, within viewBox, below bays at y: 670)
    if (entranceId === 'ENTRANCE_D') return 400;   // Entertainment - West (middle height)
    return 400;
}

function getEntranceX(entranceId) {
    return getEntranceXFromBay(entranceId);
}

function getEntranceY(entranceId) {
    return getEntranceYFromBay(entranceId);
}

function getEntranceIcon(zone) {
    if (zone === 'FASHION') return '👗';
    if (zone === 'SHOPPING') return '🛍️';
    if (zone === 'FOOD') return '🍕';
    if (zone === 'ENTERTAINMENT') return '🎬';
    return '🅿️';
}

function getCategoryBadge(category) {
    if (category === 'POD') return '♿';
    if (category === 'FAMILY') return '👨‍👩‍👧';
    if (category === 'STAFF') return '👔';
    return '';
}

// Update bay visual
function updateBayVisual(bayId, state) {
    console.log(`🔄 Updating bay ${bayId} to state: ${state}`);
    const bayElement = document.querySelector(`[data-bay-id="${bayId}"]`);
    if (bayElement) {
        // Map state names to CSS classes
        let cssClass = 'parking-bay ';
        if (state === 'AVAILABLE' || state === 'available') {
            cssClass += 'available';
        } else if (state === 'UNAVAILABLE' || state === 'unavailable' || state === 'OCCUPIED' || state === 'occupied') {
            cssClass += 'unavailable';
        }
        
        // Update the class
        bayElement.setAttribute('class', cssClass);
        
        // Force the rect element to update its fill color immediately
        const rect = bayElement.querySelector('rect');
        if (rect) {
            if (state === 'AVAILABLE' || state === 'available') {
                rect.style.fill = 'rgba(16, 185, 129, 0.3)'; // Green
                rect.style.stroke = '#10b981';
            } else {
                rect.style.fill = 'rgba(239, 68, 68, 0.3)'; // Red
                rect.style.stroke = '#ef4444';
            }
        }
        
        console.log(`✅ Bay ${bayId} visual updated to: ${cssClass}`);
    } else {
        console.warn(`⚠️ Bay element not found for ${bayId}`);
    }
}

// Update statistics
function updateStatistics() {
    const total = Object.keys(baysData).length;
    const available = Object.values(baysData).filter(b => 
        b.state === 'AVAILABLE' || b.state === 'available'
    ).length;
    const occupied = total - available;
    const occupancy = total > 0 ? Math.round((occupied / total) * 100) : 0;
    
    document.getElementById('totalBays').textContent = total;
    document.getElementById('availableBays').textContent = available;
    document.getElementById('occupiedBays').textContent = occupied;
    document.getElementById('occupancyText').textContent = occupancy + '%';
    document.getElementById('occupancyFill').style.width = occupancy + '%';
}

// Update zones list
function updateZonesList() {
    const zonesList = document.getElementById('zonesList');
    const zones = {};
    
    Object.values(baysData).forEach(bay => {
        if (!zones[bay.zone_name]) {
            zones[bay.zone_name] = {
                name: bay.zone_name,
                entrance: bay.entrance_name,
                color: bay.entrance_color,
                total: 0,
                available: 0
            };
        }
        zones[bay.zone_name].total++;
        if (bay.state === 'AVAILABLE') {
            zones[bay.zone_name].available++;
        }
    });
    
    zonesList.innerHTML = Object.values(zones).map(zone => `
        <div class="zone-item" style="border-left-color: ${zone.color}">
            <div class="zone-header">
                <span class="zone-name">${zone.name}</span>
                <span class="zone-availability">${zone.available}/${zone.total}</span>
            </div>
            <div class="zone-entrance">${zone.entrance}</div>
        </div>
    `).join('');
}

// Add activity
function addActivity(type, message) {
    const feed = document.getElementById('activityFeed');
    const time = new Date().toLocaleTimeString();
    
    const item = document.createElement('div');
    item.className = `activity-item ${type}`;
    item.innerHTML = `
        <span class="time">${time}</span>
        <span>${message}</span>
    `;
    
    feed.insertBefore(item, feed.firstChild);
    
    // Keep only last 50 items
    while (feed.children.length > 50) {
        feed.removeChild(feed.lastChild);
    }
}

// Update clock
function updateClock() {
    const now = new Date();
    const timeStr = now.toLocaleTimeString();
    document.getElementById('currentTime').textContent = timeStr;
}

// Zoom controls
let currentZoom = 0.65;
const minZoom = 0.5;
const maxZoom = 3;

document.getElementById('btnZoomIn')?.addEventListener('click', () => {
    if (currentZoom < maxZoom) {
        currentZoom += 0.2;
        updateZoom();
    }
});

document.getElementById('btnZoomOut')?.addEventListener('click', () => {
    if (currentZoom > minZoom) {
        currentZoom -= 0.2;
        updateZoom();
    }
});

document.getElementById('btnReset')?.addEventListener('click', () => {
    currentZoom = 1;
    updateZoom();
});

function updateZoom() {
    const svg = document.getElementById('parkingMap');
    const mapWrapper = document.getElementById('mapWrapper');
    
    if (svg) {
        svg.style.transform = `scale(${currentZoom})`;
        svg.style.transformOrigin = 'center';
        svg.style.transition = 'transform 0.2s ease';
    }
}
