"""`handle_webhook` — the entrypoint that settles money, previously untested.

`test_payments.py` covers signature verification and the settlement core reached
through `mock_pay`. Nothing called `handle_webhook`, which is the path a real
provider takes, and nothing exercised Safeguard 3a — the unique index on
`payment_events.event_id` that makes a replayed event a no-op.

3a was unreachable from the existing tests for two independent reasons:

  * `mock_pay` returns early on `already_paid` before reaching `_settle` a
    second time, so the replay never happened; and
  * the unique index does not exist on the test database at all, because
    `create_all_indexes()` runs at application startup and a test never performs
    one. Every test here takes `app_indexes` for that reason.

The two safeguards are distinguishable, which is what makes these tests worth
having rather than merely green:

    3a  unique event id   -> {"deduped": True}      and ONE payment_events row
    3b  status guard      -> {"already_paid": True} and TWO rows

So an assertion of `deduped` plus a row count of one can only pass if the index
is really there and really fired.

What 3a does and does not buy, stated honestly: 3b already prevents a double
CREDIT, because its conditional update only matches a payment that is not yet
paid. 3a prevents a duplicate settlement EVENT — exactly-once accounting of what
the provider told us — and short-circuits before any further work or
notification. Both are wanted; only one is about the money.
"""
import asyncio
import json
import secrets
from datetime import datetime, timezone

import pytest

from app.core.constants import PaymentStatus

pytestmark = pytest.mark.integration


def _body(provider_ref: str, event_id: str, status: str = "paid") -> bytes:
    """A provider webhook body. MockProvider parses JSON and checks no
    signature, so this is the whole contract."""
    return json.dumps({"event_id": event_id,
                       "provider_ref": provider_ref,
                       "status": status}).encode()


@pytest.fixture
async def payable(app_indexes):
    """A raised, unpaid fee with a provider_ref, plus the real app indexes.

    Mirrors `TestSettlement.paid_scenario` in test_payments.py — a lawyer, a
    client, a case, an executed engagement letter (billing requires one) and a
    fee request — and then sets `provider_ref`, which a real payment acquires
    when checkout is created. Without it `handle_webhook` cannot resolve the
    event back to a payment.
    """
    from app.db.collections import (
        get_agreements_col, get_cases_col, get_engagements_col,
        get_payment_events_col, get_payments_col, get_users_col,
    )
    from app.services import payment_service as ps

    now = datetime.now(timezone.utc)
    tag = secrets.token_hex(4)
    lawyer_id, client_id = f"WH-L-{tag}", f"WH-C-{tag}"
    case_id, agr_id, eng_id = f"WH-CASE-{tag}", f"WH-AGR-{tag}", f"WH-ENG-{tag}"

    await get_users_col().insert_many([
        {"_id": lawyer_id, "role": "lawyer", "is_active": True,
         "email": f"wh-l-{tag}@test.invalid", "full_name": "Adv Webhook",
         "created_at": now},
        {"_id": client_id, "role": "client", "is_active": True,
         "email": f"wh-c-{tag}@test.invalid", "full_name": "Client Webhook",
         "created_at": now},
    ])
    await get_cases_col().insert_one({
        "_id": case_id, "lawyer_id": lawyer_id, "client_id": client_id,
        "title": "Webhook case", "case_number": f"WH/{tag}", "status": "active",
        "created_at": now})
    await get_agreements_col().insert_one({
        "_id": agr_id, "case_id": case_id, "engagement_id": eng_id,
        "title": "Engagement Letter", "status": "executed",
        "parties": [{"user_id": lawyer_id, "signed": True},
                    {"user_id": client_id, "signed": True}],
        "created_at": now})
    await get_engagements_col().insert_one({
        "_id": eng_id, "case_id": case_id, "lawyer_id": lawyer_id,
        "client_id": client_id, "status": "accepted", "fee_amount": 50_000,
        "fee_type": "fixed", "agreement_id": agr_id, "created_at": now})

    fee = await ps.create_fee_request(
        lawyer_id, {"case_id": case_id, "amount": 50_000,
                    "purpose": "professional_fee", "engagement_id": eng_id})
    pid = fee.get("id") or fee["_id"]

    # Checkout has been started: a `provider_ref` exists and the status has
    # moved CREATED -> PENDING. Setting the reference without the status would
    # be a state production never produces, and a webhook only ever arrives
    # after checkout.
    provider_ref = f"mock_ref_{tag}"
    await get_payments_col().update_one(
        {"_id": pid},
        {"$set": {"provider_ref": provider_ref,
                  "status": PaymentStatus.PENDING.value}},
    )

    yield {"payment_id": pid, "provider_ref": provider_ref,
           "payer_id": client_id, "payee_id": lawyer_id}

    await get_payments_col().delete_one({"_id": pid})
    await get_payment_events_col().delete_many({"payment_id": pid})
    await get_cases_col().delete_one({"_id": case_id})
    await get_engagements_col().delete_one({"_id": eng_id})
    await get_agreements_col().delete_one({"_id": agr_id})
    await get_users_col().delete_many({"_id": {"$in": [lawyer_id, client_id]}})


