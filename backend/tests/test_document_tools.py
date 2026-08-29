"""Document-tool tests — the security ones.

The agent can read files a user uploaded. The identity is BOUND INTO THE TOOL at
construction and is never a tool argument, precisely so a hallucinated id cannot
become an IDOR: one user's agent reading another user's FIR.

That property is the whole reason these tests exist. If someone later "simplifies"
read_document to take a user_id parameter, this file is what stops it shipping.
"""
import uuid

import pytest

from app.ai.tools.document_tools import build_document_tools

# NOT marked at file level. The three binding tests below need no service at
# all, and a file-level `integration` marker deselected them from every
# default run -- so the property this file exists to protect (one user's
# agent must never read another user's FIR) was never actually asserted in
# CI. The seven that touch Mongo are marked individually; the `mongo`
# fixture already pytest.skip()s when the database is unreachable, so they
# degrade gracefully on their own.


@pytest.fixture
async def two_users_with_uploads(mongo, tmp_path):
    """Alice and Bob each upload one document."""
    from app.db.collections import get_intakes_col

    alice_file = tmp_path / "alice_fir.txt"
    bob_file = tmp_path / "bob_secret.txt"
    alice_file.write_text("ALICE FIR: theft under s.379 PPC at Model Town police station.")
    bob_file.write_text("BOB CONFIDENTIAL: settlement of Rs 5,000,000.")

    alice_id, bob_id = f"f-{uuid.uuid4().hex[:8]}", f"f-{uuid.uuid4().hex[:8]}"
    alice_tok, bob_tok = f"t-{uuid.uuid4().hex[:8]}", f"t-{uuid.uuid4().hex[:8]}"

    col = get_intakes_col()
    await col.insert_one({
        "_id": alice_tok, "session_token": alice_tok, "client_id": "ALICE",
        "evidence_files": [{"file_id": alice_id, "filename": "fir.txt",
                            "size": 60, "path": str(alice_file)}],
    })
    await col.insert_one({
        "_id": bob_tok, "session_token": bob_tok, "client_id": "BOB",
        "evidence_files": [{"file_id": bob_id, "filename": "secret.txt",
                            "size": 60, "path": str(bob_file)}],
    })

    yield {"alice_file_id": alice_id, "bob_file_id": bob_id}

    await col.delete_many({"_id": {"$in": [alice_tok, bob_tok]}})


def _tools(user_id: str) -> dict:
    return {t.name: t for t in build_document_tools(user_id, "client")}


# ── binding ───────────────────────────────────────────────────────────────────

def test_no_user_means_no_document_tools_at_all():
    """An unbound file reader must never exist."""
    assert build_document_tools("") == []


def test_tools_are_built_for_an_authenticated_user():
    assert set(_tools("ALICE")) == {"list_my_documents", "read_document"}


def test_read_document_does_not_expose_a_user_id_argument():
    """If the model could pass a user id, a hallucinated one would be an IDOR."""
    assert "user_id" not in _tools("ALICE")["read_document"].args
    assert set(_tools("ALICE")["read_document"].args) == {"file_id"}


# ── access control ────────────────────────────────────────────────────────────

@pytest.mark.integration
async def test_user_can_list_their_own_uploads(two_users_with_uploads):
    files = await _tools("ALICE")["list_my_documents"].ainvoke({})
    assert [f["filename"] for f in files] == ["fir.txt"]


@pytest.mark.integration
async def test_user_can_read_their_own_document(two_users_with_uploads):
    result = await _tools("ALICE")["read_document"].ainvoke(
        {"file_id": two_users_with_uploads["alice_file_id"]})
    assert "ALICE FIR" in result["text"]


@pytest.mark.integration
async def test_user_CANNOT_read_another_users_document(two_users_with_uploads):
    """The IDOR test. Alice supplies Bob's real file_id."""
    result = await _tools("ALICE")["read_document"].ainvoke(
        {"file_id": two_users_with_uploads["bob_file_id"]})

    assert "error" in result
    assert "text" not in result
    assert "CONFIDENTIAL" not in str(result)
    assert "5,000,000" not in str(result)


@pytest.mark.integration
async def test_users_listing_is_scoped_to_themselves(two_users_with_uploads):
    bob_files = await _tools("BOB")["list_my_documents"].ainvoke({})
    assert [f["filename"] for f in bob_files] == ["secret.txt"]


@pytest.mark.integration
async def test_unknown_file_id_returns_an_error_not_a_crash(two_users_with_uploads):
    result = await _tools("ALICE")["read_document"].ainvoke({"file_id": "does-not-exist"})
    assert "error" in result


@pytest.mark.integration
async def test_user_with_no_uploads_is_told_so(mongo):
    files = await _tools("NOBODY")["list_my_documents"].ainvoke({})
    assert "error" in files[0]
    # The model must not narrate a document that does not exist.
    assert "not uploaded" in files[0]["error"].lower()


# ── extraction ────────────────────────────────────────────────────────────────

@pytest.mark.integration
async def test_scanned_file_with_no_text_layer_is_reported_not_invented(mongo, tmp_path):
    """There is no OCR in the stack. An empty extraction must say so rather than
    return "" and let the model narrate an imaginary document."""
    from app.db.collections import get_intakes_col

    empty = tmp_path / "scan.txt"
    empty.write_text("   \n  ")
    file_id, token = f"f-{uuid.uuid4().hex[:8]}", f"t-{uuid.uuid4().hex[:8]}"

    col = get_intakes_col()
    await col.insert_one({
        "_id": token, "session_token": token, "client_id": "SCANUSER",
        "evidence_files": [{"file_id": file_id, "filename": "scan.txt",
                            "size": 5, "path": str(empty)}],
    })
    try:
        result = await _tools("SCANUSER")["read_document"].ainvoke({"file_id": file_id})
        assert "error" in result
        assert "no readable text" in result["error"].lower()
    finally:
        await col.delete_one({"_id": token})
