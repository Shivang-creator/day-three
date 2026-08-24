"""The append-only event log and its reducer. Case state is always
`reduce(events)` — never a mutable status flag — so replay from the log is
the only source of truth (PLAN §4.3).
"""
from __future__ import annotations

import dataclasses
import hashlib
from typing import Any

from core.models import CaseState, Mother, ToJsonMixin

EVENT_TYPES = frozenset(
    {
        "ENROLLED",
        "CONTACT_DUE",
        "MESSAGE_QUEUED",
        "REPLY_RECEIVED",
        "FORM_READ",
        "VERDICT",
        "SLOT_BOOKED",
        "NURSE_PAGED",
        "NURSE_FLAGGED",
        "CONTACT_RESCHEDULED",
        "RETRY_SCHEDULED",
        "ASHA_VISIT_TASK",
        "HUMAN_REVIEW",
        "CLOCK_SET",
        "MODEL_FALLBACK",
    }
)

TAGS = frozenset({"Observed", "Rule", "Simulated", "Generated"})


@dataclasses.dataclass(frozen=True)
class Event(ToJsonMixin):
    seq: int
    case_id: str
    at: str  # ISO datetime string
    type: str
    payload: dict
    tag: str  # Observed | Rule | Simulated | Generated
    rule_id: str | None = None
    source: dict | None = None
    idempotency_key: str = ""


def idempotency_key(case_id: str, clock_iso: str, type_: str, rung: str = "") -> str:
    """sha256(case_id | clock_iso | type | rung) — stable for the same inputs,
    so a retried append is a provable no-op (PLAN §4.2)."""
    raw = "|".join([case_id, clock_iso, type_, rung])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def reduce(events: list[Event]) -> CaseState:
    """Fold the ordered event log into a CaseState. Raises ValueError if there
    is no ENROLLED event — a case cannot exist without one."""
    mother: Mother | None = None
    rung = ""
    next_due: str | None = None
    open_slot: str | None = None
    flags: list[str] = []
    last_reply: str | None = None
    route_history: list[str] = []

    for e in sorted(events, key=lambda ev: ev.seq):
        if e.type == "ENROLLED":
            mother = Mother(**e.payload["mother"])
            rung = e.payload.get("rung", "D1")
        elif e.type == "CONTACT_DUE":
            rung = e.payload.get("rung", rung)
            next_due = e.payload.get("due", next_due)
        elif e.type == "CONTACT_RESCHEDULED":
            rung = e.payload.get("rung", rung)
            next_due = e.payload.get("due", next_due)
        elif e.type == "RETRY_SCHEDULED":
            next_due = e.payload.get("due", next_due)
        elif e.type == "REPLY_RECEIVED":
            last_reply = e.payload.get("text") or e.payload.get("summary")
        elif e.type == "VERDICT":
            route = e.payload.get("route")
            if route:
                route_history.append(route)
        elif e.type == "SLOT_BOOKED":
            open_slot = e.payload.get("slot_iso", open_slot)
        elif e.type == "NURSE_FLAGGED":
            flags.append(e.payload.get("reason", "flagged"))
        elif e.type == "HUMAN_REVIEW":
            flags.append(e.payload.get("reason", "human_review"))
        elif e.type == "ASHA_VISIT_TASK":
            flags.append("asha_visit_task")

    if mother is None:
        raise ValueError("cannot reduce: case has no ENROLLED event")

    return CaseState(
        mother=mother,
        rung=rung,
        next_due=next_due,
        open_slot=open_slot,
        flags=tuple(flags),
        last_reply=last_reply,
        route_history=tuple(route_history),
    )
