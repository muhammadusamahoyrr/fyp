"""What the AI surfaces are allowed to tell a user about their own answer.

Both chat surfaces render trust information — citation status, claim support,
repeal warnings, calibrated confidence. This file covers the three things that
were missing from that picture and the one rule they all share: a trust signal
may only say what the system can actually support.

  * a link to a cited source, and ONLY when that source can really be opened;
  * the request id, so an answer can be named — quoted in a report, or used to
    open its audit trail;
  * a lawyer-facing provenance view that shows the machinery without exposing
    prompts, secrets, or a provider's response body.

Offline. No database, no Chroma, no provider.
"""
import asyncio

import pytest

from app.ai import source_links
from app.services import provenance_view


# ── source links ─────────────────────────────────────────────────────────────
#
# A citation names a `source_file`. Measured on the live index (2026-09-02):
# 46 distinct source files over 24,851 chunks, of which 8 resolve to a PDF held
# in this repository — 12,119 chunks, 49% of the corpus. So "no link" is the
# normal outcome for half of all citations and must be a first-class answer,
# not an error and not a URL that 404s in the user's face.

@pytest.fixture
def corpus(tmp_path, monkeypatch):
    """A tiny corpus tree, so these tests do not depend on which PDFs are checked in."""
    root = tmp_path / "knowledge_base"
    (root / "raw" / "civil").mkdir(parents=True)
    (root / "raw" / "civil" / "held-here.pdf").write_bytes(b"%PDF-1.4 held")
    (root / "raw" / "notes.txt").write_text("not a servable document")
    (tmp_path / "secret.env").write_text("GROQ_API_KEY=sk-live-do-not-serve")

    monkeypatch.setattr(source_links, "_CORPUS_ROOT", root)
    source_links.refresh()
    yield root
    source_links.refresh()


def test_a_source_that_is_held_here_gets_a_link(corpus):
    assert source_links.source_url("held-here.pdf") == \
        "/api/v1/ai/source/held-here.pdf"


def test_a_source_that_is_not_held_here_gets_no_link(corpus):
    """Half the corpus. An empty string, never a URL that will 404."""
    assert source_links.source_url("punjab-tenancy-act-1887.pdf") == ""
    assert source_links.resolve("punjab-tenancy-act-1887.pdf") is None


@pytest.mark.parametrize("name", [
    "../secret.env",
    "../../secret.env",
    "raw/civil/held-here.pdf",      # a path, not a basename
    "/etc/passwd",
    "C:\\Windows\\win.ini",
    "",
    "   ",
    "held-here.pdf/../../secret.env",
])
def test_a_path_is_never_resolved_only_a_known_basename(corpus, name):
    """`source_file` is chunk metadata, so it is data.

    Resolution is a dict lookup against basenames found by scanning the corpus,
    never a path join — so these are absent from the map rather than filtered
    out of it, and a new traversal spelling cannot be invented.
    """
    assert source_links.resolve(name) is None
    assert source_links.source_url(name) == ""


def test_only_documents_are_servable(corpus):
    """A stray .txt in the corpus tree is not a citable source document."""
    assert source_links.resolve("notes.txt") is None


def test_links_are_stamped_onto_statute_citations(corpus):
    citations = [
        {"statute": "PPC 1860", "section": "302", "source": "held-here.pdf"},
        {"statute": "Punjab Tenancy Act 1887", "section": "5",
         "source": "punjab-tenancy-act-1887.pdf"},
    ]
    source_links.apply_source_links(citations)
    assert citations[0]["source_url"] == "/api/v1/ai/source/held-here.pdf"
    assert citations[1]["source_url"] == "", "an unavailable source must not be linked"


def test_a_judgment_keeps_its_own_url(corpus):
    """Judgments link to the court's own PDF; nothing here may overwrite that."""
    citations = [{"type": "judgment", "statute": "2026LHC4194",
                  "url": "https://sys.lhc.gov.pk/x.pdf", "source": "held-here.pdf"}]
    source_links.apply_source_links(citations)
    assert citations[0]["url"] == "https://sys.lhc.gov.pk/x.pdf"
    assert "source_url" not in citations[0]


