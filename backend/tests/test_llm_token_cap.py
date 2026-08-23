"""Every provider caps generated tokens.

Left unset, an OpenAI-compatible provider bills against the model's FULL
context. OpenRouter refused every request with 402 "you requested up to 65536
tokens, but can only afford 5308" on an account that still had credit for
hundreds of real answers -- the ceiling is what is reserved, not what is spent.
An uncapped call therefore prices a two-paragraph legal answer as if it were a
novel, and the app stops answering while the balance says it should not.

Pinned per builder rather than as one assertion, because the parameter is named
differently by each SDK and adding a provider without the cap would otherwise
reintroduce the fault silently.
"""
import inspect

import pytest

from app.ai import llm


def _src(fn):
    return inspect.getsource(fn)


def test_the_cap_is_set_and_modest():
    assert 1000 <= llm.MAX_OUTPUT_TOKENS <= 4000


@pytest.mark.parametrize("builder,param", [
    (llm._build_gemini,     "max_output_tokens"),
    (llm._build_groq,       "max_tokens"),
    (llm._build_openrouter, "max_tokens"),
    (llm._build_ollama,     "num_predict"),
])
def test_each_builder_passes_the_cap(builder, param):
    src = _src(builder)
    assert f"{param}=MAX_OUTPUT_TOKENS" in src, (
        f"{builder.__name__} does not cap output tokens via {param}"
    )


def test_every_registered_builder_is_covered():
    """A provider added to _BUILDERS without a cap would 402 (or overspend) the
    moment it became primary."""
    capped = {"max_output_tokens", "max_tokens", "num_predict"}
    for name, builder in llm._BUILDERS.items():
        src = _src(builder)
        assert any(f"{p}=MAX_OUTPUT_TOKENS" in src for p in capped), (
            f"provider {name!r} builds an LLM without an output cap"
        )
