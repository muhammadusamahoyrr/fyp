"""Authenticated encryption for stored signatures — AES-256-GCM.

WHAT THIS REPLACES. `parties[].signature_data` held the raw base64 PNG of a
drawn signature, or a typed legal name, in clear. Privacy was achieved by
OMISSION -- `PartyOut` does not declare the field, so it is not serialised --
which protects it from a counterparty and from nobody else. Anyone reading the
database read every signature on the platform. Meanwhile the UI told users
"AES-256 encrypted", which was untrue twice over: nothing was encrypted, and
the only cipher in the system was Fernet (AES-128-CBC) for CNICs.

WHY A SEPARATE KEY FROM `encryption_key`. That key is Fernet's, and it protects
CNICs. Reusing it would mean one compromised key exposes identity documents and
signatures together, and rotating for one forces rotation for the other. They
are different data with different lifetimes, so they get different keys.
`SIGNATURE_ENCRYPTION_KEY` is unrelated to the CNIC key and nothing here touches
`security.py`.

WHY GCM AND NOT FERNET. Fernet is fine, but it has no associated data. AES-GCM
authenticates AAD alongside the ciphertext, which lets the envelope be BOUND to
the agreement and the party it belongs to: a ciphertext lifted out of one row
and pasted into another fails to decrypt rather than silently producing a valid
signature under someone else's name. That is the replay protection, and it is
the reason for the choice.

ENCRYPTION IS NOT INTEGRITY, AND THIS FILE DOES ONLY THE FIRST. `body_sha256`
still records what was signed, and the idempotency fingerprint still hashes the
PLAINTEXT signature. Both are unchanged and neither is a secret: a digest proves
a document was not altered, it does not keep anything confidential. Conflating
the two is how a system ends up claiming encryption because it computes hashes.

LEGACY ROWS ARE READ, NEVER REWRITTEN. Signatures written before this module
exists are plain strings. `decrypt_signature` returns them unchanged, so the PDF
of an agreement executed last month still renders. Nothing here migrates them:
re-encrypting historical rows is an operator decision about production data, not
a side effect of a deploy.
"""
from __future__ import annotations

import base64
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import settings

#: Envelope version. Bumped only if the shape or algorithm changes, so an old
#: row can always say how to read itself rather than being guessed at.
ENVELOPE_VERSION = 1
ALGORITHM = "AES-256-GCM"

#: 96 bits, the size AES-GCM is specified for. A random nonce per encryption.
_NONCE_BYTES = 12
_KEY_BYTES = 32                       # AES-256

_KEY_HELP = (
    "SIGNATURE_ENCRYPTION_KEY is not set. Signatures are not stored without it "
    "-- this refuses rather than falling back to clear text. Generate one with:\n"
    "    python -c \"import base64,os; "
    "print(base64.b64encode(os.urandom(32)).decode())\"\n"
    "It is SEPARATE from ENCRYPTION_KEY (which protects CNICs) and must not be "
    "the same value."
)


class SignatureKeyMissing(RuntimeError):
    """Raised when a signature would be stored with no key configured."""


class SignatureDecryptionError(RuntimeError):
    """The envelope did not authenticate — wrong key, wrong agreement, wrong
    party, or tampered ciphertext. Deliberately does not say which."""


def _key() -> bytes:
    """The configured key, or refuse.

    Read on every call rather than cached at import: tests point it at a
    throwaway value, and a module-level cache would freeze whichever key
    happened to be set when the first agreement was signed.
    """
    raw = (getattr(settings, "signature_encryption_key", "") or "").strip()
    if not raw:
        raise SignatureKeyMissing(_KEY_HELP)
    try:
        key = base64.b64decode(raw, validate=True)
    except Exception as exc:                                      # noqa: BLE001
        raise SignatureKeyMissing(
            "SIGNATURE_ENCRYPTION_KEY is not valid base64. " + _KEY_HELP
        ) from exc
    if len(key) != _KEY_BYTES:
        raise SignatureKeyMissing(
            f"SIGNATURE_ENCRYPTION_KEY decodes to {len(key)} bytes, not "
            f"{_KEY_BYTES}. AES-256 needs exactly {_KEY_BYTES}. " + _KEY_HELP
        )
    return key


def associated_data(agreement_id: str, party_ref: str) -> bytes:
    """What the ciphertext is bound to.

    `party_ref` is the party's `user_id` for a registered signer and its
    `party_id` for an external one — whichever identifies the SLOT this
    signature fills. Both are included so a signature cannot be moved between
    agreements, or between parties of one agreement, and still decrypt.
    """
    return f"v{ENVELOPE_VERSION}|{agreement_id}|{party_ref}".encode("utf-8")


def is_encrypted(stored) -> bool:
    """True when `stored` is an envelope this module wrote."""
    return isinstance(stored, dict) and stored.get("alg") == ALGORITHM


def encrypt_signature(plaintext: str, *, agreement_id: str,
                      party_ref: str) -> dict:
    """The stored envelope for one signature. Never returns clear text."""
    if plaintext is None:
        raise ValueError("refusing to encrypt a null signature")
    nonce = os.urandom(_NONCE_BYTES)
    ct = AESGCM(_key()).encrypt(
        nonce, plaintext.encode("utf-8"),
        associated_data(agreement_id, party_ref))
    return {
        "v": ENVELOPE_VERSION,
        "alg": ALGORITHM,
        "n": base64.b64encode(nonce).decode("ascii"),
        "ct": base64.b64encode(ct).decode("ascii"),
    }


def decrypt_signature(stored, *, agreement_id: str, party_ref: str) -> str | None:
    """The signature behind `stored`, whatever shape it is in.

    THREE CASES, AND THE MIDDLE ONE IS THE POINT:

    `None`        no signature yet — returns None.
    a plain `str` a row written before this module. Returned as it stands, so
                  historical agreements still render. NOT re-encrypted here.
    an envelope   decrypted, with the agreement and party as associated data.

    A failure to authenticate raises rather than returning a placeholder: a
    signature that cannot be verified must not be presented as one.
    """
    if stored is None:
        return None
    if isinstance(stored, str):
        return stored
    if not is_encrypted(stored):
        raise SignatureDecryptionError(
            "stored signature is neither clear text nor a recognised envelope")
    try:
        ct = base64.b64decode(stored["ct"])
        nonce = base64.b64decode(stored["n"])
    except Exception as exc:                                      # noqa: BLE001
        raise SignatureDecryptionError("malformed signature envelope") from exc
    try:
        plain = AESGCM(_key()).decrypt(
            nonce, ct, associated_data(agreement_id, party_ref))
    except InvalidTag as exc:
        raise SignatureDecryptionError(
            "signature did not authenticate for this agreement and party"
        ) from exc
    return plain.decode("utf-8")
