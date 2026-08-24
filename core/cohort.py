"""Synthetic mother cohort generator (PLAN §4.8). Deterministic: the same
seed always produces the same mothers (`generate`) and the same per-mother
scripted reply at every rung (`scripted_reply`) — this is what makes a
sweep, and therefore a whole demo, byte-for-byte replayable. Uses
`random.Random(seed)` only, never the shared `random` module state, so two
calls in the same process never interfere with each other.
"""
from __future__ import annotations

import random

from core.models import Mother, SymptomForm
from core.rulepack import RulePack

# Fixed synthetic first-name list (PLAN §4.8) — no real person is named.
NAMES = [
    "Asha", "Priya", "Sunita", "Kavita", "Meena", "Rekha", "Geeta", "Anjali",
    "Pooja", "Neha", "Suman", "Radha", "Lata", "Kiran", "Shanti", "Usha",
    "Manju", "Savita", "Nirmala", "Vandana", "Renu", "Shobha", "Kamala",
    "Indira", "Vimla", "Sarita", "Deepa", "Rani", "Seema", "Jyoti", "Poonam",
    "Babita", "Sarla", "Sushila", "Kusum", "Malti", "Anita", "Rina", "Laxmi",
    "Sudha",
]

VARIANTS = ("WHO", "HBNC")

# Deterministic mix (PLAN §4.8): ~70% no sign at any rung, ~10% a red sign
# at D3, ~10% a yellow sign at D7, ~10% silent (no reply) at D3.
CATEGORIES = ("no_sign", "red_d3", "yellow_d7", "silent_d3")
CATEGORY_WEIGHTS = (0.70, 0.10, 0.10, 0.10)

# category_for() assigns exact quotas (round(DEFAULT_N * weight) per
# minority category) over a seed-shuffled index list, rather than an
# independent per-mother coin flip — with only ~4 expected minority-category
# mothers out of 38, an independent roll can land a whole category at zero
# for an unlucky seed (it does for at least one category at seed 3). A
# quota guarantees every category actually appears, which is what "seed=3
# is the demo default" (PLAN §4.8) needs to be true every time, not just in
# expectation. Calibrated for the default cohort size; a mother's index is
# parsed from her mother_id ("mother-07" -> 7).
DEFAULT_N = 38

# Which sign each scripted category flips true, and at which rung.
RED_SCRIPT_SIGN = "NB_FEVER"
YELLOW_SCRIPT_SIGN = "NB_SKIN_PUSTULES"


def generate(seed: int, n: int = 38, epoch: str = "2026-08-24T00:00:00Z") -> list[Mother]:
    """`n` synthetic mothers, deterministic in `seed` alone. Names cycle
    through the fixed `NAMES` list and are suffixed `"(synthetic #NN)"`;
    phones are the non-dialable `+91-00000-000NN` pattern."""
    rng = random.Random(seed)
    mothers = []
    for i in range(n):
        name = NAMES[i % len(NAMES)]
        variant = rng.choice(VARIANTS)
        mothers.append(
            Mother(
                mother_id=f"mother-{i:02d}",
                display_name=f"{name} (synthetic #{i:02d})",
                phone=f"+91-00000-000{i:02d}",
                variant=variant,
                discharge_epoch=epoch,
            )
        )
    return mothers


def _category_assignment(seed: int, n: int = DEFAULT_N) -> dict[int, str]:
    indices = list(range(n))
    random.Random(f"cohort-category-shuffle:{seed}").shuffle(indices)
    quotas = {
        "red_d3": round(n * CATEGORY_WEIGHTS[CATEGORIES.index("red_d3")]),
        "yellow_d7": round(n * CATEGORY_WEIGHTS[CATEGORIES.index("yellow_d7")]),
        "silent_d3": round(n * CATEGORY_WEIGHTS[CATEGORIES.index("silent_d3")]),
    }
    assignment: dict[int, str] = {}
    cursor = 0
    for category in ("red_d3", "yellow_d7", "silent_d3"):
        count = quotas[category]
        for idx in indices[cursor : cursor + count]:
            assignment[idx] = category
        cursor += count
    for idx in indices[cursor:]:
        assignment[idx] = "no_sign"
    return assignment


def category_for(seed: int, mother_id: str, n: int = DEFAULT_N) -> str:
    """Deterministic per-mother category — see the DEFAULT_N note above for
    why this is a quota assignment rather than an independent coin flip per
    mother. `mother_id` must be in `generate()`'s own `"mother-NN"` shape;
    the index is parsed back out of it.

    R-05 (RED-TEAM.md): this used to call `_category_assignment(seed)` with
    NO `n`, silently defaulting to `DEFAULT_N=38` regardless of how many
    mothers `generate()` had actually been asked for — `POST /api/seed
    {"n": 2000}` enrolled fine, but the next `/api/advance` KeyError'd at
    index 38 (`_category_assignment(seed)` only ever built a 38-entry
    table). `n` must match the cohort size the caller actually used;
    `core/sweep.py::run_sweep` and `app/orchestrator.py::advance` now
    thread the real enrolled count through instead of relying on this
    default."""
    index = int(mother_id.rsplit("-", 1)[-1])
    return _category_assignment(seed, n)[index]


def scripted_reply(seed: int, mother: Mother, rung: str, pack: RulePack, n: int = DEFAULT_N) -> SymptomForm | None:
    """The mother's scripted keypad reply for this rung, or None for
    silence. A keypad reply is the complete, human-operated channel: every
    sign in the pack is explicitly set true/false (core/gate.py relies on
    this — only an explicit keypad False can ever clear a sign to
    NEXT_CONTACT). `n` is the cohort's own size (R-05) — see
    `category_for`'s docstring."""
    category = category_for(seed, mother.mother_id, n)
    if category == "silent_d3" and rung == "D3":
        return None

    signs: dict[str, bool] = {s.sign_id: False for s in pack.signs}
    if category == "red_d3" and rung == "D3" and RED_SCRIPT_SIGN in signs:
        signs[RED_SCRIPT_SIGN] = True
    elif category == "yellow_d7" and rung == "D7" and YELLOW_SCRIPT_SIGN in signs:
        signs[YELLOW_SCRIPT_SIGN] = True

    return SymptomForm(subject="newborn", signs=signs, origin="keypad", reader="none")
