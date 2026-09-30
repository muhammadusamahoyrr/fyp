"""A failed extraction says so, and a long case is read, not cut at 3,000.

`extract_fields` turned every failure into `fields = {}`: the client saw a blank
form that looked exactly like "your case says nothing about this". And the model
was shown only the first 3,000 characters of a case whose intake accepts 20,000
for the incident alone.
"""
from __future__ import annotations

import json

import pytest

from app.services import document_service
from app.services.document_service import _EXTRACT_MAX_CHARS


class _Reply:
    def __init__(self, content):
        self.content = content


@pytest.fixture
def world(monkeypatch):
    state = {"replies": [], "prompts": [], "description": "Tenant owes PKR 200,000 rent."}

    class _Cases:
        async def find_by_id(self, case_id):
            return {"_id": case_id, "client_id": "c1", "status": "open",
                    "description": state["description"]}

    class _LLM:
        def invoke(self, messages):
            state["prompts"].append(messages)
            nxt = state["replies"].pop(0)
            if isinstance(nxt, Exception):
                raise nxt
            return _Reply(nxt)

    import app.ai.llm as llm_mod
    monkeypatch.setattr(document_service, "case_repo", _Cases())
    monkeypatch.setattr(llm_mod, "get_llm", lambda **k: _LLM())
    return state


async def _extract():
    return await document_service.extract_fields("case-1", "c1", "legal_notice")


async def test_a_good_read_is_ok(world):
    world["replies"] = [json.dumps({"sender_name": "Ali", "demand": "Pay 200,000"})]
    res = await _extract()
    assert res["extraction_status"] == "ok"
    assert res["fields"]["sender_name"] == "Ali"


async def test_a_read_that_found_nothing_is_empty_not_failed(world):
    world["replies"] = [json.dumps({"sender_name": "", "demand": ""})]
    assert (await _extract())["extraction_status"] == "empty"


async def test_one_bad_reply_is_retried(world):
    world["replies"] = ["Sure! Here are the fields:", json.dumps({"sender_name": "Ali"})]
    res = await _extract()
    assert res["extraction_status"] == "ok" and len(world["prompts"]) == 2


async def test_a_read_that_keeps_failing_is_reported_failed(world):
    world["replies"] = [RuntimeError("provider down"), "not json"]
    res = await _extract()
    assert res["extraction_status"] == "failed"
    assert res["fields"] == {}
    assert len(world["prompts"]) == 2


async def test_a_json_list_is_not_accepted_as_fields(world):
    world["replies"] = ["[1, 2]", "[3]"]
    assert (await _extract())["extraction_status"] == "failed"


async def test_free_text_extraction_rejects_non_object_json(world):
    world["replies"] = ['["not", "a", "field map"]']
    assert await document_service.extract_fields_from_text(
        "Draft a notice for unpaid rent", "legal_notice") == {}


async def test_a_long_case_is_read_past_3000_characters(world):
    tail = "RELIEF: recover PKR 200,000 with costs."
    world["description"] = "x" * 5_000 + tail
    world["replies"] = [json.dumps({"demand": "Pay"})]
    res = await _extract()
    assert tail in world["prompts"][0][1]["content"], "facts after 3,000 chars never reached the model"
    assert res["truncated"] is False


async def test_a_case_past_the_bound_is_flagged_truncated(world):
    world["description"] = "y" * (_EXTRACT_MAX_CHARS + 10)
    world["replies"] = [json.dumps({"demand": "Pay"})]
    assert (await _extract())["truncated"] is True
