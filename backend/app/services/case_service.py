import logging
import secrets
from datetime import datetime, timezone

from pymongo.errors import DuplicateKeyError

from app.core.constants import CaseStatus
from app.core.pkt import pkt_date, pkt_day_start_utc, pkt_today
from app.core.exceptions import (
    AppValidationError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
)
from app.repositories.case_repo import CaseRepository
from app.repositories.user_repo import UserRepository

logger = logging.getLogger(__name__)

case_repo = CaseRepository()
user_repo = UserRepository()


def _hearing_fingerprint(hearing: dict) -> str:
    """The details a hearing request id is bound to, canonicalised.

    Dates are compared as UTC instants (the stored value comes back naive,
    the request's may carry an offset), and absent and empty are the same.
    """
    import hashlib
    import json

    d = hearing.get("date")
    if isinstance(d, datetime):
        d = (d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d.astimezone(timezone.utc)).isoformat()
    canon = {"date": d, **{k: (hearing.get(k) or None) for k in ("court", "judge", "notes", "purpose", "time")}}
    return hashlib.sha256(json.dumps(canon, sort_keys=True, default=str).encode()).hexdigest()


class _NoClient(Exception):
    """Internal: skip a client notice on a case with no client account."""


def _gen_case_number() -> str:
    return f"ATT-{datetime.now(timezone.utc).year}-{secrets.token_hex(4).upper()}"


def _public_case(case: dict | None) -> dict | None:
    """Strip internal-only fields before a case leaves the API.

    ``case_embedding`` is no longer written — nothing ever read it, so both the
    field and the embedding that produced it are gone (see the removal note on
    ``create_case``). This strip stays for the cases ALREADY carrying one: the
    response models use ``extra="allow"`` for pass-through, so without it a
    legacy document would ship its vector straight back out, and it is heavy in
    the wholesale-cached /cases list. Safe to delete once the field has been
    unset from the collection."""
    if not case:
        return case
    case = dict(case)
    # Messages and tasks are served by their own routes, which apply who-may-
    # see-what. Inline on the case they reached every reader: a client got the
    # lawyer's private tasks, and a newly engaged lawyer got the previous
    # lawyer's whole conversation.
    case.pop("messages", None)
    case.pop("tasks", None)
    case.pop("case_embedding", None)
    case.pop("intake_conversion_owner", None)
    case.pop("intake_conversion_epoch", None)
    return case


def _is_intake_collision(exc: DuplicateKeyError) -> bool:
    """Did this duplicate come from `uniq_case_per_intake`?

    Read off the index NAME where the driver reports it, and fall back to the
    key pattern. Matching on the error message text would break the first time
    MongoDB rephrased it, and the consequence of guessing wrong here is a
    misleading instruction to a client who cannot act on it either way.
    """
    details = getattr(exc, "details", None) or {}
    if "uniq_case_per_intake" in str(details.get("errmsg", "")):
        return True
    return "intake_id" in (details.get("keyPattern") or {})


async def create_walk_in_case(lawyer_id: str, data: dict) -> dict:
    """A case the lawyer opens for a client who has no account here.

    Owned by the lawyer from the start (`lawyer_id`), with no `client_id`: the
    client's name and phone are stored on the case as plain record fields.
    IN_PROGRESS, because the lawyer has already taken it. No engagement exists
    (there is nobody to agree terms with), so fee requests are not possible on
    it, and no notification is ever addressed to a client.
    """
    now = datetime.now(timezone.utc)
    doc = {
        "_id": secrets.token_urlsafe(16),
        "client_id": None,
        "lawyer_id": lawyer_id,
        "walk_in": True,
        "client_name": data["client_name"],
        "client_phone": data.get("client_phone") or None,
        "court": data.get("court") or None,
        "court_case_number": data.get("court_case_number") or None,
        "case_type": data["case_type"],
        "province": data["province"],
        "status": CaseStatus.IN_PROGRESS.value,
        "title": data["title"],
        "description": data.get("description") or "",
        "milestones": [],
        "hearing_dates": [],
        "created_at": now,
        "updated_at": now,
    }
    for _ in range(5):
        doc["case_number"] = _gen_case_number()
        try:
            await case_repo.insert(doc)
            break
        except DuplicateKeyError:
            continue
    else:
        raise ConflictError("Could not create the case. Please try again.")
    return _public_case(doc)


