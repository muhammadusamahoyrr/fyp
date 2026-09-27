"""The legacy letter census tells a new-flow engagement from a broken legacy one.

`scripts/engagement_letter_reconcile.py` was written when every engagement had
a letter, so "retained engagement with no `agreement_id`" meant something had
gone wrong. Since AGREEMENTS_PRODUCT_PLAN.md §17 R5-3 it is the normal state of
every new hire -- and without the split below, the tool would report each one
as a defect, which is how an audit script stops being read.

The split is `appointment_id`: written only by the new flow (§17 R5-1), absent
from every legacy row. What must NOT change is the rest of the detection -- the
orphans, the missing rows, the cancelled letters -- so those are asserted here
too, beside it.
"""
from __future__ import annotations

import secrets
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path("scripts").resolve()))

from app.core.constants import AgreementStatus, EngagementStatus  # noqa: E402

pytestmark = pytest.mark.integration

CLIENT = "RC-CLIENT"
LAWYER = "RC-LAWYER"


@pytest.fixture
async def world(mongo):
    """A clean slate: the census scans the WHOLE collection, so any row left by
    another test would land in its buckets."""
    from app.db.collections import (
        get_agreements_col, get_cases_col, get_engagements_col,
    )

    yield
    await get_engagements_col().delete_many({"client_id": CLIENT})
    await get_agreements_col().delete_many({"created_by": {"$in": [CLIENT, LAWYER]}})
    await get_cases_col().delete_many({"client_id": CLIENT})


async def _engagement(*, appointment: bool, agreement_id=None,
                      status=EngagementStatus.ACCEPTED.value) -> str:
    """One engagement. `appointment=True` makes it a new-flow row."""
    from app.db.collections import get_cases_col, get_engagements_col

    now = datetime.now(timezone.utc)
    eng_id = f"RC-ENG-{secrets.token_hex(5)}"
    case_id = f"RC-CASE-{secrets.token_hex(5)}"
    await get_cases_col().insert_one({
        "_id": case_id, "client_id": CLIENT, "lawyer_id": LAWYER,
        "case_number": f"RC-{case_id[-6:]}", "title": "Matter",
        "created_at": now, "updated_at": now})
    doc = {"_id": eng_id, "case_id": case_id, "client_id": CLIENT,
           "lawyer_id": LAWYER, "status": status,
           "created_at": now, "updated_at": now}
    if appointment:
        doc["appointment_id"] = f"RC-APPT-{secrets.token_hex(5)}"
    if agreement_id is not None:
        doc["agreement_id"] = agreement_id
    await get_engagements_col().insert_one(doc)
    return eng_id


async def _letter(status: str, engagement_id: str | None = None) -> str:
    from app.db.collections import get_agreements_col

    now = datetime.now(timezone.utc)
    agr_id = f"RC-AGR-{secrets.token_hex(5)}"
    await get_agreements_col().insert_one({
        "_id": agr_id, "title": "Engagement Letter", "status": status,
        "engagement_id": engagement_id, "case_id": None,
        "body_html": "Terms.", "parties": [], "audit_log": [],
        "created_by": LAWYER, "created_at": now, "updated_at": now})
    return agr_id


async def _census() -> dict:
    from engagement_letter_reconcile import census
    return await census()


def _affected_ids(report) -> set[str]:
    return {a["engagement_id"] for a in report["affected"]}


def _delta(before: dict, after: dict, bucket: str) -> int:
    """The census scans the WHOLE collection, and other test files leave rows
    in it. So every count here is measured as a change, and every membership
    claim names the ids this test created."""
    return after["buckets"].get(bucket, 0) - before["buckets"].get(bucket, 0)


# ── the split ───────────────────────────────────────────────────────────────

async def test_a_new_flow_engagement_with_no_letter_is_not_a_finding(world):
    """THE regression this change exists for."""
    before = await _census()
    eng_id = await _engagement(appointment=True)

    report = await _census()

    assert _delta(before, report, "new_flow_no_letter") == 1
    assert _delta(before, report, "legacy_never_generated") == 0
    assert "never_generated" not in report["buckets"], "the old bucket is gone"
    assert eng_id not in _affected_ids(report), "a normal new hire was reported"
    assert eng_id not in {r["engagement_id"] for r in report["stranded"]}


async def test_a_legacy_engagement_with_no_letter_is_still_a_finding(world):
    """No `appointment_id`: written before the new flow, so its letter is
    genuinely missing and an auditor should still see it."""
    before = await _census()
    eng_id = await _engagement(appointment=False)

    report = await _census()

    assert _delta(before, report, "legacy_never_generated") == 1
    assert eng_id in _affected_ids(report)
    row = next(a for a in report["affected"] if a["engagement_id"] == eng_id)
    assert row["letter_state"] == "legacy_never_generated"
    assert row["reconcilable"] is False, "a missing letter is not auto-repairable"


async def test_the_two_are_counted_separately_in_one_run(world):
    before = await _census()
    new_id = await _engagement(appointment=True)
    legacy_id = await _engagement(appointment=False)

    report = await _census()

    assert _delta(before, report, "new_flow_no_letter") == 1
    assert _delta(before, report, "legacy_never_generated") == 1
    assert legacy_id in _affected_ids(report)
    assert new_id not in _affected_ids(report)


# ── everything else the census must keep detecting ──────────────────────────

async def test_a_cancelled_letter_is_still_stranded_and_reconcilable(world):
    before = await _census()
    agr_id = await _letter(AgreementStatus.CANCELLED.value)
    eng_id = await _engagement(appointment=False, agreement_id=agr_id)

    report = await _census()

    assert eng_id in {a["engagement_id"] for a in report["stranded"]}
    assert _delta(before, report, AgreementStatus.CANCELLED.value) == 1


async def test_a_dangling_agreement_id_is_still_reported(world):
    before = await _census()
    eng_id = await _engagement(appointment=False, agreement_id="RC-GONE")

    report = await _census()

    assert _delta(before, report, "letter_row_missing") == 1
    assert eng_id in _affected_ids(report)


async def test_an_executed_letter_is_still_clean(world):
    before = await _census()
    agr_id = await _letter(AgreementStatus.EXECUTED.value)
    eng_id = await _engagement(appointment=False, agreement_id=agr_id)

    report = await _census()

    assert _delta(before, report, "executed_ok") == 1
    assert eng_id not in _affected_ids(report)


async def test_a_new_flow_engagement_does_not_hide_a_real_orphan(world):
    """The six census orphans are found by a REVERSE scan, which the split does
    not touch: a letter whose engagement is gone is still reported."""
    await _engagement(appointment=True)
    orphan = await _letter(AgreementStatus.PENDING.value,
                           engagement_id="RC-NO-SUCH-ENGAGEMENT")

    report = await _census()

    assert orphan in {o["agreement_id"] for o in report["orphans"]}


async def test_the_scan_still_covers_every_retained_status(world):
    """`completed` and `terminated` are retained too, and a legacy one of
    either still counts as a finding."""
    before = await _census()
    ids = {await _engagement(appointment=False, status=s)
           for s in (EngagementStatus.COMPLETED.value,
                     EngagementStatus.TERMINATED.value)}

    report = await _census()

    assert report["retained_engagements"] == before["retained_engagements"] + 2
    assert ids <= _affected_ids(report)
