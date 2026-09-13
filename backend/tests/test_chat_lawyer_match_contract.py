"""The chat surface must report what the matching service actually said.

THE DEFECT

`match_lawyers_for_case` returns `{"result_kind", "notice", "matches"}`.
`_fetch_matched_lawyers` iterated that dict directly, so the loop variable was
the string `"result_kind"`, `m.get` raised `AttributeError`, and a bare `except`
turned the whole thing into `[]`. The chat surface has shown **zero** matched
lawyers for every session since — silently, because the failure produced an
empty list, which is indistinguishable from a genuine absence of candidates.

That indistinguishability is why these tests separate four outcomes that the old
code collapsed into one:

    matched          ranked candidates, each with a score
    general_listing  nothing qualified; verified lawyers for BROWSING, and the
                     service sets match_score to None precisely so nothing can
                     present them as ranked
    none             no verified lawyers at all
    unavailable      no case to match against, or the lookup failed — which is
                     NOT the same as "there are none"

No ranking or eligibility logic is touched here. This is about carrying the
service's verdict across a boundary without losing or inventing anything.
"""
from __future__ import annotations

import logging

import pytest

from app.websockets import chat_socket


def _lawyer(_id="L1", score=0.83, province="punjab", rating=4.5):
    return {
        "_id": _id, "full_name": f"Adv {_id}", "province": province,
        "match_score": score, "match_reason": "specialises in civil",
        "lawyer_profile": {"rating": rating, "specializations": ["civil"]},
    }


@pytest.fixture
def service(monkeypatch):
    """Replace the matching service. Ranking itself is not under test."""
    state: dict = {"result": None, "raises": None, "calls": 0}

    async def fake(case_id, top_n=5):
        state["calls"] += 1
        if state["raises"] is not None:
            raise state["raises"]
        return state["result"]

    from app.services import lawyer_service
    monkeypatch.setattr(lawyer_service, "match_lawyers_for_case", fake)
    return state


SESSION = {"case_id": "case-1"}


# ── the three result kinds ─────────────────────────────────────────────────

async def test_ranked_matches_are_read_from_the_matches_list(service):
    """The regression. Iterating the dict yielded its KEYS, so this was []."""
    service["result"] = {"result_kind": "matched", "notice": "",
                         "matches": [_lawyer("L1"), _lawyer("L2", score=0.71)]}

    out = await chat_socket._fetch_matched_lawyers(SESSION, n=3)

    assert out["result_kind"] == "matched"
    assert len(out["matched_lawyers"]) == 2, (
        "candidates were not read from the service's matches list")
    assert out["matched_lawyers"][0]["full_name"] == "Adv L1"
    assert out["matched_lawyers"][0]["match_score"] == 0.83


async def test_a_general_listing_keeps_its_null_scores(service):
    """The service sets match_score to None so nothing can rank these.

    Defaulting it to 0.0 here is what let the UI render "0% match" — a precise
    number for a measurement that was never made.
    """
    service["result"] = {
        "result_kind": "general_listing",
        "notice": "No specific match; showing verified lawyers.",
        "matches": [_lawyer("L9", score=None)],
    }

    out = await chat_socket._fetch_matched_lawyers(SESSION, n=3)

    assert out["result_kind"] == "general_listing"
    assert out["matched_lawyers"][0]["match_score"] is None, (
        "an unranked candidate was given a score")
    assert out["notice"].startswith("No specific match")


async def test_no_candidates_is_reported_as_none_not_as_a_failure(service):
    service["result"] = {"result_kind": "none",
                         "notice": "No verified lawyers are available.",
                         "matches": []}

    out = await chat_socket._fetch_matched_lawyers(SESSION, n=3)

    assert out["result_kind"] == "none"
    assert out["matched_lawyers"] == []
    assert out["notice"]


# ── the two ways there is nothing to say ───────────────────────────────────

async def test_a_session_with_no_case_never_calls_the_service(service):
    """Nothing to match against. Not a failure, and not 'no lawyers found'."""
    out = await chat_socket._fetch_matched_lawyers({}, n=3)

    assert out["result_kind"] == chat_socket.MATCH_KIND_UNAVAILABLE
    assert out["matched_lawyers"] == []
    assert service["calls"] == 0, "the matcher was run for a session with no case"


