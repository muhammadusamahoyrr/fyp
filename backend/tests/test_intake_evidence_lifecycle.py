"""Evidence: quotas, bounded reads, download, delete, and the orphan window.

Upload was the only operation. There was no way to read a file back and no way
to remove one — the UI's ✕ filtered a React array, so the file stayed on disk
and on the intake for ever while the client believed it was gone.

Four other gaps sat behind it: the whole request body was buffered BEFORE the
size check (so refusing a 2 GB upload first held 2 GB in memory), there was no
per-intake ceiling of any kind, a failed record write left the bytes orphaned,
and a converted intake still accepted uploads that could no longer reach the
analysis they were meant for.
"""
from __future__ import annotations

import io
import secrets
from datetime import datetime, timedelta, timezone

import pytest

from app.core.exceptions import AppValidationError, ConflictError, NotFoundError
from app.services import intake_service

pytestmark = pytest.mark.integration


class FakeUpload:
    """Enough of Starlette's UploadFile for this service: chunked `read`."""

    def __init__(self, content: bytes, filename="evidence.pdf",
                 content_type="application/pdf"):
        self._buf = io.BytesIO(content)
        self.filename = filename
        self.content_type = content_type

    async def read(self, size: int = -1) -> bytes:
        return self._buf.read(size if size and size > 0 else None)


def _pdf(size: int) -> bytes:
    """A payload whose first bytes sniff as a PDF, padded to `size`."""
    head = b"%PDF-1.4\n"
    return head + b"0" * max(0, size - len(head))


@pytest.fixture
async def intake(mongo):
    from app.db.collections import get_intakes_col, get_ocr_revisions_col, get_users_col

    tag = secrets.token_hex(4)
    client_id, token = f"EV-C-{tag}", f"EV-T-{tag}"
    now = datetime.now(timezone.utc)

    await get_users_col().insert_one({
        "_id": client_id, "role": "client", "is_active": True,
        "email": f"ev-{tag}@test.invalid", "full_name": "Evidence Client",
        "province": "punjab", "created_at": now,
    })
    await get_intakes_col().insert_one({
        "_id": f"EV-I-{tag}", "session_token": token, "client_id": client_id,
        "current_step": 3, "completed": False, "case_id": None,
        "step1": {"province": "punjab"},
        "step3": {"incident_description": "A tenancy dispute."},
        "clarification_qa": [], "evidence_files": [],
        "created_at": now, "updated_at": now,
    })

    yield {"client_id": client_id, "token": token, "tag": tag}

    await get_users_col().delete_many({"_id": client_id})
    await get_intakes_col().delete_many({"session_token": token})
    await get_ocr_revisions_col().delete_many({"owner_id": client_id})


async def _upload(intake, size=2048, **kw):
    return await intake_service.upload_evidence(
        intake["token"], intake["client_id"], FakeUpload(_pdf(size), **kw))


async def test_detected_mime_is_stored_and_returned_not_the_claimed_header(intake):
    result = await _upload(intake, content_type="image/png")
    from app.db.collections import get_intakes_col
    stored = await get_intakes_col().find_one({"session_token": intake["token"]})
    assert result["content_type"] == "application/pdf"
    assert stored["evidence_files"][0]["content_type"] == "application/pdf"

    # Even a legacy/tampered metadata value cannot steer the response header.
    await get_intakes_col().update_one(
        {"session_token": intake["token"],
         "evidence_files.file_id": result["file_id"]},
        {"$set": {"evidence_files.$.content_type": "text/html"}},
    )
    _, _, served = await intake_service.get_evidence_file(
        intake["token"], intake["client_id"], result["file_id"]
    )
    assert served == "application/pdf"


async def test_quota_guard_is_atomic_under_concurrent_appends(intake):
    import asyncio
    repo = intake_service.intake_repo
    results = await asyncio.gather(*[
        repo.add_evidence_file(
            intake["token"], {"file_id": f"r{i}", "size": 1}, 12, 40
        )
        for i in range(13)
    ])
    assert sum(bool(x) for x in results) == 12


