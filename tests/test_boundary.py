"""The deterministic-core boundary, enforced as a test (PLAN §2). core/ must
stay pure — no model SDK, no network, no wall clock, no direct env/file I/O —
and the only place in the whole repo allowed to write to a store is
app/orchestrator.py. This test fails the build if either guarantee breaks.
"""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CORE = ROOT / "core"

# Forbidden import targets for core/ — model SDKs, network, and cloud clients.
# Matched both as an exact imported name and as a dotted prefix, so
# `import google.cloud.firestore` is caught by the `google.cloud` entry.
FORBIDDEN_IMPORTS = {
    "genai",
    "google.cloud",
    "google.adk",
    "requests",
    "httpx",
    "urllib",
    "socket",
}

# Forbidden literal substrings for core/ — direct wall-clock reads, direct env
# reads, and direct file opens. core/ takes time via an injected Clock, config
# via function parameters, and reads files (e.g. the rule pack) through the
# store/shell layer, never itself.
FORBIDDEN_SUBSTRINGS = ("datetime.now(", "time.time(", "os.environ", "open(")

EXCLUDE_DIR_PARTS = {".venv", ".git", ".crew", "__pycache__", "tests"}


def _core_py_files() -> list[Path]:
    return sorted(CORE.rglob("*.py"))


def _repo_py_files_outside_tests() -> list[Path]:
    out = []
    for path in ROOT.rglob("*.py"):
        if any(part in EXCLUDE_DIR_PARTS for part in path.parts):
            continue
        out.append(path)
    return sorted(out)


def _imported_names(tree: ast.AST) -> set[str]:
    """Every name a module could be imported/reached under: the dotted module
    path, and (for `from X import Y`) the bare alias `Y` too, so
    `from google import genai` is caught even though `genai` alone isn't a
    dotted prefix of anything."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod:
                names.add(mod)
            for alias in node.names:
                names.add(alias.name)
                if mod:
                    names.add(f"{mod}.{alias.name}")
    return names


def _forbidden_hit(name: str) -> str | None:
    for forbidden in FORBIDDEN_IMPORTS:
        if name == forbidden or name.startswith(forbidden + "."):
            return forbidden
    return None


def test_core_directory_is_actually_scanned():
    """Sanity check on the scanner itself: if core/ were empty or the glob
    were wrong, every check below would pass vacuously. Fail loudly instead."""
    found = {p.name for p in _core_py_files()}
    assert {"clock.py", "models.py", "events.py"} <= found, (
        f"expected core/ scan to include the known modules, found {found}"
    )


def test_core_imports_no_model_or_network_code():
    violations = []
    for path in _core_py_files():
        tree = ast.parse(path.read_text(), filename=str(path))
        for name in _imported_names(tree):
            hit = _forbidden_hit(name)
            if hit:
                violations.append(f"{path.relative_to(ROOT)}: imports '{name}' (forbidden: '{hit}')")
    assert not violations, "\n".join(violations)


def test_core_never_reads_the_wall_clock_or_env_or_opens_files_directly():
    violations = []
    for path in _core_py_files():
        text = path.read_text()
        for token in FORBIDDEN_SUBSTRINGS:
            if token in text:
                violations.append(f"{path.relative_to(ROOT)}: contains forbidden token '{token}'")
    assert not violations, "\n".join(violations)


def test_injecting_a_forbidden_import_is_actually_caught(tmp_path):
    """Proves the checker isn't vacuous: a core-shaped file that imports
    httpx must be flagged. This is the automated version of the T-13 task
    card's manual check ("injecting `import httpx` into core/gate.py makes
    it fail")."""
    poisoned = tmp_path / "poisoned_core_module.py"
    poisoned.write_text("import httpx\n\ndef f():\n    return httpx.get('http://example.com')\n")
    tree = ast.parse(poisoned.read_text(), filename=str(poisoned))
    hits = {n for n in _imported_names(tree) if _forbidden_hit(n)}
    assert hits == {"httpx"}


def _store_append_call_sites(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    sites = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "append":
            try:
                receiver = ast.unparse(node.func.value)
            except Exception:
                receiver = "<unparseable>"
            if "store" in receiver.lower():
                sites.append(f"{path.relative_to(ROOT)}:{node.lineno} — {receiver}.append(")
    return sites


def test_only_orchestrator_appends_to_a_store():
    orchestrator = ROOT / "app" / "orchestrator.py"
    violations = []
    for path in _repo_py_files_outside_tests():
        if path == orchestrator:
            continue
        violations.extend(_store_append_call_sites(path))
    assert not violations, "store.append() found outside app/orchestrator.py:\n" + "\n".join(violations)


def test_agent_directory_never_imports_the_store_module():
    """The ADK agent gets a ReadOnlyStoreView, never the writable Store — if
    agent/ can't even `import store`, it structurally cannot call
    store.append(), reinforcing the scoped-tools guarantee (PLAN §1.3)."""
    agent_dir = ROOT / "agent"
    if not agent_dir.exists():
        return  # nothing to check yet — agent/ lands in T-17+
    violations = []
    for path in sorted(agent_dir.rglob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        names = _imported_names(tree)
        if "store" in names or any(n.startswith("store.") for n in names):
            violations.append(str(path.relative_to(ROOT)))
    assert not violations, f"agent/ files importing store: {violations}"