async def test_a_service_failure_does_not_break_the_chat_turn(service):
    service["raises"] = RuntimeError("boom")

    out = await chat_socket._fetch_matched_lawyers(SESSION, n=3)

    assert out["result_kind"] == chat_socket.MATCH_KIND_UNAVAILABLE
    assert out["matched_lawyers"] == []


async def test_unavailable_is_distinguishable_from_no_candidates(service):
    """The whole point. `[]` meant both, so a broken lookup looked exactly like
    a genuine absence — and that is how this defect survived."""
    service["result"] = {"result_kind": "none", "notice": "", "matches": []}
    genuine = await chat_socket._fetch_matched_lawyers(SESSION, n=3)

    service["raises"] = RuntimeError("boom")
    broken = await chat_socket._fetch_matched_lawyers(SESSION, n=3)

    assert genuine["matched_lawyers"] == broken["matched_lawyers"] == []
    assert genuine["result_kind"] != broken["result_kind"]


async def test_a_non_mapping_result_is_handled_rather_than_crashing(service):
    """Exactly the shape that caused the original bug, if it ever returns."""
    service["result"] = [_lawyer("L1")]

    out = await chat_socket._fetch_matched_lawyers(SESSION, n=3)

    assert out["result_kind"] == chat_socket.MATCH_KIND_UNAVAILABLE
    assert out["matched_lawyers"] == []


async def test_malformed_entries_are_skipped_not_crashed_on(service):
    service["result"] = {"result_kind": "matched", "notice": "",
                         "matches": [_lawyer("L1"), "not-a-lawyer", None]}

    out = await chat_socket._fetch_matched_lawyers(SESSION, n=3)

    assert len(out["matched_lawyers"]) == 1


# ── diagnostics: useful, and safe ──────────────────────────────────────────

async def test_a_failure_is_logged_without_the_exception_body(service, caplog):
    """A diagnostic line, not a place to reproduce whatever the error quoted.

    An exception body can carry a query, a document fragment or an identifier;
    the class name is what makes the failure findable.
    """
    service["raises"] = RuntimeError(
        "connection to mongodb://user:pw@host failed for CNIC 35201-1234567-1")

    with caplog.at_level(logging.WARNING):
        await chat_socket._fetch_matched_lawyers(SESSION, n=3)

    body = caplog.text
    assert "RuntimeError" in body, "the failure was swallowed with no diagnostic"
    assert "35201-1234567-1" not in body
    assert "mongodb://" not in body
    assert "user:pw" not in body


async def test_the_failure_log_names_no_case_or_client(service, caplog):
    service["raises"] = ValueError("x")

    with caplog.at_level(logging.WARNING):
        await chat_socket._fetch_matched_lawyers({"case_id": "case-SECRET-42"},
                                                 n=3)

    assert "case-SECRET-42" not in caplog.text


async def test_a_successful_match_logs_no_warning(service, caplog):
    service["result"] = {"result_kind": "matched", "notice": "",
                         "matches": [_lawyer()]}

    with caplog.at_level(logging.WARNING):
        await chat_socket._fetch_matched_lawyers(SESSION, n=3)

    assert "lawyer matching" not in caplog.text, (
        "a healthy path logged a warning, which trains people to ignore them")


# ── the shape the socket hands to both response paths ──────────────────────

async def test_the_payload_shape_is_stable_across_every_outcome(service):
    """Both call sites index the same three keys, so every path must have them."""
    outcomes = [
        {"result_kind": "matched", "notice": "", "matches": [_lawyer()]},
        {"result_kind": "general_listing", "notice": "n", "matches": [_lawyer(score=None)]},
        {"result_kind": "none", "notice": "n", "matches": []},
    ]
    for result in outcomes:
        service["result"] = result
        out = await chat_socket._fetch_matched_lawyers(SESSION, n=3)
        assert set(out) == {"result_kind", "notice", "matched_lawyers"}
        assert isinstance(out["matched_lawyers"], list)

    service["raises"] = RuntimeError("boom")
    out = await chat_socket._fetch_matched_lawyers(SESSION, n=3)
    assert set(out) == {"result_kind", "notice", "matched_lawyers"}

    out = await chat_socket._fetch_matched_lawyers({}, n=3)
    assert set(out) == {"result_kind", "notice", "matched_lawyers"}


