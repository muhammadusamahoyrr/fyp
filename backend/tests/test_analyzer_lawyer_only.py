"""Document Analyzer: access policy "registered-lawyer-only".

Any registered account whose role is lawyer may use the analyzer; a client or
an admin may not. It is not a KYC check: no KYC process exists yet.

Decision of 2026-10-03: the analyzer lives on the lawyer dashboard only. Its
reports carry legal-playbook results and AI drafting items that are not
approved for anyone but a lawyer to read, so every analyzer endpoint refuses
a client (403) -- no raw AI output can reach a client response.
"""
from __future__ import annotations

import pytest

from tests._analyzer_support import ATTESTED, http, pdf_with, upload  # noqa: F401 -- fixture

RUN = "run-x"
SOURCE = "src-x"
CLIENT_REFUSED = [
    ("post", ""), ("get", ""), ("get", "/attestation"),
    ("get", f"/runs/{RUN}"), ("post", f"/runs/{RUN}/ocr-text"), ("post", f"/runs/{RUN}/document"),
    ("post", f"/runs/{RUN}/terms"), ("post", f"/runs/{RUN}/cancel"), ("get", f"/runs/{RUN}/text"),
    ("get", f"/runs/{RUN}/graph"), ("get", f"/runs/{RUN}/report"),
    ("get", f"/{SOURCE}"), ("delete", f"/{SOURCE}"),
]


def test_the_access_policy_is_registered_lawyer_only_not_kyc():
    from app.api.v1.routes import document_analyses
    assert document_analyses.ACCESS_POLICY == "registered-lawyer-only"
    assert document_analyses.require_registered_lawyer is document_analyses.require_lawyer


@pytest.mark.parametrize("role", ["client", "admin"])
@pytest.mark.parametrize("method, path", CLIENT_REFUSED)
async def test_a_client_or_admin_is_refused_by_every_analyzer_endpoint(http, method, path, role):
    client, actor = http
    actor.update(role=role)
    response = await client.request(method.upper(), f"/documents/analyses{path}",
                                    headers=ATTESTED, json={} if method == "post" else None)
    assert response.status_code == 403, (method, path, response.status_code)


async def test_a_lawyer_can_upload_and_list(http):
    client, actor = http
    assert actor["role"] == "lawyer"
    created = await upload(client, content=pdf_with(["TENANCY AGREEMENT between the Landlord and the Tenant."]))
    assert created.status_code == 202, created.text     # accepted, queued
    listed = await client.get("/documents/analyses")
    assert listed.status_code == 200
