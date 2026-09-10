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
import asyncio

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

    # Clear first, not only on teardown. A run killed mid-test (a dropped
    # connection, a Ctrl-C) leaves these documents behind and every later run
    # then dies on a duplicate _id in setup rather than on anything real.
    await get_users_col().delete_many({"_id": {"$regex": "^LM-"}})
    await get_cases_col().delete_many({"_id": {"$regex": "^LM-"}})

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

    results = (await lawyer_service.match_lawyers_for_case("LM-CASE"))["matches"]

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

    results = (await lawyer_service.match_lawyers_for_case("LM-CASE"))["matches"]
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

    results = (await lawyer_service.match_lawyers_for_case("LM-CASE"))["matches"]

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

    results = (await lawyer_service.match_lawyers_for_case("LM-CASE"))["matches"]
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

    results = (await lawyer_service.match_lawyers_for_case("LM-CASE"))["matches"]

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

    results = (await lawyer_service.match_lawyers_for_case("LM-CASE"))["matches"]

    assert "LM-CRIM" not in {r["_id"] for r in results}


# ── a listing is not a match ─────────────────────────────────────────────────

async def test_a_real_match_is_labelled_matched(pool, monkeypatch):
    from app.services import lawyer_service

    _fake_hits(monkeypatch, [])
    _forget_spy(monkeypatch)

    out = await lawyer_service.match_lawyers_for_case("LM-CASE")

    assert out["result_kind"] == "matched"
    assert out["notice"] is None
    assert all(m["match_score"] is not None for m in out["matches"])


async def test_nothing_matching_returns_a_listing_not_a_ranked_list(pool, monkeypatch):
    """The previous behaviour emitted these as scored matches with the caveat
    in a `match_reason` suffix the frontend never rendered."""
    from app.db.collections import get_cases_col
    from app.services import lawyer_service

    # no lawyer on the platform does constitutional work in Punjab
    await get_cases_col().update_one(
        {"_id": "LM-CASE"}, {"$set": {"case_type": "constitutional"}}
    )
    _fake_hits(monkeypatch, [])
    _forget_spy(monkeypatch)

    out = await lawyer_service.match_lawyers_for_case("LM-CASE")

    assert out["result_kind"] == "general_listing"
    assert out["notice"] and "punjab" in out["notice"]
    assert out["matches"], "a listing was available but was not returned"
    # structurally distinct: nothing here can be rendered as a ranked score
    assert all(m["match_score"] is None for m in out["matches"])
    assert all(m["match_reason"] is None for m in out["matches"])


async def test_an_unverified_lawyer_is_never_surfaced_even_as_a_listing(
    pool, monkeypatch
):
    """The deleted final fallback queried role=lawyer with no KYC filter at
    all, so anyone who had merely registered could be shown to a client."""
    from app.db.collections import get_cases_col, get_users_col
    from app.services import lawyer_service

    await get_users_col().update_many(
        {"_id": {"$regex": "^LM-"}, "role": "lawyer"},
        {"$set": {"lawyer_profile.kyc_verified": False}},
    )
    await get_cases_col().update_one(
        {"_id": "LM-CASE"}, {"$set": {"case_type": "constitutional"}}
    )
    _fake_hits(monkeypatch, [])
    _forget_spy(monkeypatch)

    out = await lawyer_service.match_lawyers_for_case("LM-CASE")

    assert out["matches"] == []
    assert out["result_kind"] == "none"
    assert "verified" in out["notice"]


async def test_the_listing_prefers_the_case_province_before_widening(
    pool, monkeypatch
):
    from app.db.collections import get_cases_col
    from app.services import lawyer_service

    await get_cases_col().update_one(
        {"_id": "LM-CASE"},
        {"$set": {"case_type": "constitutional", "province": "sindh"}},
    )
    _fake_hits(monkeypatch, [])
    _forget_spy(monkeypatch)

    out = await lawyer_service.match_lawyers_for_case("LM-CASE")

    assert out["result_kind"] == "general_listing"
    assert {m["_id"] for m in out["matches"]} == {"LM-SINDH"}


# ── the index is maintained by the app, not by an admin remembering to ───────

@pytest.fixture
def index_spy(monkeypatch):
    """Record embed/forget calls instead of touching ChromaDB or the model."""
    calls = {"embedded": [], "forgotten": []}

    def _embed(lawyer_id):
        calls["embedded"].append(lawyer_id)
        return True

    def _forget(ids):
        calls["forgotten"].extend(ids)
        return len(list(ids))

    monkeypatch.setattr("app.ai.lawyer_embeddings.schedule_embed", _embed, raising=True)
    monkeypatch.setattr("app.ai.lawyer_embeddings.forget_lawyers", _forget, raising=True)
    return calls


async def test_kyc_approval_embeds_the_lawyer(pool, index_spy):
    """`embed_lawyer`'s docstring claimed this happened from the beginning.
    Nothing called it, so the store held two smoke-test rows and no real
    lawyer."""
    from app.db.collections import get_users_col
    from app.services import admin_service

    await get_users_col().update_one(
        {"_id": "LM-CRIM"}, {"$set": {"lawyer_profile.kyc_verified": False}}
    )

    await admin_service.process_kyc("LM-CRIM", True, None,
                                    actor={"_id": "LM-ADM", "email": "a@x.test"})

    assert index_spy["embedded"] == ["LM-CRIM"]


async def test_kyc_rejection_removes_the_lawyer_from_the_index(pool, index_spy):
    """Rejection can follow an earlier approval. Nothing used to remove a
    vector once it had been written."""
    from app.services import admin_service

    await admin_service.process_kyc("LM-CRIM", False, "Bar number unverifiable",
                                    actor={"_id": "LM-ADM", "email": "a@x.test"})

    assert index_spy["forgotten"] == ["LM-CRIM"]
    assert index_spy["embedded"] == []


async def test_editing_embedded_profile_text_reindexes(pool, index_spy):
    from app.services import user_service

    await user_service.update_lawyer_profile("LM-CRIM", {"bio": "Now also does bail."})

    assert index_spy["embedded"] == ["LM-CRIM"]