async def test_no_lawyer_payload_carries_a_path_or_internal_field(service):
    """What reaches the browser is a fixed projection, not the raw document."""
    raw = _lawyer()
    raw["specialization_embedding"] = [0.1] * 384
    raw["email"] = "private@example.com"
    raw["cnic_encrypted"] = "SECRET"
    service["result"] = {"result_kind": "matched", "notice": "", "matches": [raw]}

    out = await chat_socket._fetch_matched_lawyers(SESSION, n=3)
    entry = out["matched_lawyers"][0]

    assert set(entry) == {"id", "full_name", "province", "match_score",
                          "match_reason", "rating", "specializations"}
    assert "private@example.com" not in repr(entry)
    assert "SECRET" not in repr(entry)
    assert "specialization_embedding" not in entry


# ── malformed shapes must cost one row, never the conversation ─────────────
#
# The old projection trusted a nested value: `(m.get("lawyer_profile") or {})`
# guards None and "", but a profile that is a STRING or a LIST is truthy, so
# `.get` was called on it and raised AttributeError — taking down the whole
# chat turn. Each case below was reproduced against the code before the fix.

@pytest.mark.parametrize("profile", ["oops", ["a", "b"], 42, True, ("x",)])
async def test_a_non_mapping_lawyer_profile_does_not_break_the_turn(service, profile):
    service["result"] = {"result_kind": "matched", "notice": "",
                         "matches": [{**_lawyer(), "lawyer_profile": profile}]}

    out = await chat_socket._fetch_matched_lawyers(SESSION, n=3)

    assert len(out["matched_lawyers"]) == 1
    assert out["matched_lawyers"][0]["rating"] == 0.0
    assert out["matched_lawyers"][0]["specializations"] == []


async def test_non_list_specializations_never_reach_the_component(service):
    """A bare string would be rendered with `.slice().join()`, which is a
    TypeError on a string — a malformed record crashing the UI that shows it."""
    service["result"] = {"result_kind": "matched", "notice": "", "matches": [
        {**_lawyer(), "lawyer_profile": {"rating": 4.0, "specializations": "civil"}}]}

    out = await chat_socket._fetch_matched_lawyers(SESSION, n=3)

    assert out["matched_lawyers"][0]["specializations"] == []


async def test_non_string_specialisation_entries_are_dropped(service):
    service["result"] = {"result_kind": "matched", "notice": "", "matches": [
        {**_lawyer(), "lawyer_profile": {"specializations": ["civil", 7, None, "family"]}}]}

    assert out_specs(await chat_socket._fetch_matched_lawyers(SESSION, n=3)) == \
        ["civil", "family"]


def out_specs(out):
    return out["matched_lawyers"][0]["specializations"]


@pytest.mark.parametrize("rating", ["high", None, [1], True, {"x": 1}])
async def test_a_non_numeric_rating_becomes_zero_not_a_crash(service, rating):
    service["result"] = {"result_kind": "matched", "notice": "", "matches": [
        {**_lawyer(), "lawyer_profile": {"rating": rating}}]}

    out = await chat_socket._fetch_matched_lawyers(SESSION, n=3)

    assert out["matched_lawyers"][0]["rating"] == 0.0


@pytest.mark.parametrize("score,expected", [
    (0.83, 0.83),
    (0.0, 0.0),            # a genuine measurement of a poor fit — must survive
    (None, None),          # the service saying "not ranked"
    ("0.9", None),         # a string is not a measurement
    (True, None),          # isinstance(True, int) is True — must not become 100%
    ([0.5], None),
])
async def test_match_scores_are_preserved_or_dropped_never_invented(
        service, score, expected):
    service["result"] = {"result_kind": "matched", "notice": "",
                         "matches": [{**_lawyer(), "match_score": score}]}

    out = await chat_socket._fetch_matched_lawyers(SESSION, n=3)

    assert out["matched_lawyers"][0]["match_score"] == expected


async def test_one_malformed_row_does_not_remove_the_healthy_ones(service):
    service["result"] = {"result_kind": "matched", "notice": "", "matches": [
        _lawyer("L1"),
        {**_lawyer("L2"), "lawyer_profile": "broken"},
        _lawyer("L3"),
    ]}

    out = await chat_socket._fetch_matched_lawyers(SESSION, n=3)

    assert [l["full_name"] for l in out["matched_lawyers"]] == \
        ["Adv L1", "Adv L2", "Adv L3"]


