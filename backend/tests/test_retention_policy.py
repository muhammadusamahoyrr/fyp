"""What the system keeps, what it would remove, and what a hold protects.

APPROVED 2026-09-03: 12 months for everything a user can see, 7 years for the
accountability record. Admins only may place a legal hold.

NOTHING HERE DELETES ANYTHING, AND THAT IS ASSERTED

The plan is a DRY RUN. The first observable effect of a wrong retention number
is that the data is gone, so deletion is a separate, deliberate step and there
is deliberately no flag one call away from it. Several tests below exist purely
to keep it that way.

The properties that matter most are the ones that fail silently:

  * A HOLD BEATS EVERY PERIOD, including the user's own Delete button.
    Otherwise the retention job destroys evidence exactly when a dispute makes
    it valuable, automatically, with nobody deciding.
  * THE CLOCK IS LAST ACTIVITY. A conversation someone still uses must never be
    truncated from underneath them.
  * THE REPORT NAMES NOBODY. It is read on dashboards and pasted into tickets,
    and must not become a list of whose data is about to expire.

Integration, because eligibility and hold enforcement are database semantics.
No provider is called in this file.
"""
import secrets
from datetime import timedelta

import pytest

from app.db.collections import get_chat_sessions_col, get_research_sessions_col
from app.services import conversation_service as conversations
from app.services import legal_holds, retention

OWNER = {"_id": "ret-owner", "role": "client"}
LAWYER = {"_id": "ret-lawyer", "role": "lawyer"}
ADMIN = "ret-admin"
CASE = "ret-case-1"

CLIENT = conversations.SURFACE_CLIENT
RESEARCH = conversations.SURFACE_RESEARCH


@pytest.fixture
async def clean(mongo):
    async def wipe():
        await get_chat_sessions_col().delete_many({"client_id": OWNER["_id"]})
        await get_research_sessions_col().delete_many({"owner_id": LAWYER["_id"]})
        await legal_holds.get_legal_holds_col().delete_many(
            {"target_id": {"$in": [OWNER["_id"], LAWYER["_id"], CASE]}})

    legal_holds._reset_index_cache()
    await wipe()
    yield
    await wipe()


async def _aged(surface, owner, *, days_idle, case_id=None):
    """A conversation last touched `days_idle` ago."""
    ref = await conversations.open_ref(
        surface, f"ret-{secrets.token_hex(4)}", owner["_id"])
    patch = {"updated_at": retention._now() - timedelta(days=days_idle)}
    if case_id:
        patch["case_id"] = case_id
    col = (get_chat_sessions_col() if surface == CLIENT
           else get_research_sessions_col())
    await col.update_one({"_id": ref.doc_id}, {"$set": patch})
    return ref


# ══════════════════════════════════════════════════════════════════════════════
# The approved periods
# ══════════════════════════════════════════════════════════════════════════════

def test_everything_a_user_can_see_expires_at_twelve_months():
    """One number, because a privacy policy has to state it and a policy that
    needs a table is a policy nobody reads."""
    assert retention.USER_DATA_SECONDS == 365 * retention.DAY
    for store in ("conversation_messages", "conversation_turns",
                  "chat_sessions", "research_sessions",
                  "langgraph_checkpoints"):
        assert retention.PERIODS[store] == retention.USER_DATA_SECONDS, store


def test_the_accountability_record_outlives_it_by_six_years():
    """A user deleting a conversation asks for it to stop being visible to
    them; they are not, and cannot be, asking the firm to forget it gave
    advice."""
    assert retention.ACCOUNTABILITY_SECONDS == 7 * 365 * retention.DAY
    for store in ("answer_provenance", "provenance_outbox", "tombstones"):
        assert retention.PERIODS[store] == retention.ACCOUNTABILITY_SECONDS


