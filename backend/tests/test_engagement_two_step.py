"""The two-step engagement flow, and the exits from an active engagement.

WHAT WAS WRONG. A lawyer set the fee and claimed the case in one call, so the
client first learned the price from inside a relationship they had not agreed
to — and `accepted` was absorbing: cancel returned 422 for the client, decline
returned 422 for the lawyer, and only an administrator closing the case could
end it. The engagement letter, the one place a client agrees to a price, was
generated AFTER acceptance and wrapped in `except Exception: pass`.

WHAT THESE TESTS HOLD. Two properties, and they are the reason the redesign is
one change rather than three patches:

  CONSENT   nothing is claimed until the CLIENT acts. The case stays available
            through the whole negotiation, and an accepted engagement always has
            an executed-able letter behind it.
  EXIT      `accepted` has doors. Both parties can reach both of them.

Written against the real database because the load-bearing guard is a partial
unique index, and because "the case is still claimable" is a claim about stored
state that a mocked repository would happily agree with.
"""
from __future__ import annotations

import asyncio
import secrets
from datetime import datetime, timezone

import pytest

from app.core.constants import CaseStatus, EngagementStatus
from app.core.exceptions import (
    AppValidationError,
    ConflictError,
    ForbiddenError,
    ServiceUnavailableError,
)
from app.services import engagement_service

pytestmark = pytest.mark.integration


TERMS = {"fee_amount": 75000, "fee_type": "fixed", "scope_note": "Trial court only."}


@pytest.fixture
async def parties(app_indexes):
    """A client, two verified lawyers, and a case ready to be taken."""
    from app.db.collections import (
        get_agreements_col, get_cases_col, get_engagements_col, get_users_col,
    )

    tag = secrets.token_hex(4)
    client_id = f"EN-C-{tag}"
    lawyer_id = f"EN-L1-{tag}"
    rival_id = f"EN-L2-{tag}"
    case_id = f"EN-CASE-{tag}"
    now = datetime.now(timezone.utc)

    profile = {"specializations": ["civil"], "kyc_verified": True, "rating": 4.0,
               "total_reviews": 3, "availability": True, "experience_years": 6}
    await get_users_col().insert_many([
        {"_id": client_id, "role": "client", "is_active": True,
         "email": f"en-c-{tag}@test.invalid", "full_name": "Client Engage",
         "province": "punjab", "created_at": now},
        {"_id": lawyer_id, "role": "lawyer", "is_active": True,
         "email": f"en-l1-{tag}@test.invalid", "full_name": "Adv First",
         "province": "punjab", "created_at": now, "lawyer_profile": dict(profile)},
        {"_id": rival_id, "role": "lawyer", "is_active": True,
         "email": f"en-l2-{tag}@test.invalid", "full_name": "Adv Second",
         "province": "punjab", "created_at": now, "lawyer_profile": dict(profile)},
    ])
    await get_cases_col().insert_one({
        "_id": case_id, "client_id": client_id, "lawyer_id": None,
        "case_number": f"ATT-2026-{tag.upper()}", "case_type": "civil",
        "province": "punjab", "status": CaseStatus.OPEN.value,
        "title": "A tenancy arrears claim", "description": "Arrears since March.",
        "milestones": [], "hearing_dates": [],
        "created_at": now, "updated_at": now,
    })

    yield {"client_id": client_id, "lawyer_id": lawyer_id,
           "rival_id": rival_id, "case_id": case_id}

    await get_users_col().delete_many({"_id": {"$in": [client_id, lawyer_id, rival_id]}})
    await get_cases_col().delete_many({"_id": case_id})
    await get_engagements_col().delete_many({"case_id": case_id})
    await get_agreements_col().delete_many({"case_id": case_id})


@pytest.fixture(autouse=True)
def _no_embed(monkeypatch):
    """Accepting schedules a lawyer re-embed; not this test's subject."""
    try:
        from app.ai import lawyer_embeddings
        monkeypatch.setattr(lawyer_embeddings, "schedule_embed", lambda _id: False)
    except Exception:
        pass


async def _request(p) -> str:
    eng = await engagement_service.request_engagement(
        p["client_id"], {"case_id": p["case_id"], "lawyer_id": p["lawyer_id"],
                         "message": "Please take this."})
    return eng["id"]