def test_stamping_never_raises_and_never_drops_a_citation(corpus):
    """A link is a convenience; the citation itself is the trust signal."""
    citations = [{"statute": "PPC 1860", "section": "302"}, {}, {"source": None}]
    source_links.apply_source_links(citations)
    assert len(citations) == 3
    assert all(c.get("source_url") == "" for c in citations)


def test_an_unreadable_corpus_yields_no_links_rather_than_failing(monkeypatch):
    monkeypatch.setattr(source_links, "_CORPUS_ROOT",
                        __import__("pathlib").Path("/definitely/not/here"))
    source_links.refresh()
    try:
        assert source_links.source_url("anything.pdf") == ""
    finally:
        source_links.refresh()


# ── the lawyer provenance view ───────────────────────────────────────────────

RECORD = {
    "_id": "mongo-object-id",
    "schema_version": 3,
    "turn_type": "answer",
    "request_id": "req-abc",
    "session_id": "sess-1",
    "user_id": "lawyer-A",
    "created_at": __import__("datetime").datetime(2026, 9, 2, 10, 30),
    "query": "What notice is required to evict a tenant?",
    "normalized_query": "notice required evict tenant",
    "language": "en",
    "case_type": "civil",
    "province": "punjab",
    "case_id": "case-1",
    "case_context_supplied": True,
    "case_context_hash": "abc123",
    "case_record_version": "2026-08-30T10:00:00",
    "case_context_used_by": ["retrieval", "generation"],
    "answer_sha256": "deadbeef",
    "answer_preview": "Under the Punjab Rented Premises Act...",
    "answer_llm": {"provider": "groq", "model": "openai/gpt-oss-120b",
                   "tier": "main", "purpose": "answer_generation"},
    "answer_llm_origin": "current_turn",
    "llm_calls": [
        {"provider": "gemini", "model": "gemini-2.0-flash", "tier": "main",
         "purpose": "answer_generation", "outcome": "failure",
         "latency_ms": 120.0, "is_fallback": False, "call_id": "c1",
         "kind": "rate_limit", "status_code": 429, "cooldown_s": 60.0,
         "scope": "model"},
        {"provider": "groq", "model": "openai/gpt-oss-120b", "tier": "main",
         "purpose": "answer_generation", "outcome": "success",
         "latency_ms": 2100.0, "is_fallback": True, "call_id": "c2"},
    ],
    "citation_grounding": {"measurable": True, "cited": ["a", "b", "c"],
                           "grounded": ["a", "b"], "ungrounded": ["c"],
                           "grounded_ratio": 0.667, "retrieved_count": 12},
    "statute_chunks": [{"chunk_id": "ch1", "statute": "Punjab Rented Premises Act 2009",
                        "section_number": "30", "source_file": "prpa.pdf",
                        "province": "punjab", "law_type": "civil"}],
    "case_law": [{"judgment_id": "j1", "citation": "2026LHC4194",
                  "title": "X v. Y", "score": 0.81}],
    "tool_calls": [{"tool": "limitation_calculator", "args": {"days": "30"},
                    "ok": True, "result": "expires 2026-10-02"}],
    "web_search_used": False,
    "arbitration": {"output": "answer", "source": "decision_engine",
                    "confidence": 0.42},
    "signals": {"relevance_score": 0.61, "signal_variance": 0.04,
                "bm25_confidence": 0.55, "confidence": 0.85},
    "is_grounded": True,
    "cache_hit": False,
    "convergence_status": "converged",
    "attempts": {"retrieval": 1, "generation": 1, "clarification_depth": 0},
    "execution": {"total_ms": 4210.0, "llm_ms": 3900.0, "llm_calls": 4,
                  "tool_calls": ["limitation_calculator"], "errors": [],
                  "models": ["groq/openai/gpt-oss-120b"]},
    "versions": {"embedding_model": "multilingual-e5-base", "chunking": "v2"},
}


