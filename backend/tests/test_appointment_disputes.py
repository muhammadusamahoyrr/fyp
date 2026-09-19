"""A client's route when the record of their consultation is wrong.

THE GAP. A lawyer can mark a client absent, or never record an outcome at all.
Both decide something about the client, and the client had no way to say
otherwise — the no-show notice told them to "contact them directly", and an
unrecorded consultation produced silence. `exists_completed` gates their right
to review the lawyer, so either failure silently removes that right from the
person least able to do anything about it.

THE RULE EVERY TEST HERE DEFENDS. Filing a report changes NOTHING about the
appointment. A client who could correct their own record by asserting it could
manufacture review eligibility for a consultation that never happened, and the
review would then carry exactly the weight of the thing it was invented to
bypass. Only support may change the record.
"""
import asyncio
import secrets
from datetime import datetime, timedelta, timezone

import pytest

from app.core.exceptions import (
    AppValidationError,
    ConflictError,
    NotFoundError,
)
from app.services import appointment_disputes as disputes

pytestmark = pytest.mark.integration

NOTE = "The lawyer marked me absent but I attended the whole consultation."
PRIVATE = "INTERNAL: lawyer has three similar reports this quarter."
# Whitespace only: named here so the escape never has to survive a
# decorator, where a stray newline is a syntax error rather than a value.
WHITESPACE = chr(10) + chr(9) + "  "


@pytest.fixture
async def parties(app_indexes):
    from app.db.collections import (
        get_appointment_disputes_col,
        get_appointments_col,
        get_notifications_col,
        get_users_col,
    )

    tag = secrets.token_hex(4)
    lawyer_id = f"DS-L-{tag}"
    client_id, other_client = f"DS-C-{tag}", f"DS-C2-{tag}"
    admin_id = f"DS-A-{tag}"
    now = datetime.now(timezone.utc)

    await get_users_col().insert_many([
        {"_id": lawyer_id, "role": "lawyer", "is_active": True,
         "email": f"{lawyer_id}@test.invalid", "full_name": "Adv One",
         "province": "punjab", "created_at": now,
         "lawyer_profile": {"specializations": ["criminal"],
                            "kyc_verified": True, "rating": 4.0,
                            "total_reviews": 0, "availability": True,
                            "experience_years": 5}},
        {"_id": client_id, "role": "client", "is_active": True,
         "email": f"{client_id}@test.invalid", "full_name": "Client One",
         "created_at": now},
        {"_id": other_client, "role": "client", "is_active": True,
         "email": f"{other_client}@test.invalid", "full_name": "Client Two",
         "created_at": now},
        {"_id": admin_id, "role": "admin", "is_active": True,
         "email": f"{admin_id}@test.invalid", "full_name": "Support",
         "created_at": now},
    ])
    yield {"lawyer_id": lawyer_id, "client_id": client_id,
           "other_client": other_client, "admin_id": admin_id}
    ids = [lawyer_id, client_id, other_client, admin_id]
    await get_users_col().delete_many({"_id": {"$in": ids}})
    await get_appointments_col().delete_many({"lawyer_id": lawyer_id})
    await get_appointment_disputes_col().delete_many({"lawyer_id": lawyer_id})
    await get_notifications_col().delete_many({"user_id": {"$in": ids}})


_slots = iter(range(1, 20_000))
_SLOT_EPOCH = datetime(2000, 1, 1, tzinfo=timezone.utc)


async def _appt(parties, *, status="no_show", ended_hours_ago=5,
                client_id=None, **over):
    """A stored appointment in whatever state the test needs.

    Written directly: an appointment that has already ENDED cannot be produced
    through the booking API, and these reports are all about finished ones.
    Each row carries a unique slot sentinel so the unique slot indexes, which
    are about a different guarantee entirely, stay out of the way.
    """
    from app.db.collections import get_appointments_col

    end = datetime.now(timezone.utc) - timedelta(hours=ended_hours_ago)
    doc = {
        "_id": f"DS-AP-{secrets.token_hex(6)}",
        "client_id": client_id or parties["client_id"],
        "lawyer_id": parties["lawyer_id"],
        "case_id": None,
        "scheduled_at": end - timedelta(hours=1),
        "end_at": end,
        "duration_minutes": 60,
        "status": status,
        "mode": "video",
        "timezone": "Asia/Karachi",
        "schedule_version": 0,
        "notes": None,
        "lawyer_notes": None,
        "cancel_reason": None,
        "cancelled_by": None,
        "meeting_link": None,
        "created_at": end - timedelta(days=2),
        "updated_at": end,
        "occupied_slots": [_SLOT_EPOCH + timedelta(minutes=30 * next(_slots))],
    }
    doc.update(over)
    await get_appointments_col().insert_one(doc)
    return doc["_id"]