async def test_editing_a_field_that_is_not_embedded_does_not_reindex(pool, index_spy):
    """An hourly-rate change must not pay for a model load."""
    from app.services import user_service

    await user_service.update_lawyer_profile("LM-CRIM", {"hourly_rate": 5000})

    assert index_spy["embedded"] == []


async def test_setting_province_reindexes_even_though_it_is_not_in_lawyer_profile(
    pool, index_spy
):
    """province lives at the TOP level, so it arrives through update_profile,
    not update_lawyer_profile — and it is both embedded text and the vector
    query's filter. Missing this hook filters a lawyer out of their own
    province."""
    from app.services import user_service

    await user_service.update_profile("LM-CRIM", {"province": "sindh"})

    assert index_spy["embedded"] == ["LM-CRIM"]


async def test_a_client_changing_province_does_not_touch_the_lawyer_index(
    pool, index_spy
):
    from app.services import user_service

    await user_service.update_profile("LM-CLIENT", {"province": "sindh"})

    assert index_spy["embedded"] == []


async def test_closing_a_lawyer_account_removes_them_from_the_index(pool, index_spy):
    """Both closure paths — self-service and admin delete — go through
    _close_account_record, so this is the single hook that covers both."""
    from app.db.collections import get_users_col
    from app.services import user_service

    user = await get_users_col().find_one({"_id": "LM-CRIM"})
    await user_service._close_account_record(user, reason="self_service")

    assert index_spy["forgotten"] == ["LM-CRIM"]


async def test_deactivating_a_lawyer_removes_them_from_the_index(pool, index_spy):
    """Deactivation via admin update_user does not go through closure."""
    from app.services import admin_service

    await admin_service.update_user("LM-CRIM", {"is_active": False},
                                    actor={"_id": "LM-ADM", "email": "a@x.test"})

    assert index_spy["forgotten"] == ["LM-CRIM"]


async def test_an_unverified_lawyer_is_never_embedded(pool, monkeypatch):
    """The gate is at the point of entry: everything in the collection is
    someone a client can be shown."""
    from app.ai import lawyer_embeddings
    from app.db.collections import get_users_col

    await get_users_col().update_one(
        {"_id": "LM-CRIM"}, {"$set": {"lawyer_profile.kyc_verified": False}}
    )

    upserted = []
    monkeypatch.setattr(
        lawyer_embeddings, "_get_collection",
        lambda: type("C", (), {"upsert": lambda self, **kw: upserted.append(kw)})(),
        raising=True,
    )

    assert await lawyer_embeddings.embed_lawyer("LM-CRIM") is False
    assert upserted == []


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


# ── province is a ranking factor, not only a filter ──────────────────────────

def test_the_local_lawyer_outranks_an_equally_qualified_federal_one():
    """Province used to be a filter and nothing more, so it could not affect an
    ordering. Because `federal` lawyers are candidates in every province, a
    well-credentialled federal advocate led the ranking in someone else's
    province and "matched to a lawyer in your province" was not what the
    ranking did."""
    from app.services.lawyer_service import _score_lawyer

    local = _lawyer("L", province="kpk", specs=["criminal"], rating=4.3, exp=11)
    federal = _lawyer("F", province="federal", specs=["criminal"], rating=4.3, exp=11)

    local_score, local_reason = _score_lawyer(local, "criminal", 0.80, case_province="kpk")
    federal_score, _ = _score_lawyer(federal, "criminal", 0.80, case_province="kpk")

    assert local_score > federal_score
    assert "practises in kpk" in local_reason


def test_being_local_does_not_beat_doing_this_kind_of_work():
    """The province weight sits deliberately below specialization: a nearby
    generalist must still lose to a same-province specialist, and proximity
    must not outweigh relevant expertise."""
    from app.services.lawyer_service import _score_lawyer

    local_generalist = _lawyer("G", province="kpk", specs=["family"], rating=4.3, exp=11)
    local_specialist = _lawyer("S", province="kpk", specs=["criminal"], rating=4.3, exp=11)

    g, _ = _score_lawyer(local_generalist, "criminal", 0.80, case_province="kpk")
    s, _ = _score_lawyer(local_specialist, "criminal", 0.80, case_province="kpk")

    assert s > g


def test_federal_earns_the_province_boost_only_on_a_federal_matter():
    """`federal` means "practises nationwide" — which is why such a lawyer is a
    candidate everywhere — not that they are local everywhere."""
    from app.services.lawyer_service import _score_lawyer

    fed = _lawyer("F", province="federal", specs=["criminal"], rating=4.3, exp=11)

    on_federal, reason = _score_lawyer(fed, "criminal", 0.80, case_province="federal")
    on_punjab, _ = _score_lawyer(fed, "criminal", 0.80, case_province="punjab")

    assert on_federal > on_punjab
    assert "practises in federal" in reason


def test_an_unknown_case_province_simply_awards_no_boost():
    from app.services.lawyer_service import _score_lawyer

    lawyer = _lawyer("X", province="punjab", specs=["criminal"])
    score, reason = _score_lawyer(lawyer, "criminal", 0.80, case_province=None)

    assert "practises in" not in reason
    assert 0.0 <= score <= 1.0


async def test_the_matcher_passes_the_case_province_through(pool, monkeypatch):
    """End to end: the boost is useless if match_lawyers_for_case forgets to
    tell _score_lawyer which province the case is in."""
    from app.services import lawyer_service

    _fake_hits(monkeypatch, [
        {"lawyer_id": "LM-CRIM", "semantic_score": 0.80, "metadata": {}},
        {"lawyer_id": "LM-SINDH", "semantic_score": 0.80, "metadata": {}},
    ])
    _forget_spy(monkeypatch)

    out = await lawyer_service.match_lawyers_for_case("LM-CASE")
    by_id = {m["_id"]: m for m in out["matches"]}

    # identical specialization and semantic score; LM-CRIM is in the case's
    # province (punjab), LM-SINDH is not
    assert by_id["LM-CRIM"]["match_score"] > by_id["LM-SINDH"]["match_score"]
    assert "practises in punjab" in by_id["LM-CRIM"]["match_reason"]


