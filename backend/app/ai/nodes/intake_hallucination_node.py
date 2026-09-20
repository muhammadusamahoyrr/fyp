import json

from pydantic import BaseModel

from app.ai.answer_citations import (
    build_generation_evidence,
    format_evidence_for_prompt,
    grounding_veto,
    parse_claim_support,
)
from app.ai.graph.state import AgentState
from app.ai.intake_evidence import (
    BIND_ID,
    BIND_NONE,
    STATUS_BOUND,
    bind_intake_citations,
    bind_textually,
    build_intake_claims,
    summarise_binding,
)
from app.ai.llm import get_structured_llm
from app.ai.nodes.intake_node import INTAKE_STATUTE_LIMIT
from app.ai.provider_health import PURPOSE_INTAKE_GROUNDING

# THE VERDICT COVERS THE SUMMARY NOW, NOT ONLY THE ACTIONS.
#
# This judge used to be handed `recommended_actions` alone, and its single
# boolean was then stamped on the whole analysis — summary and law list
# included. The summary asserts the client's legal position and was never
# checked against anything.
#
# The claim list is passed in one flat block and the verdicts come back as one
# flat string, for the reason recorded in answer_citations.parse_claim_support:
# the fast tier emits malformed tool calls when asked for a wide structured
# output. Structure lives in the deterministic parser, not in the schema. This
# is still ONE model call — the same one as before, with more in front of it.
_SYSTEM = """\
You are a legal answer validator for Pakistani intake case analysis.

You are given numbered law sections, and numbered claims taken from an analysis built on them. Each claim names the sections it rests on.

Return JSON with:
- is_grounded: true if every claim is reasonably supported by the sections it names
- reason: one-sentence explanation in English
- claim_support: one verdict per claim, as "index:value" pairs separated by commas, where value is one of supported, partial, unsupported. Example: "1:supported,2:partial,3:unsupported"

Judge each claim only against the sections it names. Do not use knowledge beyond the sections provided."""

_CAUTION = (
    " Note: some parts of this analysis could not be fully verified against the "
    "retrieved law sections — please confirm with a qualified Pakistani lawyer."
)

_CITATION_CAUTION = (
    " Note: one or more statutes cited here could not be matched to the "
    "retrieved law sections and must not be relied on without checking."
)


class IntakeGroundingOutput(BaseModel):
    is_grounded: bool
    reason: str
    claim_support: str = ""


def _finish(parsed: dict | None, status: str, extra: dict, caution: bool = True) -> dict:
    """Not grounded. Carry the analysis through with the caution attached.

    `is_grounded` was a bool asked to carry three meanings — verified grounded,
    verified ungrounded, and never checked — and every case where the check
    could not run resolved to the first of those. `grounding_status` names which
    of the three actually happened.
    """
    out: dict = {"is_grounded": False, "grounding_status": status, **extra}
    if parsed is not None:
        if caution:
            parsed["summary"] = (parsed.get("summary", "") or "") + _CAUTION
        out["answer"] = json.dumps(parsed, ensure_ascii=False)
    return out


