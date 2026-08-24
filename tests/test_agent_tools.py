"""agent/tools.py + agent/agent.py (T-18, PLAN §4.9 / §1.3 "scoped tools").
No network here: LlmAgent construction doesn't call the model, and the four
tool callables are plain Python we call directly.
"""
from __future__ import annotations

import ast
from pathlib import Path

from agent import tools as agent_tools
from agent.agent import build_writer
from core import rulepack
from core.events import Event
from store.memory import MemoryStore
from store.readonly import ReadOnlyStoreView

ROOT = Path(__file__).resolve().parent.parent
PACK_PATH = ROOT / "tests" / "fixtures" / "pack_min.json"


def _event(seq: int, case_id: str, type_: str, key: str) -> Event:
    return Event(
        seq=seq,
        case_id=case_id,
        at="2026-08-24T00:00:00+00:00",
        type=type_,
        payload={"mother": {
            "mother_id": "mother-01",
            "display_name": "Test Mother (synthetic #01)",
            "phone": "+91-00000-00001",
            "variant": "WHO",
            "discharge_epoch": "2026-08-24T00:00:00+00:00",
        }, "rung": "D1"},
        tag="Simulated",
        idempotency_key=key,
    )


def test_toolset_has_exactly_four_named_tools():
    pack = rulepack.load(PACK_PATH)
    store = MemoryStore()
    view = ReadOnlyStoreView(store)
    writer = build_writer(view, pack)
    names = [getattr(t, "__name__", None) for t in writer.tools]
    assert names == ["read_case", "read_rule", "translate", "draft_message"]


def test_no_tool_in_agent_tools_py_references_store_append():
    source = (ROOT / "agent" / "tools.py").read_text()
    tree = ast.parse(source, filename="agent/tools.py")
    hits = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == "append":
            hits.append(ast.dump(node))
    assert not hits, f"agent/tools.py references .append(): {hits}"


def test_read_case_only_ever_receives_a_readonly_store_view():
    store = MemoryStore()
    store.append("3:mother-01", _event(0, "3:mother-01", "ENROLLED", "k0"), "k0")
    view = ReadOnlyStoreView(store)
    assert not hasattr(view, "append")  # structurally enforced, not by convention

    pack = rulepack.load(PACK_PATH)
    read_case, _, _, _ = agent_tools.make_tools(view, pack)
    result_json = read_case("3:mother-01")
    assert "mother-01" in result_json or "Test Mother" in result_json


def test_injection_style_case_id_yields_no_write_and_no_crash():
    store = MemoryStore()
    store.append("3:mother-01", _event(0, "3:mother-01", "ENROLLED", "k0"), "k0")
    view = ReadOnlyStoreView(store)
    pack = rulepack.load(PACK_PATH)
    read_case, _, _, _ = agent_tools.make_tools(view, pack)

    before = len(store.events("3:mother-01"))
    injected = "3:mother-01'; store.append(events); DROP TABLE cases; --"
    result = read_case(injected)
    assert "error" in result  # no such case_id — the injected string is just a lookup key, nothing else
    assert len(store.events("3:mother-01")) == before  # untouched


def test_read_rule_returns_citation_for_known_rule_and_error_for_unknown():
    pack = rulepack.load(PACK_PATH)
    view = ReadOnlyStoreView(MemoryStore())
    _, read_rule, _, _ = agent_tools.make_tools(view, pack)

    found = read_rule("NB-01")
    assert "source_quote" in found and "URGENT_FACILITY_NOW" in found

    missing = read_rule("NOT-A-REAL-RULE")
    assert "error" in missing


def test_draft_message_delegates_to_quiet_templates():
    pack = rulepack.load(PACK_PATH)
    view = ReadOnlyStoreView(MemoryStore())
    _, _, _, draft_message = agent_tools.make_tools(view, pack)

    from agent import quiet

    expected = quiet.render("review", "en", {"name": "X"})["text"]
    assert draft_message("review", "en", {"name": "X"}) == expected


def test_translate_known_pair_and_honest_gap_on_unknown_text():
    pack = rulepack.load(PACK_PATH)
    view = ReadOnlyStoreView(MemoryStore())
    _, _, translate, _ = agent_tools.make_tools(view, pack)

    from agent import quiet

    en_text = quiet._TEMPLATES["review"]["en"]
    hi_text = quiet._TEMPLATES["review"]["hi"]
    assert translate(en_text, "hi") == hi_text
    assert translate(hi_text, "en") == en_text

    result = translate("some completely novel sentence nobody templated", "hi")
    assert result.startswith("[untranslated:hi]")
