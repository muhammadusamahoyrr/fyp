"""Gate 3F: the list is not the document.

WHAT CHANGED
------------
`GET /agreements` returned a bare list of FULL agreements. Forty agreements
were forty complete contracts on the wire to draw forty one-line rows, and
neither screen rendered the body. It now returns one page of light rows.

THE RISK IN A STATUS FILTER
---------------------------
A filter is a second place where "which rows may this user see?" gets decided,
and a second place is how a rule gets fixed in one place and not the other.
So there is ONE filter -- `AgreementRepository.visible_to` -- and the status
is ANDed onto it. `status=draft` is therefore not a way to ask for somebody
else's drafts; it narrows what the caller could already see.

NO MOCKS. Every integration test here runs against a real replica set via
`mongo_transactional`, the same fixture Gate 3C uses.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timezone

import pytest

from app.core.constants import AgreementStatus, CaseStatus

#: Deliberately NOT the lawyer's display name. A typed signature is the
#: signer's full legal name, and if the two strings were equal no assertion
#: could distinguish a leaked signature from the `full_name` every list row is
#: supposed to carry.
TYPED_SIGNATURE = "Lister Ahmed Khan, Advocate"

LAWYER = "F3-LAWYER"
CLIENT = "F3-CLIENT"
STRANGER = "F3-STRANGER"
FOURTH = "F3-FOURTH"


@pytest.fixture
async def world(mongo_transactional):
    from app.db.collections import (
        get_agreements_col,
        get_cases_col,
        get_event_outbox_col,
        get_users_col,
    )

    await get_users_col().insert_many([
        {"_id": LAWYER, "full_name": "Adv Lister", "role": "lawyer",
         "email": "l@f3.test", "is_active": True,
         "lawyer_profile": {"kyc_verified": True, "specializations": ["civil"]}},
        {"_id": CLIENT, "full_name": "The Client", "role": "client",
         "email": "c@f3.test", "is_active": True},
        {"_id": STRANGER, "full_name": "Nobody", "role": "client",
         "email": "s@f3.test", "is_active": True},
        # A FOURTH registered user, so the cap test below is refused by the CAP
        # and not by "not a registered user" — which would pass for the wrong
        # reason and keep passing if the cap were removed.
        {"_id": FOURTH, "full_name": "One Too Many", "role": "client",
         "email": "f@f3.test", "is_active": True},
    ])
    yield
    ids = [LAWYER, CLIENT, STRANGER, FOURTH]
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
        "title": "A matter", "case_number": f"C-{cid[:8]}",
        "status": CaseStatus.IN_PROGRESS.value,
        "milestones": [], "created_at": now, "updated_at": now,
    })
    return cid


async def _draft(case_id: str, body: str = "Scope and fee.") -> dict:
    from app.services import agreement_service

    return await agreement_service.create_draft(
        title="Retainer", body_html=body,
        client_id=CLIENT, creator_id=LAWYER, case_id=case_id)


async def _send(draft: dict):
    from app.services import agreement_service

    return await agreement_service.sign_and_send_draft(
        agreement_id=draft["_id"], creator_id=LAWYER,
        expected_version=draft["version"],
        expected_body_sha256=agreement_service.body_digest(draft["body_html"]),
        method="typed", signature_data=TYPED_SIGNATURE, consent=True,
        idempotency_key=secrets.token_urlsafe(12))


async def _listing(user_id, **kw):
    from app.services import agreement_service
    return await agreement_service.list_agreements(user_id, **kw)


# ── the list is light ───────────────────────────────────────────────────────

@pytest.mark.integration
async def test_a_list_row_carries_no_document_body(world):
    """The body is the thing being sent forty times for nothing."""
    d = await _draft(await _case())
    await _send(d)

    [row] = (await _listing(CLIENT))["items"]
    assert row["id"] == d["_id"]
    assert row["title"] == "Retainer"
    assert "body_html" not in row, "the list is shipping whole contracts again"
    assert "body_sha256" not in row, (
        "the digest is evidence about a specific document and belongs with it"
    )
    assert "audit_log" not in row, "the audit log records signer IP addresses"


@pytest.mark.integration
async def test_a_list_row_never_carries_a_signature(world):
    """`signature_data` is the signature itself -- a typed legal name here.

    A list of agreements is not a place to hand every party's signature to
    every other party.
    """
    d = await _draft(await _case())
    await _send(d)

    [row] = (await _listing(CLIENT))["items"]
    signed = [p for p in row["parties"] if p["signed"]]
    assert signed, "the sender's signature should be recorded"
    for party in row["parties"]:
        assert "signature_data" not in party
    assert TYPED_SIGNATURE not in str(row), (
        "the typed signature leaked into the list under some other key"
    )
    assert row["parties"][0]["full_name"] == "Adv Lister", (
        "the display name must survive -- it is what the row shows"
    )


@pytest.mark.integration
async def test_the_body_is_still_reachable_by_opening_the_agreement(world):
    """Removing it from the LIST must not remove it from the document."""
    from app.services import agreement_service

    d = await _draft(await _case())
    await _send(d)

    full = await agreement_service.get_agreement(d["_id"], CLIENT)
    assert full["body_html"] == "Scope and fee."


# ── pagination ──────────────────────────────────────────────────────────────

@pytest.mark.integration
async def test_pagination_reports_the_whole_total_not_the_page_size(world):
    """A client that believes it received everything and did not is how a
    "you have no agreements" screen gets shown to someone who has forty."""
    case_id = await _case()
    for _ in range(5):
        await _send(await _draft(case_id))

    first = await _listing(CLIENT, page=1, page_size=2)
    assert len(first["items"]) == 2
    assert first["total"] == 5
    assert first["pages"] == 3
    assert first["page"] == 1

    last = await _listing(CLIENT, page=3, page_size=2)
    assert len(last["items"]) == 1
    assert last["total"] == 5


@pytest.mark.integration
async def test_pages_do_not_overlap_or_drop_rows(world):
    """An unordered paginated query silently repeats some rows and never shows
    others.

    THE TIMESTAMPS ARE STAGGERED DELIBERATELY. Five rows created in a loop
    share a creation instant to the millisecond, and Mongo then returns them
    in natural order -- which, on a small collection with no deletes, happens
    to be insertion order and is stable across queries by luck. An earlier
    version of this test passed with the sort removed entirely, because
    "no overlap, no drops" is satisfied by that accident. Distinct timestamps
    are what make the ORDER assertion below mean anything.
    """
    from app.db.collections import get_agreements_col

    case_id = await _case()
    created = []
    for i in range(5):
        d = await _draft(case_id)
        await _send(d)
        stamp = datetime(2026, 3, 1 + i, 12, 0, tzinfo=timezone.utc)
        await get_agreements_col().update_one(
            {"_id": d["_id"]}, {"$set": {"created_at": stamp}})
        created.append(d["_id"])

    newest_first = list(reversed(created))

    seen = []
    for page in (1, 2, 3):
        seen += [r["id"] for r in
                 (await _listing(CLIENT, page=page, page_size=2))["items"]]

    assert len(seen) == 5
    assert len(set(seen)) == 5, "a row appeared on two pages"
    assert seen == newest_first, (
        "the pages are not ordered newest-first; without an explicit sort, "
        "paging over a changing collection repeats and drops rows"
    )


def test_the_list_item_schema_declares_no_document_fields():
    """The SCHEMA, not just the service that builds the dict.

    `_list_row` pops the body and the service tests assert on its output, so
    a list model that declared `body_html` would pass every one of them and
    still put the document back on the wire the moment anything returned a
    row that had not been through `_list_row`.
    """
    from app.schemas.agreement import AgreementListItem, AgreementOut

    declared = set(AgreementListItem.model_fields)
    for field in ("body_html", "body_sha256", "audit_log"):
        assert field not in declared, (
            f"the list schema declares {field}: the list is the document again"
        )
    assert "body_html" in AgreementOut.model_fields, (
        "opening a single agreement must still return its text"
    )
    assert {"id", "title", "status", "version"} <= declared


@pytest.mark.integration
async def test_an_oversized_page_is_refused_rather_than_quietly_trimmed(world):
    """Silently returning fewer rows than asked for looks identical to
    "that is all there is"."""
    from app.core.exceptions import AppValidationError
    from app.services import agreement_service

    with pytest.raises(AppValidationError) as exc:
        await _listing(CLIENT, page_size=agreement_service.MAX_PAGE_SIZE + 1)
    assert str(agreement_service.MAX_PAGE_SIZE) in str(exc.value)


# ── the status filter cannot widen visibility ───────────────────────────────

@pytest.mark.integration
async def test_the_status_filter_narrows_the_list(world):
    case_id = await _case()
    sent = await _draft(case_id)
    await _send(sent)
    await _draft(case_id)          # stays a draft

    pending = await _listing(LAWYER, status=AgreementStatus.PENDING.value)
    assert [r["id"] for r in pending["items"]] == [sent["_id"]]
    assert pending["total"] == 1

    everything = await _listing(LAWYER)
    assert everything["total"] == 2


@pytest.mark.integration
async def test_asking_for_drafts_returns_only_your_own(world):
    """THE FILTER MUST NOT BE A SECOND VISIBILITY RULE.

    `status=draft` is the obvious way to try to reach a draft that is not
    yours. It narrows what the caller could already see and nothing more.
    """
    case_id = await _case()
    mine = await _draft(case_id)

    as_author = await _listing(LAWYER, status=AgreementStatus.DRAFT.value)
    assert [r["id"] for r in as_author["items"]] == [mine["_id"]]

    as_counterparty = await _listing(CLIENT, status=AgreementStatus.DRAFT.value)
    assert as_counterparty["items"] == []
    assert as_counterparty["total"] == 0, (
        "the counterparty was told a draft about them exists"
    )


@pytest.mark.integration
async def test_a_stranger_sees_nothing_on_any_page_or_filter(world):
    case_id = await _case()
    await _send(await _draft(case_id))
    await _draft(case_id)

    assert (await _listing(STRANGER))["total"] == 0
    for status in (AgreementStatus.DRAFT.value, AgreementStatus.PENDING.value):
        assert (await _listing(STRANGER, status=status))["total"] == 0


@pytest.mark.integration
async def test_an_unknown_status_is_refused_not_answered_with_nothing(world):
    """"No agreements" and "you asked for a state that does not exist" look
    identical in an empty list, and only one of them is the caller's bug."""
    from app.core.exceptions import AppValidationError

    with pytest.raises(AppValidationError) as exc:
        await _listing(CLIENT, status="archived")
    assert "archived" in str(exc.value)


