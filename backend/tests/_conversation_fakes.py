"""Offline stand-ins for the conversation store, for tests about other things.

`/ai/research` and the WebSocket both open a conversation, claim a turn and take
a lease before running the graph. Those are database operations, so a unit test
about provenance, attribution or routing would otherwise have to reach Mongo —
and a test that quietly opens a network connection is how a suite stops being
deterministic and starts being slow and flaky.

These fakes keep the SHAPE and the DECISIONS of the real modules — the same
claim outcomes, the same refusals, the same fencing on the owner token — and
drop only the storage. Tests that are actually about persistence use the real
modules against the test database; see test_conversations.py,
test_conversation_hardening.py and test_conversation_identity.py.
"""
from __future__ import annotations

from app.core.exceptions import ConflictError, ForbiddenError
from app.services import conversation_service as real_conversations
from app.services import conversation_turns as real_turns


class FakeConversations:
    """conversation_service without a database.

    Message building, the canonical identity and the case-binding rule are
    delegated to the real implementations: all three are pure, and a fake that
    reimplemented them would let a test pass while the real rule was broken.
    """

    SURFACE_CLIENT = real_conversations.SURFACE_CLIENT
    SURFACE_RESEARCH = real_conversations.SURFACE_RESEARCH
    build_message = staticmethod(real_conversations.build_message)
    ConversationRef = real_conversations.ConversationRef
    CONTEXT_WINDOW = real_conversations.CONTEXT_WINDOW
    DELETION_EFFECTS = real_conversations.DELETION_EFFECTS
    DELETION_NOTICE = real_conversations.DELETION_NOTICE

    def __init__(self, session=None, owner_field="owner_id", store_fails=False,
                 surface=None):
        self.owner_field = owner_field
        self.store_fails = store_fails
        self.surface = surface or self.SURFACE_CLIENT
        self.messages: list[dict] = []
        self.pending: list = []
        # Conversation settings written by a frame.
        self.meta: list[dict] = []
        self.created: list[str] = []
        # Keyed by session id, like the real collection.
        self.sessions: dict[str, dict] = {}
        if session is not None:
            session.setdefault("_id", f"doc-{session.get('session_id', 's1')}")
            self.sessions[str(session.get("session_id", "s1"))] = session

    @property
    def session(self):
        return next(reversed(self.sessions.values()), None) if self.sessions else None

    @session.setter
    def session(self, value):
        if value is None:
            self.sessions = {}
            return
        value.setdefault("_id", f"doc-{value.get('session_id', 's1')}")
        self.sessions = {str(value.get("session_id", "s1")): value}

    # ── creation and ownership ──────────────────────────────────────────────
    def _owner_of(self, session):
        return (session.get(self.owner_field)
                or session.get("client_id") or session.get("owner_id"))

    async def ensure_session(self, surface, session_id, owner_id, **kwargs):
        existing = self.sessions.get(str(session_id))
        if existing is not None:
            owner = self._owner_of(existing)
            if owner is not None and str(owner) != str(owner_id):
                raise ForbiddenError("Conversation not available")
            return existing
        self.created.append(session_id)
        created = {"_id": f"doc-{session_id}", "session_id": str(session_id),
                   self.owner_field: str(owner_id),
                   "case_id": kwargs.get("case_id"), "messages": []}
        self.sessions[str(session_id)] = created
        return created

    async def get_raw(self, surface, session_id, owner_id):
        existing = self.sessions.get(str(session_id))
        if existing is None:
            raise ForbiddenError("Conversation not available")
        owner = self._owner_of(existing)
        if owner is not None and str(owner) != str(owner_id):
            raise ForbiddenError("Conversation not available")
        return existing

    async def open_ref(self, surface, session_id, owner_id, *, case_id=None,
                       create=True):
        session = (await self.ensure_session(surface, session_id, owner_id,
                                             case_id=case_id)
                   if create else await self.get_raw(surface, session_id, owner_id))
        # The real ref builder, so the canonical key a test sees is the one
        # production would produce.
        return real_conversations.ref_for(surface, session, owner_id)

    async def assert_case_binding(self, surface, session_id, owner_id, requested):
        """The real rule, over the fake's stored session."""
        session = await self.get_raw(surface, session_id, owner_id)
        stored = session.get("case_id") or None
        wanted = str(requested) if requested else None
        if stored != wanted:
            raise ConflictError(
                "This conversation is fixed to the case it was started for. "
                "Start a new conversation to research a different matter.")
        return stored

    # ── messages ────────────────────────────────────────────────────────────
    async def append_message(self, ref, message, *, turn_id=None):
        if self.store_fails:
            raise RuntimeError("storage unavailable")
        # Idempotent on (conversation, turn, role), like the unique index.
        if turn_id:
            for existing in self.messages:
                if (existing.get("_turn") == turn_id
                        and existing.get("role") == message.get("role")):
                    return existing
        record = {**message, "_turn": turn_id,
                  "id": f"m{len(self.messages) + 1}", "seq": len(self.messages) + 1}
        self.messages.append(record)
        return record

    async def recent_context(self, ref, *, limit=None, exclude_turn_id=None):
        """The real exclusion rule: the current turn is not history.

        Reproduced rather than stubbed, because a test asserting the model does
        not see the question twice has to exercise the thing that prevents it.
        """
        window = limit or self.CONTEXT_WINDOW
        return [{"role": m.get("role", ""), "content": m.get("content", "")}
                for m in self.messages
                if m.get("role") in ("user", "assistant")
                and not (exclude_turn_id and m.get("_turn") == exclude_turn_id)
                ][-window:]

    async def last_assistant_message(self, ref):
        for message in reversed(self.messages):
            if message.get("role") == "assistant" and message.get("content"):
                return message["content"]
        return None

    async def set_pending_question(self, surface, session_id, owner_id, question):
        self.pending.append(question)

    async def update_meta(self, ref, meta):
        # The real one drops anything outside the whitelist; a fake that
        # recorded everything would let a test "prove" a field is refused when
        # only the fake refused it.
        fields = {k: v for k, v in (meta or {}).items()
                  if k in real_conversations.SETTABLE_META}
        self.meta.append(fields)
        return bool(fields)


