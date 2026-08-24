"""agent/reader.py::read — turns a mother's free-text reply into a
SymptomForm (PLAN §4.5 / §4.9). Calls `gemini_client.generate_json`
directly rather than standing up a second ADK LlmAgent, so the reader
inherits the exact same cache / hard-timeout / kill-switch / round-robin
guarantees as every other model call in this repo — and so a replay of the
same text is free (PLAN §10 depends on that).

Verified against the installed `google-adk==2.7.1` (never from memory): its
own `LlmAgent.output_schema` docstring says plainly "The ADK supports using
output_schema and tools together", so nothing here is forced by an ADK
limitation the plan anticipated — routing through gemini_client is a
deliberate choice to reuse its guarantees instead of re-implementing them
around a second agent that would otherwise bypass caching entirely.

The output schema has no free-text "assessment" field, ever: only a
true|unknown value per known sign and an `unclear` list of unmapped
phrases. Even a model that wanted to assert a sign is absent has no
`false` slot to put it in — this is the reader-level half of PLAN §4.5's
"the reader can never clear" guarantee (core/gate.py::normalise is the
second, structural half, for defense in depth: it rewrites any stray
`false` to `unknown` too, in case a future schema is ever loosened).
"""
from __future__ import annotations

import logging
import sys

from agent import gemini_client
from core.models import SymptomForm

logger = logging.getLogger("agent.reader")


def _schema_for_pack(pack) -> dict:
    sign_ids = [s.sign_id for s in pack.signs]
    return {
        "type": "object",
        "properties": {
            "signs": {
                "type": "object",
                "properties": {sid: {"type": "string", "enum": ["true", "unknown"]} for sid in sign_ids},
                "required": sign_ids,
                "additionalProperties": False,
            },
            "unclear": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["signs", "unclear"],
        "additionalProperties": False,
    }


def _prompt_for(text: str, pack) -> str:
    sign_lines = "\n".join(f'- {s.sign_id}: "{s.label_en}"' for s in pack.signs)
    return (
        "A mother in a postnatal follow-up programme sent this reply about "
        f'her or her newborn\'s condition:\n\n"{text}"\n\n'
        "For each of the following known danger signs, decide only whether "
        'the reply CLEARLY states it is present ("true") — otherwise say '
        '"unknown". Never claim a sign is absent; if the reply does not '
        "clearly say a sign is present, that sign is unknown, not false, "
        "even if the reply sounds reassuring. Known signs:\n"
        f"{sign_lines}\n\n"
        "List in `unclear` any symptom-shaped phrases in the reply you could "
        "not map to one of the known signs above, verbatim, so a nurse can "
        "read them. Do not add any other field or free-text assessment."
    )


def read(text: str, pack, *, subject: str = "newborn", store=None, timeout_s: int = 20) -> SymptomForm:
    """`pack` is a loaded core.rulepack.RulePack. `store`, if given, is the
    same duck-typed cache object gemini_client.generate_json accepts — pass
    the real Store (never a ReadOnlyStoreView; the reader isn't a tool the
    agent calls itself, it's the shell reading a reply) to make a replay of
    the same text free."""
    sign_ids = [s.sign_id for s in pack.signs]
    schema = _schema_for_pack(pack)
    prompt = _prompt_for(text, pack)
    result = gemini_client.generate_json(prompt, schema, timeout_s=timeout_s, store=store)

    if result.get("degraded"):
        logger.error(
            "MODEL_FALLBACK agent.reader.read: reason=%s — returning an all-unknown SymptomForm "
            "(the honest visible failure: 'no reader available, a nurse reads this reply')",
            result.get("reason"),
        )
        return SymptomForm(
            subject=subject,
            signs={sid: "unknown" for sid in sign_ids},
            origin="free_text",
            reader="gemini",
            source_text=text,
            reader_confidence=0.0,
        )

    raw_signs = result.get("signs", {})
    signs = {sid: (True if raw_signs.get(sid) == "true" else "unknown") for sid in sign_ids}

    return SymptomForm(
        subject=subject,
        signs=signs,
        origin="free_text",
        reader="gemini",
        source_text=text,
        reader_confidence=1.0,
    )


if __name__ == "__main__":  # pragma: no cover - manual smoke check (T-18 accept criterion)
    from core import rulepack

    text_arg = sys.argv[1] if len(sys.argv) > 1 else "baby not feeding since morning, feels hot"
    pack_path = sys.argv[2] if len(sys.argv) > 2 else "rules/postnatal.v1.json"
    loaded_pack = rulepack.load(pack_path)
    form = read(text_arg, loaded_pack)
    print(form.to_json())
