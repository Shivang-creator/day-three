"""Loads and validates a rule pack (PLAN §4.4). Rules are data, not code: this
module only evaluates shape and citations, it never encodes clinical
judgement. `rules/schema.json` documents the structure; the checks below are
hand-rolled stdlib (no jsonschema dependency — see PLAN §2 core boundary).
"""
from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "rules" / "schema.json"

ROUTES = frozenset(
    {
        "HUMAN_REVIEW_NOW",
        "URGENT_FACILITY_NOW",
        "SAME_DAY_VISIT",
        "HUMAN_REVIEW",
        "NEXT_CONTACT",
    }
)

SELF_HARM_SIGN_ID = "M_SELF_HARM"


class RulePackError(ValueError):
    """Raised with the offending entry named in the message, e.g.
    "rule 'NB-01': source_id 'WHO-X' not found in sources"."""


@dataclasses.dataclass(frozen=True)
class Source:
    source_id: str
    title: str
    url: str
    accessed: str


@dataclasses.dataclass(frozen=True)
class LadderRung:
    rung: str
    due_hours_after_discharge: float
    window_hours: float
    variant: str
    source_id: str
    source_quote: str
    source_url: str
    fact_id: str | None = None  # the granular research-fact id (e.g. "SCHED-PCPNC-C2"), if any


@dataclasses.dataclass(frozen=True)
class Sign:
    sign_id: str
    subject: str
    severity: str
    label_en: str
    label_hi: str
    keypad: str
    source_id: str
    source_quote: str
    source_url: str
    fact_id: str | None = None


@dataclasses.dataclass(frozen=True)
class Rule:
    rule_id: str
    when: dict
    route: str
    actions: tuple
    source_id: str
    source_quote: str
    source_url: str
    fact_id: str | None = None


@dataclasses.dataclass(frozen=True)
class SilencePolicy:
    retry_after_hours: float
    max_retries: int
    then: tuple
    source_id: str
    source_quote: str
    source_url: str
    fact_id: str | None = None
    silence_id: str | None = None
    timing_sourced: bool | None = None
    timing_note: str | None = None


@dataclasses.dataclass(frozen=True)
class Clinic:
    open: str
    close: str
    slot_minutes: int
    urgent_reserve_per_day: int
    tz: str


@dataclasses.dataclass(frozen=True)
class RulePack:
    pack_id: str
    version: str
    reviewed_by: str | None
    sources: tuple  # tuple[Source, ...]
    ladder: tuple  # tuple[LadderRung, ...]
    signs: tuple  # tuple[Sign, ...]
    rules: tuple  # tuple[Rule, ...]
    silence: SilencePolicy
    clinic: Clinic
    not_modelled: tuple = ()  # raw dicts: {"id","subject","reason"} — topics explicitly excluded, cited nowhere else
    disagreements: tuple = ()  # raw dicts: {"id","topic","reading_a","reading_b","applied","source_ids"}


def load(path: str | Path) -> RulePack:
    raw = json.loads(Path(path).read_text())
    _check_required_top_level(raw)

    sources = _build_sources(raw)
    source_ids = {s.source_id for s in sources}

    ladder = _build_ladder(raw, source_ids)
    signs = _build_signs(raw, source_ids)
    sign_ids = {s.sign_id for s in signs}
    rules = _build_rules(raw, source_ids, sign_ids)
    silence = _build_silence(raw, source_ids)
    clinic = _build_clinic(raw)

    _check_unique_rule_ids(rules)
    _check_self_harm_shape(signs, rules)

    return RulePack(
        pack_id=_require_str(raw, "pack_id", "rule pack"),
        version=_require_str(raw, "version", "rule pack"),
        reviewed_by=raw.get("reviewed_by"),
        sources=tuple(sources),
        ladder=tuple(ladder),
        signs=tuple(signs),
        rules=tuple(rules),
        silence=silence,
        clinic=clinic,
        not_modelled=tuple(raw.get("not_modelled", [])),
        disagreements=tuple(raw.get("disagreements", [])),
    )


# ---------------------------------------------------------------- helpers --


def _require_str(d: dict, key: str, ctx: str) -> str:
    v = d.get(key)
    if not isinstance(v, str) or not v.strip():
        raise RulePackError(f"{ctx}: missing or empty '{key}'")
    return v


def _check_required_top_level(raw: dict) -> None:
    schema = json.loads(SCHEMA_PATH.read_text())
    for key in schema["required"]:
        if key not in raw:
            raise RulePackError(f"rule pack: missing required top-level key '{key}'")


