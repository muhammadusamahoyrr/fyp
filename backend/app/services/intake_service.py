import asyncio
import json
import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.core.config import settings
from pydantic import ValidationError as PydanticValidationError

from app.core.constants import CaseStatus
from app.core.exceptions import AppValidationError, ConflictError, NotFoundError
from app.repositories.intake_repo import IntakeRepository
from app.repositories.case_repo import CaseRepository
from app.services.case_service import create_case
from app.schemas.intake import (
    IntakeStep1,
    IntakeStep2,
    IntakeStep3,
    IntakeStep4,
    IntakeStep5,
)
from app.utils.file_handler import detect_mime, ext_for_mime

logger = logging.getLogger(__name__)

intake_repo = IntakeRepository()
case_repo   = CaseRepository()

_MAX_CLARIFY_ROUNDS = 4

STEP_REQUIRED_FIELDS = {
    1: ["province"],
    2: [],  # case_type is AI-detected; urgency is optional (defaults to "medium")
    3: ["incident_description"],
    4: [],
    5: ["desired_outcome"],
}

# The step contract. Validation used to be STEP_REQUIRED_FIELDS alone — a
# non-empty check on a couple of names — while five Pydantic models describing
# these exact payloads sat in schemas/intake.py imported by nothing.
STEP_SCHEMAS = {
    1: IntakeStep1,
    2: IntakeStep2,
    3: IntakeStep3,
    4: IntakeStep4,
    5: IntakeStep5,
}

# Domain-specific missing-fact templates (mirrors fact_gap_node.py)
_CLARIFY_TEMPLATES = {
    "criminal": (
        "Criminal case key facts:\n"
        "1. Has an FIR been filed? At which police station?\n"
        "2. What is the nature and severity of harm or injury?\n"
        "3. Are there witnesses?\n"
        "4. What is the exact date and location of the incident?"
    ),
    "family": (
        "Family law key facts:\n"
        "1. Is the marriage registered under Muslim Family Laws Ordinance 1961?\n"
        "2. Are children involved? Ages?\n"
        "3. What is the agreed Mehr (dower) amount?\n"
        "4. Is the dispute about divorce, custody, inheritance, or maintenance?"
    ),
    "civil": (
        "Civil case key facts:\n"
        "1. Is there a written contract or registered agreement?\n"
        "2. What proof of ownership or entitlement exists?\n"
        "3. What is the disputed amount or property value?\n"
        "4. Has a formal legal notice been sent to the other party?"
    ),
    "constitutional": (
        "Constitutional matter key facts:\n"
        "1. Which fundamental right under the Constitution of Pakistan 1973 is violated?\n"
        "2. Which government authority is responsible?\n"
        "3. Has a writ petition or complaint been filed previously?\n"
        "4. Is this an individual matter or public interest?"
    ),
}

_CLARIFY_SYSTEM = """\
You are a Pakistani legal intake specialist. The user has described their legal issue.

INSTRUCTIONS:
1. Review what the user has ALREADY provided in their description and prior answers below.
2. Identify the ONE most critical fact still missing that would significantly improve legal analysis for THIS specific situation.
3. If all key facts for this situation are present, respond with exactly: DONE

Your question MUST be specific to what THIS user described — reference details from their description.
Ask in the same language the user used (English or Urdu). No explanations — just the question.

GOOD example: "You mentioned your landlord beat you — did you sustain injuries that required medical attention?"
BAD example: "What is the nature and severity of harm?" (too generic, ignores what user said)"""

_FALLBACK_QUESTIONS = {
    "criminal": "Can you describe what happened, including the date and location of the incident?",
    "family": "Can you describe the family dispute and who is involved?",
    "civil": "Can you describe the dispute, including what property or amount is involved?",
    "constitutional": "Which government authority or institution is involved in your matter?",
}


async def start_intake(client_id: str) -> dict:
    token = secrets.token_urlsafe(24)
    doc = {
        "_id":               secrets.token_urlsafe(16),
        "session_token":     token,
        "client_id":         client_id,
        "current_step":      1,
        "completed":         False,
        "step1":             None,
        "step2":             None,
        "step3":             None,
        "step4":             None,
        "step5":             None,
        "case_id":           None,
        "clarification_qa":  [],   # [{q: str, a: str | None}]
        "ai_structured_case": {
            "summary":              "pending",
            "applicable_laws":      [],
            "recommended_actions":  [],
            "risk_level":           None,
            "grounded":             False,
            "grounding_status":     "unverified",
        },
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }
    await intake_repo.insert(doc)
    return {"session_token": token, "message": "Intake session started"}


