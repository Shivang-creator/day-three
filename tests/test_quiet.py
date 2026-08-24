"""agent/quiet.py + agent/templates.json (T-17, PLAN §4.9/§10)."""
from __future__ import annotations

from agent import quiet

EXPECTED_INTENTS = {
    "checkin_D1",
    "checkin_D3",
    "checkin_D7",
    "checkin_D14",
    "checkin_D21",
    "checkin_D28",
    "checkin_D42",
    "come_now",
    "same_day",
    "retry",
    "review",
}


def test_every_expected_intent_is_present():
    assert set(quiet.known_intents()) == EXPECTED_INTENTS


def test_every_intent_has_both_languages_non_empty():
    templates = quiet._load_templates()
    for intent, entry in templates.items():
        assert "en" in entry and entry["en"].strip(), f"{intent} missing en"
        assert "hi" in entry and entry["hi"].strip(), f"{intent} missing hi"


def test_render_returns_the_common_shape():
    result = quiet.render("review", "en", {"name": "Asha (synthetic #01)"})
    assert set(result.keys()) == {"text", "tag", "model", "degraded"}
    assert result["tag"] == "Rule"
    assert result["model"] == "template"
    assert result["degraded"] is True


def test_render_fills_facts_into_the_template():
    result = quiet.render("come_now", "en", {"name": "Priya (synthetic #07)", "clinic_address": "Ward 4"})
    assert "Priya (synthetic #07)" in result["text"]
    assert "Ward 4" in result["text"]


def test_render_hindi_language_selected():
    en = quiet.render("checkin_D3", "en", {"name": "X"})
    hi = quiet.render("checkin_D3", "hi", {"name": "X"})
    assert en["text"] != hi["text"]


def test_render_unknown_intent_does_not_raise():
    result = quiet.render("nonexistent_intent", "en", {})
    assert result["degraded"] is True
    assert "nonexistent_intent" in result["text"]


def test_render_missing_language_falls_back_to_english():
    result = quiet.render("come_now", "mr", {"name": "X", "clinic_address": "Y"})
    en_equivalent = quiet.render("come_now", "en", {"name": "X", "clinic_address": "Y"})
    assert result["text"] == en_equivalent["text"]


def test_render_missing_fact_does_not_raise():
    # come_now needs {name} and {clinic_address}; give it neither.
    result = quiet.render("come_now", "en", {})
    assert result["degraded"] is True
    assert isinstance(result["text"], str)
