"""A user must be told that filing falsely is itself an offence.

The Punjab Protection of Ownership of Immovable Property (Amendment) Ordinance
2026 (18 Feb 2026) raised the penalty for illegal possession to 5-10 years and a
fine up to Rs 10,000,000, and in the same instrument made a FALSE complaint
punishable by Rs 500,000 and up to five years.

Everything else in this feature helps a user press a claim. Nothing warned them
that pressing a weak one is now prosecutable. These tests pin the warning in
place, and pin the thing that makes it more than decoration: the service refuses
to file without an acknowledgement, so a UI that drops the warning fails loudly
instead of filing on the user's behalf.
"""
import pytest

from app.services import dispute_intake as di


class TestTheWarningItself:
    def test_punjab_names_the_statutory_penalty(self):
        r = di.false_complaint_risk("punjab")
        assert r["applies"] is True
        assert "500,000" in r["penalty"]
        assert "five years" in r["penalty"]
        assert "2026" in r["source"]

    def test_punjab_cites_the_enacted_act_not_the_superseded_ordinance(self):
        """Verified against the Punjab Gazette of 14 May 2026. The February 2026
        Ordinance that press coverage cites has since been enacted as Act XXXVII
        of 2026 — citing the spent Ordinance would send an auditor to the wrong
        instrument."""
        src = di.false_complaint_risk("punjab")["source"]
        assert "Act XXXVII of 2026" in src
        assert "s.16(3)" in src
        assert "14 May 2026" in src
        assert "Ordinance" not in src

    def test_the_mandatory_one_year_minimum_is_not_hidden(self):
        """s.16(3) reads 'may extend to five years but NOT LESS THAN ONE YEAR'.
        Press coverage rendered this as 'up to five years', which conceals a
        mandatory custodial floor. Understating a floor is the dangerous error."""
        pen = di.false_complaint_risk("punjab")["penalty"]
        assert "not less than one year" in pen

    def test_the_fine_is_stated_as_a_ceiling_not_a_flat_figure(self):
        """'fine which may extend to five hundred thousand rupees' is a maximum.
        Reporting it as 'a fine of Rs 500,000' overstates the certainty."""
        pen = di.false_complaint_risk("punjab")["penalty"]
        assert "may extend to Rs 500,000" in pen

    def test_other_provinces_get_a_warning_without_invented_figures(self):
        """The Punjab figures are Punjab's. Quoting them elsewhere would be
        fabricating law, which is the failure mode this codebase exists to avoid."""
        r = di.false_complaint_risk("sindh")
        assert r["applies"] is True
        assert "500,000" not in r["penalty"]
        assert "vary by province" in r["penalty"]

    def test_an_unknown_province_still_warns(self):
        """Failing open on the warning is the safe direction: silence is the one
        outcome that leaves the user exposed."""
        r = di.false_complaint_risk("atlantis")
        assert r["applies"] is True
        assert r["headline"]


def _intake(province="punjab"):
    """A complete, valid intake. The province drives which warning applies, so it
    must survive validation before the gate can pick the right text."""
    return {
        "property_description": "5 marla plot, Model Town",
        "province": province,
        "opposing_party": "Neighbour",
        "timeline": "Occupied since March 2026",
        "relief_wanted": "restore_possession",
    }


class TestTheGate:
    async def test_filing_without_acknowledgement_is_refused(self):
        with pytest.raises(di.FilingRiskNotAcknowledged) as exc:
            await di.create_dispute(
                "client1", "nicop", 200, "Someone occupied my plot",
                _intake(), acknowledged_filing_risk=False)
        assert "500,000" in str(exc.value)

    async def test_the_default_is_refusal_not_permission(self):
        """Omitting the argument entirely must not file. A caller that forgets
        the warning is exactly who this protects."""
        with pytest.raises(di.FilingRiskNotAcknowledged):
            await di.create_dispute(
                "client1", "nicop", 200, "Someone occupied my plot",
                _intake())

    async def test_the_refusal_says_what_the_risk_is(self):
        """An error reading 'acknowledgement required' teaches the user nothing.
        The message carries the penalty so the warning survives the failure."""
        with pytest.raises(di.FilingRiskNotAcknowledged) as exc:
            await di.create_dispute("c", "nicop", 200, "x", _intake())
        msg = str(exc.value)
        assert "false complaint" in msg.lower()
        assert "five years" in msg

    async def test_the_gate_runs_before_any_llm_call(self, monkeypatch):
        """Refusing early costs nothing; classifying first would spend an LLM call
        on a filing that cannot proceed."""
        called = {"n": 0}

        async def _spy(text):
            called["n"] += 1
            return {}

        monkeypatch.setattr(di, "classify_grievance", _spy)
        with pytest.raises(di.FilingRiskNotAcknowledged):
            await di.create_dispute("c", "nicop", 200, "x", _intake())
        assert called["n"] == 0
