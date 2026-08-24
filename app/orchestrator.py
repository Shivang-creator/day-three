"""app/orchestrator.py — the only place a Store is ever written to outside
tests (PLAN §4.2, §4.10; enforced by tests/test_boundary.py::
test_only_orchestrator_appends_to_a_store — that check scans the whole repo
for `<x>.append(` where "store" appears in the receiver, everywhere except
this file). Every HTTP route in app/main.py that changes state calls into a
function here; core/ stays a pure function library that never sees a Store,
a Clock it didn't get handed, or the model.

Design decisions a reader of core/ alone can't see, because they live in the
seam between "sweep.py computes decisions" and "the pack has rule_ids but no
message text" (PLAN §4.7's own words: "sweep.py never sees message text; text
is rendered afterwards by the shell" — this file is that shell):

1. **The routine check-in and retry-reminder texts are NOT core Actions.**
   `core/routing.py::plan()` only emits a MESSAGE_MOTHER action when a pack
   RULE fires (URGENT_FACILITY_NOW -> "come_now", SAME_DAY_VISIT -> "same_day"
   — see `rules/postnatal.v1.json`, no rule's `actions` list contains a
   MESSAGE_MOTHER token for HUMAN_REVIEW_NOW or the gate's generic
   HUMAN_REVIEW). The "Hello, this is your Day 3 check-in" and "we didn't
   hear from you" texts are pack-driven but rule-*less* — they fire off
   `CONTACT_DUE` (a rung's window opening) and `RETRY_CONTACT` (silence's
   first retry) respectively, not off a `Rule.when` match. Encoding them as
   fake rules just to get a MESSAGE_MOTHER token out of `routing.plan()`
   would put UI copy inside `rules/postnatal.v1.json`'s citation-bearing
   clinical data — the wrong layer. So `advance()` queues `checkin_<rung>`
   itself, right where it appends `CONTACT_DUE`, and `_write_action()` queues
   `retry` itself, right where it turns `RETRY_CONTACT` into `RETRY_SCHEDULED`.
   Consequence: these two intents are ALWAYS rendered via `agent/quiet.py`
   (template only) — see decision 2 below for why that's also correct
   per PLAN §4.9, not just convenient.

2. **Only `come_now` and `same_day` (ESCALATION_INTENTS) ever reach the
   model.** PLAN §4.9: "routine rung check-ins are templates; the model
   drafts only escalation messages." `agent/writer.py::render()` itself has
   no opinion on this — it happily spins up a full ADK agent turn for ANY
   intent if the kill-switch is on. If this file called `agent_writer.render`
   for every one of a 38-mother D3 sweep's routine check-ins, that would be
   ~38 live model calls for TEXT THAT'S GOING TO BE THE TEMPLATE ANYWAY per
   `agent/tools.py::draft_message`'s own docstring ("Always prefer this over
   free composition for anything that has a template"), not the ~6-8 PLAN
   §12 budgets for a D3 sweep. So this file makes the "only escalations use
   the model" decision itself, before ever calling `agent.writer`.

3. **A per-namespace Quiet Mode meta flag (`quiet:<seed>`), independent of
   the process-wide `MODEL_OFF` env var.** `POST /api/quiet {seed, on}` sets
   it. When on: (a) every MESSAGE_MOTHER, even an escalation, renders via
   `agent/quiet.py` directly — `agent_writer.render` (and therefore the
   model) is never called; (b) free text in `POST /api/reply` is NOT passed
   to `agent/reader.py::read()` at all — this file builds the all-"unknown"
   SymptomForm itself. That second half is PLAN §10 verbatim: "In Quiet Mode
   free text is not read at all and goes to `HUMAN_REVIEW`" — an all-unknown
   SymptomForm with the pack's own `M_SELF_HARM`/other red signs unknown
   forces `core/gate.py::evaluate` to `HUMAN_REVIEW` by construction (or
   `NEXT_CONTACT` never — see gate's route table), independent of whatever
   `MODEL_OFF` happens to be. No FORM_READ event is appended in this path —
   nothing read the text, so no read event exists (an honest absence, not a
   degraded one).

4. **`MODEL_CALL_BUDGET` (PLAN §12, ≤8 calls/sweep target, env-configurable,
   default 12) is enforced HERE**, as a per-call counter threaded through one
   `advance()` or `reply()` invocation. T-18's outbox flagged that neither
   `agent/gemini_client.py` nor `agent/writer.py` enforces this — by design,
   per decision 2, the shell is the only place that already knows which
   messages are "escalation" candidates in the first place.

5. **`CONTACT_RESCHEDULED` (the routing-computed "when's this mother's next
   ladder rung" `SCHEDULE_CONTACT` action) DOES update `state.rung` ahead of
   the demo's own explicit `/api/advance` step** (`core/events.py::reduce`
   folds `CONTACT_RESCHEDULED.rung` straight into `state.rung`). This is
   safe, not a bug: `core/schedule.py::due_now` still gates on the target
   rung's time window, so an early rung bump does nothing until the clock
   actually gets there — and `/api/advance` unconditionally re-appends a
   fresh `CONTACT_DUE{rung: to}` for every relevant case on its own next
   call anyway (T-12's outbox note: "run_sweep does not itself advance a
   case's rung... `/api/advance` must append a CONTACT_DUE event... before
   calling run_sweep"), which is idempotent-safe and simply overwrites
   whatever `CONTACT_RESCHEDULED` had already set.

6. **Cross-call slot-booking safety is best-effort, not airtight.**
   `core/sweep.py::run_sweep` only prevents double-booking *within one
   sweep call* (its own `booked: set[str] = set()` starts empty every call —
   T-11/T-12's own contract). This file additionally persists every booked
   `slot_iso` in `store.meta["booked:<seed>"]` and threads it into
   `core/routing.py::plan(..., booked=...)` for the single-case `/api/reply`
   path, so a live judge reply won't collide with a slot a bulk sweep already
   took. It does NOT feed that persisted set back into `run_sweep` itself
   (that function's signature has no `booked` parameter to accept one) — two
   *separate* `/api/advance` calls whose target clocks land on the same
   clinic day could in principle both book the day's 09:00 slot. Flagged for
   T-29 (red team) and T-30; low risk in practice since ladder rungs for one
   mother are weeks apart and 38 mothers rarely fill one day twice over.

7. **Tag choice for `ASHA_VISIT_TASK` is "Simulated", not "Rule".** PLAN §6's
   legend table lists bookings/pages/schedules/template text as "Rule" (the
   *decision* to act is rule-computed) but PLAN §7's Honesty section
   separately calls out "the ASHA assignment" as one of the things
   "Simulated, and labelled so on screen" — there is no real ASHA app on the
   other end of this event, only a demo channel. Every other action type
   (`SLOT_BOOKED`, `NURSE_PAGED`, `NURSE_FLAGGED`, `HUMAN_REVIEW`,
   `CONTACT_RESCHEDULED`, `RETRY_SCHEDULED`) is tagged "Rule".
"""
from __future__ import annotations