async def _open(parties, appt_id, *, category="incorrect_no_show",
                statement=NOTE, client_id=None):
    return await disputes.open_dispute(
        appt_id=appt_id, client_id=client_id or parties["client_id"],
        category=category, statement=statement)


async def _resolve(parties, dispute_id, *, decision, version=0,
                   explanation="Reviewed.", support_note=None, role="admin",
                   actor=None):
    return await disputes.resolve_dispute(
        dispute_id=dispute_id, actor_id=actor or parties["admin_id"],
        actor_role=role, expected_version=version, decision=decision,
        explanation=explanation, support_note=support_note)


async def _status(appt_id):
    from app.db.collections import get_appointments_col
    return (await get_appointments_col().find_one({"_id": appt_id}))["status"]


# ── 1. Which reports are allowed ─────────────────────────────────────────────

async def test_a_wrong_no_show_can_be_reported(parties):
    appt = await _appt(parties, status="no_show")

    dispute = await _open(parties, appt)

    assert dispute["category"] == "incorrect_no_show"
    assert dispute["status"] == "open"
    assert dispute["statement"] == NOTE


async def test_an_unrecorded_outcome_can_be_reported(parties):
    appt = await _appt(parties, status="confirmed", ended_hours_ago=5)

    dispute = await _open(parties, appt, category="outcome_not_recorded")

    assert dispute["category"] == "outcome_not_recorded"


async def test_a_confirmed_appointment_inside_the_grace_period_cannot_be_reported(parties):
    """The grace period is the outcome queue's, not a second one invented
    here, so "overdue an outcome" means the same thing to the client reporting
    it as to the queue chasing the lawyer."""
    appt = await _appt(parties, status="confirmed", ended_hours_ago=1)

    with pytest.raises(AppValidationError):
        await _open(parties, appt, category="outcome_not_recorded")


@pytest.mark.parametrize("status", ["pending", "cancelled", "completed",
                                    "expired"])
async def test_other_statuses_cannot_be_reported(parties, status):
    appt = await _appt(parties, status=status)

    for category in ("incorrect_no_show", "outcome_not_recorded"):
        with pytest.raises(AppValidationError):
            await _open(parties, appt, category=category)


async def test_a_category_that_does_not_match_the_record_is_refused(parties):
    """"The lawyer wrongly marked me absent" is not a thing that can be said
    about an appointment nobody has recorded an outcome for."""
    no_show = await _appt(parties, status="no_show")
    unrecorded = await _appt(parties, status="confirmed", ended_hours_ago=5)

    with pytest.raises(AppValidationError):
        await _open(parties, no_show, category="outcome_not_recorded")
    with pytest.raises(AppValidationError):
        await _open(parties, unrecorded, category="incorrect_no_show")


@pytest.mark.parametrize("bad", [None, "", "   ", "unhappy", "other",
                                 "INCORRECT_NO_SHOW"])
async def test_an_unknown_category_is_refused(parties, bad):
    appt = await _appt(parties, status="no_show")

    with pytest.raises(AppValidationError):
        await _open(parties, appt, category=bad)


@pytest.mark.parametrize("bad", [None, "", "   ", WHITESPACE])
async def test_an_empty_statement_is_refused(parties, bad):
    """A report with nothing in it is not a report. Support would be asked to
    adjudicate a complaint that does not say anything."""
    appt = await _appt(parties, status="no_show")

    with pytest.raises(AppValidationError):
        await _open(parties, appt, statement=bad)


async def test_an_overlong_statement_is_refused(parties):
    appt = await _appt(parties, status="no_show")

    with pytest.raises(AppValidationError):
        await _open(parties, appt, statement="x" * 2001)


# ── 2. Filing changes nothing ────────────────────────────────────────────────

async def test_filing_a_report_changes_no_appointment_field(parties):
    """THE RULE THE WHOLE DESIGN RESTS ON."""
    from app.db.collections import get_appointments_col

    appt = await _appt(parties, status="no_show")
    before = await get_appointments_col().find_one({"_id": appt})

    await _open(parties, appt)

    assert await get_appointments_col().find_one({"_id": appt}) == before


