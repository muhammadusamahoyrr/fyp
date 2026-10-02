"""Build the Document Analyzer's authority library from OFFICIAL sources.

Writes app/services/analyzer/authorities/library.yaml: the exact text of
every provision a legal playbook cites, cut from the official publication,
with where it came from (URL, SHA-256 of the file, pages, retrieval date).

WHY A SEPARATE LIBRARY, NOT THE CHAT CORPUS
  The Chroma corpus labels chunks by guessed section numbers, and the labels
  are not reliable (Transfer of Property Act s.107: the only chunk labelled
  "107" is a footnote). A citation shown to a lawyer must resolve to the
  provision itself, so this library is cut by EXPLICIT start and end headings
  and checked, not guessed.

PINNED SOURCES
  Each source's SHA-256 is pinned below. If the official file changes (an
  amendment, a re-upload), the build REFUSES: a person must read the new text,
  update the pin and rebuild -- and every approval bound to the old text stops
  counting (approvals bind the cited provisions' hashes).

TEXT
  Extracted with pdfplumber from the PDF text layer. Two characters the
  publishers' text layer uses as look-alikes are normalised (U+037E GREEK
  QUESTION MARK -> ';', U+2011 NON-BREAKING HYPHEN -> '-'); "Page N of M"
  footer lines are dropped. Footnote numbers stay where the text layer puts
  them, e.g. "2107. Leases how made" is footnote 2 followed by "107.".
  Nothing else is changed.

AUTHORITY METADATA
  Every source here is `official` (only the publishers in
  authorities.OFFICIAL_HOSTS may claim it); `amended_up_to` is null because
  none of these files states the amendment date it reflects. COVERAGE lists,
  per document type, the statutes held and the known gaps, some of which
  are release blockers (see authorities.release_blockers).

CURRENCY
  --currency re-fetches each official file, compares it with its pin and
  writes app/services/analyzer/authority_currency.yaml (status, date, the
  pin checked). It never changes the library: a changed file is reported
  as source_changed and the build itself keeps refusing until a person
  reads the new text and moves the pin.

Usage:
  python scripts/build_analyzer_authorities.py              # download, verify, write
  python scripts/build_analyzer_authorities.py --dir DIR    # use files already in DIR
  python scripts/build_analyzer_authorities.py --check      # verify only; exit 1 on drift
  python scripts/build_analyzer_authorities.py --currency   # re-fetch, record currency
"""
from __future__ import annotations

import argparse
import functools
import hashlib
import re
import sys
import tempfile
from pathlib import Path

import httpx
import pdfplumber
import yaml

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.services.analyzer import authorities  # noqa: E402
from app.services.analyzer.authorities import LIBRARY_PATH, dump_library  # noqa: E402

RETRIEVED = "2026-10-01"

SOURCES = {
    "punjab_rented_premises_act_2009": {
        "statute": "Punjab Rented Premises Act 2009",
        "jurisdiction": "punjab",
        "publisher": "Punjab Code, Government of the Punjab",
        "url": "https://punjabcode.punjab.gov.pk/uploads/articles/THE_PUNJAB_RENTED_PREMISES_ACT_2009.doc.pdf",
        "listing_url": "https://punjabcode.punjab.gov.pk/en/show_article/VGEFMQQzVm8-",
        "sha256": "dc8e42971dfd2bd770c08f80b2b079ccaa6db54079a7b45adc40ee64cfc26962",
    },
    "registration_act_1908": {
        "statute": "Registration Act 1908",
        "jurisdiction": "federal",
        "publisher": "Pakistan Code, Ministry of Law and Justice",
        "url": "https://pakistancode.gov.pk/pdffiles/administrator0f29bc9f1e3dfed37c0034eed1e29d53.pdf",
        "listing_url": None,
        "sha256": "b9f6a700e43ad5824252330b41abd675690035b2347da61978f08d486fa40674",
    },
    "transfer_of_property_act_1882": {
        "statute": "Transfer of Property Act 1882",
        "jurisdiction": "federal",
        "publisher": "Pakistan Code, Ministry of Law and Justice",
        "url": "https://pakistancode.gov.pk/pdffiles/administrator77923ce792b475e339e1f46ba0442da3.pdf",
        "listing_url": None,
        "sha256": "d75669bc902f55b55b0bde6f5ddc1002bb891a834d89a2d56b840462a8449185",
    },
    "contract_act_1872": {
        "statute": "Contract Act 1872",
        "jurisdiction": "federal",
        "publisher": "Pakistan Code, Ministry of Law and Justice",
        "url": "https://pakistancode.gov.pk/pdffiles/administrator8332a6df32386960ac7d81a5cf7aade2.pdf",
        "listing_url": None,
        "sha256": "930c60f67216530fab28f37d439ad3c3ae941dc918c914f2e7c18ddbabb7bfbd",
    },
}