import dataclasses
import logging
import os
from datetime import datetime, timedelta

from agent import quiet
from agent import writer as agent_writer
from agent.gemini_client import model_enabled
from agent.reader import read as reader_read
from core import gate, routing
from core.clock import Clock, FixedClock
from core.schedule import due_now
from core.cohort import generate as generate_cohort
from core.events import Event, idempotency_key, reduce
from core.models import Mother, SymptomForm
from core.rulepack import RulePack
from core.sweep import SILENCE_ROUTE, run_sweep
from store.readonly import ReadOnlyStoreView

logger = logging.getLogger("app.orchestrator")

# The cohort's discharge epoch — a single source of truth this file owns
# (rather than relying on core.cohort.generate's own default parameter),
# since /api/advance's rung -> clock arithmetic must agree with whatever
# epoch /api/seed actually enrolled the cohort at.
DEFAULT_EPOCH = "2026-08-24T00:00:00Z"

# Simulated — there is no real clinic behind this address; PLAN §7 lists
# "clinic slot capacity" among the things labelled Simulated on screen.
CLINIC_ADDRESS = "Day Three Clinic, Sector 12 Primary Health Centre"

# Only these two intents are ever candidates for a live model draft
# (decision 2 above). Every other MESSAGE_MOTHER-shaped text this file
# queues (checkin_<rung>, retry) always renders via agent/quiet.py.
ESCALATION_INTENTS = frozenset({"come_now", "same_day"})