def test_the_policy_reports_itself_rather_than_being_restated():
    """A documented period that no longer matches the enforced one is worse
    than no documentation."""
    described = retention.describe()
    assert described["user_data_days"] == 365
    assert described["accountability_days"] == 7 * 365
    assert described["clock"] == "last activity"
    assert described["deletion_enabled"] is False


def test_an_unknown_store_has_no_period_rather_than_a_default():
    """A default would silently apply somebody's guess to a store nobody
    considered."""
    with pytest.raises(KeyError):
        retention.cutoff("some_new_collection")


# ══════════════════════════════════════════════════════════════════════════════
# The clock is last activity
# ══════════════════════════════════════════════════════════════════════════════

async def test_a_conversation_still_in_use_is_never_eligible(clean):
    """`updated_at` moves with every message, so an active thread is safe
    however old its first question is. Truncating one from underneath a user
    mid-thread is the failure this clock exists to prevent."""
    await _aged(CLIENT, OWNER, days_idle=0)
    plan = await retention.plan()
    assert plan["conversations"]["chat_sessions"]["conversations_eligible"] == 0


async def test_a_conversation_untouched_for_a_year_is_eligible(clean):
    await _aged(CLIENT, OWNER, days_idle=400)
    plan = await retention.plan()
    assert plan["conversations"]["chat_sessions"]["conversations_eligible"] == 1


async def test_the_boundary_is_where_the_period_says(clean):
    await _aged(CLIENT, OWNER, days_idle=364)
    assert (await retention.plan())["conversations"]["chat_sessions"][
        "conversations_eligible"] == 0

    await _aged(CLIENT, OWNER, days_idle=366)
    assert (await retention.plan())["conversations"]["chat_sessions"][
        "conversations_eligible"] == 1


# ══════════════════════════════════════════════════════════════════════════════
# A hold beats every period
# ══════════════════════════════════════════════════════════════════════════════

async def test_a_user_hold_protects_their_expired_conversations(clean):
    await _aged(CLIENT, OWNER, days_idle=400)
    await legal_holds.place(legal_holds.SCOPE_USER, OWNER["_id"],
                            reason="dispute 2026-14", placed_by=ADMIN)

    summary = (await retention.plan())["conversations"]["chat_sessions"]
    assert summary["conversations_eligible"] == 0
    assert summary["conversations_held"] == 1


async def test_a_case_hold_protects_research_bound_to_it(clean):
    await _aged(RESEARCH, LAWYER, days_idle=400, case_id=CASE)
    await legal_holds.place(legal_holds.SCOPE_CASE, CASE,
                            reason="regulator request", placed_by=ADMIN)

    summary = (await retention.plan())["conversations"]["research_sessions"]
    assert summary["conversations_eligible"] == 0
    assert summary["conversations_held"] == 1


async def test_a_case_hold_does_not_protect_unrelated_conversations(clean):
    """A hold is a freeze on a matter, not an amnesty."""
    await _aged(RESEARCH, LAWYER, days_idle=400, case_id=CASE)
    await _aged(RESEARCH, LAWYER, days_idle=400, case_id="ret-case-other")
    await legal_holds.place(legal_holds.SCOPE_CASE, CASE,
                            reason="regulator request", placed_by=ADMIN)

    summary = (await retention.plan())["conversations"]["research_sessions"]
    assert summary["conversations_eligible"] == 1
    assert summary["conversations_held"] == 1


async def test_lifting_a_hold_resumes_the_normal_schedule(clean):
    await _aged(CLIENT, OWNER, days_idle=400)
    await legal_holds.place(legal_holds.SCOPE_USER, OWNER["_id"],
                            reason="dispute", placed_by=ADMIN)
    assert await legal_holds.lift(legal_holds.SCOPE_USER, OWNER["_id"],
                                  lifted_by=ADMIN)

    summary = (await retention.plan())["conversations"]["chat_sessions"]
    assert summary["conversations_eligible"] == 1