async def test_filing_a_report_grants_no_review_eligibility(parties):
    from app.repositories.appointment_repo import AppointmentRepository

    appt = await _appt(parties, status="no_show")
    await _open(parties, appt)

    assert await AppointmentRepository().exists_completed(
        parties["client_id"], parties["lawyer_id"]) is False


def test_the_service_offers_a_client_no_way_to_complete_an_appointment():
    """Asserted against the source: the only status this module ever writes is
    COMPLETED, and only from the support path."""
    import inspect

    source = inspect.getsource(disputes)
    writers = [line for line in source.splitlines()
               if "compare_and_set" in line and not line.lstrip().startswith("#")]
    assert len(writers) == 1, writers
    assert "_correct_appointment" in source.split("compare_and_set")[0][-2000:]


# ── 3. Authorization ─────────────────────────────────────────────────────────

async def test_a_client_cannot_report_another_clients_appointment(parties):
    """Refused the same way a missing appointment is: a different error would
    confirm the appointment exists to somebody entitled to know nothing."""
    appt = await _appt(parties, status="no_show",
                       client_id=parties["other_client"])

    with pytest.raises(NotFoundError):
        await _open(parties, appt)


async def test_a_report_for_an_unknown_appointment_is_refused_identically(parties):
    with pytest.raises(NotFoundError):
        await _open(parties, "DS-AP-nope")


async def test_a_client_cannot_read_another_clients_report(parties):
    appt = await _appt(parties, status="no_show")
    dispute = await _open(parties, appt)

    with pytest.raises(NotFoundError):
        await disputes.get_for_client(dispute["id"], parties["other_client"])


@pytest.mark.parametrize("role", ["client", "lawyer", "paralegal", "", None])
async def test_only_support_may_decide(parties, role):
    appt = await _appt(parties, status="no_show")
    dispute = await _open(parties, appt)

    from app.core.exceptions import ForbiddenError
    with pytest.raises(ForbiddenError):
        await _resolve(parties, dispute["id"], decision="dismiss_report",
                       role=role, actor=parties["lawyer_id"])


# ── 4. One live complaint per appointment ────────────────────────────────────

async def test_an_identical_retry_returns_the_same_report(parties):
    """A submit button pressed twice, or a dropped connection retried, must not
    file two complaints — and must not fail either, because the client cannot
    tell whether the first attempt landed."""
    appt = await _appt(parties, status="no_show")

    first = await _open(parties, appt)
    second = await _open(parties, appt)

    assert first["id"] == second["id"]


async def test_a_conflicting_retry_is_refused(parties):
    appt = await _appt(parties, status="no_show")
    await _open(parties, appt)

    with pytest.raises(ConflictError):
        await _open(parties, appt, statement="Actually something different.")


async def test_concurrent_submissions_produce_one_report(parties):
    """THE PRE-CHECK CANNOT DO THIS. Two submissions racing both read "none
    open", both pass, and support ends up adjudicating the same complaint
    twice — possibly differently. The unique partial index is what decides."""
    from app.db.collections import get_appointment_disputes_col

    appt = await _appt(parties, status="no_show")

    await asyncio.gather(_open(parties, appt), _open(parties, appt),
                         _open(parties, appt), return_exceptions=True)

    rows = await get_appointment_disputes_col().find(
        {"appointment_id": appt}).to_list(length=10)
    assert len(rows) == 1, f"{len(rows)} live complaints for one appointment"


async def test_the_uniqueness_is_a_real_database_constraint(parties):
    """Asserted by bypassing the service entirely: a second open row for one
    appointment must be impossible, not merely unreachable through the code."""
    from pymongo.errors import DuplicateKeyError

    from app.db.collections import get_appointment_disputes_col

    appt = await _appt(parties, status="no_show")
    await _open(parties, appt)

    with pytest.raises(DuplicateKeyError):
        await get_appointment_disputes_col().insert_one({
            "_id": f"dsp_{secrets.token_hex(6)}",
            "appointment_id": appt, "active_key": appt,
            "client_id": parties["client_id"], "lawyer_id": parties["lawyer_id"],
            "category": "incorrect_no_show", "statement": "second",
            "status": "open", "version": 0,
        })