# DECISIONS.md 2026-08-25 01:35: HUMAN_REVIEW_NOW sorts alongside URGENT.
WORKLIST_RANK = {
    "URGENT_FACILITY_NOW": 0,
    "HUMAN_REVIEW_NOW": 0,
    "HUMAN_REVIEW": 1,
    "SAME_DAY_VISIT": 2,
    SILENCE_ROUTE: 3,
    "NEXT_CONTACT": 4,
}


class NotFoundError(LookupError):
    """A namespace/case_id combination that doesn't exist. app/main.py maps
    this to HTTP 404."""


# --------------------------------------------------------------- helpers --


def _ns(seed: int | str) -> str:
    return str(seed)


def full_case_id(seed: int | str, case_id: str) -> str:
    """`case_id` may already be namespaced ("3:mother-07") or bare
    ("mother-07") — accept either, since the HTTP layer always has `seed`
    separately as `?seed=`."""
    prefix = f"{_ns(seed)}:"
    return case_id if case_id.startswith(prefix) else f"{prefix}{case_id}"


def _clock_meta_key(seed: int | str) -> str:
    return f"clock:{_ns(seed)}"


def _quiet_meta_key(seed: int | str) -> str:
    return f"quiet:{_ns(seed)}"


def _booked_meta_key(seed: int | str) -> str:
    return f"booked:{_ns(seed)}"


def get_clock(store, seed: int | str, override_iso: str | None = None) -> FixedClock:
    """The effective "now" for one call: `override_iso` (the `?clock=` query
    param) wins if given; otherwise the namespace's stored clock (set by
    `enroll()`/`advance()`). Raises NotFoundError if the namespace was never
    seeded and no override was given — there is no sensible "now" to use."""
    if override_iso:
        return FixedClock(datetime.fromisoformat(override_iso))
    meta = store.get_meta(_clock_meta_key(seed))
    if meta is None:
        raise NotFoundError(f"seed {seed!r} has not been seeded yet (no stored clock)")
    return FixedClock(datetime.fromisoformat(meta["iso"]))


def quiet_on(store, seed: int | str) -> bool:
    meta = store.get_meta(_quiet_meta_key(seed))
    return bool(meta and meta.get("on"))


def set_quiet(store, seed: int | str, on: bool) -> None:
    store.set_meta(_quiet_meta_key(seed), {"on": bool(on)})


def _booked_slots(store, seed: int | str) -> set[str]:
    meta = store.get_meta(_booked_meta_key(seed))
    return set(meta["slots"]) if meta else set()


def _save_booked_slots(store, seed: int | str, booked: set[str]) -> None:
    store.set_meta(_booked_meta_key(seed), {"slots": sorted(booked)})


def _new_budget() -> dict:
    return {"used": 0, "limit": int(os.environ.get("MODEL_CALL_BUDGET", "12"))}


def _append(store, case_id: str, clock_iso: str, type_: str, payload: dict, tag: str, rule_id: str | None, *, key_extra: str = "") -> Event:
    seq = len(store.events(case_id))
    key = idempotency_key(case_id, clock_iso, type_, key_extra)
    event = Event(seq=seq, case_id=case_id, at=clock_iso, type=type_, payload=payload, tag=tag, rule_id=rule_id, idempotency_key=key)
    store.append(case_id, event, key)
    return event


def _format_slot_time(slot_iso: str) -> str:
    return datetime.fromisoformat(slot_iso).strftime("%H:%M")