async def save_step(token: str, step: int, data: dict, client_id: str) -> dict:
    intake = await intake_repo.find_by_token(token)
    if not intake or intake.get("client_id") != client_id:
        raise NotFoundError("Intake session")
    if intake.get("completed"):
        raise AppValidationError("Intake already completed")

    cleaned = _validate_step(step, data)
    await intake_repo.update_step(token, step, cleaned)

    updated = await intake_repo.find_by_token(token)
    return {
        "session_token": token,
        "current_step":  updated.get("current_step", step),
        "completed":     False,
        "case_id":       None,
    }


# ─── P2: Multi-round clarification ───────────────────────────────────────────

async def get_clarification(token: str, client_id: str, answer: str | None) -> dict:
    """
    Multi-round AI clarification.
    Call 1 (answer=None): get Q1 (most critical missing fact).
    Call 2 (answer=Q1_answer): save answer, get Q2 or done.
    Returns: { question, done, round }
    """
    # Imported beside get_llm, in the function, matching how every other AI
    # dependency enters this module. It was missing entirely: the name was used
    # at the call site below and bound nowhere, so evaluating the argument
    # raised NameError before get_llm ran — and the `except Exception` around
    # it reported that as "the provider failed, let the user through". Every
    # intake since silently received zero clarifying questions.
    from app.ai.llm import get_llm
    from app.ai.provider_health import PURPOSE_INTAKE_EXTRACTION

    intake = await intake_repo.find_by_token(token)
    if not intake or intake.get("client_id") != client_id:
        raise NotFoundError("Intake session")

    qa_list  = list(intake.get("clarification_qa") or [])
    step2    = intake.get("step2") or {}
    step3    = intake.get("step3") or {}
    province = (intake.get("step1") or {}).get("province", "federal")
    desc     = step3.get("incident_description", "")

    # Detect case type from description so we pick the right Q&A template.
    # The dropdown was removed from the UI, so step2.case_type is unreliable.
    if desc:
        from app.ai.nodes.classifier_node import _score_query
        scores = _score_query(desc)
        best_type, (best_score, _) = max(scores.items(), key=lambda x: x[1][0])
        case_type = best_type.value if best_score >= 0.20 else step2.get("case_type", "civil")
    else:
        case_type = step2.get("case_type", "civil")

    # Save the answer to the last unanswered question
    if answer and qa_list and qa_list[-1].get("a") is None:
        qa_list[-1]["a"] = answer.strip()

    # A QUESTION ALREADY OUTSTANDING IS THE ANSWER TO THIS CALL.
    #
    # Idempotency, and it is the natural kind rather than a bolted-on token: if
    # the last question has no answer and this call supplied none, the client is
    # asking what to answer — and that is a question that already exists.
    #
    # Without this a retry after a dropped response generated ANOTHER question
    # and appended it, so the client saw a different question than the one they
    # were about to answer, the list grew a round they never completed, and an
    # LLM call was spent to make things worse. A double-submitted button did the
    # same thing.
    if qa_list and qa_list[-1].get("a") is None and not answer:
        outstanding = qa_list[-1].get("q") or ""
        if outstanding:
            answered = sum(1 for qa in qa_list if qa.get("a"))
            return {"question": outstanding, "done": False,
                    "round": min(answered + 1, _MAX_CLARIFY_ROUNDS)}

    # Already done 2 rounds → force proceed
    answered_rounds = sum(1 for qa in qa_list if qa.get("a"))
    if answered_rounds >= _MAX_CLARIFY_ROUNDS:
        await intake_repo.save_clarification_qa(token, qa_list)
        return {"question": None, "done": True, "round": answered_rounds}

    # Build context for LLM
    prev_qa_text = "\n".join(
        f"Q{i+1}: {qa['q']}\nA{i+1}: {qa.get('a') or '(no answer)'}"
        for i, qa in enumerate(qa_list)
    )
    template = _CLARIFY_TEMPLATES.get(case_type, "")

    user_msg = (
        f"Case type: {case_type}\n"
        f"Province: {province}\n"
        f"Description: {desc}\n"
        f"Previous Q&A:\n{prev_qa_text or 'None yet'}\n\n"
        f"Domain key facts:\n{template}"
    )

    try:
        llm      = get_llm(purpose=PURPOSE_INTAKE_EXTRACTION)
        response = await asyncio.to_thread(llm.invoke, [
            {"role": "system", "content": _CLARIFY_SYSTEM},
            {"role": "user",   "content": user_msg},
        ])
        text = response.content.strip()
    except Exception:
        # LLM failed — let user proceed rather than trapping them in a loop.
        #
        # Logged, not just swallowed. A bare `except Exception` here treated a
        # NameError in this very function as a provider outage and degraded
        # silently for the entire life of the feature. Letting the client
        # through is still right; doing it without a trace is not.
        logger.exception("Intake clarification failed — proceeding without a question")
        await intake_repo.save_clarification_qa(token, qa_list)
        return {"question": None, "done": True, "round": answered_rounds}

    if text.upper().startswith("DONE"):
        await intake_repo.save_clarification_qa(token, qa_list)
        return {"question": None, "done": True, "round": answered_rounds}

    # New question
    next_round = answered_rounds + 1
    qa_list.append({"q": text, "a": None})
    await intake_repo.save_clarification_qa(token, qa_list)
    return {"question": text, "done": False, "round": next_round}


