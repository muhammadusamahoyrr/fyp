"""Evidence limitations must survive the journey, not just exist at the source.

Milestone 1 established the facts. This file is about whether they still exist by
the time anyone can act on them — after a page reload, after conversion, and in
the context handed to a model that drafts against the case.

Three failures are asserted against specifically, because each one turns a
qualified statement into a confident one:

  * a `.doc` that said "stored, not analysed" at upload and "could not be read"
    after a refresh — a wrongly alarming claim about a perfectly fine file;
  * a file whose text was truncated out of the prompt still reporting
    "Read in full";
  * a case summary outliving the record of how much evidence it was built from,
    so a lawyer reads a confident paragraph with no sign that most of the bundle
    was never opened.

HTTP serialisation is exercised through the real response models. A field the
service returns and the schema drops is invisible to every service-level test,
and that is precisely the layer these fields cross.
"""
from __future__ import annotations

import io
import secrets
from datetime import datetime, timezone

import pytest

from app.services import intake_service
from app.services.evidence_coverage import (
    coverage_line,
    derive_analysis_support,
    snapshot_from_statuses,
)

pytestmark = pytest.mark.integration

_OLE2 = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_PNG = b"\x89PNG\r\n\x1a\n"


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
    client_id, token = f"EC-C-{tag}", f"EC-T-{tag}"
    now = datetime.now(timezone.utc)
    await get_users_col().insert_one({
        "_id": client_id, "role": "client", "is_active": True,
        "email": f"ec-{tag}@test.invalid", "full_name": "Coverage Client",
        "province": "punjab", "created_at": now,
    })
    await get_intakes_col().insert_one({
        "_id": f"EC-I-{tag}", "session_token": token, "client_id": client_id,
        "current_step": 3, "completed": False, "case_id": None,
        "step1": {"province": "punjab"},
        "step3": {"incident_description": "A tenancy dispute."},
        "clarification_qa": [], "evidence_files": [],
        "created_at": now, "updated_at": now,
    })
    yield {"client_id": client_id, "token": token}
    await get_users_col().delete_many({"_id": client_id})
    await get_intakes_col().delete_many({"session_token": token})


async def _upload(intake, content, name, mime):
    return await intake_service.upload_evidence(
        intake["token"], intake["client_id"], FakeUpload(content, name, mime))


# ── 1. storage-only survives the round trip ─────────────────────────────────

async def test_storage_only_is_persisted_on_the_record_not_just_returned(intake):
    """The defect: it lived only in the upload response, so a reload lost it."""
    from app.db.collections import get_intakes_col

    result = await _upload(intake, _OLE2 + b"\x00" * 512, "old.doc",
                           "application/msword")
    assert result["analysis_support"] == "storage_only"

    stored = await get_intakes_col().find_one({"session_token": intake["token"]})
    record = stored["evidence_files"][0]

    assert record["analysis_support"] == "storage_only", (
        "the capability was returned to the client but never written down")


@pytest.mark.parametrize("magic,name,mime", [
    (_OLE2, "old.doc", "application/msword"),
    (_PNG, "photo.png", "image/png"),
])
async def test_live_and_restored_views_agree(intake, magic, name, mime):
    """Live-versus-refresh equivalence, which is the whole bug.

    The upload response and the restored intake must describe the same file the
    same way. They described it differently, and the restored one was wrong.
    """
    live = await _upload(intake, magic + b"\x00" * 512, name, mime)
    restored = await intake_service.get_intake(
        intake["token"], intake["client_id"])
    entry = next(f for f in restored["evidence_files"]
                 if f["file_id"] == live["file_id"])

    assert entry["analysis_support"] == live["analysis_support"] == "storage_only"
    assert entry["notice"], "the restored view lost the explanation"


async def test_a_legacy_record_without_the_field_is_derived_conservatively(intake):
    """Files uploaded before the field existed still have their content type.

    Derived from that rather than left blank — but only for types we recognise.
    An unrecognised type yields None ("unknown"), never an assertion that it was
    analysable.
    """
    assert derive_analysis_support(
        {"content_type": "application/msword"}) == "storage_only"
    assert derive_analysis_support({"content_type": "image/webp"}) == "storage_only"
    assert derive_analysis_support({"content_type": "application/pdf"}) is None
    assert derive_analysis_support({"content_type": "application/x-unknown"}) is None
    assert derive_analysis_support({}) is None
    assert derive_analysis_support(None) is None