async def create_case(client_id: str, data: dict,
                      status: str = CaseStatus.OPEN.value) -> dict:
    """Open a case. `status` lets intake create it as a DRAFT.

    Intake needs a real `case_id` before the client has confirmed anything —
    the analysis pipeline is bound to one, and provenance records it — so the
    case has to exist early. It previously existed as OPEN, which meant the
    client was told to "review and confirm" a case that was already live, and
    the confirm button had nothing left to do.

    A draft is a case that exists for the analysis and for nothing else. See
    `assert_not_draft` for the boundary.
    """
    case_id = secrets.token_urlsafe(16)
    doc = {
        "_id": case_id,
        "case_number": _gen_case_number(),
        "client_id": client_id,
        "lawyer_id": None,
        "intake_id": data.get("intake_id"),
        "case_type": data["case_type"],
        "province": data["province"],
        "status": status,
        "title": data["title"],
        "description": data["description"],
        "milestones": [],
        "hearing_dates": [],
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }

    # Optional intake-derived fields, copied only when the caller supplied
    # them. This used to be a closed literal, so `user_selected_type` and
    # `type_was_corrected` — which intake conversion has always passed, and
    # whose whole purpose is auditing an AI reclassification — were built and
    # then dropped on the floor here. Anything not in this list is still
    # ignored, so a caller cannot inject arbitrary keys onto a case.
    for field in (
        "user_selected_type",
        "type_was_corrected",
        "party_role",
        "desired_outcome",
        "urgency",
        "has_evidence",
        "evidence_count",
        "intake_conversion_owner",
        "intake_conversion_epoch",
    ):
        if field in data:
            doc[field] = data[field]
    # Retry on case_number collision (unique index — extremely rare but handled).
    #
    # The retry is for `case_number` ONLY. `uniq_case_per_intake` can also raise
    # DuplicateKeyError here, and a new case number does nothing about that — so
    # a caller hitting it burned five attempts and was told "could not generate a
    # unique case number, please try again", which is both false and an
    # instruction to repeat something that cannot succeed. The two collisions
    # mean opposite things: one is bad luck, the other is "this intake already
    # has a case, go and find it".
    for attempt in range(5):
        doc["case_number"] = _gen_case_number()
        try:
            await case_repo.insert(doc)
            break
        except DuplicateKeyError as exc:
            if _is_intake_collision(exc):
                raise ConflictError(
                    "This intake has already produced a case. Reload the page to "
                    "continue with it."
                ) from exc
            if attempt == 4:
                raise AppValidationError("Could not generate a unique case number — please try again")
            continue

    # No case embedding is computed here any more.
    #
    # `_embed_case` ran a CPU-bound e5 inference on every case creation — on a
    # machine with no GPU — to store a 384-dim vector of the client's own
    # description on the case. Nothing ever read it: `match_lawyers_for_case`
    # embeds the description fresh at query time through
    # `query_similar_lawyers`, and the 384 dimensions date the field to the
    # pre-Chroma design (matching runs on 768-dim e5). So it cost work at
    # creation and retained a derived representation of the client's account of
    # their problem, indefinitely, for no feature.

    return _public_case(doc)



# ── Draft cases ──────────────────────────────────────────────────────────────
#
# A draft exists so the intake analysis has a real `case_id` to run against and
# to record in provenance. It is NOT a case anyone else may act on: no lawyer
# may be asked for it, no match may be computed from it, nothing may be booked
# against it. Those are three separate call sites, so the rule lives in one
# function rather than as three copies that drift.


def is_draft(case: dict | None) -> bool:
    return bool(case) and case.get("status") == CaseStatus.DRAFT.value