_VALID_CASE_TYPES = {"civil", "criminal", "family", "constitutional"}

_TYPE_CLASSIFY_SYSTEM = """\
You are a Pakistani legal intake specialist. Based on the case description, classify it into exactly one category:
- criminal: FIR, murder/قتل, theft/چوری, assault, robbery/ڈکیتی, rape/زنا, bail/بیل, arrest/گرفتاری, cybercrime, PECA, PPC offences
- family: divorce/طلاق, talaq, khula/خلع, custody/حضانت, maintenance/نفقہ, nikah/نکاح, inheritance/وراثت, dowry/جہیز, mehr/مہر, MFLO, shadi/شادی
- constitutional: fundamental rights, writ petition, government authority, Supreme/High Court, Article of Constitution
- civil: property dispute, contract, debt, tenancy, eviction, compensation, damages, CPC matters

The description may be in English, Urdu script, or Romanized Urdu — handle all three.
Return only the single word: criminal, family, constitutional, or civil. Nothing else."""


async def _ai_classify_case_type(description: str, user_selected: str) -> tuple[str, bool]:
    """
    Returns (final_case_type, was_corrected).
    Step 1: keyword classifier (fast, free).
    Step 2: LLM fallback when keyword confidence < 0.30 (ambiguous description).
    """
    from app.ai.nodes.classifier_node import _score_query

    scores = _score_query(description)
    best_type, (best_score, _) = max(scores.items(), key=lambda x: x[1][0])

    if best_score >= 0.30:
        ai_type = best_type.value
    else:
        # Low keyword signal — let the LLM decide
        try:
            from app.ai.llm import get_fast_llm
            from app.ai.provider_health import PURPOSE_INTAKE_EXTRACTION
            llm = get_fast_llm(purpose=PURPOSE_INTAKE_EXTRACTION)
            response = await asyncio.to_thread(llm.invoke, [
                {"role": "system", "content": _TYPE_CLASSIFY_SYSTEM},
                {"role": "user",   "content": description[:1200]},
            ])
            ai_type = response.content.strip().lower().split()[0]
            if ai_type not in _VALID_CASE_TYPES:
                ai_type = user_selected  # LLM gave unexpected output — trust user
        except Exception:
            # Same reasoning as get_clarification: falling back to the user's
            # own pick is the right behaviour, but it must leave evidence.
            logger.exception("Intake case-type classification failed — trusting the user's pick")
            ai_type = user_selected

    was_corrected = ai_type != user_selected
    return ai_type, was_corrected


# ─── Convert + P1 (embedding) + P5 (auto-match) ──────────────────────────────

# How long one conversion may hold its claim before another request may take it
# over. Sized for the slow path, not the happy one: the analysis runs an LLM,
# and on a CPU-only deployment that is minutes. Too short and a retry re-pays
# for an analysis still in flight; too long and a worker that died mid-convert
# locks the client out of their own intake.
_CONVERSION_CLAIM_TTL = timedelta(minutes=10)