async def test_a_stored_value_wins_over_the_derived_one(intake):
    assert derive_analysis_support(
        {"analysis_support": "storage_only", "content_type": "application/pdf"}
    ) == "storage_only"


# ── 2. HTTP serialisation — the layer that silently drops fields ────────────

async def test_the_detail_endpoint_serialises_the_new_fields(intake):
    """Through the REAL response model.

    A service can return a field that the Pydantic response model then drops,
    and no service-level test can see it. These fields cross exactly that layer.
    """
    from app.schemas.intake import IntakeDetailResponse

    await _upload(intake, _OLE2 + b"\x00" * 512, "old.doc", "application/msword")
    detail = await intake_service.get_intake(intake["token"], intake["client_id"])

    serialised = IntakeDetailResponse(**detail).model_dump()
    entry = serialised["evidence_files"][0]

    assert entry["analysis_support"] == "storage_only"
    assert entry["notice"]
    assert "prompt_truncated" in entry


async def test_unknown_page_counters_serialise_as_null_not_zero(intake):
    """`None` means the extractor could not determine the count.

    Coerced to 0 it becomes a definite claim — "0 of 5 pages had text" — built
    entirely out of an absence. Asserted after the response model, because that
    is where an `int` annotation would quietly do the coercing.
    """
    from app.schemas.intake import IntakeEvidenceFile

    entry = IntakeEvidenceFile(
        file_id="f1", filename="b.pdf",
        extraction_status="partially_read",
        pages_total=None, pages_with_text=None,
        pages_failed=None, pages_skipped=None,
    ).model_dump()

    for key in ("pages_total", "pages_with_text", "pages_failed", "pages_skipped"):
        assert entry[key] is None, f"{key} was coerced away from unknown"


def test_public_evidence_passes_counters_through_unchanged():
    record = [{
        "file_id": "f1", "status": "partially_read",
        "pages_total": None, "pages_with_text": 2,
        "pages_failed": None, "pages_skipped": 0,
    }]
    out = intake_service._public_evidence(
        [{"file_id": "f1", "filename": "b.pdf"}], record)[0]

    assert out["pages_total"] is None
    assert out["pages_with_text"] == 2
    assert out["pages_failed"] is None
    assert out["pages_skipped"] == 0, "a real zero must survive as a zero"


# ── 3. truncation is one contract ──────────────────────────────────────────

def test_prompt_truncated_is_always_a_bool_in_the_public_view():
    """The live record says `truncated`; the public view says `prompt_truncated`.

    One name crosses the wire, and it is never None — a tri-state here is what
    lets a caller treat "unknown" as "false".
    """
    out = intake_service._public_evidence(
        [{"file_id": "f1", "filename": "b.pdf"}],
        [{"file_id": "f1", "status": "readable", "truncated": True}])[0]

    assert out["prompt_truncated"] is True

    out2 = intake_service._public_evidence(
        [{"file_id": "f2", "filename": "c.pdf"}],
        [{"file_id": "f2", "status": "readable"}])[0]

    assert out2["prompt_truncated"] is False


# ── 4. the case keeps the caveat with the summary ──────────────────────────

def test_the_snapshot_is_sanitised():
    """Safe to store on a case, return over the API and put in a prompt."""
    snap = snapshot_from_statuses([{
        "file_id": "f1", "status": "partially_read",
        "pages_total": 5, "pages_with_text": 2,
        "path": "/srv/uploads/evidence/tok/secret.pdf",
        "text": "CONFIDENTIAL client statement",
        "filename": "Zubaida-Bibi-FIR.pdf",
    }])
    body = repr(snap)

    assert "secret.pdf" not in body
    assert "CONFIDENTIAL" not in body
    assert "Zubaida" not in body
    assert "/srv" not in body


def test_the_snapshot_counts_each_category_separately():
    snap = snapshot_from_statuses([
        {"status": "readable", "pages_total": 2, "pages_with_text": 2},
        {"status": "partially_read", "pages_total": 5, "pages_with_text": 1},
        {"status": "omitted_limit", "pages_total": 1, "pages_with_text": 1},
        {"status": "storage_only", "pages_total": None, "pages_with_text": None},
        {"status": "unreadable", "pages_total": 3, "pages_with_text": 0},
    ])

    assert snap["files_total"] == 5
    assert snap["files_read_in_full"] == 1
    assert snap["files_partially_read"] == 1
    assert snap["files_omitted_for_length"] == 1
    assert snap["files_storage_only"] == 1
    assert snap["files_not_read"] == 1
    assert snap["complete"] is False


