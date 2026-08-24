"""tools/diagram.py (T-25). The event requires an architecture PNG upload, so
the script that makes it is tested like any other deliverable: it runs cold,
writes a real PNG of the required size, names every top-level source dir from
PLAN §3, respects the DESIGN.md text floor, and re-renders identically.

Every render here goes to tmp_path — never docs/ — so the session-wide
deliverables guard (tests/test_deliverables_untouched.py) stays green.
"""
from __future__ import annotations

import os
import struct
import subprocess
import sys
from pathlib import Path

import pytest

from tools import diagram

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "tools" / "diagram.py"


def _png_size(path: Path) -> tuple[int, int]:
    head = path.read_bytes()[:24]
    assert head[:8] == b"\x89PNG\r\n\x1a\n", "not a PNG"
    return struct.unpack(">II", head[16:24])


@pytest.fixture(scope="module")
def rendered(tmp_path_factory) -> Path:
    """Run the script exactly as `make diagram` does, into a temp dir."""
    out = tmp_path_factory.mktemp("diagram") / "architecture.png"
    env = {**os.environ, "GEMINI_MODEL": "gemini-3.5-flash", "STORE": "memory",
           "MODEL_OFF": "0", "MPLBACKEND": "Agg"}
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--out", str(out)],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    assert "wrote" in proc.stdout
    return out


def test_script_runs_and_writes_a_png(rendered):
    assert rendered.exists()


def test_png_is_2400_by_1500_and_over_50_kb(rendered):
    assert _png_size(rendered) == (2400, 1500)
    assert rendered.stat().st_size > 50 * 1024


def test_node_labels_match_top_level_source_dirs():
    """PLAN §3 layout: every code dir is a box, and every box is a real dir."""
    assert set(diagram.DIR_NODES) == {"rules", "core", "store", "agent", "app", "tools"}
    for name in diagram.DIR_NODES:
        assert (ROOT / name).is_dir(), f"{name}/ drawn but missing from the repo"


def test_every_text_size_meets_the_design_floor():
    """DESIGN.md: text >= 18 px at full size. The script's own floor is 19."""
    assert diagram.MIN_PX >= 18
    assert min(diagram.SIZES.values()) >= diagram.MIN_PX


def test_footer_reads_pack_and_env_at_render_time(monkeypatch):
    pack = diagram.read_pack()
    assert pack["version"] not in ("?", "")
    assert pack["signs"] >= 12 and pack["rules"] >= 8
    monkeypatch.setenv("GEMINI_MODEL", "model-from-env")
    monkeypatch.setenv("STORE", "firestore")
    env = diagram.read_env()
    assert env["model"] == "model-from-env"
    assert env["store"] == "firestore"


def test_rerender_is_byte_identical(tmp_path):
    """Re-runnable by design: the same inputs give the same bytes, so a later
    route change shows up as a real diff and nothing else does."""
    env = {"model": "gemini-3.5-flash", "store": "memory", "model_off": "0"}
    a = diagram.render(tmp_path / "a.png", env=env)
    b = diagram.render(tmp_path / "b.png", env=env)
    assert a.read_bytes() == b.read_bytes()
