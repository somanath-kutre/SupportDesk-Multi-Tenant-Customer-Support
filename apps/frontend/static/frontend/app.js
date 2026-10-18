/* SupportDesk frontend: dependency-free single-page app (hash routing, JWT, WebSocket). */
(() => {
  "use strict";
  const API = "/api/v1";

  // ------------------------------------------------------------------ helpers
  const $ = (sel, el = document) => el.querySelector(sel);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const fmt = (iso) => (iso ? new Date(iso).toLocaleString() : "-");
  const label = (v) => String(v || "").replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
  const isStaff = (r) => ["org_admin", "manager", "agent"].includes(r);
  const isManager = (r) => ["org_admin", "manager"].includes(r);

  function toast(msg, isErr = false) {
    const el = document.createElement("div");
    el.className = "toast" + (isErr ? " err" : "");
    el.textContent = msg;
    $("#toasts").appendChild(el);
    setTimeout(() => el.remove(), 4500);
  }

  // --------------------------------------------------------------- auth store
  const getAccess = () => localStorage.getItem("sd_access");
  const getRefresh = () => localStorage.getItem("sd_refresh");
  function setTokens(t) {
    if (t.access) localStorage.setItem("sd_access", t.access);
    if (t.refresh) localStorage.setItem("sd_refresh", t.refresh);
  }
  function clearTokens() {
    localStorage.removeItem("sd_access");
    localStorage.removeItem("sd_refresh");
  }
  function parseJwt(token) {
    try {
      const b64 = token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
      const json = decodeURIComponent(atob(b64).split("").map((c) => "%" + ("00" + c.charCodeAt(0).toString(16)).slice(-2)).join(""));
      return JSON.parse(json);
    } catch (e) { return null; }
  }
  const me = () => (getAccess() ? parseJwt(getAccess()) : null);  // {user_id, username, role, org_id}

  // ---------------------------------------------------------------- API layer
  class ApiError extends Error {
    constructor(status, message, data) { super(message); this.status = status; this.data = data; }
  }

  function errorMessage(data, status) {
    const e = data && data.error;
    if (!e) return `Request failed (${status})`;
    if (e.details && typeof e.details === "object") {
      const parts = Object.entries(e.details).map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(" ") : v}`);
      if (parts.length) return parts.join(" | ");
    }
    return e.message || `Request failed (${status})`;
  }

  let refreshing = null;
  async function refreshAccess() {
    if (!getRefresh()) return false;
    if (!refreshing) {
      refreshing = fetch(`${API}/auth/refresh/`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ refresh: getRefresh() }),
      }).then(async (r) => { if (!r.ok) return false; setTokens(await r.json()); return true; })
        .catch(() => false).finally(() => { refreshing = null; });
    }
    return refreshing;
  }

  async function api(path, { method = "GET", body, form, auth = true, raw = false } = {}, canRetry = true) {
    const headers = {};
    let payload;
    if (auth && getAccess()) headers.Authorization = "Bearer " + getAccess();
    if (form) payload = form;
    else if (body !== undefined) { headers["Content-Type"] = "application/json"; payload = JSON.stringify(body); }
    const res = await fetch(API + path, { method, headers, body: payload });
    if (res.status === 401 && auth && canRetry && getRefresh()) {
      if (await refreshAccess()) return api(path, { method, body, form, auth, raw }, false);
      logout();
      throw new ApiError(401, "Session expired. Please sign in again.");
    }
    if (raw) return res;
    if (res.status === 204) return null;
    let data = null;
    try { data = await res.json(); } catch (e) { /* empty body */ }
    if (!res.ok) throw new ApiError(res.status, errorMessage(data, res.status), data);
    return data;
  }

  function logout() {
    const refresh = getRefresh();
    if (refresh && getAccess()) {
      fetch(`${API}/auth/logout/`, { method: "POST", headers: { "Content-Type": "application/json", Authorization: "Bearer " + getAccess() }, body: JSON.stringify({ refresh }) }).catch(() => {});
    }
    clearTokens();
    closeWs();
    stopPolling();
    location.hash = "#/login";
  }

  // -------------------------------------------------------------- UI building
  const app = $("#app");
  function shell(active, inner) {
    const u = me();
    const links = [["tickets", "Tickets"]];
    if (isManager(u.role)) links.push(["dashboard", "Dashboard"]);
    if (isManager(u.role)) links.push(["team", "Team & SLA"]);
    links.push(["notifications", "Notifications"]);
    app.innerHTML = `
      <header class="topbar">
        <span class="brand">SupportDesk</span>
        <nav>${links.map(([k, t]) => `<a href="#/${k}" class="${active === k ? "active" : ""}">${t}${k === "notifications" ? ' <span id="bellcount"></span>' : ""}</a>`).join("")}</nav>
        <span class="who">${esc(u.username)} · ${esc(label(u.role))}</span>
        <button id="logout">Sign out</button>
      </header>
      <main>${inner}</main>`;
    $("#logout").onclick = logout;
    updateBell();
  }

  function modal(title, bodyHtml, onMount) {
    const back = document.createElement("div");
    back.className = "modal-back";
    back.innerHTML = `<div class="modal"><div class="row spread"><h2>${esc(title)}</h2><button data-x>✕</button></div>${bodyHtml}</div>`;
    document.body.appendChild(back);
    const close = () => back.remove();
    back.addEventListener("click", (e) => { if (e.target === back) close(); });
    $("[data-x]", back).onclick = close;
    onMount(back, close);
  }

  const statusBadge = (s) => `<span class="badge s-${esc(s)}">${esc(label(s))}</span>`;
  const priorityBadge = (p) => `<span class="badge p-${esc(p)}">${esc(label(p))}</span>`;

  function slaText(t) {
    if (t.first_response_at) return `<span class="ok">Responded</span>`;
    if (!t.first_response_due_at || ["resolved", "closed"].includes(t.status)) return `<span class="muted">-</span>`;
    if (t.first_response_breached) return `<span class="bad">Breached</span>`;
    const mins = Math.round((new Date(t.first_response_due_at) - Date.now()) / 60000);
    if (mins < 0) return `<span class="bad">Overdue</span>`;
    return mins < 90 ? `Due in ${mins} min` : `Due in ${Math.round(mins / 60)} h`;
  }

  // ------------------------------------------------------------------- login
  function pageLogin() {
    stopPolling();
    app.innerHTML = `
      <div class="auth card">
        <h1>SupportDesk</h1><p class="muted">Multi-tenant customer support &amp; SLA platform</p>
        <div class="tabs"><button data-t="in" class="on">Sign in</button><button data-t="cust">Customer sign-up</button><button data-t="org">New organization</button></div>
        <form id="f-in">
          <label>Username</label><input name="username" autocomplete="username" required>
          <label>Password</label><input name="password" type="password" autocomplete="current-password" required>
          <p><button class="primary" type="submit">Sign in</button></p>
          <p class="small muted">Demo (after <code>seed_demo</code>): customer1 / agent1 / manager / admin, password <code>Pass@12345</code></p>
        </form>
        <form id="f-cust" hidden>
          <label>Organization slug</label><input name="org_slug" placeholder="acme" required>
          <label>Username</label><input name="username" required>
          <label>Email</label><input name="email" type="email" required>
          <label>Password (min 8, not common)</label><input name="password" type="password" required>
          <p><button class="primary" type="submit">Create customer account</button></p>
        </form>
        <form id="f-org" hidden>
          <label>Organization name</label><input name="organization_name" required>
          <label>Admin username</label><input name="username" required>
          <label>Admin email</label><input name="email" type="email" required>
          <label>Password</label><input name="password" type="password" required>
          <p><button class="primary" type="submit">Create organization</button></p>
        </form>
      </div>`;
    const forms = { in: $("#f-in"), cust: $("#f-cust"), org: $("#f-org") };
    app.querySelectorAll(".tabs button").forEach((b) => (b.onclick = () => {
      app.querySelectorAll(".tabs button").forEach((x) => x.classList.toggle("on", x === b));
      Object.entries(forms).forEach(([k, f]) => (f.hidden = k !== b.dataset.t));
    }));
    const data = (f) => Object.fromEntries(new FormData(f));
    const login = async (username, password) => {
      setTokens(await api("/auth/login/", { method: "POST", body: { username, password }, auth: false }));
      location.hash = "#/tickets";
    };
    forms.in.onsubmit = async (e) => {
      e.preventDefault();
      const d = data(forms.in);
      try { await login(d.username, d.password); } catch (err) { toast(err.message, true); }
    };
    forms.cust.onsubmit = async (e) => {
      e.preventDefault();
      const d = data(forms.cust);
      try { await api("/auth/register/", { method: "POST", body: d, auth: false }); await login(d.username, d.password); toast("Account created"); }
      catch (err) { toast(err.message, true); }
    };
    forms.org.onsubmit = async (e) => {
      e.preventDefault();
      const d = data(forms.org);
      try { await api("/auth/register-organization/", { method: "POST", body: d, auth: false }); await login(d.username, d.password); toast("Organization created"); }
      catch (err) { toast(err.message, true); }
    };
  }

  // ----------------------------------------------------------------- tickets
  const listState = { page: 1, status: "", priority: "", search: "", scope: "", ordering: "-created_at" };

  async function pageTickets() {
    const u = me();
    shell("tickets", `
      <div class="row spread"><div><h1>Tickets</h1><p class="muted">${isStaff(u.role) ? "All tickets in your organization" : "Your tickets"}</p></div>
      <button class="primary" id="new">+ New ticket</button></div>
      <div class="card"><div class="row filters">
        <input id="q" placeholder="Search subject or description" value="${esc(listState.search)}" style="min-width:240px">
        <select id="st"><option value="">Any status</option>${["open", "in_progress", "waiting_customer", "resolved", "closed"].map((s) => `<option value="${s}" ${listState.status === s ? "selected" : ""}>${label(s)}</option>`).join("")}</select>
        <select id="pr"><option value="">Any priority</option>${["low", "medium", "high", "urgent"].map((s) => `<option value="${s}" ${listState.priority === s ? "selected" : ""}>${label(s)}</option>`).join("")}</select>
        ${isStaff(u.role) ? `<select id="sc"><option value="">All</option><option value="unassigned">Unassigned</option><option value="mine">Assigned to me</option><option value="breached">SLA breached</option></select>` : ""}
        <select id="od"><option value="-created_at">Newest first</option><option value="created_at">Oldest first</option><option value="first_response_due_at">First-response due soonest</option></select>
      </div></div>
      <div class="card" id="list"><div class="empty">Loading…</div></div>`);
    if ($("#sc")) $("#sc").value = listState.scope;
    $("#od").value = listState.ordering;
    $("#new").onclick = openNewTicket;
    let timer;
    const reload = () => { listState.page = 1; loadList(); };
    $("#q").oninput = (e) => { listState.search = e.target.value; clearTimeout(timer); timer = setTimeout(reload, 300); };
    $("#st").onchange = (e) => { listState.status = e.target.value; reload(); };
    $("#pr").onchange = (e) => { listState.priority = e.target.value; reload(); };
    if ($("#sc")) $("#sc").onchange = (e) => { listState.scope = e.target.value; reload(); };
    $("#od").onchange = (e) => { listState.ordering = e.target.value; reload(); };
    loadList();
  }

  async function loadList() {
    const p = new URLSearchParams({ page: listState.page, page_size: 15, ordering: listState.ordering });
    if (listState.search) p.set("search", listState.search);
    if (listState.status) p.set("status", listState.status);
    if (listState.priority) p.set("priority", listState.priority);
    if (listState.scope === "unassigned") p.set("unassigned", "true");
    if (listState.scope === "mine") p.set("assigned_to_me", "true");
    if (listState.scope === "breached") p.set("breached", "true");
    const box = $("#list");
    try {
      const data = await api(`/tickets/?${p}`);
      if (!box) return;
      if (!data.results.length) { box.innerHTML = `<div class="empty">No tickets match.</div>`; return; }
      const staff = isStaff(me().role);
      box.innerHTML = `<table><thead><tr><th>#</th><th>Subject</th><th>Status</th><th>Priority</th>${staff ? "<th>Requester</th>" : ""}<th>Assignee</th><th>First response</th><th>Created</th></tr></thead><tbody>
        ${data.results.map((t) => `<tr class="click" data-id="${t.id}"><td>${t.id}</td><td>${esc(t.subject)}</td><td>${statusBadge(t.status)}</td><td>${priorityBadge(t.priority)}</td>${staff ? `<td>${esc(t.requester.username)}</td>` : ""}<td>${t.assignee ? esc(t.assignee.username) : '<span class="muted">Unassigned</span>'}</td><td>${slaText(t)}</td><td class="small">${fmt(t.created_at)}</td></tr>`).join("")}</tbody></table>
        <div class="row spread" style="margin-top:12px"><span class="muted small">${data.count} ticket(s) · page ${listState.page}</span>
        <span class="row"><button id="prev" ${data.previous ? "" : "disabled"}>← Prev</button><button id="next" ${data.next ? "" : "disabled"}>Next →</button></span></div>`;
      box.querySelectorAll("tr.click").forEach((tr) => (tr.onclick = () => (location.hash = `#/tickets/${tr.dataset.id}`)));
      $("#prev").onclick = () => { listState.page--; loadList(); };
      $("#next").onclick = () => { listState.page++; loadList(); };
    } catch (err) { toast(err.message, true); }
  }

  function openNewTicket() {
    modal("New ticket", `
      <form id="nt"><label>Subject</label><input name="subject" minlength="5" maxlength="200" required>
      <label>Priority</label><select name="priority"><option>low</option><option selected>medium</option><option>high</option><option>urgent</option></select>
      <label>Description</label><textarea name="description" minlength="10" required></textarea>
      <p><button class="primary" type="submit">Create ticket</button></p></form>`, (back, close) => {
      $("#nt", back).onsubmit = async (e) => {
        e.preventDefault();
        try {
          const t = await api("/tickets/", { method: "POST", body: Object.fromEntries(new FormData(e.target)) });
          close(); toast("Ticket created"); location.hash = `#/tickets/${t.id}`;
        } catch (err) { toast(err.message, true); }
      };
    });
  }

  // ----------------------------------------------------------- ticket detail
  const TRANSITIONS = { open: ["in_progress", "waiting_customer", "resolved", "closed"], in_progress: ["open", "waiting_customer", "resolved"], waiting_customer: ["in_progress", "resolved"], resolved: ["open", "closed"], closed: [] };
  const CUSTOMER_OK = new Set(["open>closed", "resolved>closed", "resolved>open"]);
  const ACTION_LABEL = { in_progress: "Start work", waiting_customer: "Wait for customer", resolved: "Mark resolved", closed: "Close", open: "Move to Open" };
  let cur = null;   // state of the ticket on screen
  let ws = null;

  function closeWs() { if (ws) { ws.onclose = null; ws.close(); ws = null; } }

  async function loadTicket(id) {
    const staff = isStaff(me().role);
    const [ticket, comments, atts, events] = await Promise.all([
      api(`/tickets/${id}/`),
      api(`/tickets/${id}/comments/?page_size=100`),
      api(`/tickets/${id}/attachments/`),
      staff ? api(`/tickets/${id}/timeline/`) : Promise.resolve([]),
    ]);
    const previousStaff = cur && cur.id === id ? cur.staff : null;
    cur = { id, ticket, comments: comments.results, atts, events, staff: previousStaff || [] };
    if (!previousStaff && isManager(me().role)) {
      try {
        const users = await api("/users/?page_size=100&is_active=true");
        cur.staff = users.results.filter((x) => isStaff(x.role));
      } catch (e) { /* assignee list is optional */ }
    }
  }

  async function pageTicket(id) {
    const u = me();
    shell("tickets", `<p><a href="#/tickets">← All tickets</a></p>
      <div id="t-head"></div>
      <div class="grid g2"><div>
        <div class="card"><h3>Conversation <span id="live" class="live off">○ offline</span></h3><div id="t-comments"></div>
          <form id="cf"><label>Add a reply</label><textarea name="body" required></textarea>
          <div class="row spread" style="margin-top:8px">${isStaff(u.role) ? `<label style="margin:0"><input type="checkbox" name="is_internal" style="width:auto"> Internal note (staff only)</label>` : "<span></span>"}
          <button class="primary" type="submit">Send</button></div></form></div>
      </div><div id="t-side"></div></div>`);
    try { await loadTicket(id); } catch (err) { toast(err.message, true); location.hash = "#/tickets"; return; }
    paintTicket();
    $("#cf").onsubmit = async (e) => {
      e.preventDefault();
      const fd = new FormData(e.target);
      try {
        await api(`/tickets/${id}/comments/`, { method: "POST", body: { body: fd.get("body"), is_internal: fd.get("is_internal") === "on" } });
        e.target.reset(); await refreshTicket();
      } catch (err) { toast(err.message, true); }
    };
    openWs(id);
  }

  async function refreshTicket() {
    if (!cur) return;
    try { await loadTicket(cur.id); paintTicket(); } catch (err) { toast(err.message, true); }
  }

  function openWs(id) {
    closeWs();
    const proto = location.protocol === "https:" ? "wss" : "ws";
    ws = new WebSocket(`${proto}://${location.host}/ws/tickets/${id}/?token=${encodeURIComponent(getAccess())}`);
    ws.onopen = () => { const el = $("#live"); if (el) { el.textContent = "● live"; el.classList.remove("off"); } };
    ws.onclose = () => { const el = $("#live"); if (el) { el.textContent = "○ offline"; el.classList.add("off"); } };
    ws.onmessage = (ev) => {
      let msg; try { msg = JSON.parse(ev.data); } catch (e) { return; }
      if (cur && cur.id === id) {
        if (msg.event === "sla_breached") toast("SLA breached on this ticket", true);
        refreshTicket();
      }
    };
  }

  function paintTicket() {
    const { ticket: t, comments, atts, events } = cur;
    const u = me();
    const next = TRANSITIONS[t.status].filter((s) => isStaff(u.role) || CUSTOMER_OK.has(`${t.status}>${s}`));
    $("#t-head").innerHTML = `<div class="card"><div class="row spread"><div><h1>#${t.id} ${esc(t.subject)}</h1>
      <div class="row">${statusBadge(t.status)} ${priorityBadge(t.priority)}</div></div></div>
      <p style="white-space:pre-wrap;word-break:break-word">${esc(t.description)}</p></div>`;

    $("#t-comments").innerHTML = comments.length ? comments.map((c) => `
      <div class="comment ${c.is_internal ? "internal" : ""}"><div class="meta"><b>${esc(c.author.username)}</b> · ${fmt(c.created_at)}${c.is_internal ? " · INTERNAL NOTE" : ""}</div><div class="body">${esc(c.body)}</div></div>`).join("")
      : `<div class="empty">No replies yet.</div>`;

    const assignHtml = !isStaff(u.role) ? "" : isManager(u.role)
      ? `<label>Assign to</label><div class="row"><select id="asg"><option value="">Unassigned</option>${cur.staff.map((s) => `<option value="${s.id}" ${t.assignee && t.assignee.id === s.id ? "selected" : ""}>${esc(s.username)} (${esc(label(s.role))})</option>`).join("")}</select><button id="asgbtn">Save</button></div>`
      : (!t.assignee ? `<p><button id="claim">Assign to me</button></p>` : "");

    $("#t-side").innerHTML = `
      <div class="card"><h3>Details</h3><dl class="kv">
        <dt>Requester</dt><dd>${esc(t.requester.username)}</dd>
        <dt>Assignee</dt><dd>${t.assignee ? esc(t.assignee.username) : '<span class="muted">Unassigned</span>'}</dd>
        <dt>Created</dt><dd>${fmt(t.created_at)}</dd>
        <dt>First response</dt><dd>${slaText(t)}<div class="small muted">Due ${fmt(t.first_response_due_at)}</div></dd>
        <dt>Resolution</dt><dd>${t.resolution_breached ? '<span class="bad">Breached</span>' : t.resolved_at ? '<span class="ok">Resolved</span>' : "On track"}<div class="small muted">Due ${fmt(t.resolution_due_at)}</div></dd>
        <dt>Version</dt><dd class="muted">${t.version}</dd></dl>
        ${next.length ? `<h3 style="margin-top:14px">Actions</h3><div class="row">${next.map((s) => `<button data-st="${s}" class="${s === "resolved" ? "primary" : ""}">${t.status === "resolved" && s === "open" ? "Reopen" : ACTION_LABEL[s]}</button>`).join("")}</div>` : ""}
        ${assignHtml}</div>
      <div class="card"><h3>Attachments</h3>
        ${atts.length ? atts.map((a) => `<div class="row spread small"><a href="#" data-att="${a.id}" data-name="${esc(a.original_name)}">${esc(a.original_name)}</a><span class="muted">${Math.max(1, Math.round(a.size / 1024))} KB</span></div>`).join("") : '<div class="muted small">None</div>'}
        <input type="file" id="file" style="margin-top:10px"><div class="small muted">png, jpg, pdf, txt, csv, docx, xlsx · max 5 MB</div></div>
      ${isStaff(u.role) ? `<div class="card"><h3>Timeline</h3><ul class="tl">${events.map((e) => `<li><b>${esc(label(e.event_type))}</b>${e.from_value || e.to_value ? ` · ${esc(e.from_value)} → ${esc(e.to_value)}` : ""}<div class="muted">${esc(e.actor ? e.actor.username : "system")} · ${fmt(e.created_at)}</div></li>`).join("")}</ul></div>` : ""}`;

    $("#t-side").querySelectorAll("[data-st]").forEach((b) => (b.onclick = () => ticketAction("status", { status: b.dataset.st })));
    if ($("#asgbtn")) $("#asgbtn").onclick = () => ticketAction("assign", { assignee_id: $("#asg").value ? Number($("#asg").value) : null });
    if ($("#claim")) $("#claim").onclick = () => ticketAction("assign", { assignee_id: u.user_id });
    $("#file").onchange = uploadFile;
    $("#t-side").querySelectorAll("[data-att]").forEach((a) => (a.onclick = (e) => { e.preventDefault(); downloadAtt(a.dataset.att, a.dataset.name); }));
  }

  async function ticketAction(kind, payload) {
    try {
      await api(`/tickets/${cur.id}/${kind}/`, { method: "POST", body: { ...payload, version: cur.ticket.version } });
      toast("Updated");
    } catch (err) {
      toast(err.status === 409 ? "Someone else changed this ticket. Reloaded the latest version." : err.message, true);
    }
    refreshTicket();
  }

  async function uploadFile(e) {
    const file = e.target.files[0];
    if (!file) return;
    const form = new FormData();
    form.append("file", file);
    try { await api(`/tickets/${cur.id}/attachments/`, { method: "POST", form }); toast("File uploaded"); }
    catch (err) { toast(err.message, true); }
    refreshTicket();
  }

  async function downloadAtt(attId, name) {
    try {
      const res = await api(`/tickets/${cur.id}/attachments/${attId}/download/`, { raw: true });
      if (!res.ok) throw new ApiError(res.status, "Download failed");
      const url = URL.createObjectURL(await res.blob());
      const a = document.createElement("a");
      a.href = url; a.download = name; a.click();
      setTimeout(() => URL.revokeObjectURL(url), 5000);
    } catch (err) { toast(err.message, true); }
  }

  // --------------------------------------------------------------- dashboard
  async function pageDashboard() {
    shell("dashboard", `<h1>Dashboard</h1><p class="muted">Updated at most once a minute (cached on the server)</p><div id="dash"><div class="empty">Loading…</div></div>`);
    try {
      const d = await api("/reports/summary/");
      const bars = (obj) => { const max = Math.max(1, ...Object.values(obj)); return Object.entries(obj).map(([k, v]) => `<div class="barrow"><span>${esc(label(k))}</span><div><div class="bar" style="width:${(v / max) * 100}%"></div></div><b>${v}</b></div>`).join(""); };
      $("#dash").innerHTML = `
        <div class="grid g4">
          <div class="card"><h3>Total tickets</h3><div class="stat">${d.total_tickets}</div></div>
          <div class="card"><h3>First-response breaches</h3><div class="stat ${d.sla_first_response_breaches ? "bad" : ""}">${d.sla_first_response_breaches}</div></div>
          <div class="card"><h3>Resolution breaches</h3><div class="stat ${d.sla_resolution_breaches ? "bad" : ""}">${d.sla_resolution_breaches}</div></div>
          <div class="card"><h3>Avg first response</h3><div class="stat">${d.avg_first_response_minutes ?? "-"}<span class="small muted"> min</span></div></div>
        </div>
        <div class="grid g2" style="grid-template-columns:1fr 1fr">
          <div class="card"><h2>By status</h2>${bars(d.by_status)}</div>
          <div class="card"><h2>By priority</h2>${bars(d.by_priority)}</div>
        </div>
        <div class="card"><h2>Agent workload (open tickets)</h2>${d.agent_workload.length ? `<table><tbody>${d.agent_workload.map((w) => `<tr><td>${esc(w.agent)}</td><td><b>${w.open_tickets}</b></td></tr>`).join("")}</tbody></table>` : '<div class="muted">No assigned open tickets.</div>'}</div>`;
    } catch (err) { toast(err.message, true); }
  }

  // ------------------------------------------------------------ team & SLA
  async function pageTeam() {
    const admin = me().role === "org_admin";
    shell("team", `<h1>Team &amp; SLA</h1>
      <div class="card"><div class="row spread"><h2>Users</h2>${admin ? '<button class="primary" id="addu">+ Add user</button>' : ""}</div><div id="users"></div></div>
      <div class="card"><h2>SLA policies</h2><p class="muted small">Targets in minutes. Changes apply to new tickets only.${admin ? "" : " Only organization admins can edit."}</p><div id="sla"></div></div>`);
    const loadUsers = async () => {
      const data = await api("/users/?page_size=100");
      $("#users").innerHTML = `<table><thead><tr><th>Username</th><th>Email</th><th>Role</th><th>Active</th>${admin ? "<th></th>" : ""}</tr></thead><tbody>
        ${data.results.map((x) => `<tr><td>${esc(x.username)}</td><td>${esc(x.email)}</td><td>${admin && x.id !== me().user_id ? `<select data-role="${x.id}">${["org_admin", "manager", "agent", "customer"].map((r) => `<option value="${r}" ${x.role === r ? "selected" : ""}>${label(r)}</option>`).join("")}</select>` : esc(label(x.role))}</td><td>${x.is_active ? "Yes" : "No"}</td>${admin ? `<td>${x.id !== me().user_id ? `<button data-act="${x.id}" data-on="${x.is_active}" class="${x.is_active ? "danger" : ""}">${x.is_active ? "Deactivate" : "Activate"}</button>` : ""}</td>` : ""}</tr>`).join("")}</tbody></table>`;
      $("#users").querySelectorAll("[data-role]").forEach((s) => (s.onchange = async () => { try { await api(`/users/${s.dataset.role}/`, { method: "PATCH", body: { role: s.value } }); toast("Role updated"); } catch (err) { toast(err.message, true); loadUsers(); } }));
      $("#users").querySelectorAll("[data-act]").forEach((b) => (b.onclick = async () => { try { await api(`/users/${b.dataset.act}/`, { method: "PATCH", body: { is_active: b.dataset.on !== "true" } }); loadUsers(); } catch (err) { toast(err.message, true); } }));
    };
    const loadSla = async () => {
      const data = await api("/sla-policies/");
      const order = { urgent: 0, high: 1, medium: 2, low: 3 };
      $("#sla").innerHTML = `<table><thead><tr><th>Priority</th><th>First response (min)</th><th>Resolution (min)</th>${admin ? "<th></th>" : ""}</tr></thead><tbody>
        ${data.results.sort((a, b) => order[a.priority] - order[b.priority]).map((p) => `<tr><td>${priorityBadge(p.priority)}</td>
          <td>${admin ? `<input type="number" min="1" value="${p.first_response_minutes}" data-fr="${p.id}">` : p.first_response_minutes}</td>
          <td>${admin ? `<input type="number" min="1" value="${p.resolution_minutes}" data-rs="${p.id}">` : p.resolution_minutes}</td>
          ${admin ? `<td><button data-save="${p.id}">Save</button></td>` : ""}</tr>`).join("")}</tbody></table>`;
      $("#sla").querySelectorAll("[data-save]").forEach((b) => (b.onclick = async () => {
        const id = b.dataset.save;
        try { await api(`/sla-policies/${id}/`, { method: "PATCH", body: { first_response_minutes: Number($(`[data-fr="${id}"]`).value), resolution_minutes: Number($(`[data-rs="${id}"]`).value) } }); toast("SLA policy saved"); }
        catch (err) { toast(err.message, true); }
      }));
    };
    if ($("#addu")) $("#addu").onclick = () => modal("Add user", `
      <form id="au"><label>Username</label><input name="username" required><label>Email</label><input name="email" type="email" required>
      <label>Password</label><input name="password" type="password" required>
      <label>Role</label><select name="role"><option value="agent">Agent</option><option value="manager">Manager</option><option value="customer">Customer</option><option value="org_admin">Org admin</option></select>
      <p><button class="primary" type="submit">Create</button></p></form>`, (back, close) => {
      $("#au", back).onsubmit = async (e) => { e.preventDefault(); try { await api("/users/", { method: "POST", body: Object.fromEntries(new FormData(e.target)) }); close(); toast("User created"); loadUsers(); } catch (err) { toast(err.message, true); } };
    });
    try { await Promise.all([loadUsers(), loadSla()]); } catch (err) { toast(err.message, true); }
  }

  // ----------------------------------------------------------- notifications
  async function pageNotifications() {
    shell("notifications", `<div class="row spread"><h1>Notifications</h1><button id="all">Mark all read</button></div><div class="card" id="nl"><div class="empty">Loading…</div></div>`);
    const load = async () => {
      const data = await api("/notifications/?page_size=50");
      $("#nl").innerHTML = data.results.length ? `<table><tbody>${data.results.map((n) => `<tr class="click" data-n="${n.id}" data-t="${n.ticket_id || ""}"><td>${n.is_read ? "" : "● "}${esc(n.message)}</td><td class="small muted">${fmt(n.created_at)}</td></tr>`).join("")}</tbody></table>` : '<div class="empty">You are all caught up.</div>';
      $("#nl").querySelectorAll("tr.click").forEach((tr) => (tr.onclick = async () => {
        try { await api(`/notifications/${tr.dataset.n}/read/`, { method: "POST" }); } catch (e) { /* ignore */ }
        if (tr.dataset.t) location.hash = `#/tickets/${tr.dataset.t}`; else load();
      }));
    };
    $("#all").onclick = async () => { try { await api("/notifications/read-all/", { method: "POST" }); load(); updateBell(); } catch (err) { toast(err.message, true); } };
    try { await load(); } catch (err) { toast(err.message, true); }
  }

  // ------------------------------------------------- bell badge + polling
  let poll = null;
  async function updateBell() {
    const el = $("#bellcount");
    if (!el || !getAccess()) return;
    try {
      const d = await api("/notifications/?is_read=false&page_size=1");
      el.innerHTML = d.count ? `<span class="badge" style="background:var(--bad);color:#fff;border-color:var(--bad)">${d.count}</span>` : "";
    } catch (e) { /* ignore */ }
  }
  function startPolling() { if (!poll) poll = setInterval(updateBell, 30000); }
  function stopPolling() { clearInterval(poll); poll = null; }

  // ------------------------------------------------------------------ router
  async function route() {
    closeWs();
    cur = null;
    const hash = location.hash.replace(/^#\/?/, "");
    const [page, arg] = hash.split("/");
    if (!getAccess() && !getRefresh()) { if (page !== "login") { location.hash = "#/login"; return; } return pageLogin(); }
    if (page === "login" || !page) { location.hash = "#/tickets"; return; }
    startPolling();
    const u = me();
    if (!u) { logout(); return; }
    if ((page === "dashboard" || page === "team") && !isManager(u.role)) { location.hash = "#/tickets"; return; }
    if (page === "tickets" && arg) return pageTicket(Number(arg));
    if (page === "tickets") return pageTickets();
    if (page === "dashboard") return pageDashboard();
    if (page === "team") return pageTeam();
    if (page === "notifications") return pageNotifications();
    location.hash = "#/tickets";
  }

  window.addEventListener("hashchange", route);
  route();
})();