def test_one_unknown_page_total_makes_the_total_unknown():
    """A partial sum presented as a total is a smaller number that reads as a
    complete one."""
    snap = snapshot_from_statuses([
        {"status": "readable", "pages_total": 3, "pages_with_text": 3},
        {"status": "storage_only", "pages_total": None, "pages_with_text": None},
    ])

    assert snap["pages_total"] is None
    assert snap["pages_with_text"] is None


def test_an_unrecognised_status_counts_as_not_read():
    """A future status must not vanish from the totals by falling through."""
    snap = snapshot_from_statuses([{"status": "something_new_in_2027"}])

    assert snap["files_not_read"] == 1
    assert snap["complete"] is False


def test_a_truncated_file_is_never_reported_as_complete_coverage():
    snap = snapshot_from_statuses([
        {"status": "readable", "pages_total": 2, "pages_with_text": 2,
         "truncated": True},
    ])

    assert snap["files_prompt_truncated"] == 1
    assert snap["complete"] is False, (
        "every file read in full, but the analysis did not see all of it")


def test_an_empty_evidence_set_is_not_complete_coverage():
    verified_zero = snapshot_from_statuses([], uploaded_count=0)

    assert verified_zero is not None
    assert verified_zero["complete"] is False


def test_a_missing_record_produces_no_snapshot_at_all():
    """`None` means no extraction record. A snapshot of zero built from it would
    state, on the case, that nothing was uploaded."""
    assert snapshot_from_statuses(None) is None
    assert snapshot_from_statuses(None, uploaded_count=0) is None


def test_an_empty_list_needs_corroboration_to_mean_zero():
    """`[]` against three attachments is a missing record, not "no documents"."""
    assert snapshot_from_statuses([]) is None, "unverified empty claimed a zero"
    assert snapshot_from_statuses([], uploaded_count=3) is None, (
        "an empty record contradicted by three uploads claimed a zero")
    assert snapshot_from_statuses([], uploaded_count=0) is not None


def test_coverage_line_composed_over_a_missing_record_reads_unknown():
    """The composed path, end to end — producer into renderer.

    Each half was correct in isolation: the renderer treats `None` as unknown,
    and the producer returned a well-formed dict. Composed, the producer's dict
    of zeros satisfied the renderer's verified-zero branch, and the pair
    asserted "No documents were uploaded with this case" for a case whose
    evidence had simply never been recorded.
    """
    line = coverage_line(snapshot_from_statuses(None))

    assert "UNKNOWN" in line
    assert "No documents were uploaded" not in line


def test_coverage_line_composed_over_a_verified_zero_reads_zero():
    """The other half of the distinction must still be reachable."""
    line = coverage_line(snapshot_from_statuses([], uploaded_count=0))

    assert line == "No documents were uploaded with this case."


# ── 5. downstream consumers of the summary ─────────────────────────────────

def test_case_context_carries_the_coverage_line():
    from app.services.case_context import build_case_context, context_block

    ctx = build_case_context({
        "ai_summary": "A tenancy claim.", "case_type": "civil",
        "province": "punjab", "case_number": "ATT-2026-1",
        "ai_evidence_coverage": snapshot_from_statuses([
            {"status": "readable", "pages_total": 1, "pages_with_text": 1},
            {"status": "unreadable", "pages_total": 4, "pages_with_text": 0},
        ]),
    })

    assert "evidence_coverage" in ctx
    assert "could not be read" in ctx["evidence_coverage"]
    assert "evidence_coverage:" in context_block(ctx)


def test_a_case_predating_coverage_tracking_reports_unknown_not_complete():
    """The dangerous default. Every case created before this change has no
    snapshot, and the tempting rendering of that is silence."""
    from app.services.case_context import build_case_context

    ctx = build_case_context({"ai_summary": "An old summary.",
                              "case_type": "civil", "province": "punjab"})

    assert "UNKNOWN" in ctx["evidence_coverage"]
    assert "all" in ctx["evidence_coverage"].lower()
    assert "read in full" not in ctx["evidence_coverage"].lower()


def test_the_coverage_line_never_claims_completeness_it_cannot_support():
    assert "UNKNOWN" in coverage_line(None)
    assert "UNKNOWN" in coverage_line({})
    full = coverage_line(snapshot_from_statuses(
        [{"status": "readable", "pages_total": 1, "pages_with_text": 1}]))
    assert "All 1 uploaded file(s) were read in full." == full


