"""The lawyer directory: paging, search, filtering and sorting server-side.

All of it used to happen in the browser, over whichever 20 lawyers the first
page contained. `find_lawyers` took `page`/`page_size` but no search and a sort
hardcoded to rating DESC — so the client fetched page 1 and did the rest
itself. Every narrowing was therefore a
statement about 20 lawyers presented as a statement about the directory, and the
21st lawyer could not be reached by any combination of controls.

Sorting is the clearest case: sorting one page is not sorting a list. The
cheapest lawyer on the platform is very unlikely to be among the 20 you happen
to be holding.

25 lawyers here, deliberately more than one page, because every one of these
defects is invisible at 20.
"""
import pytest

pytestmark = pytest.mark.integration

PAGE = 10
TOTAL = 25


@pytest.fixture
async def directory(mongo):
    """25 verified lawyers with spread-out names, fees, experience and ratings."""
    from app.core.security import hash_password
    from app.db.collections import get_users_col

    await get_users_col().delete_many({"_id": {"$regex": "^DIR-"}})

    docs = []
    for i in range(TOTAL):
        # Names run Z..A as the index rises, so a name sort cannot agree with
        # insertion order by accident.
        letter = chr(ord("Z") - i)
        docs.append({
            "_id": f"DIR-{i:02d}",
            "role": "lawyer",
            "email": f"dir-{i:02d}@x.test",
            "password_hash": hash_password("Str0ngPass1"),
            "full_name": f"{letter} Advocate {i:02d}",
            "is_active": True,
            "province": "punjab" if i % 2 == 0 else "sindh",
            "lawyer_profile": {
                "bar_number": f"PBC/{1000 + i}/2019",
                "specializations": ["criminal"] if i % 2 == 0 else ["family"],
                "kyc_verified": True,
                "rating": round(1.0 + (i % 5), 1),
                "total_reviews": 3,
                "availability": i % 3 != 0,
                "experience_years": i,
                "hourly_rate": 1000 * (i + 1),
                "bio": "Practising advocate.",
            },
        })
    # A lawyer who never filled in the optional fee and experience fields. Both
    # are sortable, so this row proves the sorts place a blank sensibly rather
    # than dropping the lawyer out of the directory.
    docs.append({
        "_id": "DIR-NOFEE", "role": "lawyer", "email": "dir-nofee@x.test",
        "password_hash": hash_password("Str0ngPass1"),
        "full_name": "Unpriced Advocate", "is_active": True, "province": "punjab",
        "lawyer_profile": {"specializations": ["criminal"], "kyc_verified": True,
                           "rating": 4.0, "availability": True},
    })
    await get_users_col().insert_many(docs)
    yield
    await get_users_col().delete_many({"_id": {"$regex": "^DIR-"}})


async def _search(**kw):
    from app.services.lawyer_service import search_lawyers
    params = {"province": None, "case_type": None, "min_rating": 0.0,
              "availability": None, "page": 1, "page_size": PAGE}
    params.update(kw)
    return await search_lawyers(**params)


def _ids(result):
    return [u["_id"] for u in result.items]


# ── paging ───────────────────────────────────────────────────────────────────

async def test_a_lawyer_beyond_the_first_page_is_reachable(directory):
    """THE defect. With one page of 20 and no paging, lawyer 21 did not exist
    as far as any client was concerned."""
    first = await _search(page=1, page_size=20)
    later = await _search(page=2, page_size=20)

    assert len(first.items) == 20
    assert later.items, "there is no second page — the rest are unreachable"
    assert not set(_ids(first)) & set(_ids(later)), "pages overlap"


async def test_the_page_count_covers_everyone(directory):
    result = await _search(page=1, page_size=PAGE)
    assert result.total >= TOTAL
    assert result.pages == (result.total + PAGE - 1) // PAGE


async def test_paging_visits_every_lawyer_exactly_once(directory):
    """The property that makes paging trustworthy, and the one an unstable sort
    silently breaks: many of these lawyers share a rating, so without the `_id`
    tiebreaker MongoDB is free to order the ties differently on each query —
    re-showing one lawyer on page 2 and skipping another entirely."""
    first = await _search(page=1, page_size=PAGE)
    seen: list[str] = []
    for page in range(1, first.pages + 1):
        seen += _ids(await _search(page=page, page_size=PAGE))

    assert len(seen) == len(set(seen)), "a lawyer appeared on two pages"
    assert len(seen) == first.total, "paging did not reach every lawyer"


