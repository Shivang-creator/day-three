"""ADK writer agent toolset (PLAN §4.9, T-18). `make_tools(store_view, pack)`
returns the four bound tool callables with the exact PLAN signatures —
`read_case(case_id)`, `read_rule(rule_id)`, `translate(text, to)`,
`draft_message(intent, lang, facts)`. `store_view` and `pack` are captured
in a closure at build time, never exposed as a parameter the model itself
could supply — there is nothing for a prompt-injected reply to substitute.

None of the four writes anything: read_case/read_rule only read (through
`store_view.events()` and `pack.rules`); translate/draft_message are pure
string transforms with no store or file access at all. This is the concrete
shape of PLAN §1.3's "scoped tools" claim — a prompt-injected reply has no
write method reachable from inside the agent, structurally, not by
convention. (tests/test_boundary.py::test_agent_directory_never_imports_the_store_module
additionally guarantees this whole directory can't even `import store`.)
"""
from __future__ import annotations

import dataclasses
import json
import logging

from agent import quiet
from core.events import reduce

logger = logging.getLogger("agent.tools")

_HINDI_RANGE = range(0x0900, 0x0980)


def _is_hindi(text: str) -> bool:
    return any(ord(ch) in _HINDI_RANGE for ch in text)


_template_pairs_cache: dict[str, str] | None = None


def _template_pairs() -> dict[str, str]:
    """A best-effort English<->Hindi lookup built from agent/templates.json's
    own reviewed parallel text — used by translate() for exact matches.
    Not a general MT model; see translate()'s docstring for why."""
    global _template_pairs_cache
    if _template_pairs_cache is None:
        pairs: dict[str, str] = {}
        for entry in quiet._TEMPLATES.values():
            en, hi = entry.get("en"), entry.get("hi")
            if en and hi:
                pairs[en] = hi
                pairs[hi] = en
        _template_pairs_cache = pairs
    return _template_pairs_cache


def make_tools(store_view, pack):
    """`store_view` must be a ReadOnlyStoreView (or anything exposing only
    `.events()`/`.case_ids()`) and `pack` a loaded core.rulepack.RulePack.
    Returns `(read_case, read_rule, translate, draft_message)`."""

    def read_case(case_id: str) -> str:
        """Return the case's current state (mother, rung, flags, route
        history) as JSON, reduced from its event log. Never returns raw
        events, never accepts anything but a case_id string — there is no
        code path from this string to a write, injected or not."""
        events = store_view.events(case_id)
        if not events:
            return json.dumps({"error": f"no such case_id: {case_id}"})
        state = reduce(events)
        return state.to_json()

    def read_rule(rule_id: str) -> str:
        """Return one rule's shape, including its citation (source_id,
        source_quote, source_url) — the model quotes this, it never invents
        a citation. An unknown rule_id is an explicit JSON error, not a
        guess the model could fill in on its own."""
        for rule in pack.rules:
            if rule.rule_id == rule_id:
                return json.dumps(dataclasses.asdict(rule))
        return json.dumps({"error": f"no such rule_id: {rule_id}"})

    def _translate_with_gemma(text: str, to: str) -> str | None:
        """Fallback translation using Google Gemma (e.g. gemma-2-2b-it / gemma-2-9b-it)
        via Google GenAI or local model when reviewed templates have no exact match."""
        gemma_model = os.environ.get("GEMMA_MODEL", "gemma-2-2b-it")
        api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GEMMA_API_KEY")
        if not api_key or os.environ.get("MODEL_OFF", "0") == "1":
            return None
        try:
            from google import genai
            from google.genai import types
            client = genai.Client(api_key=api_key)
            target_lang = "Hindi" if to == "hi" else "English"
            prompt = f"Translate the following medical/postnatal message into {target_lang}. Return ONLY the direct translation:\n\n{text}"
            config = types.GenerateContentConfig(
                temperature=0.1,
                http_options=types.HttpOptions(timeout=5000),
            )
            resp = client.models.generate_content(model=gemma_model, contents=prompt, config=config)
            if resp and resp.text:
                return resp.text.strip()
        except Exception as exc:
            logger.warning("Gemma translation fallback skipped: %s", exc)
        return None

    def translate(text: str, to: str) -> str:
        """Translate `text` to "hi" or "en" using reviewed parallel templates
        with Google Gemma (gemma-2-2b-it) as intelligent fallback for non-templated text.
        If both are offline/unreachable, returns an honest '[untranslated:<lang>]' gap."""
        if to not in ("en", "hi"):
            return json.dumps({"error": f"unsupported target language: {to}"})
        pairs = _template_pairs()
        candidate = pairs.get(text)
        if candidate is not None and _is_hindi(candidate) == (to == "hi"):
            return candidate
        gemma_trans = _translate_with_gemma(text, to)
        if gemma_trans:
            return gemma_trans
        logger.warning("agent.tools.translate: no known translation for text (len=%d) to %r", len(text), to)
        return f"[untranslated:{to}] {text}"

    def draft_message(intent: str, lang: str, facts: dict) -> str:
        """Deterministic, pack-reviewed template text for a known intent
        (PLAN §4.9: "routine rung check-ins are templates; the model drafts
        only escalation messages"). Always prefer this over free
        composition for anything that has a template. Delegates to
        agent/quiet.py so there is exactly one place template text is
        filled, in or out of Quiet Mode."""
        return quiet.render(intent, lang, facts)["text"]

    return read_case, read_rule, translate, draft_message

