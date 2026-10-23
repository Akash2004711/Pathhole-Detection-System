// Government Authority Dashboard: statistics, report management table with
// pagination, verification/reject/priority/assign/status actions, map,
// analytics and maintenance-team administration. All via /api/authority.

let authorityUser = null;
let authorityRole = "government_authority";
let allReports = [];
let page = 1;
let authorityActiveView = "overview";
const PAGE_SIZE = 10;

const $ = (id) => document.getElementById(id);

function switchView(name) {
    authorityActiveView = name;
    document.querySelectorAll(".view").forEach(v => v.style.display = "none");
    const el = $("view-" + name);
    if (el) el.style.display = "block";
    document.querySelectorAll(".nav-btn[data-view]").forEach(b =>
        b.classList.toggle("active", b.dataset.view === name));
    if (name === "overview") loadOverview();
    if (name === "reports") loadReports();
    if (name === "map") initMap();
    if (name === "analytics") loadAnalytics();
    if (name === "teams") loadTeams();
    if (name === "profile") loadProfile();
}

// ---------- Overview ----------
async function loadOverview() {
    try {
        const a = await apiFetch("/api/authority/analytics");
        $("govStats").innerHTML = [
            stat("Total reports", a.total_reports, "#111827"),
            stat("New", a.new_reports, "#2563eb"),
            stat("Pending verification", a.pending_verification, "#f59e0b"),
            stat("High priority", a.high_priority, "#dc2626"),
            stat("Awaiting assignment", a.awaiting_assignment, "#0891b2"),
            stat("Active repairs", a.active_repairs, "#f97316"),
            stat("Completed", a.completed_repairs, "#16a34a"),
            stat("Rejected", a.rejected, "#6b7280"),
        ].join("");
    } catch (e) { $("govOverviewNote").textContent = configHint(e); }
}

function stat(label, value, color) {
    return `<div class="stat-card" style="border-top-color:${color}">
        <div class="stat-value">${escapeHtml(value)}</div>
        <div class="stat-label">${escapeHtml(label)}</div></div>`;
}

function configHint(e) {
    return (e && (e.message || "Could not load data."));
}

// ---------- Reports table ----------
async function loadReports(live = false) {
    const status = $("govStatusFilter").value;
    const priority = $("govPriorityFilter").value;
    let url = "/api/authority/reports?limit=500";
    if (status) url += "&status=" + encodeURIComponent(status);
    if (priority) url += "&priority=" + encodeURIComponent(priority);
    try {
        const { reports } = await apiFetch(url);
        allReports = reports;
        const statuses = [...new Set(reports.map(r => r.status))];
        const sf = $("govStatusFilter");
        const cur = sf.value;
        sf.innerHTML = `<option value="">All statuses</option>` +
            statuses.map(s => `<option value="${s}">${STATUS_LABELS[s] || s}</option>`).join("");
        sf.value = cur;
        if (!live) page = 1;
        renderTable();
    } catch (e) { $("govTable").querySelector("tbody").innerHTML =
        `<tr><td colspan="9" class="muted">${escapeHtml(configHint(e))}</td></tr>`; }
}

function filtered() {
    const q = $("govSearch").value.toLowerCase();
    return allReports.filter(r => !q ||
        (r.address || "").toLowerCase().includes(q) || r.id.toLowerCase().includes(q));
}

function renderTable() {
    const rows = filtered();
    const totalPages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
    if (page > totalPages) page = totalPages;
    const slice = rows.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);
    $("pageInfo").textContent = ` Page ${page} / ${totalPages} · ${rows.length} reports`;

    $("govTable").querySelector("tbody").innerHTML = slice.map(r => `
        <tr>
            <td><button class="link-btn mono" data-open="${escapeHtml(r.id)}">${escapeHtml(r.id.slice(0, 8))}</button></td>
            <td class="small">${escapeHtml((r.created_at || "").slice(0, 10))}</td>
            <td class="small">${escapeHtml(r.address || (r.location ? r.location.latitude.toFixed(3) + ", " + r.location.longitude.toFixed(3) : "—"))}</td>
            <td>${escapeHtml(r.pothole_count)}</td>
            <td>${escapeHtml(r.max_confidence || "—")}</td>
            <td>${statusBadge(r.status)}</td>
            <td>${priorityBadge(r.priority)}</td>
            <td class="small">${escapeHtml(r.assigned_team_name || "—")}</td>
            <td><button class="link-btn" data-open="${escapeHtml(r.id)}">Manage</button></td>
        </tr>`).join("") ||
        `<tr><td colspan="9" class="muted">No reports found.</td></tr>`;

    $("govTable").querySelectorAll("[data-open]").forEach(el =>
        el.addEventListener("click", () => openDetail(el.dataset.open)));
}

