"""tools/adversarial.py (T-20, PLAN §4.9 / §12). Runs the adversarial reply
set (tests/fixtures/adversarial_replies.json, M=33 rows >= 30 required) all
the way through the real pipeline — agent.reader.read() then
core.gate.evaluate() — and writes docs/adversarial-results.json.

Quota-aware by construction (PLAN's "quota-aware" doctrine and §12's call
budget): this tool NEVER touches the network by default. It replays a
persistent, git-committed recording cache at
tests/fixtures/adversarial_cache.json (keyed exactly the way
agent.gemini_client.generate_json keys a real call — model|prompt|schema) so
a previously-recorded real response comes back for free. A row that was
never recorded honestly falls through to agent.reader.read()'s own
degraded-safe fallback (all signs "unknown" -> core.gate.evaluate() ->
HUMAN_REVIEW, never a silent NEXT_CONTACT) — the exact same code path
tests/test_reader_schema.py already exercises with the model disabled.

Set LIVE=1 to record NEW real calls, capped at MAX_LIVE_CALLS (8) for the
whole process — once the cap is hit, every further row in the same LIVE=1
run degrades safely instead of spending more budget, it does not raise.
Rows are processed with `priority_live: true` fixture rows first, so the
budget is spent on the highest-stakes cases (self-harm phrasings, an
injection attempt, a negation) rather than whichever row happens to sit
first in the file. A key, if used, is read from the environment
(GEMINI_API_KEY / GEMINI_API_KEYS via agent.gemini_client) and is never
printed or logged by this module — only agent.gemini_client's own 429
handling ever logs the last 4 characters of a key, unchanged from T-17.

Run: `python -m tools.adversarial` (mocked/cached) or
     `LIVE=1 python -m tools.adversarial` (records up to 8 real calls).
Prints one copyable summary line; T-26 copies the numbers into README.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from agent import gemini_client, reader as agent_reader
from core import gate, rulepack
from store.memory import MemoryStore

logger = logging.getLogger("tools.adversarial")

ROOT = Path(__file__).resolve().parent.parent
FIXTURES_PATH = ROOT / "tests" / "fixtures" / "adversarial_replies.json"
CACHE_PATH = ROOT / "tests" / "fixtures" / "adversarial_cache.json"
RESULTS_PATH = ROOT / "docs" / "adversarial-results.json"
PACK_PATH = ROOT / "rules" / "postnatal.v1.json"

MAX_LIVE_CALLS = 8

# Safety-urgency ranking, low to high (independent of core.gate's own
# precedence-check ORDER, which is about which rule fires first, not a
# linear severity scale). Used only to classify an adversarial outcome as
# caught / missed / over-escalated relative to the fixture's expected_route.
URGENCY_RANK = {
    "NEXT_CONTACT": 0,
    "HUMAN_REVIEW": 1,
    "SAME_DAY_VISIT": 2,
    "URGENT_FACILITY_NOW": 3,
    "HUMAN_REVIEW_NOW": 4,
}


def _load_fixtures() -> list[dict]:
    data = json.loads(FIXTURES_PATH.read_text())
    return data["rows"]


def _ordered_for_budget(rows: list[dict]) -> list[dict]:
    """priority_live rows first (stable otherwise) — spends a capped LIVE=1
    budget on the highest-stakes cases regardless of file order."""
    return sorted(rows, key=lambda r: 0 if r.get("priority_live") else 1)


def _install_budget_cap(max_live_calls: int) -> dict:
    """Wraps gemini_client._call so LIVE=1 can never spend more than
    max_live_calls real network calls in one process — once hit, further
    rows raise inside generate_json's own try/except and degrade safely
    (degraded results are never cached, so nothing bad gets recorded)."""
    real_call = gemini_client._call
    counter = {"n": 0}

    def counting_call(model, api_key, prompt, schema, timeout_s):
        if counter["n"] >= max_live_calls:
            raise RuntimeError(f"tools.adversarial: LIVE budget of {max_live_calls} calls exhausted")
        counter["n"] += 1
        return real_call(model, api_key, prompt, schema, timeout_s)

    gemini_client._call = counting_call
    return counter


def run(*, live: bool = False, max_live_calls: int = MAX_LIVE_CALLS) -> dict:
    pack = rulepack.load(PACK_PATH)
    rows = _ordered_for_budget(_load_fixtures())
    cache = MemoryStore(str(CACHE_PATH))

    counter = {"n": 0}
    if live:
        counter = _install_budget_cap(max_live_calls)
    else:
        # Belt and suspenders: replay-only mode must never spend budget even
        # if a real key happens to be sitting in the ambient environment —
        # force the kill-switch off for this process only (does not touch
        # .env.local). A cache hit still returns the real recorded value,
        # because generate_json checks the cache before model_enabled().
        os.environ["MODEL_OFF"] = "1"

    results = []
    for row in rows:
        # subject is display/provenance metadata only (core/gate.py::evaluate
        # reads every sign in the pack regardless of subject — T-10's own
        # note) so a fixed default here does not affect routing; category
        # naming in the fixture already documents which subject each row is
        # really about.
        form = agent_reader.read(row["text"], pack, subject="newborn", store=cache)
        verdict = gate.evaluate(form, pack)
        actual_route = verdict.route
        expected_route = row["expected_route"]
        recorded = form.reader_confidence == 1.0  # True only for a real, undegraded model response

        actual_rank = URGENCY_RANK[actual_route]
        expected_rank = URGENCY_RANK[expected_route]
        if actual_route == expected_route:
            outcome = "caught"
        elif actual_rank > expected_rank:
            outcome = "over_escalated"
        else:
            outcome = "missed"

        results.append(
            {
                "id": row["id"],
                "lang": row["lang"],
                "category": row["category"],
                "text": row["text"],
                "expected_route": expected_route,
                "actual_route": actual_route,
                "outcome": outcome,
                "recorded": recorded,
                "reason": row["reason"],
            }
        )
        if outcome == "missed":
            logger.warning(
                "ADVERSARIAL_MISS id=%s category=%s expected=%s actual=%s recorded=%s",
                row["id"],
                row["category"],
                expected_route,
                actual_route,
                recorded,
            )

    n = len(results)
    caught = sum(1 for r in results if r["outcome"] == "caught")
    missed_rows = [r for r in results if r["outcome"] == "missed"]
    over_escalated = sum(1 for r in results if r["outcome"] == "over_escalated")
    recorded_total = sum(1 for r in results if r["recorded"])

    payload = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "model": os.environ.get("GEMINI_MODEL", "gemini-3.5-flash"),
        "n": n,
        "max_live_calls": max_live_calls,
        "live_recorded_this_run": counter["n"],
        "totals": {
            "caught": caught,
            "missed": len(missed_rows),
            "over_escalated": over_escalated,
            "recorded": recorded_total,
            "unrecorded": n - recorded_total,
        },
        "miss_rate": round(len(missed_rows) / n, 4) if n else 0.0,
        "missed": [
            {k: r[k] for k in ("id", "category", "lang", "expected_route", "actual_route", "recorded", "reason")}
            for r in missed_rows
        ],
        "rows": results,
    }
    return payload


def _summary_line(payload: dict) -> str:
    t = payload["totals"]
    return (
        f"ADVERSARIAL n={payload['n']} caught={t['caught']} missed={t['missed']} "
        f"over_escalated={t['over_escalated']} miss_rate={payload['miss_rate']:.2%} "
        f"recorded={t['recorded']}/{payload['n']} live_calls_this_run={payload['live_recorded_this_run']}/"
        f"{payload['max_live_calls']} model={payload['model']}"
    )


def main(argv: list[str] | None = None) -> dict:
    """R-09 (RED-TEAM.md): the README's own documented command,
    `python -m tools.adversarial`, used to overwrite the COMMITTED
    `docs/adversarial-results.json` on every run — only `run_at` actually
    changed (the numbers reproduce exactly, mocked/cached), but that still
    meant the tracked file showed as dirty after running a command the
    README itself tells a judge to run. Printing the summary line no
    longer touches the committed file at all unless `--write` is passed
    explicitly — an intentional, opt-in update to the tracked artifact,
    not a side effect of merely running the tool."""
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write",
        action="store_true",
        help="overwrite the committed docs/adversarial-results.json with this run's results (default: print only)",
    )
    args = parser.parse_args(argv)

    live = os.environ.get("LIVE") == "1"
    payload = run(live=live)
    line = _summary_line(payload)
    print(line)
    def _display_path(p):
        try:
            return p.relative_to(ROOT)
        except ValueError:
            return p

    if args.write:
        RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
        RESULTS_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        print(f"wrote {_display_path(RESULTS_PATH)}")
    else:
        print(f"{_display_path(RESULTS_PATH)} left untouched — pass --write to update the committed file (R-09)")
    return payload


if __name__ == "__main__":  # pragma: no cover - manual/CI entrypoint
    main()
