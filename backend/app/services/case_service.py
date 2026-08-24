import asyncio
import logging
import secrets
from datetime import datetime, timezone

from pymongo.errors import DuplicateKeyError

from app.core.constants import CaseStatus
from app.core.exceptions import AppValidationError, ForbiddenError, NotFoundError
from app.repositories.case_repo import CaseRepository
from app.repositories.user_repo import UserRepository

logger = logging.getLogger(__name__)

case_repo = CaseRepository()
user_repo = UserRepository()


def _gen_case_number() -> str:
    return f"ATT-{datetime.now(timezone.utc).year}-{secrets.token_hex(4).upper()}"


def _public_case(case: dict | None) -> dict | None:
    """Strip internal-only fields before a case leaves the API.

    ``case_embedding`` is a ~384-dim matching vector — never for the client,
    and heavy to ship (esp. in the wholesale-cached /cases list). The response
    models use ``extra="allow"`` for pass-through, so this MUST be removed here
    or it would leak straight back out."""
    if not case:
        return case
    case = dict(case)
    case.pop("case_embedding", None)
    return case


async def _embed_case(case_id: str, description: str) -> None:
    try:
        from app.ai.pipelines.retriever import _embeddings
        emb = _embeddings()
        vector = await asyncio.to_thread(emb.embed_query, f"query: {description[:512]}")
        await case_repo.set_embedding(case_id, vector)
    except Exception:
        # Non-critical — matching falls back to MongoDB scoring — but log it so
        # a persistent embedding failure is visible, not silently swallowed.
        logger.exception("Case embedding failed for %s", case_id)


async def create_case(client_id: str, data: dict) -> dict:
    case_id = secrets.token_urlsafe(16)
    doc = {
        "_id": case_id,
        "case_number": _gen_case_number(),
        "client_id": client_id,
        "lawyer_id": None,
        "intake_id": data.get("intake_id"),
        "case_type": data["case_type"],
        "province": data["province"],
        "status": CaseStatus.OPEN.value,
        "title": data["title"],
        "description": data["description"],
        "milestones": [],
        "hearing_dates": [],
        "case_embedding": None,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }
    # Retry on case_number collision (unique index — extremely rare but handled)
    for attempt in range(5):
        doc["case_number"] = _gen_case_number()
        try:
            await case_repo.insert(doc)
            break
        except DuplicateKeyError:
            if attempt == 4:
                raise AppValidationError("Could not generate a unique case number — please try again")
            continue

    # Schedule embedding for lawyer matching (non-blocking)
    description = data.get("description", "")
    if description:
        asyncio.create_task(_embed_case(case_id, description))

    return _public_case(doc)


async def get_case(case_id: str, requester_id: str, requester_role: str) -> dict:
    case = await case_repo.find_by_id(case_id)
    if not case:
        raise NotFoundError("Case")
    _assert_access(case, requester_id, requester_role)
    case = _public_case(case)
    client = await user_repo.find_by_id(case.get("client_id", ""))
    if client:
        case["client_name"] = client.get("full_name", "")
        case["client_email"] = client.get("email", "")
    return case


async def list_cases(user_id: str, role: str, page: int, page_size: int) -> dict:
    if role == "client":
        result = await case_repo.find_by_client(user_id, page, page_size)
    elif role == "lawyer":
        result = await case_repo.find_by_lawyer(user_id, page, page_size)
    else:
        result = await case_repo.paginate({}, page, page_size)

    # Batch-fetch all client users in one query (fixes N+1)
    client_ids = list({c.get("client_id") for c in result.items if c.get("client_id")})
    client_docs = await user_repo.find_many({"_id": {"$in": client_ids}}) if client_ids else []
    client_map = {u["_id"]: u for u in client_docs}

    enriched = []
    for case in result.items:
        case = _public_case(case)
        client = client_map.get(case.get("client_id", ""))
        if client:
            case["client_name"] = client.get("full_name", "")
            case["client_email"] = client.get("email", "")
        enriched.append(case)

    return {
        "items": enriched,
        "total": result.total,
        "page": result.page,
        "page_size": result.page_size,
        "pages": result.pages,
    }


