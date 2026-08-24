import dataclasses
import json

import pytest

from core.events import Event, idempotency_key, reduce
from core.models import Mother

MOTHER = Mother(
    mother_id="m-01",
    display_name="Asha (synthetic #01)",
    phone="+91-00000-00001",
    variant="WHO",
    discharge_epoch="2026-08-24T00:00:00+00:00",
)


def _enrolled(seq: int, case_id: str = "case-01", rung: str = "D1") -> Event:
    return Event(
        seq=seq,
        case_id=case_id,
        at="2026-08-24T00:00:00+00:00",
        type="ENROLLED",
        payload={"mother": dataclasses.asdict(MOTHER), "rung": rung},
        tag="Simulated",
    )


def test_event_to_json_has_sorted_keys():
    e = _enrolled(0)
    raw = e.to_json()
    parsed = json.loads(raw)
    assert list(parsed.keys()) == sorted(parsed.keys())
    # re-serialising the parsed dict with sort_keys should equal the original
    assert json.dumps(parsed, sort_keys=True) == raw


def test_idempotency_key_is_deterministic():
    a = idempotency_key("case-01", "2026-08-27T00:00:00+00:00", "VERDICT", "D3")
    b = idempotency_key("case-01", "2026-08-27T00:00:00+00:00", "VERDICT", "D3")
    assert a == b


def test_idempotency_key_differs_by_case_id():
    a = idempotency_key("case-01", "2026-08-27T00:00:00+00:00", "VERDICT", "D3")
    b = idempotency_key("case-02", "2026-08-27T00:00:00+00:00", "VERDICT", "D3")
    assert a != b


def test_reduce_requires_an_enrolled_event():
    with pytest.raises(ValueError):
        reduce([])


def test_reduce_builds_case_state_from_enrolled_event():
    state = reduce([_enrolled(0)])
    assert state.mother.mother_id == "m-01"
    assert state.rung == "D1"
    assert state.route_history == ()


def test_reduce_sorts_out_of_order_events_by_seq():
    verdict_first = Event(
        seq=2,
        case_id="case-01",
        at="2026-08-27T00:00:00+00:00",
        type="VERDICT",
        payload={"route": "URGENT_FACILITY_NOW"},
        tag="Rule",
        rule_id="NB-03",
    )
    rescheduled = Event(
        seq=1,
        case_id="case-01",
        at="2026-08-26T00:00:00+00:00",
        type="CONTACT_RESCHEDULED",
        payload={"rung": "D3", "due": "2026-08-27T00:00:00+00:00"},
        tag="Rule",
    )
    # deliberately appended out of seq order
    state = reduce([verdict_first, _enrolled(0), rescheduled])
    assert state.rung == "D3"
    assert state.route_history == ("URGENT_FACILITY_NOW",)


def test_reduce_accumulates_route_history_across_multiple_verdicts():
    events = [
        _enrolled(0),
        Event(
            seq=1,
            case_id="case-01",
            at="2026-08-27T00:00:00+00:00",
            type="VERDICT",
            payload={"route": "NEXT_CONTACT"},
            tag="Rule",
        ),
        Event(
            seq=2,
            case_id="case-01",
            at="2026-08-31T00:00:00+00:00",
            type="VERDICT",
            payload={"route": "URGENT_FACILITY_NOW"},
            tag="Rule",
            rule_id="NB-03",
        ),
    ]
    state = reduce(events)
    assert state.route_history == ("NEXT_CONTACT", "URGENT_FACILITY_NOW")
