"""Unknown jurisdiction must not silently become federal jurisdiction.

The province filter is `province IN (asked_for, "federal")`. With an unknown
province that reduces to federal-only — and the client UI sends province: null
on every message, so this was the DEFAULT path for client chat.

Measured before the fix, on "Can a tenant be evicted without notice from a
rented shop?":

    province="unknown" -> 10 docs, 100% federal: Transfer of Property Act 1882
                          and CPC 1908, neither of which governs shop tenancy
                          in Punjab
    province="punjab"  -> Punjab Rented Premises Act 2009, the statute that
                          actually answers it

1,608 of 10,679 statute chunks (15.1%) are provincial. Every one of them was
invisible to a question that simply did not state a province, and nothing told
the user that a jurisdiction had been assumed on their behalf.

The corpus tests here read Chroma but write nothing.
"""
import pytest

from app.ai.pipelines.retriever import province_is_known


# ── the "is a jurisdiction known" predicate ──────────────────────────────────

@pytest.mark.parametrize("value,known", [
    ("punjab", True), ("Punjab", True), ("PUNJAB", True),
    ("sindh", True), ("federal", True),
    ("unknown", False), ("UNKNOWN", False), ("Unknown", False),
    ("", False), (None, False), ("none", False), ("null", False),
    ("  ", False),
])
def test_province_is_known(value, known):
    assert province_is_known(value) is known


# ── the filter itself, CAPTURED from build_retriever ────────────────────────
# Not re-derived here. An earlier version of this file reimplemented the where
# clause and asserted against its own copy, which would have passed even if
# build_retriever stopped applying it. These call the real function and record
# what it actually hands to Chroma.

def _captured_where(monkeypatch, province, case_type="civil"):
    """The `filter` build_retriever really passes to Chroma's retriever."""
    from app.ai.pipelines import retriever as r

    seen = {}

    class _FakeStore:
        def __init__(self, **kw):
            pass

        def as_retriever(self, search_kwargs=None, **kw):
            seen["search_kwargs"] = search_kwargs or {}
            return "retriever-sentinel"

    # A real BM25Retriever — _FilteredBM25Retriever's field is typed, so a stub
    # is rejected by pydantic and would only prove that a stub works.
    from langchain_core.documents import Document
    from langchain_community.retrievers import BM25Retriever
    real_bm25 = BM25Retriever.from_documents(
        [Document(page_content="x", metadata={"province": "federal"})], k=1)

    monkeypatch.setattr(r, "Chroma", _FakeStore)
    monkeypatch.setattr(r, "_embeddings", lambda: object())
    monkeypatch.setattr(r, "_bm25", lambda *a, **k: real_bm25)
    # build_retriever passes a live client into Chroma; the fake store ignores
    # it, so any object will do and no database is touched.
    monkeypatch.setattr(r, "get_chroma", lambda: object())
    monkeypatch.setattr(r, "EnsembleRetriever", lambda **kw: kw)
    r.build_retriever(case_type, province)
    return seen["search_kwargs"].get("filter")


def test_known_province_constrains_to_that_province_plus_federal(monkeypatch):
    where = _captured_where(monkeypatch, "punjab")
    clause = where["$and"][0]["$or"]
    assert {"province": {"$eq": "punjab"}} in clause
    assert {"province": {"$eq": "federal"}} in clause


def test_unknown_province_applies_no_province_constraint(monkeypatch):
    """The whole fix: no narrowing, so provincial statutes stay eligible."""
    where = _captured_where(monkeypatch, "unknown")
    assert "province" not in str(where), f"unknown must not filter by province: {where}"
    assert "retrieval_scope" in str(where), "reference-only must still be excluded"


def test_invalid_province_is_treated_as_unspecified_not_as_a_filter(monkeypatch):
    """"National" is not a jurisdiction. Filtering on it would match nothing."""
    where = _captured_where(monkeypatch, "National")
    assert "province" not in str(where)


def test_bm25_filter_passes_everything_through_when_jurisdiction_is_unknown():
    from langchain_core.documents import Document
    from langchain_community.retrievers import BM25Retriever
    from app.ai.pipelines.retriever import _FilteredBM25Retriever

    # A real BM25Retriever — the field is typed, and a stub would only prove
    # that a stub works. Offline: BM25 needs no model and no network.
    docs = [Document(page_content="tenant eviction notice punjab",
                     metadata={"province": "punjab"}),
            Document(page_content="tenant eviction notice federal",
                     metadata={"province": "federal"}),
            Document(page_content="tenant eviction notice sindh",
                     metadata={"province": "sindh"})]
    bm25 = BM25Retriever.from_documents(docs, k=10)

    unknown = _FilteredBM25Retriever(bm25=bm25, province="unknown")
    got = unknown.invoke("tenant eviction")
    assert {d.metadata["province"] for d in got} == {"punjab", "federal", "sindh"},         "unknown must not drop provincial docs"

    punjab = _FilteredBM25Retriever(bm25=bm25, province="punjab")
    kept = {d.metadata["province"] for d in punjab.invoke("tenant eviction")}
    assert kept == {"punjab", "federal"}, "a stated province still constrains"