# ── similarity calibration ───────────────────────────────────────────────────

def test_off_topic_similarity_calibrates_to_no_relevance():
    """Raw e5 cosine never drops below ~0.72, so a question about baking bread
    scored 0.72-0.78 against every lawyer and the 0.60 reason threshold could
    never fire. Below the measured noise floor now means zero, not "strong"."""
    from app.ai.lawyer_embeddings import calibrate_similarity

    # measured off-topic range on 2026-09-01: min 0.7200, p50 0.7476, max 0.7837
    assert calibrate_similarity(0.7200) == 0.0
    assert calibrate_similarity(0.7476) == 0.0
    assert calibrate_similarity(0.7837) < 0.35, "off-topic must not reach 'partial'"


def test_a_genuine_best_match_calibrates_near_the_top():
    from app.ai.lawyer_embeddings import calibrate_similarity

    # measured on-topic best: 0.8506 (bail/PPC 380), 0.8330 (khula/custody)
    assert calibrate_similarity(0.8506) >= 0.60, "a real best match must read 'strong'"
    assert calibrate_similarity(0.8330) >= 0.60
    assert calibrate_similarity(0.9999) <= 1.0


def test_calibration_is_monotonic_so_ranking_is_untouched():
    """The transform may rescale but must never reorder: retrieval order was
    already good (correct specialism in the top 5 on 17 of 20 probes)."""
    from app.ai.lawyer_embeddings import calibrate_similarity

    raws = [0.60, 0.72, 0.75, 0.77, 0.80, 0.83, 0.86, 0.95]
    cal = [calibrate_similarity(r) for r in raws]
    assert cal == sorted(cal)
    assert all(0.0 <= c <= 1.0 for c in cal)


def test_query_returns_both_calibrated_and_raw(monkeypatch):
    """`raw_similarity` is kept so the calibration can be re-derived when the
    model or corpus changes."""
    from app.ai import lawyer_embeddings as le

    class _Col:
        def count(self): return 1
        def query(self, **kw):
            return {"ids": [["L1"]], "distances": [[0.15]], "metadatas": [[{}]]}

    monkeypatch.setattr(le, "_get_collection", lambda: _Col())
    monkeypatch.setattr(le, "_embeddings", lambda: type("E", (), {
        "embed_query": lambda self, t: [0.1, 0.2]})())

    out = asyncio.run(le.query_similar_lawyers("q", "punjab", 5))

    assert out[0]["raw_similarity"] == 0.85
    assert out[0]["semantic_score"] == le.calibrate_similarity(0.85)
    assert out[0]["semantic_score"] != out[0]["raw_similarity"]


# ── indexed vs. merely un-ranked ─────────────────────────────────────────────
#
# `None` buys the redistribution of the whole 0.50 semantic weight, so it has to
# mean what it says. The matcher used to pass it for any candidate the vector
# query did not return, conflating "we hold no vector for them" with "we hold
# one and it ranked poorly" — and since ranking poorly is exactly what a bad
# semantic match does, the bonus landed on the lawyers it was meant to exclude.
#
# Measured before the fix, on the real path: the same lawyer scored 0.489 when
# returned with a semantic score of 0.0 and 0.977 when the query simply left
# them out; an un-ranked lawyer took first place at 0.977 over a genuine 0.90
# semantic match at 0.912.


def _indexed(monkeypatch, ids):
    """Pretend exactly these lawyer ids hold a vector."""
    monkeypatch.setattr(
        "app.ai.lawyer_embeddings.indexed_lawyer_ids",
        lambda wanted: {i for i in wanted if i in set(ids)},
        raising=True,
    )


async def test_an_indexed_lawyer_left_out_of_the_hits_scores_zero_not_none(
    pool, monkeypatch
):
    """Falling out of the result list must not pay better than being in it."""
    from app.services.lawyer_service import match_lawyers_for_case

    _fake_hits(monkeypatch, [{"lawyer_id": "LM-CRIM", "semantic_score": 0.0}])
    _indexed(monkeypatch, ["LM-CRIM"])
    ranked = await match_lawyers_for_case("LM-CASE")
    with_hit = [m for m in ranked["matches"]
                if m["_id"] == "LM-CRIM"][0]["match_score"]

    _fake_hits(monkeypatch, [])            # same lawyer, same vector, no hit
    _indexed(monkeypatch, ["LM-CRIM"])
    ranked = await match_lawyers_for_case("LM-CASE")
    without_hit = [m for m in ranked["matches"]
                   if m["_id"] == "LM-CRIM"][0]["match_score"]

    assert without_hit == with_hit


async def test_a_genuinely_unindexed_lawyer_still_gets_the_redistribution(
    pool, monkeypatch
):
    """The other half. `None` is still honest when there really is no vector:
    we have no evidence this lawyer fits badly, so we do not invent one."""
    from app.services.lawyer_service import match_lawyers_for_case

    # No hit AND no vector — the only combination that earns the `None` branch.
    _fake_hits(monkeypatch, [])
    _indexed(monkeypatch, [])
    ranked = await match_lawyers_for_case("LM-CASE")
    scored = [m for m in ranked["matches"] if m["_id"] == "LM-CRIM"][0]

    # Scored on what is known about them, not on a fabricated semantic figure.
    assert scored["match_score"] > 0.5
    assert "profile match" not in scored["match_reason"]


async def test_a_measured_match_outranks_an_unranked_higher_rated_lawyer(
    pool, monkeypatch
):
    """The inversion itself. LM-FAMILY is rated 4.9 to LM-CRIM's 4.5 but does
    not specialise in this case type; LM-CRIM is the measured 0.90 match."""
    from app.db.collections import get_users_col
    from app.services.lawyer_service import match_lawyers_for_case

    # Put both in the Mongo pool for a criminal case.
    await get_users_col().update_one(
        {"_id": "LM-FAMILY"},
        {"$set": {"lawyer_profile.specializations": ["family", "criminal"]}},
    )
    _fake_hits(monkeypatch, [{"lawyer_id": "LM-CRIM", "semantic_score": 0.90}])
    _indexed(monkeypatch, ["LM-CRIM", "LM-FAMILY"])

    ranked = await match_lawyers_for_case("LM-CASE")
    assert ranked["matches"][0]["_id"] == "LM-CRIM"


