"""build_judgment_pairs.py — retriever training pairs mined from real judgments.

WHAT THIS IS, AND WHY IT IS NOT AN EVALUATION SET
--------------------------------------------------
Judgments cite statutory provisions, and each citation is a human-authored link
between judicial prose and a section. That is genuine distant supervision from
data we already hold — no GPT-4 in the loop, unlike LEGAL-UQA.

It is deliberately NOT used for evaluation. Measured over the 164 judgments that
yield a resolvable citation:

    ocr_word_split      153  (93%)   "fo rmal", "t he Pistol", "Code o"
    party_names          36  (22%)   "son of", "Mst.", "versus"
    page_header_leak     22  (13%)   "27 Criminal Appeal No.243-J of 2025 ..."

Training averages that noise out over gradients. A benchmark cannot: a test set
where 93% of queries contain broken words measures the tokeniser as much as the
retriever. There is also a register problem — these passages are judicial
submissions ("He submits that the learned Executing Court committed a
jurisdictional error..."), not the lay questions the deployed retriever actually
fails on. Using them as eval would measure something real and quietly fail to
measure the thing that is broken.

WHY A SEPARATE SCRIPT RATHER THAN A FLAG ON build_finetune_data.py
-------------------------------------------------------------------
That script is hardcoded to one collection (`constitutional_collection`,
`build_retriever("constitutional", "federal")`) because every LEGAL-UQA gold
chunk lives there. Judgment citations do not: they land in criminal, civil and
family, so each item has to be routed to the collection its gold chunk is
actually in. Rather than reshape a working script, this one imports its
constants and its leakage-safe grouping so the two cannot drift:

    TEST_FRACTION, SEED, MIN_NEGATIVE_CHARS, MAX_NEGATIVES, _components

Hard negatives are mined the same way — from the deployed retriever's own
top-ranked non-gold results, skipping synthetic chunks and heading stubs.

Output is stamped `source: "judgment_citation"` and written to its own
directory. It is NOT merged into the constitutional training data, so a later
run can measure whether adding it helped, hurt, or did nothing, in isolation
from the gain the constitutional pairs already produced.

Usage
-----
  python scripts/build_judgment_pairs.py --out data/judgment_finetune
"""
from __future__ import annotations

import argparse
import asyncio
import json
import random
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Reused, not reimplemented — see module docstring.
from scripts.build_finetune_data import (  # noqa: E402
    MAX_NEGATIVES,
    MIN_NEGATIVE_CHARS,
    SEED,
    TEST_FRACTION,
    _components,
)

from app.ai.answer_citations import extract_citations, normalise_statute  # noqa: E402
from app.ai.nodes.retrieval_node import _is_synthetic  # noqa: E402
from app.ai.pipelines.retriever import CASE_TYPE_TO_COLLECTION, build_retriever  # noqa: E402
from app.db.chroma import connect_chroma, get_chroma  # noqa: E402
from app.db.mongodb import connect_db, get_database  # noqa: E402

SOURCE = "judgment_citation"

# Characters either side of the citation to take as the query passage.
_BEFORE, _AFTER = 340, 140

# A passage shorter than this after cleaning has lost its subject and would
# train the model on a fragment.
_MIN_QUERY_CHARS = 140

# ── Cleaning ─────────────────────────────────────────────────────────────────
# Every pattern here removes something that is demonstrably NOT part of the
# legal proposition: running headers, the court's own letterhead, and the
# citation the model is supposed to learn to find.

_WS = re.compile(r"\s+")

_HEADERS = [
    re.compile(r"Stereo\.?\s*H\s*C\s*J\s*D\s*A\s*\d*\.?", re.I),
    re.compile(r"JUDGMENT\s+SHEET", re.I),
    re.compile(r"(LAHORE|ISLAMABAD|PESHAWAR|SINDH|BALOCHISTAN)\s+HIGH\s+COURT[, ]*\w*", re.I),
    re.compile(r"JUDICIAL\s+DEPARTMENT", re.I),
    # "Criminal Appeal No.243-J of 2025", "Writ Petition No. 104 of 2025"
    re.compile(r"\b(?:Criminal|Civil|Writ|Family|Tax)\s+"
               r"(?:Appeal|Revision|Petition|Reference|Suit|Miscellaneous)\s*"
               r"No\.?\s*[\dA-Za-z\-/]+\s*(?:of\s*\d{4})?", re.I),
    re.compile(r"Petition\s+for\s+Special\s+Leave\s+to\s+Appeal\s*No\.?\s*[\d/]+\s*"
               r"(?:of\s*\d{4})?", re.I),
]

