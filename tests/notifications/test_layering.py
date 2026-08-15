"""Enforces the layering rule ``t42/notifications/__init__.py`` states in its own docstring:
``t42.notifications`` may import ``t42.storage.accounts`` and ``boto3``, but nothing else from
``t42.storage`` (no ``repository``, ``codec``, ``replay``) and nothing from ``t42.engine`` - that
is what makes "the notifier cannot see a hand" checkable rather than merely claimed.

Pulled forward from ROADMAP.md 4.7 into 4.4, since it's cheap and protects exactly the modules
(``records.py``, ``pump.py``) that phase adds, rather than leaving the rule unguarded until 4.7.

Static analysis rather than a runtime import sweep, the same reasoning
``tests/cli/test_layering.py`` gives: it walks the source with ``ast`` instead of actually
importing every module, so it can't be fooled by an import hidden inside a function body that
never runs during a normal test session, and it costs nothing to run either way.
"""

from __future__ import annotations

import ast
from pathlib import Path

import t42.notifications

_FORBIDDEN_PREFIXES = ("t42.engine",)
_ALLOWED_STORAGE = "t42.storage.accounts"


def _imported_modules(source_path: Path) -> set[str]:
    """Every dotted module name a file might make available, including the
    ``from t42.storage import repository`` form - ``node.module`` alone would miss that one,
    since it names only ``t42.storage``, not the submodule the import actually pulls in."""
    tree = ast.parse(source_path.read_text(), filename=str(source_path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            modules.add(node.module)
            modules.update(f"{node.module}.{alias.name}" for alias in node.names)
    return modules


def _is_forbidden(module: str) -> bool:
    if module.startswith("t42.storage"):
        return module != _ALLOWED_STORAGE and not module.startswith(f"{_ALLOWED_STORAGE}.")
    return any(
        module == prefix or module.startswith(f"{prefix}.") for prefix in _FORBIDDEN_PREFIXES
    )


def test_no_module_under_notifications_imports_engine_or_non_accounts_storage() -> None:
    notifications_root = Path(t42.notifications.__file__).parent
    violations: dict[str, set[str]] = {}
    for source_path in sorted(notifications_root.rglob("*.py")):
        forbidden = {m for m in _imported_modules(source_path) if _is_forbidden(m)}
        if forbidden:
            violations[str(source_path.relative_to(notifications_root))] = forbidden

    assert not violations, f"t42.notifications modules importing forbidden layers: {violations}"
