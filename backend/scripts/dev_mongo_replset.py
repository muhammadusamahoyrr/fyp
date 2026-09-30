"""Start a throwaway single-node MongoDB replica set for development and tests.

Transactions -- which the Document Analyzer and agreement transitions need --
do not exist on a standalone mongod. Production (Atlas) is a replica set; this
gives a laptop the same capability without touching the ordinary local Mongo
on 27017.

    python scripts/dev_mongo_replset.py            # start (or reuse) on 27018
    python scripts/dev_mongo_replset.py --stop     # shut it down

Then, for the tests that need transactions:

    AAI_TEST_MONGO_URL="mongodb://127.0.0.1:27018/?replicaSet=rs0" pytest ...

Finds `mongod` on PATH, else the newest standard Windows install
(C:/Program Files/MongoDB/Server/<ver>/bin), else pass --mongod. No mongosh is
required: the replica set is initiated through pymongo. Data lives in
backend/.mongo-rs/ (git-ignored); delete the folder to start from nothing.
Binds to 127.0.0.1 only.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path

from pymongo import MongoClient
from pymongo.errors import OperationFailure, ServerSelectionTimeoutError

BACKEND = Path(__file__).resolve().parents[1]
DEFAULT_DBPATH = BACKEND / ".mongo-rs"
SET_NAME = "rs0"


def _client(port: int, timeout_ms: int = 1500) -> MongoClient:
    return MongoClient(f"mongodb://127.0.0.1:{port}/?directConnection=true",
                       serverSelectionTimeoutMS=timeout_ms)


def _running(port: int) -> bool:
    try:
        _client(port).admin.command("ping")
        return True
    except ServerSelectionTimeoutError:
        return False


def _find_mongod(explicit: Path | None) -> str:
    if explicit:
        return str(explicit)
    found = shutil.which("mongod")
    if found:
        return found
    installs = sorted(Path("C:/Program Files/MongoDB/Server").glob("*/bin/mongod.exe"),
                      key=lambda p: [int(x) if x.isdigit() else x
                                     for x in p.parts[-3].split(".")])
    if installs:
        return str(installs[-1])
    sys.exit("mongod not found: put it on PATH or pass --mongod")


def _start(port: int, dbpath: Path, mongod: str) -> None:
    dbpath.mkdir(parents=True, exist_ok=True)
    flags = 0
    if sys.platform == "win32":
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    subprocess.Popen(
        [mongod, "--replSet", SET_NAME, "--port", str(port), "--bind_ip", "127.0.0.1",
         "--dbpath", str(dbpath), "--logpath", str(dbpath / "mongod.log"), "--logappend"],
        creationflags=flags, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        close_fds=True)
    for _ in range(60):
        if _running(port):
            return
        time.sleep(0.5)
    sys.exit(f"mongod did not come up on {port}; see {dbpath / 'mongod.log'}")


def _initiate(port: int) -> None:
    admin = _client(port).admin
    try:
        admin.command("replSetGetStatus")
    except OperationFailure as exc:
        if exc.code != 94:          # NotYetInitialized
            raise
        admin.command("replSetInitiate", {
            "_id": SET_NAME, "members": [{"_id": 0, "host": f"127.0.0.1:{port}"}]})
    for _ in range(60):
        if admin.command("hello").get("isWritablePrimary"):
            return
        time.sleep(0.5)
    sys.exit("replica set did not elect a primary")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=27018)
    parser.add_argument("--dbpath", type=Path, default=DEFAULT_DBPATH)
    parser.add_argument("--stop", action="store_true")
    parser.add_argument("--mongod", type=Path, default=None, help="path to mongod")
    args = parser.parse_args()

    if args.stop:
        if _running(args.port):
            try:
                _client(args.port).admin.command("shutdown")
            except Exception:  # noqa: BLE001 -- the connection drops on shutdown
                pass
        print(f"stopped (port {args.port})")
        return

    if not _running(args.port):
        _start(args.port, args.dbpath, _find_mongod(args.mongod))
    _initiate(args.port)
    print(f"ready: mongodb://127.0.0.1:{args.port}/?replicaSet={SET_NAME}")


if __name__ == "__main__":
    main()