# OCR splits a word across a space: "fo rmal", "t he", "Cod e". Only repaired
# where the fragment is 1-2 letters and rejoining yields a plausible word —
# conservative, because over-joining would fuse genuinely separate words.
_OCR_SPLIT = re.compile(r"\b([a-zA-Z]{1,2}) ([a-z]{2,})\b")
# Words that legitimately stand alone as 1-2 letters and must never be joined.
_REAL_SHORT = {
    "a", "an", "as", "at", "be", "by", "do", "go", "he", "if", "in", "is", "it",
    "me", "my", "no", "of", "on", "or", "so", "to", "up", "us", "we", "i",
}


def _repair_ocr(text: str) -> str:
    def join(m: re.Match) -> str:
        head, tail = m.group(1), m.group(2)
        if head.lower() in _REAL_SHORT:
            return m.group(0)
        return head + tail
    return _OCR_SPLIT.sub(join, text)


def _clean(passage: str, statute: str, section: str) -> str:
    text = passage
    for pat in _HEADERS:
        text = pat.sub(" ", text)
    text = _repair_ocr(text)
    # Remove the citation itself. Left in, the retriever matches on the section
    # number alone and the pair teaches nothing about the law's language.
    text = re.sub(r"(?i)\b(?:section|sections|sec\.?|s\.|u/s|under\s+section)\s*"
                  + re.escape(section) + r"\b", " ", text)
    text = re.sub(r"(?i)\b" + re.escape(section) + r"\s+(?:of\s+the\s+)?"
                  + r"(?:Cr\.?P\.?C|C\.?P\.?C|P\.?P\.?C|Code)", " ", text)
    return _WS.sub(" ", text).strip(" ,.;:-")


# ── Recital filtering ────────────────────────────────────────────────────────
# The windowing above takes whatever text surrounds the citation. Sometimes that
# is legal argument; sometimes it lands on the opening recital — the cause title,
# the counsel appearance block, the order-sheet header, or the enumeration of
# parties — which names people and dockets but states no legal proposition:
#
#   "AALIA NEELUM, C.J:- The appellant-Musharaf Habib, son of Habib Nawaz,
#    Caste Awan, resident of Naushera, Tehsil &, District Khushab, has assailed
#    his conviction…"                                            -> PPC 1860 s.302
#
# Trained on, that pair teaches the retriever to associate Pakistani personal
# names with s.302. Names are near-uniformly distributed across sections, so the
# gradient is noise pulling every name-dense query toward whichever section
# happened to be cited. A missing pair costs less than a mislabelled one.
#
# WHY MARKER GROUPS AND NOT A KEYWORD LIST
# Single keywords do not separate the two classes. Measured over the 296 mined
# pairs, "FIR No" appears in 24.7% and "Advocate" in 12.5% — both occur inside
# genuine reasoning ("the FIR was registered after a delay of six hours"), so
# dropping on either alone would discard good pairs. What distinguishes a recital
# is the CO-OCCURRENCE of independent identification devices, and the absence of
# any legal proposition. So the rule needs both a positive and a negative signal.
#
# The inverse rule — requiring legal vocabulary — was tried first and rejected:
# it dropped 215/296, including substantive passages whose reasoning simply used
# words outside the lexicon. A recall-oriented lexicon cannot be the primary
# gate; it works only as a counterweight, which is how it is used here.

