"""Gate 3E: the executed agreement as a document, and its evidence record.

WHAT THIS CLOSES
----------------
A fully executed agreement existed only as a database row. Nobody could
download it, and the signature evidence -- timestamps, IP, body digest -- was
written faithfully and readable by no one. For a legal product that is the gap
that matters most.

WHAT THE DOCUMENT MAY SAY
-------------------------
Facts that were recorded, and nothing else. No enforceability, no validity, no
ETO classification: those are legal conclusions nobody with the standing to
reach them has reviewed, and asserting one would repeat the failure Phase 0
removed from the marketing copy.

ESCAPING IS AT THE RENDER SINK
------------------------------
reportlab's Paragraph parses markup. `<`, `&` and quotes in ordinary legal
text ("the defendant paid <50% of what was owed") must survive into the PDF as
themselves, and an `<img src=...>` in a field must NOT open that path on the
server. `P()` escapes by default; these tests check the rendered bytes.

NO MOCKS. Integration tests run against a real replica set via
`mongo_transactional`. The PDF tests call the real reportlab builder and read
the real output bytes.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timezone

import pytest

from app.core.constants import AgreementStatus, CaseStatus

LAWYER = "E3-LAWYER"
CLIENT = "E3-CLIENT"
STRANGER = "E3-STRANGER"
TYPED_SIGNATURE = "Lister Ahmed Khan, Advocate"
CLIENT_SIGNATURE = "Ayesha Bibi"


@pytest.fixture
async def world(mongo_transactional):
    from app.db.collections import (
        get_agreement_downloads_col,
        get_agreements_col,
        get_cases_col,
        get_event_outbox_col,
        get_users_col,
    )

    await get_users_col().insert_many([
        {"_id": LAWYER, "full_name": "Adv Lister", "role": "lawyer",
         "email": "l@e3.test", "is_active": True,
         "lawyer_profile": {"kyc_verified": True, "specializations": ["civil"]}},
        {"_id": CLIENT, "full_name": "The Client", "role": "client",
         "email": "c@e3.test", "is_active": True},
        {"_id": STRANGER, "full_name": "Nobody", "role": "client",
         "email": "s@e3.test", "is_active": True},
    ])
    yield
    ids = [LAWYER, CLIENT, STRANGER]
    await get_users_col().delete_many({"_id": {"$in": ids}})
    await get_cases_col().delete_many({"client_id": CLIENT})
    await get_agreements_col().delete_many({"created_by": {"$in": ids}})
    await get_agreement_downloads_col().delete_many({"user_id": {"$in": ids}})
    await get_event_outbox_col().delete_many({"payload.recipient_id": {"$in": ids}})


async def _case() -> str:
    from app.db.collections import get_cases_col

    now = datetime.now(timezone.utc)
    cid = secrets.token_urlsafe(12)
    await get_cases_col().insert_one({
        "_id": cid, "client_id": CLIENT, "lawyer_id": LAWYER,
        "title": "A matter", "case_number": f"C-{cid[:8]}",
        "status": CaseStatus.IN_PROGRESS.value,
        "milestones": [], "created_at": now, "updated_at": now,
    })
    return cid


async def _draft(body: str = "Fees are 40% of recovery.") -> dict:
    from app.services import agreement_service

    return await agreement_service.create_draft(
        title="Retainer", body_html=body,
        client_id=CLIENT, creator_id=LAWYER, case_id=await _case())


async def _sent(body: str = "Fees are 40% of recovery.") -> dict:
    from app.services import agreement_service

    d = await _draft(body)
    await agreement_service.sign_and_send_draft(
        agreement_id=d["_id"], creator_id=LAWYER,
        expected_version=d["version"],
        expected_body_sha256=agreement_service.body_digest(d["body_html"]),
        method="typed", signature_data=TYPED_SIGNATURE, consent=True,
        idempotency_key=secrets.token_urlsafe(12), ip_address="203.0.113.9")
    return d


async def _executed(body: str = "Fees are 40% of recovery.") -> dict:
    """A real two-signature execution, through the real signing path."""
    from app.services import agreement_service

    d = await _sent(body)
    await agreement_service.submit_signature(
        agreement_id=d["_id"], user_id=CLIENT, method="typed",
        signature_data=CLIENT_SIGNATURE, ip_address="198.51.100.7")
    return d


async def _row(agreement_id: str):
    from app.db.collections import get_agreements_col
    return await get_agreements_col().find_one({"_id": agreement_id})


def pdf_text(pdf: bytes) -> str:
    """Every line of visible text in the PDF.

    Read with `pypdf`, which is already a dependency. A hand-rolled extractor
    was tried first and produced gibberish: reportlab filters its content
    streams through ASCII85 AND Flate, so inflating alone yields the a85 text
    rather than the page. Asserting on a broken reading of the document is
    worse than not asserting -- it fails on correct output and would have been
    "fixed" by weakening the assertions.
    """
    from io import BytesIO

    from pypdf import PdfReader

    pages = PdfReader(BytesIO(pdf)).pages
    return "\n".join(page.extract_text() or "" for page in pages)


# ── authorisation ───────────────────────────────────────────────────────────

@pytest.mark.integration
async def test_a_non_party_is_told_it_does_not_exist(world):
    """404, NOT 403. A 403 confirms the id exists, and for a signed contract
    between two other people that is itself a disclosure."""
    from app.core.exceptions import NotFoundError
    from app.services import agreement_service

    d = await _executed()

    with pytest.raises(NotFoundError):
        await agreement_service.executed_pdf(d["_id"], STRANGER)

    # Indistinguishable from an id that never existed.
    with pytest.raises(NotFoundError):
        await agreement_service.executed_pdf("NO-SUCH-AGREEMENT", STRANGER)


@pytest.mark.integration
async def test_a_party_may_download_it(world):
    from app.services import agreement_service

    d = await _executed()
    for who in (LAWYER, CLIENT):
        pdf, filename = await agreement_service.executed_pdf(d["_id"], who)
        assert pdf.startswith(b"%PDF-")
        assert filename.endswith(".pdf")


@pytest.mark.integration
async def test_a_pending_agreement_has_no_executed_copy(world):
    """A party is entitled to know the state of their own agreement, so this
    is a plain explanation rather than a 404."""
    from app.core.exceptions import AppValidationError
    from app.services import agreement_service

    d = await _sent()
    with pytest.raises(AppValidationError) as exc:
        await agreement_service.executed_pdf(d["_id"], CLIENT)
    assert "not been fully signed" in str(exc.value)


@pytest.mark.integration
async def test_a_draft_pdf_does_not_admit_the_draft_exists(world):
    """The counterparty must not learn a draft naming them is being written,
    and a PDF route is exactly the sort of place that leaks it."""
    from app.core.exceptions import NotFoundError
    from app.services import agreement_service

    d = await _draft()

    with pytest.raises(NotFoundError):
        await agreement_service.executed_pdf(d["_id"], CLIENT)


@pytest.mark.integration
async def test_the_author_of_a_draft_is_told_why_instead(world):
    """The author knows it exists; "not found" about their own row is a lie."""
    from app.core.exceptions import AppValidationError
    from app.services import agreement_service

    d = await _draft()
    with pytest.raises(AppValidationError):
        await agreement_service.executed_pdf(d["_id"], LAWYER)


# ── contents ────────────────────────────────────────────────────────────────

@pytest.mark.integration
async def test_the_pdf_carries_the_digest_and_both_signatures(world):
    from app.services import agreement_service

    d = await _executed()
    row = await _row(d["_id"])
    pdf, _ = await agreement_service.executed_pdf(d["_id"], CLIENT)
    text = pdf_text(pdf)

    assert row["body_sha256"], "an executed agreement must carry its digest"
    assert row["body_sha256"] in text, "the digest is not on the document"
    assert TYPED_SIGNATURE in text, "the sender's signature is missing"
    assert CLIENT_SIGNATURE in text, "the counterparty's signature is missing"
    assert "Fees are 40% of recovery." in text, "the agreement text is missing"


@pytest.mark.integration
async def test_the_recorded_signing_ip_reaches_the_certificate(world):
    """The IP lives in `audit_log`, keyed by actor -- NOT on the party.

    A first version of the builder read `party["ip_address"]`, which does not
    exist, so every certificate would have said "not recorded" even where an
    address had been captured.
    """
    from app.services import agreement_service

    d = await _executed()
    pdf, _ = await agreement_service.executed_pdf(d["_id"], CLIENT)
    text = pdf_text(pdf)

    assert "203.0.113.9" in text, "the sender's recorded IP is missing"
    assert "198.51.100.7" in text, "the signer's recorded IP is missing"


@pytest.mark.integration
async def test_an_unrecorded_ip_is_stated_as_unrecorded_not_invented(world):
    """D8: no placeholder, and nothing borrowed from another party."""
    from app.db.collections import get_agreements_col
    from app.services import agreement_pdf, agreement_service

    d = await _executed()
    await get_agreements_col().update_one(
        {"_id": d["_id"]}, {"$set": {"audit_log.$[].ip_address": None}})

    row = await _row(d["_id"])
    assert agreement_pdf.signing_ips(row) == {}

    pdf, _ = await agreement_service.executed_pdf(d["_id"], CLIENT)
    text = pdf_text(pdf)
    assert agreement_pdf.IP_NOT_RECORDED in text
    assert "203.0.113.9" not in text
    assert "0.0.0.0" not in text, "an invented placeholder is a false fact"


@pytest.mark.integration
async def test_the_certificate_reaches_no_legal_conclusion(world):
    """Facts only. Enforceability and ETO classification are counsel-gated."""
    from app.services import agreement_service

    d = await _executed()
    pdf, _ = await agreement_service.executed_pdf(d["_id"], CLIENT)
    text = pdf_text(pdf).lower()

    for claim in ("enforceable", "legally binding", "valid under",
                  "electronic transactions ordinance", "eto 2002",
                  "admissible", "court will"):
        assert claim not in text, (
            f"the certificate asserts {claim!r}, which is a legal conclusion "
            "nobody with the standing to reach it has reviewed"
        )


@pytest.mark.integration
async def test_times_are_stated_as_the_servers(world):
    """A client clock is whatever the signer's machine claimed."""
    from app.services import agreement_service

    d = await _executed()
    pdf, _ = await agreement_service.executed_pdf(d["_id"], CLIENT)
    text = pdf_text(pdf)

    assert "UTC" in text
    assert "server" in text.lower()