def _conversion_result(token: str, intake: dict) -> dict:
    """The /convert payload, rebuilt from a converted intake.

    Lets a repeat call answer with what the first call decided. Intakes
    converted before the classification was stored fall back to what step 2
    holds, so an old record replays a truthful payload rather than a null one.
    """
    return {
        "session_token":      token,
        "current_step":       5,
        "completed":          True,
        "case_id":            intake.get("case_id"),
        "ai_case_type":       intake.get("ai_case_type"),
        "user_case_type":     intake.get("user_case_type")
                              or (intake.get("step2") or {}).get("case_type"),
        "type_was_corrected": bool(intake.get("type_was_corrected")),
    }


async def convert_to_case(
    token: str,
    client_id: str,
    language: str = "en",
    urgency: str | None = None,
) -> dict:
    """Turn a finished intake into a case. Safe to call more than once.

    One intake yields at most one case. The old flow read `completed`, then ran
    a classification, a case insert and a full AI analysis before writing
    `completed` back — a check-then-act window seconds to minutes wide. Two
    convert calls in that window (a double submit, a client retry after a
    timeout, two open tabs) both passed the check and both opened a case: the
    client saw one, the other was billed for, matched to lawyers, and left
    behind with no intake pointing at it.

    The guard is now an atomic claim taken before any work, and the case is
    pinned to the intake the moment it is created.
    """
    intake = await intake_repo.find_by_token(token)
    if not intake or intake.get("client_id") != client_id:
        raise NotFoundError("Intake session")

    # A second convert REPLAYS the first one's answer rather than failing. The
    # caller whose response was lost to a dropped connection has no way to tell
    # "already converted" from "never converted", and a 422 pushed it into
    # exactly the retry loop this guard exists to stop.
    if intake.get("completed"):
        return _conversion_result(token, intake)

    missing = [i for i in range(1, 6) if intake.get(f"step{i}") is None]
    if missing:
        raise AppValidationError(f"Steps not completed: {missing}")

    if not await intake_repo.claim_conversion(token, _CONVERSION_CLAIM_TTL):
        # Someone else holds the claim. Re-read: if they finished while we were
        # asking, the client gets the case; otherwise say so plainly, and do
        # not start a second conversion beside theirs.
        current = await intake_repo.find_by_token(token) or intake
        if current.get("completed"):
            return _conversion_result(token, current)
        raise ConflictError("This intake is already being converted — please wait")

    try:
        return await _convert_claimed_intake(token, client_id, intake, language, urgency)
    except Exception:
        # Release on the way out so the client can retry. `case_id` is left
        # pinned on purpose: the retry resumes on the case that already exists.
        await intake_repo.release_conversion(token)
        raise


