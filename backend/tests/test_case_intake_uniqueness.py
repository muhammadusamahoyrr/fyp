"""One intake, one case — enforced by the database, not only by the code.

`convert_to_case` takes an atomic claim and pins the case to the intake the
moment it exists. That closes every window a request can lose except one: a
hard kill between the insert and the pin leaves a real case that the intake has
no record of, so the retry, finding nothing pinned, opens a second one.

No application-level guard can close that. The process is gone between the two
writes. Only a constraint the database itself holds can, which is what
`uniq_case_per_intake` is for.

These tests assert on the CONSTRAINT rather than on the service, because the
service is exactly the layer that is absent in the failure being defended
against. They also cover the two ways a naive version of this index goes wrong:
swallowing every case that has no intake, and being scoped so narrowly it
catches nothing.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timezone

import pytest
from pymongo.errors import DuplicateKeyError

from app.core.constants import CaseStatus

pytestmark = pytest.mark.integration


def _case(intake_id, **over) -> dict:
    tag = secrets.token_hex(6)
    doc = {
        "_id": f"UQ-{tag}",
        "case_number": f"ATT-2026-{tag.upper()[:8]}",
        "client_id": "UQ-CLIENT",
        "lawyer_id": None,
        "intake_id": intake_id,
        "case_type": "civil",
        "province": "punjab",
        "status": CaseStatus.OPEN.value,
        "title": "A case",
        "description": "…",
        "milestones": [],
        "hearing_dates": [],
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }
    doc.update(over)
    return doc


@pytest.fixture
async def cases(app_indexes):
    from app.db.collections import get_cases_col

    col = get_cases_col()
    made: list[str] = []

    async def insert(intake_id, **over):
        doc = _case(intake_id, **over)
        await col.insert_one(doc)
        made.append(doc["_id"])
        return doc["_id"]

    yield col, insert
    await col.delete_many({"_id": {"$in": made}})


async def test_the_index_exists(cases):
    col, _ = cases
    info = await col.index_information()
    assert "uniq_case_per_intake" in info, (
        "the guarantee is not enforced; a second case per intake is possible"
    )


async def test_a_second_case_for_one_intake_is_refused(cases):
    """The crash window, closed.

    This is the exact sequence: a case is created, the process dies before
    `attach_case` records it, and a retry tries to open another.
    """
    col, insert = cases
    intake_id = f"UQ-INTAKE-{secrets.token_hex(4)}"
    await insert(intake_id)

    with pytest.raises(DuplicateKeyError):
        await insert(intake_id)


async def test_cases_created_outside_intake_are_unaffected(cases):
    """The failure mode of a naive unique index.

    A case made directly through `POST /cases` carries `intake_id: None`. Under
    an unscoped unique index the first such case would block every other one
    ever created — the guard would take out the feature it was protecting.
    """
    col, insert = cases
    await insert(None)
    await insert(None)
    await insert(None)


async def test_a_missing_intake_id_is_also_unaffected(cases):
    """Legacy rows predate the field entirely."""
    col, insert = cases
    doc_a = _case(None)
    doc_b = _case(None)
    del doc_a["intake_id"], doc_b["intake_id"]
    await col.insert_one(doc_a)
    await col.insert_one(doc_b)
    await col.delete_many({"_id": {"$in": [doc_a["_id"], doc_b["_id"]]}})


async def test_different_intakes_do_not_collide(cases):
    col, insert = cases
    await insert(f"UQ-A-{secrets.token_hex(4)}")
    await insert(f"UQ-B-{secrets.token_hex(4)}")


async def test_the_filter_is_scoped_to_real_intake_ids(cases):
    """`$type: "string"`, not `$ne: null` — partial filters do not support $ne.

    Asserted on the stored definition because getting this wrong fails in one
    of two silent directions: too broad and every intake-less case collides,
    too narrow and nothing is enforced at all.
    """
    col, _ = cases
    info = await col.index_information()
    spec = info["uniq_case_per_intake"]
    assert spec.get("unique") is True
    assert spec["partialFilterExpression"] == {
        "intake_id": {"$exists": True, "$type": "string"}
    }


async def test_the_lookup_index_exists(cases):
    """`convert_to_case` reads by intake_id on every resumed conversion.

    There was no index on the field at all, so that read was a collection scan.
    """
    col, _ = cases
    info = await col.index_information()
    keys = [tuple(k for k, _ in spec["key"]) for spec in info.values()]
    assert any("intake_id" in k for k in keys)
