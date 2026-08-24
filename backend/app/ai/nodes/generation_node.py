import asyncio
import re

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


# Appended to the system prompt only when case law was retrieved, so the model
# is never told to cite precedent it doesn't have.
_CASE_LAW_RIDER_EN = """

You are ALSO given RELEVANT CASE LAW (Lahore High Court judgments). When a judgment directly supports your analysis, add this section right after **Applicable Law:**

**Case Law:**
- [Neutral citation] — [one-line holding, e.g. "2026LHC4194 — post-arrest bail granted in a narcotics case where the recovery was unwitnessed"]

Cite ONLY judgments shown in the case-law context — never invent a citation. Note that these are High Court precedents (persuasive, not binding on other High Courts). If none are truly on point, omit the Case Law section entirely.

Reminder: after all sections, the VERY LAST line of your output must still be ONLY this JSON and nothing after it: {"confidence": 0.85}"""

_CASE_LAW_RIDER_UR = """

آپ کو متعلقہ عدالتی فیصلے (لاہور ہائیکورٹ) بھی دیے گئے ہیں۔ اگر کوئی فیصلہ آپ کے تجزیے کی تائید کرتا ہو تو **قابل اطلاق قانون:** کے فوراً بعد یہ سیکشن شامل کریں:

**عدالتی نظائر:**
- [حوالہ] — [ایک سطر میں فیصلے کا خلاصہ]

صرف دیے گئے فیصلوں کا حوالہ دیں — نیا حوالہ نہ گھڑیں۔ اگر کوئی فیصلہ موزوں نہ ہو تو یہ سیکشن نہ لکھیں۔

یاد رہے: تمام سیکشنز کے بعد، آپ کے جواب کی آخری لائن صرف یہ JSON ہونی چاہیے: {"confidence": 0.85}"""


def _format_case_law(chunks: list[dict]) -> str:
    lines = []
    for c in chunks:
        cite = c.get("citation") or _case_reference(c)
        title = c.get("title", "")
        snippet = (c.get("content") or "")[:400]
        lines.append(f"- {cite} ({title})\n  {snippet}")
    return "\n".join(lines)


# The model tends to parrot whichever heading it is shown ("according to the
# statutory determination, ..."), which exposes internal machinery to a user who
# should just be reading a legal answer. Prompting reduces this but does not
# guarantee it, so the attribution phrase is also stripped deterministically.
_META_ATTRIBUTION = re.compile(
    r"(?i)\b(?:according to|based on|as per|per|from)\s+(?:the|these|this)\s+"
    # The model slips adjectives in ("the PROVIDED statutory determination"), so
    # allow a couple of filler words before the term itself.
    r"(?:\w+\s+){0,2}"
    r"(?:statutory determinations?|computed results?|engine results?|"
    r"authoritative[a-z ]*results?|tool results?|verified facts?)\s*,?\s*"
)


def _strip_meta_attribution(text: str) -> str:
    """Remove 'According to the statutory determination, ...' style prefixes."""
    def _fix(match: re.Match) -> str:
        return ""

    cleaned = _META_ATTRIBUTION.sub(_fix, text)
    # Re-capitalise any sentence left starting lowercase by the removal.
    return re.sub(
        r"(^|(?<=[.!?:]\s)|(?<=\n))([a-z])",
        lambda m: m.group(1) + m.group(2).upper(),
        cleaned,
    )


def _format_tool_results(results: list[dict]) -> str:
    """Render deterministic engine output for the prompt.

    Errors are rendered too, and on purpose: if the bail engine could not find
    the section, the model must know that and say so, rather than silently
    falling back to guessing from statute text.
    """
    lines = []
    for r in results:
        payload = r.get("result")
        lines.append(f"- {r['tool']}({_compact_args(r.get('args', {}))}) →\n  {payload}")
    return "\n".join(lines)


def _compact_args(args: dict) -> str:
    return ", ".join(f"{k}={v!r}" for k, v in args.items())


_TOOL_RIDER = """

STATUTORY DETERMINATION
The question below includes a STATUTORY DETERMINATION: a figure or conclusion
derived directly from the governing statute. It is exact. It OVERRIDES anything
in the retrieved text that contradicts it.
- State its figures and conclusions exactly. Never recompute or round them.
- Cite its `legal_basis` under "Applicable Law" — that IS the applicable law,
  even when no statute chunk was retrieved. Never write "no applicable law
  sections are provided" when a statutory determination is present.
- Carry through any `disclaimer`, `verify` or `warnings` field it returns.
- If it carries an `error`, or `found` is false, tell the user that precise point
  could not be confirmed — do NOT fill the gap with a guess.
- Write the conclusion DIRECTLY, in your own voice. The user is reading a legal
  answer, not a system trace.
    GOOD: "The court fee is PKR 37,500 — an ad valorem fee of 7.5% of the claim
           value under the Court Fees Act 1870 as amended in Punjab."
    BAD:  "According to the computed results / the engine / the statutory
           determination, the court fee is PKR 37,500."
  Never use the words "engine", "tool", "computed result", or "determination"
  to refer to where your information came from."""