async def update_case(
    case_id: str, updates: dict, requester_id: str, requester_role: str
) -> dict:
    case = await case_repo.find_by_id(case_id)
    if not case:
        raise NotFoundError("Case")
    _assert_access(case, requester_id, requester_role)

    # Defense-in-depth: the schema already excludes them, but never allow
    # assignment/status writes through the generic PATCH.
    updates = {k: v for k, v in updates.items() if k in {"title", "description"}}
    if not updates:
        return _public_case(case)

    updates["updated_at"] = datetime.now(timezone.utc)
    await case_repo.update_one({"_id": case_id}, {"$set": updates})
    return _public_case(await case_repo.find_by_id(case_id))


async def add_milestone(case_id: str, milestone: dict, lawyer_id: str) -> dict:
    case = await case_repo.find_by_id(case_id)
    if not case:
        raise NotFoundError("Case")
    if case.get("lawyer_id") != lawyer_id:
        raise ForbiddenError("Only the assigned lawyer can add milestones")

    milestone["completed"] = False
    milestone["completed_at"] = None
    await case_repo.add_milestone(case_id, milestone)
    return _public_case(await case_repo.find_by_id(case_id))


async def add_hearing(case_id: str, hearing: dict, lawyer_id: str) -> dict:
    case = await case_repo.find_by_id(case_id)
    if not case:
        raise NotFoundError("Case")
    if case.get("lawyer_id") != lawyer_id:
        raise ForbiddenError("Only the assigned lawyer can schedule hearings")

    hearing["_id"] = secrets.token_urlsafe(8)
    hearing["created_at"] = datetime.now(timezone.utc)
    await case_repo.add_hearing(case_id, hearing)

    # Tell the client — hearing dates are the #1 thing clients ask about
    try:
        from app.core.constants import NotificationType
        from app.services import notification_service
        date_str = hearing["date"].strftime("%d %b %Y") if hasattr(hearing.get("date"), "strftime") else str(hearing.get("date", ""))[:10]
        await notification_service.create_notification(
            case["client_id"],
            NotificationType.HEARING_SCHEDULED,
            "Hearing scheduled",
            f"{case.get('title', 'Your case')}: hearing on {date_str}"
            + (f" at {hearing['court']}" if hearing.get("court") else ""),
            payload={"case_id": case_id, "hearing_id": hearing["_id"]},
        )
    except Exception:
        pass  # notification failure must not block scheduling

    return _public_case(await case_repo.find_by_id(case_id))


