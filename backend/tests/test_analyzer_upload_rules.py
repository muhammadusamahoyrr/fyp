"""Document Analyzer, P1 slice 1 / commit 3: what an upload must be.

Pure: every fixture is built in memory. The DOCX cases are real zip files
whose DECLARED structure trips each guard (see upload_rules' docstring for
what is deliberately left to the extraction stage).
"""
from __future__ import annotations

import io
import os
import zipfile

import pytest

from app.services.analyzer import upload_rules as ur
from app.services.analyzer.errors import UploadRejected

PDF = b"%PDF-1.4\n1 0 obj << >> endobj\ntrailer << >>\n%%EOF\n"


def _flag_encrypted(data: bytes, name: str) -> bytes:
    """Set the 'encrypted' bit on `name`'s central-directory record.

    `zipfile` resets flag_bits when it writes, so the bit is patched into the
    bytes afterwards -- in the central directory, which is what `infolist()`
    (and therefore the validator) reads.
    """
    out = bytearray(data)
    target = name.encode()
    at = out.find(b"PK")
    while at != -1:
        name_len = int.from_bytes(out[at + 28:at + 30], "little")
        if bytes(out[at + 46:at + 46 + name_len]) == target:
            out[at + 8] |= 0x01
            return bytes(out)
        at = out.find(b"PK", at + 4)
    raise AssertionError(f"{name} not in the central directory")


def docx(parts: dict[str, bytes] | None = None, *, flag_encrypted: str | None = None,
         extra: int = 0) -> bytes:
    parts = parts if parts is not None else {
        "[Content_Types].xml": b"<Types/>",
        "word/document.xml": b"<w:document><w:body><w:p>Rent is PKR 85,000.</w:p></w:body></w:document>",
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in parts.items():
            info = zipfile.ZipInfo(name)
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, data)
        for i in range(extra):
            z.writestr(f"customXml/item{i}.xml", b"<x/>")
    data = buf.getvalue()
    return _flag_encrypted(data, flag_encrypted) if flag_encrypted else data


def png(width: int, height: int, mode: str = "1") -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new(mode, (width, height)).save(buf, format="PNG")
    return buf.getvalue()


def code_of(content: bytes) -> str:
    with pytest.raises(UploadRejected) as err:
        ur.validate(content)
    return err.value.code


# ── accepted ─────────────────────────────────────────────────────────────────

def test_a_pdf_is_accepted_by_content():
    v = ur.validate(PDF)
    assert (v.mime, v.kind, v.size) == (ur.PDF, "pdf", len(PDF))
    assert len(v.sha256) == 64


def test_a_real_docx_is_accepted():
    assert ur.validate(docx()).kind == "docx"


def test_a_small_png_is_accepted():
    assert ur.validate(png(40, 30, "RGB")).kind == "image"


# ── refused ──────────────────────────────────────────────────────────────────

def test_empty_and_oversized_files():
    assert code_of(b"") == "empty_file"
    with pytest.raises(UploadRejected) as err:
        ur.validate(b"%PDF-" + b"0" * ur.MAX_BYTES)
    assert err.value.code == "file_too_large" and err.value.status == 413


def test_old_word_is_refused_with_a_way_forward():
    with pytest.raises(UploadRejected) as err:
        ur.validate(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 100)
    assert err.value.code == "doc_not_supported" and ".docx or PDF" in err.value.message


@pytest.mark.parametrize("content", [
    b"GIF89a" + b"\0" * 20,                       # an image type we do not OCR
    b"just some text, not a document",
    b"RIFF\0\0\0\0WEBPVP8 ",
])
def test_other_types_are_refused(content):
    assert code_of(content) == "unsupported_type"


def test_a_plain_zip_is_not_a_docx():
    # PK magic means "a zip". detect_mime alone would call this a Word file.
    assert code_of(docx({"notes.txt": b"hello"})) == "invalid_docx"
    assert code_of(b"PK\x03\x04 truncated") == "invalid_docx"


