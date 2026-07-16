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

import asyncio
import logging
from pathlib import Path

from langchain_core.tools import BaseTool, StructuredTool

logger = logging.getLogger(__name__)

# Chars of extracted text handed back to the model. A 40-page contract would
# otherwise blow the context budget in a single tool call.
_MAX_CHARS = 12_000


def _extract_text_sync(path: Path) -> str:
    """Extract text from a PDF, DOCX or plain-text file. Blocking — call in a thread."""
    suffix = path.suffix.lower()

    if suffix == ".pdf":
        from pypdf import PdfReader
        reader = PdfReader(str(path))
        return "\n".join(page.extract_text() or "" for page in reader.pages)

    if suffix == ".docx":
        import docx
        return "\n".join(p.text for p in docx.Document(str(path)).paragraphs)

    if suffix in (".txt", ".md"):
        return path.read_text(encoding="utf-8", errors="replace")

    raise ValueError(f"unsupported file type '{suffix}'")


async def _read_file(path_str: str) -> dict:
    path = Path(path_str)
    if not path.exists():
        return {"error": "The file is recorded but missing from storage."}

    try:
        text = await asyncio.to_thread(_extract_text_sync, path)
    except ValueError as exc:
        return {"error": str(exc)}
    except Exception as exc:
        logger.exception("text extraction failed for %s", path)
        return {"error": f"Could not read the file: {exc}"}

    stripped = text.strip()
    if not stripped:
        # Overwhelmingly a phone photo of an FIR, or a scanned PDF with no text
        # layer. There is no OCR in the stack, so say so rather than returning ""
        # and letting the model narrate an empty document.
        return {
            "error": "This file has no readable text layer — it is most likely a scan or photo.",
            "hint": "Ask the user to type the key details, or to upload a text-based PDF.",
        }

    truncated = len(stripped) > _MAX_CHARS
    return {
        "text": stripped[:_MAX_CHARS],
        "chars": len(stripped),
        "truncated": truncated,
        **({"note": f"Only the first {_MAX_CHARS} characters are shown."} if truncated else {}),
    }


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
        except Exception as exc:
            logger.exception("list_my_documents failed")
            return [{"error": f"Could not list your documents: {exc}"}]

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
        except Exception as exc:
            logger.exception("read_document lookup failed")
            return {"error": f"Could not open the document: {exc}"}

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