def assert_not_draft(case: dict | None, action: str) -> None:
    """Refuse an action on a case the client has not confirmed yet.

    The message names what the client has to do, because they CAN fix this —
    unlike most 422s, the remedy is one button away on a screen they were just
    looking at.
    """
    if is_draft(case):
        raise AppValidationError(
            f"This case is still a draft, so it cannot {action} yet. "
            "Confirm it at the end of the intake first."
        )


async def confirm_case(
    case_id: str,
    client_id: str,
    case_type: str | None = None,
) -> dict:
    """Promote a draft to open. The client's confirmation, made real.

    ATOMIC AND IDEMPOTENT, in that order.

    Atomic because the conditional update is what decides: two clicks race
    here, and only the one that finds the case still `draft` performs the
    transition. Idempotent because the loser — and every later retry — must not
    be an error: the client pressed a button twice, and the outcome they asked
    for has happened.

    Scoped to the owner in the same filter as the status, so an authorization
    check cannot pass while the write lands on someone else's case.
    """
    case = await case_repo.find_by_id(case_id)
    if not case:
        raise NotFoundError("Case")
    if case.get("client_id") != client_id:
        raise ForbiddenError("Case does not belong to you")

    if case.get("status") == CaseStatus.OPEN.value:
        # A same-payload retry is idempotent. A different category is a new
        # edit and must not be smuggled through a replayed confirmation.
        if case_type is not None and case_type != case.get("case_type"):
            raise ConflictError(
                "This case is already confirmed with a different category."
            )
        return _public_case(case)

    if not is_draft(case):
        # Closed, dismissed, in progress — a draft is the ONLY thing that may
        # become open this way, and naming the current state says why.
        raise AppValidationError(
            f"Only a draft case can be confirmed — this one is "
            f"'{case.get('status')}'."
        )

    now = datetime.now(timezone.utc)
    updates = {
        "status": CaseStatus.OPEN.value,
        "confirmed_at": now,
        "updated_at": now,
    }
    if case_type is not None:
        updates.update({
            "case_type": case_type,
            "case_type_source": "client",
            "case_type_changed_by": client_id,
            "case_type_changed_at": now,
        })

    promoted = await case_repo.update_one(
        {"_id": case_id, "client_id": client_id,
         "status": CaseStatus.DRAFT.value},
        {"$set": updates},
    )
    if not promoted:
        # Lost the race to a concurrent press. Whatever it achieved is the
        # answer only when it achieved the SAME requested state. Two tabs can
        # submit different category choices at once; silently returning the
        # winner to the loser would tell both callers their own choice was
        # accepted. Re-read and apply the same payload check as the ordinary
        # already-open replay path.
        current = await case_repo.find_by_id(case_id)
        if not current:
            raise NotFoundError("Case")
        if case_type is not None and case_type != current.get("case_type"):
            raise ConflictError(
                "This case was concurrently confirmed with a different category."
            )
        return _public_case(current)

    # MATCHING IS NOT RUN HERE, and `matched_lawyers` is no longer written.
    #
    # Confirmation used to schedule a full semantic match — an embedding pass and
    # a vector query, CPU-bound on a deployment with no GPU — and cache the
    # result on the case. Nothing ever read that field. Every surface that shows
    # matched lawyers calls `lawyer_service.match_lawyers_for_case` for itself:
    # `/lawyers/match` (ModLawyers) and the chat socket, each from its own
    # request. So the cost was paid on every confirmation to populate a column
    # with no reader, and it was about to be paid again on every category change
    # to keep that column correct.
    #
    # Matching is a QUERY, answered when someone asks. The same reasoning that
    # removed `case_embedding` from `create_case`: derived data with no reader is
    # cost and staleness, not a feature.
    logger.info("case %s confirmed by client %s", case_id, client_id)
    return _public_case(await case_repo.find_by_id(case_id))


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


