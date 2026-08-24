"""Gemini client wrapper (PLAN §4.9): hard timeout, JSON-schema output,
cache-through-store, `GEMINI_API_KEYS` round-robin on 429, and a process-wide
fail-fast once every key has confirmed a quota-shaped 429 in one round.

Every failure is logged loudly (`logger.error`, never swallowed silently —
"a graceful fallback can also HIDE a total failure") and turns into a
`degraded=True` dict instead of an exception, so a caller in agent/writer.py
or agent/reader.py never has to wrap this in try/except: it always gets
something back, and checks `result["degraded"]` to know whether it's real.

This module never imports `store` (agent/ is structurally forbidden from
it — tests/test_boundary.py::test_agent_directory_never_imports_the_store_module).
`store` is accepted here as a duck-typed object exposing `.cache_get(key)` /
`.cache_put(key, value)`; callers pass the real Store or a ReadOnlyStoreView-
adjacent object without this module ever naming the `store` package.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time

logger = logging.getLogger("agent.gemini_client")

# Process-wide: once every key in one round-robin pass has come back 429,
# stop even attempting the network for a bounded cool-down (PLAN §4.9
# "daily-quota 429 -> fail-fast for the process"). A transient single-key
# 429 does NOT set this — only a round where every configured key failed.
#
# R-08 (RED-TEAM.md): this used to be permanent for the process's whole
# lifetime — one burst of transient 429s (not necessarily the daily quota)
# would silently turn the reader off forever, with nothing in `/api/health`
# or the UI to show it. Now it is time-boxed: `_QUOTA_EXHAUSTED_UNTIL` is a
# `time.monotonic()` deadline, honouring the API's own Retry-After if the
# exception carried one (`exc.retry_after`, seconds) and never shorter than
# `QUOTA_COOLDOWN_S` (env, default below). `quota_exhausted()` is the one
# place that reads/clears this — everything else (generate_json, health)
# calls it rather than touching the bools directly.
_QUOTA_EXHAUSTED = False
_QUOTA_EXHAUSTED_UNTIL = 0.0
_DEFAULT_QUOTA_COOLDOWN_S = 60.0


def _quota_cooldown_s() -> float:
    try:
        return float(os.environ.get("QUOTA_COOLDOWN_S", _DEFAULT_QUOTA_COOLDOWN_S))
    except ValueError:
        return _DEFAULT_QUOTA_COOLDOWN_S


def quota_exhausted() -> bool:
    """Is the process-wide 429 fail-fast currently active? Self-clearing:
    once `time.monotonic()` passes `_QUOTA_EXHAUSTED_UNTIL`, this both
    returns False and resets the flag — a later call is free to try the
    network again. Exposed for `/api/health` (R-02/R-08: this must be
    visible, not silently inferred)."""
    global _QUOTA_EXHAUSTED
    if _QUOTA_EXHAUSTED and time.monotonic() >= _QUOTA_EXHAUSTED_UNTIL:
        _QUOTA_EXHAUSTED = False
    return _QUOTA_EXHAUSTED


def quota_retry_after_s() -> float:
    """Seconds remaining on the current cool-down, 0 if not exhausted."""
    if not quota_exhausted():
        return 0.0
    return max(0.0, _QUOTA_EXHAUSTED_UNTIL - time.monotonic())


def model_enabled() -> bool:
    """The kill-switch predicate. A model call is even attempted only if a
    key is configured AND MODEL_OFF isn't "1" — every place in agent/ that
    decides whether to touch the network routes through this rather than
    re-deriving the condition."""
    has_key = bool(os.environ.get("GEMINI_API_KEYS") or os.environ.get("GEMINI_API_KEY"))
    return has_key and os.environ.get("MODEL_OFF", "0") != "1"


def _keys() -> list[str]:
    multi = os.environ.get("GEMINI_API_KEYS", "").strip()
    if multi:
        return [k.strip() for k in multi.split(",") if k.strip()]
    single = os.environ.get("GEMINI_API_KEY", "").strip()
    return [single] if single else []


def _cache_key(model: str, prompt: str, schema: dict) -> str:
    """sha256(model|prompt|schema) per PLAN §4.9 — deterministic, so the same
    (model, prompt, schema) triple always hits the same cache slot and a
    replay never touches the network."""
    raw = "|".join([model, prompt, json.dumps(schema, sort_keys=True)])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _call(model: str, api_key: str, prompt: str, schema: dict, timeout_s: int) -> dict:
    """The network seam. Tests monkeypatch this function directly ("mock at
    the module boundary" — never touches google.genai in a test process).
    Raises on any failure; only ever invoked when model_enabled() is True."""
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)
    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_json_schema=schema,
        http_options=types.HttpOptions(timeout=int(timeout_s * 1000)),
    )
    response = client.models.generate_content(model=model, contents=prompt, config=config)
    text = response.text
    if not text:
        raise ValueError("empty response from model")
    return json.loads(text)


def generate_json(
    prompt: str,
    schema: dict,
    *,
    timeout_s: int = 20,
    cache_key: str | None = None,
    store=None,
) -> dict:
    """PLAN §4.9. On success returns the parsed JSON plus bookkeeping:
        {...schema fields..., "degraded": False, "model": GEMINI_MODEL}
    On ANY failure (kill-switch off, timeout, malformed JSON, every key
    quota-exhausted) returns, after a loud ERROR log:
        {"degraded": True, "reason": "<short cause>", "model": GEMINI_MODEL}
    `store`, if given, is checked first (cache hit -> zero network calls,
    "every replay is free") and written to on a fresh success only —
    degraded results are never cached, so a later real call can still
    succeed once the outage clears.
    """
    global _QUOTA_EXHAUSTED, _QUOTA_EXHAUSTED_UNTIL
    model = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash")
    key = cache_key or _cache_key(model, prompt, schema)

    if store is not None:
        cached = store.cache_get(key)
        if cached is not None:
            return cached

    if not model_enabled():
        reason = "MODEL_OFF=1" if os.environ.get("MODEL_OFF", "0") == "1" else "no GEMINI_API_KEY configured"
        logger.error("MODEL_FALLBACK model=%s reason=%s (kill-switch)", model, reason)
        return {"degraded": True, "reason": reason, "model": model}

    if quota_exhausted():
        retry_after = quota_retry_after_s()
        logger.error(
            "MODEL_FALLBACK model=%s reason=quota-exhausted-this-process (fail-fast, no network attempt; "
            "retry in %.0fs)",
            model,
            retry_after,
        )
        return {
            "degraded": True,
            "reason": "quota-exhausted-this-process",
            "model": model,
            "retry_after_s": retry_after,
        }

    keys = _keys()
    last_reason = "no keys configured"
    max_retry_after = 0.0
    for api_key in keys:
        try:
            result = _call(model, api_key, prompt, schema, timeout_s)
            payload = dict(result)
            payload["degraded"] = False
            payload["model"] = model
            if store is not None:
                store.cache_put(key, payload)
            return payload
        except Exception as exc:  # noqa: BLE001 - every model failure must degrade, never propagate
            code = getattr(exc, "code", None)
            if code == 429:
                tail = api_key[-4:] if len(api_key) >= 4 else api_key
                last_reason = f"429 rate/quota limit (key ...{tail})"
                logger.warning("gemini 429, rotating to next key: %s", last_reason)
                # R-08: honour the API's own Retry-After if it told us one,
                # so a short burst-rate 429 doesn't get treated the same as
                # a full-day quota exhaustion.
                retry_after = getattr(exc, "retry_after", None)
                if isinstance(retry_after, (int, float)) and retry_after > max_retry_after:
                    max_retry_after = float(retry_after)
                continue
            last_reason = f"{type(exc).__name__}: {exc}"
            logger.error("MODEL_FALLBACK model=%s reason=%s", model, last_reason)
            return {"degraded": True, "reason": last_reason, "model": model}
    else:
        # Every configured key was tried and every one came back 429 — this
        # is the daily-quota shape, not a transient blip. Fail fast, but
        # only for a bounded cool-down (R-08), not for the rest of the
        # process's life: `max(max_retry_after, QUOTA_COOLDOWN_S)`.
        _QUOTA_EXHAUSTED = True
        cooldown = max(max_retry_after, _quota_cooldown_s())
        _QUOTA_EXHAUSTED_UNTIL = time.monotonic() + cooldown
        logger.error(
            "MODEL_FALLBACK model=%s reason=%s (all keys exhausted; failing fast for %.0fs)",
            model,
            last_reason,
            cooldown,
        )
        return {"degraded": True, "reason": last_reason, "model": model, "retry_after_s": cooldown}
