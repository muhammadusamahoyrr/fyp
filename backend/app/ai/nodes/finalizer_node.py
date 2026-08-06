import re

from langchain_core.messages import AIMessage

from app.ai import cache
from app.ai.graph.state import AgentState
from app.ai.nodes.cache_node import is_personalised
from app.utils.pii import scrub_pii as _scrub_pii

_REFUSE = (
    "I was unable to provide a reliable answer based on the available Pakistani legal documents. "
    "Please consult a qualified Pakistani lawyer for accurate advice on your specific situation."
)

# Distinct message for a retrieval FAULT. Telling a user no relevant law was
# found, when in fact the search itself failed, is a false statement about the
# law — and it discourages them from simply retrying.
_REFUSE_ERROR = (
    "I hit a technical problem searching the legal documents and could not "
    "complete your request. Please try again in a moment. If it keeps happening, "
    "please consult a qualified Pakistani lawyer for your specific situation."
)

# Prompt leakage artifacts from LLM output
_LEAK_RE  = re.compile(
    r'(?im)^(System:|Human:|Assistant:|<\|im_start\||<\|im_end\||\[INST\]|<<SYS>>|Note to AI:|###\s*System).*$'
)


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
        failed = (state.get("arbitration_source") == "error"
                  or state.get("retrieval_error"))
        msg = _REFUSE_ERROR if failed else _REFUSE
        return {
            "answer":             msg,
            "confidence":         0.0,
            "is_grounded":        False,
            # "error" keeps a fault out of the abstention statistics; a genuine
            # evidence-based refusal stays "max_attempts".
            "convergence_status": "error" if failed else "max_attempts",
            "messages":           [AIMessage(content=msg)],
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