async def list_cases(user_id: str, role: str, page: int, page_size: int,
                     status: str | None = None) -> dict:
    """The caller's cases, optionally narrowed to one status.

    The status filter is applied INSIDE the caller's scope (client_id /
    lawyer_id), never instead of it, so it cannot widen what anyone sees.
    `total` then answers "how many of my cases have this status" exactly —
    which is what the lawyer dashboard needs, without downloading the list.
    """
    if role == "client":
        result = await case_repo.find_by_client(user_id, page, page_size, status=status)
    elif role == "lawyer":
        result = await case_repo.find_by_lawyer(user_id, page, page_size, status=status)
    else:
        result = await case_repo.paginate({"status": status} if status else {}, page, page_size)

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
    # A closed or dismissed case is a record: no field changes, from anyone.
    _assert_open(case)

    # Defense-in-depth: the schema already excludes them, but never allow
    # assignment/status writes through the generic PATCH.
    updates = {k: v for k, v in updates.items() if k in {"title", "description", "case_type"}}
    if not updates:
        return _public_case(case)

    # A category change overrides the pipeline's verified classification, so
    # it is recorded rather than silently applied. Without this the AI's
    # answer would be overwritten in place and the case would claim a
    # classification the pipeline never made.
    new_type = updates.get("case_type")
    if new_type is not None and new_type != case.get("case_type"):
        # Once a lawyer is working the case, the type is theirs to correct:
        # the client changing it underneath them would re-label a matter the
        # lawyer has already scoped. Title and description stay editable.
        if requester_role == "client" and case.get("lawyer_id"):
            raise ConflictError(
                "The case type can't be changed while a lawyer is working on the case. "
                "Ask your lawyer to change it.")
        # Who actually made the change (it was always recorded as the client).
        updates["case_type_source"]     = requester_role
        updates["case_type_changed_by"] = requester_id
        updates["case_type_changed_at"] = datetime.now(timezone.utc)
        # Only on the FIRST override. `ai_case_type` means "what the pipeline
        # decided", so a second change must not record the first change as the
        # machine's answer — checked against the stored case, not against this
        # update, which never contains the key.
        if "ai_case_type" not in case:
            updates["ai_case_type"] = case.get("case_type")

    updates["updated_at"] = datetime.now(timezone.utc)

    # No cached matches to invalidate any more.
    #
    # A category change used to leave `matched_lawyers` holding results computed
    # for the category the client had just rejected, so this cleared and rebuilt
    # it. Nothing read that field, so both the staleness and the rebuild were
    # work in service of a column with no reader — matching is computed live on
    # request, where it always sees the current category by construction.
    await case_repo.update_one({"_id": case_id}, {"$set": updates})
    return _public_case(await case_repo.find_by_id(case_id))


