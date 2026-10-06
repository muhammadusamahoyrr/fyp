"""`scripts/serve.py start --env-overlay FILE`: settings for one backend run
without editing .env -- including EMPTY values, which PowerShell cannot pass."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("serve_script", BACKEND / "scripts" / "serve.py")
serve = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(serve)


def test_overlay_lines_become_process_settings_including_empty_ones(tmp_path):
    f = tmp_path / "overlay"
    f.write_text("# a comment\n\nREDIS_URL=\nDB_NAME = attorney_ai_local\nANALYZER_AI_PROVIDER=\"simulated\"\n"
                 "MONGODB_URL=mongodb://127.0.0.1:27018/?replicaSet=rs0\n", encoding="utf-8")
    assert serve.read_env_overlay(f) == {"REDIS_URL": "", "DB_NAME": "attorney_ai_local",
                                         "ANALYZER_AI_PROVIDER": "simulated",
                                         "MONGODB_URL": "mongodb://127.0.0.1:27018/?replicaSet=rs0"}


@pytest.mark.parametrize("line", ["NOT A SETTING", "lower_case=1", "=value"])
def test_a_malformed_line_is_an_error_not_skipped(tmp_path, line):
    f = tmp_path / "overlay"
    f.write_text(f"DB_NAME=x\n{line}\n", encoding="utf-8")
    with pytest.raises(ValueError):
        serve.read_env_overlay(f)


def test_the_shipped_example_is_safe_by_construction():
    example = serve.read_env_overlay(BACKEND / ".env.analyzer-demo.example")
    assert example["ANALYZER_AI_PROVIDER"] == "simulated" and example["ANALYZER_AI_SYNTHETIC_ONLY"] == "true"
    assert example["MONGODB_URL"].startswith("mongodb://127.0.0.1") and example["ANALYZER_KEKS"] == ""
    assert example["ANALYZER_ENGINE_HYPOTHESES"] == "false" and example["REDIS_URL"] == ""
