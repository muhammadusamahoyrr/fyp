from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from app.ai.graph.edges import (
    route_after_fact_gap,
    route_after_grader,
    route_after_grader_intake,
    route_after_hallucination,
    route_after_triage,
)
from app.ai.graph.state import AgentState
from app.ai.nodes.fact_gap_node         import fact_gap_node
from app.ai.nodes.finalizer_node        import finalizer_node
from app.ai.nodes.generation_node       import generation_node
from app.ai.nodes.hallucination_node    import hallucination_node
from app.ai.nodes.retrieval_grader_node import retrieval_grader_node
from app.ai.nodes.retrieval_node        import retrieval_node
from app.ai.nodes.triage_node           import triage_node


def build_chat_graph():
    """
    7-node chat graph with convergence control.

    Flow:
        triage_node
          ├─ off_topic ──────────────────────────────────────► finalizer_node → END
          └─ legal ──► fact_gap_node
                         ├─ needs_clarification ─────────────► END  (HITL breakpoint)
                         └─ proceed ──► retrieval_node
                                          └─ retrieval_grader_node
                                               ├─ poor + budget ──► retrieval_node  (≤3 retries)
                                               └─ ok ──► generation_node
                                                           └─ hallucination_node
                                                                ├─ not grounded + budget ──► generation_node  (≤2 retries)
                                                                └─ done ──► finalizer_node → END

    Simple path (enough facts from triage):
        triage → fact_gap (single check, no HITL) → retrieval → grader → generation → hallucination → finalizer

    HITL path (critical facts missing):
        triage → fact_gap → END  [client sends clarification answer]
        triage → fact_gap (clarification_attempts≥1 → bypass) → retrieval → ...
    """
    builder = StateGraph(AgentState)

    builder.add_node("triage_node",           triage_node)
    builder.add_node("fact_gap_node",         fact_gap_node)
    builder.add_node("retrieval_node",        retrieval_node)
    builder.add_node("retrieval_grader_node", retrieval_grader_node)
    builder.add_node("generation_node",       generation_node)
    builder.add_node("hallucination_node",    hallucination_node)
    builder.add_node("finalizer_node",        finalizer_node)

    builder.set_entry_point("triage_node")

    builder.add_conditional_edges(
        "triage_node",
        route_after_triage,
        {"finalizer_node": "finalizer_node", "fact_gap_node": "fact_gap_node"},
    )

    builder.add_conditional_edges(
        "fact_gap_node",
        route_after_fact_gap,
        {"retrieval_node": "retrieval_node", "END": END},
    )

    # retrieval_node always feeds into the grader
    builder.add_edge("retrieval_node", "retrieval_grader_node")

    builder.add_conditional_edges(
        "retrieval_grader_node",
        route_after_grader,
        {"retrieval_node": "retrieval_node", "generation_node": "generation_node"},
    )

    # generation always feeds into hallucination check
    builder.add_edge("generation_node", "hallucination_node")

    builder.add_conditional_edges(
        "hallucination_node",
        route_after_hallucination,
        {"generation_node": "generation_node", "finalizer_node": "finalizer_node"},
    )

    builder.add_edge("finalizer_node", END)

    return builder.compile(checkpointer=MemorySaver())


def build_intake_graph():
    """
    Intake graph with retrieval quality gate and action grounding check.

    Flow:
        retrieval_node
            └── retrieval_grader_node
                    ├── relevance < 0.4 AND attempts < 2 → retrieval_node (retry once)
                    └── ok ──► intake_node
                                   └── intake_hallucination_node → END

    Used only by convert_to_case(). Does not use the full chat convergence loop.
    """
    from app.ai.nodes.intake_node import intake_node
    from app.ai.nodes.intake_hallucination_node import intake_hallucination_node

    builder = StateGraph(AgentState)
    builder.add_node("retrieval_node",           retrieval_node)
    builder.add_node("retrieval_grader_node",    retrieval_grader_node)
    builder.add_node("intake_node",              intake_node)
    builder.add_node("intake_hallucination_node", intake_hallucination_node)

    builder.set_entry_point("retrieval_node")
    builder.add_edge("retrieval_node", "retrieval_grader_node")
    builder.add_conditional_edges(
        "retrieval_grader_node",
        route_after_grader_intake,
        {"retrieval_node": "retrieval_node", "intake_node": "intake_node"},
    )
    builder.add_edge("intake_node",              "intake_hallucination_node")
    builder.add_edge("intake_hallucination_node", END)

    return builder.compile()


chat_graph   = build_chat_graph()
intake_graph = build_intake_graph()