# ── escaping at the render sink ─────────────────────────────────────────────

@pytest.mark.integration
async def test_angle_brackets_ampersands_and_quotes_render_intact(world):
    """reportlab parses markup, so these are the characters that break it --
    and ordinary legal text is full of them."""
    from app.services import agreement_service

    body = ('Fees are <50% of recovery & costs, per the "schedule" '
            "attached; see clause 4 > clause 3.")
    d = await _executed(body)
    pdf, _ = await agreement_service.executed_pdf(d["_id"], CLIENT)
    text = pdf_text(pdf)

    assert "<50%" in text
    assert "&" in text
    assert '"schedule"' in text
    assert "clause 4 > clause 3" in text


@pytest.mark.integration
async def test_markup_in_the_body_is_printed_not_interpreted(world):
    """A field that reaches the parser unescaped is a server-side file read:
    `<img src="...">` embeds that path's contents in the generated PDF."""
    from app.services import agreement_service

    body = 'The parties agree <b>nothing</b> and <img src="/etc/passwd"/> applies.'
    d = await _executed(body)
    pdf, _ = await agreement_service.executed_pdf(d["_id"], CLIENT)
    text = pdf_text(pdf)

    assert "<b>nothing</b>" in text, "markup was interpreted instead of printed"
    assert '<img src="/etc/passwd"/>' in text


