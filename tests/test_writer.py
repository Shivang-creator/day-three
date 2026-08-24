"""agent/writer.py::render — the kill-switch defense in depth and the
loud-fallback contract. No network: the ADK Runner is mocked at the module
boundary (agent.agent.build_writer / runner_for)."""
from __future__ import annotations

import pytest

from agent import gemini_client, quiet, writer


@pytest.fixture(autouse=True)
def _reset_module_state(monkeypatch):
    monkeypatch.setattr(gemini_client, "_QUOTA_EXHAUSTED", False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEYS", raising=False)
    monkeypatch.delenv("MODEL_OFF", raising=False)
    monkeypatch.setenv("GEMINI_MODEL", "gemini-3.5-flash")


def test_render_falls_back_to_quiet_when_no_key_configured():
    result = writer.render("review", "en", {"name": "X"})
    expected = quiet.render("review", "en", {"name": "X"})
    assert result["text"] == expected["text"]
    assert result["tag"] == "Rule"
    assert result["degraded"] is True


def test_render_falls_back_to_quiet_when_model_off(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    monkeypatch.setenv("MODEL_OFF", "1")
    result = writer.render("come_now", "hi", {"name": "X", "clinic_address": "Y"})
    expected = quiet.render("come_now", "hi", {"name": "X", "clinic_address": "Y"})
    assert result["text"] == expected["text"]
    assert result["degraded"] is True


class _FakePart:
    def __init__(self, text):
        self.text = text


class _FakeContent:
    def __init__(self, text):
        self.parts = [_FakePart(text)]


class _FakeEvent:
    def __init__(self, text):
        self.content = _FakeContent(text)

    def is_final_response(self):
        return True


class _FakeRunner:
    def __init__(self, text):
        self._text = text

    def run(self, *, user_id, session_id, new_message):  # noqa: ARG002
        yield _FakeEvent(self._text)


class _FakeSession:
    id = "sess-1"


class _FakeSessionService:
    def create_session_sync(self, *, app_name, user_id):  # noqa: ARG002
        return _FakeSession()


def test_render_success_path_returns_generated_tag(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    from agent import agent as agent_module

    monkeypatch.setattr(agent_module, "build_writer", lambda *a, **k: object())
    monkeypatch.setattr(agent_module, "runner_for", lambda *a, **k: (_FakeRunner("please come now"), _FakeSessionService()))

    result = writer.render("come_now", "en", {"name": "X", "clinic_address": "Y"})
    assert result == {"text": "please come now", "tag": "Generated", "model": "gemini-3.5-flash", "degraded": False}


def test_render_degrades_loudly_on_agent_exception(monkeypatch, caplog):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    from agent import agent as agent_module

    def boom(*a, **k):
        raise RuntimeError("adk blew up")

    monkeypatch.setattr(agent_module, "build_writer", boom)

    with caplog.at_level("ERROR"):
        result = writer.render("review", "en", {"name": "X"})

    assert result["degraded"] is True
    assert result["tag"] == "Rule"
    assert "adk blew up" in result["reason"]
    assert any("MODEL_FALLBACK" in rec.message for rec in caplog.records)