# ── the vector store membership rule cuts both ways ──────────────────────────

async def test_reactivating_a_lawyer_puts_them_back_in_the_index(pool, index_spy):
    """Deactivation dropped the vector and reactivation put nothing back, so a
    restored lawyer returned verified, active and searchable in MongoDB while
    permanently absent from semantic matching."""
    from app.services import admin_service

    await admin_service.update_user("LM-CRIM", {"is_active": False}, actor=None)
    assert index_spy["forgotten"] == ["LM-CRIM"]

    await admin_service.update_user("LM-CRIM", {"is_active": True}, actor=None)
    assert index_spy["embedded"] == ["LM-CRIM"]


async def test_an_already_active_lawyer_is_not_reindexed_by_an_unrelated_edit(
    pool, index_spy
):
    """Only the transition back into matchability re-indexes. An admin editing
    a phone number must not pay for a model load."""
    from app.services import admin_service

    await admin_service.update_user("LM-CRIM", {"phone": "0300-1111111"},
                                    actor=None)
    assert index_spy["embedded"] == []
    assert index_spy["forgotten"] == []


async def test_an_embed_is_abandoned_if_the_lawyer_stops_being_matchable(
    pool, monkeypatch
):
    """The gate ran before a multi-second model load. An admin rejecting KYC
    inside that window called `forget_lawyers` on a row that did not exist yet,
    and the upsert then landed after the removal — seating a rejected lawyer in
    the candidate pool with nothing left to take them out."""
    import app.ai.lawyer_embeddings as le
    from app.db.collections import get_users_col

    upserted: list[str] = []

    class _Col:
        def upsert(self, **kw):
            upserted.append(kw["ids"][0])

    class _Model:
        def embed_documents(self, texts):
            return [[0.0] * 768]

    async def _slow(fn, arg):
        await get_users_col().update_one(
            {"_id": "LM-CRIM"},
            {"$set": {"lawyer_profile.kyc_verified": False}},
        )
        return fn(arg)

    monkeypatch.setattr(le, "_get_collection", lambda: _Col(), raising=True)
    monkeypatch.setattr(le, "_embeddings", lambda: _Model(), raising=True)
    monkeypatch.setattr(le.asyncio, "to_thread", _slow, raising=True)

    assert await le.embed_lawyer("LM-CRIM") is False
    assert upserted == []


async def test_taking_on_a_case_reindexes_the_lawyer(pool, index_spy):
    """`build_profile_text` describes a lawyer by their five most recent cases,
    but nothing re-ran it when that work changed. The design note names "closes
    a case"; there is no close-case action, and cases are read with no status
    filter, so assignment is the moment the text actually changes."""
    from app.ai.lawyer_embeddings import schedule_embed

    schedule_embed("LM-CRIM")   # what accept_engagement now calls
    assert index_spy["embedded"] == ["LM-CRIM"]


# ── who is reachable at all ──────────────────────────────────────────────────

async def test_a_federal_lawyer_is_reachable_when_the_vector_store_is_down(
    pool, monkeypatch
):
    """The vector pool has always treated `federal` as a candidate in every
    province; the MongoDB pool did not. A nationwide advocate with no vector was
    therefore reachable through neither, and the two pools — whose whole purpose
    is to cover for each other — disagreed about who exists."""
    from app.db.collections import get_users_col
    from app.services.lawyer_service import match_lawyers_for_case

    await get_users_col().insert_one(
        _lawyer("LM-FED", province="federal", specs=["criminal"], rating=4.0)
    )

    async def _down(**kwargs):
        raise RuntimeError("chroma unavailable")

    monkeypatch.setattr("app.ai.lawyer_embeddings.query_similar_lawyers",
                        _down, raising=True)

    ranked = await match_lawyers_for_case("LM-CASE")
    assert "LM-FED" in [m["_id"] for m in ranked["matches"]]


async def test_a_lawyer_with_no_rating_field_is_still_matchable(pool, monkeypatch):
    """A `$gte` of 0.0 reads as inert and is not: in MongoDB a document whose
    `lawyer_profile.rating` key is ABSENT does not satisfy it. Such a lawyer
    vanished from search, from the match pool and from the general listing at
    once, and the client was told no verified lawyers existed."""
    from app.db.collections import get_users_col
    from app.services.lawyer_service import match_lawyers_for_case

    _fake_hits(monkeypatch, [])
    await get_users_col().update_one(
        {"_id": "LM-CRIM"}, {"$unset": {"lawyer_profile.rating": ""}}
    )

    ranked = await match_lawyers_for_case("LM-CASE")
    assert ranked["result_kind"] == "matched"
    assert "LM-CRIM" in [m["_id"] for m in ranked["matches"]]


# ── what reaches the client ──────────────────────────────────────────────────

async def test_the_internal_embedding_never_reaches_a_client(pool, monkeypatch):
    """`UserProfileResponse` passes `lawyer_profile` through as a raw dict, so a
    field inside the sub-document is not covered by the top-level whitelist.
    `lawyer_service` kept a third private copy of the sanitiser that stripped the
    two top-level secrets and not this — the exact failure
    `admin_service._safe_user` documents as the reason it stopped hand-rolling
    one."""
    from app.db.collections import get_users_col
    from app.services.lawyer_service import match_lawyers_for_case, search_lawyers

    await get_users_col().update_one(
        {"_id": "LM-CRIM"},
        {"$set": {"lawyer_profile.specialization_embedding": [0.1] * 384}},
    )
    _fake_hits(monkeypatch, [])

    ranked = await match_lawyers_for_case("LM-CASE")
    matched = [m for m in ranked["matches"] if m["_id"] == "LM-CRIM"][0]
    assert "specialization_embedding" not in (matched.get("lawyer_profile") or {})

    listed = await search_lawyers(province="punjab", case_type=None,
                                  min_rating=0.0, availability=None,
                                  page=1, page_size=10)
    browsed = [u for u in listed.items if u["_id"] == "LM-CRIM"][0]
    assert "specialization_embedding" not in (browsed.get("lawyer_profile") or {})


