"""agent/reader.py (T-18, PLAN §4.5 / §4.9). The model is mocked at
gemini_client._call (the same module boundary every other test in this repo
mocks at) — no network here."""
from __future__ import annotations

from pathlib import Path

import pytest

from agent import gemini_client, reader
from core import rulepack

ROOT = Path(__file__).resolve().parent.parent
PACK_PATH = ROOT / "tests" / "fixtures" / "pack_min.json"


@pytest.fixture(autouse=True)
def _reset_module_state(monkeypatch):
    monkeypatch.setattr(gemini_client, "_QUOTA_EXHAUSTED", False)
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    monkeypatch.delenv("GEMINI_API_KEYS", raising=False)
    monkeypatch.delenv("MODEL_OFF", raising=False)
    monkeypatch.setenv("GEMINI_MODEL", "gemini-3.5-flash")


@pytest.fixture
def pack():
    return rulepack.load(PACK_PATH)


def test_schema_has_no_free_text_assessment_field(pack):
    schema = reader._schema_for_pack(pack)
    top_level_keys = set(schema["properties"].keys())
    assert top_level_keys == {"signs", "unclear"}
    assert "assessment" not in top_level_keys


def test_schema_restricts_every_sign_to_true_or_unknown(pack):
    schema = reader._schema_for_pack(pack)
    sign_schemas = schema["properties"]["signs"]["properties"]
    for sign_id in [s.sign_id for s in pack.signs]:
        assert sign_schemas[sign_id]["enum"] == ["true", "unknown"]


def test_read_maps_true_and_unknown_correctly(monkeypatch, pack):
    def fake_call(model, api_key, prompt, schema, timeout_s):
        return {"signs": {"NB_NOT_FEEDING": "true", "NB_FEVER": "unknown", "M_SELF_HARM": "unknown"}, "unclear": []}

    monkeypatch.setattr(gemini_client, "_call", fake_call)
    form = reader.read("baby not feeding since morning, feels hot", pack)
    assert form.signs["NB_NOT_FEEDING"] is True
    assert form.signs["NB_FEVER"] == "unknown"
    assert form.origin == "free_text"
    assert form.reader == "gemini"


def test_read_never_produces_a_false_value_even_if_model_tries(monkeypatch, pack):
    # a model that ignores the schema and tries to assert absence — the
    # reader only ever maps to True or "unknown", never False.
    def fake_call(model, api_key, prompt, schema, timeout_s):
        return {"signs": {"NB_NOT_FEEDING": "false", "NB_FEVER": "true", "M_SELF_HARM": "unknown"}, "unclear": []}

    monkeypatch.setattr(gemini_client, "_call", fake_call)
    form = reader.read("some text", pack)
    assert False not in form.signs.values()
    assert form.signs["NB_NOT_FEEDING"] == "unknown"  # "false" from the model maps to unknown, never False
    assert form.signs["NB_FEVER"] is True


def test_read_falls_back_to_all_unknown_when_model_disabled(monkeypatch, pack):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    form = reader.read("baby not feeding", pack)
    assert set(form.signs.values()) == {"unknown"}
    assert form.reader_confidence == 0.0


def test_read_falls_back_to_all_unknown_on_model_failure(monkeypatch, pack):
    def fake_call(model, api_key, prompt, schema, timeout_s):
        raise TimeoutError("model took too long")

    monkeypatch.setattr(gemini_client, "_call", fake_call)
    form = reader.read("baby not feeding", pack)
    assert set(form.signs.values()) == {"unknown"}