async def test_an_out_of_range_page_is_empty_not_an_error(directory):
    result = await _search(page=99, page_size=PAGE)
    assert result.items == []
    assert result.total >= TOTAL


# ── search across the whole directory ────────────────────────────────────────

async def test_search_finds_a_lawyer_who_is_not_on_the_first_page(directory):
    """Client-side search could only ever match the page already loaded.

    The target is taken from the LAST page of the default ordering and then
    searched for, so the test proves reach rather than assuming which lawyer
    happens to fall where.
    """
    first = await _search(page=1, page_size=PAGE)
    last = await _search(page=first.pages, page_size=PAGE)
    target = last.items[-1]
    assert target["_id"] not in set(_ids(first)), "the fixture fits on one page"

    found = await _search(q=target["full_name"])

    assert found.total == 1, f"search did not reach {target['full_name']!r}"
    assert found.items[0]["_id"] == target["_id"]


async def test_search_matches_a_specialization(directory):
    found = await _search(q="family")
    assert found.total > 0
    for u in found.items:
        assert "family" in u["lawyer_profile"]["specializations"]


async def test_search_matches_a_province(directory):
    found = await _search(q="sindh")
    assert found.total > 0
    assert all(u["province"] == "sindh" for u in found.items)


async def test_search_by_bar_number(directory):
    found = await _search(bar_number="PBC/1024/2019")
    assert found.total == 1
    assert found.items[0]["lawyer_profile"]["bar_number"] == "PBC/1024/2019"


async def test_a_search_needle_is_escaped_not_executed(directory):
    """The needle is a user's keystrokes, not a pattern. Unescaped, `.*` would
    match everyone and `a|b` would silently widen the search."""
    assert (await _search(q=".*")).total == 0
    assert (await _search(q="Advocate|Unpriced")).total == 0


async def test_search_results_are_themselves_paged(directory):
    """A search that matches more than one page must page, not truncate."""
    wide = await _search(q="Advocate", page_size=PAGE)
    assert wide.total >= TOTAL
    assert wide.pages > 1
    assert len(wide.items) == PAGE


# ── filters across the whole directory ───────────────────────────────────────
#
# Fee and experience are NOT filters. They are shown on every lawyer and they
# order the directory through `sort`, but narrowing by them was dropped as a
# directory control — so the filter set is province, case_type, min_rating,
# availability, page and page_size, plus free-text search.


async def test_filters_combine(directory):
    found = await _search(province="punjab", case_type="criminal", page_size=50)
    for u in found.items:
        assert u["province"] == "punjab"
        assert "criminal" in u["lawyer_profile"]["specializations"]


async def test_fee_and_experience_are_not_accepted_as_filters(directory):
    """Removed deliberately, so their absence is pinned. Both fields are
    OPTIONAL on a lawyer, and any range over them has to decide what to do with
    a lawyer who left them blank; the honest answer — keep them — makes the
    filter weak enough not to be worth its complexity."""
    import inspect
    from app.services.lawyer_service import search_lawyers

    params = set(inspect.signature(search_lawyers).parameters)
    assert not params & {"min_fee", "max_fee", "min_experience", "max_experience"}


async def test_fee_and_experience_still_order_the_directory(directory):
    """Dropping the filters must not drop the sorts, which are how a client
    still reaches the cheapest or the most experienced lawyer."""
    fees = [u["lawyer_profile"].get("hourly_rate")
            for u in await _all_sorted("fee_asc")
            if u["lawyer_profile"].get("hourly_rate") is not None]
    assert fees == sorted(fees)

    years = [u["lawyer_profile"].get("experience_years", 0)
             for u in await _all_sorted("experience_desc")]
    assert years == sorted(years, reverse=True)


# ── sorting across the whole directory ───────────────────────────────────────

