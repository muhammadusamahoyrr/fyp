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
from app.services.evidence_coverage import (
    STORAGE_ONLY_MIMES,
    derive_analysis_support,
    snapshot_from_statuses,
)
from app.utils.file_handler import detect_mime, ext_for_mime

logger = logging.getLogger(__name__)

intake_repo = IntakeRepository()
case_repo   = CaseRepository()

_MAX_CLARIFY_ROUNDS = 4


async def _save_clarification_or_conflict(token: str, qa_list: list) -> None:
    if not await intake_repo.save_clarification_qa(token, qa_list):
        raise ConflictError(
            "This intake changed or started converting. Reload before answering."
        )

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
    if not await intake_repo.update_step(token, step, cleaned):
        raise ConflictError(
            "This intake changed or started converting. Reload before editing it."
        )

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
    Multi-round AI clarification, up to _MAX_CLARIFY_ROUNDS (4).
    Call 1 (answer=None): get Q1 (most critical missing fact).
    Call N (answer=previous): save answer, get the next question or done.
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

    # Round budget spent → force proceed (_MAX_CLARIFY_ROUNDS, currently 4)
    answered_rounds = sum(1 for qa in qa_list if qa.get("a"))
    if answered_rounds >= _MAX_CLARIFY_ROUNDS:
        await _save_clarification_or_conflict(token, qa_list)
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
        await _save_clarification_or_conflict(token, qa_list)
        return {"question": None, "done": True, "round": answered_rounds}

    if text.upper().startswith("DONE"):
        await _save_clarification_or_conflict(token, qa_list)
        return {"question": None, "done": True, "round": answered_rounds}

    # New question
    next_round = answered_rounds + 1
    qa_list.append({"q": text, "a": None})
    await _save_clarification_or_conflict(token, qa_list)
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


async def _renew_conversion_claim(token: str, owner: str) -> None:
    """Keep a live conversion fenced for as long as its slow AI call runs."""
    interval = max(_CONVERSION_CLAIM_TTL.total_seconds() / 3, 1)
    while True:
        await asyncio.sleep(interval)
        if not await intake_repo.renew_conversion(
            token, owner, _CONVERSION_CLAIM_TTL
        ):
            return


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

    owner = secrets.token_urlsafe(16)
    conversion_epoch = await intake_repo.claim_conversion(
        token, _CONVERSION_CLAIM_TTL, owner
    )
    if conversion_epoch is None:
        # Someone else holds the claim. Re-read: if they finished while we were
        # asking, the client gets the case; otherwise say so plainly, and do
        # not start a second conversion beside theirs.
        current = await intake_repo.find_by_token(token) or intake
        if current.get("completed"):
            return _conversion_result(token, current)
        raise ConflictError("This intake is already being converted — please wait")

    # Re-read after claiming. A step/evidence write that committed between the
    # first read and the claim must be included in the conversion snapshot.
    intake = await intake_repo.find_by_token(token) or intake
    heartbeat = asyncio.create_task(_renew_conversion_claim(token, owner))
    try:
        return await _convert_claimed_intake(
            token, client_id, intake, language, urgency, owner,
            conversion_epoch,
        )
    except Exception:
        # Release on the way out so the client can retry. `case_id` is left
        # pinned on purpose: the retry resumes on the case that already exists.
        await intake_repo.release_conversion(token, owner)
        raise
    finally:
        heartbeat.cancel()
        try:
            await heartbeat
        except asyncio.CancelledError:
            pass


