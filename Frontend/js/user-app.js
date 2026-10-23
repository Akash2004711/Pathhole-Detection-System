// User Dashboard logic: overview, detection, report submission, my reports,
// nearby map and profile. All data comes from the real backend API.

let currentUser = null;
let selectedFile = null;
let selectedVideo = null;
let cameraStream = null;
let lastDetection = null;              // most recent DetectionResult
let reportLocation = { lat: null, lng: null };
let reportMapHandle = null;
let myReportsCache = [];
let userActiveView = "overview";

const $ = (id) => document.getElementById(id);

// ---------- View switching ----------
function switchView(name) {
    if (userActiveView === "detect" && name !== "detect") stopLiveDetection();
    userActiveView = name;
    document.querySelectorAll(".view").forEach(v => v.style.display = "none");
    const el = $("view-" + name);
    if (el) el.style.display = "block";
    document.querySelectorAll(".nav-btn[data-view]").forEach(b =>
        b.classList.toggle("active", b.dataset.view === name));
    if (name === "overview") loadOverview();
    if (name === "reports") loadMyReports();
    if (name === "nearby") initNearby();
    if (name === "submit") initReportMap();
    if (name === "profile") loadProfile();
}

// ---------- Overview ----------
async function loadOverview() {
    try {
        const { reports } = await apiFetch("/api/reports/my");
        myReportsCache = reports;
        const total = reports.length;
        const pending = reports.filter(r => ["submitted", "under_review"].includes(r.status)).length;
        const inRepair = reports.filter(r => ["assigned", "in_progress"].includes(r.status)).length;
        const resolved = reports.filter(r => r.status === "resolved").length;
        $("userStats").innerHTML = [
            statCard("Total reports", total, "#2563eb"),
            statCard("Awaiting verification", pending, "#f59e0b"),
            statCard("Under repair", inRepair, "#0891b2"),
            statCard("Resolved", resolved, "#16a34a"),
        ].join("");
        const recent = reports.slice(0, 5);
        $("recentActivity").innerHTML = recent.length
            ? recent.map(r => reportRow(r)).join("")
            : `<p class="muted">No reports yet. Detect a pothole and submit your first report.</p>`;
    } catch (e) {
        $("userStats").innerHTML = `<p class="muted">${escapeHtml(configHint(e))}</p>`;
    }
}

function statCard(label, value, color) {
    return `<div class="stat-card" style="border-top-color:${color}">
        <div class="stat-value">${escapeHtml(value)}</div>
        <div class="stat-label">${escapeHtml(label)}</div></div>`;
}

function reportRow(r) {
    return `<div class="list-row" data-open="${escapeHtml(r.id)}">
        <div><strong>${escapeHtml(r.id.slice(0, 8))}</strong>
            <div class="muted small">${escapeHtml(r.address || (r.location ? r.location.latitude.toFixed(4) + ", " + r.location.longitude.toFixed(4) : "No location"))}</div>
        </div>
        <div>${statusBadge(r.status)} ${priorityBadge(r.priority)}</div>
    </div>`;
}

function configHint(e) {
    if (e && e.status === 503) return e.message;
    return e && e.message ? e.message : "Could not load data.";
}

// ---------- Detection (image / video / camera) ----------
function initDetection() {
    $("imageInput").addEventListener("change", function () {
        const file = this.files[0];
        if (!file || !file.type.startsWith("image/")) return;
        selectedFile = file; selectedVideo = null;
        showPreview(URL.createObjectURL(file));
        $("detectButton").disabled = false; $("detectVideoButton").disabled = true;
    });
    $("videoInput").addEventListener("change", function () {
        const file = this.files[0];
        if (!file || !file.type.startsWith("video/")) return;
        selectedVideo = file; selectedFile = null;
        $("previewImage").style.display = "none";
        $("previewText").style.display = "block";
        $("previewText").textContent = "🎥 Video selected: " + file.name;
        $("detectVideoButton").disabled = false; $("detectButton").disabled = true;
    });

    $("cameraButton").addEventListener("click", openCamera);
    $("captureButton").addEventListener("click", capturePhoto);
    $("closeCameraButton").addEventListener("click", stopCamera);
    $("liveDetectButton").addEventListener("click", startLiveDetection);
    $("stopLiveButton").addEventListener("click", stopLiveDetection);
    $("detectButton").addEventListener("click", () => runDetection("image"));
    $("detectVideoButton").addEventListener("click", () => runDetection("video"));
    $("useForReportBtn").addEventListener("click", () => {
        switchView("submit");
        setReportSummary();
    });
}