async def _all_sorted(sort):
    first = await _search(sort=sort, page_size=PAGE)
    out = list(first.items)
    for page in range(2, first.pages + 1):
        out += (await _search(sort=sort, page=page, page_size=PAGE)).items
    return out


async def test_sorting_orders_the_whole_directory_not_one_page(directory):
    """The cheapest lawyer overall must lead, even though a client-side sort of
    page 1 could never have found them."""
    cheapest_first = await _search(sort="fee_asc", page_size=PAGE)
    fees = [u["lawyer_profile"].get("hourly_rate")
            for u in cheapest_first.items if u["lawyer_profile"].get("hourly_rate")]
    assert fees == sorted(fees)

    everyone = await _all_sorted("fee_asc")
    priced = [u["lawyer_profile"].get("hourly_rate") for u in everyone
              if u["lawyer_profile"].get("hourly_rate") is not None]
    assert priced == sorted(priced), "the sort did not hold across pages"


async def test_rating_sorts_both_ways(directory):
    desc = [u["lawyer_profile"]["rating"] for u in await _all_sorted("rating_desc")]
    asc = [u["lawyer_profile"]["rating"] for u in await _all_sorted("rating_asc")]
    assert desc == sorted(desc, reverse=True)
    assert asc == sorted(asc)


async def test_name_sorts_both_ways(directory):
    names = [u["full_name"] for u in await _all_sorted("name_asc")]
    assert names == sorted(names)
    assert [u["full_name"] for u in await _all_sorted("name_desc")] == \
        sorted(names, reverse=True)


async def test_experience_sorts_high_first(directory):
    years = [u["lawyer_profile"].get("experience_years", 0)
             for u in await _all_sorted("experience_desc")]
    assert years == sorted(years, reverse=True)


async def test_an_unknown_sort_key_falls_back_rather_than_failing(directory):
    """The key is validated at the route; the repository must still not explode
    or, worse, sort on an attacker-chosen field."""
    found = await _search(sort="whatever_i_like", page_size=PAGE)
    ratings = [u["lawyer_profile"]["rating"] for u in found.items]
    assert ratings == sorted(ratings, reverse=True)


# ── nothing that already worked was broken ───────────────────────────────────

async def test_existing_filters_still_work(directory):
    by_province = await _search(province="punjab", page_size=50)
    assert all(u["province"] == "punjab" for u in by_province.items)

    by_type = await _search(case_type="family", page_size=50)
    assert all("family" in u["lawyer_profile"]["specializations"]
               for u in by_type.items)

    available = await _search(availability=True, page_size=50)
    assert all(u["lawyer_profile"]["availability"] for u in available.items)

    rated = await _search(min_rating=4.0, page_size=50)
    assert all(u["lawyer_profile"]["rating"] >= 4.0 for u in rated.items)


async def test_the_default_order_is_still_rating_first(directory):
    """No `sort` given must behave exactly as the directory always did."""
    ratings = [u["lawyer_profile"]["rating"]
               for u in (await _search(page_size=PAGE)).items]
    assert ratings == sorted(ratings, reverse=True)


async def test_unverified_and_inactive_lawyers_are_still_excluded(directory):
    from app.db.collections import get_users_col

    await get_users_col().update_one(
        {"_id": "DIR-00"}, {"$set": {"lawyer_profile.kyc_verified": False}})
    await get_users_col().update_one(
        {"_id": "DIR-01"}, {"$set": {"is_active": False}})

    ids = _ids(await _search(page_size=50))
    assert "DIR-00" not in ids
    assert "DIR-01" not in ids


async def test_the_response_never_carries_internal_fields(directory):
    result = await _search(page_size=PAGE)
    for u in result.items:
        assert "password_hash" not in u
        assert "specialization_embedding" not in (u.get("lawyer_profile") or {})


# ── location precision ───────────────────────────────────────────────────────
#
# `_inject_coords` fills a missing pin with the province centre plus a
# deterministic offset of up to 0.4 degrees — roughly 44 km. It wrote that into
# the SAME `lat`/`lng` fields as a genuinely geocoded address, so no caller
# could tell an office from a number this function invented. The UI could not
# know, and offered "Get Directions" to both: a client following them would be
# routed to a fabricated destination with nothing on screen to doubt.


