"""Test deploy.sh script."""

import subprocess
import re


def test_deploy_script_syntax():
    """Test that deploy.sh has valid bash syntax."""
    result = subprocess.run(
        ["bash", "-n", "deploy.sh"],
        cwd=".",
        capture_output=True,
        text=True
    )
    assert result.returncode == 0, f"Syntax check failed: {result.stderr}"


def test_deploy_script_dry_run():
    """Test that deploy.sh --dry-run prints all expected gcloud commands."""
    result = subprocess.run(
        ["bash", "deploy.sh", "--dry-run"],
        cwd=".",
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


def test_deploy_script_api_key_masked():
    """Test that API key is never printed in stdout."""
    result = subprocess.run(
        ["bash", "deploy.sh", "--dry-run"],
        cwd=".",
        capture_output=True,
        text=True
    )

    output = result.stdout + result.stderr

    # Read the actual API key from .env.local
    with open(".env.local", "r") as f:
        env_content = f.read()
        match = re.search(r"GEMINI_API_KEY=([^\n]+)", env_content)
        if match:
            api_key = match.group(1).strip('"')
            # The API key should NOT appear in stdout
            assert api_key not in result.stdout, \
                "API key found in stdout (not masked)"
            # But it should be masked as ***MASKED***
            assert "GEMINI_API_KEY=***MASKED***" in output, \
                "API key not properly masked in output"