@pytest.mark.integration
async def test_a_signature_containing_markup_does_not_break_the_document(world):
    """The signature is user text too, and it is rendered in its own cell."""
    from app.services import agreement_service

    d = await _sent()
    await agreement_service.submit_signature(
        agreement_id=d["_id"], user_id=CLIENT, method="typed",
        signature_data='A & B <Ltd>', ip_address=None)

    pdf, _ = await agreement_service.executed_pdf(d["_id"], CLIENT)
    assert "A & B <Ltd>" in pdf_text(pdf)


# ── what must not cross the wire ────────────────────────────────────────────

@pytest.mark.integration
async def test_signatures_and_the_audit_log_stay_out_of_json(world):
    """The PDF is the ONLY place a signature is reproduced.

    `get_agreement` and the list are the two JSON paths a party can reach;
    neither may carry the signature blob or the audit log, which holds the
    other party's IP.
    """
    from app.schemas.agreement import AgreementListItem, AgreementOut
    from app.services import agreement_service

    d = await _executed()

    full = AgreementOut(**await agreement_service.get_agreement(d["_id"], CLIENT))
    dumped = full.model_dump()
    assert "audit_log" not in dumped
    assert TYPED_SIGNATURE not in str(dumped)
    for party in dumped["parties"]:
        assert "signature_data" not in party

    [row] = (await agreement_service.list_agreements(CLIENT))["items"]
    listed = AgreementListItem(**{**row, "_id": row["id"]}).model_dump()
    assert "audit_log" not in listed
    assert TYPED_SIGNATURE not in str(listed)
    assert "203.0.113.9" not in str(listed), "an IP reached the list"


# ── the download is recorded ────────────────────────────────────────────────

@pytest.mark.integration
async def test_every_download_is_logged(world):
    """The row exists for the downloaded-share metric, and incidentally
    records who took a copy of a signed contract."""
    from app.db.collections import get_agreement_downloads_col
    from app.services import agreement_service

    d = await _executed()
    assert await get_agreement_downloads_col().count_documents(
        {"agreement_id": d["_id"]}) == 0

    await agreement_service.executed_pdf(d["_id"], CLIENT)
    await agreement_service.executed_pdf(d["_id"], LAWYER)

    rows = await get_agreement_downloads_col().find(
        {"agreement_id": d["_id"]}).to_list(None)
    assert len(rows) == 2, "a download went unrecorded"
    assert {r["user_id"] for r in rows} == {CLIENT, LAWYER}
    assert all(r["bytes"] > 0 for r in rows)
    assert all(isinstance(r["downloaded_at"], datetime) for r in rows)