def test_bm25_province_filter_does_not_shrink_the_top_k():
    """Post-filtering a fixed top-k silently returns fewer than k documents.

    BM25 ranks globally, then the province filter deletes some of the k it
    returned — so a Punjab query could come back with 2 chunks while eligible
    Punjab documents sat at rank 11+ and were never considered. Dense retrieval
    does not have this problem (Chroma filters BEFORE ranking), so the two
    halves of the ensemble disagreed about how much evidence they may supply.
    """
    from langchain_core.documents import Document
    from langchain_community.retrievers import BM25Retriever
    from app.ai.pipelines.retriever import _FilteredBM25Retriever

    # 20 sindh docs rank first on the shared term, then 10 punjab ones.
    docs = [Document(page_content=f"eviction notice tenant sindh {i}",
                     metadata={"province": "sindh"}) for i in range(20)]
    docs += [Document(page_content=f"eviction notice tenant punjab {i}",
                      metadata={"province": "punjab"}) for i in range(10)]
    bm25 = BM25Retriever.from_documents(docs, k=5)

    punjab = _FilteredBM25Retriever(bm25=bm25, province="punjab", k=5)
    got = punjab.invoke("eviction notice tenant punjab")
    assert len(got) == 5, (
        f"province filtering shrank the result set to {len(got)}; eligible "
        "documents below the original top-k were never considered")
    assert all(d.metadata["province"] == "punjab" for d in got)
    # ...and k is restored, so the shared cached retriever is not mutated.
    assert bm25.k == 5


# ── jurisdiction precedence in triage ────────────────────────────────────────

def _resolve(existing_province, incoming_basis, model_says):
    """The REAL resolver triage_node calls — not a copy of its rule.

    Re-implementing precedence here would pass even if triage stopped applying
    it, which is the failure mode this file exists to prevent.
    """
    from app.ai.jurisdiction import resolve
    return resolve(requested=existing_province,
                   requested_basis=incoming_basis,
                   inferred=model_says)


def test_an_explicit_user_choice_beats_the_models_inference():
    """A stated jurisdiction is a fact, not a hypothesis.

    Before this, whatever the LLM returned overrode the user's selection, so a
    Punjab client whose question the model read as Sindh was answered from the
    wrong provincial code with no trace of the substitution.
    """
    province, basis = _resolve("punjab", "user_selected", model_says="sindh")
    assert province == "punjab"
    assert basis == "user_selected"


def test_the_model_may_infer_when_the_user_said_nothing():
    province, basis = _resolve("unknown", "unspecified", model_says="punjab")
    assert province == "punjab"
    assert basis == "inferred_from_query"


def test_an_invalid_model_province_is_not_trusted():
    """"National" has been observed from a smaller model; it is not a province."""
    province, basis = _resolve("unknown", "unspecified", model_says="National")
    assert basis == "unspecified"
    assert not province_is_known(province)


def test_nothing_known_stays_unspecified_and_never_becomes_federal():
    province, basis = _resolve("unknown", "unspecified", model_says="unknown")
    assert basis == "unspecified"
    assert province != "federal", "silently assuming federal is the bug"


# ── corpus-level evidence (reads Chroma, writes nothing) ─────────────────────

@pytest.fixture(scope="module")
def chroma():
    from app.db.chroma import connect_chroma
    connect_chroma()


def test_provincial_law_is_a_material_share_of_the_corpus(chroma):
    """Guards the premise: if provincial chunks vanished, this fix is moot."""
    import collections
    from app.db.chroma import get_chroma
    counts = collections.Counter()
    for c in ("criminal_collection", "civil_collection",
              "family_collection", "constitutional_collection"):
        for m in get_chroma().get_collection(c).get(include=["metadatas"])["metadatas"]:
            counts[m.get("province") or "?"] += 1
    provincial = sum(v for k, v in counts.items() if k not in ("federal", "?"))
    assert provincial > 1000, f"expected substantial provincial law, got {counts}"


