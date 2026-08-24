"""Day Three — FastAPI shell. This is the only I/O boundary allowed to import
core, store, and agent together; core itself stays pure (see tests/test_boundary.py)."""
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

load_dotenv(".env.local")

APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "static"

app = FastAPI(title="Day Three")


@app.get("/api/health")
def health():
    return {
        "model": os.environ.get("GEMINI_MODEL", ""),
        "model_off": os.environ.get("MODEL_OFF", "0") == "1",
        "store": os.environ.get("STORE", "memory"),
        "rules_version": "0.0.0",
        "git_sha": os.environ.get("GIT_SHA", "dev"),
    }


@app.get("/", response_class=HTMLResponse)
def index():
    return (STATIC_DIR / "index.html").read_text()


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
