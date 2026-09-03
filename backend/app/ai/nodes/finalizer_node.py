import re

from langchain_core.messages import AIMessage

from app.ai import cache
from app.ai.answer_citations import annotate_citations_from_evidence, apply_currency
from app.ai.source_links import apply_source_links
from app.ai.graph.state import AgentState
import logging

from app.ai.nodes.cache_node import (
    cache_block_reason,
    effective_language,
)
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

logger = logging.getLogger(__name__)


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


def _sanitised_claims(claims: list[dict]) -> list[dict]:
    """Claim text goes through the same scrubbing the answer does.

    The claims were split from the PRE-sanitise answer inside hallucination_node,
    so a CNIC or phone number masked in the answer would otherwise survive
    verbatim in the claim quoted beside it — and the provenance record and the
    user-facing answer are supposed to redact identically.

    The verdicts are carried across unchanged rather than recomputed: re-splitting
    the sanitised text could renumber the claims and silently attach a verdict to
    a different sentence than the one it was made about.
    """
    return [{**claim, "text": _scrub_pii(claim.get("text", ""))} for claim in claims]


def _answer_llm_for_cache():
    """Attribution for the answer being cached. None when nothing generated it."""
    try:
        from app.ai.provider_health import current_turn
        turn = current_turn()
        return turn.answer_llm() if turn else None
    except Exception:
        return None


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

        # A refusal the user can act on. "I couldn't find that" is indistinguish-
        # able from a retrieval miss, so a user asking for the current stamp duty
        # rate would simply rephrase and try again — the corpus will never hold
        # the answer, and saying so is more useful than another empty search.
        reason = state.get("refusal_reason")
        if reason and not failed:
            redirect = state.get("refusal_redirect")
            msg = reason + (f" You'll want {redirect} for that." if redirect else "")
            return {
                "answer":             msg,
                "confidence":         0.0,
                "is_grounded":        False,
                "convergence_status": "unanswerable",
                "messages":           [AIMessage(content=msg)],
            }

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

    # Label each citation by where it came from, against the FINAL answer text —
    # after sanitising, so the list describes exactly the words the user reads.
    #
    # Matched against `generation_evidence`, NOT reranked_chunks: a citation may
    # only be called "matched" against a source the model actually saw. Matching
    # on the full graded set let a chunk that never entered the prompt be
    # reported as the answer's source — a claim the system cannot support.
    # A citation to anything outside that set is `unresolved`, which is correct.
    #
    # Skipped on a cache hit: that path has an answer but no retrieval, so every
    # citation would match against an empty evidence set and be relabelled
    # "unresolved". The stored list was already annotated when it was written.
    citations = state.get("citations", [])
    claims = _sanitised_claims(state.get("claim_assessments") or [])
    if not state.get("cache_hit"):
        citations = annotate_citations_from_evidence(
            clean, state.get("generation_evidence") or [])

    # Stamp repeal currency onto the citations and the claims resting on them.
    # Deterministic, no model, no extra call — it reads the same omission map
    # the drafting-path verifier uses. Two values only: `repealed` when the Act
    # declares the section omitted, `unknown` otherwise. Never `in_force`:
    # repeal data covers 4 of 43 statutes and is a lower bound, so silence is
    # absence of evidence, not evidence of currency.
    #
    # Applied on the cache-hit path too. A cached answer is served precisely
    # because it looks identical, and a provision repealed since the entry was
    # written must not inherit that entry's silence.
    apply_currency(citations, claims, province=state.get("province", "") or "")

    # Write-through: cache generic, grounded answers so an identical later query
    # skips the retrieval→generation chain.
    #
    # Eligibility is `cache_block_reason` — THE SAME function the lookup node
    # consults. It used to be a separate expression here that happened to agree
    # with the one over there, which is not a property but a coincidence with a
    # maintenance schedule: a rule added to one file was a rule missing from the
    # other, and the direction that failed was always the same one — something
    # got written that should not have been.
    #
    # The two conditions below are genuinely write-only and stay here: an
    # ungrounded answer is not worth serving again, and a cache-hit passthrough
    # would rewrite the entry it just read.
    blocked = cache_block_reason(state)
    if blocked:
        logger.debug("cache: write-back declined (%s)", blocked)
    if (
        is_grounded
        and not blocked
        and not state.get("cache_hit")
        and not state.get("followup_intent")
    ):
        try:
            await cache.set_result(
                state.get("normalized_query") or state["query"],
                state.get("case_type", ""),
                state.get("province", ""),
                {
                    "answer":      clean,
                    # The ANNOTATED list, so a cache hit serves citations that
                    # still say which of them the answer actually cited.
                    "citations":   citations,
                    # Without this a cache hit would serve an answer whose every
                    # claim reads "unassessed" — a quality cliff invisible to the
                    # user, on a path chosen precisely because it looks identical.
                    "claims":      claims,
                    "confidence":  state.get("confidence", 0.0),
                    "is_grounded": True,
                    # Stored so a later cache hit can report the signals that
                    # were actually measured when this answer was produced,
                    # instead of the 0.0 initialisers of a turn where retrieval
                    # never ran. A hit is not evidence that the evidence was bad.
                    "relevance_score": state.get("relevance_score", 0.0),
                    "bm25_confidence": state.get("bm25_confidence", 0.0),
                    "signal_variance": state.get("signal_variance", 0.0),
                    # Who wrote this answer, recorded WHEN IT WAS WRITTEN. A
                    # later cache hit runs no generation, so without this the
                    # served answer has no author at all — and the previous
                    # design filled that gap with whatever model the current
                    # turn happened to touch last.
                    "answer_llm": _answer_llm_for_cache(),
                },
                # None → invalidate on TTL + embedding/chunking version only.
                # Collection-version busting activates once the ingest pipeline
                # calls cache.invalidate_collection (a later enhancement).
                collection_names=None,
                # Same identity the lookup will use. Written by the same helper
                # so the read and the write cannot disagree about which bucket
                # this answer belongs in.
                language=effective_language(state),
            )
        except Exception:
            pass  # cache is best-effort — never fail the response on a cache error

    # Stamp a link onto every citation whose source document is actually held
    # here. Deliberately AFTER the cache write: a URL is derived from what is on
    # disk right now, so freezing one into a cache entry would outlive the file
    # it points at. A cache hit re-enters this line and is linked afresh.
    apply_source_links(citations)

    return {
        "answer":             clean,
        "citations":          citations,
        "claim_assessments":  claims,
        "convergence_status": "converged" if is_grounded else "max_attempts",
        "messages":           [AIMessage(content=clean[:500])],
    }