def intake_hallucination_node(state: AgentState) -> dict:
    answer = state.get("answer", "")

    # The analyst's list, or an identical rebuild of it.
    #
    # Normally `intake_node` puts it in state and this reads exactly what the
    # analyst was shown. The fallback covers a state that never went through
    # that node — mirroring the chat path, which carries one for the same
    # reason — and it is safe only because `build_generation_evidence` is
    # deterministic and BOTH sides pass `INTAKE_STATUTE_LIMIT`. Rebuilding under
    # a different limit is precisely how `[3]` came to mean different sections
    # to the analyst and its judge.
    #
    # Preferred over reporting "no evidence retrieved", which would be a false
    # negative on the one field a reader most needs to be true.
    evidence = state.get("generation_evidence")
    if not evidence:
        evidence = build_generation_evidence(
            state.get("reranked_chunks") or [],
            state.get("case_law_chunks") or [],
            statute_limit=INTAKE_STATUTE_LIMIT,
        )

    if not answer:
        return {"is_grounded": False, "grounding_status": "no_answer"}

    try:
        parsed = json.loads(answer)
    except Exception:
        return {"is_grounded": False, "grounding_status": "unparseable"}

    # ── Phase 1: bind the citations. Deterministic, no model. ────────────────
    #
    # An evidence id either exists or it does not, and the section it names
    # either matches that chunk or it does not. Asking a language model to
    # decide that would be slower, less certain, and — on a CPU-only
    # deployment — the expensive half of the node.
    law_citations = parsed.get("law_citations") or []
    citations, binding_mode = bind_intake_citations(law_citations, evidence)

    if binding_mode != BIND_ID and not citations:
        # A provider that ignored the id contract entirely. Fall back to the
        # chat path's behaviour so the analysis degrades to today's quality
        # rather than to a wall of phantoms — and record WHICH route ran, so a
        # silent downgrade is not mistaken for a clean result.
        legacy = parsed.get("applicable_laws") or []
        if legacy:
            citations, binding_mode = bind_textually("\n".join(str(x) for x in legacy),
                                                     evidence)

    binding = summarise_binding(citations)
    bound_extra = {
        "citations": citations,
        "binding_mode": binding_mode if citations else BIND_NONE,
        "citation_binding": binding,
    }

    # A citation that named a source nobody showed the model is a fabricated
    # citation. Flagged on the analysis itself, not only in the record: this is
    # the sentence a reader most needs to see.
    if binding["untrustworthy"]:
        parsed["summary"] = (parsed.get("summary", "") or "") + _CITATION_CAUTION

    # ── Phase 2: judge the claims. One model call. ───────────────────────────
    if not evidence:
        # No evidence is not grounding. Retrieval returning nothing — or failing
        # outright, which this graph has no decision node to notice — is
        # precisely when an analysis is least supported.
        return _finish(parsed, "no_evidence_retrieved", bound_extra)

    actions = parsed.get("recommended_actions") or []
    claims = build_intake_claims(parsed.get("summary", ""), actions, citations, evidence)

    # Nothing was claimed on a source's authority, so nothing was verified.
    # Still not a pass — but the caution stays off, because "some parts could
    # not be verified" is noise on an analysis that recommended nothing and
    # cited nothing. A caution nobody needs is a caution nobody reads.
    #
    # A summary resting on citations that DID bind is judged as usual; the rule
    # is about an analysis with nothing checkable in it, not about the absence
    # of the actions field alone.
    if not claims or (not actions and not binding[STATUS_BOUND]):
        # `parsed` is handed over only when something actually changed it — a
        # fabricated-citation notice. Otherwise no `answer` is returned at all,
        # so this path cannot rewrite an analysis it had nothing to say about.
        return _finish(parsed if binding["untrustworthy"] else None,
                       "no_actions", bound_extra, caution=False)

    checkable = [c for c in claims if c["citation_status"] == "matched"]
    if not checkable:
        # Nothing rests on a source that resolved, so there is nothing the judge
        # could check. Running it anyway would spend a call to obtain a verdict
        # about nothing.
        #
        # A fabricated citation is reported AS one. It is the more specific and
        # far more serious finding, and "nothing bound" would describe the same
        # state in a way that sounds like an absence rather than an invention.
        status = "citations_unverified" if binding["untrustworthy"] else "no_bound_citations"
        return _finish(parsed, status,
                       {**bound_extra, "claim_assessments": claims},
                       caution=not binding["untrustworthy"])

    claims_block = "\n".join(
        f"{c['index']}. (rests on {', '.join(c['source_ids']) or 'nothing resolvable'}) "
        f"[{c['kind']}] {c['text']}"
        for c in checkable
    )

    try:
        llm = get_structured_llm(IntakeGroundingOutput,
                                 purpose=PURPOSE_INTAKE_GROUNDING)
        result: IntakeGroundingOutput = llm.invoke([
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": (
                f"Law sections:\n{format_evidence_for_prompt(evidence)}\n\n"
                f"Claims to assess:\n{claims_block}"
            )},
        ])
    except Exception:
        return _finish(parsed, "judge_failed",
                       {**bound_extra, "claim_assessments": claims})

    # Never raises: an unparseable verdict leaves every claim `unassessed`,
    # which is the honest report. A missing verdict is not evidence of support.
    assessed = parse_claim_support(result.claim_support, claims)

    # The judge's own claim assessment gets a vote on the judge's verdict. Both
    # halves come from one call, and the one the user is shown must not be the
    # one nobody checked against the other. Deterministic, and only ever in the
    # safe direction: it can withdraw a claim of groundedness, never grant one.
    veto = grounding_veto(assessed)
    graded = {**bound_extra, "claim_assessments": assessed, "grounding_veto": veto}

    # A fabricated citation is not something a judge's "grounded" can outvote.
    if binding["untrustworthy"]:
        return _finish(parsed, "citations_unverified", graded, caution=False)

    if result.is_grounded and veto is None:
        return {"is_grounded": True, "grounding_status": "grounded", **graded}

    return _finish(parsed, "ungrounded" if veto is None else "claims_disagree", graded)
