"""Rule 1: the core modules never import the callers (api, checkins, demo, importer, planner, store)."""

import ast
from pathlib import Path

import pytest

PACKAGE = Path(__file__).parent.parent / "src" / "mycal"
CALLERS = {"api", "checkins", "demo", "importer", "planner", "store"}
CORE = sorted(p for p in PACKAGE.glob("*.py") if p.stem not in CALLERS and p.stem != "__init__")


def imported_modules(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
            names.update(f"{node.module}.{alias.name}" for alias in node.names)
    return names


@pytest.mark.parametrize("path", CORE + [PACKAGE / "__init__.py"], ids=lambda p: p.stem)
def test_core_module_does_not_import_callers(path: Path) -> None:
    banned = {f"mycal.{caller}" for caller in CALLERS}
    assert not imported_modules(path) & banned