_RECITAL_GROUPS: dict[str, list[re.Pattern]] = {
    # "son of X", "resident of Y", "Caste Awan" — identifies a person, not a law.
    "party_identification": [
        re.compile(r"(?i)\b(?:son|daughter|widow)\s+of\s+[A-Z]"),
        re.compile(r"(?i)\bresident\s+of\b"),
        re.compile(r"(?i)\bcaste\b"),
        re.compile(r"(?i)\bTehsil\b"),
        re.compile(r"(?i)\br/o\b"),
    ],
    # Cause title: "Muhammad Ayub versus Muhammad Shoaib".
    "case_title": [
        re.compile(r"[A-Z][a-z]+\s+(?i:versus|v/s|vs\.)\s+[A-Z]"),
    ],
    # Who appeared. Pure procedure, never a legal proposition.
    "appearance_block": [
        re.compile(r"(?i),\s*Advocates?[,.]?\s*(?:for\s+the|$)"),
        re.compile(r"(?i)\bFor\s+the\s+(?:appellant|petitioner|respondent|State"
                   r"|complainant|informant)\b"),
        re.compile(r"(?i)\b(?:Mr|Malik|Syed|Rana|Ch|Sardar|Mian|M/s)\.?\s+"
                   r"[A-Z][\w-]+.{0,60}?,\s*Advocates?\b"),
        re.compile(r"(?i)\bResearch\s+Officer\b"),
        re.compile(r"(?i)\b(?:Assistant|Additional)\s+(?:Advocate\s+General"
                   r"|Prosecutor\s+General)\b"),
        re.compile(r"(?i)\bamicus\s+curiae\b"),
    ],
    # "Raheel Kamran J:-", "MUHAMMAD SAJID MEHMOOD SETHI, J .:-" — the judge
    # signing on. Mixed AND upper case, and the stray space before the period is
    # real: it is how the OCR renders it.
    "judge_signature": [
        re.compile(r"[A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+){0,4},?\s+"
                   r"(?:C\.?J|J)\s*\.?\s*[:\-–—]"),
        re.compile(r"(?i)\bThrough\s+this\s+(?:single\s+)?judgment,?\s+I\s+"
                   r"(?:intend|propose)\b"),
        re.compile(r"(?i)\bOrder\s+with\s+signature\s+of\s+Judge\b"),
    ],
    # Case numbers and hearing dates that survived _HEADERS.
    "docket_residue": [
        re.compile(r"(?i)\b(?:C\.?R\.?|W\.?P\.?|R\.?F\.?A\.?|C\.?M\.?"
                   r"|Crl\.?\s*(?:Misc|A)\.?)\s*No\.?\s*\d"),
        re.compile(r"(?i)\bdate\s+of\s+(?:hearing|institution|decision)\b"),
        re.compile(r"(?i)\bvide\s+(?:judgment|order|decree)[^.]{0,40}\bdated\b"),
        re.compile(r"(?i)\bSr\.\s*No\.\s*of\s*Order\b"),
    ],
    # Lists of co-accused. This is the group that catches the s.302 example
    # above's sibling — a bare name list with no "son of" to key on.
    "name_enumeration": [
        re.compile(r"\bMst\."),
        re.compile(r"@\s*[A-Z][a-z]"),
        re.compile(r"(?:[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3},\s+){3,}"),
        re.compile(r"(?i)\bco-\s?accused\b"),
        re.compile(r"(?i)\b(?:appellants?|petitioners?|respondents?)\s+along\s+with\b"),
    ],
}

# Counterweight, NOT a gate — see above. Deliberately recall-oriented: it only
# has to show that the passage asserts something legal, not classify what.
_SUBSTANCE = re.compile(
    r"(?i)\b(submit(?:s|ted)|contend(?:s|ed)|argue(?:s|d)|held|observ(?:ed|es)|"
    r"provide(?:s|d)\s+that|shall\s+be|must\s+be|entitled\s+to|burden\s+of\s+proof|"
    r"settled\s+law|jurisdiction|mandatory|ingredient|prima\s+facie|admissib|"
    r"corroborat|in\s+view\s+of|cannot\s+be|is\s+liable|violation|evidence|witness|"
    r"cross\s*-?\s*examination|prosecution|offence|question(?:s)?\s+(?:is|are|arises)|"
    r"principle|requirement|condition)\b")

