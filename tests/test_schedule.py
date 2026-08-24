from datetime import datetime, timezone
from pathlib import Path

import pytest

from core.clock import FixedClock
from core.models import CaseState, Mother
from core.rulepack import load
from core.schedule import Contact, due_now, next_contact

PACK = load(Path(__file__).parent.parent / "rules" / "postnatal.v1.json")

EPOCH = "2026-08-24T00:00:00+00:00"


def _mother(variant: str) -> Mother:
    return Mother(
        mother_id="m-01",
        display_name="Asha (synthetic #01)",
        phone="+91-00000-00001",
        variant=variant,
        discharge_epoch=EPOCH,
    )


def _state(variant: str, rung: str) -> CaseState:
    return CaseState(mother=_mother(variant), rung=rung)


def test_next_contact_after_d1_who_is_d3_at_48_hours():
    contact = next_contact(_state("WHO", "D1"), PACK, "WHO")
    assert contact.rung == "D3"
    assert contact.due == "2026-08-26T00:00:00+00:00"  # +48h


def test_next_contact_returns_none_after_the_last_rung():
    assert next_contact(_state("WHO", "D42"), PACK, "WHO") is None


def test_next_contact_falls_back_to_the_first_rung_when_current_rung_is_off_ladder():
    # An HBNC (institutional) mother is enrolled with the ENROLLED-default
    # rung "D1", which is not on the HBNC ladder (that ladder starts at D3).
    contact = next_contact(_state("HBNC", "D1"), PACK, "HBNC")
    assert contact.rung == "D3"
    assert contact.due == "2026-08-27T00:00:00+00:00"  # +72h


def test_who_and_hbnc_disagree_on_when_d3_is_due():
    who = next_contact(_state("WHO", "D1"), PACK, "WHO")
    hbnc = next_contact(_state("HBNC", "D1"), PACK, "HBNC")
    assert who.rung == hbnc.rung == "D3"
    assert who.due != hbnc.due  # WHO: 48h: HBNC: 72h — two different, non-identical schedules


def test_due_now_returns_none_before_the_window_opens():
    clock = FixedClock(datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc))  # 12h in, D1 due at 24h
    assert due_now(_state("WHO", "D1"), clock, PACK) is None


def test_due_now_returns_the_contact_inside_the_window():
    clock = FixedClock(datetime(2026, 8, 25, 0, 0, tzinfo=timezone.utc))  # exactly 24h in
    contact = due_now(_state("WHO", "D1"), clock, PACK)
    assert contact is not None
    assert contact.rung == "D1"


def test_due_now_returns_none_after_the_window_closes():
    clock = FixedClock(datetime(2026, 8, 27, 0, 0, tzinfo=timezone.utc))  # D1 window closed at 48h
    assert due_now(_state("WHO", "D1"), clock, PACK) is None


def test_due_now_returns_none_when_rung_is_not_on_this_variants_ladder():
    clock = FixedClock(datetime(2026, 8, 24, 0, 0, tzinfo=timezone.utc))
    assert due_now(_state("HBNC", "D1"), clock, PACK) is None


def test_contact_to_json_has_sorted_keys():
    contact = next_contact(_state("WHO", "D1"), PACK, "WHO")
    import json

    parsed = json.loads(contact.to_json())
    assert list(parsed.keys()) == sorted(parsed.keys())
