"""The cohort sweep (PLAN §4.7): the "background workflow" as a pure
function over an event-log snapshot, an injected clock, and a rule pack.
`sweep.py` never renders message text — every Decision carries
`actions_without_text`, the exact object Quiet Mode diffs (model on vs off
must produce byte-identical Decisions; only the text rendered afterwards by
the shell may differ).
"""
from __future__ import annotations

import dataclasses

from core.clock import Clock
from core.cohort import scripted_reply
from core.events import Event, reduce
from core.gate import evaluate
from core.models import Action, Decision, ToJsonMixin, Verdict
from core.routing import plan, silence_plan
from core.rulepack import RulePack
from core.schedule import due_now

# Sentinel Verdict.route for a case whose contact was due and who did not
# reply — not one of core/gate.py's five gate routes (silence bypasses the
# gate entirely; there is no SymptomForm to evaluate).
SILENCE_ROUTE = "SILENCE"


@dataclasses.dataclass(frozen=True)
class SweepResult(ToJsonMixin):
    decisions: tuple  # tuple[Decision, ...]
    actions: tuple  # tuple[Action, ...] — every decision's actions, flattened, in decision order


def run_sweep(snapshot: dict[str, list[Event]], clock: Clock, pack: RulePack) -> SweepResult:
    """For every case_id in `snapshot` whose *current* rung has an open
    contact window at `clock.now()` (core/schedule.py::due_now — this reads
    each case's own state, so it naturally respects each mother's WHO/HBNC
    variant), pull that mother's scripted keypad reply (core/cohort.py,
    keyed by the seed parsed from the case_id's `"{seed}:{mother_id}"`
    namespace — T-14's convention) and evaluate it, or run the silence
    policy if she did not reply. A case whose current rung is not due right
    now is skipped entirely, which is what makes calling this repeatedly
    with an unchanged snapshot and clock a safe no-op (used by
    `/api/replay`, T-19).

    Slot bookings are threaded through `core.routing.plan`'s `booked`
    parameter across the whole sweep, so two urgent cases evaluated in the
    same pass never collide on the same clinic slot.
    """
    decisions: list[Decision] = []
    all_actions: list[Action] = []
    booked: set[str] = set()
    now_iso = clock.now().isoformat()

    for case_id in sorted(snapshot):
        state = reduce(snapshot[case_id])
        contact = due_now(state, clock, pack)
        if contact is None:
            continue

        seed_str, _, _rest = case_id.partition(":")
        seed = int(seed_str)
        form = scripted_reply(seed, state.mother, contact.rung, pack)

        if form is None:
            verdict = Verdict(route=SILENCE_ROUTE, fired=(), unknown=(), tag="Simulated")
            actions = tuple(silence_plan(state, clock, pack))
        else:
            verdict = evaluate(form, pack)
            actions = tuple(plan(verdict, state, clock, pack, booked=booked))
            for a in actions:
                if a.type == "BOOK_SLOT":
                    booked.add(a.payload["slot_iso"])

        decisions.append(
            Decision(
                case_id=case_id,
                clock=now_iso,
                rung=contact.rung,
                verdict=verdict,
                actions_without_text=actions,
            )
        )
        all_actions.extend(actions)

    return SweepResult(decisions=tuple(decisions), actions=tuple(all_actions))