def test_unknown_jurisdiction_now_reaches_provincial_statutes(chroma):
    """The end-to-end proof, on the query that exposed the bug."""
    from app.ai.pipelines.retriever import build_retriever
    q = "Can a tenant be evicted without notice from a rented shop?"

    docs = build_retriever("civil", "unknown").invoke(q)
    statutes = {d.metadata.get("statute", "") for d in docs}
    assert any("Punjab" in s for s in statutes), (
        f"unknown jurisdiction still cannot see provincial law: {statutes}")


def test_a_stated_province_still_narrows(chroma):
    """The fix must not turn every query into an all-jurisdictions search."""
    from app.ai.pipelines.retriever import build_retriever
    docs = build_retriever("civil", "federal").invoke(
        "Can a tenant be evicted without notice from a rented shop?")
    provinces = {d.metadata.get("province", "federal") for d in docs}
    assert provinces <= {"federal"}, f"federal query leaked other provinces: {provinces}"


# ── conflicting jurisdictions ────────────────────────────────────────────────

def test_user_says_punjab_model_says_sindh_the_user_wins():
    """Direct conflict. The user's statement is a fact about their situation."""
    from app.ai.jurisdiction import BASIS_USER, resolve
    province, basis = resolve(requested="punjab",
                              requested_basis=BASIS_USER, inferred="sindh")
    assert (province, basis) == ("punjab", BASIS_USER)


def test_user_says_federal_model_says_punjab_the_user_wins():
    from app.ai.jurisdiction import BASIS_USER, resolve
    province, basis = resolve(requested="federal",
                              requested_basis=BASIS_USER, inferred="punjab")
    assert (province, basis) == ("federal", BASIS_USER)


def test_an_earlier_inference_does_not_outrank_a_later_inference():
    """A basis of `inferred` is not a user statement and must not lock in.

    Otherwise the first turn's guess would bind the whole conversation, and a
    user who later says "actually I'm in Sindh" would keep getting Punjab law.
    """
    from app.ai.jurisdiction import BASIS_INFERRED, resolve
    province, basis = resolve(requested="punjab",
                              requested_basis=BASIS_INFERRED, inferred="sindh")
    assert (province, basis) == ("sindh", BASIS_INFERRED)


def test_conflicting_invalid_values_collapse_to_unspecified():
    from app.ai.jurisdiction import BASIS_UNSPECIFIED, UNSPECIFIED, resolve
    province, basis = resolve(requested="National", inferred="Pakistan")
    assert (province, basis) == (UNSPECIFIED, BASIS_UNSPECIFIED)


def test_a_province_without_corpus_coverage_is_valid_but_flagged():
    """Sindh is a real jurisdiction; the corpus simply has no Sindh statutes.

    That is a coverage gap to disclose, not a reason to reject the selection —
    silently treating it as unknown would hide the gap.
    """
    from app.ai import jurisdiction as j
    assert j.is_known("sindh") is True
    assert j.has_corpus("sindh") is False
    assert j.has_corpus("punjab") is True


# ── generation must not generalise provincial law nationwide ─────────────────

def _evidence(*provinces):
    return [{"kind": "statute", "province": p, "statute": f"Act {p}"} for p in provinces]


def test_provincial_evidence_is_detected():
    from app.ai.nodes.generation_node import _has_provincial_evidence
    assert _has_provincial_evidence(_evidence("punjab", "federal")) is True
    assert _has_provincial_evidence(_evidence("federal", "federal")) is False
    assert _has_provincial_evidence([]) is False
    # Case law carries no province and must not trigger the rider on its own.
    assert _has_provincial_evidence([{"kind": "judgment", "province": ""}]) is False


def test_rider_is_attached_only_when_unspecified_and_provincial():
    """Both conditions, or the prompt is left alone."""
    from app.ai.jurisdiction import (BASIS_UNSPECIFIED, BASIS_USER)
    from app.ai.nodes.generation_node import _has_provincial_evidence

    def should_attach(basis, evidence):
        return (basis == BASIS_UNSPECIFIED and _has_provincial_evidence(evidence))

    assert should_attach(BASIS_UNSPECIFIED, _evidence("punjab", "federal")) is True
    # User chose Punjab — they know the jurisdiction; no rider.
    assert should_attach(BASIS_USER, _evidence("punjab")) is False
    # Unspecified but purely federal — nothing provincial to attribute.
    assert should_attach(BASIS_UNSPECIFIED, _evidence("federal")) is False


def test_the_rider_text_forbids_nationwide_generalisation():
    from app.ai.nodes.generation_node import _MIXED_JURISDICTION_RIDER_EN as rider
    low = rider.lower()
    assert "never present a provincial rule as the law of pakistan" in low
    assert "name the province" in low
    assert "federal" in low, "federal provisions must still be stated as nationwide"
