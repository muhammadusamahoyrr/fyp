"""A lawyer's private files on a case (2026-10-11).

Private to the uploader; the case is re-checked on every call; the kind of file
is decided from its bytes; a closed case takes no new files.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.core.config import settings
from app.db.collections import get_cases_col
from app.db.mongodb import get_database
from app.services import case_files

pytestmark = pytest.mark.integration

LAWYER, OTHER, CLIENT = "cf-lawyer", "cf-other", "cf-client"
CASE, CLOSED, NOT_MINE = "cf-case", "cf-closed", "cf-not-mine"
PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


@pytest.fixture(autouse=True)
async def _setup(mongo, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "upload_root", str(tmp_path))
    cases = get_cases_col()
    await cases.delete_many({"_id": {"$in": [CASE, CLOSED, NOT_MINE]}})
    await cases.insert_many([
        {"_id": CASE, "client_id": CLIENT, "lawyer_id": LAWYER, "status": "in_progress", "title": "A"},
        {"_id": CLOSED, "client_id": CLIENT, "lawyer_id": LAWYER, "status": "closed", "title": "B"},
        {"_id": NOT_MINE, "client_id": CLIENT, "lawyer_id": OTHER, "status": "in_progress", "title": "C"},
    ])
    await get_database()["case_files"].delete_many({"case_id": {"$in": [CASE, CLOSED, NOT_MINE]}})
    yield
    await cases.delete_many({"_id": {"$in": [CASE, CLOSED, NOT_MINE]}})
    await get_database()["case_files"].delete_many({"case_id": {"$in": [CASE, CLOSED, NOT_MINE]}})


async def test_upload_list_read_delete():
    up = await case_files.upload(CASE, LAWYER, PDF, "summons.pdf")
    assert up["name"] == "summons.pdf" and up["content_type"] == "application/pdf"
    assert [f["id"] for f in await case_files.list_for_case(CASE, LAWYER)] == [up["id"]]
    row, data = await case_files.read(CASE, up["id"], LAWYER)
    assert data == PDF
    await case_files.delete(CASE, up["id"], LAWYER)
    assert await case_files.list_for_case(CASE, LAWYER) == []


async def test_the_kind_comes_from_the_bytes_not_the_name():
    up = await case_files.upload(CASE, LAWYER, PNG, "looks-like.pdf")
    assert up["content_type"] == "image/png" and up["name"] == "looks-like.png"
    with pytest.raises(HTTPException) as e:
        await case_files.upload(CASE, LAWYER, b"<html><script>x</script>", "evil.pdf")
    assert e.value.status_code == 422


async def test_size_and_empty_are_refused():
    with pytest.raises(HTTPException):
        await case_files.upload(CASE, LAWYER, b"", "x.pdf")
    with pytest.raises(HTTPException) as e:
        await case_files.upload(CASE, LAWYER, b"%PDF-" + b"0" * case_files.MAX_BYTES, "big.pdf")
    assert e.value.status_code == 422


async def test_a_path_in_the_name_is_only_a_label():
    up = await case_files.upload(CASE, LAWYER, PDF, "..\\..\\etc/passwd")
    assert "/" not in up["name"] and "\\" not in up["name"] and up["name"].endswith(".pdf")
    # Stored under the server's id, inside the store.
    assert case_files._path_for(up["id"]).parent == case_files._root()


async def test_another_lawyer_sees_nothing_and_cannot_upload():
    up = await case_files.upload(CASE, LAWYER, PDF, "a.pdf")
    with pytest.raises(HTTPException) as e:
        await case_files.list_for_case(CASE, OTHER)
    assert e.value.status_code in (403, 404)
    with pytest.raises(HTTPException):
        await case_files.read(CASE, up["id"], OTHER)
    with pytest.raises(HTTPException):
        await case_files.upload(NOT_MINE, LAWYER, PDF, "a.pdf")


async def test_a_file_id_on_another_case_is_not_found():
    up = await case_files.upload(CASE, LAWYER, PDF, "a.pdf")
    await get_cases_col().update_one({"_id": NOT_MINE}, {"$set": {"lawyer_id": LAWYER}})
    with pytest.raises(HTTPException) as e:
        await case_files.read(NOT_MINE, up["id"], LAWYER)
    assert e.value.status_code == 404


async def test_a_closed_case_takes_no_new_files():
    with pytest.raises(HTTPException) as e:
        await case_files.upload(CLOSED, LAWYER, PDF, "late.pdf")
    assert e.value.status_code == 409


async def test_a_lawyer_taken_off_the_case_loses_its_files():
    up = await case_files.upload(CASE, LAWYER, PDF, "a.pdf")
    await get_cases_col().update_one({"_id": CASE}, {"$set": {"lawyer_id": OTHER}})
    with pytest.raises(HTTPException):
        await case_files.read(CASE, up["id"], LAWYER)
