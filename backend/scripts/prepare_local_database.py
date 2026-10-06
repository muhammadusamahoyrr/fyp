"""Prepare a FRESH LOCAL database so the normal backend can start on it.

    venv\\Scripts\\python scripts\\prepare_local_database.py --db attorney_ai_local
    venv\\Scripts\\python scripts\\prepare_local_database.py --db attorney_ai_local --mongo mongodb://127.0.0.1:27018/?replicaSet=rs0

The normal startup refuses to run until the appointment booking indexes exist
(main.py: `assert_appointment_booking_ready`); creating them is an operator
step that startup deliberately never does on its own. On an EMPTY local
database that operator step is exactly the specs in
app/db/appointment_index_spec.py, and nothing else -- which is all this does.

  * LOCAL ONLY: refuses mongodb+srv and any non-loopback host. It is not a
    tool for a hosted cluster (that is the reviewed activation sequence).
  * CREATE ONLY: never drops an index, never writes, seeds or deletes data.
  * EMPTY OR ALREADY-PREPARED ONLY: refuses a database that has appointment
    rows, because there the slot backfill (appointment_backfill_cli) must run
    first.

Every other index (including the Document Analyzer's) is created by the
normal startup itself (`create_all_indexes`).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

DEFAULT_MONGO = "mongodb://127.0.0.1:27018/?replicaSet=rs0"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", required=True, help="database name, e.g. attorney_ai_local")
    parser.add_argument("--mongo", default=DEFAULT_MONGO, help="a LOCAL MongoDB URL (default: the dev replica set)")
    args = parser.parse_args(argv)

    from app.services.analyzer.simulated_provider import local_database
    if not local_database(args.mongo):
        print("refused: only a database on this machine (mongodb://127.0.0.1...) can be prepared here",
              file=sys.stderr)
        return 2

    from pymongo import MongoClient

    from app.db.appointment_index_spec import ALL_INDEX_REQUIREMENTS
    with MongoClient(args.mongo, serverSelectionTimeoutMS=5000) as client:
        db = client[args.db]
        if db["appointments"].estimated_document_count():
            print(f"refused: {args.db} already has appointments; run the slot preflight/backfill instead",
                  file=sys.stderr)
            return 2
        created = 0
        for spec in ALL_INDEX_REQUIREMENTS:
            existing = {ix["name"] for ix in db[spec.collection].list_indexes()}
            if spec.name in existing:
                continue
            options = {"name": spec.name, "unique": spec.unique, "sparse": spec.sparse}
            if spec.partial_filter:
                options["partialFilterExpression"] = dict(spec.partial_filter)
            db[spec.collection].create_index(list(spec.keys), **options)
            created += 1
    print(f"{args.db}: {created} appointment index(es) created, "
          f"{len(ALL_INDEX_REQUIREMENTS) - created} already present. Nothing else was changed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