async def test_stale_conversion_worker_cannot_write_or_release_new_owner(intake):
    from app.db.collections import get_intakes_col
    repo = intake_service.intake_repo
    first_epoch = await repo.claim_conversion(
        intake["token"], timedelta(minutes=10), "worker-a"
    )
    assert first_epoch == 1
    await get_intakes_col().update_one(
        {"session_token": intake["token"]},
        {"$set": {"conversion_claim_expires_at": datetime.now(timezone.utc) - timedelta(seconds=1)}},
    )
    second_epoch = await repo.claim_conversion(
        intake["token"], timedelta(minutes=10), "worker-b"
    )
    assert second_epoch == 2
    assert not await repo.attach_case(intake["token"], "stale-case", "worker-a")
    assert not await repo.release_conversion(intake["token"], "worker-a")
    assert not await repo.mark_completed(
        intake["token"], "stale-case", "worker-a"
    )
    assert await repo.attach_case(intake["token"], "real-case", "worker-b")


async def test_readable_upload_text_is_supplied_to_intake_analysis(monkeypatch):
    """A FULLY read file is still `readable`, and its text still reaches the prompt.

    Patches `extraction_runner.extract_many`, which is where extraction now
    happens. The previous version of this test patched
    `document_tools._read_file`; that seam is no longer on the intake path, so
    left alone it would have gone on passing while testing nothing.
    """
    from app.ai import extraction_runner
    from app.ai.extraction import COMPLETE, OUTCOME_SUCCEEDED, ExtractionResult

    async def readable(files, **kw):
        return {f["file_id"]: (
            ExtractionResult(outcome=OUTCOME_SUCCEEDED, completeness=COMPLETE,
                             pages_total=1, pages_attempted=1, pages_with_text=1),
            "Rent agreement dated 1 January.",
        ) for f in files}

    monkeypatch.setattr(extraction_runner, "extract_many", readable)
    path = intake_service._EVIDENCE_DIR / "owned.pdf"
    text, statuses = await intake_service._extract_intake_evidence([
        {"file_id": "f-owned", "path": str(path)}
    ])

    assert "Rent agreement" in text
    assert "WARNING" not in text, "a fully read file must carry no warning"
    assert len(statuses) == 1
    assert statuses[0]["file_id"] == "f-owned"
    assert statuses[0]["status"] == "readable"
    assert statuses[0]["completeness"] == COMPLETE
    assert statuses[0]["truncated"] is False
    assert statuses[0]["extractor_version"]


async def test_out_of_tree_evidence_is_never_read_for_analysis(monkeypatch, tmp_path):
    """Containment is decided BEFORE extraction is asked about the file.

    Asserts on the paths actually handed to the runner, rather than on a flag
    set by a function that is no longer called — the latter cannot fail.
    """
    from app.ai import extraction_runner

    seen = []

    async def spy(files, **kw):
        seen.extend(f["path"] for f in files)
        return {}

    monkeypatch.setattr(extraction_runner, "extract_many", spy)
    text, statuses = await intake_service._extract_intake_evidence([
        {"file_id": "escape", "path": str(tmp_path / "outside.pdf")}
    ])

    assert text == ""
    assert statuses[0]["status"] == "invalid_path"
    assert seen == [], f"an out-of-tree path reached the extractor: {seen}"


# ── the bounded read ────────────────────────────────────────────────────────

async def test_an_oversized_file_is_refused(intake):
    with pytest.raises(AppValidationError) as exc:
        await _upload(intake, size=intake_service._MAX_EVIDENCE_SIZE + 1024)
    assert "too large" in str(exc.value.detail).lower()


async def test_an_oversized_file_is_not_fully_buffered_first(intake):
    """`await file.read()` held the ENTIRE body before checking the size.

    Asserted by counting how much was actually read: the reader must stop about
    one chunk past the limit, not consume the whole payload.
    """
    oversize = intake_service._MAX_EVIDENCE_SIZE * 3
    upload = FakeUpload(_pdf(oversize))

    with pytest.raises(AppValidationError):
        await intake_service.upload_evidence(
            intake["token"], intake["client_id"], upload)

    consumed = upload._buf.tell()
    assert consumed <= intake_service._MAX_EVIDENCE_SIZE + intake_service._EVIDENCE_CHUNK, (
        f"read {consumed} bytes to reject a file over a "
        f"{intake_service._MAX_EVIDENCE_SIZE}-byte limit"
    )


async def test_a_file_within_the_limit_is_stored(intake):
    result = await _upload(intake, size=4096)
    assert result["file_id"]
    assert result["size"] == 4096


# ── per-intake quotas ───────────────────────────────────────────────────────

async def test_the_file_count_is_capped(intake):
    """Only a per-FILE limit existed, so one intake could hold unlimited files."""
    from app.db.collections import get_intakes_col

    padding = [
        {"file_id": f"f{i}", "filename": "x.pdf", "size": 1024,
         "content_type": "application/pdf", "path": "/nowhere"}
        for i in range(intake_service._MAX_EVIDENCE_FILES)
    ]
    await get_intakes_col().update_one(
        {"session_token": intake["token"]},
        {"$set": {"evidence_files": padding}})

    with pytest.raises(AppValidationError) as exc:
        await _upload(intake)
    assert "at most" in str(exc.value.detail)


