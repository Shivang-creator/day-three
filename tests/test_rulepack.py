import copy
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


def test_real_pack_placeholder_loads_with_a_version():
    pack = load(Path(__file__).parent.parent / "rules" / "postnatal.v1.json")
    assert pack.version


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


def test_duplicate_route_across_rules_raises():
    data = _base()
    data["rules"][1]["route"] = "URGENT_FACILITY_NOW"
    with pytest.raises(RulePackError, match="already claimed"):
        load(_write_tmp(data))


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
    # give NB-01 a different route so the duplicate-route check doesn't fire first
    for r in data["rules"]:
        if r["rule_id"] == "NB-01":
            r["route"] = "SAME_DAY_VISIT"
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