class FakeTurns:
    """conversation_turns without a database, and with in-memory claims.

    The claim outcomes and the FENCING are the real behaviour: a second claim of
    the same id replays, a claim while one is running is refused, a claim with a
    different fingerprint conflicts, and a completion by a worker that no longer
    holds the lease fails. Those are exactly what a test about idempotency or
    lease loss depends on, so they are reproduced rather than stubbed away.
    """

    CLAIM_RUN = real_turns.CLAIM_RUN
    CLAIM_REPLAY = real_turns.CLAIM_REPLAY
    CLAIM_IN_PROGRESS = real_turns.CLAIM_IN_PROGRESS
    STATUS_COMPLETED = real_turns.STATUS_COMPLETED
    LEASE_SECONDS = real_turns.LEASE_SECONDS
    TURN_TIMEOUT_S = real_turns.TURN_TIMEOUT_S
    STATUS_IN_PROGRESS = real_turns.STATUS_IN_PROGRESS
    CANCEL_STOPPED = real_turns.CANCEL_STOPPED
    CANCEL_ALREADY_ANSWERED = real_turns.CANCEL_ALREADY_ANSWERED
    CANCEL_ALREADY_ENDED = real_turns.CANCEL_ALREADY_ENDED
    CANCEL_UNKNOWN = real_turns.CANCEL_UNKNOWN
    CANCEL_MESSAGES = real_turns.CANCEL_MESSAGES
    content_hash = staticmethod(real_turns.content_hash)
    request_fingerprint = staticmethod(real_turns.request_fingerprint)
    validate_client_message_id = staticmethod(real_turns.validate_client_message_id)
    new_owner_token = staticmethod(real_turns.new_owner_token)
    busy_error = staticmethod(real_turns.busy_error)

    def __init__(self, lease_free=True, lose_lease=False):
        self.records: dict[tuple, dict] = {}
        self.lease_free = lease_free
        # Simulates a worker whose lease expired and was reclaimed: every fenced
        # write it attempts fails.
        self.lose_lease = lose_lease
        self.completed: list[dict] = []
        self.failed: list[dict] = []
        self.released: list[str] = []
        # Turn ids whose conversation slot was freed by a cancellation.
        self.released_for_turn: list[str] = []
        self.renewals = 0

    async def claim_turn(self, conversation_key, client_message_id, fingerprint,
                         *, owner_token, **kwargs):
        key = (str(conversation_key), str(client_message_id))
        existing = self.records.get(key)
        if existing is None:
            record = {"_id": f"turn-{len(self.records) + 1}",
                      "conversation_id": str(conversation_key),
                      "client_message_id": str(client_message_id),
                      "content_hash": str(fingerprint), "status": "in_progress",
                      "lease_owner": owner_token, "response": None,
                      "request_id": None}
            self.records[key] = record
            return self.CLAIM_RUN, record
        if existing["content_hash"] != str(fingerprint):
            raise ConflictError(
                "This message id was already used for a different question. "
                "Send a new message id.")
        if existing["status"] == self.STATUS_COMPLETED:
            return self.CLAIM_REPLAY, existing
        return self.CLAIM_IN_PROGRESS, existing

    async def acquire_conversation_lease(self, ref, turn_id, owner_token, **kwargs):
        return self.lease_free

    async def renew_conversation_lease(self, ref, owner_token, **kwargs):
        return not self.lose_lease

    async def renew_lease(self, turn_id, owner_token, **kwargs):
        self.renewals += 1
        return not self.lose_lease

    async def holds_authority(self, ref, turn_id, owner_token, now=None):
        """Both leases, as one guard — the real behaviour.

        `lose_lease` models a worker whose deadline passed and was reclaimed:
        it holds neither, so every fenced operation refuses it.
        """
        return not self.lose_lease

    async def renew_authority(self, ref, turn_id, owner_token, **kwargs):
        self.renewals += 1
        return not self.lose_lease

    async def release_conversation_lease(self, ref, owner_token):
        self.released.append(owner_token)

    async def active_turn(self, ref, now=None):
        return None

    async def complete_turn(self, turn_id, owner_token, *, response, request_id):
        if self.lose_lease:
            return False
        for record in self.records.values():
            if record["_id"] == turn_id and record["lease_owner"] == owner_token:
                record.update(status=self.STATUS_COMPLETED, response=response,
                              request_id=request_id)
                self.completed.append(record)
                return True
        return False

    async def annotate_response(self, turn_id, request_id, patch):
        """Patch a completed turn's stored response, so a replay is identical."""
        for record in self.records.values():
            if record["_id"] == turn_id and record.get("request_id") == request_id:
                record["response"] = {**(record.get("response") or {}), **patch}
                return True
        return False

    async def fail_turn(self, turn_id, owner_token, *, reason=""):
        for record in self.records.values():
            if record["_id"] == turn_id:
                record.update(status="failed", reason=reason)
                self.failed.append(record)
                return True
        return False

    async def delete_turns(self, conversation_key):
        return 0

    async def get_turn(self, conversation_key, client_message_id):
        return self.records.get((str(conversation_key), str(client_message_id)))

    async def pending_turn(self, conversation_key, now=None):
        for (key, msg_id), record in self.records.items():
            if key == str(conversation_key) and record["status"] == "in_progress":
                return {"client_message_id": msg_id, "status": record["status"],
                        "started_at": None, "attempts": 1}
        return None

    async def abandon_turn(self, conversation_key, client_message_id, now=None):
        record = self.records.get(
            (str(conversation_key), str(client_message_id)))
        if record is None:
            return real_turns.CANCEL_UNKNOWN, None
        if record["status"] == self.STATUS_COMPLETED:
            return real_turns.CANCEL_ALREADY_ANSWERED, record
        if record["status"] != self.STATUS_IN_PROGRESS:
            return real_turns.CANCEL_ALREADY_ENDED, record
        # Clearing the lease owner is what discards the answer: the running
        # worker's fenced completion then matches nothing.
        record.update(status="cancelled", lease_owner=None)
        return real_turns.CANCEL_STOPPED, record

    async def release_conversation_lease_for_turn(self, ref, turn_id):
        self.released_for_turn.append(str(turn_id))
        return True


def install(monkeypatch, module, *, conversations=None, turns=None):
    """Point one route module at the fakes. Returns (conversations, turns)."""
    conversations = conversations or FakeConversations()
    turns = turns or FakeTurns()
    monkeypatch.setattr(module, "conversations", conversations)
    if hasattr(module, "turns"):
        monkeypatch.setattr(module, "turns", turns)
    return conversations, turns
