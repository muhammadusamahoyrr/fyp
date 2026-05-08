from app.ai.graph.state import AgentState
from app.ai.llm import get_llm

_MAX_TO_GRADE = 8

# One LLM call returns a binary relevance array: [1,0,1,...] — one digit per chunk.
_SYSTEM = """\
You are a legal document relevance grader for Pakistani law.

Given the user's query and a numbered list of law section excerpts, decide which chunks are relevant.

A chunk is relevant if it contains legal principles or statutory text that directly addresses the user's legal situation.

Return ONLY a JSON array of 0s and 1s — one entry per chunk in order.
Example for 5 chunks: [1,0,1,1,0]
No explanation. No other text."""


def retrieval_grader_node(state: AgentState) -> dict:
    chunks     = state.get("retrieved_chunks", [])
    prev_score = state.get("relevance_score", 0.0)

    if not chunks:
        return {
            "reranked_chunks":      [],
            "prev_relevance_score": prev_score,
            "relevance_score":      0.0,
        }

    to_grade = chunks[:_MAX_TO_GRADE]
    rest     = chunks[_MAX_TO_GRADE:]   # pass through ungraded

    context = "\n\n".join(
        f"[{i+1}] {c.get('statute', '')} "
        f"{'Section ' + c['section_number'] if c.get('section_number') else ''}\n"
        f"{c['content'][:300]}"
        for i, c in enumerate(to_grade)
    )

    try:
        llm      = get_llm()
        response = llm.invoke([
            {"role": "system", "content": _SYSTEM},
            {"role": "user",   "content": (
                f"User query: {state['query']}\n\n"
                f"Chunks to grade:\n{context}"
            )},
        ])
        import json
        grades = json.loads(response.content.strip())

        graded  = [c for c, g in zip(to_grade, grades) if g == 1]
        n_kept  = len(graded)
        score   = round(n_kept / max(len(to_grade), 1), 3)

    except Exception:
        # Fallback: keep all chunks, score proportional to count
        graded = to_grade
        score  = round(min(len(to_grade) / 10.0, 1.0), 3)

    return {
        "reranked_chunks":      graded + rest,
        "prev_relevance_score": prev_score,
        "relevance_score":      score,
    }
