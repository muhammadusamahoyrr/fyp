"""A case begins as a draft and becomes real only when the client says so.

WHAT THIS CHANGES

Intake needs a real `case_id` before the client has confirmed anything: the
analysis pipeline is bound to one and provenance records it. So the case has to
exist early — and it used to exist as OPEN. The client was then invited to
"review and confirm your structured case before saving" a case that was already
live, and the Confirm button showed a toast and advanced the screen. It called
nothing, because there was nothing left to do.

A draft is a case that exists for the analysis and for nothing else. The three
things it must not be — sent to a lawyer, matched, booked against — are three
separate call sites, so the rule lives in `assert_not_draft` and each of them is
tested against it here rather than trusting one helper to be wired everywhere.

Run against the real database: the promotion is a conditional update, and
"exactly one of two clicks performed it" is a claim about stored state.
"""
from __future__ import annotations

import asyncio
import secrets
from datetime import datetime, timedelta, timezone

import pytest

from app.core.constants import AppointmentMode, CaseStatus
from app.core.exceptions import AppValidationError, ConflictError, ForbiddenError, NotFoundError
from app.services import (
    appointment_service,
    case_service,
    engagement_service,
    intake_service,
)

pytestmark = pytest.mark.integration

# There is no post-confirmation matcher to capture or stub any more.
# Matching is computed live by `/lawyers/match`, so the tests below spy
# directly on `lawyer_service.match_lawyers_for_case` — the expensive call
# itself — rather than on a wrapper that could be deleted without a single
# test noticing.


@pytest.fixture
async def party(app_indexes):
    """A client, a verified lawyer, and a clean slate."""
    from app.db.collections import (
        get_appointments_col, get_cases_col, get_engagements_col,
        get_intakes_col, get_users_col,
    )

    tag = secrets.token_hex(4)
    client_id, lawyer_id = f"DR-C-{tag}", f"DR-L-{tag}"
    now = datetime.now(timezone.utc)

    await get_users_col().insert_many([
        {"_id": client_id, "role": "client", "is_active": True,
         "email": f"dr-c-{tag}@test.invalid", "full_name": "Draft Client",
         "province": "punjab", "created_at": now},
        {"_id": lawyer_id, "role": "lawyer", "is_active": True,
         "email": f"dr-l-{tag}@test.invalid", "full_name": "Adv Draft",
         "province": "punjab", "created_at": now,
         "lawyer_profile": {"specializations": ["civil"], "kyc_verified": True,
                            "rating": 4.2, "total_reviews": 5,
                            "availability": True, "experience_years": 8}},
    ])

    yield {"client_id": client_id, "lawyer_id": lawyer_id, "tag": tag}

    await get_users_col().delete_many({"_id": {"$in": [client_id, lawyer_id]}})
    await get_cases_col().delete_many({"client_id": client_id})
    await get_engagements_col().delete_many({"client_id": client_id})
    await get_appointments_col().delete_many({"client_id": client_id})
    await get_intakes_col().delete_many({"client_id": client_id})


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    async def classify(description, user_selected):
        return user_selected, False

    async def run_ai(**kw):
        return {"summary": "A tenancy claim.", "applicable_laws": [],
                "recommended_actions": [], "risk_level": "medium",
                "grounded": False, "grounding_status": "stubbed_in_test"}

    monkeypatch.setattr(intake_service, "_ai_classify_case_type", classify)
    monkeypatch.setattr(intake_service, "_run_intake_ai", run_ai)
    try:
        from app.ai import lawyer_embeddings
        monkeypatch.setattr(lawyer_embeddings, "schedule_embed", lambda _id: False)
    except Exception:
        pass


async def _draft(party) -> str:
    """A draft case, made the way a case is really made: through the intake."""
    started = await intake_service.start_intake(party["client_id"])
    token = started["session_token"]
    cid = party["client_id"]
    await intake_service.save_step(token, 1, {"province": "punjab",
                                              "party_role": "plaintiff"}, cid)
    await intake_service.save_step(token, 2, {"case_type": "civil",
                                              "urgency": "medium"}, cid)
    await intake_service.save_step(token, 3, {
        "incident_description": "My landlord seized my shop in Lahore."}, cid)
    await intake_service.save_step(token, 4, {"has_evidence": False}, cid)
    await intake_service.save_step(token, 5, {
        "desired_outcome": "Recover possession"}, cid)
    result = await intake_service.convert_to_case(token, cid)
    return result["case_id"]


