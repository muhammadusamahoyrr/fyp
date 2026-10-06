"""End-to-end smoke test of the Document Analyzer against a REAL server process.

What it proves that the unit and integration suites cannot: the actual app,
started by uvicorn with DOC_ANALYZER on, its real startup (indexes, readiness,
background worker and housekeeping loops), real login, real multipart upload
over HTTP -- all working together.

ISOLATION (nothing shared is touched):
  * MongoDB: a throwaway database `attorney_ai_smoke` on the dev replica set
    (127.0.0.1:27018, see dev_mongo_replset.py); dropped at the end.
  * No Redis; no AI, SMTP, telemetry or payment credentials (all blanked).
  * Chroma: a temporary directory (see _analyzer_smoke_server.py).
  * Uploads: a temporary upload_root. A fresh random master key.
  * The real backend/.env is read but never modified; every value that
    could reach a shared service is overridden here.

Run:  python scripts/dev_mongo_replset.py && python scripts/analyzer_smoke.py
Exit code 0 = every check passed.
"""
from __future__ import annotations

import base64
import io
import os
import secrets
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

import httpx
from pymongo import MongoClient

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

PORT = 8765
BASE = f"http://127.0.0.1:{PORT}/api/v1"
MONGO = "mongodb://127.0.0.1:27018/?replicaSet=rs0"
DB = "attorney_ai_smoke"

passed: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    if not condition:
        raise SystemExit(f"FAIL  {label}  {detail}")
    passed.append(label)
    print(f"ok    {label}", flush=True)


def pdf(lines: list[str]) -> bytes:
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    for line in lines:
        c.drawString(72, 720, line)
        c.showPage()
    c.save()
    return buf.getvalue()


def env() -> dict:
    e = dict(os.environ)
    e.update({
        "MONGODB_URL": MONGO, "DB_NAME": DB, "REDIS_URL": "",
        "DOC_ANALYZER": "true", "RUN_SCHEDULERS": "true",
        "ANALYZER_KEKS": "smoke:" + base64.b64encode(secrets.token_bytes(32)).decode(),
        "ANALYZER_KEK_ACTIVE": "smoke",
        "UPLOAD_ROOT": tempfile.mkdtemp(prefix="analyzer-smoke-uploads-"),
        "GROQ_API_KEY": "", "GROQ_API_KEY_2": "", "GEMINI_API_KEY": "", "OPENROUTER_API_KEY": "",
        "SMTP_HOST": "", "SMTP_USER": "", "SMTP_PASSWORD": "",
        "LANGFUSE_PUBLIC_KEY": "", "LANGFUSE_SECRET_KEY": "", "LANGFUSE_HOST": "",
        "SAFEPAY_API_KEY": "", "SAFEPAY_SECRET_KEY": "", "SAFEPAY_WEBHOOK_SECRET": "",
        "PAYMENTS_DRY_RUN": "true", "ENGLISH_OCR_ENABLED": "false",
    })
    return e


def seed_lawyer(mongo: MongoClient) -> tuple[str, str]:
    """The analyzer is a lawyer's tool (2026-10-03): the smoke signs in as one."""
    from app.core.security import hash_password
    email, password = f"smoke-{uuid.uuid4().hex[:8]}@example.com", secrets.token_urlsafe(16)
    mongo[DB]["users"].insert_one({
        "_id": uuid.uuid4().hex, "role": "lawyer", "email": email,
        "password_hash": hash_password(password), "full_name": "Smoke Lawyer",
        "phone": None, "province": None, "avatar_url": None, "is_active": True})
    return email, password


def wait_for(client, run_id, statuses, *, timeout=120):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        run = client.get(f"/documents/analyses/runs/{run_id}").json()
        if run.get("status") in statuses:
            return run
        time.sleep(1)
    raise SystemExit(f"FAIL  run {run_id} did not reach {statuses} (last: {run.get('status')})")