async def _convert_claimed_intake(
    token: str,
    client_id: str,
    intake: dict,
    language: str,
    urgency: str | None,
) -> dict:
    """The conversion itself. Only ever runs under a held claim."""
    step1 = intake.get("step1") or {}
    step2 = intake.get("step2") or {}
    step3 = intake.get("step3") or {}
    step4 = intake.get("step4") or {}
    step5 = intake.get("step5") or {}

    # Classify on the base description ONLY — before Q&A is appended.
    # Appending clarification Q&A first would pollute keyword scores because the
    # questions themselves contain domain words (e.g. civil template asks about
    # "contract" and "property value"), which biases the classifier.
    base_description = step3.get("incident_description", "")
    user_case_type   = step2.get("case_type", "civil")
    ai_case_type, type_corrected = await _ai_classify_case_type(base_description, user_case_type)

    # Enrich description with clarification Q&A for AI analysis (after classification)
    qa_list  = intake.get("clarification_qa") or []
    answered = [qa for qa in qa_list if qa.get("a")]
    sections = [base_description]
    if answered:
        qa_text = "\n".join(f"Q: {qa['q']}\nA: {qa['a']}" for qa in answered)
        sections.append(f"Additional context from intake:\n{qa_text}")

    # Steps 4 and 5 were collected, stored, and then read by nothing: the
    # analysis ran on step 3 alone. What the client wants out of the matter,
    # what they can prove, and which side of it they are on are exactly the
    # facts that shape a recommendation, so they belong in front of the model.
    desired_outcome = (step5.get("desired_outcome") or "").strip()
    if desired_outcome:
        sections.append(f"Desired outcome:\n{desired_outcome}")

    evidence_note  = (step4.get("evidence_description") or "").strip()
    evidence_count = len(intake.get("evidence_files") or [])
    evidence_bits  = []
    if step4.get("has_evidence"):
        evidence_bits.append("The client says they hold supporting evidence.")
    if evidence_count:
        evidence_bits.append(f"{evidence_count} file(s) were uploaded during intake.")
    if evidence_note:
        evidence_bits.append(evidence_note)
    if evidence_bits:
        sections.append("Evidence:\n" + " ".join(evidence_bits))

    opposing_party = (step4.get("opposing_party") or "").strip()
    if opposing_party:
        sections.append(f"Opposing party:\n{opposing_party}")

    party_role = step1.get("party_role")
    if party_role:
        sections.append(f"The client is the {party_role} in this matter.")

    notes = (step5.get("additional_notes") or "").strip()
    if notes:
        sections.append(f"Additional notes:\n{notes}")

    description = "\n\n".join(s for s in sections if s)

    case_data = {
        "case_type":            ai_case_type,          # AI-verified, not raw user pick
        "user_selected_type":   user_case_type,        # keep original for audit
        "type_was_corrected":   type_corrected,
        "province":             step1.get("province"),
        # The TITLE stays the client's own account of the incident. The
        # enriched description above is analysis input; a case titled "The
        # client is the plaintiff in this matter" would read as generated.
        "title":                (base_description[:80] or description[:80]),
        "description":          description,
        "intake_id":            intake["_id"],
        # Carried onto the case so downstream work — matching, drafting, the
        # lawyer's own view — can see which side the client is on and what they
        # asked for, instead of trying to re-derive it from prose.
        "party_role":           party_role,
        "desired_outcome":      desired_outcome or None,
        "urgency":              urgency or step2.get("urgency", "medium"),
        "has_evidence":         bool(step4.get("has_evidence")) or evidence_count > 0,
        "evidence_count":       evidence_count,
    }
    # Resume onto the case a previous failed attempt already opened, if there
    # is one. Creating a second case here is what turns a retry into duplicate
    # legal records for one dispute.
    #
    # TWO places to look, and the second one is the crash path.
    #
    # `intake.case_id` covers an attempt that failed AFTER pinning the case. It
    # does NOT cover a process killed between the case insert and that pin: the
    # case exists, the intake has no idea, and `uniq_case_per_intake` then
    # refuses every retry. Before this lookup that surfaced as
    # "Could not generate a unique case number — please try again", five times
    # over, for ever — a client permanently unable to convert their own intake,
    # told to retry the one thing that could never work.
    #
    # Searching by `intake_id` finds the orphan and adopts it, which is what the
    # index is for: it guarantees there is at most one, so whatever comes back
    # IS this intake's case.
    pinned_id = intake.get("case_id")
    pinned    = await case_repo.find_by_id(pinned_id) if pinned_id else None
    if not pinned:
        pinned = await case_repo.find_by_intake(intake["_id"])
        if pinned:
            logger.warning(
                "intake %s had an unpinned case %s — adopting it rather than "
                "creating a second", token, pinned["_id"])

    if pinned:
        case_id = pinned["_id"]
        await case_repo.update_one({"_id": case_id}, {"$set": case_data})
        # Re-pin: the crash path arrives here with the intake still not knowing
        # about its own case, and leaving it that way would need this recovery
        # to run again on every future attempt.
        if intake.get("case_id") != case_id:
            await intake_repo.attach_case(token, case_id)
    else:
        # DRAFT, not open. The analysis below needs a real `case_id` — it is
        # bound to one and provenance records it — so the case has to exist
        # before the client has confirmed anything. Creating it OPEN meant the
        # client was invited to "review and confirm" a case that was already
        # live, and the confirm button had nothing left to do.
        case = await create_case(client_id, case_data, status=CaseStatus.DRAFT.value)
        case_id = case["_id"]
        # Written before the AI work below, not after it: everything from here
        # to mark_completed can fail, and a case the intake does not know about
        # is a case the next attempt will duplicate.
        await intake_repo.attach_case(token, case_id)
    # Embedding is scheduled inside create_case

    # Use frontend-provided urgency if given; fall back to what the user stored in step 2
    effective_urgency = urgency or step2.get("urgency", "medium")

    # Run AI structured analysis using the AI-verified case type
    ai_data = await _run_intake_ai(
        query=description,
        case_type=ai_case_type,
        province=step1.get("province", "federal"),
        session_id=token,
        case_id=case_id,
        language=language,
        urgency=effective_urgency,
        # Carried for the audit record only. The provenance store names the
        # user whose turn it was, and an intake conversion has one.
        client_id=client_id,
    )
    await intake_repo.save_ai_structured_case(token, ai_data)

    # Sync AI summary + verified type to case document so lawyer matching can use it
    if ai_data and ai_data.get("summary"):
        await case_repo.update_one(
            {"_id": case_id},
            {"$set": {
                "ai_summary": ai_data.get("summary"),
                "case_type":  ai_case_type,
            }}
        )

    # Matching does NOT run here any more. A draft cannot be matched — it is
    # not a case anyone should be ranked against — so this moved to the moment
    # the client confirms. See case_service.confirm_case.

    await intake_repo.mark_completed(
        token,
        case_id,
        ai_case_type=ai_case_type,
        user_case_type=user_case_type,
        type_was_corrected=type_corrected,
    )
    return {
        "session_token":      token,
        "current_step":       5,
        "completed":          True,
        "case_id":            case_id,
        "ai_case_type":       ai_case_type,
        "user_case_type":     user_case_type,
        "type_was_corrected": type_corrected,
    }


