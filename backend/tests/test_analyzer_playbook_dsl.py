"""Document Analyzer, P2A: the playbook condition language (pure)."""
from __future__ import annotations

import pytest

from app.services.analyzer.playbook_dsl import UNKNOWN, PlaybookError, evaluate, validate

F = lambda name: {"field": name}            # noqa: E731
V = lambda value: {"value": value}          # noqa: E731

CTX = {"document_type": "tenancy", "jurisdiction": "punjab",
       "terms": {"term_months": 11, "rent_period": "monthly", "tenancy_year_to_year": None}}


def ev(expr, ctx=CTX):
    validate(expr)
    return evaluate(expr, ctx)


def test_comparisons_on_confirmed_terms():
    assert ev({"eq": [F("jurisdiction"), V("punjab")]}) is True
    assert ev({"gt": [F("terms.term_months"), V(12)]}) is False
    assert ev({"lte": [F("terms.term_months"), V(12)]}) is True
    assert ev({"in": [F("terms.rent_period"), V(["monthly", "yearly"])]}) is True


def test_not_stated_is_unknown_and_unknown_propagates():
    year_to_year = {"eq": [F("terms.tenancy_year_to_year"), V(True)]}
    assert ev(year_to_year) is UNKNOWN
    assert ev({"not": [year_to_year]}) is UNKNOWN
    assert ev({"exists": [F("terms.tenancy_year_to_year")]}) is False
    absent = {"gt": [F("terms.rent_amount"), V(0)]}          # never answered at all
    assert ev(absent) is UNKNOWN


def test_kleene_all_and_any():
    t, f = {"eq": [V(1), V(1)]}, {"eq": [V(1), V(2)]}
    u = {"eq": [F("terms.tenancy_year_to_year"), V(True)]}
    assert ev({"all": [t, u]}) is UNKNOWN and ev({"all": [f, u]}) is False
    assert ev({"any": [t, u]}) is True and ev({"any": [f, u]}) is UNKNOWN
    assert ev({"all": [t, t]}) is True and ev({"any": [f, f]}) is False


def test_the_registration_limbs_read_as_written():
    # Any ONE limb is enough: year-to-year, over one year, or a yearly rent.
    limbs = {"any": [{"eq": [F("terms.tenancy_year_to_year"), V(True)]},
                     {"gt": [F("terms.term_months"), V(12)]},
                     {"eq": [F("terms.rent_period"), V("yearly")]}]}
    # 11 months, monthly, year-to-year NOT STATED: cannot say no.
    assert ev(limbs) is UNKNOWN
    assert ev(limbs, {**CTX, "terms": {**CTX["terms"], "tenancy_year_to_year": False}}) is False
    assert ev(limbs, {**CTX, "terms": {**CTX["terms"], "term_months": 13}}) is True


@pytest.mark.parametrize("expr,message", [
    ({"eq": [F("jurisdiction"), V("punjab")], "ne": []}, "exactly one operator"),
    ({"equals": [V(1), V(1)]}, "unknown operator"),
    ({"eq": [F("jurisdiction")]}, "exactly 2"),
    ({"eq": [F("province"), V("punjab")]}, "unknown field"),
    ({"eq": ["jurisdiction", V("punjab")]}, "operand must be"),          # a bare string
    ({"gt": [F("jurisdiction"), V("a")]}, "whole numbers"),
    ({"eq": [F("terms.term_months"), V("11")]}, "compares int with str"),
    ({"in": [F("jurisdiction"), V([])]}, "non-empty"),
    ({"in": [F("jurisdiction"), V(["punjab", 1])]}, "mixes types"),
    ({"all": []}, "at least one"),
    ({"exists": [V(1)]}, "exactly one {field"),
    ({"eq": [F("terms.tenancy_year_to_year"), V(1)]}, "compares bool with int"),
])
def test_malformed_conditions_never_load(expr, message):
    with pytest.raises(PlaybookError, match=message):
        validate(expr)
