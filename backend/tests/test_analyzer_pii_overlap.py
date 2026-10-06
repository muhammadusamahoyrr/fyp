"""Overlapping uncertainty flags (pii-mask.9). New synthetic development
fixtures only -- pii-eval-7 and every spent set are never opened.

The dead end, reproduced first: "Signed by Bilal Malik House 12 Butt Road 3."
raises two flags that overlap without either containing the other -- "Butt
Road" (a signer?) and "Road 3" (an address?). A flag counted as decided only
when ONE decision contained it, the API refuses overlapping decisions, and the
screen refused a selection that touched a flag: the lawyer could not resolve
both, so the request could never be sent.

Now:
  * overlapping flags are ONE region that keeps every reason;
  * a region is resolved only when decisions cover every character of it;
    an uncovered part stays flagged, as its own (smaller) region;
  * "not personal" is accepted on any part of a flagged region;
  * overlapping decisions are still refused (incompatible decisions block).
"""
from __future__ import annotations

import pytest

from app.services.analyzer import pii_confirmation, pii_mask, receipts
from app.services.analyzer import pii_evaluation as ev
from app.services.analyzer.errors import UploadRejected
from tests.test_analyzer_pii_evaluation import doc, send_capture
from tests.test_analyzer_pii_identity import at, sent
from tests.test_analyzer_pii_mask import masked

TEXT = "Landlord: Bilal Malik.\nSigned by Bilal Malik House 12 Butt Road 3.\n"


def remask(decisions):
    rows = ev._rows(TEXT)
    return pii_mask.prepare(TEXT, rows, {r["sentence_id"] for r in rows}, decisions), rows


def spans(m):
    return [(TEXT[u["start"]:u["end"]], tuple(u.get("reasons", [u["reason"]]))) for u in m.uncertain]


def decide(value, decision, nth=0):
    a, b = at(TEXT, value, nth)
    return {"start": a, "end": b, "decision": decision}


def test_overlapping_flags_are_one_region_that_keeps_every_reason():
    m, _ = masked(TEXT)
    [(region, reasons)] = [s for s in spans(m) if "Road" in s[0]]
    assert region == "Butt Road 3"
    assert set(reasons) == {"signer_not_recognised", "address_not_delimited"}


def test_one_decision_on_the_region_resolves_it():
    m, _ = remask([decide("Butt Road 3", "address")])
    assert not m.uncertain and "Butt" not in sent(m) and "Road 3" not in sent(m)


def test_deciding_part_of_a_region_leaves_the_rest_flagged_never_cleared():
    m, _ = remask([decide("Road 3", "address")])
    assert spans(m) == [("Butt", ("signer_not_recognised",))]             # the rest, with its own reason
    done, _ = remask([decide("Road 3", "address"), decide("Butt", "not_personal")])
    assert not done.uncertain and "Butt" in sent(done) and "Road 3" not in sent(done)


def test_the_api_accepts_decisions_on_parts_of_a_region_and_refuses_overlaps():
    rows = ev._rows(TEXT)
    ids = {r["sentence_id"] for r in rows}
    ok = [decide("Butt", "not_personal"), decide("Road 3", "address")]
    assert pii_confirmation._validated(TEXT, rows, ids, ok)              # before: "not_flagged" on "Butt"
    with pytest.raises(UploadRejected) as e:
        pii_confirmation._validated(TEXT, rows, ids, [decide("Butt Road", "personal_name"), decide("Road 3", "address")])
    assert e.value.code == "overlapping_spans"                           # incompatible decisions still block
    with pytest.raises(UploadRejected) as e:
        pii_confirmation._validated(TEXT, rows, ids, [decide("Landlord", "not_personal")])
    assert e.value.code == "not_flagged"                                 # outside every region: refused


def test_each_effective_resolution_is_a_different_request():
    a, _ = remask([decide("Butt Road 3", "address")])
    b, _ = remask([decide("Road 3", "address"), decide("Butt", "not_personal")])
    def digest(m):
        return receipts.request_digest([{"role": "user", "content": sent(m)}])
    assert digest(a) != digest(b)                                        # each needs its own approval


def test_resolving_a_region_keeps_the_reviewed_identities():
    first = remask([decide("Bilal Malik", "different_person", 1), decide("Butt Road 3", "address")])[0]
    tokens = {TEXT[x:y] + f"@{x}": t for x, y, k, t in first.masked_spans if k == "NAME"}
    assert len(set(tokens.values())) == 2                                # the reviewer separated the two mentions
    again = remask([decide("Bilal Malik", "different_person", 1), decide("Road 3", "address"),
                    decide("Butt", "not_personal")])[0]
    assert {TEXT[x:y] + f"@{x}": t for x, y, k, t in again.masked_spans if k == "NAME"} == tokens


def test_the_simulated_reviewer_resolves_an_overlapping_region_through_the_api():
    d = doc("Landlord: [[NAME:p1|Bilal Malik]].\nSigned by [[NAME:p1|Bilal Malik]] "
            "[[ADDRESS:a1|House 12 Butt Road 3]] [[DEADLINE:d1|within 7 days]].", parties=["p1"])
    for mode in ("manual", "review"):
        r = ev.score_document(d, send_capture([]), mode=mode, pipeline="production-rules-only")
        assert not any(x.startswith("api_rejected") for x in r["block_reasons"]), (mode, r["block_reasons"])
    r = ev.score_document(d, send_capture([]), mode="review", pipeline="production-rules-only")
    assert r["sent"] and sum(s["leak"] for s in r["spans"]) == 0 and r["deadlines_preserved"] is True


def test_not_personal_on_any_part_of_a_region_is_accepted_and_resolves_only_that_part():
    rows = ev._rows(TEXT)
    ids = {r["sentence_id"] for r in rows}
    part = [decide("Butt", "not_personal")]                     # inside the region "Butt Road 3", not equal to it
    assert pii_confirmation._validated(TEXT, rows, ids, part)
    m, _ = remask(part)
    assert spans(m) == [("Road 3", ("address_not_delimited", "signer_not_recognised"))]   # the rest still waits
