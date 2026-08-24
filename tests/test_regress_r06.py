"""R-06 named regression (RED-TEAM.md Attack 3e / BOARD.md): `POST
/api/reply`'s `keypad` field was a bare `Optional[dict]` — ANY JSON value
per sign reached `core/gate.py::evaluate`, whose true/unknown checks are
`v is True` / `v == "unknown"`; everything else (`null`, `0`, `"no"`,
`"true"` as a string, ...) fell through neither check and was implicitly
treated as an explicit clear, landing on `NEXT_CONTACT` even though the
gate's whole design promise is "only an explicit keypad False can ever
clear a sign" — none of those values IS the literal boolean False.
Fix: `app/main.py::ReplyBody.keypad` is now `dict[str, StrictBool]`,
rejecting anything that isn't a literal JSON true/false with a 422 before
it ever reaches core/.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import PACK, app

client = TestClient(app)


@pytest.mark.parametrize("bad_value", [None, 0, 1, "no", "yes", "true", "false", [], {}])
def test_regress_r06_non_boolean_keypad_values_are_rejected(monkeypatch, bad_value):
    monkeypatch.setenv("MODEL_OFF", "1")
    seed = 90601
    worklist = client.post("/api/seed", json={"seed": seed}).json()["worklist"]
    case_id = worklist[0]["case_id"].split(":", 1)[1]

    r = client.post("/api/reply", params={"seed": seed}, json={"case_id": case_id, "keypad": {"NB_FEVER": bad_value}})
    assert r.status_code == 422, f"value {bad_value!r} must be rejected, not silently treated as a clear (R-06)"


def test_regress_r06_all_false_keypad_still_legitimately_clears(monkeypatch):
    """The fix must not break the real, intended clear path: a genuine
    keypad boolean False for every sign is still a valid NEXT_CONTACT."""
    monkeypatch.setenv("MODEL_OFF", "1")
    seed = 90602
    worklist = client.post("/api/seed", json={"seed": seed}).json()["worklist"]
    case_id = worklist[0]["case_id"].split(":", 1)[1]

    all_false = {s.sign_id: False for s in PACK.signs}
    r = client.post("/api/reply", params={"seed": seed}, json={"case_id": case_id, "keypad": all_false})
    assert r.status_code == 200
    assert r.json()["verdict"]["route"] == "NEXT_CONTACT"


def test_regress_r06_real_boolean_true_still_escalates(monkeypatch):
    monkeypatch.setenv("MODEL_OFF", "1")
    seed = 90603
    worklist = client.post("/api/seed", json={"seed": seed}).json()["worklist"]
    case_id = worklist[0]["case_id"].split(":", 1)[1]
    red_sign = next(s.sign_id for s in PACK.signs if s.severity == "red" and s.sign_id != "M_SELF_HARM")

    keypad = {s.sign_id: False for s in PACK.signs}
    keypad[red_sign] = True
    r = client.post("/api/reply", params={"seed": seed}, json={"case_id": case_id, "keypad": keypad})
    assert r.status_code == 200
    assert r.json()["verdict"]["route"] == "URGENT_FACILITY_NOW"