async def test_conversion_writes_the_snapshot_onto_the_case(intake, monkeypatch):
    """The summary and its caveat are written by the SAME guarded update.

    A separate write could land without it, and a summary that outlives its
    caveat is the failure this closes.
    """
    from app.db.collections import get_cases_col

    async def classify(description, user_selected):
        return user_selected or "civil", False

    async def run_ai(**kw):
        return {
            "summary": "A tenancy claim.", "applicable_laws": [],
            "recommended_actions": [], "risk_level": "medium",
            "grounded": False, "grounding_status": "stubbed_in_test",
        }

    monkeypatch.setattr(intake_service, "_ai_classify_case_type", classify)
    monkeypatch.setattr(intake_service, "_run_intake_ai", run_ai)

    cid, token = intake["client_id"], intake["token"]
    # REAL uploads, so the snapshot is built from real extraction rather than
    # from something a stub asserted. One readable, one that no extractor can
    # read.
    await intake_service.upload_evidence(
        token, cid, FakeUpload(b"%PDF-1.4\n" + b"0" * 512, "bundle.pdf",
                               "application/pdf"))
    await intake_service.upload_evidence(
        token, cid, FakeUpload(_OLE2 + b"\x00" * 512, "old.doc",
                               "application/msword"))

    await intake_service.save_step(token, 2, {"case_type": "civil",
                                              "urgency": "medium"}, cid)
    await intake_service.save_step(token, 4, {"has_evidence": True}, cid)
    await intake_service.save_step(token, 5, {"desired_outcome": "Recover"}, cid)
    first = await intake_service.convert_to_case(token, cid)

    stored = await get_cases_col().find_one({"_id": first["case_id"]})
    try:
        snap = stored.get("ai_evidence_coverage")
        assert snap, "the case carries a summary with no record of its coverage"
        assert stored.get("ai_summary") == "A tenancy claim."
        assert snap["files_total"] == 2, "the snapshot lost an attached file"
        assert snap["files_storage_only"] == 1, "the .doc was not recorded as such"
        assert snap["complete"] is False

        # Replay: conversion is idempotent, and the caveat must not be lost by a
        # second pass that finds the work already done.
        again = await intake_service.convert_to_case(token, cid)
        assert again["case_id"] == first["case_id"]
        after = await get_cases_col().find_one({"_id": first["case_id"]})
        assert after.get("ai_evidence_coverage") == snap
    finally:
        await get_cases_col().delete_many({"client_id": cid})


async def test_a_case_with_uploads_never_claims_none_when_the_ai_omits_them(
        intake, monkeypatch):
    """THE DEFECT THIS CLOSES.

    The snapshot was built from `ai_data.get("evidence_extraction")`. When the
    analysis returned a summary without that key — a failed pipeline, an older
    path, any stub — `.get()` returned None and the snapshot became a record of
    zero. The case then asserted that nothing was uploaded, for a client who had
    attached files, beside a summary that never saw them.

    The snapshot is now built from the LOCAL extraction result, which is
    computed before the model runs and cannot go missing because the model did.
    """
    from app.db.collections import get_cases_col

    async def classify(description, user_selected):
        return user_selected or "civil", False

    async def run_ai(**kw):
        # A summary, and deliberately NO evidence_extraction key.
        return {"summary": "A tenancy claim.", "applicable_laws": [],
                "recommended_actions": [], "risk_level": "medium",
                "grounded": False, "grounding_status": "stubbed_in_test"}

    monkeypatch.setattr(intake_service, "_ai_classify_case_type", classify)
    monkeypatch.setattr(intake_service, "_run_intake_ai", run_ai)

    cid, token = intake["client_id"], intake["token"]
    await intake_service.upload_evidence(
        token, cid, FakeUpload(_OLE2 + b"\x00" * 512, "affidavit.doc",
                               "application/msword"))
    await intake_service.save_step(token, 2, {"case_type": "civil",
                                              "urgency": "medium"}, cid)
    await intake_service.save_step(token, 4, {"has_evidence": True}, cid)
    await intake_service.save_step(token, 5, {"desired_outcome": "Recover"}, cid)
    result = await intake_service.convert_to_case(token, cid)

    stored = await get_cases_col().find_one({"_id": result["case_id"]})
    try:
        snap = stored.get("ai_evidence_coverage")
        line = coverage_line(snap)

        assert stored.get("ai_summary") == "A tenancy claim."
        assert "No documents were uploaded" not in line, (
            "the case denied uploads that exist")
        # Not merely "avoided the false claim". Degrading to UNKNOWN would also
        # avoid it while silently losing the file — an `or snap is None` here
        # would let exactly that pass, so the count is asserted directly.
        assert snap is not None, "the attached file vanished from the record"
        assert snap["files_total"] == 1
        assert snap["files_storage_only"] == 1
    finally:
        await get_cases_col().delete_many({"client_id": cid})