function showPreview(url) {
    $("previewImage").src = url;
    $("previewImage").style.display = "block";
    $("previewText").style.display = "none";
}

async function openCamera() {
    try {
        cameraStream = await navigator.mediaDevices.getUserMedia({
            video: { facingMode: "environment" }, audio: false,
        });
        const v = $("cameraVideo");
        v.srcObject = cameraStream;
        $("cameraContainer").style.display = "block";
        // No click needed: begin live detection automatically once the feed is ready.
        if (v.videoWidth) startLiveDetection();
        else v.addEventListener("loadedmetadata", () => startLiveDetection(), { once: true });
    } catch (e) {
        alert("Cannot open camera: " + e.message + "\nCamera access requires HTTPS or localhost.");
    }
}

function capturePhoto() {
    if (!cameraStream) return;
    const v = $("cameraVideo");
    if (!v.videoWidth) { alert("Camera not ready yet."); return; }
    const canvas = $("cameraCanvas");
    canvas.width = v.videoWidth; canvas.height = v.videoHeight;
    canvas.getContext("2d").drawImage(v, 0, 0, canvas.width, canvas.height);
    canvas.toBlob((blob) => {
        if (!blob) { alert("Capture failed."); return; }
        selectedFile = new File([blob], "camera-photo.jpg", { type: "image/jpeg" });
        selectedVideo = null;
        showPreview(URL.createObjectURL(selectedFile));
        $("detectButton").disabled = false; $("detectVideoButton").disabled = true;
        stopCamera();
    }, "image/jpeg", 0.9);
}

function stopCamera() {
    stopLiveDetection();
    if (cameraStream) { cameraStream.getTracks().forEach(t => t.stop()); cameraStream = null; }
    $("cameraVideo").srcObject = null;
    $("cameraContainer").style.display = "none";
}

// ---------- Live (real-time) camera detection ----------
const LIVE_INTERVAL_MS = 1000;          // sample the camera about once per second
const LIVE_MAX_WIDTH = 640;             // downscale frames (the model input is 640 anyway)
const GPS_CACHE_MS = 60000;             // reuse a recent GPS fix to keep captures fast
const AUTO_REPORT_COOLDOWN_MS = 8000;   // min gap between two auto-reports (dedupe floor)
let liveRunning = false;
let liveBusy = false;
let liveTimer = null;
let reportInFlight = false;             // at most one auto-report pipeline at a time
let cachedPos = null;                   // last GPS fix
let cachedPosAt = 0;
let lastReportAt = 0;                   // when the last auto-report was filed
let lastReportedCount = 0;              // potholes already reported in this sighting
const liveFrameCanvas = document.createElement("canvas");

function setLiveStatus(text) {
    const el = $("liveStatus");
    if (el) el.textContent = text;
}

async function startLiveDetection() {
    if (liveRunning) return;            // already running (e.g. auto-started on open)
    if (!cameraStream) { await openCamera(); if (!cameraStream) return; }
    const v = $("cameraVideo");
    if (!v.videoWidth) { setLiveStatus("Camera not ready yet — try again in a second."); return; }
    liveRunning = true;
    $("liveHud").style.display = "block";
    $("liveDetectButton").style.display = "none";
    $("stopLiveButton").style.display = "inline-block";
    setLiveStatus("Live detection running… sampling the camera in real time.");
    liveTick();                                   // immediate first frame
    liveTimer = setInterval(liveTick, LIVE_INTERVAL_MS);
}

