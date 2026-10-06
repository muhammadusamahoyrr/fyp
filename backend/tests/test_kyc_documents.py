"""Lawyer KYC uploads: onboarding's Credentials & Photo step, made real.

Before this, the step's upload buttons sent nothing and the admin KYC screen
listed hardcoded document names. These tests go through the HTTP routes with
the real role guards (only the signed-in user is overridden).
"""
from __future__ import annotations

import secrets

import pytest
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.integration

PDF = b"%PDF-1.4\n% kyc test\n" + b"0" * 64
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


@pytest.fixture
async def world(mongo, tmp_path, monkeypatch):
    from app.core.config import settings
    from app.core.security import hash_password
    from app.db.collections import get_users_col

    monkeypatch.setattr(settings, "upload_root", str(tmp_path))
    tag = secrets.token_hex(4)
    lawyer, other, client = f"KYC-L-{tag}", f"KYC-O-{tag}", f"KYC-C-{tag}"
    # bar_number is uniquely indexed: one per test lawyer.
    def profile(n):
        return {"bar_number": f"PBC/{tag}/{n}", "specializations": ["civil"], "kyc_verified": False,
                "kyc_status": "pending"}
    await get_users_col().insert_many([
        {"_id": lawyer, "role": "lawyer", "full_name": "Adv One", "email": f"l-{tag}@k.pk",
         "is_active": True, "password_hash": hash_password("Passw0rd!x"), "lawyer_profile": profile(1)},
        {"_id": other, "role": "lawyer", "full_name": "Adv Two", "email": f"o-{tag}@k.pk",
         "is_active": True, "lawyer_profile": profile(2)},
        {"_id": client, "role": "client", "full_name": "Client", "email": f"c-{tag}@k.pk",
         "is_active": True, "lawyer_profile": None},
    ])
    yield {"lawyer": lawyer, "other": other, "client": client, "root": tmp_path / "kyc"}
    await get_users_col().delete_many({"_id": {"$in": [lawyer, other, client]}})


@pytest.fixture(autouse=True)
def _clear_overrides():
    from app.main import app
    from app.core.rate_limit import limiter
    was = limiter.enabled
    limiter.enabled = False
    yield
    limiter.enabled = was
    app.dependency_overrides.clear()


def _as(user_id: str, role: str) -> AsyncClient:
    from app.dependencies import get_current_user
    from app.main import app

    app.dependency_overrides[get_current_user] = lambda: {"_id": user_id, "role": role}
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test/api/v1")


async def _upload(user_id, role, kind, content, name="file.bin"):
    async with _as(user_id, role) as c:
        return await c.post("/users/me/kyc/documents", data={"kind": kind},
                            files={"file": (name, content, "application/octet-stream")})


async def test_a_lawyer_uploads_a_credential_and_sees_it_listed(world):
    resp = await _upload(world["lawyer"], "lawyer", "bar_certificate", PDF, "bar.pdf")
    assert resp.status_code == 200, resp.text
    meta = resp.json()["bar_certificate"]
    assert meta["filename"] == "bar.pdf" and meta["content_type"] == "application/pdf"
    async with _as(world["lawyer"], "lawyer") as c:
        listed = (await c.get("/users/me/kyc/documents")).json()
    assert set(listed) == {"bar_certificate"}
    assert len(list((world["root"] / world["lawyer"]).iterdir())) == 1


async def test_types_are_checked_from_the_bytes(world):
    # Text pretending to be a PDF by name.
    assert (await _upload(world["lawyer"], "lawyer", "education", b"hello", "x.pdf")).status_code == 422
    # A PDF is not a photo.
    assert (await _upload(world["lawyer"], "lawyer", "photo", PDF, "me.png")).status_code == 422
    assert (await _upload(world["lawyer"], "lawyer", "photo", PNG, "me.png")).status_code == 200


async def test_size_limit_and_unknown_kind_are_refused(world):
    big = PDF + b"0" * (5 * 1024 * 1024)
    assert (await _upload(world["lawyer"], "lawyer", "education", big)).status_code == 422
    assert (await _upload(world["lawyer"], "lawyer", "passport", PDF)).status_code == 422


async def test_only_lawyers_can_upload(world):
    assert (await _upload(world["client"], "client", "bar_certificate", PDF)).status_code == 403


async def test_reuploading_a_kind_replaces_the_file(world):
    await _upload(world["lawyer"], "lawyer", "professional", PDF, "a.pdf")
    resp = await _upload(world["lawyer"], "lawyer", "professional", PNG, "b.png")
    assert resp.json()["professional"]["filename"] == "b.png"
    files = list((world["root"] / world["lawyer"]).iterdir())
    assert len(files) == 1 and files[0].suffix == ".png"


