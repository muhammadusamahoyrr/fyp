"""What the pipeline is doing, in words a waiting user can act on.

ONE VOCABULARY, TWO TRANSPORTS

The client chat surface pushes stages down a WebSocket. The lawyer research
surface has no socket — it is one long HTTP request — so it records the stage on
the turn and the page reads it. The transports could hardly be more different;
the STAGES must not be, or the same pipeline would describe itself two ways
depending on which page you were looking at, and a user comparing notes with
their lawyer would be told different things about the same machinery.

So the map lives here, imported by both, and neither owns it.

WHY THESE STAGES AND NOT MORE

"Thinking" for thirty seconds tells someone nothing except that the thing is
slow; it is the same word whether we are reading statutes or writing prose. The
five below are the distinctions a waiting person can actually act on — a search
that runs long means a hard question, a check that runs long means a shaky
answer — and they are derived from the nodes really executing rather than from a
timer pretending to know.

Nodes not listed emit no stage. A stage that does not change what the user
understands is noise, and noise is what stops people reading the stage that
matters.
"""
from __future__ import annotations

from typing import Optional

# node name → (stage id, the words shown to a user)
NODE_STAGES: dict[str, tuple[str, str]] = {
    "triage_node":            ("understanding", "Reading your question"),
    "classifier_node":        ("understanding", "Reading your question"),
    "retrieval_node":         ("searching",     "Searching Pakistani law"),
    "tool_node":              ("searching",     "Checking the statute books"),
    "retrieval_grader_node":  ("weighing",      "Weighing the sources found"),
    "generation_node":        ("writing",       "Writing the answer"),
    "hallucination_node":     ("checking",      "Checking the answer against its sources"),
    "finalizer_node":         ("checking",      "Checking the answer against its sources"),
}

# The order a turn passes through them. Used to refuse a BACKWARDS stage: the
# graph legitimately re-enters generation after a failed grounding check, and a
# progress line that jumped from "checking" back to "writing" would read as the
# system losing its place rather than as it retrying.
STAGE_ORDER: tuple[str, ...] = (
    "understanding", "searching", "weighing", "writing", "checking",
)


def stage_for(node_name: Optional[str]) -> Optional[tuple[str, str]]:
    """The stage a node announces, or None for nodes the user need not see."""
    return NODE_STAGES.get(node_name or "")


def node_name_from(serialized: Optional[dict], kwargs: dict) -> str:
    """The node's name, wherever LangChain happened to put it."""
    return (serialized or {}).get("name") or kwargs.get("name") or ""


def is_forward(previous: Optional[str], candidate: str) -> bool:
    """Is `candidate` at or beyond `previous` in the pipeline?

    A retry sends the graph back to an earlier node, and the honest thing to
    show for that is the furthest point reached, not a rewind. Unknown stages
    are allowed through rather than silently dropped — a stage added to the map
    without being added to the order should still appear.
    """
    if previous is None:
        return True
    if previous not in STAGE_ORDER or candidate not in STAGE_ORDER:
        return True
    return STAGE_ORDER.index(candidate) >= STAGE_ORDER.index(previous)
