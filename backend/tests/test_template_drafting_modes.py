"""The catalogue tells the UI how each builder can safely receive input."""
from __future__ import annotations

import pytest

from app.api.v1.routes.documents import list_templates
from app.services import document_service

pytestmark = pytest.mark.asyncio


async def test_every_template_has_one_honest_drafting_mode():
    items = await list_templates(current_user={"_id": "user-1"})
    assert items

    for item in items:
        if item["structured_fields"]:
            assert item["drafting_mode"] == "dedicated"
        elif document_service.supports_field_extraction(item["template_type"]):
            assert item["drafting_mode"] == "ai"
        else:
            assert item["drafting_mode"] == "manual"


async def test_the_nine_templates_without_prompts_are_not_labelled_ai():
    items = await list_templates(current_user={"_id": "user-1"})
    by_type = {item["template_type"]: item for item in items}
    missing = {
        "bail_application", "dispute_petition", "inheritance_demand",
        "inheritance_settlement", "labour_demand", "poa_revocation",
        "power_of_attorney", "urdu_pleading", "wasiyyat_nama",
    }
    assert missing <= set(by_type)
    assert all(by_type[key]["drafting_mode"] != "ai" for key in missing)