async def test_a_resolved_report_frees_the_appointment_for_another(parties):
    """History accumulates; only one report at a time may be live."""
    appt = await _appt(parties, status="no_show")
    first = await _open(parties, appt)
    await _resolve(parties, first["id"], decision="confirm_no_show")

    second = await _open(parties, appt, statement="Still disagree.")

    assert second["id"] != first["id"]
    assert second["status"] == "open"


# ── 5. Decisions ─────────────────────────────────────────────────────────────

async def test_confirming_a_no_show_leaves_the_appointment_alone(parties):
    appt = await _appt(parties, status="no_show")
    dispute = await _open(parties, appt)

    resolved = await _resolve(parties, dispute["id"],
                              decision="confirm_no_show")

    assert resolved["status"] == "resolved"
    assert await _status(appt) == "no_show"


async def test_dismissing_a_report_leaves_the_appointment_alone(parties):
    appt = await _appt(parties, status="no_show")
    dispute = await _open(parties, appt)

    resolved = await _resolve(parties, dispute["id"],
                              decision="dismiss_report")

    assert resolved["status"] == "dismissed"
    assert await _status(appt) == "no_show"


async def test_correcting_a_no_show_completes_the_appointment(parties):
    appt = await _appt(parties, status="no_show")
    dispute = await _open(parties, appt)

    await _resolve(parties, dispute["id"], decision="correct_to_completed")

    assert await _status(appt) == "completed"


async def test_a_correction_grants_review_eligibility(parties):
    """The point of the whole workflow: the right `exists_completed` gates is
    restored, by a person, deliberately."""
    from app.repositories.appointment_repo import AppointmentRepository

    appt = await _appt(parties, status="no_show")
    dispute = await _open(parties, appt)

    assert await AppointmentRepository().exists_completed(
        parties["client_id"], parties["lawyer_id"]) is False

    await _resolve(parties, dispute["id"], decision="correct_to_completed")

    assert await AppointmentRepository().exists_completed(
        parties["client_id"], parties["lawyer_id"]) is True


async def test_an_unrecorded_outcome_can_be_corrected_too(parties):
    appt = await _appt(parties, status="confirmed", ended_hours_ago=5)
    dispute = await _open(parties, appt, category="outcome_not_recorded")

    await _resolve(parties, dispute["id"], decision="correct_to_completed")

    assert await _status(appt) == "completed"


async def test_a_correction_records_who_did_it_and_why(parties):
    from app.db.collections import get_appointments_col

    appt = await _appt(parties, status="no_show")
    dispute = await _open(parties, appt)

    await _resolve(parties, dispute["id"], decision="correct_to_completed")

    marker = (await get_appointments_col().find_one({"_id": appt}))["admin_correction"]
    assert marker["dispute_id"] == dispute["id"]
    assert marker["corrected_by"] == parties["admin_id"]


async def test_a_correction_fabricates_no_consultation_detail(parties):
    """Nobody here attended the consultation. Inventing a note or a joining
    link would put a claim about what happened into a legal record."""
    from app.db.collections import get_appointments_col

    appt = await _appt(parties, status="no_show")
    dispute = await _open(parties, appt)

    await _resolve(parties, dispute["id"], decision="correct_to_completed",
                   support_note=PRIVATE)

    row = await get_appointments_col().find_one({"_id": appt})
    assert row["lawyer_notes"] is None
    assert row["meeting_link"] is None
    assert "INTERNAL" not in repr(row)


@pytest.mark.parametrize("bad", ["", "   ", None])
async def test_a_decision_needs_a_public_explanation(parties, bad):
    appt = await _appt(parties, status="no_show")
    dispute = await _open(parties, appt)

    with pytest.raises(AppValidationError):
        await _resolve(parties, dispute["id"], decision="dismiss_report",
                       explanation=bad)


async def test_an_unknown_decision_is_refused(parties):
    appt = await _appt(parties, status="no_show")
    dispute = await _open(parties, appt)

    with pytest.raises(AppValidationError):
        await _resolve(parties, dispute["id"], decision="delete_everything")


# ── 6. Races ─────────────────────────────────────────────────────────────────

async def test_a_stale_version_is_refused(parties):
    appt = await _appt(parties, status="no_show")
    dispute = await _open(parties, appt)

    with pytest.raises((ConflictError, AppValidationError)):
        await _resolve(parties, dispute["id"], decision="dismiss_report",
                       version=7)

    assert (await disputes.get_for_support(dispute["id"]))["status"] == "open"


