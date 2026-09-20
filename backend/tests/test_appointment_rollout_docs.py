"""Documentation that would be dangerous if it were wrong.

Most prose does not need a test. These do, because each one is a statement an
operator ACTS on, and each was false until this change:

  * the checklist listed four index commands while the registry declared
    eight. A subset that looks complete is worse than no list, because it gets
    run and then ticked off.

  * the sweep's own module said nothing scheduled it and it was not registered
    in `main.py`. A reader deciding whether expiry could fire would have
    believed it could not.

  * the checklist said deadline-guarded confirmation was unimplemented and E2
    unmet, which would have blocked an activation that is in fact only waiting
    on operational evidence.

Nothing here tests wording for its own sake. Each assertion is about a claim
that changes what somebody does.
"""
import pathlib

import pytest

pytestmark = pytest.mark.integration


def _checklist() -> str:
    root = pathlib.Path(__file__).resolve().parents[2]
    return (root / "APPOINTMENT_ROLLOUT_CHECKLIST.md").read_text(
        encoding="utf-8")


# ── The index list must be the whole registry, or not a list at all ────────

def test_every_declared_index_command_appears_in_the_checklist():
    """Generated from `ALL_INDEX_REQUIREMENTS`, so it cannot become a subset.

    The previous version hardcoded four commands while the registry declared
    eight - the outcome-queue, reminder and dispute indexes were simply
    missing, and step 8 would then have failed for a reason step 7 caused.
    """
    from app.db.appointment_index_spec import ALL_INDEX_REQUIREMENTS
    from app.db.appointment_slot_preflight import _create_command

    text = _checklist()
    missing = [spec.name for spec in ALL_INDEX_REQUIREMENTS
               if _create_command(spec) not in text]

    assert missing == [], missing


def test_the_checklist_contains_no_index_command_the_registry_does_not_declare():
    """The other direction: a command for an index nobody declares would be an
    operator building something the validator then reports as unexpected."""
    import re

    from app.db.appointment_index_spec import ALL_INDEX_REQUIREMENTS
    from app.db.appointment_slot_preflight import _create_command

    declared = {_create_command(spec) for spec in ALL_INDEX_REQUIREMENTS}
    in_doc = set(re.findall(r"^db\.\w+\.createIndex\(.+\)$", _checklist(),
                            flags=re.MULTILINE))

    # `uniq_pending_slot` is the OBSOLETE index, present in the rollback
    # section on purpose: rolling back past step 9 must rebuild it.
    in_doc = {c for c in in_doc if "uniq_pending_slot" not in c}

    assert in_doc - declared == set(), in_doc - declared


def test_the_checklist_points_at_the_preflight_rather_than_itself():
    text = _checklist()

    assert "recommended_create" in text
    assert "python -m app.db.appointment_slot_preflight" in text


def test_the_checklist_separates_correctness_from_query_indexes():
    """An operator who cannot tell which indexes block startup from which
    block one feature cannot sequence the rollout."""
    text = _checklist()

    assert "CORRECTNESS" in text
    assert "QUERY" in text
    assert "capacity" in text.lower()


def _registry():
    from app.db.appointment_index_spec import ALL_INDEX_REQUIREMENTS
    from app.db.v2_index_spec import CORRECTNESS

    return ALL_INDEX_REQUIREMENTS, CORRECTNESS


def test_the_checklist_names_every_index_and_its_collection():
    """Derived from `ALL_INDEX_REQUIREMENTS`, so adding a ninth index makes
    this fail until the checklist mentions it."""
    specs, _ = _registry()
    text = _checklist()

    missing = [f"{s.collection}.{s.name}" for s in specs
               if s.name not in text or s.collection not in text]

    assert missing == [], missing


def test_the_checklist_states_the_correct_index_totals():
    """The previous text said "three unique plus five non-unique". The
    registry declares four unique and four query, and an operator sizing a
    maintenance window from a wrong count plans the wrong window.

    Counted from the registry rather than hardcoded here, so this test cannot
    become the second stale copy of the same numbers.
    """
    specs, CORRECTNESS = _registry()
    text = _checklist()

    unique = [s for s in specs if s.unique]
    query = [s for s in specs if s.kind != CORRECTNESS]
    correctness = [s for s in specs if s.kind == CORRECTNESS]

    # Every correctness index here is enforced by uniqueness; if that ever
    # stops being true the wording below needs rethinking, not patching.
    assert len(unique) == len(correctness)

    assert f"{len(unique)} UNIQUE builds" in text, text[:0] or len(unique)
    assert f"{len(query)} non-unique" in text
    assert "three unique index builds" not in text
    assert "five non-unique" not in text


