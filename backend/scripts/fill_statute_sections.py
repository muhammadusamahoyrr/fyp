"""fill_statute_sections.py — add individually missing statute sections.

WHAT THIS IS NOT
----------------
Not a merge. The heyIamUmair CSVs cover statutes we already hold in full, so
importing them wholesale would re-ingest ~1,400 rows to add almost nothing, and
would overwrite section text we already have with a differently-parsed copy of
the same law. This script writes ONLY sections the corpus does not hold at all,
and never touches an existing chunk.

WHY SO LITTLE IS ACTUALLY MISSING
----------------------------------
Measured against the corpus, per source file:

    Pakistan_Penal_Code.csv        498 sections   0 missing
    qanun-e-shahadat_1984.csv      165 sections   0 missing
    Transfer_property.csv          124 sections   0 missing
    2-limitation-act-1908.csv       28 sections   0 missing
    Muslim_Family_Laws_1961.csv     11 sections   0 missing
    Police_law.csv                 178 sections   0 missing
    Code_of_Criminal_Procedure     337 sections   8 missing

Police_law.csv looks like a 178-section gap only until the name is normalised:
its Book is "Police Law", ours is "Police Order, 2002", and every one of its
sections is already held. That is a naming artefact, not a gap.

SCHEDULE ROWS ARE REJECTED, AND THIS IS THE POINT OF THE SCRIPT
----------------------------------------------------------------
Six of the eight CrPC "missing sections" are not sections. They are numbered
FORMS from Schedule V, which the CSV records with the form number in the
`Section` column:

    Ch XXXV  SCHEDULE V  Sec 23  "Warrant of Attachment in the Case of a Dispute"
    Ch XXXV  SCHEDULE V  Sec 26  "Bond to prosecute or give Evidence"

Ingested as written, those become CrPC s.23 and s.26 — colliding with the real
sections of those numbers and teaching the retriever that s.26 is a bond form.
A bulk merge would have imported all six silently. Any row whose chapter is a
schedule is therefore refused, and the refusal is reported rather than hidden.

WHAT ACTUALLY GETS ADDED
-------------------------
Two real sections, both lettered, both in real chapters:

    CrPC 265-A  Ch XXII-A  Trials before Court of Session ... Public Prosecutor
    CrPC 516-A  Ch XLIII   Order for custody and disposal of property pending trial

Lettered sections are the corpus's known weak spot — a citation to one that is
not held resolves UNVERIFIABLE — so these two are worth the write on their own.

Note for the record: this does NOT close the gap that motivated the exercise.
PPC 489-F (dishonoured cheque) is absent from the corpus AND absent from every
CSV in this dataset, as are 489-A, 302-B and CrPC 544-A. This source cannot
supply them.

Usage
-----
  python scripts/fill_statute_sections.py --csv-dir DIR           # dry run
  python scripts/fill_statute_sections.py --csv-dir DIR --apply
"""
from __future__ import annotations

import argparse
import collections
import csv
import hashlib
import re
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.ai.answer_citations import normalise_statute  # noqa: E402
from app.ai.corpus_index import (  # noqa: E402
    canonical_section,
    is_lettered,
    section_key,
)
from app.ai.pipelines.retriever import CASE_TYPE_TO_COLLECTION  # noqa: E402
from app.db.chroma import connect_chroma, get_chroma  # noqa: E402

csv.field_size_limit(10 ** 7)

# Normalised book name -> (collection, statute label, law_type) matching what
# the corpus already stores, so a filled section is indistinguishable in
# metadata from an originally-ingested one.
TARGETS: dict[str, tuple[str, str, str]] = {
    "CRPC": ("criminal_collection", "CrPC 1898", "criminal"),
    "PPC": ("criminal_collection", "PPC 1860", "criminal"),
    "QSO": ("criminal_collection", "Qanun-e-Shahadat Order, 1984", "criminal"),
    "TRANSFER OF PROPERTY ACT": ("civil_collection",
                                 "Transfer of Property Act, 1882", "civil"),
    "LIMITATION ACT": ("civil_collection", "Limitation Act, 1908", "civil"),
    "MFLO": ("family_collection", "Muslim Family Laws Ordinance, 1961", "family"),
    # The CSV calls it "Police Law"; the corpus holds it as the Police Order,
    # 2002. Mapping it here means its sections are really checked rather than
    # skipped as an unknown book — which is what made it look like a 178-section
    # gap in the first place.
    "POLICE LAW": ("criminal_collection", "Police Order, 2002", "criminal"),
}

# A row from a schedule carries a FORM number, not a section number.
_SCHEDULE = re.compile(r"(?i)\bschedule\b")
# Below this the row is a stub heading, not the text of a provision.
_MIN_CHARS = 120


def held_sections() -> dict[str, set[str]]:
    client = get_chroma()
    held: dict[str, set[str]] = collections.defaultdict(set)
    for collection in set(CASE_TYPE_TO_COLLECTION.values()):
        try:
            got = client.get_collection(collection).get(include=["metadatas"])
        except Exception:
            continue
        for meta in got["metadatas"]:
            meta = meta or {}
            statute = (meta.get("statute") or "").strip()
            section = str(meta.get("section_number") or "").strip()
            if statute and section:
                held[normalise_statute(statute)].add(canonical_section(section))
    return held


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", errors="replace", newline="") as fh:
        return list(csv.DictReader(fh))


