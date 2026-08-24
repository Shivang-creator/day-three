"""Day Three — FastAPI shell. This is the only I/O boundary allowed to import
core, store, and agent together; core itself stays pure (see tests/test_boundary.py).
Every state-changing route delegates to app/orchestrator.py, the only place a
Store is written to outside tests.
"""
import dataclasses
import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, StrictBool

from agent.gemini_client import model_enabled, quota_exhausted, quota_retry_after_s
from app import orchestrator
from core.rulepack import load as load_rulepack
from store import make_store
from tools import quiet_diff

load_dotenv(".env.local")

APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "static"
ROOT_DIR = APP_DIR.parent
RULES_PATH = ROOT_DIR / "rules" / "postnatal.v1.json"

app = FastAPI(title="Day Three")

# Loaded once at import time: the rule pack is immutable input data (PLAN
# §4.4), and the store backend is selected once from STORE (PLAN §4.2). Both
# are cheap to construct and every route shares them.
PACK = load_rulepack(RULES_PATH)
STORE = make_store()


class SeedBody(BaseModel):
    seed: int
    n: int = 38


class AdvanceBody(BaseModel):
    seed: int
    to: str


class ReplyBody(BaseModel):
    case_id: str
    # R-06 (RED-TEAM.md): a bare `Optional[dict]` accepted ANY JSON value
    # per sign — `null`/`0`/`"no"` all reached core/gate.py::evaluate as
    # neither `is True` nor `== "unknown"`, which its own fall-through
    # treats as an implicit clear (NEXT_CONTACT), even though none of them
    # is the explicit keypad `False` the gate's "reader can never clear"
    # rule requires. `StrictBool` rejects anything that isn't a literal
    # JSON true/false with a 422 before it ever reaches core/ — unanswered
    # must never look like "no sign", it must fail loudly instead.
    keypad: Optional[dict[str, StrictBool]] = None
    text: Optional[str] = None


class QuietBody(BaseModel):
    seed: int
    on: bool


class ResetBody(BaseModel):
    seed: int


def _not_found(exc: orchestrator.NotFoundError):
    raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/health")
def health():
    # R-02: `model_off` alone only reflects the MODEL_OFF env var — a blank
    # GEMINI_API_KEY (README: "leave it empty and the app runs on
    # templates") left it reporting `model_off: false`, so a judge on a
    # fresh clone with no key saw no signal anywhere that they were looking
    # at template output. `model_enabled` is the SAME predicate
    # `app/orchestrator.py::_render_message` actually gates every model
    # call on (`agent.gemini_client.model_enabled()`), so this can never
    # drift from what the app really does. `quota_exhausted`/
    # `quota_retry_after_s` surface R-08's process-wide 429 cool-down, which
    # was previously invisible outside the server log.
    return {
        "model": os.environ.get("GEMINI_MODEL", ""),
        "model_off": os.environ.get("MODEL_OFF", "0") == "1",
        "model_enabled": model_enabled(),
        "quota_exhausted": quota_exhausted(),
        "quota_retry_after_s": quota_retry_after_s(),
        "store": os.environ.get("STORE", "memory"),
        "rules_version": PACK.version,
        "git_sha": os.environ.get("GIT_SHA", "dev"),
    }


@app.get("/api/rules")
def rules():
    return dataclasses.asdict(PACK)


# R-05 (RED-TEAM.md): POST /api/seed {"n": 2000} used to enroll fine (200
# OK, ~2s of writes) and only fail later, at /api/advance, with an
# unrelated-looking 500 KeyError — core/cohort.py's category table was
# built for the wrong size (fixed separately, core/cohort.py::category_for
# is now n-aware). This caps `n` at the API boundary too: an uncapped
# enroll is its own problem (an unbounded number of synthetic writes from
# one request), independent of that crash.
MAX_SEED_N = 200


@app.post("/api/seed")
def seed(body: SeedBody):
    if not (1 <= body.n <= MAX_SEED_N):
        raise HTTPException(status_code=400, detail=f"n must be between 1 and {MAX_SEED_N} (got {body.n})")
    return {"worklist": orchestrator.enroll(STORE, PACK, body.seed, n=body.n)}