function stopLiveDetection() {
    liveRunning = false;
    if (liveTimer) { clearInterval(liveTimer); liveTimer = null; }
    liveBusy = false;
    const start = $("liveDetectButton"), stop = $("stopLiveButton");
    if (start) start.style.display = "inline-block";
    if (stop) stop.style.display = "none";
    const hud = $("liveHud"); if (hud) hud.style.display = "none";
    clearLiveOverlay();
}

async function liveTick() {
    if (!liveRunning || liveBusy) return;
    const v = $("cameraVideo");
    if (!v.videoWidth || !v.videoHeight) return;
    liveBusy = true;
    try {
        const scale = Math.min(1, LIVE_MAX_WIDTH / v.videoWidth);
        const w = Math.round(v.videoWidth * scale), h = Math.round(v.videoHeight * scale);
        liveFrameCanvas.width = w; liveFrameCanvas.height = h;
        liveFrameCanvas.getContext("2d").drawImage(v, 0, 0, w, h);
        const blob = await new Promise(res => liveFrameCanvas.toBlob(res, "image/jpeg", 0.7));
        if (!blob) return;
        const fd = new FormData();
        fd.append("file", new File([blob], "live-frame.jpg", { type: "image/jpeg" }));
        const t0 = performance.now();
        const data = await apiFetch("/api/detection/image?store=false", { method: "POST", body: fd });
        const rtt = Math.round(performance.now() - t0);
        lastDetection = data;                     // "Use for report" stays live
        drawLiveOverlay(data, w, h);
        updateLiveHud(data, rtt);
        autoReportIfNew(blob, data.pothole_count);
    } catch (e) {
        setLiveStatus("Live detection error: " + (e && e.message ? e.message : e));
    } finally {
        liveBusy = false;
    }
}

function drawLiveOverlay(data, sentW, sentH) {
    const v = $("cameraVideo"), overlay = $("liveOverlay");
    const cw = v.videoWidth, ch = v.videoHeight;
    if (!cw || !ch) return;
    if (overlay.width !== cw) overlay.width = cw;
    if (overlay.height !== ch) overlay.height = ch;
    const ctx = overlay.getContext("2d");
    ctx.clearRect(0, 0, cw, ch);
    const fx = cw / sentW, fy = ch / sentH;
    ctx.lineWidth = Math.max(2, Math.round(cw / 400));
    ctx.font = `${Math.max(14, Math.round(cw / 45))}px system-ui, sans-serif`;
    (data.detections || []).forEach(d => {
        const x = d.bbox.x1 * fx, y = d.bbox.y1 * fy;
        const bw = (d.bbox.x2 - d.bbox.x1) * fx, bh = (d.bbox.y2 - d.bbox.y1) * fy;
        ctx.strokeStyle = "#ff3b3b";
        ctx.strokeRect(x, y, bw, bh);
        const label = `${d.class_name} ${Math.round(d.confidence)}%`;
        const tw = ctx.measureText(label).width;
        ctx.fillStyle = "rgba(255,59,59,.85)";
        ctx.fillRect(x, Math.max(0, y - 20), tw + 8, 20);
        ctx.fillStyle = "#fff";
        ctx.fillText(label, x + 4, Math.max(14, y - 5));
    });
}

function clearLiveOverlay() {
    const overlay = $("liveOverlay");
    if (overlay && overlay.getContext) {
        overlay.getContext("2d").clearRect(0, 0, overlay.width, overlay.height);
    }
}

function updateLiveHud(data, rtt) {
    $("liveCount").textContent = data.pothole_count;
    $("liveConf").textContent = data.max_confidence ? data.max_confidence + "% conf" : "no pothole";
    $("liveLatency").textContent = rtt + " ms";
}