async def _accepted_terms_pending(p) -> str:
    """A request with terms on the table, ready for the client to accept."""
    eid = await _request(p)
    await engagement_service.propose_terms(eid, p["lawyer_id"], TERMS)
    return eid


async def _case(case_id) -> dict:
    from app.db.collections import get_cases_col
    return await get_cases_col().find_one({"_id": case_id})


# ── CONSENT: nothing is claimed until the client acts ───────────────────────

async def test_proposing_terms_does_not_claim_the_case(parties):
    """The single most important assertion in this file."""
    eid = await _request(parties)
    result = await engagement_service.propose_terms(eid, parties["lawyer_id"], TERMS)

    assert result["status"] == EngagementStatus.TERMS_PROPOSED.value
    case = await _case(parties["case_id"])
    assert case["lawyer_id"] is None
    assert case["status"] != CaseStatus.IN_PROGRESS.value


async def test_the_client_sees_the_fee_before_accepting(parties):
    eid = await _request(parties)
    proposed = await engagement_service.propose_terms(eid, parties["lawyer_id"], TERMS)
    assert proposed["fee_amount"] == 75000
    assert proposed["fee_type"] == "fixed"
    assert proposed["scope_note"] == "Trial court only."


async def test_a_proposal_without_a_fee_is_refused(parties):
    """The old flow allowed a fee-less acceptance; the letter then said
    'as mutually agreed' about a number nobody had ever named."""
    eid = await _request(parties)
    with pytest.raises(AppValidationError):
        await engagement_service.propose_terms(
            eid, parties["lawyer_id"], {"fee_amount": None, "fee_type": "fixed"})


async def test_a_proposal_without_a_fee_type_is_refused(parties):
    eid = await _request(parties)
    with pytest.raises(AppValidationError):
        await engagement_service.propose_terms(
            eid, parties["lawyer_id"], {"fee_amount": 5000, "fee_type": None})


async def test_client_acceptance_is_what_claims_the_case(parties):
    eid = await _request(parties)
    await engagement_service.propose_terms(eid, parties["lawyer_id"], TERMS)
    accepted = await engagement_service.accept_terms(eid, parties["client_id"])

    assert accepted["status"] == EngagementStatus.ACCEPTED.value
    case = await _case(parties["case_id"])
    assert case["lawyer_id"] == parties["lawyer_id"]
    assert case["status"] == CaseStatus.IN_PROGRESS.value


async def test_the_lawyer_cannot_accept_on_the_clients_behalf(parties):
    eid = await _request(parties)
    await engagement_service.propose_terms(eid, parties["lawyer_id"], TERMS)
    with pytest.raises(ForbiddenError):
        await engagement_service.accept_terms(eid, parties["lawyer_id"])


async def test_terms_cannot_be_accepted_before_they_are_proposed(parties):
    eid = await _request(parties)
    with pytest.raises(AppValidationError):
        await engagement_service.accept_terms(eid, parties["client_id"])


async def test_declining_terms_puts_the_case_back_on_the_market(parties):
    eid = await _request(parties)
    await engagement_service.propose_terms(eid, parties["lawyer_id"], TERMS)
    declined = await engagement_service.decline_terms(
        eid, parties["client_id"], "Too expensive")

    assert declined["status"] == EngagementStatus.DECLINED.value
    case = await _case(parties["case_id"])
    assert case["lawyer_id"] is None
    assert case["status"] == CaseStatus.OPEN.value


async def test_a_client_can_still_walk_away_while_terms_are_open(parties):
    """Cancel used to be `requested`-only, which would have made an unwanted
    proposal something the client had to formally decline to escape."""
    eid = await _request(parties)
    await engagement_service.propose_terms(eid, parties["lawyer_id"], TERMS)
    cancelled = await engagement_service.cancel_engagement(eid, parties["client_id"])
    assert cancelled["status"] == EngagementStatus.CANCELLED.value


async def test_a_lawyer_can_withdraw_terms_they_proposed(parties):
    eid = await _request(parties)
    await engagement_service.propose_terms(eid, parties["lawyer_id"], TERMS)
    declined = await engagement_service.decline_engagement(
        eid, parties["lawyer_id"], "Conflict of interest")
    assert declined["status"] == EngagementStatus.DECLINED.value
    case = await _case(parties["case_id"])
    assert case["lawyer_id"] is None


# ── the guard that must not regress ─────────────────────────────────────────