async def test_a_matched_lawyer_can_be_placed_on_the_map(pool, monkeypatch):
    """`_inject_coords` ran in `search_lawyers` only, so the AI-matched lawyer —
    the one the page most wants to pin — was the single lawyer without
    coordinates unless they had entered a precise address."""
    from app.services.lawyer_service import match_lawyers_for_case

    _fake_hits(monkeypatch, [])
    ranked = await match_lawyers_for_case("LM-CASE")
    matched = [m for m in ranked["matches"] if m["_id"] == "LM-CRIM"][0]

    lp = matched.get("lawyer_profile") or {}
    assert lp.get("lat") is not None and lp.get("lng") is not None


# ── eligibility on a federal matter ──────────────────────────────────────────
#
# Settled deliberately as RANK, DO NOT EXCLUDE.
#
# The two pools used to disagree in both directions. A provincial matter was
# fixed first: the vector pool admitted `federal` lawyers and the MongoDB pool
# did not, so a nationwide advocate with no vector was reachable through
# neither. The federal direction was the mirror image — the vector pool admitted
# every province while the MongoDB pool admitted only `federal`.
#
# It is resolved by widening rather than narrowing. Enrolment is not something
# this system can verify, and its own federal-forum case types (FIA cybercrime
# among them) are routinely handled by provincially enrolled advocates, so a
# filter here would be a guess at a bar rule that silently hides the right
# lawyer. The 0.17 province weight carries the distinction instead.


@pytest.fixture
async def federal_pool(pool):
    """The Punjab pool, plus a federal advocate and a federal case."""
    from app.db.collections import get_cases_col, get_users_col

    await get_users_col().insert_one(
        _lawyer("LM-FEDADV", province="federal", specs=["constitutional"],
                rating=4.0)
    )
    await get_users_col().update_one(
        {"_id": "LM-CRIM"},
        {"$set": {"lawyer_profile.specializations": ["constitutional"]}},
    )
    await get_cases_col().insert_one({
        "_id": "LM-FEDCASE", "client_id": "LM-CLIENT",
        # Explicit: `case_number` carries a plain unique index, so a second
        # case left without one collides with LM-CASE on `null`.
        "case_number": "LM-FED-0001",
        "case_type": "constitutional", "province": "federal",
        "title": "Article 199 petition",
        "description": "Constitutional petition under Article 199.",
        "status": "open"})
    yield


async def test_a_provincial_lawyer_is_eligible_for_a_federal_matter(
    federal_pool, monkeypatch
):
    """Widened, not narrowed. A Punjab advocate must stay reachable for a
    federal matter rather than being filtered out on an enrolment rule this
    system cannot verify."""
    from app.services.lawyer_service import match_lawyers_for_case

    _fake_hits(monkeypatch, [])          # MongoDB pool alone decides eligibility
    ranked = await match_lawyers_for_case("LM-FEDCASE")

    ids = [m["_id"] for m in ranked["matches"]]
    assert "LM-CRIM" in ids


async def test_the_federal_advocate_still_leads_on_a_federal_matter(
    federal_pool, monkeypatch
):
    """The other half of the decision: eligible is not the same as equal. Both
    lawyers specialise in the case type and neither has a vector, so the
    province weight is the only thing separating them — and it must."""
    from app.services.lawyer_service import match_lawyers_for_case

    _fake_hits(monkeypatch, [])
    ranked = await match_lawyers_for_case("LM-FEDCASE")

    assert ranked["matches"][0]["_id"] == "LM-FEDADV"
    assert "practises in federal" in ranked["matches"][0]["match_reason"]


async def test_a_directory_search_is_not_widened(pool):
    """`include_federal` is off by default and must stay off here. A client who
    filters the directory to Punjab means Punjab — the widening is a rule about
    MATCHING eligibility, not about what a filter means."""
    from app.db.collections import get_users_col
    from app.services.lawyer_service import search_lawyers

    await get_users_col().insert_one(
        _lawyer("LM-FEDADV2", province="federal", specs=["criminal"])
    )

    found = await search_lawyers(province="punjab", case_type=None,
                                 min_rating=0.0, availability=None,
                                 page=1, page_size=20)
    assert "LM-FEDADV2" not in [u["_id"] for u in found.items]


async def test_a_federal_listing_does_not_claim_a_place_to_practise_in(
    federal_pool, monkeypatch
):
    """The listing notice interpolates the province. Widening the federal pool
    to every province made "verified lawyers available in federal" both the
    wrong shape and the wrong claim — federal is not somewhere you practise."""
    from app.db.collections import get_users_col
    from app.services.lawyer_service import _general_listing

    # Nobody lists this case type, so the listing is what a federal case falls
    # back to.
    await get_users_col().update_many(
        {"_id": {"$regex": "^LM-"}, "role": "lawyer"},
        {"$set": {"lawyer_profile.specializations": ["family"]}},
    )
    _fake_hits(monkeypatch, [])

    listing = await _general_listing("federal", 5)
    assert listing is not None
    _, notice = listing
    assert "in federal" not in notice
    assert "for a federal matter" in notice


# ── qualification: may a candidate be called a match at all? ─────────────────
#
# `result_kind: "matched"` used to mean only "the candidate pool was not empty",
# which is a fact about the query and not about any lawyer. The vector pool
# filters on province alone, so it is almost never empty: measured on the real
# data, a Punjab criminal case admitted 10 candidates of whom 3 listed criminal.
# The other 7 were scored, ranked and returned under "AI-Recommended Match", and
# with top_n = 5 at least two of the five slots were guaranteed to be a family or
# civil specialist.
#
# The composite score cannot be the gate. A Punjab family lawyer against a
# Punjab criminal case scores 0.285 indexed at semantic 0.0 and 0.570 unindexed
# — the no-vector branch doubles the non-semantic weights, so having no evidence
# outscores having measured evidence of a poor fit.


