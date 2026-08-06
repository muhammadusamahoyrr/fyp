"""
build_law_graph.py — Statute cross-reference graph for graph-guided hop-2.

Run after any ingest (chunk ids change):
    python scripts/build_law_graph.py

Output: backend/chroma_data/law_graph.json (node-link JSON, not pickle —
unpickling executes arbitrary code and a build artifact should not do that)

What was wrong with the previous version
----------------------------------------
It produced 44 edges across 2,639 nodes — effectively no graph at all. Three
causes, all measured:

1. It looked for lawyer shorthand ("PPC 302", "CrPC 154"). Across 3,998
   criminal chunks that pattern matched ZERO times. Legislation does not cite
   itself that way; briefs do.

2. It ignored bare intra-statute references ("section 12", "under section 5"),
   which is how statutes actually cross-reference — 492 of those same 3,998
   chunks contain one.

3. Source nodes were keyed on the canonical statute name ("PPC 1860" ->
   ppc_1860_302) while citation targets were keyed on the abbreviation ("PPC"
   -> ppc_302). The two never matched, so every edge landed on an orphan stub
   that pointed at no chunk.

How this version works
----------------------
Pass 1 indexes every (statute, section) that actually EXISTS, with all the chunk
ids that make it up — a section spanning several chunks keeps all of them.

Pass 2 extracts references and resolves them against that index. An edge is only
created when the target section genuinely exists, so every edge is traversable.
Unresolved references are counted and reported rather than silently turned into
dangling stubs.

A bare "section N" resolves within the SAME statute, which is the common case.
"section N of the X Act" resolves against X via the alias table.
"""
from __future__ import annotations

import collections
import json
import re
import sys
from pathlib import Path

import networkx as nx

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.db.chroma import connect_chroma, get_chroma  # noqa: E402

COLLECTIONS = [
    "civil_collection",
    "criminal_collection",
    "family_collection",
    "constitutional_collection",
]

OUTPUT_PATH = BACKEND_DIR / "chroma_data" / "law_graph.json"

# Higher = more worth following in hop-2.
RELATION_WEIGHTS = {
    "defined_by": 1.20,
    "cite":       1.15,
    "ref":        1.10,
    "amend":      1.05,
}

# Shorthand -> canonical statute name as stored in chunk metadata. Validated
# against the corpus at build time; unknown targets are reported, not guessed.
STATUTE_ALIASES = {
    "ppc":                          "PPC 1860",
    "pakistan penal code":          "PPC 1860",
    "penal code":                   "PPC 1860",
    "crpc":                         "CrPC 1898",
    "code of criminal procedure":   "CrPC 1898",
    "criminal procedure code":      "CrPC 1898",
    "mflo":                         "Muslim Family Laws Ordinance 1961",
    "muslim family laws ordinance": "Muslim Family Laws Ordinance 1961",
    "qso":                          "Qanun-e-Shahadat Order 1984",
    "qanun-e-shahadat":             "Qanun-e-Shahadat Order 1984",
    "constitution":                 "Constitution of Pakistan 1973",
}

# "section 12", "sections 12", optionally "... of the <Something> Act 1861"
_REF_RE = re.compile(
    r"\bsections?\s+(\d+[A-Z]?)\b"
    r"(?:\s+of\s+(?:the\s+)?"
    r"([A-Za-z][A-Za-z\s\-'\.]{3,60}?(?:Act|Code|Ordinance|Order)(?:[,\s]+\d{4})?))?",
    re.IGNORECASE,
)
# Constitution uses articles
_ARTICLE_RE = re.compile(r"\barticles?\s+(\d+[A-Z]?)\b", re.IGNORECASE)

_AMEND_RE = re.compile(
    r"\b(amend|substitut|insert|replac|omit)\w*", re.IGNORECASE)
_DEFINED_RE = re.compile(
    r"(?:as\s+defined|has\s+the\s+meaning\s+assigned|within\s+the\s+meaning)",
    re.IGNORECASE)


def node_id(statute: str, section: str) -> str:
    return f"{statute.lower().replace(' ', '_')}::{section}"


# Anaphoric self-reference: inside a statute, "this Code" / "the said Act" /
# "the same Ordinance" point back at the statute doing the referring.
_ANAPHORA_RE = re.compile(
    r"^(?:this|the|that|same|said|the\s+said|the\s+same)\s+"
    r"(?:code|act|ordinance|order)$",
    re.IGNORECASE,
)


