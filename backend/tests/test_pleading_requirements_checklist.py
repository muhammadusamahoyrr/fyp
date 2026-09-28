"""A prose draft gets a checklist of what the Code requires -- never a verdict.

The field-based compliance check cannot judge a lawyer's free text, and it
reported `checked: false` for every lawyer draft, including a plaint. The
checklist gives the requirements (same rule set as the check, from one source)
without claiming any of them is met.
"""
from __future__ import annotations

import httpx
import pytest
from httpx import ASGITransport

from app.services import pleading_rules
from app.services.pleading_rules import check_pleading, requirements_for


def test_a_plaint_lists_every_requirement_the_check_uses():
    checklist = requirements_for("plaint_civil")
    check = check_pleading("plaint_civil", {})
    assert checklist["covered"] is True
    assert [i["clause"] for i in checklist["items"]] == [i["clause"] for i in check["items"]]
    assert checklist["basis"] == check["basis"]


def test_nothing_is_ever_marked_satisfied():
    for template in ("plaint_civil", "written_statement", "guardianship_petition",
                     "wakalatnama_checklist"):
        report = requirements_for(template)
        assert report["checked"] is False
        assert {i["status"] for i in report["items"]} == {"to_confirm"}, template


def test_an_uncovered_instrument_says_so():
    report = requirements_for("legal_notice")
    assert report["covered"] is False and report["items"] == []


def test_one_source_for_both(monkeypatch):
    """Changing the rule set changes the checklist and the check together."""
    extra = {"clause": "TEST r.99", "text": "t", "hint": "h", "fields": ("x",)}
    monkeypatch.setattr(pleading_rules, "_GENERAL_RULES",
                        pleading_rules._GENERAL_RULES + (extra,))
    assert "TEST r.99" in [i["clause"] for i in requirements_for("written_statement")["items"]]
    assert "TEST r.99" in [i["clause"] for i in check_pleading("written_statement", {})["items"]]


@pytest.mark.parametrize("template", ["plaint_civil", "legal_notice"])
async def test_the_route_answers_and_is_not_swallowed_by_doc_id(template):
    from app.dependencies import get_current_user
    from app.main import app

    async def _user():
        return {"_id": "lawyer-x", "role": "lawyer", "is_active": True}

    app.dependency_overrides[get_current_user] = _user
    try:
        async with httpx.AsyncClient(transport=ASGITransport(app=app),
                                     base_url="http://test/api/v1") as c:
            res = await c.get(f"/documents/requirements/{template}")
    finally:
        app.dependency_overrides.clear()
    assert res.status_code == 200, res.text
    assert res.json()["covered"] is (template == "plaint_civil")
