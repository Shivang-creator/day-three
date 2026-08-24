"""R-05 named regression (RED-TEAM.md Attack 3f / BOARD.md): `POST
/api/seed {"n": 2000}` used to accept an uncapped `n` (200 OK, thousands of
synthetic writes) and only fail later, at the NEXT `/api/advance`, with an
unrelated-looking `500 KeyError` — `core/cohort.py::category_for` always
built its quota-assignment table for `DEFAULT_N=38` regardless of the real
`n`, so any mother index >= 38 crashed `core/sweep.py::run_sweep`. Fix:
`n` is capped at the `/api/seed` boundary (`app/main.py::MAX_SEED_N=200`,
400 beyond), AND `category_for`/`scripted_reply`/`run_sweep` are now
n-aware end to end (defense in depth — the crash is gone even below the
cap, at any `n` the caller actually used).
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_regress_r05_seed_n_over_the_cap_is_rejected_with_400():
    r = client.post("/api/seed", json={"seed": 90501, "n": 2000})
    assert r.status_code == 400
    assert "n" in r.json()["detail"].lower()


def test_regress_r05_seed_n_zero_or_negative_is_rejected_with_400():
    r = client.post("/api/seed", json={"seed": 90502, "n": 0})
    assert r.status_code == 400


def test_regress_r05_a_larger_but_in_bounds_n_survives_advance(monkeypatch):
    """The actual crash the red team hit: n above DEFAULT_N=38 (but within
    the new cap) used to KeyError inside run_sweep. 100 is well past 38,
    well under the 200 cap."""
    monkeypatch.setenv("MODEL_OFF", "1")
    seed_resp = client.post("/api/seed", json={"seed": 90503, "n": 100})
    assert seed_resp.status_code == 200
    assert len(seed_resp.json()["worklist"]) == 100

    advance_resp = client.post("/api/advance", json={"seed": 90503, "to": "D3"})
    assert advance_resp.status_code == 200, (
        f"advance() must not KeyError for a cohort larger than DEFAULT_N=38 (R-05): {advance_resp.text}"
    )
    assert advance_resp.json()["run_summary"]["n_due"] > 0


def test_regress_r05_category_for_is_n_aware():
    from core.cohort import category_for

    # A category assignment built for n=100 can look up an index that a
    # table built for the old hardcoded default (38) would KeyError on.
    result = category_for(3, "mother-63", n=100)
    assert result in ("no_sign", "red_d3", "yellow_d7", "silent_d3")