def test_the_view_reports_who_actually_answered():
    """Not the last successful call — that is usually the fast grounding judge."""
    view = provenance_view.build_view(RECORD)
    assert view["model"]["answered_by"]["model"] == "openai/gpt-oss-120b"
    assert view["model"]["origin"] == "current_turn"


def test_a_failover_is_visible_as_a_failover():
    """An answer served by the second provider must not look like a first-try success."""
    view = provenance_view.build_view(RECORD)
    attempts = view["model"]["attempts"]
    assert len(attempts) == 2
    assert attempts[0]["outcome"] == "failure"
    assert attempts[0]["provider"] == "gemini"
    assert attempts[1]["is_fallback"] is True


def test_a_provider_failure_is_classified_not_quoted():
    """provider_health records a fixed vocabulary and never str(exc): Groq's 429
    body carries an organization id and OpenRouter's 402 carries a user id. The
    view must not undo that by inventing a place to put one."""
    view = provenance_view.build_view(RECORD)
    failure = view["model"]["attempts"][0]
    assert failure["reason"] == "provider rate limit"
    assert failure["status_code"] == 429
    for leaked in ("message", "body", "error", "detail", "response", "kind"):
        assert leaked not in failure


def test_an_unrecognised_failure_kind_still_says_nothing_specific():
    record = {**RECORD, "llm_calls": [
        {"provider": "p", "model": "m", "outcome": "failure",
         "kind": "something_new_we_have_not_mapped", "status_code": 500}]}
    view = provenance_view.build_view(record)
    assert view["model"]["attempts"][0]["reason"] == "provider call failed"


def test_the_view_carries_no_prompt_no_secret_and_no_chunk_text():
    """The stored record holds none of these; the view must not reconstruct them."""
    view = provenance_view.build_view({
        **RECORD,
        # Fields a future build_record might add. A view built by subtraction
        # would publish each of them the day it was added.
        "system_prompt": "You are an expert Pakistani legal assistant...",
        "rendered_prompt": "--- CASE ON FILE ---",
        "api_key": "sk-live-000",
        "case_context": {"title": "Ali v. Landlord", "description": "secret facts"},
    })
    blob = repr(view)
    for secret in ("You are an expert", "CASE ON FILE", "sk-live-000",
                   "Ali v. Landlord", "secret facts", "expires 2026-10-02"):
        assert secret not in blob, f"{secret!r} reached the lawyer view"


def test_the_view_is_a_whitelist_not_a_blacklist():
    """The property the test above depends on, stated directly."""
    view = provenance_view.build_view({**RECORD, "a_brand_new_field": "surprise"})
    assert "a_brand_new_field" not in view
    assert "surprise" not in repr(view)


def test_the_view_never_carries_the_internal_document_id_or_owner():
    view = provenance_view.build_view(RECORD)
    assert "_id" not in view
    assert "user_id" not in view


def test_the_view_identifies_the_case_without_copying_its_facts():
    view = provenance_view.build_view(RECORD)
    assert view["case"]["case_id"] == "case-1"
    assert view["case"]["context_hash"] == "abc123"
    assert view["case"]["used_by"] == ["retrieval", "generation"]


def test_citation_grounding_is_reported_as_a_measurement():
    view = provenance_view.build_view(RECORD)
    grounding = view["citation_grounding"]
    assert grounding["measurable"] is True
    assert grounding["cited_count"] == 3
    assert grounding["grounded_count"] == 2
    assert grounding["ungrounded"] == ["c"], \
        "a lawyer's question is WHICH citation could not be placed"


def test_an_answer_with_no_parseable_citation_is_not_reported_as_ungrounded():
    """`measurable: false` means there was nothing to ground. That is not a finding."""
    view = provenance_view.build_view({
        **RECORD,
        "citation_grounding": {"measurable": False, "reason": "No parseable citation",
                               "cited": [], "grounded": [], "ungrounded": [],
                               "grounded_ratio": None},
    })
    grounding = view["citation_grounding"]
    assert grounding["measurable"] is False
    assert grounding["grounded_ratio"] is None
    assert grounding["reason"]


