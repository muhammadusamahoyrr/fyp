"""V2 create answers on the slashless URL -- the one the browser can reach.

Next.js redirects `/api/v1/documents/v2/` to `/api/v1/documents/v2` (308) before
proxying, and the create route existed only at the slashed path. The slashless
request matched only the legacy `GET /documents/{doc_id}` (doc_id="v2") and came
back 405, so every document created from the frontend with the flag on failed.
The smoke run missed it because it called the backend directly.
"""
from __future__ import annotations

import uuid

import httpx
import pytest
from httpx import ASGITransport

from app.core.config import settings
from app.db.collections import get_documents_col

pytestmark = pytest.mark.integration

CLIENT = {"_id": f"cp-client-{uuid.uuid4().hex[:6]}", "role": "client", "is_active": True}


@pytest.fixture
async def http(mongo, monkeypatch):
    from app.dependencies import get_current_user
    from app.main import app

    monkeypatch.setattr(settings, "documents_v2", True)

    async def _current():
        return CLIENT

    app.dependency_overrides[get_current_user] = _current
    try:
        async with httpx.AsyncClient(transport=ASGITransport(app=app),
                                     base_url="http://test/api/v1") as client:
            yield client
    finally:
        app.dependency_overrides.clear()
        await get_documents_col().delete_many({"client_id": CLIENT["_id"]})


@pytest.mark.parametrize("path", ["/documents/v2", "/documents/v2/"],
                         ids=["slashless-browser", "slashed-direct"])
async def test_create_answers_on_both_paths(http, path):
    res = await http.post(path, headers={"Idempotency-Key": str(uuid.uuid4())},
                          json={"template_type": "legal_notice", "title": "Notice"})
    assert res.status_code == 201, res.text
    assert res.json()["template_type"] == "legal_notice"


async def test_both_paths_are_one_route_and_replay_one_document(http):
    key = str(uuid.uuid4())
    body = {"template_type": "legal_notice", "title": "Notice"}
    first = await http.post("/documents/v2", headers={"Idempotency-Key": key}, json=body)
    again = await http.post("/documents/v2/", headers={"Idempotency-Key": key}, json=body)
    assert first.status_code == again.status_code == 201
    assert first.json()["id"] == again.json()["id"]