async def _case(case_id) -> dict:
    from app.db.collections import get_cases_col
    return await get_cases_col().find_one({"_id": case_id})


# ── draft creation ──────────────────────────────────────────────────────────

async def test_intake_produces_a_draft_not_an_open_case(party):
    case_id = await _draft(party)
    assert (await _case(case_id))["status"] == CaseStatus.DRAFT.value


async def test_the_analysis_ran_against_the_real_case_id(party, monkeypatch):
    """The reason the case must exist before confirmation.

    The pipeline is bound to a `case_id` and provenance records it, so deferring
    creation entirely would mean analysing a case that does not exist.
    """
    seen = {}

    async def capture(**kw):
        seen["case_id"] = kw["case_id"]
        return {"summary": "ok", "applicable_laws": [], "recommended_actions": [],
                "risk_level": "medium", "grounded": False,
                "grounding_status": "stubbed_in_test"}

    monkeypatch.setattr(intake_service, "_run_intake_ai", capture)
    case_id = await _draft(party)

    assert seen["case_id"] == case_id
    assert await _case(case_id) is not None


async def test_a_draft_still_belongs_to_its_client(party):
    case_id = await _draft(party)
    case = await case_service.get_case(case_id, party["client_id"], "client")
    assert case["status"] == CaseStatus.DRAFT.value


async def test_a_direct_case_creation_is_still_open(party):
    """Only intake makes drafts. `POST /cases` is unchanged."""
    made = await case_service.create_case(party["client_id"], {
        "case_type": "civil", "province": "punjab",
        "title": "direct", "description": "…"})
    assert made["status"] == CaseStatus.OPEN.value


# ── a draft is excluded from every lawyer flow ─────────────────────────────

async def test_a_draft_cannot_be_sent_to_a_lawyer(party):
    case_id = await _draft(party)
    with pytest.raises(AppValidationError) as exc:
        await engagement_service.request_engagement(
            party["client_id"],
            {"case_id": case_id, "lawyer_id": party["lawyer_id"], "message": None})
    assert "draft" in str(exc.value.detail).lower()


async def test_a_draft_cannot_be_matched(party):
    from app.services import lawyer_service

    case_id = await _draft(party)
    with pytest.raises(AppValidationError):
        await lawyer_service.match_lawyers_for_case(case_id, top_n=5)


async def test_a_draft_cannot_be_booked_against(party):
    case_id = await _draft(party)
    when = (datetime.now(timezone.utc) + timedelta(days=3)).replace(
        hour=11, minute=0, second=0, microsecond=0)
    with pytest.raises(AppValidationError):
        await appointment_service.book_appointment(
            client_id=party["client_id"], lawyer_id=party["lawyer_id"],
            case_id=case_id, scheduled_at=when, duration_minutes=30,
            mode=AppointmentMode.VIDEO, notes=None)


async def test_conversion_does_not_run_the_matcher(party, monkeypatch):
    """Matching moved to confirmation. Running it here would rank lawyers
    against a case the client may never confirm.

    Spies on `match_lawyers_for_case` — the expensive thing that must not run —
    rather than on the wrapper that used to call it. The first version of this
    test patched `intake_service._auto_match_lawyers` and asserted it was not
    called; that function had no callers left, so the assertion was true no
    matter what conversion did. A test satisfied by an accident is not a test.
    """
    from app.services import lawyer_service

    calls = {"n": 0}

    async def counted(case_id, top_n=5):
        calls["n"] += 1
        return {"result_kind": "none", "notice": "", "matches": []}

    monkeypatch.setattr(lawyer_service, "match_lawyers_for_case", counted)
    await _draft(party)
    await asyncio.sleep(0)
    assert calls["n"] == 0, "conversion ran the matcher against an unconfirmed case"


# ── confirmation ────────────────────────────────────────────────────────────

async def test_confirmation_promotes_the_draft_to_open(party):
    case_id = await _draft(party)
    result = await case_service.confirm_case(case_id, party["client_id"])

    assert result["status"] == CaseStatus.OPEN.value
    assert (await _case(case_id))["status"] == CaseStatus.OPEN.value