async def test_a_zero_semantic_wrong_specialization_candidate_is_not_a_match(
    pool, monkeypatch
):
    """The headline case. LM-FAMILY is a Punjab family lawyer; the case is Punjab
    criminal. Measured relevance is zero, so province, rating, availability and
    experience are all there is — and none of them is evidence of fit."""
    from app.services.lawyer_service import match_lawyers_for_case

    _fake_hits(monkeypatch, [{"lawyer_id": "LM-FAMILY", "semantic_score": 0.0}])
    _indexed(monkeypatch, ["LM-FAMILY"])

    ranked = await match_lawyers_for_case("LM-CASE")
    assert "LM-FAMILY" not in [m["_id"] for m in ranked["matches"]]


async def test_an_unindexed_wrong_specialization_candidate_is_not_a_match(
    pool, monkeypatch
):
    """The worse half: with no vector the semantic weight is redistributed, so
    this candidate scored 0.570 — higher than the measured-and-poor one above.
    No evidence must not outrank bad evidence into a match."""
    from app.services.lawyer_service import match_lawyers_for_case

    _fake_hits(monkeypatch, [{"lawyer_id": "LM-FAMILY", "semantic_score": None}])
    _indexed(monkeypatch, [])

    ranked = await match_lawyers_for_case("LM-CASE")
    assert "LM-FAMILY" not in [m["_id"] for m in ranked["matches"]]


async def test_an_exact_specialization_candidate_qualifies_without_a_vector(
    pool, monkeypatch
):
    """Claiming the domain is evidence in its own right. A verified criminal
    lawyer must not be withheld from a criminal case merely because the index
    has not caught up with them."""
    from app.services.lawyer_service import match_lawyers_for_case

    _fake_hits(monkeypatch, [])
    _indexed(monkeypatch, [])

    ranked = await match_lawyers_for_case("LM-CASE")
    assert ranked["result_kind"] == "matched"
    assert "LM-CRIM" in [m["_id"] for m in ranked["matches"]]


async def test_strong_semantic_relevance_qualifies_without_an_exact_label(
    pool, monkeypatch
):
    """The property the design note claims and keyword search cannot give: a
    lawyer whose profile text reads like this case is reachable even though
    their `specializations` say something else. Removing this would reduce
    matching to a label lookup."""
    from app.services.lawyer_service import match_lawyers_for_case

    # LM-CIVIL lists civil only, but reads strongly like this criminal matter.
    _fake_hits(monkeypatch, [{"lawyer_id": "LM-CIVIL", "semantic_score": 0.80}])
    _indexed(monkeypatch, ["LM-CIVIL"])

    ranked = await match_lawyers_for_case("LM-CASE")
    assert "LM-CIVIL" in [m["_id"] for m in ranked["matches"]]


async def test_a_mixed_pool_returns_only_the_relevant_lawyers(pool, monkeypatch):
    """Both kinds of candidate in one pool: the relevant survive, the rest are
    dropped rather than ranked below them."""
    from app.services.lawyer_service import match_lawyers_for_case

    _fake_hits(monkeypatch, [
        {"lawyer_id": "LM-CRIM",   "semantic_score": 0.70},   # relevant
        {"lawyer_id": "LM-FAMILY", "semantic_score": 0.02},   # not
        {"lawyer_id": "LM-CIVIL",  "semantic_score": 0.05},   # not
    ])
    _indexed(monkeypatch, ["LM-CRIM", "LM-FAMILY", "LM-CIVIL"])

    ranked = await match_lawyers_for_case("LM-CASE")
    assert [m["_id"] for m in ranked["matches"]] == ["LM-CRIM"]


async def test_no_padding_when_fewer_than_top_n_qualify(pool, monkeypatch):
    """top_n is a maximum, not a quota.

    Four candidates, five slots, two qualified. LM-SINDH qualifies on an exact
    specialization despite being in the wrong province — province RANKS a
    candidate and must neither qualify nor disqualify one — while LM-FAMILY and
    LM-CIVIL are exactly the padding the old code would have used to reach five.
    """
    from app.services.lawyer_service import match_lawyers_for_case

    _fake_hits(monkeypatch, [
        {"lawyer_id": "LM-CRIM",   "semantic_score": 0.70},  # relevant
        {"lawyer_id": "LM-SINDH",  "semantic_score": 0.01},  # relevant: specialism
        {"lawyer_id": "LM-FAMILY", "semantic_score": 0.01},  # padding candidate
        {"lawyer_id": "LM-CIVIL",  "semantic_score": 0.01},  # padding candidate
    ])
    _indexed(monkeypatch, ["LM-CRIM", "LM-FAMILY", "LM-CIVIL", "LM-SINDH"])

    ranked = await match_lawyers_for_case("LM-CASE", top_n=5)

    assert {m["_id"] for m in ranked["matches"]} == {"LM-CRIM", "LM-SINDH"}
    assert len(ranked["matches"]) == 2, "slots were padded with irrelevant lawyers"


async def test_a_pool_of_only_irrelevant_lawyers_becomes_a_listing(
    pool, monkeypatch
):
    """Nothing qualifies, so the honest answer is a browse list — not a ranked
    one. The lawyers stay VISIBLE; what changes is the claim made about them."""
    from app.db.collections import get_users_col
    from app.services.lawyer_service import match_lawyers_for_case

    # Nobody on the platform does criminal work.
    await get_users_col().update_many(
        {"_id": {"$regex": "^LM-"}, "role": "lawyer"},
        {"$set": {"lawyer_profile.specializations": ["family"]}},
    )
    _fake_hits(monkeypatch, [{"lawyer_id": "LM-FAMILY", "semantic_score": 0.05}])
    _indexed(monkeypatch, ["LM-FAMILY"])

    ranked = await match_lawyers_for_case("LM-CASE")

    assert ranked["result_kind"] == "general_listing"
    assert ranked["matches"], "verified lawyers must still be offered to browse"
    # Not ranked against the case, so nothing may present them as scored.
    assert all(m["match_score"] is None for m in ranked["matches"])
    assert ranked["notice"]