# ── Peshi tracker: structured hearing outcomes ────────────────────────────────
# Deterministic plain-language explanations — no LLM in this path.
HEARING_OUTCOMES = {
    "adjourned": {
        "label": "Adjourned (new date given)",
        "meaning": "The hearing was postponed — nothing was decided today. This is very common and does not hurt your case. Note the next date below.",
        "meaning_ur": "سماعت ملتوی ہو گئی — آج کوئی فیصلہ نہیں ہوا۔ یہ بہت عام بات ہے اور اس سے آپ کے کیس کو نقصان نہیں پہنچتا۔ اگلی تاریخ نوٹ کر لیں۔",
    },
    "arguments_heard": {
        "label": "Arguments heard",
        "meaning": "Your lawyer (or the other side) presented arguments before the judge. The case moved forward today.",
        "meaning_ur": "آپ کے وکیل یا مخالف فریق نے جج کے سامنے دلائل پیش کیے۔ آج کیس آگے بڑھا۔",
    },
    "evidence_recorded": {
        "label": "Evidence / witness recorded",
        "meaning": "Evidence was presented or a witness testified. This is real progress — recorded evidence becomes part of the case file.",
        "meaning_ur": "شہادت پیش کی گئی یا گواہ کا بیان ریکارڈ ہوا۔ یہ حقیقی پیش رفت ہے — ریکارڈ شدہ شہادت کیس فائل کا حصہ بن جاتی ہے۔",
    },
    "order_reserved": {
        "label": "Order / judgment reserved",
        "meaning": "The judge has heard both sides and will announce the decision on a later date. No more arguments are needed on this point.",
        "meaning_ur": "جج نے دونوں فریقوں کو سن لیا ہے اور فیصلہ بعد میں سنائیں گے۔ اس نکتے پر مزید دلائل کی ضرورت نہیں۔",
    },
    "decided": {
        "label": "Decided / order announced",
        "meaning": "The court announced its decision today. Ask your lawyer for a copy of the order and what it means for the next steps.",
        "meaning_ur": "عدالت نے آج فیصلہ سنا دیا۔ اپنے وکیل سے حکم نامے کی کاپی اور اگلے اقدامات کے بارے میں پوچھیں۔",
    },
    "judge_on_leave": {
        "label": "Judge on leave / bench not available",
        "meaning": "The judge was not available, so nothing happened today. A new date has been set. This is routine and not your lawyer's fault.",
        "meaning_ur": "جج دستیاب نہیں تھے، اس لیے آج کچھ نہیں ہوا۔ نئی تاریخ مقرر کر دی گئی ہے۔ یہ معمول کی بات ہے۔",
    },
    "other": {
        "label": "Other",
        "meaning": "See your lawyer's note below for what happened at this hearing.",
        "meaning_ur": "اس سماعت میں کیا ہوا، اس کے لیے نیچے اپنے وکیل کا نوٹ دیکھیں۔",
    },
}


async def record_hearing_outcome(
    case_id: str, hearing_id: str, data: dict, lawyer_id: str
) -> dict:
    """Lawyer records what happened at a hearing; client is notified in plain language."""
    case = await case_repo.find_by_id(case_id)
    if not case:
        raise NotFoundError("Case")
    if case.get("lawyer_id") != lawyer_id:
        raise ForbiddenError("Only the assigned lawyer can record hearing outcomes")

    outcome_key = data["outcome"]
    info = HEARING_OUTCOMES.get(outcome_key)
    if not info:
        raise AppValidationError(f"outcome must be one of {sorted(HEARING_OUTCOMES)}")

    fields = {
        "outcome":             outcome_key,
        "outcome_label":       info["label"],
        "outcome_note":        data.get("note") or "",
        "outcome_meaning":     info["meaning"],
        "outcome_meaning_ur":  info["meaning_ur"],
        "outcome_recorded_at": datetime.now(timezone.utc),
    }
    updated = await case_repo.update_hearing(case_id, hearing_id, fields)
    if not updated:
        raise NotFoundError("Hearing")

    # Auto-schedule the next hearing if a next date was given
    next_hearing = None
    if data.get("next_date"):
        prev = next((h for h in case.get("hearing_dates", []) if h.get("_id") == hearing_id), {})
        next_hearing = {
            "_id":        secrets.token_urlsafe(8),
            "date":       data["next_date"],
            "court":      prev.get("court", ""),
            "judge":      prev.get("judge"),
            "purpose":    data.get("next_purpose") or "Next hearing",
            "time":       data.get("next_time"),
            "notes":      None,
            "outcome":    None,
            "created_at": datetime.now(timezone.utc),
        }
        await case_repo.add_hearing(case_id, next_hearing)

    # Plain-language update to the client
    try:
        from app.core.constants import NotificationType
        from app.services import notification_service
        body = f"{case.get('title', 'Your case')}: {info['label']}."
        if data.get("note"):
            body += f" Lawyer's note: {data['note']}"
        if next_hearing is not None:
            d = next_hearing["date"]
            date_str = d.strftime("%d %b %Y") if hasattr(d, "strftime") else str(d)[:10]
            body += f" Next date: {date_str}."
        await notification_service.create_notification(
            case["client_id"],
            NotificationType.CASE_UPDATE,
            "Hearing update",
            body,
            payload={"case_id": case_id, "hearing_id": hearing_id, "outcome": outcome_key},
        )
    except Exception:
        pass

    return _public_case(await case_repo.find_by_id(case_id))


