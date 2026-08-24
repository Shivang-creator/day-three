"""R-09 named regression (RED-TEAM.md Attack 3c / BOARD.md): `python -m
tools.adversarial` — the README's own documented "prove it yourself"
command — used to unconditionally overwrite the COMMITTED
`docs/adversarial-results.json` on every run (only `run_at` actually
changed; the summary numbers reproduce exactly, mocked/cached), leaving
the tracked file dirty just from running the command a judge is told to
run. Fix: `tools/adversarial.py::main` only writes when `--write` is
passed; the default run prints the summary line and leaves the committed
file untouched.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RESULTS_PATH = REPO_ROOT / "docs" / "adversarial-results.json"


def test_regress_r09_running_the_readme_command_leaves_the_committed_file_byte_identical(monkeypatch):
    monkeypatch.setenv("MODEL_OFF", "1")
    before = RESULTS_PATH.read_bytes()

    result = subprocess.run(
        [sys.executable, "-m", "tools.adversarial"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr

    after = RESULTS_PATH.read_bytes()
    assert after == before, (
        "the README's own documented `python -m tools.adversarial` command must never modify the "
        "committed docs/adversarial-results.json without --write (R-09)"
    )
    assert "ADVERSARIAL n=" in result.stdout
    assert "left untouched" in result.stdout


def test_regress_r09_write_flag_is_required_to_update_the_committed_file(tmp_path, monkeypatch):
    from tools import adversarial

    fake_results = tmp_path / "adversarial-results.json"
    fake_results.write_text('{"sentinel": "untouched"}')
    monkeypatch.setattr(adversarial, "RESULTS_PATH", fake_results)

    adversarial.main([])
    assert fake_results.read_text() == '{"sentinel": "untouched"}'

    adversarial.main(["--write"])
    assert fake_results.read_text() != '{"sentinel": "untouched"}'
