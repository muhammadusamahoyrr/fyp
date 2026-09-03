"""List, open, rename, archive and delete AI conversations.

Two surfaces, one set of rules:

    /conversations          the client chatbot's conversations
    /research-conversations the lawyer research assistant's

Every handler passes the AUTHENTICATED caller's id to the service, which pushes
it into the Mongo filter. No handler reads a session and then checks who owns
it, and no handler accepts an owner from the request — a conversation that is
not yours does not come back at all, so there is nothing to forget to check.

A refusal is always the same refusal. "No such conversation" and "not yours"
produce one 403 with one message, because distinguishing them would let anyone
holding a session id learn whether it exists, and session ids travel in URLs,
logs and screenshots.
"""
import logging

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from app.dependencies import get_current_user
from app.schemas.common import StatusResponse
from app.core.exceptions import ForbiddenError
from app.services import conversation_service as conversations

logger = logging.getLogger(__name__)

# One refusal for every way a conversation can be unavailable: it never
# existed, it is someone else's, or its case is no longer accessible to this
# caller. Distinguishing them would answer questions the caller should not be
# able to ask — whether a session id is real, and whether a matter exists.
_DENIED = "Conversation not available"

# How far past the requested page size to read before filtering out
# inaccessible rows, and the hard ceiling on that read.
_OVERFETCH_FACTOR = 3
_OVERFETCH_CAP = 200

router = APIRouter(tags=["conversations"])


class RenameRequest(BaseModel):
    title: str = Field(min_length=1, max_length=conversations.TITLE_MAX)


class CancelRequest(BaseModel):
    # Bounds only. The CONTENT rule lives in conversation_turns and is applied
    # in the handler, so the socket and this route cannot drift into two
    # different notions of a valid turn id.
    client_message_id: str = Field(min_length=1, max_length=128)


class ArchiveRequest(BaseModel):
    archived: bool = True


class NewConversationRequest(BaseModel):
    """Optional hints for a conversation the UI is starting deliberately.

    `case_id` is accepted only on the research surface and is VERIFIED against
    the case repository before it is stored — see `_authorised_case_id`. The
    client surface has no case binding here at all: the previous WebSocket path
    took `case_id` straight off the frame and wrote it to the session with no
    check, so a client could bind their conversation to any case id they could
    name.
    """
    title: str | None = Field(default=None, max_length=conversations.TITLE_MAX)
    case_id: str | None = None


def _new_session_id() -> str:
    import secrets
    return secrets.token_urlsafe(16)


async def _case_is_accessible(case_id: str | None, current_user: dict) -> bool:
    """Can this caller see that case RIGHT NOW? Never raises.

    Separate from `_authorised_case_id` because two callers want different
    things from the same question: an endpoint acting on one conversation wants
    a refusal, and the list wants to quietly omit the row. Raising in the list
    would mean one revoked case made a lawyer's entire conversation list fail.
    """
    if not case_id:
        return True
    from app.core.exceptions import ForbiddenError, NotFoundError
    from app.services import case_service
    try:
        await case_service.get_case(
            case_id, str(current_user["_id"]), current_user.get("role", "client"))
        return True
    except (NotFoundError, ForbiddenError):
        return False
    except Exception:
        # A storage failure is not an authorization decision. Fail CLOSED: an
        # inaccessible-looking row is a smaller error than a leaked one.
        logger.exception("case access check failed for %r", case_id)
        return False


async def _authorised_case_id(case_id: str | None, current_user: dict) -> str | None:
    """The case id, once the caller is proved to be on that case. Else refuse.

    Runs the real access rule (`case_service.get_case`), not a copy of it, and
    collapses "no such case" and "not your case" into the same refusal the rest
    of this module uses — a lawyer must not be able to walk case ids and learn
    which ones are real.
    """
    if not case_id:
        return None
    if not await _case_is_accessible(case_id, current_user):
        raise ForbiddenError(_DENIED)
    return str(case_id)


