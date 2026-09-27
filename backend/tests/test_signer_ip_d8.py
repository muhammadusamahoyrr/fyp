"""D8: the IP recorded against a signature must be one we can stand behind.

`core/client_ip.py` was written to answer "can we say, and stand behind, where
this request came from?", and `executed_pdf` already asks it -- a download row
stores `ip_address if ip_verifiable else None`. The three routes that write an
address into the PERMANENT audit log did not: they read `request.client.host`
directly, so behind a reverse proxy every signature recorded the proxy, and
`agreement_pdf` prints that value on the evidence certificate as the signer's
origin. A false statement about a real person, on every document.

The helper itself was already well tested in `test_agreement_pdf_3e.py`. What
was missing is proof that the signing paths CALL it -- a correct helper nobody
uses protects nothing -- so these tests assert at the route boundary and at the
stored row, not at `client_ip`.

The same rule is asserted three times, once per writing path, because the
defect was three independent copies of one mistake and a single shared test
would let two of them drift back.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.core.constants import CaseStatus

LAWYER = "D8-LAWYER"
CLIENT = "D8-CLIENT"

TYPED_SIGNATURE = "Lister Ahmed Khan, Advocate"
CLIENT_SIGNATURE = "Ayesha Bibi"

#: The address a hostile client puts in `X-Forwarded-For` hoping it is believed.
SPOOFED = "1.2.3.4"
#: The address the socket actually reports.
PEER = "203.0.113.9"
#: A configured reverse proxy.
PROXY = "10.0.0.1"
#: The real client, as a trusted proxy would report it.
BEHIND_PROXY = "198.51.100.7"


def _Req(peer=None, headers=None):
    """A REAL `starlette.requests.Request`, not a stand-in.

    `test_agreement_pdf_3e.py` proves `client_ip` against a two-attribute stub,
    which is right for a unit test of the helper. These tests call the route
    functions themselves, and the send route is wrapped by SlowAPI, which
    refuses anything that is not a genuine Request -- so the scope is built by
    hand and the real object constructed from it. It reads `client` and
    `headers` exactly as the running server would.
    """
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/",
        "raw_path": b"/",
        "query_string": b"",
        "root_path": "",
        "server": ("testserver", 80),
        "headers": [(k.lower().encode(), v.encode())
                    for k, v in (headers or {}).items()],
        "client": (peer, 40000) if peer else None,
        # SlowAPI reads `request.app.state.limiter`; the limiter itself is
        # disabled per-test below so these assertions never depend on a quota.
        "app": _app(),
    }
    from starlette.requests import Request
    return Request(scope)


def _app():
    from app.main import app
    return app


@pytest.fixture
def no_proxies(monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "trusted_proxies", "", raising=False)
    return settings


@pytest.fixture
def one_proxy(monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "trusted_proxies", PROXY, raising=False)
    return settings


@pytest.fixture
def captured(monkeypatch):
    """Replace all three service entry points with recorders.

    The assertion is about what the ROUTE resolved and forwarded, so the
    service is out of the picture here; it gets its own tests below.
    """
    seen: dict = {}

    # The send route is rate limited (D6). That rule has its own tests; here it
    # would only make the third assertion in a run depend on the first two.
    from app.core.rate_limit import limiter
    monkeypatch.setattr(limiter, "enabled", False, raising=False)

    def _recorder(name):
        async def _fn(**kwargs):
            seen[name] = kwargs
            return {"_id": "x"}
        return _fn

    from app.services import agreement_service
    for fn in ("submit_signature", "decline_agreement", "sign_and_send_draft"):
        monkeypatch.setattr(agreement_service, fn, _recorder(fn), raising=True)
    return seen


# ── driving the three routes ────────────────────────────────────────────────

async def _call_sign(request):
    from app.api.v1.routes.agreements import sign_agreement
    from app.schemas.agreement import SignatureSubmit

    return await sign_agreement(
        agreement_id="A1",
        body=SignatureSubmit(method="typed", signature_data=CLIENT_SIGNATURE),
        request=request,
        current_user={"_id": CLIENT},
    )


async def _call_decline(request):
    from app.api.v1.routes.agreements import decline_agreement
    from app.schemas.agreement import AgreementDecline

    return await decline_agreement(
        agreement_id="A1",
        body=AgreementDecline(reason="The fee is wrong."),
        request=request,
        current_user={"_id": CLIENT},
    )


async def _call_send(request):
    from app.api.v1.routes.agreements import sign_and_send_draft
    from app.schemas.agreement import DraftSignAndSend

    return await sign_and_send_draft(
        agreement_id="A1",
        body=DraftSignAndSend(
            expected_version=1,
            expected_body_sha256="0" * 64,
            method="typed",
            signature_data=TYPED_SIGNATURE,
            consent=True,
        ),
        request=request,
        current_user={"_id": LAWYER},
        idempotency_key="k-" + secrets.token_urlsafe(8),
    )


ROUTES = [
    pytest.param(_call_sign, "submit_signature", id="sign"),
    pytest.param(_call_decline, "decline_agreement", id="decline"),
    pytest.param(_call_send, "sign_and_send_draft", id="send"),
]


# ── 1-3. the spoof, once per writing path ───────────────────────────────────

@pytest.mark.parametrize("call,recorded_as", ROUTES)
async def test_a_forwarding_header_from_an_untrusted_peer_is_not_the_signer_ip(
        call, recorded_as, captured, no_proxies):
    """THE defect. No proxy is configured, so `X-Forwarded-For` is just text a
    caller sent, and believing it would let a signer write their own origin
    into the evidence record."""
    await call(_Req(peer=PEER, headers={"x-forwarded-for": SPOOFED}))

    kwargs = captured[recorded_as]
    assert kwargs["ip_address"] != SPOOFED, "the header was believed"
    assert kwargs["ip_address"] == PEER, "the socket address is what we hold"


# ── 4. a configured proxy IS believed, end to end ───────────────────────────

@pytest.mark.parametrize("call,recorded_as", ROUTES)
async def test_a_trusted_proxy_resolves_the_real_client(
        call, recorded_as, captured, one_proxy):
    """The leftmost entry is the client; the rest of the chain is
    intermediaries. Getting this wrong in the other direction -- ignoring a
    real proxy -- records the proxy on every signature."""
    await call(_Req(peer=PROXY,
                    headers={"x-forwarded-for": f"{BEHIND_PROXY}, {PROXY}"}))

    kwargs = captured[recorded_as]
    assert kwargs["ip_address"] == BEHIND_PROXY
    assert kwargs["ip_verifiable"] is True


# ── 5. unverifiable is reported as such ─────────────────────────────────────

@pytest.mark.parametrize("call,recorded_as", ROUTES)
async def test_an_unverifiable_origin_is_flagged_not_forwarded_as_fact(
        call, recorded_as, captured, one_proxy):
    """A forwarding header arrived, but from a peer that is not our proxy. The
    address we hold is that unknown machine's, not the client's, so the route
    must say so rather than passing it down as though it were the signer's."""
    await call(_Req(peer="192.0.2.50", headers={"x-forwarded-for": SPOOFED}))

    kwargs = captured[recorded_as]
    assert kwargs["ip_verifiable"] is False


