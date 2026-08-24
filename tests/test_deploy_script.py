"""Test deploy.sh script.

R-01 (RED-TEAM.md / .crew/BOARD.md): a fresh clone has no `.env.local`, but
`deploy.sh` hard-requires one to exist before it ever reaches its own
`--dry-run` early exit (`if [ ! -f .env.local ]; then ... exit 1; fi` runs
unconditionally), and `test_deploy_script_api_key_masked` used to `open`
the repo's real `.env.local` directly — both fail with no
"secrets committed to the developer's machine" file present. Regression
test: `test_regress_r01_deploy_tests_pass_with_no_env_local` below, plus
these two tests now run against a throwaway `.env.local` built fresh in a
tmp dir (via the `deploy_env` fixture) instead of depending on whatever the
real repo tree happens to have — so `make test` is reproducible on a
cold clone with zero setup, per the README's own claimed numbers.
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
FAKE_API_KEY = "AIzaSyFAKE0000000000000000000000000TEST"


@pytest.fixture
def deploy_env(tmp_path):
    """A throwaway directory holding only deploy.sh + a synthetic
    `.env.local` — independent of whatever (if anything) the developer's
    real `.env.local` contains, and present even on a fresh clone."""
    shutil.copy(REPO_ROOT / "deploy.sh", tmp_path / "deploy.sh")
    (tmp_path / ".env.local").write_text(
        f'GEMINI_API_KEY={FAKE_API_KEY}\nGEMINI_MODEL=gemini-3.5-flash\nGCP_PROJECT=test-project\n'
    )
    return tmp_path


def test_deploy_script_syntax():
    """Test that deploy.sh has valid bash syntax. No .env.local needed —
    `bash -n` only parses, never executes."""
    result = subprocess.run(
        ["bash", "-n", str(REPO_ROOT / "deploy.sh")],
        capture_output=True,
        text=True
    )
    assert result.returncode == 0, f"Syntax check failed: {result.stderr}"


def test_deploy_script_dry_run(deploy_env):
    """Test that deploy.sh --dry-run prints all expected gcloud commands."""
    result = subprocess.run(
        ["bash", "deploy.sh", "--dry-run"],
        cwd=str(deploy_env),
        capture_output=True,
        text=True
    )
    # Should not error (exit 0) even though auth is not active
    assert result.returncode == 0, f"Dry-run failed: {result.stderr}"

    output = result.stdout + result.stderr

    # Check for expected gcloud commands
    expected_commands = [
        "gcloud config set project",
        "gcloud services enable run.googleapis.com",
        "gcloud services enable cloudbuild.googleapis.com",
        "gcloud services enable artifactregistry.googleapis.com",
        "gcloud services enable firestore.googleapis.com",
        "gcloud services enable aiplatform.googleapis.com",
        "gcloud run deploy day-three",
    ]

    for cmd in expected_commands:
        assert cmd in output, f"Expected command not found: {cmd}"


def test_deploy_script_api_key_masked(deploy_env):
    """Test that API key is never printed in stdout."""
    result = subprocess.run(
        ["bash", "deploy.sh", "--dry-run"],
        cwd=str(deploy_env),
        capture_output=True,
        text=True
    )

    output = result.stdout + result.stderr

    # Read the actual API key from the fixture's own throwaway .env.local
    # (never the developer's real one — R-01).
    env_content = (deploy_env / ".env.local").read_text()
    match = re.search(r"GEMINI_API_KEY=([^\n]+)", env_content)
    assert match, "fixture .env.local should always define GEMINI_API_KEY"
    api_key = match.group(1).strip('"')
    assert api_key == FAKE_API_KEY
    # The API key should NOT appear in stdout
    assert api_key not in result.stdout, \
        "API key found in stdout (not masked)"
    # But it should be masked as ***MASKED***
    assert "GEMINI_API_KEY=***MASKED***" in output, \
        "API key not properly masked in output"


def test_regress_r01_deploy_tests_pass_with_no_env_local(tmp_path):
    """R-01 named regression: a cold clone (deploy.sh + no .env.local
    anywhere nearby) must fail LOUDLY with deploy.sh's own clear error, not
    with a bare Python FileNotFoundError from the test harness itself —
    and it must not need a real .env.local to exist for the test suite to
    collect/run cleanly (see the deploy_env fixture above, used by the two
    tests that actually need one)."""
    shutil.copy(REPO_ROOT / "deploy.sh", tmp_path / "deploy.sh")
    assert not (tmp_path / ".env.local").exists()

    result = subprocess.run(
        ["bash", "deploy.sh", "--dry-run"],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert ".env.local not found" in (result.stdout + result.stderr)
