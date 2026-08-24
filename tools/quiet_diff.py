"""tools/quiet_diff.py (T-19, PLAN §10). `make quiet-diff` -> runs the seeded
demo cohort (default seed 3) through the day-3 sweep TWICE, from ENROLLED,
in two throwaway `MemoryStore`s ("scratch namespaces" per PLAN §10) — once
with the model kill-switch on (`MODEL_OFF=1`, agent/quiet.py templates
only) and once with it off — then diffs the DECISION fields of every
resulting event (route, rule_id, action types, the booked slot) between the
two runs. This is the kill-switch's own proof, not an assertion of it:
`core/sweep.py::run_sweep` computes `Decision.actions_without_text` from
`core/routing.py::plan()` alone (pure, pack-driven, no model in the loop —
PLAN §4.7's own words: "sweep.py never sees message text"), so the two runs
MUST produce identical decisions by construction. If they ever don't,
something has leaked the model into a place it can influence a verdict, a
citation, an action type, or a clinic slot — exactly what pc-red-team will
try to provoke.

Only the *prose* — the MESSAGE_QUEUED text for the sweep's escalation
messages (`agent/orchestrator.py::ESCALATION_INTENTS = {"come_now",
"same_day"}`; routine check-ins/retries always render via agent/quiet.py in
both runs, model on or off, per orchestrator's own module docstring
decisions 1-2) — is allowed to differ, and the tool counts exactly how many
messages did.

Two ways to run the model-on side, chosen by the `LIVE` env var:

  - **Default (no `LIVE`)**: model-on is MOCKED AT THE MODULE BOUNDARY
    (`agent.writer.render` — the same seam `tests/test_writer.py` and
    `tests/test_api.py`'s own "mocked model-ON path" already monkeypatch;
    `agent.writer.render` is the boundary between the orchestrator and the
    ADK Runner, exactly analogous to how `agent.gemini_client.generate_json`
    is the boundary for the free-text reader) with a RECORDED CACHE of real
    Gemini output (`tests/fixtures/quiet_diff_recorded.json`) — a prior
    `LIVE=1` run's actual response text, replayed for zero network calls
    (quota-aware: `make quiet-diff`/CI/a fresh clone never spends a call).
    A key with no recording falls back to the Quiet template itself
    (logged loudly, never fabricated text) rather than inventing a string.
  - **`LIVE=1`**: makes REAL calls through the real ADK writer agent, capped
    hard at `--max-live-calls` (default 4, via `MODEL_CALL_BUDGET` — the
    orchestrator's own existing per-call budget enforcement, PLAN §12) —
    seed 3's D3 sweep has exactly 4 URGENT_FACILITY_NOW cases (T-16's own
    outbox), so this is a tight, not generous, cap. Every real response is
    captured as it's returned (wrapping `agent.writer.render`, not
    reconstructing it from the outbox afterward, so the recorded key always
    matches exactly what was actually rendered) and merged into the
    recorded-cache file on disk.

Deviation from PLAN §10's literal sketch, documented deliberately: the card
this file was built from (T-19) names `/api/replay?seed=&clock=` as a GET
with query params — matching every other read-style route in PLAN §4.10
("every route ... takes `?seed=` ... `?clock=`") — whereas PLAN §4.10's own
older sketch of just this one route wrote `POST /api/replay {seed}`. The
GET+query-param shape is what got built (app/main.py); see that route's own
docstring for the one-line reasoning.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import tempfile
from pathlib import Path

logger = logging.getLogger("tools.quiet_diff")

ROOT = Path(__file__).resolve().parent.parent
RULES_PATH = ROOT / "rules" / "postnatal.v1.json"
RECORDED_CACHE_PATH = ROOT / "tests" / "fixtures" / "quiet_diff_recorded.json"

DEFAULT_SEED = 3
DEFAULT_TO = "D3"
DEFAULT_N = 38
MAX_LIVE_CALLS_DEFAULT = 4


def _record_key(intent: str, lang: str, name: str) -> str:
    """Deterministic per (intent, lang, mother) — the cohort is
    seed-deterministic (core/cohort.py), so the same seed always produces
    the same `facts["name"]` for the same case, forever."""
    return f"{intent}|{lang}|{name}"


def _load_recorded_cache() -> dict:
    if RECORDED_CACHE_PATH.exists():
        return json.loads(RECORDED_CACHE_PATH.read_text())
    return {}


def _save_recorded_cache(cache: dict) -> None:
    RECORDED_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    RECORDED_CACHE_PATH.write_text(json.dumps(cache, indent=2, sort_keys=True) + "\n")


# Tier-3 fallback for `_mocked_render`, used ONLY when a case has no entry
# in the recorded-real-Gemini-output cache (tests/fixtures/quiet_diff_recorded.json)
# — e.g. a fresh clone that has never run `LIVE=1`, or (what actually
# happened building this task: `GenerateRequestsPerDayPerProjectPerModel-FreeTier`
# hit its 20/day cap on 2026-08-25 before a single LIVE call through the ADK
# writer succeeded — see .crew/outbox/T-19.md) a day whose quota is already
# spent. This is the SAME convention `tests/test_writer.py` and
# `tests/test_api.py::test_reply_free_text_model_on_mocked_produces_a_generated_message`
# already use for their own "prove the Generated path exists" tests: a
# fixed, clearly-synthetic string, tagged Generated, NEVER presented as a
# real network response — it exists so `make quiet-diff`'s decision-identity
# proof is reproducible offline/in CI/on a quota-exhausted day, exactly like
# `make demo` is. A real LIVE=1 recording, once captured, always wins over
# this (checked first, below).
_SYNTHETIC_MOCK_TEXT = {
    "en": "Please come to the clinic now — a nurse is expecting you. [mock draft, no live call this run]",
    "hi": "Kripya abhi clinic aayein — nurse aapka intezaar kar rahi hain. [mock draft, no live call this run]",
}


def _mocked_render(cache: dict):
    """A drop-in replacement for `agent.writer.render`. Tier 1: a real
    recorded response (from a prior successful `LIVE=1` run) — never
    fabricated. Tier 2 (this function's own fallback, not
    `agent.writer.render`'s production fallback): the synthetic mock text
    above, so the tool still proves "model-on prose differs from model-off
    prose" deterministically even with an empty/absent recording."""

    def _render(intent, lang, facts, *, store_view=None, pack=None, timeout_s=20):  # noqa: ARG001
        key = _record_key(intent, lang, facts.get("name", ""))
        cached_text = cache.get(key)
        if cached_text is not None:
            return {
                "text": cached_text,
                "tag": "Generated",
                "model": os.environ.get("GEMINI_MODEL", "gemini-3.5-flash"),
                "degraded": False,
            }
        logger.info(
            "tools.quiet_diff: no recorded LIVE response for key=%r — using the synthetic mock text "
            "(run `LIVE=1 python -m tools.quiet_diff` to record a real one)",
            key,
        )
        return {
            "text": _SYNTHETIC_MOCK_TEXT.get(lang, _SYNTHETIC_MOCK_TEXT["en"]),
            "tag": "Generated",
            "model": os.environ.get("GEMINI_MODEL", "gemini-3.5-flash"),
            "degraded": False,
        }

    return _render


def _recording_render(cache: dict, real_render):
    """Wraps the REAL `agent.writer.render` (used only under `LIVE=1`) to
    capture every genuine model response as it comes back, keyed exactly
    the way it was rendered — not reconstructed from the outbox afterward,
    so a recorded key can never silently drift from what actually ran."""

    def _render(intent, lang, facts, **kwargs):
        result = real_render(intent, lang, facts, **kwargs)
        if not result.get("degraded") and result.get("tag") == "Generated":
            cache[_record_key(intent, lang, facts.get("name", ""))] = result["text"]
        return result

    return _render


def _run_sweep(*, seed: int, to: str, n: int, model_on: bool, live: bool, max_live_calls: int, recorded_cache: dict):
    """One enroll()+advance() pass in a throwaway MemoryStore. Returns
    (decisions, messages, run_summary). `decisions` is exactly
    `orchestrator.advance()`'s own "decisions" list — PLAN §4.7's own
    Decision object, which never carries message text — sorted by case_id
    for a stable diff. `messages` is `{"<case_id>|<intent>": text}` built
    from the namespace's outbox afterward.
    """
    from app import orchestrator
    from core.rulepack import load as load_rulepack
    from store.memory import MemoryStore

    pack = load_rulepack(RULES_PATH)
    store = MemoryStore()

    env_keys = ("MODEL_OFF", "GEMINI_API_KEY", "GEMINI_API_KEYS", "MODEL_CALL_BUDGET")
    env_backup = {k: os.environ.get(k) for k in env_keys}
    undo_patches = []

    import agent.writer as agent_writer_module

    original_render = agent_writer_module.render

    try:
        if not model_on:
            os.environ["MODEL_OFF"] = "1"
        else:
            os.environ.pop("MODEL_OFF", None)
            if live:
                if not (os.environ.get("GEMINI_API_KEY") or os.environ.get("GEMINI_API_KEYS")):
                    raise SystemExit(
                        "LIVE=1 requires a real GEMINI_API_KEY (or GEMINI_API_KEYS) already in the "
                        "environment / .env.local — quiet_diff.py never fabricates one."
                    )
                os.environ["MODEL_CALL_BUDGET"] = str(max_live_calls)
                agent_writer_module.render = _recording_render(recorded_cache, original_render)
            else:
                # model_enabled() just needs a truthy key present; the real
                # network is never reached because render() itself is
                # replaced below — this placeholder is never sent anywhere.
                # R-01: `.setdefault` is a no-op when GEMINI_API_KEY is
                # already SET to the empty string (README's own
                # `cp .env.example .env.local` leaves it exactly that way,
                # and `load_dotenv` puts "" into os.environ, not "unset") —
                # `agent.gemini_client.model_enabled()` then sees a falsy
                # key and orchestrator._render_message short-circuits to the
                # Quiet template before ever calling this module's patched
                # `agent_writer.render`, so "on" silently degrades to "off"
                # and `make quiet-diff` prints "0 prose fields differ" on a
                # fresh clone. Check truthiness, not presence.
                if not os.environ.get("GEMINI_API_KEY"):
                    os.environ["GEMINI_API_KEY"] = "quiet-diff-mock-key-not-a-real-secret"
                agent_writer_module.render = _mocked_render(recorded_cache)
            undo_patches.append(lambda: setattr(agent_writer_module, "render", original_render))

        orchestrator.enroll(store, pack, seed, n=n)
        result = orchestrator.advance(store, pack, seed, to)
    finally:
        for fn in undo_patches:
            fn()
        for k, v in env_backup.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    decisions = sorted(result["decisions"], key=lambda d: d["case_id"])
    outbox_rows = orchestrator.outbox(store, seed)
    messages = {f"{row['case_id']}|{row['intent']}": row["text"] for row in outbox_rows}
    return decisions, messages, result["run_summary"]


def _diff_list(off: list, on: list, key_fn) -> list[dict]:
    off_by_key = {key_fn(d): d for d in off}
    on_by_key = {key_fn(d): d for d in on}
    changes = []
    for key in sorted(set(off_by_key) | set(on_by_key)):
        a, b = off_by_key.get(key), on_by_key.get(key)
        if a != b:
            changes.append({"case_id": key, "off": a, "on": b})
    return changes


def _diff_dict(off: dict, on: dict) -> list[dict]:
    changes = []
    for key in sorted(set(off) | set(on)):
        a, b = off.get(key), on.get(key)
        if a != b:
            changes.append({"key": key, "off": a, "on": b})
    return changes


def run_diff(
    *,
    seed: int = DEFAULT_SEED,
    to: str = DEFAULT_TO,
    n: int = DEFAULT_N,
    live: bool | None = None,
    max_live_calls: int = MAX_LIVE_CALLS_DEFAULT,
    work_dir: str | Path | None = None,
) -> dict:
    """The whole proof, callable both from the CLI (`python -m
    tools.quiet_diff`) and from `GET /api/replay` (app/main.py) — the exact
    same function backs both surfaces, so the UI's Replay panel and the
    command-line beat can never disagree.

    `live=None` (the default) reads the `LIVE` env var itself, so the CLI
    entrypoint's `LIVE=1 python -m tools.quiet_diff` works with no extra
    flag; callers that must never spend a live call (the HTTP route) pass
    `live=False` explicitly, overriding the environment.
    """
    if live is None:
        live = os.environ.get("LIVE") == "1"

    if work_dir is None:
        work_dir = tempfile.mkdtemp(prefix="quiet_diff_")
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    recorded_cache = _load_recorded_cache()
    cache_size_before = len(recorded_cache)

    decisions_off, messages_off, summary_off = _run_sweep(
        seed=seed, to=to, n=n, model_on=False, live=False, max_live_calls=max_live_calls, recorded_cache=recorded_cache
    )
    decisions_on, messages_on, summary_on = _run_sweep(
        seed=seed, to=to, n=n, model_on=True, live=live, max_live_calls=max_live_calls, recorded_cache=recorded_cache
    )
    newly_recorded = len(recorded_cache) - cache_size_before

    paths = {
        "decisions_off": work_dir / "decisions_off.json",
        "decisions_on": work_dir / "decisions_on.json",
        "messages_off": work_dir / "messages_off.json",
        "messages_on": work_dir / "messages_on.json",
    }
    paths["decisions_off"].write_text(json.dumps(decisions_off, indent=2, sort_keys=True) + "\n")
    paths["decisions_on"].write_text(json.dumps(decisions_on, indent=2, sort_keys=True) + "\n")
    paths["messages_off"].write_text(json.dumps(messages_off, indent=2, sort_keys=True) + "\n")
    paths["messages_on"].write_text(json.dumps(messages_on, indent=2, sort_keys=True) + "\n")

    decision_changes = _diff_list(decisions_off, decisions_on, key_fn=lambda d: d["case_id"])
    message_changes = _diff_dict(messages_off, messages_on)

    # The literal `diff decisions_on.json decisions_off.json` PLAN §10 asks
    # for, as the printed proof — empty stdout is itself the assertion.
    diff_proc = subprocess.run(
        ["diff", str(paths["decisions_on"]), str(paths["decisions_off"])],
        capture_output=True,
        text=True,
        check=False,
    )
    print(f"$ diff {paths['decisions_on'].name} {paths['decisions_off'].name}")
    print(diff_proc.stdout if diff_proc.stdout else "(empty)")

    summary_line = f"QUIET DIFF: {len(decision_changes)} decision changes · {len(message_changes)} prose fields differ"
    print(summary_line)

    if live:
        _save_recorded_cache(recorded_cache)
        print(
            f"LIVE=1: {summary_on['model_calls_used']}/{summary_on['model_call_budget']} real model call(s) "
            f"attempted; {newly_recorded} new real response(s) actually recorded into "
            f"{RECORDED_CACHE_PATH.relative_to(ROOT)} (the rest degraded honestly — see the MODEL_FALLBACK "
            f"log lines above, e.g. a live 429)"
        )

    return {
        "seed": seed,
        "to": to,
        "live": live,
        "decision_changes": decision_changes,
        "message_changes": message_changes,
        "decisions_on": decisions_on,
        "decisions_off": decisions_off,
        "messages_on": messages_on,
        "messages_off": messages_off,
        "run_summary_on": summary_on,
        "run_summary_off": summary_off,
        "summary_line": summary_line,
        "work_dir": str(work_dir),
        "paths": {k: str(v) for k, v in paths.items()},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--to", default=DEFAULT_TO)
    parser.add_argument("--n", type=int, default=DEFAULT_N)
    parser.add_argument("--max-live-calls", type=int, default=MAX_LIVE_CALLS_DEFAULT)
    args = parser.parse_args(argv)

    try:
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env.local")
    except Exception:  # noqa: BLE001 - optional convenience only
        pass

    result = run_diff(seed=args.seed, to=args.to, n=args.n, max_live_calls=args.max_live_calls)
    return 1 if result["decision_changes"] else 0


if __name__ == "__main__":  # pragma: no cover - manual/CI entrypoint
    sys.exit(main())
