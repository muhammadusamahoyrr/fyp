from langgraph.graph import END, StateGraph

from app.ai.graph.checkpointer import MongoDBSaver
from app.ai.graph.edges import (
    route_after_cache,
    route_after_classifier,
    route_after_gatekeeper,
    route_after_grader,
    route_after_grader_intake,
    route_after_hallucination,
    route_after_triage,
)
from app.ai.graph.state import AgentState
from app.ai.nodes.cache_node            import cache_lookup_node
from app.ai.nodes.classifier_node       import classifier_node
from app.ai.nodes.clarification_node    import clarification_node
from app.ai.nodes.fact_gap_node         import fact_gap_node
from app.ai.nodes.finalizer_node        import finalizer_node
from app.ai.nodes.gatekeeper_node       import gatekeeper_node
from app.ai.nodes.generation_node       import generation_node
from app.ai.nodes.hallucination_node    import hallucination_node
from app.ai.nodes.retrieval_grader_node import retrieval_grader_node
from app.ai.nodes.retrieval_node        import retrieval_node
from app.ai.nodes.tool_node             import tool_node
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
                                                                       └─ cache_lookup_node
                                                                            ├─ hit ► finalizer_node → END
                                                                            └─ miss ► tool_node (bail / court-fee /
                                                                                      inheritance / case-law engines)
                                                                                    └─ retrieval_node
                                                                                    └─ retrieval_grader_node
                                                                                         ├─ poor+budget ► retrieval_node
                                                                                         └─ ok ► generation_node
                                                                                                   └─ hallucination_node
                                                                                                        ├─ not grounded+budget ► generation_node
                                                                                                        └─ done ► finalizer_node → END
    """
    builder = StateGraph(AgentState)

    # Register all nodes
    builder.add_node("gatekeeper_node",       gatekeeper_node)  # injection/jailbreak gate
    builder.add_node("classifier_node",       classifier_node)
    builder.add_node("clarification_node",    clarification_node)  # uses interrupt()
    builder.add_node("triage_node",           triage_node)
    builder.add_node("fact_gap_node",         fact_gap_node)
    builder.add_node("cache_lookup_node",     cache_lookup_node)
    builder.add_node("tool_node",             tool_node)  # deterministic legal engines
    builder.add_node("retrieval_node",        retrieval_node)
    builder.add_node("retrieval_grader_node", retrieval_grader_node)
    builder.add_node("generation_node",       generation_node)
    builder.add_node("hallucination_node",    hallucination_node)
    builder.add_node("finalizer_node",        finalizer_node)

    # Entry point is the gatekeeper — blocks prompt-injection / jailbreak
    # attempts before any other processing.
    builder.set_entry_point("gatekeeper_node")

    # gatekeeper: clean → classifier, injection detected → straight to finalizer
    builder.add_conditional_edges(
        "gatekeeper_node",
        route_after_gatekeeper,
        {"classifier_node": "classifier_node", "finalizer_node": "finalizer_node"},
    )

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

    # fact_gap_node now uses interrupt() internally — proceeds to the cache lookup
    builder.add_edge("fact_gap_node", "cache_lookup_node")

    # Semantic cache: a hit skips the whole retrieval→generation chain.
    builder.add_conditional_edges(
        "cache_lookup_node",
        route_after_cache,
        {"finalizer_node": "finalizer_node", "tool_node": "tool_node"},
    )

    # tool_node always falls through to retrieval. It is a PLAIN edge, not part
    # of the grader's retry loop — a retrieval retry must not re-run the engines
    # (they are deterministic, so a second call cannot produce a better answer,
    # and re-running them would just burn tokens).
    builder.add_edge("tool_node", "retrieval_node")

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

    # interrupt() inside clarification_node suspends the run mid-graph, so the
    # state MUST outlive the process that created it. MemorySaver kept it in RAM:
    # a restart, or a second uvicorn worker picking up the user's reply, silently
    # lost the pending clarification. Mongo-backed checkpoints survive both.
    return builder.compile(checkpointer=MongoDBSaver())


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