function autoReportIfNew(blob, count) {
    if (!$("autoReportToggle").checked) return;
    if (count === 0) { lastReportedCount = 0; return; }   // scene cleared → next sighting is new
    // Report only when a NEW pothole appears (count increased) and the cooldown passed.
    if (count > lastReportedCount && (Date.now() - lastReportAt) >= AUTO_REPORT_COOLDOWN_MS) {
        maybeAutoReport(blob, count);
    }
}

async function maybeAutoReport(blob, seenCount) {
    if (reportInFlight) return;                    // serialize: one report at a time
    reportInFlight = true;
    try {
        // Reuse a recent GPS fix so every capture can report without re-prompting.
        const now = Date.now();
        if (!cachedPos || (now - cachedPosAt) > GPS_CACHE_MS) {
            try { cachedPos = await getCurrentPosition(); cachedPosAt = now; }
            catch (_) { setLiveStatus("Auto-report skipped: GPS location unavailable."); return; }
        }
        const pos = cachedPos;
        // Run WITH storage so this capture keeps its media, then file the report.
        const fd = new FormData();
        fd.append("file", new File([blob], "live-report.jpg", { type: "image/jpeg" }));
        const stored = await apiFetch("/api/detection/image?store=true", { method: "POST", body: fd });
        const payload = {
            media_type: "image",
            location: { latitude: pos.latitude, longitude: pos.longitude },
            description: "Auto-detected from live camera.",
            category: "pothole",
            detections: stored.detections || [],
            pothole_count: stored.pothole_count || 0,
            max_confidence: stored.max_confidence ?? null,
            original_object: stored.original_object || null,
            annotated_object: stored.annotated_object || null,
        };
        const created = await apiFetch("/api/reports", { method: "POST", json: payload });
        // Record this sighting so the same potholes are not re-reported.
        lastReportAt = Date.now();
        lastReportedCount = Math.max(stored.pothole_count || 0, seenCount || 0);
        setLiveStatus("✅ New pothole captured (" + created.id.slice(0, 8) + ") → dashboard updated. Sighting total: " + lastReportedCount + ".");
        // Reflect immediately on this user's dashboard.
        if (userActiveView === "overview") loadOverview();
        else if (userActiveView === "reports") loadMyReports(true);
    } catch (e) {
        setLiveStatus("Auto-report failed: " + (e && e.message ? e.message : e));
    } finally {
        reportInFlight = false;
    }
}

async function runDetection(type) {
    $("detectError").style.display = "none";
    $("loading").style.display = "block";
    $("loadingText").textContent = type === "video"
        ? "Analyzing video frames. This may take a while..." : "AI is analyzing the image...";
    $("detectButton").disabled = true; $("detectVideoButton").disabled = true;

    const file = type === "video" ? selectedVideo : selectedFile;
    const fd = new FormData();
    fd.append("file", file);
    const path = type === "video" ? "/api/detection/video" : "/api/detection/image";

    try {
        const data = await apiFetch(path, { method: "POST", body: fd });
        lastDetection = data;
        renderDetectionResult(data, type);
    } catch (e) {
        $("detectError").style.display = "block";
        $("detectError").textContent = e.message;
    } finally {
        $("loading").style.display = "none";
        $("detectButton").disabled = !selectedFile;
        $("detectVideoButton").disabled = !selectedVideo;
    }
}

