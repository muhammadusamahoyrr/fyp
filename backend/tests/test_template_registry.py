"""The catalogue must describe the builders that actually exist.

The failure this guards against is not a crash. It is a registry that says a
template reads ten fields while its builder reads eleven: the form collects ten,
the eleventh renders as a blank line, and the shape report calls the document
complete. Every check here is about that class of quiet divergence.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.core.constants import DocumentTemplate
from app.services import template_registry as reg
from app.services.pdf_generator import _GENERATORS

pytestmark = pytest.mark.asyncio


# ── deriving the truth from the source ────────────────────────────────────────

_SOURCE = Path(__file__).resolve().parents[1] / "app" / "services" / "pdf_generator.py"

# Closures the builders define over their own field dict. `truthy("x")` reads x
# just as much as `f.get("x")` does.
_CLOSURES = {"truthy", "has", "nonempty", "yes", "stated"}


def _derive() -> dict[str, set[str]]:
    """Every top-level field key each builder reads, parsed from the module.

    Only `.get` on the builder's OWN field-dict parameter counts. Matching `.get`
    on any receiver pulls in loop variables — `heir`, `fraction` and `amount`
    come from iterating a list of heirs and are the shape of a nested object,
    not fields anybody submits.
    """
    tree = ast.parse(_SOURCE.read_text(encoding="utf-8"))
    funcs = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}

    names: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "_GENERATORS"
                for t in node.targets):
            for key, value in zip(node.value.keys, node.value.values):
                names[key.value] = value.id

    derived: dict[str, set[str]] = {}
    for template, fname in names.items():
        fn = funcs[fname]
        params = [a.arg for a in fn.args.args]
        holder = params[1] if len(params) > 1 else "f"

        keys: set[str] = set()
        for node in ast.walk(fn):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            first = node.args[0]
            if not (isinstance(first, ast.Constant)
                    and isinstance(first.value, str)):
                continue
            func = node.func
            if (isinstance(func, ast.Attribute) and func.attr == "get"
                    and isinstance(func.value, ast.Name)
                    and func.value.id == holder):
                keys.add(first.value)
            elif isinstance(func, ast.Name) and func.id in _CLOSURES:
                keys.add(first.value)
        derived[template] = keys
    return derived


async def test_the_field_map_matches_what_the_builders_read():
    """The anti-drift check this whole module rests on.

    If this fails, a builder gained or lost a field and FIELDS was not updated.
    Update FIELDS — do not relax this test. A registry that is allowed to be
    approximately right reports documents complete while a section of them
    renders empty, which is the exact failure it exists to prevent.
    """
    derived = _derive()
    assert set(derived) == set(reg.FIELDS), (
        "a builder was added or removed without updating FIELDS"
    )
    for template, keys in sorted(derived.items()):
        assert set(reg.FIELDS[template]) == keys, (
            f"{template}: registry has {sorted(reg.FIELDS[template])}, "
            f"the builder reads {sorted(keys)}"
        )


# ── the catalogue only offers what can be rendered ───────────────────────────

async def test_every_listed_template_has_a_builder():
    # The property the two hardcoded frontend lists did not have. Between them
    # they offered documents nothing could render.
    for item in reg.listing(include_system=True):
        assert item["template_type"] in _GENERATORS


async def test_every_builder_is_described():
    # The reverse direction: a builder with no entry is unreachable from the
    # picker, so the work of writing it is wasted rather than wrong.
    for template in _GENERATORS:
        assert reg.spec(template) is not None
        assert reg.spec(template)["label"]
        assert reg.spec(template)["description"]


async def test_every_constant_has_a_builder():
    # DocumentTemplate is what the API validates against. A member with no
    # builder is a 500 waiting for whoever selects it.
    for member in DocumentTemplate:
        assert reg.known(member.value), f"{member.value} has no builder"


async def test_a_system_issued_document_is_not_offered_for_drafting():
    # Nobody composes a receipt. A "generate a receipt" tile invites someone to
    # manufacture a record of a payment that never happened.
    offered = {i["template_type"] for i in reg.listing()}
    assert "payment_receipt" not in offered
    assert "payment_receipt" in {
        i["template_type"] for i in reg.listing(include_system=True)}


async def test_the_wakalatnama_entry_does_not_claim_to_be_one():
    # The builder's own docstring opens "THIS IS NOT A WAKALATNAMA" — Rule 4(4)
    # leaves the instrument's contents to the High Court Rules and Orders, which
    # this system does not hold. A picker that rounds that up sends someone to
    # court with a checklist believing it is an appointment.
    entry = reg.spec("wakalatnama_checklist")
    assert "checklist" in entry["label"].lower()
    assert "NOT a Vakalatnama" in entry["description"]


# ── shape reporting ───────────────────────────────────────────────────────────

async def test_an_unreadable_key_is_reported_rather_than_dropped():
    # THE finding this report exists for. A misspelled key is discarded in
    # silence today, and the document renders with an empty line where the user
    # believes they supplied a value.
    report = reg.shape_report("nda", {
        "party_a": "A Ltd", "party_b": "B Ltd", "purpose": "evaluation",
        "partyA": "A Ltd",          # camelCase typo
        "jurisdiciton": "Lahore",   # misspelling
    })
    assert report["unknown"] == ["jurisdiciton", "partyA"]
    assert "party_a" in report["provided"]


async def test_a_blank_string_counts_as_absent():
    # "   " in a form field is the user having typed nothing, and it renders as
    # nothing. Counting it as provided would report a hole as filled.
    report = reg.shape_report("nda", {"party_a": "   ", "party_b": "B"})
    assert "party_a" in report["blank"]
    assert "party_b" in report["provided"]


async def test_zero_and_false_are_values_somebody_chose():
    # A rent due day of 0 or a `pre_arrest: False` is an answer, not an absence,
    # and reporting it blank would send the user back to re-enter what they
    # already decided.
    report = reg.shape_report("bail_application", {"pre_arrest": False})
    assert "pre_arrest" in report["provided"]
    report = reg.shape_report("rental_agreement", {"rent_due_day": 0})
    assert "rent_due_day" in report["provided"]


async def test_an_empty_structured_field_is_blank():
    # An empty calculation renders an empty table under a heading promising one.
    report = reg.shape_report("labour_demand", {"calculation": {}})
    assert "calculation" in report["blank"]
    report = reg.shape_report("labour_demand", {"calculation": {"total": 1}})
    assert "calculation" in report["provided"]


async def test_an_unknown_template_reports_nothing_rather_than_all_clear():
    # An empty `blank` list on an unknown template reads as a pass. It is not
    # one — nothing was checked, and the report says which.
    report = reg.shape_report("no_such_template", {"a": 1})
    assert report["checked"] is False
    assert report["reason"] == "unknown_template"


async def test_the_report_never_claims_legal_completeness():
    # Requiredness for the four templates a statute enumerates belongs to
    # pleading_rules. This report must not grow a "required" or "complete" key
    # and start asserting a statutory requirement nobody checked.
    report = reg.shape_report("plaint_civil", {})
    assert "required" not in report
    assert "complete" not in report
    assert "compliant" not in report


async def test_structured_fields_are_declared_as_such():
    # A form that renders a text input for `computation` collects a string, and
    # the builder emits an empty computation table with no warning.
    for template, structured in reg.STRUCTURED.items():
        assert structured <= reg.FIELDS[template], (
            f"{template} declares a structured field its builder never reads")
        assert set(reg.spec(template)["structured_fields"]) == set(structured)
