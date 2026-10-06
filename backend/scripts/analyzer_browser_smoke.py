"""OFFLINE browser smoke-test server for the Document Analyzer. TEST TOOL ONLY.

    python scripts/analyzer_browser_smoke.py --port 8765 --out <scratch dir>
    python scripts/analyzer_browser_smoke.py --cleanup --out <scratch dir>   # after a forced stop

Runs the real FastAPI app on 127.0.0.1 against a SCRATCH database on the local
development replica set, with a FAKE AI provider injected in-process (the
`TRANSPORT` hook the test suite uses) that records each request body it
receives to `<out>/captured.jsonl`. Seeds two lawyers and a client through the
real registration code. On exit (Ctrl+C / SIGTERM) the scratch database and
files are removed.

Why this cannot leak into production:
  * it is a script under `scripts/`, not a route, setting or env flag: the
    fake transport is a module attribute set in THIS process only, and the
    app never sets or reads a "fake provider" switch (tests assert it);
  * it refuses to start unless the database is loopback and the database
    name starts with `aai_smoke_` -- never the configured `.env` database;
  * hosted services (Redis, SMTP, Langfuse, Safepay, model keys) are blanked
    BEFORE the app's settings are built, and a socket guard refuses any
    connection to a non-loopback host for the life of the process.
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import socket
import sys
import tempfile
from pathlib import Path

LOOPBACK = {"localhost", "127.0.0.1", "::1"}


def _is_local(host) -> bool:
    if host is None:
        return True
    host = (host.decode() if isinstance(host, bytes) else str(host)).strip("[]").lower()
    return host in LOOPBACK or host.startswith("127.")


def guard_network() -> list[str]:
    """Refuse every name lookup and connection that is not loopback."""
    refused: list[str] = []
    real_lookup, real_connect = socket.getaddrinfo, socket.socket.connect

    def lookup(host, *a, **kw):
        if not _is_local(host):
            refused.append(str(host))
            raise OSError(f"smoke: external network refused ({host})")
        return real_lookup(host, *a, **kw)

    def connect(self, address):
        if isinstance(address, tuple) and not _is_local(address[0]):
            refused.append(str(address[0]))
            raise OSError("smoke: external connection refused")
        return real_connect(self, address)

    socket.getaddrinfo = lookup
    socket.socket.connect = connect
    return refused


def _cleanup(args) -> int:
    """A forced stop (e.g. Stop-Process on Windows) skips the server's own
    cleanup: drop exactly the scratch database and work folder it recorded."""
    import pymongo
    from urllib.parse import urlparse
    recorded = json.loads((args.out / "server.json").read_text(encoding="utf-8"))
    if not recorded["db_name"].startswith("aai_smoke_") or not _is_local(urlparse(args.mongo).hostname):
        print("refused: not a smoke scratch database", file=sys.stderr)
        return 2
    with pymongo.MongoClient(args.mongo, serverSelectionTimeoutMS=5000) as client:
        client.drop_database(recorded["db_name"])
    shutil.rmtree(recorded["work"], ignore_errors=True)
    print(f"smoke cleanup: dropped {recorded['db_name']}, removed {recorded['work']}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--mongo", default="mongodb://127.0.0.1:27018/?replicaSet=rs0")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--cleanup", action="store_true",
                        help="drop the scratch database and files recorded in <out>/server.json (after a forced stop)")
    args = parser.parse_args()
    if args.cleanup:
        return _cleanup(args)
    from urllib.parse import urlparse
    if not _is_local(urlparse(args.mongo).hostname):
        print("refused: the smoke server runs only against a loopback database", file=sys.stderr)
        return 2
    db_name = f"aai_smoke_{secrets.token_hex(4)}"
    work = Path(tempfile.mkdtemp(prefix="aai_smoke_"))
    args.out.mkdir(parents=True, exist_ok=True)

    # BEFORE the app builds its settings: scratch database, no hosted services.
    os.environ.update({"MONGODB_URL": args.mongo, "DB_NAME": db_name, "REDIS_URL": "", "RUN_SCHEDULERS": "false",
                       "SMTP_HOST": "", "SMTP_USER": "", "SMTP_PASSWORD": "", "LANGFUSE_PUBLIC_KEY": "",
                       "LANGFUSE_SECRET_KEY": "", "LANGFUSE_HOST": "", "SAFEPAY_API_KEY": "",
                       "SAFEPAY_SECRET_KEY": "", "SAFEPAY_WEBHOOK_SECRET": "", "GROQ_API_KEY": "",
                       "GROQ_API_KEY_2": "", "GEMINI_API_KEY": "", "OPENROUTER_API_KEY": "",
                       "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"})
    refused = guard_network()
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    import asyncio
    import base64

    import httpx
    import uvicorn

    from app.core.config import settings
    assert settings.db_name == db_name and _is_local(urlparse(settings.mongodb_url).hostname)
    from app.services.analyzer import ai_records, ai_stage, hypothesis_review_stage
    from tests.test_analyzer_ai_config import GOOD                # the test suite's in-process AI settings
    from tests.test_analyzer_pii_confirmation import answer_with_token

    for name, value in GOOD.items():
        setattr(settings, name, value)
    settings.doc_analyzer = True
    settings.analyzer_pii_review_required = True
    settings.analyzer_ai_synthetic_only = True
    settings.upload_root = str(work / "uploads")
    settings.analyzer_keks = "k1:" + base64.b64encode(secrets.token_bytes(32)).decode()
    settings.analyzer_kek_active = "k1"
    ai_records.POLICY_DIR = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "ai_policies"

    captured = args.out / "captured.jsonl"

    async def respond(request):
        body = json.loads(request.content)
        with captured.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"messages": body["messages"]}) + "\n")
        prompt = body["messages"][1]["content"]
        if "## item " in prompt:
            import re
            from app.services.analyzer.hypotheses import review
            answer = {"schema_version": review.SCHEMA_VERSION, "prompt_version": review.PROMPT_VERSION,
                      "reviews": [{"question_id": q, "signal": "supports", "explanation": "Named in the wording."}
                                  for q in re.findall(r"^## item (\w+)$", prompt, re.M)]}
        else:
            answer = answer_with_token(prompt)
        return httpx.Response(200, json={"model": body["model"], "id": "smoke-1", "usage": {"total_tokens": 9},
                                         "choices": [{"finish_reason": "stop",
                                                      "message": {"content": json.dumps(answer)}}]})

    ai_stage.TRANSPORT = httpx.MockTransport(respond)
    hypothesis_review_stage.TRANSPORT = httpx.MockTransport(respond)

    async def seed():
        from app.db.mongodb import connect_db
        from app.schemas.auth import RegisterRequest
        from app.services import auth_service
        await connect_db()
        from app.db.indexes import create_all_indexes
        await create_all_indexes()             # a fresh scratch database: production's own index set
        # The appointment indexes are an OPERATOR step in production (the startup
        # preflight refuses to create them); on an empty scratch database the
        # operator step is exactly these specs.
        from app.db.appointment_index_spec import ALL_INDEX_REQUIREMENTS
        from app.db.mongodb import get_database
        db = get_database()
        for spec in ALL_INDEX_REQUIREMENTS:
            options = {"name": spec.name, "unique": spec.unique, "sparse": spec.sparse}
            if spec.partial_filter:
                options["partialFilterExpression"] = dict(spec.partial_filter)
            await db[spec.collection].create_index(list(spec.keys), **options)
        accounts = {"lawyer_a": ("Smoke Lawyer A", "smoke.lawyer.a@example.com", "lawyer"),
                    "lawyer_b": ("Smoke Lawyer B", "smoke.lawyer.b@example.com", "lawyer"),
                    "client": ("Smoke Client", "smoke.client@example.com", "client")}
        password = "Smoke-Pass-" + secrets.token_hex(4)
        for full_name, email, role in accounts.values():
            await auth_service.register(RegisterRequest(full_name=full_name, email=email, password=password,
                                                        role=role))
        # The smoke test exercises the Analyzer, not onboarding: both lawyers are
        # onboarded (the dashboard's own test: a bar number and a specialization).
        lawyers = get_database()["users"].find({"role": "lawyer", "email": {"$regex": r"^smoke\."}}, {"_id": 1})
        for n, user in enumerate(await lawyers.sort("email", 1).to_list(None)):
            await get_database()["users"].update_one({"_id": user["_id"]}, {"$set": {
                "lawyer_profile.bar_number": f"SMOKE/{n + 1:04d}", "lawyer_profile.specializations": ["Civil Litigation"]}})
        (args.out / "accounts.json").write_text(json.dumps(
            {k: {"email": v[1], "password": password, "role": v[2]} for k, v in accounts.items()}), encoding="utf-8")
        from app.db.mongodb import close_db
        await close_db()                       # the app reconnects on its own loop at startup

    def cleanup():
        import pymongo
        with pymongo.MongoClient(args.mongo, serverSelectionTimeoutMS=5000) as client:
            assert db_name.startswith("aai_smoke_")
            client.drop_database(db_name)

    try:
        asyncio.run(seed())
        (args.out / "server.json").write_text(json.dumps({"port": args.port, "db_name": db_name, "work": str(work)}),
                                              encoding="utf-8")
        print(f"smoke server: http://127.0.0.1:{args.port} db={db_name} out={args.out}", flush=True)
        uvicorn.run("app.main:app", host="127.0.0.1", port=args.port, log_level="warning")
    finally:
        try:
            cleanup()
        finally:
            shutil.rmtree(work, ignore_errors=True)
            (args.out / "refused.json").write_text(json.dumps(sorted(set(refused))), encoding="utf-8")
            print("smoke server: scratch database dropped, files removed", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
