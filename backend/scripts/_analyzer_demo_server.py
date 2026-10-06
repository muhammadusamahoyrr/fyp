"""The backend process of the OFFLINE analyzer demo. Started by
scripts/analyzer_demo.py -- not meant to be run by hand.

    python scripts/_analyzer_demo_server.py --port 8765 --db-name aai_demo_<hex> --state <dir>

Runs the REAL FastAPI app on 127.0.0.1 against a fresh, dedicated demo
database on the local replica set, with the analyzer's demo mode active
(ANALYZER_AI_PROVIDER=simulated, app/services/analyzer/simulated_provider.py:
labelled as such everywhere). Before the app's settings are built, every hosted service is
blanked and the JWT and field-encryption keys are replaced by fresh
per-process ones, so demo data is unreadable outside this run and nothing
from the real `.env` secrets protects it. A socket guard refuses every
non-loopback connection for the life of the process.

Stops gracefully when `<state>/backend.stop` appears (Windows cannot signal a
detached process); the demo database is left in place for `reset`.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import secrets
import sys
import tempfile
import threading
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "scripts"))

ACCOUNTS = {  # fictional demo accounts; passwords are generated per start
    "lawyer": ("Demo Lawyer (synthetic)", "demo.lawyer@example.com", "lawyer", "DEMO/0001"),
    "second_lawyer": ("Second Demo Lawyer (synthetic)", "demo.lawyer2@example.com", "lawyer", "DEMO/0002"),
    "client": ("Demo Client (synthetic)", "demo.client@example.com", "client", None),
}


def demo_password() -> str:
    """Random, and always within the registration policy (upper case, digit, 8-72 chars)."""
    return f"Demo-{secrets.token_urlsafe(9)}-{secrets.randbelow(900) + 100}"


def _write(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--frontend-port", type=int, required=True)
    parser.add_argument("--mongo", default="mongodb://127.0.0.1:27018/?replicaSet=rs0")
    parser.add_argument("--db-name", required=True)
    parser.add_argument("--state", type=Path, required=True)
    args = parser.parse_args()

    from analyzer_demo import check_database             # light: no settings, no database
    check_database(args.mongo, args.db_name)             # refuses hosted / non-demo databases

    from cryptography.fernet import Fernet
    os.environ.update({
        "MONGODB_URL": args.mongo, "DB_NAME": args.db_name,
        "SECRET_KEY": secrets.token_hex(32), "ENCRYPTION_KEY": Fernet.generate_key().decode(),
        "SIGNATURE_ENCRYPTION_KEY": "", "APP_ENV": "development",
        "FRONTEND_URL": f"http://127.0.0.1:{args.frontend_port}",
        "REDIS_URL": "", "RUN_SCHEDULERS": "false", "CHROMA_HOST": "",
        "SMTP_HOST": "", "SMTP_USER": "", "SMTP_PASSWORD": "",
        "LANGFUSE_PUBLIC_KEY": "", "LANGFUSE_SECRET_KEY": "", "LANGFUSE_HOST": "",
        "SAFEPAY_API_KEY": "", "SAFEPAY_SECRET_KEY": "", "SAFEPAY_WEBHOOK_SECRET": "", "PAYMENTS_DRY_RUN": "true",
        "GROQ_API_KEY": "", "GROQ_API_KEY_2": "", "GROQ_API_KEY_3": "", "GEMINI_API_KEY": "",
        "OPENROUTER_API_KEY": "", "ANALYZER_AI_MODEL": "", "ANALYZER_AI_POLICY_ID": "",
        "ANALYZER_AI_ZDR_STATUS": "unverified", "ANALYZER_AI_ZDR_VERIFIED_ON": "", "ANALYZER_AI_ZDR_EVIDENCE": "",
        "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"})
    from analyzer_browser_smoke import guard_network
    refused = guard_network()

    # Chroma is embedded at backend/chroma_data; a second process opening it can
    # corrupt it. The analyzer never uses it: give this process an empty one.
    from app.db import chroma
    chroma._CHROMA_PATH = Path(tempfile.mkdtemp(prefix="aai-demo-chroma-"))

    from app.core.config import settings
    assert settings.db_name == args.db_name and settings.mongodb_url == args.mongo
    settings.doc_analyzer = True
    settings.analyzer_ai = True
    settings.analyzer_ai_synthetic_only = True
    settings.analyzer_pii_review_required = True
    settings.analyzer_engine_hypotheses = False        # the AI report engine; drafting questions stay off
    settings.analyzer_hypothesis_review_ui = False
    settings.upload_root = str(args.state / "uploads" / args.db_name)
    settings.analyzer_keks = "k1:" + base64.b64encode(secrets.token_bytes(32)).decode()   # memory only
    settings.analyzer_kek_active = "k1"
    settings.analyzer_ai_provider = "simulated"          # the normal pipeline's simulated provider

    import app.main as main_module

    async def _no_warmup():                            # Whisper/embeddings: heavy and unused here
        return None

    main_module._warmup_models = _no_warmup

    async def seed() -> dict:
        from app.db.appointment_index_spec import ALL_INDEX_REQUIREMENTS
        from app.db.indexes import create_all_indexes
        from app.db.mongodb import close_db, connect_db, get_database
        from app.schemas.auth import RegisterRequest
        from app.services import auth_service
        await connect_db()
        db = get_database()
        assert db.name == args.db_name and await db.list_collection_names() == [], "not a fresh demo database"
        await create_all_indexes()
        # Appointment indexes are an operator step in production; on an empty
        # demo database the operator step is exactly these specs.
        for spec in ALL_INDEX_REQUIREMENTS:
            options = {"name": spec.name, "unique": spec.unique, "sparse": spec.sparse}
            if spec.partial_filter:
                options["partialFilterExpression"] = dict(spec.partial_filter)
            await db[spec.collection].create_index(list(spec.keys), **options)
        out = {}
        for key, (full_name, email, role, bar) in ACCOUNTS.items():
            password = demo_password()
            await auth_service.register(RegisterRequest(full_name=full_name, email=email, password=password,
                                                        role=role))
            if bar:   # onboarded, as the lawyer dashboard requires (fictional bar number)
                await db["users"].update_one({"email": email}, {"$set": {
                    "lawyer_profile.bar_number": bar, "lawyer_profile.specializations": ["Civil Litigation"]}})
            out[key] = {"email": email, "password": password, "role": role}
        await close_db()                               # the app reconnects on its own loop at startup
        return out

    accounts = asyncio.run(seed())
    _write(args.state / "accounts.json", {
        "notice": "Local offline demo accounts for a throwaway database. Not real people. Regenerated on every start.",
        "database": args.db_name, "accounts": accounts})

    import uvicorn
    server = uvicorn.Server(uvicorn.Config(main_module.app, host="127.0.0.1", port=args.port, log_level="warning"))
    stop_file = args.state / "backend.stop"

    def watch() -> None:
        while not server.started and not server.should_exit:
            time.sleep(0.2)
        from app.services.analyzer import readiness
        _write(args.state / "backend.ready.json", {
            "pid": os.getpid(), "port": args.port, "db_name": args.db_name, "ai_provider": settings.analyzer_ai_provider,
            "analyzer_ready": readiness.is_ready(), "analyzer_problems": list(readiness.problems())})
        while not stop_file.exists() and not server.should_exit:
            time.sleep(0.5)
        server.should_exit = True

    threading.Thread(target=watch, daemon=True).start()
    try:
        server.run()
    finally:
        _write(args.state / "backend.exit.json", {"refused_hosts": sorted(set(refused))})
    return 0


if __name__ == "__main__":
    sys.exit(main())
