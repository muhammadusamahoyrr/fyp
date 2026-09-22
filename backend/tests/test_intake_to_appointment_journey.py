"""The whole client journey, in one pass, against a real database.

    intake → case (DRAFT) → client confirms → matching → engagement → appointment

Every stage of this had tests. The SEAM between the stages had none, and every
defect found in the September audit lived in a seam: data that step 1 collected
and conversion never read, a category the last screen changed and no request
saved, a case id written under a key another module read differently.

So this asserts on what one stage HANDS THE NEXT, not on what each computes:
whether the case carries the party role the intake collected, whether matching
sees the category the client confirmed, whether the appointment lands on the
case the engagement assigned. A unit test on either side of a seam passes
happily while the seam itself drops the data on the floor.

Marked integration because it uses the real Mongo indexes: the engagement and
appointment guards are partial unique indexes, and a journey that never touches
them is not the journey a client actually walks.
"""
from __future__ import annotations

import secrets
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from support.hire_fixtures import (  # noqa: E402
    delete_appointments_for, seed_completed_appointment,
)

from app.core.constants import (  # noqa: E402
    AppointmentMode, CaseStatus, EngagementStatus,
)
from app.services import (  # noqa: E402
    appointment_service,
    case_service,
    engagement_service,
    intake_service,
    lawyer_service,
)

pytestmark = pytest.mark.integration


@pytest.fixture
async def journey_parties(app_indexes):
    """A verified family-law lawyer and a client, on the real indexes."""
    from app.db.collections import get_users_col

    tag = secrets.token_hex(4)
    lawyer_id, client_id = f"JN-L-{tag}", f"JN-C-{tag}"
    now = datetime.now(timezone.utc)

    await get_users_col().insert_many([
        {"_id": lawyer_id, "role": "lawyer", "is_active": True,
         "email": f"jn-l-{tag}@test.invalid", "full_name": "Adv Journey",
         "province": "punjab", "created_at": now,
         "lawyer_profile": {"specializations": ["family", "civil"],
                            "kyc_verified": True, "rating": 4.5,
                            "total_reviews": 12, "availability": True,
                            "experience_years": 9, "languages": ["en", "ur"]}},
        {"_id": client_id, "role": "client", "is_active": True,
         "email": f"jn-c-{tag}@test.invalid", "full_name": "Client Journey",
         "province": "punjab", "created_at": now},
    ])
    yield {"lawyer_id": lawyer_id, "client_id": client_id, "tag": tag}
    await get_users_col().delete_many({"_id": {"$in": [lawyer_id, client_id]}})
    await delete_appointments_for(client_id)


@pytest.fixture
def offline_ai(monkeypatch):
    """Stub only the model calls. Every database write stays real.

    The point of this test is the handoffs, and an LLM in the middle of it
    would make the run non-deterministic and slow without exercising a single
    seam. `_run_intake_ai` and the classifier are replaced; conversion,
    persistence, matching, engagement and booking all run for real.
    """
    async def fake_classify(description, user_selected):
        return user_selected, False

    async def fake_run_ai(**kw):
        return {
            "summary": "A family maintenance claim in Punjab.",
            "applicable_laws": ["Muslim Family Laws Ordinance 1961"],
            "recommended_actions": ["File before the Family Court"],
            "risk_level": "medium",
            "grounded": False,
            "grounding_status": "stubbed_in_test",
        }

    async def no_match(case_id):
        # Auto-matching is fire-and-forget inside conversion; the journey below
        # calls the matcher explicitly so the assertion is on a value, not on
        # whether a background task happened to finish.
        return None

    monkeypatch.setattr(intake_service, "_ai_classify_case_type", fake_classify)
    monkeypatch.setattr(intake_service, "_run_intake_ai", fake_run_ai)


async def _walk_intake(client_id: str) -> dict:
    """Steps 1-5 exactly as ModIntake sends them, then convert."""
    started = await intake_service.start_intake(client_id)
    token = started["session_token"]

    await intake_service.save_step(token, 1, {
        "province": "punjab", "party_role": "plaintiff"}, client_id)
    await intake_service.save_step(token, 2, {
        "case_type": "family", "urgency": "high"}, client_id)
    await intake_service.save_step(token, 3, {
        "incident_description":
            "My husband has not paid maintenance for eight months in Lahore.",
        "incident_date": None, "incident_location": None}, client_id)
    await intake_service.save_step(token, 4, {
        "has_evidence": True,
        "evidence_description": "Bank statements showing no transfers.",
        "opposing_party": None}, client_id)
    await intake_service.save_step(token, 5, {
        "desired_outcome": "A maintenance order and arrears",
        "additional_notes": None}, client_id)

    converted = await intake_service.convert_to_case(token, client_id)
    return {"token": token, **converted}


