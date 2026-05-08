import asyncio
import json
import secrets
from datetime import datetime

from app.core.exceptions import AppValidationError, NotFoundError
from app.repositories.intake_repo import IntakeRepository
from app.repositories.case_repo import CaseRepository
from app.services.case_service import create_case

intake_repo = IntakeRepository()
case_repo   = CaseRepository()

_MAX_CLARIFY_ROUNDS = 4

STEP_REQUIRED_FIELDS = {
    1: ["province"],
    2: ["case_type", "urgency"],
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

Based on the context below, decide if any CRITICAL fact is still missing.
If all key facts are present, respond with exactly: DONE

Otherwise, ask the ONE most important missing question using the domain templates as a guide.
Ask in the same language the user used (English or Urdu). No explanations — just the question."""


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
        },
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
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

    qa_list   = list(intake.get("clarification_qa") or [])
    step2     = intake.get("step2") or {}
    step3     = intake.get("step3") or {}
    case_type = step2.get("case_type", "civil")
    province  = (intake.get("step1") or {}).get("province", "federal")
    desc      = step3.get("incident_description", "")

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
        response = llm.invoke([
            {"role": "system", "content": _CLARIFY_SYSTEM},
            {"role": "user",   "content": user_msg},
        ])
        text = response.content.strip()
    except Exception:
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

    # Enrich description with clarification Q&A if present
    description = step3.get("incident_description", "")
    qa_list     = intake.get("clarification_qa") or []
    answered    = [qa for qa in qa_list if qa.get("a")]
    if answered:
        qa_text = "\n".join(f"Q: {qa['q']}\nA: {qa['a']}" for qa in answered)
        description = f"{description}\n\nAdditional context from intake:\n{qa_text}"

    case_data = {
        "case_type":   step2.get("case_type"),
        "province":    step1.get("province"),
        "title":       description[:80],
        "description": description,
        "intake_id":   intake["_id"],
    }
    case = await create_case(client_id, case_data)
    case_id = case["_id"]

    # P1 — generate 768-dim case embedding (non-blocking)
    asyncio.create_task(_embed_case(case_id, description))

    # Use frontend-provided urgency if given; fall back to what the user stored in step 2
    effective_urgency = urgency or step2.get("urgency", "medium")

    # Run AI structured analysis
    ai_data = await _run_intake_ai(
        query=description,
        case_type=step2.get("case_type", "civil"),
        province=step1.get("province", "federal"),
        session_id=token,
        case_id=case_id,
        language=language,
        urgency=effective_urgency,
    )
    await intake_repo.save_ai_structured_case(token, ai_data)

    # P5 — auto-match top 5 lawyers (non-blocking, best-effort)
    asyncio.create_task(_auto_match_lawyers(case_id))

    await intake_repo.mark_completed(token, case_id)
    return {"session_token": token, "current_step": 5, "completed": True, "case_id": case_id}


async def _embed_case(case_id: str, description: str) -> None:
    """P1 — embed case description and store in MongoDB."""
    try:
        from app.ai.pipelines.retriever import _embeddings
        emb_model = _embeddings()
        # "query: " prefix for multilingual-e5 query-side embedding
        vector = await asyncio.to_thread(
            emb_model.embed_query, f"query: {description[:512]}"
        )
        await case_repo.set_embedding(case_id, vector)
    except Exception:
        pass  # non-critical — matching falls back to MongoDB scoring


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
        "language":               language,
        "needs_clarification":    False,
        "clarification_question": "",
        "retrieved_chunks":       [],
        "reranked_chunks":        [],
        "relevance_score":        1.0,
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
        return json.loads(result["answer"])
    except Exception:
        return {
            "summary":             "AI structuring unavailable — case created successfully.",
            "applicable_laws":     [],
            "recommended_actions": ["Consult a qualified Pakistani lawyer for advice."],
            "risk_level":          "medium",
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
    missing  = [f for f in required if not data.get(f)]
    if missing:
        raise AppValidationError(f"Missing required fields for step {step}: {missing}")