@pytest.mark.integration
async def test_a_refused_download_is_not_logged_as_one(world):
    """The metric counts documents that were SERVED."""
    from app.core.exceptions import AppValidationError, NotFoundError
    from app.db.collections import get_agreement_downloads_col
    from app.services import agreement_service

    pending = await _sent()
    with pytest.raises(AppValidationError):
        await agreement_service.executed_pdf(pending["_id"], CLIENT)
    with pytest.raises(NotFoundError):
        await agreement_service.executed_pdf(pending["_id"], STRANGER)

    assert await get_agreement_downloads_col().count_documents(
        {"agreement_id": pending["_id"]}) == 0


@pytest.mark.integration
async def test_an_unverifiable_ip_is_not_stored_against_the_download(world):
    """D8 again, at the audit row this time."""
    from app.db.collections import get_agreement_downloads_col
    from app.services import agreement_service

    d = await _executed()
    await agreement_service.executed_pdf(
        d["_id"], CLIENT, ip_address="10.0.0.5", ip_verifiable=False)
    await agreement_service.executed_pdf(
        d["_id"], LAWYER, ip_address="203.0.113.9", ip_verifiable=True)

    rows = {r["user_id"]: r async for r in
            get_agreement_downloads_col().find({"agreement_id": d["_id"]})}
    assert rows[CLIENT]["ip_address"] is None, (
        "an address that could not be verified was stored as fact"
    )
    assert rows[LAWYER]["ip_address"] == "203.0.113.9"


# ── D8: whose IP is this, and can we stand behind it? ───────────────────────
#
# Unit tests, no database. The rule decides what an evidence document is
# allowed to assert, so it is worth testing on its own rather than only
# through a PDF.

class _Req:
    """The two things `client_ip` reads off a request."""

    def __init__(self, peer=None, headers=None):
        self.client = type("P", (), {"host": peer})() if peer else None
        self.headers = headers or {}


@pytest.fixture
def no_proxies(monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "trusted_proxies", "", raising=False)
    return settings


@pytest.fixture
def one_proxy(monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "trusted_proxies", "10.0.0.1", raising=False)
    return settings


def test_with_no_proxy_the_socket_address_is_the_client(no_proxies):
    from app.core.client_ip import client_ip, ip_is_verifiable

    req = _Req(peer="203.0.113.9")
    assert client_ip(req) == "203.0.113.9"
    assert ip_is_verifiable(req) is True


def test_a_forwarding_header_from_an_untrusted_peer_is_ignored(no_proxies):
    """This is the forgery case. `X-Forwarded-For` is caller-supplied text, so
    trusting it without checking who connected lets a signer write their own
    IP into the signature record."""
    from app.core.client_ip import client_ip, ip_is_verifiable

    req = _Req(peer="203.0.113.9",
               headers={"x-forwarded-for": "1.2.3.4"})
    assert client_ip(req) == "203.0.113.9", "the header was believed"
    assert ip_is_verifiable(req) is False, (
        "something is in front of us that we were not told about, so the "
        "address we hold may be its, not the client's"
    )


def test_a_trusted_proxy_is_believed(one_proxy):
    from app.core.client_ip import client_ip, ip_is_verifiable

    req = _Req(peer="10.0.0.1",
               headers={"x-forwarded-for": "203.0.113.9, 10.0.0.1"})
    assert client_ip(req) == "203.0.113.9", "the leftmost entry is the client"
    assert ip_is_verifiable(req) is True


def test_a_peer_that_is_not_the_configured_proxy_is_not_believed(one_proxy):
    from app.core.client_ip import client_ip, ip_is_verifiable

    req = _Req(peer="192.0.2.50",
               headers={"x-forwarded-for": "1.2.3.4"})
    assert client_ip(req) == "192.0.2.50"
    assert ip_is_verifiable(req) is False


def test_rubbish_in_the_header_does_not_reach_the_document(one_proxy):
    """A trusted proxy vouches for the chain, not for its contents."""
    from app.core.client_ip import client_ip

    for value in ("unknown", "", "not-an-ip", "999.1.2.3", "localhost"):
        req = _Req(peer="10.0.0.1", headers={"x-forwarded-for": value})
        assert client_ip(req) is None, f"{value!r} was accepted as an address"


def test_no_peer_at_all_is_not_an_address(no_proxies):
    """None is a real answer and callers must handle it. "We do not know" is
    a true statement; "0.0.0.0" is not."""
    from app.core.client_ip import client_ip, ip_is_verifiable

    req = _Req(peer=None)
    assert client_ip(req) is None
    assert ip_is_verifiable(req) is False
