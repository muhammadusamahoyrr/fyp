"""The suite must never write into the directory the application serves.

The same failure as `test_mongo_test_isolation`, one layer down. Tests call the
real `generate_pdf`, which writes to `{upload_root}/docs` — in a developer
checkout, the live upload directory. One run of the V2 suites left 320 files
there: 302 `legacy-<hex>.pdf` fixtures plus wakalatnama and guardianship
samples, indistinguishable by name from real client documents.

It was found from the other end. A post-migration census of the DOCUMENTS_V2
estate showed the legacy artifact directory had gained 305 PDFs since the
backup — a directory that should have been static. Nothing was corrupted; every
write was a new filename. But a census of that directory cannot be trusted
while a test run can add to it, and the next person to check would have had to
re-derive the same explanation.

These tests cover the guard rather than trusting it, because a safety check
nobody exercises is a safety check that quietly stops working.
"""
from __future__ import annotations

from pathlib import Path

import pytest

REPO_UPLOADS = Path(__file__).resolve().parents[1] / "uploads"


def _under(path, root) -> bool:
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
        return True
    except ValueError:
        return False


def _configured_upload_root() -> Path:
    """The setting, as a bare Path.

    Returned unwrapped ON PURPOSE. Asserting on `settings.upload_root` directly
    makes pytest render the whole `Settings` object in the failure message, and
    that object carries `mongodb_url` — password included. A failing test would
    then print the production credential into the terminal and into CI logs.
    Reading the one field out first keeps the assertion message to a path.
    """
    from app.core.config import settings

    return Path(settings.upload_root)


def test_the_redirect_applies_without_being_asked_for():
    """DELIBERATELY TAKES NO FIXTURE.

    Every other test here names `_isolate_upload_root`, which activates it
    whether or not it is autouse — so none of them would notice `autouse=True`
    being dropped, and the leak would come back silently. This one fails the
    moment the guard stops being automatic, which is the property that actually
    matters: an opt-in guard protects only the tests that remember to opt in.
    """
    root = _configured_upload_root()
    assert not _under(root, REPO_UPLOADS)


def test_the_upload_root_is_not_the_repositorys_own(_isolate_upload_root):
    root = _configured_upload_root()
    assert not _under(root, REPO_UPLOADS)
    assert _under(root, _isolate_upload_root)


@pytest.mark.parametrize("module_path,attribute", [
    # Each of these evaluates `settings.upload_root` ONCE, at import. Repointing
    # the setting alone leaves them aimed at the real directory, which is what
    # made the leak survive the database isolation already in place.
    ("app.services.pdf_generator", "UPLOADS_DIR"),
    ("app.services.intake_service", "_EVIDENCE_DIR"),
    ("app.utils.file_handler", "UPLOADS_ROOT"),
])
def test_constants_that_snapshot_the_setting_are_repointed(
        module_path, attribute, _isolate_upload_root):
    module = pytest.importorskip(module_path)
    value = getattr(module, attribute)
    assert not _under(value, REPO_UPLOADS), (
        f"{module_path}.{attribute} still points into the real upload directory"
    )
    assert _under(value, _isolate_upload_root)


def test_the_v2_artifact_store_resolves_under_the_temporary_root(
        _isolate_upload_root):
    """`artifact_store` resolves the setting per call rather than at import, so
    it needs no patch — but that is a property worth pinning, not assuming."""
    from app.services.artifact_store import _root

    assert _under(_root(), _isolate_upload_root)


def test_generating_a_pdf_does_not_touch_the_real_upload_directory(
        _isolate_upload_root):
    """The behavioural proof. Everything above checks configuration; this calls
    the generator the leaking suites call and follows the bytes."""
    from app.services.pdf_generator import generate_pdf

    before = set(REPO_UPLOADS.glob("docs/*.pdf")) if REPO_UPLOADS.exists() else set()
    out = Path(generate_pdf("upload-isolation-probe", "legal_notice",
                            {"recipient_name": "Test Recipient"}))
    after = set(REPO_UPLOADS.glob("docs/*.pdf")) if REPO_UPLOADS.exists() else set()

    assert out.is_file()
    assert _under(out, _isolate_upload_root)
    assert not _under(out, REPO_UPLOADS)
    assert after == before, "the generator added a file to the real directory"
