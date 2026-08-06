"""
ingest_legal_uqa.py — Ingests the LEGAL-UQA dataset into constitutional_collection.

Dataset: https://huggingface.co/datasets/nlp-anonymous-researcher/LEGAL-UQA
  619 bilingual (English + Urdu) Pakistani constitutional law Q&A rows.

What this script does
---------------------
  1. Downloads LEGAL-UQA from HuggingFace (train + validation splits).
  2. Validates that expected columns are present — fails loudly if not.
  3. Deduplicates by context_index — unique articles only.
  4. Produces TWO chunk types per unique article:
       a) Context chunk  — the raw constitutional article text (eng + urdu)
       b) QA chunk       — question + answer pair as a retrieval target
  5. Embeds via E5Embeddings (same object the live pipeline uses).
     NOTE: E5Embeddings.embed_documents() adds "passage: " prefix internally.
     Do NOT add it again here — passing raw text is correct.
  6. Upserts into constitutional_collection (skips already-present chunk_ids).
  7. Prints a summary. Run build_law_graph.py afterwards to refresh the graph.

Usage
-----
  cd backend
  pip install datasets          # one-time
  python scripts/ingest_legal_uqa.py

Safe to re-run — upsert is idempotent (ChromaDB deduplicates on chunk_id).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

# ── Imports after path fix ────────────────────────────────────────────────────

try:
    from datasets import load_dataset
except ImportError:
    print("ERROR: 'datasets' package not installed.")
    print("       Run:  pip install datasets")
    sys.exit(1)

from app.db.chroma import connect_chroma, get_chroma
from app.ai.pipelines.retriever import _embeddings

# ── Config ────────────────────────────────────────────────────────────────────

DATASET_NAME = "nlp-anonymous-researcher/LEGAL-UQA"
COLLECTION   = "constitutional_collection"
STATUTE      = "Constitution of Pakistan 1973"
PROVINCE     = "federal"
LAW_TYPE     = "constitutional"
SOURCE_FILE  = "LEGAL-UQA"

# E5 multilingual-e5-base: 512 token limit.
# ~4 chars/token for English, ~1-2 chars/token for Urdu.
# 1800 chars is a safe budget that keeps meaningful content within token limit.
_MAX_CHARS = 1800

_EXPECTED_COLUMNS = {
    "context_index", "context_eng", "context_urdu",
    "question_eng", "question_urdu", "answer_eng", "answer_urdu",
}

# LEGAL-UQA context text opens with the article number itself — "25A. Equality
# of citizens ..." — and only rarely writes the word "Article". Matching solely
# on "Article N" therefore failed on almost every row, and the caller then fell
# back to the dataset ROW INDEX, which was stored as if it were an article
# number. That produced citations to articles that do not exist (the
# Constitution has 280; indices ran past 290) and, worse, plausible-but-wrong
# ones: row 27 carried the text of Article 25A.
_ARTICLE_LEADING_RE = re.compile(r'^\s*(\d{1,3}[A-Z]?)\s*[\.\)\:]')
_ARTICLE_NAMED_RE = re.compile(r'\bArticle\s+(\d{1,3}[A-Z]?)', re.IGNORECASE)


def _validate_columns(ds) -> None:
    """Fail loudly if dataset schema doesn't match expected columns."""
    for split_name in ("train", "validation"):
        if split_name not in ds:
            continue
        actual = set(ds[split_name].column_names)
        missing = _EXPECTED_COLUMNS - actual
        if missing:
            print(f"\nERROR: Dataset split '{split_name}' is missing columns: {missing}")
            print(f"       Actual columns: {sorted(actual)}")
            print("\n       Update _EXPECTED_COLUMNS and the row.get() calls below")
            print("       to match the real column names.")
            sys.exit(1)
    print("  Column validation passed.")


def _extract_article(text: str) -> str:
    """Article number from the text, or "" when it cannot be determined.

    Returning "" is deliberate. The caller must NOT substitute a row index: an
    empty section number is honest, while a wrong article number is a false
    citation that reads as authoritative.
    """
    text = (text or "").strip()
    m = _ARTICLE_LEADING_RE.match(text) or _ARTICLE_NAMED_RE.search(text)
    if not m:
        return ""
    num = m.group(1)
    # The Constitution of Pakistan runs to 280 articles; anything beyond that is
    # a misparse, not an article.
    digits = int(re.sub(r"[A-Z]", "", num) or 0)
    return num if 1 <= digits <= 280 else ""


def _build_context_chunk(ctx_eng: str, ctx_urdu: str, ctx_index: int) -> dict:
    article  = _extract_article(ctx_eng)   # "" when unknown — never the row index
    chunk_id = f"legal_uqa_ctx_{ctx_index}"
    content  = ctx_eng.strip()
    if ctx_urdu and ctx_urdu.strip():
        content = f"{content}\n\n{ctx_urdu.strip()}"
    # Truncate to safe token budget — tokenizer handles the rest
    content = content[:_MAX_CHARS]
    return {
        "chunk_id":       chunk_id,
        "content":        content,
        "statute":        STATUTE,
        "section_number": article,
        "source_file":    SOURCE_FILE,
        "province":       PROVINCE,
        "law_type":       LAW_TYPE,
    }