async def test_a_lifted_hold_is_kept_not_deleted(clean):
    """What was frozen, by whom, and for how long is itself the kind of thing
    an auditor asks about, and a deleted hold record cannot answer it."""
    await legal_holds.place(legal_holds.SCOPE_USER, OWNER["_id"],
                            reason="dispute", placed_by=ADMIN)
    await legal_holds.lift(legal_holds.SCOPE_USER, OWNER["_id"], lifted_by=ADMIN)

    history = await legal_holds.listing(include_lifted=True)
    mine = [h for h in history if h["target_id"] == OWNER["_id"]]
    assert len(mine) == 1
    assert mine[0]["lifted_by"] == ADMIN
    assert mine[0]["reason"] == "dispute"


# ══════════════════════════════════════════════════════════════════════════════
# A hold beats the user's own Delete button
# ══════════════════════════════════════════════════════════════════════════════

async def test_a_held_user_cannot_delete_their_own_conversation(clean):
    """Otherwise a user under hold destroys evidence about themselves by
    pressing a button — and the button is right there, labelled Delete, doing
    exactly what it says."""
    ref = await _aged(CLIENT, OWNER, days_idle=1)
    await conversations.append_message(
        ref, conversations.build_message("user", "my landlord evicted me"),
        turn_id="t1")
    await legal_holds.place(legal_holds.SCOPE_USER, OWNER["_id"],
                            reason="dispute", placed_by=ADMIN)

    result = await conversations.delete_session(
        CLIENT, ref.session_id, OWNER["_id"])

    assert result["messages_removed"] == 0
    doc = await get_chat_sessions_col().find_one({"_id": ref.doc_id})
    assert doc["deleted_at"] is None, "a held conversation was tombstoned"
    assert doc["archived"] is True, "it should still leave the user's list"


async def test_the_user_is_told_rather_than_silently_refused(clean):
    """A silent no-op would have them believe the data is gone when it is not,
    which is a worse lie than refusing."""
    ref = await _aged(CLIENT, OWNER, days_idle=1)
    await legal_holds.place(legal_holds.SCOPE_USER, OWNER["_id"],
                            reason="dispute", placed_by=ADMIN)

    result = await conversations.delete_session(
        CLIENT, ref.session_id, OWNER["_id"])

    assert "legal hold" in result["notice"]
    assert result["effects"]["messages"] == "retained under legal hold"


async def test_deletion_works_normally_without_a_hold(clean):
    """The override must not become the behaviour."""
    ref = await _aged(CLIENT, OWNER, days_idle=1)
    await conversations.append_message(
        ref, conversations.build_message("user", "a question"), turn_id="t1")

    result = await conversations.delete_session(
        CLIENT, ref.session_id, OWNER["_id"])

    assert result["messages_removed"] >= 1
    doc = await get_chat_sessions_col().find_one({"_id": ref.doc_id})
    assert doc["deleted_at"] is not None


# ══════════════════════════════════════════════════════════════════════════════
# Holds themselves
# ══════════════════════════════════════════════════════════════════════════════

async def test_two_admins_reacting_to_one_dispute_produce_one_hold(clean):
    """Enforced by a partial-unique index rather than by a check they could
    race. Two active holds on one target would both need lifting, and
    forgetting the second is how data outlives a hold everyone believes was
    lifted."""
    first = await legal_holds.place(legal_holds.SCOPE_USER, OWNER["_id"],
                                    reason="dispute", placed_by=ADMIN)
    second = await legal_holds.place(legal_holds.SCOPE_USER, OWNER["_id"],
                                     reason="same dispute", placed_by="other-admin")

    assert first["_id"] == second["_id"]
    active = await legal_holds.listing()
    assert len([h for h in active if h["target_id"] == OWNER["_id"]]) == 1


