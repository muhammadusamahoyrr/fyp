"""`ensure_indexes` must survive a legacy index name — and only that.

THE DEFECT. `chat_sessions` on a database that predates the explicit `name=`
carries Mongo's auto-generated `session_id_1`: same key, same `unique: true`.
`create_indexes` then refuses with code 85 ("Index already exists with a
different name"), the refusal propagates out of `create_all_indexes`, and
`lifespan` aborts — the whole application fails to start against a database
whose uniqueness guarantee is actually in place. Observed against a real
deployment on 2026-09-23.

WHAT MUST NOT HAPPEN WHILE FIXING IT. The module's own comment says a missing
index here "makes the guarantee silently absent, which is the worst shape a
failure takes". So a blanket `except OperationFailure: pass` would trade a loud
startup failure for a silent correctness hole. These tests pin both halves: the
legacy name is accepted, and everything else still raises.
"""
from __future__ import annotations

import secrets

import pytest

pytestmark = pytest.mark.integration


@pytest.fixture
async def surface(mongo, monkeypatch):
    """A throwaway collection registered as a conversation surface."""
    from app.db import mongodb
    from app.services import conversation_service as cs

    name = f"convidx_{secrets.token_hex(4)}"
    col = mongodb.get_database()[name]
    monkeypatch.setitem(cs._SURFACES, "idxtest", (lambda: col, "client_id"))
    cs._reset_index_cache()
    yield col
    cs._reset_index_cache()
    await col.drop()


async def _index_names(col) -> set[str]:
    return {i["name"] async for i in col.list_indexes()}


async def test_the_legacy_auto_named_index_is_accepted(surface):
    """THE regression. `session_id_1` carries the identical guarantee."""
    from pymongo import ASCENDING
    from app.services import conversation_service as cs

    # Exactly what an older deployment has: created without an explicit name.
    await surface.create_index([("session_id", ASCENDING)], unique=True)
    assert "session_id_1" in await _index_names(surface)

    await cs.ensure_indexes("idxtest")          # must not raise

    names = await _index_names(surface)
    assert "session_id_1" in names, "the existing index was dropped"
    assert "session_id_unique" not in names, "a duplicate index was created"


async def test_a_fresh_collection_gets_the_named_index(surface):
    from app.services import conversation_service as cs

    await cs.ensure_indexes("idxtest")

    assert "session_id_unique" in await _index_names(surface)


async def test_a_NON_unique_legacy_index_gets_the_real_one_alongside(surface):
    """MEASURED 2026-09-23, against MongoDB 8.2, because the first version of
    this test asserted the opposite and was wrong.

    Mongo raises code 85 only when the existing index is EQUIVALENT — same
    keys, same options. A non-unique `session_id_1` differs, so the create
    succeeds and the unique index is added beside it. Nothing is swallowed,
    because nothing was raised: the guarantee ends up enforced either way.
    """
    from pymongo import ASCENDING
    from app.services import conversation_service as cs

    await surface.create_index([("session_id", ASCENDING)])   # NOT unique

    await cs.ensure_indexes("idxtest")                        # no raise

    assert "session_id_unique" in await _index_names(surface)


async def test_a_partial_unique_legacy_index_gets_the_real_one_alongside(surface):
    """Same measured behaviour: a partial index is not equivalent either, so
    the unqualified unique index is created and covers the rows the partial
    one exempts."""
    from pymongo import ASCENDING
    from app.services import conversation_service as cs

    await surface.create_index(
        [("session_id", ASCENDING)], unique=True,
        partialFilterExpression={"session_id": {"$type": "string"}})

    await cs.ensure_indexes("idxtest")                        # no raise

    assert "session_id_unique" in await _index_names(surface)


async def test_the_equivalence_check_refuses_anything_weaker(surface):
    """The safety property, tested where it lives.

    `ensure_indexes` only tolerates code 85 when this returns True, so this is
    what stands between "a legacy name is fine" and "any existing index is
    fine". Mongo does not currently raise 85 for the weaker shapes below — the
    two tests above measure that — so the guard is asserted directly rather
    than through a Mongo behaviour that would have to be faked.
    """
    from pymongo import ASCENDING
    from app.services import conversation_service as cs

    assert await cs._session_id_uniqueness_already_enforced(surface) is False

    await surface.create_index([("session_id", ASCENDING)])
    assert await cs._session_id_uniqueness_already_enforced(surface) is False, (
        "a NON-unique index was accepted as enforcing uniqueness")
    await surface.drop_index("session_id_1")

    await surface.create_index(
        [("session_id", ASCENDING)], unique=True,
        partialFilterExpression={"session_id": {"$type": "string"}})
    assert await cs._session_id_uniqueness_already_enforced(surface) is False, (
        "a PARTIAL unique index was accepted; it exempts what its filter excludes")
    await surface.drop_index("session_id_1")

    await surface.create_index([("client_id", ASCENDING)], unique=True)
    assert await cs._session_id_uniqueness_already_enforced(surface) is False, (
        "a unique index on a DIFFERENT field was accepted")
    await surface.drop_index("client_id_1")

    await surface.create_index([("session_id", ASCENDING)], unique=True)
    assert await cs._session_id_uniqueness_already_enforced(surface) is True


async def test_the_guarantee_actually_holds_after_acceptance(surface):
    """Not just that startup proceeded — that a duplicate is still refused."""
    from pymongo import ASCENDING
    from pymongo.errors import DuplicateKeyError
    from app.services import conversation_service as cs

    await surface.create_index([("session_id", ASCENDING)], unique=True)
    await cs.ensure_indexes("idxtest")

    await surface.insert_one({"session_id": "S1", "client_id": "C"})
    with pytest.raises(DuplicateKeyError):
        await surface.insert_one({"session_id": "S1", "client_id": "C"})
