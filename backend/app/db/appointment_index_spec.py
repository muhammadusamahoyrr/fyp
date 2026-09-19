"""THE index specification for the appointment booking guarantees.

One structure, four consumers: production creation, the mandatory enforcer, the
read-only preflight, and the test fixture's validation. None of them restates an
index, so none of them can be checking a different system from the one that
ships — the failure `v2_index_spec` was written to end, applied to a second
surface rather than solved again.

THE GENERIC MACHINERY IS IMPORTED, NOT COPIED

`IndexSpec`, `evaluate` and the problem codes live in `v2_index_spec`. They are
not V2-specific — they describe an index and compare it against
`index_information()` — and re-deriving them here would produce exactly the
divergence both files exist to prevent. The name is now the only V2 thing about
them; if a third consumer appears, move them to a neutral module rather than
copying them a second time.

WHY THIS CANNOT INHERIT THE V2 FLAG BEHAVIOUR

`enforce_v2_correctness_indexes` reports and returns when DOCUMENTS_V2 is off,
which is right for a feature nothing uses yet: refusing to boot over an index
no write path touches would take a working system down for nothing.

APPOINTMENTS ARE ALREADY LIVE AND HAVE NO FLAG. Every booking writes through
these constraints from the moment the code deploys, so "missing but nothing
depends on it" is not a state this collection can be in. A missing index here
means double-bookings are being accepted right now, silently, and the evidence
is two lawyers in the same room. Hence a separate, unconditional enforcer.

AND IT CANNOT BE BUILT WITH `_try_unique_partial`

That helper ends in a bare `except Exception -> logger.warning -> return`, so a
collection carrying pre-existing duplicates leaves the index ABSENT while every
reader believes the guarantee holds. For a legacy deployment that trade is
defensible. For the guarantee that stops a lawyer being booked twice it is not:
the failure is silent, and it is discovered by the client who turns up.
"""
from __future__ import annotations

from pymongo import ASCENDING

from app.core.constants import AppointmentStatus
from app.db.v2_index_spec import CORRECTNESS, QUERY, IndexSpec

APPOINTMENTS = "appointments"

# The statuses that still HOLD a slot.
#
# Scoping the guard to these two is what makes cancellation release a booking:
# a cancelled row leaves the partial index's scope entirely, so its instants
# stop colliding with anyone else's. Confirmation, by contrast, stays inside the
# scope and keeps its claim — which the superseded `uniq_pending_slot` got
# backwards, since it covered PENDING only and therefore FREED a slot at the
# moment the lawyer agreed to it.
ACTIVE_STATUSES: tuple[str, ...] = (
    AppointmentStatus.PENDING.value,
    AppointmentStatus.CONFIRMED.value,
)

_ACTIVE_FILTER = {"status": {"$in": list(ACTIVE_STATUSES)}}

# Indexes THIS SYSTEM created and has since superseded. Reported by the
# preflight, never dropped by it.
OBSOLETE_INDEXES: tuple[tuple[str, str, str], ...] = (
    (APPOINTMENTS, "uniq_pending_slot",
     "Superseded by uniq_appointment_lawyer_slot. It was unique on "
     "(lawyer_id, scheduled_at) — EXACT START ONLY — so 10:00/60min and "
     "10:30/60min both survived it, and it was scoped to PENDING alone, so "
     "confirming an appointment released the slot it had just been agreed "
     "for. It is no longer created; an existing deployment still carries it. "
     "DROP IT ONLY AFTER the replacement indexes are built and validated: it "
     "is weak, but while it is the only guard in place, dropping it first "
     "leaves no overlap protection at all."),
)