def _target_iso_for_rung(pack: RulePack, rung: str) -> str:
    """The clock instant at which every mother whose variant's ladder has a
    rung named `rung` is inside that rung's contact window. When variants
    disagree on `due_hours_after_discharge` for the same rung name, the
    LATEST due time is used — that's always inside the window of every
    variant whose window hasn't yet closed by then, because a rung's window
    only ever opens at or after `due_hours_after_discharge` (see the WHO/HBNC
    D3 worked example in T-12's outbox: WHO D3 = [48,72]h, HBNC D3 = [72,96]h;
    max(48,72)=72h lands exactly on WHO's close and HBNC's open — both due)."""
    matches = [r for r in pack.ladder if r.rung == rung]
    if not matches:
        raise ValueError(f"unknown rung {rung!r} — not present in the rule pack's ladder")
    epoch = datetime.fromisoformat(DEFAULT_EPOCH)
    target = epoch + timedelta(hours=max(r.due_hours_after_discharge for r in matches))
    return target.isoformat()


def _is_iso(value: str) -> bool:
    try:
        datetime.fromisoformat(value)
        return True
    except ValueError:
        return False


def _keypad_summary(keypad: dict) -> str:
    return ", ".join(f"{sid}:{'yes' if val else 'no'}" for sid, val in sorted(keypad.items()))


def _verdict_payload(verdict) -> dict:
    return {"route": verdict.route, "fired": [dict(f) for f in verdict.fired], "unknown": list(verdict.unknown)}


def _render_message(*, intent: str, lang: str, facts: dict, store, pack, quiet_flag: bool, budget: dict) -> dict:
    """Decisions 2 and 3 above, in one place: only ESCALATION_INTENTS are
    even candidates for the model, and only when Quiet Mode is off, the
    kill-switch is on, and the per-call budget isn't exhausted. Everything
    else always goes through agent/quiet.py — no model call is even
    attempted, so it costs nothing against the budget."""
    if intent not in ESCALATION_INTENTS:
        return quiet.render(intent, lang, facts)
    if quiet_flag:
        return quiet.render(intent, lang, facts)
    if not model_enabled():
        # R-02: this is the case a blank GEMINI_API_KEY hits — an
        # escalation message that WOULD have gone to the model, silently
        # downgraded instead. Previously unlogged (RED-TEAM.md Attack 1:
        # "the 4 writer fallbacks logged NOTHING"), unlike the identical
        # degrade one branch down for a budget exhaustion. Same log shape
        # as that one so both fallback causes are greppable together.
        logger.error(
            "MODEL_FALLBACK app.orchestrator: model_enabled()=False (no key / MODEL_OFF) — intent=%r forced to Quiet template",
            intent,
        )
        return quiet.render(intent, lang, facts)
    if budget["used"] >= budget["limit"]:
        logger.error(
            "MODEL_FALLBACK app.orchestrator: MODEL_CALL_BUDGET (%s) exhausted — intent=%r forced to Quiet template",
            budget["limit"],
            intent,
        )
        return quiet.render(intent, lang, facts)
    budget["used"] += 1
    return agent_writer.render(intent, lang, facts, store_view=ReadOnlyStoreView(store), pack=pack)


def _message_event_payload(msg: dict, intent: str, lang: str) -> dict:
    return {"intent": intent, "lang": lang, "text": msg["text"], "model": msg["model"], "degraded": msg["degraded"]}


