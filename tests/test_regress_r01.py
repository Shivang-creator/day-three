"""R-01 named regression (RED-TEAM.md Attack 2 / BOARD.md): a fresh clone
following the README's own `cp .env.example .env.local` step leaves
GEMINI_API_KEY SET to the empty string (not unset). `tools/quiet_diff.py`
used `os.environ.setdefault("GEMINI_API_KEY", ...)` for its mocked model-on
path, which is a no-op when the key is already present-but-empty —
`agent.gemini_client.model_enabled()` then sees a falsy key and
`app/orchestrator.py::_render_message` silently degrades every escalation
to the Quiet template, so the "model on" arm becomes byte-identical to
"model off" and `make quiet-diff` prints "0 prose fields differ" instead of
the README's claimed 4 — even though a real key was never asked for.

Fix: `tools/quiet_diff.py::_run_sweep` now checks truthiness
(`if not os.environ.get("GEMINI_API_KEY")`) instead of using `.setdefault`.
"""
from __future__ import annotations

import os

import pytest

from tools import quiet_diff


@pytest.fixture
def empty_gemini_key(monkeypatch):
    """Simulates the exact state python-dotenv leaves after the README's
    `cp .env.example .env.local` on a fresh clone: GEMINI_API_KEY is SET,
    to the empty string — not absent from os.environ."""
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.delenv("GEMINI_API_KEYS", raising=False)
    monkeypatch.delenv("MODEL_OFF", raising=False)
    yield


def test_regress_r01_quiet_diff_prose_differs_even_with_empty_key_in_environ(empty_gemini_key):
    assert os.environ["GEMINI_API_KEY"] == ""  # precondition: present, falsy — not unset

    result = quiet_diff.run_diff(seed=3, to="D3")

    assert result["decision_changes"] == []
    assert len(result["message_changes"]) > 0, (
        "an empty-but-present GEMINI_API_KEY must not silently collapse the "
        "mocked model-on arm back to the model-off templates (R-01)"
    )
    assert result["summary_line"] == "QUIET DIFF: 0 decision changes · 4 prose fields differ"


def test_regress_r01_empty_key_left_falsy_after_run(empty_gemini_key):
    """The fix must not leak its internal mock key into the real
    environment for any caller running after it (env_backup restore)."""
    quiet_diff.run_diff(seed=3, to="D3")
    assert os.environ.get("GEMINI_API_KEY") == "", "quiet_diff must restore the caller's original env after it runs"
