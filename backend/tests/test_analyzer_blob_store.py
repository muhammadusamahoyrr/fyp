"""Document Analyzer, P1 slice 1 / commit 2: the encrypted blob store.

Pure envelope tests first (no I/O): round trip, fresh keys and nonces, the
appended tag, AAD binding of every header field, tamper detection, and strict
master-key parsing. Then storage against a real Mongo and a temporary
upload_root: write/read, source scoping, idempotent removal, atomic re-wrap,
and the orphan sweep.
"""
from __future__ import annotations

import base64
import os
import time
import uuid

import pytest

from app.core.config import settings
from app.services.analyzer import blob_store as bs

K1 = base64.b64encode(b"\x11" * 32).decode()
K2 = base64.b64encode(b"\x22" * 32).decode()


def ring(active="k1", **extra) -> bs.Keyring:
    raw = ",".join([f"k1:{K1}", f"k2:{K2}"] + [f"{k}:{v}" for k, v in extra.items()])
    return bs.parse_keyring(raw, active)


def blob(plaintext=b"TENANCY AGREEMENT\n1. The Landlord lets the shop...", **kw):
    args = dict(blob_id=uuid.uuid4().hex, source_id="src-1", purpose="original",
                mime="application/pdf", keyring=ring())
    args.update(kw)
    return bs.encrypt(plaintext, **args)


# ── the envelope ─────────────────────────────────────────────────────────────

def test_round_trip():
    plaintext = os.urandom(5000)
    header, ct = blob(plaintext)
    assert bs.decrypt(header, ct, keyring=ring()) == plaintext


def test_every_encryption_uses_fresh_keys_and_two_distinct_nonces():
    h1, c1 = blob(b"same")
    h2, c2 = blob(b"same")
    for h in (h1, h2):
        assert len(h["content_nonce"]) == bs.NONCE_BYTES == len(h["wrap_nonce"])
        assert h["content_nonce"] != h["wrap_nonce"]
    assert c1 != c2 and h1["wrapped_dek"] != h2["wrapped_dek"]
    assert h1["content_nonce"] != h2["content_nonce"]


def test_the_tag_is_appended_not_stored_separately():
    plaintext = b"x" * 100
    header, ct = blob(plaintext)
    assert len(ct) == len(plaintext) + bs.TAG_BYTES == header["ciphertext_size"]
    assert len(header["wrapped_dek"]) == bs.KEY_BYTES + bs.TAG_BYTES
    assert "tag" not in header


def test_header_records_what_is_needed_and_no_key_material():
    header, _ = blob()
    assert {"_id", "source_id", "purpose", "mime", "format", "alg", "kek_id", "size",
            "plaintext_sha256", "content_nonce", "wrap_nonce", "wrapped_dek",
            "ciphertext_size"} <= set(header)
    assert header["format"] == 1 and header["alg"] == "A256GCM" and header["kek_id"] == "k1"
    raw = repr(header).encode()
    assert b"\x11" * 8 not in raw     # the master key is nowhere in the record


@pytest.mark.parametrize("field,value", [
    ("source_id", "src-2"), ("purpose", "canonical_text"), ("mime", "text/plain"),
    ("_id", uuid.uuid4().hex), ("format", 2),
])
def test_every_bound_header_field_is_authenticated(field, value):
    header, ct = blob()
    header[field] = value
    with pytest.raises(bs.BlobIntegrityError):
        bs.decrypt(header, ct, keyring=ring())


def test_a_key_id_swapped_in_the_header_fails():
    header, ct = blob()
    header["kek_id"] = "k2"          # the wrap AAD names k1
    with pytest.raises(bs.BlobIntegrityError):
        bs.decrypt(header, ct, keyring=ring())


def test_a_flipped_ciphertext_byte_fails_with_no_partial_result():
    header, ct = blob(b"A" * 64)
    tampered = bytearray(ct)
    tampered[10] ^= 0x01
    with pytest.raises(bs.BlobIntegrityError):
        bs.decrypt(header, bytes(tampered), keyring=ring())


def test_a_blob_under_an_unconfigured_key_is_refused():
    header, ct = blob()
    only_k2 = bs.parse_keyring(f"k2:{K2}", "k2")
    with pytest.raises(bs.KeyUnavailableError):
        bs.decrypt(header, ct, keyring=only_k2)


def test_rewrap_changes_only_the_key_wrapping():
    header, ct = blob(b"payload")
    fields = bs.rewrapped(header, keyring=ring(), new_kek_id="k2")
    assert fields["kek_id"] == "k2" and fields["wrap_nonce"] != header["wrap_nonce"]
    moved = {**header, **fields}
    assert bs.decrypt(moved, ct, keyring=ring()) == b"payload"
    # after rotation the old key can be retired
    assert bs.decrypt(moved, ct, keyring=bs.parse_keyring(f"k2:{K2}", "k2")) == b"payload"


# ── master keys ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,active", [
    ("", "k1"),
    (f"k1:{base64.b64encode(b'x' * 31).decode()}", "k1"),     # 31 bytes
    (f"k1:{base64.b64encode(b'x' * 33).decode()}", "k1"),     # 33 bytes
    ("k1:not*base64!", "k1"),
    (f"k1{K1}", "k1"),                                         # no separator
    (f"bad id:{K1}", "bad id"),
    (f"k1:{K1},k1:{K2}", "k1"),                                # repeated id
    (f"k1:{K1}", "k9"),                                        # active not configured
    (f"k1:{K1}", ""),
])
def test_key_configuration_is_strict(raw, active):
    with pytest.raises(bs.KeyConfigError) as err:
        bs.parse_keyring(raw, active)
    # never echo key material
    assert K1 not in str(err.value) and K2 not in str(err.value)