def _write_action(
    store,
    pack,
    case_id: str,
    clock_iso: str,
    action,
    *,
    sibling_actions: tuple,
    mother: Mother,
    quiet_flag: bool,
    budget: dict,
) -> tuple[list[Event], str | None]:
    """Turns one core.models.Action into one or more appended Events. Returns
    (events, booked_slot_iso_or_None) so the caller can accumulate the
    namespace's booked-slots meta (decision 6 above)."""
    events: list[Event] = []
    newly_booked: str | None = None

    if action.type == "BOOK_SLOT":
        slot_iso = action.payload["slot_iso"]
        events.append(_append(store, case_id, clock_iso, "SLOT_BOOKED", {"slot_iso": slot_iso}, "Rule", action.rule_id, key_extra=slot_iso))
        newly_booked = slot_iso
    elif action.type == "PAGE_NURSE":
        priority = action.payload["priority"]
        events.append(_append(store, case_id, clock_iso, "NURSE_PAGED", {"priority": priority}, "Rule", action.rule_id, key_extra=priority))
    elif action.type == "FLAG_NURSE":
        reason = action.payload.get("reason", "")
        events.append(_append(store, case_id, clock_iso, "NURSE_FLAGGED", {"reason": reason}, "Rule", action.rule_id, key_extra=reason))
    elif action.type == "HUMAN_REVIEW":
        reason = action.payload.get("reason", "")
        events.append(_append(store, case_id, clock_iso, "HUMAN_REVIEW", {"reason": reason}, "Rule", action.rule_id, key_extra=reason))
    elif action.type == "SCHEDULE_CONTACT":
        rung, due = action.payload["rung"], action.payload["due"]
        events.append(
            _append(store, case_id, clock_iso, "CONTACT_RESCHEDULED", {"rung": rung, "due": due}, "Rule", action.rule_id, key_extra=rung)
        )
    elif action.type == "RETRY_CONTACT":
        due = action.payload["due"]
        events.append(_append(store, case_id, clock_iso, "RETRY_SCHEDULED", {"due": due}, "Rule", action.rule_id, key_extra=due))
        # The "we haven't heard from you" reminder — see module docstring
        # decision 1: not a core Action, queued here where the retry itself
        # is decided. Always a routine template (decision 2), never a
        # candidate for the model.
        state = reduce(store.events(case_id))
        msg = quiet.render("retry", "hi", {"name": mother.display_name, "rung": state.rung})
        events.append(
            _append(
                store, case_id, clock_iso, "MESSAGE_QUEUED", _message_event_payload(msg, "retry", "hi"), msg["tag"], action.rule_id, key_extra="retry"
            )
        )
    elif action.type == "ASHA_VISIT_TASK":
        due = action.payload["due"]
        events.append(_append(store, case_id, clock_iso, "ASHA_VISIT_TASK", {"due": due}, "Simulated", action.rule_id, key_extra=due))
    elif action.type == "MESSAGE_MOTHER":
        intent = action.payload["intent"]
        lang = action.payload.get("lang", "hi")
        facts = {"name": mother.display_name}
        if intent == "come_now":
            facts["clinic_address"] = CLINIC_ADDRESS
        elif intent == "same_day":
            facts["clinic_address"] = CLINIC_ADDRESS
            slot_action = next((a for a in sibling_actions if a.type == "BOOK_SLOT"), None)
            facts["slot_time"] = _format_slot_time(slot_action.payload["slot_iso"]) if slot_action else "today"
        msg = _render_message(intent=intent, lang=lang, facts=facts, store=store, pack=pack, quiet_flag=quiet_flag, budget=budget)
        events.append(
            _append(
                store, case_id, clock_iso, "MESSAGE_QUEUED", _message_event_payload(msg, intent, lang), msg["tag"], action.rule_id, key_extra=intent
            )
        )
    else:  # pragma: no cover - defensive; every current Action.type is handled above
        logger.error("app.orchestrator: unknown Action.type %r for case_id=%r — not applied", action.type, case_id)

    return events, newly_booked


def _apply_actions(store, pack, case_id: str, clock_iso: str, actions: tuple, mother: Mother, quiet_flag: bool, budget: dict) -> set[str]:
    booked: set[str] = set()
    for action in actions:
        _events, slot = _write_action(
            store, pack, case_id, clock_iso, action, sibling_actions=actions, mother=mother, quiet_flag=quiet_flag, budget=budget
        )
        if slot:
            booked.add(slot)
    return booked


# ------------------------------------------------------------ entry points --


def enroll(store, pack: RulePack, seed: int, n: int = 38) -> list[dict]:
    """`POST /api/seed`. Deterministic per seed (core.cohort.generate); safe
    to call twice with the same seed — every ENROLLED event's idempotency
    key is stable per mother_id, so a re-seed is a no-op for mothers already
    enrolled (though raising `n` will add the newly-in-range mothers)."""
    mothers = generate_cohort(seed, n=n, epoch=DEFAULT_EPOCH)
    for mother in mothers:
        case_id = full_case_id(seed, mother.mother_id)
        payload = {"mother": dataclasses.asdict(mother), "rung": "D1"}
        _append(store, case_id, DEFAULT_EPOCH, "ENROLLED", payload, "Simulated", None, key_extra=mother.mother_id)
    store.set_meta(_clock_meta_key(seed), {"iso": DEFAULT_EPOCH})
    if store.get_meta(_quiet_meta_key(seed)) is None:
        set_quiet(store, seed, False)
    if store.get_meta(_booked_meta_key(seed)) is None:
        _save_booked_slots(store, seed, set())
    return worklist(store, pack, seed)