def test_the_view_is_json_safe():
    """Mongo hands back ObjectId and datetime; a route must not have to remember."""
    import json

    class Oid:
        def __repr__(self):
            return "ObjectId('x')"

    view = provenance_view.build_view({**RECORD, "request_id": Oid()})
    json.dumps(view)   # raises if anything survived unconverted
    assert isinstance(view["created_at"], str)
    assert view["created_at"].startswith("2026-09-02")


def test_the_evidence_is_identified_not_reproduced():
    """Chunk ids let a lawyer re-fetch the evidence; the view is not a copy of it."""
    view = provenance_view.build_view(RECORD)
    statute = view["evidence"]["statutes"][0]
    assert statute["chunk_id"] == "ch1"
    assert statute["section"] == "30"
    assert "content" not in statute and "text" not in statute


def test_a_tool_call_reports_that_it_ran_not_what_it_returned():
    view = provenance_view.build_view(RECORD)
    tool = view["evidence"]["tools"][0]
    assert tool == {"tool": "limitation_calculator", "ok": True}


def test_the_view_carries_the_versions_needed_to_reproduce_it():
    view = provenance_view.build_view(RECORD)
    assert view["versions"]["embedding_model"] == "multilingual-e5-base"
    assert view["versions"]["chunking"] == "v2"


def test_a_repaired_turn_says_so():
    """An answer produced from repaired-and-suspect state reached the user anyway."""
    view = provenance_view.build_view(
        {**RECORD, "invariant_violation": "grader returned no grades"})
    assert view["invariant_violation"] == "grader returned no grades"


def test_no_record_yields_no_view():
    assert provenance_view.build_view(None) is None
    assert provenance_view.build_view({}) is None


def test_a_partial_record_does_not_break_the_view():
    """Old records predate fields the view reads; the audit must still open."""
    view = provenance_view.build_view({"request_id": "req-old"})
    assert view["request_id"] == "req-old"
    assert view["model"]["attempts"] == []
    assert view["evidence"]["statutes"] == []
    assert view["case"]["context_supplied"] is False


# ── route: who may read a provenance view ────────────────────────────────────

@pytest.fixture
def route(monkeypatch):
    import app.api.v1.routes.provenance as routes
    seen = {}

    async def get_by_request(request_id, user_id):
        seen["request_id"] = request_id
        seen["user_id"] = user_id
        return RECORD if request_id == "req-abc" else None

    monkeypatch.setattr(routes.provenance_service, "get_by_request", get_by_request)
    return routes, seen


def test_the_view_route_is_scoped_to_the_caller(route):
    routes, seen = route
    asyncio.run(routes.get_provenance_view(
        "req-abc", current_user={"_id": "lawyer-A", "role": "lawyer"}))
    assert seen["user_id"] == "lawyer-A", \
        "user_id must be pushed into the query, not checked after the fact"


def test_someone_elses_request_id_is_not_found(route):
    """The lookup is owner-filtered, so another user's record simply is not there."""
    from fastapi import HTTPException
    routes, _ = route
    with pytest.raises(HTTPException) as exc:
        asyncio.run(routes.get_provenance_view(
            "req-does-not-exist", current_user={"_id": "lawyer-A", "role": "lawyer"}))
    assert exc.value.status_code == 404


def test_a_missing_record_and_another_users_record_look_the_same(route):
    """Distinguishing them would confirm that someone else's request id exists."""
    from fastapi import HTTPException
    routes, _ = route
    messages = []
    for rid in ("req-does-not-exist", "req-belongs-to-someone-else"):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(routes.get_provenance_view(
                rid, current_user={"_id": "lawyer-A", "role": "lawyer"}))
        messages.append((exc.value.status_code, exc.value.detail))
    assert messages[0] == messages[1]