function renderDetectionResult(data, type) {
    $("resultCard").style.display = "block";
    const img = $("resultImage");
    const src = data.annotated_url || data.annotated_media;
    if (src) { img.src = src; img.style.display = "block"; }
    else img.style.display = "none";

    if (data.pothole_count > 0) {
        $("resultInfo").innerHTML =
            `<div class="result-box"><h3>🚧 ${data.pothole_count} pothole detection(s)</h3>
             <p>Highest confidence: <span class="confidence">${data.max_confidence}%</span></p>
             <p class="muted small">Inference time: ${data.inference_time_ms} ms · Model: ${escapeHtml(data.model)}</p></div>` +
            data.detections.slice(0, 12).map((d, i) =>
                `<div class="result-box"><strong>#${i + 1}</strong> ${escapeHtml(d.class_name)} — ${d.confidence}%</div>`
            ).join("");
        if (type === "video") {
            $("resultInfo").innerHTML += `<p class="muted small">Video counts are per-frame detections (sampled every N frames); they may repeat the same physical pothole across frames.</p>`;
        }
    } else {
        $("resultInfo").innerHTML = `<div class="no-result"><h3>✅ No pothole detected</h3><p>The model found no potholes in this ${type}.</p></div>`;
    }
    // Only image detections can be attached to a single report submission.
    $("useForReportBtn").style.display = type === "image" ? "inline-block" : "none";
    $("resultCard").scrollIntoView({ behavior: "smooth", block: "start" });
}

function setReportSummary() {
    if (lastDetection) {
        $("reportDetectSummary").textContent =
            `Detection attached: ${lastDetection.pothole_count} pothole(s), max confidence ${lastDetection.max_confidence || 0}%.`;
    } else {
        $("reportDetectSummary").textContent =
            "No detection attached. Run a detection first for stronger reports, or submit location + description only.";
    }
}

// ---------- Submit report ----------
async function initReportMap() {
    if (reportMapHandle) return;
    setReportSummary();
    try {
        const { L, map } = await createMap("reportMap");
        reportMapHandle = { L, map };
        window.__onLocationChange = (lat, lng) => {
            reportLocation.lat = lat; reportLocation.lng = lng;
            $("lat").value = lat.toFixed(6); $("lng").value = lng.toFixed(6);
        };
        let start = [12.97, 77.59];
        if ($("lat").value && $("lng").value) start = [parseFloat($("lat").value), parseFloat($("lng").value)];
        pickLocationMarker(L, map, start);
    } catch (e) { $("reportMap").innerHTML = `<p class="muted">Map unavailable: ${escapeHtml(e.message)}</p>`; }
}

function bindReportForm() {
    $("useMyLocation").addEventListener("click", async () => {
        try {
            const pos = await getCurrentPosition();
            $("lat").value = pos.latitude; $("lng").value = pos.longitude;
            reportLocation = pos;
            if (reportMapHandle) {
                reportMapHandle.map.setView([pos.latitude, pos.longitude], 16);
            }
        } catch (e) { alert("Location error: " + e.message); }
    });
    $("lat").addEventListener("input", () => { reportLocation.lat = parseFloat($("lat").value); });
    $("lng").addEventListener("input", () => { reportLocation.lng = parseFloat($("lng").value); });

    $("reportForm").addEventListener("submit", async (e) => {
        e.preventDefault();
        const msg = $("reportMessage");
        msg.style.display = "none";
        const lat = parseFloat($("lat").value), lng = parseFloat($("lng").value);
        if (isNaN(lat) || isNaN(lng)) { showFormMsg(msg, "Valid GPS coordinates are required."); return; }

        const payload = {
            media_type: "image",
            location: { latitude: lat, longitude: lng },
            address: $("address").value.trim() || null,
            description: $("description").value.trim() || null,
            category: $("category").value || null,
            detections: lastDetection ? lastDetection.detections : [],
            pothole_count: lastDetection ? lastDetection.pothole_count : 0,
            max_confidence: lastDetection ? lastDetection.max_confidence : null,
            original_object: lastDetection ? (lastDetection.original_object || null) : null,
            annotated_object: lastDetection ? (lastDetection.annotated_object || null) : null,
        };
        try {
            const created = await apiFetch("/api/reports", { method: "POST", json: payload });
            showFormMsg(msg, "✅ Report " + created.id.slice(0, 8) + " submitted.", false);
            lastDetection = null;
            $("reportForm").reset();
            setTimeout(() => switchView("reports"), 1200);
        } catch (e) { showFormMsg(msg, e.message); }
    });
}

