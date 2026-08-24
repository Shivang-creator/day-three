from datetime import datetime, timezone
from pathlib import Path

import pytest

from core import slots
from core.clock import FixedClock
from core.gate import evaluate
from core.models import CaseState, Mother, SymptomForm
from core.rulepack import load
from core.routing import plan, silence_plan
from core.schedule import next_contact

PACK = load(Path(__file__).parent.parent / "rules" / "postnatal.v1.json")
EPOCH = "2026-08-24T00:00:00+00:00"


def _mother(variant="WHO") -> Mother:
    return Mother(
        mother_id="m-01", display_name="Asha (synthetic #01)", phone="+91-00000-00001",
        variant=variant, discharge_epoch=EPOCH,
    )


def _state(rung="D1", variant="WHO", retry_count=0) -> CaseState:
    return CaseState(mother=_mother(variant), rung=rung, retry_count=retry_count)


def _clock(dt=datetime(2026, 8, 26, 10, 0, tzinfo=timezone.utc)) -> FixedClock:
    return FixedClock(dt)


def _form(subject="newborn", signs=None):
    return SymptomForm(subject=subject, signs=signs or {}, origin="keypad")


# ------------------------------------------------------------------- slots --


def test_earliest_returns_first_slot_of_the_day_when_urgent():
    clock = _clock(datetime(2026, 8, 26, 0, 0, tzinfo=timezone.utc))
    iso = slots.earliest(clock, frozenset(), PACK, urgent=True)
    assert iso == "2026-08-26T09:00:00+00:00"  # clinic opens 09:00, first (reserved) slot


def test_urgent_uses_reserve_first():
    clock = _clock(datetime(2026, 8, 26, 0, 0, tzinfo=timezone.utc))
    urgent_slot = slots.earliest(clock, frozenset(), PACK, urgent=True)
    routine_slot = slots.earliest(clock, frozenset(), PACK, urgent=False)
    # clinic.urgent_reserve_per_day == 2, slot_minutes == 20: routine must
    # skip the first 2 reserved slots even though nothing is booked yet.
    assert urgent_slot == "2026-08-26T09:00:00+00:00"
    assert routine_slot == "2026-08-26T09:40:00+00:00"
    assert urgent_slot < routine_slot


def test_no_double_booking():
    clock = _clock(datetime(2026, 8, 26, 0, 0, tzinfo=timezone.utc))
    first = slots.earliest(clock, frozenset(), PACK, urgent=True)
    second = slots.earliest(clock, frozenset({first}), PACK, urgent=True)
    assert first != second
    third = slots.earliest(clock, frozenset({first, second}), PACK, urgent=True)
    assert third not in (first, second)


def test_earliest_rolls_over_to_the_next_day_once_full():
    clock = _clock(datetime(2026, 8, 26, 16, 55, tzinfo=timezone.utc))  # 5 min before close
    iso = slots.earliest(clock, frozenset(), PACK, urgent=True)
    assert iso.startswith("2026-08-27")


# -------------------------------------------------------------------- plan --


def test_urgent_yields_four_actions():
    verdict = evaluate(_form(signs={"NB_FEVER": True}), PACK)
    actions = plan(verdict, _state(rung="D1"), _clock(), PACK)
    assert len(actions) == 4
    types = [a.type for a in actions]
    assert types == ["BOOK_SLOT", "PAGE_NURSE", "MESSAGE_MOTHER", "SCHEDULE_CONTACT"]


def test_every_action_carries_a_rule_id():
    verdict = evaluate(_form(signs={"NB_FEVER": True}), PACK)
    actions = plan(verdict, _state(rung="D1"), _clock(), PACK)
    assert all(a.rule_id for a in actions)


def test_urgent_book_slot_uses_the_urgent_reserve():
    clock = _clock(datetime(2026, 8, 26, 0, 0, tzinfo=timezone.utc))
    verdict = evaluate(_form(signs={"NB_FEVER": True}), PACK)
    actions = plan(verdict, _state(rung="D1"), clock, PACK)
    book = next(a for a in actions if a.type == "BOOK_SLOT")
    assert book.payload["slot_iso"] == "2026-08-26T09:00:00+00:00"


