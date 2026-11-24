"""Regressions from the 2026-11-24 audit.

1. `agent/tools.py` used `os.environ` in the Gemma translation fallback
   without importing `os`. Every `translate()` call for text that is not an
   exact reviewed template raised NameError, which `agent/writer.py` caught
   and turned into a silent Quiet-template fallback — so the fallback the
   commit added could never run, and three tests failed on main.
2. `POST /api/reply`'s `text` had no length bound on a public endpoint that
   forwards it to the model.
"""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from agent import tools as agent_tools
from app.main import MAX_REPLY_TEXT_CHARS, app
from core import rulepack
from store.memory import MemoryStore
from store.readonly import ReadOnlyStoreView

ROOT = Path(__file__).resolve().parent.parent
client = TestClient(app)


def test_translate_of_untemplated_text_does_not_raise(monkeypatch):
    monkeypatch.setenv("MODEL_OFF", "1")
    pack = rulepack.load(ROOT / "tests" / "fixtures" / "pack_min.json")
    _, _, translate, _ = agent_tools.make_tools(ReadOnlyStoreView(MemoryStore()), pack)
    assert translate("A line with no reviewed template.", "hi").startswith("[untranslated:hi]")


def test_oversized_reply_text_is_rejected_before_it_reaches_the_reader(monkeypatch):
    monkeypatch.setenv("MODEL_OFF", "1")
    seed = 112401
    worklist = client.post("/api/seed", json={"seed": seed}).json()["worklist"]
    case_id = worklist[0]["case_id"].split(":", 1)[1]

    too_long = "x" * (MAX_REPLY_TEXT_CHARS + 1)
    r = client.post("/api/reply", params={"seed": seed}, json={"case_id": case_id, "text": too_long})
    assert r.status_code == 422

    ok = client.post("/api/reply", params={"seed": seed}, json={"case_id": case_id, "text": "x" * MAX_REPLY_TEXT_CHARS})
    assert ok.status_code == 200
