"""A completed consultation, the prerequisite for every NEW hire.

`request_engagement` refuses unless the client names a completed appointment
with the same lawyer (AGREEMENTS_PRODUCT_PLAN.md §17 R5-1). Tests whose subject
is something AFTER that gate -- the case guards, the claim, termination -- need
one to get there, and this writes it directly rather than driving the booking
flow, which has its own tests and its own clock rules.

The row is shaped like one `book_appointment` + `complete_appointment` would
leave: a slot that has ended, status `completed`. It carries no
`occupied_slots` and no `idempotency_key`, so it cannot collide with the
appointment unique indexes, which only cover active rows and string keys.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from app.core.constants import AppointmentStatus


async def seed_completed_appointment(
    client_id: str,
    lawyer_id: str,
    case_id: str | None = None,
    **overrides,
) -> str:
    """Insert a finished consultation and return its id.

    `overrides` replace any field, which is how the negative tests build a
    consultation that is pending, still in progress, or someone else's.
    """
    from app.db.collections import get_appointments_col

    now = datetime.now(timezone.utc)
    start = now - timedelta(days=2)
    doc = {
        "_id": f"test-appt-{secrets.token_hex(6)}",
        "client_id": client_id,
        "lawyer_id": lawyer_id,
        "case_id": case_id,
        "scheduled_at": start,
        "end_at": start + timedelta(minutes=30),
        "duration_minutes": 30,
        "status": AppointmentStatus.COMPLETED.value,
        "mode": "video",
        "schedule_version": 1,
        "created_at": start - timedelta(days=1),
        "updated_at": start + timedelta(minutes=30),
    }
    doc.update(overrides)
    await get_appointments_col().insert_one(doc)
    return doc["_id"]


async def delete_appointments_for(*user_ids: str) -> None:
    """Remove every appointment these users are party to. For teardown."""
    from app.db.collections import get_appointments_col

    ids = [u for u in user_ids if u]
    await get_appointments_col().delete_many(
        {"$or": [{"client_id": {"$in": ids}}, {"lawyer_id": {"$in": ids}}]})