def advance(store, pack: RulePack, seed: int, to: str) -> dict:
    """`POST /api/advance`. `to` is either a ladder rung name ("D3") or a raw
    ISO datetime. For a rung name: appends `CONTACT_DUE` + queues the
    routine check-in message for every case whose *own variant's* ladder has
    that rung (module docstring decision 1), then runs `core.sweep.run_sweep`
    and writes every resulting Decision (module docstring decisions 2-7)."""
    case_ids = store.case_ids(_ns(seed))
    if not case_ids:
        raise NotFoundError(f"seed {seed!r} has not been seeded yet")

    rung_name = None if _is_iso(to) else to
    target_iso = to if rung_name is None else _target_iso_for_rung(pack, rung_name)
    # R-04 (RED-TEAM.md): a naive ISO string (no timezone) passes `_is_iso`
    # (datetime.fromisoformat accepts naive datetimes) but FixedClock itself
    # rejects it. This USED to `set_meta` the poisoned clock before ever
    # constructing/validating the FixedClock, so a rejected `/api/advance`
    # still left `meta clock:<seed>` pointing at the bad value — every
    # LATER `/api/reply` on that seed then 400'd too (get_clock() builds a
    # FixedClock from whatever was last persisted), with no way back except
    # a successful advance overwriting it. Build+validate the clock FIRST;
    # only persist it once construction has actually succeeded.
    clock = FixedClock(datetime.fromisoformat(target_iso))
    store.set_meta(_clock_meta_key(seed), {"iso": target_iso})
    is_quiet = quiet_on(store, seed)
    budget = _new_budget()

    if rung_name is not None:
        for case_id in case_ids:
            state = reduce(store.events(case_id))
            mother = state.mother
            on_ladder = any(r.rung == rung_name and r.variant == mother.variant for r in pack.ladder)
            if not on_ladder:
                continue
            _append(store, case_id, target_iso, "CONTACT_DUE", {"rung": rung_name, "due": target_iso}, "Simulated", None, key_extra=rung_name)
            msg = quiet.render(f"checkin_{rung_name}", "hi", {"name": mother.display_name})
            _append(
                store,
                case_id,
                target_iso,
                "MESSAGE_QUEUED",
                _message_event_payload(msg, f"checkin_{rung_name}", "hi"),
                msg["tag"],
                None,
                key_extra=f"checkin_{rung_name}",
            )

    snapshot = {cid: store.events(cid) for cid in case_ids}
    # R-05: `n` here is the namespace's REAL enrolled count (not the
    # cohort's DEFAULT_N=38 default) — core.cohort.category_for's lookup
    # table must be sized to match whatever `POST /api/seed` actually
    # enrolled, or a case whose index falls outside a stale/mismatched
    # table KeyErrors inside run_sweep.
    result = run_sweep(snapshot, clock, pack, n=len(case_ids))

    booked = _booked_slots(store, seed)
    decisions_out = []
    for decision in result.decisions:
        state = reduce(store.events(decision.case_id))
        mother = state.mother
        _append(
            store,
            decision.case_id,
            target_iso,
            "VERDICT",
            _verdict_payload(decision.verdict),
            decision.verdict.tag,
            None,
            key_extra=f"sweep:{decision.verdict.route}",
        )
        booked |= _apply_actions(store, pack, decision.case_id, target_iso, decision.actions_without_text, mother, is_quiet, budget)
        decisions_out.append(
            {
                "case_id": decision.case_id,
                "rung": decision.rung,
                "route": decision.verdict.route,
                "actions": [{"type": a.type, "rule_id": a.rule_id, "payload": a.payload} for a in decision.actions_without_text],
            }
        )
    _save_booked_slots(store, seed, booked)

    n_urgent = sum(1 for d in decisions_out if d["route"] in ("URGENT_FACILITY_NOW", "HUMAN_REVIEW_NOW"))
    n_review = sum(1 for d in decisions_out if d["route"] == "HUMAN_REVIEW")
    n_silence = sum(1 for d in decisions_out if d["route"] == SILENCE_ROUTE)
    run_summary = {
        "clock": target_iso,
        "n_due": len(decisions_out),
        "n_urgent": n_urgent,
        "n_review": n_review,
        "n_silence": n_silence,
        "model_calls_used": budget["used"],
        "model_call_budget": budget["limit"],
    }
    return {"decisions": decisions_out, "run_summary": run_summary}


