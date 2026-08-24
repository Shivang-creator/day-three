"""Routing (PLAN §4.6): turns a Verdict into the concrete Action list a case
needs right now, and turns prolonged silence into a retry-then-escalate
Action list. Pure functions of (verdict/state, clock, pack); `plan()` takes
an optional `booked` set of already-taken slot timestamps so a whole-cohort
sweep (core/sweep.py, T-12) can avoid double-booking clinic slots across
cases evaluated back to back in the same pass.
"""
from __future__ import annotations

from datetime import timedelta

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
) -> list[Action]:
    """Every Action carries a `rule_id` naming why it exists. The Contact
    Ladder keeps moving regardless of route — an urgent visit today does not
    cancel the mother's next scheduled contact."""
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

    ladder_action = _schedule_next_contact_action(state, pack)
    if ladder_action is not None:
        actions.append(ladder_action)

    return actions


def silence_plan(state: CaseState, clock: Clock, pack: RulePack) -> list[Action]:
    """A CONTACT_DUE with no REPLY_RECEIVED inside the window is a signal,
    not a non-event (PLAN §4.6): retry once, then escalate. `state.retry_count`
    (core/events.py::reduce) counts consecutive RETRY_SCHEDULED events since
    the last reply or new contact."""
    silence = pack.silence
    rule_id = silence.silence_id or "SIL-01"

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
