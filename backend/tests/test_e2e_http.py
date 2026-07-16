"""End-to-end HTTP tests.

These drive the REAL ASGI app: real routing, real request validation, real
`response_model` serialisation, real auth dependency. Nothing is stubbed except
the authenticated identity — everything a request touches on the way in and out
is the production code path.

They deliberately target the deterministic legal engines (bail, calculators) so
the suite stays fast, offline and repeatable: no LLM, no database, no network.
An E2E that needed a live model would be too flaky to run on every push, which is
the same as not having one.
"""
import httpx
import pytest

from app.dependencies import get_current_user
from app.main import app

API = "/api/v1"

FAKE_USER = {"_id": "test-user", "email": "test@example.com", "role": "client",
             "is_active": True}


@pytest.fixture
async def client():
    """ASGI client with the authenticated user overridden.

    No lifespan is run, so Mongo/Chroma are never touched — these routes only hit
    pure services.
    """
    app.dependency_overrides[get_current_user] = lambda: FAKE_USER
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
async def anon_client():
    """No auth override — used to prove the routes are actually protected."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ── liveness ──────────────────────────────────────────────────────────────────

async def test_health_endpoint(anon_client):
    r = await anon_client.get("/")
    assert r.status_code == 200


# ── auth is enforced ──────────────────────────────────────────────────────────

async def test_protected_route_rejects_an_anonymous_caller(anon_client):
    r = await anon_client.post(f"{API}/calculators/court-fee", json={
        "claim_value": 500_000, "suit_type": "money_recovery", "province": "punjab"})
    assert r.status_code in (401, 403)


# ── court fee: full HTTP round trip ───────────────────────────────────────────

async def test_court_fee_end_to_end(client):
    r = await client.post(f"{API}/calculators/court-fee", json={
        "claim_value": 500_000, "suit_type": "money_recovery", "province": "punjab"})

    assert r.status_code == 200
    body = r.json()
    assert body["court_fee"] == 37_500          # 7.5% ad valorem
    assert body["computation"] == "ad_valorem"
    # The "this is an estimate" caveat must survive serialisation — a user acting
    # on a bare number is exactly the failure this field exists to prevent.
    assert body["verify"]
    assert body["legal_basis"]


async def test_court_fee_rejects_an_invalid_suit_type(client):
    """suit_type/province are Literal-constrained. Before that they were plain
    `str`, so this request returned 200 and a fee for a suit type that does not
    exist."""
    r = await client.post(f"{API}/calculators/court-fee", json={
        "claim_value": 500_000, "suit_type": "not_a_real_suit", "province": "punjab"})
    assert r.status_code == 422


async def test_court_fee_rejects_an_invalid_province(client):
    r = await client.post(f"{API}/calculators/court-fee", json={
        "claim_value": 500_000, "suit_type": "money_recovery", "province": "atlantis"})
    assert r.status_code == 422


async def test_court_fee_rejects_a_negative_claim(client):
    r = await client.post(f"{API}/calculators/court-fee", json={
        "claim_value": -1, "suit_type": "money_recovery", "province": "punjab"})
    assert r.status_code == 422


async def test_court_fee_applies_documented_defaults_when_fields_are_omitted(client):
    """Omitted fields default rather than 422. That is the existing API contract —
    pinning it here so the defaults are a deliberate choice, not an accident.

    NOTE: a caller who omits `province` silently gets the PUNJAB schedule, and the
    response cites the Punjab Finance Acts as its legal_basis. The rates happen to
    be identical across provinces today, so the number is right and the citation is
    not. Making province required would be the stricter contract."""
    r = await client.post(f"{API}/calculators/court-fee", json={"claim_value": 500_000})
    assert r.status_code == 200
    body = r.json()
    assert body["suit_type"] == "money_recovery"
    assert body["province"] == "punjab"


# ── bail: full HTTP round trip ────────────────────────────────────────────────

async def test_bail_check_end_to_end(client):
    r = await client.post(f"{API}/bail/check", json={
        "law": "PPC", "section": "379", "arrested": True})

    assert r.status_code == 200
    body = r.json()
    assert body["found"] is True
    assert body["offence"]["bailable"] is False
    assert "CrPC s.497" in body["guidance"]["sections"]   # post-arrest route
    assert body["disclaimer"]


async def test_bail_check_unknown_section_is_a_200_with_found_false(client):
    """An unknown offence is a legitimate answer ("not in the reference list"),
    not a server error — the caller still gets the general rule and a disclaimer."""
    r = await client.post(f"{API}/bail/check", json={
        "law": "PPC", "section": "999-Z", "arrested": True})

    assert r.status_code == 200
    body = r.json()
    assert body["found"] is False
    assert body["disclaimer"]


async def test_bail_search_end_to_end(client):
    r = await client.get(f"{API}/bail/search", params={"q": "qatl-e-amd"})

    assert r.status_code == 200
    results = r.json()["results"]
    assert results[0]["section"] == "302"
    # Aliases are an internal search aid and must never reach the API surface.
    assert "aliases" not in results[0]


async def test_bail_search_for_a_non_offence_returns_empty(client):
    r = await client.get(f"{API}/bail/search", params={"q": "khula"})
    assert r.status_code == 200
    assert r.json()["results"] == []


# ── OpenAPI ───────────────────────────────────────────────────────────────────

async def test_openapi_spec_is_served_and_documents_the_routes(anon_client):
    r = await anon_client.get("/openapi.json")
    assert r.status_code == 200
    spec = r.json()
    assert spec["info"]["title"] == "Attorney.AI API"
    assert f"{API}/bail/check" in spec["paths"]
    assert f"{API}/calculators/court-fee" in spec["paths"]
