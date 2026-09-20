"""A legacy .doc is kept, downloadable, and honestly labelled at upload time.

Its OLE2 magic has always been allow-listed and no extractor has ever been able
to read it, so it uploaded silently and the client found out at the analysis
screen — after they had finished the questionnaire — that it had contributed
nothing.

Refusing the upload would be the wrong fix. The file is still their evidence and
their lawyer can still open it; throwing it away to avoid an awkward message
loses something real. So it is stored deliberately, and the limitation is stated
at the one moment the client can cheaply act on it.
"""
from __future__ import annotations

import io
import secrets
from datetime import datetime, timezone

import pytest

from app.services import intake_service

pytestmark = pytest.mark.integration

#: OLE2 compound-document header — what `detect_mime` keys on for `.doc`.
_OLE2 = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


class FakeUpload:
    def __init__(self, content: bytes, filename: str, content_type: str):
        self._buf = io.BytesIO(content)
        self.filename = filename
        self.content_type = content_type

    async def read(self, size: int = -1) -> bytes:
        return self._buf.read(size if size and size > 0 else None)


@pytest.fixture
async def intake(mongo):
    from app.db.collections import get_intakes_col, get_users_col

    tag = secrets.token_hex(4)
    client_id, token = f"LD-C-{tag}", f"LD-T-{tag}"
    now = datetime.now(timezone.utc)

    await get_users_col().insert_one({
        "_id": client_id, "role": "client", "is_active": True,
        "email": f"ld-{tag}@test.invalid", "full_name": "Legacy Client",
        "province": "punjab", "created_at": now,
    })
    await get_intakes_col().insert_one({
        "_id": f"LD-I-{tag}", "session_token": token, "client_id": client_id,
        "current_step": 3, "completed": False, "case_id": None,
        "step1": {"province": "punjab"},
        "step3": {"incident_description": "A tenancy dispute."},
        "clarification_qa": [], "evidence_files": [],
        "created_at": now, "updated_at": now,
    })

    yield {"client_id": client_id, "token": token}

    await get_users_col().delete_many({"_id": client_id})
    await get_intakes_col().delete_many({"session_token": token})


async def _upload(intake, content: bytes, name: str, mime: str) -> dict:
    return await intake_service.upload_evidence(
        intake["token"], intake["client_id"], FakeUpload(content, name, mime))


async def test_a_legacy_doc_is_still_accepted_and_stored(intake):
    """Preserved deliberately — it is the client's evidence either way."""
    result = await _upload(intake, _OLE2 + b"\x00" * 2048,
                           "affidavit.doc", "application/msword")

    assert result["file_id"]
    assert result["content_type"] == "application/msword"


async def test_the_client_is_told_at_upload_that_it_will_not_be_analysed(intake):
    result = await _upload(intake, _OLE2 + b"\x00" * 2048,
                           "affidavit.doc", "application/msword")

    assert result["analysis_support"] == "storage_only"
    notice = result["notice"]
    assert ".docx" in notice and "PDF" in notice, (
        "the notice must say what to upload instead")
    assert "downloaded" in notice, (
        "the client must be told their file was not thrown away")


async def test_a_stored_legacy_doc_remains_downloadable(intake):
    """The half that makes storing it honest rather than a consolation."""
    result = await _upload(intake, _OLE2 + b"\x00" * 2048,
                           "affidavit.doc", "application/msword")

    path, filename, mime = await intake_service.get_evidence_file(
        intake["token"], intake["client_id"], result["file_id"])

    assert path.is_file()
    assert filename == "affidavit.doc"
    assert mime == "application/msword"


async def test_a_readable_format_carries_no_notice(intake):
    """The control: the warning must not appear on files that are fine."""
    result = await _upload(intake, b"%PDF-1.4\n" + b"0" * 1024,
                           "notice.pdf", "application/pdf")

    assert "notice" not in result
    assert "analysis_support" not in result


async def test_a_legacy_doc_is_reported_unreadable_by_the_extractor(intake):
    """The upload-time notice and the analysis-time status must agree.

    Two places telling the client different things about the same file is how
    the original defect felt from the outside.
    """
    from app.ai.extraction import ERR_LEGACY_DOC_FORMAT, extract_file

    result = await _upload(intake, _OLE2 + b"\x00" * 2048,
                           "affidavit.doc", "application/msword")
    path, _, _ = await intake_service.get_evidence_file(
        intake["token"], intake["client_id"], result["file_id"])

    extracted = extract_file(str(path))

    assert extracted.error_code == ERR_LEGACY_DOC_FORMAT
    assert extracted.text == ""