async def _auto_match_lawyers(case_id: str) -> None:
    """P5 — run semantic lawyer matching and cache top 5 results on the case."""
    try:
        from app.services.lawyer_service import match_lawyers_for_case
        matches = await match_lawyers_for_case(case_id, top_n=5)
        slim = [
            {
                "lawyer_id":       str(m.get("_id", "")),
                "full_name":       m.get("full_name", ""),
                "province":        m.get("province", ""),
                "match_score":     m.get("match_score", 0.0),
                "match_reason":    m.get("match_reason", ""),
                "rating":          (m.get("lawyer_profile") or {}).get("rating", 0.0),
                "specializations": (m.get("lawyer_profile") or {}).get("specializations", []),
                "availability":    (m.get("lawyer_profile") or {}).get("availability", False),
            }
            for m in matches
        ]
        await case_repo.set_matched_lawyers(case_id, slim)
    except Exception:
        pass  # non-critical


async def _run_intake_ai(
    query: str,
    case_type: str,
    province: str,
    session_id: str,
    case_id: str,
    language: str = "en",
    urgency: str = "medium",
    client_id: str = "",
) -> dict:
    from app.ai.graph.supervisor import intake_graph

    state = {
        "query":                  query,
        "normalized_query":       "",
        "session_id":             session_id,
        "case_id":                case_id,
        "case_type":              case_type,
        "case_type_confidence":   0.0,
        "complexity":             "simple",
        "urgency":                urgency,
        "province":               province,
        "province_inferred":      False,
        "language":               language,
        "classifier_case_type":   case_type,
        "classifier_confidence":  1.0,
        "classifier_scores":      {},
        "precomputed_collection_names": [],
        "routing_mode":           "single",
        "followup_intent":        None,
        "needs_clarification":    False,
        "clarification_question": "",
        "clarification_depth":    0,
        "interrupt_active":       False,
        "interrupt_question_type": "",
        "interrupt_question_text": "",
        "interrupt_step":         0,
        "interrupt_expires_at":   "",
        "web_search_enabled":     False,
        "retrieved_chunks":       [],
        "reranked_chunks":        [],
        "relevance_score":        1.0,
        "signal_variance":        0.0,
        "bm25_confidence":        0.0,
        "cache_hit":              False,
        "cache_confidence":       0.0,
        # Intake runs build_intake_graph(), which has no decision_node — the
        # verdict stays "pending" and is never read. Seeded for schema parity.
        "arbitration_output":     "pending",
        "arbitration_source":     "none",
        "arbitration_confidence": 0.0,
        "answer":                 "",
        "citations":              [],
        "generation_evidence":    [],
        "claim_assessments":      [],
        "case_law_chunks":        [],
        "tool_results":           [],
        "confidence":             0.0,
        "is_grounded":            False,
        "prev_relevance_score":   0.0,
        "prev_confidence":        0.0,
        "known_facts":            [],
        "fact_delta":             0,
        "retrieval_attempts":     0,
        "generation_attempts":    0,
        "clarification_attempts": 0,
        "convergence_status":     "pending",
        "messages":               [],
    }

    # Minted BEFORE the graph runs, and stored on the analysis. A provenance
    # write may land in the outbox rather than the collection, so without an id
    # fixed in advance the analysis and its audit record cannot be joined until
    # delivery happens to complete.
    request_id = secrets.token_urlsafe(16)

    try:
        result = await intake_graph.ainvoke(state)
        analysis = json.loads(result["answer"])
        # The grounding verdict was computed and then dropped on the floor here:
        # this read only `answer`, so even a correct "not grounded" never left
        # the graph. Carried through now, with the status that says WHICH of
        # verified / unverified / unchecked actually happened.
        analysis["grounded"] = bool(result.get("is_grounded"))
        analysis["grounding_status"] = result.get("grounding_status") or "unverified"

        # The evidence the analysis was actually built on. `reranked_chunks`
        # reached this function and were dropped on the floor: nothing recorded
        # WHICH sections produced the analysis, so no later reader could check
        # it against them or re-fetch them.
        analysis["law_citations"] = result.get("citations") or []
        analysis["claim_assessments"] = result.get("claim_assessments") or []
        analysis["binding_mode"] = result.get("binding_mode") or "none"
        analysis["citation_binding"] = result.get("citation_binding") or {}
        analysis["grounding_veto"] = result.get("grounding_veto")
        analysis["evidence_chunk_ids"] = [
            e.get("chunk_id", "") for e in (result.get("generation_evidence") or [])
            if e.get("chunk_id")
        ]
        analysis["provenance_request_id"] = request_id

        await _record_intake_provenance(
            result, analysis, session_id, client_id, request_id)
        return analysis
    except Exception:
        logger.exception("Intake analysis pipeline failed for session %s", session_id)
        return {
            "summary":             "AI structuring unavailable — case created successfully.",
            "applicable_laws":     [],
            "recommended_actions": ["Consult a qualified Pakistani lawyer for advice."],
            "risk_level":          "medium",
            "grounded":            False,
            "grounding_status":    "pipeline_failed",
            "law_citations":       [],
            "claim_assessments":   [],
            "binding_mode":        "none",
            "evidence_chunk_ids":  [],
            "provenance_request_id": request_id,
        }


