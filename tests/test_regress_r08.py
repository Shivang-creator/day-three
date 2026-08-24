"""R-08 named regression (RED-TEAM.md Attack 1 / BOARD.md): a single round
where every configured Gemini key comes back 429 used to set
`agent.gemini_client._QUOTA_EXHAUSTED = True` for the rest of the PROCESS's
life — one transient burst-rate 429 permanently silenced the free-text
reader (self-harm text degrading to HUMAN_REVIEW forever), with nothing in
`/api/health` to show it. Fix: the exhaustion is now time-boxed
(`quota_exhausted()` self-clears after a bounded cool-down, honouring the
API's own Retry-After when given one) and surfaced via
`agent.gemini_client.quota_exhausted()` / `/api/health`'s `quota_exhausted`
field.
"""
from __future__ import annotations

import pytest

from agent import gemini_client


class Fake429(Exception):
    code = 429


class Fake429WithRetryAfter(Exception):
    code = 429

    def __init__(self, retry_after):
        super().__init__("rate limited")
        self.retry_after = retry_after


@pytest.fixture(autouse=True)
def _reset_module_state(monkeypatch):
    monkeypatch.setattr(gemini_client, "_QUOTA_EXHAUSTED", False)
    monkeypatch.setattr(gemini_client, "_QUOTA_EXHAUSTED_UNTIL", 0.0)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEYS", raising=False)
    monkeypatch.delenv("MODEL_OFF", raising=False)
    monkeypatch.delenv("QUOTA_COOLDOWN_S", raising=False)
    monkeypatch.setenv("GEMINI_MODEL", "gemini-3.5-flash")


def test_regress_r08_quota_exhaustion_self_clears_after_cooldown(monkeypatch):
    """The core claim: exhaustion is bounded, not permanent for the process."""
    monkeypatch.setenv("GEMINI_API_KEYS", "key-one,key-two")
    monkeypatch.setenv("QUOTA_COOLDOWN_S", "0.05")  # 50ms — fast test, still a real cool-down
    monkeypatch.setattr(gemini_client, "_call", lambda *a, **k: (_ for _ in ()).throw(Fake429("quota exceeded")))

    first = gemini_client.generate_json("prompt", {"type": "object"})
    assert first["degraded"] is True
    assert gemini_client.quota_exhausted() is True

    import time

    time.sleep(0.08)  # past the 50ms cool-down

    assert gemini_client.quota_exhausted() is False, "quota flag must self-clear after its cool-down (R-08)"

    calls = []
    monkeypatch.setattr(gemini_client, "_call", lambda *a, **k: calls.append(1) or {"text": "ok again"})
    second = gemini_client.generate_json("prompt", {"type": "object"})
    assert second["degraded"] is False, "a call after the cool-down must reach the network again, not fail fast forever"
    assert calls == [1]


def test_regress_r08_retry_after_from_the_api_extends_the_cooldown(monkeypatch):
    """A 429 that names its own Retry-After must not be shortened to the
    module's default cool-down — the longer of the two wins."""
    monkeypatch.setenv("GEMINI_API_KEYS", "key-one")
    monkeypatch.setenv("QUOTA_COOLDOWN_S", "0.01")
    monkeypatch.setattr(gemini_client, "_call", lambda *a, **k: (_ for _ in ()).throw(Fake429WithRetryAfter(0.2)))

    gemini_client.generate_json("prompt", {"type": "object"})
    assert gemini_client.quota_exhausted() is True
    assert gemini_client.quota_retry_after_s() > 0.05, "the API's own Retry-After (0.2s) must not be discarded for the shorter default"


def test_regress_r08_quota_exhausted_visible_via_health(monkeypatch):
    """R-02/R-08: the flag must be readable, not just internal — this is
    what /api/health reports as `quota_exhausted`."""
    monkeypatch.setenv("GEMINI_API_KEYS", "key-one")
    assert gemini_client.quota_exhausted() is False

    monkeypatch.setattr(gemini_client, "_call", lambda *a, **k: (_ for _ in ()).throw(Fake429("quota exceeded")))
    gemini_client.generate_json("prompt", {"type": "object"})
    assert gemini_client.quota_exhausted() is True
