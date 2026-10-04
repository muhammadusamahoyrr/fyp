"""Encrypted storage for analyzer files (DOC_ANALYZER_PLAN.md §6.4).

Everything a user uploads to the analyzer, and every canonical text derived
from it, is stored encrypted with a per-blob data key. What is on disk alone
is useless; what is in Mongo alone is useless; both plus a configured master
key are needed to read a byte.

ENVELOPE (format 1)

  * AES-256-GCM for the content AND for wrapping the data key.
  * One fresh 32-byte data key (DEK) per blob, used for exactly one
    encryption, so a content nonce can never repeat under a DEK.
  * Two SEPARATE random 96-bit nonces: `content_nonce` and `wrap_nonce`.
  * `AESGCM.encrypt` returns ciphertext with its 16-byte tag APPENDED. The file
    holds `ciphertext || tag`; `wrapped_dek` holds `wrapped || tag`. There is
    no separate tag field.
  * AAD binds context, so a blob or a key cannot be swapped between records:
        content: {format, blob_id, source_id, purpose, mime}
        wrap:    {format, blob_id, source_id, purpose, kek_id}
    Editing any of those header fields makes decryption fail.
  * The header lives in Mongo (`analysis_blobs`); the disk holds only
    `ciphertext || tag`, at {upload_root}/analyzer/blobs/{blob_id}.bin.

MASTER KEYS

  `ANALYZER_KEKS` = "id:base64,id:base64"; `ANALYZER_KEK_ACTIVE` = the id used
  for new blobs. Every key must decode to EXACTLY 32 bytes or the analyzer is
  not ready (readiness reports it; key material never appears in a message).
  Rotation re-wraps data keys only (`rewrap`); content is never re-encrypted.

FAILURE IS AN ERROR, NEVER A PARTIAL READ. A GCM failure on the key or the
content raises `BlobIntegrityError` and returns no bytes.
"""
from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import json
import os
import re
import secrets
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

FORMAT = 1
ALG = "A256GCM"
NONCE_BYTES = 12
KEY_BYTES = 32
TAG_BYTES = 16
#: `pii_map`: the encrypted token -> value map of PII masking (pii_mask.py).
PURPOSES = ("original", "canonical_text", "pii_map")

_KEK_ID = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
_BLOB_ID = re.compile(r"^[0-9a-f]{32}$")


class KeyConfigError(RuntimeError):
    """The master-key configuration is unusable. Messages carry ids, never keys."""


class KeyUnavailableError(RuntimeError):
    """A blob is wrapped under a key id that is not configured here."""


class BlobIntegrityError(RuntimeError):
    """Authentication failed: the file, the header or the key does not match."""


class BlobNotFoundError(LookupError):
    """No such blob for this source and purpose."""


# ── keys ─────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Keyring:
    keys: dict[str, bytes]
    active: str

    def key(self, kek_id: str) -> bytes:
        try:
            return self.keys[kek_id]
        except KeyError:
            raise KeyUnavailableError(
                f"blob is wrapped under key id {kek_id!r}, which is not configured") from None


def parse_keyring(raw: str, active: str) -> Keyring:
    """Parse `ANALYZER_KEKS` / `ANALYZER_KEK_ACTIVE`, or raise KeyConfigError.

    Strict: bad base64, a key that is not exactly 32 bytes, a malformed or
    repeated id, or an active id that is not configured are all refusals.
    """
    keys: dict[str, bytes] = {}
    entries = [e.strip() for e in (raw or "").split(",") if e.strip()]
    if not entries:
        raise KeyConfigError("ANALYZER_KEKS is empty: no master key is configured")
    for entry in entries:
        kek_id, sep, encoded = entry.partition(":")
        kek_id = kek_id.strip()
        if not sep or not _KEK_ID.match(kek_id):
            raise KeyConfigError(
                "ANALYZER_KEKS entries must look like id:base64 with an id of "
                "letters, digits, '_' or '-' (at most 32)")
        if kek_id in keys:
            raise KeyConfigError(f"ANALYZER_KEKS repeats key id {kek_id!r}")
        try:
            key = base64.b64decode(encoded.strip(), validate=True)
        except (binascii.Error, ValueError):
            raise KeyConfigError(f"key {kek_id!r} is not valid base64") from None
        if len(key) != KEY_BYTES:
            raise KeyConfigError(
                f"key {kek_id!r} decodes to {len(key)} bytes; exactly {KEY_BYTES} are required")
        keys[kek_id] = key
    active = (active or "").strip()
    if active not in keys:
        raise KeyConfigError(
            "ANALYZER_KEK_ACTIVE must name one of the configured key ids")
    return Keyring(keys=keys, active=active)


