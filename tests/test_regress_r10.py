"""R-10 named regression (RED-TEAM.md Attack 4 / BOARD.md): README claims
"every rule ... carries a verbatim source_quote and URL" — but
`M-SELF-HARM-01` (and its sign `M_SELF_HARM`) quoted the crew's OWN
research note ("Do not invent a threshold or a route for this...") while
citing it under a WHO landing-page URL that does not contain that
sentence. Fix: both entries' `source_url` (and the `RESEARCH-NOTE` source
list entry's own `url`) now point at `research/RULES-SOURCE.md` (via a
real, fetchable raw GitHub URL) — the file that actually contains the
quoted sentence — instead of a WHO domain.
"""
from __future__ import annotations

from pathlib import Path

from core.rulepack import load

RULES_PATH = Path(__file__).resolve().parent.parent / "rules" / "postnatal.v1.json"
RESEARCH_SOURCE_PATH = Path(__file__).resolve().parent.parent / "research" / "RULES-SOURCE.md"


def test_regress_r10_self_harm_rule_and_sign_do_not_cite_a_who_url():
    pack = load(RULES_PATH)

    self_harm_sign = next(s for s in pack.signs if s.sign_id == "M_SELF_HARM")
    self_harm_rule = next(r for r in pack.rules if r.rule_id == "M-SELF-HARM-01")

    for entry, name in ((self_harm_sign, "sign M_SELF_HARM"), (self_harm_rule, "rule M-SELF-HARM-01")):
        assert entry.source_id == "RESEARCH-NOTE"
        assert "who.int" not in entry.source_url, (
            f"{name}: source_quote is the crew's own research note, not WHO text — "
            f"source_url must not point at a WHO domain (R-10), got {entry.source_url!r}"
        )
        assert "RULES-SOURCE.md" in entry.source_url


def test_regress_r10_research_note_source_url_matches_the_two_entries():
    pack = load(RULES_PATH)
    research_source = next(s for s in pack.sources if s.source_id == "RESEARCH-NOTE")
    assert "who.int" not in research_source.url
    assert "RULES-SOURCE.md" in research_source.url


def test_regress_r10_the_quoted_sentence_actually_lives_in_the_research_note():
    pack = load(RULES_PATH)
    self_harm_rule = next(r for r in pack.rules if r.rule_id == "M-SELF-HARM-01")
    text = RESEARCH_SOURCE_PATH.read_text()
    # Normalise the em-dash/whitespace exactly as the pack does — this is
    # the actual verbatim-quote guarantee, checked against the real file.
    assert "Do not invent a threshold or a route for this" in text
    assert self_harm_rule.source_quote.split(" — ")[0] in text
