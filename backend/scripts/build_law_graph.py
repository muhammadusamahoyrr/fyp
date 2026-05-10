"""
build_law_graph.py — Builds a NetworkX statute cross-reference graph from ChromaDB.

Run this ONCE (and re-run whenever you ingest new statutes):
    python scripts/build_law_graph.py

The graph is saved to: backend/chroma_data/law_graph.gpickle

Graph structure (adapted from Fan-Luo/Legal-RAG graph_retriever.py):
  - Nodes: statute sections identified by chunk_id
  - Edges: cross-references with relation_type + weight
    - "cite"       weight=1.15  (explicit "see PPC Section X")
    - "ref"        weight=1.10  (general reference)
    - "amend"      weight=1.05  (amendment references)
    - "defined_by" weight=1.20  (definitional cross-link)

Hop-2 in retrieval_node.py traverses this graph instead of using regex.
"""

from __future__ import annotations

import os
import re
import sys
import pickle
from pathlib import Path

import networkx as nx

# Add backend to path so we can import app modules
BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.db.chroma import get_chroma, connect_chroma  # noqa: E402 (after path fix)

# ── Config ────────────────────────────────────────────────────────────────────

COLLECTIONS = [
    "civil_collection",
    "criminal_collection",
    "family_collection",
    "constitutional_collection",
]

OUTPUT_PATH = BACKEND_DIR / "chroma_data" / "law_graph.gpickle"

# Relation weights — higher = more important to follow in hop-2
RELATION_WEIGHTS = {
    "defined_by": 1.20,
    "cite":       1.15,
    "ref":        1.10,
    "amend":      1.05,
}

# Regex to find statute section mentions in chunk text
# Matches: "PPC 302", "Section 302 PPC", "Article 14", "MFLO 7", "CrPC 154"
_CITE_RE = re.compile(
    r'\b(PPC|CrPC|MFLO|QSO|PECA|CPC|MCA)\s+(?:Section\s+)?(\d+(?:[A-Z])?)'
    r'|(?:Section|Article)\s+(\d+(?:[A-Z])?)\s+(?:of\s+)?(?:the\s+)?'
    r'(Pakistan Penal Code|Code of Criminal Procedure|Muslim Family Laws Ordinance)',
    re.IGNORECASE
)

_AMEND_RE = re.compile(
    r'\b(amend|substitut|insert|replac|omit)\w*\s+(?:by|vide|through)',
    re.IGNORECASE
)

_DEFINED_BY_RE = re.compile(
    r'(?:as\s+defined|has\s+the\s+meaning\s+assigned)\s+in\s+(?:Section|Article)\s+(\d+)',
    re.IGNORECASE
)


def _make_node_id(statute: str, section_number: str, chunk_id: str) -> str:
    """Stable node identifier."""
    if statute and section_number:
        return f"{statute.lower().replace(' ', '_')}_{section_number}"
    return chunk_id or f"unknown_{hash(statute)}"


def _detect_relation(text: str) -> str:
    """Infer the relation type from chunk text."""
    if _DEFINED_BY_RE.search(text):
        return "defined_by"
    if _AMEND_RE.search(text):
        return "amend"
    cites = _CITE_RE.findall(text)
    if cites:
        return "cite"
    return "ref"


def build_graph() -> nx.DiGraph:
    """
    Extract all statute sections from ChromaDB collections and build
    a directed cross-reference graph.
    """
    connect_chroma()
    chroma = get_chroma()
    G = nx.DiGraph()

    print(f"Building law graph from {len(COLLECTIONS)} collections...")

    for collection_name in COLLECTIONS:
        try:
            col    = chroma.get_collection(collection_name)
            result = col.get(include=["documents", "metadatas"])
        except Exception as e:
            print(f"  ⚠ Could not load {collection_name}: {e}")
            continue

        docs      = result.get("documents", [])
        metadatas = result.get("metadatas", [])
        print(f"  {collection_name}: {len(docs)} chunks")

        for text, meta in zip(docs, metadatas):
            statute        = meta.get("statute", "")
            section_number = meta.get("section_number", "")
            chunk_id       = meta.get("chunk_id", "")
            province       = meta.get("province", "federal")
            law_type       = meta.get("law_type", "")

            src_id = _make_node_id(statute, section_number, chunk_id)

            # Add source node with metadata
            G.add_node(src_id, **{
                "statute":        statute,
                "section_number": section_number,
                "chunk_id":       chunk_id,
                "province":       province,
                "law_type":       law_type,
                "collection":     collection_name,
            })

            # Find cross-references in text
            citations = _CITE_RE.findall(text)
            for match in citations:
                # match is a tuple from the regex groups
                if match[0] and match[1]:
                    ref_statute = match[0].upper()
                    ref_section = match[1]
                elif match[2] and match[3]:
                    ref_statute = match[3]
                    ref_section = match[2]
                else:
                    continue

                tgt_id       = _make_node_id(ref_statute, ref_section, "")
                relation     = _detect_relation(text)
                weight       = RELATION_WEIGHTS.get(relation, 1.0)

                # Add a stub node for the target if it doesn't exist yet
                if not G.has_node(tgt_id):
                    G.add_node(tgt_id, statute=ref_statute, section_number=ref_section)

                if src_id != tgt_id:
                    G.add_edge(src_id, tgt_id, relation=relation, weight=weight)

    print(f"\nGraph built: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")
    return G


def save_graph(G: nx.DiGraph, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        pickle.dump(G, f, protocol=pickle.HIGHEST_PROTOCOL)
    print(f"Saved to: {path}")


if __name__ == "__main__":
    G = build_graph()
    save_graph(G, OUTPUT_PATH)
    print("\nSample nodes:")
    for node in list(G.nodes)[:5]:
        print(f"  {node}: {dict(list(G.nodes[node].items())[:3])}")
