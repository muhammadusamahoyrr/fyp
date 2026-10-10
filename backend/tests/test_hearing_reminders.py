"""The day before a hearing, both parties are reminded, once per date."""
import secrets
from datetime import datetime, timedelta, timezone

import pytest

from app.services import hearing_reminders as hr

pytestmark = pytest.mark.integration

# 18:00 PKT on 10 Nov; "tomorrow" is 11 Nov in Pakistan.
NOW = datetime(2026, 11, 10, 13, 0, tzinfo=timezone.utc)


def _midnight(y, m, d):
    # How add_hearing stores a picked day: midnight UTC of that day (naive).
    return datetime(y, m, d)


@pytest.fixture
async def world(app_indexes):
    from app.db.collections import get_cases_col, get_notifications_col

    from app.db.collections import get_users_col

    tag = secrets.token_hex(4)
    ids = {"tag": tag, "client": f"HR-C-{tag}", "lawyer": f"HR-L-{tag}"}
    # Live accounts: reminders go only to accounts that exist and are active.
    await get_users_col().insert_many([
        {"_id": ids["client"], "role": "client", "is_active": True, "email": f"{ids['client']}@x.invalid"},
        {"_id": ids["lawyer"], "role": "lawyer", "is_active": True, "email": f"{ids['lawyer']}@x.invalid"},
    ])
    yield ids
    await get_cases_col().delete_many({"_id": {"$regex": f"^HR-{tag}"}})
    await get_notifications_col().delete_many({"user_id": {"$in": [ids["client"], ids["lawyer"]]}})
    await get_users_col().delete_many({"_id": {"$in": [ids["client"], ids["lawyer"]]}})


async def _case(world, suffix, hearings, status="in_progress", lawyer=True):
    from app.db.collections import get_cases_col

    await get_cases_col().insert_one({
        "_id": f"HR-{world['tag']}-{suffix}", "title": f"Case {suffix}", "status": status,
        "client_id": world["client"], "lawyer_id": world["lawyer"] if lawyer else None,
        "hearing_dates": hearings, "created_at": NOW,
    })


async def _notes(world):
    from app.db.collections import get_notifications_col

    return await get_notifications_col().find(
        {"user_id": {"$in": [world["client"], world["lawyer"]]}}).to_list(None)


async def test_tomorrows_hearing_reminds_client_and_lawyer_once(world):
    await _case(world, "a", [{"_id": "h1", "date": _midnight(2026, 11, 11), "time": "10:00",
                              "court": "Civil Court Lahore", "outcome": None}])
    first = await hr.send_due_hearing_reminders(now=NOW)
    assert first["sent"] == 2
    notes = await _notes(world)
    assert sorted(n["user_id"] for n in notes) == sorted([world["client"], world["lawyer"]])
    assert all(n["type"] == "hearing_reminder" for n in notes)
    assert "tomorrow at 10:00, Civil Court Lahore" in notes[0]["body"]
    assert notes[0]["payload"]["case_id"] == f"HR-{world['tag']}-a"

    again = await hr.send_due_hearing_reminders(now=NOW + timedelta(hours=1))
    assert again["sent"] == 0 and again["deduplicated"] == 2
    assert len(await _notes(world)) == 2


async def test_a_rescheduled_hearing_is_reminded_again_for_its_new_date(world):
    from app.db.collections import get_cases_col

    await _case(world, "a", [{"_id": "h1", "date": _midnight(2026, 11, 11), "outcome": None}])
    await hr.send_due_hearing_reminders(now=NOW)
    await get_cases_col().update_one({"_id": f"HR-{world['tag']}-a"},
                                     {"$set": {"hearing_dates.0.date": _midnight(2026, 11, 12)}})
    later = await hr.send_due_hearing_reminders(now=NOW + timedelta(days=1))
    assert later["sent"] == 2
    assert len(await _notes(world)) == 4