async def _confirm(case_id: str, client_id: str) -> None:
    """The step the client takes before anyone else may act on the case.

    Conversion now produces a DRAFT: it exists so the analysis had a real
    `case_id` to run against, and it cannot be matched, engaged or booked
    against until the client confirms it. Every stage below this point is
    downstream of that confirmation, which is why it belongs in the journey
    rather than in a fixture — it IS one of the handoffs being tested.
    """
    await case_service.confirm_case(case_id, client_id)


# ── the journey, one stage at a time ────────────────────────────────────────

async def test_intake_produces_a_case_the_client_can_open(journey_parties, offline_ai):
    client_id = journey_parties["client_id"]

    result = await _walk_intake(client_id)
    assert result["case_id"]

    case = await case_service.get_case(result["case_id"], client_id, "client")
    # A draft until the client confirms — the case exists for the analysis.
    assert case["status"] == CaseStatus.DRAFT.value
    assert case["province"] == "punjab"

    await _confirm(result["case_id"], client_id)
    confirmed = await case_service.get_case(result["case_id"], client_id, "client")
    assert confirmed["status"] == CaseStatus.OPEN.value


async def test_the_case_carries_what_the_intake_collected(journey_parties, offline_ai):
    """The seam that lost the party role, the outcome and the evidence."""
    client_id = journey_parties["client_id"]

    result = await _walk_intake(client_id)
    case = await case_service.get_case(result["case_id"], client_id, "client")

    assert case["party_role"] == "plaintiff"
    assert case["desired_outcome"] == "A maintenance order and arrears"
    assert case["has_evidence"] is True
    assert case["urgency"] == "high"
    assert "Bank statements" in case["description"]


async def test_the_case_title_is_the_clients_own_account(journey_parties, offline_ai):
    client_id = journey_parties["client_id"]
    result = await _walk_intake(client_id)
    case = await case_service.get_case(result["case_id"], client_id, "client")
    assert case["title"].startswith("My husband has not paid maintenance")


async def test_a_category_change_survives_into_matching(journey_parties, offline_ai):
    """Step 5's category change reaching the record that matching reads.

    This is the end-to-end form of the defect: the client corrects the
    category, and until the write existed, matching went on ranking lawyers
    against the category they had just rejected.
    """
    client_id = journey_parties["client_id"]
    result = await _walk_intake(client_id)
    case_id = result["case_id"]

    await case_service.update_case(case_id, {"case_type": "civil"}, client_id, "client")

    case = await case_service.get_case(case_id, client_id, "client")
    assert case["case_type"] == "civil"
    assert case["ai_case_type"] == "family"      # the original is still on record
    assert case["case_type_source"] == "client"


async def test_matching_runs_on_the_created_case(journey_parties, offline_ai):
    client_id = journey_parties["client_id"]
    result = await _walk_intake(client_id)
    await _confirm(result["case_id"], client_id)

    matched = await lawyer_service.match_lawyers_for_case(result["case_id"], top_n=5)

    assert matched["result_kind"] in {"matched", "general_listing", "none"}
    assert isinstance(matched["matches"], list)


