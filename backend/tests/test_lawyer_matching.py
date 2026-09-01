"""Lawyer matching — the candidate pool and how it is scored.

`match_lawyers_for_case` had no test coverage at all. What it had instead was a
branch that asked whether the vector store returned *any* rows before checking
whether those rows resolved to a real lawyer:

    if semantic_hits:      # 2 rows, both deleted from Mongo months ago
        ...                # resolves to nothing -> empty list
    else:
        ...                # the province + case-type MongoDB pool — never ran

On 2026-09-01 `lawyers_collection` held exactly two rows, `test-lawyer-001` and
`e2e-lawyer-seed-001`, both smoke-test accounts long since deleted, both
`province: punjab`. Every Punjab or federal case — 45 of 59 real cases — took
the semantic branch, produced nothing, and fell through to a last-resort listing
of whoever had the highest rating, with no province or case-type relevance at
all. Two dead rows suppressed a pool of 25 lawyers.

The first test here is that scenario.
"""
import pytest

from app.core.security import hash_password

pytestmark = pytest.mark.integration


def _lawyer(_id: str, *, province: str, specs: list[str], rating: float = 4.0,
            exp: int = 10, verified: bool = True, active: bool = True) -> dict:
    return {
        "_id": _id,
        "role": "lawyer",
        "email": f"{_id.lower()}@x.test",
        "password_hash": hash_password("Str0ngPass1"),
        "full_name": f"Adv {_id}",
        "is_active": active,
        "province": province,
        "lawyer_profile": {
            "bar_number": f"BAR-{_id}",
            "specializations": specs,
            "kyc_verified": verified,
            "rating": rating,
            "total_reviews": 5,
            "availability": True,
            "experience_years": exp,
            "bio": "Practising advocate.",
        },
    }


@pytest.fixture
async def pool(mongo):
    """Four verified Punjab lawyers and one case, all removed afterwards."""
    from app.db.collections import get_cases_col, get_users_col

    await get_users_col().insert_many([
        _lawyer("LM-CRIM", province="punjab", specs=["criminal"], rating=4.5),
        _lawyer("LM-CIVIL", province="punjab", specs=["civil"], rating=4.2),
        _lawyer("LM-FAMILY", province="punjab", specs=["family"], rating=4.9),
        _lawyer("LM-SINDH", province="sindh", specs=["criminal"], rating=5.0),
        {"_id": "LM-CLIENT", "role": "client", "email": "lm-c@x.test",
         "password_hash": hash_password("Str0ngPass1"), "is_active": True},
    ])
    await get_cases_col().insert_one({
        "_id": "LM-CASE",
        "client_id": "LM-CLIENT",
        "case_type": "criminal",
        "province": "punjab",
        "title": "FIR quashment",
        "description": "Client seeks pre-arrest bail after an FIR under PPC 380.",
        "status": "open",
    })
    yield
    await get_users_col().delete_many({"_id": {"$regex": "^LM-"}})
    await get_cases_col().delete_many({"_id": {"$regex": "^LM-"}})


def _fake_hits(monkeypatch, hits):
    """Replace the vector search. Tests must not depend on ChromaDB state."""
    async def _q(query_text, province, n_results=20):
        return list(hits)
    monkeypatch.setattr(
        "app.ai.lawyer_embeddings.query_similar_lawyers", _q, raising=True
    )
    return _q


def _forget_spy(monkeypatch):
    forgotten: list[str] = []

    def _f(ids):
        forgotten.extend(ids)
        return len(list(ids))

    monkeypatch.setattr("app.ai.lawyer_embeddings.forget_lawyers", _f, raising=True)
    return forgotten


# ── the regression that started this ─────────────────────────────────────────

async def test_stale_vectors_do_not_suppress_the_mongo_pool(pool, monkeypatch):
    """THE defect. Two vector rows pointing at deleted lawyers must not hide
    every real lawyer in the province."""
    from app.services import lawyer_service

    _fake_hits(monkeypatch, [
        {"lawyer_id": "test-lawyer-001", "semantic_score": 0.91, "metadata": {}},
        {"lawyer_id": "e2e-lawyer-seed-001", "semantic_score": 0.88, "metadata": {}},
    ])
    _forget_spy(monkeypatch)

    results = await lawyer_service.match_lawyers_for_case("LM-CASE")

    ids = {r["_id"] for r in results}
    assert "test-lawyer-001" not in ids
    assert "e2e-lawyer-seed-001" not in ids
    # the real Punjab pool is present and the case-type match leads it
    assert "LM-CRIM" in ids
    assert results[0]["_id"] == "LM-CRIM"


async def test_unresolvable_hits_are_removed_from_the_store(pool, monkeypatch):
    """A ghost row poisons at most one query. Previously it poisoned every
    query forever, because nothing ever deleted from the collection."""
    from app.services import lawyer_service

    _fake_hits(monkeypatch, [
        {"lawyer_id": "test-lawyer-001", "semantic_score": 0.91, "metadata": {}},
        {"lawyer_id": "LM-CRIM", "semantic_score": 0.80, "metadata": {}},
    ])
    forgotten = _forget_spy(monkeypatch)

    await lawyer_service.match_lawyers_for_case("LM-CASE")

    assert forgotten == ["test-lawyer-001"]  # the live lawyer is left alone


# ── the two pools are merged, not alternatives ───────────────────────────────