async def test_an_outstanding_proposal_blocks_a_request_to_another_lawyer(parties):
    """The window the two-step flow opened, closed.

    `find_pending_for_case` was hardcoded to "requested", so once terms were
    proposed the case read as having nothing pending and a second lawyer could
    be asked in parallel — two lawyers each about to take one case.
    """
    eid = await _request(parties)
    await engagement_service.propose_terms(eid, parties["lawyer_id"], TERMS)

    with pytest.raises(ConflictError):
        await engagement_service.request_engagement(
            parties["client_id"],
            {"case_id": parties["case_id"], "lawyer_id": parties["rival_id"],
             "message": "You too?"})


async def test_the_index_refuses_a_second_open_engagement_on_one_case(parties):
    """The guard, asserted against the database rather than the service.

    This test was originally written to force two `terms_proposed` engagements
    onto one case so the claim could race them. The insert is REFUSED — which is
    the guarantee itself, and a better thing to assert than the race it was
    meant to set up. Two lawyers cannot both be mid-negotiation for one case,
    so the double-claim it was reaching for cannot be reached from here at all.
    """
    from pymongo.errors import DuplicateKeyError

    from app.db.collections import get_engagements_col

    eid = await _request(parties)
    await engagement_service.propose_terms(eid, parties["lawyer_id"], TERMS)

    now = datetime.now(timezone.utc)
    with pytest.raises(DuplicateKeyError):
        await get_engagements_col().insert_one({
            "_id": secrets.token_urlsafe(16), "case_id": parties["case_id"],
            "client_id": parties["client_id"], "lawyer_id": parties["rival_id"],
            "status": EngagementStatus.TERMS_PROPOSED.value,
            "created_at": now, "updated_at": now,
        })


async def test_two_presses_of_accept_do_not_cost_the_client_their_lawyer(parties):
    """The realistic race, now that the button belongs to the CLIENT.

    The loser of the claim used to cancel the engagement — so a double-click
    would have set the case up with a lawyer and then cancelled the engagement
    that put them there. The second press must be a no-op.
    """
    from app.db.collections import get_cases_col

    eid = await _accepted_terms_pending(parties)

    first, second = await asyncio.gather(
        engagement_service.accept_terms(eid, parties["client_id"]),
        engagement_service.accept_terms(eid, parties["client_id"]),
        return_exceptions=True,
    )
    for outcome in (first, second):
        assert not isinstance(outcome, Exception), outcome
        assert outcome["status"] == EngagementStatus.ACCEPTED.value

    case = await get_cases_col().find_one({"_id": parties["case_id"]})
    assert case["lawyer_id"] == parties["lawyer_id"]


async def test_a_case_claimed_elsewhere_is_a_real_conflict(parties):
    """The branch that MUST still cancel: someone else holds the case."""
    from app.db.collections import get_cases_col, get_engagements_col

    eid = await _accepted_terms_pending(parties)
    await get_cases_col().update_one(
        {"_id": parties["case_id"]},
        {"$set": {"lawyer_id": parties["rival_id"],
                  "status": CaseStatus.IN_PROGRESS.value}},
    )

    with pytest.raises(ConflictError):
        await engagement_service.accept_terms(eid, parties["client_id"])

    eng = await get_engagements_col().find_one({"_id": eid})
    assert eng["status"] == EngagementStatus.CANCELLED.value


# ── the letter is the consent artifact ──────────────────────────────────────

async def test_acceptance_produces_an_engagement_letter(parties):
    from app.db.collections import get_agreements_col

    eid = await _request(parties)
    await engagement_service.propose_terms(eid, parties["lawyer_id"], TERMS)
    accepted = await engagement_service.accept_terms(eid, parties["client_id"])

    assert accepted["agreement_id"]
    agreement = await get_agreements_col().find_one({"_id": accepted["agreement_id"]})
    assert agreement is not None
    assert "75,000" in agreement["body_html"]
    assert "Trial court only." in agreement["body_html"]


