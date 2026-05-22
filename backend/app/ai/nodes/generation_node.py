import json

from app.ai.graph.state import AgentState
from app.ai.llm import get_llm
from app.ai.nodes._history import format_history

DISCLAIMER = (
    "\n\n---\n"
    "*This information is for general guidance only and does not constitute legal advice. "
    "Please consult a qualified Pakistani lawyer for your specific situation.*"
)

# IRAC-style (Issue, Rule, Application, Conclusion) structured prompts.
_SYSTEM_EN = """\
You are an expert Pakistani legal assistant. Using ONLY the law sections provided below, answer the user's legal question in this exact structure:

**Issue:**
[One sentence: what is the core legal question?]

**Applicable Law:**
[List only the sections from the provided context. Format: "PPC Section 302 — [short title]"]

**Legal Analysis:**
[Apply the law to the stated facts. Reference section numbers explicitly. Be specific.]

**Conclusion:**
[Clear, direct answer to the user's question.]

**Recommended Actions:**
1. [First step the user should take]
2. [Second step]
3. [If applicable, third step]

**Risks & Limitations:**
[Important caveats, time limits, or gaps in the provided information]

Rules:
- Cite ONLY section numbers that appear in the provided context — never invent citations
- Write in plain English a non-lawyer can understand
- On the very last line, output ONLY this JSON (nothing else after it): {"confidence": 0.85}"""

_SYSTEM_UR = """\
آپ ایک ماہر پاکستانی قانونی معاون ہیں۔ صرف نیچے دی گئی قانونی دفعات استعمال کرتے ہوئے اس ڈھانچے میں جواب دیں:

**مسئلہ:**
[ایک جملے میں: بنیادی قانونی سوال کیا ہے؟]

**قابل اطلاق قانون:**
[صرف وہ دفعات جو سیاق میں موجود ہیں۔ مثال: "پی پی سی دفعہ 302 — قتل"]

**قانونی تجزیہ:**
[دی گئی حقائق پر قانون کا اطلاق کریں۔ دفعہ نمبر واضح طور پر بیان کریں۔]

**نتیجہ:**
[صارف کے سوال کا واضح جواب۔]

**تجویز کردہ اقدامات:**
1. [پہلا قدم]
2. [دوسرا قدم]
3. [اگر ضروری ہو، تیسرا قدم]

**خطرات اور حدود:**
[اہم احتیاط، وقت کی حدود، یا معلومات میں کمی]

اصول:
- صرف سیاق میں دکھائی گئی دفعات کا حوالہ دیں — نئی دفعات نہ گھڑیں
- آسان زبان میں جواب دیں
- آخری لائن میں صرف یہ JSON لکھیں: {"confidence": 0.85}"""


def _format_chunks(chunks: list[dict]) -> str:
    lines = []
    for i, c in enumerate(chunks[:8], 1):
        statute = c.get("statute") or c.get("source_file", "Pakistani Law")
        section = f" Section {c['section_number']}" if c.get("section_number") else ""
        lines.append(f"[{i}] {statute}{section}\n{c['content'][:600]}")
    return "\n\n".join(lines)


_SYSTEM_DEEPEN = """\
You are an expert Pakistani legal assistant. The user wants more detail on the previous answer.

Using the retrieved law sections and the conversation history below, elaborate on the specific aspect the user is asking about.
Keep the same IRAC structure but go deeper — add more legal analysis, cite additional sections, and explain implications.

On the very last line, output ONLY this JSON: {"confidence": 0.85}"""


def generation_node(state: AgentState) -> dict:
    attempts  = state.get("generation_attempts", 0) + 1
    prev_conf = state.get("confidence", 0.0)

    llm     = get_llm()
    context = _format_chunks(state.get("reranked_chunks", []))
    lang    = state.get("language", "en")
    intent  = state.get("followup_intent")

    # Pick system prompt based on intent
    if intent == "deepen":
        system = _SYSTEM_DEEPEN
    else:
        system = _SYSTEM_UR if lang in ("ur", "roman_urdu") else _SYSTEM_EN

    # Use normalized query for generation so Urdu queries are standard script
    question = state.get("normalized_query") or state["query"]

    # On generation retry: use only top-ranked chunks (stricter grounding)
    if attempts > 1:
        chunks_to_use = state.get("reranked_chunks", [])[:4]
        context = _format_chunks(chunks_to_use)

    history = format_history(state, max_turns=4)
    history_section = f"\nConversation context:\n{history}\n" if history else ""

    response = llm.invoke([
        {"role": "system", "content": system},
        {"role": "user", "content": (
            f"Question: {question}\n"
            f"Case type: {state.get('case_type', 'civil')}\n"
            f"Province: {state.get('province', 'federal')}\n"
            f"{history_section}\n"
            f"Retrieved law sections:\n{context}"
        )},
    ])

    raw        = response.content.strip()
    confidence = 0.3

    lines = raw.splitlines()
    try:
        last       = json.loads(lines[-1])
        confidence = float(last.get("confidence", 0.3))
        raw        = "\n".join(lines[:-1]).strip()
    except (json.JSONDecodeError, IndexError, ValueError):
        pass

    citations = [
        {
            "statute": c["statute"],
            "section": c["section_number"],
            "source":  c["source_file"],
        }
        for c in state.get("reranked_chunks", [])[:5]
        if c.get("section_number")
    ]

    return {
        "answer":              raw + DISCLAIMER,
        "citations":           citations,
        "confidence":          confidence,
        "generation_attempts": attempts,
        "prev_confidence":     prev_conf,
    }