def reply(store, pack: RulePack, seed: int, case_id: str, *, keypad: dict | None = None, text: str | None = None, clock_override: str | None = None) -> dict:
    """`POST /api/reply`. Decision 3 above governs the Quiet Mode free-text
    path. `keypad` and `text` may both be given (merged per
    `core.gate.merge`), or just one."""
    if keypad is None and text is None:
        raise ValueError("reply requires 'keypad' and/or 'text'")

    full_id = full_case_id(seed, case_id)
    events = store.events(full_id)
    if not events:
        raise NotFoundError(f"no such case: {full_id!r}")
    state = reduce(events)
    mother = state.mother
    clock = get_clock(store, seed, clock_override)
    clock_iso = clock.now().isoformat()
    is_quiet = quiet_on(store, seed)

    reply_payload: dict = {}
    if text:
        reply_payload["text"] = text
    if keypad:
        reply_payload["keypad"] = dict(keypad)
        if "text" not in reply_payload:
            reply_payload["summary"] = _keypad_summary(keypad)
    _append(store, full_id, clock_iso, "REPLY_RECEIVED", reply_payload, "Observed", None, key_extra=f"reply:{len(events)}")

    keypad_form = SymptomForm(subject="newborn", signs=dict(keypad), origin="keypad", reader="none") if keypad else None

    reader_form = None
    if text:
        if is_quiet:
            sign_ids = [s.sign_id for s in pack.signs]
            reader_form = SymptomForm(subject="newborn", signs={sid: "unknown" for sid in sign_ids}, origin="free_text", reader="none", source_text=text)
        else:
            reader_form = reader_read(text, pack, subject="newborn", store=store)
            read_tag = "Generated" if reader_form.reader_confidence > 0 else "Rule"
            _append(
                store,
                full_id,
                clock_iso,
                "FORM_READ",
                {"signs": dict(reader_form.signs), "reader": reader_form.reader, "unclear": []},
                read_tag,
                None,
                key_extra=f"form_read:{len(events)}",
            )

    if keypad_form is not None and reader_form is not None:
        form = gate.merge(keypad_form, reader_form)
    else:
        form = keypad_form if keypad_form is not None else reader_form

    verdict = gate.evaluate(form, pack)
    _append(store, full_id, clock_iso, "VERDICT", _verdict_payload(verdict), verdict.tag, None, key_extra=f"reply-verdict:{len(events)}")

    booked = _booked_slots(store, seed)
    # J-07/R-07 (JUDGE-REPORT.md, .crew/BOARD.md): only advance the Contact
    # Ladder if this reply is actually answering a contact that's due RIGHT
    # NOW at this clock — otherwise a handful of replies sent back-to-back
    # (a keypad reply plus a few free-text messages, none of which moved
    # the clock) used to fast-forward `state.rung` one full ladder step per
    # reply, silently skipping every rung in between. See routing.plan's
    # own `advance_ladder` docstring for the full story.
    is_due_now = due_now(state, clock, pack) is not None
    actions = routing.plan(verdict, state, clock, pack, booked=booked, advance_ladder=is_due_now)
    budget = _new_budget()
    booked |= _apply_actions(store, pack, full_id, clock_iso, tuple(actions), mother, is_quiet, budget)
    _save_booked_slots(store, seed, booked)

    return {
        "case_id": full_id,
        "verdict": _verdict_payload(verdict) | {"tag": verdict.tag},
        "actions": [{"type": a.type, "rule_id": a.rule_id, "payload": a.payload} for a in actions],
    }


