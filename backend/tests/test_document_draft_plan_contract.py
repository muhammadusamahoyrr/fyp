"""Pure contract tests for the client prompt planner."""
from __future__ import annotations

import pytest

from app.core.exceptions import AppValidationError
from app.services import document_draft_plan_service as plans


@pytest.mark.parametrize(("prompt", "expected"), [
    ("A 6-month NDA between ABC Pvt Ltd and a designer", "nda"),
    ("Prepare a tenancy agreement for a flat in Karachi", "rental_agreement"),
    ("Draft a petition under section 22-A", "petition_22a"),
    ("Written statement replying to a civil plaint", "written_statement"),
    ("FIA cybercrime complaint about account hacking", "fia_cybercrime"),
])
def test_known_prompt_types_are_selected_conservatively(prompt, expected):
    assert plans.infer_template_type(prompt) == expected


def test_an_unknown_prompt_does_not_guess_an_instrument():
    assert plans.infer_template_type("Please prepare a document about my situation") is None


def test_an_unknown_prompt_asks_for_a_real_supported_template():
    questions, remaining = plans.questions_for(None, {})
    assert remaining == 1
    assert questions[0]["field"] == "template_type"
    assert questions[0]["legal_requirement"] is False
    values = {option["value"] for option in questions[0]["options"]}
    assert "nda" in values
    assert "lawyer_draft" not in values
    assert "payment_receipt" not in values


def test_questions_are_bounded_and_are_not_called_legal_requirements():
    questions, remaining = plans.questions_for("nda", {})
    assert len(questions) == plans.MAX_QUESTIONS
    assert remaining == 5
    assert all(q["legal_requirement"] is False for q in questions)


def test_only_templates_with_real_prompt_extractors_are_offered():
    supported = set(plans.supported_template_types())
    assert "nda" in supported
    assert "rental_agreement" in supported
    assert "inheritance_settlement" not in supported  # dedicated calculator
    assert "lawyer_draft" not in supported


def test_manual_or_system_templates_are_refused_by_the_prompt_path():
    with pytest.raises(AppValidationError):
        plans._require_supported("payment_receipt")
    with pytest.raises(AppValidationError):
        plans._require_supported("power_of_attorney")

