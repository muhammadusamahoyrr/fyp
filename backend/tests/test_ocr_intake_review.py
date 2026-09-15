"""Product bridge and review gate for local English OCR.

No provider and no real database: real intake/OCR service and repository code
run against the same collection fake used by Milestone 3A.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from support.fake_mongo import FakeCollection  # noqa: E402

from app.ai import extraction as E  # noqa: E402
from app.ai import ocr as O  # noqa: E402


@pytest.fixture
def repo(monkeypatch):
    from app.repositories import ocr_revision_repo as module
    from app.services import ocr_service

    collection = FakeCollection()
    instance = module.OcrRevisionRepository()
    monkeypatch.setattr(type(instance), "col", property(lambda self: collection))
    monkeypatch.setattr(module, "_repo", instance)
    monkeypatch.setattr(module, "ocr_revision_repo", lambda: instance)
    monkeypatch.setattr(ocr_service, "ocr_revision_repo", lambda: instance)
    instance.collection = collection
    return instance


def _page(text="OCR read 1000 rupees"):
    return O.OcrPageResult(
        page_number=1,
        status=O.OCR_COMPLETED_UNCONFIRMED,
        text=text,
        text_sha256=O.sha256_of(text),
        engine="tesseract",
        engine_version="5.4.0",
    )


def _scanned_result(page):
    return E.ExtractionResult(
        outcome=E.OUTCOME_SUCCEEDED,
        completeness=E.NONE,
        error_code=E.ERR_NO_TEXT_LAYER,
        pages_total=1,
        pages_attempted=1,
        pages_with_text=0,
        page_reports=[E.PageReport(1, E.PAGE_NO_TEXT_FOUND)],
        ocr_pages=[page],
    )


async def _async_value(value):
    return value


@pytest.mark.asyncio
async def test_confirmation_keeps_engine_text_and_adds_separate_human_text(
    tmp_path, repo, monkeypatch
):
    from app.core.config import settings
    from app.services import ocr_service

    monkeypatch.setattr(settings, "english_ocr_enabled", True)
    path = tmp_path / "scan.pdf"
    path.write_bytes(b"current source bytes")
    page = _page()
    await ocr_service.run_ocr_for_file(
        owner_id="client-a", session_id="intake-a", file_id="file-a",
        path=str(path), content_type="application/pdf",
        extraction_result=_scanned_result(page), ocr_pages=[page],
    )
    before = dict(repo.collection.docs[0])

    review = await ocr_service.review_pages_for_file(
        owner_id="client-a", file_id="file-a", path=str(path))
    corrected = "The fine is 10,000 rupees"
    outcome = await ocr_service.confirm_page(
        owner_id="client-a", file_id="file-a",
        revision_id=review[0]["revision_id"], path=str(path),
        source_sha256=review[0]["source_sha256"],
        ocr_text_sha256=review[0]["text_sha256"],
        confirmed_text=corrected,
    )

    stored = repo.collection.docs[0]
    assert outcome["confirmed"] is True
    assert stored["text"] == before["text"]
    assert stored["text_sha256"] == before["text_sha256"]
    assert stored["confirmed_text"] == corrected
    assert stored["confirmed_text_sha256"] == hashlib.sha256(
        corrected.encode("utf-8")).hexdigest()


@pytest.mark.asyncio
async def test_a_stale_preview_cannot_confirm_replaced_source(
    tmp_path, repo, monkeypatch
):
    from app.core.config import settings
    from app.core.exceptions import ConflictError
    from app.services import ocr_service

    monkeypatch.setattr(settings, "english_ocr_enabled", True)
    path = tmp_path / "scan.pdf"
    path.write_bytes(b"version one")
    page = _page()
    await ocr_service.run_ocr_for_file(
        owner_id="client-a", session_id="intake-a", file_id="file-a",
        path=str(path), content_type="application/pdf",
        extraction_result=_scanned_result(page), ocr_pages=[page],
    )
    review = await ocr_service.review_pages_for_file(
        owner_id="client-a", file_id="file-a", path=str(path))
    path.write_bytes(b"version two")

    with pytest.raises(ConflictError):
        await ocr_service.confirm_page(
            owner_id="client-a", file_id="file-a",
            revision_id=review[0]["revision_id"], path=str(path),
            source_sha256=review[0]["source_sha256"],
            ocr_text_sha256=review[0]["text_sha256"],
            confirmed_text=review[0]["text"],
        )


@pytest.mark.asyncio
async def test_review_and_prompt_use_the_checkpointed_revision_not_newest_guess(
    tmp_path, repo, monkeypatch
):
    from app.core.config import settings
    from app.services import ocr_service

    monkeypatch.setattr(settings, "english_ocr_enabled", True)
    path = tmp_path / "scan.pdf"
    path.write_bytes(b"one stable source")
    source = O.source_digest(path)

    first, _ = await repo.create_if_absent(
        owner_id="client-a", session_id="intake-a", file_id="file-a",
        page_number=1, source_sha256=source,
        text="First engine text", text_sha256=O.sha256_of("First engine text"),
        engine="engine-a", engine_version="1", language="eng",
        config_version="one", status=O.OCR_COMPLETED_UNCONFIRMED,
    )
    second, _ = await repo.create_if_absent(
        owner_id="client-a", session_id="intake-a", file_id="file-a",
        page_number=1, source_sha256=source,
        text="Competing text", text_sha256=O.sha256_of("Competing text"),
        engine="engine-b", engine_version="2", language="eng",
        config_version="two", status=O.OCR_COMPLETED_UNCONFIRMED,
    )
    review = await ocr_service.review_pages_for_file(
        owner_id="client-a", file_id="file-a", path=str(path),
        revision_ids=[first["_id"]],
    )
    assert [row["revision_id"] for row in review] == [first["_id"]]
    assert second["_id"] not in {row["revision_id"] for row in review}

    await ocr_service.confirm_page(
        owner_id="client-a", file_id="file-a", revision_id=first["_id"],
        path=str(path), source_sha256=source,
        ocr_text_sha256=first["text_sha256"],
        confirmed_text="Human-confirmed first reading",
    )
    text, complete, pages, page_numbers = await ocr_service.confirmed_text_for_file(
        owner_id="client-a", file_id="file-a", source_sha256=source,
        revision_ids=[first["_id"]],
    )
    assert (text, complete, pages) == ("Human-confirmed first reading", True, 1)
    assert page_numbers == {1}


@pytest.mark.asyncio
async def test_a_missing_checkpointed_revision_can_never_be_all_confirmed(
    tmp_path, repo, monkeypatch
):
    from app.core.config import settings
    from app.core.exceptions import ConflictError
    from app.services import ocr_service

    monkeypatch.setattr(settings, "english_ocr_enabled", True)
    path = tmp_path / "scan.pdf"
    path.write_bytes(b"stable source")
    page = _page()
    await ocr_service.run_ocr_for_file(
        owner_id="client-a", session_id="intake-a", file_id="file-a",
        path=str(path), content_type="application/pdf",
        extraction_result=_scanned_result(page), ocr_pages=[page],
    )
    review = await ocr_service.review_pages_for_file(
        owner_id="client-a", file_id="file-a", path=str(path))
    await ocr_service.confirm_page(
        owner_id="client-a", file_id="file-a",
        revision_id=review[0]["revision_id"], path=str(path),
        source_sha256=review[0]["source_sha256"],
        ocr_text_sha256=review[0]["text_sha256"],
        confirmed_text="Confirmed page one",
    )
    pinned = [review[0]["revision_id"], "revision-that-is-gone"]

    text, complete, pages, page_numbers = await ocr_service.confirmed_text_for_file(
        owner_id="client-a", file_id="file-a",
        source_sha256=review[0]["source_sha256"], revision_ids=pinned,
    )
    assert (text, complete, pages) == ("", False, 2)
    assert page_numbers == set()
    with pytest.raises(ConflictError):
        await ocr_service.review_pages_for_file(
            owner_id="client-a", file_id="file-a", path=str(path),
            revision_ids=pinned,
        )


@pytest.mark.asyncio
async def test_prompt_revalidates_the_confirmed_text_hash(
    tmp_path, repo, monkeypatch
):
    """A later bad write cannot alter what the human confirmation admits."""
    from app.core.config import settings
    from app.services import ocr_service

    monkeypatch.setattr(settings, "english_ocr_enabled", True)
    path = tmp_path / "scan.pdf"
    path.write_bytes(b"stable source")
    page = _page()
    await ocr_service.run_ocr_for_file(
        owner_id="client-a", session_id="intake-a", file_id="file-a",
        path=str(path), content_type="application/pdf",
        extraction_result=_scanned_result(page), ocr_pages=[page],
    )
    review = await ocr_service.review_pages_for_file(
        owner_id="client-a", file_id="file-a", path=str(path))
    await ocr_service.confirm_page(
        owner_id="client-a", file_id="file-a",
        revision_id=review[0]["revision_id"], path=str(path),
        source_sha256=review[0]["source_sha256"],
        ocr_text_sha256=review[0]["text_sha256"],
        confirmed_text="The confirmed amount is 10,000 rupees",
    )
    # Simulate a future buggy/manual update that changes the value but not the
    # hash. Prompt assembly must compare them again rather than trust a flag.
    repo.collection.docs[0]["confirmed_text"] = "The amount is 1,000,000 rupees"

    text, complete, pages, page_numbers = await ocr_service.confirmed_text_for_file(
        owner_id="client-a", file_id="file-a",
        source_sha256=review[0]["source_sha256"],
        revision_ids=[review[0]["revision_id"]],
    )
    assert text == ""
    assert complete is False
    assert pages == 1
    assert page_numbers == set()


@pytest.mark.asyncio
async def test_a_tampered_confirmation_is_not_accepted_as_an_idempotent_replay(
    tmp_path, repo, monkeypatch
):
    from app.core.config import settings
    from app.core.exceptions import ConflictError
    from app.services import ocr_service

    monkeypatch.setattr(settings, "english_ocr_enabled", True)
    path = tmp_path / "scan.pdf"
    path.write_bytes(b"stable source")
    page = _page()
    await ocr_service.run_ocr_for_file(
        owner_id="client-a", session_id="intake-a", file_id="file-a",
        path=str(path), content_type="application/pdf",
        extraction_result=_scanned_result(page), ocr_pages=[page],
    )
    review = await ocr_service.review_pages_for_file(
        owner_id="client-a", file_id="file-a", path=str(path)
    )
    corrected = "The confirmed amount is 10,000 rupees"
    await ocr_service.confirm_page(
        owner_id="client-a", file_id="file-a",
        revision_id=review[0]["revision_id"], path=str(path),
        source_sha256=review[0]["source_sha256"],
        ocr_text_sha256=review[0]["text_sha256"],
        confirmed_text=corrected,
    )
    repo.collection.docs[0]["confirmed_text"] = "tampered after confirmation"

    with pytest.raises(ConflictError):
        await ocr_service.confirm_page(
            owner_id="client-a", file_id="file-a",
            revision_id=review[0]["revision_id"], path=str(path),
            source_sha256=review[0]["source_sha256"],
            ocr_text_sha256=review[0]["text_sha256"],
            confirmed_text=corrected,
        )


@pytest.mark.asyncio
async def test_intake_refuses_a_revision_outside_its_active_checkpoint(
    tmp_path, monkeypatch
):
    from app.core.exceptions import NotFoundError
    from app.services import intake_service as intake
    from app.services import ocr_service

    path = tmp_path / "scan.pdf"
    path.write_bytes(b"source")
    monkeypatch.setattr(
        intake,
        "_find_evidence",
        lambda *_args, **_kwargs: _async_value(({
            "completed": False,
            "evidence_review_state": [{
                "file_id": "file-a", "ocr_revision_ids": ["current-rev"],
            }],
        }, {"file_id": "file-a"})),
    )
    monkeypatch.setattr(
        intake,
        "get_evidence_file",
        lambda *_args, **_kwargs: _async_value((path, "scan.pdf", "application/pdf")),
    )
    called = False

    async def should_not_confirm(**_kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(ocr_service, "confirm_page", should_not_confirm)

    with pytest.raises(NotFoundError):
        await intake.confirm_evidence_ocr_page(
            "intake-a", "client-a", "file-a", "old-rev",
            source_sha256="a" * 64, text_sha256="b" * 64,
            confirmed_text="text",
        )
    assert called is False


@pytest.mark.asyncio
async def test_intake_requests_ocr_blocks_unconfirmed_then_uses_confirmation(
    tmp_path, repo, monkeypatch
):
    from app.ai import extraction_runner
    from app.core.config import settings
    from app.services import intake_service as intake
    from app.services import ocr_service

    monkeypatch.setattr(settings, "english_ocr_enabled", True)
    monkeypatch.setattr(intake, "_EVIDENCE_DIR", tmp_path)
    path = tmp_path / "scan.pdf"
    path.write_bytes(b"scan bytes")
    page = _page("Secret OCR amount 1000")
    result = _scanned_result(page)
    calls = []

    async def fake_extract_many(files, **kwargs):
        calls.append(kwargs)
        return {"file-a": (result, "")}

    monkeypatch.setattr(extraction_runner, "extract_many", fake_extract_many)
    files = [{"file_id": "file-a", "path": str(path),
              "content_type": "application/pdf"}]

    prompt, statuses = await intake._extract_intake_evidence(
        files, owner_id="client-a", session_id="intake-a")
    assert calls[0]["ocr"] == {"enabled": True, "language": "eng"}
    assert "Secret OCR amount" not in prompt
    assert statuses[0]["ocr_review_required"] is True

    review = await ocr_service.review_pages_for_file(
        owner_id="client-a", file_id="file-a", path=str(path))
    await ocr_service.confirm_page(
        owner_id="client-a", file_id="file-a",
        revision_id=review[0]["revision_id"], path=str(path),
        source_sha256=review[0]["source_sha256"],
        ocr_text_sha256=review[0]["text_sha256"],
        confirmed_text="Corrected amount is 10,000 rupees",
    )

    prompt, statuses = await intake._extract_intake_evidence(
        files, owner_id="client-a", session_id="intake-a")
    assert "Secret OCR amount" not in prompt
    assert "Corrected amount is 10,000 rupees" in prompt
    assert statuses[0]["ocr_review_required"] is False
    assert statuses[0]["ocr_confirmed"] is True
    assert statuses[0]["pages_with_text"] == 1
    assert statuses[0]["text_yielding_page_ratio"] == 1.0
    assert "1 of 1 pages produced no text" not in prompt


@pytest.mark.asyncio
async def test_a_failed_ocr_page_cannot_make_the_review_impossible(
    tmp_path, repo, monkeypatch
):
    """Only completed readings are pinned; failures remain disclosed gaps."""
    from app.ai import extraction_runner
    from app.core.config import settings
    from app.services import intake_service as intake
    from app.services import ocr_service

    monkeypatch.setattr(settings, "english_ocr_enabled", True)
    monkeypatch.setattr(intake, "_EVIDENCE_DIR", tmp_path)
    path = tmp_path / "mixed-scan.pdf"
    path.write_bytes(b"two page scan")
    good = _page("Page one amount 1000")
    failed = O.OcrPageResult(
        page_number=2,
        status=O.OCR_TIMEOUT,
        error_code="ocr_page_timeout",
    )
    result = E.ExtractionResult(
        outcome=E.OUTCOME_SUCCEEDED,
        completeness=E.NONE,
        error_code=E.ERR_NO_TEXT_LAYER,
        pages_total=2,
        pages_attempted=2,
        pages_with_text=0,
        page_reports=[
            E.PageReport(1, E.PAGE_NO_TEXT_FOUND, images_present=True),
            E.PageReport(2, E.PAGE_NO_TEXT_FOUND, images_present=True),
        ],
        ocr_pages=[good, failed],
    )

    async def fake_extract_many(_files, **_kwargs):
        return {"file-a": (result, "")}

    monkeypatch.setattr(extraction_runner, "extract_many", fake_extract_many)
    files = [{
        "file_id": "file-a",
        "path": str(path),
        "content_type": "application/pdf",
    }]

    _, pending = await intake._extract_intake_evidence(
        files, owner_id="client-a", session_id="intake-a"
    )
    assert pending[0]["ocr_status"] == O.OCR_TIMEOUT
    assert len(pending[0]["ocr_revision_ids"]) == 1
    review = await ocr_service.review_pages_for_file(
        owner_id="client-a",
        file_id="file-a",
        path=str(path),
        revision_ids=pending[0]["ocr_revision_ids"],
    )
    assert [page["page_number"] for page in review] == [1]
    await ocr_service.confirm_page(
        owner_id="client-a",
        file_id="file-a",
        revision_id=review[0]["revision_id"],
        path=str(path),
        source_sha256=review[0]["source_sha256"],
        ocr_text_sha256=review[0]["text_sha256"],
        confirmed_text="Confirmed page one amount 1000",
    )

    prompt, final = await intake._extract_intake_evidence(
        files,
        owner_id="client-a",
        session_id="intake-a",
        resume_ocr_state=pending,
    )
    assert "Confirmed page one amount 1000" in prompt
    assert final[0]["ocr_review_required"] is False
    assert final[0]["ocr_confirmed"] is True
    assert final[0]["pages_with_text"] == 1
    assert final[0]["status"] == "partially_read"
    assert "1 of 2 pages produced no text" in prompt


@pytest.mark.asyncio
async def test_disabling_new_ocr_does_not_strand_an_existing_review(
    tmp_path, repo, monkeypatch
):
    """The execution flag is a kill switch, not a confirmation eraser."""
    from app.ai import extraction_runner
    from app.core.config import settings
    from app.services import intake_service as intake
    from app.services import ocr_service

    monkeypatch.setattr(settings, "english_ocr_enabled", True)
    monkeypatch.setattr(intake, "_EVIDENCE_DIR", tmp_path)
    path = tmp_path / "scan.pdf"
    path.write_bytes(b"stable source")
    result = _scanned_result(_page("The flne is 1000 rupees"))
    calls = []

    async def fake_extract_many(files, **kwargs):
        calls.append(kwargs)
        return {"file-a": (result, "")}

    monkeypatch.setattr(extraction_runner, "extract_many", fake_extract_many)
    files = [{"file_id": "file-a", "path": str(path),
              "content_type": "application/pdf"}]
    _, pending = await intake._extract_intake_evidence(
        files, owner_id="client-a", session_id="intake-a")
    review = await ocr_service.review_pages_for_file(
        owner_id="client-a", file_id="file-a", path=str(path))

    # Operational rollback: no further engine invocation is allowed.
    monkeypatch.setattr(settings, "english_ocr_enabled", False)
    await ocr_service.confirm_page(
        owner_id="client-a", file_id="file-a",
        revision_id=review[0]["revision_id"], path=str(path),
        source_sha256=review[0]["source_sha256"],
        ocr_text_sha256=review[0]["text_sha256"],
        confirmed_text="The fine is 10,000 rupees",
    )
    prompt, resumed = await intake._extract_intake_evidence(
        files,
        owner_id="client-a",
        session_id="intake-a",
        resume_ocr_state=pending,
    )

    assert pending[0]["ocr_review_required"] is True
    assert calls[-1]["ocr"] is None, "the disabled engine ran again"
    assert "The fine is 10,000 rupees" in prompt
    assert resumed[0]["ocr_confirmed"] is True
    assert resumed[0]["ocr_review_required"] is False


@pytest.mark.asyncio
async def test_flag_off_preserves_the_existing_plain_extraction_call(
    tmp_path, monkeypatch
):
    from app.ai import extraction_runner
    from app.core.config import settings
    from app.services import intake_service as intake

    monkeypatch.setattr(settings, "english_ocr_enabled", False)
    monkeypatch.setattr(intake, "_EVIDENCE_DIR", tmp_path)
    path = tmp_path / "native.pdf"
    path.write_bytes(b"native")
    result = E.ExtractionResult(
        outcome=E.OUTCOME_SUCCEEDED, completeness=E.COMPLETE,
        text="native evidence", pages_total=1, pages_attempted=1,
        pages_with_text=1,
    )
    seen = []

    async def fake_extract_many(files, **kwargs):
        seen.append(kwargs)
        return {"f": (result, result.text)}

    monkeypatch.setattr(extraction_runner, "extract_many", fake_extract_many)
    prompt, statuses = await intake._extract_intake_evidence(
        [{"file_id": "f", "path": str(path),
          "content_type": "application/pdf"}],
        owner_id="client-a", session_id="intake-a")

    assert seen[0]["ocr"] is None
    assert "native evidence" in prompt
    assert statuses[0]["status"] == "readable"