async def test_confirmation_records_when_it_happened(party):
    case_id = await _draft(party)
    await case_service.confirm_case(case_id, party["client_id"])
    assert (await _case(case_id))["confirmed_at"] is not None


async def test_confirmation_stores_the_final_category_in_the_same_transition(party):
    case_id = await _draft(party)
    result = await case_service.confirm_case(
        case_id, party["client_id"], "criminal"
    )
    stored = await _case(case_id)
    assert result["status"] == CaseStatus.OPEN.value
    assert stored["case_type"] == "criminal"
    assert stored["case_type_source"] == "client"
    assert stored["case_type_changed_by"] == party["client_id"]


async def test_confirm_replay_cannot_rewrite_an_open_cases_category(party):
    case_id = await _draft(party)
    await case_service.confirm_case(case_id, party["client_id"], "criminal")
    with pytest.raises(ConflictError):
        await case_service.confirm_case(case_id, party["client_id"], "family")
    assert (await _case(case_id))["case_type"] == "criminal"


async def test_confirmation_is_idempotent(party):
    """A second press is the client asking for something already true."""
    case_id = await _draft(party)
    first = await case_service.confirm_case(case_id, party["client_id"])
    second = await case_service.confirm_case(case_id, party["client_id"])

    assert first["status"] == second["status"] == CaseStatus.OPEN.value


async def test_two_simultaneous_confirmations_both_succeed(party):
    """A double-clicked button must not produce an error for the second click."""
    case_id = await _draft(party)
    a, b = await asyncio.gather(
        case_service.confirm_case(case_id, party["client_id"]),
        case_service.confirm_case(case_id, party["client_id"]),
        return_exceptions=True,
    )
    for outcome in (a, b):
        assert not isinstance(outcome, Exception), outcome
        assert outcome["status"] == CaseStatus.OPEN.value


async def test_two_simultaneous_different_categories_do_not_both_claim_success(party):
    """Only the category that won the atomic promotion may report success."""
    case_id = await _draft(party)
    outcomes = await asyncio.gather(
        case_service.confirm_case(case_id, party["client_id"], "criminal"),
        case_service.confirm_case(case_id, party["client_id"], "family"),
        return_exceptions=True,
    )

    successes = [item for item in outcomes if not isinstance(item, Exception)]
    conflicts = [item for item in outcomes if isinstance(item, ConflictError)]
    assert len(successes) == 1
    assert len(conflicts) == 1
    stored = await _case(case_id)
    assert successes[0]["case_type"] == stored["case_type"]
    assert stored["case_type"] in {"criminal", "family"}


async def test_a_stranger_cannot_confirm_someone_elses_case(party):
    case_id = await _draft(party)
    with pytest.raises(ForbiddenError):
        await case_service.confirm_case(case_id, "DR-STRANGER")
    assert (await _case(case_id))["status"] == CaseStatus.DRAFT.value


async def test_confirming_a_missing_case_is_not_found(party):
    with pytest.raises(NotFoundError):
        await case_service.confirm_case("no-such-case", party["client_id"])


# ── invalid transitions ────────────────────────────────────────────────────

@pytest.mark.parametrize("status", [
    CaseStatus.CLOSED.value,
    CaseStatus.DISMISSED.value,
    CaseStatus.IN_PROGRESS.value,
])
async def test_only_a_draft_can_be_confirmed(party, status):
    from app.db.collections import get_cases_col

    case_id = await _draft(party)
    await get_cases_col().update_one({"_id": case_id}, {"$set": {"status": status}})

    with pytest.raises(AppValidationError) as exc:
        await case_service.confirm_case(case_id, party["client_id"])
    assert status in str(exc.value.detail)


# ── after confirmation the case behaves normally ───────────────────────────

async def test_a_confirmed_case_can_be_sent_to_a_lawyer(party):
    case_id = await _draft(party)
    await case_service.confirm_case(case_id, party["client_id"])

    eng = await engagement_service.request_engagement(
        party["client_id"],
        {"case_id": case_id, "lawyer_id": party["lawyer_id"], "message": None})
    assert eng["case_id"] == case_id