@pytest.mark.parametrize("matches", ["nope", None, 42, {"a": 1}])
async def test_a_non_list_matches_value_is_treated_as_malformed(service, matches):
    """A string is iterable, so the old loop walked it character by character
    and reported "matched" with no candidates — a healthy-looking empty."""
    service["result"] = {"result_kind": "matched", "notice": "", "matches": matches}

    out = await chat_socket._fetch_matched_lawyers(SESSION, n=3)

    assert out["result_kind"] == chat_socket.MATCH_KIND_UNAVAILABLE
    assert out["matched_lawyers"] == []


async def test_missing_identity_fields_do_not_crash(service):
    service["result"] = {"result_kind": "matched", "notice": "", "matches": [
        {"_id": None, "full_name": None, "province": None, "match_score": None}]}

    out = await chat_socket._fetch_matched_lawyers(SESSION, n=3)
    entry = out["matched_lawyers"][0]

    assert entry["id"] == "" and entry["full_name"] == ""
    assert entry["match_score"] is None


# ── non-finite numbers: real floats that JSON cannot carry ─────────────────
#
# NaN and ±Infinity satisfy `isinstance(x, float)`, so a type check waves them
# through. Python's json module then emits the bare tokens `NaN` and `Infinity`,
# which are NOT valid JSON — `JSON.parse` rejects them — so a single non-finite
# value makes the whole websocket frame unparseable in the browser and takes
# down a chat turn that had otherwise succeeded.

NON_FINITE = [float("nan"), float("inf"), float("-inf")]
NON_FINITE_IDS = ["nan", "+inf", "-inf"]


@pytest.mark.parametrize("score", NON_FINITE, ids=NON_FINITE_IDS)
async def test_a_non_finite_score_becomes_none(service, score):
    """A score that cannot be transmitted is not a score."""
    service["result"] = {"result_kind": "matched", "notice": "",
                         "matches": [{**_lawyer(), "match_score": score}]}

    out = await chat_socket._fetch_matched_lawyers(SESSION, n=3)

    assert out["matched_lawyers"][0]["match_score"] is None


@pytest.mark.parametrize("rating", NON_FINITE, ids=NON_FINITE_IDS)
async def test_a_non_finite_rating_follows_the_unavailable_convention(service, rating):
    """0.0, not None — that is what every other path already means by "no
    rating", and the UI omits the stars rather than printing a zero."""
    service["result"] = {"result_kind": "matched", "notice": "", "matches": [
        {**_lawyer(), "lawyer_profile": {"rating": rating}}]}

    out = await chat_socket._fetch_matched_lawyers(SESSION, n=3)

    assert out["matched_lawyers"][0]["rating"] == 0.0


async def test_legitimate_zeros_survive_the_finiteness_check(service):
    """The guard must not sweep up real measurements.

    A 0.0 score is a genuine verdict of a poor fit, and a 0.0 rating is a real
    unrated lawyer. Neither is non-finite.
    """
    service["result"] = {"result_kind": "matched", "notice": "", "matches": [
        {**_lawyer(), "match_score": 0.0, "lawyer_profile": {"rating": 0.0}}]}

    entry = (await chat_socket._fetch_matched_lawyers(SESSION, n=3))["matched_lawyers"][0]

    assert entry["match_score"] == 0.0
    assert entry["rating"] == 0.0


@pytest.mark.parametrize("score", NON_FINITE, ids=NON_FINITE_IDS)
@pytest.mark.parametrize("rating", NON_FINITE, ids=NON_FINITE_IDS)
async def test_the_payload_is_strict_json_serialisable(service, score, rating):
    """`allow_nan=False` is what a conforming JSON encoder does.

    Asserted on the WHOLE payload rather than a field, because the failure mode
    is the frame as a unit: one bad number and the client parses none of it.
    """
    import json

    service["result"] = {"result_kind": "matched", "notice": "", "matches": [
        {**_lawyer(), "match_score": score, "lawyer_profile": {"rating": rating}}]}

    out = await chat_socket._fetch_matched_lawyers(SESSION, n=3)
    encoded = json.dumps(out, allow_nan=False)      # must not raise

    assert "NaN" not in encoded
    assert "Infinity" not in encoded


async def test_a_healthy_payload_is_also_strict_json_serialisable(service):
    import json

    service["result"] = {"result_kind": "general_listing", "notice": "browse",
                         "matches": [_lawyer("L1"), _lawyer("L2", score=None)]}

    encoded = json.dumps(
        await chat_socket._fetch_matched_lawyers(SESSION, n=3), allow_nan=False)

    assert '"match_score": null' in encoded, (
        "an unranked candidate must serialise as null, not as a number")