async def test_verified_lawyers_stay_visible_in_the_listing(pool, monkeypatch):
    """The qualification gate must never make a KYC-verified lawyer disappear
    from the platform. It governs what we CLAIM about them, not whether they
    exist: every one of them is still reachable to browse and through search."""
    from app.db.collections import get_users_col
    from app.services.lawyer_service import match_lawyers_for_case, search_lawyers

    await get_users_col().update_many(
        {"_id": {"$regex": "^LM-"}, "role": "lawyer"},
        {"$set": {"lawyer_profile.specializations": ["family"]}},
    )
    _fake_hits(monkeypatch, [])
    _indexed(monkeypatch, [])

    ranked = await match_lawyers_for_case("LM-CASE")
    assert ranked["result_kind"] == "general_listing"
    listed = {m["_id"] for m in ranked["matches"]}
    assert {"LM-CRIM", "LM-CIVIL", "LM-FAMILY"} <= listed

    found = await search_lawyers(province="punjab", case_type=None,
                                 min_rating=0.0, availability=None,
                                 page=1, page_size=20)
    assert {"LM-CRIM", "LM-CIVIL", "LM-FAMILY"} <= {u["_id"] for u in found.items}


async def test_the_federal_widening_does_not_admit_irrelevant_lawyers(
    federal_pool, monkeypatch
):
    """Eligibility and relevance are different gates and both must hold. The
    federal rule widens WHO may be considered; it must not smuggle a lawyer
    with no evidence of fit into a match."""
    from app.db.collections import get_users_col
    from app.services.lawyer_service import match_lawyers_for_case

    # A Punjab lawyer, eligible for a federal matter under the widened rule,
    # but practising a different area of law and with no measured relevance.
    await get_users_col().insert_one(
        _lawyer("LM-PBIRREL", province="punjab", specs=["family"], rating=5.0)
    )
    _fake_hits(monkeypatch, [{"lawyer_id": "LM-PBIRREL", "semantic_score": 0.0}])
    _indexed(monkeypatch, ["LM-PBIRREL"])

    ranked = await match_lawyers_for_case("LM-FEDCASE")

    ids = [m["_id"] for m in ranked["matches"]]
    assert "LM-PBIRREL" not in ids
    # the genuinely relevant candidates are unaffected
    assert "LM-FEDADV" in ids


# ── drift between MongoDB and the vector store ───────────────────────────────
#
# Every write to `lawyers_collection` is fire-and-forget, because none of the
# actions that trigger one — approving KYC, editing a profile, accepting a case
# — should fail because an index is unavailable. The cost of that trade is
# drift, and until now nothing could observe it: a lawyer approved while Chroma
# was down was never indexed and no request path would ever notice. Repair
# existed only as a script somebody had to remember to run, which is how the
# store came to hold two smoke-test rows and no real lawyer at all.


def _index(monkeypatch, stored, *, embed_ok=True, read_raises=False):
    """Fake the vector store. Returns (embedded, forgotten) as they happen.

    `forget_lawyers` is re-patched here, not left to the fake collection's
    `delete`. The autouse `_no_background_embeds` fixture in conftest replaces
    it with a no-op so tests cannot write to the developer's real ChromaDB, and
    that no-op never reaches `_get_collection` at all — so a test asserting on
    removal has to override it and win by fixture order, exactly as that
    fixture's docstring says.
    """
    import app.ai.lawyer_embeddings as le

    embedded: list[str] = []
    forgotten: list[str] = []

    class _Col:
        def get(self, **kw):
            if read_raises:
                raise RuntimeError("chroma down")
            return {"ids": list(stored)}

    async def _embed(lawyer_id):
        if not embed_ok:
            raise RuntimeError("model unavailable")
        embedded.append(lawyer_id)
        return True

    def _forget(ids):
        forgotten.extend(ids)
        return len(list(ids))

    monkeypatch.setattr(le, "_get_collection", lambda: _Col(), raising=True)
    monkeypatch.setattr(le, "embed_lawyer", _embed, raising=True)
    monkeypatch.setattr(le, "forget_lawyers", _forget, raising=True)
    return embedded, forgotten


async def test_a_missing_lawyer_is_embedded(pool, monkeypatch):
    """The drift that matters: verified, active, matchable — and absent from the
    index, so invisible to semantic matching with nothing to report it."""
    from app.ai.lawyer_embeddings import reconcile_index

    embedded, forgotten = _index(monkeypatch, stored=[])
    report = await reconcile_index()

    assert "LM-CRIM" in embedded
    assert report["embedded"] == len(embedded)
    assert forgotten == []


async def test_a_lawyer_who_should_not_be_indexed_is_removed(pool, monkeypatch):
    """The other direction. A row for someone no longer matchable is what let
    two deleted smoke-test accounts suppress the entire real candidate pool."""
    from app.ai.lawyer_embeddings import reconcile_index

    embedded, forgotten = _index(
        monkeypatch, stored=["LM-CRIM", "LM-CIVIL", "LM-FAMILY", "LM-SINDH",
                             "a-deleted-account"])
    report = await reconcile_index()

    assert forgotten == ["a-deleted-account"]
    assert report["forgotten"] == 1
    assert embedded == []


async def test_an_index_that_already_agrees_is_left_alone(pool, monkeypatch):
    """Cheap when clean. It must not re-embed what is already there — a stale
    vector is a far smaller problem than a missing one, the next profile edit
    repairs it, and re-embedding on a schedule would put a model load on a
    machine with no GPU for nothing."""
    from app.ai.lawyer_embeddings import reconcile_index

    embedded, forgotten = _index(
        monkeypatch, stored=["LM-CRIM", "LM-CIVIL", "LM-FAMILY", "LM-SINDH"])
    report = await reconcile_index()

    assert embedded == []
    assert forgotten == []
    assert report == {"checked": 4, "embedded": 0, "refreshed": 0,
                      "forgotten": 0, "failed": 0, "skipped": 0}


