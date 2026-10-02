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
  Extracted with pdfplumber from the PDF text layer, line by line. Two
  characters the publishers' text layer uses as look-alikes are normalised
  (U+037E GREEK QUESTION MARK -> ';', U+2011 NON-BREAKING HYPHEN -> '-');
  "Page N of M" footer lines are dropped. Footnote numbers stay where the
  text layer puts them, e.g. "2107. Leases how made" is footnote 2 followed
  by "107.". Nothing else is changed.

FOOTNOTES ARE NOTES, NOT TEXT
  The publishers set footnotes in a smaller type than the body. A line whose
  type is smaller than 0.8 x the page's body size is a footnote line; every
  other line is body. A provision is cut from BODY lines only, so a page's
  footnotes never land inside a section that runs across that page
  (Contract Act s.28 once carried s.27's footnote that way). Each footnote
  whose marker -- a small-type number in the provision's own lines -- appears
  in the provision is attached to it as a note {page, marker, text,
  marker_in_text: true}. A footnote that another provision's marker points
  to is not attached; one that NO marker on its page points to is attached
  to every provision on that page with marker_in_text: false, never dropped.

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
    # The Registration Act and the Transfer of Property Act are cut from the
    # PUNJAB Code, not Pakistan Code: the subject devolved to the provinces
    # (18th Amendment) and the Punjab has amended both -- TPA s.1 wholly
    # substituted by Punjab Act VIII of 2011; Registration Act amended by
    # Punjab Acts XIX of 2011 and XL of 2026, among others. The tenancy pack
    # is a Punjab pack, so it cites the text in force in the Punjab.
    "punjab_registration_act_1908": {
        "statute": "Registration Act 1908",
        "jurisdiction": "punjab",
        "publisher": "Punjab Code, Government of the Punjab",
        "url": "https://punjabcode.punjab.gov.pk/uploads/articles/registration-act-1908-doc-pdf.pdf",
        "listing_url": None,
        "sha256": "2d20ce6cffeedeb53446410043dab72c26cfe5108de250fab83c9f5e612cfcd8",
    },
    "punjab_transfer_of_property_act_1882": {
        "statute": "Transfer of Property Act 1882",
        "jurisdiction": "punjab",
        "publisher": "Punjab Code, Government of the Punjab",
        "url": "https://punjabcode.punjab.gov.pk/uploads/articles/THE_TRANSFER_OF_PROPERTY_ACT_1882.doc.pdf",
        "listing_url": None,
        "sha256": "c9250ac578d088e7779aaf1dea7b3b29ec3a6aa50a6c25c5ae83d3bc4f121097",
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
                     "Act 1882 (both as published in the Punjab Code) are held. Notifications under "
                     "TPA s.1(3) and (4) and under the proviso to Registration Act s.17(1) are not.",
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
             "text": "No source states a consolidated date it is amended up to (the Punjab Code "
                     "footnotes date individual amendments); whether later amendments exist is "
                     "decided only by the lawyer who approves each pack.",
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
    ("punjab_registration_act_1908", "17(1)", "Documents of which registration is compulsory",
     "17. Documents of which registration is compulsory", "(2) Nothing in clauses (b) and (c)", 13),
    ("punjab_transfer_of_property_act_1882", "1", "Short title, commencement, extent and exemption",
     "1. Short title, commencement, extent and exemption", "2. Repeal of Acts.", 9),
    ("punjab_transfer_of_property_act_1882", "107", "Leases how made",
     "107. Leases how made", "108. Rights and liabilities of lessor and lessee", 9),
    ("contract_act_1872", "27", "Agreement in restraint of trade void",
     "27. Agreement in restraint of trade void", "28. Agreements in restraint of legal proceedings", 3),
    ("contract_act_1872", "28", "Agreements in restraint of legal proceedings void",
     "28. Agreements in restraint of legal proceedings void", "29. Agreements void for uncertainty", 3),
]

# Footnotes attached to a provision although their marker is outside it,
# each with the reason: {(source, section): [(page, marker), ...]}.
EXTRA_NOTES = {
    # Footnote 1 hangs on the Act's title ("1THE TRANSFER OF PROPERTY ACT,
    # 1882"), but it is the record of the Act's EXTENT -- ss.54, 107 and 123
    # extended to Punjab municipalities and every cantonment, and the Act's
    # adoption by the Punjab after the 18th Amendment -- which s.1 governs and
    # the tenancy pack's registration reminders rely on.
    ("punjab_transfer_of_property_act_1882", "1"): [(9, "1")],
}

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


SMALL = 0.8        # below this fraction of the body size: footnote type / a footnote marker


def _size(char: dict) -> float:
    return round(char["size"], 1)


def _dominant(sizes: list[float]) -> float:
    return max(set(sizes), key=sizes.count)


def _small_digits(chars: list[dict], limit: float) -> list[str]:
    """Runs of small-type digits in a line: its footnote markers."""
    runs, run = [], ""
    for c in chars:
        if c["text"].isdigit() and _size(c) < limit:
            run += c["text"]
        elif run:
            runs.append(run)
            run = ""
    return runs + ([run] if run else [])


@functools.lru_cache(maxsize=None)
def page_lines(pdf: Path) -> tuple[tuple[int, tuple, tuple], ...]:
    """Per page: (page, body lines as (text, markers), footnotes as (marker, text))."""
    with pdfplumber.open(pdf) as doc:
        pages = [[(line["text"], [c for c in line["chars"] if not c["text"].isspace()])
                  for line in page.extract_text_lines(return_chars=True)] for page in doc.pages]
    pages = [[(text, chars) for text, chars in lines if chars] for lines in pages]
    # The whole Act's body size: on a footnote-heavy page the footnote type can
    # outnumber the body type (Transfer of Property Act, page 8).
    body_size = _dominant([_size(c) for lines in pages for _, chars in lines for c in chars])
    out = []
    for n, lines in enumerate(pages, start=1):
        body, notes = [], []
        for text, chars in lines:
            size = _dominant([_size(c) for c in chars])
            if size >= SMALL * body_size:
                body.append((text, tuple(_small_digits(chars, SMALL * body_size))))
                continue
            lead = _small_digits(chars[:4], SMALL * size)
            if text.strip().isdigit():
                notes.append([text.strip(), ""])                     # marker on its own line
            elif lead and text.startswith(lead[0]):
                notes.append([lead[0], text[len(lead[0]):]])      # a new footnote
            elif notes:
                notes[-1][1] += "\n" + text                          # its next line
        out.append((n, tuple(body), tuple((m, normalise(t)) for m, t in notes)))
    return tuple(out)


def cut(pdf: Path, start: str, end: str, first_page: int) -> tuple[str, list[int], list[dict]]:
    pages = page_lines(pdf)
    joined, lines = "", []
    for n, body, _ in pages[first_page - 1:]:
        for text, markers in body:
            lines.append((len(joined), len(joined) + len(text), n, markers))
            joined += text + "\n"
    i = joined.find(start)
    if i < 0:
        raise SystemExit(f"start marker not found: {start!r}")
    j = joined.find(end, i + len(start))
    if j < 0:
        raise SystemExit(f"end marker not found: {end!r}")
    within = [(n, markers) for a, b, n, markers in lines if a < j and b > i]
    spanned = sorted({n for n, _ in within})
    wanted = {(n, m) for n, markers in within for m in markers}
    # A footnote no marker anywhere on its page refers to (the publisher's
    # marker is wrong or missing) cannot be placed; it is shown with every
    # provision on that page, flagged, rather than dropped.
    on_page = {(n, m) for n, body, _ in pages for _, markers in body for m in markers}
    notes = [{"page": n, "marker": m, "marker_in_text": (n, m) in wanted, "text": text}
             for n, _, footnotes in pages if n in spanned
             for m, text in footnotes if (n, m) in wanted or (n, m) not in on_page]
    return normalise(joined[i:j]), spanned, notes


def extra_notes(pdf: Path, wanted: list[tuple[int, str]], pages: list[int]) -> list[dict]:
    footnotes = {(n, m): text for n, _, notes in page_lines(pdf) for m, text in notes}
    out = []
    for page, marker in wanted:
        if page not in pages or (page, marker) not in footnotes:
            raise SystemExit(f"extra note p{page} [{marker}] not found on the provision's pages")
        out.append({"page": page, "marker": marker, "marker_in_text": False,
                    "text": footnotes[(page, marker)]})
    return out


def build(directory: Path) -> dict:
    sources = {sid: {**meta, "retrieved": RETRIEVED, "authority_status": authorities.OFFICIAL,
                     "amended_up_to": None} for sid, meta in SOURCES.items()}
    provisions = []
    for sid, section, heading, start, end, first_page in PROVISIONS:
        text, pages, notes = cut(fetch(sid, directory), start, end, first_page)
        notes = sorted(extra_notes(fetch(sid, directory), EXTRA_NOTES.get((sid, section), []), pages) + notes,
                       key=lambda n: (n["page"], int(n["marker"])))
        if "�" in text + "".join(n["text"] for n in notes):
            raise SystemExit(f"{sid} s.{section}: unreadable characters in the text layer")
        provision = {
            "statute": SOURCES[sid]["statute"], "section": section, "heading": heading,
            "source": sid, "pages": pages, "text": text,
            "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()}
        if notes:
            provision["notes"] = notes
            provision["notes_sha256"] = authorities.notes_hash(notes)
        provisions.append(provision)
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