def test_the_view_route_is_lawyer_only():
    """A client is shown the findings; this endpoint is the machinery behind them."""
    import app.api.v1.routes.provenance as routes
    from app.dependencies import require_lawyer

    route = next(r for r in routes.router.routes
                 if getattr(r, "path", "") == "/provenance/{request_id}/view")
    guards = [d.call for d in route.dependant.dependencies]
    assert require_lawyer in guards, "the view is not behind the lawyer guard"


def test_the_original_provenance_endpoint_is_unchanged():
    """Preserving the existing contract: the raw record endpoint keeps its shape
    and its audience. The view is an addition, not a replacement."""
    import app.api.v1.routes.provenance as routes
    from app.dependencies import require_lawyer

    route = next(r for r in routes.router.routes
                 if getattr(r, "path", "") == "/provenance/{request_id}")
    guards = [d.call for d in route.dependant.dependencies]
    assert require_lawyer not in guards


# ── route: serving the document behind a citation ────────────────────────────

def test_the_source_route_serves_a_document_that_is_held(corpus):
    import app.api.v1.routes.ai as ai_routes
    response = asyncio.run(ai_routes.ai_source_document(
        "held-here.pdf", current_user={"_id": "u", "role": "lawyer"}))
    assert response.media_type == "application/pdf"
    assert response.path.name == "held-here.pdf"
    # inline: a citation being checked mid-answer, not a download that was asked for
    assert "inline" in response.headers["content-disposition"]


def test_the_source_route_404s_for_a_document_that_is_not_held(corpus):
    from fastapi import HTTPException
    import app.api.v1.routes.ai as ai_routes
    with pytest.raises(HTTPException) as exc:
        asyncio.run(ai_routes.ai_source_document(
            "punjab-tenancy-act-1887.pdf", current_user={"_id": "u", "role": "lawyer"}))
    assert exc.value.status_code == 404


@pytest.mark.parametrize("name", ["../secret.env", "../../secret.env",
                                  "/etc/passwd", "notes.txt", ""])
def test_the_source_route_refuses_anything_outside_the_corpus(corpus, name):
    from fastapi import HTTPException
    import app.api.v1.routes.ai as ai_routes
    with pytest.raises(HTTPException) as exc:
        asyncio.run(ai_routes.ai_source_document(
            name, current_user={"_id": "u", "role": "lawyer"}))
    assert exc.value.status_code == 404


def test_the_source_route_requires_authentication():
    """A corpus document is public law, but the route is not an open file server."""
    import app.api.v1.routes.ai as ai_routes
    from app.dependencies import get_current_user

    route = next(r for r in ai_routes.router.routes
                 if getattr(r, "path", "") == "/ai/source/{source_file}")
    guards = [d.call for d in route.dependant.dependencies]
    assert get_current_user in guards


def test_the_source_route_cannot_be_reached_with_a_nested_path():
    """A path parameter does not match across `/`, so a nested path never
    reaches the handler at all — the router rejects it first."""
    import app.api.v1.routes.ai as ai_routes
    route = next(r for r in ai_routes.router.routes
                 if getattr(r, "path", "") == "/ai/source/{source_file}")
    assert route.path_regex.match("/ai/source/held-here.pdf")
    assert not route.path_regex.match("/ai/source/raw/civil/held-here.pdf")


# ── the citation a link is attached to ───────────────────────────────────────

def test_only_a_citation_backed_by_retrieved_evidence_can_be_linked(corpus):
    """An `unresolved` citation has no chunk, so it has no source file, so it
    gets no link. That is the honest outcome: the whole meaning of unresolved
    is "we cannot show you where this came from" — offering a document would
    contradict the status printed next to it."""
    from app.ai.answer_citations import annotate_citations
    chunks = [{"statute": "PPC 1860", "section_number": "379",
               "source_file": "held-here.pdf", "chunk_id": "c1",
               "province": "federal"}]
    citations = annotate_citations(
        "Theft is defined in PPC Section 379. See also section 154 of the CrPC.",
        chunks)
    source_links.apply_source_links(citations)

    by_status = {c["status"]: c for c in citations}
    assert by_status["matched"]["source_url"] == "/api/v1/ai/source/held-here.pdf"
    assert by_status["unresolved"]["source_url"] == "", \
        "a citation we could not place must not be given a document"


