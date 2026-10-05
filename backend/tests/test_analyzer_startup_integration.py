"""The Document Analyzer runs inside the NORMAL application: its routes are on
the main FastAPI app (under the same /api/v1 prefix the frontend proxies), the
main lifespan starts its worker exactly once per process, and that worker is
inert unless DOC_ANALYZER is on and readiness passed. No separate server."""
from __future__ import annotations

import ast
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]


def test_the_analyzer_routes_are_on_the_main_app():
    from app.main import app
    paths = {getattr(r, "path", "") for r in app.routes}
    for path in ("/api/v1/documents/analyses", "/api/v1/documents/analyses/runs/{run_id}/report",
                 "/api/v1/documents/analyses/runs/{run_id}/pii-confirmation/preview",
                 "/api/v1/documents/analyses/runs/{run_id}/processing-receipt"):
        assert path in paths, path


def test_the_main_lifespan_starts_the_analyzer_worker_exactly_once():
    tree = ast.parse((BACKEND / "app" / "main.py").read_text(encoding="utf-8"))
    started = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
               and getattr(n.func, "attr", getattr(n.func, "id", "")) == "create_task"
               and n.args and isinstance(n.args[0], ast.Call)
               and getattr(n.args[0].func, "id", "") in ("_analyzer_worker", "_analyzer_housekeeping")]
    assert sorted(c.args[0].func.id for c in started) == ["_analyzer_housekeeping", "_analyzer_worker"]
    # ... and not behind the Redis/RUN_SCHEDULERS gate: the runner's lease and
    # fence keep it single-processing per run whatever the worker count.
    lifespan = next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == "lifespan")
    gated = [n for n in ast.walk(lifespan) if isinstance(n, ast.If)
             and "run_schedulers" in ast.unparse(n.test)]
    assert all("_analyzer_worker" not in ast.unparse(g) for g in gated)


async def test_the_worker_is_inert_unless_the_analyzer_is_on_and_ready(monkeypatch):
    from app.core.config import settings
    from app.services.analyzer import readiness, runner
    calls = []

    async def spy(owner):
        calls.append(owner)
        return None

    monkeypatch.setattr(runner, "process_one", spy)
    monkeypatch.setattr(settings, "doc_analyzer", False)
    assert await runner.tick() == [] and calls == []
    monkeypatch.setattr(settings, "doc_analyzer", True)
    readiness._reset_for_tests()                                     # never checked = not ready
    try:
        assert await runner.tick() == [] and calls == []
        readiness._STATE.checked = True
        await runner.tick()
        assert calls                                                 # on and ready: it works
    finally:
        readiness._reset_for_tests()


async def test_readiness_names_a_simulated_provider_on_a_hosted_database(monkeypatch):
    from app.core.config import settings
    from app.services.analyzer import ai_config, readiness
    for name, value in {"analyzer_ai": True, "analyzer_ai_provider": "simulated",
                        "analyzer_ai_synthetic_only": True,
                        "mongodb_url": "mongodb+srv://cluster0.example.net/x"}.items():
        monkeypatch.setattr(settings, name, value)

    async def fine():
        return True

    async def no_index_problems():
        return []

    monkeypatch.setattr(readiness, "transactions_supported", fine)
    monkeypatch.setattr("app.db.indexes.validate_analyzer_indexes", no_index_problems)
    monkeypatch.setattr("app.services.analyzer.blob_store.keyring_problems", lambda: [])
    try:
        assert await readiness.refresh() == [ai_config.AI_SIMULATED_NEEDS_LOCAL_DATABASE]
        assert not readiness.is_ready()                              # the analyzer answers 503, nothing else
    finally:
        readiness._reset_for_tests()