# ── party rules ─────────────────────────────────────────────────────────────

@pytest.mark.integration
async def test_the_same_party_twice_is_refused_not_silently_collapsed(world):
    """Skipping the duplicate turned the caller's mistake into a different,
    misleading complaint -- "needs at least two parties" -- and in the
    three-id form it passed silently as a two-party agreement."""
    from app.core.exceptions import AppValidationError
    from app.services import agreement_service

    case_id = await _case()
    with pytest.raises(AppValidationError) as exc:
        await agreement_service._create_agreement(
            title="Retainer", body_html="Terms.",
            parties=[CLIENT, CLIENT], creator_id=LAWYER, case_id=case_id)
    assert "more than once" in str(exc.value)


@pytest.mark.integration
async def test_naming_the_creator_explicitly_is_allowed(world):
    """AND MUST STAY ALLOWED.

    A first version of the duplicate rule also refused this, on the reasoning
    that you should list "only the counterparty". That broke every engagement
    letter: `create_pending_engagement_letter` passes the lawyer AND the
    client explicitly, because it knows exactly who both are. The test suite
    caught it as eight red engagement tests.

    The rule is about the same id appearing TWICE, which is unambiguously a
    mistake -- not about which of two distinct people is named.
    """
    from app.services import agreement_service

    case_id = await _case()
    created = await agreement_service._create_agreement(
        title="Retainer", body_html="Terms.",
        parties=[LAWYER, CLIENT], creator_id=LAWYER, case_id=case_id)

    assert {p["user_id"] for p in created["parties"]} == {LAWYER, CLIENT}
    assert len(created["parties"]) == 2, "the creator was added a second time"