# ── the corpus root is a boundary, not a starting point ──────────────────────
#
# The basename lookup stops a CALLER naming a path. It does nothing about the
# values in the map, which come from the filesystem — and a filesystem points
# outward. These cover the two ways a document inside the corpus can name a
# file outside it.

def _symlink(link, target):
    """Create a symlink, or skip. Windows needs Developer Mode or admin."""
    import os
    try:
        os.symlink(target, link)
    except (OSError, NotImplementedError, AttributeError) as exc:
        pytest.skip(f"symlinks not creatable in this environment ({exc})")


def test_a_symlinked_document_is_never_indexed(tmp_path, monkeypatch):
    """Inside a directory served by basename, a symlink is arbitrary read."""
    root = tmp_path / "knowledge_base"
    (root / "raw").mkdir(parents=True)
    secret = tmp_path / "outside.pdf"
    secret.write_bytes(b"%PDF-1.4 not ours")
    _symlink(root / "raw" / "escape.pdf", secret)

    monkeypatch.setattr(source_links, "_CORPUS_ROOT", root)
    source_links.refresh()
    try:
        assert source_links.resolve("escape.pdf") is None
        assert source_links.source_url("escape.pdf") == ""
        assert "escape.pdf" not in source_links._catalogue()[0]
    finally:
        source_links.refresh()


def test_a_document_reached_through_a_symlinked_directory_is_rejected(tmp_path, monkeypatch):
    """rglob follows directory links, so the FILE it yields is not a link and
    still sits outside the corpus. The per-candidate containment check is the
    one that catches this; the symlink check alone does not."""
    root = tmp_path / "knowledge_base"
    root.mkdir()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "smuggled.pdf").write_bytes(b"%PDF-1.4 outside")
    _symlink(root / "raw", elsewhere)

    monkeypatch.setattr(source_links, "_CORPUS_ROOT", root)
    source_links.refresh()
    try:
        assert source_links.resolve("smuggled.pdf") is None
        assert source_links.source_url("smuggled.pdf") == ""
    finally:
        source_links.refresh()


def test_a_document_swapped_for_a_symlink_after_indexing_is_not_served(corpus):
    """The catalogue is cached for the life of the process. A path that was a
    plain file when it was indexed is not necessarily one when it is read, so
    the checks are repeated at serve time rather than trusted from indexing."""
    import os
    held = corpus / "raw" / "civil" / "held-here.pdf"
    assert source_links.resolve("held-here.pdf") is not None   # indexed as a file

    secret = corpus.parent / "secret.env"
    held.unlink()
    try:
        os.symlink(secret, held)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlinks not creatable in this environment ({exc})")

    # Same cached catalogue entry — only the re-check can catch this.
    assert source_links.resolve("held-here.pdf") is None


def test_a_basename_the_corpus_holds_twice_is_unlinkable(tmp_path, monkeypatch):
    """`source_file` no longer identifies a document, and either choice would
    let an answer citing one Act link to another. There is no right answer, so
    no link is offered — the same outcome as a document we do not hold."""
    root = tmp_path / "knowledge_base"
    (root / "raw" / "civil").mkdir(parents=True)
    (root / "raw" / "criminal").mkdir(parents=True)
    (root / "raw" / "civil" / "act.pdf").write_bytes(b"%PDF-1.4 civil")
    (root / "raw" / "criminal" / "act.pdf").write_bytes(b"%PDF-1.4 criminal")
    (root / "raw" / "civil" / "unique.pdf").write_bytes(b"%PDF-1.4 unique")

    monkeypatch.setattr(source_links, "_CORPUS_ROOT", root)
    source_links.refresh()
    try:
        assert source_links.is_ambiguous("act.pdf")
        assert source_links.resolve("act.pdf") is None
        assert source_links.source_url("act.pdf") == ""
        # An ambiguous name must not poison the rest of the catalogue.
        assert source_links.source_url("unique.pdf") == "/api/v1/ai/source/unique.pdf"
    finally:
        source_links.refresh()