# What the library holds per document type, and what it does not. A gap that
# is a release blocker keeps the legal layer for that type unreleased.
COVERAGE = {
    "tenancy": {
        "statutes": ["Punjab Rented Premises Act 2009", "Registration Act 1908",
                     "Transfer of Property Act 1882"],
        "gaps": [
            {"id": "tenancy.punjab_only",
             "text": "Only Punjab's rent law is held; tenancies in other provinces or "
                     "Islamabad are not covered.",
             "release_blocker": False},
            {"id": "tenancy.partial_sections",
             "text": "Only sections 5-7 of the Punjab Rented Premises Act 2009, section 17(1) of "
                     "the Registration Act 1908 and sections 1 and 107 of the Transfer of Property "
                     "Act 1882 are held.",
             "release_blocker": False},
            {"id": "tenancy.stamp_duty",
             "text": "Stamp duty (Stamp Act 1899 and the Punjab finance laws) is not held.",
             "release_blocker": False},
        ],
    },
    "nda": {
        "statutes": ["Contract Act 1872"],
        "gaps": [
            {"id": "nda.general_contract_law_only",
             "text": "Only sections 27 and 28 of the Contract Act 1872 are held; no statute "
                     "specific to confidential information is.",
             "release_blocker": False},
        ],
    },
    "employment": {
        "statutes": ["Contract Act 1872"],
        "gaps": [
            {"id": "employment.no_employment_statute",
             "text": "No employment statute's text is held (federal or provincial labour and "
                     "standing-orders law); only Contract Act 1872 sections 27 and 28. "
                     "Employment legal provisions must be added by a lawyer.",
             "release_blocker": True},
        ],
    },
    "all": {
        "statutes": [],
        "gaps": [
            {"id": "all.amendment_date_unknown",
             "text": "No source states the date it is amended up to; whether later amendments "
                     "exist is decided only by the lawyer who approves each pack.",
             "release_blocker": False},
        ],
    },
}

# (source, section, heading, start marker, end marker, first page to search)
# The first page skips each Act's table of contents, which repeats headings.
PROVISIONS = [
    ("punjab_rented_premises_act_2009", "5", "Agreement between landlord and tenant",
     "5. Agreement between landlord and tenant", "6. Contents of tenancy agreement", 2),
    ("punjab_rented_premises_act_2009", "6", "Contents of tenancy agreement",
     "6. Contents of tenancy agreement", "7. Payment of rent", 2),
    ("punjab_rented_premises_act_2009", "7", "Payment of rent",
     "7. Payment of rent", "8. Existing tenancy", 2),
    ("registration_act_1908", "17(1)", "Documents of which registration is compulsory",
     "17. Documents of which registration is compulsory", "(2) Nothing in clauses (b) and (c)", 3),
    ("transfer_of_property_act_1882", "1", "Short title, commencement and extent",
     "1. Short title.", "2. Repeal of Acts.", 3),
    ("transfer_of_property_act_1882", "107", "Leases how made",
     "107. Leases how made", "108. Rights and liabilities of lessor and lessee", 10),
    ("contract_act_1872", "27", "Agreement in restraint of trade void",
     "27. Agreement in restraint of trade void", "28. Agreements in restraint of legal proceedings", 3),
    ("contract_act_1872", "28", "Agreements in restraint of legal proceedings void",
     "28. Agreements in restraint of legal proceedings void", "29. Agreements void for uncertainty", 3),
]

_FOOTER = re.compile(r"^Page \d+ of \d+$")
_LOOKALIKES = {";": ";", "‑": "-"}


def normalise(text: str) -> str:
    for bad, good in _LOOKALIKES.items():
        text = text.replace(bad, good)
    lines = [line.rstrip() for line in text.replace("\r\n", "\n").split("\n")]
    return "\n".join(line for line in lines if not _FOOTER.match(line.strip())).strip()


def fetch(source_id: str, directory: Path) -> Path:
    path = directory / f"{source_id}.pdf"
    if not path.exists():
        response = httpx.get(SOURCES[source_id]["url"], timeout=120, follow_redirects=True,
                             headers={"User-Agent": "Mozilla/5.0 (attorney-ai authority builder)"})
        response.raise_for_status()
        path.write_bytes(response.content)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != SOURCES[source_id]["sha256"]:
        raise SystemExit(f"REFUSED {source_id}: the official file changed "
                         f"(pinned {SOURCES[source_id]['sha256'][:12]}, got {digest[:12]}). "
                         "Read the new text, update the pin, rebuild.")
    return path


