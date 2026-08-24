"""Guards docs/, rules/, and README.md — build deliverables — against being
modified by the test suite itself. A session-scoped fixture snapshots their
hashes before any test runs and re-checks at teardown, once every test in the
session has finished.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
WATCHED = ("docs", "rules", "README.md")


def _hash_tree() -> dict[str, str]:
    """{path relative to repo root: sha256 hex digest} for every file under
    the watched deliverables, at this instant."""
    digests: dict[str, str] = {}
    for name in WATCHED:
        target = ROOT / name
        if target.is_file():
            digests[name] = hashlib.sha256(target.read_bytes()).hexdigest()
        elif target.is_dir():
            for p in sorted(target.rglob("*")):
                if p.is_file():
                    rel = str(p.relative_to(ROOT))
                    digests[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
    return digests


@pytest.fixture(scope="session")
def deliverables_baseline():
    baseline = _hash_tree()
    yield baseline
    after = _hash_tree()
    changed = sorted(set(after) ^ set(baseline)) or [
        k for k in baseline if baseline[k] != after.get(k)
    ]
    assert after == baseline, f"docs/, rules/, or README.md changed during the test run: {changed}"


def test_baseline_snapshot_covers_the_rules_pack(deliverables_baseline):
    assert any(k.startswith("rules/") for k in deliverables_baseline), (
        "expected the rules/ pack to be part of the deliverables snapshot"
    )


def test_hashing_the_deliverables_twice_in_a_row_agrees(deliverables_baseline):
    # No writes happen between these two calls, so they must produce an
    # identical snapshot — this is what makes the teardown comparison a
    # meaningful "unchanged" check rather than a flaky one.
    assert _hash_tree() == _hash_tree()
