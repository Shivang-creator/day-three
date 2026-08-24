"""J-04 named regression (.crew/deliverables/JUDGE-REPORT.md, pc-test-user
T-28): a REVIEW-tagged worklist row printed the ENTIRE unresolved-signs
reason verbatim — `core/routing.py`'s HUMAN_REVIEW action payload is
`"unresolved red sign(s): " + ", ".join(sorted(verdict.unknown))`, ~28
SCREAMING_SNAKE_CASE tokens for an all-unknown form — which dominated the
row on desktop and consumed the entire visible worklist on the 390px mobile
viewport. Fix: `app/static/app.js::unresolvedSignsSummary` (a pure
function, no DOM) collapses this to a count behind a `<details>` disclosure
before `ruleLineHtml` renders it.

Requires `node` on PATH (present in this environment; skipped otherwise —
this repo has no JS test runner, so the pure function is extracted from the
real file and executed directly, not re-implemented, to stay grounded in
what actually ships).
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

APP_JS = Path(__file__).resolve().parent.parent / "app" / "static" / "app.js"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not on PATH")


def _extract_function(source: str, name: str) -> str:
    """Brace-balanced extraction of `function <name>(...) { ... }` from a
    plain-text JS source — good enough for this file's own coding style
    (no template-literal braces inside the function body being extracted)."""
    marker = f"function {name}("
    start = source.index(marker)
    brace_start = source.index("{", start)
    depth = 0
    for i in range(brace_start, len(source)):
        if source[i] == "{":
            depth += 1
        elif source[i] == "}":
            depth -= 1
            if depth == 0:
                return source[start : i + 1]
    raise AssertionError(f"unbalanced braces extracting function {name!r} from {APP_JS}")


REAL_ALL_UNKNOWN_REASON = (
    "unresolved red sign(s): M_BLEEDING_INCREASED, M_BREAST_TENDER, M_BREATHING_DIFFICULT, "
    "M_CALF_PAIN, M_CHEST_PAIN, M_CONVULSIONS, M_FEVER, M_FOUL_DISCHARGE, M_HEADACHE_SEVERE, "
    "M_SELF_HARM, M_VISION_BLURRED, NB_BLUE, NB_BREATHING_FAST, NB_CONVULSIONS, NB_FEEDING_POOR, "
    "NB_FEVER, NB_HYPOTHERMIA, NB_JAUNDICE_SEVERE, NB_LETHARGIC, NB_NOT_FEEDING, NB_PUS, "
    "NB_UMBILICUS_INFECTED"
)


def _run(reasons: list[str]) -> list:
    source = APP_JS.read_text()
    fn_src = _extract_function(source, "unresolvedSignsSummary")
    assert "unresolvedSignsSummary" in fn_src

    harness = fn_src + "\nconsole.log(JSON.stringify(" + json.dumps(reasons) + ".map(unresolvedSignsSummary)));"
    result = subprocess.run(["node", "-e", harness], capture_output=True, text=True)
    assert result.returncode == 0, f"node failed: {result.stderr}"
    return json.loads(result.stdout)


def test_regress_j04_wall_of_sign_codes_collapses_to_a_count():
    [summary] = _run([REAL_ALL_UNKNOWN_REASON])
    assert summary is not None
    assert summary["count"] == 22
    assert summary["label"] == "22 unresolved signs"
    # The raw tokens must still be reachable (disclosure), just not printed
    # bare in the label the row always shows.
    assert "NB_UMBILICUS_INFECTED" not in summary["label"]  # label itself never contains a sign id
    assert "NB_UMBILICUS_INFECTED" in summary["signs"]
    assert len(summary["signs"]) == 22


def test_regress_j04_non_unresolved_reasons_pass_through_unchanged():
    [summary] = _run(["no reader available — nurse reads it"])
    assert summary is None  # unrelated HUMAN_REVIEW reasons are not touched by this collapse


def test_regress_j04_single_sign_uses_singular_label():
    [summary] = _run(["unresolved red sign(s): M_FEVER"])
    assert summary["count"] == 1
    assert summary["label"] == "1 unresolved sign"
