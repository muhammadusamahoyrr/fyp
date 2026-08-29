import asyncio
import json
import secrets
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import settings
from app.core.exceptions import AppValidationError, NotFoundError
from app.repositories.intake_repo import IntakeRepository
from app.repositories.case_repo import CaseRepository
from app.services.case_service import create_case
from app.utils.file_handler import detect_mime, ext_for_mime

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

    _validate_step(step, data)
    await intake_repo.update_step(token, step, data)

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
    from app.ai.llm import get_llm

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
        llm      = get_llm()
        response = await asyncio.to_thread(llm.invoke, [
            {"role": "system", "content": _CLARIFY_SYSTEM},
            {"role": "user",   "content": user_msg},
        ])
        text = response.content.strip()
    except Exception:
        # LLM failed — let user proceed rather than trapping them in a loop
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
            llm = get_fast_llm()
            response = await asyncio.to_thread(llm.invoke, [
                {"role": "system", "content": _TYPE_CLASSIFY_SYSTEM},
                {"role": "user",   "content": description[:1200]},
            ])
            ai_type = response.content.strip().lower().split()[0]
            if ai_type not in _VALID_CASE_TYPES:
                ai_type = user_selected  # LLM gave unexpected output — trust user
        except Exception:
            ai_type = user_selected  # LLM failed — trust user

    was_corrected = ai_type != user_selected
    return ai_type, was_corrected


# ─── Convert + P1 (embedding) + P5 (auto-match) ──────────────────────────────

async def convert_to_case(
    token: str,
    client_id: str,
    language: str = "en",
    urgency: str | None = None,
) -> dict:
    intake = await intake_repo.find_by_token(token)
    if not intake or intake.get("client_id") != client_id:
        raise NotFoundError("Intake session")
    if intake.get("completed"):
        raise AppValidationError("Intake already converted to a case")

    missing = [i for i in range(1, 6) if intake.get(f"step{i}") is None]
    if missing:
        raise AppValidationError(f"Steps not completed: {missing}")

    step1 = intake.get("step1", {})
    step2 = intake.get("step2", {})
    step3 = intake.get("step3", {})

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
    if answered:
        qa_text     = "\n".join(f"Q: {qa['q']}\nA: {qa['a']}" for qa in answered)
        description = f"{base_description}\n\nAdditional context from intake:\n{qa_text}"
    else:
        description = base_description

    case_data = {
        "case_type":            ai_case_type,          # AI-verified, not raw user pick
        "user_selected_type":   user_case_type,        # keep original for audit
        "type_was_corrected":   type_corrected,
        "province":             step1.get("province"),
        "title":                description[:80],
        "description":          description,
        "intake_id":            intake["_id"],
    }
    case = await create_case(client_id, case_data)
    case_id = case["_id"]
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

    # P5 — auto-match top 5 lawyers (non-blocking, best-effort)
    asyncio.create_task(_auto_match_lawyers(case_id))

    await intake_repo.mark_completed(token, case_id)
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

    try:
        result = await intake_graph.ainvoke(state)
        analysis = json.loads(result["answer"])
        # The grounding verdict was computed and then dropped on the floor here:
        # this read only `answer`, so even a correct "not grounded" never left
        # the graph. Carried through now, with the status that says WHICH of
        # verified / unverified / unchecked actually happened.
        analysis["grounded"] = bool(result.get("is_grounded"))
        analysis["grounding_status"] = result.get("grounding_status") or "unverified"
        return analysis
    except Exception:
        return {
            "summary":             "AI structuring unavailable — case created successfully.",
            "applicable_laws":     [],
            "recommended_actions": ["Consult a qualified Pakistani lawyer for advice."],
            "risk_level":          "medium",
            "grounded":            False,
            "grounding_status":    "pipeline_failed",
        }


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


async def get_intake(token: str, client_id: str) -> dict:
    intake = await intake_repo.find_by_token(token)
    if not intake or intake.get("client_id") != client_id:
        raise NotFoundError("Intake session")
    return {
        "session_token":     token,
        "current_step":      intake.get("current_step", 1),
        "completed":         intake.get("completed", False),
        "case_id":           intake.get("case_id"),
        "ai_structured_case": intake.get("ai_structured_case"),
    }


def _validate_step(step: int, data: dict) -> None:
    required = STEP_REQUIRED_FIELDS.get(step, [])
    missing  = [f for f in required if not str(data.get(f, "")).strip()]
    if missing:
        raise AppValidationError(f"Missing required fields for step {step}: {missing}")