async def test_semantic_and_mongo_pools_are_unioned(pool, monkeypatch):
    """A lawyer reachable only by vector and one reachable only by filter must
    both appear. Neither pool may be conditional on the other being empty."""
    from app.db.collections import get_users_col
    from app.services import lawyer_service

    # LM-SINDH is outside the case province, so the Mongo filter cannot reach
    # them; only the vector store can.
    _fake_hits(monkeypatch, [
        {"lawyer_id": "LM-SINDH", "semantic_score": 0.95, "metadata": {}},
    ])
    _forget_spy(monkeypatch)

    results = await lawyer_service.match_lawyers_for_case("LM-CASE")
    ids = {r["_id"] for r in results}

    assert "LM-SINDH" in ids, "semantic-only candidate was dropped"
    assert "LM-CRIM" in ids, "MongoDB pool was suppressed by a non-empty semantic pool"
    assert await get_users_col().count_documents({"_id": "LM-SINDH"}) == 1


async def test_a_lawyer_in_both_pools_appears_once_with_their_semantic_score(
    pool, monkeypatch
):
    from app.services import lawyer_service

    _fake_hits(monkeypatch, [
        {"lawyer_id": "LM-CRIM", "semantic_score": 0.90, "metadata": {}},
    ])
    _forget_spy(monkeypatch)

    results = await lawyer_service.match_lawyers_for_case("LM-CASE")

    crim = [r for r in results if r["_id"] == "LM-CRIM"]
    assert len(crim) == 1, "duplicated across the two pools"
    assert "strong profile match" in crim[0]["match_reason"]


async def test_an_empty_vector_store_still_returns_the_mongo_pool(pool, monkeypatch):
    """The state right after the purge and before the backfill runs.

    Also pins how narrow the MongoDB pool deliberately is: province AND an
    exact case-type specialization. A Punjab civil lawyer is not a strong match
    for a Punjab criminal case and must not be padded in to fill top_n. Breadth
    is the vector store's job — it filters on province only, so once profiles
    are embedded a civil lawyer whose past work reads criminal will surface
    through the semantic pool rather than by relaxing the filter.
    """
    from app.services import lawyer_service

    _fake_hits(monkeypatch, [])
    _forget_spy(monkeypatch)

    results = await lawyer_service.match_lawyers_for_case("LM-CASE")
    ids = {r["_id"] for r in results}

    assert "LM-CRIM" in ids
    assert "LM-CIVIL" not in ids
    assert "LM-FAMILY" not in ids


async def test_a_failing_vector_search_does_not_fail_the_match(pool, monkeypatch):
    from app.services import lawyer_service

    async def _boom(query_text, province, n_results=20):
        raise RuntimeError("chroma is down")

    monkeypatch.setattr(
        "app.ai.lawyer_embeddings.query_similar_lawyers", _boom, raising=True
    )

    results = await lawyer_service.match_lawyers_for_case("LM-CASE")

    assert "LM-CRIM" in {r["_id"] for r in results}


# ── who may be ranked ────────────────────────────────────────────────────────

@pytest.mark.parametrize("field,value", [
    ("lawyer_profile.kyc_verified", False),
    ("is_active", False),
])
async def test_unverified_and_inactive_lawyers_are_never_ranked(
    pool, monkeypatch, field, value
):
    from app.db.collections import get_users_col
    from app.services import lawyer_service

    await get_users_col().update_one({"_id": "LM-CRIM"}, {"$set": {field: value}})
    _fake_hits(monkeypatch, [
        {"lawyer_id": "LM-CRIM", "semantic_score": 0.99, "metadata": {}},
    ])
    _forget_spy(monkeypatch)

    results = await lawyer_service.match_lawyers_for_case("LM-CASE")

    assert "LM-CRIM" not in {r["_id"] for r in results}


# ── scoring ──────────────────────────────────────────────────────────────────

def test_a_lawyer_with_no_vector_is_not_given_an_invented_score():
    """The MongoDB path used to hand every candidate a flat semantic score of
    0.3 — 0.15 of fabricated score that a genuinely weak real match could not
    beat. `None` now means "no vector", and the semantic weight is redistributed
    over the factors we have evidence for."""
    from app.services.lawyer_service import _score_lawyer

    lawyer = _lawyer("X", province="punjab", specs=["criminal"], rating=4.0, exp=10)

    no_vector, _ = _score_lawyer(lawyer, "criminal", None)
    weak_vector, _ = _score_lawyer(lawyer, "criminal", 0.05)

    # Same evidence, plus a measured-and-poor semantic fit, must not score
    # higher than the same lawyer with no measurement at all.
    assert weak_vector < no_vector
    assert 0.0 <= no_vector <= 1.0


def test_no_vector_does_not_claim_a_profile_match_in_its_reason():
    from app.services.lawyer_service import _score_lawyer

    lawyer = _lawyer("X", province="punjab", specs=["criminal"])
    _, reason = _score_lawyer(lawyer, "criminal", None)

    assert "profile match" not in reason
    assert "specializes in criminal" in reason


def test_specialization_still_outranks_a_bare_rating():
    from app.services.lawyer_service import _score_lawyer

    specialist = _lawyer("S", province="punjab", specs=["criminal"], rating=3.0, exp=3)
    generalist = _lawyer("G", province="punjab", specs=["family"], rating=5.0, exp=3)

    s, _ = _score_lawyer(specialist, "criminal", None)
    g, _ = _score_lawyer(generalist, "criminal", None)

    assert s > g