def worklist(store, pack: RulePack, seed: int) -> list[dict]:
    """`GET /api/worklist`. Sorted per PLAN §4.10 / DECISIONS.md: URGENT and
    HUMAN_REVIEW_NOW first, then HUMAN_REVIEW, SAME_DAY_VISIT, SILENCE,
    NEXT_CONTACT (or no verdict yet — a case never swept sorts last)."""
    rows = []
    for case_id in store.case_ids(_ns(seed)):
        events = store.events(case_id)
        state = reduce(events)
        route = state.route_history[-1] if state.route_history else None
        fired = _latest_fired(events)
        rows.append(
            {
                "case_id": case_id,
                "mother": {"display_name": state.mother.display_name, "phone": state.mother.phone, "variant": state.mother.variant},
                "rung": state.rung,
                "route": route,
                "fired": fired,
                "next_due": state.next_due,
                "open_slot": state.open_slot,
                "flags": list(state.flags),
            }
        )
    rows.sort(key=lambda r: (WORKLIST_RANK.get(r["route"], 5), r["case_id"]))
    return rows


def _latest_fired(events: list[Event]) -> list[dict]:
    for event in sorted(events, key=lambda e: e.seq, reverse=True):
        if event.type == "VERDICT":
            return event.payload.get("fired", [])
    return []


def case_detail(store, pack: RulePack, seed: int, case_id: str) -> dict:
    """`GET /api/case/{id}`. Full event timeline plus, for any event whose
    `rule_id` names a real pack rule, that rule's citation (source_id/
    source_quote/source_url) inlined for display. Synthetic rule_ids
    (`routing.LADDER_RULE_ID`, `routing.GATE_HUMAN_REVIEW_RULE_ID`, the
    silence policy's `silence_id`) have no pack-rule citation — T-11's
    outbox flagged this is expected, not a bug; those entries simply carry
    no `citation` key."""
    full_id = full_case_id(seed, case_id)
    events = store.events(full_id)
    if not events:
        raise NotFoundError(f"no such case: {full_id!r}")
    state = reduce(events)
    rules_by_id = {r.rule_id: r for r in pack.rules}

    timeline = []
    for event in sorted(events, key=lambda e: e.seq):
        entry = {
            "seq": event.seq,
            "at": event.at,
            "type": event.type,
            "payload": event.payload,
            "tag": event.tag,
            "rule_id": event.rule_id,
        }
        rule = rules_by_id.get(event.rule_id) if event.rule_id else None
        if rule is not None:
            entry["citation"] = {"source_id": rule.source_id, "source_quote": rule.source_quote, "source_url": rule.source_url}
        timeline.append(entry)

    return {
        "case_id": full_id,
        "mother": dataclasses.asdict(state.mother),
        "rung": state.rung,
        "next_due": state.next_due,
        "open_slot": state.open_slot,
        "flags": list(state.flags),
        "route_history": list(state.route_history),
        "timeline": timeline,
    }


def outbox(store, seed: int) -> list[dict]:
    """`GET /api/outbox`. Every queued message across the namespace, oldest
    first. `channel_tag` is always "Simulated" (PLAN §7: "SMS/WhatsApp/pager
    delivery (an outbox, nothing is sent)") — a fixed disclosure about the
    delivery channel itself, independent of `text_tag`, which is the
    MESSAGE_QUEUED event's own tag (Rule for a template, Generated for a
    model draft)."""
    rows = []
    for case_id in store.case_ids(_ns(seed)):
        for event in store.events(case_id):
            if event.type != "MESSAGE_QUEUED":
                continue
            rows.append(
                {
                    "case_id": case_id,
                    "at": event.at,
                    "intent": event.payload.get("intent"),
                    "lang": event.payload.get("lang"),
                    "text": event.payload.get("text"),
                    "text_tag": event.tag,
                    "model": event.payload.get("model"),
                    "degraded": event.payload.get("degraded"),
                    "channel_tag": "Simulated",
                }
            )
    rows.sort(key=lambda r: (r["at"], r["case_id"]))
    return rows


def reset(store, seed: int) -> None:
    """`POST /api/reset`. Demo/test only, per store.base.Store.reset's own
    docstring."""
    store.reset(_ns(seed))