# Capitalised words as a share of tokens. A backstop for recital forms none of
# the groups model: at 0.28 the passage is more than a quarter proper nouns.
_NAME = re.compile(r"\b[A-Z][a-z]{2,}\b")
_NAME_DENSITY_MAX = 0.28


def _recital_reason(query: str) -> str:
    """Why this passage is an opening recital, or "" if it is not.

    Two independent identification devices is enough on its own. One is enough
    only when the passage asserts nothing legal — that is what lets a genuine
    argument that merely *mentions* counsel or a case number survive.
    """
    hits = [name for name, pats in _RECITAL_GROUPS.items()
            if any(p.search(query) for p in pats)]
    substance = len({m.group(0).lower() for m in _SUBSTANCE.finditer(query)})

    if len(hits) >= 2:
        return "recital_" + "+".join(sorted(hits))
    if len(hits) == 1 and substance == 0:
        return "recital_bare_" + hits[0]

    tokens = query.split()
    density = len(_NAME.findall(query)) / len(tokens) if tokens else 0.0
    if density >= _NAME_DENSITY_MAX and substance == 0:
        return "recital_name_density"
    return ""


# ── Procedural-formula filtering ─────────────────────────────────────────────
# The recital filter above removes passages that identify PEOPLE. A second kind
# of low-value pair survives it: passages that are legal in register and mention
# evidence and prosecution, but consist of the stock narration every judgment of
# its type repeats verbatim.
#
#   "Provisions of section 265-C CrPC were complied with and the appellant was
#    charge sheeted, to which he pleaded not guilty and claimed trial. In order
#    to prove its case the prosecution produced and examined as many as 12
#    witnesses. After closure of prosecution evidence, statements of the accused
#    were recorded [under s.342] CrPC, wherein they posed innocence…"
#
# That is true of s.342 and says nothing that distinguishes s.342 from any other
# provision — the same sentence appears in judgments citing s.340, s.265-C and
# s.161. Training on it pushes every procedural query toward whichever section
# the template happened to cite.
#
# EXACT-MATCH DEDUP DOES NOT CATCH THIS. The fingerprint in _mine compares the
# first 160 characters, and these passages diverge there — different party
# names, different witness counts, different courts — while being templates from
# the same registry downstream. Detection has to be near-duplicate, not exact.
#
# THE PHRASE BANK IS DISCOVERED, NOT WRITTEN
# Hand-listing stock phrases would encode a guess about which formulae exist.
# Instead the bank is mined from the pairs themselves: every 6-gram (with digits
# normalised to "#", so "12 witnesses" and "23 PWs" share a shape) that appears
# in at least three DISTINCT judgments. Distinct judgments matters — two pairs
# from one judgment sharing text is one document, not a template.
#
# Discovering rather than assuming changed the result: the formula this filter
# removes most is not the trial-history one, it is the connected-appeals recital
# ("as both the matters are arising out of one and the same judgment dated …"),
# which had not been predicted at all.

_STOCK_N = 6
_STOCK_MIN_JUDGMENTS = 3
_WORD = re.compile(r"[a-z]+|\d+")

# Dominated by stock phrases: drop regardless of what else is present.
_COVERAGE_DOMINANT = 0.50
# Below that, coverage only condemns in company — see _boilerplate_reason.
_COVERAGE_PARTIAL = 0.30
_COVERAGE_WITH_FORMULA = 0.25
_NEAR_DUPLICATE = 0.35

# The trial-history formula named explicitly, because it is the one whose
# variants drift furthest apart lexically while staying the same template.
_TRIAL_FORMULA = re.compile(
    r"(?i)(pleaded\s+not\s+guilty|claimed\s+trial|charge\s*-?\s*sheeted|"
    r"produced\s+and\s+examined|closure\s+of\s+prosecution\s+evidence|"
    r"posed\s+innocence|wished\s+to\s+be\s+examined\s+on\s+oath|"
    r"statements?\s+of\s+(?:the\s+)?(?:accused|appellant)|"
    r"provisions\s+of\s+section\s+265|as\s+many\s+as\s+\d+\s+(?:witnesses|pws))")