async def test_an_unreadable_store_skips_the_sweep_without_forgetting_anyone(
    pool, monkeypatch
):
    """If the store cannot be read, its contents are UNKNOWN — not empty.
    Treating a failed read as an empty index would make every lawyer look
    missing and, worse, make every stored row look stale."""
    from app.ai.lawyer_embeddings import reconcile_index

    embedded, forgotten = _index(monkeypatch, stored=[], read_raises=True)
    report = await reconcile_index()

    assert embedded == []
    assert forgotten == []
    assert report["skipped"] == 1


async def test_one_failing_embed_does_not_abandon_the_rest(pool, monkeypatch):
    """A single unembeddable profile must not stop the sweep repairing the
    others, and must be counted rather than swallowed."""
    from app.ai.lawyer_embeddings import reconcile_index

    _index(monkeypatch, stored=[], embed_ok=False)
    report = await reconcile_index()

    assert report["failed"] == 4
    assert report["embedded"] == 0


async def test_an_unverified_lawyer_is_never_reconciled_into_the_index(
    pool, monkeypatch
):
    """The sweep must apply the same membership rule as everything else.
    Everything in this collection is someone a client can be shown."""
    from app.db.collections import get_users_col
    from app.ai.lawyer_embeddings import reconcile_index

    await get_users_col().insert_one(
        _lawyer("LM-UNVERIFIED", province="punjab", specs=["criminal"],
                verified=False)
    )
    embedded, _ = _index(monkeypatch, stored=[])
    await reconcile_index()

    assert "LM-UNVERIFIED" not in embedded


# ── stale vectors: indexed, but no longer describing the lawyer ──────────────
#
# The third kind of drift, and the one a set comparison structurally cannot see:
# the id is present and correct, but the vector was built from a profile that
# has since changed. It is produced by the same fire-and-forget writes as the
# others — a lawyer edits their specializations while Chroma is unreachable,
# `schedule_embed` logs and gives up — and every later sweep saw the id, called
# it healthy, and moved on.


async def test_a_changed_profile_is_detected_and_re_embedded(pool, monkeypatch):
    import app.ai.lawyer_embeddings as le

    embedded, _ = _index(
        monkeypatch,
        stored=["LM-CRIM", "LM-CIVIL", "LM-FAMILY", "LM-SINDH"],
    )
    # Every stored vector carries a fingerprint; LM-CRIM's no longer matches.
    monkeypatch.setattr(
        le, "_get_collection",
        lambda: type("C", (), {"get": staticmethod(lambda **kw: {
            "ids": ["LM-CRIM", "LM-CIVIL", "LM-FAMILY", "LM-SINDH"],
            "metadatas": [{"fingerprint": "0000000000000000"},
                          {"fingerprint": None}, {"fingerprint": None},
                          {"fingerprint": None}],
        })})(),
        raising=True,
    )

    report = await le.reconcile_index()

    assert embedded == ["LM-CRIM"], "a changed profile was not re-embedded"
    assert report["refreshed"] == 1
    assert report["embedded"] == 0, "a refresh was miscounted as a new embed"


async def test_a_vector_predating_fingerprints_is_left_alone(pool, monkeypatch):
    """Treating a missing fingerprint as stale would re-embed the whole index on
    the first sweep after deploy — a model load per lawyer, all at once, on a
    machine with no GPU, to fix nothing known to be wrong."""
    import app.ai.lawyer_embeddings as le

    embedded, forgotten = _index(
        monkeypatch, stored=["LM-CRIM", "LM-CIVIL", "LM-FAMILY", "LM-SINDH"])
    report = await le.reconcile_index()

    assert embedded == []
    assert forgotten == []
    assert report["refreshed"] == 0


async def test_an_unchanged_profile_is_not_re_embedded(pool, monkeypatch):
    """A clean sweep must load no model. Only genuinely changed profiles pay."""
    import app.ai.lawyer_embeddings as le

    current = await le.profile_fingerprint("LM-CRIM")
    assert current, "fixture lawyer has no fingerprint"

    embedded, _ = _index(monkeypatch, stored=[])
    # All four are stored. Only LM-CRIM carries a fingerprint, and it is the
    # CURRENT one — so the sweep has positive evidence that its vector is up to
    # date. The other three are deliberately left without one, which is the
    # "predates fingerprinting" case and must also not trigger work.
    monkeypatch.setattr(
        le, "_get_collection",
        lambda: type("C", (), {"get": staticmethod(lambda **kw: {
            "ids": ["LM-CRIM", "LM-CIVIL", "LM-FAMILY", "LM-SINDH"],
            "metadatas": [{"fingerprint": current}, {}, {}, {}],
        })})(),
        raising=True,
    )

    report = await le.reconcile_index()
    assert embedded == [], "an unchanged profile was needlessly re-embedded"
    assert report["refreshed"] == 0


async def test_the_fingerprint_follows_the_text_that_is_actually_embedded(pool):
    """Fingerprints the BUILT TEXT, not a hand-listed set of fields — any such
    list would drift from `build_profile_text` and then keep looking correct."""
    from app.ai.lawyer_embeddings import profile_fingerprint
    from app.db.collections import get_users_col

    before = await profile_fingerprint("LM-CRIM")
    await get_users_col().update_one(
        {"_id": "LM-CRIM"},
        {"$set": {"lawyer_profile.bio": "Now practises tax law exclusively."}},
    )
    after = await profile_fingerprint("LM-CRIM")

    assert before and after and before != after


async def test_an_unindexable_lawyer_has_no_fingerprint(pool):
    """None means 'should not be in the store', which the caller must not
    confuse with 'unchanged'."""
    from app.ai.lawyer_embeddings import profile_fingerprint
    from app.db.collections import get_users_col

    await get_users_col().update_one(
        {"_id": "LM-CRIM"}, {"$set": {"lawyer_profile.kyc_verified": False}})
    assert await profile_fingerprint("LM-CRIM") is None