# ── 6. the current deployment is unchanged ──────────────────────────────────

@pytest.mark.parametrize("call,recorded_as", ROUTES)
async def test_with_no_proxy_a_direct_client_is_recorded_as_before(
        call, recorded_as, captured, no_proxies):
    """Nothing is configured and nothing is forwarded -- today's production
    shape. The socket address is the client's and must still be recorded, or
    this fix would quietly empty the field it exists to protect."""
    await call(_Req(peer=PEER))

    kwargs = captured[recorded_as]
    assert kwargs["ip_address"] == PEER
    assert kwargs["ip_verifiable"] is True


# ── the stored row ──────────────────────────────────────────────────────────

@pytest.fixture
async def world(mongo_transactional):
    from app.db.collections import (
        get_agreements_col, get_cases_col, get_event_outbox_col, get_users_col,
    )

    await get_users_col().insert_many([
        {"_id": LAWYER, "full_name": "Adv Lister", "role": "lawyer",
         "email": "l@d8.test", "is_active": True,
         "lawyer_profile": {"kyc_verified": True, "specializations": ["civil"]}},
        {"_id": CLIENT, "full_name": "The Client", "role": "client",
         "email": "c@d8.test", "is_active": True},
    ])
    yield
    ids = [LAWYER, CLIENT]
    await get_users_col().delete_many({"_id": {"$in": ids}})
    await get_cases_col().delete_many({"client_id": CLIENT})
    await get_agreements_col().delete_many({"created_by": {"$in": ids}})
    await get_event_outbox_col().delete_many({"payload.recipient_id": {"$in": ids}})


async def _case() -> str:
    from app.db.collections import get_cases_col

    now = datetime.now(timezone.utc)
    cid = secrets.token_urlsafe(12)
    await get_cases_col().insert_one({
        "_id": cid, "client_id": CLIENT, "lawyer_id": LAWYER,
        "title": "A matter", "case_number": f"D8-{cid[:8]}",
        "status": CaseStatus.IN_PROGRESS.value,
        "milestones": [], "created_at": now, "updated_at": now,
    })
    return cid