async def test_the_total_size_is_capped(intake):
    from app.db.collections import get_intakes_col

    await get_intakes_col().update_one(
        {"session_token": intake["token"]},
        {"$set": {"evidence_files": [{
            "file_id": "big", "filename": "big.pdf",
            "size": intake_service._MAX_EVIDENCE_TOTAL - 512,
            "content_type": "application/pdf", "path": "/nowhere"}]}})

    with pytest.raises(AppValidationError) as exc:
        await _upload(intake, size=4096)
    assert "total" in str(exc.value.detail).lower()


# ── a converted intake takes no more evidence ──────────────────────────────

async def test_a_completed_intake_refuses_uploads(intake):
    """`save_step` always refused a completed intake; upload did not.

    A file attached after conversion arrives too late for the analysis it was
    uploaded for, and nothing said so.
    """
    from app.db.collections import get_intakes_col

    await get_intakes_col().update_one(
        {"session_token": intake["token"]}, {"$set": {"completed": True}})

    with pytest.raises(AppValidationError) as exc:
        await _upload(intake)
    assert "already been converted" in str(exc.value.detail)


# ── download ────────────────────────────────────────────────────────────────

async def test_an_uploaded_file_can_be_read_back(intake):
    """There was no way to do this at all."""
    up = await _upload(intake, size=1500)
    path, filename, mime = await intake_service.get_evidence_file(
        intake["token"], intake["client_id"], up["file_id"])

    assert path.is_file()
    assert path.stat().st_size == 1500
    assert filename == "evidence.pdf"
    assert mime == "application/pdf"


async def test_another_client_cannot_download_it(intake):
    up = await _upload(intake)
    with pytest.raises(NotFoundError):
        await intake_service.get_evidence_file(
            intake["token"], "EV-STRANGER", up["file_id"])


async def test_an_unknown_file_id_is_not_found(intake):
    await _upload(intake)
    with pytest.raises(NotFoundError):
        await intake_service.get_evidence_file(
            intake["token"], intake["client_id"], "no-such-file")


async def test_a_record_pointing_outside_the_evidence_root_is_refused(intake):
    """`file_id` arrives from a URL; only the stored path decides the bytes.

    A record whose path escapes the evidence directory is corrupt, not a file to
    serve — so it is refused rather than read.
    """
    from app.db.collections import get_intakes_col

    await get_intakes_col().update_one(
        {"session_token": intake["token"]},
        {"$set": {"evidence_files": [{
            "file_id": "escape", "filename": "passwd", "size": 10,
            "content_type": "text/plain", "path": "/etc/passwd"}]}})

    with pytest.raises(NotFoundError):
        await intake_service.get_evidence_file(
            intake["token"], intake["client_id"], "escape")


# ── delete ──────────────────────────────────────────────────────────────────

async def test_deleting_removes_both_the_record_and_the_file(intake):
    """The ✕ filtered a React array. The file stayed on disk for ever."""
    up = await _upload(intake)
    path, _, _ = await intake_service.get_evidence_file(
        intake["token"], intake["client_id"], up["file_id"])
    assert path.is_file()
    from app.db.collections import get_ocr_revisions_col
    await get_ocr_revisions_col().insert_one({
        "_id": f"ocr-{intake['tag']}",
        "owner_id": intake["client_id"],
        "file_id": up["file_id"],
        "text": "derived sensitive text",
    })
    from app.db.collections import get_intakes_col
    await get_intakes_col().update_one(
        {"session_token": intake["token"]},
        {"$set": {"evidence_review_state": [{
            "file_id": up["file_id"], "ocr_review_required": True,
        }]}}
    )

    await intake_service.delete_evidence_file(
        intake["token"], intake["client_id"], up["file_id"])

    assert not path.exists(), "the record went but the bytes stayed"
    assert await get_ocr_revisions_col().find_one({
        "_id": f"ocr-{intake['tag']}"
    }) is None, "the source went but its OCR text stayed"
    detail = await intake_service.get_intake(intake["token"], intake["client_id"])
    assert detail["evidence_files"] == []
    assert detail["ocr_review_required"] is False, (
        "a deleted file left the resumed intake trapped in OCR review"
    )


