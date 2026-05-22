"""
ingest_pakistan_laws.py — Ingests AyeshaJadoon/Pakistan_Laws_Dataset into ChromaDB.

Dataset: https://huggingface.co/datasets/AyeshaJadoon/Pakistan_Laws_Dataset
  967 Pakistani law documents — criminal, civil, family, constitutional, statutes.
  Stored as a single pdf_data.json file with keys: file_name, text.

What this script does
---------------------
  1. Downloads pdf_data.json from HuggingFace via hf_hub_download.
  2. Validates expected keys are present (file_name, text).
  3. Classifies each law into a collection by keyword-matching file_name.
  4. Chunks each law with section-aware splitting (same logic as the main pipeline).
  5. Embeds via E5Embeddings (multilingual-e5-base) — "passage:" prefix added internally.
  6. Upserts into the appropriate ChromaDB collection — idempotent on chunk_id.
  7. Prints a summary per collection.

Collections targeted:
  criminal_collection       — penal code, criminal procedure, terrorism, narcotics …
  family_collection         — family, marriage, divorce, guardianship, maintenance …
  constitutional_collection — constitution, amendments …
  civil_collection          — everything else (default)

Usage
-----
  cd backend
  python scripts/ingest_pakistan_laws.py

Safe to re-run — chunk_ids are deterministic so re-runs skip already-present chunks.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

try:
    from huggingface_hub import hf_hub_download
except ImportError:
    print("ERROR: 'huggingface_hub' package not installed.")
    print("       Run:  pip install huggingface_hub")
    sys.exit(1)

from app.db.chroma import connect_chroma, get_chroma
from app.ai.pipelines.retriever import _embeddings

# ── Config ────────────────────────────────────────────────────────────────────

DATASET_NAME = "AyeshaJadoon/Pakistan_Laws_Dataset"
PROVINCE     = "federal"

CHUNK_SIZE = 800
CHUNK_OVER = 100

SECTION_RE = re.compile(
    r"(?m)^(?:Section|Sec\.|S\.)\s*(\d+[A-Z]?(?:\.\d+)?(?:\([a-z]\))?)[.\s]",
    re.IGNORECASE,
)

_SLUG_RE = re.compile(r"[^a-z0-9]+")

# Classification rules: (keywords, law_type, collection_name)
# Evaluated top-to-bottom; first match wins.
_RULES: list[tuple[list[str], str, str]] = [
    (
        ["constitution", "fundamental rights", "18th amendment", "19th amendment",
         "20th amendment", "21st amendment", "22nd amendment", "23rd amendment",
         "24th amendment", "25th amendment", "26th amendment", "27th amendment"],
        "constitutional",
        "constitutional_collection",
    ),
    (
        ["family", "marriage", "divorce", "guardianship", "custody", "nikah",
         "maintenance", "dower", "muslim personal law", "child marriage",
         "dissolution of muslim", "west pakistan family", "family court"],
        "family",
        "family_collection",
    ),
    (
        ["penal code", "criminal procedure", "anti-terrorism", "narcotics",
         "cybercrime", "peca", "hudood", "offences", "punishment for",
         "prevention of", "suppression of", "anti-money", "firearms",
         "explosive", "jail", "prison", "probation", "juvenile justice",
         "trafficking", "kidnapping", "qisas", "diyat"],
        "criminal",
        "criminal_collection",
    ),
]

_DEFAULT = ("civil", "civil_collection")


def _classify(file_name: str) -> tuple[str, str]:
    name = file_name.lower()
    for keywords, law_type, collection in _RULES:
        if any(kw in name for kw in keywords):
            return law_type, collection
    return _DEFAULT


def _slug(name: str) -> str:
    return _SLUG_RE.sub("_", name.lower()).strip("_")[:60]


def _split_sections(text: str) -> list[tuple[str | None, str]]:
    splits, last_end, last_sec = [], 0, None
    for m in SECTION_RE.finditer(text):
        if m.start() > last_end:
            splits.append((last_sec, text[last_end : m.start()].strip()))
        last_sec = m.group(1)
        last_end = m.start()
    splits.append((last_sec, text[last_end:].strip()))
    return [(s, t) for s, t in splits if t]


def _slide(text: str) -> list[str]:
    chunks, start = [], 0
    while start < len(text):
        chunks.append(text[start : start + CHUNK_SIZE])
        start += CHUNK_SIZE - CHUNK_OVER
    return chunks


def _make_chunks(content: str, statute: str, law_type: str, source_file: str) -> list[dict]:
    """Deterministic chunk_ids: pak_laws_{slug(source_file)}_{index:04d}"""
    slug = _slug(Path(source_file).stem)
    chunks = []
    i = 0
    for sec_num, block in _split_sections(content):
        parts = [block] if len(block) <= CHUNK_SIZE else _slide(block)
        for part in parts:
            chunks.append({
                "chunk_id":       f"pak_laws_{slug}_{i:04d}",
                "content":        part.strip(),
                "statute":        statute,
                "section_number": sec_num or "",
                "source_file":    source_file,
                "province":       PROVINCE,
                "law_type":       law_type,
            })
            i += 1
    return chunks


def ingest() -> None:
    # ── 1. Load dataset ───────────────────────────────────────────────────────
    print(f"Downloading {DATASET_NAME}/pdf_data.json …")
    json_path = hf_hub_download(DATASET_NAME, "pdf_data.json", repo_type="dataset")
    with open(json_path, "r", encoding="utf-8") as f:
        all_rows: list[dict] = json.load(f)
    print(f"  {len(all_rows)} laws loaded")

    # ── 2. Validate keys ──────────────────────────────────────────────────────
    if not all_rows:
        print("Dataset is empty — nothing to ingest.")
        return

    sample = all_rows[0]
    missing = {"file_name", "text"} - set(sample.keys())
    if missing:
        print(f"\nERROR: Dataset is missing expected keys: {missing}")
        print(f"       Actual keys: {sorted(sample.keys())}")
        print("       Update the key names in this script to match.")
        sys.exit(1)
    print("  Key validation passed.")

    # ── 3. Build chunks, classified per collection ────────────────────────────
    collection_chunks: dict[str, list[dict]] = {
        "constitutional_collection": [],
        "family_collection":         [],
        "criminal_collection":       [],
        "civil_collection":          [],
    }
    law_counts: dict[str, int] = {k: 0 for k in collection_chunks}
    skipped = 0

    for row in all_rows:
        file_name = (row.get("file_name") or "").strip()
        content   = (row.get("text")      or "").strip()

        if not content:
            skipped += 1
            continue

        statute             = Path(file_name).stem or file_name
        law_type, col_name  = _classify(file_name)
        chunks              = _make_chunks(content, statute, law_type, file_name)
        collection_chunks[col_name].extend(chunks)
        law_counts[col_name] += 1

    print("\n  Classification summary:")
    for col_name in collection_chunks:
        n_laws   = law_counts[col_name]
        n_chunks = len(collection_chunks[col_name])
        print(f"    {col_name:<30} {n_laws:>4} laws  ->  {n_chunks:>6} chunks")
    total_chunks = sum(len(v) for v in collection_chunks.values())
    print(f"    {'TOTAL':<30} {sum(law_counts.values()):>4} laws  ->  {total_chunks:>6} chunks")
    if skipped:
        print(f"  {skipped} rows skipped (empty content)")

    # ── 4. Connect to ChromaDB ────────────────────────────────────────────────
    print("\nConnecting to ChromaDB …")
    connect_chroma()
    chroma    = get_chroma()
    emb_model = _embeddings()

    EMBED_BATCH = 500   # embed this many chunks at once — shows progress
    UPSERT_BATCH = 100  # upsert batch size for ChromaDB
    grand_total = 0

    # ── 5-6. Embed + upsert per collection ────────────────────────────────────
    for col_name, chunks in collection_chunks.items():
        if not chunks:
            print(f"\n[{col_name}] No chunks — skipping.")
            continue

        collection = chroma.get_or_create_collection(
            name=col_name,
            metadata={"hnsw:space": "cosine"},
        )
        existing   = set(collection.get(include=[])["ids"])
        new_chunks = [c for c in chunks if c["chunk_id"] not in existing]

        print(f"\n[{col_name}]")
        print(f"  Total chunks : {len(chunks)}")
        print(f"  Already in DB: {len(existing)}")
        print(f"  New to embed : {len(new_chunks)}")

        if not new_chunks:
            print("  All present — skipping.")
            continue

        embedded_so_far = 0
        for emb_start in range(0, len(new_chunks), EMBED_BATCH):
            emb_batch = new_chunks[emb_start : emb_start + EMBED_BATCH]
            texts     = [c["content"] for c in emb_batch]

            print(f"  Embedding chunks {emb_start + 1}-{emb_start + len(emb_batch)}/{len(new_chunks)} ...", flush=True)
            vectors = emb_model.embed_documents(texts)

            # upsert this embed batch in smaller sub-batches
            for u_start in range(0, len(emb_batch), UPSERT_BATCH):
                batch = emb_batch[u_start : u_start + UPSERT_BATCH]
                vecs  = vectors[u_start : u_start + UPSERT_BATCH]
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
            embedded_so_far += len(emb_batch)
            print(f"  Upserted {embedded_so_far}/{len(new_chunks)} chunks so far.", flush=True)

        print(f"  Done — {len(new_chunks)} chunks added to '{col_name}'.")
        grand_total += len(new_chunks)

    print(f"\n{'─'*55}")
    print(f"Total new chunks added across all collections: {grand_total}")
    print("\nNext step: rebuild the law graph to include new cross-references:")
    print("  python scripts/build_law_graph.py")


if __name__ == "__main__":
    ingest()
