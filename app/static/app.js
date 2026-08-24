// Day Three — UI shell (T-22). Vanilla JS, no build step, no framework.
// Implements docs/DESIGN.md: top bar (seed/clock/advance/reset), worklist
// pane, case timeline pane, footer. Outbox/Quiet/Replay/reply box are T-23
// (the outbox pane below is a placeholder shell only).
//
// Reconciliation note: every route path lives in ROUTES below (PLAN §4.10).
// If app/orchestrator.py's response shapes change, this file and ROUTES are
// the only place to update.
(function () {
  "use strict";

  // ------------------------------------------------------------- routes --
  const ROUTES = {
    health: () => "/api/health",
    rules: () => "/api/rules",
    seed: () => "/api/seed",
    advance: () => "/api/advance",
    worklist: (seed) => `/api/worklist?seed=${encodeURIComponent(seed)}`,
    case: (seed, id) => `/api/case/${encodeURIComponent(id)}?seed=${encodeURIComponent(seed)}`,
    reset: () => "/api/reset",
  };

  // The orchestrator's cohort epoch (app/orchestrator.py DEFAULT_EPOCH).
  // There is no GET /clock route, so the client mirrors this constant to
  // label the clock right after Seed, before any Advance response arrives.
  const DEFAULT_EPOCH = "2026-08-24T00:00:00Z";
  const RUNGS = ["D1", "D3", "D7", "D14", "D42"];

  const SEVERITY = {
    URGENT_FACILITY_NOW: { label: "EMERGENCY", cls: "row-sev-emerg" },
    HUMAN_REVIEW_NOW: { label: "REVIEW NOW", cls: "row-sev-emerg" },
    HUMAN_REVIEW: { label: "REVIEW", cls: "row-sev-review" },
    SAME_DAY_VISIT: { label: "SAME-DAY", cls: "row-sev-urgent" },
    SILENCE: { label: "SILENT", cls: "row-sev-silent" },
    NEXT_CONTACT: { label: "ROUTINE", cls: "row-sev-routine" },
  };
  const DEFAULT_SEVERITY = { label: "ROUTINE", cls: "row-sev-routine" };

  // ------------------------------------------------------------ state --
  const state = {
    seed: 3,
    clockIso: null,
    clockLabel: null,
    clockIsOverride: false,
    selectedCaseId: null,
    worklist: null,
    caseDetail: null,
    modelOff: false,
  };

  // -------------------------------------------------------------- dom --
  const $ = (id) => document.getElementById(id);
  const els = {
    seedInput: $("seed-input"),
    seedBtn: $("seed-btn"),
    emptySeedBtn: $("empty-seed-btn"),
    resetBtn: $("reset-btn"),
    advanceGroup: $("advance-group"),
    clockDisplay: $("clock-display"),
    seedNote: $("seed-note"),
    clockNote: $("clock-note"),
    quotaStrip: $("quota-strip"),
    progressBar: $("progress-bar"),
    worklistBody: $("worklist-body"),
    worklistMeta: $("worklist-meta"),
    caseBody: $("case-body"),
    caseTitle: $("case-title"),
    caseMeta: $("case-meta"),
    footerText: $("footer-text"),
    tabbar: $("tabbar"),
    panes: Array.from(document.querySelectorAll(".pane")),
  };

  // ----------------------------------------------------------- helpers --
  function escapeHtml(value) {
    if (value === null || value === undefined) return "";
    return String(value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function formatDateTime(iso) {
    if (!iso) return "";
    const d = new Date(iso);
    if (isNaN(d.getTime())) return escapeHtml(iso);
    return d.toISOString().slice(0, 16).replace("T", " ");
  }

  function formatDate(iso) {
    if (!iso) return "";
    const d = new Date(iso);
    if (isNaN(d.getTime())) return escapeHtml(iso);
    return d.toISOString().slice(0, 10);
  }

  function formatTime(iso) {
    if (!iso) return "";
    const d = new Date(iso);
    if (isNaN(d.getTime())) return escapeHtml(iso);
    return d.toISOString().slice(11, 16);
  }

  function subjectForRuleId(ruleId) {
    if (!ruleId) return "";
    if (ruleId.startsWith("NB-")) return "newborn";
    if (ruleId.startsWith("M-")) return "mother";
    return "";
  }

  function looksLikePackRuleId(ruleId) {
    return typeof ruleId === "string" && /^(NB|M|SIL)-\d+$/.test(ruleId);
  }

  function pill(tag, opts) {
    opts = opts || {};
    const cls =
      { Observed: "pill-observed", Rule: "pill-rule", Simulated: "pill-simulated", Generated: "pill-generated" }[tag] ||
      "pill-observed";
    let label = escapeHtml(tag);
    let extraCls = "";
    if (tag === "Generated" && opts.degraded) {
      label = "Generated &middot; fallback";
      extraCls = " pill-fallback";
    }
    let suffix = "";
    if (opts.ruleId) {
      suffix += ` <span class="pill-rule-id">${escapeHtml(opts.ruleId)}</span>`;
    } else if (tag === "Generated" && opts.model && !opts.degraded) {
      suffix += ` <span class="pill-rule-id">${escapeHtml(opts.model)}</span>`;
    }
    return `<span class="pill ${cls}${extraCls}">${label}${suffix}</span>`;
  }

  function citationDetails(citation) {
    if (!citation || !citation.source_quote) return "";
    return (
      `<details class="event-citation"><summary>source</summary>` +
      `<p class="event-quote">${escapeHtml(citation.source_quote)}</p></details>`
    );
  }

  function setProgress(pane, loading) {
    if (loading) pane.classList.add("pane-loading");
    else pane.classList.remove("pane-loading");
  }

  let progressTimer = null;
  function beginGlobalProgress() {
    clearTimeout(progressTimer);
    progressTimer = setTimeout(() => {
      els.progressBar.hidden = false;
    }, 400);
  }
  function endGlobalProgress() {
    clearTimeout(progressTimer);
    els.progressBar.hidden = true;
  }

  function showQuotaStrip(text) {
    els.quotaStrip.hidden = false;
    els.quotaStrip.textContent = text;
  }
  function hideQuotaStrip() {
    els.quotaStrip.hidden = true;
  }

  // ------------------------------------------------------------- fetch --
  async function api(method, path, body) {
    beginGlobalProgress();
    try {
      const opts = { method, headers: {} };
      if (body !== undefined) {
        opts.headers["content-type"] = "application/json";
        opts.body = JSON.stringify(body);
      }
      const res = await fetch(path, opts);
      let data = null;
      try {
        data = await res.json();
      } catch (_e) {
        data = null;
      }
      if (!res.ok) {
        const detail = (data && (data.detail || data.error)) || res.statusText || "request failed";
        return { ok: false, status: res.status, detail, data };
      }
      return { ok: true, status: res.status, data };
    } catch (err) {
      return { ok: false, status: 0, detail: err && err.message ? err.message : "network error", data: null };
    } finally {
      endGlobalProgress();
    }
  }

  // -------------------------------------------------------- empty/error --
  function emptyWorklistHtml() {
    return (
      `<div class="empty-state"><p>No cohort yet. Seed ${escapeHtml(state.seed)} enrols 38 synthetic mothers.</p>` +
      `<button type="button" class="btn btn-primary" id="empty-seed-btn-2">Seed cohort</button></div>`
    );
  }

  function errorHtml(status, detail, retryId) {
    return (
      `<div class="error-box"><p><strong>HTTP ${escapeHtml(status || "0")}</strong> &middot; ${escapeHtml(detail || "request failed")}</p>` +
      `<button type="button" class="btn btn-ghost retry-btn" id="${retryId}">Retry</button></div>`
    );
  }

  function loadingHtml(label) {
    return `<div class="empty-state" aria-busy="true">${escapeHtml(label || "Loading…")}</div>`;
  }

  // ------------------------------------------------------------- render --
  function renderClock() {
    const label = state.clockLabel ? ` ${escapeHtml(state.clockLabel)}` : "";
    const value = state.clockIso ? formatDate(state.clockIso) : "—";
    const overrideNote = state.clockIsOverride ? ' <span class="pill pill-simulated">Simulated</span>' : "";
    els.clockDisplay.innerHTML = `<span class="clock-value mono">${value}${label}</span>${overrideNote}`;
  }

  function renderFooter(health) {
    if (!health) {
      els.footerText.textContent = "footer unavailable — /api/health failed";
      return;
    }
    const quiet = health.model_off ? "Quiet Mode — templates" : "Quiet Mode OFF";
    els.footerText.textContent = `model ${health.model || "unset"} · store ${health.store} · rules ${health.rules_version} · sha ${health.git_sha} · ${quiet}`;
  }

  function worklistCounts(rows) {
    const counts = { "row-sev-emerg": 0, "row-sev-urgent": 0, "row-sev-review": 0, "row-sev-silent": 0, "row-sev-routine": 0 };
    const names = { "row-sev-emerg": "emergency", "row-sev-urgent": "same-day", "row-sev-review": "review", "row-sev-silent": "silent", "row-sev-routine": "routine" };
    rows.forEach((row) => {
      const sev = SEVERITY[row.route] || DEFAULT_SEVERITY;
      counts[sev.cls] = (counts[sev.cls] || 0) + 1;
    });
    return Object.keys(names)
      .filter((cls) => counts[cls] > 0)
      .map((cls) => `${counts[cls]} ${names[cls]}`)
      .join(" · ");
  }

  function ruleLineHtml(row) {
    if (row.fired && row.fired.length) {
      const f = row.fired[0];
      return (
        `<div class="row-rule-line">${pill("Rule", { ruleId: f.rule_id })} ${escapeHtml(f.source_id || "")}` +
        citationDetails(f) +
        `</div>`
      );
    }
    if (row.route === "HUMAN_REVIEW") {
      const reason = (row.flags || []).find((f) => f !== "asha_visit_task") || "no reader available — nurse reads it";
      return `<div class="row-rule-line">no rule fired · ${escapeHtml(reason)}</div>`;
    }
    if (row.route === "SILENCE") {
      const hasAsha = (row.flags || []).includes("asha_visit_task");
      return `<div class="row-rule-line">no reply since rung ${escapeHtml(row.rung)}${hasAsha ? " · ASHA task" : ""}</div>`;
    }
    return "";
  }

  function actionsLineHtml(row) {
    const parts = [];
    if (row.open_slot) parts.push(`slot ${formatTime(row.open_slot)}`);
    if (row.next_due) parts.push(`next contact ${formatDate(row.next_due)}`);
    if (!parts.length) return "";
    return `<div class="row-actions-line">${escapeHtml(parts.join(" · "))}</div>`;
  }

  function worklistRowHtml(row) {
    const sev = SEVERITY[row.route] || DEFAULT_SEVERITY;
    const subject = subjectForRuleId(row.fired && row.fired[0] && row.fired[0].rule_id);
    const current = row.case_id === state.selectedCaseId;
    return (
      `<li><button type="button" class="worklist-row ${sev.cls}" data-case-id="${escapeHtml(row.case_id)}" ` +
      `${current ? 'aria-current="true"' : ""}>` +
      `<span class="bar" aria-hidden="true"></span>` +
      `<span class="row-content">` +
      `<span class="row-label">${sev.label}</span> <span class="row-name">${escapeHtml(row.mother.display_name)}${subject ? " · " + subject : ""} · ${escapeHtml(row.rung)}</span>` +
      ruleLineHtml(row) +
      actionsLineHtml(row) +
      `</span></button></li>`
    );
  }

  function renderWorklist() {
    const rows = state.worklist;
    if (rows === null) {
      els.worklistBody.innerHTML = loadingHtml("Loading worklist…");
      els.worklistMeta.textContent = "";
      return;
    }
    if (rows.error) {
      els.worklistBody.innerHTML = errorHtml(rows.status, rows.detail, "worklist-retry");
      const retry = $("worklist-retry");
      if (retry) retry.addEventListener("click", () => loadWorklist());
      els.worklistMeta.textContent = "";
      return;
    }
    if (!rows.length) {
      els.worklistBody.innerHTML = emptyWorklistHtml();
      const btn = $("empty-seed-btn-2");
      if (btn) btn.addEventListener("click", doSeed);
      els.worklistMeta.textContent = "";
      return;
    }
    els.worklistMeta.textContent = `${rows.length} · ${state.clockLabel || ""}`;
    els.worklistBody.innerHTML = `<ul class="worklist-list" aria-label="Morning worklist">${rows.map(worklistRowHtml).join("")}</ul>`;
    Array.from(els.worklistBody.querySelectorAll(".worklist-row")).forEach((btn) => {
      btn.addEventListener("click", () => selectCase(btn.getAttribute("data-case-id")));
    });
  }

  function eventBodyHtml(entry) {
    const p = entry.payload || {};
    switch (entry.type) {
      case "ENROLLED":
        return `enrolled · rung ${escapeHtml(p.rung || "")}`;
      case "CONTACT_DUE":
        return `rung ${escapeHtml(p.rung || "")} due`;
      case "REPLY_RECEIVED":
        if (p.text) return `<span lang="hi">&ldquo;${escapeHtml(p.text)}&rdquo;</span>`;
        return escapeHtml(p.summary || "keypad reply");
      case "FORM_READ":
      case "READER_FORM": {
        const signs = Object.entries(p.signs || {}).filter(([, v]) => v === true || v === "unknown");
        if (!signs.length) return "no signs reported";
        return signs.map(([k, v]) => `${escapeHtml(k)}: ${v === true ? "true" : "unknown"}`).join(", ");
      }
      case "VERDICT": {
        const fired = p.fired || [];
        const head = `<strong>${escapeHtml(p.route || "")}</strong>`;
        if (!fired.length) return head;
        return (
          head +
          fired
            .map(
              (f) =>
                `<div class="row-rule-line">${pill("Rule", { ruleId: f.rule_id })} ${escapeHtml(f.source_id || "")}${citationDetails(f)}</div>`
            )
            .join("")
        );
      }
      case "SLOT_BOOKED":
        return `slot ${formatTime(p.slot_iso)}`;
      case "NURSE_PAGED":
        return `priority ${escapeHtml(p.priority || "")}`;
      case "NURSE_FLAGGED":
      case "HUMAN_REVIEW":
        return escapeHtml(p.reason || "");
      case "CONTACT_RESCHEDULED":
        return `rung ${escapeHtml(p.rung || "")} due ${formatDate(p.due)}`;
      case "RETRY_SCHEDULED":
        return `retry due ${formatTime(p.due)}`;
      case "ASHA_VISIT_TASK":
        return `ASHA visit task due ${formatDate(p.due)}`;
      case "MESSAGE_QUEUED": {
        const text = p.text ? `<span lang="${p.lang === "hi" ? "hi" : "en"}">&ldquo;${escapeHtml(p.text)}&rdquo;</span>` : "";
        return `${escapeHtml(p.lang || "")} ${text}`;
      }
      default:
        return escapeHtml(JSON.stringify(p)).slice(0, 200);
    }
  }

  function timelineEntryHtml(entry) {
    // agent/quiet.py sets degraded=True on every template by design (not a
    // failure); only a Generated-tagged degraded message is a real fallback
    // (DESIGN.md §5: "Generated ... degraded:true -> fallback").
    const degraded = entry.type === "MESSAGE_QUEUED" && entry.tag === "Generated" && entry.payload && entry.payload.degraded;
    const rowCls = degraded ? "timeline-row event-fallback" : "timeline-row";
    let citationLine = "";
    if (entry.citation) {
      citationLine = `<div class="event-citation-line">${escapeHtml(entry.rule_id || "")} · ${escapeHtml(entry.citation.source_id || "")}${citationDetails(entry.citation)}</div>`;
    } else if (entry.rule_id && entry.tag === "Rule" && looksLikePackRuleId(entry.rule_id)) {
      citationLine = `<div class="missing-citation">citation missing</div>`;
    } else if (entry.rule_id) {
      citationLine = `<div class="row-rule-line mono">${escapeHtml(entry.rule_id)}</div>`;
    }
    const fallbackNote = degraded ? `<div class="missing-citation">model unavailable — template used; decision unchanged</div>` : "";
    return (
      `<li class="${rowCls}"><span class="ts mono">${escapeHtml(formatDateTime(entry.at))}</span>` +
      `<span class="event-body"><span class="event-type">${escapeHtml(entry.type)}</span> ${pill(entry.tag, { degraded, ruleId: entry.type === "VERDICT" ? null : null })}` +
      `<span class="event-text">${eventBodyHtml(entry)}</span>${citationLine}${fallbackNote}</span></li>`
    );
  }

  function renderCase() {
    const detail = state.caseDetail;
    if (detail === null) {
      els.caseTitle.textContent = "Case";
      els.caseMeta.textContent = "";
      els.caseBody.innerHTML = state.selectedCaseId
        ? loadingHtml("Loading case…")
        : `<div class="empty-state"><p>Select a mother.</p></div>`;
      return;
    }
    if (detail.error) {
      els.caseTitle.textContent = "Case";
      els.caseBody.innerHTML = errorHtml(detail.status, detail.detail, "case-retry");
      const retry = $("case-retry");
      if (retry) retry.addEventListener("click", () => loadCase(state.selectedCaseId));
      return;
    }
    els.caseTitle.textContent = detail.mother.display_name;
    els.caseMeta.textContent = `${detail.mother.variant} · ${detail.mother.phone} · rung ${detail.rung}`;
    const timeline = (detail.timeline || []).map(timelineEntryHtml).join("");
    els.caseBody.innerHTML = `<ol class="timeline" aria-label="Case timeline">${timeline || "<li>No events yet.</li>"}</ol>`;
  }

  // -------------------------------------------------------------- data --
  async function loadHealth() {
    const res = await api("GET", ROUTES.health());
    if (res.ok) {
      renderFooter(res.data);
      state.modelOff = !!res.data.model_off;
      if (state.modelOff) showQuotaStrip("Model off (server) — templates in use; decisions unchanged.");
      else hideQuotaStrip();
    } else {
      renderFooter(null);
    }
  }

  async function loadWorklist() {
    state.worklist = null;
    renderWorklist();
    setProgress(document.getElementById("pane-worklist"), true);
    const res = await api("GET", ROUTES.worklist(state.seed));
    setProgress(document.getElementById("pane-worklist"), false);
    if (!res.ok) {
      state.worklist = { error: true, status: res.status, detail: res.detail };
    } else {
      state.worklist = res.data.worklist || [];
      // fallback signal only readable from a case's MESSAGE_QUEUED — loadCase().
    }
    renderWorklist();
  }

  async function loadCase(caseId) {
    state.selectedCaseId = caseId;
    state.caseDetail = null;
    renderCase();
    renderWorklist();
    setProgress(document.getElementById("pane-case"), true);
    const res = await api("GET", ROUTES.case(state.seed, caseId));
    setProgress(document.getElementById("pane-case"), false);
    if (!res.ok) {
      state.caseDetail = { error: true, status: res.status, detail: res.detail };
    } else {
      state.caseDetail = res.data;
      // see timelineEntryHtml's comment: only Generated+degraded is a real fallback.
      const anyDegraded = (res.data.timeline || []).some(
        (e) => e.type === "MESSAGE_QUEUED" && e.tag === "Generated" && e.payload && e.payload.degraded
      );
      if (anyDegraded) showQuotaStrip("Model unavailable (quota) — templates in use; decisions unchanged.");
      else if (!state.modelOff) hideQuotaStrip();
    }
    renderCase();
    switchToPane("pane-case");
  }

  function selectCase(caseId) {
    loadCase(caseId);
  }

  async function doSeed() {
    const raw = els.seedInput.value.trim();
    let seedVal = parseInt(raw, 10);
    if (isNaN(seedVal) || String(seedVal) !== raw) {
      seedVal = 3;
      els.seedInput.value = "3";
      els.seedNote.hidden = false;
      els.seedNote.textContent = "seed must be a whole number — using 3";
    } else {
      els.seedNote.hidden = true;
    }
    state.seed = seedVal;
    state.selectedCaseId = null;
    state.caseDetail = null;
    els.seedBtn.disabled = true;
    if (els.emptySeedBtn) els.emptySeedBtn.disabled = true;
    els.worklistBody.innerHTML = loadingHtml("Seeding cohort…");
    const res = await api("POST", ROUTES.seed(), { seed: state.seed, n: 38 });
    els.seedBtn.disabled = false;
    if (els.emptySeedBtn) els.emptySeedBtn.disabled = false;
    if (!res.ok) {
      state.worklist = { error: true, status: res.status, detail: res.detail };
      renderWorklist();
      return;
    }
    state.clockIso = DEFAULT_EPOCH;
    state.clockLabel = "D1";
    state.clockIsOverride = false;
    renderClock();
    state.worklist = res.data.worklist || [];
    renderWorklist();
    renderCase();
    updateUrl();
  }

  async function doAdvance(to) {
    const btns = Array.from(els.advanceGroup.querySelectorAll(".advance-btn"));
    btns.forEach((b) => (b.disabled = true));
    els.advanceGroup.setAttribute("aria-busy", "true");
    const original = btns.map((b) => b.textContent);
    btns.forEach((b) => (b.textContent = "Advancing…"));
    setProgress(document.getElementById("pane-worklist"), true);
    const res = await api("POST", ROUTES.advance(), { seed: state.seed, to });
    setProgress(document.getElementById("pane-worklist"), false);
    btns.forEach((b, i) => (b.textContent = original[i]));
    btns.forEach((b) => (b.disabled = false));
    els.advanceGroup.removeAttribute("aria-busy");
    if (!res.ok) {
      state.worklist = { error: true, status: res.status, detail: res.detail };
      renderWorklist();
      return;
    }
    if (!state.clockIsOverride) {
      state.clockIso = res.data.run_summary.clock;
      state.clockLabel = RUNGS.includes(to) ? to : "custom";
      renderClock();
    }
    await loadWorklist();
    if (state.selectedCaseId) await loadCase(state.selectedCaseId);
    updateUrl();
  }

  async function doReset() {
    if (!window.confirm(`Reset seed ${state.seed}? This clears the synthetic cohort.`)) return;
    const res = await api("POST", ROUTES.reset(), { seed: state.seed });
    if (!res.ok) return;
    state.worklist = [];
    state.caseDetail = null;
    state.selectedCaseId = null;
    state.clockIso = null;
    state.clockLabel = null;
    state.clockIsOverride = false;
    renderClock();
    renderWorklist();
    renderCase();
  }

  // ---------------------------------------------------------------- url --
  function updateUrl() {
    const params = new URLSearchParams(window.location.search);
    params.set("seed", String(state.seed));
    const next = `${window.location.pathname}?${params.toString()}`;
    window.history.replaceState(null, "", next);
  }

  function readUrlParams() {
    const params = new URLSearchParams(window.location.search);
    const seedRaw = params.get("seed");
    if (seedRaw !== null) {
      const parsed = parseInt(seedRaw, 10);
      if (!isNaN(parsed) && String(parsed) === seedRaw.trim()) {
        state.seed = parsed;
        els.seedInput.value = String(parsed);
      } else {
        els.seedNote.hidden = false;
        els.seedNote.textContent = "seed must be a whole number — using 3";
      }
    }
    const clockRaw = params.get("clock");
    if (clockRaw) {
      const d = new Date(clockRaw);
      if (!isNaN(d.getTime())) {
        state.clockIso = clockRaw;
        state.clockLabel = null;
        state.clockIsOverride = true;
      } else {
        els.clockNote.hidden = false;
        els.clockNote.textContent = "clock ignored: not ISO";
      }
    }
  }

  // ----------------------------------------------------- phone tab bar --
  function switchToPane(paneId) {
    els.panes.forEach((p) => p.classList.toggle("active", p.id === paneId));
    Array.from(els.tabbar.querySelectorAll(".tab-btn")).forEach((btn) => {
      const on = btn.getAttribute("data-pane") === paneId;
      btn.setAttribute("aria-current", on ? "true" : "false");
    });
  }

  // -------------------------------------------------------------- init --
  function wireEvents() {
    els.seedBtn.addEventListener("click", doSeed);
    if (els.emptySeedBtn) els.emptySeedBtn.addEventListener("click", doSeed);
    els.resetBtn.addEventListener("click", doReset);
    Array.from(els.advanceGroup.querySelectorAll(".advance-btn")).forEach((btn) => {
      btn.addEventListener("click", () => doAdvance(btn.getAttribute("data-to")));
    });
    Array.from(els.tabbar.querySelectorAll(".tab-btn")).forEach((btn) => {
      btn.addEventListener("click", () => switchToPane(btn.getAttribute("data-pane")));
    });
  }

  async function init() {
    readUrlParams();
    renderClock();
    wireEvents();
    switchToPane("pane-worklist");
    await loadHealth();
    await loadWorklist();
    if (state.worklist && state.worklist.length && !state.clockLabel) {
      // Cohort already existed server-side (shared URL) — we cannot know the
      // exact rung label without a clock route, so leave the date blank
      // until the next Advance; the worklist itself still renders fully.
      state.clockIso = state.clockIso || DEFAULT_EPOCH;
      renderClock();
    }
  }

  document.addEventListener("DOMContentLoaded", init);
})();