def test_urgent_uses_the_reserve_first_inside_plan_too():
    """Regression for the reserve behaviour surfacing correctly through
    plan(), not just the slots module directly: an urgent booking made via
    plan() must land on a reserved slot even when routine bookings already
    occupy the general schedule."""
    clock = _clock(datetime(2026, 8, 26, 0, 0, tzinfo=timezone.utc))
    routine_slot = slots.earliest(clock, frozenset(), PACK, urgent=False)
    verdict = evaluate(_form(signs={"NB_FEVER": True}), PACK)
    actions = plan(verdict, _state(rung="D1"), clock, PACK, booked=frozenset({routine_slot}))
    book = next(a for a in actions if a.type == "BOOK_SLOT")
    assert book.payload["slot_iso"] == "2026-08-26T09:00:00+00:00"


def test_no_double_booking_across_two_plan_calls():
    clock = _clock(datetime(2026, 8, 26, 0, 0, tzinfo=timezone.utc))
    verdict = evaluate(_form(signs={"NB_FEVER": True}), PACK)
    first_actions = plan(verdict, _state(rung="D1"), clock, PACK)
    first_slot = next(a for a in first_actions if a.type == "BOOK_SLOT").payload["slot_iso"]
    second_actions = plan(verdict, _state(rung="D1"), clock, PACK, booked=frozenset({first_slot}))
    second_slot = next(a for a in second_actions if a.type == "BOOK_SLOT").payload["slot_iso"]
    assert first_slot != second_slot


def test_same_day_visit_yields_book_slot_and_message_but_not_page_nurse():
    verdict = evaluate(_form(signs={"NB_SKIN_PUSTULES": True}), PACK)
    actions = plan(verdict, _state(rung="D1"), _clock(), PACK)
    types = {a.type for a in actions}
    assert types == {"BOOK_SLOT", "MESSAGE_MOTHER", "SCHEDULE_CONTACT"}


def test_self_harm_pages_nurse_at_high_priority():
    verdict = evaluate(_form(subject="mother", signs={"M_SELF_HARM": True}), PACK)
    actions = plan(verdict, _state(rung="D1"), _clock(), PACK)
    page = next(a for a in actions if a.type == "PAGE_NURSE")
    assert page.payload["priority"] == "high"


def test_human_review_route_yields_a_human_review_action():
    verdict = evaluate(_form(signs={"NB_FEVER": "unknown"}), PACK)
    actions = plan(verdict, _state(rung="D1"), _clock(), PACK)
    assert any(a.type == "HUMAN_REVIEW" for a in actions)


def test_next_contact_route_only_schedules_the_ladder():
    all_false = {s.sign_id: False for s in PACK.signs}
    verdict = evaluate(_form(signs=all_false), PACK)
    actions = plan(verdict, _state(rung="D1"), _clock(), PACK)
    assert [a.type for a in actions] == ["SCHEDULE_CONTACT"]


def test_plan_schedules_the_actual_next_ladder_contact():
    verdict = evaluate(_form(signs={"NB_FEVER": True}), PACK)
    state = _state(rung="D1", variant="WHO")
    actions = plan(verdict, state, _clock(), PACK)
    schedule = next(a for a in actions if a.type == "SCHEDULE_CONTACT")
    expected = next_contact(state, PACK, "WHO")
    assert schedule.payload["rung"] == expected.rung
    assert schedule.payload["due"] == expected.due


def test_plan_at_the_last_rung_yields_no_schedule_contact_action():
    verdict = evaluate(_form(signs={"NB_FEVER": True}), PACK)
    actions = plan(verdict, _state(rung="D42", variant="WHO"), _clock(), PACK)
    assert not any(a.type == "SCHEDULE_CONTACT" for a in actions)


# ---------------------------------------------------------------- silence --


def test_silence_retry_then_asha_and_flag():
    clock = _clock()
    first = silence_plan(_state(retry_count=0), clock, PACK)
    assert [a.type for a in first] == ["RETRY_CONTACT"]

    second = silence_plan(_state(retry_count=1), clock, PACK)
    assert [a.type for a in second] == ["ASHA_VISIT_TASK", "FLAG_NURSE"]


def test_silence_retry_due_is_six_hours_out():
    clock = _clock(datetime(2026, 8, 26, 10, 0, tzinfo=timezone.utc))
    actions = silence_plan(_state(retry_count=0), clock, PACK)
    assert actions[0].payload["due"] == "2026-08-26T16:00:00+00:00"


def test_silence_actions_carry_the_silence_rule_id():
    actions = silence_plan(_state(retry_count=1), _clock(), PACK)
    assert all(a.rule_id == "SIL-01" for a in actions)
