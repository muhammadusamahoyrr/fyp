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