async def test_a_case_with_no_uploads_reports_a_verified_zero(intake, monkeypatch):
    """The other side: genuinely no attachments must not degrade to UNKNOWN.

    Losing this would make every empty case indistinguishable from an
    unrecorded one, which is the same flattening in the opposite direction.
    """
    from app.db.collections import get_cases_col

    async def classify(description, user_selected):
        return user_selected or "civil", False

    async def run_ai(**kw):
        return {"summary": "A tenancy claim.", "applicable_laws": [],
                "recommended_actions": [], "risk_level": "medium",
                "grounded": False, "grounding_status": "stubbed_in_test"}

    monkeypatch.setattr(intake_service, "_ai_classify_case_type", classify)
    monkeypatch.setattr(intake_service, "_run_intake_ai", run_ai)

    cid, token = intake["client_id"], intake["token"]
    await intake_service.save_step(token, 2, {"case_type": "civil",
                                              "urgency": "medium"}, cid)
    await intake_service.save_step(token, 4, {"has_evidence": False}, cid)
    await intake_service.save_step(token, 5, {"desired_outcome": "Recover"}, cid)
    result = await intake_service.convert_to_case(token, cid)

    stored = await get_cases_col().find_one({"_id": result["case_id"]})
    try:
        snap = stored.get("ai_evidence_coverage")
        assert snap is not None, "a genuinely empty case lost its verified zero"
        assert snap["files_total"] == 0
        assert coverage_line(snap) == "No documents were uploaded with this case."
    finally:
        await get_cases_col().delete_many({"client_id": cid})


def test_adding_coverage_did_not_weaken_the_scrub_or_the_whitelist():
    """The EXACT whitelist is pinned once, in `test_v2_stage5.py`, beside the
    other Stage 5 privacy guards. Asserting the same set here too would mean two
    places to update and one of them going stale — so this checks the property
    that changed (a new field is present and carries no PII) rather than
    restating the contract that owns it."""
    from app.services.case_context import build_case_context

    ctx = build_case_context({
        "ai_summary": "Contact me at a@b.com or 0300-1234567.",
        "client_id": "CLIENT-SECRET", "lawyer_id": "LAWYER-SECRET",
        "case_type": "civil", "province": "punjab",
    })

    assert "evidence_coverage" in ctx
    assert "a@b.com" not in ctx["summary"]
    assert "CLIENT-SECRET" not in repr(ctx)
    assert "LAWYER-SECRET" not in repr(ctx)


# ── hardening: a stored snapshot is untrusted input ────────────────────────
#
# It lives in a database document. Migrations, hand edits and older code can all
# put something there that does not mean what it looks like, and the renderer
# feeds a legal drafting prompt. Every check below fails toward UNKNOWN, because
# the alternative is a confident sentence built from a value nobody verified.

def _valid() -> dict:
    return snapshot_from_statuses([
        {"status": "readable", "pages_total": 2, "pages_with_text": 2},
        {"status": "unreadable", "pages_total": 4, "pages_with_text": 0},
    ])


def test_a_valid_snapshot_still_validates():
    """The control. Hardening that rejects correct records is not hardening."""
    from app.services.evidence_coverage import validate_snapshot

    assert validate_snapshot(_valid()) is not None
    assert "could not be read" in coverage_line(_valid())


def test_a_boolean_is_not_a_count():
    """`isinstance(True, int)` is True in Python, so a naive check accepts
    `True` and renders it as the number 1 — a count fabricated from a flag."""
    from app.services.evidence_coverage import validate_snapshot

    for field in ("files_total", "files_read_in_full", "files_not_read"):
        snap = {**_valid(), field: True}
        assert validate_snapshot(snap) is None, f"{field}=True was accepted"
        assert coverage_line(snap).startswith("Evidence coverage")


