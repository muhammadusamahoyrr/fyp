"""Test retrieval + generation + hallucination nodes end-to-end."""
import asyncio
import sys
sys.path.insert(0, ".")
from app.db.chroma import connect_chroma
connect_chroma()

from app.ai.nodes.retrieval_node import retrieval_node
from app.ai.nodes.generation_node import generation_node
from app.ai.nodes.hallucination_node import hallucination_node

state = {
    "query": "My landlord beat me up. What can I do under Pakistani law?",
    "case_type": "criminal",
    "province": "punjab",
    "language": "en",
    "retrieved_chunks": [],
    "reranked_chunks": [],
    "answer": "",
    "citations": [],
    "confidence": 0.0,
}

async def main():
    print("=== RETRIEVAL ===")
    ret = await retrieval_node(state)
    state.update(ret)
    print(f"Retrieved {len(state['reranked_chunks'])} chunks")
    for c in state["reranked_chunks"][:6]:
        print(f"  {c['statute']} | {c['content'][:80]}")

    print()
    print("=== GENERATION ===")
    gen = await generation_node(state)
    state.update(gen)
    print(state["answer"][:600])

    print()
    print("=== HALLUCINATION ===")
    hall = await hallucination_node(state)
    state.update(hall)
    print("is_grounded:", state.get("is_grounded"))
    print("confidence:", state.get("confidence"))
    print("answer (first 200):", state.get("answer", "")[:200])

if __name__ == "__main__":
    asyncio.run(main())