def _shape(query: str) -> list[str]:
    """Tokens with digits collapsed, so witness counts do not defeat matching."""
    return ["#" if t.isdigit() else t for t in _WORD.findall(query.lower())]


def _stock_bank(items: list[dict]) -> set[str]:
    """6-grams occurring in >= 3 distinct judgments — the repeated formulae."""
    seen: dict[str, set] = defaultdict(set)
    for it in items:
        shape = _shape(it["question"])
        for i in range(len(shape) - _STOCK_N + 1):
            seen[" ".join(shape[i:i + _STOCK_N])].add(it["judgment_id"])
    return {g for g, js in seen.items() if len(js) >= _STOCK_MIN_JUDGMENTS}


def _stock_coverage(query: str, bank: set[str]) -> float:
    """Share of tokens sitting inside a known stock phrase."""
    shape = _shape(query)
    if not shape:
        return 0.0
    covered = [False] * len(shape)
    for i in range(len(shape) - _STOCK_N + 1):
        if " ".join(shape[i:i + _STOCK_N]) in bank:
            for k in range(i, i + _STOCK_N):
                covered[k] = True
    return sum(covered) / len(shape)


def _max_cross_similarity(items: list[dict]) -> list[float]:
    """For each pair, its highest 6-gram Jaccard against a DIFFERENT judgment.

    Same-judgment comparisons are skipped: overlapping windows cut from one
    document are expected to resemble each other and prove nothing about
    templating. 182 items is 16k comparisons — small enough to do exactly
    rather than approximate with MinHash.
    """
    grams = []
    for it in items:
        shape = _shape(it["question"])
        grams.append({" ".join(shape[i:i + _STOCK_N])
                      for i in range(len(shape) - _STOCK_N + 1)})
    best = [0.0] * len(items)
    for i in range(len(items)):
        for k in range(i + 1, len(items)):
            if items[i]["judgment_id"] == items[k]["judgment_id"]:
                continue
            a, b = grams[i], grams[k]
            if not a or not b:
                continue
            sim = len(a & b) / len(a | b)
            if sim > best[i]:
                best[i] = sim
            if sim > best[k]:
                best[k] = sim
    return best


def _boilerplate_reason(query: str, coverage: float, similarity: float) -> str:
    """Why this passage is procedural formula, or "" if it is not.

    Coverage alone condemns only when it dominates. Below that it needs
    corroboration — the named formula, a near-duplicate in another judgment, or
    the absence of any legal assertion. That last clause is what spares a
    genuine argument built around a stock phrase, e.g. "…upon their resolution
    depends whether the judgment dated 05.03.2021, rendered by the learned
    Additional Sessions Judge, may stand or must fall", which is 34% stock and
    still the best PPC 376 pair in the set.
    """
    if coverage >= _COVERAGE_DOMINANT:
        return "boilerplate_stock_coverage"

    formula = len({m.group(0).lower() for m in _TRIAL_FORMULA.finditer(query)})
    if formula >= 3 and coverage >= _COVERAGE_WITH_FORMULA:
        return "boilerplate_trial_history"
    if similarity >= _NEAR_DUPLICATE and coverage >= _COVERAGE_PARTIAL:
        return "boilerplate_near_duplicate"

    substance = len({m.group(0).lower() for m in _SUBSTANCE.finditer(query)})
    if coverage >= _COVERAGE_PARTIAL and substance == 0:
        return "boilerplate_no_substance"
    return ""


def _filter_boilerplate(items: list[dict]) -> tuple[list[dict], list[dict], int]:
    bank = _stock_bank(items)
    sims = _max_cross_similarity(items)
    kept, dropped = [], []
    for it, sim in zip(items, sims):
        coverage = _stock_coverage(it["question"], bank)
        reason = _boilerplate_reason(it["question"], coverage, sim)
        if reason:
            dropped.append({**{k: v for k, v in it.items()},
                            "reason": reason,
                            "stock_coverage": round(coverage, 3),
                            "max_cross_judgment_similarity": round(sim, 3)})
        else:
            it["stock_coverage"] = round(coverage, 3)
            kept.append(it)
    return kept, dropped, len(bank)


