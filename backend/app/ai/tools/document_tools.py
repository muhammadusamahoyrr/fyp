"""Document-reading skills — let the agent read files the user actually uploaded.

Today the intake flow accepts evidence uploads (FIR scans, notices, contracts)
via POST /intake/{token}/evidence. The bytes are validated and written to disk
and then never opened again. These tools close that loop: the agent can list a
user's uploads and read their text.

SECURITY — the important part
-----------------------------
The user's identity is BOUND INTO THE TOOL at construction time; it is never a
tool argument. If it were an argument, the model could pass any user id it liked
and a hallucinated value would become an IDOR: one user's agent reading another
user's FIR. Instead `build_document_tools(user_id, role)` closes over the
authenticated id, and every lookup filters on it inside the database query.

The model can therefore only ever ask "read file X" — and if X is not the
caller's file, the lookup simply finds nothing.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

from langchain_core.tools import BaseTool, StructuredTool

logger = logging.getLogger(__name__)

# Chars of extracted text handed back to the model. A 40-page contract would
# otherwise blow the context budget in a single tool call.
_MAX_CHARS = 12_000


# `_extract_text_sync` was removed with this change rather than kept as a
# wrapper. It returned a bare string, which is precisely the shape that made the
# original defect possible: a caller holding only text cannot know whether it is
# the whole document. `app.ai.extraction.extract_file` is the single extraction
# entry point now, and it always returns the completeness alongside the text.


def _public_extraction(result, text: str) -> dict:
    """The model-facing view of one extraction.

    BACKWARD COMPATIBLE ON PURPOSE. `text`, `chars`, `truncated`, `note` and
    `error` keep their old meanings, because the tool description the model was
    trained against promises them and two callers already read them. Everything
    new is additive, and the one thing that CHANGED is that a partially-read
    document now says so instead of looking identical to a fully-read one.
    """
    from app.ai.extraction import COMPLETE, NONE, message_for

    if result.error_code and not text.strip():
        out = {"error": message_for(result.error_code),
               "extraction": result.as_dict()}
        if result.completeness == NONE:
            out["hint"] = ("Ask the user to type the key details, or to upload a "
                           "text-based PDF.")
        return out

    stripped = text.strip()
    truncated = len(stripped) > _MAX_CHARS
    out = {
        "text": stripped[:_MAX_CHARS],
        "chars": len(stripped),
        "truncated": truncated,
        "extraction": result.as_dict(),
    }
    if truncated:
        out["note"] = f"Only the first {_MAX_CHARS} characters are shown."

    if result.completeness != COMPLETE:
        # The whole point of this milestone. The model is told, in the same
        # breath as the text, that the text is not all of the document — and is
        # told what to do about it, because "some of this is missing" without an
        # instruction reads as a hedge rather than a constraint.
        out["incomplete"] = True
        out["completeness"] = result.completeness
        out["warning"] = _incompleteness_sentence(result)
        out["hint"] = ("Do not assume the missing parts are unimportant. Say "
                       "which pages could not be read and ask the user to type "
                       "those details.")
    return out


def _incompleteness_sentence(result) -> str:
    """Plain words for what was missed. No page is called a scan."""
    bits = []
    if result.pages_total and result.pages_with_text < result.pages_total:
        unread = result.pages_total - result.pages_with_text
        bits.append(f"{unread} of {result.pages_total} pages produced no text")
    if result.pages_skipped:
        bits.append(f"{result.pages_skipped} pages were not processed")
    if result.pages_failed:
        bits.append(f"{result.pages_failed} pages could not be read")
    if any(p.images_present for p in result.page_reports):
        # Deliberately hedged. We saw an image reference; we cannot know whether
        # it held text, and claiming either way is the mistake this replaces.
        bits.append("some pages contain images whose contents cannot be read")
    for note in result.limitations:
        if note.startswith("unsupported_part:"):
            bits.append(f"{note.split(':', 1)[1]} were not read")
    if not bits:
        bits.append("this document may not have been read in full")
    return ("Only part of this document could be read: "
            + "; ".join(bits) + ".")


async def _read_file(path_str: str) -> dict:
    """Read one file through the bounded child-process runner.

    No longer `asyncio.to_thread`: that shares the interpreter-wide executor
    with everything else and cannot actually stop work it has given up waiting
    for. See `app.ai.extraction_runner`.
    """
    from app.ai.extraction_runner import extract_one

    result, text = await extract_one(path_str)
    return _public_extraction(result, text)


# The tools that read ONE user's private files.
#
# Named here, beside the functions themselves, because another decision depends
# on knowing exactly which tools are user-scoped: the result cache must refuse
# any turn that could reach them. A second list maintained elsewhere would go
# stale the first time a tool is added, and it would go stale silently in the
# direction that caches a private answer.
USER_SCOPED_TOOL_NAMES = frozenset({"list_my_documents", "read_document"})


# Does this question ask about the user's OWN files?
#
# Document phrasing shares no vocabulary with the bail/fee/inheritance triggers,
# so it needs its own gate. It lives here rather than in `tool_node` because two
# callers need it now, and the second one — the result cache, deciding whether
# this turn's answer may be shared with other users — runs before `tool_node`
# does. Importing one node from another to ask would be a cycle waiting to
# happen; the question belongs beside the tools it is about.
_DOC_RE = re.compile(
    r"\b(my|the|this|that|uploaded?|attached?)\s+\w*\s*"
    r"(document|documents|file|files|fir|contract|agreement|notice|deed|"
    r"lease|paper|papers|evidence|scan|pdf)\b"
    r"|\b(read|open|check|review|summari[sz]e|look at)\s+(my|the|it|this|that)\b"
    r"|\bi\s+(uploaded|attached|sent)\b",
    re.IGNORECASE,
)


def mentions_document(query: str) -> bool:
    return bool(_DOC_RE.search(query or ""))


def build_document_tools(user_id: str, role: str = "client") -> list[BaseTool]:
    """Build document tools bound to ONE authenticated user.

    Returns [] when there is no authenticated user — an unbound document tool
    must never exist.
    """
    if not user_id:
        return []

    from app.repositories.intake_repo import IntakeRepository

    intake_repo = IntakeRepository()

    async def _list_my_documents() -> list[dict]:
        try:
            sessions = await intake_repo.find_evidence_by_client(user_id)
        except Exception:
            # The exception is LOGGED, never returned. Interpolating it put the
            # driver's own message — which can quote a connection string, a
            # namespace or a document fragment — straight into text the model
            # sees and may repeat back to the client.
            logger.exception("list_my_documents failed")
            return [{"error": "Your documents could not be listed right now.",
                     "hint": "Do not claim to have read anything. Say the list "
                             "could not be retrieved."}]

        files: list[dict] = []
        for session in sessions:
            for meta in session.get("evidence_files", []):
                files.append({
                    "file_id":  meta.get("file_id"),
                    "filename": meta.get("filename"),
                    "size":     meta.get("size"),
                })
        if not files:
            return [{"error": "You have not uploaded any documents.",
                     "hint": "Do not claim to have read anything. Say no document was found."}]
        return files

    async def _read_document(file_id: str) -> dict:
        # Ownership is enforced by the query itself: only this user's sessions are
        # ever fetched, so a file_id belonging to anyone else simply is not found.
        try:
            sessions = await intake_repo.find_evidence_by_client(user_id)
        except Exception:
            logger.exception("read_document lookup failed")
            return {"error": "This document could not be opened right now.",
                    "hint": "Do not invent its contents. Say it could not be opened."}

        for session in sessions:
            for meta in session.get("evidence_files", []):
                if meta.get("file_id") == file_id:
                    result = await _read_file(meta.get("path", ""))
                    result["filename"] = meta.get("filename")
                    return result

        return {
            "error": f"No document with id '{file_id}' belongs to you.",
            "hint": "Call list_my_documents first to get valid file_ids. Never invent one.",
        }

    list_tool = StructuredTool.from_function(
        coroutine=_list_my_documents,
        name="list_my_documents",
        description=(
            "List the documents THIS user has uploaded (FIR scans, notices, contracts, "
            "agreements). Call this FIRST whenever the user refers to 'my document', "
            "'the FIR I uploaded', 'my contract', or asks you to look at a file. "
            "Returns file_id + filename for each. An empty result means they have "
            "uploaded nothing — say so; never pretend to have read a document."
        ),
    )

    read_tool = StructuredTool.from_function(
        coroutine=_read_document,
        name="read_document",
        description=(
            "Read the text of a document the user uploaded. Pass the `file_id` from "
            "list_my_documents — never guess one. "
            "Returns the extracted `text`. If it returns an `error` saying there is no "
            "readable text layer, the file is a scan or photo and CANNOT be read: tell "
            "the user that plainly and ask them to type the key details. Never invent "
            "the contents of a document you could not read."
        ),
    )

    return [list_tool, read_tool]
