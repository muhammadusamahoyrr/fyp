"""Clarifying questions come in ONE language per intake, chosen by code.

The prompt used to tell the model "ask in the same language the user used" and
leave it there, so every round re-decided: one intake got an English first
question and an Urdu second one, another got four Urdu questions for an English
description. The language is now decided by `_clarify_language`, pinned by the
first question, stated to the model, and checked on the way out.
"""
from __future__ import annotations

import pytest

from app.services import intake_service
from app.services.intake_service import _clarify_language

EN_Q = "What is the amount of rent that is currently overdue?"
UR_Q = "کیا آپ کے پاس کرایہ دار کے ساتھ کوئی تحریری معاہدہ موجود ہے؟"
EN_DESC = "My tenant has not paid rent for six months."
UR_DESC = "میرے کرایہ دار نے چھ ماہ سے کرایہ ادا نہیں کیا۔"


# ── the rule ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(("qa", "desc", "requested", "expected"), [
    ([], EN_DESC, None, "en"),                      # English text, no preference
    ([], "mera kirayedar kiraya nahi de raha", None, "en"),   # Roman Urdu
    ([], UR_DESC, None, "ur"),                      # Urdu script
    ([], EN_DESC, "ur", "ur"),                      # app set to Urdu
    ([], UR_DESC, "en", "ur"),                      # the client wrote in Urdu
    ([{"q": EN_Q, "a": "222222"}], EN_DESC, "ur", "en"),   # pinned: toggle mid-intake
    ([{"q": UR_Q, "a": "222222"}], EN_DESC, "en", "ur"),   # pinned the other way
], ids=["english", "roman-urdu", "urdu-script", "app-urdu", "urdu-wins",
        "pinned-en", "pinned-ur"])
def test_the_language_is_decided_once_and_by_code(qa, desc, requested, expected):
    assert _clarify_language(qa, desc, requested) == expected


# ── the service ──────────────────────────────────────────────────────────────

class FakeRepo:
    def __init__(self, doc):
        self.doc = doc

    async def find_by_token(self, token):
        return dict(self.doc)

    async def save_clarification_qa(self, token, qa_list):
        self.doc["clarification_qa"] = qa_list
        return True


def _doc(qa, desc=EN_DESC):
    return {"_id": "i-1", "session_token": "t", "client_id": "c", "completed": False,
            "step1": {"province": "punjab"}, "step2": {"case_type": "civil"},
            "step3": {"incident_description": desc}, "clarification_qa": qa}


class _Reply:
    def __init__(self, content):
        self.content = content


@pytest.fixture
def model(monkeypatch):
    """A scripted model that records every prompt it is sent."""
    state = {"replies": [], "prompts": []}

    class _LLM:
        def invoke(self, messages):
            state["prompts"].append(messages)
            return _Reply(state["replies"].pop(0))

    import app.ai.llm as llm_mod
    monkeypatch.setattr(llm_mod, "get_llm", lambda **k: _LLM())
    return state


async def test_the_model_is_told_the_language(monkeypatch, model):
    monkeypatch.setattr(intake_service, "intake_repo", FakeRepo(_doc([])))
    model["replies"] = [EN_Q]

    await intake_service.get_clarification("t", "c", None)

    system = model["prompts"][0][0]["content"]
    assert "Write the question in English only." in system
    assert "same language the user used" not in system


async def test_the_second_round_cannot_switch_to_urdu(monkeypatch, model):
    """The reported defect: Q1 in English, Q2 in Urdu."""
    repo = FakeRepo(_doc([{"q": EN_Q, "a": None}]))
    monkeypatch.setattr(intake_service, "intake_repo", repo)
    model["replies"] = [UR_Q, "Do you have a written tenancy agreement?"]

    result = await intake_service.get_clarification("t", "c", "222222", language="ur")

    assert result["question"] == "Do you have a written tenancy agreement?"
    assert len(model["prompts"]) == 2, "an off-language question was not retried"
    assert "English only" in model["prompts"][0][0]["content"]


async def test_an_urdu_intake_stays_urdu(monkeypatch, model):
    monkeypatch.setattr(intake_service, "intake_repo", FakeRepo(_doc([], desc=UR_DESC)))
    model["replies"] = [UR_Q]

    result = await intake_service.get_clarification("t", "c", None)

    assert result["question"] == UR_Q
    assert len(model["prompts"]) == 1
    assert "Urdu only" in model["prompts"][0][0]["content"]


async def test_a_model_that_will_not_comply_still_lets_the_client_proceed(monkeypatch, model):
    monkeypatch.setattr(intake_service, "intake_repo", FakeRepo(_doc([])))
    model["replies"] = [UR_Q, UR_Q]

    result = await intake_service.get_clarification("t", "c", None)

    assert result["question"] == UR_Q      # one retry, then the question is used
    assert len(model["prompts"]) == 2


async def test_done_is_never_retried(monkeypatch, model):
    monkeypatch.setattr(intake_service, "intake_repo", FakeRepo(_doc([])))
    model["replies"] = ["DONE"]

    result = await intake_service.get_clarification("t", "c", None)

    assert result["done"] is True
    assert len(model["prompts"]) == 1