async def test_a_target_can_be_held_again_after_being_lifted(clean):
    """The unique index is on ACTIVE holds only, or a target could never be
    frozen twice."""
    await legal_holds.place(legal_holds.SCOPE_USER, OWNER["_id"],
                            reason="first", placed_by=ADMIN)
    await legal_holds.lift(legal_holds.SCOPE_USER, OWNER["_id"], lifted_by=ADMIN)
    again = await legal_holds.place(legal_holds.SCOPE_USER, OWNER["_id"],
                                    reason="second", placed_by=ADMIN)
    assert again["reason"] == "second"
    assert await legal_holds.is_held(user_id=OWNER["_id"]) is True


async def test_a_hold_must_say_why(clean):
    """A hold with no reason cannot be reviewed later, and an unreviewable hold
    is one nobody dares lift."""
    from app.core.exceptions import AppValidationError

    with pytest.raises(AppValidationError):
        await legal_holds.place(legal_holds.SCOPE_USER, OWNER["_id"],
                                reason="   ", placed_by=ADMIN)


async def test_a_hold_is_on_a_user_or_a_case_and_nothing_else(clean):
    from app.core.exceptions import AppValidationError

    with pytest.raises(AppValidationError):
        await legal_holds.place("message", "m-1", reason="x", placed_by=ADMIN)


async def test_lifting_a_hold_that_is_not_there_is_not_an_error(clean):
    assert await legal_holds.lift(
        legal_holds.SCOPE_USER, "nobody", lifted_by=ADMIN) is False


def test_hold_coverage_reads_owner_and_case(clean):
    held = {legal_holds.SCOPE_USER: {"u1"}, legal_holds.SCOPE_CASE: {"c1"}}
    assert legal_holds.covers(held, owner_id="u1", case_id=None) is True
    assert legal_holds.covers(held, owner_id="u2", case_id="c1") is True
    assert legal_holds.covers(held, owner_id="u2", case_id="c2") is False
    # Client chat has no case binding, so only the owner clause reaches it.
    assert legal_holds.covers(held, owner_id="u2", case_id=None) is False


# ══════════════════════════════════════════════════════════════════════════════
# The report deletes nothing and names nobody
# ══════════════════════════════════════════════════════════════════════════════

async def test_the_plan_removes_nothing(clean):
    ref = await _aged(CLIENT, OWNER, days_idle=400)
    await conversations.append_message(
        ref, conversations.build_message("user", "a question"), turn_id="t1")

    await retention.plan()

    doc = await get_chat_sessions_col().find_one({"_id": ref.doc_id})
    assert doc is not None, "the dry run deleted a conversation"
    from app.services import conversation_messages as messages
    assert await messages.count_for_conversation(ref.key) == 1


async def test_the_plan_names_nobody(clean):
    """Read on a dashboard and pasted into tickets. The one thing it must not
    become is a listing of whose data is about to expire."""
    ref = await _aged(RESEARCH, LAWYER, days_idle=400, case_id=CASE)
    await conversations.append_message(
        ref, conversations.build_message("user", "my landlord evicted me"),
        turn_id="t1")

    blob = repr(await retention.plan())

    assert LAWYER["_id"] not in blob
    assert ref.session_id not in blob
    assert CASE not in blob
    assert "landlord" not in blob


async def test_nothing_in_the_module_can_delete(clean):
    """Deletion is a separate, deliberate step. Asserted so it does not become
    one flag away from a dry run — the first observable effect of a wrong
    retention number is that the data is gone."""
    import inspect

    source = inspect.getsource(retention)
    for destructive in ("delete_one", "delete_many", "drop("):
        assert destructive not in source, (
            f"retention.py can call {destructive}; deletion was supposed to be "
            f"a separate step")
    assert (await retention.plan())["deletion_enabled"] is False


async def test_a_sweep_is_capped_before_it_is_written(clean):
    """A mistake should be a small mistake. The cap exists now so the deletion
    step inherits it rather than adding it afterwards."""
    assert retention.MAX_PER_RUN <= 1000
    assert (await retention.plan())["policy"]["deletion_enabled"] is False