# ── Windowing noise (flagged, not filtered) ──────────────────────────────────
# The window is cut around the gold citation, so it can overrun into discussion
# of a DIFFERENT provision. The gold link is still real — the judgment did cite
# it there — but the passage's dominant content points elsewhere:
#
#   gold CrPC 1898 s.544, passage mostly about conviction under s.302(b) PPC
#
# Not filtered, because "dominant" is a judgement call and the pair is not
# wrong, only diluted. Flagged so the rate is known and can be revisited if a
# training run underperforms.

def _competing_sections(item: dict) -> list[str]:
    """Sections cited in the passage other than the gold one."""
    gold = item["gold_citation"]
    others = []
    for cite in extract_citations(item["question"]):
        label = f"{cite.statute} s.{cite.section}"
        if label != gold and label not in others:
            others.append(label)
    return others


# ── Mining ───────────────────────────────────────────────────────────────────

def _corpus_index() -> tuple[dict, dict, dict]:
    """(statute, section) -> chunk ids; chunk id -> text; chunk id -> case_type."""
    client = get_chroma()
    by_key: dict[tuple[str, str], list[str]] = defaultdict(list)
    text: dict[str, str] = {}
    case_of: dict[str, str] = {}
    for case_type, coll in CASE_TYPE_TO_COLLECTION.items():
        try:
            got = client.get_collection(coll).get(include=["documents", "metadatas"])
        except Exception as exc:
            print(f"    skipping {coll}: {exc}")
            continue
        for cid, doc, meta in zip(got["ids"], got["documents"], got["metadatas"]):
            meta = meta or {}
            key_id = meta.get("chunk_id") or cid
            text[key_id] = doc or ""
            case_of[key_id] = case_type
            st = (meta.get("statute") or "").strip()
            sec = str(meta.get("section_number") or "").strip()
            if st and sec:
                by_key[(normalise_statute(st), sec)].append(key_id)
    return by_key, text, case_of


async def _judgments() -> list[dict]:
    await connect_db()
    return await get_database()["judgments"].find(
        {}, {"_id": 1, "text": 1, "court": 1, "year": 1, "province": 1}
    ).to_list(length=None)


def _mine(docs: list[dict], by_key: dict, case_of: dict) -> list[dict]:
    """One item per (judgment, cited section) whose section is in the corpus."""
    items: list[dict] = []
    recitals: list[dict] = []
    seen_queries: set[str] = set()
    dropped = Counter()

    for d in docs:
        raw = d.get("text") or ""
        if not raw:
            dropped["no_text"] += 1
            continue
        for cite in extract_citations(raw):
            gold = by_key.get(cite.key)
            if not gold:
                dropped["section_not_in_corpus"] += 1
                continue
            m = re.search(r"\b" + re.escape(cite.section) + r"\b", raw)
            if not m:
                dropped["citation_span_not_located"] += 1
                continue
            window = raw[max(0, m.start() - _BEFORE): m.end() + _AFTER]
            query = _clean(window, cite.statute, cite.section)
            if len(query) < _MIN_QUERY_CHARS:
                dropped["too_short_after_cleaning"] += 1
                continue
            # Before the fingerprint, so a discarded recital never occupies the
            # dedup slot of a good passage from the same judgment.
            reason = _recital_reason(query)
            if reason:
                dropped["opening_recital"] += 1
                recitals.append({"question": query, "reason": reason,
                                 "gold_citation": f"{cite.statute} s.{cite.section}",
                                 "judgment_id": d.get("_id")})
                continue
            fingerprint = query[:160].lower()
            if fingerprint in seen_queries:
                dropped["duplicate_query"] += 1
                continue
            seen_queries.add(fingerprint)
            items.append({
                "question": query,
                "relevant_chunks": sorted(gold),
                "case_type": case_of.get(gold[0], "civil"),
                "province": d.get("province") or "federal",
                "source": SOURCE,
                "judgment_id": d.get("_id"),
                "gold_citation": f"{cite.statute} s.{cite.section}",
            })
    return items, dropped, recitals


