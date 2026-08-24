"""J-01/J-02 named regression (.crew/deliverables/JUDGE-REPORT.md, pc-test-user
T-28): on a genuinely fresh clone (`cp .env.example .env.local`, GEMINI_API_KEY
left blank), the judge found `make test` failing ONE test —
`tests/test_quietmode.py::test_message_prose_differs_between_model_on_and_model_off`
— but ONLY inside the full suite, not run alone (J-01); the same fresh clone's
`make quiet-diff` printed `0 decision changes · 0 prose fields differ`,
contradicting the README's promised `4 prose fields differ` two lines above
the command (J-02).

Root cause, confirmed identical to R-01: `app/main.py` calls
`load_dotenv(".env.local")` at import time, which — the FIRST time any test
module imports `app.main` — sets `os.environ["GEMINI_API_KEY"] = ""` (present,
falsy) for the rest of the pytest session. Run alone,
`tests/test_quietmode.py` never imports `app.main`, so `GEMINI_API_KEY` stays
entirely ABSENT and the old `os.environ.setdefault(...)` in
`tools/quiet_diff.py` still worked (setdefault only no-ops when the key
already exists). Run after `app.main` has been imported by an earlier test,
the key is present-but-empty and `.setdefault` becomes a no-op — the exact
R-01 bug, just reached via a different door. The fix
(`tools/quiet_diff.py::_run_sweep` checking truthiness) closes both doors at
once; this test proves the SPECIFIC ordering the judge hit.
"""
from __future__ import annotations


def test_regress_j01_j02_quiet_diff_survives_app_main_having_loaded_dotenv_first(monkeypatch):
    # Simulate "app.main was already imported earlier in the suite, and its
    # load_dotenv(".env.local") call already ran against a fresh-clone
    # .env.local with GEMINI_API_KEY left blank" — the exact precondition
    # the judge's full-suite run had, without needing a real subprocess.
    import app.main  # noqa: F401 — the import itself is the point: triggers load_dotenv

    monkeypatch.setenv("GEMINI_API_KEY", "")  # what a fresh-clone .env.local leaves behind
    monkeypatch.delenv("GEMINI_API_KEYS", raising=False)
    monkeypatch.delenv("MODEL_OFF", raising=False)

    from tools import quiet_diff

    result = quiet_diff.run_diff(seed=3, to="D3")

    assert result["decision_changes"] == []
    assert len(result["message_changes"]) > 0, (
        "J-01/J-02: quiet_diff must produce prose changes even when GEMINI_API_KEY was left "
        "present-but-empty by an earlier test importing app.main"
    )
    assert result["summary_line"] == "QUIET DIFF: 0 decision changes · 4 prose fields differ"