@functools.lru_cache(maxsize=None)
def page_texts(pdf: Path) -> tuple[tuple[int, str], ...]:
    with pdfplumber.open(pdf) as doc:
        return tuple((n, doc.pages[n - 1].extract_text() or "") for n in range(1, len(doc.pages) + 1))


def cut(pdf: Path, start: str, end: str, first_page: int) -> tuple[str, list[int]]:
    pages = page_texts(pdf)
    joined, offsets = "", []
    for n, text in pages[first_page - 1:]:
        offsets.append((len(joined), n))
        joined += text + "\n"
    i = joined.find(start)
    if i < 0:
        raise SystemExit(f"start marker not found: {start!r}")
    j = joined.find(end, i + len(start))
    if j < 0:
        raise SystemExit(f"end marker not found: {end!r}")
    spanned = [n for k, (off, n) in enumerate(offsets)
               if off < j and (k + 1 == len(offsets) or offsets[k + 1][0] > i)]
    return normalise(joined[i:j]), spanned


def build(directory: Path) -> dict:
    sources = {sid: {**meta, "retrieved": RETRIEVED, "authority_status": authorities.OFFICIAL,
                     "amended_up_to": None} for sid, meta in SOURCES.items()}
    provisions = []
    for sid, section, heading, start, end, first_page in PROVISIONS:
        text, pages = cut(fetch(sid, directory), start, end, first_page)
        if "�" in text:
            raise SystemExit(f"{sid} s.{section}: unreadable characters in the text layer")
        provisions.append({
            "statute": SOURCES[sid]["statute"], "section": section, "heading": heading,
            "source": sid, "pages": pages, "text": text,
            "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()})
    return {"version": 1, "sources": sources, "coverage": COVERAGE, "provisions": provisions}


def currency(today: str) -> dict:
    """Re-fetch every official file and compare it with its pin. Writes nothing
    into the library; a changed or unreachable file is recorded as such."""
    out = {}
    for sid, meta in SOURCES.items():
        entry = {"pinned_sha256": meta["sha256"], "last_checked": today}
        try:
            response = httpx.get(meta["url"], timeout=120, follow_redirects=True,
                                 headers={"User-Agent": "Mozilla/5.0 (attorney-ai authority builder)"})
            response.raise_for_status()
        except httpx.HTTPError as exc:
            out[sid] = {**entry, "status": authorities.CHECK_FAILED, "observed_sha256": None,
                        "error": type(exc).__name__}
            continue
        observed = hashlib.sha256(response.content).hexdigest()
        out[sid] = {**entry, "observed_sha256": observed,
                    "status": authorities.SOURCE_UNCHANGED if observed == meta["sha256"]
                    else authorities.SOURCE_CHANGED}
    return {"version": 1, "sources": out}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dir", type=Path, help="directory holding (or receiving) the source PDFs")
    parser.add_argument("--check", action="store_true", help="verify the committed library; write nothing")
    parser.add_argument("--currency", action="store_true",
                        help="re-fetch the official files and record their currency")
    args = parser.parse_args()
    if args.currency:
        import datetime

        result = currency(datetime.date.today().isoformat())
        rendered = ("# Currency of the authority library's official sources -- GENERATED by\n"
                    "# scripts/build_analyzer_authorities.py --currency. See authorities.py.\n"
                    + yaml.safe_dump(result, sort_keys=True))
        authorities.parse_currency(rendered, authorities.load_library())   # never write the unreadable
        authorities.CURRENCY_PATH.write_text(rendered, encoding="utf-8", newline="\n")
        for sid, entry in result["sources"].items():
            print(f"{sid}: {entry['status']}")
        return
    directory = args.dir or Path(tempfile.mkdtemp(prefix="analyzer-authorities-"))
    directory.mkdir(parents=True, exist_ok=True)
    rendered = dump_library(build(directory))
    if args.check:
        current = LIBRARY_PATH.read_text(encoding="utf-8").replace("\r\n", "\n")
        if current != rendered:
            raise SystemExit("DRIFT: library.yaml differs from what the official sources produce")
        print("library.yaml matches the official sources")
        return
    LIBRARY_PATH.write_text(rendered, encoding="utf-8", newline="\n")
    print(f"wrote {LIBRARY_PATH} ({len(yaml.safe_load(rendered)['provisions'])} provisions)")


if __name__ == "__main__":
    main()