async def test_confirmation_does_not_run_the_matcher_either(party, monkeypatch):
    """Matching is a QUERY, not a side effect of a write.

    Confirmation used to schedule a semantic match — an embedding pass and a
    vector query, CPU-bound on a box with no GPU — and cache the ranking on
    `case.matched_lawyers`. NOTHING read that field: every surface that shows
    matched lawyers calls `match_lawyers_for_case` for itself. So the cost bought
    a column with no reader, and keeping that column honest then meant spending
    it again on every category correction.

    Deferring the work was right while something consumed it. With no consumer,
    not doing it beats doing it later.
    """
    from app.services import lawyer_service

    calls = {"n": 0}

    async def counted(case_id, top_n=5):
        calls["n"] += 1
        return {"result_kind": "none", "notice": "", "matches": []}

    monkeypatch.setattr(lawyer_service, "match_lawyers_for_case", counted)

    case_id = await _draft(party)
    await case_service.confirm_case(case_id, party["client_id"])
    for _ in range(10):
        await asyncio.sleep(0)

    assert calls["n"] == 0, "confirmation spent a match nothing will read"


async def test_confirmation_schedules_no_background_work(party, monkeypatch):
    """Nothing is deferred off the confirmation any more.

    The obvious version of this test — confirm, then assert the stored case has
    no `matched_lawyers` — is VACUOUS, and was: reintroducing the scheduled
    matcher left it passing, because a backgrounded write is not guaranteed to
    have landed by the time the assertion runs. It asserted a race, not a rule.

    Counting `create_task` instead is deterministic, and it is the property that
    actually matters: the cost was the scheduling, whatever the task then wrote.
    """
    created = []
    real = asyncio.create_task

    def spy(coro, *a, **kw):
        created.append(getattr(coro, "__qualname__", repr(coro)))
        return real(coro, *a, **kw)

    case_id = await _draft(party)
    monkeypatch.setattr(asyncio, "create_task", spy)
    await case_service.confirm_case(case_id, party["client_id"])

    assert created == [], f"confirmation deferred work: {created}"


async def test_a_second_confirmation_does_not_re_stamp_the_time(party):
    """The guard against a double-click used to be observable through the
    matcher being scheduled exactly once. That signal is gone with the matcher.

    `confirmed_at` replaces it: it is set by the same conditional update, so it
    moves if and only if the transition runs again. `test_confirmation_is_
    idempotent` already covers the status the client sees; this covers the write
    underneath it.
    """
    case_id = await _draft(party)
    await case_service.confirm_case(case_id, party["client_id"])
    stamped = (await _case(case_id))["confirmed_at"]

    await case_service.confirm_case(case_id, party["client_id"])

    assert (await _case(case_id))["confirmed_at"] == stamped, (
        "the second press re-ran the transition")




# ── the guarantees this must not break ─────────────────────────────────────

async def test_one_intake_still_produces_exactly_one_case(party):
    from app.db.collections import get_cases_col

    case_id = await _draft(party)
    count = await get_cases_col().count_documents({"client_id": party["client_id"]})
    assert count == 1
    assert case_id


async def test_a_repeat_convert_still_replays(party):
    """Draft status must not disturb conversion idempotency."""
    started = await intake_service.start_intake(party["client_id"])
    token = started["session_token"]
    cid = party["client_id"]
    for step, data in [
        (1, {"province": "punjab"}), (2, {"case_type": "civil", "urgency": "medium"}),
        (3, {"incident_description": "A tenancy dispute."}),
        (4, {"has_evidence": False}), (5, {"desired_outcome": "Possession"}),
    ]:
        await intake_service.save_step(token, step, data, cid)

    first = await intake_service.convert_to_case(token, cid)
    second = await intake_service.convert_to_case(token, cid)
    assert first["case_id"] == second["case_id"]


async def test_the_orphan_crash_recovery_still_adopts_a_draft(party):
    """The recovery path must work on the status conversion now produces."""
    from app.db.collections import get_cases_col, get_intakes_col

    case_id = await _draft(party)
    # Simulate the crash: unpin the case, leaving the intake unaware of it.
    intake = await get_intakes_col().find_one({"case_id": case_id})
    await get_intakes_col().update_one(
        {"_id": intake["_id"]},
        {"$set": {"case_id": None, "completed": False},
         "$unset": {"conversion_claimed_at": ""}})

    again = await intake_service.convert_to_case(
        intake["session_token"], party["client_id"])

    assert again["case_id"] == case_id
    assert await get_cases_col().count_documents(
        {"intake_id": intake["_id"]}) == 1