async def add_milestone(case_id: str, milestone: dict, lawyer_id: str) -> dict:
    case = await case_repo.find_by_id(case_id)
    if not case:
        raise NotFoundError("Case")
    if case.get("lawyer_id") != lawyer_id:
        raise ForbiddenError("Only the assigned lawyer can add milestones")
    _assert_open(case)

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
    _assert_open(case)

    hearing["_id"] = secrets.token_urlsafe(8)
    hearing["created_at"] = datetime.now(timezone.utc)
    rid = hearing.get("request_id") or None
    if rid:
        hearing["request_fingerprint"] = _hearing_fingerprint(hearing)
    else:
        hearing.pop("request_id", None)       # never store a null id
    if not await case_repo.add_hearing_once(case_id, hearing):
        # Not added. With a known request id this is a repeat (double click,
        # retry after a lost reply): return the hearing created the first time.
        # The same id for DIFFERENT details is a client bug, not a retry.
        current = await case_repo.find_by_id(case_id)
        if current:
            _assert_open(current)             # closed since it was read
        existing = next((h for h in (current or {}).get("hearing_dates") or []
                         if rid and h.get("request_id") == rid), None)
        if existing is None:
            raise NotFoundError("Case")
        if existing.get("request_fingerprint") != hearing.get("request_fingerprint"):
            raise ConflictError("This request was already used for a different hearing. Reload and try again.")
        case, hearing = current, existing
        # Fall through: make sure the notice exists. Its event id is the
        # hearing's, so this is a no-op when the first attempt already sent it,
        # and restores it when that attempt failed after the write.

    # Tell the client — hearing dates are the #1 thing clients ask about.
    # A walk-in case has no client account: nobody to notify.
    try:
        if not case.get("client_id"):
            raise _NoClient()
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
            # One notice per hearing, however often the request is repeated.
            logical_event_id=f"hearing-scheduled:{case_id}:{hearing['_id']}",
        )
    except _NoClient:
        pass
    except Exception:
        # Must not block scheduling, but must not vanish either: the client
        # was not told about a hearing, and that needs to be findable.
        logger.exception("hearing-scheduled notification failed for case %s", case_id)

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
    _assert_open(case)

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
    # The next hearing, if a next date was given, is written TOGETHER with
    # the outcome (one atomic write), never as a second step.
    next_hearing = None
    if data.get("next_date"):
        prev = next((h for h in case.get("hearing_dates", []) if h.get("_id") == hearing_id), {})
        next_hearing = {
            "_id":        secrets.token_urlsafe(8),
            "request_id": f"next-{hearing_id}",
            "date":       data["next_date"],
            "court":      prev.get("court", ""),
            "judge":      prev.get("judge"),
            "purpose":    data.get("next_purpose") or "Next hearing",
            "time":       data.get("next_time"),
            "notes":      None,
            "outcome":    None,
            "created_at": datetime.now(timezone.utc),
        }

    if not await case_repo.record_outcome_once(case_id, hearing_id, fields, next_hearing):
        # Nothing written. Either the hearing does not exist, or it already has
        # an outcome (another tab, a retry after a lost reply, or a concurrent
        # request that won). The recorded one is never overwritten, and no
        # next hearing or notice follows.
        current = await case_repo.find_by_id(case_id)
        if current:
            _assert_open(current)             # closed since it was read
        h = next((x for x in (current or {}).get("hearing_dates") or [] if x.get("_id") == hearing_id), None)
        if h is None:
            raise NotFoundError("Hearing")
        raise ConflictError("An outcome is already recorded for this hearing.")

    # Plain-language update to the client (none on a walk-in case)
    try:
        if not case.get("client_id"):
            raise _NoClient()
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
            logical_event_id=f"hearing-outcome:{case_id}:{hearing_id}",
        )
    except _NoClient:
        pass
    except Exception:
        logger.exception("hearing-outcome notification failed for case %s", case_id)

    return _public_case(await case_repo.find_by_id(case_id))