def test_the_checklist_counts_correctness_indexes_per_collection():
    """Three on `appointments` and one on `appointment_disputes` - the second
    is the one an operator does not expect to block startup."""
    specs, CORRECTNESS = _registry()
    text = _checklist()

    correctness = [s for s in specs if s.kind == CORRECTNESS]
    on_appointments = [s for s in correctness
                       if s.collection == "appointments"]
    elsewhere = [s for s in correctness if s.collection != "appointments"]

    assert f"{len(on_appointments)} on" in text
    assert f"{len(elsewhere)} on" in text
    for spec in elsewhere:
        assert spec.name in text


def test_e1_does_not_name_a_fixed_number_of_indexes():
    """"The four indexes above" was already wrong once. E1 must point at the
    registry and the readiness gate, not at a count."""
    text = _checklist()

    assert "The four indexes above" not in text
    assert "validate_appointment_indexes()" in text
    assert "canonical registry" in text


def test_the_checklist_does_not_claim_all_four_prerequisites_are_unmet():
    """E2 is met in code. Saying otherwise sends somebody to re-implement a
    deadline guard that already exists."""
    text = _checklist()

    assert "All are unmet" not in text
    assert "all currently unmet" not in text
    assert "E1, E3 and E4" in text


def test_the_checklist_still_refuses_production():
    """Correcting E2 must not read as permission."""
    text = _checklist()

    assert "NO-GO" in text
    assert "unmet" in text


# ── Claims about whether expiry can fire ───────────────────────────────────

def test_the_sweep_no_longer_claims_nothing_schedules_it():
    """It is wired now. A reader deciding whether expiry could fire would
    otherwise conclude, from the module itself, that it could not."""
    from app.services import appointment_expiry_sweep

    doc = appointment_expiry_sweep.__doc__ or ""

    for stale in ("Nothing calls it", "not registered in `main.py`",
                  "DORMANT ON PURPOSE", "NOT SCHEDULED"):
        assert stale not in doc, stale


def test_the_sweep_documents_that_it_is_wired_and_off():
    from app.services import appointment_expiry_sweep

    doc = appointment_expiry_sweep.__doc__ or ""

    assert "appointment_expiry_enabled" in doc
    assert "appointment_scheduler" in doc


def test_the_sweep_no_longer_claims_confirm_ignores_the_deadline():
    """`confirm` rejects a lapsed request now. The old text said the opposite
    and called it correct - which would send a reader to re-implement it."""
    from app.services import appointment_expiry_sweep

    doc = appointment_expiry_sweep.__doc__ or ""

    # The dangerous claim is the negative one; asserting the absence of a
    # phrase that the CORRECTED text also contains ("NO LONGER THE ONLY
    # ENFORCEMENT POINT") tests punctuation, not meaning.
    assert "`confirm` deliberately does NOT reject" not in doc
    assert "confirm` now refuses a lapsed" in doc
    assert "expiry_enabled" in doc


def test_the_scheduler_documents_three_jobs():
    from app.services import appointment_scheduler

    doc = appointment_scheduler.__doc__ or ""

    assert "both flags off" not in doc
    assert "The two jobs hold" not in doc
    assert "THREE" in doc or "three" in doc


def test_the_scheduler_documents_the_two_kinds_of_index_dependency():
    """Ordinary QUERY indexes skip one job; the expiry index is additionally a
    startup prerequisite while expiry is enabled. Treating them as the same
    thing is how a performance index becomes a boot failure, or how an
    activation prerequisite becomes a silent skip."""
    from app.services import appointment_scheduler

    doc = appointment_scheduler.__doc__ or ""

    assert "appointment_pending_expiry" in doc
    assert "ACTIVATION PREREQUISITE" in doc
    assert "flag off" in doc


# ── The checklist's own status claims ──────────────────────────────────────

def test_the_checklist_no_longer_says_expiry_is_unregistered():
    text = _checklist()

    assert "it is not registered in" not in text
    assert "Nothing\ncalls `services/appointment_expiry_sweep.py`" not in text


def test_the_checklist_records_e2_as_met_in_code_but_not_activated():
    text = _checklist()

    assert "unmet — not implemented" not in text
    assert "MET IN CODE" in text


def test_the_checklist_still_records_the_unmet_operational_gates():
    """The point of correcting E2 is NOT to imply the rollout is ready."""
    text = _checklist()

    assert "unmet" in text                      # E1, E3, E4 remain
    assert "NO-GO" in text
    assert "UNVERIFIED" in text


def test_the_checklist_describes_both_activation_guards():
    text = _checklist()

    assert "assert_appointment_expiry_activation_ready" in text
    assert "every cycle" in text
