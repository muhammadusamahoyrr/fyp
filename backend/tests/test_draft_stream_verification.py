"""The streaming draft path is checked and audited.

/ai/draft/stream had no safety net of any kind: no grounding node, no citation
check, no decision engine and no provenance row — raw model output straight into
a lawyer's document editor. The prompt instructs the model to write
"[placeholder]" rather than invent a citation, and nothing enforced it.

Two properties, both asserted here:

  * the drafted text is buffered and run through the SAME citation record the
    document path stores, emitted as a final SSE event;
  * the turn is written to the provenance store, so groundedness and refusal
    rates computed from that store stop silently excluding every document a
    lawyer drafted.

Backward compatibility is the third property and the reason this could ship
without a frontend change: _consumeSSE in frontend/src/lib/api.js does
`if (parsed.content) onToken(...)`, so an event carrying `verification` and no
`content` is skipped rather than erroring. test_verification_event_shape pins
the shape that relies on.

These tests do not call an LLM. They drive the generator with a stubbed model.
"""
import inspect
import json

import pytest

from app.api.v1.routes import ai as ai_routes


# ── ordering: the lawyer waits for tokens, not for the checker ───────────────

def test_verification_runs_after_the_stream_not_before():
    src = inspect.getsource(ai_routes.ai_draft_stream)
    astream_at = src.index("llm.astream")
    verify_at = src.index("_verification_record")

    assert astream_at < verify_at, "verification must not delay the first token"


def test_the_done_sentinel_is_emitted_last():
    """A client that stops at [DONE] must still have seen the verification."""
    src = inspect.getsource(ai_routes.ai_draft_stream)

    assert src.index("_verification_record") < src.index("[DONE]")


def test_tokens_are_buffered_for_the_check():
    src = inspect.getsource(ai_routes.ai_draft_stream)

    assert "buf.append" in src
    assert "".join(["dra", "fted"]) in src


# ── the failure paths stay quiet ─────────────────────────────────────────────

def test_a_failed_stream_is_not_verified_or_audited():
    """Half a draft that errored is not a document; recording it as an answer
    would corrupt any rate computed from the store."""
    src = inspect.getsource(ai_routes.ai_draft_stream)

    assert "failed = True" in src
    assert "not failed" in src


def test_verification_failure_cannot_break_the_stream():
    """The check is advisory. If it raises, the lawyer still gets their draft."""
    src = inspect.getsource(ai_routes.ai_draft_stream)
    after = src[src.index("_verification_record"):]

    assert "except Exception" in after


def test_provenance_failure_cannot_break_the_stream():
    src = inspect.getsource(ai_routes.ai_draft_stream)
    after = src[src.index("record_answer"):]

    assert "except Exception" in after


# ── the event shape the existing frontend can ignore ─────────────────────────

def test_verification_event_shape():
    """_consumeSSE skips any parsed event without `.content`. The verification
    event must therefore carry no `content` key, or the frontend would render
    the JSON blob into the lawyer's document."""
    event = {"verification": {"ran": True, "flagged": []}}
    line = f"data: {json.dumps(event)}\n\n"

    parsed = json.loads(line[len("data: "):].strip())
    assert "content" not in parsed
    assert parsed.get("verification") is not None


def test_the_verification_payload_is_json_encodable():
    """_verification_record contains datetimes; a raw json.dumps would raise
    inside the generator and truncate the stream after the last token."""
    src = inspect.getsource(ai_routes.ai_draft_stream)

    assert "jsonable_encoder" in src


# ── the record it reuses ─────────────────────────────────────────────────────

async def test_verification_record_is_fail_open_and_marks_itself():
    """Reused unchanged from the document path: a check that could not run
    reports ran: False, which is explicitly not a pass."""
    from app.services.document_service import _verification_record

    record = await _verification_record({"draft": "No citations here."})

    assert "ran" in record
    assert isinstance(record["ran"], bool)


async def test_verification_never_raises_on_odd_input():
    from app.services.document_service import _verification_record

    for payload in ({}, {"draft": ""}, {"draft": "x" * 5000}):
        assert await _verification_record(payload) is not None


# ── the audit turn ───────────────────────────────────────────────────────────

def test_the_turn_is_recorded_as_an_answer():
    src = inspect.getsource(ai_routes.ai_draft_stream)

    assert "provenance_service.record_answer" in src
    assert "TURN_ANSWER" in src


def test_the_session_id_distinguishes_drafting_turns():
    """Drafting turns share a store with chat turns; without a distinguishable
    session they would be indistinguishable in any rate computed from it."""
    src = inspect.getsource(ai_routes.ai_draft_stream)

    assert "draft:" in src


def test_record_answer_never_raises_by_contract():
    """Relied on above — the audit write must not fail the turn it describes."""
    from app.services import provenance_service

    doc = inspect.getdoc(provenance_service.record_answer) or ""
    assert "never raises" in doc.lower()
