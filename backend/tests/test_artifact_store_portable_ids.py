"""The artifact store holds ONE id rule on every platform.

A revision id is a single path component: it may contain neither `/` nor `\\`.
`\\` is a separator on Windows and an ordinary filename character on POSIX, so
without this rule the same id was refused on Windows and stored on Linux as a
file literally named `..\\..\\escape.0.pdf` -- contained on one host, resolving
differently on another sharing the volume. Defensive hardening and portability,
not a fix for an exploitable Linux traversal (containment already held).

Runs identically on Windows and Linux: every case below is platform-independent.
"""
from __future__ import annotations

import secrets
import uuid
from pathlib import Path

import pytest

from app.core.config import settings
from app.services import artifact_store as store
from app.services.artifact_store import ArtifactStoreError

A = b"%PDF-1.4 portable id check"

BAD_IDS = [
    "a/b", "a\\b",                      # one separator of each kind
    "../../escape", "..\\..\\escape",   # traversal, both forms
    "/absolute", "\\absolute",          # leading separator, both forms
    "docs/..\\mixed",                   # both kinds together
]


@pytest.fixture(autouse=True)
def _store(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "upload_root", str(tmp_path))
    return tmp_path


def _store_root(tmp_path: Path) -> Path:
    return tmp_path.resolve() / "v2"


# ── every entry point refuses both separators ────────────────────────────────

@pytest.mark.parametrize("bad", BAD_IDS)
@pytest.mark.parametrize("call", [
    lambda rid: store.write_final(rid, 0, A),
    lambda rid: store.publish(rid, 0, "worker-1"),
    lambda rid: store.final_key(rid, 0),
    lambda rid: store.staging_path(rid, 0, "worker-1"),
    lambda rid: store.render_id(rid, 0, "worker-1"),
], ids=["write_final", "publish", "final_key", "staging_path", "render_id"])
def test_a_separator_in_a_revision_id_is_refused(call, bad):
    with pytest.raises(ArtifactStoreError, match="single path component"):
        call(bad)


# ── refused BEFORE any filesystem work ───────────────────────────────────────

@pytest.mark.parametrize("bad", ["../../escape", "..\\..\\escape"])
@pytest.mark.parametrize("call", [
    lambda rid: store.write_final(rid, 0, A),
    lambda rid: store.publish(rid, 0, "worker-1"),
], ids=["write_final", "publish"])
def test_the_refusal_happens_before_the_store_is_touched(tmp_path, call, bad):
    # Both entry points create the store directories as their first FS action;
    # a refused id must not get that far.
    assert not _store_root(tmp_path).exists()
    with pytest.raises(ArtifactStoreError):
        call(bad)
    assert not _store_root(tmp_path).exists(), "the store was touched before the refusal"
    assert list(tmp_path.rglob("*")) == [], "something was written for a refused id"


# ── server-minted ids are unaffected ─────────────────────────────────────────

@pytest.mark.parametrize("rid", [
    secrets.token_urlsafe(16),                          # document_v2_service
    str(uuid.uuid5(uuid.NAMESPACE_URL, "doc-1:1")),     # migration's planned ids
    "rev-1", "rev_2.with.dots",
], ids=["token_urlsafe", "uuid5", "simple", "dotted"])
def test_valid_ids_keep_their_existing_behaviour(tmp_path, rid):
    key = store.write_final(rid, 3, A)
    assert key == f"docs/{rid}.3.pdf"                   # key format unchanged
    path = store.local_path(key)
    assert _store_root(tmp_path) in path.parents
    assert path.read_bytes() == A