async def reschedule_hearing(
    case_id: str, hearing_id: str, data: dict, lawyer_id: str
) -> dict:
    """Move an upcoming hearing to a new date; the client is told.

    Only a hearing with no outcome can move: once an outcome is recorded the
    next date belongs to that outcome. Each move is kept on the hearing
    (`reschedules`), so the old date is never silently lost."""
    case = await case_repo.find_by_id(case_id)
    if not case:
        raise NotFoundError("Case")
    if case.get("lawyer_id") != lawyer_id:
        raise ForbiddenError("Only the assigned lawyer can reschedule hearings")
    _assert_open(case)

    hearing = next((h for h in case.get("hearing_dates", []) if h.get("_id") == hearing_id), None)
    if hearing is None:
        raise NotFoundError("Hearing")
    if hearing.get("outcome"):
        # 409, like the same refusal when the outcome lands mid-request: it is
        # a conflict with the hearing's state, and the page re-reads on 409.
        raise ConflictError(
            "This hearing already has an outcome. Set the next date from its outcome instead."
        )

    # Days are compared on the PAKISTAN calendar. It used UTC dates and allowed
    # one day back, so it accepted yesterday — and between 00:00 and 05:00
    # PKT, two days back. The new day is stored the way every reader expects a
    # hearing day: midnight UTC of the Pakistan date.
    new_day = pkt_date(data["date"])
    if new_day < pkt_today(datetime.now(timezone.utc)):
        raise AppValidationError("Pick a date from today onwards")
    new_date = pkt_day_start_utc(new_day)

    old_date = hearing.get("date")
    old_time = hearing.get("time")
    new_time = data.get("time") or old_time
    old_day = pkt_date(old_date) if isinstance(old_date, datetime) else str(old_date)[:10]
    if str(old_day) == str(new_day) and old_time == new_time:
        raise AppValidationError("That is already the hearing's date and time")

    entry = {
        "from_date": old_date,
        "from_time": old_time,
        "to_date": new_date,
        "to_time": new_time,
        "reason": (data.get("reason") or "").strip() or None,
        "at": datetime.now(timezone.utc),
    }
    # One conditional write: only if the hearing is still where it was read
    # (same date and time, still no outcome). The old code rebuilt the history
    # from that read and wrote it all back, so a concurrent move lost an entry
    # and a concurrent outcome could be moved; and it notified regardless.
    moved = await case_repo.move_hearing(
        case_id, hearing_id, expect_date=old_date, expect_time=old_time,
        new_date=new_date, new_time=new_time, history_entry=entry)
    if not moved:
        current = await case_repo.find_by_id(case_id)
        if current:
            _assert_open(current)             # closed since it was read
        h = next((x for x in (current or {}).get("hearing_dates") or [] if x.get("_id") == hearing_id), None)
        if h is None:
            raise ConflictError("This hearing was removed meanwhile. Reload the case.")
        if h.get("outcome"):
            raise ConflictError("An outcome was recorded for this hearing meanwhile, so it can no longer be moved.")
        raise ConflictError("This hearing was changed meanwhile. Reload the case and try again.")
    history = [entry]

    # Tell the client: a moved date is exactly what they plan travel around.
    # A walk-in case has no client account to tell.
    try:
        if not case.get("client_id"):
            raise _NoClient()
        from app.core.constants import NotificationType
        from app.services import notification_service

        def _day(d):
            return d.strftime("%d %b %Y") if hasattr(d, "strftime") else str(d)[:10]
        body = (f"{case.get('title', 'Your case')}: hearing moved from {_day(old_date)} "
                f"to {_day(new_date)}" + (f" at {new_time}" if new_time else "") + ".")
        if history[-1]["reason"]:
            body += f" Reason: {history[-1]['reason']}"
        await notification_service.create_notification(
            case["client_id"],
            NotificationType.CASE_UPDATE,
            "Hearing rescheduled",
            body,
            payload={"case_id": case_id, "hearing_id": hearing_id},
            logical_event_id=f"hearing-rescheduled:{case_id}:{hearing_id}:{entry['at'].isoformat()}",
        )
    except _NoClient:
        pass
    except Exception:
        # Must not undo the move, but the client was not told: log it.
        logger.exception("hearing-rescheduled notification failed for case %s", case_id)

    return _public_case(await case_repo.find_by_id(case_id))


async def send_message(
    case_id: str, sender_id: str, sender_role: str, sender_name: str, text: str
) -> dict:
    case = await case_repo.find_by_id(case_id)
    if not case:
        raise NotFoundError("Case")
    _assert_access(case, sender_id, sender_role)
    _assert_open(case)
    if not case.get("client_id"):
        # A walk-in client has no account: a message here would reach nobody.
        raise ConflictError("This client is not on Attorney.AI, so messages cannot be sent on this case.")
    msg = {
        "_id": secrets.token_urlsafe(8),
        # The engagement this message belongs to (None while unassigned).
        "lawyer_id": case.get("lawyer_id"),
        "sender_id": sender_id,
        "sender_role": sender_role,
        "sender_name": sender_name,
        "text": text,
        "created_at": datetime.now(timezone.utc),
    }
    if not await case_repo.add_message(case_id, msg):
        await _refuse_unwritten(case_id)

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
    return [m for m in case.get("messages", []) if _thread_visible(m, requester_id, requester_role)]