def _check_citation(entry: dict, ctx: str, source_ids: set[str]) -> None:
    source_id = entry.get("source_id")
    if not isinstance(source_id, str) or not source_id.strip():
        raise RulePackError(f"{ctx}: missing or empty 'source_id'")
    if source_id not in source_ids:
        raise RulePackError(f"{ctx}: source_id '{source_id}' not found in sources")

    quote = entry.get("source_quote")
    if not isinstance(quote, str) or len(quote) < 20:
        raise RulePackError(
            f"{ctx}: source_quote must be at least 20 characters (got {len(quote) if isinstance(quote, str) else 0})"
        )

    url = entry.get("source_url")
    if not isinstance(url, str) or not url.startswith("http"):
        raise RulePackError(f"{ctx}: source_url must start with 'http' (got {url!r})")


def _build_sources(raw: dict) -> list[Source]:
    out = []
    for i, s in enumerate(raw.get("sources", [])):
        ctx = f"source #{i}"
        out.append(
            Source(
                source_id=_require_str(s, "source_id", ctx),
                title=_require_str(s, "title", ctx),
                url=_require_str(s, "url", ctx),
                accessed=_require_str(s, "accessed", ctx),
            )
        )
    if not out:
        raise RulePackError("rule pack: 'sources' must be non-empty")
    return out


def _build_ladder(raw: dict, source_ids: set[str]) -> list[LadderRung]:
    out = []
    for entry in raw.get("ladder", []):
        rung = entry.get("rung", "<unknown>")
        ctx = f"ladder rung '{rung}'"
        _check_citation(entry, ctx, source_ids)
        out.append(
            LadderRung(
                rung=_require_str(entry, "rung", ctx),
                due_hours_after_discharge=entry["due_hours_after_discharge"],
                window_hours=entry["window_hours"],
                variant=_require_str(entry, "variant", ctx),
                source_id=entry["source_id"],
                source_quote=entry["source_quote"],
                source_url=entry["source_url"],
                fact_id=entry.get("fact_id"),
            )
        )
    if not out:
        raise RulePackError("rule pack: 'ladder' must be non-empty")
    return out


def _build_signs(raw: dict, source_ids: set[str]) -> list[Sign]:
    out = []
    for entry in raw.get("signs", []):
        sign_id = entry.get("sign_id", "<unknown>")
        ctx = f"sign '{sign_id}'"
        _check_citation(entry, ctx, source_ids)
        label_hi = entry.get("label_hi")
        if not isinstance(label_hi, str) or not label_hi.strip():
            raise RulePackError(f"{ctx}: missing Hindi label 'label_hi'")
        out.append(
            Sign(
                sign_id=_require_str(entry, "sign_id", ctx),
                subject=_require_str(entry, "subject", ctx),
                severity=_require_str(entry, "severity", ctx),
                label_en=_require_str(entry, "label_en", ctx),
                label_hi=label_hi,
                keypad=_require_str(entry, "keypad", ctx),
                source_id=entry["source_id"],
                source_quote=entry["source_quote"],
                source_url=entry["source_url"],
                fact_id=entry.get("fact_id"),
            )
        )
    if not out:
        raise RulePackError("rule pack: 'signs' must be non-empty")
    return out


def _referenced_sign_ids(when: dict) -> set[str]:
    """Flatten every list-of-strings value in a `when` clause (any_of, all_of,
    ...future combinators) into the set of sign_ids it references."""
    ids: set[str] = set()
    for value in when.values():
        if isinstance(value, list):
            ids.update(v for v in value if isinstance(v, str))
    return ids


def _build_rules(raw: dict, source_ids: set[str], sign_ids: set[str]) -> list[Rule]:
    out = []
    for entry in raw.get("rules", []):
        rule_id = entry.get("rule_id", "<unknown>")
        ctx = f"rule '{rule_id}'"
        _check_citation(entry, ctx, source_ids)

        when = entry.get("when")
        if not isinstance(when, dict) or not when:
            raise RulePackError(f"{ctx}: 'when' must be a non-empty object")
        for sid in _referenced_sign_ids(when):
            if sid not in sign_ids:
                raise RulePackError(f"{ctx}: references unknown sign '{sid}'")

        route = entry.get("route")
        if route not in ROUTES:
            raise RulePackError(f"{ctx}: route '{route}' is not one of {sorted(ROUTES)}")

        actions = entry.get("actions")
        if not isinstance(actions, list) or not actions:
            raise RulePackError(f"{ctx}: 'actions' must be a non-empty list")

        out.append(
            Rule(
                rule_id=_require_str(entry, "rule_id", ctx),
                when=when,
                route=route,
                actions=tuple(actions),
                source_id=entry["source_id"],
                source_quote=entry["source_quote"],
                source_url=entry["source_url"],
                fact_id=entry.get("fact_id"),
            )
        )
    if not out:
        raise RulePackError("rule pack: 'rules' must be non-empty")
    return out


