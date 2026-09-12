"""The admin case breakdown must account for every status that can exist.

`total_cases` counts every row in the collection. `cases_by_status` was a
hand-written list of five statuses, which was complete until intake started
producing `draft` cases — from then on the two disagreed by exactly the number of
unconfirmed drafts, and nothing said so. A dashboard whose parts do not sum to
its own total is worse than one that is plainly wrong, because it reads as fine.

The fix reads `CaseStatus`. These tests pin that, so adding a sixth status
cannot quietly reintroduce the gap.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timezone

import pytest

from app.core.constants import CaseStatus
from app.services import admin_service

pytestmark = pytest.mark.integration


@pytest.fixture
async def cases(mongo):
    """One case in every status, so no status can be missed by accident."""
    from app.db.collections import get_cases_col

    tag = secrets.token_hex(4)
    now = datetime.now(timezone.utc)
    made = []
    for status in CaseStatus:
        case_id = f"AS-{tag}-{status.value}"
        made.append(case_id)
        await get_cases_col().insert_one({
            "_id": case_id,
            "case_number": f"ATT-2026-{secrets.token_hex(3).upper()}",
            "client_id": f"AS-C-{tag}", "lawyer_id": None,
            "case_type": "civil", "province": "punjab",
            "status": status.value, "title": "t", "description": "d",
            "milestones": [], "hearing_dates": [],
            "created_at": now, "updated_at": now,
        })

    yield {"tag": tag, "ids": made}

    await get_cases_col().delete_many({"_id": {"$in": made}})


async def test_every_status_appears_in_the_breakdown(cases):
    stats = await admin_service.get_analytics()

    missing = [s.value for s in CaseStatus if s.value not in stats["cases_by_status"]]
    assert missing == [], f"statuses absent from the breakdown: {missing}"


async def test_drafts_are_reported_rather_than_omitted(cases):
    """The specific status whose absence caused the gap."""
    stats = await admin_service.get_analytics()

    assert stats["cases_by_status"].get(CaseStatus.DRAFT.value, 0) >= 1


async def test_the_breakdown_accounts_for_every_known_status(cases):
    """The invariant that actually broke.

    Stated so it cannot go flaky on real data. A bare
    `sum(cases_by_status) == total_cases` would fail on any row carrying a status
    outside the enum — legacy or hand-edited — which is a different problem and
    not this test's business. So the shortfall is compared against exactly that
    population: whatever the breakdown fails to account for must be off-enum
    rows, nothing else.

    Before the fix the gap included every draft, and drafts ARE on the enum, so
    this fails — which is the point.
    """
    from app.db.collections import get_cases_col

    stats = await admin_service.get_analytics()
    unaccounted = stats["total_cases"] - sum(stats["cases_by_status"].values())
    off_enum = await get_cases_col().count_documents(
        {"status": {"$nin": [s.value for s in CaseStatus]}})

    assert unaccounted == off_enum, (
        f"{unaccounted - off_enum} case(s) with a known status are counted by "
        f"total_cases but missing from cases_by_status"
    )