@pytest.mark.integration
async def test_the_creator_listed_twice_is_still_refused(world):
    """The creator may appear once. Twice is the duplicate rule again."""
    from app.core.exceptions import AppValidationError
    from app.services import agreement_service

    case_id = await _case()
    with pytest.raises(AppValidationError) as exc:
        await agreement_service._create_agreement(
            title="Retainer", body_html="Terms.",
            parties=[LAWYER, LAWYER, CLIENT], creator_id=LAWYER, case_id=case_id)
    assert "more than once" in str(exc.value)


@pytest.mark.integration
async def test_the_party_cap_is_still_enforced(world):
    """The cap moved from two to three on 2026-09-23 (the owner's reversal of
    D2), so this no longer asserts "exactly two". It asserts there is STILL a
    cap: a limit that quietly becomes unbounded is the failure worth catching,
    not the specific number.

    `parties=[CLIENT, STRANGER]` plus the creator is three, which is now the
    maximum and is accepted; a fourth is refused.
    """
    from app.core.exceptions import AppValidationError
    from app.services import agreement_service

    case_id = await _case()

    ok = await agreement_service._create_agreement(
        title="Retainer", body_html="Terms.",
        parties=[CLIENT, STRANGER], creator_id=LAWYER, case_id=case_id)
    assert len(ok["parties"]) == agreement_service.MAX_PARTIES == 3

    with pytest.raises(AppValidationError) as exc:
        await agreement_service._create_agreement(
            title="Retainer", body_html="Terms.",
            parties=[CLIENT, STRANGER, FOURTH], creator_id=LAWYER,
            case_id=case_id)
    assert "at most 3 parties" in str(exc.value)