async def send_message(
    case_id: str, sender_id: str, sender_role: str, sender_name: str, text: str
) -> dict:
    case = await case_repo.find_by_id(case_id)
    if not case:
        raise NotFoundError("Case")
    _assert_access(case, sender_id, sender_role)
    msg = {
        "_id": secrets.token_urlsafe(8),
        "sender_id": sender_id,
        "sender_role": sender_role,
        "sender_name": sender_name,
        "text": text,
        "created_at": datetime.now(timezone.utc),
    }
    await case_repo.add_message(case_id, msg)

    # Tell the other side. Without this the message is stored and surfaced only
    # if they happen to reopen the case — so a lawyer asking for a document, or
    # a client answering, could sit unread indefinitely while both parties
    # believed the ball was in the other's court.
    #
    # Best-effort, like every other notify in this file: a notification failure
    # must never lose a message that has already been written.
    try:
        from app.core.constants import NotificationType
        from app.services import notification_service

        recipient = (
            case.get("lawyer_id")
            if sender_id == case.get("client_id")
            else case.get("client_id")
        )
        # No lawyer engaged yet (or a malformed case) — nobody to tell.
        if recipient and recipient != sender_id:
            preview = text.strip().replace("\n", " ")
            if len(preview) > 140:
                preview = preview[:139] + "…"
            await notification_service.create_notification(
                recipient,
                NotificationType.CASE_MESSAGE,
                f"New message from {sender_name}",
                # The preview carries the message itself, so an urgent request
                # ("send me the fard before Thursday") is legible without
                # opening the app.
                f"{case.get('title', 'Your case')}: {preview}",
                payload={"case_id": case_id, "message_id": msg["_id"],
                         "sender_role": sender_role},
            )
    except Exception:
        logger.exception("case message notification failed for case %s", case_id)

    return msg


async def list_messages(case_id: str, requester_id: str, requester_role: str) -> list:
    case = await case_repo.find_by_id(case_id)
    if not case:
        raise NotFoundError("Case")
    _assert_access(case, requester_id, requester_role)
    return list(case.get("messages", []))


async def add_task(case_id: str, task_data: dict, lawyer_id: str) -> dict:
    case = await case_repo.find_by_id(case_id)
    if not case:
        raise NotFoundError("Case")
    if case.get("lawyer_id") != lawyer_id:
        raise ForbiddenError("Only the assigned lawyer can add tasks")
    task = {
        "_id": secrets.token_urlsafe(8),
        "title": task_data["title"],
        "due": task_data.get("due"),
        "priority": task_data.get("priority", "medium"),
        "description": task_data.get("description"),
        "done": False,
        "completed_at": None,
        "created_at": datetime.now(timezone.utc),
    }
    await case_repo.add_task(case_id, task)
    return task


async def list_tasks(case_id: str, requester_id: str, requester_role: str) -> list:
    case = await case_repo.find_by_id(case_id)
    if not case:
        raise NotFoundError("Case")
    _assert_access(case, requester_id, requester_role)
    return list(case.get("tasks", []))


async def toggle_task(case_id: str, task_id: str, done: bool, lawyer_id: str) -> dict:
    case = await case_repo.find_by_id(case_id)
    if not case:
        raise NotFoundError("Case")
    if case.get("lawyer_id") != lawyer_id:
        raise ForbiddenError("Only the assigned lawyer can update tasks")
    await case_repo.toggle_task(case_id, task_id, done)
    return _public_case(await case_repo.find_by_id(case_id))


def _assert_access(case: dict, user_id: str, role: str) -> None:
    if role == "admin":
        return
    if role == "client" and case.get("client_id") == user_id:
        return
    if role == "lawyer" and case.get("lawyer_id") == user_id:
        return
    raise ForbiddenError("Access denied to this case")