@pytest.mark.parametrize("kind", ["decided", "closed", "today", "day_after"])
async def test_hearings_that_are_not_tomorrow_or_no_longer_bind_are_skipped(world, kind):
    day = {"today": _midnight(2026, 11, 10), "day_after": _midnight(2026, 11, 12)}.get(kind, _midnight(2026, 11, 11))
    await _case(world, "a", [{"_id": "h1", "date": day, "outcome": "adjourned" if kind == "decided" else None}],
                status="closed" if kind == "closed" else "in_progress")
    result = await hr.send_due_hearing_reminders(now=NOW)
    assert result["sent"] == 0
    assert await _notes(world) == []


async def test_a_case_without_a_lawyer_reminds_only_the_client(world):
    await _case(world, "a", [{"_id": "h1", "date": _midnight(2026, 11, 11), "outcome": None}], lawyer=False)
    assert (await hr.send_due_hearing_reminders(now=NOW))["sent"] == 1


def test_the_pkt_day_of_a_stored_date():
    assert hr.hearing_day(datetime(2026, 11, 11)).isoformat() == "2026-11-11"
    assert hr.hearing_day(datetime(2026, 11, 10, 19, 0, tzinfo=timezone.utc)).isoformat() == "2026-11-11"


def test_the_scheduler_is_off_by_default():
    from app.core.config import Settings

    assert Settings.model_fields["hearing_reminders_enabled"].default is False


# ── starvation: already-sent reminders must not use up the per-run limit ────

async def test_later_hearings_are_reached_once_earlier_ones_are_reminded(world):
    """Each run counted every candidate, sent or not, against `limit`, and
    returned at the limit. Once the first `limit` reminders had gone out, every
    later run re-counted them as duplicates and never reached the rest."""
    from app.db.collections import get_cases_col, get_notifications_col

    day = datetime(2026, 11, 11)
    await get_cases_col().insert_many([
        {"_id": f"HR-{world['tag']}-m{i:03d}", "case_number": f"HR-{world['tag']}-m{i:03d}", "lawyer_id": world["lawyer"], "client_id": world["client"],
         "title": f"Case {i}", "status": "in_progress", "created_at": NOW,
         "hearing_dates": [{"_id": f"h{i}", "date": day, "time": "10:00", "outcome": None}]}
        for i in range(40)                              # 40 hearings x 2 recipients = 80 reminders
    ])
    first = await hr.send_due_hearing_reminders(now=NOW, limit=50)
    assert first["sent"] == 50
    second = await hr.send_due_hearing_reminders(now=NOW + timedelta(minutes=30), limit=50)
    assert second["sent"] == 30, f"later hearings were never reached: {second}"
    third = await hr.send_due_hearing_reminders(now=NOW + timedelta(hours=1), limit=50)
    assert third["sent"] == 0, "a reminder was sent twice"
    total = await get_notifications_col().count_documents(
        {"user_id": {"$in": [world["client"], world["lawyer"]]}, "type": "hearing_reminder"})
    assert total == 80


async def test_inactive_recipients_do_not_use_up_the_limit(world):
    from app.db.collections import get_cases_col, get_users_col

    day = datetime(2026, 11, 11)
    await get_users_col().update_one({"_id": world["lawyer"]}, {"$set": {"is_active": False}})
    await get_cases_col().insert_many([
        {"_id": f"HR-{world['tag']}-i{i:03d}", "case_number": f"HR-{world['tag']}-i{i:03d}", "lawyer_id": world["lawyer"], "client_id": world["client"],
         "title": f"Case {i}", "status": "in_progress", "created_at": NOW,
         "hearing_dates": [{"_id": f"h{i}", "date": day, "outcome": None}]}
        for i in range(10)
    ])
    result = await hr.send_due_hearing_reminders(now=NOW, limit=10)
    assert result["sent"] == 10, f"skipped (inactive) recipients consumed the limit: {result}"