// ---------- Report detail + actions ----------
async function openDetail(id) {
    try {
        const [r, hist, teams] = await Promise.all([
            apiFetch("/api/reports/" + id),
            apiFetch("/api/reports/" + id + "/history").catch(() => ({ history: [] })),
            apiFetch("/api/authority/maintenance-teams").catch(() => ({ teams: [] })),
        ]);
        window.__currentReport = r;
        const media = [
            r.original_url ? `<img src="${r.original_url}" class="detail-img">` : "",
            r.annotated_url ? `<img src="${r.annotated_url}" class="detail-img">` : "",
            r.repair_evidence_url ? `<img src="${r.repair_evidence_url}" class="detail-img">` : "",
        ].join("");
        const teamOpts = (teams.teams || []).map(t =>
            `<option value="${escapeHtml(t.id)}">${escapeHtml(t.name)}</option>`).join("");
        $("detailBody").innerHTML = `
            <h3>Report ${escapeHtml(r.id.slice(0, 10))} ${statusBadge(r.status)} ${priorityBadge(r.priority)}</h3>
            <p><strong>Potholes:</strong> ${r.pothole_count} · <strong>Confidence:</strong> ${escapeHtml(r.max_confidence || "n/a")}</p>
            <p><strong>Location:</strong> ${escapeHtml(r.address || "—")} (${r.location ? r.location.latitude.toFixed(5) + ", " + r.location.longitude.toFixed(5) : "n/a"})</p>
            <p><strong>Description:</strong> ${escapeHtml(r.description || "—")}</p>
            <p><strong>Team:</strong> ${escapeHtml(r.assigned_team_name || "—")}</p>
            <div class="media-row">${media || '<p class="muted">No media.</p>'}</div>

            <div class="action-panel">
                <h4>Actions</h4>
                <div class="row">
                    <button class="act-btn green" data-act="verified">✔ Verify</button>
                    <button class="act-btn gray" data-act="duplicate">Duplicate</button>
                    <button class="act-btn red" data-act="rejected">✖ Reject</button>
                </div>
                <div class="row">
                    <select id="actPriority">
                        <option value="">Set priority…</option>
                        <option value="critical">Critical</option><option value="high">High</option>
                        <option value="medium">Medium</option><option value="low">Low</option>
                    </select>
                    <button class="act-btn blue" data-act="priority">Apply priority</button>
                </div>
                <div class="row">
                    <select id="actTeam"><option value="">Select team…</option>${teamOpts}</select>
                    <input type="date" id="actTargetDate">
                    <button class="act-btn blue" data-act="assign">Assign team</button>
                </div>
                <div class="row">
                    <select id="actStatus">
                        <option value="">Advance status…</option>
                        <option value="under_review">Under Review</option>
                        <option value="in_progress">Start repair</option>
                        <option value="resolved">Resolve (needs evidence)</option>
                        <option value="reopened">Reopen</option>
                    </select>
                    <input type="file" id="actEvidence" accept="image/*">
                    <button class="act-btn blue" data-act="status">Update status</button>
                </div>
                <p id="actMsg" class="small-text"></p>
            </div>

            <h4>History</h4>
            <div class="history">${(hist.history || []).map(h =>
                `<div class="h-row"><span>${escapeHtml(h.event)}</span>
                 <span class="muted small">${escapeHtml((h.created_at || "").replace("T", " ").slice(0, 19))}</span>
                 ${h.reason ? `<span class="small">— ${escapeHtml(h.reason)}</span>` : ""}</div>`).join("")}</div>`;
        $("detailModal").style.display = "flex";
        bindActions(r);
    } catch (e) { alert("Could not open report: " + e.message); }
}

function bindActions(r) {
    document.querySelectorAll("[data-act]").forEach(btn => {
        btn.onclick = () => handleAction(btn.dataset.act, r);
    });
}