def _build_silence(raw: dict, source_ids: set[str]) -> SilencePolicy:
    entry = raw.get("silence")
    if not isinstance(entry, dict):
        raise RulePackError("rule pack: missing 'silence' policy")
    ctx = "silence policy"
    _check_citation(entry, ctx, source_ids)
    then = entry.get("then")
    if not isinstance(then, list) or not then:
        raise RulePackError(f"{ctx}: 'then' must be a non-empty list")
    return SilencePolicy(
        retry_after_hours=entry["retry_after_hours"],
        max_retries=entry["max_retries"],
        then=tuple(then),
        source_id=entry["source_id"],
        source_quote=entry["source_quote"],
        source_url=entry["source_url"],
        fact_id=entry.get("fact_id"),
        silence_id=entry.get("silence_id"),
        timing_sourced=entry.get("timing_sourced"),
        timing_note=entry.get("timing_note"),
    )


def _build_clinic(raw: dict) -> Clinic:
    entry = raw.get("clinic")
    if not isinstance(entry, dict):
        raise RulePackError("rule pack: missing 'clinic' table")
    ctx = "clinic table"
    return Clinic(
        open=_require_str(entry, "open", ctx),
        close=_require_str(entry, "close", ctx),
        slot_minutes=entry["slot_minutes"],
        urgent_reserve_per_day=entry["urgent_reserve_per_day"],
        tz=_require_str(entry, "tz", ctx),
    )


def _check_unique_rule_ids(rules: list[Rule]) -> None:
    """rule_id is the pack's own primary key (it is what a fired Verdict cites
    back to the nurse) — two rules sharing one would make citations ambiguous.

    Earlier drafts of this loader instead required each *route* to be claimed
    by exactly one rule. That was wrong: gate.py computes the route from sign
    severity (PLAN §4.5), and `rules[]` exists to give every individual danger
    sign its own citation — e.g. ten different newborn-red signs each need
    their own rule_id and source_quote, all correctly routing
    URGENT_FACILITY_NOW. A pack with real WHO/HBNC citations (T-07) could
    never satisfy one-rule-per-route once it grew past five rules total.
    See regression test test_multiple_rules_may_share_one_route.
    """
    seen: dict[str, int] = {}
    for i, r in enumerate(rules):
        if r.rule_id in seen:
            raise RulePackError(
                f"rule '{r.rule_id}': rule_id already used by rule at index {seen[r.rule_id]} "
                "(rule_id must be unique — it is the citation key)"
            )
        seen[r.rule_id] = i


def _check_self_harm_shape(signs: list[Sign], rules: list[Rule]) -> None:
    self_harm = next((s for s in signs if s.sign_id == SELF_HARM_SIGN_ID), None)
    if self_harm is None:
        raise RulePackError(f"rule pack: sign '{SELF_HARM_SIGN_ID}' (EPDS item 10) is required")
    if self_harm.severity != "red":
        raise RulePackError(f"sign '{SELF_HARM_SIGN_ID}': severity must be 'red' (got {self_harm.severity!r})")

    owning_rule = next(
        (r for r in rules if SELF_HARM_SIGN_ID in _referenced_sign_ids(r.when)),
        None,
    )
    if owning_rule is None:
        raise RulePackError(f"rule pack: no rule references sign '{SELF_HARM_SIGN_ID}'")
    if owning_rule.route != "HUMAN_REVIEW_NOW":
        raise RulePackError(
            f"rule '{owning_rule.rule_id}': the '{SELF_HARM_SIGN_ID}' rule must route "
            f"'HUMAN_REVIEW_NOW' (got {owning_rule.route!r}) — self-harm is never an automated closure"
        )
    if "PAGE_NURSE" not in owning_rule.actions:
        raise RulePackError(
            f"rule '{owning_rule.rule_id}': the '{SELF_HARM_SIGN_ID}' rule must include a 'PAGE_NURSE' action"
        )
