"""Deterministic clinic slot booking (PLAN §4.6). Pure function of an
injected clock, a set of already-booked slot timestamps, and the pack's
clinic table — no I/O, no wall clock.

Slot times are computed in whatever tzinfo the injected Clock returns (this
build runs entirely on a simulated UTC clock — see core/clock.py); the
clinic table's `tz` field is descriptive metadata for display, not used for
a real IANA conversion here.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta

from core.clock import Clock
from core.rulepack import RulePack


def _day_slots(day: date, pack: RulePack, tzinfo) -> list[datetime]:
    clinic = pack.clinic
    day_open = datetime.combine(day, time.fromisoformat(clinic.open), tzinfo=tzinfo)
    day_close = datetime.combine(day, time.fromisoformat(clinic.close), tzinfo=tzinfo)
    slots: list[datetime] = []
    t = day_open
    step = timedelta(minutes=clinic.slot_minutes)
    while t < day_close:
        slots.append(t)
        t += step
    return slots


def earliest(clock: Clock, booked: frozenset[str] | set[str], pack: RulePack, urgent: bool) -> str:
    """The earliest free clinic slot at or after clock.now(), as an ISO
    datetime string. `booked` is the set of slot ISO strings already taken
    (across the whole sweep, not just this one case — callers doing many
    bookings in one pass should thread the growing set through, see
    core/routing.py::plan). The first `clinic.urgent_reserve_per_day` slots
    of each day are reserved: an urgent booking may use them (and will,
    since they are also the day's earliest), a non-urgent booking skips
    them entirely, even if it would otherwise leave the reserve empty.
    """
    now = clock.now()
    reserve_n = pack.clinic.urgent_reserve_per_day
    day = now.date()
    while True:
        day_slots = _day_slots(day, pack, now.tzinfo)
        candidates = [t for i, t in enumerate(day_slots) if urgent or i >= reserve_n]
        for t in candidates:
            if t < now:
                continue
            iso = t.isoformat()
            if iso not in booked:
                return iso
        day = day + timedelta(days=1)
