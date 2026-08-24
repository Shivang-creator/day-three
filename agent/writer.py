"""agent/writer.py::render — runs the ADK writer agent (agent/agent.py) for
one drafting turn and returns a message in the shape every downstream
caller (routing, outbox, UI) expects, whether or not the model actually
ran:
    {"text": str, "tag": "Generated" | "Rule", "model": str, "degraded": bool}

Defense in depth for the kill-switch doctrine ("every verdict stays
byte-identical; the UI shows its degraded label"): render() checks
`gemini_client.model_enabled()` itself and falls straight through to
agent/quiet.py's deterministic templates when the model is off or no key
is configured — it never even builds an ADK agent in that case, and any
failure *during* a real run (timeout, malformed output, ADK error) is
logged loudly and degrades the exact same way. T-19 wires a per-seed
override on top of this same check; this file is what makes the
underlying kill-switch claim true rather than aspirational.
"""
from __future__ import annotations

import logging
import os

from google.genai import types

from agent import agent as agent_module
from agent import gemini_client
from agent import quiet

logger = logging.getLogger("agent.writer")


class _EmptyStoreView:
    """Used when render() is called without a real store_view — e.g. a pure
    template intent with no case context needed yet. The agent's read_case
    tool still works, it just always reports "no such case_id"."""

    def events(self, case_id):  # noqa: ARG002
        return []

    def case_ids(self, namespace):  # noqa: ARG002
        return []


class _EmptyPack:
    """Used when render() is called without a real rule pack. read_rule
    still works, it just always reports "no such rule_id"."""

    rules: tuple = ()


_EMPTY_STORE_VIEW = _EmptyStoreView()
_EMPTY_PACK = _EmptyPack()


def render(intent: str, lang: str, facts: dict, *, store_view=None, pack=None, timeout_s: int = 20) -> dict:
    """Draft the message for `intent` in `lang` given `facts`. `store_view`
    (a ReadOnlyStoreView) and `pack` (a loaded core.rulepack.RulePack) are
    optional — pass them so the agent's read_case/read_rule tools have real
    data to cite; omitting them still runs, those two tools just report
    "not found" if the model tries them."""
    model = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash")

    if not gemini_client.model_enabled():
        reason = "MODEL_OFF=1" if os.environ.get("MODEL_OFF", "0") == "1" else "no GEMINI_API_KEY configured"
        logger.error(
            "MODEL_FALLBACK agent.writer.render: model disabled (%s) — Quiet template for intent=%r",
            reason,
            intent,
        )
        return quiet.render(intent, lang, facts)

    try:
        writer = agent_module.build_writer(store_view or _EMPTY_STORE_VIEW, pack or _EMPTY_PACK, model=model)
        runner, session_service = agent_module.runner_for(writer)
        session = session_service.create_session_sync(app_name=agent_module.APP_NAME, user_id="orchestrator")
        prompt = (
            f'Draft the "{intent}" message in language "{lang}" using these facts: {facts}. '
            "Prefer draft_message for a known intent; use read_case/read_rule only if you need "
            "more context; use translate only for freely composed text. Reply with the message "
            "text only, nothing else."
        )
        new_message = types.Content(role="user", parts=[types.Part(text=prompt)])

        text = None
        for event in runner.run(user_id="orchestrator", session_id=session.id, new_message=new_message):
            if event.is_final_response() and event.content and event.content.parts:
                text = "".join(part.text for part in event.content.parts if getattr(part, "text", None))

        if not text or not text.strip():
            raise ValueError("empty response from writer agent")

        return {"text": text.strip(), "tag": "Generated", "model": model, "degraded": False}

    except Exception as exc:  # noqa: BLE001 - a dead model must degrade loudly, never blank the outbox
        logger.error(
            "MODEL_FALLBACK agent.writer.render: intent=%r reason=%s: %s — falling back to Quiet template",
            intent,
            type(exc).__name__,
            exc,
        )
        fallback = quiet.render(intent, lang, facts)
        fallback["reason"] = f"{type(exc).__name__}: {exc}"
        return fallback
