import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from core.clock import FixedClock
from core.cohort import CATEGORIES, category_for, generate
from core.events import Event
from core.rulepack import load
from core.sweep import SILENCE_ROUTE, run_sweep

PACK = load(Path(__file__).parent.parent / "rules" / "postnatal.v1.json")
EPOCH_DT = datetime(2026, 8, 24, 0, 0, tzinfo=timezone.utc)
EPOCH = EPOCH_DT.isoformat()


def test_seed_is_reproducible():
    a = [m.to_json() for m in generate(3)]
    b = [m.to_json() for m in generate(3)]
    assert a == b


def test_generate_default_n_is_38():
    assert len(generate(3)) == 38


def test_display_names_are_marked_synthetic():
    assert "synthetic" in generate(3)[0].display_name


def test_phones_are_non_dialable():
    for m in generate(3):
        assert re.fullmatch(r"\+91-00000-000\d\d", m.phone)


def test_category_mix_is_within_expected_bounds():
    mothers = generate(3)
    counts = {c: 0 for c in CATEGORIES}
    for m in mothers:
        counts[category_for(3, m.mother_id)] += 1
    # ~70/10/10/10 over 38 mothers — loose bounds so this isn't flaky, but
    # tight enough to catch a badly broken weighting (e.g. all one category).
    assert counts["no_sign"] >= len(mothers) * 0.5
    for minority in ("red_d3", "yellow_d7", "silent_d3"):
        assert counts[minority] >= 1


def _enrolled_at_d3(case_id: str, mother, due_iso: str) -> list[Event]:
    return [
        Event(seq=0, case_id=case_id, at=EPOCH, type="ENROLLED",
              payload={"mother": {
                  "mother_id": mother.mother_id, "display_name": mother.display_name,
                  "phone": mother.phone, "variant": mother.variant, "discharge_epoch": mother.discharge_epoch,
              }, "rung": "D1"}, tag="Simulated"),
        Event(seq=1, case_id=case_id, at=due_iso, type="CONTACT_DUE",
              payload={"rung": "D3", "due": due_iso}, tag="Rule"),
    ]


def _seed3_snapshot() -> dict[str, list[Event]]:
    # +72h lands exactly on the WHO D3 window's close (due 48h + window 24h)
    # and the HBNC D3 window's open (due 72h) simultaneously, so every
    # mother regardless of variant is due right now.
    due_iso = (EPOCH_DT + timedelta(hours=72)).isoformat()
    snapshot = {}
    for m in generate(3):
        case_id = f"3:{m.mother_id}"
        snapshot[case_id] = _enrolled_at_d3(case_id, m, due_iso)
    return snapshot


def test_sweep_on_seed_3_at_d3_yields_at_least_one_urgent_and_one_silent():
    clock = FixedClock(EPOCH_DT + timedelta(hours=72))
    result = run_sweep(_seed3_snapshot(), clock, PACK)
    routes = [d.verdict.route for d in result.decisions]
    assert len(result.decisions) == 38
    assert "URGENT_FACILITY_NOW" in routes
    assert SILENCE_ROUTE in routes


def test_sweep_decisions_json_is_stable_across_two_runs():
    clock = FixedClock(EPOCH_DT + timedelta(hours=72))
    snapshot = _seed3_snapshot()
    first = [d.to_json() for d in run_sweep(snapshot, clock, PACK).decisions]
    second = [d.to_json() for d in run_sweep(snapshot, clock, PACK).decisions]
    assert first == second


def test_sweep_never_double_books_urgent_slots():
    clock = FixedClock(EPOCH_DT + timedelta(hours=72))
    result = run_sweep(_seed3_snapshot(), clock, PACK)
    slots = [a.payload["slot_iso"] for a in result.actions if a.type == "BOOK_SLOT"]
    assert len(slots) == len(set(slots))


def test_sweep_skips_cases_with_no_open_window():
    # D1 is due at +24h, not +72h — nothing should fire for this case yet.
    clock = FixedClock(EPOCH_DT + timedelta(hours=72))
    m = generate(3)[0]
    case_id = f"3:{m.mother_id}"
    events = [
        Event(seq=0, case_id=case_id, at=EPOCH, type="ENROLLED",
              payload={"mother": {
                  "mother_id": m.mother_id, "display_name": m.display_name,
                  "phone": m.phone, "variant": m.variant, "discharge_epoch": m.discharge_epoch,
              }, "rung": "D1"}, tag="Simulated"),
    ]
    result = run_sweep({case_id: events}, clock, PACK)
    assert result.decisions == ()
