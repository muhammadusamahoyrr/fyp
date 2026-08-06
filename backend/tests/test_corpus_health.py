"""Corpus regression suite — the measurement harness.

Why this exists
---------------
Every corpus-quality number produced during development came from a throwaway
script, so nothing could be compared over time and nothing failed when the
corpus degraded. Two real defects show the cost:

  * Contents-page stubs took THREE wrong attempts to fix (a length threshold, an
    exact prefix match, then a normalised head match), because each attempt's
    effect could only be checked by hand.
  * The Constitution stored dataset ROW INDICES as article numbers, and it was
    found by accident while probing candidates for this very file.

Both would have failed here immediately.

Design
------
GOLD is a fixed set of provisions verified present in the corpus, each pinned by
a distinctive phrase from its own text. HEALTH assertions bound the metrics that
regressed. Thresholds are set at the CURRENT measured value with headroom, so
they catch degradation without being brittle.

These tests read the live ChromaDB. When it is unavailable they skip rather than
fail — a missing corpus is an environment issue, not a regression.
"""
import collections
import re

import pytest

try:
    from app.db.chroma import connect_chroma, get_chroma
    connect_chroma()
    _CLIENT = get_chroma()
except Exception:  # pragma: no cover - environment without a built corpus
    _CLIENT = None

pytestmark = pytest.mark.skipif(_CLIENT is None, reason="ChromaDB not available")

STATUTE_COLLECTIONS = ("criminal_collection", "civil_collection",
                       "family_collection", "constitutional_collection")

# (collection, statute, section, phrase that must appear in that section's text)
# Every entry was verified against the live corpus before being written here.
GOLD = [
    ("criminal_collection", "PPC 1860", "302", "qatl"),
    ("criminal_collection", "PPC 1860", "379", "theft"),
    ("criminal_collection", "PPC 1860", "420", "cheating"),
    ("criminal_collection", "CrPC 1898", "154", "cognizable"),
    ("criminal_collection", "CrPC 1898", "497", "bail"),
    ("criminal_collection", "Qanun-e-Shahadat Order 1984", "17", "competence"),
    ("civil_collection", "Limitation Act 1908", "3", "prescribe"),
    ("civil_collection", "Transfer of Property Act 1882", "54", "sale"),
    ("civil_collection", "Punjab Rented Premises Act 2009", "15", "eviction"),
    ("civil_collection", "Punjab Pre-emption Act 1991", "13", "pre"),
    ("family_collection", "Muslim Family Laws Ordinance 1961", "7", "talaq"),
    ("family_collection", "Muslim Family Laws Ordinance 1961", "9", "maintain"),
    ("family_collection", "Family Courts Act 1964", "5", "jurisdiction"),
]


def _section_docs(collection: str, statute: str, section: str) -> list[str]:
    col = _CLIENT.get_collection(collection)
    got = col.get(
        where={"$and": [{"statute": {"$eq": statute}},
                        {"section_number": {"$eq": section}}]},
        include=["documents"], limit=100)
    return got.get("documents") or []


def _all_meta(collection: str):
    col = _CLIENT.get_collection(collection)
    got = col.get(include=["documents", "metadatas"], limit=100000)
    return got.get("documents") or [], got.get("metadatas") or []


# ── gold provisions: present, and containing the right law ───────────────────

@pytest.mark.parametrize("collection,statute,section,phrase", GOLD,
                         ids=[f"{s}-s{sec}" for _c, s, sec, _p in GOLD])
def test_gold_provision_is_present_and_correct(collection, statute, section, phrase):
    """A provision the system is expected to answer from. Absence is a coverage
    regression; the wrong text under that number is a citation defect."""
    docs = _section_docs(collection, statute, section)
    assert docs, f"{statute} s.{section} is MISSING from {collection}"
    joined = " ".join(docs).lower()
    assert phrase in joined, (
        f"{statute} s.{section} exists but its text does not mention "
        f"{phrase!r} — the section number may be mislabelled")


def test_the_query_that_failed_in_production_now_has_its_law():
    """'Can a tenant be evicted without notice in Punjab?' scored 0.21 because
    provincial rent law was absent entirely."""
    docs = _section_docs("civil_collection", "Punjab Rented Premises Act 2009", "15")
    assert docs and "eviction" in " ".join(docs).lower()


# ── contents-page stubs ──────────────────────────────────────────────────────

_ALNUM = re.compile(r"[^a-z0-9]+")
_TRAILING_PAGENO = re.compile(r"[\.\s]*\d{1,3}\s*$")


def _norm(t: str) -> str:
    return _ALNUM.sub("", _TRAILING_PAGENO.sub("", t or "").lower())


