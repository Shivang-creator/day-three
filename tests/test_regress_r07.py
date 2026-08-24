"""R-07 named regression (RED-TEAM.md Attack 3f / BOARD.md, NIT): `GET
/api/replay?seed=&clock=D99` (an unknown rung) raised a bare `ValueError`
from `app/orchestrator.py::_target_iso_for_rung` all the way out to FastAPI
as an unhandled 500 — every other route that can hit the same validation
(`/api/advance`) already maps `ValueError` to a 400. `/api/replay` now does
too.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_regress_r07_replay_with_an_unknown_clock_rung_is_400_not_500(monkeypatch):
    monkeypatch.setenv("MODEL_OFF", "1")
    r = client.get("/api/replay", params={"seed": 3, "clock": "D99"})
    assert r.status_code == 400
    assert "D99" in r.json()["detail"]


def test_regress_r07_replay_with_a_known_rung_still_works(monkeypatch):
    monkeypatch.setenv("MODEL_OFF", "1")
    r = client.get("/api/replay", params={"seed": 3, "clock": "D3"})
    assert r.status_code == 200
    assert r.json()["decision_changes"] == 0
