"""R-02 named regression (RED-TEAM.md Attack 1 / BOARD.md): with
GEMINI_API_KEY left blank (README: "leave it empty and the app runs on
templates") and MODEL_OFF unset/"0", `/api/health` used to report
`model_off: false` — the ONLY field the UI keyed its "templates in use"
strip and footer text off — so nothing anywhere told a judge the app was
degraded. `/api/health` now also reports `model_enabled` (the literal
predicate `app/orchestrator.py` gates every model call on), and the UI
(app/static/app.js::loadHealth) keys its strip/footer off that field
instead. The four writer fallbacks this causes are also now logged
(previously silent — see app/orchestrator.py::_render_message).
"""
from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient

from agent import gemini_client
from app.main import app


@pytest.fixture(autouse=True)
def _reset_quota(monkeypatch):
    monkeypatch.setattr(gemini_client, "_QUOTA_EXHAUSTED", False)
    monkeypatch.setattr(gemini_client, "_QUOTA_EXHAUSTED_UNTIL", 0.0)


def test_regress_r02_blank_key_reports_model_disabled_in_health(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.delenv("GEMINI_API_KEYS", raising=False)
    monkeypatch.delenv("MODEL_OFF", raising=False)

    client = TestClient(app)
    body = client.get("/api/health").json()

    assert body["model_off"] is False, "precondition: the literal env var is unset/0"
    assert body["model_enabled"] is False, (
        "a blank GEMINI_API_KEY must show up as model_enabled=False even though MODEL_OFF is not set (R-02)"
    )


def test_regress_r02_writer_fallback_is_logged_not_silent(monkeypatch, caplog):
    """Previously: app/orchestrator.py::_render_message's `not
    model_enabled()` branch returned the Quiet template with zero log
    output for an escalation intent — the ONLY branch of that function that
    didn't log its own fallback."""
    from app import orchestrator

    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.delenv("GEMINI_API_KEYS", raising=False)
    monkeypatch.delenv("MODEL_OFF", raising=False)

    with caplog.at_level(logging.ERROR, logger="app.orchestrator"):
        msg = orchestrator._render_message(
            intent="come_now",
            lang="hi",
            facts={"name": "Test Mother"},
            store=None,
            pack=None,
            quiet_flag=False,
            budget={"used": 0, "limit": 12},
        )

    assert msg["tag"] == "Rule"  # degraded to the Quiet template
    assert any("MODEL_FALLBACK" in r.message for r in caplog.records), (
        "a blank-key escalation fallback must log MODEL_FALLBACK, not degrade silently (R-02)"
    )