APPOINTMENT_INDEX_REQUIREMENTS: tuple[IndexSpec, ...] = (
    # 1 — a lawyer cannot be in two places at once.
    IndexSpec(
        collection=APPOINTMENTS,
        name="uniq_appointment_lawyer_slot",
        keys=(("lawyer_id", ASCENDING), ("occupied_slots", ASCENDING)),
        kind=CORRECTNESS, unique=True, partial_filter=_ACTIVE_FILTER,
        why=("MULTIKEY UNIQUE: a unique index over an array rejects two "
             "documents that share ANY element, so two active appointments for "
             "one lawyer sharing a single half-hour collide on insert. This is "
             "the correctness guarantee; `has_conflict` is only a friendly "
             "early error and races by construction."),
    ),
    # 2 — and neither can a client.
    IndexSpec(
        collection=APPOINTMENTS,
        name="uniq_appointment_client_slot",
        keys=(("client_id", ASCENDING), ("occupied_slots", ASCENDING)),
        kind=CORRECTNESS, unique=True, partial_filter=_ACTIVE_FILTER,
        why=("The half nobody checked. `has_conflict` only ever asked about "
             "the LAWYER, so one client could book two different lawyers for "
             "the same hour — committing two diaries to a person who can "
             "attend one of them."),
    ),
    # 3 — a retried booking is one booking.
    IndexSpec(
        collection=APPOINTMENTS,
        name="uniq_appointment_idempotency",
        keys=(("client_id", ASCENDING), ("idempotency_key", ASCENDING)),
        kind=CORRECTNESS, unique=True,
        partial_filter={"idempotency_key": {"$type": "string"}},
        why=("PARTIAL ON $type, NOT SPARSE. A compound sparse index still "
             "indexes a document when ANY key is present, and `client_id` is "
             "always present — so every appointment booked without a key would "
             "carry a null and the second one would collide with the first. "
             "The partial filter admits only rows that actually have a key."),
    ),
    # 4 — the expiry sweep's read, and only that.
    IndexSpec(
        collection=APPOINTMENTS,
        name="appointment_pending_expiry",
        keys=(("status", ASCENDING), ("expires_at", ASCENDING)),
        kind=QUERY,
        partial_filter={"status": AppointmentStatus.PENDING.value},
        why=("QUERY, NOT CORRECTNESS. Nothing is wrong without it; the sweep "
             "in services/appointment_expiry_sweep.py simply degrades into a "
             "collection scan on a table that grows for ever. Equality on "
             "`status`, then the RANGE and sort key `expires_at`, in that "
             "order. Partial on pending alone because that is the only status "
             "the sweep ever asks about, and the completed and cancelled rows "
             "it excludes are the ones that accumulate — so the index stays "
             "the size of the open queue rather than of the history. NOT "
             "unique and NOT a TTL index: a TTL would DELETE the appointment "
             "rather than record that it expired, destroying the record of a "
             "legal engagement to save a status write."),
    ),
    # 5 — the outstanding-outcome queue's read.
    IndexSpec(
        collection=APPOINTMENTS,
        name="appointment_confirmed_outcome",
        keys=(("status", ASCENDING), ("end_at", ASCENDING), ("_id", ASCENDING)),
        kind=QUERY,
        partial_filter={"status": AppointmentStatus.CONFIRMED.value},
        why=("QUERY, NOT CORRECTNESS. Nothing is wrong without it. It serves "
             "services/appointment_outcomes.py, which lists the consultations "
             "a lawyer has not reported an outcome for. Equality on `status`, "
             "then the RANGE key `end_at`, then `_id` — which is here because "
             "the queue is KEYSET-paginated on `(end_at, _id)` and the tiebreak "
             "belongs in the index that serves the sort, or every page boundary "
             "costs an in-memory sort of the rows sharing an `end_at`. Partial "
             "on confirmed alone: completed and cancelled rows are the ones "
             "that accumulate for ever, and the queue never asks about them."),
    ),
    # 6 — the reminder sweep's read.
    IndexSpec(
        collection=APPOINTMENTS,
        name="appointment_confirmed_reminder",
        keys=(("status", ASCENDING), ("scheduled_at", ASCENDING),
              ("_id", ASCENDING)),
        kind=QUERY,
        partial_filter={"status": AppointmentStatus.CONFIRMED.value},
        why=("QUERY, NOT CORRECTNESS. Nothing is wrong without it, and it must "
             "never block booking or startup — a missing performance index is "
             "an outage for a reason that is not the reason. It serves "
             "services/appointment_reminders.py, which selects confirmed "
             "appointments starting inside the T-24h and T-1h windows. "
             "Equality on `status`, then the RANGE key `scheduled_at`, then "
             "`_id` — the keyset tiebreak, which belongs in the index serving "
             "the sort or every page boundary costs an in-memory sort of the "
             "rows sharing a start. Partial on confirmed: nothing else is ever "
             "reminded about, and the completed and cancelled rows excluded "
             "are the ones that accumulate for ever."),
    ),
)


def correctness_requirements() -> tuple[IndexSpec, ...]:
    return tuple(s for s in APPOINTMENT_INDEX_REQUIREMENTS if s.kind == CORRECTNESS)


def index_names() -> frozenset[str]:
    """The names this system owns on the appointments collection.

    Used to recognise which constraint a DuplicateKeyError came from WITHOUT
    putting the driver's message anywhere near a response.
    """
    return frozenset(s.name for s in APPOINTMENT_INDEX_REQUIREMENTS)