# ── a category change costs nothing, because there is no cache to fix ───
#
# The staleness these tests were written for was real: confirmation cached a
# ranking built from the AI's guessed category, and the client's own
# correction was saved on the NEXT screen, so the cache described the
# category they had just rejected. Clearing and rebuilding it fixed that —
# by paying for a second embedding pass per correction, to keep a field with
# no reader accurate.
#
# Removing the cache removes the staleness AND the cost. What these tests
# guard now is that no write path reaches the matcher at all.

async def test_changing_the_category_persists_it(party):
    from app.db.collections import get_cases_col

    case_id = await _draft(party)
    await case_service.confirm_case(case_id, party["client_id"])
    await case_service.update_case(
        case_id, {"case_type": "family"}, party["client_id"], "client")

    stored = await get_cases_col().find_one({"_id": case_id})
    assert stored["case_type"] == "family"


async def test_changing_the_category_spends_no_match(party, monkeypatch):
    """The correction is a cheap write. It was the most expensive one here."""
    from app.services import lawyer_service

    calls = {"n": 0}

    async def counted(case_id, top_n=5):
        calls["n"] += 1
        return {"result_kind": "none", "notice": "", "matches": []}

    case_id = await _draft(party)
    await case_service.confirm_case(case_id, party["client_id"])

    monkeypatch.setattr(lawyer_service, "match_lawyers_for_case", counted)
    await case_service.update_case(
        case_id, {"case_type": "criminal"}, party["client_id"], "client")
    for _ in range(10):
        await asyncio.sleep(0)

    assert calls["n"] == 0


async def test_a_legacy_cached_ranking_is_left_alone(party):
    """Cases confirmed BEFORE this change still carry a `matched_lawyers` array.

    It is not cleared, on purpose: nothing reads it, so rewriting every such
    document would be a migration that changes no behaviour. This pins the
    choice, so a later reader knows the leftover is deliberate and not a
    clearing step someone dropped.
    """
    from app.db.collections import get_cases_col

    case_id = await _draft(party)
    await case_service.confirm_case(case_id, party["client_id"])
    await get_cases_col().update_one(
        {"_id": case_id},
        {"$set": {"matched_lawyers": [{"_id": "L-LEGACY", "full_name": "Old"}]}})

    await case_service.update_case(
        case_id, {"case_type": "family"}, party["client_id"], "client")

    stored = await get_cases_col().find_one({"_id": case_id})
    assert stored["matched_lawyers"] == [{"_id": "L-LEGACY", "full_name": "Old"}]





async def test_a_draft_category_change_never_matches(party, monkeypatch):
    """A draft must not be matched, however its category moves."""
    from app.services import lawyer_service

    calls = {"n": 0}

    async def counted(case_id, top_n=5):
        calls["n"] += 1
        return {"result_kind": "none", "notice": "", "matches": []}

    case_id = await _draft(party)
    monkeypatch.setattr(lawyer_service, "match_lawyers_for_case", counted)

    await case_service.update_case(
        case_id, {"case_type": "family"}, party["client_id"], "client")
    for _ in range(5):
        await asyncio.sleep(0)

    assert calls["n"] == 0



# ── the draft rule reaches every boundary, not three of them ────────────────

async def test_a_draft_cannot_have_documents_created_against_it(party):
    from app.services import document_v2_service

    case_id = await _draft(party)
    with pytest.raises(AppValidationError) as exc:
        await document_v2_service._require_case_access(party["client_id"], case_id)
    assert "draft" in str(exc.value.detail).lower()


async def test_a_draft_cannot_enter_the_active_legacy_document_path(party):
    from app.services import document_service

    case_id = await _draft(party)
    with pytest.raises(AppValidationError):
        await document_service.extract_fields(
            case_id, party["client_id"], "legal_notice"
        )
    with pytest.raises(AppValidationError):
        await document_service.generate_document(
            case_id, party["client_id"], "legal_notice", {"facts": "x"}
        )


async def test_standalone_document_drafting_is_unaffected(party):
    """`case_id` of None is a real flow — a template with no case yet."""
    from app.services import document_v2_service

    await document_v2_service._require_case_access(party["client_id"], None)


async def test_a_confirmed_case_can_have_documents_created_against_it(party):
    from app.services import document_v2_service

    case_id = await _draft(party)
    await case_service.confirm_case(case_id, party["client_id"])
    await document_v2_service._require_case_access(party["client_id"], case_id)