@app.post("/api/advance")
def advance(body: AdvanceBody):
    try:
        return orchestrator.advance(STORE, PACK, body.seed, body.to)
    except orchestrator.NotFoundError as exc:
        _not_found(exc)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/worklist")
def worklist(seed: int = Query(...)):
    return {"worklist": orchestrator.worklist(STORE, PACK, seed)}


@app.get("/api/case/{case_id}")
def case(case_id: str, seed: int = Query(...)):
    try:
        return orchestrator.case_detail(STORE, PACK, seed, case_id)
    except orchestrator.NotFoundError as exc:
        _not_found(exc)


@app.post("/api/reply")
def reply(body: ReplyBody, seed: int = Query(...), clock: Optional[str] = Query(None)):
    try:
        return orchestrator.reply(STORE, PACK, seed, body.case_id, keypad=body.keypad, text=body.text, clock_override=clock)
    except orchestrator.NotFoundError as exc:
        _not_found(exc)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/quiet")
def quiet(body: QuietBody):
    orchestrator.set_quiet(STORE, body.seed, body.on)
    return {"seed": body.seed, "on": body.on}


@app.get("/api/replay")
def replay(seed: int = Query(...), clock: Optional[str] = Query(None)):
    """PLAN §10 / T-19: the UI's Replay panel. Runs the seeded cohort's day-3
    sweep TWICE, from ENROLLED, in two throwaway scratch namespaces (model
    on vs off — never touching `STORE`/the real namespace at all) and
    returns the DECISION diff (must always be empty) plus the message-prose
    diff. `tools/quiet_diff.py::run_diff` is the exact function backing
    both this route and its own CLI (`python -m tools.quiet_diff`) — the
    UI and the command-line beat can never disagree because there is only
    one implementation.

    Deliberately GET + query params (`?seed=&clock=`), not PLAN §4.10's
    older `POST /api/replay {seed}` sketch: every other read-only route in
    this file already takes `?seed=` (T-16's own convention, "every route
    accepts ?seed=... and ?clock="), and this route never writes to the
    real Store — it's a read, so it gets a read verb. `clock` here reuses
    that same query-param name to mean the sweep's target rung/ISO ("to"
    in `orchestrator.advance`'s terms, and `tools/quiet_diff.py`'s own
    `--to`), defaulting to "D3" — the demo default — when omitted.

    `live=False` is HARD-CODED here, never read from the `LIVE` env var:
    an HTTP route a judge (or a UI click-happy tester) can hit repeatedly
    must never spend a real model call on its own. Live recording is a
    deliberate, budgeted, CLI-only act (`LIVE=1 python -m tools.quiet_diff`,
    capped at 4 real calls) — see that module's own docstring.

    R-07 (RED-TEAM.md): an unknown `clock` (e.g. `?clock=D99`, not a rung on
    any variant's ladder) used to reach `orchestrator._target_iso_for_rung`
    unguarded and raise a bare `ValueError`, which FastAPI turned into an
    unhandled 500 — every other route that can hit the same validation
    (`/api/advance`, `/api/reply`) already maps `ValueError` to a client
    400; this route hadn't."""
    try:
        result = quiet_diff.run_diff(seed=seed, to=clock or quiet_diff.DEFAULT_TO, live=False)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "seed": seed,
        "to": clock or quiet_diff.DEFAULT_TO,
        "decision_changes": len(result["decision_changes"]),
        "message_changes": len(result["message_changes"]),
        "diff": result["decision_changes"],
        "summary_line": result["summary_line"],
    }


@app.get("/api/outbox")
def outbox(seed: int = Query(...)):
    return {"outbox": orchestrator.outbox(STORE, seed)}


@app.post("/api/reset")
def reset(body: ResetBody):
    orchestrator.reset(STORE, body.seed)
    return {"seed": body.seed, "reset": True}


@app.get("/", response_class=HTMLResponse)
def index():
    return (STATIC_DIR / "index.html").read_text()


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