async def test_a_missing_version_is_refused(parties):
    appt = await _appt(parties, status="no_show")
    dispute = await _open(parties, appt)

    with pytest.raises(AppValidationError):
        await disputes.resolve_dispute(
            dispute_id=dispute["id"], actor_id=parties["admin_id"],
            actor_role="admin", expected_version=None,
            decision="dismiss_report", explanation="x")


async def test_two_admins_deciding_at_once_produce_one_winner(parties):
    appt = await _appt(parties, status="no_show")
    dispute = await _open(parties, appt)

    results = await asyncio.gather(
        _resolve(parties, dispute["id"], decision="confirm_no_show",
                 explanation="Kept."),
        _resolve(parties, dispute["id"], decision="dismiss_report",
                 explanation="Dropped."),
        return_exceptions=True)

    ok = [r for r in results if not isinstance(r, Exception)]
    clashed = [r for r in results if isinstance(r, ConflictError)]
    assert len(ok) == 1, results
    assert len(clashed) == 1, results


async def test_an_appointment_changed_under_a_correction_is_a_clean_conflict(parties):
    """A lawyer recording the outcome themselves while support is deciding is
    not an error to overwrite — it is their own record of their consultation."""
    from app.db.collections import get_appointments_col

    appt = await _appt(parties, status="no_show")
    dispute = await _open(parties, appt)
    await get_appointments_col().update_one(
        {"_id": appt}, {"$set": {"status": "completed"}})

    with pytest.raises(ConflictError):
        await _resolve(parties, dispute["id"], decision="correct_to_completed")

    assert (await disputes.get_for_support(dispute["id"]))["status"] == "open"


async def test_a_crash_between_correction_and_resolution_is_recoverable(parties):
    """THE RECOVERY PATH.

    The appointment is corrected first and the dispute closed second, so a
    process dying in between leaves a corrected appointment and an OPEN
    complaint. That state is visible and finishable; the reverse order would
    leave a closed complaint whose correction never happened, with nothing open
    to signal it.
    """
    from app.db.collections import get_appointment_disputes_col

    appt = await _appt(parties, status="no_show")
    dispute = await _open(parties, appt)

    # The first attempt corrects the appointment, then "dies" before closing.
    real_resolve = disputes.dispute_repo.resolve

    async def _die(*a, **kw):
        raise RuntimeError("process died")

    disputes.dispute_repo.resolve = _die
    try:
        with pytest.raises(RuntimeError):
            await _resolve(parties, dispute["id"],
                           decision="correct_to_completed")
    finally:
        disputes.dispute_repo.resolve = real_resolve

    assert await _status(appt) == "completed", "precondition: correction landed"
    row = await get_appointment_disputes_col().find_one({"_id": dispute["id"]})
    assert row["status"] == "open", "precondition: the dispute is still open"

    # The retry finishes the job rather than refusing or correcting twice.
    finished = await _resolve(parties, dispute["id"],
                              decision="correct_to_completed")

    assert finished["status"] == "resolved"
    assert await _status(appt) == "completed"


# ── 7. Projections and privacy ───────────────────────────────────────────────

async def test_the_client_view_hides_the_private_support_note(parties):
    appt = await _appt(parties, status="no_show")
    dispute = await _open(parties, appt)
    await _resolve(parties, dispute["id"], decision="confirm_no_show",
                   explanation="We reviewed the record.",
                   support_note=PRIVATE)

    view = await disputes.get_for_client(dispute["id"], parties["client_id"])

    assert "support_note" not in view
    assert PRIVATE not in repr(view)
    assert view["resolution_explanation"] == "We reviewed the record."


async def test_the_client_view_hides_internal_mechanism(parties):
    appt = await _appt(parties, status="no_show")
    dispute = await _open(parties, appt)

    view = await disputes.get_for_client(dispute["id"], parties["client_id"])

    assert "active_key" not in view
    assert "_id" not in view


async def test_the_support_view_carries_the_private_note(parties):
    appt = await _appt(parties, status="no_show")
    dispute = await _open(parties, appt)
    await _resolve(parties, dispute["id"], decision="confirm_no_show",
                   support_note=PRIVATE)

    view = await disputes.get_for_support(dispute["id"])

    assert view["support_note"] == PRIVATE
    assert "active_key" not in view