async def _record_intake_provenance(
    result: dict,
    analysis: dict,
    session_id: str,
    client_id: str,
    request_id: str,
) -> None:
    """Put the intake turn in the audit store, through the EXISTING path.

    `provenance_service.build_record` is pure over state, so there is no reason
    for intake to have a provenance path of its own — the drafting endpoint
    already reuses it the same way, with a synthetic state and a prefixed
    session id.

    The answer handed over is the RENDERED analysis, not the raw JSON document.
    `_citation_grounding` measures citations by parsing the answer text, and
    pointing it at `{"summary": ...}` would have it measure the punctuation of a
    serialisation format rather than the law the analysis names.

    Never raises. An audit write must not fail the conversion it describes —
    the same contract `record_answer` itself keeps.
    """
    try:
        from app.services import provenance_service

        rendered = "\n".join([
            analysis.get("summary", "") or "",
            *(analysis.get("applicable_laws") or []),
            *(analysis.get("recommended_actions") or []),
        ]).strip()

        await provenance_service.record_answer(
            state={**result, "answer": rendered},
            session_id=f"intake:{session_id}",
            user_id=client_id,
            request_id=request_id,
            turn_type=provenance_service.TURN_ANSWER,
        )
    except Exception:
        logger.exception(
            "intake: provenance write failed for session %s (request %s)",
            session_id, request_id)


