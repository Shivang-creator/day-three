"""J-07 named regression (.crew/deliverables/JUDGE-REPORT.md, pc-test-user
T-28, confirmed by pc-debugger): replying to the SAME case multiple times
in one sitting (none of which advance the clock) used to fast-forward the
case's Contact Ladder rung one full step per reply — `app/orchestrator.py`
called `core.routing.plan()` unconditionally on every `/api/reply`, and
`plan()` always appended a `SCHEDULE_CONTACT` action for the NEXT rung
(`core.routing._schedule_next_contact_action`), which `core/events.py`'s
reducer folds straight into `state.rung`. Four replies in a row therefore
skipped straight to the ladder's LAST rung (D42), never actually checking
in at D14/D21/D28 — not just a cosmetic display bug, a silently skipped
follow-up schedule.

Fix: `app/orchestrator.py::reply()` now only lets the ladder advance
(`routing.plan(..., advance_ladder=...)`) when this reply is answering a
contact that is genuinely due at the current clock
(`core.schedule.due_now`); an off-schedule reply's verdict-driven actions
(BOOK_SLOT/PAGE_NURSE/HUMAN_REVIEW/...) still apply exactly as before.
"""
from __future__ import annotations

from pathlib import Path

from app import orchestrator
from core.rulepack import load as load_rulepack
from store.memory import MemoryStore

RULES_PATH = Path(__file__).resolve().parent.parent / "rules" / "postnatal.v1.json"


def test_regress_j07_four_replies_at_the_same_clock_do_not_skip_ladder_rungs(monkeypatch):
    monkeypatch.setenv("MODEL_OFF", "1")
    pack = load_rulepack(RULES_PATH)
    store = MemoryStore()
    seed = 90701

    orchestrator.enroll(store, pack, seed, n=1)
    orchestrator.advance(store, pack, seed, "D3")

    rung_before = orchestrator.case_detail(store, pack, seed, "mother-00")["rung"]

    all_false = {s.sign_id: False for s in pack.signs}
    orchestrator.reply(store, pack, seed, "mother-00", keypad=all_false)
    orchestrator.reply(store, pack, seed, "mother-00", text="feeling fine today")
    orchestrator.reply(store, pack, seed, "mother-00", text="still fine")
    orchestrator.reply(store, pack, seed, "mother-00", text="all good")

    rung_after = orchestrator.case_detail(store, pack, seed, "mother-00")["rung"]

    assert rung_after == rung_before, (
        f"four replies with the clock unchanged must not move the rung at all (was {rung_before!r}, "
        f"now {rung_after!r}) — J-07"
    )
    assert rung_after != "D42", "must never fast-forward straight to the ladder's last rung from replies alone"


def test_regress_j07_ladder_still_advances_when_a_reply_genuinely_answers_a_due_contact(monkeypatch):
    """The other half of the guarantee: this is a timing fix, not a removal
    of the ladder-advance mechanism — a reply that DOES answer a contact
    due right now must still move the ladder forward, same as before.

    Uses a SILENT mother specifically: `advance()`'s own sweep only
    auto-resolves (and ladder-advances) a case whose scripted reply exists;
    a silent mother's rung is left exactly where CONTACT_DUE set it
    (core/routing.py's silence path never touches the ladder), so she is
    still genuinely "due" at the same clock when this test replies for her
    "late" — the real-world shape of a mother who finally answers."""
    monkeypatch.setenv("MODEL_OFF", "1")
    pack = load_rulepack(RULES_PATH)
    store = MemoryStore()
    seed = 90703

    orchestrator.enroll(store, pack, seed, n=38)
    orchestrator.advance(store, pack, seed, "D3")

    rows = orchestrator.worklist(store, pack, seed)
    silent_row = next(r for r in rows if r["route"] == "SILENCE")
    bare_case_id = silent_row["case_id"].split(":", 1)[1]
    rung_before = silent_row["rung"]
    assert rung_before == "D3"

    all_false = {s.sign_id: False for s in pack.signs}
    orchestrator.reply(store, pack, seed, bare_case_id, keypad=all_false)

    rung_after = orchestrator.case_detail(store, pack, seed, bare_case_id)["rung"]
    assert rung_after != rung_before, "a reply answering a contact genuinely due now must still advance the ladder"
