from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from app.ai.graph.edges import (
    route_after_classifier,
    route_after_grader,
    route_after_grader_intake,
    route_after_hallucination,
    route_after_triage,
)
from app.ai.graph.state import AgentState
from app.ai.nodes.classifier_node       import classifier_node
from app.ai.nodes.clarification_node    import clarification_node
from app.ai.nodes.fact_gap_node         import fact_gap_node
from app.ai.nodes.finalizer_node        import finalizer_node
from app.ai.nodes.generation_node       import generation_node
from app.ai.nodes.hallucination_node    import hallucination_node
from app.ai.nodes.retrieval_grader_node import retrieval_grader_node
from app.ai.nodes.retrieval_node        import retrieval_node
from app.ai.nodes.triage_node           import triage_node


def build_chat_graph():
    """
    9-node chat graph with classifier-first routing and interrupt() HITL.

    Flow:
        classifier_node
          └───────────────────────────────► triage_node
                                              ├─ off_topic ────────► finalizer_node → END
                                              ├─ missing_info ─────► clarification_node (interrupt)
                                              │                        └─────────────────► fact_gap_node
                                              └─ ok ───────────────► fact_gap_node
                                                                       └─ proceed ► retrieval_node
                                                                                    └─ retrieval_grader_node
                                                                                         ├─ poor+budget ► retrieval_node
                                                                                         └─ ok ► generation_node
                                                                                                   └─ hallucination_node
                                                                                                        ├─ not grounded+budget ► generation_node
                                                                                                        └─ done ► finalizer_node → END
    """
    builder = StateGraph(AgentState)

    # Register all nodes
    builder.add_node("classifier_node",       classifier_node)
    builder.add_node("clarification_node",    clarification_node)  # uses interrupt()
    builder.add_node("triage_node",           triage_node)
    builder.add_node("fact_gap_node",         fact_gap_node)
    builder.add_node("retrieval_node",        retrieval_node)
    builder.add_node("retrieval_grader_node", retrieval_grader_node)
    builder.add_node("generation_node",       generation_node)
    builder.add_node("hallucination_node",    hallucination_node)
    builder.add_node("finalizer_node",        finalizer_node)

    # Entry point is now classifier (fast, no LLM cost)
    builder.set_entry_point("classifier_node")

    # classifier ALWAYS proceeds to triage first to catch gibberish
    builder.add_edge("classifier_node", "triage_node")

    # triage branches based on off-topic vs missing info vs ready
    builder.add_conditional_edges(
        "triage_node",
        route_after_triage,
        {
            "finalizer_node": "finalizer_node",
            "clarification_node": "clarification_node",
            "fact_gap_node": "fact_gap_node"
        },
    )

    # clarification always proceeds to fact_gap after collecting user input
    builder.add_edge("clarification_node", "fact_gap_node")

    # fact_gap_node now uses interrupt() internally — always proceeds to retrieval
    builder.add_edge("fact_gap_node", "retrieval_node")

    builder.add_edge("retrieval_node", "retrieval_grader_node")

    builder.add_conditional_edges(
        "retrieval_grader_node",
        route_after_grader,
        {"retrieval_node": "retrieval_node", "generation_node": "generation_node"},
    )

    builder.add_edge("generation_node", "hallucination_node")

    builder.add_conditional_edges(
        "hallucination_node",
        route_after_hallucination,
        {"generation_node": "generation_node", "finalizer_node": "finalizer_node"},
    )

    builder.add_edge("finalizer_node", END)

    # interrupt() inside clarification_node requires MemorySaver to persist state
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
