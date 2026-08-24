"""Routing (PLAN §4.6): turns a Verdict into the concrete Action list a case
needs right now, and turns prolonged silence into a retry-then-escalate
Action list. Pure functions of (verdict/state, clock, pack); `plan()` takes
an optional `booked` set of already-taken slot timestamps so a whole-cohort
sweep (core/sweep.py, T-12) can avoid double-booking clinic slots across
cases evaluated back to back in the same pass.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from core import slots
from core.clock import Clock
from core.models import Action, CaseState, Verdict
from core.rulepack import Rule, RulePack
from core.schedule import next_contact

# Attribution for the routine "keep the Contact Ladder moving" action, which
# is not something any single rule fires — it is routing.py's own policy
# that every case keeps its next scheduled contact regardless of route.
LADDER_RULE_ID = "SCHED-LADDER"
# Attribution for the HUMAN_REVIEW route, which (unlike the other routes)
# has no fired rule behind it — core/gate.py returns Verdict.fired == () for
# it, since it fires on the *absence* of a confirmed sign, not a rule match.
GATE_HUMAN_REVIEW_RULE_ID = "GATE-HUMAN-REVIEW"


def _rule_by_id(pack: RulePack, rule_id: str) -> Rule:
    return next(r for r in pack.rules if r.rule_id == rule_id)


def _schedule_next_contact_action(state: CaseState, pack: RulePack) -> Action | None:
    contact = next_contact(state, pack, state.mother.variant)
    if contact is None:
        return None  # already at the ladder's last rung — nothing further to schedule
    return Action(
        type="SCHEDULE_CONTACT",
        rule_id=LADDER_RULE_ID,
        payload={"rung": contact.rung, "due": contact.due},
    )


def plan(
    verdict: Verdict,
    state: CaseState,
    clock: Clock,
    pack: RulePack,
    booked: frozenset[str] | set[str] = frozenset(),
    advance_ladder: bool = True,
) -> list[Action]:
    """Every Action carries a `rule_id` naming why it exists. The Contact
    Ladder keeps moving regardless of route — an urgent visit today does not
    cancel the mother's next scheduled contact.

    `advance_ladder` (R-07/J-07, JUDGE-REPORT.md): `core/sweep.py::run_sweep`
    only ever calls `plan()` for a case whose CURRENT rung is actually due
    right now (it checks `core.schedule.due_now` first) — for that caller,
    "the ladder keeps moving" correctly means "move to the next rung."
    `app/orchestrator.py::reply()` used to call `plan()` unconditionally for
    ANY reply at ANY time, with no such due-now guard — so every single
    `/api/reply` (not just one that actually answered a due contact) pushed
    `state.rung` one step further along the ladder, letting a handful of
    replies sent back-to-back (none of which advanced the CLOCK) silently
    skip straight to the ladder's last rung. `advance_ladder=False` lets a
    caller suppress the ladder-reschedule action specifically, for a reply
    that isn't answering a currently-due contact, without touching the
    verdict-driven actions (BOOK_SLOT/PAGE_NURSE/HUMAN_REVIEW/...) at all."""
    actions: list[Action] = []
    booked_now = set(booked)

    if verdict.fired:
        # A rule fired (URGENT_FACILITY_NOW, SAME_DAY_VISIT, or the
        # self-harm HUMAN_REVIEW_NOW): realise the union of every fired
        # rule's abstract action tokens into concrete Actions, attributed to
        # the first-fired rule_id.
        urgent = verdict.route == "URGENT_FACILITY_NOW"
        primary_rule_id = verdict.fired[0]["rule_id"]
        tokens: list[str] = []
        for f in verdict.fired:
            for token in _rule_by_id(pack, f["rule_id"]).actions:
                if token not in tokens:
                    tokens.append(token)

        for token in tokens:
            if token == "BOOK_SLOT":
                slot_iso = slots.earliest(clock, booked_now, pack, urgent)
                booked_now.add(slot_iso)
                actions.append(Action(type="BOOK_SLOT", rule_id=primary_rule_id, payload={"slot_iso": slot_iso}))
            elif token == "PAGE_NURSE":
                priority = "high" if urgent or verdict.route == "HUMAN_REVIEW_NOW" else "routine"
                actions.append(Action(type="PAGE_NURSE", rule_id=primary_rule_id, payload={"priority": priority}))
            elif token == "HUMAN_REVIEW":
                actions.append(
                    Action(type="HUMAN_REVIEW", rule_id=primary_rule_id, payload={"reason": verdict.route})
                )
            elif token.startswith("MESSAGE_MOTHER:"):
                intent = token.split(":", 1)[1]
                actions.append(
                    Action(type="MESSAGE_MOTHER", rule_id=primary_rule_id, payload={"intent": intent, "lang": "hi"})
                )
    elif verdict.route == "HUMAN_REVIEW":
        actions.append(
            Action(
                type="HUMAN_REVIEW",
                rule_id=GATE_HUMAN_REVIEW_RULE_ID,
                payload={"reason": "unresolved red sign(s): " + ", ".join(sorted(verdict.unknown))},
            )
        )
    # NEXT_CONTACT: nothing fired and nothing unresolved — no escalation action.

    if advance_ladder:
        ladder_action = _schedule_next_contact_action(state, pack)
        if ladder_action is not None:
            actions.append(ladder_action)

    return actions


def silence_plan(state: CaseState, clock: Clock, pack: RulePack) -> list[Action]:
    """A CONTACT_DUE with no REPLY_RECEIVED inside the window is a signal,
    not a non-event (PLAN §4.6): retry once, then escalate. `state.retry_count`
    (core/events.py::reduce) counts consecutive RETRY_SCHEDULED events since
    the last reply or new contact.

    R-03 (RED-TEAM.md): re-running a sweep at an UNCHANGED clock (the same
    D3 target called twice) used to escalate straight to ASHA/FLAG_NURSE on
    the second call, even though no time had actually passed since the
    first call scheduled the retry. Cause: this function only ever checked
    `state.retry_count < max_retries`, never whether the retry it already
    scheduled (`state.next_due`, set by the RETRY_SCHEDULED event) had
    actually come due yet. A sweep must be a safe no-op when the clock
    hasn't moved (module docstring of core/sweep.py) — so if a retry is
    already pending and its own due time is still in the future, this
    returns no actions at all rather than re-deciding anything."""
    silence = pack.silence
    rule_id = silence.silence_id or "SIL-01"

    if state.retry_count > 0 and state.next_due:
        retry_due = datetime.fromisoformat(state.next_due)
        if clock.now() < retry_due:
            return []  # already retried once; its own window hasn't elapsed — idempotent no-op

    if state.retry_count < silence.max_retries:
        due = (clock.now() + timedelta(hours=silence.retry_after_hours)).isoformat()
        return [Action(type="RETRY_CONTACT", rule_id=rule_id, payload={"due": due})]

    actions: list[Action] = []
    for token in silence.then:
        if token == "ASHA_VISIT_TASK":
            actions.append(Action(type="ASHA_VISIT_TASK", rule_id=rule_id, payload={"due": clock.now().isoformat()}))
        elif token == "FLAG_NURSE":
            actions.append(Action(type="FLAG_NURSE", rule_id=rule_id, payload={"reason": "silence_after_retry"}))
    return actions