def configured_keyring() -> Keyring:
    from app.core.config import settings
    return parse_keyring(settings.analyzer_keks, settings.analyzer_kek_active)


def keyring_problems() -> list[str]:
    """For readiness: why the configured keys cannot be used, or []."""
    try:
        configured_keyring()
    except KeyConfigError as exc:
        return [f"analyzer_keys_invalid: {exc}"]
    return []


# ── the envelope (pure) ──────────────────────────────────────────────────────

def _aad(**fields) -> bytes:
    return json.dumps(fields, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _content_aad(header: dict) -> bytes:
    return _aad(format=header["format"], blob_id=header["_id"], source_id=header["source_id"],
                purpose=header["purpose"], mime=header["mime"])


def _wrap_aad(header: dict, kek_id: str) -> bytes:
    return _aad(format=header["format"], blob_id=header["_id"], source_id=header["source_id"],
                purpose=header["purpose"], kek_id=kek_id)


def encrypt(plaintext: bytes, *, blob_id: str, source_id: str, purpose: str, mime: str,
            keyring: Keyring) -> tuple[dict, bytes]:
    """Return `(header, ciphertext_with_tag)`. Performs no I/O."""
    if purpose not in PURPOSES:
        raise ValueError(f"unknown blob purpose: {purpose!r}")
    if not _BLOB_ID.match(blob_id):
        raise ValueError("blob_id must be 32 lowercase hex characters")
    header = {
        "_id": blob_id, "source_id": source_id, "purpose": purpose, "mime": mime,
        "format": FORMAT, "alg": ALG, "kek_id": keyring.active,
        "size": len(plaintext),
        "plaintext_sha256": hashlib.sha256(plaintext).hexdigest(),
    }
    dek = AESGCM.generate_key(bit_length=KEY_BYTES * 8)
    content_nonce = secrets.token_bytes(NONCE_BYTES)
    wrap_nonce = secrets.token_bytes(NONCE_BYTES)
    ciphertext = AESGCM(dek).encrypt(content_nonce, plaintext, _content_aad(header))
    wrapped = AESGCM(keyring.key(keyring.active)).encrypt(
        wrap_nonce, dek, _wrap_aad(header, keyring.active))
    header.update(content_nonce=content_nonce, wrap_nonce=wrap_nonce, wrapped_dek=wrapped,
                  ciphertext_size=len(ciphertext))
    return header, ciphertext


def _unwrap(header: dict, keyring: Keyring) -> bytes:
    try:
        return AESGCM(keyring.key(header["kek_id"])).decrypt(
            bytes(header["wrap_nonce"]), bytes(header["wrapped_dek"]),
            _wrap_aad(header, header["kek_id"]))
    except InvalidTag:
        raise BlobIntegrityError("data key failed authentication") from None


def decrypt(header: dict, ciphertext: bytes, *, keyring: Keyring) -> bytes:
    """Plaintext, or BlobIntegrityError. Never a partial result."""
    if header.get("format") != FORMAT or header.get("alg") != ALG:
        raise BlobIntegrityError("unsupported blob format")
    dek = _unwrap(header, keyring)
    try:
        return AESGCM(dek).decrypt(bytes(header["content_nonce"]), ciphertext,
                                   _content_aad(header))
    except InvalidTag:
        raise BlobIntegrityError("content failed authentication") from None


def rewrapped(header: dict, *, keyring: Keyring, new_kek_id: str) -> dict:
    """The header fields that re-wrap this blob's data key under `new_kek_id`.

    A NEW wrap nonce, always. The content and its nonce are untouched."""
    dek = _unwrap(header, keyring)
    wrap_nonce = secrets.token_bytes(NONCE_BYTES)
    wrapped = AESGCM(keyring.key(new_kek_id)).encrypt(
        wrap_nonce, dek, _wrap_aad(header, new_kek_id))
    return {"kek_id": new_kek_id, "wrap_nonce": wrap_nonce, "wrapped_dek": wrapped}


# ── storage ──────────────────────────────────────────────────────────────────

def _root() -> Path:
    from app.core.config import settings
    # Resolved each call so a test that repoints upload_root is honoured.
    return Path(settings.upload_root).resolve() / "analyzer" / "blobs"


def _path(blob_id: str) -> Path:
    if not _BLOB_ID.match(blob_id):
        raise ValueError("blob_id must be 32 lowercase hex characters")
    return _root() / f"{blob_id}.bin"


def _write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    with open(tmp, "wb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def new_blob_id() -> str:
    return uuid.uuid4().hex


async def write(plaintext: bytes, *, source_id: str, purpose: str, mime: str,
                blob_id: str | None = None) -> dict:
    """Encrypt and write the FILE; return the header to be recorded.

    Deliberately does not insert the Mongo record: the caller records it in the
    same transaction as whatever the blob belongs to (the upload's source and
    run), so a failed transaction leaves at most an unreferenced file, which
    `sweep_orphans` removes. The reverse (a record whose file never landed)
    cannot happen: the file is written first.
    """
    keyring = configured_keyring()
    header, ciphertext = encrypt(plaintext, blob_id=blob_id or new_blob_id(),
                                 source_id=source_id, purpose=purpose, mime=mime,
                                 keyring=keyring)
    await asyncio.to_thread(_write_atomic, _path(header["_id"]), ciphertext)
    header["created_at"] = datetime.now(timezone.utc)
    return header


async def read(blob_id: str, *, source_id: str, purpose: str) -> bytes:
    """The plaintext of one blob, checked to belong to this source and purpose."""
    from app.db.collections import get_analysis_blobs_col

    header = await get_analysis_blobs_col().find_one(
        {"_id": blob_id, "source_id": source_id, "purpose": purpose})
    if header is None:
        raise BlobNotFoundError("no such blob for this source")
    try:
        ciphertext = await asyncio.to_thread(_path(blob_id).read_bytes)
    except FileNotFoundError:
        raise BlobNotFoundError("blob file is missing") from None
    return decrypt(header, ciphertext, keyring=configured_keyring())


async def remove_file(blob_id: str) -> None:
    """Idempotent: a file already gone is the goal, not an error."""
    try:
        await asyncio.to_thread(_path(blob_id).unlink)
    except FileNotFoundError:
        pass


async def rewrap(blob_id: str, *, new_kek_id: str | None = None) -> bool:
    """Re-wrap one blob's data key under a new master key, atomically.

    One conditional update on `(_id, kek_id, wrap_nonce)`: if another rotation
    got there first, this returns False and changes nothing. The file is never
    touched.
    """
    from app.db.collections import get_analysis_blobs_col

    keyring = configured_keyring()
    target = new_kek_id or keyring.active
    col = get_analysis_blobs_col()
    header = await col.find_one({"_id": blob_id})
    if header is None:
        raise BlobNotFoundError("no such blob")
    if header["kek_id"] == target:
        return False
    return await _commit_rewrap(header, keyring=keyring, new_kek_id=target)


async def _commit_rewrap(header: dict, *, keyring: Keyring, new_kek_id: str) -> bool:
    """Replace the wrapping of `header`'s data key, if nobody else did since.

    The filter is the header as READ: `(kek_id, wrap_nonce)` identify the exact
    wrapping this worker unwrapped. A concurrent rotation changes the nonce, so
    a loser matches nothing and cannot overwrite the winner.
    """
    from app.db.collections import get_analysis_blobs_col

    fields = rewrapped(header, keyring=keyring, new_kek_id=new_kek_id)
    result = await get_analysis_blobs_col().update_one(
        {"_id": header["_id"], "kek_id": header["kek_id"], "wrap_nonce": header["wrap_nonce"]},
        {"$set": fields})
    return result.modified_count == 1


async def sweep_orphans(older_than_seconds: int = 3600) -> int:
    """Delete files with no `analysis_blobs` record, older than the cutoff.

    A file is written before its record is committed; if that transaction
    fails, or the process dies between the two, the file is unreferenced.
    The age cutoff keeps this from racing an upload still in flight.
    """
    from app.db.collections import get_analysis_blobs_col

    root = _root()
    if not root.exists():
        return 0
    cutoff = time.time() - older_than_seconds
    candidates = []
    for path in root.iterdir():
        name = path.name
        if name.endswith(".tmp") and path.stat().st_mtime < cutoff:
            candidates.append((None, path))      # an interrupted atomic write
        elif name.endswith(".bin") and _BLOB_ID.match(name[:-4]) and path.stat().st_mtime < cutoff:
            candidates.append((name[:-4], path))
    ids = [b for b, _ in candidates if b]
    known = set()
    if ids:
        async for row in get_analysis_blobs_col().find({"_id": {"$in": ids}}, {"_id": 1}):
            known.add(row["_id"])
    removed = 0
    for blob_id, path in candidates:
        if blob_id in known:
            continue
        try:
            await asyncio.to_thread(path.unlink)
            removed += 1
        except FileNotFoundError:
            pass
    return removed
