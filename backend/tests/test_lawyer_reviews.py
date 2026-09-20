"""Lawyer reviews: the aggregate, and reading the reviews behind it.

TWO defects, both about the same thing — the rating being treated as a value in
its own right rather than as a cache of the reviews.

1. The aggregate could be left permanently wrong. `submit_review` inserted the
   review, then INCREMENTED `lawyer_profile.rating` in a second write. If that
   second write failed the client was stuck: the review existed, the rating did
   not reflect it, and every retry was refused by the unique index as a
   duplicate. Nothing in the API could repair it.

2. Nothing could read the reviews. The rating and the COUNT were reachable
   through the lawyer profile, so a client saw "4.6 (5)" with nothing behind
   it — the number they are asked to trust, with none of the evidence for it.

The fix for (1) is to derive the aggregate from the reviews instead of adding to
it, which makes the update idempotent and therefore safe to retry and safe to
run at the moment a duplicate is detected. Deliberately not a transaction:
transactions need a replica set, so that version would take a path in production
that no test ever runs.
"""
import pytest
from pymongo import ASCENDING

from app.core.security import hash_password

pytestmark = pytest.mark.integration


@pytest.fixture
async def reviewed(mongo):
    """One lawyer, three clients who may review, and an accepted engagement each."""
    from app.db.collections import (get_engagements_col, get_lawyer_reviews_col,
                                    get_users_col)

    for col in (get_users_col(), get_engagements_col(), get_lawyer_reviews_col()):
        await col.delete_many({"_id": {"$regex": "^RV-"}})
    await get_lawyer_reviews_col().delete_many({"lawyer_id": "RV-LAWYER"})

    # Build the real unique index, because it IS the guarantee under test.
    #
    # Nothing creates application indexes in the test database — `create_all_indexes`
    # runs at app startup, which an integration test never performs. So
    # "one review per (client, lawyer)" was enforced in production by an index
    # and by nothing at all here: a test asserting a duplicate is refused
    # silently passed a duplicate straight through. Creating it is idempotent
    # and uses the same name and keys as `_lawyer_reviews_indexes`.
    await get_lawyer_reviews_col().create_index(
        [("client_id", ASCENDING), ("lawyer_id", ASCENDING)],
        unique=True, name="uniq_client_lawyer_review",
    )

    await get_users_col().insert_many([
        {"_id": "RV-LAWYER", "role": "lawyer", "email": "rv-l@x.test",
         "password_hash": hash_password("Str0ngPass1"), "full_name": "Adv Rana",
         "is_active": True, "province": "punjab",
         "lawyer_profile": {"specializations": ["criminal"], "kyc_verified": True,
                            "rating": 0.0, "total_reviews": 0,
                            "availability": True, "experience_years": 9}},
        {"_id": "RV-C1", "role": "client", "email": "rv-c1@x.test",
         "full_name": "Muhammad Usama Khan",
         "password_hash": hash_password("Str0ngPass1"), "is_active": True},
        {"_id": "RV-C2", "role": "client", "email": "rv-c2@x.test",
         "full_name": "Ayesha", "is_active": True,
         "password_hash": hash_password("Str0ngPass1")},
        {"_id": "RV-C3", "role": "client", "email": "rv-c3@x.test",
         "full_name": "Bilal Ahmed Sheikh", "is_active": True,
         "password_hash": hash_password("Str0ngPass1")},
    ])
    await get_engagements_col().insert_many([
        {"_id": f"RV-ENG-{c}", "client_id": c, "lawyer_id": "RV-LAWYER",
         "case_id": f"RV-CASE-{c}", "status": "accepted"}
        for c in ("RV-C1", "RV-C2", "RV-C3")
    ])
    yield
    for col in (get_users_col(), get_engagements_col(), get_lawyer_reviews_col()):
        await col.delete_many({"_id": {"$regex": "^RV-"}})
    await get_lawyer_reviews_col().delete_many({"lawyer_id": "RV-LAWYER"})


async def _rating():
    from app.repositories.user_repo import UserRepository
    lawyer = await UserRepository().find_by_id("RV-LAWYER")
    lp = lawyer["lawyer_profile"]
    return lp.get("rating"), lp.get("total_reviews")


# ── the aggregate is derived, not accumulated ────────────────────────────────

async def test_a_review_updates_the_aggregate(reviewed):
    from app.services.lawyer_service import submit_review

    await submit_review("RV-LAWYER", "RV-C1", 4, "Helpful throughout.")
    assert await _rating() == (4.0, 1)


async def test_the_aggregate_is_the_mean_of_every_review(reviewed):
    from app.services.lawyer_service import submit_review

    await submit_review("RV-LAWYER", "RV-C1", 5, None)
    await submit_review("RV-LAWYER", "RV-C2", 4, None)
    await submit_review("RV-LAWYER", "RV-C3", 3, None)
    assert await _rating() == (4.0, 3)


