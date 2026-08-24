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