async def test_conversion_that_wins_the_race_preserves_source_and_reviewed_ocr(
    intake,
):
    """A refused delete must not erase the confirmation conversion will use."""
    from app.db.collections import get_ocr_revisions_col

    up = await _upload(intake)
    path, _, _ = await intake_service.get_evidence_file(
        intake["token"], intake["client_id"], up["file_id"]
    )
    revision_id = f"ocr-race-{intake['tag']}"
    await get_ocr_revisions_col().insert_one({
        "_id": revision_id,
        "owner_id": intake["client_id"],
        "file_id": up["file_id"],
        "text": "reviewed evidence",
    })
    epoch = await intake_service.intake_repo.claim_conversion(
        intake["token"], timedelta(minutes=10), "conversion-won"
    )
    assert epoch == 1

    with pytest.raises(ConflictError):
        await intake_service.delete_evidence_file(
            intake["token"], intake["client_id"], up["file_id"]
        )

    assert path.is_file()
    assert await get_ocr_revisions_col().find_one({"_id": revision_id})
    detail = await intake_service.get_intake(
        intake["token"], intake["client_id"]
    )
    assert [row["file_id"] for row in detail["evidence_files"]] == [up["file_id"]]


async def test_ocr_delete_failure_releases_the_fence(intake, monkeypatch):
    """A transient derived-store failure cannot wedge conversion forever."""
    from app.repositories import ocr_revision_repo as module

    up = await _upload(intake)

    class BrokenOcrRepo:
        async def delete_for_file(self, **_kwargs):
            raise RuntimeError("derived store unavailable")

    monkeypatch.setattr(module, "ocr_revision_repo", lambda: BrokenOcrRepo())
    with pytest.raises(RuntimeError, match="derived store unavailable"):
        await intake_service.delete_evidence_file(
            intake["token"], intake["client_id"], up["file_id"]
        )

    epoch = await intake_service.intake_repo.claim_conversion(
        intake["token"], timedelta(minutes=10), "conversion-after-failure"
    )
    assert epoch == 1


async def test_deleting_frees_the_quota(intake):
    """A removed file that still counted would make the cap unusable."""
    up = await _upload(intake, size=8192)
    await intake_service.delete_evidence_file(
        intake["token"], intake["client_id"], up["file_id"])

    again = await _upload(intake, size=8192)
    assert again["file_id"] != up["file_id"]


async def test_another_client_cannot_delete_it(intake):
    up = await _upload(intake)
    with pytest.raises(NotFoundError):
        await intake_service.delete_evidence_file(
            intake["token"], "EV-STRANGER", up["file_id"])

    detail = await intake_service.get_intake(intake["token"], intake["client_id"])
    assert len(detail["evidence_files"]) == 1


async def test_evidence_cannot_be_deleted_after_conversion(intake):
    """Once analysed, it is part of the case record."""
    from app.db.collections import get_intakes_col

    up = await _upload(intake)
    await get_intakes_col().update_one(
        {"session_token": intake["token"]}, {"$set": {"completed": True}})

    with pytest.raises(AppValidationError):
        await intake_service.delete_evidence_file(
            intake["token"], intake["client_id"], up["file_id"])


async def test_deleting_twice_is_not_found_the_second_time(intake):
    up = await _upload(intake)
    await intake_service.delete_evidence_file(
        intake["token"], intake["client_id"], up["file_id"])
    with pytest.raises(NotFoundError):
        await intake_service.delete_evidence_file(
            intake["token"], intake["client_id"], up["file_id"])


# ── the orphan window ───────────────────────────────────────────────────────

async def test_a_failed_record_write_leaves_no_file_behind(intake, monkeypatch):
    """The bytes land on disk BEFORE the record exists.

    Without cleanup the file is unreachable by the client, uncounted by the
    quota, and invisible to any later census — a permanent leak from a request
    that already failed.
    """
    from pathlib import Path

    before = set(Path(intake_service._EVIDENCE_DIR / intake["token"]).glob("*")) \
        if (intake_service._EVIDENCE_DIR / intake["token"]).exists() else set()

    async def boom(token, meta, max_files, max_total):
        raise RuntimeError("record write failed")

    monkeypatch.setattr(intake_service.intake_repo, "add_evidence_file", boom)

    with pytest.raises(RuntimeError):
        await _upload(intake)

    after = set(Path(intake_service._EVIDENCE_DIR / intake["token"]).glob("*")) \
        if (intake_service._EVIDENCE_DIR / intake["token"]).exists() else set()
    assert after == before, f"orphaned file(s) left behind: {after - before}"