function showFormMsg(el, text, isError = true) {
    el.style.display = "block";
    el.className = isError ? "error-message" : "success-note";
    el.textContent = text;
}

// ---------- My reports ----------
async function loadMyReports(live = false) {
    const list = $("myReports");
    if (!live) list.innerHTML = `<p class="muted">Loading...</p>`;
    try {
        const { reports } = await apiFetch("/api/reports/my");
        myReportsCache = reports;
        const statuses = [...new Set(reports.map(r => r.status))];
        const filter = $("reportStatusFilter");
        const cur = filter.value;
        filter.innerHTML = `<option value="">All statuses</option>` +
            statuses.map(s => `<option value="${s}">${STATUS_LABELS[s] || s}</option>`).join("");
        filter.value = cur;
        renderMyReports();
    } catch (e) { if (!live) list.innerHTML = `<p class="muted">${escapeHtml(configHint(e))}</p>`; }
}

function renderMyReports() {
    const q = $("reportSearch").value.toLowerCase();
    const sf = $("reportStatusFilter").value;
    let rows = myReportsCache.filter(r => {
        const matchQ = !q || (r.address || "").toLowerCase().includes(q) || r.id.toLowerCase().includes(q);
        const matchS = !sf || r.status === sf;
        return matchQ && matchS;
    });
    const list = $("myReports");
    list.innerHTML = rows.length
        ? rows.map(reportRow).join("")
        : `<p class="muted">No matching reports.</p>`;
    list.querySelectorAll("[data-open]").forEach(el =>
        el.addEventListener("click", () => openDetail(el.dataset.open)));
}

// ---------- Report detail + timeline ----------
const TIMELINE = ["submitted", "under_review", "verified", "assigned", "in_progress", "resolved"];

async function openDetail(id) {
    try {
        const [report, hist] = await Promise.all([
            apiFetch("/api/reports/" + id),
            apiFetch("/api/reports/" + id + "/history"),
        ]);
        const media = [
            report.original_url ? `<img src="${report.original_url}" class="detail-img" alt="original">` : "",
            report.annotated_url ? `<img src="${report.annotated_url}" class="detail-img" alt="annotated">` : "",
            report.repair_evidence_url ? `<img src="${report.repair_evidence_url}" class="detail-img" alt="repair evidence">` : "",
        ].join("");
        const timeline = buildTimeline(hist.history);
        $("detailBody").innerHTML = `
            <h3>Report ${escapeHtml(report.id.slice(0, 10))}</h3>
            <div class="detail-badges">${statusBadge(report.status)} ${priorityBadge(report.priority)}</div>
            <p><strong>Potholes:</strong> ${report.pothole_count} · <strong>Confidence:</strong> ${report.max_confidence || "n/a"}%</p>
            <p><strong>Location:</strong> ${escapeHtml(report.address || "—")} (${report.location ? report.location.latitude.toFixed(5) + ", " + report.location.longitude.toFixed(5) : "n/a"})</p>
            <p><strong>Description:</strong> ${escapeHtml(report.description || "—")}</p>
            ${report.assigned_team_name ? `<p><strong>Assigned team:</strong> ${escapeHtml(report.assigned_team_name)}</p>` : ""}
            <div class="media-row">${media || `<p class="muted">No media stored for this report.</p>`}</div>
            <h4>Status timeline</h4>
            <div class="timeline">${timeline}</div>`;
        $("detailModal").style.display = "flex";
    } catch (e) { alert("Could not load report: " + e.message); }
}

function buildTimeline(history) {
    const done = new Set(history.map(h => h.new || h.event));
    let html = "";
    TIMELINE.forEach(s => {
        const active = done.has(s);
        html += `<div class="t-step ${active ? "done" : ""}">${STATUS_LABELS[s]}</div>`;
    });
    // Show rejection/duplicate if present.
    const bad = history.find(h => ["rejected", "duplicate"].includes(h.new));
    if (bad) html += `<div class="t-step reject">Closed: ${STATUS_LABELS[bad.new]}</div>`;
    return html;
}

