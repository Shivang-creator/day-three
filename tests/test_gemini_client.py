"""agent/gemini_client.py (T-17, PLAN §4.9). Network is mocked at the module
boundary (`gemini_client._call`) per T-17's own context note — no test here
ever touches google.genai or the network.
"""
from __future__ import annotations

import pytest

from agent import gemini_client


class Fake429(Exception):
    code = 429


class FakeTimeout(Exception):
    pass


class FakeStore:
    """Minimal duck-typed cache: exactly the two methods gemini_client
    actually calls, nothing else — proves the module doesn't need the real
    Store, just something cache-shaped."""

    def __init__(self):
        self._cache: dict[str, dict] = {}

    def cache_get(self, key):
        return self._cache.get(key)

    def cache_put(self, key, value):
        self._cache[key] = value


@pytest.fixture(autouse=True)
def _reset_module_state(monkeypatch):
    # _QUOTA_EXHAUSTED is process-wide by design; tests must not leak it.
    monkeypatch.setattr(gemini_client, "_QUOTA_EXHAUSTED", False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEYS", raising=False)
    monkeypatch.delenv("MODEL_OFF", raising=False)
    monkeypatch.setenv("GEMINI_MODEL", "gemini-3.5-flash")


def test_model_enabled_requires_a_key():
    assert gemini_client.model_enabled() is False


def test_model_enabled_true_with_key_and_no_kill_switch(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    assert gemini_client.model_enabled() is True


def test_model_off_disables_even_with_a_key(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    monkeypatch.setenv("MODEL_OFF", "1")
    assert gemini_client.model_enabled() is False


def test_no_key_returns_degraded_without_calling_network(monkeypatch):
    calls = []
    monkeypatch.setattr(gemini_client, "_call", lambda *a, **k: calls.append(1) or {})
    result = gemini_client.generate_json("prompt", {"type": "object"})
    assert result["degraded"] is True
    assert "key" in result["reason"].lower()
    assert calls == []


def test_model_off_returns_degraded_without_calling_network(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    monkeypatch.setenv("MODEL_OFF", "1")
    calls = []
    monkeypatch.setattr(gemini_client, "_call", lambda *a, **k: calls.append(1) or {})
    result = gemini_client.generate_json("prompt", {"type": "object"})
    assert result["degraded"] is True
    assert result["reason"] == "MODEL_OFF=1"
    assert calls == []


def test_timeout_returns_degraded_and_does_not_cache(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    monkeypatch.setattr(gemini_client, "_call", lambda *a, **k: (_ for _ in ()).throw(FakeTimeout("timed out")))
    store = FakeStore()
    result = gemini_client.generate_json("prompt", {"type": "object"}, store=store)
    assert result["degraded"] is True
    assert "FakeTimeout" in result["reason"]
    assert store._cache == {}


def test_success_returns_undegraded_result_and_caches(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    monkeypatch.setattr(gemini_client, "_call", lambda *a, **k: {"text": "hello"})
    store = FakeStore()
    result = gemini_client.generate_json("prompt", {"type": "object"}, store=store)
    assert result["degraded"] is False
    assert result["text"] == "hello"
    assert result["model"] == "gemini-3.5-flash"
    assert len(store._cache) == 1


def test_cache_hit_skips_the_network_entirely(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    calls = []
    monkeypatch.setattr(gemini_client, "_call", lambda *a, **k: calls.append(1) or {"text": "should not run"})
    store = FakeStore()
    key = gemini_client._cache_key("gemini-3.5-flash", "prompt", {"type": "object"})
    store.cache_put(key, {"text": "cached", "degraded": False, "model": "gemini-3.5-flash"})
    result = gemini_client.generate_json("prompt", {"type": "object"}, store=store)
    assert result["text"] == "cached"
    assert calls == []


def test_429_round_robins_to_the_next_key(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEYS", "key-one,key-two")
    seen_keys = []

    def fake_call(model, api_key, prompt, schema, timeout_s):
        seen_keys.append(api_key)
        if api_key == "key-one":
            raise Fake429("rate limited")
        return {"text": "ok from key two"}

    monkeypatch.setattr(gemini_client, "_call", fake_call)
    result = gemini_client.generate_json("prompt", {"type": "object"})
    assert result["degraded"] is False
    assert result["text"] == "ok from key two"
    assert seen_keys == ["key-one", "key-two"]


def test_all_keys_429_sets_process_wide_quota_exhausted_and_fails_fast_next_call(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEYS", "key-one,key-two")
    calls = []

    def always_429(model, api_key, prompt, schema, timeout_s):
        calls.append(api_key)
        raise Fake429("quota exceeded")

    monkeypatch.setattr(gemini_client, "_call", always_429)

    first = gemini_client.generate_json("prompt", {"type": "object"})
    assert first["degraded"] is True
    assert len(calls) == 2  # tried both keys

    # second call must fail fast — no further _call invocations at all
    second = gemini_client.generate_json("prompt", {"type": "object"})
    assert second["degraded"] is True
    assert second["reason"] == "quota-exhausted-this-process"
    assert len(calls) == 2  # unchanged: no network attempt this time