_EVIDENCE_DIR = Path(settings.upload_root) / "evidence"
_ALLOWED_MIME = {
    "image/jpeg", "image/png", "image/gif", "image/webp",
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
_MAX_EVIDENCE_SIZE = 10 * 1024 * 1024  # 10 MB


async def upload_evidence(token: str, client_id: str, file) -> dict:
    import aiofiles

    intake = await intake_repo.find_by_token(token)
    if not intake or intake.get("client_id") != client_id:
        raise NotFoundError("Intake session")

    content = await file.read()
    if len(content) > _MAX_EVIDENCE_SIZE:
        raise AppValidationError("File too large — maximum size is 10 MB")

    # Validate by actual file contents, not the client-supplied Content-Type header
    detected_mime = detect_mime(content[:16])
    if detected_mime not in _ALLOWED_MIME:
        raise AppValidationError("File type not allowed. Accepted: PDF, Word, JPEG, PNG, GIF, WebP")

    save_dir = _EVIDENCE_DIR / token
    save_dir.mkdir(parents=True, exist_ok=True)

    file_id = uuid.uuid4().hex
    # Extension from the DETECTED type — never from the client filename.
    suffix  = ext_for_mime(detected_mime)
    save_path = save_dir / f"{file_id}{suffix}"

    async with aiofiles.open(save_path, "wb") as f:
        await f.write(content)

    file_meta = {
        "file_id":      file_id,
        "filename":     file.filename,
        "content_type": file.content_type,
        "size":         len(content),
        "path":         str(save_path),
    }
    await intake_repo.add_evidence_file(token, file_meta)
    return {
        "file_id":      file_id,
        "filename":     file.filename,
        "size":         len(content),
        "content_type": file.content_type,
    }


def _public_evidence(files: list[dict] | None) -> list[dict]:
    """Evidence metadata a browser may see.

    `path` is dropped. It is the absolute location on the server's disk, of no
    use to the client, and handing it out discloses the upload root and the
    file-naming scheme to anyone who asks for their own intake.
    """
    return [
        {
            "file_id":      f.get("file_id", ""),
            "filename":     f.get("filename", ""),
            "content_type": f.get("content_type"),
            "size":         f.get("size"),
        }
        for f in (files or [])
        if f.get("file_id")
    ]


async def get_intake(token: str, client_id: str) -> dict:
    """Everything needed to put the client back where they were.

    The response used to be the token, the step number and the AI analysis. A
    refresh therefore restored a session pointing at a half-filled intake and a
    form with every field blank — the answers were on the server and the browser
    had no way to ask for them, so the client retyped their own account of their
    legal problem, or carried on from step 3 with the earlier steps apparently
    empty.
    """
    intake = await intake_repo.find_by_token(token)
    if not intake or intake.get("client_id") != client_id:
        raise NotFoundError("Intake session")

    # Keyed "1".."5" rather than a list: the client reads specific steps back,
    # and a positional array makes a missing middle step ambiguous.
    steps = {
        str(i): intake.get(f"step{i}")
        for i in range(1, 6)
        if intake.get(f"step{i}") is not None
    }

    # Read from the CASE, not from the intake: the intake records that a case
    # was produced, the case itself records whether the client confirmed it.
    case_status = None
    if intake.get("case_id"):
        case = await case_repo.find_by_id(intake["case_id"])
        case_status = (case or {}).get("status")

    return {
        "session_token":     token,
        "current_step":      intake.get("current_step", 1),
        "completed":         intake.get("completed", False),
        "case_id":           intake.get("case_id"),
        "case_status":       case_status,
        "ai_structured_case": intake.get("ai_structured_case"),
        "steps":             steps,
        "clarification_qa":  list(intake.get("clarification_qa") or []),
        "evidence_files":    _public_evidence(intake.get("evidence_files")),
    }


def _validate_step(step: int, data: dict) -> dict:
    """Check the payload against its step model and return the cleaned data.

    Returns what gets STORED, not what arrived: the model coerces types, drops
    nothing silently (unknown keys are an error, not a shrug), and normalises
    the party role's casing. The required-field check runs first so its
    messages — which the UI already surfaces — keep their existing wording.
    """
    required = STEP_REQUIRED_FIELDS.get(step, [])
    missing  = [f for f in required if not str(data.get(f, "")).strip()]
    if missing:
        raise AppValidationError(f"Missing required fields for step {step}: {missing}")

    model = STEP_SCHEMAS.get(step)
    if model is None:
        return data
    try:
        parsed = model(**data)
    except PydanticValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in e['loc']) or 'body'}: {e['msg']}"
            for e in exc.errors()
        )
        raise AppValidationError(f"Invalid data for step {step} — {problems}") from exc
    # mode="json" so enum members land in Mongo as the plain strings every
    # reader already expects — Province/CaseType subclass str, so this would
    # round-trip either way, but only by accident of their base class.
    #
    # exclude_unset keeps a step's stored shape to what the client actually
    # sent, so re-saving one step never backfills defaults over another's data.
    return parsed.model_dump(mode="json", exclude_unset=True)
