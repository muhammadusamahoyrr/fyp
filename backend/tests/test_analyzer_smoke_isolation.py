"""The offline browser smoke tool (scripts/analyzer_browser_smoke.py) cannot be
switched on in production: no route, setting or environment flag selects a
fake provider; normal startup leaves the provider hooks unset; the tool
refuses a non-loopback database."""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]


def test_normal_startup_leaves_the_provider_hooks_unset():
    import app.main  # noqa: F401 -- the production app, as uvicorn imports it
    from app.services.analyzer import ai_stage, hypothesis_review_stage
    assert ai_stage.TRANSPORT is None and hypothesis_review_stage.TRANSPORT is None


def test_no_setting_selects_a_fake_provider():
    from app.core.config import Settings
    names = set(Settings.model_fields)
    assert not [n for n in names if re.search(r"fake|mock|smoke|transport", n, re.I)]


def test_no_app_code_sets_the_hook_or_knows_the_smoke_tool():
    for path in (BACKEND / "app").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "analyzer_browser_smoke" not in text, path
        for m in re.finditer(r"^\s*(?:[\w.]+\.)?TRANSPORT\s*=\s*(.+)$", text, re.M):
            assert m.group(1).split("#")[0].strip().startswith("None"), (path, m.group(0))


def test_the_smoke_tool_refuses_a_non_loopback_database(tmp_path):
    r = subprocess.run([sys.executable, str(BACKEND / "scripts" / "analyzer_browser_smoke.py"),
                        "--mongo", "mongodb+srv://cluster0.example.net/x", "--out", str(tmp_path)],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 2 and "loopback" in r.stderr
    assert not list(tmp_path.iterdir())                     # refused before creating anything
