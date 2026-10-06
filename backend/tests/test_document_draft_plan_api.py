"""HTTP contract and role gate for the V2 draft-plan resource."""
from __future__ import annotations

import uuid

import httpx
import pytest
from httpx import ASGITransport

from app.core.config import settings
from app.db.collections import get_document_draft_plans_col

pytestmark = pytest.mark.integration

CLIENT_ID = f"plan-api-{uuid.uuid4().hex[:8]}"


@pytest.fixture
async def http(mongo, monkeypatch):
    from app.dependencies import get_current_user
    from app.main import app

    actor = {"_id": CLIENT_ID, "role": "client", "is_active": True}
    monkeypatch.setattr(settings, "documents_v2", True)

    async def current():
        return actor

    app.dependency_overrides[get_current_user] = current
    try:
        async with httpx.AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test/api/v1",
        ) as client:
            yield client, actor
    finally:
        app.dependency_overrides.clear()
        await get_document_draft_plans_col().delete_many({"owner_id": CLIENT_ID})


@pytest.mark.parametrize("path", [
    "/documents/v2/plans", "/documents/v2/plans/",
])
async def test_browser_and_direct_create_paths_both_work(http, path):
    client, _actor = http
    response = await client.post(
        path,
        headers={"Idempotency-Key": str(uuid.uuid4())},
        json={"prompt": "Please prepare a document about my situation"},
    )
    assert response.status_code == 201, response.text
    assert response.json()["status"] == "needs_template"
    assert response.json()["questions"][0]["field"] == "template_type"


async def test_create_requires_an_idempotency_key(http):
    client, _actor = http
    response = await client.post(
        "/documents/v2/plans",
        json={"prompt": "Please prepare a document about my situation"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "missing_idempotency_key"


async def test_lawyers_cannot_use_the_client_prompt_endpoint(http):
    client, actor = http
    actor["role"] = "lawyer"
    response = await client.post(
        "/documents/v2/plans",
        headers={"Idempotency-Key": str(uuid.uuid4())},
        json={"prompt": "Please prepare a document about my situation"},
    )
    assert response.status_code == 403


async def test_the_whole_resource_is_inert_while_v2_is_off(http, monkeypatch):
    client, _actor = http
    monkeypatch.setattr(settings, "documents_v2", False)
    response = await client.post(
        "/documents/v2/plans",
        headers={"Idempotency-Key": str(uuid.uuid4())},
        json={"prompt": "Please prepare a document about my situation"},
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "feature_disabled"

