"""pytest plugin (CI only): record what the agreement TRANSACTION tests did.

Loaded with `-p txn_guard` by the tests workflow. It watches every test that
uses the `mongo_transactional` fixture (directly or through another fixture)
and writes, to the path in $TXN_GUARD_REPORT:

  * executed       - how many actually ran (passed or failed);
  * replica_skips  - which ones skipped because MongoDB is not a replica set.

`check_txn_guard.py` then fails the job on any replica-set skip, or on zero
executed tests while the fixture exists. A green job must mean these tests RAN:
a self-skip is the silent failure this guard exists to catch.
"""
import json
import os

FIXTURE = "mongo_transactional"
REPLICA_REASON = "multi-document transactions need a replica set"

_uses: set[str] = set()
_state = {"collected": 0, "executed": 0, "replica_skips": [], "other_skips": []}


def pytest_collection_modifyitems(session, config, items):
    for item in items:
        if FIXTURE in getattr(item, "fixturenames", ()):
            _uses.add(item.nodeid)
    _state["collected"] = len(_uses)


def pytest_runtest_logreport(report):
    if report.nodeid not in _uses:
        return
    if report.skipped:
        reason = str(report.longrepr)
        bucket = "replica_skips" if REPLICA_REASON in reason else "other_skips"
        if report.nodeid not in _state[bucket]:
            _state[bucket].append(report.nodeid)
    elif report.when == "call":
        _state["executed"] += 1


def pytest_sessionfinish(session, exitstatus):
    path = os.environ.get("TXN_GUARD_REPORT")
    if path:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(_state, fh, indent=2)
