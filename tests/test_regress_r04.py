"""R-04 named regression (RED-TEAM.md Attack 3f / BOARD.md): `POST
/api/advance` with a naive ISO datetime (no timezone, e.g.
"1999-01-01T00:00:00") passes `_is_iso` (datetime.fromisoformat accepts
naive datetimes) but `core.clock.FixedClock` itself rejects it. The bug:
`app/orchestrator.py::advance()` used to `store.set_meta(...)` the
poisoned clock BEFORE constructing/validating the FixedClock, so a
rejected advance still left the namespace's stored clock pointing at the
bad value — every LATER `/api/reply` on that seed then 400'd too (with the
same misleading "naive datetime" error, not a 404/other clear signal),
until a successful advance happened to overwrite it. Fix: build+validate
the FixedClock first; only persist the clock once construction succeeds.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import PACK, STORE, app

client = TestClient(app)


def test_regress_r04_a_rejected_naive_iso_advance_never_poisons_the_namespace_clock(monkeypatch):
    monkeypatch.setenv("MODEL_OFF", "1")
    seed = 90104

    client.post("/api/seed", json={"seed": seed})
    clock_before = STORE.get_meta(f"clock:{seed}")
    assert clock_before is not None

    bad = client.post("/api/advance", json={"seed": seed, "to": "1999-01-01T00:00:00"})
    assert bad.status_code == 400

    clock_after_rejected_advance = STORE.get_meta(f"clock:{seed}")
    assert clock_after_rejected_advance == clock_before, (
        "a rejected naive-ISO advance must not overwrite the namespace's stored clock (R-04)"
    )


def test_regress_r04_reply_still_works_after_a_rejected_advance(monkeypatch):
    """The other half of the same guarantee: with the clock left intact,
    /api/reply for a case on this seed must not 400 as collateral damage."""
    monkeypatch.setenv("MODEL_OFF", "1")
    seed = 90105

    worklist = client.post("/api/seed", json={"seed": seed}).json()["worklist"]
    case_id = worklist[0]["case_id"].split(":", 1)[1]

    bad = client.post("/api/advance", json={"seed": seed, "to": "1999-01-01T00:00:00"})
    assert bad.status_code == 400

    all_signs = {s.sign_id: False for s in PACK.signs}
    reply = client.post("/api/reply", params={"seed": seed}, json={"case_id": case_id, "keypad": all_signs})
    assert reply.status_code == 200, (
        f"a reply on this seed must not 400 as collateral damage from an earlier rejected advance (R-04): {reply.text}"
    )
