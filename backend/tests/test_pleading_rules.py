"""Pleading compliance against the CPC.

The drafter produced a PDF and nothing checked whether it contained what a court
requires — so a plaint missing its jurisdiction facts looked exactly as finished
as a complete one. A pleading returned for non-compliance costs a litigant a
hearing date.

Every requirement here is quoted from the Code of Civil Procedure 1908. The
structure of a pleading is statutory, not stylistic: Order VI Rule 3 provides
that "the forms in Appendix A, when applicable, and forms of like character
shall be used for all pleadings."
"""
import pytest

from app.services import pleading_rules as pr

COMPLETE = {
    "court": "Court of the Senior Civil Judge, Lahore",
    "plaintiff_name": "Ali Khan", "plaintiff_address": "12 Model Town, Lahore",
    "defendant_name": "Bilal Ahmed", "defendant_address": "44 Gulberg, Lahore",
    "facts": "The defendant occupied the plot on 3 March 2026 without right.",
    "cause_of_action": "Dispossession on 3 March 2026",
    "jurisdiction_facts": "The property is situated within this Court's territorial limits.",
    "relief_sought": "Restoration of possession and permanent injunction",
    "suit_value": 2_500_000,
    "verification": "Verified at Lahore on 24 August 2026 that paras 1-4 are true to knowledge.",
}


class TestACompletePlaint:
    def test_it_passes(self):
        r = pr.check_pleading(pr.PLAINT, COMPLETE)
        assert r["complete"] is True
        assert r["missing"] == 0

    def test_conditional_clauses_are_not_counted_as_missing(self):
        """Order VII Rule 1(d) and (h) apply only when those facts exist.
        Flagging them on every ordinary plaint would train users to ignore the
        report — worse than having no report."""
        r = pr.check_pleading(pr.PLAINT, COMPLETE)
        na = [i["clause"] for i in r["items"] if i["status"] == "not_applicable"]
        assert "(d)" in na and "(h)" in na

    def test_conditional_clauses_apply_when_context_says_so(self):
        r = pr.check_pleading(pr.PLAINT, COMPLETE,
                              {"party_is_minor_or_unsound": True})
        d = next(i for i in r["items"] if i["clause"] == "(d)")
        assert d["status"] == "missing"


class TestEachRequirementIsActuallyChecked:
    @pytest.mark.parametrize("drop,clause", [
        ("court", "(a)"),
        ("plaintiff_name", "(b)"),
        ("defendant_name", "(c)"),
        ("cause_of_action", "(e)"),
        ("jurisdiction_facts", "(f)"),
        ("relief_sought", "(g)"),
        ("suit_value", "(i)"),
        ("verification", "Order VI Rule 15"),
    ])
    def test_removing_a_field_flags_its_clause(self, drop, clause):
        draft = {k: v for k, v in COMPLETE.items() if k != drop}
        r = pr.check_pleading(pr.PLAINT, draft)
        item = next(i for i in r["items"] if i["clause"] == clause)
        assert item["status"] == "missing"
        assert r["complete"] is False

    def test_a_name_without_an_address_does_not_satisfy_the_clause(self):
        """Rule 1(b) is "name, description and place of residence" — all of it."""
        draft = {k: v for k, v in COMPLETE.items() if k != "plaintiff_address"}
        r = pr.check_pleading(pr.PLAINT, draft)
        b = next(i for i in r["items"] if i["clause"] == "(b)")
        assert b["status"] == "missing"
        assert "incomplete" in b["detail"]

    def test_blank_strings_do_not_count_as_present(self):
        draft = dict(COMPLETE, relief_sought="   ")
        r = pr.check_pleading(pr.PLAINT, draft)
        g = next(i for i in r["items"] if i["clause"] == "(g)")
        assert g["status"] == "missing"

    def test_a_zero_valuation_is_not_a_valuation(self):
        draft = dict(COMPLETE, suit_value=0)
        r = pr.check_pleading(pr.PLAINT, draft)
        i = next(x for x in r["items"] if x["clause"] == "(i)")
        assert i["status"] == "missing"

    def test_alternate_field_names_are_accepted(self):
        """A template may call the same particular something else."""
        draft = {k: v for k, v in COMPLETE.items() if k != "relief_sought"}
        draft["prayer"] = "Restoration of possession"
        r = pr.check_pleading(pr.PLAINT, draft)
        assert r["complete"] is True


class TestItCitesTheLaw:
    def test_every_finding_names_its_rule(self):
        """A finding the user cannot check is just an opinion."""
        r = pr.check_pleading(pr.PLAINT, {})
        assert all(i["clause"] and i["requirement"] for i in r["items"])

    def test_the_basis_is_stated(self):
        r = pr.check_pleading(pr.PLAINT, COMPLETE)
        assert "Order VII Rule 1" in r["basis"]
        assert "Appendix A" in r["source_note"]

    def test_it_does_not_claim_to_be_legal_advice(self):
        r = pr.check_pleading(pr.PLAINT, COMPLETE)
        assert "not legal advice" in r["advisory"]


class TestScope:
    def test_a_written_statement_is_checked_against_order_vi_only(self):
        r = pr.check_pleading(pr.WRITTEN_STATEMENT, {"facts": "Denied.",
                                                     "verification": "Verified."})
        assert r["checked"] is True
        assert all(i["clause"].startswith("Order VI") for i in r["items"])

    def test_an_unknown_type_says_it_was_not_checked(self):
        """Silence would read as a pass. It has to say so."""
        r = pr.check_pleading("nda", COMPLETE)
        assert r["checked"] is False
        assert "not a finding of compliance" in r["reason"]
        assert r["items"] == []

    def test_an_empty_plaint_flags_everything_applicable(self):
        r = pr.check_pleading(pr.PLAINT, {})
        # Order VII Rule 1 has 9 clauses; (d) and (h) are conditional, so 7
        # apply unconditionally. Plus Order VI Rules 2 and 15 = 9.
        assert r["missing"] == 9
        assert r["satisfied"] == 0