async def test_a_failed_letter_leaves_no_engagement_and_no_claim(parties, monkeypatch):
    """`except Exception: pass` is gone, and the claim is given back.

    An engagement standing with no letter was a billing loophole that
    payment_service had to defend against separately. Now the letter records
    terms the client has just accepted, so proceeding without one would leave
    that agreement with no artifact at all.
    """
    from app.services import agreement_service

    async def boom(**kw):
        raise RuntimeError("agreement service down")

    monkeypatch.setattr(agreement_service, "create_pending_engagement_letter", boom)

    eid = await _request(parties)
    await engagement_service.propose_terms(eid, parties["lawyer_id"], TERMS)

    with pytest.raises(ServiceUnavailableError):
        await engagement_service.accept_terms(eid, parties["client_id"])

    case = await _case(parties["case_id"])
    assert case["lawyer_id"] is None, "the claim was not released"

    from app.db.collections import get_engagements_col
    eng = await get_engagements_col().find_one({"_id": eid})
    assert eng["status"] == EngagementStatus.TERMS_PROPOSED.value


async def test_the_client_can_retry_after_a_failed_letter(parties, monkeypatch):
    from app.services import agreement_service

    calls = {"n": 0}
    real = agreement_service.create_pending_engagement_letter

    async def flaky(**kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("transient")
        return await real(**kw)

    monkeypatch.setattr(agreement_service, "create_pending_engagement_letter", flaky)

    eid = await _request(parties)
    await engagement_service.propose_terms(eid, parties["lawyer_id"], TERMS)
    with pytest.raises(ServiceUnavailableError):
        await engagement_service.accept_terms(eid, parties["client_id"])

    accepted = await engagement_service.accept_terms(eid, parties["client_id"])
    assert accepted["status"] == EngagementStatus.ACCEPTED.value


# ── EXIT: `accepted` has doors ──────────────────────────────────────────────

async def _accepted(p) -> str:
    eid = await _request(p)
    await engagement_service.propose_terms(eid, p["lawyer_id"], TERMS)
    await engagement_service.accept_terms(eid, p["client_id"])
    return eid


@pytest.mark.parametrize("who", ["client_id", "lawyer_id"])
async def test_either_party_can_terminate(parties, who):
    eid = await _accepted(parties)
    ended = await engagement_service.terminate_engagement(
        eid, parties[who], "The relationship broke down.")
    assert ended["status"] == EngagementStatus.TERMINATED.value
    assert ended["termination_reason"] == "The relationship broke down."


async def test_termination_releases_the_case(parties):
    """The client must be able to engage someone else immediately."""
    eid = await _accepted(parties)
    await engagement_service.terminate_engagement(
        eid, parties["client_id"], "Unresponsive.")

    case = await _case(parties["case_id"])
    assert case["lawyer_id"] is None
    assert case["status"] == CaseStatus.OPEN.value

    # And the case really is available again.
    again = await engagement_service.request_engagement(
        parties["client_id"],
        {"case_id": parties["case_id"], "lawyer_id": parties["rival_id"],
         "message": "Can you take over?"})
    assert again["status"] == EngagementStatus.REQUESTED.value


async def test_termination_requires_a_reason(parties):
    eid = await _accepted(parties)
    with pytest.raises(AppValidationError):
        await engagement_service.terminate_engagement(eid, parties["client_id"], "   ")


async def test_a_stranger_cannot_end_someone_elses_engagement(parties):
    eid = await _accepted(parties)
    with pytest.raises(ForbiddenError):
        await engagement_service.terminate_engagement(eid, parties["rival_id"], "Mine now")


async def test_completion_is_a_handshake_by_default(parties):
    """One party asserting the matter is over does not make it over."""
    eid = await _accepted(parties)
    proposed = await engagement_service.complete_engagement(
        eid, parties["lawyer_id"], note="Decree obtained.")

    assert proposed["status"] == EngagementStatus.ACCEPTED.value
    assert proposed["completion_proposed_by"] == "lawyer"

    case = await _case(parties["case_id"])
    assert case["status"] == CaseStatus.IN_PROGRESS.value


async def test_the_other_party_confirms_completion(parties):
    eid = await _accepted(parties)
    await engagement_service.complete_engagement(
        eid, parties["lawyer_id"], note="Decree obtained.")
    done = await engagement_service.complete_engagement(eid, parties["client_id"])

    assert done["status"] == EngagementStatus.COMPLETED.value
    assert done["completion_kind"] == "mutual"


async def test_completion_closes_the_case_with_the_lawyer_still_on_it(parties):
    """Completion and termination differ precisely here.

    The lawyer did the work; the case history is theirs. Handing the case back
    unowned on completion would erase who conducted it.
    """
    eid = await _accepted(parties)
    await engagement_service.complete_engagement(eid, parties["lawyer_id"], note="Done.")
    await engagement_service.complete_engagement(eid, parties["client_id"])

    case = await _case(parties["case_id"])
    assert case["lawyer_id"] == parties["lawyer_id"]
    assert case["status"] == CaseStatus.CLOSED.value


async def test_one_party_cannot_confirm_its_own_proposal(parties):
    eid = await _accepted(parties)
    await engagement_service.complete_engagement(eid, parties["lawyer_id"], note="Done.")
    with pytest.raises(AppValidationError):
        await engagement_service.complete_engagement(eid, parties["lawyer_id"])


async def test_a_one_sided_completion_needs_a_note(parties):
    """The escape hatch cannot be a silent one."""
    eid = await _accepted(parties)
    with pytest.raises(AppValidationError):
        await engagement_service.complete_engagement(
            eid, parties["client_id"], note=None, one_sided=True)


async def test_a_one_sided_completion_is_recorded_as_one_sided(parties):
    """The record must never claim an agreement that did not happen."""
    eid = await _accepted(parties)
    done = await engagement_service.complete_engagement(
        eid, parties["client_id"], note="Lawyer stopped responding.", one_sided=True)

    assert done["status"] == EngagementStatus.COMPLETED.value
    assert done["completion_kind"] == "one_sided"
    assert done["completed_by"] == "client"


@pytest.mark.parametrize("action,args", [
    ("complete_engagement", {"note": "x"}),
    ("terminate_engagement", {"reason": "x"}),
])
async def test_an_ended_engagement_cannot_be_ended_again(parties, action, args):
    eid = await _accepted(parties)
    await engagement_service.terminate_engagement(eid, parties["client_id"], "Done here.")

    with pytest.raises(AppValidationError):
        await getattr(engagement_service, action)(eid, parties["client_id"], **args)


async def test_exits_are_not_reachable_before_acceptance(parties):
    eid = await _request(parties)
    await engagement_service.propose_terms(eid, parties["lawyer_id"], TERMS)
    with pytest.raises(AppValidationError):
        await engagement_service.terminate_engagement(eid, parties["client_id"], "no")


# ── what the exits must not break ───────────────────────────────────────────

async def test_a_completed_engagement_still_counts_as_having_retained(parties):
    """Reviews are gated on having actually retained the lawyer.

    Scoping that to `accepted` would have removed the right to review at the
    exact moment a client is most likely to have something to say.
    """
    from app.repositories.engagement_repo import EngagementRepository

    repo = EngagementRepository()
    eid = await _accepted(parties)
    await engagement_service.complete_engagement(
        eid, parties["client_id"], note="All finished.", one_sided=True)

    assert await repo.exists_accepted(parties["client_id"], parties["lawyer_id"])


async def test_a_terminated_engagement_still_counts_as_having_retained(parties):
    from app.repositories.engagement_repo import EngagementRepository

    repo = EngagementRepository()
    eid = await _accepted(parties)
    await engagement_service.terminate_engagement(
        eid, parties["client_id"], "Poor communication.")

    assert await repo.exists_accepted(parties["client_id"], parties["lawyer_id"])


async def test_a_merely_requested_engagement_does_not_count(parties):
    from app.repositories.engagement_repo import EngagementRepository

    repo = EngagementRepository()
    await _request(parties)
    assert not await repo.exists_accepted(parties["client_id"], parties["lawyer_id"])


# ── every "is this engagement live?" check must know the new state ──────────

async def test_an_account_with_terms_outstanding_cannot_be_closed(parties):
    """Account closure blocks on open obligations, and a proposal is one.

    The blocker list named `requested` and `accepted`. `terms_proposed` did not
    exist when it was written, so adding the state silently opened a hole: a
    lawyer could close their account with terms sitting in front of a client,
    which is precisely the stranding this check exists to prevent.
    """
    from app.services.user_service import _open_obligations

    eid = await _request(parties)
    await engagement_service.propose_terms(eid, parties["lawyer_id"], TERMS)

    assert await _open_obligations(parties["lawyer_id"], "lawyer")
    assert await _open_obligations(parties["client_id"], "client")


async def test_an_ended_engagement_stops_blocking_closure(parties):
    from app.services.user_service import _open_obligations

    eid = await _accepted_terms_pending(parties)
    await engagement_service.decline_terms(eid, parties["client_id"], "No thanks")

    assert not await _open_obligations(parties["lawyer_id"], "lawyer")