async def test_the_projections_are_allowlists(parties):
    """A field added to this collection tomorrow must not appear in a client
    response because a denylist forgot it."""
    from app.db.collections import get_appointment_disputes_col

    appt = await _appt(parties, status="no_show")
    dispute = await _open(parties, appt)
    await get_appointment_disputes_col().update_one(
        {"_id": dispute["id"]},
        {"$set": {"internal_scoring": "SECRET", "reviewer_draft": "SECRET"}})

    view = await disputes.get_for_client(dispute["id"], parties["client_id"])
    support = await disputes.get_for_support(dispute["id"])

    assert "SECRET" not in repr(view)
    assert "SECRET" not in repr(support)


# ── 8. Notifications ─────────────────────────────────────────────────────────

async def _notices(user_id=None, kind=None):
    from app.db.collections import get_notifications_col

    query = {}
    if user_id:
        query["user_id"] = user_id
    if kind:
        query["type"] = kind
    return await get_notifications_col().find(query).to_list(length=50)


async def test_the_client_is_told_the_outcome(parties):
    appt = await _appt(parties, status="no_show")
    dispute = await _open(parties, appt)

    await _resolve(parties, dispute["id"], decision="confirm_no_show",
                   explanation="The record stands.", support_note=PRIVATE)

    notices = await _notices(parties["client_id"],
                             "appointment_dispute_resolved")
    assert len(notices) == 1
    assert "The record stands." in notices[0]["body"]
    assert PRIVATE not in repr(notices)


async def test_the_lawyer_is_told_only_about_a_correction(parties):
    appt = await _appt(parties, status="no_show")
    dispute = await _open(parties, appt)

    await _resolve(parties, dispute["id"], decision="confirm_no_show")

    assert await _notices(parties["lawyer_id"],
                          "appointment_record_corrected") == []


async def test_a_correction_tells_the_lawyer_without_the_clients_words(parties):
    """Handing a lawyer the client's free text tells them a client complained
    about them, in the client's own words, whatever the outcome."""
    appt = await _appt(parties, status="no_show")
    dispute = await _open(parties, appt)

    await _resolve(parties, dispute["id"], decision="correct_to_completed",
                   support_note=PRIVATE)

    notices = await _notices(parties["lawyer_id"],
                             "appointment_record_corrected")
    assert len(notices) == 1
    blob = repr(notices)
    assert NOTE not in blob
    assert PRIVATE not in blob


async def test_notifications_are_deduplicated_per_dispute(parties):
    appt = await _appt(parties, status="no_show")
    dispute = await _open(parties, appt)

    await _resolve(parties, dispute["id"], decision="confirm_no_show")

    ids = [n.get("logical_event_id") for n in
           await _notices(parties["client_id"], "appointment_dispute_resolved")]
    assert ids == [f"dispute:{dispute['id']}:resolved:client"]


async def test_a_notification_failure_does_not_undo_the_decision(parties):
    """Best-effort and AFTER the fact: the decision is committed, and a
    delivery failure must not report it as having failed."""
    from app.services import notification_service

    appt = await _appt(parties, status="no_show")
    dispute = await _open(parties, appt)

    async def _boom(**kwargs):
        raise RuntimeError("notifications down")

    real = notification_service.create_notification
    notification_service.create_notification = _boom
    try:
        resolved = await _resolve(parties, dispute["id"],
                                  decision="correct_to_completed")
    finally:
        notification_service.create_notification = real

    assert resolved["status"] == "resolved"
    assert await _status(appt) == "completed"


# ── 9. The support queue ─────────────────────────────────────────────────────

async def test_the_queue_lists_open_reports_oldest_first(parties):
    made = []
    for i in range(3):
        appt = await _appt(parties, status="no_show")
        made.append((await _open(parties, appt))["id"])

    page = await disputes.list_open(page=1, page_size=10)

    ids = [d["id"] for d in page["items"]]
    assert ids == made


async def test_the_queue_excludes_decided_reports(parties):
    appt = await _appt(parties, status="no_show")
    dispute = await _open(parties, appt)
    await _resolve(parties, dispute["id"], decision="dismiss_report")

    page = await disputes.list_open(page=1, page_size=10)

    assert all(d["id"] != dispute["id"] for d in page["items"])