async def add_task(case_id: str, task_data: dict, lawyer_id: str) -> dict:
    case = await case_repo.find_by_id(case_id)
    if not case:
        raise NotFoundError("Case")
    if case.get("lawyer_id") != lawyer_id:
        raise ForbiddenError("Only the assigned lawyer can add tasks")
    _assert_open(case)
    task = {
        "_id": secrets.token_urlsafe(8),
        "lawyer_id": lawyer_id,
        "title": task_data["title"],
        "due": task_data.get("due"),
        "priority": task_data.get("priority", "medium"),
        "description": task_data.get("description"),
        "done": False,
        "completed_at": None,
        "created_at": datetime.now(timezone.utc),
    }
    if not await case_repo.add_task(case_id, task):
        await _refuse_unwritten(case_id)
    return task


async def list_tasks(case_id: str, requester_id: str, requester_role: str) -> list:
    case = await case_repo.find_by_id(case_id)
    if not case:
        raise NotFoundError("Case")
    # Tasks are the lawyer's working notes, never shown to the client.
    if requester_role == "client":
        raise ForbiddenError("Tasks are private to the lawyer")
    _assert_access(case, requester_id, requester_role)
    return [t for t in case.get("tasks", []) if _thread_visible(t, requester_id, requester_role)]


async def toggle_task(case_id: str, task_id: str, done: bool, lawyer_id: str) -> dict:
    case = await case_repo.find_by_id(case_id)
    if not case:
        raise NotFoundError("Case")
    if case.get("lawyer_id") != lawyer_id:
        raise ForbiddenError("Only the assigned lawyer can update tasks")
    _assert_open(case)
    task = next((t for t in case.get("tasks", []) if t.get("_id") == task_id), None)
    if task is None or not _thread_visible(task, lawyer_id, "lawyer"):
        raise NotFoundError("Task")
    if not await case_repo.toggle_task(case_id, task_id, done):
        # Nothing changed: already in that state, or closed since it was read.
        current = await case_repo.find_by_id(case_id)
        if current:
            _assert_open(current)
    return _public_case(await case_repo.find_by_id(case_id))


CLOSED_STATUSES = (CaseStatus.CLOSED.value, CaseStatus.DISMISSED.value)


async def _refuse_unwritten(case_id: str) -> None:
    """A guarded write matched nothing: say why (closed meanwhile, or gone)."""
    current = await case_repo.find_by_id(case_id)
    if current:
        _assert_open(current)
    raise NotFoundError("Case")


def _assert_open(case: dict) -> None:
    """A closed or dismissed case is a record, not a workspace: no new
    hearings, outcomes, tasks or messages, and no notifications to a client
    about a matter that has ended."""
    if case.get("status") in CLOSED_STATUSES:
        raise ConflictError("This case is closed, so it can no longer be changed.")


def _thread_visible(item: dict, requester_id: str, requester_role: str) -> bool:
    """Whether one message or task belongs to this reader.

    Every message and task records the lawyer whose engagement it belongs to
    (`lawyer_id`, None while no lawyer is engaged). A lawyer sees only their
    own; the client and admins see every message. A row with no `lawyer_id`
    KEY predates this rule: it is the current lawyer's, because ending an
    engagement stamps every such row with the departing lawyer
    (`seal_threads_for`)."""
    if requester_role != "lawyer":
        return True
    if "lawyer_id" not in item:
        return True
    return item.get("lawyer_id") == requester_id


async def seal_threads_for(case_id: str, lawyer_id: str, session=None) -> None:
    """Stamp a departing lawyer onto the case's untagged messages and tasks,
    so the next lawyer engaged does not inherit them. Called inside the
    engagement-termination transaction."""
    from app.db.collections import get_cases_col
    col = get_cases_col()
    for field in ("messages", "tasks"):
        # The array must exist for an array-filtered update; skip it if not.
        await col.update_one(
            {"_id": case_id, field: {"$type": "array"}},
            {"$set": {f"{field}.$[x].lawyer_id": lawyer_id}},
            array_filters=[{"x.lawyer_id": {"$exists": False}}],
            session=session,
        )


def _assert_access(case: dict, user_id: str, role: str) -> None:
    if role == "admin":
        return
    if role == "client" and case.get("client_id") == user_id:
        return
    if role == "lawyer" and case.get("lawyer_id") == user_id:
        return
    raise ForbiddenError("Access denied to this case")