async def _convert_claimed_intake(
    token: str,
    client_id: str,
    intake: dict,
    language: str,
    urgency: str | None,
    conversion_owner: str,
    conversion_epoch: int,
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
        "intake_conversion_owner": conversion_owner,
        "intake_conversion_epoch": conversion_epoch,
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
        adopted = await case_repo.update_one(
            {
                "_id": case_id,
                "$or": [
                    {"intake_conversion_epoch": {"$lt": conversion_epoch}},
                    {"intake_conversion_epoch": {"$exists": False}},
                    {"intake_conversion_epoch": conversion_epoch},
                ],
            },
            {"$set": case_data},
        )
        if not adopted:
            raise ConflictError("A newer intake conversion owns this case")
        # Re-pin: the crash path arrives here with the intake still not knowing
        # about its own case, and leaving it that way would need this recovery
        # to run again on every future attempt.
        if intake.get("case_id") != case_id:
            if not await intake_repo.attach_case(token, case_id, conversion_owner):
                raise ConflictError("Intake conversion ownership was lost")
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
        if not await intake_repo.attach_case(token, case_id, conversion_owner):
            raise ConflictError("Intake conversion ownership was lost")
    # Embedding is scheduled inside create_case

    # Use frontend-provided urgency if given; fall back to what the user stored in step 2
    effective_urgency = urgency or step2.get("urgency", "medium")

    evidence_text, evidence_status = await _extract_intake_evidence(
        intake.get("evidence_files") or []
    )

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
        evidence_text=evidence_text,
        evidence_status=evidence_status,
    )
    if not await intake_repo.save_ai_structured_case(
        token, ai_data, conversion_owner
    ):
        raise ConflictError("Intake conversion ownership was lost")

    # Sync AI summary + verified type to case document so lawyer matching can use it
    if ai_data and ai_data.get("summary"):
        # The intake write immediately above is the fence. BaseRepository's
        # boolean reports *modified*, not *matched*, so an idempotent same-value
        # case update cannot be used as an ownership verdict.
        await case_repo.update_one(
            {"_id": case_id, "intake_conversion_owner": conversion_owner,
             "intake_conversion_epoch": conversion_epoch},
            {"$set": {
                "ai_summary": ai_data.get("summary"),
                "case_type":  ai_case_type,
                # Written in the SAME guarded update as the summary it qualifies.
                # A separate write could land without it — and a summary that
                # outlives its caveat is exactly the failure being closed: a
                # lawyer reads a confident paragraph with no sign that two
                # thirds of the bundle was never opened.
                #
                # Sanitised by construction: counts and versions only. No
                # filenames, no paths, no extracted text.
                #
                # Built from the LOCAL extraction result, not from `ai_data`.
                # The analysis echoes the statuses back, but it can fail or come
                # from a path that never set the key — and `.get()` returning
                # None then produced a snapshot of zero, which asserts on the
                # case that nothing was uploaded. `evidence_status` is computed
                # before the model runs and is always a list, so it cannot go
                # missing because the model did.
                #
                # `uploaded_count` corroborates the empty case: no statuses AND
                # no attachments is a verified zero; no statuses WITH
                # attachments is a gap, and records UNKNOWN instead.
                "ai_evidence_coverage": snapshot_from_statuses(
                    evidence_status,
                    uploaded_count=len(intake.get("evidence_files") or []),
                ),
            }}
        )

    # Matching does NOT run here any more. A draft cannot be matched — it is
    # not a case anyone should be ranked against — so this moved to the moment
    # the client confirms. See case_service.confirm_case.

    if not await intake_repo.mark_completed(
        token,
        case_id,
        conversion_owner,
        ai_case_type=ai_case_type,
        user_case_type=user_case_type,
        type_was_corrected=type_corrected,
    ):
        raise ConflictError("Intake conversion ownership was lost")
    await case_repo.update_one(
        {"_id": case_id, "intake_conversion_owner": conversion_owner,
         "intake_conversion_epoch": conversion_epoch},
        {"$unset": {"intake_conversion_owner": ""}},
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


async def _run_intake_ai(
    query: str,
    case_type: str,
    province: str,
    session_id: str,
    case_id: str,
    language: str = "en",
    urgency: str = "medium",
    client_id: str = "",
    evidence_text: str = "",
    evidence_status: list[dict] | None = None,
) -> dict:
    from app.ai.graph.supervisor import intake_graph

    state = {
        "query":                  query,
        "normalized_query":       "",
        "session_id":             session_id,
        "case_id":                case_id,
        "intake_evidence_text":   evidence_text,
        "intake_evidence_status": evidence_status or [],
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
        analysis["evidence_extraction"] = evidence_status or []

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
            "evidence_extraction": evidence_status or [],
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
_MAX_EVIDENCE_SIZE = 10 * 1024 * 1024      # 10 MB per file
# Per-INTAKE ceilings. Only a per-file limit existed, so one session could store
# an unbounded number of 10 MB files: the cap read as a storage limit and was a
# request limit. Sized for a real evidence bundle — receipts, an FIR, a couple of
# photographs — not for a document archive.
_MAX_EVIDENCE_FILES = 12
_MAX_EVIDENCE_TOTAL = 40 * 1024 * 1024     # 40 MB across the whole intake
# Read in chunks so an oversized upload is refused as it arrives.
_EVIDENCE_CHUNK = 1024 * 1024
_MAX_EVIDENCE_PROMPT_CHARS = 12_000


async def _extract_intake_evidence(files: list[dict]) -> tuple[str, list[dict]]:
    """Extract bounded text from owned intake files for the analysis prompt.

    WHAT CHANGED AND WHY IT MATTERS HERE

    This used to ask one question per file — did any text come out — and record
    `readable` if it did. A bundle whose typed cover sheet sat in front of two
    scanned pages was therefore handed to the analysis as its cover sheet, marked
    fully read. The model then reasoned about a case from a title page, and
    nothing anywhere in the record said that two thirds of the evidence had not
    been seen.

    Now each file carries how much of it was read, and anything less than whole
    is reported as `partially_read` with the page counts behind it. `readable`
    has a narrower meaning than it used to: the whole document, as far as we can
    tell. Downstream consumers that only understood `readable`/`unreadable` still
    work, because `partially_read` is the honest answer where they would
    previously have been told `readable`, and the prompt builder reads the
    counts rather than the label.

    Extraction runs in ONE bounded child process for the whole batch — not on
    the shared thread pool, and not per file. See `app.ai.extraction_runner`.
    """
    from app.ai import extraction_runner
    from app.ai.extraction import COMPLETE, NONE, OUTCOME_SUCCEEDED

    statuses: list[dict] = []
    root = _EVIDENCE_DIR.resolve()

    owned: list[dict] = []
    for meta in files:
        file_id = str(meta.get("file_id") or "")
        stored = Path(meta.get("path") or "")
        try:
            resolved = stored.resolve()
            resolved.relative_to(root)
        except (OSError, ValueError):
            # Containment is decided BEFORE anything is read, and before the
            # child process is even asked about it.
            statuses.append({"file_id": file_id, "status": "invalid_path"})
            continue
        owned.append({
            "file_id": file_id,
            "path": str(resolved),
            # Derived server-side, falling back to the stored content type for
            # records written before the field existed.
            "analysis_support": derive_analysis_support(meta),
        })

    if not owned:
        return "", statuses

    extracted = await extraction_runner.extract_many(owned)

    excerpts: list[str] = []
    remaining = _MAX_EVIDENCE_PROMPT_CHARS

    for item in owned:
        file_id = item["file_id"]
        result, text = extracted.get(file_id, (None, ""))
        if result is None:
            statuses.append({"file_id": file_id, "status": "unreadable"})
            continue

        record = {
            "file_id": file_id,
            "completeness": result.completeness,
            "pages_total": result.pages_total,
            "pages_attempted": result.pages_attempted,
            "pages_with_text": result.pages_with_text,
            "pages_failed": result.pages_failed,
            "pages_skipped": result.pages_skipped,
            "processing_coverage": result.processing_coverage,
            "text_yielding_page_ratio": result.text_yielding_page_ratio,
            "extractor_version": result.extractor_version,
            "config_version": result.config_version,
        }
        if result.limitations:
            record["limitations"] = list(result.limitations)
        if result.error_code:
            record["error_code"] = result.error_code

        stripped = (text or "").strip()
        if not stripped:
            # A format no extractor can read is NOT a failure, and calling it
            # one tells the client to re-upload something that will fail the
            # same way. Kept distinct so the six presentation states survive
            # analysis, not just the upload response.
            if item.get("analysis_support") == "storage_only" or result.error_code in (
                    "legacy_doc_format", "image_no_text_extraction"):
                record["status"] = "storage_only"
            elif result.error_code == "file_missing":
                record["status"] = "missing"
            else:
                record["status"] = "unreadable"
            record["truncated"] = False
            statuses.append(record)
            continue

        if remaining <= 0:
            # Extracted fine; omitted because the PROMPT ran out of room. A
            # different fact from "could not be read", and kept distinct so the
            # client can be told which one happened.
            record["status"] = "omitted_limit"
            record["truncated"] = True
            statuses.append(record)
            continue

        excerpt = stripped[:remaining]
        prompt_truncated = len(excerpt) < len(stripped)
        remaining -= len(excerpt)

        header = f"[file {file_id}]"
        if result.completeness != COMPLETE:
            # The warning travels INSIDE the prompt text, beside the excerpt it
            # qualifies. A note kept only in the status list would be a record
            # that the model never saw.
            header += "\n[WARNING: " + _evidence_gap_sentence(result) + "]"
        excerpts.append(header + "\n" + excerpt)

        record["status"] = (
            "readable" if result.completeness == COMPLETE else "partially_read")
        record["truncated"] = prompt_truncated
        statuses.append(record)

    # WHAT THE MODEL WAS NOT GIVEN, BY CATEGORY.
    #
    # A file that produced no text was simply skipped, so the prompt looked
    # identical to a client who never uploaded it. Listing them is not enough on
    # its own either: "not read" covers three situations with three different
    # remedies, and collapsing them tells the client to re-upload a file that
    # will always fail, or to shorten a bundle that was actually unreadable.
    #
    # Listed by id and reason only. Filenames are the client's own text and have
    # no business inside an untrusted-data block.
    blocks = list(excerpts)

    def _block(rows, heading, instruction):
        if not rows:
            return
        lines = "\n".join(
            f"- file {r['file_id']}: {_UNREAD_REASONS.get(r.get('status'), 'not read')}"
            for r in rows)
        blocks.append("[" + heading + "]\n" + lines + "\n" + instruction)

    _block(
        [s for s in statuses if s.get("status") == "omitted_limit"],
        "OMITTED FOR LENGTH — read successfully, but not shown to you",
        "These were readable. Their contents are simply absent here, so do not "
        "treat their subject matter as unevidenced.")
    _block(
        [s for s in statuses if s.get("status") == "storage_only"],
        "NOT ANALYSABLE — stored, but this format cannot be read at all",
        "Nothing is wrong with these files. Say they must be read by a person, "
        "and do not ask the client to upload the same format again.")
    _block(
        [s for s in statuses
         if s.get("status") in ("unreadable", "missing", "invalid_path")],
        "COULD NOT BE READ — extraction failed",
        "Treat the evidence as incomplete and say plainly that these could not "
        "be read.")

    # A file counted as fully read can still have been cut by the prompt budget.
    # Without this the model is told the document was read in full and shown
    # only part of it — the most confident possible version of a partial answer.
    truncated = [s for s in statuses if s.get("truncated")]
    if truncated:
        ids = ", ".join(str(s["file_id"]) for s in truncated)
        blocks.append(
            "[TRUNCATED — you were shown only the beginning of these files]\n"
            + "- " + ids + "\n"
            + "Do not state or imply that you have seen these documents in full.")

    return "\n\n".join(blocks), statuses


#: Why a file contributed nothing, in words the model can repeat to a client.
_UNREAD_REASONS = {
    "unreadable": "could not be read (no text could be extracted)",
    "missing": "is recorded but missing from storage",
    "invalid_path": "could not be located",
    "storage_only": "is stored but its format cannot be read for analysis",
    "omitted_limit": ("was read successfully but left out because the analysis "
                      "reached its length limit"),
}

def _evidence_gap_sentence(result) -> str:
    """What was not read, in words, for the analysis prompt.

    Never calls a page a scan. An image reference tells us there is something we
    cannot read, not what it is.
    """
    bits = []
    if result.pages_total and result.pages_with_text < result.pages_total:
        bits.append(
            f"{result.pages_total - result.pages_with_text} of "
            f"{result.pages_total} pages produced no text")
    if result.pages_skipped:
        bits.append(f"{result.pages_skipped} pages were not processed")
    if result.pages_failed:
        bits.append(f"{result.pages_failed} pages could not be read")
    if any(p.images_present for p in result.page_reports):
        bits.append("some pages contain images whose contents cannot be read")
    for note in result.limitations:
        if note.startswith("unsupported_part:"):
            bits.append(f"{note.split(':', 1)[1]} were not read")
    if not bits:
        bits.append("this document may not have been read in full")
    return (
        "This document was only partially read — "
        + "; ".join(bits)
        + ". Do not assume the unread parts are unimportant, and say so in your "
          "answer rather than presenting this as the complete document."
    )


async def _read_bounded(file, limit: int) -> bytes:
    """Read at most `limit` bytes, refusing anything larger.

    `await file.read()` buffered the ENTIRE body before the size check, so
    rejecting a 2 GB upload meant first holding 2 GB in memory — the check
    protected the disk and not the process. Reading a chunk past the limit is
    enough to know it is too big.
    """
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(_EVIDENCE_CHUNK)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise AppValidationError("File too large — maximum size is 10 MB")
        chunks.append(chunk)
    return b"".join(chunks)


async def upload_evidence(token: str, client_id: str, file) -> dict:
    import aiofiles

    intake = await intake_repo.find_by_token(token)
    if not intake or intake.get("client_id") != client_id:
        raise NotFoundError("Intake session")
    # A converted intake takes no more evidence. `save_step` has always refused
    # a completed intake and this did not, so a file could be attached to a
    # session whose case had already been analysed — arriving too late to be
    # part of the analysis it was uploaded for, with nothing saying so.
    if intake.get("completed"):
        raise AppValidationError(
            "This intake has already been converted to a case — upload further "
            "documents from the case page instead."
        )

    existing = list(intake.get("evidence_files") or [])
    if len(existing) >= _MAX_EVIDENCE_FILES:
        raise AppValidationError(
            f"You can attach at most {_MAX_EVIDENCE_FILES} files to one intake. "
            "Remove one before adding another."
        )

    content = await _read_bounded(file, _MAX_EVIDENCE_SIZE)

    used = sum(int(f.get("size") or 0) for f in existing)
    if used + len(content) > _MAX_EVIDENCE_TOTAL:
        raise AppValidationError(
            f"That would exceed the {_MAX_EVIDENCE_TOTAL // (1024 * 1024)} MB "
            "total for one intake. Remove a file before adding another."
        )

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
        "content_type": detected_mime,
        "size":         len(content),
        "path":         str(save_path),
    }
    # PERSISTED, not just returned. The upload response carried this and the
    # stored record did not, so the moment the page reloaded a legacy .doc or an
    # image stopped saying "stored, not analysed" and started saying "could not
    # be read" — a different and wrongly alarming claim about a file that is
    # perfectly fine.
    if detected_mime in _STORAGE_ONLY_MIMES:
        file_meta["analysis_support"] = "storage_only"
    # THE FILE IS ON DISK BEFORE THE RECORD EXISTS. If the record write fails,
    # the bytes are stored with nothing pointing at them — unreachable by the
    # client, uncounted by the quota, and invisible to any later cleanup. The
    # upload has already failed from the caller's side; leaving the file behind
    # turns that into a permanent leak, so it is removed on the way out.
    try:
        stored = await intake_repo.add_evidence_file(
            token, file_meta, _MAX_EVIDENCE_FILES, _MAX_EVIDENCE_TOTAL
        )
        if not stored:
            raise ConflictError(
                "The intake changed while this file was uploading. It may be "
                "converting, completed, or at its evidence limit. Reload and try again."
            )
    except Exception:
        try:
            save_path.unlink(missing_ok=True)
        except OSError:
            logger.exception("could not remove orphaned evidence file %s", save_path)
        raise

    result = {
        "file_id":      file_id,
        "filename":     file.filename,
        "size":         len(content),
        "content_type": detected_mime,
    }

    # LEGACY .doc IS STORED, NOT ANALYSED — and the client is told so HERE.
    #
    # Its OLE2 magic is allow-listed at upload and no extractor has ever been
    # able to read it, so it used to upload silently and the client discovered
    # at the analysis screen that it had contributed nothing. Refusing the
    # upload instead would be worse: the file is still theirs, it is still
    # evidence, and their lawyer can still open it.
    #
    # So it is kept, downloadable, and deliberately storage-only — with the
    # limitation stated at the moment of upload, which is the moment they can
    # cheaply do something about it.
    notice = _STORAGE_ONLY_NOTICES.get(detected_mime)
    if notice:
        result["analysis_support"] = "storage_only"
        result["notice"] = notice

    return result


#: Formats accepted at upload that NO extractor can read. Both were silently
#: accepted and only revealed themselves at the analysis screen, after the
#: client had finished the questionnaire — the moment they could least cheaply
#: do anything about it.
#:
#: Refusing the upload would be worse. The file is still their evidence, their
#: lawyer can still open it, and discarding it to avoid an awkward message loses
#: something real. So it is kept, downloadable, and deliberately storage-only,
#: with the limitation stated at upload.
_STORAGE_ONLY_MIMES = STORAGE_ONLY_MIMES

_STORAGE_ONLY_NOTICES = {
    "application/msword": (
        "Saved, but legacy Word (.doc) files cannot be read for analysis. "
        "Upload a .docx or PDF copy if you want its contents considered. "
        "This file stays attached and can still be downloaded."
    ),
    **{
        mime: (
            "Saved, but images cannot be read for analysis — there is no text "
            "recognition in this system. Type the key details into your "
            "description, or upload a text-based PDF. This file stays attached "
            "and can still be downloaded."
        )
        for mime in ("image/jpeg", "image/png", "image/gif", "image/webp")
    },
}


async def _find_evidence(token: str, client_id: str, file_id: str) -> tuple[dict, dict]:
    """The intake and the one evidence entry, or raise. Ownership checked here."""
    intake = await intake_repo.find_by_token(token)
    if not intake or intake.get("client_id") != client_id:
        raise NotFoundError("Intake session")
    entry = next(
        (f for f in (intake.get("evidence_files") or []) if f.get("file_id") == file_id),
        None,
    )
    if entry is None:
        raise NotFoundError("Evidence file")
    return intake, entry


async def get_evidence_file(token: str, client_id: str, file_id: str) -> tuple[Path, str, str]:
    """Resolve an uploaded file for download. Returns (path, filename, mime).

    There was no way to read an uploaded file back. A client could attach
    evidence and then never see it again, and nothing could verify that what was
    stored is what they meant to send.

    The path comes from the RECORD, never from the request, and is confined to
    the evidence directory — `file_id` reaches this function from a URL, and a
    stored path is the only thing that should decide which bytes are returned.
    """
    _, entry = await _find_evidence(token, client_id, file_id)

    stored = Path(entry.get("path") or "")
    try:
        resolved = stored.resolve()
        resolved.relative_to(_EVIDENCE_DIR.resolve())
    except (OSError, ValueError):
        # A record pointing outside the evidence root is corrupt, not a file to
        # serve. Refused rather than read.
        logger.error("evidence record %s has an out-of-tree path", file_id)
        raise NotFoundError("Evidence file")

    if not resolved.is_file():
        raise NotFoundError("Evidence file")

    # Re-sniff on read so records created before detected MIME was stored do
    # not keep serving a browser-controlled Content-Type forever.
    try:
        with resolved.open("rb") as handle:
            served_mime = detect_mime(handle.read(16))
    except OSError:
        raise NotFoundError("Evidence file")
    if served_mime not in _ALLOWED_MIME:
        served_mime = "application/octet-stream"
    return (resolved, entry.get("filename") or "evidence", served_mime)


async def delete_evidence_file(token: str, client_id: str, file_id: str) -> dict:
    """Remove an uploaded file — the record AND the bytes.

    The UI's ✕ filtered a React array and nothing else, so a removed file stayed
    on disk and in the intake for ever: the client believed it was gone, the
    quota still counted it, and the analysis still described it.

    The record goes first. A record with no file reads as a missing file and is
    recoverable; a file with no record is an invisible orphan.
    """
    intake, entry = await _find_evidence(token, client_id, file_id)
    if intake.get("completed"):
        raise AppValidationError(
            "This intake has already been converted — its evidence is part of "
            "the case record and cannot be removed here."
        )

    if not await intake_repo.remove_evidence_file(token, file_id):
        raise ConflictError(
            "The intake changed before this file could be removed. Reload and try again."
        )

    stored = Path(entry.get("path") or "")
    try:
        resolved = stored.resolve()
        resolved.relative_to(_EVIDENCE_DIR.resolve())
        resolved.unlink(missing_ok=True)
    except (OSError, ValueError):
        # The record is already gone, which is what the client asked for. A file
        # left behind is a cleanup problem, not a failed request.
        logger.warning("evidence %s unlinked from the intake but not from disk", file_id)

    return {"file_id": file_id, "deleted": True}


def _public_evidence(files: list[dict] | None,
                     extraction: list[dict] | None = None) -> list[dict]:
    """Evidence metadata a browser may see.

    `path` is dropped. It is the absolute location on the server's disk, of no
    use to the client, and handing it out discloses the upload root and the
    file-naming scheme to anyone who asks for their own intake.

    `extraction` is the per-file record produced at conversion. Merging it here
    is what lets a restored intake say "3 of 5 pages produced no text" beside
    the file it happened to, rather than leaving the client to infer it from an
    analysis that reads as though it saw everything.
    """
    by_id = {
        str(e.get("file_id")): e
        for e in (extraction or [])
        if e.get("file_id")
    }

    out = []
    for f in (files or []):
        if not f.get("file_id"):
            continue
        entry = {
            "file_id":      f.get("file_id", ""),
            "filename":     f.get("filename", ""),
            "content_type": f.get("content_type"),
            "size":         f.get("size"),
        }
        # Derived server-side and returned on EVERY read, not only in the upload
        # response. Without it a reload turned "stored, not analysed" into
        # "could not be read" — a wrongly alarming claim about a fine file.
        support = derive_analysis_support(f)
        if support:
            entry["analysis_support"] = support
            entry["notice"] = _STORAGE_ONLY_NOTICES.get(
                str(f.get("content_type") or ""))

        record = by_id.get(str(f.get("file_id")))
        if record:
            entry.update({
                "extraction_status": record.get("status"),
                "completeness":      record.get("completeness"),
                # Counters are passed through AS STORED. `None` means the
                # extractor could not determine the count, which is not zero —
                # coercing it would let "unknown" render as "0 of 5 pages had
                # text", a definite claim built from an absence.
                "pages_total":       record.get("pages_total"),
                "pages_with_text":   record.get("pages_with_text"),
                "pages_failed":      record.get("pages_failed"),
                "pages_skipped":     record.get("pages_skipped"),
                "prompt_truncated":  bool(record.get("truncated")),
                "limitations":       list(record.get("limitations") or []),
            })
        out.append(entry)
    return out


async def get_resumable_intake(client_id: str) -> dict | None:
    """The intake this client should be put back into, if any.

    WHY THIS EXISTS
    ---------------
    Resuming used to depend entirely on a token in one browser's localStorage.
    That token is cleared on sign-out, lost when site data is cleared, and
    absent on a second device — and after conversion it is the ONLY route to a
    draft case awaiting confirmation. So logging out between converting and
    confirming left a real case its owner could never confirm and the UI could
    never find: permanently orphaned, with nothing reporting it.

    The server knows which intakes are unfinished. It should be the one to say.

    WHICH ONE
    ---------
    A converted intake whose case is still a DRAFT wins over an unfinished one,
    however old. The draft is the state with something at stake — a case already
    analysed, waiting on one click — while an unfinished intake has lost only
    typing. Within each group, most recently touched first.

    An intake with nothing in it is never offered: a session that was started
    and abandoned before step 1 is indistinguishable from starting fresh, and
    resuming one would just be a confusing no-op.
    """
    # Query the two semantic states directly. A limit on "recent intakes" can
    # bury an older converted draft under abandoned sessions, despite the
    # product rule that a real draft case always wins.
    draft_ids = await case_repo.find_draft_ids_for_client(client_id)
    pending_draft = await intake_repo.find_latest_for_draft_cases(
        client_id, draft_ids
    )
    unfinished = await intake_repo.find_latest_unfinished(client_id)
    chosen = pending_draft or unfinished
    if chosen is None:
        return None
    return await get_intake(chosen["session_token"], client_id)


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
    case_type = None
    ai_case_type = intake.get("ai_case_type")
    if intake.get("case_id"):
        case = await case_repo.find_by_id(intake["case_id"])
        case_status = (case or {}).get("status")
        case_type = (case or {}).get("case_type")

    return {
        "session_token":     token,
        "current_step":      intake.get("current_step", 1),
        "completed":         intake.get("completed", False),
        "case_id":           intake.get("case_id"),
        "case_status":       case_status,
        "case_type":         case_type,
        "ai_case_type":      ai_case_type,
        "ai_structured_case": intake.get("ai_structured_case"),
        "steps":             steps,
        "clarification_qa":  list(intake.get("clarification_qa") or []),
        # The extraction record lives on the analysis, because that is the run
        # it describes. Merged in here so a refresh restores the limitations
        # alongside the files rather than burying them in the AI payload.
        "evidence_files":    _public_evidence(
            intake.get("evidence_files"),
            (intake.get("ai_structured_case") or {}).get("evidence_extraction"),
        ),
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