def _precision(user):
    return (user.get("lawyer_profile") or {}).get("location_precision")


async def test_a_geocoded_address_is_marked_exact(directory):
    from app.db.collections import get_users_col
    from app.services.lawyer_service import _inject_coords

    await get_users_col().update_one(
        {"_id": "DIR-00"},
        {"$set": {"lawyer_profile.address": "12 Mall Road, Lahore",
                  "lawyer_profile.lat": 31.5497,
                  "lawyer_profile.lng": 74.3436}},
    )
    doc = await get_users_col().find_one({"_id": "DIR-00"})
    out = _inject_coords(doc)

    assert _precision(out) == "exact"
    assert out["lawyer_profile"]["lat"] == 31.5497


async def test_an_invented_pin_is_marked_approximate(directory):
    """The one that matters. These coordinates are not the lawyer's office and
    must never be presented, or navigated to, as though they were."""
    from app.db.collections import get_users_col
    from app.services.lawyer_service import _inject_coords

    doc = await get_users_col().find_one({"_id": "DIR-02"})
    assert (doc["lawyer_profile"].get("lat")) is None, "fixture already has a pin"

    out = _inject_coords(doc)

    assert _precision(out) == "approximate"
    assert out["lawyer_profile"]["lat"] is not None, "the map still gets a pin"


async def test_a_lawyer_with_no_province_gets_no_pin_and_says_so(directory):
    from app.db.collections import get_users_col
    from app.services.lawyer_service import _inject_coords

    await get_users_col().update_one({"_id": "DIR-04"}, {"$unset": {"province": ""}})
    doc = await get_users_col().find_one({"_id": "DIR-04"})
    out = _inject_coords(doc)

    assert _precision(out) == "none"
    assert (out.get("lawyer_profile") or {}).get("lat") is None


async def test_every_directory_result_declares_its_precision(directory):
    """A caller must never have to guess, so the field is always present."""
    result = await _search(page_size=50)
    assert result.items
    for user in result.items:
        assert _precision(user) in {"exact", "approximate", "none"}, \
            f"{user['_id']} has no location_precision"


async def test_an_approximate_pin_stays_within_its_province(directory):
    """The offset exists to stop province-mates stacking on one pixel; it must
    not wander into a different province."""
    from app.db.collections import get_users_col
    from app.services.lawyer_service import _inject_coords
    from app.utils.geocoding import province_coords

    doc = await get_users_col().find_one({"_id": "DIR-06"})
    out = _inject_coords(doc)
    centre = province_coords(doc["province"])

    assert abs(out["lawyer_profile"]["lat"] - centre[0]) <= 0.4
    assert abs(out["lawyer_profile"]["lng"] - centre[1]) <= 0.4


# ── demo office locations ────────────────────────────────────────────────────
#
# Six roster entries in `scripts/seed_demo_lawyers.py` carry a real office
# address with coordinates PINNED from a one-off geocode, so the profile can
# offer "Get Directions". The other six deliberately carry none, so the same
# dataset also exercises the branch where directions must be withheld.
#
# These tests guard the property that makes the first group safe: `exact` must
# mean the coordinates really are where the address is. A hand-typed
# plausible-looking number would be the exact defect `location_precision`
# exists to prevent, reintroduced as seed data — and no runtime check could
# catch it, because a fabricated coordinate is indistinguishable from a real
# one once written.


def _demo_module():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "seed_demo_lawyers", "scripts/seed_demo_lawyers.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# Rough city centres. Only used to assert a pinned coordinate lands in the city
# its address names — the cheap check that catches a transposed or invented pair.
_CITY_CENTRES = {
    "Islamabad":  (33.6844, 73.0479),
    "Rawalpindi": (33.5651, 73.0169),
    "Lahore":     (31.5204, 74.3587),
}


def test_every_demo_office_names_a_lawyer_on_the_roster():
    mod = _demo_module()
    names = {e["full_name"] for e in mod.ROSTER}
    assert set(mod.OFFICES) <= names, (
        f"OFFICES names lawyers not in the roster: {set(mod.OFFICES) - names}")


