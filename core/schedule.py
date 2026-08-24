"""The Contact Ladder (PLAN §4.4, §4.6): the deterministic postnatal
follow-up schedule for one mother's variant (WHO or HBNC). Every function
here is a pure function of a CaseState, a RulePack, and an injected Clock —
no wall clock, no I/O (see tests/test_boundary.py).
"""
from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta

from core.clock import Clock
from core.models import CaseState, ToJsonMixin
from core.rulepack import LadderRung, RulePack


@dataclasses.dataclass(frozen=True)
class Contact(ToJsonMixin):
    rung: str
    due: str  # ISO datetime — the contact window opens
    window_end: str  # ISO datetime — the contact window closes


def _rungs_for_variant(pack: RulePack, variant: str) -> list[LadderRung]:
    rungs = [r for r in pack.ladder if r.variant == variant]
    if not rungs:
        raise ValueError(f"rule pack has no ladder rungs for variant {variant!r}")
    return sorted(rungs, key=lambda r: r.due_hours_after_discharge)


def _to_contact(epoch: datetime, rung: LadderRung) -> Contact:
    due = epoch + timedelta(hours=rung.due_hours_after_discharge)
    window_end = due + timedelta(hours=rung.window_hours)
    return Contact(rung=rung.rung, due=due.isoformat(), window_end=window_end.isoformat())


def next_contact(state: CaseState, pack: RulePack, variant: str) -> Contact | None:
    """The contact that comes after `state.rung` on this variant's ladder.

    If `state.rung` is not itself on this variant's ladder (e.g. a freshly
    enrolled HBNC mother still carries the "D1" placeholder rung from
    ENROLLED, but the HBNC institutional ladder starts at D3), the *first*
    rung on this ladder is treated as next. Returns None once `state.rung`
    is already the last rung — there is nothing further to schedule.
    """
    epoch = datetime.fromisoformat(state.mother.discharge_epoch)
    rungs = _rungs_for_variant(pack, variant)
    names = [r.rung for r in rungs]
    if state.rung not in names:
        return _to_contact(epoch, rungs[0])
    idx = names.index(state.rung)
    if idx + 1 >= len(rungs):
        return None
    return _to_contact(epoch, rungs[idx + 1])


def due_now(state: CaseState, clock: Clock, pack: RulePack) -> Contact | None:
    """Is `state.rung`'s own contact window open at `clock.now()`? Uses
    `state.mother.variant` to pick the ladder. Returns None both when the
    window has not opened yet and when `state.rung` is not on this mother's
    ladder at all (the caller should have already moved past it, e.g. via
    `next_contact`)."""
    epoch = datetime.fromisoformat(state.mother.discharge_epoch)
    rungs = _rungs_for_variant(pack, state.mother.variant)
    match = next((r for r in rungs if r.rung == state.rung), None)
    if match is None:
        return None
    contact = _to_contact(epoch, match)
    now = clock.now()
    if datetime.fromisoformat(contact.due) <= now <= datetime.fromisoformat(contact.window_end):
        return contact
    return None
