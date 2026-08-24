"""R-03 named regression (RED-TEAM.md Attack 3f / BOARD.md): re-running
`/api/advance` at the SAME target clock used to escalate a silent mother
straight to ASHA_VISIT_TASK + FLAG_NURSE on the second call, even though no
time had passed since the first call scheduled her 6h retry —
`core/routing.py::silence_plan` only checked `state.retry_count <
max_retries`, never whether the retry it had already scheduled was
actually due yet. `core/sweep.py`'s own docstring promises "calling this
repeatedly with an unchanged snapshot and clock [is] a safe no-op" — this
broke that promise specifically for a case that had just gone silent.

RED-TEAM.md's own note: "Existing idempotency test only inspects
worklist[0] (an URGENT row)" — this test walks every silent mother's
`flags`/`route`, not just the worklist's first row, and re-advances at the
IDENTICAL clock (not a later one) to isolate the bug from the (correct)
behaviour of retrying again after time actually passes.
"""
from __future__ import annotations

from pathlib import Path

from app import orchestrator
from core.rulepack import load as load_rulepack
from store.memory import MemoryStore

RULES_PATH = Path(__file__).resolve().parent.parent / "rules" / "postnatal.v1.json"


def _silent_mothers(store, pack, seed):
    rows = orchestrator.worklist(store, pack, seed)
    return {r["case_id"]: r for r in rows if r["route"] == "SILENCE"}


def test_regress_r03_second_sweep_at_the_same_clock_does_not_escalate_silence(monkeypatch):
    monkeypatch.setenv("MODEL_OFF", "1")
    pack = load_rulepack(RULES_PATH)
    store = MemoryStore()
    seed = 9101

    orchestrator.enroll(store, pack, seed, n=38)
    first = orchestrator.advance(store, pack, seed, "D3")
    assert first["run_summary"]["n_silence"] > 0, "seed's D3 sweep must produce at least one silent mother to test this"

    silent_after_first = _silent_mothers(store, pack, seed)
    assert silent_after_first, "precondition: at least one SILENCE row after the first sweep"
    for row in silent_after_first.values():
        assert "asha_visit_task" not in row["flags"], "a mother's FIRST silent sweep must never escalate immediately"

    # Re-run advance() at the exact same target clock (idempotent call —
    # NOT a later re-advance): must not move any silent mother past the
    # retry she was just given.
    second = orchestrator.advance(store, pack, seed, "D3")
    assert second["run_summary"]["n_silence"] == first["run_summary"]["n_silence"]

    silent_after_second = _silent_mothers(store, pack, seed)
    for case_id, row in silent_after_second.items():
        assert "asha_visit_task" not in row["flags"], (
            f"{case_id}: escalated to ASHA on a second sweep at an UNCHANGED clock — "
            "the 6h retry window cannot have elapsed (R-03)"
        )
        assert "silence_after_retry" not in row["flags"], f"{case_id}: FLAG_NURSE fired before the retry window elapsed (R-03)"


def test_regress_r03_escalation_still_happens_once_the_retry_window_actually_elapses(monkeypatch):
    """The other half of the guarantee: this is a timing fix, not a
    disabling of escalation altogether — advancing PAST the 6h retry due
    time must still reach ASHA/FLAG_NURSE for a mother who stays silent."""
    monkeypatch.setenv("MODEL_OFF", "1")
    pack = load_rulepack(RULES_PATH)
    store = MemoryStore()
    seed = 9102

    orchestrator.enroll(store, pack, seed, n=38)
    orchestrator.advance(store, pack, seed, "D3")
    silent_ids = list(_silent_mothers(store, pack, seed).keys())
    assert silent_ids

    # 7 hours later (past the 6h retry_after_hours), same rung's window
    # still open — re-advance with an explicit ISO clock past the retry due.
    from datetime import datetime, timedelta

    d3_iso = store.get_meta(f"clock:{seed}")["iso"]
    later = (datetime.fromisoformat(d3_iso) + timedelta(hours=7)).isoformat()
    orchestrator.advance(store, pack, seed, later)

    rows_after = orchestrator.worklist(store, pack, seed)
    by_id = {r["case_id"]: r for r in rows_after}
    escalated = [cid for cid in silent_ids if "asha_visit_task" in by_id[cid]["flags"]]
    assert escalated, "once the 6h retry window has genuinely elapsed, silence must still escalate to ASHA/FLAG_NURSE"