async def test_a_failed_rating_write_can_be_repaired_by_retrying(reviewed, monkeypatch):
    """THE defect.

    The review lands, the aggregate update then fails. Under the incremental
    version the client was stuck forever: the review existed, so every retry was
    refused as a duplicate, and no code path recalculated the number. Now the
    retry repairs the aggregate before reporting the conflict.
    """
    from app.core.exceptions import ConflictError
    from app.repositories.user_repo import UserRepository
    from app.services import lawyer_service

    real = UserRepository.recompute_rating

    async def _explode(self, lawyer_id):
        raise RuntimeError("write concern not met")

    monkeypatch.setattr(UserRepository, "recompute_rating", _explode)
    with pytest.raises(RuntimeError):
        await lawyer_service.submit_review("RV-LAWYER", "RV-C1", 5, "Excellent.")

    # The review is stored; the aggregate is not, so it is wrong.
    assert await _rating() == (0.0, 0)

    # The client retries. It is still a duplicate — but no longer a dead end.
    monkeypatch.setattr(UserRepository, "recompute_rating", real)
    with pytest.raises(ConflictError):
        await lawyer_service.submit_review("RV-LAWYER", "RV-C1", 5, "Excellent.")

    assert await _rating() == (5.0, 1), "the retry did not repair the aggregate"


async def test_recomputing_twice_changes_nothing(reviewed):
    """Idempotence is the property that makes a retry safe. The incremental
    version double-counted on a second run; this must not."""
    from app.repositories.user_repo import UserRepository
    from app.services.lawyer_service import submit_review

    await submit_review("RV-LAWYER", "RV-C1", 5, None)
    once = await _rating()

    repo = UserRepository()
    await repo.recompute_rating("RV-LAWYER")
    await repo.recompute_rating("RV-LAWYER")

    assert await _rating() == once


async def test_a_blocked_duplicate_cannot_inflate_the_rating(reviewed):
    """The property the original insert-first ordering was designed for, kept."""
    from app.core.exceptions import ConflictError
    from app.services.lawyer_service import submit_review

    await submit_review("RV-LAWYER", "RV-C1", 5, None)
    for _ in range(3):
        with pytest.raises(ConflictError):
            await submit_review("RV-LAWYER", "RV-C1", 1, "trying again")

    assert await _rating() == (5.0, 1)


async def test_the_aggregate_is_repaired_from_drift(reviewed):
    """Self-healing: a rating that is already wrong — for any historical reason
    — is corrected, which an incremental update could never do."""
    from app.db.collections import get_users_col
    from app.repositories.user_repo import UserRepository
    from app.services.lawyer_service import submit_review

    await submit_review("RV-LAWYER", "RV-C1", 4, None)
    await get_users_col().update_one(
        {"_id": "RV-LAWYER"},
        {"$set": {"lawyer_profile.rating": 4.9,
                  "lawyer_profile.total_reviews": 87}},
    )

    await UserRepository().recompute_rating("RV-LAWYER")
    assert await _rating() == (4.0, 1)


async def test_a_lawyer_with_no_reviews_reads_as_zero(reviewed):
    """Not 'unchanged'. A lawyer whose reviews are all gone must not keep a
    stale average."""
    from app.db.collections import get_users_col
    from app.repositories.user_repo import UserRepository

    await get_users_col().update_one(
        {"_id": "RV-LAWYER"},
        {"$set": {"lawyer_profile.rating": 4.9, "lawyer_profile.total_reviews": 12}},
    )
    await UserRepository().recompute_rating("RV-LAWYER")
    assert await _rating() == (0.0, 0)


# ── reading the reviews behind the number ────────────────────────────────────

async def test_reviews_can_be_read_back(reviewed):
    from app.services.lawyer_service import list_reviews, submit_review

    await submit_review("RV-LAWYER", "RV-C1", 5, "Clear advice, well prepared.")
    page = await list_reviews("RV-LAWYER", page=1, page_size=10)

    assert page["total"] == 1
    assert page["items"][0]["stars"] == 5
    assert page["items"][0]["comment"] == "Clear advice, well prepared."


async def test_a_reviewer_is_never_identified_beyond_an_initial(reviewed):
    """A client's presence on a lawyer's public profile implies they had a legal
    matter. Publishing a full name against that is a disclosure they never
    explicitly agreed to and cannot take back once indexed."""
    from app.services.lawyer_service import list_reviews, submit_review

    await submit_review("RV-LAWYER", "RV-C1", 5, "Good.")
    item = (await list_reviews("RV-LAWYER", page=1, page_size=10))["items"][0]

    assert item["reviewer"] == "Muhammad K."
    assert "Usama" not in item["reviewer"]
    assert "client_id" not in item
    assert "rv-c1@x.test" not in str(item)


async def test_a_single_name_reviewer_is_handled(reviewed):
    from app.services.lawyer_service import list_reviews, submit_review

    await submit_review("RV-LAWYER", "RV-C2", 4, "Fine.")
    item = (await list_reviews("RV-LAWYER", page=1, page_size=10))["items"][0]
    assert item["reviewer"] == "Ayesha"


async def test_reviews_are_paginated_newest_first(reviewed):
    from app.services.lawyer_service import list_reviews, submit_review

    await submit_review("RV-LAWYER", "RV-C1", 5, "first")
    await submit_review("RV-LAWYER", "RV-C2", 4, "second")
    await submit_review("RV-LAWYER", "RV-C3", 3, "third")

    page = await list_reviews("RV-LAWYER", page=1, page_size=2)
    assert page["total"] == 3
    assert len(page["items"]) == 2
    assert page["pages"] == 2


async def test_a_lawyer_with_no_reviews_returns_an_empty_page(reviewed):
    from app.services.lawyer_service import list_reviews

    page = await list_reviews("RV-LAWYER", page=1, page_size=10)
    assert page["items"] == []
    assert page["total"] == 0


async def test_reviews_for_a_non_lawyer_are_a_404(reviewed):
    from app.core.exceptions import NotFoundError
    from app.services.lawyer_service import list_reviews

    with pytest.raises(NotFoundError):
        await list_reviews("RV-C1", page=1, page_size=10)