def resolve_statute(raw: str | None, source_statute: str, known: set[str]) -> str | None:
    """Map a referenced statute name onto a canonical one that exists in the corpus."""
    if not raw:
        return source_statute          # bare "section N" -> same statute
    low = " ".join(raw.split()).lower().strip(" ,.")
    if _ANAPHORA_RE.match(low):
        return source_statute
    if low in STATUTE_ALIASES:
        cand = STATUTE_ALIASES[low]
        return cand if cand in known else None
    for alias, canon in STATUTE_ALIASES.items():
        if alias in low:
            return canon if canon in known else None

    # Fuzzy name match, deliberately conservative. A false edge sends hop-2 to
    # the WRONG statute, which is worse than no edge at all — so require a
    # reasonably specific string and refuse when several statutes match.
    if len(low) < 8:
        return None
    candidates = {k for k in known if low in k.lower() or k.lower() in low}
    return candidates.pop() if len(candidates) == 1 else None


def _relation(window: str) -> str:
    if _DEFINED_RE.search(window):
        return "defined_by"
    if _AMEND_RE.search(window):
        return "amend"
    return "cite"


def build_graph() -> nx.DiGraph:
    connect_chroma()
    chroma = get_chroma()
    G = nx.DiGraph()

    # ── Pass 1: index every section that actually exists ─────────────────────
    sections: dict[tuple[str, str], list[str]] = collections.defaultdict(list)
    records: list[tuple[str, str, str, dict]] = []   # statute, section, text, meta

    for cname in COLLECTIONS:
        try:
            col = chroma.get_collection(cname)
            res = col.get(include=["documents", "metadatas"], limit=100000)
        except Exception as exc:
            print(f"  could not load {cname}: {exc}")
            continue
        docs = res.get("documents") or []
        metas = res.get("metadatas") or []
        print(f"  {cname}: {len(docs)} chunks")
        for text, meta in zip(docs, metas):
            meta = meta or {}
            statute = str(meta.get("statute", "")).strip()
            section = str(meta.get("section_number", "")).strip()
            if not statute or not section:
                continue
            sections[(statute, section)].append(str(meta.get("chunk_id", "")))
            records.append((statute, section, text or "", {**meta, "collection": cname}))

    known_statutes = {s for s, _ in sections}
    print(f"\n  indexed {len(sections)} distinct (statute, section) nodes "
          f"across {len(known_statutes)} statutes")

    for (statute, section), chunk_ids in sections.items():
        G.add_node(node_id(statute, section),
                   statute=statute, section_number=section,
                   chunk_ids=[c for c in chunk_ids if c])

    # ── Pass 2: resolve references against real sections only ────────────────
    resolved = collections.Counter()
    unresolved = collections.Counter()

    for statute, section, text, _meta in records:
        src = node_id(statute, section)
        is_constitution = "constitution" in statute.lower()
        pattern = _ARTICLE_RE if is_constitution else _REF_RE

        for m in pattern.finditer(text):
            tgt_section = m.group(1)
            raw_statute = None if is_constitution else (
                m.group(2) if m.lastindex and m.lastindex >= 2 else None)
            tgt_statute = resolve_statute(raw_statute, statute, known_statutes)
            if tgt_statute is None:
                unresolved[(raw_statute or "?")[:40]] += 1
                continue
            if (tgt_statute, tgt_section) not in sections:
                unresolved[f"{tgt_statute} s.{tgt_section}"] += 1
                continue
            tgt = node_id(tgt_statute, tgt_section)
            if tgt == src:
                continue
            window = text[max(0, m.start() - 60): m.end() + 20]
            rel = _relation(window)
            G.add_edge(src, tgt, relation=rel, weight=RELATION_WEIGHTS.get(rel, 1.0))
            resolved[rel] += 1

    print(f"\nGraph built: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")
    print(f"  references resolved  : {sum(resolved.values())}  {dict(resolved)}")
    print(f"  references unresolved: {sum(unresolved.values())}")
    for label, n in unresolved.most_common(6):
        print(f"      {n:>5}  {label}")

    orphans = [n for n, d in G.nodes(data=True) if not d.get("chunk_ids")]
    print(f"  nodes with no chunk_ids (should be 0): {len(orphans)}")
    if G.number_of_nodes():
        deg = [d for _, d in G.degree()]
        print(f"  mean degree: {sum(deg)/len(deg):.2f}   "
              f"connected nodes: {sum(1 for d in deg if d)}")
    return G


def save_graph(G: nx.DiGraph, path: Path) -> None:
    """Write node-link JSON.

    Deliberately not pickle: unpickling executes arbitrary code, and a build
    artifact that may be copied between machines or restored from a backup
    should not carry that property. JSON is also inspectable and diffable.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    data = nx.node_link_data(G, edges="edges")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)
    print(f"Saved to: {path}  ({path.stat().st_size:,} bytes)")

    legacy = path.with_suffix(".gpickle")
    if legacy.exists():
        legacy.unlink()
        print(f"Removed superseded pickle: {legacy}")


if __name__ == "__main__":
    save_graph(build_graph(), OUTPUT_PATH)