async def _status(payment_id: str) -> str:
    from app.db.collections import get_payments_col
    doc = await get_payments_col().find_one({"_id": payment_id})
    return doc["status"]


async def _event_count(payment_id: str) -> int:
    from app.db.collections import get_payment_events_col
    return await get_payment_events_col().count_documents(
        {"payment_id": payment_id})


# ── the entrypoint itself ────────────────────────────────────────────────────

async def test_a_webhook_settles_a_pending_payment(payable):
    """The path a real provider takes, which nothing called before."""
    from app.services import payment_service as ps

    out = await ps.handle_webhook(
        {}, _body(payable["provider_ref"], "evt-1"))

    assert out == {"status": "paid"}
    assert await _status(payable["payment_id"]) == "paid"
    assert await _event_count(payable["payment_id"]) == 1


async def test_a_webhook_for_an_unknown_reference_is_ignored(payable):
    from app.services import payment_service as ps

    out = await ps.handle_webhook({}, _body("mock_ref_nobody", "evt-x"))

    assert out == {"ignored": True}
    assert await _status(payable["payment_id"]) == "pending"


async def test_a_failed_status_marks_the_payment_failed(payable):
    from app.services import payment_service as ps

    out = await ps.handle_webhook(
        {}, _body(payable["provider_ref"], "evt-f", status="failed"))

    assert out == {"status": "failed"}
    assert await _status(payable["payment_id"]) == "failed"


async def test_a_malformed_body_is_refused(payable):
    from app.services.payments.base import WebhookSignatureError
    from app.services import payment_service as ps

    with pytest.raises(WebhookSignatureError):
        await ps.handle_webhook({}, b"{not json")
    assert await _status(payable["payment_id"]) == "pending"


# ── Safeguard 3a: the replayed event ─────────────────────────────────────────

async def test_a_replayed_event_is_deduped_by_the_unique_index(payable):
    """THE gap. The same event_id delivered twice.

    `deduped` AND a single event row together prove Safeguard 3a fired: without
    the unique index the second insert would succeed, giving two rows, and the
    call would fall through to the status guard and return `already_paid`
    instead. Both halves of the assertion are load-bearing.
    """
    from app.services import payment_service as ps

    first = await ps.handle_webhook(
        {}, _body(payable["provider_ref"], "evt-replay"))
    second = await ps.handle_webhook(
        {}, _body(payable["provider_ref"], "evt-replay"))

    assert first == {"status": "paid"}
    assert second == {"deduped": True}, (
        "the replay was not caught by the event-id index — it fell through to "
        "the status guard, which means 3a did not fire"
    )
    assert await _event_count(payable["payment_id"]) == 1


async def test_a_replay_arriving_before_settlement_completes_is_deduped(payable):
    """The scenario 3a exists for: the SAME event delivered twice while the
    payment is still pending, concurrently.

    Exactly one delivery may settle. The other must be refused by the index
    rather than by the status guard, because at the moment both start neither
    can see the other's write yet — which is precisely the window a status check
    cannot close on its own.
    """
    from app.services import payment_service as ps

    assert await _status(payable["payment_id"]) == "pending"

    body = _body(payable["provider_ref"], "evt-concurrent")
    results = await asyncio.gather(
        ps.handle_webhook({}, body),
        ps.handle_webhook({}, body),
        return_exceptions=True,
    )

    settled = [r for r in results if r == {"status": "paid"}]
    refused = [r for r in results if r == {"deduped": True}]

    assert len(settled) == 1, f"expected exactly one settlement, got {results}"
    assert len(refused) == 1, f"the duplicate was not refused: {results}"
    assert await _event_count(payable["payment_id"]) == 1
    assert await _status(payable["payment_id"]) == "paid"


async def test_two_distinct_events_are_stopped_by_the_status_guard(payable):
    """The other safeguard, kept distinct.

    A DIFFERENT event id is not a replay, so 3a cannot help: it is 3b, the
    conditional status update, that refuses to pay a payment twice. Asserting
    the different return value and the second event row is what stops these two
    tests from silently collapsing into one.
    """
    from app.services import payment_service as ps

    first = await ps.handle_webhook(
        {}, _body(payable["provider_ref"], "evt-a"))
    second = await ps.handle_webhook(
        {}, _body(payable["provider_ref"], "evt-b"))

    assert first == {"status": "paid"}
    assert second == {"already_paid": True}
    assert await _event_count(payable["payment_id"]) == 2
    assert await _status(payable["payment_id"]) == "paid"


async def test_the_lawyer_is_never_credited_twice(payable):
    """What all of the above is actually for."""
    from app.db.collections import get_payments_col
    from app.services import payment_service as ps

    body = _body(payable["provider_ref"], "evt-money")
    await ps.handle_webhook({}, body)
    paid_at = (await get_payments_col().find_one(
        {"_id": payable["payment_id"]}))["paid_at"]

    for _ in range(3):
        await ps.handle_webhook({}, body)

    doc = await get_payments_col().find_one({"_id": payable["payment_id"]})
    assert doc["paid_at"] == paid_at, "settlement was applied more than once"
    assert await _event_count(payable["payment_id"]) == 1
