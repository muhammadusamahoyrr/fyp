"""The last intake step asks the client to confirm their case category.

Their answer used to go nowhere. The cards set React state, and the button
beside them made no request at all — so a client who corrected the AI's
classification saw the new category on every screen while MongoDB kept the old
one indefinitely. Nothing reconciled the two, and the lawyer matching that runs
off `case_type` used the category the client had just rejected.

The write is audited rather than silent: a client overriding a verified
classification is a fact about the case, and a legal record that quietly
replaces the pipeline's answer with a layperson's cannot later say which one it
is showing.
"""
from __future__ import annotations

import pytest

from app.core.exceptions import ForbiddenError, NotFoundError
from app.services import case_service


CLIENT = "client-1"
OTHER = "client-2"
CASE_ID = "case-1"


class FakeCaseRepo:
    def __init__(self, case):
        self.cases = {case["_id"]: case}

    async def find_by_id(self, case_id):
        case = self.cases.get(case_id)
        return dict(case) if case else None

    async def update_one(self, filter, update):
        case = self.cases.get(filter["_id"])
        if case is None:
            return False
        case.update(update.get("$set", {}))
        return True


@pytest.fixture
def repo(monkeypatch):
    r = FakeCaseRepo({
        "_id": CASE_ID,
        "client_id": CLIENT,
        "lawyer_id": None,
        "case_type": "civil",
        "title": "A tenancy dispute",
        "description": "…",
        "status": "open",
    })
    monkeypatch.setattr(case_service, "case_repo", r)
    return r


async def test_the_client_can_change_the_category(repo):
    result = await case_service.update_case(
        CASE_ID, {"case_type": "family"}, CLIENT, "client")
    assert result["case_type"] == "family"
    assert repo.cases[CASE_ID]["case_type"] == "family"


async def test_the_change_records_who_made_it(repo):
    await case_service.update_case(
        CASE_ID, {"case_type": "family"}, CLIENT, "client")
    stored = repo.cases[CASE_ID]
    assert stored["case_type_source"] == "client"
    assert stored["case_type_changed_by"] == CLIENT
    assert stored["case_type_changed_at"] is not None


async def test_the_ai_classification_is_preserved(repo):
    """The pipeline's answer must survive being overridden.

    Without this the case would claim a classification the pipeline never made,
    and the audit trail for an AI-assisted legal product would be gone.
    """
    await case_service.update_case(
        CASE_ID, {"case_type": "criminal"}, CLIENT, "client")
    assert repo.cases[CASE_ID]["ai_case_type"] == "civil"


async def test_confirming_the_same_category_is_not_recorded_as_a_change(repo):
    await case_service.update_case(
        CASE_ID, {"case_type": "civil"}, CLIENT, "client")
    assert "case_type_source" not in repo.cases[CASE_ID]


async def test_an_earlier_override_is_not_overwritten_by_a_later_one(repo):
    """Two changes must not lose the ORIGINAL machine classification."""
    await case_service.update_case(CASE_ID, {"case_type": "family"}, CLIENT, "client")
    await case_service.update_case(CASE_ID, {"case_type": "criminal"}, CLIENT, "client")
    assert repo.cases[CASE_ID]["ai_case_type"] == "civil"
    assert repo.cases[CASE_ID]["case_type"] == "criminal"


async def test_a_stranger_cannot_change_the_category(repo):
    with pytest.raises((ForbiddenError, NotFoundError)):
        await case_service.update_case(
            CASE_ID, {"case_type": "family"}, OTHER, "client")
    assert repo.cases[CASE_ID]["case_type"] == "civil"


async def test_status_and_assignment_still_cannot_be_patched(repo):
    """The whitelist gained one field; it must not have gained two."""
    await case_service.update_case(
        CASE_ID,
        {"case_type": "family", "status": "closed", "lawyer_id": "someone"},
        CLIENT, "client",
    )
    stored = repo.cases[CASE_ID]
    assert stored["status"] == "open"
    assert stored["lawyer_id"] is None


async def test_title_and_description_still_work(repo):
    result = await case_service.update_case(
        CASE_ID, {"title": "New title"}, CLIENT, "client")
    assert result["title"] == "New title"


def test_the_route_schema_accepts_a_case_type():
    """The schema is the enum gate — an invented category cannot be stored."""
    from pydantic import ValidationError

    from app.schemas.case import CaseUpdate

    assert CaseUpdate(case_type="family").case_type == "family"
    with pytest.raises(ValidationError):
        CaseUpdate(case_type="banana")


def test_create_case_keeps_the_intake_audit_fields():
    """`user_selected_type` and `type_was_corrected` were built and dropped.

    Intake conversion has always passed both — they exist to record that the AI
    reclassified what the client picked — and `create_case` built its document
    from a closed literal that mentioned neither.
    """
    import inspect

    src = inspect.getsource(case_service.create_case)
    assert "user_selected_type" in src
    assert "type_was_corrected" in src