async function handleAction(act, r) {
    const msg = $("actMsg");
    msg.textContent = "Working...";
    try {
        if (act === "verified" || act === "duplicate") {
            const note = prompt("Optional review note:") || null;
            await apiFetch(`/api/authority/reports/${r.id}/verify`, { method: "POST", json: { decision: act, note } });
        } else if (act === "rejected") {
            const reason = prompt("Rejection reason (required):");
            if (!reason) { msg.textContent = "Rejection needs a reason."; return; }
            await apiFetch(`/api/authority/reports/${r.id}/reject`, { method: "POST", json: { reason } });
        } else if (act === "priority") {
            const p = $("actPriority").value;
            if (!p) { msg.textContent = "Choose a priority first."; return; }
            await apiFetch(`/api/authority/reports/${r.id}/priority`, { method: "PATCH", json: { priority: p } });
        } else if (act === "assign") {
            const team = $("actTeam").value;
            if (!team) { msg.textContent = "Choose a team first."; return; }
            await apiFetch(`/api/authority/reports/${r.id}/assign`, { method: "POST",
                json: { team_id: team, target_date: $("actTargetDate").value || null } });
        } else if (act === "status") {
            const s = $("actStatus").value;
            if (!s) { msg.textContent = "Choose a status first."; return; }
            let evidenceObject = null;
            if (s === "resolved" && $("actEvidence").files[0]) {
                evidenceObject = await uploadEvidence(r.id, $("actEvidence").files[0]);
            }
            await apiFetch(`/api/authority/reports/${r.id}/status`, { method: "PATCH",
                json: { status: s, evidence_object: evidenceObject } });
        }
        msg.textContent = "✅ Done. Refreshing...";
        await openDetail(r.id);
        loadReports();
    } catch (e) { msg.textContent = "⚠️ " + e.message; }
}

async function uploadEvidence(reportId, file) {
    // Privileged upload goes through the backend (Admin SDK), which enforces
    // the authority role - never a direct client Storage write.
    const fd = new FormData();
    fd.append("file", file);
    const res = await apiFetch(`/api/authority/reports/${reportId}/evidence`,
        { method: "POST", body: fd });
    return res.evidence_object;
}

// ---------- Map ----------
async function initMap() {
    if (window.__govMap) { reloadGovMap(); return; }
    try {
        const { L, map } = await createMap("govMap");
        window.__govMap = { L, map, layer: null };
        reloadGovMap();
    } catch (e) { $("govMap").innerHTML = `<p class="muted">Map unavailable: ${escapeHtml(e.message)}</p>`; }
}

async function reloadGovMap() {
    const { L, map } = window.__govMap;
    if (window.__govMap.layer) window.__govMap.layer.remove();
    let url = "/api/authority/reports?limit=500";
    if ($("mapStatusFilter").value) url += "&status=" + encodeURIComponent($("mapStatusFilter").value);
    if ($("mapPriorityFilter").value) url += "&priority=" + encodeURIComponent($("mapPriorityFilter").value);
    try {
        const { reports } = await apiFetch(url);
        window.__govMap.layer = addReportMarkers(L, map, reports);
    } catch (e) { /* ignore */ }
}

// ---------- Analytics ----------
async function loadAnalytics() {
    try {
        const a = await apiFetch("/api/authority/analytics");
        const bar = (obj) => {
            const entries = Object.entries(obj || {});
            if (!entries.length) return `<p class="muted">No data yet.</p>`;
            const max = Math.max(...entries.map(e => e[1]));
            return entries.map(([k, v]) =>
                `<div class="bar-row"><span class="bar-label">${escapeHtml(STATUS_LABELS[k] || k)}</span>
                 <div class="bar-track"><div class="bar-fill" style="width:${(v / max * 100).toFixed(0)}%"></div></div>
                 <span class="bar-val">${v}</span></div>`).join("");
        };
        $("analyticsBody").innerHTML = `
            <h4>Reports by status</h4>${bar(a.by_status)}
            <h4>Reports by priority</h4>${bar(a.by_priority)}
            <h4>Top areas (recurring hotspots)</h4>${bar(a.by_area)}
            <div class="metric-row">
                <div class="metric"><strong>${escapeHtml(a.avg_hours_submit_to_verify ?? "n/a")}</strong><span>avg hrs: submit→verify</span></div>
                <div class="metric"><strong>${escapeHtml(a.avg_hours_assign_to_complete ?? "n/a")}</strong><span>avg hrs: assign→complete</span></div>
                <div class="metric"><strong>${escapeHtml(a.completed_repairs)}</strong><span>completed repairs</span></div>
            </div>
            <p class="muted small">Averages are computed from stored timestamps; records missing a timestamp are excluded.</p>`;
    } catch (e) { $("analyticsBody").innerHTML = `<p class="muted">${escapeHtml(configHint(e))}</p>`; }
}