def test_encrypted_docx_entries_are_refused():
    assert code_of(docx(flag_encrypted="word/document.xml")) == "encrypted_docx"


def test_too_many_parts():
    assert code_of(docx(extra=ur.DOCX_MAX_ENTRIES)) == "docx_too_complex"


def test_an_entry_declaring_too_much_is_refused():
    parts = {"[Content_Types].xml": b"<Types/>", "word/document.xml": b"<w/>",
             "word/media/big.bin": b"\0" * (ur.DOCX_MAX_ENTRY_UNCOMPRESSED + 1)}
    assert code_of(docx(parts)) == "docx_too_large"


def test_a_compression_bomb_is_refused_by_ratio():
    # 8 MB of zeros deflates to a few KB: a ratio far above 100:1.
    parts = {"[Content_Types].xml": b"<Types/>", "word/document.xml": b"<w/>",
             "word/media/pad.bin": b"\0" * (8 * 1024 * 1024)}
    assert code_of(docx(parts)) == "docx_too_large"


def test_an_overlong_document_xml_is_refused():
    # Hex text barely compresses (~2:1), so only the document.xml cap applies.
    body = os.urandom(ur.DOCX_MAX_DOCUMENT_XML // 2 + 10).hex().encode()
    parts = {"[Content_Types].xml": b"<Types/>", "word/document.xml": body}
    with pytest.raises(UploadRejected) as err:
        ur.validate(docx(parts))
    assert err.value.code == "docx_too_large" and "longer" in err.value.message


def test_images_over_25_megapixels_and_broken_images():
    assert code_of(png(6000, 5000)) == "image_too_large"          # 30 MP, tiny file
    assert code_of(b"\x89PNG\r\n\x1a\n" + b"garbage" * 10) == "invalid_image"


# ── options, attestation, fingerprint ────────────────────────────────────────

def test_options_are_normalised_and_bounded():
    assert ur.normalise_options(None, None) == {"side": "tenant", "depth": "medium"}
    assert ur.normalise_options(" Landlord ", "DEEP") == {"side": "landlord", "depth": "deep"}
    with pytest.raises(UploadRejected) as err:
        ur.normalise_options("buyer", "quick")
    assert err.value.code == "invalid_side"
    with pytest.raises(UploadRejected):
        ur.normalise_options("tenant", "exhaustive")


@pytest.mark.parametrize("attested", [None, "", "false", "True", "1", "yes"])
def test_attestation_must_be_exactly_true(attested):
    with pytest.raises(UploadRejected) as err:
        ur.check_attestation(attested, "synthetic-v1")
    assert err.value.code == "synthetic_attestation_required"


def test_attestation_must_name_a_known_wording():
    with pytest.raises(UploadRejected):
        ur.check_attestation("true", "synthetic-v0")
    assert ur.check_attestation("true", "synthetic-v1") == {"synthetic": True,
                                                            "ui_text_version": "synthetic-v1"}
    assert "do not upload real client or confidential documents" in \
        ur.ATTESTATION_VERSIONS["synthetic-v1"]


def test_the_fingerprint_covers_file_options_and_attestation():
    att = {"synthetic": True, "ui_text_version": "synthetic-v1"}
    base = ur.request_fingerprint("a" * 64, {"side": "tenant", "depth": "medium"}, att)
    assert base == ur.request_fingerprint("a" * 64, {"depth": "medium", "side": "tenant"}, att)
    assert base != ur.request_fingerprint("b" * 64, {"side": "tenant", "depth": "medium"}, att)
    assert base != ur.request_fingerprint("a" * 64, {"side": "landlord", "depth": "medium"}, att)
    assert base != ur.request_fingerprint("a" * 64, {"side": "tenant", "depth": "medium"},
                                          {**att, "ui_text_version": "synthetic-v2"})
