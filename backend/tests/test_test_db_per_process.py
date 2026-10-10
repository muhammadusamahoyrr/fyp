"""Every pytest process gets its own throwaway database, and drops only that.

A fixed `<name>_test` was shared by every pytest process on the machine, so a
full run and a targeted run made at the same time deleted each other's
documents and reported failures that passed alone.
"""
from __future__ import annotations

import pytest

from tests.conftest import (
    MONGO_DB_NAME_MAX,
    TEST_DB_MARKER,
    TEST_DB_SUFFIX,
    assert_droppable_test_db,
    make_test_db_name,
)


def _name(original="attorney_ai", **kw):
    return make_test_db_name(original, **({"pid": 4242, "worker": "main", "token": "a1b2c3"} | kw))


# ── the name ────────────────────────────────────────────────────────────────

def test_the_name_ends_test_carries_the_marker_and_is_not_the_app_db():
    name = _name()
    assert name.endswith(TEST_DB_SUFFIX)
    assert TEST_DB_MARKER in name
    assert name != "attorney_ai"
    assert name.startswith("attorney_ai")


def test_pid_worker_and_token_all_make_the_name_different():
    base = _name()
    assert _name(pid=4243) != base
    assert _name(worker="gw1") != base
    assert _name(token="ffffff") != base


def test_the_app_name_already_ending_test_still_gets_a_new_name():
    name = make_test_db_name("attorney_ai_test", pid=1, worker="main", token="abc")
    assert name != "attorney_ai_test"
    assert name.endswith(TEST_DB_SUFFIX) and TEST_DB_MARKER in name
    assert "_test_pt" not in name, "the suffix was doubled"


def test_the_run_id_is_sanitised_and_bounded():
    name = _name(run_id="Ab/c.d$e f*" + "x" * 200)
    assert name.endswith(TEST_DB_SUFFIX)
    for bad in '/\\. "$*<>:|?':
        assert bad not in name, f"{bad!r} reached the database name"
    assert "abcdef" in name
    assert len(name) <= MONGO_DB_NAME_MAX


def test_an_empty_run_id_adds_nothing():
    assert _name(run_id="") == _name(run_id=None) == _name(run_id="$$$")


def test_a_long_app_name_is_cut_to_mongos_limit_keeping_the_tail():
    name = make_test_db_name("a" * 200, pid=99999999, worker="gw123", token="abcdef",
                             run_id="r" * 50)
    assert len(name) <= MONGO_DB_NAME_MAX
    assert name.endswith(TEST_DB_SUFFIX) and TEST_DB_MARKER in name


def test_this_session_is_on_its_own_database():
    from app.core.config import settings

    assert settings.db_name.endswith(TEST_DB_SUFFIX)
    assert TEST_DB_MARKER in settings.db_name
    assert settings.db_name != "attorney_ai_test", "back on the shared database"


# ── the drop guard ──────────────────────────────────────────────────────────

def test_the_guard_allows_this_runs_own_database():
    own = _name()
    assert_droppable_test_db(own, original="attorney_ai", own=own)


@pytest.mark.parametrize("target", [
    "attorney_ai",                      # the application database
    "attorney_ai_test",                 # the old shared name: no marker
    "attorney_ai_pt1_main_zzz_test",    # another process's database
    "attorney_ai_local",
])
def test_the_guard_refuses_anything_else(target):
    own = _name()
    with pytest.raises(AssertionError):
        assert_droppable_test_db(target, original="attorney_ai", own=own)


def test_the_guard_refuses_a_name_without_suffix_or_marker_even_if_own():
    for bad in ("attorney_ai_pt1", "attorney_ai_1_test"):
        with pytest.raises(AssertionError):
            assert_droppable_test_db(bad, original="attorney_ai", own=bad)


def test_the_guard_refuses_the_app_database_even_if_misconfigured_as_own():
    name = "x_pt1_test"
    with pytest.raises(AssertionError):
        assert_droppable_test_db(name, original=name, own=name)


@pytest.mark.integration
async def test_an_integration_test_writes_to_this_runs_database(mongo):
    from app.core.config import settings

    assert mongo.name == settings.db_name
    assert TEST_DB_MARKER in mongo.name