def test_an_ambiguous_citation_is_left_unlinkable_rather_than_offered(tmp_path, monkeypatch):
    """The UI must never render a link it will then fail to open. Unavailable
    and ambiguous are both decided BEFORE anything is shown, so neither reaches
    the user as a 404."""
    root = tmp_path / "knowledge_base"
    (root / "a").mkdir(parents=True)
    (root / "b").mkdir(parents=True)
    (root / "a" / "act.pdf").write_bytes(b"%PDF")
    (root / "b" / "act.pdf").write_bytes(b"%PDF")

    monkeypatch.setattr(source_links, "_CORPUS_ROOT", root)
    source_links.refresh()
    try:
        citations = [{"statute": "X", "section": "1", "source": "act.pdf"},
                     {"statute": "Y", "section": "2", "source": "missing.pdf"}]
        source_links.apply_source_links(citations)
        assert [c["source_url"] for c in citations] == ["", ""]
    finally:
        source_links.refresh()


def test_indexing_is_deterministic(corpus):
    """rglob gives no ordering guarantee. Without the sort, two processes could
    disagree about what a corpus contains and neither would look wrong."""
    first = source_links._catalogue()[0]
    source_links.refresh()
    second = source_links._catalogue()[0]
    assert first == second
    assert list(first) == list(second), "the catalogue's own order must be stable"


# ── external judgment URLs ───────────────────────────────────────────────────

@pytest.mark.parametrize("url", [
    "javascript:alert(document.cookie)",
    "JavaScript:alert(1)",           # scheme matching is case-insensitive
    "  javascript:alert(1)  ",       # and survives trimming
    "data:text/html,<script>fetch('/api/v1/cases')</script>",
    "file:///etc/passwd",
    "vbscript:msgbox(1)",
    "//evil.example/x.pdf",          # scheme-relative: inherits the page's
    "https://",                      # no host, not addressable
    "http:///x.pdf",
    "not a url at all",
    "",
    "   ",
])
def test_an_unsafe_judgment_url_is_not_a_link(url):
    """A judgment URL is court-published data arriving through the citator, so
    it is data. An allowlist, because the dangerous schemes are the ones nobody
    thinks to blacklist."""
    assert source_links.safe_external_url(url) == ""


@pytest.mark.parametrize("url", [
    "https://sys.lhc.gov.pk/appjudgments/2026LHC4194.pdf",
    "http://sys.lhc.gov.pk/x.pdf",
])
def test_a_real_court_url_survives(url):
    assert source_links.safe_external_url(url) == url


def test_a_non_string_url_is_not_a_link():
    for value in (None, 123, {"url": "https://x/y"}, ["https://x/y"]):
        assert source_links.safe_external_url(value) == ""


def test_a_judgment_with_an_unsafe_url_keeps_the_citation_and_loses_the_link(corpus):
    """The citation is the trust signal; the link is a convenience. Dropping the
    whole chip would hide a judgment the answer actually relied on."""
    citations = [{"type": "judgment", "statute": "2026LHC4194",
                  "url": "javascript:alert(1)", "source": "javascript:alert(2)"}]
    source_links.apply_source_links(citations)
    assert len(citations) == 1
    assert citations[0]["statute"] == "2026LHC4194"
    assert citations[0]["url"] == ""
    assert citations[0]["source"] == "", "source is the client's href fallback"


def test_a_judgment_with_a_real_url_is_untouched(corpus):
    citations = [{"type": "judgment", "statute": "2026LHC4194",
                  "url": "https://sys.lhc.gov.pk/x.pdf"}]
    source_links.apply_source_links(citations)
    assert citations[0]["url"] == "https://sys.lhc.gov.pk/x.pdf"
    assert "source_url" not in citations[0]


# ── the answer's author is projected, never passed through ───────────────────