def test_keyring_problems_reports_without_key_material(monkeypatch):
    monkeypatch.setattr(settings, "analyzer_keks", f"k1:{base64.b64encode(b'y' * 16).decode()}")
    monkeypatch.setattr(settings, "analyzer_kek_active", "k1")
    problems = bs.keyring_problems()
    assert len(problems) == 1 and "exactly 32" in problems[0]
    monkeypatch.setattr(settings, "analyzer_keks", f"k1:{K1}")
    assert bs.keyring_problems() == []


# ── storage ──────────────────────────────────────────────────────────────────

@pytest.fixture
def store(monkeypatch, tmp_path, mongo):
    monkeypatch.setattr(settings, "upload_root", str(tmp_path))
    monkeypatch.setattr(settings, "analyzer_keks", f"k1:{K1},k2:{K2}")
    monkeypatch.setattr(settings, "analyzer_kek_active", "k1")
    return mongo


async def _record(db, header):
    await db["analysis_blobs"].insert_one(header)


async def test_write_then_read(store):
    source = f"src-{uuid.uuid4().hex[:8]}"
    plaintext = b"Rent is PKR 85,000 per month." * 20
    header = await bs.write(plaintext, source_id=source, purpose="original", mime="application/pdf")
    on_disk = bs._path(header["_id"]).read_bytes()
    assert plaintext[:20] not in on_disk, "plaintext reached the disk"
    await _record(store, header)
    assert await bs.read(header["_id"], source_id=source, purpose="original") == plaintext


async def test_a_blob_is_read_only_for_its_own_source_and_purpose(store):
    source = f"src-{uuid.uuid4().hex[:8]}"
    header = await bs.write(b"secret", source_id=source, purpose="original", mime="application/pdf")
    await _record(store, header)
    with pytest.raises(bs.BlobNotFoundError):
        await bs.read(header["_id"], source_id="someone-else", purpose="original")
    with pytest.raises(bs.BlobNotFoundError):
        await bs.read(header["_id"], source_id=source, purpose="canonical_text")


async def test_removal_is_idempotent(store):
    header = await bs.write(b"x", source_id="s", purpose="original", mime="application/pdf")
    await bs.remove_file(header["_id"])
    await bs.remove_file(header["_id"])
    assert not bs._path(header["_id"]).exists()


async def test_rewrap_is_atomic_and_leaves_the_file_alone(store, monkeypatch):
    source = f"src-{uuid.uuid4().hex[:8]}"
    header = await bs.write(b"rotate me", source_id=source, purpose="original", mime="application/pdf")
    await _record(store, header)
    before = bs._path(header["_id"]).read_bytes()

    monkeypatch.setattr(settings, "analyzer_kek_active", "k2")
    assert await bs.rewrap(header["_id"]) is True
    assert await bs.rewrap(header["_id"]) is False         # already under k2
    assert bs._path(header["_id"]).read_bytes() == before  # content untouched
    row = await store["analysis_blobs"].find_one({"_id": header["_id"]})
    assert row["kek_id"] == "k2" and row["wrap_nonce"] != header["wrap_nonce"]
    monkeypatch.setattr(settings, "analyzer_keks", f"k2:{K2}")   # k1 retired
    assert await bs.read(header["_id"], source_id=source, purpose="original") == b"rotate me"


async def test_a_lost_rewrap_race_changes_nothing(store, monkeypatch):
    header = await bs.write(b"race", source_id="s", purpose="original", mime="application/pdf")
    await _record(store, header)
    monkeypatch.setattr(settings, "analyzer_kek_active", "k2")
    keyring = bs.configured_keyring()
    # Two rotations read the same header; the first commits.
    assert await bs._commit_rewrap(dict(header), keyring=keyring, new_kek_id="k2") is True
    winner = await store["analysis_blobs"].find_one({"_id": header["_id"]})
    # The second still holds the stale header: its CAS must miss.
    assert await bs._commit_rewrap(dict(header), keyring=keyring, new_kek_id="k2") is False
    row = await store["analysis_blobs"].find_one({"_id": header["_id"]})
    assert row["wrap_nonce"] == winner["wrap_nonce"], "the loser overwrote the winner"
    assert await bs.read(header["_id"], source_id="s", purpose="original") == b"race"


async def test_sweep_removes_only_old_unreferenced_files(store):
    kept = await bs.write(b"kept", source_id="s", purpose="original", mime="application/pdf")
    await _record(store, kept)
    orphan = await bs.write(b"orphan", source_id="s", purpose="original", mime="application/pdf")
    fresh = await bs.write(b"fresh", source_id="s", purpose="original", mime="application/pdf")
    old = time.time() - 7200
    for h in (kept, orphan):
        os.utime(bs._path(h["_id"]), (old, old))
    stray = bs._root() / ".x.bin.deadbeef.tmp"
    stray.write_bytes(b"half")
    os.utime(stray, (old, old))

    assert await bs.sweep_orphans(older_than_seconds=3600) == 2
    assert bs._path(kept["_id"]).exists(), "a referenced file was swept"
    assert bs._path(fresh["_id"]).exists(), "an upload still in flight was swept"
    assert not bs._path(orphan["_id"]).exists() and not stray.exists()