// ---------- Nearby ----------
async function initNearby() {
    if (window.__nearbyInit) { reloadNearby(); return; }
    window.__nearbyInit = true;
    try {
        const { L, map } = await createMap("nearbyMap");
        window.__nearby = { L, map, layer: null };
        reloadNearby();
    } catch (e) { $("nearbyMap").innerHTML = `<p class="muted">Map unavailable: ${escapeHtml(e.message)}</p>`; }
}

async function reloadNearby() {
    const { L, map } = window.__nearby;
    if (window.__nearby.layer) window.__nearby.layer.remove();
    let url = "/api/reports/nearby";
    const note = $("nearbyNote");
    const useRadius = $("nearbyWithin5").checked && window.__nearby.center;
    if (useRadius) {
        url += `?lat=${window.__nearby.center.latitude}&lng=${window.__nearby.center.longitude}&radius_km=5`;
        note.textContent = "Showing reports within 5 km of your location.";
    } else {
        note.textContent = "Showing recent reported potholes. Center on your location for a distance filter.";
    }
    try {
        const { reports } = await apiFetch(url);
        window.__nearby.layer = addReportMarkers(L, map, reports);
        if (!reports.length) note.textContent += " No nearby reports yet.";
    } catch (e) { note.textContent = configHint(e); }
}

// ---------- Profile ----------
function loadProfile() {
    $("profileName").value = currentUser.displayName || "";
    $("profileEmail").value = currentUser.email || "";
    getUserRole(currentUser.uid).then(r => $("profileRole").textContent = r);
    $("profileForm").onsubmit = async (e) => {
        e.preventDefault();
        const name = $("profileName").value.trim();
        const msg = $("profileMessage");
        try {
            await currentUser.updateProfile({ displayName: name });
            await firebase.firestore().collection("users").doc(currentUser.uid).update({
                display_name: name, updated_at: new Date().toISOString(),
            });
            $("userName").textContent = name || "there";
            showFormMsg(msg, "Profile updated.", false);
        } catch (e) { showFormMsg(msg, e.message); }
    };
}

// ---------- Bootstrap ----------
(async function () {
    const session = await requireAuth(["user"]);
    if (!session) return;
    currentUser = session.user;
    $("userName").textContent = currentUser.displayName || (currentUser.email || "there").split("@")[0];

    initDetection();
    bindReportForm();

    document.querySelectorAll(".nav-btn[data-view]").forEach(b =>
        b.addEventListener("click", () => switchView(b.dataset.view)));
    document.querySelectorAll("[data-goto]").forEach(b =>
        b.addEventListener("click", () => switchView(b.dataset.goto)));
    $("logoutBtn").addEventListener("click", logoutUser);
    $("closeDetail").addEventListener("click", () => $("detailModal").style.display = "none");
    $("reportSearch").addEventListener("input", renderMyReports);
    $("reportStatusFilter").addEventListener("change", renderMyReports);
    $("nearbyWithin5").addEventListener("change", reloadNearby);
    $("nearbyLocate").addEventListener("click", async () => {
        try {
            const pos = await getCurrentPosition();
            window.__nearby.center = pos;
            window.__nearby.map.setView([pos.latitude, pos.longitude], 13);
            reloadNearby();
        } catch (e) { $("nearbyNote").textContent = "Location unavailable: " + e.message; }
    });

    loadOverview();

    // Real-time sync: continuously refresh whatever data view is open, so
    // authority status changes (verified/assigned/in-progress/resolved) show up
    // here automatically without a manual reload.
    startLive(async () => {
        if (userActiveView === "overview") await loadOverview();
        else if (userActiveView === "reports") await loadMyReports(true);
        else if (userActiveView === "nearby" && window.__nearby) await reloadNearby();
    });
})();
