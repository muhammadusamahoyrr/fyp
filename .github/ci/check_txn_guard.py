"""Fail CI unless the agreement transaction tests genuinely ran.

Usage: python check_txn_guard.py <report.json> [<report.json> ...]
Reads the reports written by the txn_guard pytest plugin (one per test step).

Fails when:
  * any transaction test skipped because MongoDB is not a replica set; or
  * the `mongo_transactional` fixture exists in backend/tests/conftest.py but
    zero tests using it executed.

Before the agreements code lands the fixture does not exist, so there is
nothing to require; from the moment it does, this becomes strict on its own.
"""
import json
import sys
from pathlib import Path

CONFTEST = Path(__file__).resolve().parents[2] / "backend" / "tests" / "conftest.py"

fixture_defined = "def mongo_transactional(" in CONFTEST.read_text(encoding="utf-8")
executed, collected, replica_skips, other_skips, missing = 0, 0, [], [], []
for path in sys.argv[1:]:
    p = Path(path)
    if not p.exists():
        missing.append(path)
        continue
    r = json.loads(p.read_text(encoding="utf-8"))
    executed += r["executed"]
    collected += r["collected"]
    replica_skips += r["replica_skips"]
    other_skips += r["other_skips"]

print(f"transaction fixture defined: {fixture_defined}")
print(f"transaction tests collected={collected} executed={executed} "
      f"replica-set skips={len(replica_skips)} other skips={len(other_skips)}")
for n in other_skips:
    print(f"  skipped (other reason): {n}")

failures = []
if missing:
    failures.append(f"missing guard report(s): {missing} — a test step did not run")
if replica_skips:
    failures.append(f"{len(replica_skips)} transaction test(s) skipped for lack of a "
                    f"replica set: {replica_skips[:10]}")
if fixture_defined and executed == 0:
    failures.append("the transaction fixture exists but ZERO transaction tests executed")

if failures:
    for f in failures:
        print(f"::error title=Transaction test guard::{f}")
    sys.exit(1)
print("transaction test guard: OK" if fixture_defined
      else "transaction test guard: no transaction fixture in this revision — nothing to require")
