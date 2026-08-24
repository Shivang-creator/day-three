// Day Three — UI shell (T-22 + T-23). Vanilla JS, no build step, no framework.
// Implements docs/DESIGN.md: top bar, worklist, case timeline, outbox, Quiet
// toggle, Replay panel, reply box. Kept dense (few blank lines, single-line
// template literals) to hold the 40KB total payload budget across the three
// static files — see .crew/outbox/T-23.md for the size accounting.
//
// Every route lives in ROUTES (PLAN §4.10); this file is the one place to
// update if app/orchestrator.py's response shapes change. `replay` is coded
// against tools/quiet_diff.py::run_diff()'s own return shape
// (decision_changes/message_changes as arrays of {case_id|key, off, on}),
// per this task's context pack naming GET /api/replay?seed=&clock= — the
// route may not exist yet (T-19 in flight); a 404 renders the honest
// "not available" state in replayPanelHtml so the panel works the moment
// the route lands, with no code change needed here.
(function () {
  "use strict";

  const ROUTES = {
    health: () => "/api/health",
    rules: () => "/api/rules",
    seed: () => "/api/seed",
    advance: () => "/api/advance",
    worklist: (seed) => `/api/worklist?seed=${encodeURIComponent(seed)}`,
    case: (seed, id) => `/api/case/${encodeURIComponent(id)}?seed=${encodeURIComponent(seed)}`,
    reset: () => "/api/reset",
    outbox: (seed) => `/api/outbox?seed=${encodeURIComponent(seed)}`,
    reply: (seed) => `/api/reply?seed=${encodeURIComponent(seed)}`,
    quiet: () => "/api/quiet",
    replay: (seed) => `/api/replay?seed=${encodeURIComponent(seed)}`,
  };
  const ESCALATION_INTENTS = new Set(["come_now", "same_day"]);
  // orchestrator.py's DEFAULT_EPOCH — mirrored here because there's no GET
  // /clock route to recover it from on a shared-URL page load.
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

  const state = {
    seed: 3, clockIso: null, clockLabel: null, clockIsOverride: false,
    selectedCaseId: null, worklist: null, caseDetail: null, modelOff: false, health: null,
    pack: null, // GET /api/rules, cached once — keypad labels + digits
    outbox: null,
    quietOn: false, // per-seed toggle, client-tracked (no GET to read it back)
    lastReply: null, // {caseId, html} inline result under the reply box
    replay: null, // {loading,elapsed} | {notAvailable,status} | {error,status,detail} | {data}
  };

  const $ = (id) => document.getElementById(id);
  const els = {
    seedInput: $("seed-input"), seedBtn: $("seed-btn"), emptySeedBtn: $("empty-seed-btn"),
    resetBtn: $("reset-btn"), advanceGroup: $("advance-group"), clockDisplay: $("clock-display"),
    seedNote: $("seed-note"), clockNote: $("clock-note"), quotaStrip: $("quota-strip"),
    progressBar: $("progress-bar"), worklistBody: $("worklist-body"), worklistMeta: $("worklist-meta"),
    caseBody: $("case-body"), caseTitle: $("case-title"), caseMeta: $("case-meta"),
    footerText: $("footer-text"), tabbar: $("tabbar"), panes: Array.from(document.querySelectorAll(".pane")),
    outboxBody: $("outbox-body"), quietBtn: $("quiet-toggle"), quietBadge: $("quiet-badge"),
    topbarControls: $("topbar-controls"), scrollHint: $("topbar-scroll-hint"),
  };

  // ------------------------------------------------------------- helpers --
  function escapeHtml(value) {
    if (value === null || value === undefined) return "";
    return String(value).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }
  function formatDateTime(iso) {
    if (!iso) return "";
    const d = new Date(iso);
    return isNaN(d.getTime()) ? escapeHtml(iso) : d.toISOString().slice(0, 16).replace("T", " ");
  }
  function formatDate(iso) {
    if (!iso) return "";
    const d = new Date(iso);
    return isNaN(d.getTime()) ? escapeHtml(iso) : d.toISOString().slice(0, 10);
  }
  function formatTime(iso) {
    if (!iso) return "";
    const d = new Date(iso);
    return isNaN(d.getTime()) ? escapeHtml(iso) : d.toISOString().slice(11, 16);
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
    const cls = { Observed: "pill-observed", Rule: "pill-rule", Simulated: "pill-simulated", Generated: "pill-generated" }[tag] || "pill-observed";
    let label = escapeHtml(tag), extraCls = "", suffix = "";
    if (tag === "Generated" && opts.degraded) { label = "Generated &middot; fallback"; extraCls = " pill-fallback"; }
    if (opts.ruleId) suffix = ` <span class="pill-rule-id">${escapeHtml(opts.ruleId)}</span>`;
    else if (tag === "Generated" && opts.model && !opts.degraded) suffix = ` <span class="pill-rule-id">${escapeHtml(opts.model)}</span>`;
    return `<span class="pill ${cls}${extraCls}">${label}${suffix}</span>`;
  }
  function citationDetails(citation) {
    if (!citation || !citation.source_quote) return "";
    return `<details class="event-citation"><summary>source</summary><p class="event-quote">${escapeHtml(citation.source_quote)}</p></details>`;
  }
  // J-04 (.crew/deliverables/JUDGE-REPORT.md): app/orchestrator.py's generic
  // HUMAN_REVIEW action carries `reason: "unresolved red sign(s): <every
  // unresolved sign_id, comma-joined>"` (core/routing.py) — for an
  // all-unknown SymptomForm that is ~28 raw SCREAMING_SNAKE_CASE tokens,
  // printed verbatim it dominated the worklist row (and consumed the whole
  // 390px mobile viewport). Pure function so it's independently testable
  // (see tests/test_regress_j04.py, which runs this via node).
  function unresolvedSignsSummary(reason) {
    const m = /^unresolved red sign\(s\): ?(.*)$/.exec(reason || "");
    if (!m) return null;
    const signs = m[1].split(",").map((s) => s.trim()).filter(Boolean);
    if (!signs.length) return { count: 0, label: "unresolved signs — open case for detail", signs: [] };
    const label = `${signs.length} unresolved sign${signs.length === 1 ? "" : "s"}`;
    return { count: signs.length, label, signs };
  }
  function setProgress(pane, loading) {
    pane.classList.toggle("pane-loading", loading);
  }
  let progressTimer = null;
  function beginGlobalProgress() {
    clearTimeout(progressTimer);
    progressTimer = setTimeout(() => (els.progressBar.hidden = false), 400);
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

  // --------------------------------------------------------------- fetch --
  async function api(method, path, body) {
    beginGlobalProgress();
    try {
      const opts = { method, headers: {} };
      if (body !== undefined) { opts.headers["content-type"] = "application/json"; opts.body = JSON.stringify(body); }
      const res = await fetch(path, opts);
      let data = null;
      try { data = await res.json(); } catch (_e) { data = null; }
      if (!res.ok) return { ok: false, status: res.status, detail: (data && (data.detail || data.error)) || res.statusText || "request failed", data };
      return { ok: true, status: res.status, data };
    } catch (err) {
      return { ok: false, status: 0, detail: err && err.message ? err.message : "network error", data: null };
    } finally {
      endGlobalProgress();
    }
  }

  // --------------------------------------------------------- empty/error --
  function emptyWorklistHtml() {
    return `<div class="empty-state"><p>No cohort yet. Seed ${escapeHtml(state.seed)} enrols 38 synthetic mothers.</p><button type="button" class="btn btn-primary" id="empty-seed-btn-2">Seed cohort</button></div>`;
  }
  function errorHtml(status, detail, retryId) {
    return `<div class="error-box"><p><strong>HTTP ${escapeHtml(status || "0")}</strong> &middot; ${escapeHtml(detail || "request failed")}</p><button type="button" class="btn btn-ghost retry-btn" id="${retryId}">Retry</button></div>`;
  }
  function loadingHtml(label) {
    return `<div class="empty-state" aria-busy="true">${escapeHtml(label || "Loading…")}</div>`;
  }

  // -------------------------------------------------------------- render --
  function renderClock() {
    const label = state.clockLabel ? ` ${escapeHtml(state.clockLabel)}` : "";
    const value = state.clockIso ? formatDate(state.clockIso) : "—";
    const overrideNote = state.clockIsOverride ? ' <span class="pill pill-simulated">Simulated</span>' : "";
    els.clockDisplay.innerHTML = `<span class="clock-value mono">${value}${label}</span>${overrideNote}`;
  }
  function renderFooter() {
    const health = state.health;
    if (!health) { els.footerText.textContent = "footer unavailable — /api/health failed"; return; }
    // R-02: keyed on `model_enabled` (the SAME predicate the server gates
    // every model call on), not the raw `model_off` env flag — a blank
    // GEMINI_API_KEY or a live quota exhaustion both mean "templates in
    // use" even though MODEL_OFF itself is "0".
    const templatesOnly = state.modelOff || state.quietOn;
    const quiet = templatesOnly ? "Quiet Mode — templates" : "Quiet Mode OFF";
    els.footerText.textContent = `model ${health.model || "unset"} · store ${health.store} · rules ${health.rules_version} · sha ${health.git_sha} · ${quiet}`;
  }
  function renderQuietSwitch() {
    const on = state.modelOff || state.quietOn;
    els.quietBtn.setAttribute("aria-checked", on ? "true" : "false");
    els.quietBtn.classList.toggle("on", on);
    els.quietBtn.disabled = state.modelOff;
    els.quietBtn.title = state.modelOff ? "model unavailable (server: off, no key, or quota) — see the strip above" : "";
    els.quietBadge.hidden = !on;
  }

  function ruleLineHtml(row) {
    if (row.fired && row.fired.length) {
      const f = row.fired[0];
      return `<div class="row-rule-line">${pill("Rule", { ruleId: f.rule_id })} ${escapeHtml(f.source_id || "")}${citationDetails(f)}</div>`;
    }
    if (row.route === "HUMAN_REVIEW") {
      const reason = (row.flags || []).find((f) => f !== "asha_visit_task") || "no reader available — nurse reads it";
      const unresolved = unresolvedSignsSummary(reason);
      if (unresolved) {
        return `<div class="row-rule-line">no rule fired · <details class="unresolved-signs"><summary>${escapeHtml(unresolved.label)}</summary>${escapeHtml(unresolved.signs.join(", ")) || "open case for detail"}</details></div>`;
      }
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
    return parts.length ? `<div class="row-actions-line">${escapeHtml(parts.join(" · "))}</div>` : "";
  }
  function worklistRowHtml(row) {
    const sev = SEVERITY[row.route] || DEFAULT_SEVERITY;
    const subject = subjectForRuleId(row.fired && row.fired[0] && row.fired[0].rule_id);
    const current = row.case_id === state.selectedCaseId;
    return (
      `<li><button type="button" class="worklist-row ${sev.cls}" data-case-id="${escapeHtml(row.case_id)}" ${current ? 'aria-current="true"' : ""}>` +
      `<span class="bar" aria-hidden="true"></span><span class="row-content">` +
      `<span class="row-label">${sev.label}</span> <span class="row-name">${escapeHtml(row.mother.display_name)}${subject ? " · " + subject : ""} · ${escapeHtml(row.rung)}</span>` +
      ruleLineHtml(row) + actionsLineHtml(row) + `</span></button></li>`
    );
  }
  function renderWorklist() {
    const rows = state.worklist;
    if (rows === null) { els.worklistBody.innerHTML = loadingHtml("Loading worklist…"); els.worklistMeta.textContent = ""; return; }
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
    Array.from(els.worklistBody.querySelectorAll(".worklist-row")).forEach((btn) => btn.addEventListener("click", () => selectCase(btn.getAttribute("data-case-id"))));
  }

  function eventBodyHtml(entry) {
    const p = entry.payload || {};
    switch (entry.type) {
      case "ENROLLED": return `enrolled · rung ${escapeHtml(p.rung || "")}`;
      case "CONTACT_DUE": return `rung ${escapeHtml(p.rung || "")} due`;
      case "REPLY_RECEIVED":
        return p.text ? `<span lang="hi">&ldquo;${escapeHtml(p.text)}&rdquo;</span>` : escapeHtml(p.summary || "keypad reply");
      case "FORM_READ":
      case "READER_FORM": {
        const signs = Object.entries(p.signs || {}).filter(([, v]) => v === true || v === "unknown");
        if (!signs.length) return "no signs reported";
        if (signs.every(([, v]) => v === "unknown")) return "no reader available — nurse reads it";
        return signs.map(([k, v]) => `${escapeHtml(k)}: ${v === true ? "true" : "unknown"}`).join(", ");
      }
      case "VERDICT": {
        const fired = p.fired || [];
        const head = `<strong>${escapeHtml(p.route || "")}</strong>`;
        if (!fired.length) return head;
        return head + fired.map((f) => `<div class="row-rule-line">${pill("Rule", { ruleId: f.rule_id })} ${escapeHtml(f.source_id || "")}${citationDetails(f)}</div>`).join("");
      }
      case "SLOT_BOOKED": return `slot ${formatTime(p.slot_iso)}`;
      case "NURSE_PAGED": return `priority ${escapeHtml(p.priority || "")}`;
      case "NURSE_FLAGGED":
      case "HUMAN_REVIEW": return escapeHtml(p.reason || "");
      case "CONTACT_RESCHEDULED": return `rung ${escapeHtml(p.rung || "")} due ${formatDate(p.due)}`;
      case "RETRY_SCHEDULED": return `retry due ${formatTime(p.due)}`;
      case "ASHA_VISIT_TASK": return `ASHA visit task due ${formatDate(p.due)}`;
      case "MESSAGE_QUEUED": {
        const text = p.text ? `<span lang="${p.lang === "hi" ? "hi" : "en"}">&ldquo;${escapeHtml(p.text)}&rdquo;</span>` : "";
        return `${escapeHtml(p.lang || "")} ${text}`;
      }
      default: return escapeHtml(JSON.stringify(p)).slice(0, 200);
    }
  }
  function timelineEntryHtml(entry) {
    // agent/quiet.py sets degraded=True on every template by design (not a
    // failure); only a Generated-tagged degraded message is a real fallback
    // (DESIGN.md §5: "Generated ... degraded:true -> fallback").
    const degraded = entry.type === "MESSAGE_QUEUED" && entry.tag === "Generated" && entry.payload && entry.payload.degraded;
    const rowCls = degraded ? "timeline-row event-fallback" : "timeline-row";
    let citationLine = "";
    if (entry.citation) citationLine = `<div class="event-citation-line">${escapeHtml(entry.rule_id || "")} · ${escapeHtml(entry.citation.source_id || "")}${citationDetails(entry.citation)}</div>`;
    else if (entry.rule_id && entry.tag === "Rule" && looksLikePackRuleId(entry.rule_id)) citationLine = `<div class="missing-citation">citation missing</div>`;
    else if (entry.rule_id) citationLine = `<div class="row-rule-line mono">${escapeHtml(entry.rule_id)}</div>`;
    const fallbackNote = degraded ? `<div class="missing-citation">model unavailable — template used; decision unchanged</div>` : "";
    return (
      `<li class="${rowCls}"><span class="ts mono">${escapeHtml(formatDateTime(entry.at))}</span>` +
      `<span class="event-body"><span class="event-type">${escapeHtml(entry.type)}</span> ${pill(entry.tag, { degraded })}` +
      `<span class="event-text">${eventBodyHtml(entry)}</span>${citationLine}${fallbackNote}</span></li>`
    );
  }
  function renderCase() {
    const detail = state.caseDetail;
    if (detail === null) {
      els.caseTitle.textContent = "Case";
      els.caseMeta.textContent = "";
      els.caseBody.innerHTML = state.selectedCaseId ? loadingHtml("Loading case…") : `<div class="empty-state"><p>Select a mother.</p></div>`;
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

  // ----------------------------------------------------- outbox pane (T-23) --
  function outboxRowHtml(row, nameByCase) {
    const channel = ESCALATION_INTENTS.has(row.intent) ? "WhatsApp" : row.intent === "retry" ? "Pager" : "SMS";
    const name = nameByCase[row.case_id] || row.case_id;
    const text = row.text ? `<span lang="${row.lang === "hi" ? "hi" : "en"}">&ldquo;${escapeHtml(row.text)}&rdquo;</span>` : "";
    return (
      `<li class="outbox-row"><div class="outbox-head">${escapeHtml(channel)} &rarr; ${escapeHtml(name)} <span class="mono">${escapeHtml(row.lang || "")}</span> ${pill(row.text_tag, { degraded: row.degraded, model: row.model })}</div>` +
      `<div class="outbox-text">${text}</div></li>`
    );
  }
  function outboxListHtml() {
    if (state.outbox === null) return loadingHtml("Loading outbox…");
    if (state.outbox.error) return errorHtml(state.outbox.status, state.outbox.detail, "outbox-retry");
    if (!state.outbox.length) return `<div class="empty-state"><p>Nothing sent yet &mdash; nothing is ever delivered.</p></div>`;
    const nameByCase = {};
    (state.worklist && state.worklist.length ? state.worklist : []).forEach((r) => (nameByCase[r.case_id] = r.mother.display_name));
    const rows = state.outbox.slice().reverse().map((r) => outboxRowHtml(r, nameByCase)).join("");
    return `<ul class="outbox-list">${rows}</ul>`;
  }
  function keypadGroupHtml(subject, label) {
    const signs = (state.pack ? state.pack.signs : []).filter((s) => s.subject === subject);
    if (!signs.length) return "";
    const rows = signs
      .map((s) => `<label class="keypad-item"><input type="checkbox" data-sign="${escapeHtml(s.sign_id)}"> <span class="mono">${escapeHtml(s.keypad)}</span> ${escapeHtml(s.label_en)} &mdash; <span lang="hi">${escapeHtml(s.label_hi)}</span></label>`)
      .join("");
    return `<fieldset class="keypad-group"><legend>${escapeHtml(label)}</legend>${rows}</fieldset>`;
  }
  function replyResultHtml(data, sent) {
    const v = data.verdict;
    const sev = SEVERITY[v.route] || DEFAULT_SEVERITY;
    const observed = sent.text
      ? `<p>You typed: <span lang="hi">&ldquo;${escapeHtml(sent.text)}&rdquo;</span> ${pill("Observed")}</p>`
      : `<p>Keypad sent ${pill("Observed")}</p>`;
    const fired = (v.fired || []).map((f) => `<div class="row-rule-line">${pill("Rule", { ruleId: f.rule_id })} ${escapeHtml(f.source_id || "")}${citationDetails(f)}</div>`).join("");
    // MESSAGE_MOTHER's real tag (Rule vs Generated) depends on server-side
    // budget/model state this call can't know in advance — shown honestly
    // in the case timeline refetch, not guessed here.
    const actions = (data.actions || [])
      .map((a) => (a.type === "MESSAGE_MOTHER" ? `<div class="row-rule-line">message queued &middot; see timeline for tag</div>` : `<div class="row-rule-line">${pill(a.type === "ASHA_VISIT_TASK" ? "Simulated" : "Rule", { ruleId: a.rule_id })} ${escapeHtml(a.type)}</div>`))
      .join("");
    return `<div class="reply-result">${observed}<p class="reply-route ${sev.cls}">${pill(v.tag || "Rule")} ${escapeHtml(sev.label)}</p>${fired || `<div class="row-rule-line">no rule fired</div>`}${actions || `<div class="row-rule-line">no actions</div>`}</div>`;
  }
  function replyBoxHtml() {
    if (!state.selectedCaseId) return `<div class="empty-state"><p>Select a mother to reply as her.</p></div>`;
    const result = state.lastReply && state.lastReply.caseId === state.selectedCaseId ? state.lastReply.html : "";
    const keypad = state.pack ? keypadGroupHtml("newborn", "Newborn") + keypadGroupHtml("mother", "Mother") : loadingHtml("Loading keypad…");
    return (
      `<div class="reply-box"><h3>Reply as this mother <span class="pill pill-simulated">Simulated channel</span></h3>${keypad}` +
      `<button type="button" class="btn btn-primary" id="send-keypad-btn">Send keypad</button>` +
      `<label class="reply-text-label">free text<textarea id="reply-text" maxlength="280" placeholder="type what the mother might say, any language"></textarea></label>` +
      `<button type="button" class="btn btn-ghost" id="send-text-btn" disabled>Send text</button><div id="reply-result">${result}</div></div>`
    );
  }
  function replayCount(d, key) {
    const v = d[key];
    if (Array.isArray(v)) return v.length;
    return typeof v === "number" ? v : 0;
  }
  function replayDiffRows(d) {
    const rows = [];
    if (Array.isArray(d.diff)) {
      d.diff.forEach((r) => rows.push([r.case || r.case_id || "", r.field || "decision", r.model_on ?? r.on ?? "", r.model_off ?? r.off ?? ""]));
    } else {
      (d.decision_changes || []).forEach((r) => rows.push([r.case_id || "", "decision", JSON.stringify(r.on), JSON.stringify(r.off)]));
      (d.message_changes || []).forEach((r) => rows.push([r.key || "", "message", String(r.on), String(r.off)]));
    }
    if (!rows.length) return "";
    const body = rows.map((r) => `<tr>${r.map((c) => `<td>${escapeHtml(String(c)).slice(0, 200)}</td>`).join("")}</tr>`).join("");
    return `<div class="table-wrap"><table><thead><tr><th>case</th><th>field</th><th>model on</th><th>model off</th></tr></thead><tbody>${body}</tbody></table></div>`;
  }
  function replayPanelHtml() {
    const r = state.replay;
    if (r && r.loading) return `<div class="replay-panel"><p aria-busy="true">Replaying model-on and model-off&hellip; ${r.elapsed}s</p></div>`;
    if (r && r.notAvailable)
      return `<div class="replay-panel"><button type="button" class="btn btn-ghost" id="replay-btn">Replay this seed</button><p class="missing-citation">Replay not available yet &mdash; HTTP ${escapeHtml(r.status)} from /api/replay. This panel starts working the moment the route lands.</p></div>`;
    if (r && r.error) return `<div class="replay-panel">${errorHtml(r.status, r.detail, "replay-retry")}</div>`;
    if (r && r.data) {
      const d = r.data;
      const dCount = replayCount(d, "decision_changes"), mCount = replayCount(d, "message_changes");
      const cls = dCount > 0 ? "replay-number mono replay-bad" : "replay-number mono";
      const warn = dCount > 0 ? `<p class="missing-citation">decisions differ — this is the bug the design forbids</p>` : "";
      return `<div class="replay-panel"><button type="button" class="btn btn-ghost" id="replay-btn">Replay again</button><p class="${cls}">${dCount} decision changes &middot; ${mCount} message changes</p>${warn}${replayDiffRows(d)}</div>`;
    }
    return `<div class="replay-panel"><button type="button" class="btn btn-ghost" id="replay-btn">Replay this seed</button></div>`;
  }
  function renderOutboxPane() {
    els.outboxBody.innerHTML = outboxListHtml() + `<div class="divider"></div>` + replyBoxHtml() + `<div class="divider"></div>` + replayPanelHtml();
    const retry = $("outbox-retry");
    if (retry) retry.addEventListener("click", loadOutbox);
    const skb = $("send-keypad-btn");
    if (skb) skb.addEventListener("click", sendKeypad);
    const ta = $("reply-text"), stb = $("send-text-btn");
    if (ta && stb) ta.addEventListener("input", () => (stb.disabled = !ta.value.trim()));
    if (stb) stb.addEventListener("click", sendText);
    const rretry = $("reply-retry");
    if (rretry) rretry.addEventListener("click", () => submitReply(state.lastReplyBody || {}));
    const rbtn = $("replay-btn");
    if (rbtn) rbtn.addEventListener("click", doReplay);
    const rrretry = $("replay-retry");
    if (rrretry) rrretry.addEventListener("click", doReplay);
  }
  async function submitReply(body) {
    if (!state.selectedCaseId) return;
    state.lastReplyBody = body;
    const res = await api("POST", ROUTES.reply(state.seed), Object.assign({ case_id: state.selectedCaseId }, body));
    if (!res.ok) {
      state.lastReply = { caseId: state.selectedCaseId, html: errorHtml(res.status, res.detail, "reply-retry") };
      renderOutboxPane();
      return;
    }
    state.lastReply = { caseId: state.selectedCaseId, html: replyResultHtml(res.data, body) };
    await loadWorklist();
    await loadOutbox();
    await loadCase(state.selectedCaseId, false);
  }
  function sendKeypad() {
    const checks = Array.from(els.outboxBody.querySelectorAll(".keypad-item input[type=checkbox]"));
    const keypad = {};
    checks.forEach((c) => (keypad[c.getAttribute("data-sign")] = c.checked));
    submitReply({ keypad });
  }
  function sendText() {
    const ta = $("reply-text");
    const text = ta ? ta.value.trim() : "";
    if (text) submitReply({ text });
  }
  let replayTimer = null;
  async function doReplay() {
    clearInterval(replayTimer);
    state.replay = { loading: true, elapsed: 0 };
    renderOutboxPane();
    replayTimer = setInterval(() => {
      if (state.replay && state.replay.loading) { state.replay.elapsed += 1; renderOutboxPane(); }
    }, 1000);
    const res = await api("GET", ROUTES.replay(state.seed));
    clearInterval(replayTimer);
    state.replay = !res.ok
      ? res.status === 404
        ? { notAvailable: true, status: res.status }
        : { error: true, status: res.status, detail: res.detail }
      : { data: res.data };
    renderOutboxPane();
  }

  // ---------------------------------------------------------------- data --
  async function loadHealth() {
    const res = await api("GET", ROUTES.health());
    state.health = res.ok ? res.data : null;
    if (res.ok) {
      // R-02: `model_enabled` is the real predicate (MODEL_OFF env AND a
      // configured key), so `state.modelOff` ("templates only, server
      // side") now also catches a blank GEMINI_API_KEY — previously only
      // the literal MODEL_OFF=1 case showed this strip, so "leave the key
      // empty" (README) silently ran on templates with no on-screen signal.
      state.modelOff = res.data.model_enabled === false;
      if (res.data.quota_exhausted) {
        showQuotaStrip(`Model off (server) — quota exhausted, retry in ~${Math.ceil(res.data.quota_retry_after_s || 0)}s; templates in use; decisions unchanged.`);
      } else if (state.modelOff) {
        showQuotaStrip("Model off (server) — templates in use; decisions unchanged.");
      } else {
        hideQuotaStrip();
      }
    }
    renderFooter();
    renderQuietSwitch();
  }
  async function loadRules() {
    const res = await api("GET", ROUTES.rules());
    if (res.ok) state.pack = res.data;
    if (state.selectedCaseId) renderOutboxPane(); // keypad becomes available mid-session
  }
  async function loadWorklist() {
    state.worklist = null;
    renderWorklist();
    setProgress(document.getElementById("pane-worklist"), true);
    const res = await api("GET", ROUTES.worklist(state.seed));
    setProgress(document.getElementById("pane-worklist"), false);
    state.worklist = res.ok ? res.data.worklist || [] : { error: true, status: res.status, detail: res.detail };
    renderWorklist();
  }
  async function loadOutbox() {
    state.outbox = null;
    renderOutboxPane();
    const res = await api("GET", ROUTES.outbox(state.seed));
    state.outbox = res.ok ? res.data.outbox || [] : { error: true, status: res.status, detail: res.detail };
    renderOutboxPane();
  }
  async function loadCase(caseId, switchPane) {
    if (switchPane === undefined) switchPane = true;
    state.selectedCaseId = caseId;
    state.caseDetail = null;
    renderCase();
    renderWorklist();
    renderOutboxPane(); // reply box reacts to selectedCaseId immediately
    setProgress(document.getElementById("pane-case"), true);
    const res = await api("GET", ROUTES.case(state.seed, caseId));
    setProgress(document.getElementById("pane-case"), false);
    if (!res.ok) {
      state.caseDetail = { error: true, status: res.status, detail: res.detail };
    } else {
      state.caseDetail = res.data;
      // see timelineEntryHtml's comment: only Generated+degraded is a real fallback.
      const anyDegraded = (res.data.timeline || []).some((e) => e.type === "MESSAGE_QUEUED" && e.tag === "Generated" && e.payload && e.payload.degraded);
      if (anyDegraded) showQuotaStrip("Model unavailable (quota) — templates in use; decisions unchanged.");
      else if (!state.modelOff) hideQuotaStrip();
    }
    renderCase();
    if (switchPane) switchToPane("pane-case");
  }
  async function doQuietToggle() {
    if (state.modelOff) return;
    const next = !state.quietOn;
    els.quietBtn.disabled = true;
    const res = await api("POST", ROUTES.quiet(), { seed: state.seed, on: next });
    els.quietBtn.disabled = false;
    if (!res.ok) return;
    state.quietOn = next;
    renderQuietSwitch();
    renderFooter();
    renderOutboxPane();
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
    state.quietOn = false;
    state.lastReply = null;
    state.replay = null;
    renderQuietSwitch();
    els.seedBtn.disabled = true;
    if (els.emptySeedBtn) els.emptySeedBtn.disabled = true;
    els.worklistBody.innerHTML = loadingHtml("Seeding cohort…");
    const res = await api("POST", ROUTES.seed(), { seed: state.seed, n: 38 });
    els.seedBtn.disabled = false;
    if (els.emptySeedBtn) els.emptySeedBtn.disabled = false;
    if (!res.ok) { state.worklist = { error: true, status: res.status, detail: res.detail }; renderWorklist(); return; }
    state.clockIso = DEFAULT_EPOCH;
    state.clockLabel = "D1";
    state.clockIsOverride = false;
    renderClock();
    state.worklist = res.data.worklist || [];
    renderWorklist();
    renderCase();
    await loadOutbox();
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
    if (!res.ok) { state.worklist = { error: true, status: res.status, detail: res.detail }; renderWorklist(); return; }
    if (!state.clockIsOverride) {
      state.clockIso = res.data.run_summary.clock;
      state.clockLabel = RUNGS.includes(to) ? to : "custom";
      renderClock();
    }
    await loadWorklist();
    if (state.selectedCaseId) await loadCase(state.selectedCaseId, false);
    await loadOutbox();
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
    state.outbox = null;
    state.quietOn = false;
    state.lastReply = null;
    state.replay = null;
    renderClock();
    renderWorklist();
    renderCase();
    renderQuietSwitch();
    renderOutboxPane();
  }

  // ------------------------------------------------------------------ url --
  function updateUrl() {
    const params = new URLSearchParams(window.location.search);
    params.set("seed", String(state.seed));
    window.history.replaceState(null, "", `${window.location.pathname}?${params.toString()}`);
  }
  function readUrlParams() {
    const params = new URLSearchParams(window.location.search);
    const seedRaw = params.get("seed");
    if (seedRaw !== null) {
      const parsed = parseInt(seedRaw, 10);
      if (!isNaN(parsed) && String(parsed) === seedRaw.trim()) { state.seed = parsed; els.seedInput.value = String(parsed); }
      else { els.seedNote.hidden = false; els.seedNote.textContent = "seed must be a whole number — using 3"; }
    }
    const clockRaw = params.get("clock");
    if (clockRaw) {
      const d = new Date(clockRaw);
      if (!isNaN(d.getTime())) { state.clockIso = clockRaw; state.clockLabel = null; state.clockIsOverride = true; }
      else { els.clockNote.hidden = false; els.clockNote.textContent = "clock ignored: not ISO"; }
    }
  }

  // -------------------------------------------------- topbar scroll hint --
  // Phone breakpoint (<=699px) makes .topbar-controls a horizontally
  // scrolling strip (DESIGN.md §3) so the five Advance buttons all fit.
  // J-05: that scroll was real but had zero visual affordance, so a judge
  // at 390px saw the row clipped mid-label and assumed it was broken. This
  // toggles a small fading "more content" chevron whenever the strip is
  // scrollable and not already scrolled to its end.
  function updateScrollHint() {
    const el = els.topbarControls;
    const hint = els.scrollHint;
    if (!el || !hint) return;
    const hasMore = el.scrollWidth - el.clientWidth - el.scrollLeft > 4;
    hint.classList.toggle("visible", hasMore);
  }

  // ------------------------------------------------------------- tab bar --
  function switchToPane(paneId) {
    els.panes.forEach((p) => p.classList.toggle("active", p.id === paneId));
    Array.from(els.tabbar.querySelectorAll(".tab-btn")).forEach((btn) => btn.setAttribute("aria-current", btn.getAttribute("data-pane") === paneId ? "true" : "false"));
  }

  // -------------------------------------------------------------- init --
  function wireEvents() {
    els.seedBtn.addEventListener("click", doSeed);
    if (els.emptySeedBtn) els.emptySeedBtn.addEventListener("click", doSeed);
    els.resetBtn.addEventListener("click", doReset);
    Array.from(els.advanceGroup.querySelectorAll(".advance-btn")).forEach((btn) => btn.addEventListener("click", () => doAdvance(btn.getAttribute("data-to"))));
    Array.from(els.tabbar.querySelectorAll(".tab-btn")).forEach((btn) => btn.addEventListener("click", () => switchToPane(btn.getAttribute("data-pane"))));
    els.quietBtn.addEventListener("click", doQuietToggle);
    if (els.topbarControls) {
      els.topbarControls.addEventListener("scroll", updateScrollHint, { passive: true });
      window.addEventListener("resize", updateScrollHint);
    }
  }
  async function init() {
    readUrlParams();
    renderClock();
    wireEvents();
    switchToPane("pane-worklist");
    updateScrollHint();
    await loadHealth();
    loadRules(); // not awaited — keypad renders once it lands, worklist/case unaffected
    await loadWorklist();
    await loadOutbox();
    if (state.worklist && state.worklist.length && !state.clockLabel) {
      // Cohort already existed server-side (shared URL); no clock route to
      // recover the exact rung label from, so leave the date at epoch until
      // the next Advance — the worklist itself still renders fully.
      state.clockIso = state.clockIso || DEFAULT_EPOCH;
      renderClock();
    }
    updateScrollHint();
  }
  document.addEventListener("DOMContentLoaded", init);
})();
