"""Dead code that was removed, and a public contract that was not.

Three small changes with one thing in common: each is easy to undo by accident
later, and none of them is covered by a behavioural test anywhere else,
because the whole point of each is that NOTHING behaves differently.

  * `exclude_id` was a parameter of `has_conflict` that no caller ever
    supplied, guarding a branch that could not be reached. Removed.

  * `GET /appointments/availability/{lawyer_id}` is superseded by
    `GET /lawyers/{id}/bookable-slots` and is DEPRECATED, not deleted - it is
    a public contract and this module already ships one breaking change.

  * `getLawyerAvailability` was the only caller of that endpoint in this
    application, and it was itself called by nothing. Removed.
"""
import pathlib

import pytest

pytestmark = pytest.mark.integration


def _frontend_root() -> pathlib.Path:
    return (pathlib.Path(__file__).resolve().parents[2] / "frontend" / "src")


# ── 1. The parameter that could only be supplied by mistake ─────────────────

def test_has_conflict_no_longer_takes_an_exclude_id():
    """It was added for a reschedule path that was never built this way.

    Rescheduling does not call `has_conflict` at all; it relies on the unique
    slot indexes directly. So the branch was unreachable and the argument
    could only ever be passed by mistake - and a mistaken `exclude_id` would
    silently EXCLUDE a real conflict from a pre-check, which is the one thing
    it must not do.
    """
    import inspect

    from app.repositories.appointment_repo import AppointmentRepository

    params = inspect.signature(AppointmentRepository.has_conflict).parameters

    assert "exclude_id" not in params
    assert list(params) == ["self", "lawyer_id", "scheduled_at",
                            "duration_minutes"]


def test_no_code_in_the_application_references_an_exclude_id():
    """Parsed, not text-searched.

    A text scan also matches the docstring that RECORDS why the parameter was
    removed - and that docstring is the thing most likely to stop somebody
    adding it back. The property worth asserting is that no executable code
    names it: not as a parameter, not as a keyword argument, not as a
    variable. The AST answers exactly that and ignores prose.
    """
    import ast
    import pathlib

    import app

    root = pathlib.Path(app.__file__).parent
    offenders = []
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            named = (
                (isinstance(node, ast.arg) and node.arg == "exclude_id")
                or (isinstance(node, ast.keyword) and node.arg == "exclude_id")
                or (isinstance(node, ast.Name) and node.id == "exclude_id")
            )
            if named:
                offenders.append(f"{path.name}:{getattr(node, 'lineno', '?')}")

    assert offenders == [], offenders


async def test_has_conflict_still_detects_an_overlap(app_indexes):
    """The removal must not have taken the behaviour with it.

    This is the friendly early error, not the guarantee - the unique indexes
    are what actually prevent a double booking - but it is what turns the
    common case into a clear message instead of a duplicate-key error.
    """
    import secrets
    from datetime import datetime, timedelta, timezone

    from app.core.constants import AppointmentStatus
    from app.db.collections import get_appointments_col
    from app.repositories.appointment_repo import AppointmentRepository
    from app.services.appointment_slots import occupied_slots

    tag = secrets.token_hex(4)
    lawyer_id = f"DP-L-{tag}"
    start = (datetime.now(timezone.utc) + timedelta(days=3)).replace(
        minute=0, second=0, microsecond=0)

    await get_appointments_col().insert_one({
        "_id": f"DP-A-{tag}", "lawyer_id": lawyer_id,
        "client_id": f"DP-C-{tag}", "scheduled_at": start,
        "end_at": start + timedelta(minutes=60), "duration_minutes": 60,
        "status": AppointmentStatus.CONFIRMED.value,
        "occupied_slots": occupied_slots(start, 60),
        "created_at": datetime.now(timezone.utc), "schedule_version": 1,
    })
    try:
        repo = AppointmentRepository()

        # Straddles the second half of the existing hour.
        assert await repo.has_conflict(
            lawyer_id, start + timedelta(minutes=30), 60) is True
        # Starts exactly when the other ends: touching, not overlapping.
        assert await repo.has_conflict(
            lawyer_id, start + timedelta(minutes=60), 60) is False
        # A different lawyer is not a conflict.
        assert await repo.has_conflict(f"DP-OTHER-{tag}", start, 60) is False
    finally:
        await get_appointments_col().delete_one({"_id": f"DP-A-{tag}"})


# ── 2. Deprecated, and still served ─────────────────────────────────────────

def test_the_legacy_availability_endpoint_is_marked_deprecated():
    """`deprecated=True` is what puts it in the OpenAPI schema as such, which
    IS the notice to anybody integrating against it."""
    from app.main import app

    routes = [r for r in app.routes
              if getattr(r, "path", "") ==
              "/api/v1/appointments/availability/{lawyer_id}"]

    assert len(routes) == 1
    assert routes[0].deprecated is True


def test_the_legacy_availability_endpoint_is_still_served():
    """NOT DELETED. It is a public contract, this application is no longer
    necessarily its only caller, and the module already ships one breaking
    change this cycle (`confirm` now requires a versioned body). Two at once
    turns "one client needs updating" into "we broke integrations".
    """
    from app.main import app

    paths = {getattr(r, "path", "") for r in app.routes}

    assert "/api/v1/appointments/availability/{lawyer_id}" in paths


def test_the_replacement_endpoint_exists():
    """Deprecating something with no successor is just breaking it slowly."""
    from app.main import app

    paths = {getattr(r, "path", "") for r in app.routes}

    assert "/api/v1/lawyers/{lawyer_id}/bookable-slots" in paths


def test_the_deprecation_names_its_replacement():
    """A deprecation notice that does not say what to use instead leaves the
    reader exactly where they started."""
    from app.api.v1.routes import appointments

    doc = appointments.get_lawyer_availability.__doc__ or ""

    assert "DEPRECATED" in doc
    assert "bookable-slots" in doc


# ── 3. The wrapper nothing called ───────────────────────────────────────────

def test_the_dead_frontend_wrapper_is_gone():
    api = _frontend_root() / "lib" / "api.js"

    assert "getLawyerAvailability" not in api.read_text(encoding="utf-8")


def test_no_frontend_component_calls_the_legacy_availability_endpoint():
    """The UI reads bookable slots from the server now. A component reaching
    for booked-slots-only would be re-introducing the hardcoded candidate
    times that made Sunday 09:00 bookable."""
    offenders = []
    for path in _frontend_root().rglob("*.js*"):
        text = path.read_text(encoding="utf-8", errors="ignore")
        if "appointments/availability/" in text:
            offenders.append(path.name)

    assert offenders == [], offenders
