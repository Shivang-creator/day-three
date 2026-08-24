import json
from pathlib import Path

import pytest

from core.rulepack import RulePackError, load

FIXTURE = Path(__file__).parent / "fixtures" / "pack_min.json"


def _base() -> dict:
    return json.loads(FIXTURE.read_text())


def _write(tmp_path: Path, data: dict) -> Path:
    p = tmp_path / "pack.json"
    p.write_text(json.dumps(data))
    return p


def test_pack_min_loads_successfully():
    pack = load(FIXTURE)
    assert pack.pack_id == "pack_min"
    assert pack.version == "0.1.0"
    assert len(pack.ladder) == 2
    assert len(pack.signs) == 3
    assert len(pack.rules) == 2


REAL_PACK = Path(__file__).parent.parent / "rules" / "postnatal.v1.json"


def test_real_pack_loads_with_a_version():
    pack = load(REAL_PACK)
    assert pack.version == "1.0.0"


def test_real_pack_meets_the_t07_minimum_counts():
    pack = load(REAL_PACK)
    assert len(pack.signs) >= 12
    assert len(pack.rules) >= 8


def test_real_pack_has_both_who_and_hbnc_ladder_variants():
    pack = load(REAL_PACK)
    variants = {r.variant for r in pack.ladder}
    assert variants == {"WHO", "HBNC"}


def test_real_pack_self_harm_is_not_falsely_attributed_to_a_clinical_source():
    """The research file is explicit that no WHO/MoHFW document sources a
    self-harm screening rule (research/RULES-SOURCE.md, "What we do NOT
    model"). M_SELF_HARM must not carry a fact_id claiming otherwise — its
    citation is the research file's own non-finding, not a fabricated
    clinical threshold."""
    pack = load(REAL_PACK)
    self_harm = next(s for s in pack.signs if s.sign_id == "M_SELF_HARM")
    assert self_harm.fact_id is None
    assert self_harm.source_id == "RESEARCH-NOTE"


def test_real_pack_not_modelled_covers_self_harm_and_names_a_reason():
    pack = load(REAL_PACK)
    ids = {n["id"]: n for n in pack.not_modelled}
    assert "NOT-01" in ids
    assert "self-harm" in ids["NOT-01"]["subject"].lower()
    assert len(ids["NOT-01"]["reason"]) >= 20


def test_real_pack_documents_all_three_source_disagreements():
    pack = load(REAL_PACK)
    assert len(pack.disagreements) == 3
    for d in pack.disagreements:
        assert d["applied"]
        assert d["reading_a"] and d["reading_b"]


def test_real_pack_silence_discloses_its_timing_is_unsourced():
    """retry_after_hours/max_retries (PLAN §4.6) are a product decision, not
    a WHO/HBNC citation — the pack must say so rather than dress a builder
    choice up as sourced."""
    pack = load(REAL_PACK)
    assert pack.silence.timing_sourced is False
    assert pack.silence.timing_note


def test_error_names_the_offending_entry():
    data = _base()
    data["rules"][0]["source_id"] = "NOT-A-SOURCE"
    with pytest.raises(RulePackError, match="NB-01"):
        load(_write_tmp(data))


def _write_tmp(data: dict) -> Path:
    import tempfile

    d = Path(tempfile.mkdtemp())
    return _write(d, data)


def test_missing_source_id_on_ladder_entry_raises():
    data = _base()
    del data["ladder"][0]["source_id"]
    with pytest.raises(RulePackError, match="source_id"):
        load(_write_tmp(data))


def test_source_id_not_found_in_sources_raises():
    data = _base()
    data["signs"][0]["source_id"] = "GHOST-SOURCE"
    with pytest.raises(RulePackError, match="not found in sources"):
        load(_write_tmp(data))


def test_source_quote_shorter_than_20_chars_raises():
    data = _base()
    data["rules"][0]["source_quote"] = "too short"
    with pytest.raises(RulePackError, match="20 characters"):
        load(_write_tmp(data))


def test_source_url_not_starting_with_http_raises():
    data = _base()
    data["signs"][0]["source_url"] = "not-a-url"
    with pytest.raises(RulePackError, match="source_url"):
        load(_write_tmp(data))


def test_rule_referencing_unknown_sign_raises():
    data = _base()
    data["rules"][0]["when"] = {"any_of": ["NB_DOES_NOT_EXIST"]}
    with pytest.raises(RulePackError, match="unknown sign"):
        load(_write_tmp(data))


def test_duplicate_rule_id_raises():
    data = _base()
    data["rules"][1]["rule_id"] = data["rules"][0]["rule_id"]
    with pytest.raises(RulePackError, match="already used"):
        load(_write_tmp(data))


def test_multiple_rules_may_share_one_route():
    """Regression: an earlier loader required exactly one rule per route,
    which real WHO/HBNC citation data (T-07, ten+ distinct red newborn signs
    all routing URGENT_FACILITY_NOW) can never satisfy. Two rules with
    different rule_ids and the same route must both load cleanly."""
    data = _base()
    extra = dict(data["rules"][0])
    extra["rule_id"] = "NB-99"
    extra["when"] = {"any_of": ["NB_FEVER"]}
    data["rules"].append(extra)
    pack = load(_write_tmp(data))
    routes = [r.route for r in pack.rules]
    assert routes.count("URGENT_FACILITY_NOW") == 2


def test_missing_self_harm_sign_raises():
    data = _base()
    data["signs"] = [s for s in data["signs"] if s["sign_id"] != "M_SELF_HARM"]
    data["rules"] = [r for r in data["rules"] if r["rule_id"] != "M-SELF-HARM-01"]
    with pytest.raises(RulePackError, match="M_SELF_HARM"):
        load(_write_tmp(data))


def test_self_harm_sign_must_be_red_raises():
    data = _base()
    for s in data["signs"]:
        if s["sign_id"] == "M_SELF_HARM":
            s["severity"] = "yellow"
    with pytest.raises(RulePackError, match="severity must be 'red'"):
        load(_write_tmp(data))


def test_self_harm_rule_must_route_human_review_now_raises():
    data = _base()
    for r in data["rules"]:
        if r["rule_id"] == "M-SELF-HARM-01":
            r["route"] = "URGENT_FACILITY_NOW"
    with pytest.raises(RulePackError, match="HUMAN_REVIEW_NOW"):
        load(_write_tmp(data))


def test_self_harm_rule_must_page_nurse_raises():
    data = _base()
    for r in data["rules"]:
        if r["rule_id"] == "M-SELF-HARM-01":
            r["actions"] = ["HUMAN_REVIEW"]
    with pytest.raises(RulePackError, match="PAGE_NURSE"):
        load(_write_tmp(data))


def test_sign_missing_hindi_label_raises():
    data = _base()
    data["signs"][0]["label_hi"] = ""
    with pytest.raises(RulePackError, match="Hindi label"):
        load(_write_tmp(data))


def test_missing_required_top_level_key_raises():
    data = _base()
    del data["clinic"]
    with pytest.raises(RulePackError, match="clinic"):
        load(_write_tmp(data))