async def _readable(session_summary_or_doc: dict, current_user: dict) -> None:
    """Refuse a conversation whose case the caller can no longer see.

    Authorization is rechecked on EVERY operation, not just at creation. A
    lawyer taken off a matter keeps owning the conversation row — ownership and
    case access are different facts — and without this recheck they would keep
    reading research bound to a case they are no longer on, possibly months
    later.

    The refusal is the same generic one used for a missing or foreign
    conversation, so "exists but you lost access" is not distinguishable from
    "never existed".
    """
    case_id = session_summary_or_doc.get("case_id")
    if case_id and not await _case_is_accessible(case_id, current_user):
        raise ForbiddenError(_DENIED)


# ══════════════════════════════════════════════════════════════════════════════
# Client chatbot conversations
# ══════════════════════════════════════════════════════════════════════════════

client_router = APIRouter(prefix="/conversations", tags=["conversations"])


@client_router.get("")
async def list_conversations(
    include_archived: bool = False,
    limit: int = Query(conversations.DEFAULT_LIST_PAGE, ge=1,
                       le=conversations.MAX_LIST_PAGE),
    after: str | None = Query(None, max_length=512),
    search: str | None = Query(None, max_length=120),
    current_user: dict = Depends(get_current_user),
):
    """One page of this user's chat conversations, newest first.

    Paginated because the previous version returned a bare array capped at
    fifty with no way to ask for more: a user with a fifty-first conversation
    could not reach it by any route — no cursor, no search, no "load more". It
    was not slow, it was unreachable.

    `search` matches the title and the question that named the conversation.
    """
    return await conversations.list_page(
        conversations.SURFACE_CLIENT, str(current_user["_id"]),
        include_archived=include_archived, limit=limit,
        after=after, search=search)


@client_router.post("")
async def create_conversation(
    body: NewConversationRequest | None = None,
    current_user: dict = Depends(get_current_user),
):
    """Start a real, persisted conversation.

    "New Chat" used to be a client-side array reset: it minted a session id in
    the browser and nothing existed until the first message was answered, so a
    new chat abandoned before its first reply left no trace and a refresh lost
    the one in progress. The session id is minted HERE so it is a server fact
    from the moment the user asks for it.
    """
    session_id = _new_session_id()
    session = await conversations.ensure_session(
        conversations.SURFACE_CLIENT, session_id, str(current_user["_id"]),
        title=(body.title if body else None))
    return conversations.summarise(session)


@client_router.get("/{session_id}")
async def get_conversation(
    session_id: str,
    after_seq: int | None = Query(
        default=None, description="Cursor: messages AFTER this sequence."),
    before_seq: int | None = Query(
        default=None, description="Cursor: messages BEFORE this sequence."),
    page_size: int = Query(50, ge=1, le=200),
    current_user: dict = Depends(get_current_user),
):
    """One conversation and one page of its messages, oldest first.

    READS FROM THE END BY DEFAULT.

    With no cursor this returns the NEWEST page. A reader opens a conversation
    at its end, so fetching from the start meant a lawyer reopening a two-year
    thread waited for every page of it before seeing the answer they came back
    for. Follow `older_cursor` while `has_older` is true to walk backwards.

    `after_seq` still walks FORWARD from a point, unchanged, for any caller that
    wants a conversation from its beginning.

    Messages are always oldest-first WITHIN a page, whichever direction the page
    was read — a direction that leaked into the output would be a transcript
    that renders backwards on one code path.

    They carry the trust metadata the answers originally showed — citation
    status, claim support, calibrated confidence, jurisdiction and the request
    id — so a reloaded answer is qualified exactly as it was when first given.
    """
    return await conversations.get_session(
        conversations.SURFACE_CLIENT, session_id, str(current_user["_id"]),
        after_seq=after_seq, before_seq=before_seq, page_size=page_size)


@client_router.patch("/{session_id}")
async def rename_conversation(
    session_id: str,
    body: RenameRequest,
    current_user: dict = Depends(get_current_user),
):
    return await conversations.rename_session(
        conversations.SURFACE_CLIENT, session_id, str(current_user["_id"]),
        body.title)