async def test_admin_views_the_file_inline_and_uncached(world):
    await _upload(world["lawyer"], "lawyer", "bar_certificate", PDF, "bar.pdf")
    async with _as("ADMIN-1", "admin") as c:
        resp = await c.get(f"/admin/kyc/{world['lawyer']}/documents/bar_certificate")
        missing = await c.get(f"/admin/kyc/{world['other']}/documents/bar_certificate")
    assert resp.status_code == 200
    assert resp.content == PDF
    assert resp.headers["content-disposition"].startswith("inline")
    assert "no-store" in resp.headers["cache-control"]
    assert missing.status_code == 404


async def test_no_one_but_an_admin_can_read_a_lawyers_files(world):
    await _upload(world["lawyer"], "lawyer", "bar_certificate", PDF)
    async with _as(world["other"], "lawyer") as c:
        resp = await c.get(f"/admin/kyc/{world['lawyer']}/documents/bar_certificate")
    assert resp.status_code == 403


async def test_closing_the_account_removes_the_files_and_the_record(world):
    from app.db.collections import get_users_col
    from app.services import user_service

    await _upload(world["lawyer"], "lawyer", "bar_certificate", PDF)
    assert (world["root"] / world["lawyer"]).exists()
    await user_service.close_account(world["lawyer"], "Passw0rd!x")
    assert not (world["root"] / world["lawyer"]).exists()
    user = await get_users_col().find_one({"_id": world["lawyer"]})
    assert "kyc_documents" not in (user.get("lawyer_profile") or {})


async def test_a_failed_erasure_keeps_a_tombstone_and_the_sweep_finishes_it(world, monkeypatch):
    """Deletion failure must be observable and retried: never files on disk
    with no record pointing at them (branch review, finding 1)."""
    from app.db.collections import get_users_col
    from app.services import kyc_documents, user_service

    await _upload(world["lawyer"], "lawyer", "bar_certificate", PDF, "Adv One bar.pdf")
    folder = world["root"] / world["lawyer"]

    real_rmtree = kyc_documents.shutil.rmtree

    # A locked file, as shutil sees it: with ignore_errors the failure is
    # swallowed silently (the old behaviour), otherwise it raises.
    def locked(path, ignore_errors=False, **k):
        if not ignore_errors:
            raise PermissionError("file in use")
    monkeypatch.setattr(kyc_documents.shutil, "rmtree", locked)
    await user_service.close_account(world["lawyer"], "Passw0rd!x")

    assert folder.exists(), "the files should still be on disk after a failed deletion"
    lp = (await get_users_col().find_one({"_id": world["lawyer"]}))["lawyer_profile"]
    assert lp.get("kyc_erasure_pending"), "no tombstone was kept for the pending erasure"
    assert lp["kyc_documents"]["bar_certificate"]["file_id"], "the pointer to the files was lost"
    assert "filename" not in lp["kyc_documents"]["bar_certificate"], "the filename (personal data) was kept"
    assert "file in use" in lp.get("kyc_erasure_error", "")

    # Only the delete is restored; the fixture's upload_root patch stays.
    monkeypatch.setattr(kyc_documents.shutil, "rmtree", real_rmtree)
    assert await kyc_documents.retry_pending_erasures() >= 1
    assert not folder.exists()
    lp = (await get_users_col().find_one({"_id": world["lawyer"]}))["lawyer_profile"]
    assert "kyc_documents" not in lp and "kyc_erasure_pending" not in lp


# ── Truthful, retry-safe erasure (branch review, final round) ──────────────

def _lock_folders_of(monkeypatch, kyc_documents, locked_ids):
    """rmtree fails for these users' folders (a locked file), works otherwise."""
    real = kyc_documents.shutil.rmtree

    def rmtree(path, ignore_errors=False, **k):
        if any(str(path).endswith(i) for i in locked_ids):
            if not ignore_errors:
                raise PermissionError("file in use")
            return
        return real(path, ignore_errors=ignore_errors, **k)
    monkeypatch.setattr(kyc_documents.shutil, "rmtree", rmtree)
    return real


async def _close(user_id):
    from app.db.collections import get_users_col
    from app.services import user_service
    user = await get_users_col().find_one({"_id": user_id})
    return await user_service._close_account_record(user, reason="test")