def main(out_dir: Path) -> int:
    connect_chroma()
    print("\n  indexing corpus…")
    by_key, text, case_of = _corpus_index()
    print(f"    lookup keys: {len(by_key)}   chunks with text: {len(text)}")

    docs = asyncio.run(_judgments())
    print(f"  judgments: {len(docs)}")

    items, dropped, recitals = _mine(docs, by_key, case_of)
    print(f"\n  mined pairs: {len(items)}")
    for reason, n in dropped.most_common():
        print(f"    dropped {reason:26s} {n}")
    if not items:
        raise SystemExit("no pairs mined — nothing to write")

    if recitals:
        print(f"\n  opening-recital filter removed {len(recitals)}:")
        for reason, n in Counter(r["reason"] for r in recitals).most_common(8):
            print(f"    {reason:52s} {n}")

    # Second pass: procedural formula. Needs the whole set, because both the
    # phrase bank and the similarity are properties of the collection.
    before = len(items)
    items, boilerplate, bank_size = _filter_boilerplate(items)
    print(f"\n  procedural-formula filter: stock phrase bank {bank_size} 6-grams "
          f"(>= {_STOCK_MIN_JUDGMENTS} distinct judgments)")
    print(f"    removed {len(boilerplate)} of {before}")
    for reason, n in Counter(b["reason"] for b in boilerplate).most_common():
        print(f"    {reason:44s} {n}")

    # Flagged only — see the section comment.
    noisy = 0
    for it in items:
        others = _competing_sections(it)
        if others:
            it["competing_sections"] = others
            noisy += 1
    print(f"\n  windowing noise (flagged, NOT dropped): {noisy} of {len(items)} "
          f"({100 * noisy / len(items):.1f}%) cite another section in the passage")

    print(f"\n  by case_type: {dict(Counter(i['case_type'] for i in items))}")
    print(f"  distinct gold citations: {len({i['gold_citation'] for i in items})}")

    # ── leakage-safe split, using the SAME grouping as the constitutional run ─
    groups = _components(items)
    keys = sorted(groups)
    random.Random(SEED).shuffle(keys)
    target = len(items) * TEST_FRACTION
    test_keys, running = set(), 0
    for k in keys:
        if running >= target:
            break
        test_keys.add(k)
        running += len(groups[k])
    train_keys = set(keys) - test_keys
    train = [it for k in train_keys for it in groups[k]]
    test = [it for k in test_keys for it in groups[k]]

    train_gold = {c for it in train for c in it["relevant_chunks"]}
    test_gold = {c for it in test for c in it["relevant_chunks"]}
    overlap = train_gold & test_gold
    if overlap:
        raise SystemExit(
            f"LEAKAGE: {len(overlap)} gold chunk(s) in both splits, e.g. "
            f"{sorted(overlap)[:3]} — the split is not group-clean")
    print(f"  components {len(keys)} | train {len(train)} | test {len(test)} | "
          f"gold overlap 0")

    # ── hard negatives, mined per case_type from the deployed retriever ──────
    print("\n  mining hard negatives from the current retriever…")
    retrievers: dict[tuple[str, str], object] = {}
    triplets, positives_only, no_text = [], 0, 0

    for n, it in enumerate(train, 1):
        if n % 25 == 0:
            print(f"    {n}/{len(train)}")
        gold = set(it["relevant_chunks"])
        pos_id = next((c for c in sorted(gold)
                       if len(text.get(c, "")) >= MIN_NEGATIVE_CHARS), None)
        if pos_id is None:
            no_text += 1
            continue

        key = (it["case_type"], it["province"])
        if key not in retrievers:
            try:
                retrievers[key] = build_retriever(*key)
            except Exception as exc:
                print(f"      retriever {key} unavailable: {exc}")
                retrievers[key] = None
        retriever = retrievers[key]

        docs_r = []
        if retriever is not None:
            try:
                docs_r = retriever.invoke(it["question"])
            except Exception:
                docs_r = []

        negatives = []
        for d in docs_r:
            meta = d.metadata or {}
            cid = meta.get("chunk_id", "")
            if _is_synthetic(meta) or cid in gold:
                continue
            body = text.get(cid, "")
            if len(body) < MIN_NEGATIVE_CHARS:
                continue
            negatives.append(body)
            if len(negatives) >= MAX_NEGATIVES:
                break

        if not negatives:
            positives_only += 1
            triplets.append({"query": it["question"], "positive": text[pos_id],
                             "source": SOURCE})
            continue
        for neg in negatives:
            triplets.append({"query": it["question"], "positive": text[pos_id],
                             "negative": neg, "source": SOURCE})

    print(f"\n  training examples : {len(triplets)}")
    print(f"    with a hard negative : {sum(1 for t in triplets if 'negative' in t)}")
    print(f"    positive-only        : {positives_only}")
    print(f"    dropped, no usable gold text: {no_text}")

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "train_triplets.json").write_text(
        json.dumps(triplets, indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / "test_questions.json").write_text(
        json.dumps(test, indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / "mined_pairs.json").write_text(
        json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")
    # Kept so the filter is auditable — a quality filter nobody can inspect is
    # indistinguishable from silently losing data.
    (out_dir / "dropped_recitals.json").write_text(
        json.dumps(recitals, indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / "dropped_boilerplate.json").write_text(
        json.dumps(boilerplate, indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / "split_manifest.json").write_text(json.dumps({
        "source": SOURCE,
        "seed": SEED,
        "test_fraction": TEST_FRACTION,
        "n_mined_pairs": len(items),
        "n_dropped_opening_recital": len(recitals),
        "recital_filter": {
            "rule": "drop if >=2 marker groups, or 1 group with no substance "
                    "token, or name-density >= %.2f with no substance token"
                    % _NAME_DENSITY_MAX,
            "marker_groups": sorted(_RECITAL_GROUPS),
            "name_density_max": _NAME_DENSITY_MAX,
            "dropped_written_to": "dropped_recitals.json",
        },
        "n_dropped_procedural_formula": len(boilerplate),
        "boilerplate_filter": {
            "rule": "drop if stock-phrase coverage >= %.2f; or >=3 trial-history "
                    "phrases with coverage >= %.2f; or cross-judgment 6-gram "
                    "Jaccard >= %.2f with coverage >= %.2f; or coverage >= %.2f "
                    "with no substance token"
                    % (_COVERAGE_DOMINANT, _COVERAGE_WITH_FORMULA,
                       _NEAR_DUPLICATE, _COVERAGE_PARTIAL, _COVERAGE_PARTIAL),
            "stock_phrase_bank": "%d-grams occurring in >= %d distinct judgments, "
                                 "mined from the pairs themselves"
                                 % (_STOCK_N, _STOCK_MIN_JUDGMENTS),
            "dropped_written_to": "dropped_boilerplate.json",
        },
        "n_flagged_windowing_noise": noisy,
        "windowing_noise": "pairs whose passage also cites another section; "
                           "flagged in `competing_sections`, NOT dropped",
        "n_train_questions": len(train),
        "n_test_questions": len(test),
        "n_train_groups": len(train_keys),
        "n_test_groups": len(test_keys),
        "gold_overlap": 0,
        "grouped_by": "connected components over shared gold chunks",
        "min_negative_chars": MIN_NEGATIVE_CHARS,
        "max_negatives": MAX_NEGATIVES,
        "not_merged_with": "data/finetune (constitutional / LEGAL-UQA)",
        "intended_use": "retriever training only — NOT an evaluation set; see "
                        "module docstring for the OCR and register reasons",
    }, indent=2), encoding="utf-8")

    print(f"\n  wrote -> {out_dir}")
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Mine retriever training pairs from judgments.")
    p.add_argument("--out", type=Path, default=Path("data/judgment_finetune"))
    a = p.parse_args()
    raise SystemExit(main(a.out))