def body_of(row: dict) -> str:
    """Section text as "N. Heading  Body" — the shape existing chunks use."""
    heading = " ".join((row.get("Heading") or "").split())
    text = " ".join((row.get("Defination") or "").split())
    section = (row.get("Section") or "").strip()
    return f"{section}. {heading}  {text}".strip()


def main(args) -> int:
    connect_chroma()
    held = held_sections()

    files = sorted(Path(args.csv_dir).glob("*.csv"))
    if not files:
        raise SystemExit(f"no CSVs under {args.csv_dir}")

    plan: list[tuple[str, str, str, str, str]] = []   # coll, statute, law, sec, body
    rejected = collections.Counter()
    rejected_detail: list[str] = []
    per_file: list[tuple[str, str, int, int, int]] = []

    for path in files:
        rows = read_csv(path)
        if not rows:
            continue
        book = normalise_statute((rows[0].get("Book") or "").strip())
        target = TARGETS.get(book)
        if target is None:
            rejected["book_not_mapped"] += len(rows)
            rejected_detail.append(f"{path.name}: book {book!r} not in TARGETS")
            per_file.append((path.name, book, len(rows), 0, 0))
            continue

        collection, statute, law_type = target
        # Keyed on the corpus label: the CSV's own book name may differ.
        have = held.get(normalise_statute(statute), set())
        n_missing = n_added = 0
        for row in rows:
            raw = (row.get("Section") or "").strip()
            if not raw:
                continue
            section = canonical_section(raw)
            if section in have:
                continue
            n_missing += 1
            if _SCHEDULE.search(row.get("Chapter Title") or ""):
                rejected["schedule_form_not_a_section"] += 1
                rejected_detail.append(
                    f"{book} {section}: chapter "
                    f"{(row.get('Chapter Title') or '').strip()[:28]!r} — "
                    f"{(row.get('Heading') or '')[:44]!r}")
                continue
            body = body_of(row)
            if len(body) < _MIN_CHARS:
                rejected["too_short"] += 1
                continue
            plan.append((collection, statute, law_type, section, body))
            n_added += 1
        per_file.append((path.name, book, len(rows), n_missing, n_added))

    print("\n  per source file: rows | not held | fillable")
    for name, book, n, miss, add in per_file:
        print(f"    {name[:46]:46s} {book[:22]:22s} {n:5d} {miss:6d} {add:6d}")

    print(f"\n  rejected:")
    for reason, n in rejected.most_common():
        print(f"    {reason:34s} {n}")
    for line in rejected_detail[:10]:
        if "not in TARGETS" not in line:
            print(f"      {line}")

    print(f"\n  to write: {len(plan)}")
    for collection, statute, _law, section, body in plan:
        print(f"    {statute} s.{section}{'  (lettered)' if is_lettered(section) else ''}"
              f"  -> {collection}  {len(body)} chars")
        print(f"        {body[:110]}")

    if not plan:
        print("\n  Nothing to fill.\n")
        return 0
    if not args.apply:
        print("\n  Dry run — nothing written. Re-run with --apply.\n")
        return 0

    from app.ai.pipelines.retriever import _embeddings
    embeddings = _embeddings()
    client = get_chroma()
    written = 0
    for collection, statute, law_type, section, body in plan:
        # The corpus stores lettered sections COMPACTLY — "365B", "18A", not
        # "365-B". CorpusIndex.has() matches raw-or-compact, so a hyphenated
        # value resolves for "265-A" but not for "265A" or "265 A", i.e. the
        # filled section would verify for one spelling of a citation and come
        # back UNVERIFIABLE for the other two. Store what the corpus stores.
        stored_section = section_key(section)
        slug = re.sub(r"[^a-z0-9]+", "_", statute.lower()).strip("_")
        sec_slug = re.sub(r"[^a-z0-9]+", "_", stored_section.lower())
        chunk_id = f"statutes_{slug}_fill_{sec_slug}"
        client.get_collection(collection).upsert(
            ids=[chunk_id],
            embeddings=embeddings.embed_documents([body]),
            documents=[body],
            metadatas=[{
                "chunk_id": chunk_id,
                "statute": statute,
                "section_number": stored_section,
                "law_type": law_type,
                "province": "federal",
                "content_sha": hashlib.sha256(body.encode()).hexdigest()[:12],
                # Provenance differs from the originals on purpose: a filled
                # section should be traceable to the dataset it came from.
                "source_file": "heyIamUmair/pakistani-law-family-criminal-property",
            }],
        )
        written += 1
        print(f"    wrote {chunk_id}")

    after = held_sections()
    print(f"\n  sections written: {written}")
    for book in {normalise_statute(st) for _, st, _, _, _ in plan}:
        print(f"  {book}: {len(held.get(book, set()))} -> {len(after.get(book, set()))}")
    print()
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Fill individually missing statute sections.")
    p.add_argument("--csv-dir", required=True, help="directory of the source CSVs")
    p.add_argument("--apply", action="store_true", help="write the sections")
    raise SystemExit(main(p.parse_args()))
