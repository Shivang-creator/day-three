"""Frozen data shapes shared by the core. Every value that crosses a boundary
(store, API, agent) goes through `.to_json()`, which produces a sorted-key
JSON string — that determinism is what makes byte-identical replay possible.
"""
from __future__ import annotations

import dataclasses
import json
from datetime import datetime
from typing import Any


def _jsonable(value: Any) -> Any:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: _jsonable(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    return value


class ToJsonMixin:
    def to_json(self) -> str:
        return json.dumps(_jsonable(self), sort_keys=True)


@dataclasses.dataclass(frozen=True)
class Mother(ToJsonMixin):
    mother_id: str
    display_name: str
    phone: str
    variant: str  # "WHO" | "HBNC"
    discharge_epoch: str  # ISO datetime string


@dataclasses.dataclass(frozen=True)
class Enrolment(ToJsonMixin):
    case_id: str
    mother_id: str
    namespace: str  # seed, as a string
    epoch: str  # ISO datetime string


@dataclasses.dataclass(frozen=True)
class SymptomForm(ToJsonMixin):
    subject: str  # "newborn" | "mother"
    signs: dict  # sign_id -> True | False | "unknown"
    origin: str  # "keypad" | "free_text" | "nurse" | "synthetic"
    reader: str = "none"  # "none" | "gemini" | "gemma" | "both"
    source_text: str = ""
    reader_confidence: float = 0.0  # display only; gate ignores it


@dataclasses.dataclass(frozen=True)
class Verdict(ToJsonMixin):
    route: str  # URGENT_FACILITY_NOW | SAME_DAY_VISIT | HUMAN_REVIEW_NOW | HUMAN_REVIEW | NEXT_CONTACT
    fired: tuple = ()  # tuple of {"rule_id","signs","source_id","source_quote"}
    unknown: tuple = ()  # sign_ids left unknown
    tag: str = "Rule"


@dataclasses.dataclass(frozen=True)
class Action(ToJsonMixin):
    type: str  # BOOK_SLOT | PAGE_NURSE | FLAG_NURSE | MESSAGE_MOTHER | SCHEDULE_CONTACT |
    # RETRY_CONTACT | ASHA_VISIT_TASK | HUMAN_REVIEW
    rule_id: str
    payload: dict = dataclasses.field(default_factory=dict)


@dataclasses.dataclass(frozen=True)
class CaseState(ToJsonMixin):
    mother: Mother
    rung: str
    next_due: str | None = None
    open_slot: str | None = None
    flags: tuple = ()
    last_reply: str | None = None
    route_history: tuple = ()


@dataclasses.dataclass(frozen=True)
class Decision(ToJsonMixin):
    """The object Quiet Mode diffs — deliberately has no message text."""

    case_id: str
    clock: str
    rung: str
    verdict: Verdict
    actions_without_text: tuple = ()