def test_no_contents_stubs_remain():
    """1,346 were removed. A stub is a chunk whose normalised head prefixes a
    longer chunk of the SAME section — a contents line duplicating the
    provision it names, carrying none of the rule."""
    offenders = []
    for name in STATUTE_COLLECTIONS:
        docs, metas = _all_meta(name)
        groups = collections.defaultdict(list)
        for d, m in zip(docs, metas):
            m = m or {}
            groups[(m.get("statute", ""), m.get("section_number", ""))].append(d or "")
        for (statute, section), members in groups.items():
            for text in members:
                if len(text) >= 120:
                    continue
                head = _norm(text)[:25]
                if len(head) < 12:
                    continue
                if any(len(o) > len(text) and _norm(o).startswith(head)
                       for o in members if o is not text):
                    offenders.append(f"{statute} s.{section}")
    assert not offenders, (
        f"{len(offenders)} contents stub(s) reappeared, e.g. {offenders[:5]}. "
        f"Run scripts/prune_toc_stubs.py")


# ── Constitution article numbering ───────────────────────────────────────────

def test_no_impossible_constitution_articles():
    """The Constitution of Pakistan has 280 articles. Anything beyond that was a
    dataset row index stored as an article number — 83 chunks once were."""
    _docs, metas = _all_meta("constitutional_collection")
    bad = sorted({s for m in metas
                  if (s := str((m or {}).get("section_number", "")))
                  and s.rstrip("ABCDEFGHIJKLMNOPQRSTUVWXYZ").isdigit()
                  and int(s.rstrip("ABCDEFGHIJKLMNOPQRSTUVWXYZ")) > 280})
    assert not bad, f"article numbers above 280 present: {bad[:10]}"


def test_constitution_article_numbers_match_their_text():
    """The dangerous case: row 27 held the text of Article 25A. Article 27
    exists, so a wrong citation looked entirely plausible."""
    docs, metas = _all_meta("constitutional_collection")
    leading = re.compile(r"^\s*(\d{1,3}[A-Z]?)\s*[\.\)\:]")
    mismatches = []
    for d, m in zip(docs, metas):
        stated = str((m or {}).get("section_number", "") or "")
        if not stated:
            continue
        hit = leading.match((d or "").strip())
        if hit and hit.group(1) != stated:
            mismatches.append(f"meta s.{stated} vs text {hit.group(1)}")
    assert not mismatches, f"article number disagrees with its own text: {mismatches[:5]}"


# ── coverage and structure ───────────────────────────────────────────────────

def test_section_numbers_are_populated():
    """Generation cites sections. Blank section numbers degrade every citation;
    coverage was patchy before re-ingestion (QSO 0%, Limitation 11.8%)."""
    total = with_section = 0
    for name in STATUTE_COLLECTIONS:
        _docs, metas = _all_meta(name)
        total += len(metas)
        with_section += sum(1 for m in metas if (m or {}).get("section_number"))
    assert total, "statute collections are empty"
    ratio = with_section / total
    assert ratio >= 0.75, f"only {ratio:.1%} of statute chunks carry a section number"


def test_judgment_corpus_spans_multiple_courts():
    """Precedent-aware ranking is meaningless on a single-court corpus, and a
    litigant outside that province gets only persuasive authority."""
    _docs, metas = _all_meta("judgments_collection")
    courts = collections.Counter(str((m or {}).get("court", "")) for m in metas)
    assert len(courts) >= 5, f"only {len(courts)} court(s) indexed: {dict(courts)}"


def test_supreme_court_authority_is_represented():
    """binding_national is the highest precedent weight. Without Supreme Court
    judgments that branch of the ranker can never fire."""
    _docs, metas = _all_meta("judgments_collection")
    national = sum(1 for m in metas
                   if (m or {}).get("authority") == "binding_national")
    assert national > 0, "no binding_national judgments — SC corpus missing"


def test_every_judgment_chunk_has_a_jurisdiction():
    """province and authority drive the precedent ranker; a chunk without them
    is treated as persuasive everywhere."""
    _docs, metas = _all_meta("judgments_collection")
    missing = sum(1 for m in metas
                  if not (m or {}).get("province") or not (m or {}).get("authority"))
    assert missing == 0, f"{missing} judgment chunks lack province/authority"


def test_provincial_law_is_indexed():
    """Every chunk was province='federal' at one point, which made the
    retriever's province filter exclude nothing at all."""
    provinces = collections.Counter()
    for name in STATUTE_COLLECTIONS:
        _docs, metas = _all_meta(name)
        for m in metas:
            provinces[str((m or {}).get("province", ""))] += 1
    non_federal = sum(v for k, v in provinces.items() if k not in ("federal", ""))
    assert non_federal > 0, f"no provincial statutes indexed: {dict(provinces)}"
