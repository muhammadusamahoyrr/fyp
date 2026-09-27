"""Tests for check_txn_guard.py — run: python -m pytest .github/ci -q

Each case runs the real script as a subprocess, against a stand-in conftest
(TXN_GUARD_CONFTEST) and report files written by the test, and asserts the exit
code CI would see.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent / "check_txn_guard.py"
WITH_FIXTURE = "import pytest\n\n@pytest.fixture\nasync def mongo_transactional(mongo):\n    return mongo\n"
WITHOUT_FIXTURE = "import pytest\n"


def report(tmp_path, name, *, collected=0, executed=0, replica_skips=(), other_skips=()):
    p = tmp_path / name
    p.write_text(json.dumps({"collected": collected, "executed": executed,
                             "replica_skips": list(replica_skips),
                             "other_skips": list(other_skips)}), encoding="utf-8")
    return str(p)


def run(tmp_path, conftest_text, *reports):
    conftest = tmp_path / "conftest.py"
    conftest.write_text(conftest_text, encoding="utf-8")
    env = {**os.environ, "TXN_GUARD_CONFTEST": str(conftest)}
    r = subprocess.run([sys.executable, str(SCRIPT), *reports],
                       capture_output=True, text=True, env=env)
    return r.returncode, r.stdout


# ── the five required cases ──────────────────────────────────────────────────

def test_no_fixture_and_no_report_passes(tmp_path):
    missing = str(tmp_path / "txn-integration.json")      # never written
    code, out = run(tmp_path, WITHOUT_FIXTURE, report(tmp_path, "txn-unit.json"), missing)
    assert code == 0, out
    assert "nothing to require" in out
    assert "collected=0 executed=0" in out                  # informational output kept


def test_fixture_and_missing_report_fails(tmp_path):
    missing = str(tmp_path / "txn-integration.json")
    code, out = run(tmp_path, WITH_FIXTURE,
                    report(tmp_path, "txn-unit.json", collected=5, executed=5), missing)
    assert code == 1, out
    assert "missing guard report" in out


def test_fixture_and_zero_executed_fails(tmp_path):
    code, out = run(tmp_path, WITH_FIXTURE,
                    report(tmp_path, "txn-unit.json"), report(tmp_path, "txn-integration.json"))
    assert code == 1, out
    assert "ZERO transaction tests executed" in out


def test_fixture_and_replica_set_skip_fails(tmp_path):
    code, out = run(tmp_path, WITH_FIXTURE,
                    report(tmp_path, "txn-unit.json", collected=3, executed=2),
                    report(tmp_path, "txn-integration.json", collected=1,
                           replica_skips=["tests/test_x.py::test_atomic"]))
    assert code == 1, out
    assert "skipped for lack of a replica set" in out


def test_fixture_and_successful_execution_passes(tmp_path):
    code, out = run(tmp_path, WITH_FIXTURE,
                    report(tmp_path, "txn-unit.json", collected=10, executed=10),
                    report(tmp_path, "txn-integration.json", collected=259, executed=258,
                           other_skips=["tests/test_live.py::test_smtp"]))
    assert code == 0, out
    assert "transaction test guard: OK" in out


# ── protection is not weakened without the fixture ───────────────────────────

def test_no_fixture_but_a_replica_set_skip_still_fails(tmp_path):
    code, out = run(tmp_path, WITHOUT_FIXTURE,
                    report(tmp_path, "txn-unit.json", replica_skips=["tests/t.py::t"]),
                    report(tmp_path, "txn-integration.json"))
    assert code == 1, out


def test_no_fixture_with_both_reports_passes(tmp_path):
    code, out = run(tmp_path, WITHOUT_FIXTURE,
                    report(tmp_path, "txn-unit.json"), report(tmp_path, "txn-integration.json"))
    assert code == 0, out
