// Shared runtime config + Firebase bootstrap for the frontend.
// Firebase web config and the Maps key are fetched from the backend
// (/api/config), which reads them from the environment. No secrets here.

const API_BASE = window.location.origin.startsWith("http") &&
    !location.port ? location.origin : "http://127.0.0.1:8000";

const PDS = {
    config: null,
    apiBase: API_BASE,

    async loadConfig() {
        if (this.config) return this.config;
        try {
            const res = await fetch(API_BASE + "/api/config");
            this.config = await res.json();
        } catch (e) {
            console.error("Failed to load /api/config:", e);
            this.config = { apiKey: "", projectId: "", googleMapsApiKey: "" };
        }
        return this.config;
    },

    firebaseEnabled() {
        return !!(this.config && this.config.apiKey && this.config.authDomain);
    },

    initFirebase() {
        if (!this.firebaseEnabled()) return null;
        if (window.__pdsFirebaseApp) return window.__pdsFirebaseApp;
        const app = firebase.initializeApp(this.config);
        window.__pdsFirebaseApp = app;
        return app;
    },

    auth() {
        const app = this.initFirebase();
        return app ? firebase.auth() : null;
    },
};

// Authenticated fetch helper: attaches the Firebase ID token.
async function apiFetch(path, options = {}) {
    const auth = PDS.auth();
    const headers = Object.assign({}, options.headers || {});
    if (auth && auth.currentUser) {
        const token = await auth.currentUser.getIdToken();
        headers["Authorization"] = "Bearer " + token;
    }
    if (options.json) {
        headers["Content-Type"] = "application/json";
        options.body = JSON.stringify(options.json);
        delete options.json;
    }
    const res = await fetch(PDS.apiBase + path, { ...options, headers });
    const text = await res.text();
    let data = null;
    try { data = text ? JSON.parse(text) : null; } catch (_) { data = { raw: text }; }
    if (!res.ok) {
        const detail = (data && (data.detail || data.message)) || res.statusText;
        const err = new Error(detail);
        err.status = res.status;
        err.data = data;
        throw err;
    }
    return data;
}

function escapeHtml(s) {
    return String(s == null ? "" : s)
        .replace(/[&<>"']/g, c => ({
            "&": "&amp;", "<": "&lt;", ">": "&gt;",
            '"': "&quot;", "'": "&#39;",
        }[c]));
}

const STATUS_LABELS = {
    submitted: "Submitted", under_review: "Under Review", verified: "Verified",
    rejected: "Rejected", duplicate: "Duplicate", assigned: "Assigned",
    in_progress: "In Progress", resolved: "Resolved", reopened: "Reopened",
};

const PRIORITY_COLORS = {
    low: "#16a34a", medium: "#2563eb", high: "#f59e0b", critical: "#dc2626",
};

function statusBadge(status) {
    const label = STATUS_LABELS[status] || status || "Unknown";
    return `<span class="badge badge-${escapeHtml(status)}">${escapeHtml(label)}</span>`;
}

function priorityBadge(priority) {
    if (!priority) return `<span class="muted">—</span>`;
    const color = PRIORITY_COLORS[priority] || "#6b7280";
    return `<span class="badge" style="background:${color};color:#fff">${escapeHtml(priority)}</span>`;
}

// ---------- Live sync (auto-refresh between dashboards) ----------
// Both dashboards poll the authenticated backend on a short interval while the
// relevant view is open, so a citizen's new report shows up on the authority
// dashboard and an authority's status change shows up on the citizen dashboard
// without any manual reload. Uses the same backend endpoints (Admin SDK), so it
// works for every role with no extra setup. The heartbeat pauses when the tab is
// hidden to avoid needless requests.
const LIVE = { intervalMs: 5000, timer: null, badge: null };

function ensureLiveBadge() {
    if (LIVE.badge && document.body.contains(LIVE.badge)) return LIVE.badge;
    const b = document.createElement("div");
    b.id = "liveBadge";
    b.className = "live-badge";
    b.title = "Auto-refreshing in real time";
    b.innerHTML = '<span class="live-dot"></span> Live';
    document.body.appendChild(b);
    LIVE.badge = b;
    return b;
}

function flashLive() {
    const b = ensureLiveBadge();
    b.classList.add("pulse");
    setTimeout(() => b.classList.remove("pulse"), 700);
}

function setLiveStatus(text, ok = true) {
    const b = ensureLiveBadge();
    b.innerHTML = `<span class="live-dot${ok ? "" : " err"}"></span> ${escapeHtml(text)}`;
}

function startLive(tick, intervalMs = LIVE.intervalMs) {
    ensureLiveBadge();
    stopLive();
    const run = () => {
        if (document.hidden) return;              // pause when tab not visible
        setLiveStatus("Syncing…");
        Promise.resolve()
            .then(tick)
            .then(() => { setLiveStatus("Live"); flashLive(); })
            .catch(() => setLiveStatus("Offline", false));
    };
    run();                                          // immediate first sync
    LIVE.timer = setInterval(run, intervalMs);
}

function stopLive() {
    if (LIVE.timer) { clearInterval(LIVE.timer); LIVE.timer = null; }
}