// ---------- Teams ----------
async function loadTeams() {
    try {
        const { teams } = await apiFetch("/api/authority/maintenance-teams");
        $("teamList").innerHTML = teams.length ? teams.map(t => `
            <div class="list-row">
                <div><strong>${escapeHtml(t.name)}</strong>
                    <div class="muted small">${escapeHtml(t.jurisdiction || "—")} · ${escapeHtml(t.contact_email || "")}</div></div>
                <div>${t.active ? '<span class="badge badge-resolved">active</span>' : '<span class="badge badge-rejected">inactive</span>'}
                    <button class="link-btn" data-toggle="${escapeHtml(t.id)}" data-active="${!t.active}">toggle</button></div>
            </div>`).join("") : `<p class="muted">No maintenance teams yet.</p>`;
        $("teamList").querySelectorAll("[data-toggle]").forEach(el =>
            el.onclick = async () => {
                try {
                    await apiFetch("/api/authority/maintenance-teams/" + el.dataset.toggle,
                        { method: "PATCH", json: { active: el.dataset.active === "true" } });
                    loadTeams();
                } catch (e) { alert(e.message); }
            });
    } catch (e) { $("teamList").innerHTML = `<p class="muted">${escapeHtml(configHint(e))}</p>`; }
}

function bindTeamForm() {
    $("teamForm").addEventListener("submit", async (e) => {
        e.preventDefault();
        try {
            await apiFetch("/api/authority/maintenance-teams", { method: "POST", json: {
                name: $("teamName").value.trim(),
                contact_email: $("teamEmail").value.trim() || null,
                jurisdiction: $("teamJurisdiction").value.trim() || null,
            }});
            $("teamForm").reset();
            loadTeams();
        } catch (e) { alert(e.message); }
    });
}

// ---------- Profile ----------
function loadProfile() {
    $("govName").textContent = authorityUser.displayName || "—";
    $("govEmail").textContent = authorityUser.email || "—";
    // Use the role already resolved authoritatively by requireAuth (from the
    // backend) instead of a second client-side Firestore read that can return
    // empty when offline. Fall back to the live role only if something changed.
    $("govRole").textContent = authorityRole || "government_authority";
    getUserRole(authorityUser.uid)
        .then(r => { if (r) { authorityRole = r; $("govRole").textContent = r; } })
        .catch(() => { /* keep the resolved role already shown */ });
}

// ---------- Bootstrap ----------
(async function () {
    const session = await requireAuth(["government_authority"]);
    if (!session) return;
    authorityUser = session.user;
    authorityRole = session.role || "government_authority";

    document.querySelectorAll(".nav-btn[data-view]").forEach(b =>
        b.addEventListener("click", () => switchView(b.dataset.view)));
    $("logoutBtn").addEventListener("click", logoutUser);
    $("closeDetail").addEventListener("click", () => $("detailModal").style.display = "none");
    $("govReload").addEventListener("click", loadReports);
    $("govSearch").addEventListener("input", renderTable);
    $("prevPage").addEventListener("click", () => { page--; renderTable(); });
    $("nextPage").addEventListener("click", () => { page++; renderTable(); });
    $("mapStatusFilter").innerHTML = `<option value="">All statuses</option>` +
        Object.entries(STATUS_LABELS).map(([k, v]) =>
            `<option value="${escapeHtml(k)}">${escapeHtml(v)}</option>`).join("");
    $("mapStatusFilter").addEventListener("change", reloadGovMap);
    $("mapPriorityFilter").addEventListener("change", reloadGovMap);
    bindTeamForm();

    loadOverview();

    // Real-time sync: keep whatever authority view is open fresh, so a citizen's
    // new report (or status changes elsewhere) appears here automatically
    // without reloading.
    startLive(async () => {
        if (authorityActiveView === "overview") await loadOverview();
        else if (authorityActiveView === "reports") await loadReports(true);
        else if (authorityActiveView === "analytics") await loadAnalytics();
        else if (authorityActiveView === "teams") await loadTeams();
        else if (authorityActiveView === "map" && window.__govMap) await reloadGovMap();
    });
})();
