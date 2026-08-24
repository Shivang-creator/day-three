from pathlib import Path

import pytest

from core.gate import evaluate, merge, normalise
from core.models import SymptomForm
from core.rulepack import load

PACK = load(Path(__file__).parent.parent / "rules" / "postnatal.v1.json")


def _form(subject="newborn", signs=None, origin="keypad", reader="none", source_text=""):
    return SymptomForm(subject=subject, signs=signs or {}, origin=origin, reader=reader, source_text=source_text)


# ---------------------------------------------------------------- normalise --


def test_normalise_fills_missing_signs_as_unknown():
    form = normalise(_form(signs={}), PACK)
    assert form.signs["NB_FEVER"] == "unknown"
    assert len(form.signs) == len(PACK.signs)


def test_reader_false_becomes_unknown():
    form = normalise(_form(signs={"NB_FEVER": False}, origin="free_text", reader="gemini"), PACK)
    assert form.signs["NB_FEVER"] == "unknown"


def test_normalise_keypad_false_stays_false():
    form = normalise(_form(signs={"NB_FEVER": False}, origin="keypad"), PACK)
    assert form.signs["NB_FEVER"] is False


def test_normalise_true_survives_free_text():
    form = normalise(_form(signs={"NB_FEVER": True}, origin="free_text", reader="gemini"), PACK)
    assert form.signs["NB_FEVER"] is True


# --------------------------------------------------------------------- merge --


def test_merge_true_wins_over_either_source():
    keypad = _form(signs={"NB_FEVER": False}, origin="keypad")
    reader = _form(signs={"NB_FEVER": True}, origin="free_text", reader="gemini")
    merged = merge(keypad, reader)
    assert merged.signs["NB_FEVER"] is True


def test_merge_false_only_when_keypad_false():
    keypad = _form(signs={"NB_FEVER": False}, origin="keypad")
    reader = _form(signs={"NB_FEVER": "unknown"}, origin="free_text", reader="gemini")
    merged = merge(keypad, reader)
    assert merged.signs["NB_FEVER"] is False


def test_merge_keypad_unknown_reader_unknown_stays_unknown():
    keypad = _form(signs={"NB_FEVER": "unknown"}, origin="keypad")
    reader = _form(signs={"NB_FEVER": "unknown"}, origin="free_text", reader="gemini")
    merged = merge(keypad, reader)
    assert merged.signs["NB_FEVER"] == "unknown"


def test_merge_raises_on_subject_mismatch():
    keypad = _form(subject="newborn")
    reader = _form(subject="mother")
    with pytest.raises(ValueError, match="subject"):
        merge(keypad, reader)


# ------------------------------------------------------------------ evaluate --


def test_self_harm_routes_human_review_now():
    verdict = evaluate(_form(subject="mother", signs={"M_SELF_HARM": True}), PACK)
    assert verdict.route == "HUMAN_REVIEW_NOW"
    assert verdict.fired[0]["rule_id"] == "M-SELF-HARM-01"


def test_any_red_true_routes_urgent_facility_now():
    verdict = evaluate(_form(signs={"NB_FEVER": True}), PACK)
    assert verdict.route == "URGENT_FACILITY_NOW"


def test_any_yellow_true_with_no_red_routes_same_day_visit():
    verdict = evaluate(_form(signs={"NB_SKIN_PUSTULES": True}), PACK)
    assert verdict.route == "SAME_DAY_VISIT"


def test_red_unknown_with_nothing_true_routes_human_review():
    verdict = evaluate(_form(signs={"NB_FEVER": "unknown"}), PACK)
    assert verdict.route == "HUMAN_REVIEW"


def test_all_signs_false_routes_next_contact():
    # evaluate() considers every sign in the pack regardless of form.subject
    # (a case's verdict is about the mother-and-newborn pair, not one alone
    # — PLAN §0), so a genuine "all clear" needs every sign explicitly false.
    all_false = {s.sign_id: False for s in PACK.signs}
    verdict = evaluate(_form(signs=all_false), PACK)
    assert verdict.route == "NEXT_CONTACT"


def test_precedence_self_harm_beats_urgent():
    verdict = evaluate(_form(subject="mother", signs={"M_SELF_HARM": True, "M_FEVER_WEAK": True}), PACK)
    assert verdict.route == "HUMAN_REVIEW_NOW"


def test_precedence_urgent_beats_same_day():
    verdict = evaluate(_form(signs={"NB_FEVER": True, "NB_SKIN_PUSTULES": True}), PACK)
    assert verdict.route == "URGENT_FACILITY_NOW"


def test_precedence_same_day_beats_human_review():
    verdict = evaluate(_form(signs={"NB_SKIN_PUSTULES": True, "NB_FEVER": "unknown"}), PACK)
    assert verdict.route == "SAME_DAY_VISIT"


def test_reader_cannot_lower_route():
    """A free-text reader claiming a red sign is false must not clear the
    case to NEXT_CONTACT — normalise() rewrites it to unknown first, so the
    gate lands on HUMAN_REVIEW instead. This is the structural proof behind
    'the model can never output clear.'"""
    verdict = evaluate(_form(signs={"NB_FEVER": False}, origin="free_text", reader="gemini"), PACK)
    assert verdict.route != "NEXT_CONTACT"
    assert verdict.route == "HUMAN_REVIEW"


def test_fired_cites_the_rule_that_matched():
    verdict = evaluate(_form(signs={"NB_FEVER": True}), PACK)
    fired = verdict.fired[0]
    assert fired["rule_id"].startswith("NB-")
    assert fired["source_id"] == "S1"
    assert len(fired["source_quote"]) >= 20


def test_unknown_field_lists_every_unknown_sign_not_just_red():
    form_signs = {"NB_UMBILICUS_INFECTED": "unknown"}
    verdict = evaluate(_form(signs=form_signs), PACK)
    assert "NB_UMBILICUS_INFECTED" in verdict.unknown


@pytest.mark.parametrize("rule", PACK.rules, ids=lambda r: r.rule_id)
def test_every_rule_fires_on_its_own_signs(rule):
    """Parametrised across the whole real pack: for every rule, a form with
    exactly that rule's signs true must produce a Verdict whose fired list
    names that rule_id (unless self-harm or another rule at a higher
    precedence tier pre-empts it, e.g. a red sign next to a self-harm true)."""
    sign_ids = {sid for value in rule.when.values() if isinstance(value, list) for sid in value}
    sign_by_id = {s.sign_id: s for s in PACK.signs}
    subject = sign_by_id[next(iter(sign_ids))].subject
    form = _form(subject=subject, signs={sid: True for sid in sign_ids})
    verdict = evaluate(form, PACK)
    if rule.rule_id == "M-SELF-HARM-01":
        assert verdict.route == "HUMAN_REVIEW_NOW"
    else:
        fired_ids = {f["rule_id"] for f in verdict.fired}
        assert rule.rule_id in fired_ids
