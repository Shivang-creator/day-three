"""Quiet Mode rendering (PLAN §4.9 / §10): when the kill-switch is off
(`MODEL_OFF=1`, no key, or a per-seed toggle T-19 wires in) every message
comes from `agent/templates.json` — no network call is even attempted. This
is the honest degraded state the UI shows; it must never look identical to
a live model draft, which is why every result carries `degraded: True` and
`model: "template"` rather than a real model string.

`agent/writer.py` (T-18) is the only thing that decides *whether* to call
this instead of the model; this module itself never checks MODEL_OFF — it
always renders from templates, so it also doubles as the deterministic
fallback path gemini_client.py's own failures route to.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger("agent.quiet")

TEMPLATES_PATH = Path(__file__).resolve().parent / "templates.json"


def _load_templates() -> dict:
    return json.loads(TEMPLATES_PATH.read_text(encoding="utf-8"))


_TEMPLATES = _load_templates()


def render(intent: str, lang: str, facts: dict) -> dict:
    """Fill `agent/templates.json[intent][lang]` with `facts` (a plain
    dict — {name}, {clinic_address}, {slot_time}, {rung}, ...). Returns the
    same shape a model draft would (`text`, `tag`, `model`, `degraded`) so a
    caller never branches on whether the model was involved; only the
    epistemic-tag pill in the UI does.

    Never raises: an unknown intent, missing language, or missing fact all
    degrade to *something* renderable, loudly logged (a dead template must
    not blank the outbox any more than a dead model may)."""
    if intent not in _TEMPLATES:
        logger.error("quiet.render: unknown intent %r — no template exists", intent)
        return {"text": f"[no template for intent '{intent}']", "tag": "Rule", "model": "template", "degraded": True}

    entry = _TEMPLATES[intent]
    use_lang = lang if lang in entry else "en"
    if use_lang != lang:
        logger.error("quiet.render: intent %r has no %r template, falling back to 'en'", intent, lang)
    template = entry.get(use_lang, "")

    try:
        text = template.format(**facts)
    except (KeyError, IndexError) as exc:
        logger.error("quiet.render: template %r/%r missing fact %s — rendering unfilled", intent, use_lang, exc)
        text = template

    return {"text": text, "tag": "Rule", "model": "template", "degraded": True}


def known_intents() -> list[str]:
    return sorted(_TEMPLATES.keys())