def test_every_demo_office_has_an_address_and_coordinates():
    mod = _demo_module()
    assert mod.OFFICES, "no demo offices are defined"
    for name, office in mod.OFFICES.items():
        assert office.get("address"), f"{name} has no address"
        assert isinstance(office.get("lat"), float), f"{name} has no latitude"
        assert isinstance(office.get("lng"), float), f"{name} has no longitude"


def test_each_pinned_coordinate_lands_in_the_city_its_address_names():
    """The check that a coordinate was resolved rather than typed.

    A fabricated pair would have to land within ~0.15 degrees of the right city
    by luck; a transposed lat/lng, a copied-and-not-edited duplicate, or a
    number invented to look plausible all fail here.
    """
    mod = _demo_module()
    for name, office in mod.OFFICES.items():
        city = next((c for c in _CITY_CENTRES if c.lower() in office["address"].lower()), None)
        assert city, f"{name}: address names no known city — {office['address']}"
        clat, clng = _CITY_CENTRES[city]
        assert abs(office["lat"] - clat) <= 0.15 and abs(office["lng"] - clng) <= 0.15, (
            f"{name}: {office['lat']},{office['lng']} is not in {city}")


def test_no_two_demo_offices_share_a_coordinate():
    """Copy-paste is how a plausible-looking wrong coordinate gets in."""
    mod = _demo_module()
    pairs = [(o["lat"], o["lng"]) for o in mod.OFFICES.values()]
    assert len(set(pairs)) == len(pairs), "two demo offices share a coordinate"


def test_a_demo_lawyer_with_an_office_is_exact():
    from app.services.lawyer_service import _inject_coords

    mod = _demo_module()
    for name, office in mod.OFFICES.items():
        entry = next(e for e in mod.ROSTER if e["full_name"] == name)
        out = _inject_coords({
            "_id": name, "province": entry["province"],
            "lawyer_profile": {"specializations": entry["specs"], **office},
        })
        lp = out["lawyer_profile"]
        assert lp["location_precision"] == "exact", f"{name} is not exact"
        # And the pin is the resolved address, not a province centre.
        assert lp["lat"] == office["lat"]
        assert lp["lng"] == office["lng"]


def test_a_demo_lawyer_without_an_office_is_still_approximate():
    """The safety rule is NOT relaxed for the demo. A lawyer with no address
    keeps an invented province-centre pin and must never be offered as a
    navigable destination."""
    from app.services.lawyer_service import _inject_coords

    mod = _demo_module()
    without = [e for e in mod.ROSTER if e["full_name"] not in mod.OFFICES]
    assert without, "every demo lawyer has an office — the approximate branch is untestable"

    for entry in without:
        out = _inject_coords({
            "_id": entry["full_name"], "province": entry["province"],
            "lawyer_profile": {"specializations": entry["specs"]},
        })
        assert out["lawyer_profile"]["location_precision"] == "approximate", \
            f"{entry['full_name']} claims a precision it has not earned"


def test_the_demo_roster_exercises_both_branches():
    """Both halves must be demonstrable from one seeded database, or the safety
    behaviour cannot be shown at all."""
    mod = _demo_module()
    with_office = set(mod.OFFICES)
    without = {e["full_name"] for e in mod.ROSTER} - with_office
    assert with_office and without


def test_seeding_needs_no_geocoder():
    """Coordinates are pinned constants. A seed run that called a third-party
    service would fail whenever that service was unreachable — including in the
    room during a demo."""
    import inspect
    mod = _demo_module()

    # Comments are stripped first. The provenance note above OFFICES names
    # `geocode_address` deliberately — it records where the pinned numbers came
    # from, which is the opposite of a runtime dependency. A grep over raw
    # source would flag that note and force the file to stop explaining itself.
    code = "\n".join(
        line for line in inspect.getsource(mod).splitlines()
        if not line.lstrip().startswith("#")
    )

    assert "geocode_address(" not in code, "the seed calls a geocoder"
    assert "geocoding" not in code, "the seed imports the geocoding module"
    assert "httpx" not in code, "the seed makes HTTP requests"

    # And the coordinates really are literals in the file.
    for office in mod.OFFICES.values():
        assert repr(office["lat"]) in code, "a coordinate is computed, not pinned"
