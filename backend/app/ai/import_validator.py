"""
import_validator.py — Load-time import boundary enforcement.

Workers (node modules) MUST NOT import routing-authority modules:
  app.ai.graph.edges         — routing decisions
  app.ai.graph.supervisor    — graph construction
  app.ai.decision_engine     — arbitration authority

Enforcement ensures routing logic stays centralised in the Decision Engine.
Workers receive frozen input bundles and never route themselves.

Usage (call once at application startup, before first request):
  from app.ai.import_validator import validate_worker_imports
  validate_worker_imports()   # raises ImportBoundaryError on violation

For CI: pytest fixture wraps this same call.
"""
from __future__ import annotations

import ast
import importlib.util
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_WORKER_FORBIDDEN: list[str] = [
    "app.ai.graph.edges",
    "app.ai.graph.supervisor",
    "app.ai.decision_engine",
]

_WORKER_MODULES: list[str] = [
    "app.ai.nodes.classifier_node",
    "app.ai.nodes.triage_node",
    "app.ai.nodes.clarification_node",
    "app.ai.nodes.fact_gap_node",
    "app.ai.nodes.retrieval_node",
    "app.ai.nodes.retrieval_grader_node",
    "app.ai.nodes.generation_node",
    "app.ai.nodes.hallucination_node",
    "app.ai.nodes.finalizer_node",
]


class ImportBoundaryError(RuntimeError):
    pass


def _module_path(module_name: str) -> Path | None:
    spec = importlib.util.find_spec(module_name)
    if spec and spec.origin:
        return Path(spec.origin)
    return None


def _imports_in_source(source: str) -> list[str]:
    names: list[str] = []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return names
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.append(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
    return names


def validate_worker_imports() -> None:
    """
    Scan all registered worker modules for forbidden imports.
    Raises ImportBoundaryError listing every violation found.
    """
    violations: list[str] = []

    for mod_name in _WORKER_MODULES:
        path = _module_path(mod_name)
        if path is None:
            logger.debug("import_validator: cannot resolve %s — skipping", mod_name)
            continue
        try:
            source = path.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning("import_validator: cannot read %s: %s", path, exc)
            continue

        for imp in _imports_in_source(source):
            for forbidden in _WORKER_FORBIDDEN:
                if imp == forbidden or imp.startswith(forbidden + "."):
                    violations.append(
                        f"{mod_name}  imports  '{imp}'"
                    )

    if violations:
        msg = "Import boundary violations:\n" + "\n".join(f"  • {v}" for v in violations)
        logger.error("import_validator: %s", msg)
        raise ImportBoundaryError(msg)

    logger.info(
        "import_validator: all %d worker modules passed", len(_WORKER_MODULES)
    )
