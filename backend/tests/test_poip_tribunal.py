"""The anti-dispossession tribunal must be offered where it applies.

Punjab's special court under the Overseas Pakistanis Property regime is still
ENACTED_PENDING — enacted, judges being designated, not yet sitting. Meanwhile the
Punjab Protection of Ownership of Immovable Property (Amendment) Ordinance 2026
(18 Feb 2026) tightened a tribunal aimed squarely at illegal possession, with a
30-day decision clock.

Every recorded dispute in this system so far is an illegal-occupation case. Sending
all of them to a court that is not yet hearing cases, while a 30-day tribunal
exists, is a confident wrong answer — the failure mode this codebase treats as
worse than admitting uncertainty.
"""
import pytest

from app.services import dispute_intake as di
from app.services import special_court as sc


class TestTheTribunalLookup:
    def test_punjab_dispossession_gets_the_tribunal(self):
        t = sc.poip_tribunal("punjab", "illegal_occupation")
        assert t is not None
        assert t["decision_days"] == 30
        assert "2026" in t["act"]

    def test_encroachment_also_qualifies(self):
        assert sc.poip_tribunal("punjab", "encroachment") is not None

    def test_an_inheritance_quarrel_does_not(self):
        """An anti-dispossession tribunal is the wrong forum for an inheritance
        dispute. Offering it there would be worse than offering nothing."""
        assert sc.poip_tribunal("punjab", "inheritance_dispute") is None

    def test_poa_misuse_does_not(self):
        assert sc.poip_tribunal("punjab", "poa_misuse") is None

    def test_a_province_with_no_recorded_regime_gets_nothing_invented(self):
        assert sc.poip_tribunal("sindh", "illegal_occupation") is None
        assert sc.poip_tribunal("balochistan", "illegal_occupation") is None

    def test_no_category_returns_the_regime_itself(self):
        """Callers that only want to know whether a province HAS such a tribunal
        should not have to pass a grievance."""
        assert sc.poip_tribunal("punjab") is not None

    def test_the_statutory_text_is_established_not_merely_reported(self):
        """Read off the Punjab Gazette of 14 May 2026 (Act XXXVII of 2026), so it
        is no longer 'reported'. The citation must name the Act, not the spent
        February Ordinance that press coverage quotes."""
        t = sc.poip_tribunal("punjab", "illegal_occupation")
        assert t["confidence"] == "established"
        assert "Act XXXVII of 2026" in t["act"]
        assert "14 May 2026" in t["source"]

    def test_it_still_disclaims_what_the_statute_cannot_tell_us(self):
        """Verifying the Act does not verify that a Tribunal has actually been
        notified for a district under s.11(1) — that is an executive act, not
        part of the statute. The verify duty narrows; it does not vanish."""
        t = sc.poip_tribunal("punjab", "illegal_occupation")
        assert "notified" in t["verify"]

    def test_the_thirty_day_clock_records_what_it_runs_from(self):
        """s.16(6) runs 30 days from RECEIPT OF THE COMMITTEE'S REPORT, not from
        filing — the same trap as the special court's 90-day leave-to-defend
        clock. A bare '30 days' sets the wrong expectation."""
        t = sc.poip_tribunal("punjab", "illegal_occupation")
        assert t["decision_days"] == 30
        assert "report" in t["decision_clock_starts"]
        assert t["realistic_floor_days"] == 63   # 3 (s.7(3)) + 30 (s.8(4)) + 30 (s.16(6))

    def test_the_caller_cannot_mutate_the_table(self):
        t = sc.poip_tribunal("punjab", "illegal_occupation")
        t["decision_days"] = 999
        assert sc.poip_tribunal("punjab", "illegal_occupation")["decision_days"] == 30


class TestItReachesTheUser:
    def test_a_held_punjab_land_grab_names_the_tribunal(self):
        """The hold reason must not stop at 'no court yet' when a faster route is
        open today -- and must not promise 30 days from filing either."""
        out = di._decide_state(
            {"eligible": True},
            {"needs_triage": False, "category": "illegal_occupation"},
            {"province": "Punjab", "court_status": sc.ENACTED_PENDING},
        )
        assert out["state"] == di.STATE_HELD
        joined = " ".join(out["hold_reasons"])
        assert "30 days" in joined
        assert "63 days from filing" in joined, "must not imply 30 days from filing"
        assert "lawyer" in joined.lower()

    def test_a_held_inheritance_case_is_not_offered_the_tribunal(self):
        out = di._decide_state(
            {"eligible": True},
            {"needs_triage": False, "category": "inheritance_dispute"},
            {"province": "Punjab", "court_status": sc.ENACTED_PENDING},
        )
        assert "30 days" not in " ".join(out["hold_reasons"])

    def test_the_alternative_is_computed_independently_of_holding(self):
        """A user whose special court IS operational should still learn a 30-day
        tribunal covers their land grab."""
        alt = di.alternative_forum(
            {"province": "Punjab", "court_status": sc.OPERATIONAL},
            {"category": "illegal_occupation"},
        )
        assert alt is not None and alt["decision_days"] == 30