def test_the_author_is_projected_through_an_allowlist():
    view = provenance_view.build_view(RECORD)
    assert set(view["model"]["answered_by"]) <= {
        "provider", "model", "tier", "purpose", "call_id"}
    assert view["model"]["answered_by"]["model"] == "openai/gpt-oss-120b"


def test_a_future_field_on_the_author_is_excluded():
    """`answer_llm` is built by provider_health and stored verbatim. Returning
    it directly would publish whatever that dict holds after the next change to
    it — a nested dict is where an exception to the allowlist would hide."""
    view = provenance_view.build_view({
        **RECORD,
        "answer_llm": {
            "provider": "groq", "model": "openai/gpt-oss-120b",
            "api_key": "sk-live-should-never-appear",
            "system_prompt": "You are an expert Pakistani legal assistant...",
            "error_body": "429 for organization org_01ABC on key sk-live-x",
            "raw_response": {"headers": {"authorization": "Bearer sk-live-x"}},
        },
    })
    author = view["model"]["answered_by"]
    assert author == {"provider": "groq", "model": "openai/gpt-oss-120b"}
    blob = repr(view)
    for secret in ("sk-live", "You are an expert", "org_01ABC", "authorization"):
        assert secret not in blob, f"{secret!r} reached the lawyer view"


def test_an_author_field_that_becomes_a_container_is_dropped_not_stringified():
    """str({...}) prints every key and value it holds, so stringifying is how an
    allowlist gets defeated without anyone editing the allowlist."""
    view = provenance_view.build_view({
        **RECORD,
        "answer_llm": {"provider": "groq",
                       "model": {"name": "x", "api_key": "sk-live-nested"}},
    })
    assert view["model"]["answered_by"]["model"] is None
    assert "sk-live-nested" not in repr(view)


def test_a_malformed_author_is_no_author():
    for value in (None, "groq", 42, [], {}):
        view = provenance_view.build_view({**RECORD, "answer_llm": value})
        assert view["model"]["answered_by"] is None


def test_a_malformed_llm_attempt_does_not_break_the_view():
    view = provenance_view.build_view(
        {**RECORD, "llm_calls": ["not a dict", None, {"provider": "groq"}]})
    assert view["model"]["attempts"] == [{"provider": "groq"}]


def test_an_ambiguous_name_404s_if_the_url_is_constructed_by_hand(tmp_path, monkeypatch):
    """The route still refuses it — but nothing ever hands a user that URL.

    Unlinkable is decided when the citation is built, so the 404 is a backstop
    for someone typing the address, not a state the UI can navigate into.
    """
    from fastapi import HTTPException
    import app.api.v1.routes.ai as ai_routes

    root = tmp_path / "knowledge_base"
    (root / "a").mkdir(parents=True)
    (root / "b").mkdir(parents=True)
    (root / "a" / "act.pdf").write_bytes(b"%PDF")
    (root / "b" / "act.pdf").write_bytes(b"%PDF")
    monkeypatch.setattr(source_links, "_CORPUS_ROOT", root)
    source_links.refresh()
    try:
        with pytest.raises(HTTPException) as exc:
            asyncio.run(ai_routes.ai_source_document(
                "act.pdf", current_user={"_id": "u", "role": "lawyer"}))
        assert exc.value.status_code == 404
    finally:
        source_links.refresh()


def test_the_route_never_serves_a_document_the_citation_would_not_link(corpus):
    """The route and the link agree by construction: both go through resolve().

    If they could disagree, the safe direction would be the link's — but they
    cannot, so this pins the property rather than testing two code paths.
    """
    import app.api.v1.routes.ai as ai_routes
    from fastapi import HTTPException

    for name in ("held-here.pdf", "punjab-tenancy-act-1887.pdf",
                 "notes.txt", "../secret.env"):
        linkable = bool(source_links.source_url(name))
        try:
            asyncio.run(ai_routes.ai_source_document(
                name, current_user={"_id": "u", "role": "lawyer"}))
            servable = True
        except HTTPException:
            servable = False
        assert linkable == servable, f"{name}: linkable={linkable} servable={servable}"
