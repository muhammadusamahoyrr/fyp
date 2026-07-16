"""Verifiable-POA tests — the public point-of-use check.

Two things must hold: the status shown is the LIVE status (a lapsed POA never reads
as active, even before the nightly sweep), and the public payload leaks no CNIC.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.core.constants import POAStatus
from app.services import overseas_service as ov


# ── pure live-status logic ───────────────────────────────────────────────────

def test_live_status_reports_expired_when_expiry_passed():
    past = datetime.now(timezone.utc) - timedelta(days=1)
    poa = {"status": POAStatus.ACTIVE.value, "expiry_date": past}
    assert ov._live_status(poa) == POAStatus.EXPIRED.value


def test_live_status_active_when_not_expired():
    future = datetime.now(timezone.utc) + timedelta(days=30)
    poa = {"status": POAStatus.ACTIVE.value, "expiry_date": future}
    assert ov._live_status(poa) == POAStatus.ACTIVE.value


def test_live_status_leaves_revoked_alone():
    poa = {"status": POAStatus.REVOKED.value, "expiry_date": None}
    assert ov._live_status(poa) == POAStatus.REVOKED.value


def test_verify_url_uses_the_token():
    assert ov._verify_url("abc123").endswith("/verify/abc123")
    assert ov._verify_url("") == ""


def test_verify_qr_is_valid_svg_encoding_the_link():
    """The QR is rendered by reportlab (no QR dependency). It must be real SVG with
    enough modules to be a scannable code, not just a caption."""
    svg = ov.verify_qr_svg("token-xyz")
    assert svg.lstrip().startswith("<")
    assert "svg" in svg[:300].lower()
    # a real QR is made of many rects/paths — a trivial output would be tiny
    assert len(svg) > 2000


def test_poa_pdf_embeds_the_verify_link():
    """The generated POA carries the verify URL (and its QR) so a counterparty can
    scan a PRINTED document. The SHA-256 is taken over this QR-bearing PDF."""
    from pypdf import PdfReader

    from app.services.pdf_generator import power_of_attorney

    url = "http://localhost:3000/verify/EMBEDTEST"
    path = power_of_attorney("qr_unit_test", {
        "poa_type": "special", "principal_name": "Ali", "attorney_name": "Bilal",
        "subject": "House 5", "powers": ["To sell"], "verify_url": url,
    })
    try:
        text = "\n".join(pg.extract_text() or "" for pg in PdfReader(str(path)).pages)
        assert "EMBEDTEST" in text
    finally:
        path.unlink(missing_ok=True)


# ── public verify by token (needs Mongo) ─────────────────────────────────────

pytestmark_note = "integration tests need MongoDB"


@pytest.mark.integration
class TestVerifyByToken:
    @pytest.fixture
    async def poa_doc(self, mongo):
        """Insert a POA directly (skip PDF generation) and clean up."""
        import secrets

        from app.db.collections import get_poas_col

        token = "tok_" + secrets.token_hex(6)
        doc = {
            "_id": "poa_" + secrets.token_hex(6),
            "verify_token": token,
            "principal_id": "principal-1",
            "principal_snapshot": {"id": "principal-1", "name": "Ali Khan"},
            "attorney_name": "Bilal Khan",
            "attorney_relation": "brother",
            "principal_cnic_masked": "35202-XXXXXXX-1",
            "principal_cnic_encrypted": "ENCRYPTED_BLOB_SHOULD_NEVER_LEAK",
            "poa_type": "special",
            "subject": "House 12, DHA Phase 5, Lahore",
            "powers": ["sell", "register"],
            "status": POAStatus.ACTIVE.value,
            "issue_date": "01 July 2026",
            "expiry_date": datetime.now(timezone.utc) + timedelta(days=180),
            "revoked_at": None,
            "document_sha256": "a" * 64,
            "created_at": datetime.now(timezone.utc),
        }
        await get_poas_col().insert_one(doc)
        yield doc
        await get_poas_col().delete_one({"_id": doc["_id"]})

    async def test_active_poa_verifies_with_scope(self, poa_doc):
        r = await ov.verify_by_token(poa_doc["verify_token"])
        assert r["found"] is True
        assert r["is_active"] is True
        assert r["status"] == "active"
        assert r["subject"] == "House 12, DHA Phase 5, Lahore"
        # Powers are shown as readable labels, and the tamper-hash is exposed.
        assert any("sell" in p.lower() for p in r["powers"])
        assert r["document_sha256"] == "a" * 64

    async def test_verify_never_leaks_cnic(self, poa_doc):
        r = await ov.verify_by_token(poa_doc["verify_token"])
        blob = str(r)
        assert "ENCRYPTED_BLOB_SHOULD_NEVER_LEAK" not in blob
        assert "cnic" not in blob.lower()

    async def test_revoked_poa_reads_as_revoked(self, poa_doc, mongo):
        from app.db.collections import get_poas_col
        await get_poas_col().update_one(
            {"_id": poa_doc["_id"]},
            {"$set": {"status": POAStatus.REVOKED.value,
                      "revoked_at": datetime.now(timezone.utc)}},
        )
        r = await ov.verify_by_token(poa_doc["verify_token"])
        assert r["status"] == "revoked"
        assert r["is_active"] is False
        assert r["revoked_at"] is not None

    async def test_lapsed_poa_reads_as_expired_even_if_not_swept(self, poa_doc, mongo):
        """The DB still says active; the verify must show expired anyway."""
        from app.db.collections import get_poas_col
        await get_poas_col().update_one(
            {"_id": poa_doc["_id"]},
            {"$set": {"expiry_date": datetime.now(timezone.utc) - timedelta(days=2)}},
        )
        r = await ov.verify_by_token(poa_doc["verify_token"])
        assert r["status"] == "expired"
        assert r["is_active"] is False

    async def test_unknown_token_is_not_found(self, mongo):
        r = await ov.verify_by_token("tok_does_not_exist")
        assert r["found"] is False

    async def test_empty_token_is_not_found(self, mongo):
        r = await ov.verify_by_token("")
        assert r["found"] is False