async def test_the_queue_pages_beyond_fifty(parties):
    """A support queue that silently showed the first fifty is a queue whose
    tail is never worked, and the oldest complaint has waited longest."""
    for i in range(55):
        appt = await _appt(parties, status="no_show")
        await _open(parties, appt)

    first = await disputes.list_open(page=1, page_size=25)
    second = await disputes.list_open(page=2, page_size=25)
    third = await disputes.list_open(page=3, page_size=25)

    assert first["total"] >= 55
    assert first["pages"] >= 3
    walked = ([d["id"] for d in first["items"]]
              + [d["id"] for d in second["items"]]
              + [d["id"] for d in third["items"]])
    assert len(walked) == len(set(walked)) >= 55


@pytest.mark.parametrize("bad", [0, -1, "1", None, 1.5])
async def test_an_unusable_page_is_refused(parties, bad):
    with pytest.raises(AppValidationError):
        await disputes.list_open(page=bad, page_size=10)


# ── 10. The HTTP boundary ────────────────────────────────────────────────────
#
# The service is tested directly above, deliberately: a rule that holds only
# because a response model omitted a field is a rule that vanishes the moment
# anything calls the service another way. These tests are about who may reach
# each endpoint and what actually crosses the wire.


@pytest.fixture
async def http(parties):
    import httpx
    from httpx import ASGITransport

    from app.dependencies import get_current_user, require_admin, require_client
    from app.main import app

    state = {"user": None}

    async def _current():
        user = state["user"]
        if user is None:
            from fastapi import HTTPException
            raise HTTPException(status_code=401, detail="not authenticated")
        return user

    def _role(required):
        async def _dep():
            user = await _current()
            if user.get("role") != required:
                from fastapi import HTTPException
                raise HTTPException(status_code=403, detail="forbidden")
            return user
        return _dep

    app.dependency_overrides[get_current_user] = _current
    app.dependency_overrides[require_client] = _role("client")
    app.dependency_overrides[require_admin] = _role("admin")
    async with httpx.AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test/api/v1") as client:
        client.act_as = lambda user: state.__setitem__("user", user)
        yield client
    app.dependency_overrides.clear()


def _as(role, user_id):
    return {"_id": user_id, "role": role, "is_active": True}


async def test_a_client_files_a_report_over_http(http, parties):
    appt = await _appt(parties, status="no_show")
    http.act_as(_as("client", parties["client_id"]))

    r = await http.post(f"/appointments/{appt}/disputes",
                        json={"category": "incorrect_no_show",
                              "statement": NOTE})

    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "open"
    assert body["statement"] == NOTE
    assert "support_note" not in body


async def test_filing_over_http_changes_no_appointment(http, parties):
    from app.db.collections import get_appointments_col

    appt = await _appt(parties, status="no_show")
    before = await get_appointments_col().find_one({"_id": appt})
    http.act_as(_as("client", parties["client_id"]))

    await http.post(f"/appointments/{appt}/disputes",
                    json={"category": "incorrect_no_show", "statement": NOTE})

    assert await get_appointments_col().find_one({"_id": appt}) == before


async def test_a_lawyer_cannot_file_a_report(http, parties):
    appt = await _appt(parties, status="no_show")
    http.act_as(_as("lawyer", parties["lawyer_id"]))

    r = await http.post(f"/appointments/{appt}/disputes",
                        json={"category": "incorrect_no_show",
                              "statement": NOTE})

    assert r.status_code == 403


async def test_another_client_gets_the_generic_denial(http, parties):
    """Not a 403 that confirms the appointment exists — the same answer an
    unknown id gets, so the endpoint cannot be used to discover appointments."""
    appt = await _appt(parties, status="no_show")
    http.act_as(_as("client", parties["other_client"]))

    real = await http.post(f"/appointments/{appt}/disputes",
                           json={"category": "incorrect_no_show",
                                 "statement": NOTE})
    fake = await http.post("/appointments/DS-AP-nope/disputes",
                           json={"category": "incorrect_no_show",
                                 "statement": NOTE})

    assert real.status_code == fake.status_code == 404


async def test_the_support_queue_is_closed_to_clients_and_lawyers(http, parties):
    appt = await _appt(parties, status="no_show")
    await _open(parties, appt)

    for role, user in (("client", parties["client_id"]),
                       ("lawyer", parties["lawyer_id"])):
        http.act_as(_as(role, user))
        assert (await http.get("/admin/appointment-disputes")).status_code == 403


