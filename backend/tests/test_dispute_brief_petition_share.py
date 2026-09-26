"""The case brief reports whether the petition was actually shared.

The lawyer's brief offers the petition download only when
`petition.shared_with_lawyer` is exactly true. That flag is `petition_shared`
as `send_to_lawyer` stored it: true only when the share went through. A failed
or never-attempted share must read false, never "petition present, so shared".
"""
from __future__ import annotations

import pytest

from app.services.dispute_intake import _case_brief

BASE = {"_id": "d1", "client_id": "c1", "state": "ready_for_drafting",
        "petition_document_id": "doc-1", "petition_drafted_at": None}


@pytest.mark.parametrize("stored,expected", [
    (True, True),
    (False, False),        # the share failed
    (None, False),
    ("MISSING", False),    # a dispute stored before sharing was attempted
])
def test_shared_with_lawyer_is_the_stored_share_outcome(stored, expected):
    doc = dict(BASE)
    if stored != "MISSING":
        doc["petition_shared"] = stored
    petition = _case_brief(doc, None)["petition"]
    assert petition["shared_with_lawyer"] is expected


def test_no_petition_is_no_petition_block():
    doc = {k: v for k, v in BASE.items() if not k.startswith("petition")}
    assert _case_brief(doc, None)["petition"] is None
