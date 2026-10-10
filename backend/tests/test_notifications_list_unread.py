"""GET /notifications lists every unread notification, not just the newest 30.

The list was the newest 30 of all notifications, so an unread one behind 30
newer read ones was never shown, and no badge counted it.
"""
import secrets
from datetime import datetime, timedelta, timezone

import pytest

from app.services import notification_service

pytestmark = pytest.mark.integration


@pytest.fixture
async def user(app_indexes):
    from app.db.collections import get_notifications_col

    uid = f"NL-{secrets.token_hex(4)}"
    yield uid
    await get_notifications_col().delete_many({"user_id": uid})


async def test_an_old_unread_notification_is_still_listed(user):
    from app.db.collections import get_notifications_col

    base = datetime(2026, 10, 1, tzinfo=timezone.utc)
    rows = [{"_id": f"{user}-old", "user_id": user, "type": "case_message", "title": "old unread",
             "body": "", "payload": {}, "read": False, "created_at": base}]
    rows += [{"_id": f"{user}-{i}", "user_id": user, "type": "case_update", "title": f"read {i}",
              "body": "", "payload": {}, "read": True, "created_at": base + timedelta(minutes=i + 1)}
             for i in range(40)]
    await get_notifications_col().insert_many(rows)

    listed = await notification_service.get_notifications(user)
    ids = [n["_id"] for n in listed]
    assert f"{user}-old" in ids
    assert len(listed) == 31                     # the newest 30, plus the unread one
    assert ids[0] == f"{user}-39" and ids[-1] == f"{user}-old", "newest first"


async def test_without_old_unread_the_list_is_the_newest_thirty(user):
    from app.db.collections import get_notifications_col

    base = datetime(2026, 10, 1, tzinfo=timezone.utc)
    await get_notifications_col().insert_many([
        {"_id": f"{user}-{i}", "user_id": user, "type": "case_update", "title": str(i), "body": "",
         "payload": {}, "read": i % 2 == 0, "created_at": base + timedelta(minutes=i)} for i in range(35)])
    listed = await notification_service.get_notifications(user)
    # Unread ones (odd i) older than the newest 30 are added: i = 1, 3.
    assert len(listed) == 32
    assert len({n["_id"] for n in listed}) == len(listed), "no duplicates"