def main() -> None:
    mongo = MongoClient(MONGO, serverSelectionTimeoutMS=3000)
    mongo.admin.command("ping")
    mongo.drop_database(DB)
    # The app refuses to start until the appointment correctness indexes exist:
    # by design they are an OPERATOR step (appointment_slot_preflight), never
    # created at startup. On this empty, throwaway database that step is
    # trivially safe, so it is done here -- from the app's own index spec.
    from app.db.appointment_index_spec import ALL_INDEX_REQUIREMENTS
    for spec in ALL_INDEX_REQUIREMENTS:          # appointments AND disputes
        mongo[DB][spec.collection].create_indexes([spec.model()])
    # The server's output goes to a file: an unread pipe fills up and blocks
    # the server mid-request.
    log_path = Path(tempfile.mkdtemp(prefix="analyzer-smoke-log-")) / "server.log"
    log = open(log_path, "wb")
    print(f"server log: {log_path}", flush=True)
    server = subprocess.Popen([sys.executable, str(BACKEND / "scripts" / "_analyzer_smoke_server.py"), str(PORT)],
                              cwd=str(BACKEND), env=env(), stdout=log, stderr=subprocess.STDOUT)
    try:
        for _ in range(240):
            try:
                if httpx.get(f"http://127.0.0.1:{PORT}/", timeout=2).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            if server.poll() is not None:
                raise SystemExit(f"FAIL  the smoke server exited during startup; see {log_path}")
            time.sleep(0.5)
        else:
            raise SystemExit("FAIL  the smoke server did not start")
        check("server started with DOC_ANALYZER on (isolated)", True)

        email, password = seed_lawyer(mongo)
        login = httpx.post(f"{BASE}/auth/login", json={"email": email, "password": password}, timeout=30)
        check("real login", login.status_code == 200, login.text[:200])
        client = httpx.Client(base_url=BASE, timeout=60,
                              headers={"Authorization": f"Bearer {login.json()['access_token']}"})

        att = client.get("/documents/analyses/attestation")
        check("analyzer is ready (attestation served)", att.status_code == 200, att.text[:200])
        version = att.json()["version"]

        unattested = client.post("/documents/analyses", headers={"Idempotency-Key": uuid.uuid4().hex},
                                 files={"file": ("x.pdf", b"%PDF-1.4", "application/pdf")})
        check("unattested upload refused", unattested.status_code == 422
              and unattested.json()["error"]["code"] == "synthetic_attestation_required")

        upload = client.post("/documents/analyses", data={"side": "tenant"},
                             headers={"X-Synthetic-Data-Attested": "true",
                                      "X-Synthetic-Attestation-Version": version,
                                      "Idempotency-Key": uuid.uuid4().hex},
                             files={"file": ("lease.pdf", pdf([
                                 "TENANCY AGREEMENT made at Lahore between the Landlord and the Tenant.",
                                 "1. The term is eleven (11) months. 2. Rent is Rs. 85,000 per month.",
                                 "Signed in the presence of two witnesses."]), "application/pdf")})
        check("synthetic upload accepted (202)", upload.status_code == 202, upload.text[:200])
        created = upload.json()

        run = wait_for(client, created["run_id"], {"needs_document_confirmation", "failed"})
        check("background worker extracted and segmented", run["status"] == "needs_document_confirmation",
              str(run.get("error_code")))
        check("document proposed as a Punjab tenancy",
              run["document_review"]["document_type"]["value"] == "tenancy"
              and run["document_review"]["jurisdiction"]["value"] == "punjab")

        r = client.post(f"/documents/analyses/runs/{created['run_id']}/document",
                        json={"expected_state_version": run["state_version"],
                              "document_type": "tenancy", "jurisdiction": "punjab"})
        check("document confirmed", r.status_code == 200, r.text[:200])
        run = wait_for(client, created["run_id"], {"needs_terms_confirmation", "failed"})
        months = [c["value"] for c in run["terms_review"]["candidates"]["term_months"]]
        check("key terms proposed with evidence", months == [11], str(months))

        r = client.post(f"/documents/analyses/runs/{created['run_id']}/terms", json={
            "expected_state_version": run["state_version"],
            "terms": {"term_months": {"value": 11, "sentence_ids": []},
                      "rent_period": {"value": "monthly", "sentence_ids": []},
                      "tenancy_year_to_year": {"value": None, "sentence_ids": []}}})
        check("terms confirmed", r.status_code == 200, r.text[:200])
        run = wait_for(client, created["run_id"], {"done", "failed"})
        check("analysis finished", run["status"] == "done", str(run.get("error_code")))

        report = client.get(f"/documents/analyses/runs/{created['run_id']}/report").json()
        status = {p["pack_id"]: p["status"] for p in report["packs"]}
        check("general review applied", status.get("general") == "applied", str(status))
        check("unapproved tenancy pack reported, not run",
              status.get("tenancy_punjab") == "awaiting_approval"
              and not any(f["scope"] == "legal_playbook" for f in report["legal_checks"]), str(status))
        evidence = [e["text"] for f in report["legal_checks"] for e in f["evidence"]]
        check("evidence is exact text from the document",
              "Signed in the presence of two witnesses." in evidence)

        history = client.get("/documents/analyses").json()["items"]
        check("history lists the analysis", any(i["id"] == created["source_id"] for i in history))

        deleted = client.delete(f"/documents/analyses/{created['source_id']}")
        check("delete accepted (204)", deleted.status_code == 204)
        check("deleted analysis is 404 at once",
              client.get(f"/documents/analyses/{created['source_id']}").status_code == 404)
        deadline = time.monotonic() + 150
        while time.monotonic() < deadline:
            job = mongo[DB]["analysis_deletion_outbox"].find_one({"source_id": created["source_id"]})
            if job and job.get("done_at"):
                break
            time.sleep(3)
        check("housekeeping purged it", bool(job and job.get("done_at")))
        check("no blobs or runs survive the purge",
              mongo[DB]["analysis_blobs"].count_documents({"source_id": created["source_id"]}) == 0
              and mongo[DB]["analysis_runs"].count_documents({"source_id": created["source_id"]}) == 0)
        print(f"\nSMOKE PASSED: {len(passed)} checks")
    finally:
        server.terminate()
        try:
            server.wait(timeout=20)
        except subprocess.TimeoutExpired:
            server.kill()
        log.close()
        mongo.drop_database(DB)


if __name__ == "__main__":
    main()