@client_router.delete("/{session_id}")
async def delete_conversation(
    session_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Remove a conversation from this user's chat history.

    The response says what actually happened. The messages really are removed,
    but the audit trail for answers already given is retained under its own
    policy, so claiming everything was erased would be false — see
    conversation_service.DELETION_EFFECTS.
    """
    result = await conversations.delete_session(
        conversations.SURFACE_CLIENT, session_id, str(current_user["_id"]))
    return StatusResponse(success=True, message=result["notice"])


# ══════════════════════════════════════════════════════════════════════════════
# Lawyer research conversations
# ══════════════════════════════════════════════════════════════════════════════

# Owner-scoped, NOT role-gated, and that is deliberate.
#
# `POST /ai/research` admits any authenticated user, so gating these endpoints
# on the lawyer role would mean a client's research turns were persisted into
# rows they could never list, open or delete — data created about someone that
# they have no way to reach. The property this surface actually needs is "your
# own conversations and nobody else's", which ownership gives for every role,
# and which is what stops one lawyer reading another's.
research_router = APIRouter(prefix="/research-conversations", tags=["conversations"])


@research_router.get("")
async def list_research(
    case_id: str | None = Query(
        default=None,
        description='A case id to filter to; "none" selects general (unbound) research.'),
    include_archived: bool = False,
    limit: int = Query(conversations.DEFAULT_LIST_PAGE, ge=1,
                       le=conversations.MAX_LIST_PAGE),
    after: str | None = Query(None, max_length=512),
    search: str | None = Query(None, max_length=120),
    current_user: dict = Depends(get_current_user),
):
    """One page of this lawyer's research conversations, newest first.

    `case_id` is a FILTER over conversations this lawyer already owns, so it
    grants nothing: a lawyer passing another lawyer's case id gets their own
    (empty) set of conversations for it, not that lawyer's. Binding a
    conversation to a case is the operation that checks the case, and it happens
    on create and on /ai/research.

    Rows bound to a case the caller can no longer see are OMITTED rather than
    refused. Ownership and case access are different facts, and a lawyer taken
    off a matter still owns the conversation row — but the title of a research
    thread names the matter, so listing it would leak the thing access was
    revoked over. Omitting one row keeps the rest of the list working;
    refusing the request would make one revoked case break the whole sidebar.
    """
    # Over-fetch, filter, trim — and advance the cursor over what was filtered.
    #
    # THE CURSOR IS A POSITION IN THE UNDERLYING ORDER, NOT IN THE VISIBLE LIST.
    #
    # That distinction is the whole difficulty here. If the next cursor were
    # always taken from the last VISIBLE row, then a page whose rows were all
    # filtered out would carry no cursor at all, the client would stop, and
    # every accessible conversation behind that block of revoked matters would
    # be unreachable — the same class of bug as the fifty-row cap, arriving by
    # a subtler route. So when nothing survives the filter, the cursor is taken
    # from the last row READ, and the client walks past the inaccessible block.
    size = conversations.clamp_list_limit(limit)
    rows = await conversations.list_sessions(
        conversations.SURFACE_RESEARCH, str(current_user["_id"]),
        case_id=case_id, include_archived=include_archived, after=after,
        search=search,
        limit=min(size * _OVERFETCH_FACTOR, _OVERFETCH_CAP))

    # One access check per DISTINCT case, not per row. A lawyer's list is
    # mostly a handful of matters, so this turns a page of sequential case
    # lookups into a few.
    decisions: dict[str, bool] = {}
    visible: list[dict] = []
    for row in rows:
        case = row.get("case_id")
        if case and case not in decisions:
            decisions[case] = await _case_is_accessible(case, current_user)
        if not case or decisions[case]:
            visible.append(row)
        if len(visible) > size:
            break

    page = visible[:size]
    if len(visible) > size:
        # More accessible rows are waiting; continue from the last one shown.
        has_more, tail = True, page[-1]
    elif len(rows) >= min(size * _OVERFETCH_FACTOR, _OVERFETCH_CAP):
        # The read filled up, so there may be more beyond it — including the
        # case where `page` is empty because this whole stretch was revoked.
        has_more, tail = True, rows[-1]
    else:
        has_more, tail = False, None

    return {
        "conversations": [conversations.summarise(row) for row in page],
        "next_cursor": conversations.encode_cursor(tail) if tail else None,
        "has_more": has_more,
    }


@research_router.post("")
async def create_research(
    body: NewConversationRequest | None = None,
    current_user: dict = Depends(get_current_user),
):
    """Start a research conversation, optionally bound to a case.

    The case is verified before it is stored, so the binding recorded on the
    conversation is a server fact rather than a client claim.
    """
    case_id = await _authorised_case_id(body.case_id if body else None, current_user)
    session_id = _new_session_id()
    session = await conversations.ensure_session(
        conversations.SURFACE_RESEARCH, session_id, str(current_user["_id"]),
        case_id=case_id, title=(body.title if body else None))
    return conversations.summarise(session)


@research_router.get("/{session_id}")
async def get_research(
    session_id: str,
    after_seq: int | None = Query(
        default=None, description="Cursor: messages AFTER this sequence."),
    before_seq: int | None = Query(
        default=None, description="Cursor: messages BEFORE this sequence."),
    page_size: int = Query(50, ge=1, le=200),
    current_user: dict = Depends(get_current_user),
):
    """One research conversation, with its messages and any pending question.

    `pending_question` says the last turn ended by asking the lawyer for facts
    rather than answering. It is a display hint — the LangGraph checkpoint is
    the authority on whether the turn is really interrupted, and /ai/research
    consults it before every turn. A stale hint costs a banner; it can never
    resume an answer into the wrong conversation.
    """
    session = await conversations.get_session(
        conversations.SURFACE_RESEARCH, session_id, str(current_user["_id"]),
        after_seq=after_seq, before_seq=before_seq, page_size=page_size)
    # Re-verify the case on every open. A lawyer removed from a matter must stop
    # seeing the research bound to it, and the binding was checked when the
    # conversation was created — which may have been months ago.
    await _readable(session, current_user)
    return session


@research_router.patch("/{session_id}")
async def rename_research(
    session_id: str,
    body: RenameRequest,
    current_user: dict = Depends(get_current_user),
):
    """Rename. Refused when the case is no longer accessible.

    Renaming reads the conversation back, and the returned row carries the
    title — which names the matter. Owning the row is not enough.
    """
    existing = await conversations.get_raw(
        conversations.SURFACE_RESEARCH, session_id, str(current_user["_id"]))
    await _readable(existing, current_user)
    return await conversations.rename_session(
        conversations.SURFACE_RESEARCH, session_id, str(current_user["_id"]),
        body.title)


@research_router.post("/{session_id}/archive")
async def archive_research(
    session_id: str,
    body: ArchiveRequest | None = None,
    current_user: dict = Depends(get_current_user),
):
    """Archive or unarchive. Archived conversations keep their messages and drop
    out of the default list — the research equivalent of closing a file rather
    than shredding it.

    Refused when the case is no longer accessible, for the same reason rename
    is: the response carries the conversation's title.
    """
    existing = await conversations.get_raw(
        conversations.SURFACE_RESEARCH, session_id, str(current_user["_id"]))
    await _readable(existing, current_user)
    return await conversations.set_archived(
        conversations.SURFACE_RESEARCH, session_id, str(current_user["_id"]),
        body.archived if body else True)


@research_router.delete("/{session_id}")
async def delete_research(
    session_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Remove a research conversation from this user's chat history.

    THE ONE DELIBERATE EXCEPTION TO THE CASE RECHECK
    ------------------------------------------------
    Every other operation on a case-bound conversation is refused once the case
    becomes inaccessible. Delete is not, and the asymmetry is intentional.

    The conversation is the OWNER's data — their questions, in their history —
    and losing access to a matter should not strand it there permanently, with
    the owner able neither to read it nor to get rid of it. That would be the
    worst of both: the questions retained indefinitely, by someone with no way
    to remove them.

    Deleting also reveals nothing. It reads nothing back to the caller: no
    title, no messages, no case id, no confirmation that the case ever existed.
    The response is the same notice for a conversation that was deleted, one
    that never existed, and one whose case is long gone. So the exception grants
    the ability to REMOVE without granting the ability to READ, which is the
    property that makes it safe.

    The delete itself is still owner-scoped: another user's conversation is
    refused exactly as before.
    """
    result = await conversations.delete_session(
        conversations.SURFACE_RESEARCH, session_id, str(current_user["_id"]))
    return StatusResponse(success=True, message=result["notice"])


# ── stopping a turn, and finding out whether one is still running ────────────

@client_router.post("/{session_id}/cancel")
async def cancel_client_turn(
    session_id: str,
    body: CancelRequest,
    current_user: dict = Depends(get_current_user),
):
    """Abandon a turn that is still running in this user's conversation.

    Cancellation does not stop the provider call — it is already in flight and
    nothing can recall it. It discards the ANSWER: the running worker's fenced
    completion matches nothing once the lease is cleared, so it stores no
    message, writes no provenance and sends no frame.

    The work is paid for either way. What this buys is that a user who changed
    their mind is not handed an answer they said they no longer wanted, and that
    the conversation is usable again immediately instead of after the lease.
    """
    return await _cancel_turn(
        conversations.SURFACE_CLIENT, session_id, body.client_message_id,
        current_user)


@research_router.post("/{session_id}/cancel")
async def cancel_research_turn(
    session_id: str,
    body: CancelRequest,
    current_user: dict = Depends(get_current_user),
):
    """Abandon a running research turn. See `cancel_client_turn`."""
    existing = await conversations.get_raw(
        conversations.SURFACE_RESEARCH, session_id, str(current_user["_id"]))
    await _readable(existing, current_user)
    return await _cancel_turn(
        conversations.SURFACE_RESEARCH, session_id, body.client_message_id,
        current_user)


async def _cancel_turn(surface: str, session_id: str, client_message_id: str,
                       current_user: dict) -> StatusResponse:
    """Shared: authorise the conversation, then abandon the named turn.

    Ownership is the whole authorisation. The caller cannot hold the running
    worker's lease token — cancellation comes from a different connection by
    definition, often a different tab — so the turn is abandoned on the
    conversation owner's behalf rather than the lease holder's.
    """
    from app.services import conversation_turns as turns

    target = turns.validate_client_message_id(client_message_id)
    ref = await conversations.open_ref(
        surface, session_id, str(current_user["_id"]), create=False)

    outcome, record = await turns.abandon_turn(ref.key, target)
    if outcome == turns.CANCEL_STOPPED:
        # Free the slot THIS turn holds, addressed by its id.
        #
        # The previous call passed None as the owner token, so the filter looked
        # for a slot whose token was literally None and matched nothing: Stop
        # reported success, the slot stayed held, and the next question was
        # refused as busy until the cancelled work finished on its own.
        await turns.release_conversation_lease_for_turn(ref, record["_id"])

    # Always a 200 — a page that stops a turn which finished a moment earlier
    # raced, it did not do anything wrong. But the MESSAGE says what actually
    # happened, because "stopped it" and "it had already answered" differ in a
    # way the user can check by reloading.
    return StatusResponse(success=True, message=turns.CANCEL_MESSAGES[outcome])


@research_router.get("/{session_id}/turn-status")
async def research_turn_status(
    session_id: str,
    client_message_id: str = Query(..., min_length=1, max_length=128),
    current_user: dict = Depends(get_current_user),
):
    """What the pipeline is doing for one running turn.

    Polled by a page that is already waiting on `/ai/research`, which is one
    long HTTP request with no channel to report progress on. The stage lives on
    the TURN rather than in a connection, so it also survives a refresh: a
    lawyer who reloads mid-answer sees the pipeline still working rather than a
    blank page.

    Deliberately narrow — the stage, its label and the turn's status. This is
    not a second way to read the answer, the question, or anything else a
    `get_turn` caller can see, and a polled endpoint is exactly where such a
    thing would go unnoticed.

    Owner-scoped like every other read here: `open_ref` refuses a conversation
    that is not the caller's, so a turn id is not a way to watch someone else's
    research.
    """
    from app.services import conversation_turns as turns

    target = turns.validate_client_message_id(client_message_id)
    existing = await conversations.get_raw(
        conversations.SURFACE_RESEARCH, session_id, str(current_user["_id"]))
    # Case access is re-checked, not assumed from ownership: a lawyer taken off
    # a matter keeps the row and loses the right to watch it work.
    await _readable(existing, current_user)

    ref = conversations.ref_for(
        conversations.SURFACE_RESEARCH, existing, str(current_user["_id"]))
    status = await turns.read_stage(ref.key, target)
    # A turn this conversation has never heard of is reported as absent, not
    # refused: a page polling one that finished a moment ago has raced, not
    # done anything wrong.
    return status or {"status": None, "stage": None, "label": None,
                      "started_at": None}


router.include_router(client_router)
router.include_router(research_router)
