"""Graph-guided hop-2 expansion over the statute cross-reference graph.

Hop-2 previously worked by regex-extracting statute references from the hop-1
results and issuing them as a TEXT query to the same retriever — hoping BM25
would surface the referenced provision. That is lossy: the reference is exact,
the re-query is fuzzy, and the graph built by scripts/build_law_graph.py was
never loaded by anything.

This resolves references precisely instead: a hop-1 chunk is looked up by
(statute, section), its outgoing edges are followed, and the chunk ids of the
referenced sections are returned directly. Edges are typed and weighted, so a
definitional cross-link outranks a passing mention.

Degrades to empty rather than raising. A missing or stale graph file must fall
back to the text re-query, not fail the search.

The graph is stored as JSON, not pickle. It is a locally generated artifact, but
unpickling executes arbitrary code by design, and a build output that gets copied
between machines or restored from a backup is exactly the kind of file that
should not have that property. NetworkX serialises node-link JSON natively, so
the safer format costs nothing and is inspectable besides.
"""
from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

GRAPH_PATH = Path(__file__).resolve().parents[3] / "chroma_data" / "law_graph.json"

# Enough to pull in the provisions a section actually depends on without
# swamping the hop-1 results it is meant to supplement.
DEFAULT_MAX_TARGETS = 8


@lru_cache(maxsize=1)
def get_graph():
    """Load the graph once per process. Returns None when unavailable."""
    try:
        if not GRAPH_PATH.exists():
            logger.info("law_graph: %s not found — hop-2 falls back to text re-query",
                        GRAPH_PATH)
            return None
        import networkx as nx
        with open(GRAPH_PATH, encoding="utf-8") as f:
            g = nx.node_link_graph(json.load(f), directed=True, edges="edges")
        logger.info("law_graph: loaded %d nodes, %d edges",
                    g.number_of_nodes(), g.number_of_edges())
        return g
    except Exception:
        logger.exception("law_graph: could not load graph — falling back")
        return None


def node_id(statute: str, section: str) -> str:
    """Must match scripts/build_law_graph.py exactly or nothing resolves."""
    return f"{statute.lower().replace(' ', '_')}::{section}"


def expand(refs: list[tuple[str, str]],
           max_targets: int = DEFAULT_MAX_TARGETS) -> list[str]:
    """
    Follow cross-references from (statute, section) pairs to referenced chunk ids.

    Returns chunk ids ordered by edge weight, so definitional links
    (`defined_by`, 1.20) come before passing citations (`ref`, 1.10). Empty when
    the graph is unavailable — the caller then keeps its text-query fallback.
    """
    g = get_graph()
    if g is None or not refs:
        return []

    scored: dict[str, float] = {}
    for statute, section in refs:
        if not statute or not section:
            continue
        src = node_id(statute, section)
        if not g.has_node(src):
            continue
        for _, tgt, data in g.out_edges(src, data=True):
            weight = float(data.get("weight", 1.0))
            for cid in (g.nodes[tgt].get("chunk_ids") or []):
                if not cid:
                    continue
                # A section referenced from several places is more central, so
                # keep the strongest signal rather than the first seen.
                if scored.get(cid, 0.0) < weight:
                    scored[cid] = weight

    ranked = sorted(scored.items(), key=lambda kv: -kv[1])
    return [cid for cid, _ in ranked[:max_targets]]


def stats() -> dict:
    g = get_graph()
    if g is None:
        return {"available": False}
    return {
        "available": True,
        "nodes": g.number_of_nodes(),
        "edges": g.number_of_edges(),
    }