def _build_qa_chunk(q_eng: str, a_eng: str, q_urdu: str, a_urdu: str,
                    ctx_index: int, row_index: int,
                    context_article: str = "") -> dict:
    chunk_id = f"legal_uqa_qa_{row_index}"
    content  = f"Q: {q_eng.strip()}\nA: {a_eng.strip()}"
    if q_urdu and a_urdu:
        content += f"\n\nسوال: {q_urdu.strip()}\nجواب: {a_urdu.strip()}"
    content = content[:_MAX_CHARS]
    # A QA pair is ABOUT the article it was generated from, but the answer is
    # prose and rarely states the number. Inherit it from the context chunk,
    # which is derivable — that is real information we hold, unlike the row
    # index the previous version substituted.
    article = _extract_article(a_eng) or context_article
    return {
        "chunk_id":       chunk_id,
        "content":        content,
        "statute":        STATUTE,
        "section_number": article,
        "source_file":    SOURCE_FILE,
        "province":       PROVINCE,
        "law_type":       LAW_TYPE,
    }


def ingest() -> None:
    # ── 1. Load dataset ───────────────────────────────────────────────────────
    print(f"Loading {DATASET_NAME} …")
    ds = load_dataset(DATASET_NAME)

    # ── 2. Validate columns before touching any data ──────────────────────────
    _validate_columns(ds)

    all_rows: list[dict] = []
    for split in ("train", "validation"):
        if split in ds:
            all_rows.extend(ds[split])
    print(f"  {len(all_rows)} total rows across all splits")

    # ── 3. Build chunks ───────────────────────────────────────────────────────
    seen_contexts: set[int] = set()
    context_chunks: list[dict] = []
    qa_chunks:      list[dict] = []
    skipped = 0

    for i, row in enumerate(all_rows):
        ctx_idx  = int(row.get("context_index", i))
        ctx_eng  = (row.get("context_eng")  or "").strip()
        ctx_urdu = (row.get("context_urdu") or "").strip()
        q_eng    = (row.get("question_eng") or "").strip()
        q_urdu   = (row.get("question_urdu") or "").strip()
        a_eng    = (row.get("answer_eng")   or "").strip()
        a_urdu   = (row.get("answer_urdu")  or "").strip()

        # Context chunk — one per unique article
        if ctx_idx not in seen_contexts:
            if ctx_eng:
                context_chunks.append(_build_context_chunk(ctx_eng, ctx_urdu, ctx_idx))
                seen_contexts.add(ctx_idx)
            else:
                skipped += 1

        # The article this row's context belongs to, so the QA pair can inherit
        # it rather than being left unlabelled.
        context_article = _extract_article(ctx_eng)

        # QA chunk — one per row
        if q_eng and a_eng:
            qa_chunks.append(_build_qa_chunk(q_eng, a_eng, q_urdu, a_urdu,
                                             ctx_idx, i, context_article))

    all_chunks = context_chunks + qa_chunks
    print(f"  {len(context_chunks)} unique context chunks")
    print(f"  {len(qa_chunks)} Q&A chunks")
    if skipped:
        print(f"  {skipped} rows skipped (empty context_eng)")
    print(f"  {len(all_chunks)} total chunks to upsert")

    if not all_chunks:
        print("Nothing to ingest — exiting.")
        return

    # ── 4. Connect to ChromaDB ────────────────────────────────────────────────
    print(f"\nConnecting to ChromaDB -> {COLLECTION} ...")
    connect_chroma()
    chroma     = get_chroma()
    collection = chroma.get_or_create_collection(
        name=COLLECTION,
        metadata={"hnsw:space": "cosine"},
    )
    existing = set(collection.get(include=[])["ids"])
    print(f"  Existing chunks in collection: {len(existing)}")

    # ── 5. Filter already-present chunks (idempotent) ────────────────────────
    new_chunks = [c for c in all_chunks if c["chunk_id"] not in existing]
    print(f"  New chunks to embed: {len(new_chunks)}")
    if not new_chunks:
        print("All chunks already present — nothing to do.")
        return

    # ── 6. Embed with the pipeline's E5 model ────────────────────────────────
    # IMPORTANT: E5Embeddings.embed_documents() adds "passage: " prefix
    # internally (retriever.py). Pass raw text — do NOT add the prefix here.
    print("\nEmbedding with multilingual-e5-base (this may take a few minutes) …")
    emb_model = _embeddings()
    texts     = [c["content"] for c in new_chunks]
    vectors   = emb_model.embed_documents(texts)
    print(f"  Embedded {len(vectors)} chunks")

    # ── 7. Upsert into ChromaDB in batches ───────────────────────────────────
    BATCH = 100
    print(f"\nUpserting in batches of {BATCH} …")
    total_upserted = 0

    for start in range(0, len(new_chunks), BATCH):
        batch = new_chunks[start : start + BATCH]
        vecs  = vectors[start : start + BATCH]

        collection.upsert(
            ids        = [c["chunk_id"] for c in batch],
            embeddings = vecs,
            documents  = [c["content"] for c in batch],
            metadatas  = [
                {
                    "statute":        c["statute"],
                    "section_number": c["section_number"],
                    "source_file":    c["source_file"],
                    "province":       c["province"],
                    "law_type":       c["law_type"],
                    "chunk_id":       c["chunk_id"],
                }
                for c in batch
            ],
        )
        total_upserted += len(batch)
        print(f"  Upserted {total_upserted}/{len(new_chunks)}", end="\r")

    print(f"\n\nDone — {total_upserted} chunks added to '{COLLECTION}'.")
    print("\nNext step: rebuild the law graph to include new cross-references:")
    print("  python scripts/build_law_graph.py")


if __name__ == "__main__":
    ingest()
