from app.ai.nodes._language import question_language_instruction
from app.ai.nodes.clarification_node import SYSTEM_PROMPT
from app.ai.nodes.fact_gap_node import _SYSTEM_TEMPLATE


def test_question_language_instruction_is_explicit_for_every_supported_language():
    assert question_language_instruction("en") == "Write the question in English only."
    assert question_language_instruction("ur") == (
        "Write the question in Urdu only, using Urdu script."
    )
    assert question_language_instruction("roman_urdu") == (
        "Write the question in Roman Urdu only, using Latin script."
    )


def test_question_language_instruction_fails_safe_to_english():
    assert question_language_instruction(None) == "Write the question in English only."
    assert question_language_instruction("unknown") == "Write the question in English only."


def test_both_question_prompts_use_the_explicit_language_rule():
    for prompt in (SYSTEM_PROMPT, _SYSTEM_TEMPLATE):
        assert "{language_instruction}" in prompt
        assert "same language" not in prompt.lower()