async def _sent(*, ip_verifiable: bool) -> dict:
    """A draft signed and sent by the lawyer, with the given verifiability."""
    from app.services import agreement_service

    d = await agreement_service.create_draft(
        title="Retainer", body_html="Fees are 40% of recovery.",
        client_id=CLIENT, creator_id=LAWYER, case_id=await _case())
    await agreement_service.sign_and_send_draft(
        agreement_id=d["_id"], creator_id=LAWYER,
        expected_version=d["version"],
        expected_body_sha256=agreement_service.body_digest(d["body_html"]),
        method="typed", signature_data=TYPED_SIGNATURE, consent=True,
        idempotency_key=secrets.token_urlsafe(12),
        ip_address=SPOOFED, ip_verifiable=ip_verifiable)
    return d


async def _entries(agreement_id: str, action: str) -> list[dict]:
    from app.db.collections import get_agreements_col

    row = await get_agreements_col().find_one({"_id": agreement_id})
    return [e for e in (row.get("audit_log") or []) if e.get("action") == action]


@pytest.mark.integration
async def test_an_unverifiable_address_is_not_written_into_the_audit_log(world):
    """The gate `executed_pdf` already applies, applied where it matters more:
    a download row is a log, an audit entry is evidence."""
    d = await _sent(ip_verifiable=False)

    sent = await _entries(d["_id"], "sent")
    assert len(sent) == 1
    assert sent[0]["ip_address"] is None, "an address we cannot stand behind was stored"


@pytest.mark.integration
async def test_a_verifiable_address_is_written(world):
    """The other half: the gate must not simply discard everything."""
    d = await _sent(ip_verifiable=True)

    sent = await _entries(d["_id"], "sent")
    assert sent[0]["ip_address"] == SPOOFED


@pytest.mark.integration
async def test_signing_applies_the_same_gate(world):
    from app.services import agreement_service

    d = await _sent(ip_verifiable=True)
    await agreement_service.submit_signature(
        agreement_id=d["_id"], user_id=CLIENT, method="typed",
        signature_data=CLIENT_SIGNATURE,
        ip_address=BEHIND_PROXY, ip_verifiable=False)

    signed = await _entries(d["_id"], "signed")
    assert signed and signed[-1]["ip_address"] is None


@pytest.mark.integration
async def test_declining_applies_the_same_gate(world):
    from app.services import agreement_service

    d = await _sent(ip_verifiable=True)
    await agreement_service.decline_agreement(
        agreement_id=d["_id"], user_id=CLIENT, reason="The fee is wrong.",
        ip_address=BEHIND_PROXY, ip_verifiable=False)

    declined = await _entries(d["_id"], "declined")
    assert declined and declined[-1]["ip_address"] is None


# ── 7. the certificate ──────────────────────────────────────────────────────

@pytest.mark.integration
async def test_the_certificate_does_not_print_an_unverifiable_origin(world):
    """The whole point of the gate. `agreement_pdf` reads `audit_log` straight
    onto the evidence page, so an address that should never have been stored is
    an address that gets PRINTED as the signer's origin."""
    from app.services import agreement_service
    from app.services.agreement_pdf import IP_NOT_RECORDED, build_executed_pdf
    from app.db.collections import get_agreements_col

    d = await _sent(ip_verifiable=False)
    await agreement_service.submit_signature(
        agreement_id=d["_id"], user_id=CLIENT, method="typed",
        signature_data=CLIENT_SIGNATURE,
        ip_address=SPOOFED, ip_verifiable=False)

    row = await get_agreements_col().find_one({"_id": d["_id"]})
    text = _pdf_text(build_executed_pdf(row))

    assert SPOOFED not in text, "an unverifiable address reached the certificate"
    assert IP_NOT_RECORDED in text


def _pdf_text(pdf: bytes) -> str:
    from io import BytesIO

    from pypdf import PdfReader

    pages = PdfReader(BytesIO(pdf)).pages
    return "\n".join(page.extract_text() or "" for page in pages)


# ── 8. the guard ────────────────────────────────────────────────────────────

def test_no_route_reads_the_socket_address_directly():
    """A future route must not reintroduce this by hand.

    The fix is three lines; the DEFECT was three independent copies of one
    mistake, which is what a guard test is for. `client_ip` is the only
    sanctioned reader of the peer address.
    """
    routes = Path(__file__).resolve().parents[1] / "app" / "api" / "v1" / "routes"
    offenders = [
        f"{path.name}:{n}"
        for path in sorted(routes.glob("*.py"))
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if "request.client.host" in line or ".client.host" in line
    ]
    assert not offenders, (
        "these read the socket address directly instead of client_ip(request): "
        + ", ".join(offenders))
