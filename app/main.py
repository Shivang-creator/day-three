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
from pydantic import BaseModel

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
    keypad: Optional[dict] = None
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
    return {
        "model": os.environ.get("GEMINI_MODEL", ""),
        "model_off": os.environ.get("MODEL_OFF", "0") == "1",
        "store": os.environ.get("STORE", "memory"),
        "rules_version": PACK.version,
        "git_sha": os.environ.get("GIT_SHA", "dev"),
    }


@app.get("/api/rules")
def rules():
    return dataclasses.asdict(PACK)


@app.post("/api/seed")
def seed(body: SeedBody):
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
    capped at 4 real calls) — see that module's own docstring."""
    result = quiet_diff.run_diff(seed=seed, to=clock or quiet_diff.DEFAULT_TO, live=False)
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