async def test_an_anonymous_caller_is_refused(http, parties):
    http.act_as(None)

    assert (await http.get("/admin/appointment-disputes")).status_code == 401
    assert (await http.post("/appointments/x/disputes",
                            json={"category": "incorrect_no_show",
                                  "statement": NOTE})).status_code == 401


async def test_support_works_the_queue_over_http(http, parties):
    appt = await _appt(parties, status="no_show")
    dispute = await _open(parties, appt)
    http.act_as(_as("admin", parties["admin_id"]))

    queue = await http.get("/admin/appointment-disputes")
    assert queue.status_code == 200
    assert any(d["id"] == dispute["id"] for d in queue.json()["items"])

    decided = await http.patch(
        f"/admin/appointment-disputes/{dispute['id']}",
        json={"expected_version": 0, "decision": "correct_to_completed",
              "resolution_explanation": "Record corrected after review.",
              "support_note": PRIVATE})

    assert decided.status_code == 200, decided.text
    assert decided.json()["status"] == "resolved"
    assert await _status(appt) == "completed"


async def test_a_stale_version_is_a_conflict_over_http(http, parties):
    appt = await _appt(parties, status="no_show")
    dispute = await _open(parties, appt)
    http.act_as(_as("admin", parties["admin_id"]))

    await http.patch(f"/admin/appointment-disputes/{dispute['id']}",
                     json={"expected_version": 0, "decision": "dismiss_report",
                           "resolution_explanation": "First."})
    again = await http.patch(
        f"/admin/appointment-disputes/{dispute['id']}",
        json={"expected_version": 0, "decision": "confirm_no_show",
              "resolution_explanation": "Second."})

    assert again.status_code == 409


async def test_the_version_is_required_over_http(http, parties):
    appt = await _appt(parties, status="no_show")
    dispute = await _open(parties, appt)
    http.act_as(_as("admin", parties["admin_id"]))

    r = await http.patch(f"/admin/appointment-disputes/{dispute['id']}",
                         json={"decision": "dismiss_report",
                               "resolution_explanation": "No version."})

    assert r.status_code == 422


async def test_the_private_note_never_crosses_the_client_boundary(http, parties):
    """Asserted on the WIRE, not only on the projection: the response model
    declares the field for support, so only the service's allowlist keeps it
    out of a client's response."""
    appt = await _appt(parties, status="no_show")
    dispute = await _open(parties, appt)
    await _resolve(parties, dispute["id"], decision="confirm_no_show",
                   explanation="Reviewed.", support_note=PRIVATE)

    http.act_as(_as("client", parties["client_id"]))
    r = await http.get(f"/appointments/{appt}/disputes")

    assert r.status_code == 200
    assert PRIVATE not in r.text
    assert "support_note" not in r.text
    assert "Reviewed." in r.text


async def test_an_identical_retry_over_http_returns_the_same_report(http, parties):
    appt = await _appt(parties, status="no_show")
    http.act_as(_as("client", parties["client_id"]))
    body = {"category": "incorrect_no_show", "statement": NOTE}

    first = await http.post(f"/appointments/{appt}/disputes", json=body)
    second = await http.post(f"/appointments/{appt}/disputes", json=body)

    assert first.json()["id"] == second.json()["id"]


async def test_a_conflicting_retry_over_http_is_a_conflict(http, parties):
    appt = await _appt(parties, status="no_show")
    http.act_as(_as("client", parties["client_id"]))

    await http.post(f"/appointments/{appt}/disputes",
                    json={"category": "incorrect_no_show", "statement": NOTE})
    other = await http.post(f"/appointments/{appt}/disputes",
                            json={"category": "incorrect_no_show",
                                  "statement": "Something else entirely."})

    assert other.status_code == 409


async def test_the_queue_pages_over_http(http, parties):
    for _ in range(30):
        appt = await _appt(parties, status="no_show")
        await _open(parties, appt)
    http.act_as(_as("admin", parties["admin_id"]))

    first = await http.get("/admin/appointment-disputes",
                           params={"page": 1, "page_size": 25})
    second = await http.get("/admin/appointment-disputes",
                            params={"page": 2, "page_size": 25})

    assert first.json()["total"] >= 30
    assert first.json()["pages"] >= 2
    ids = {d["id"] for d in first.json()["items"]} | {
        d["id"] for d in second.json()["items"]}
    assert len(ids) >= 30