# ── the chores ──────────────────────────────────────────────────────────────

def test_the_dead_agreement_model_is_gone():
    """`models/agreement.py` duplicated the schema with DIFFERENT defaults --
    `status: AgreementStatus = DRAFT` where the service writes `pending`.
    Nothing imported it. A second definition of the same record is a trap for
    whoever reads it first."""
    import importlib

    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("app.models.agreement")


def test_party_out_does_not_forbid_extras():
    """Its docstring once claimed "STRICT (no extra)", which was never true.

    Making it true would reject every real party: the model is validated FROM
    stored rows, and those rows carry `signature_data`. Omitting the field is
    what drops it -- forbidding extras would turn a privacy note into a 500.
    """
    from app.schemas.agreement import PartyOut

    party = PartyOut(**{
        "user_id": "U1", "full_name": "A Party", "signed": True,
        "signature_data": "a typed legal name",
    })
    assert "signature_data" not in party.model_dump()


# ── the list contract, checked against what the frontend actually reads ─────

def test_the_frontend_reads_only_fields_the_list_row_provides():
    """THE TEST THAT WOULD HAVE CAUGHT THE 3F REGRESSION.

    Gate 3F removed `body_html` from list rows. The backend tests asserted the
    removal, the frontend tests asserted the right calls were made, and nobody
    compared the two: both screens went on reading `a.body_html` off the row,
    so every agreement opened showing "No content." beside a working Sign
    button.

    A field a mapper reads and the row never carries is `undefined` -- which
    renders as an empty string or a fallback, not as an error. So the only
    place this is visible is here, holding both halves at once.

    Reads the JSX as text on purpose. The alternative is a running browser,
    and the property is structural: which keys does the mapper touch, and does
    the serialiser promise them.
    """
    import re
    from pathlib import Path

    from app.schemas.agreement import AgreementListItem

    root = Path(__file__).resolve().parents[2] / "frontend" / "src" / "components"
    screens = {
        "lawyer": (root / "lawyer" / "AgreementsPage.jsx",
                   r"function mapAgreement\(a, myId\) \{(.*?)\n\}"),
        "client": (root / "client" / "ModAgreements.jsx",
                   r"const mapAgreement = \(a, myId\) => \{(.*?)\n\};"),
    }

    provided = set(AgreementListItem.model_fields) | {"_id"}

    for name, (path, pattern) in screens.items():
        source = path.read_text(encoding="utf-8")
        match = re.search(pattern, source, re.S)
        assert match, f"{name}: mapAgreement moved; this test needs updating"

        read = set(re.findall(r"\ba\.([a-z_]+)", match.group(1)))
        missing = sorted(read - provided)
        assert not missing, (
            f"{name} mapAgreement reads {missing} off a LIST ROW, and "
            f"AgreementListItem does not provide it. The value will be "
            f"undefined and render as a blank or a fallback, which is exactly "
            f"how the body disappeared in 3F."
        )


def test_the_list_row_and_the_schema_agree():
    """`_list_row` builds the dict; `AgreementListItem` serialises it. A key
    the builder strips but the schema still declares would serialise as null
    and read, to a caller, as "this agreement has none"."""
    from app.schemas.agreement import AgreementListItem
    from app.services.agreement_service import _list_row

    row = _list_row({
        "_id": "A1", "title": "Retainer", "status": "pending",
        "body_html": "Terms.", "body_sha256": "a" * 64,
        "audit_log": [{"action": "sent"}],
        "case_id": "C1", "engagement_id": None, "created_by": "L1",
        "version": 2, "parties": [{"user_id": "L1", "signature_data": "x"}],
    })

    for stripped in ("body_html", "body_sha256", "audit_log"):
        assert stripped not in row
        assert stripped not in AgreementListItem.model_fields, (
            f"the schema still declares {stripped} that `_list_row` removes, "
            f"so it serialises as null rather than being absent"
        )

    # Everything the schema promises, the builder must actually produce.
    out = AgreementListItem(**{**row, "_id": row["id"]})
    assert out.version == 2
    assert out.status == "pending"