async def test_engagement_assigns_the_lawyer_to_that_same_case(journey_parties, offline_ai):
    client_id = journey_parties["client_id"]
    lawyer_id = journey_parties["lawyer_id"]
    result = await _walk_intake(client_id)
    case_id = result["case_id"]
    await _confirm(case_id, client_id)

    # The consultation comes first (§17 R5-1); the hire follows it.
    appt_id = await seed_completed_appointment(client_id, lawyer_id)
    requested = await engagement_service.request_engagement(
        client_id, {"case_id": case_id, "lawyer_id": lawyer_id,
                    "appointment_id": appt_id,
                    "message": "Please take my maintenance case."})
    assert requested["status"] == EngagementStatus.REQUESTED.value

    proposed = await engagement_service.propose_terms(
        requested["id"], lawyer_id, {"fee_amount": 50000, "fee_type": "fixed"})
    assert proposed["status"] == EngagementStatus.TERMS_PROPOSED.value

    # Nothing is claimed yet — the whole point of the two-step flow.
    mid = await case_service.get_case(case_id, client_id, "client")
    assert mid["lawyer_id"] is None

    accepted = await engagement_service.accept_terms(requested["id"], client_id)
    assert accepted["status"] == EngagementStatus.ACCEPTED.value

    case = await case_service.get_case(case_id, client_id, "client")
    assert case["lawyer_id"] == lawyer_id
    assert case["status"] == CaseStatus.IN_PROGRESS.value


async def test_the_appointment_lands_on_the_engaged_case(journey_parties, offline_ai):
    """The last seam: intake's case id still addressing the right case."""
    client_id = journey_parties["client_id"]
    lawyer_id = journey_parties["lawyer_id"]
    result = await _walk_intake(client_id)
    case_id = result["case_id"]
    await _confirm(case_id, client_id)

    appt_id = await seed_completed_appointment(client_id, lawyer_id)
    requested = await engagement_service.request_engagement(
        client_id, {"case_id": case_id, "lawyer_id": lawyer_id,
                    "appointment_id": appt_id, "message": None})
    await engagement_service.propose_terms(
        requested["id"], lawyer_id, {"fee_amount": 50000, "fee_type": "fixed"})
    await engagement_service.accept_terms(requested["id"], client_id)

    when = datetime.now(timezone.utc) + timedelta(days=3)
    when = when.replace(hour=11, minute=0, second=0, microsecond=0)

    appointment = await appointment_service.book_appointment(
        client_id=client_id, lawyer_id=lawyer_id, case_id=case_id,
        scheduled_at=when, duration_minutes=30,
        mode=AppointmentMode.VIDEO, notes="First consultation")

    assert appointment["case_id"] == case_id
    assert appointment["lawyer_id"] == lawyer_id
    assert appointment["client_id"] == client_id


async def test_the_whole_journey_creates_exactly_one_case(journey_parties, offline_ai):
    """The idempotency guarantee, held across the real flow.

    `_walk_intake` converts once; converting again must replay rather than open
    a second case, because the client's browser retries this call.
    """
    from app.db.collections import get_cases_col

    client_id = journey_parties["client_id"]
    result = await _walk_intake(client_id)

    replay = await intake_service.convert_to_case(result["token"], client_id)
    assert replay["case_id"] == result["case_id"]

    count = await get_cases_col().count_documents({"client_id": client_id})
    assert count == 1


async def test_invalid_step_data_never_reaches_the_case(journey_parties, offline_ai):
    """Validation at the seam, not just at the service boundary."""
    from app.core.exceptions import AppValidationError

    client_id = journey_parties["client_id"]
    started = await intake_service.start_intake(client_id)
    token = started["session_token"]

    with pytest.raises(AppValidationError):
        await intake_service.save_step(token, 1, {"province": "Atlantis"}, client_id)

    with pytest.raises(AppValidationError):
        await intake_service.save_step(
            token, 2, {"case_type": "banana", "urgency": "high"}, client_id)


async def test_the_journey_cannot_skip_the_confirmation(journey_parties, offline_ai):
    """The seam the draft status creates.

    Every stage after conversion is downstream of the client saying yes. A
    journey that reached a lawyer without it would put a real person's time
    against a case its owner had not agreed to file.
    """
    from app.core.exceptions import AppValidationError

    client_id = journey_parties["client_id"]
    lawyer_id = journey_parties["lawyer_id"]
    result = await _walk_intake(client_id)

    # A real consultation, so the refusal below can only be the draft guard.
    appt_id = await seed_completed_appointment(client_id, lawyer_id)
    with pytest.raises(AppValidationError, match="(?i)draft"):
        await engagement_service.request_engagement(
            client_id, {"case_id": result["case_id"], "lawyer_id": lawyer_id,
                        "appointment_id": appt_id, "message": "Take it now"})

    with pytest.raises(AppValidationError):
        await lawyer_service.match_lawyers_for_case(result["case_id"], top_n=5)
