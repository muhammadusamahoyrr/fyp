import re

from langchain_core.messages import AIMessage

from app.ai import cache
from app.ai.graph.state import AgentState
from app.ai.nodes.cache_node import is_personalised

_REFUSE = (
    "I was unable to provide a reliable answer based on the available Pakistani legal documents. "
    "Please consult a qualified Pakistani lawyer for accurate advice on your specific situation."
)

# ─── PII scrubbing patterns ────────────────────────────────────────────────────
_CNIC_RE      = re.compile(r'\b\d{5}-\d{7}-\d\b')
# Urdu/Extended Arabic-Indic digits (U+0660-U+0669, U+06F0-U+06F9)
_CNIC_URDU_RE = re.compile(r'[٠-٩۰-۹]{5}-[٠-٩۰-۹]{7}-[٠-٩۰-۹]')
_PHONE_RE     = re.compile(r'\b(\+92|0092|0)[\s\-]?\d{3}[\s\-]?\d{7}\b')

# Prompt leakage artifacts from LLM output
_LEAK_RE  = re.compile(
    r'(?im)^(System:|Human:|Assistant:|<\|im_start\||<\|im_end\||\[INST\]|<<SYS>>|Note to AI:|###\s*System).*$'
)


def _scrub_pii(text: str) -> str:
    text = _CNIC_RE.sub('XXXXX-XXXXXXX-X', text)
    text = _CNIC_URDU_RE.sub('XXXXX-XXXXXXX-X', text)
    text = _PHONE_RE.sub('[PHONE REDACTED]', text)
    return text


def _remove_leakage(text: str) -> str:
    return _LEAK_RE.sub('', text)


def _clean_markdown(text: str) -> str:
    # Collapse 3+ consecutive blank lines to 2
    text = re.sub(r'\n{3,}', '\n\n', text)
    # Remove trailing whitespace on each line
    text = '\n'.join(line.rstrip() for line in text.splitlines())
    return text.strip()


def _sanitise(text: str) -> str:
    text = _remove_leakage(text)
    text = _scrub_pii(text)
    text = _clean_markdown(text)
    return text


async def finalizer_node(state: AgentState) -> dict:
    # Off-topic: triage_node already set the answer — just sanitise it.
    if state.get("convergence_status") == "off_topic":
        answer = state.get("answer", "")
        if answer:
            clean = _sanitise(answer)
            return {"answer": clean, "messages": [AIMessage(content=clean[:500])]}
        return {}

    # No answer was ever generated.
    if not state.get("answer"):
        return {
            "answer":             _REFUSE,
            "confidence":         0.0,
            "is_grounded":        False,
            "convergence_status": "max_attempts",
            "messages":           [AIMessage(content=_REFUSE)],
        }

    is_grounded = state.get("is_grounded", False)
    clean       = _sanitise(state["answer"])

    # Write-through: cache generic, grounded, non-personalised primary answers so
    # an identical later query skips the retrieval→generation chain. Skip cache-hit
    # passthroughs, follow-ups (deepen/format/affirm), and fact/clarification turns.
    if (
        is_grounded
        and not state.get("cache_hit")
        and not state.get("followup_intent")
        and not is_personalised(state)
    ):
        try:
            await cache.set_result(
                state.get("normalized_query") or state["query"],
                state.get("case_type", ""),
                state.get("province", ""),
                {
                    "answer":      clean,
                    "citations":   state.get("citations", []),
                    "confidence":  state.get("confidence", 0.0),
                    "is_grounded": True,
                },
                # None → invalidate on TTL + embedding/chunking version only.
                # Collection-version busting activates once the ingest pipeline
                # calls cache.invalidate_collection (a later enhancement).
                collection_names=None,
            )
        except Exception:
            pass  # cache is best-effort — never fail the response on a cache error

    return {
        "answer":             clean,
        "convergence_status": "converged" if is_grounded else "max_attempts",
        "messages":           [AIMessage(content=clean[:500])],
    }