def _format_chunks(chunks: list[dict]) -> str:
    lines = []
    for i, c in enumerate(chunks[:8], 1):
        raw_source = c.get("statute") or c.get("source_file", "Pakistani Law")
        # Web chunks store URLs in statute — show as "Web Source" for cleaner prompts
        if raw_source.startswith("http"):
            statute = "Web Source"
        else:
            statute = raw_source
        section = f" Section {c['section_number']}" if c.get("section_number") else ""
        lines.append(f"[{i}] {statute}{section}\n{c['content'][:600]}")
    return "\n\n".join(lines)


_SYSTEM_DEEPEN = """\
You are an expert Pakistani legal assistant. The user wants more detail on the previous answer.

Using the retrieved law sections and the conversation history below, elaborate on the specific aspect the user is asking about.
Keep the same IRAC structure but go deeper — add more legal analysis, cite additional sections, and explain implications.

On the very last line, output ONLY this JSON: {"confidence": 0.85}"""


async def generation_node(state: AgentState) -> dict:
    attempts  = state.get("generation_attempts", 0) + 1
    prev_conf = state.get("confidence", 0.0)

    llm     = get_llm()
    context = _format_chunks(state.get("reranked_chunks", []))
    lang    = state.get("language", "en")
    intent  = state.get("followup_intent")

    is_urdu   = lang in ("ur", "roman_urdu")
    case_law  = state.get("case_law_chunks", [])

    # Pick system prompt based on intent
    if intent == "deepen":
        system = _SYSTEM_DEEPEN
    else:
        system = _SYSTEM_UR if is_urdu else _SYSTEM_EN

    # Only instruct the model to cite precedent when precedent was actually found.
    if case_law:
        system = system + (_CASE_LAW_RIDER_UR if is_urdu else _CASE_LAW_RIDER_EN)

    # Use normalized query for generation so Urdu queries are standard script
    question = state.get("normalized_query") or state["query"]

    # On generation retry: use only top-ranked chunks (stricter grounding)
    if attempts > 1:
        chunks_to_use = state.get("reranked_chunks", [])[:4]
        context = _format_chunks(chunks_to_use)

    if case_law:
        context += "\n\nRELEVANT CASE LAW (Lahore High Court judgments):\n" + _format_case_law(case_law)

    # Deterministic engine output outranks retrieved text — tell the model so.
    tool_results = state.get("tool_results", [])
    if tool_results:
        system = system + _TOOL_RIDER

    history = format_history(state, max_turns=4)
    history_section = f"\nConversation context:\n{history}\n" if history else ""

    tool_section = (
        f"\nSTATUTORY DETERMINATION (exact — state it directly, in your own voice):\n"
        f"{_format_tool_results(tool_results)}\n"
        if tool_results else ""
    )

    response = await asyncio.to_thread(llm.invoke, [
        {"role": "system", "content": system},
        {"role": "user", "content": (
            f"Question: {question}\n"
            f"Case type: {state.get('case_type', 'civil')}\n"
            f"Province: {state.get('province', 'federal')}\n"
            f"{history_section}"
            f"{tool_section}\n"
            f"Retrieved law sections:\n{context}"
        )},
    ])

    raw        = response.content.strip()
    confidence = 0.3

    # Use regex over the whole response so trailing whitespace/blank lines don't break extraction
    m = re.search(r'\{"confidence":\s*(\d+\.?\d*)\}', raw)
    if m:
        try:
            confidence = float(m.group(1))
            raw        = raw[:m.start()].strip()
        except ValueError:
            pass

    if tool_results:
        raw = _strip_meta_attribution(raw)

    citations = [
        {
            "statute": c["statute"],
            "section": c["section_number"],
            "source":  c["source_file"],
        }
        for c in state.get("reranked_chunks", [])[:5]
        if c.get("section_number")
    ]

    # Judgment citations carry a court-PDF url + type so the frontend can link them;
    # `statute` doubles as the flat display label used by the string-based chip render.
    for c in case_law:
        citations.append({
            # Never fall back to the internal id dressed as a citation — that
            # string ends up in the citation slot a lawyer copies into a filing.
            "statute": c.get("citation") or _case_reference(c),
            "section": "",
            "source":  c.get("pdf_url", ""),
            "type":    "judgment",
            "url":     c.get("pdf_url", ""),
            "title":   c.get("title", ""),
        })

    return {
        "answer":              raw + DISCLAIMER,
        "citations":           citations,
        "confidence":          confidence,
        "generation_attempts": attempts,
        "prev_confidence":     prev_conf,
    }
