// Map helper. Uses Leaflet (OpenStreetMap tiles) which works without any API
// key, as permitted by the spec. If GOOGLE_MAPS_API_KEY is configured the app
// still works; Leaflet is the default, honest, always-available map layer.

function loadLeaflet() {
    return new Promise((resolve, reject) => {
        if (window.L) return resolve(window.L);
        const css = document.createElement("link");
        css.rel = "stylesheet";
        css.href = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css";
        document.head.appendChild(css);
        const js = document.createElement("script");
        js.src = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js";
        js.onload = () => resolve(window.L);
        js.onerror = reject;
        document.head.appendChild(js);
    });
}

const STATUS_MARKER_COLORS = {
    submitted: "#2563eb", under_review: "#6366f1", verified: "#0891b2",
    assigned: "#f59e0b", in_progress: "#f97316", resolved: "#16a34a",
    rejected: "#6b7280", duplicate: "#6b7280", reopened: "#dc2626",
};

async function createMap(elementId, center = [12.97, 77.59], zoom = 12) {
    const L = await loadLeaflet();
    const map = L.map(elementId).setView(center, zoom);
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
        attribution: "&copy; OpenStreetMap contributors",
        maxZoom: 19,
    }).addTo(map);
    return { L, map };
}

// Plot report markers with popups. Returns array of layer handles.
function addReportMarkers(L, map, reports) {
    const layer = L.layerGroup().addTo(map);
    const bounds = [];
    reports.forEach(r => {
        if (!r.location || r.location.latitude == null) return;
        const pos = [r.location.latitude, r.location.longitude];
        bounds.push(pos);
        const color = STATUS_MARKER_COLORS[r.status] || "#2563eb";
        const marker = L.circleMarker(pos, {
            radius: 8, color, fillColor: color, fillOpacity: 0.8, weight: 2,
        });
        marker.bindPopup(
            `<strong>Report ${escapeHtml(r.id.slice(0, 8))}</strong><br>` +
            `Status: ${escapeHtml(STATUS_LABELS[r.status] || r.status)}<br>` +
            `Potholes: ${escapeHtml(r.pothole_count)}<br>` +
            (r.address ? `Location: ${escapeHtml(r.address)}<br>` : "") +
            (r.priority ? `Priority: ${escapeHtml(r.priority)}<br>` : "")
        );
        marker.on("click", () => { if (window.__onMarkerClick) window.__onMarkerClick(r); });
        layer.addLayer(marker);
    });
    if (bounds.length) map.fitBounds(bounds, { padding: [30, 30] });
    return layer;
}

// A single draggable marker for picking/adjusting a report location.
function pickLocationMarker(L, map, pos) {
    let marker = L.marker(pos, { draggable: true }).addTo(map);
    marker.on("dragend", () => {
        const p = marker.getLatLng();
        if (window.__onLocationChange) window.__onLocationChange(p.lat, p.lng);
    });
    map.setView(pos, Math.max(map.getZoom(), 15));
    if (window.__onLocationChange) window.__onLocationChange(pos[0], pos[1]);
    return marker;
}

// Request the browser's current position (explicit permission).
function getCurrentPosition() {
    return new Promise((resolve, reject) => {
        if (!navigator.geolocation) {
            reject(new Error("Geolocation is not supported by this browser."));
            return;
        }
        navigator.geolocation.getCurrentPosition(
            pos => resolve({ latitude: pos.coords.latitude, longitude: pos.coords.longitude }),
            err => reject(err),
            { enableHighAccuracy: true, timeout: 10000, maximumAge: 60000 }
        );
    });
}
