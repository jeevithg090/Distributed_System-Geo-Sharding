/* GeoShardDB console. Plain ES2020, no build step; talks to the same-origin API. */
"use strict";

(() => {
  const REGIONS = ["us", "eu", "asia"];
  const ID_BLOCK = 1_000_000;
  const REFRESH_MS = 10_000;
  const VIEWS = ["overview", "users", "assistant", "scheduler", "paging", "coordination", "queue"];
  const TITLES = {
    overview: "Overview", users: "Users", assistant: "Assistant", scheduler: "Scheduler",
    paging: "Page replacement", coordination: "Locks & deadlocks", queue: "Work queue", "not-found": "Not found",
  };

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
  const fmt = new Intl.NumberFormat();

  /** Escape text for safe interpolation into HTML. */
  const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
  ));
  const regionTag = (r) => `<span class="region-tag" data-region="${esc(r)}">${esc(String(r).toUpperCase())}</span>`;
  const pill = (text, kind = "muted", plain = false) =>
    `<span class="pill pill-${kind}${plain ? " pill-plain" : ""}">${esc(text)}</span>`;

  // ------------------------------------------------------------ storage
  const store = {
    get(area, key) { try { return window[area].getItem(key); } catch (_) { return null; } },
    set(area, key, value) {
      try { value == null ? window[area].removeItem(key) : window[area].setItem(key, value); } catch (_) { /* ignore */ }
    },
  };

  // ---------------------------------------------------------------- API
  class ApiError extends Error {
    constructor(status, detail) {
      super(typeof detail === "string" ? detail : (detail && detail.error) || `HTTP ${status}`);
      this.status = status;
      this.detail = detail;
    }
  }

  async function api(path, { method = "GET", body, params, admin = false } = {}) {
    const url = new URL(path, window.location.origin);
    if (params) {
      for (const [k, v] of Object.entries(params)) if (v !== "" && v != null) url.searchParams.set(k, v);
    }
    const headers = { Accept: "application/json" };
    if (body !== undefined) headers["Content-Type"] = "application/json";
    const key = store.get("sessionStorage", "geoshard-admin-key");
    if (admin && key) headers["X-API-Key"] = key;
    let res;
    try {
      res = await fetch(url, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
    } catch (_) {
      throw new ApiError(0, "Can't reach the API. Check that the server is running.");
    }
    let data = null;
    try { data = await res.json(); } catch (_) { /* empty or non-JSON body */ }
    if (!res.ok) throw new ApiError(res.status, data ? data.detail : res.statusText);
    return data;
  }

  /** Turn an ApiError into a short, friendly sentence. */
  function describeError(err) {
    if (!(err instanceof ApiError)) return "Something went wrong. Please try again.";
    switch (err.status) {
      case 0: return err.message;
      case 401: return "This action needs the admin API key. Set it with the “Admin key” button in the header.";
      case 404: return typeof err.detail === "string" ? err.detail : "Not found.";
      case 422: {
        const first = Array.isArray(err.detail) ? err.detail[0] : null;
        return first ? `Invalid ${first.loc ? first.loc[first.loc.length - 1] : "input"}: ${first.msg}` : "Some input was invalid.";
      }
      case 429: return "The queue is full (back-pressure). Wait for consumers to drain it and try again.";
      case 503: return typeof err.detail === "string" ? err.detail : (err.detail && err.detail.error) || "Service unavailable.";
      default: return err.message || `Request failed (HTTP ${err.status}).`;
    }
  }

  const alertBox = (kind, title, text) =>
    `<div class="alert alert-${kind}" role="${kind === "error" ? "alert" : "status"}"><div><strong>${esc(title)}</strong>${esc(text)}</div></div>`;
  const errorBox = (err, title = "Request failed") => alertBox("error", title, describeError(err));
  const emptyBox = (title, text) => `<div class="empty"><h3>${esc(title)}</h3><p>${esc(text)}</p></div>`;

  function toast(message, kind = "info") {
    const el = document.createElement("div");
    el.className = `toast ${kind === "error" ? "error" : ""}`;
    el.textContent = message;
    $("#toasts").append(el);
    setTimeout(() => el.remove(), 4500);
  }

  /** Disable a button and show a spinner while ``fn`` runs. */
  async function busy(btn, fn) {
    if (!btn) return fn();
    if (btn.getAttribute("aria-busy") === "true") return;
    btn.setAttribute("aria-busy", "true");
    btn.disabled = true;
    try { return await fn(); } finally {
      btn.removeAttribute("aria-busy");
      btn.disabled = false;
    }
  }

  // ----------------------------------------------------------- validation
  function setFieldError(input, message) {
    const errorEl = document.getElementById(`${input.id}-error`);
    if (message) {
      input.setAttribute("aria-invalid", "true");
      if (errorEl) { errorEl.textContent = message; errorEl.hidden = false; }
    } else {
      input.removeAttribute("aria-invalid");
      if (errorEl) { errorEl.textContent = ""; errorEl.hidden = true; }
    }
    return !message;
  }

  function validateInt(input, { min, max, label, required = true }) {
    const raw = input.value.trim();
    if (raw === "") return setFieldError(input, required ? `${label} is required.` : "");
    const n = Number(raw);
    if (!Number.isInteger(n)) return setFieldError(input, `${label} must be a whole number.`);
    if (min != null && n < min) return setFieldError(input, `${label} must be at least ${fmt.format(min)}.`);
    if (max != null && n > max) return setFieldError(input, `${label} must be at most ${fmt.format(max)}.`);
    return setFieldError(input, "");
  }

  // Clear a field's error as soon as the user edits it.
  document.addEventListener("input", (e) => {
    if (e.target.matches("[aria-invalid='true']")) setFieldError(e.target, "");
  });

  // -------------------------------------------------------------- theme
  const themeBtn = $("#theme-btn");
  const isDark = () => {
    const t = document.documentElement.dataset.theme;
    return t ? t === "dark" : window.matchMedia("(prefers-color-scheme: dark)").matches;
  };
  const syncThemeLabel = () => themeBtn.setAttribute("aria-label", isDark() ? "Switch to light theme" : "Switch to dark theme");
  themeBtn.addEventListener("click", () => {
    const next = isDark() ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    store.set("localStorage", "geoshard-theme", next);
    syncThemeLabel();
  });
  syncThemeLabel();

  // ---------------------------------------------------------- admin key
  const dialog = $("#admin-dialog");
  const keyInput = $("#admin-key-input");
  const syncKeyDot = () => { $("#admin-key-dot").hidden = !store.get("sessionStorage", "geoshard-admin-key"); };
  $("#admin-key-btn").addEventListener("click", () => {
    keyInput.value = store.get("sessionStorage", "geoshard-admin-key") || "";
    dialog.showModal();
    keyInput.focus();
  });
  $("#admin-key-cancel").addEventListener("click", () => dialog.close());
  $("#admin-key-clear").addEventListener("click", () => { keyInput.value = ""; keyInput.focus(); });
  $("#admin-key-form").addEventListener("submit", () => {
    store.set("sessionStorage", "geoshard-admin-key", keyInput.value.trim() || null);
    syncKeyDot();
    toast(keyInput.value.trim() ? "Admin key saved for this tab." : "Admin key cleared.");
  });
  syncKeyDot();

  // ------------------------------------------------------------- router
  const loaders = {};
  let currentView = null;

  function route() {
    const name = (window.location.hash.replace(/^#\/?/, "") || "overview").split(/[/?]/)[0];
    const view = VIEWS.includes(name) ? name : "not-found";
    $$(".view").forEach((v) => { v.hidden = v.dataset.view !== view; });
    $$(".sidenav a").forEach((a) => {
      if (a.dataset.view === view) a.setAttribute("aria-current", "page");
      else a.removeAttribute("aria-current");
    });
    document.title = `${TITLES[view]} · GeoShardDB Console`;
    const changed = currentView !== null && currentView !== view;
    currentView = view;
    if (changed) $("#main").focus({ preventScroll: true });
    if (changed) window.scrollTo({ top: 0 });
    if (loaders[view]) loaders[view]();
  }
  window.addEventListener("hashchange", route);

  // ====================================================== global status
  async function refreshGlobalStatus(health) {
    const el = $("#global-status");
    const set = (kind, long, short) => {
      el.className = `pill pill-${kind}`;
      el.title = long;
      el.innerHTML = `<span class="status-long">${esc(long)}</span><span class="status-short">${esc(short)}</span>`;
    };
    try {
      const h = health || (await api("/health"));
      if (h.status === "ok") { set("ok", "All systems operational", "Healthy"); return; }
      const parts = REGIONS.filter((r) => h.shards[r].status !== "UP").map((r) => r.toUpperCase());
      if (h.redis !== "UP") parts.push("Redis");
      set("warn", `Degraded: ${parts.join(", ")} down`, "Degraded");
    } catch (_) {
      set("bad", "API unreachable", "Offline");
    }
  }

  // =========================================================== overview
  let overviewTimer = null;
  const breakerKind = (s) => (s === "CLOSED" ? "ok" : s === "HALF_OPEN" ? "warn" : "bad");

  function regionCard(r, shard, breaker) {
    const up = shard && shard.status === "UP";
    const start = REGIONS.indexOf(r) * ID_BLOCK + 1;
    return `<article class="card region-card" data-region="${r}" aria-label="${r.toUpperCase()} shard">
      <div class="card-head">
        <h3 class="card-title">${regionTag(r)} &nbsp;Shard</h3>
        ${pill(up ? "UP" : "DOWN", up ? "ok" : "bad")}
      </div>
      <dl class="kv">
        <dt>Circuit breaker</dt><dd>${pill(breaker.state.replace("_", " "), breakerKind(breaker.state), true)}</dd>
        <dt>Recent failures</dt><dd>${fmt.format(breaker.failures)}</dd>
        <dt>User ID block</dt><dd>${fmt.format(start)} – ${fmt.format(start + ID_BLOCK - 1)}</dd>
      </dl>
    </article>`;
  }

  function meter(value, max, label) {
    const pct = max ? Math.min(100, Math.round((value / max) * 100)) : 0;
    const cls = pct >= 100 ? "bad" : pct >= 75 ? "warn" : "";
    return `<div class="meter">
      <div class="meter-label"><span>${esc(label)}</span><span>${fmt.format(value)} / ${fmt.format(max)}</span></div>
      <div class="meter-track" role="progressbar" aria-label="${esc(label)}" aria-valuemin="0" aria-valuemax="${max}" aria-valuenow="${value}">
        <div class="meter-fill ${cls}" style="width:${pct}%"></div>
      </div>
    </div>`;
  }

  function serviceCards(health, cache, rag, queue) {
    const cards = [];
    const redisUp = health && health.redis === "UP";
    if (cache) {
      const s = cache.stats;
      cards.push(`<article class="card" aria-label="Redis cache">
        <div class="card-head"><h3 class="card-title">Redis cache</h3>${pill(redisUp ? "UP" : "DOWN", redisUp ? "ok" : "bad")}</div>
        <div class="stat-row"><span class="stat-value">${s.hit_rate_pct}%</span><span class="stat-label">hit rate</span></div>
        <dl class="kv">
          <dt>Hits / misses</dt><dd>${fmt.format(s.hits)} / ${fmt.format(s.misses)}</dd>
          <dt>Memory</dt><dd>${esc(cache.used_memory)}</dd>
          <dt>Version</dt><dd>${esc(cache.redis_version)}</dd>
        </dl>
      </article>`);
    } else cards.push(`<article class="card">${errorBox(new ApiError(503, "Redis is unavailable"), "Cache stats unavailable")}</article>`);

    if (rag) {
      cards.push(`<article class="card" aria-label="RAG index">
        <div class="card-head"><h3 class="card-title">RAG index</h3>${pill(rag.index_initialized ? "Ready" : "Not built", rag.index_initialized ? "ok" : "warn")}</div>
        <div class="stat-row"><span class="stat-value">${fmt.format(rag.document_count)}</span><span class="stat-label">documents</span></div>
        <dl class="kv">
          <dt>Embeddings</dt><dd>${esc(rag.index_embedding_backend || rag.configured_embedding_backend)}</dd>
          <dt>Vector search</dt><dd>${esc(rag.vector_search)}</dd>
        </dl>
      </article>`);
    }

    if (queue) {
      cards.push(`<article class="card" aria-label="Work queue">
        <div class="card-head"><h3 class="card-title">Work queue</h3>${pill(queue.backpressure_active ? "Back-pressure" : "Flowing", queue.backpressure_active ? "warn" : "ok")}</div>
        ${meter(queue.queue_depth, queue.max_capacity, "Depth")}
        <dl class="kv">
          <dt>Processed</dt><dd>${fmt.format(queue.processed_jobs_total)}</dd>
          <dt>Consumers (this replica)</dt><dd>${fmt.format(queue.active_consumers)}</dd>
        </dl>
      </article>`);
    } else cards.push(`<article class="card">${errorBox(new ApiError(503, "Redis is unavailable"), "Queue stats unavailable")}</article>`);
    return cards.join("");
  }

  async function loadOverview() {
    const regionsEl = $("#region-cards");
    const servicesEl = $("#service-cards");
    if (!regionsEl.children.length) {
      regionsEl.innerHTML = '<div class="skeleton"></div>'.repeat(3);
      servicesEl.innerHTML = '<div class="skeleton"></div>'.repeat(3);
    }
    const [health, breakers, cache, rag, queue] = await Promise.allSettled([
      api("/health"), api("/breaker-status"), api("/cache/stats"), api("/rag/status"), api("/queue/stats"),
    ]);
    const value = (r) => (r.status === "fulfilled" ? r.value : null);
    if (!value(health) || !value(breakers)) {
      $("#overview-alert").innerHTML = errorBox(health.reason || breakers.reason, "Couldn't load cluster health");
      regionsEl.innerHTML = emptyBox("No health data", "Retry once the API is reachable.");
      servicesEl.innerHTML = "";
      regionsEl.removeAttribute("aria-busy");
      servicesEl.removeAttribute("aria-busy");
      refreshGlobalStatus();
      return;
    }
    const h = value(health);
    const down = REGIONS.filter((r) => h.shards[r].status !== "UP");
    $("#overview-alert").innerHTML = h.status === "ok" ? "" : alertBox(
      "warn", "Cluster degraded. ",
      down.length
        ? `${down.map((r) => r.toUpperCase()).join(", ")} ${down.length > 1 ? "are" : "is"} down; reads fail over to healthy regions.`
        : "Redis is down; reads bypass the cache.",
    );
    regionsEl.innerHTML = REGIONS.map((r) => regionCard(r, h.shards[r], value(breakers)[r])).join("");
    servicesEl.innerHTML = serviceCards(h, value(cache), value(rag), value(queue));
    regionsEl.removeAttribute("aria-busy");
    servicesEl.removeAttribute("aria-busy");
    $("#overview-updated").textContent = `Last updated ${new Date().toLocaleTimeString()}`;
    refreshGlobalStatus(h);
  }

  loaders.overview = () => {
    loadOverview();
    clearInterval(overviewTimer);
    overviewTimer = setInterval(() => {
      if (currentView === "overview" && $("#auto-refresh").checked && !document.hidden) loadOverview();
    }, REFRESH_MS);
  };
  $("#overview-refresh").addEventListener("click", (e) => busy(e.currentTarget, loadOverview));

  // ============================================================== users
  const userForm = $("#user-form");
  const initials = (name) => String(name || "?").split(/[\s._-]+/).filter(Boolean).slice(0, 2).map((p) => p[0].toUpperCase()).join("") || "?";

  function renderUser(u) {
    const badges = [
      `Served from ${String(u.served_from).toUpperCase()}`,
    ];
    const failed = (u.failed_regions || []).map((f) => `${String(f.region).toUpperCase()} (breaker ${f.breaker_state}, ${f.failures} ${f.failures === 1 ? "failure" : "failures"})`);
    return `<div class="user-card">
      <div class="user-head">
        <div class="avatar" aria-hidden="true">${esc(initials(u.username))}</div>
        <div>
          <div class="user-name">${esc(u.username)}</div>
          <div class="meta">User #${fmt.format(u.user_id)} · ${esc(u.email)}</div>
        </div>
      </div>
      <div class="badges">
        ${pill(badges[0], "info", true)}
        ${u.served_from_cache ? pill("Cache hit", "ok") : pill("Cache miss · read from shard", "muted")}
        ${u.failover ? pill("Failover", "warn") : ""}
        ${pill(`${u.latency_ms} ms`, "muted", true)}
      </div>
      ${failed.length ? alertBox("warn", "Failed over. ", `Tried and skipped: ${failed.join("; ")}.`) : ""}
      <dl class="kv">
        <dt>Home region</dt><dd>${regionTag(u.region)}</dd>
        <dt>Subscription</dt><dd>${esc(u.subscription_type)}</dd>
        <dt>Department</dt><dd>${esc(u.department)}</dd>
        <dt>Status</dt><dd>${esc(u.status)}</dd>
        <dt>Logins</dt><dd>${fmt.format(u.login_count)}</dd>
        <dt>Last login</dt><dd>${esc(u.last_login || "—")}</dd>
      </dl>
    </div>`;
  }

  async function lookupUser(btn) {
    const idInput = $("#user-id");
    if (!validateInt(idInput, { min: 1, max: 3 * ID_BLOCK - 1, label: "User ID" })) { idInput.focus(); return; }
    const out = $("#user-result");
    const id = Number(idInput.value);
    const region = $("#user-region").value;
    await busy(btn, async () => {
      try {
        const user = await api(`/users/${id}`, { params: { region } });
        out.innerHTML = renderUser(user);
        if (user.failover) refreshGlobalStatus();
      } catch (err) {
        out.innerHTML = err.status === 404
          ? emptyBox("No user found", `There is no user #${fmt.format(id)}${region ? ` on the ${region.toUpperCase()} shard` : ""}. Seed data with python seed_data.py, or try one of the example IDs.`)
          : errorBox(err, "Lookup failed");
      }
    });
  }

  userForm.addEventListener("submit", (e) => { e.preventDefault(); lookupUser(e.submitter || $("button[type=submit]", userForm)); });
  $$("[data-user]").forEach((chip) => chip.addEventListener("click", () => {
    $("#user-id").value = chip.dataset.user;
    $("#user-region").value = "";
    lookupUser($("button[type=submit]", userForm));
  }));

  async function loadRecent(btn) {
    const out = $("#recent-result");
    if (!out.innerHTML) out.innerHTML = '<div class="skeleton"></div>';
    await busy(btn, async () => {
      try {
        const data = await api("/users/recent/all", { params: { limit: $("#recent-limit").value } });
        const ok = data.results.filter((r) => !r.error);
        const failed = data.results.filter((r) => r.error);
        const warn = failed.length ? alertBox("warn", "Partial result. ", `${failed.map((f) => f.region.toUpperCase()).join(", ")} didn't answer.`) : "";
        if (!ok.length) { out.innerHTML = warn + emptyBox("No users yet", "Seed the shards with python seed_data.py, then run the query again."); return; }
        out.innerHTML = `${warn}<p class="meta">${fmt.format(data.total_results)} rows from ${REGIONS.length - failed.length} shards in ${data.latency_ms} ms</p>
          <div class="table-wrap"><table>
            <caption class="sr-only">Newest users per shard</caption>
            <thead><tr><th scope="col">Region</th><th scope="col" class="num">User ID</th><th scope="col">Username</th></tr></thead>
            <tbody>${ok.map((r) => `<tr><td>${regionTag(r.region)}</td>
              <td class="num"><button type="button" class="row-link" data-open-user="${r.user_id}" aria-label="Look up user ${r.user_id}">${r.user_id}</button></td>
              <td>${esc(r.username)}</td></tr>`).join("")}</tbody>
          </table></div>`;
      } catch (err) {
        out.innerHTML = errorBox(err, "Fan-out query failed");
      }
    });
  }
  $("#recent-form").addEventListener("submit", (e) => { e.preventDefault(); loadRecent(e.submitter); });
  $("#recent-result").addEventListener("click", (e) => {
    const b = e.target.closest("[data-open-user]");
    if (!b) return;
    $("#user-id").value = b.dataset.openUser;
    $("#user-region").value = "";
    lookupUser($("button[type=submit]", userForm));
    $("#user-id").scrollIntoView({ behavior: "smooth", block: "center" });
  });
  let usersLoaded = false;
  loaders.users = () => { if (!usersLoaded) { usersLoaded = true; loadRecent(); } };

  // ========================================================== assistant
  const ragQ = $("#rag-question");
  const syncCount = () => { $("#rag-count").textContent = `${ragQ.value.length} / 500`; };
  ragQ.addEventListener("input", syncCount);

  async function loadRagStatus() {
    const el = $("#rag-status");
    try {
      const s = await api("/rag/status");
      el.innerHTML = s.index_initialized
        ? `<p class="meta">${pill("Index ready", "ok")} &nbsp;${fmt.format(s.document_count)} documents · ${esc(s.index_embedding_backend)} embeddings · ${esc(s.vector_search)} search</p>`
        : alertBox("warn", "The index isn't built yet. ", "Use “Rebuild index” (admin) or run python -m rag.indexer, then ask a question.");
    } catch (err) {
      el.innerHTML = errorBox(err, "Couldn't read index status");
    }
  }

  function renderAnswer(data) {
    const docs = data.retrieved_documents || [];
    const list = docs.length ? `<h3 class="card-title">Retrieved documents</h3><ol class="doc-list">${docs.map((d) => {
      const pct = Math.max(0, Math.min(100, Math.round(d.similarity_score * 100)));
      const tags = Object.entries(d.metadata || {}).map(([k, v]) => pill(`${k}: ${v}`, "muted", true)).join(" ");
      return `<li class="doc"><p>${esc(d.text)}</p>
        <div class="doc-score"><div class="meter-track" role="progressbar" aria-label="Similarity" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${pct}"><div class="meter-fill" style="width:${pct}%"></div></div><span>${d.similarity_score.toFixed(3)}</span></div>
        <div class="badges">${tags}</div></li>`;
    }).join("")}</ol>` : "";
    return `<div class="card"><h2 class="card-title">Answer</h2><p class="answer">${esc(data.answer)}</p>${list}</div>`;
  }

  async function ask(btn) {
    const q = ragQ.value.trim();
    if (!q) { setFieldError(ragQ, "Type a question first."); ragQ.focus(); return; }
    setFieldError(ragQ, "");
    const out = $("#rag-result");
    await busy(btn, async () => {
      out.innerHTML = '<div class="skeleton"></div>';
      try {
        out.innerHTML = renderAnswer(await api("/rag/ask", { method: "POST", body: { question: q, top_k: Number($("#rag-topk").value) } }));
      } catch (err) {
        out.innerHTML = errorBox(err, "The assistant couldn't answer");
      }
    });
  }
  $("#rag-form").addEventListener("submit", (e) => { e.preventDefault(); ask(e.submitter || $("button[type=submit]", e.currentTarget)); });
  $$("[data-q]").forEach((chip) => chip.addEventListener("click", () => {
    ragQ.value = chip.dataset.q; syncCount(); ask($("#rag-form button[type=submit]"));
  }));
  $("#rag-reindex").addEventListener("click", (e) => busy(e.currentTarget, async () => {
    try {
      const r = await api("/rag/index", { method: "POST", admin: true });
      toast(`Index rebuilt with ${r.document_count} documents.`);
      loadRagStatus();
    } catch (err) { toast(describeError(err), "error"); }
  }));
  loaders.assistant = loadRagStatus;

  // ========================================================== scheduler
  function gantt(timeline) {
    if (!timeline.length) return "";
    const end = Math.max(...timeline.map((s) => s.end));
    const segs = timeline.map((s) => {
      const left = (s.start / end) * 100;
      const width = Math.max(((s.end - s.start) / end) * 100, 0.4);
      const label = s.request_id.replace("REQ-", "");
      return `<div class="gantt-seg" data-region="${esc(s.region)}" style="left:${left}%;width:${width}%" title="${esc(s.request_id)} · ${esc(s.region.toUpperCase())} · t=${s.start}–${s.end}">${width > 3 ? esc(label) : ""}</div>`;
    }).join("");
    return `<div class="gantt">
      <div class="gantt-track" role="img" aria-label="Timeline of ${timeline.length} execution slices from t=0 to t=${end}">${segs}</div>
      <div class="gantt-axis" aria-hidden="true"><span>0</span><span>${Math.round(end / 2)}</span><span>${end}</span></div>
      <div class="legend">${REGIONS.map((r) => `<span><i style="background:var(--region-${r})"></i>${r.toUpperCase()}</span>`).join("")}<span>Labels are request numbers; hover a slice for details.</span></div>
    </div>`;
  }

  $("#sched-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const count = $("#sched-count");
    if (!validateInt(count, { min: 1, max: 100, label: "Requests" })) { count.focus(); return; }
    const out = $("#sched-result");
    await busy(e.submitter, async () => {
      try {
        const d = await api("/os/schedule", { params: { algorithm: $("#sched-alg").value, count: count.value, seed: $("#sched-seed").value.trim() } });
        out.innerHTML = `<div class="grid grid-3 stats">
            <div class="card"><span class="stat-label">Avg waiting time</span><span class="stat-value">${d.avg_waiting_time}</span></div>
            <div class="card"><span class="stat-label">Avg turnaround time</span><span class="stat-value">${d.avg_turnaround_time}</span></div>
            <div class="card"><span class="stat-label">Execution slices</span><span class="stat-value">${fmt.format(d.timeline.length)}</span></div>
          </div>
          <div class="card"><h2 class="card-title">Timeline · ${esc(d.algorithm.toUpperCase())}</h2>${gantt(d.timeline)}</div>
          <div class="card"><h2 class="card-title">Requests</h2><div class="table-wrap"><table>
            <thead><tr><th scope="col">Request</th><th scope="col">Region</th><th scope="col" class="num">Priority</th><th scope="col" class="num">Cost</th><th scope="col" class="num">Arrival</th><th scope="col" class="num">Start</th><th scope="col" class="num">Done</th><th scope="col" class="num">Waiting</th><th scope="col" class="num">Turnaround</th></tr></thead>
            <tbody>${d.requests.map((r) => `<tr><td class="mono">${esc(r.request_id)}</td><td>${regionTag(r.region)}</td><td class="num">${r.priority}</td><td class="num">${r.cost_units}</td><td class="num">${r.arrival_time}</td><td class="num">${r.start_time}</td><td class="num">${r.completion_time}</td><td class="num">${r.waiting_time}</td><td class="num">${r.turnaround_time}</td></tr>`).join("")}</tbody>
          </table></div></div>`;
      } catch (err) { out.innerHTML = errorBox(err, "Simulation failed"); }
    });
  });

  // ============================================================= paging
  const PAGE_ALGS = ["fifo", "lru", "lfu", "clock", "optimal"];
  function pagingParams() {
    const cap = $("#page-cap");
    const trace = $("#page-trace");
    let ok = validateInt(cap, { min: 1, max: 64, label: "Frames" });
    const cleaned = trace.value.replace(/\s+/g, "");
    if (!cleaned) ok = setFieldError(trace, "Enter at least one page number.") && ok;
    else if (!/^\d+(,\d+)*$/.test(cleaned)) ok = setFieldError(trace, "Use whole numbers separated by commas, e.g. 1,2,3,1.") && ok;
    else if (cleaned.length > 1000) ok = setFieldError(trace, "The trace is too long (1,000 characters max).") && ok;
    else setFieldError(trace, "");
    if (!ok) { $("[aria-invalid='true']", $("#page-form")).focus(); return null; }
    return { capacity: cap.value, trace: cleaned };
  }

  $("#page-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const params = pagingParams();
    if (!params) return;
    const out = $("#page-result");
    await busy(e.submitter, async () => {
      try {
        const d = await api("/os/page-replacement", { params: { ...params, algorithm: $("#page-alg").value } });
        out.innerHTML = `<div class="grid grid-4 stats">
            <div class="card"><span class="stat-label">Hits</span><span class="stat-value">${d.hits}</span></div>
            <div class="card"><span class="stat-label">Faults</span><span class="stat-value">${d.faults}</span></div>
            <div class="card"><span class="stat-label">Hit rate</span><span class="stat-value">${d.hit_rate_pct}%</span></div>
            <div class="card"><span class="stat-label">Evictions</span><span class="stat-value">${d.evictions_count}</span></div>
          </div>
          <div class="card"><h2 class="card-title">Step by step · ${esc(d.algorithm)} with ${d.capacity} frames</h2><div class="table-wrap"><table>
            <thead><tr><th scope="col" class="num">Step</th><th scope="col" class="num">Page</th><th scope="col">Result</th><th scope="col">Frames after</th><th scope="col">Evicted</th></tr></thead>
            <tbody>${d.history.map((h, i) => `<tr><td class="num">${i + 1}</td><td class="num mono">${esc(h.item)}</td>
              <td class="${h.status === "HIT" ? "status-hit" : "status-miss"}">${h.status === "HIT" ? "Hit" : "Miss"}</td>
              <td><span class="frames">${h.cache.map((p) => `<span class="frame${h.status !== "HIT" && p === h.item ? " new" : ""}">${esc(p)}</span>`).join("")}</span></td>
              <td class="mono">${h.evicted == null ? "—" : esc(h.evicted)}</td></tr>`).join("")}</tbody>
          </table></div></div>`;
      } catch (err) { out.innerHTML = errorBox(err, "Simulation failed"); }
    });
  });

  $("#page-compare").addEventListener("click", (e) => {
    const params = pagingParams();
    if (!params) return;
    const out = $("#page-compare-result");
    busy(e.currentTarget, async () => {
      try {
        const results = await Promise.all(PAGE_ALGS.map((algorithm) => api("/os/page-replacement", { params: { ...params, algorithm } })));
        const max = Math.max(...results.map((r) => r.faults), 1);
        const best = Math.min(...results.map((r) => r.faults));
        out.innerHTML = `<div class="card"><h2 class="card-title">Page faults by algorithm (${params.capacity} frames, lower is better)</h2>
          <div class="bars">${results.map((r) => `<div class="bar-row${r.faults === best ? " best" : ""}">
            <span>${esc(r.algorithm)}</span>
            <div class="meter-track" role="progressbar" aria-label="${esc(r.algorithm)} faults" aria-valuemin="0" aria-valuemax="${max}" aria-valuenow="${r.faults}"><div class="meter-fill" style="width:${(r.faults / max) * 100}%"></div></div>
            <strong>${r.faults} faults</strong></div>`).join("")}</div></div>`;
      } catch (err) { out.innerHTML = errorBox(err, "Comparison failed"); }
    });
  });

  // ======================================================= coordination
  const CLIENT_RE = /^[A-Za-z0-9_.:-]{1,64}$/;
  async function loadLocks() {
    const el = $("#lock-table");
    try {
      const d = await api("/os/locks");
      el.innerHTML = `<div class="table-wrap"><table>
        <thead><tr><th scope="col">Region</th><th scope="col">State</th><th scope="col">Owner</th></tr></thead>
        <tbody>${REGIONS.map((r) => {
          const l = d[`lock_mutex:${r}`];
          return `<tr><td>${regionTag(r)}</td><td>${l.locked ? pill("Locked", "warn") : pill("Free", "ok")}</td><td class="mono">${esc(l.owner || "—")}</td></tr>`;
        }).join("")}</tbody></table></div>`;
    } catch (err) { el.innerHTML = errorBox(err, "Couldn't read locks"); }
  }

  $("#lock-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const client = $("#lock-client");
    if (!CLIENT_RE.test(client.value.trim())) {
      setFieldError(client, "Use 1–64 letters, numbers or . _ : -");
      client.focus();
      return;
    }
    const action = e.submitter && e.submitter.value === "release" ? "release" : "acquire";
    const region = $("#lock-region").value;
    const msg = $("#lock-msg");
    await busy(e.submitter, async () => {
      try {
        const d = await api(`/os/locks/${action}`, { method: "POST", params: { region, client_id: client.value.trim() } });
        if (action === "acquire") {
          msg.innerHTML = d.acquired
            ? alertBox("ok", "Lock acquired. ", `${d.client_id} holds the ${region.toUpperCase()} mutex for up to 30 s.`)
            : alertBox("warn", "Lock is busy. ", `${d.owner || "Another client"} holds it; your request was recorded in the wait-for graph.`);
        } else {
          msg.innerHTML = d.released
            ? alertBox("ok", "Lock released. ", `${region.toUpperCase()} is free again.`)
            : alertBox("warn", "Nothing released. ", `${d.client_id} doesn't hold the ${region.toUpperCase()} mutex.`);
        }
      } catch (err) { msg.innerHTML = errorBox(err); }
      loadLocks();
    });
  });

  const heldSlots = [];
  async function loadSemaphore() {
    const region = $("#sem-region").value;
    try {
      const d = await api("/os/semaphore/status", { params: { region } });
      $("#sem-meter").innerHTML = meter(d.active_connections, d.max_limit, `${region.toUpperCase()} slots in use`);
    } catch (err) { $("#sem-meter").innerHTML = errorBox(err, "Couldn't read semaphore"); }
    const mine = heldSlots.filter((s) => s.region === region);
    $("#sem-held").innerHTML = mine.length ? `<div class="table-wrap"><table>
      <thead><tr><th scope="col">Your slots</th><th scope="col"><span class="sr-only">Actions</span></th></tr></thead>
      <tbody>${mine.map((s) => `<tr><td class="mono">${esc(s.holder)}</td><td class="num"><button type="button" class="btn btn-ghost btn-sm" data-release="${esc(s.holder)}">Release</button></td></tr>`).join("")}</tbody>
      </table></div>` : "";
  }
  $("#sem-region").addEventListener("change", () => { $("#sem-msg").innerHTML = ""; loadSemaphore(); });
  $("#sem-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const region = $("#sem-region").value;
    await busy(e.submitter, async () => {
      try {
        const d = await api("/os/semaphore/acquire", { method: "POST", params: { region } });
        if (d.acquired) {
          heldSlots.push({ region, holder: d.holder_id });
          $("#sem-msg").innerHTML = alertBox("ok", "Slot taken. ", "It expires after 30 s if not released.");
        } else {
          $("#sem-msg").innerHTML = alertBox("warn", "All slots busy. ", `The ${region.toUpperCase()} semaphore is at its limit of ${d.max_limit}.`);
        }
      } catch (err) { $("#sem-msg").innerHTML = errorBox(err); }
      loadSemaphore();
    });
  });
  $("#sem-held").addEventListener("click", async (e) => {
    const b = e.target.closest("[data-release]");
    if (!b) return;
    const region = $("#sem-region").value;
    await busy(b, async () => {
      try {
        const d = await api("/os/semaphore/release", { method: "POST", params: { region, holder_id: b.dataset.release } });
        const i = heldSlots.findIndex((s) => s.holder === b.dataset.release);
        if (i >= 0) heldSlots.splice(i, 1);
        $("#sem-msg").innerHTML = d.released ? alertBox("ok", "Slot released.", "") : alertBox("warn", "Slot had already expired.", "");
      } catch (err) { $("#sem-msg").innerHTML = errorBox(err); }
    });
    loadSemaphore();
  });

  function renderDeadlock(d) {
    const edges = Object.entries(d.graph || {});
    const graph = edges.length
      ? `<p class="meta">Wait-for edges: ${edges.map(([tx, holders]) => `${esc(tx)} → ${holders.map(esc).join(", ")}`).join(" · ")}</p>`
      : "";
    if (!d.deadlock_detected) {
      return alertBox("ok", "No deadlock. ", edges.length ? "There are waiters, but no cycle." : "The wait-for graph is empty.") + graph;
    }
    const cycle = [...d.cycle, d.cycle[0]];
    return `${alertBox("error", "Deadlock detected. ", `Abort ${d.resolution_victim} to break the cycle.`)}
      <div class="cycle" aria-label="Cycle: ${esc(cycle.join(" waits for "))}">${cycle.map((n, i) =>
        `${i ? '<span class="arrow" aria-hidden="true">→</span>' : ""}<span class="node${n === d.resolution_victim && i < cycle.length - 1 ? " victim" : ""}">${esc(n)}</span>`).join("")}</div>${graph}`;
  }
  async function checkDeadlock(btn) {
    const out = $("#dl-result");
    await busy(btn, async () => {
      try { out.innerHTML = renderDeadlock(await api("/os/deadlocks")); } catch (err) { out.innerHTML = errorBox(err, "Detection failed"); }
    });
  }
  $("#dl-check").addEventListener("click", (e) => checkDeadlock(e.currentTarget));
  $("#dl-simulate").addEventListener("click", (e) => busy(e.currentTarget, async () => {
    try {
      await api("/os/deadlocks/simulate", { method: "POST", admin: true });
      toast("Cycle injected into the wait-for graph.");
      await checkDeadlock($("#dl-check"));
      loadLocks();
    } catch (err) { $("#dl-result").innerHTML = errorBox(err, "Couldn't inject the cycle"); }
  }));
  loaders.coordination = () => { loadLocks(); loadSemaphore(); };

  // ============================================================== queue
  async function loadQueue() {
    const el = $("#queue-stats");
    try {
      const q = await api("/queue/stats");
      el.innerHTML = `${meter(q.queue_depth, q.max_capacity, "Jobs waiting")}
        <dl class="kv">
          <dt>State</dt><dd>${q.backpressure_active ? pill("Back-pressure", "warn") : pill("Flowing", "ok")}</dd>
          <dt>Processed (all replicas)</dt><dd>${fmt.format(q.processed_jobs_total)}</dd>
          <dt>Back-pressure events</dt><dd>${fmt.format(q.backpressure_events_total)}</dd>
          <dt>Consumers on this replica</dt><dd>${fmt.format(q.active_consumers)}</dd>
          <dt>Redis key</dt><dd class="mono">${esc(q.queue_name)}</dd>
        </dl>`;
    } catch (err) { el.innerHTML = errorBox(err, "Couldn't read queue stats"); }
  }

  $("#queue-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const action = $("#queue-action");
    const payloadEl = $("#queue-payload");
    let ok = true;
    if (!action.value.trim()) ok = setFieldError(action, "Give the job an action name.");
    let payload = {};
    const raw = payloadEl.value.trim();
    if (raw) {
      try {
        payload = JSON.parse(raw);
        if (payload === null || typeof payload !== "object" || Array.isArray(payload)) throw new Error("not an object");
        setFieldError(payloadEl, "");
      } catch (_) { ok = setFieldError(payloadEl, "Payload must be a JSON object, e.g. {\"user_id\": 1}.") && ok; }
    }
    if (!ok) { $("[aria-invalid='true']", e.currentTarget).focus(); return; }
    const burst = Number($("#queue-burst").value);
    const msg = $("#queue-msg");
    await busy(e.submitter, async () => {
      let accepted = 0;
      let rejected = 0;
      let lastId = "";
      let failure = null;
      for (let i = 0; i < burst; i += 1) {
        try {
          const r = await api("/queue/produce", { method: "POST", body: { action: action.value.trim(), payload } });
          accepted += 1; lastId = r.job_id;
        } catch (err) {
          if (err.status === 429) rejected += 1;
          else { failure = err; break; }
        }
      }
      if (failure) msg.innerHTML = errorBox(failure, "Couldn't enqueue");
      else if (rejected) msg.innerHTML = alertBox("warn", "Back-pressure. ", `${accepted} accepted, ${rejected} rejected with HTTP 429 because the queue was full.`);
      else msg.innerHTML = alertBox("ok", burst === 1 ? "Job queued. " : `${accepted} jobs queued. `, burst === 1 ? `ID ${lastId}.` : "Consumers will drain them shortly.");
      loadQueue();
    });
  });
  $("#queue-refresh").addEventListener("click", (e) => busy(e.currentTarget, loadQueue));
  $("#queue-consumers").addEventListener("click", (e) => busy(e.currentTarget, async () => {
    try {
      const r = await api("/queue/start-consumers", { method: "POST", params: { count: 2 }, admin: true });
      toast(r.message);
    } catch (err) { toast(describeError(err), "error"); }
    loadQueue();
  }));
  loaders.queue = loadQueue;

  // --------------------------------------------------------------- boot
  refreshGlobalStatus();
  // Keep the header badge current on every view (the overview refreshes it itself).
  setInterval(() => { if (currentView !== "overview" && !document.hidden) refreshGlobalStatus(); }, 15_000);
  route();
})();
