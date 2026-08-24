"""The Danger-Sign Gate (PLAN §4.5). Pure function of a SymptomForm and a
RulePack — no model, no I/O. The structural answer to "a confident LLM
triaging newborns": normalise() makes it impossible for a free-text reader
to ever clear a sign to False, and evaluate() never asks the model anything
— it only reads what normalise/merge already decided.
"""
from __future__ import annotations

import dataclasses

from core.models import SymptomForm, Verdict
from core.rulepack import SELF_HARM_SIGN_ID, RulePack

# Total precedence order, most urgent first (PLAN §4.5). HUMAN_REVIEW_NOW and
# URGENT_FACILITY_NOW are deliberately different tiers: self-harm is never
# folded into "any red true" — it is escalated straight past the routine
# facility-visit route to a human, unconditionally, every time.
ROUTE_PRECEDENCE = (
    "HUMAN_REVIEW_NOW",
    "URGENT_FACILITY_NOW",
    "SAME_DAY_VISIT",
    "HUMAN_REVIEW",
    "NEXT_CONTACT",
)


def normalise(form: SymptomForm, pack: RulePack) -> SymptomForm:
    """Every sign in the pack is present in the result (missing -> "unknown").
    If `form.origin == "free_text"`, any `False` becomes "unknown" — a
    free-text reader can raise a sign to true, or leave it unknown, but it
    can never clear one to false. Only a keypad or nurse form may say "no".
    """
    signs = dict(form.signs)
    for s in pack.signs:
        signs.setdefault(s.sign_id, "unknown")
    if form.origin == "free_text":
        signs = {sid: ("unknown" if v is False else v) for sid, v in signs.items()}
    return dataclasses.replace(form, signs=signs)


def merge(keypad: SymptomForm, reader: SymptomForm) -> SymptomForm:
    """keypad ⊕ reader: true if either says true; false only if keypad says
    false (reader can never introduce a false — see normalise). Unknown
    otherwise. The result carries keypad's origin (it is the authoritative,
    human-operated channel) but folds in the reader's model attribution."""
    if keypad.subject != reader.subject:
        raise ValueError(f"cannot merge forms for different subjects: {keypad.subject!r} vs {reader.subject!r}")

    merged: dict[str, bool | str] = {}
    for sid in set(keypad.signs) | set(reader.signs):
        k = keypad.signs.get(sid, "unknown")
        r = reader.signs.get(sid, "unknown")
        if k is True or r is True:
            merged[sid] = True
        elif k is False:
            merged[sid] = False
        else:
            merged[sid] = "unknown"

    return dataclasses.replace(
        keypad,
        signs=merged,
        reader=reader.reader if reader.reader != "none" else keypad.reader,
        source_text=reader.source_text or keypad.source_text,
    )


def _when_sign_ids(when: dict) -> set[str]:
    ids: set[str] = set()
    for value in when.values():
        if isinstance(value, list):
            ids.update(v for v in value if isinstance(v, str))
    return ids


def _fired_rules_for(pack: RulePack, true_sign_ids: set[str]) -> list[dict]:
    """Every rule whose `when` overlaps the given true signs, as citation
    entries for Verdict.fired. A sign may be covered by more than one rule
    in principle; the real pack (T-07) uses one rule per sign, so this is
    normally a 1:1 match, but the gate does not assume that."""
    fired = []
    for r in pack.rules:
        matched = true_sign_ids & _when_sign_ids(r.when)
        if matched:
            fired.append(
                {
                    "rule_id": r.rule_id,
                    "signs": tuple(sorted(matched)),
                    "source_id": r.source_id,
                    "source_quote": r.source_quote,
                }
            )
    return fired


def evaluate(form: SymptomForm, pack: RulePack) -> Verdict:
    """The total precedence order (PLAN §4.5):
    HUMAN_REVIEW_NOW (self-harm true) > URGENT_FACILITY_NOW (any red true) >
    SAME_DAY_VISIT (any yellow true) > HUMAN_REVIEW (nothing true, >=1 red
    unknown) > NEXT_CONTACT (everything known false).

    `form` is normalised first, so calling evaluate() directly on a raw
    free-text reader form is safe — it can never resolve to NEXT_CONTACT.
    """
    form = normalise(form, pack)
    severity = {s.sign_id: s.severity for s in pack.signs}

    if form.signs.get(SELF_HARM_SIGN_ID) is True:
        fired = _fired_rules_for(pack, {SELF_HARM_SIGN_ID})
        unknown = tuple(sorted(sid for sid, v in form.signs.items() if v == "unknown" and sid in severity))
        return Verdict(route="HUMAN_REVIEW_NOW", fired=tuple(fired), unknown=unknown, tag="Rule")

    true_signs = {sid for sid, v in form.signs.items() if v is True and sid in severity}
    unknown_signs = {sid for sid, v in form.signs.items() if v == "unknown" and sid in severity}

    red_true = {sid for sid in true_signs if severity[sid] == "red"}
    yellow_true = {sid for sid in true_signs if severity[sid] == "yellow"}
    red_unknown = {sid for sid in unknown_signs if severity[sid] == "red"}

    if red_true:
        route = "URGENT_FACILITY_NOW"
        fired = _fired_rules_for(pack, red_true)
    elif yellow_true:
        route = "SAME_DAY_VISIT"
        fired = _fired_rules_for(pack, yellow_true)
    elif red_unknown:
        route = "HUMAN_REVIEW"
        fired = []
    else:
        route = "NEXT_CONTACT"
        fired = []

    return Verdict(route=route, fired=tuple(fired), unknown=tuple(sorted(unknown_signs)), tag="Rule")