@pytest.mark.parametrize("value", ["2", "", None, 2.0, 2.5, [], {}, object()])
def test_a_non_integer_count_is_rejected(value):
    from app.services.evidence_coverage import validate_snapshot

    assert validate_snapshot({**_valid(), "files_total": value}) is None


def test_a_negative_count_is_rejected():
    from app.services.evidence_coverage import validate_snapshot

    assert validate_snapshot({**_valid(), "files_not_read": -1}) is None
    assert validate_snapshot({**_valid(), "files_total": -5}) is None


def test_counts_that_do_not_sum_to_the_total_are_rejected():
    """A record whose parts disagree with its own total cannot be interpreted.

    Rendering it anyway is how a smaller number gets read as a complete one.
    """
    from app.services.evidence_coverage import validate_snapshot

    assert validate_snapshot({**_valid(), "files_total": 99}) is None
    assert validate_snapshot({**_valid(), "files_read_in_full": 7}) is None


def test_more_truncated_files_than_files_is_rejected():
    from app.services.evidence_coverage import validate_snapshot

    assert validate_snapshot({**_valid(), "files_prompt_truncated": 99}) is None


def test_a_missing_field_is_rejected_rather_than_defaulted():
    """Defaulting an absent count to 0 invents the most flattering value."""
    from app.services.evidence_coverage import validate_snapshot

    for field in ("files_total", "files_not_read", "files_prompt_truncated"):
        snap = {k: v for k, v in _valid().items() if k != field}
        assert validate_snapshot(snap) is None, f"missing {field} was defaulted"


def test_the_complete_flag_is_never_trusted():
    """The flag is recomputed from the counts, so a stored `True` on a record
    whose counts disagree cannot assert completeness."""
    from app.services.evidence_coverage import validate_snapshot

    lying = {**_valid(), "complete": True}          # 1 of 2 files unreadable
    checked = validate_snapshot(lying)

    assert checked is not None, "the record is structurally sound, just wrong"
    assert checked["complete"] is False
    line = coverage_line(lying)
    assert "All " not in line
    assert "could not be read" in line


def test_a_truthy_non_boolean_complete_does_not_assert_completeness():
    for truthy in ("yes", 1, [1], {"a": 1}):
        line = coverage_line({**_valid(), "complete": truthy})
        assert not line.startswith("All "), f"complete={truthy!r} was believed"


def test_a_genuinely_complete_record_is_still_reported_complete():
    """The guard must not have made completeness unreachable."""
    snap = snapshot_from_statuses(
        [{"status": "readable", "pages_total": 3, "pages_with_text": 3}])

    assert coverage_line(snap) == "All 1 uploaded file(s) were read in full."


@pytest.mark.parametrize("bad", [
    None, {}, "nonsense", [1, 2, 3], 42, True, 0.5, set(),
])
def test_a_malformed_snapshot_renders_unknown_without_raising(bad):
    from app.services.evidence_coverage import validate_snapshot

    line = coverage_line(bad)          # must not raise

    assert line.startswith("Evidence coverage")
    assert "UNKNOWN" in line
    assert validate_snapshot(bad) is None


def test_inconsistent_page_counters_are_rejected():
    from app.services.evidence_coverage import validate_snapshot

    assert validate_snapshot(
        {**_valid(), "pages_total": 2, "pages_with_text": 9}) is None
    assert validate_snapshot({**_valid(), "pages_total": "many"}) is None
    # But genuinely unknown page counts remain legal.
    assert validate_snapshot(
        {**_valid(), "pages_total": None, "pages_with_text": None}) is not None


def test_no_uploads_is_distinguished_from_no_record():
    """Two different facts that a single 'unknown' would flatten.

    A case converted with coverage tracking and genuinely no uploads has a valid
    snapshot of zero. A case predating the tracking has none. The first is a
    measurement; the second is an absence, and only one of them can be reported
    as settled.
    """
    verified_zero = snapshot_from_statuses([], uploaded_count=0)

    zero_line = coverage_line(verified_zero)
    unknown_line = coverage_line(snapshot_from_statuses(None))

    assert zero_line == "No documents were uploaded with this case."
    assert "UNKNOWN" in unknown_line
    assert zero_line != unknown_line
    assert verified_zero["files_total"] == 0
    assert verified_zero["complete"] is False


def test_an_empty_dict_is_no_record_not_zero_uploads():
    """`{}` carries no counts at all, so it cannot claim a verified zero."""
    assert "UNKNOWN" in coverage_line({})