async def test_the_closure_response_says_what_is_true(world, monkeypatch):
    from app.services import kyc_documents, user_service

    await _upload(world["other"], "lawyer", "bar_certificate", PDF)
    ok = await _close(world["other"])
    assert ok["kyc_erasure_pending"] is False
    assert "personal details have been erased" in ok["detail"]

    await _upload(world["lawyer"], "lawyer", "bar_certificate", PDF)
    _lock_folders_of(monkeypatch, kyc_documents, [world["lawyer"]])
    pending = await user_service.close_account(world["lawyer"], "Passw0rd!x")
    assert pending["closed"] is True and pending["kyc_erasure_pending"] is True
    assert "personal details have been erased" not in pending["detail"]
    assert "scheduled for deletion" in pending["detail"]


async def test_a_secondary_database_failure_does_not_fail_a_completed_closure(world, monkeypatch):
    from app.services import kyc_documents, user_service

    await _upload(world["lawyer"], "lawyer", "bar_certificate", PDF)
    _lock_folders_of(monkeypatch, kyc_documents, [world["lawyer"]])

    async def db_down(*a, **k):
        raise RuntimeError("database unavailable")
    monkeypatch.setattr(kyc_documents.user_repo, "update_one", db_down)
    result = await user_service.close_account(world["lawyer"], "Passw0rd!x")
    assert result["closed"] is True and result["kyc_erasure_pending"] is True


async def test_one_users_failure_does_not_abort_the_retry_batch(world, monkeypatch):
    from app.services import kyc_documents

    for u in (world["lawyer"], world["other"]):
        await _upload(u, "lawyer", "bar_certificate", PDF)
    _lock_folders_of(monkeypatch, kyc_documents, [world["lawyer"], world["other"]])
    await _close(world["lawyer"])
    await _close(world["other"])
    monkeypatch.undo()
    monkeypatch.setattr(__import__("app.core.config", fromlist=["settings"]).settings,
                        "upload_root", str(world["root"].parent))

    real_erase = kyc_documents.erase

    async def erase(user_id):
        if user_id == world["lawyer"]:
            raise RuntimeError("unexpected")
        return await real_erase(user_id)
    monkeypatch.setattr(kyc_documents, "erase", erase)
    assert await kyc_documents.retry_pending_erasures() >= 1
    assert not (world["root"] / world["other"]).exists(), "a failure for one user aborted the batch"


async def test_a_user_that_keeps_failing_does_not_starve_the_rest(world, monkeypatch):
    from app.services import kyc_documents

    for u in (world["lawyer"], world["other"]):
        await _upload(u, "lawyer", "bar_certificate", PDF)
    _lock_folders_of(monkeypatch, kyc_documents, [world["lawyer"], world["other"]])
    await _close(world["lawyer"])     # fails first: the oldest attempt
    await _close(world["other"])
    # Only the first lawyer's folder stays locked from here on.
    monkeypatch.undo()
    monkeypatch.setattr(__import__("app.core.config", fromlist=["settings"]).settings,
                        "upload_root", str(world["root"].parent))
    _lock_folders_of(monkeypatch, kyc_documents, [world["lawyer"]])

    # One candidate per run: the always-failing user is tried first, then moves
    # to the back, and the next run reaches the other one.
    await kyc_documents.retry_pending_erasures(batch=1, max_batches=1)
    assert (world["root"] / world["other"]).exists()
    await kyc_documents.retry_pending_erasures(batch=1, max_batches=1)
    assert not (world["root"] / world["other"]).exists(), "the failing user starved the rest"


async def test_the_retry_sweep_runs_only_where_it_holds_the_period_lock(monkeypatch):
    import asyncio
    import app.core.redis_client as redis_client
    import app.services.kyc_documents as kyc_documents
    from app.main import _kyc_erasure_retry

    calls = []

    async def retry():
        calls.append(1)
        return 0
    monkeypatch.setattr(kyc_documents, "retry_pending_erasures", retry)
    for held, expected in ((False, 0), (True, 1)):
        calls.clear()

        async def lock(key, ttl_seconds):
            assert key == "lock:scheduler:kyc_erasure"
            return held
        monkeypatch.setattr(redis_client, "acquire_period_lock", lock)
        ticks = {"n": 0}

        async def sleep(_):
            ticks["n"] += 1
            if ticks["n"] > 1:
                raise asyncio.CancelledError
        monkeypatch.setattr(asyncio, "sleep", sleep)
        try:
            await _kyc_erasure_retry()
        except asyncio.CancelledError:
            pass
        assert len(calls) == expected


def test_the_retry_sweep_is_scheduled_behind_the_scheduler_gate():
    import inspect
    import app.main as main
    src = inspect.getsource(main)
    gate = src[src.index("if redis_enabled() or settings.run_schedulers:"):src.index("# The provenance relay is NOT behind that gate.")]
    assert "_kyc_erasure_retry()" in gate
    assert src.count("_asyncio.create_task(_kyc_erasure_retry())") == 1
