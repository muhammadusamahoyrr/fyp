"""LD-03: DELETE /agreements/drafts/{id}, over HTTP.

The route declared ``response_model=StatusResponse`` (``success``, ``message``)
but returned ``{"status": "deleted"}``. FastAPI validates the response after
the handler has run, so the draft was deleted and the request then failed with
a 500 -- the lawyer was told "Could not delete the draft." for a draft that was
already gone.

The existing draft tests call ``agreement_service.delete_draft`` directly, which
is why they never saw it. This one goes through the route.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.constants import AgreementStatus

pytestmark = pytest.mark.integration


@pytest.fixture
async def draft(mongo):
    from app.db.collections import get_agreements_col

    tag = secrets.token_hex(4)
    lawyer = f"LD03-L-{tag}"
    now = datetime.now(timezone.utc)
    doc = {"_id": f"LD03-A-{tag}", "title": "Retainer", "body_html": "Scope and fee.",
           "status": AgreementStatus.DRAFT.value, "created_by": lawyer,
           "version": 1, "created_at": now, "updated_at": now}
    await get_agreements_col().insert_one(doc)
    yield {"id": doc["_id"], "lawyer": lawyer}
    await get_agreements_col().delete_many({"created_by": lawyer})


@pytest.fixture(autouse=True)
def _clear_overrides():
    from app.main import app
    yield
    app.dependency_overrides.clear()


def _as_lawyer(user_id: str) -> AsyncClient:
    from app.dependencies import get_current_user, require_lawyer
    from app.main import app

    who = {"_id": user_id, "role": "lawyer"}
    app.dependency_overrides[get_current_user] = lambda: who
    app.dependency_overrides[require_lawyer] = lambda: who
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test/api/v1")


async def test_deleting_a_draft_returns_200_and_the_draft_is_gone(draft):
    from app.db.collections import get_agreements_col

    async with _as_lawyer(draft["lawyer"]) as client:
        resp = await client.delete(f"/agreements/drafts/{draft['id']}")

    assert resp.status_code == 200, resp.text
    assert resp.json() == {"success": True, "message": "Draft deleted"}
    assert await get_agreements_col().find_one({"_id": draft["id"]}) is None
