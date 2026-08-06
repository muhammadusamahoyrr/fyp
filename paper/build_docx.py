"""
build_docx.py — Generate the FIT/IEEE-formatted paper and a technical dossier.

Why a script rather than a hand-made .docx: the paper content changes as results
arrive, and regenerating is safer than hand-editing formatting into drift. Run
it again after editing the content blocks below.

IEEE conference format applied here (US Letter):
    margins      top 0.75in, bottom 1.0in, left/right 0.625in
    title        Times New Roman 24pt, centred, single column
    authors      11pt, centred, single column
    body         Times New Roman 10pt, justified, TWO columns
    abstract     9pt, bold-italic "Abstract—" lead-in
    headings     I., II., ... centred small-caps style
    subheadings  A., B., ... italic, left
    references   8pt

The title/author block spans both columns, so the document uses two sections:
a one-column section for the header and a two-column section for the body.
python-docx has no column API, so that is set through raw XML.

Usage:
    python paper/build_docx.py
"""
from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor

OUT_DIR = Path(__file__).resolve().parent

TODO_RED = RGBColor(0xC0, 0x00, 0x00)


# ── low-level helpers ─────────────────────────────────────────────────────────

def _set_columns(section, num: int, space_twips: int = 360) -> None:
    """Set column count on a section. 360 twips = 0.25in gutter (IEEE)."""
    sect_pr = section._sectPr
    cols = sect_pr.find(qn("w:cols"))
    if cols is None:
        cols = OxmlElement("w:cols")
        sect_pr.append(cols)
    cols.set(qn("w:num"), str(num))
    cols.set(qn("w:space"), str(space_twips))
    cols.set(qn("w:equalWidth"), "1")


def _margins(section, top=0.75, bottom=1.0, left=0.625, right=0.625) -> None:
    section.top_margin    = Inches(top)
    section.bottom_margin = Inches(bottom)
    section.left_margin   = Inches(left)
    section.right_margin  = Inches(right)


def _para(doc, text="", size=10, bold=False, italic=False, align="justify",
          space_after=4, space_before=0, font="Times New Roman",
          color=None, first_line_indent=None):
    p = doc.add_paragraph()
    p.alignment = {
        "left":    WD_ALIGN_PARAGRAPH.LEFT,
        "center":  WD_ALIGN_PARAGRAPH.CENTER,
        "justify": WD_ALIGN_PARAGRAPH.JUSTIFY,
    }[align]
    pf = p.paragraph_format
    pf.space_after  = Pt(space_after)
    pf.space_before = Pt(space_before)
    pf.line_spacing = 1.0
    if first_line_indent is not None:
        pf.first_line_indent = Inches(first_line_indent)
    if text:
        run = p.add_run(text)
        run.font.name = font
        run.font.size = Pt(size)
        run.bold = bold
        run.italic = italic
        if color is not None:
            run.font.color.rgb = color
    return p


def _rich(doc, chunks, size=10, align="justify", space_after=4,
          first_line_indent=0.2):
    """Paragraph from (text, bold, italic[, color]) tuples."""
    p = doc.add_paragraph()
    p.alignment = {
        "left":    WD_ALIGN_PARAGRAPH.LEFT,
        "center":  WD_ALIGN_PARAGRAPH.CENTER,
        "justify": WD_ALIGN_PARAGRAPH.JUSTIFY,
    }[align]
    pf = p.paragraph_format
    pf.space_after  = Pt(space_after)
    pf.line_spacing = 1.0
    if first_line_indent:
        pf.first_line_indent = Inches(first_line_indent)
    for chunk in chunks:
        text, bold, italic = chunk[0], chunk[1], chunk[2]
        color = chunk[3] if len(chunk) > 3 else None
        run = p.add_run(text)
        run.font.name = "Times New Roman"
        run.font.size = Pt(size)
        run.bold, run.italic = bold, italic
        if color is not None:
            run.font.color.rgb = color
    return p


def _heading(doc, numeral, text):
    _para(doc, f"{numeral}.  {text.upper()}", size=10, bold=False,
          align="center", space_before=10, space_after=4)


def _subheading(doc, letter, text):
    _para(doc, f"{letter}.  {text}", size=10, italic=True, align="left",
          space_before=6, space_after=3)


def _todo(doc, text):
    _rich(doc, [("[TODO: ", True, False, TODO_RED),
                (text, False, True, TODO_RED),
                ("]", True, False, TODO_RED)], first_line_indent=0.2)


def _body(doc, text):
    _para(doc, text, size=10, align="justify", first_line_indent=0.2)


# ═════════════════════════════════════════════════════════════════════════════
#  THE PAPER
# ═════════════════════════════════════════════════════════════════════════════

TITLE = ("Grounded and Auditable: Tool-Augmented Retrieval-Generation with "
         "Selective Abstention for Legal Question Answering in Low-Resource, "
         "Code-Switched Jurisdictions")

ABSTRACT = (
    "Retrieval-augmented generation (RAG) is increasingly applied to legal "
    "question answering, but deployments are overwhelmingly English and target "
    "common-law or EU jurisdictions, and they are evaluated on answer quality "
    "alone. Two properties that matter more in legal practice are largely "
    "unmeasured: whether a system knows when not to answer, and whether a given "
    "answer can later be audited. We present a legal question-answering "
    "architecture for Pakistani law that addresses both. The system combines "
    "hybrid lexical-dense retrieval over a bilingual statute corpus with a set "
    "of deterministic statutory engines, whose computed output is treated as "
    "first-class evidence by a grounding verifier; routes every query through a "
    "single arbitration layer that selects among answering, requesting "
    "clarification, and refusing under an explicit asymmetric cost model; and "
    "records a durable provenance document for every turn, linking the emitted "
    "answer to the evidence, the arbitration verdict, and the model that "
    "produced it. The system additionally normalises Roman-Urdu input to Urdu "
    "script before retrieval, and resolves cross-jurisdictional statute aliases "
    "that arise when users import Indian legal terminology. We describe the "
    "architecture, the construction of an abstention-aware evaluation set built "
    "by labelling recorded production traffic, and an evaluation protocol "
    "reporting selective-prediction behaviour alongside standard ranking metrics."
)

KEYWORDS = ("legal informatics, retrieval-augmented generation, selective "
            "prediction, abstention, neuro-symbolic systems, low-resource NLP, "
            "code-switching, Urdu")

# IEEE numbered style. Order MUST match first-citation order in the text, and
# must stay in sync with references.bib (which drives the LaTeX build).
# EVERY ENTRY NEEDS VERIFYING against the real paper before submission.
REFERENCES = [
    'P. Lewis et al., "Retrieval-augmented generation for knowledge-intensive '
    'NLP tasks," in Proc. Advances in Neural Information Processing Systems '
    '(NeurIPS), 2020.',

    'I. Chalkidis, M. Fergadiotis, P. Malakasiotis, N. Aletras, and I. '
    'Androutsopoulos, "LEGAL-BERT: The muppets straight out of law school," in '
    'Findings of EMNLP, 2020.',

    'N. Guha et al., "LegalBench: A collaboratively built benchmark for '
    'measuring legal reasoning in large language models," in Proc. NeurIPS, '
    '2023.',

    'V. Karpukhin et al., "Dense passage retrieval for open-domain question '
    'answering," in Proc. EMNLP, 2020.',

    'A. Asai, Z. Wu, Y. Wang, A. Sil, and H. Hajishirzi, "Self-RAG: Learning '
    'to retrieve, generate, and critique through self-reflection," in Proc. '
    'International Conference on Learning Representations (ICLR), 2024.',

    'R. El-Yaniv and Y. Wiener, "On the foundations of noise-free selective '
    'classification," Journal of Machine Learning Research, vol. 11, '
    'pp. 1605-1641, 2010.',

    'Y. Geifman and R. El-Yaniv, "Selective classification for deep neural '
    'networks," in Proc. NeurIPS, 2017.',

    'C. Guo, G. Pleiss, Y. Sun, and K. Q. Weinberger, "On calibration of '
    'modern neural networks," in Proc. International Conference on Machine '
    'Learning (ICML), 2017.',

    'J. Platt, "Probabilistic outputs for support vector machines and '
    'comparisons to regularized likelihood methods," in Advances in Large '
    'Margin Classifiers, MIT Press, 1999.',

    'B. Zadrozny and C. Elkan, "Transforming classifier scores into accurate '
    'multiclass probability estimates," in Proc. ACM SIGKDD, 2002.',

    'A. N. Angelopoulos and S. Bates, "A gentle introduction to conformal '
    'prediction and distribution-free uncertainty quantification," arXiv '
    'preprint, 2021.',

    'S. Kadavath et al., "Language models (mostly) know what they know," arXiv '
    'preprint, 2022.',

    'Z. Ji et al., "Survey of hallucination in natural language generation," '
    'ACM Computing Surveys, vol. 55, no. 12, 2023.',

    'L. Wang, N. Yang, X. Huang, L. Yang, R. Majumder, and F. Wei, '
    '"Multilingual E5 text embeddings: A technical report," arXiv preprint, '
    '2024.',

    'S. Robertson and H. Zaragoza, "The probabilistic relevance framework: '
    'BM25 and beyond," Foundations and Trends in Information Retrieval, '
    'vol. 3, no. 4, pp. 333-389, 2009.',

    'G. V. Cormack, C. L. A. Clarke, and S. Buttcher, "Reciprocal rank fusion '
    'outperforms Condorcet and individual rank learning methods," in Proc. ACM '
    'SIGIR, 2009.',

    'F. Perez and I. Ribeiro, "Ignore previous prompt: Attack techniques for '
    'language models," in NeurIPS ML Safety Workshop, 2022.',

    'K. Greshake, S. Abdelnabi, S. Mishra, C. Endres, T. Holz, and M. Fritz, '
    '"Not what you\'ve signed up for: Compromising real-world LLM-integrated '
    'applications with indirect prompt injection," in Proc. ACM Workshop on '
    'Artificial Intelligence and Security (AISec), 2023.',

    '"Pakistan Laws Dataset." [Online]. Available: '
    'https://huggingface.co/datasets/AyeshaJadoon/Pakistan_Laws_Dataset '
    '[VERIFY authorship, citation form and licence]',

    '"LEGAL-UQA: A bilingual English-Urdu legal question answering dataset." '
    '[Online]. Available: '
    'https://huggingface.co/datasets/nlp-anonymous-researcher/LEGAL-UQA '
    '[VERIFY authorship, citation form and licence]',

    'K. Jarvelin and J. Kekalainen, "Cumulated gain-based evaluation of IR '
    'techniques," ACM Transactions on Information Systems, vol. 20, no. 4, '
    'pp. 422-446, 2002.',
]


def build_paper(path: Path) -> None:
    doc = Document()

    # Default style
    style = doc.styles["Normal"]
    style.font.name = "Times New Roman"
    style.font.size = Pt(10)

    # ── Section 1: single column header ──────────────────────────────────────
    s0 = doc.sections[0]
    _margins(s0)
    _set_columns(s0, 1)

    _para(doc, TITLE, size=24, align="center", space_after=10)

    _para(doc, "Muhammad Usama", size=11, align="center", space_after=0)
    _para(doc, "Department of Computer Science", size=10, italic=True,
          align="center", space_after=0)
    _para(doc, "COMSATS University Islamabad", size=10, italic=True,
          align="center", space_after=0)
    _para(doc, "Islamabad, Pakistan", size=10, align="center", space_after=0)
    _para(doc, "muhammadusamahoyrr@gmail.com", size=10, align="center",
          space_after=6)
    _rich(doc, [("[TODO: add supervisor as co-author — name, affiliation, "
                 "email. Confirm whether FIT review is double-blind; if so, "
                 "remove this entire author block.]", True, False, TODO_RED)],
          align="center", first_line_indent=0)

    # ── Section 2: two-column body ───────────────────────────────────────────
    s1 = doc.add_section(WD_SECTION.CONTINUOUS)
    _margins(s1)
    _set_columns(s1, 2)

    _rich(doc, [("Abstract—", True, True), (ABSTRACT, False, True)],
          size=9, first_line_indent=0.2)
    _rich(doc, [("Index Terms—", True, True), (KEYWORDS, False, True)],
          size=9, first_line_indent=0.2)

    # I. Introduction
    _heading(doc, "I", "Introduction")
    _body(doc,
        "Access to legal information is unevenly distributed. A litigant who "
        "cannot afford counsel is often unable to establish even the threshold "
        "facts of their own position: which statute governs, which forum has "
        "jurisdiction, what a filing will cost, or whether a limitation period "
        "has already expired.")
    _todo(doc, "Insert one cited statistic on the lawyer-to-population ratio or "
               "case backlog in Pakistan. Do not write a number you have not "
               "sourced.")
    _body(doc,
        "Large language models with retrieval augmentation [1] appear well "
        "suited to closing part of that gap, and legal question answering is "
        "now an active application area [2], [3]. Existing systems, however, "
        "are built predominantly for English and for common-law or European "
        "jurisdictions. Transferring them to Pakistan is not a matter of "
        "swapping the corpus. Queries arrive in English, in Urdu script, and "
        "most commonly in Roman Urdu, the transliterated register used in "
        "everyday digital communication; the applicable law combines codified "
        "statute with Islamic personal law and varies by province; and users "
        "routinely import Indian statutory terminology, asking about the Indian "
        "Penal Code when the Pakistan Penal Code governs. Each of these is a "
        "retrieval problem before it is a generation problem.")
    _body(doc,
        "A second gap is less specific to jurisdiction and, we argue, more "
        "consequential. Legal question-answering systems are evaluated almost "
        "entirely on the quality of the answers they produce. Two properties "
        "that matter more in professional practice go largely unmeasured. The "
        "first is abstention: a confidently wrong answer about bail eligibility "
        "or a limitation period can cause material harm, so a system that "
        "declines to answer when its evidence is weak is more useful than one "
        "that always responds. The second is auditability: an answer that "
        "cannot be traced to the evidence and decisions that produced it cannot "
        "be contested, corrected, or defended, which is precisely what a "
        "regulated domain requires. Neither property is captured by "
        "answer-quality metrics, and neither is achievable as an afterthought.")
    _body(doc,
        "This paper describes a legal question-answering system for Pakistani "
        "law built around both. Our contributions are: (i) verifier-aware "
        "symbolic evidence - deterministic statutory engines for court fees, "
        "bail eligibility, limitation and inheritance shares under Islamic law "
        "are treated as first-class evidence by the grounding verifier, so a "
        "correct computed answer is not mislabelled as ungrounded merely "
        "because no retrieved provision restates it; (ii) an explicit "
        "abstention policy, in which a single arbitration layer selects among "
        "answering, requesting clarification and refusing under an asymmetric "
        "cost model where an unnecessary refusal is itself a cost; "
        "(iii) code-switched retrieval for a low-resource jurisdiction, with "
        "Roman-Urdu normalisation and cross-jurisdictional alias resolution; "
        "and (iv) per-turn provenance linking every emitted answer to its "
        "evidence, its arbitration verdict and the model that served it, "
        "together with an evaluation protocol that constructs an "
        "abstention-aware test set by labelling recorded traffic.")

    # II. Related Work
    _heading(doc, "II", "Related Work")
    _rich(doc, [("Legal NLP and retrieval-augmented generation. ", True, False),
                ("Domain-adapted encoders such as LEGAL-BERT [2] established "
                 "that legal text benefits from in-domain pretraining, and "
                 "LegalBench [3] provides a broad benchmark for legal reasoning "
                 "in large language models. Retrieval augmentation [1] combined "
                 "with dense passage retrieval [4] is now the standard "
                 "architecture for grounding generated answers in source "
                 "documents. Self-RAG [5] adds self-reflection over retrieval "
                 "quality and answer support. This line of work overwhelmingly "
                 "targets English and common-law or EU material, and evaluates "
                 "the answers produced rather than the decision of whether to "
                 "answer.", False, False)])
    _rich(doc, [("Selective prediction and calibration. ", True, False),
                ("Selective classification formalises the option to abstain and "
                 "the risk-coverage trade-off it induces [6], [7]. Modern "
                 "neural networks are systematically miscalibrated [8], "
                 "motivating post-hoc mapping of scores into probability space "
                 "by Platt scaling [9] or isotonic regression [10]; conformal "
                 "prediction [11] offers distribution-free coverage guarantees "
                 "over the same problem. Language models retain some signal "
                 "about their own reliability [12], and hallucination remains a "
                 "central failure mode of generation systems [13]. These "
                 "techniques are rarely applied to the routing decision inside "
                 "a retrieval pipeline, which is where we place them.",
                 False, False)])
    _rich(doc, [("Tool-augmented and neuro-symbolic generation. ", True, False),
                ("Delegating exactly-computable subproblems to deterministic "
                 "components is well established, but the interaction between "
                 "tool output and answer verification is not. Where a grounding "
                 "check tests whether claims appear in retrieved text, computed "
                 "results are structurally invisible to it. We make the "
                 "verifier aware of symbolic evidence rather than treating "
                 "tools purely as a generation aid.", False, False)])
    _rich(doc, [("Low-resource retrieval and adversarial robustness. ", True, False),
                ("Multilingual dense encoders [14] make a single index viable "
                 "across scripts, and hybrid lexical-dense retrieval with rank "
                 "fusion [15], [16] remains strong where exact terminology "
                 "matters, as it does for statute references. Separately, "
                 "prompt injection is a practical threat to any deployed "
                 "instruction-following assistant [17], [18]. We report a "
                 "failure mode in this class that arises from pipeline "
                 "structure rather than from classifier weakness.",
                 False, False)])
    _body(doc,
        "To our knowledge, no existing system combines abstention under an "
        "explicit cost model, symbolic evidence admitted by the grounding "
        "verifier, and code-switched retrieval for a low-resource "
        "jurisdiction, nor reports an evaluation that measures all three.")

    # III. Method
    _heading(doc, "III", "Method")

    _subheading(doc, "A", "Overview")
    _body(doc,
        "The system is a directed graph of thirteen nodes executed per user "
        "turn. A turn enters an adversarial gatekeeper, is classified and "
        "triaged, may be suspended to ask the user for missing facts, is "
        "checked against a semantic cache, may invoke deterministic statutory "
        "engines, retrieves statute and case-law evidence, has that evidence "
        "scored, and only then reaches an arbitration node that decides whether "
        "to answer at all. Generation and a grounding check follow, and a "
        "finaliser sanitises the output. Conversation state, including the "
        "suspended state of a pending clarification, is checkpointed to a "
        "document store so that a turn survives process restarts and can be "
        "resumed by a different worker.")
    _body(doc,
        "Four properties distinguish the design from a standard RAG pipeline: "
        "symbolic evidence admitted by the verifier (Section III-D), "
        "three-signal confidence with an explicit abstention policy "
        "(Sections III-E and III-H), code-switched retrieval (Section III-B), "
        "and per-turn provenance (Section III-K).")

    _subheading(doc, "B", "Corpus and Retrieval")
    _body(doc,
        "The statute corpus is drawn from a public collection of 967 Pakistani "
        "legal documents [19], segmented by section and partitioned into four "
        "collections by legal domain (civil, criminal, family, "
        "constitutional). A bilingual English-Urdu constitutional "
        "question-answer set [20] is ingested into the constitutional "
        "collection as both raw article text and question-answer pairs. A "
        "separate corpus of "
        "reported Lahore High Court judgments supports case-law retrieval. "
        "Table I reports the indexed chunk counts.")

    _table_corpus(doc)

    _body(doc,
        "Retrieval is hybrid. A BM25 index and a dense index over "
        "multilingual-e5-base embeddings are combined by weighted ensemble with "
        "weights 0.6 and 0.4 respectively, the lexical channel weighted higher "
        "because exact statute and section references carry disproportionate "
        "signal in this domain. Dense retrieval applies the asymmetric query and "
        "passage prefixes the model expects. Both channels are filtered so that "
        "a query for a given province retrieves only that province's provisions "
        "or federal ones.")
    _body(doc,
        "Two mechanisms address vocabulary mismatch specific to this setting. "
        "First, a rule-based alias layer rewrites common cross-jurisdictional "
        "references before retrieval; users frequently ask about the Indian "
        "Penal Code when they mean the Pakistan Penal Code, and equivalent "
        "confusions exist for procedural codes. Second, a query rewriter maps "
        "colloquial phrasing to formal statutory terminology, and its output is "
        "accepted only if it contains recognised legal vocabulary, guarding "
        "against a degenerate rewrite.")
    _body(doc,
        "Retrieval is two-hop. The first hop issues the expanded query. "
        "Statutory cross-references appearing in the first-hop results are then "
        "extracted and issued as a second query, so that a provision "
        "incorporating another by reference pulls in the referenced text. The "
        "two result lists are merged by reciprocal rank fusion. Case-law "
        "retrieval runs semantically over the judgment corpus on the "
        "unrewritten query, since judgment prose matches lay phrasing more "
        "closely than statutory terminology, and admits at most three judgments "
        "above a conservative similarity threshold.")

    _subheading(doc, "C", "Code-Switched Input")
    _body(doc,
        "Queries arrive in English, Urdu script, or Roman Urdu - Urdu written "
        "in Latin characters, which is the dominant informal register. A triage "
        "stage classifies the input language and, for Roman Urdu, emits a "
        "transliteration into Urdu script. Retrieval runs on this normalised "
        "form, so a single multilingual dense index serves all three registers "
        "without a separate Roman-Urdu index. The lexical signal described in "
        "Section III-E recognises legal terms in both scripts.")

    _subheading(doc, "D", "Deterministic Statutory Engines")
    _body(doc,
        "Several questions in this domain have exact answers that are computed, "
        "not retrieved: court-fee schedules, bail eligibility, statutory "
        "limitation periods, labour dues, and inheritance shares under Islamic "
        "law. The system exposes these as deterministic engines invoked before "
        "retrieval, and their results are held outside the retrieved-chunk set "
        "so that a retrieval retry cannot overwrite them and the relevance "
        "grader cannot score them.")
    _body(doc,
        "The consequence for verification is the contribution we wish to "
        "emphasise. A conventional grounding check asks whether the answer's "
        "claims appear in retrieved text; under that rule, a correct court-fee "
        "figure derived from a computation is judged ungrounded, because no "
        "retrieved provision states it. Our verifier is told that engine output "
        "is computed ground truth, and that an answer faithfully restating an "
        "engine's result is grounded. Correspondingly, the abstention policy in "
        "Section III-H never refuses a turn in which an engine produced a "
        "result, since refusing a computed figure because the surrounding "
        "statutory context scored poorly is strictly worse than answering.")

    _subheading(doc, "E", "Three-Signal Confidence")
    _body(doc,
        "Each retrieved chunk receives a confidence score combining three "
        "signals: a lexical score k, the fraction of legal terms in the query "
        "present in the chunk; an embedding similarity e; and a binary "
        "relevance grade l from a fast language model. The signals are mapped "
        "into probability space by the calibration layer (Section III-F) and "
        "combined additively:")
    _equation(doc, "s = 0.40 k + 0.35 ê + 0.25 l̂", "1")
    _body(doc,
        "with the lexical term weighted highest for the same reason the lexical "
        "retrieval channel is.")
    _body(doc,
        "Disagreement between the signals is retained rather than averaged "
        "away. Let σ² be the variance of the three calibrated signals. "
        "When σ² exceeds an adaptive threshold, the score is penalised "
        "by σ², and the mean variance across chunks is passed forward "
        "to the arbitration layer, where it is the signal that distinguishes "
        "requesting more information from answering at equal mean confidence. "
        "If the relevance grader is unavailable, its signal degrades to a "
        "neutral value rather than failing closed, so that a provider outage "
        "falls through to the lexical evidence path instead of becoming "
        "indistinguishable from an absence of relevant law.")

    _subheading(doc, "F", "Calibration and Drift Monitoring")
    _body(doc,
        "Raw scores are mapped to calibrated probabilities before arbitration: "
        "Platt scaling for the language-model signal and isotonic regression "
        "for the lexical signal, with cosine similarity clamped as it already "
        "occupies probability space.")
    _todo(doc, "State plainly that fitted parameters are estimated from the "
               "labelled set of Section IV, and report the fitted values. Until "
               "they are fitted the transforms are identity, and the paper must "
               "not claim otherwise - this is why the title says 'selective' "
               "rather than 'calibrated'.")
    _body(doc,
        "Distribution shift is monitored by the population stability index over "
        "a rolling window of retrieval confidences, with a shift flagged at "
        "PSI >= 0.20 and stability below 0.10. Both the calibration state and "
        "the threshold state described next are held in a shared store rather "
        "than in process memory, so that a horizontally scaled deployment does "
        "not maintain divergent thresholds per worker.")

    _subheading(doc, "G", "Adaptive Thresholds")
    _body(doc,
        "Decision thresholds are seeded and then re-estimated from observed "
        "data: the generation floor from the 10th percentile of retrieval "
        "scores, a routing gap from the 25th percentile, and a similarity "
        "threshold from the 90th percentile, recomputed periodically over a "
        "rolling window once a warm-up volume of queries has been observed. "
        "Threshold reads occur once per chunk and are served from a "
        "process-local snapshot refreshed on a fixed interval, so the hot path "
        "performs no remote reads; writes are batched.")

    _subheading(doc, "H", "Arbitration and Abstention")
    _body(doc,
        "All routing flows through a single arbitration node; the graph's edge "
        "functions read its verdict and do not recompute confidence. The node "
        "selects one of three actions - ANSWER, DEFER (request clarification "
        "and retry retrieval), or REFUSE - over the available evidence sources.")
    _body(doc,
        "Evidence may come from the graded retrieval path, from a "
        "version-matched cache hit, or from the lexical channel alone. "
        "Lexical-only evidence is capped at confidence 0.55, so that it can "
        "support an answer but cannot present itself as a confident judgement. "
        "Each candidate source is assigned a utility:")
    _equation(doc, "u(c, a) = c / cost(a)", "2")
    _body(doc,
        "where c is calibrated confidence and cost encodes the asymmetry of the "
        "domain: answering is cheap (0.10), deferring costs more (0.30), and "
        "refusing is most expensive (0.60) in user-experience terms, which is "
        "what makes an unnecessary refusal a real cost rather than a free safe "
        "default. The action is DEFER when signal variance exceeds its "
        "threshold; REFUSE when confidence falls below a refusal ceiling; "
        "ANSWER when confidence meets or exceeds a generation floor; and DEFER "
        "otherwise. Two overrides apply. A turn retrieving zero chunks refuses "
        "unconditionally. And after a bounded number of consecutive deferrals "
        "the node enters a binary mode in which it must answer or refuse, so "
        "that a mid-confidence query cannot loop indefinitely asking for "
        "clarification. Retry budget is deliberately kept outside the "
        "arbitration node: the node judges evidence, while the graph decides "
        "whether another retrieval pass is affordable.")
    _todo(doc, "Equation (2) is the weakest formal point in the paper and a "
               "reviewer will press on it. Either derive the action from "
               "expected utility over an explicit harm matrix, or state "
               "honestly that the cost vector is a hand-set prior and show a "
               "sensitivity analysis over it.")

    _subheading(doc, "I", "Grounding Verification")
    _body(doc,
        "Generated answers are checked against the evidence actually supplied - "
        "retrieved provisions, admitted judgments, and engine output. An answer "
        "judged ungrounded has its confidence halved and receives an explicit "
        "caution directing the user to a qualified lawyer, and generation may "
        "be retried within budget. The system never presents an ungrounded "
        "answer as though it were verified.")

    _subheading(doc, "J", "Adversarial Robustness")
    _body(doc,
        "Because the assistant is instruction-following and publicly reachable, "
        "prompt injection is a live concern. A gatekeeper runs first, in two "
        "layers: a zero-cost regular-expression filter for high-signal attack "
        "strings, and a fast-model classifier for subtler attempts. The filter "
        "is deliberately narrow, because in this domain the obvious keywords "
        "are ordinary vocabulary - a question about disregarding a court order, "
        "or acting as an unrestricted agent under a power of attorney, is a "
        "legitimate legal query and must not be refused. The classifier fails "
        "open, so that a model-provider outage does not become a total service "
        "outage while the regex layer remains active.")
    _body(doc,
        "One implementation finding is worth reporting because it generalises. "
        "An intent-classification shortcut answered certain conversational "
        "turns without entering the graph, and therefore bypassed the "
        "gatekeeper entirely; an injection phrased to end in an affirmation was "
        "routed to a canned reply, unlogged and unaudited. Defence-in-depth at "
        "a single point in a pipeline is insufficient when alternative paths "
        "exist that skip that point, and any robustness figure measured under "
        "such a configuration is computed only over the traffic that reached "
        "the defended component.")

    _subheading(doc, "K", "Provenance")
    _body(doc,
        "Each turn writes a durable record linking the emitted output to the "
        "evidence and decisions behind it: retrieved chunk identifiers, "
        "admitted case-law citations, engine invocations with success state, "
        "the arbitration verdict and the signals it was computed from, "
        "convergence counters, the models that served the turn, and the "
        "embedding and chunking versions required to reproduce retrieval. The "
        "answer is stored as a cryptographic digest plus a redacted preview "
        "rather than duplicated in full, so a record identifies the answer it "
        "describes without becoming a second copy of the user's legal "
        "correspondence. Personally identifying information is masked with the "
        "same routine applied to user-facing output, covering national identity "
        "numbers in both Latin and Urdu digit forms. Records are typed by turn "
        "kind - answer, clarification, or blocked - so that turns which asked a "
        "question rather than answering one are audited without being treated "
        "as answers.")

    # IV. Evaluation Protocol
    _heading(doc, "IV", "Evaluation Protocol")

    _subheading(doc, "A", "Dataset Construction")
    _body(doc,
        "Rather than authoring question-answer pairs, we label recorded "
        "traffic. Each answered turn has already stored its query, the "
        "identifiers of the chunks retrieved for it, and the verdict reached, "
        "so annotation reduces to judging relevance over a fixed candidate set "
        "rather than inventing candidates. Following standard pooling practice, "
        "judgements are collected to a fixed depth of the ranked list; the "
        "depth is stored with each label, and metrics at deeper cut-offs are "
        "refused, since ranks below the pool are unjudged rather than known "
        "irrelevant.")
    _body(doc,
        "Each turn additionally receives one of four outcome verdicts: correct, "
        "incorrect, correct refusal, or wrong refusal. Separating a correct "
        "abstention from a mistaken one is what makes risk-coverage analysis "
        "possible; collapsing them loses exactly the distinction the system is "
        "designed around. Turns on which no retrieved evidence was relevant are "
        "retained as the unanswerable split rather than discarded, since these "
        "are the cases where refusal is the correct behaviour.")

    _subheading(doc, "B", "Query Set")
    _body(doc,
        "Evaluation queries span six categories: answerable questions the "
        "corpus should support; out-of-jurisdiction queries using Indian "
        "statutory names; questions unanswerable from this corpus; "
        "code-switched queries in Roman Urdu and Urdu script; adversarial "
        "prompt-injection attempts; and off-topic input.")
    _todo(doc, "State the final counts per category and be explicit about "
               "provenance of the queries. A set authored by the system's own "
               "developer is a bootstrap, not a benchmark; if the final set "
               "remains developer-authored, say so in Limitations rather than "
               "letting a reviewer find it.")

    _subheading(doc, "C", "Metrics")
    _body(doc,
        "Retrieval is reported by Hit@k, mean reciprocal rank, and nDCG@k [21] "
        "at cut-offs within the pooling depth. Selective prediction is reported by "
        "risk-coverage curves, the area under the risk-coverage curve, and "
        "expected calibration error, together with the rate of ungrounded "
        "answers at a given coverage. Robustness is reported as the proportion "
        "of adversarial inputs refused, measured with all bypass paths closed.")

    # V. Results
    _heading(doc, "V", "Results")
    _todo(doc, "Pending the labelled set. Do not draft narrative text here "
               "before the numbers exist. Planned tables: (1) retrieval metrics "
               "overall and per legal domain; (2) ablation - hybrid vs "
               "lexical-only vs dense-only, one-hop vs two-hop, normalised vs "
               "raw Roman Urdu; (3) abstention - arbitration enabled vs "
               "always-answer, with risk-coverage; (4) grounding - ungrounded "
               "rate with and without engine-aware verification. Ablation (4) "
               "is the strongest single result available and should be "
               "prioritised if space is short.")

    # VI. Discussion and Limitations
    _heading(doc, "VI", "Discussion and Limitations")
    _body(doc,
        "Two findings from deployment generalise beyond this system. First, "
        "defence in depth at a single point in a pipeline is insufficient when "
        "alternative paths exist that skip that point. An "
        "intent-classification shortcut answered certain turns without entering "
        "the graph and so bypassed the injection gatekeeper entirely; the "
        "classifier was not weak, it was simply not consulted. Any robustness "
        "figure measured in that configuration is computed only over traffic "
        "that reached the defended component, which is a measurement error "
        "rather than a model error. Second, in a specialised domain, "
        "keyword-based safety filters collide with legitimate vocabulary: our "
        "injection filter matched a power-of-attorney question containing the "
        "phrase 'unrestricted agent'. The cost of a false positive here is "
        "refusing a user with a genuine legal problem, which argues for narrow "
        "patterns backed by a model layer rather than broad ones.")
    _body(doc,
        "The work has substantive limitations, which we state rather than leave "
        "to be discovered. Calibration is fitted on a modest volume of labelled "
        "data drawn from a single deployment, so the mapping should be expected "
        "to shift under a different user population; conformal methods [11] "
        "would give coverage guarantees that our post-hoc fitting does not. "
        "Relevance judgements are the authors' own, not adjudicated by "
        "qualified practitioners, which is a real constraint on any claim about "
        "legal correctness as opposed to retrieval quality. Evaluation queries "
        "were authored alongside the system, making them a bootstrap rather "
        "than an independent benchmark. The cost vector in (2) is a hand-set "
        "prior encoding a plausible ordering of harms, not a quantity elicited "
        "from practitioners or derived from outcomes. Coverage is "
        "single-jurisdiction, and the corpus is weighted towards statute "
        "relative to case law, so performance on precedent-driven questions is "
        "likely weaker than on statutory ones. Finally, the pooled relevance "
        "judgements bound the depth at which ranking metrics are meaningful, "
        "and we report only cut-offs within that depth.")

    # VII. Conclusion
    _heading(doc, "VII", "Conclusion")
    _body(doc,
        "Legal question answering in a low-resource, code-switched jurisdiction "
        "is not served by transplanting an English common-law pipeline, and it "
        "is not adequately measured by answer quality alone. We described a "
        "system that treats deterministic statutory computation as evidence its "
        "own verifier can accept, that routes every query through an explicit "
        "decision between answering, clarifying and refusing, and that records "
        "for each turn the evidence and decisions behind the answer it emitted. "
        "We further described an evaluation protocol that builds an "
        "abstention-aware test set by labelling recorded traffic, so that "
        "correct refusals are measured rather than discarded.")
    _todo(doc, "Close with one concrete number once measured - ideally the "
               "reduction in ungrounded answers from engine-aware "
               "verification, which is the cleanest single result available.")

    # Ethical considerations
    _para(doc, "ETHICAL CONSIDERATIONS", size=10, align="center",
          space_before=10, space_after=4)
    _body(doc,
        "The system provides legal information, not legal advice, and every "
        "answer carries an explicit disclaimer directing users to a qualified "
        "practitioner. Refusal is treated as a first-class outcome precisely "
        "because a confident wrong answer in this domain can cause material "
        "harm. Stored records mask personally identifying information, and "
        "audit records are retrievable only by the user who produced them.")

    # References
    _para(doc, "REFERENCES", size=10, align="center", space_before=10,
          space_after=4)
    _todo(doc, "VERIFY EVERY ENTRY BELOW against the actual paper before "
               "submitting - page numbers, volume, exact venue name and year. "
               "Delete any you have not opened. Entries [19] and [20] are "
               "dataset resources whose citation form and licence must be "
               "confirmed.")
    for i, ref in enumerate(REFERENCES, 1):
        p = _para(doc, f"[{i}]\t{ref}", size=8, align="justify", space_after=2)
        p.paragraph_format.left_indent = Inches(0.22)
        p.paragraph_format.first_line_indent = Inches(-0.22)

    doc.save(path)


def _equation(doc, text, number):
    """Centred equation with a right-aligned number, IEEE style."""
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(4)
    p.paragraph_format.space_after  = Pt(4)
    run = p.add_run(f"{text}\t\t({number})")
    run.font.name = "Times New Roman"
    run.font.size = Pt(10)
    run.italic = True


def _table_corpus(doc):
    _para(doc, "TABLE I.\tINDEXED CORPUS, BY COLLECTION", size=8,
          align="center", space_before=6, space_after=3)
    rows = [("Collection", "Chunks"),
            ("Criminal", "1,735"),
            ("Constitutional", "924"),
            ("Civil", "396"),
            ("Family", "226"),
            ("Case law (LHC judgments)", "3,230")]
    table = doc.add_table(rows=len(rows), cols=2)
    table.style = "Table Grid"
    for i, (a, b) in enumerate(rows):
        for j, val in enumerate((a, b)):
            cell = table.cell(i, j)
            cell.text = val
            for para in cell.paragraphs:
                para.paragraph_format.space_after = Pt(0)
                for run in para.runs:
                    run.font.name = "Times New Roman"
                    run.font.size = Pt(8)
                    run.bold = (i == 0)


# ═════════════════════════════════════════════════════════════════════════════
#  TECHNICAL DOSSIER  (everything that will not fit in six pages)
# ═════════════════════════════════════════════════════════════════════════════

def build_dossier(path: Path) -> None:
    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = "Times New Roman"
    style.font.size = Pt(11)

    s0 = doc.sections[0]
    _margins(s0, 1.0, 1.0, 1.0, 1.0)

    _para(doc, "Attorney.AI - Technical Dossier", size=20, bold=True,
          align="center", space_after=2)
    _para(doc, "Supporting material for the FIT/IEEE submission",
          size=11, italic=True, align="center", space_after=2)
    _para(doc, "Muhammad Usama - COMSATS University Islamabad (SP23-BCS-069)",
          size=10, align="center", space_after=2)
    _para(doc, "Generated 5 August 2026", size=9, italic=True,
          align="center", space_after=14)

    def h1(t):
        _para(doc, t, size=14, bold=True, align="left",
              space_before=12, space_after=4)

    def h2(t):
        _para(doc, t, size=12, bold=True, align="left",
              space_before=8, space_after=3)

    def txt(t):
        _para(doc, t, size=11, align="justify", space_after=5,
              first_line_indent=None)

    def bullets(items):
        for it in items:
            p = doc.add_paragraph(style="List Bullet")
            p.paragraph_format.space_after = Pt(2)
            run = p.add_run(it)
            run.font.name = "Times New Roman"
            run.font.size = Pt(11)

    # --- 1
    h1("1.  Purpose of this document")
    txt("The FIT paper is capped at six pages including references, which is far "
        "less than the system warrants. This dossier holds the material that "
        "cannot fit: exact parameters, the engineering findings behind the "
        "design decisions, the current data position, and the open risks. It "
        "doubles as FYP documentation and as the reference to draw on when a "
        "reviewer asks for detail the paper had no room for.")

    # --- 2
    h1("2.  Venue requirements (verified)")
    txt("Source: https://fit.edu.pk/submission-guidelines.aspx")
    bullets([
        "Page limit: 6 pages maximum, references included.",
        "Format: two-column IEEE conference format.",
        "File type: PDF only.",
        "Submission: EasyChair (conf=fit26).",
        "Exclusivity: must not be under consideration at another venue.",
    ])
    _rich(doc, [("WARNING: ", True, False, TODO_RED),
                ("the FIT 2026 submission deadline was reported as 31 July "
                 "2026, with the conference on 14-15 December 2026. If "
                 "accurate, it has already passed. Confirm directly with "
                 "fit@comsats.edu.pk before planning around it, and treat FIT "
                 "2027 or an alternative venue as the working assumption.",
                 False, False, TODO_RED)],
          size=11, first_line_indent=None)

    # --- 3
    h1("3.  System parameters")

    h2("3.1  Retrieval")
    bullets([
        "Hybrid ensemble: BM25 weight 0.60, dense weight 0.40.",
        "Dense model: intfloat/multilingual-e5-base, with query:/passage: prefixes.",
        "Vector store: Chroma, cosine space. Dense k = 10.",
        "Province filter: matches the query province OR federal.",
        "Two-hop: hop-2 issues statute cross-references found in hop-1; "
        "lists merged by reciprocal rank fusion.",
        "Statute cross-reference graph: typed weighted edges - cite 1.15, "
        "ref 1.10, amend 1.05, defined_by 1.20.",
        "Case law: semantic only, similarity threshold 0.78, at most 3 admitted.",
    ])

    h2("3.2  Scoring and thresholds")
    bullets([
        "Signal weights: lexical 0.40, embedding 0.35, LLM grade 0.25.",
        "Variance penalty applied when inter-signal variance exceeds 0.25.",
        "Seed thresholds: generation floor 0.20 (p10), routing gap 0.15 (p25), "
        "cosine 0.70 (p90), refusal ceiling 0.10, disagreement max 0.25.",
        "Warm-up: 1000 queries (unlabelled). Rolling window 2000 samples, "
        "recomputed every 100 queries thereafter.",
        "Relevance retry threshold 0.40; max 3 retrieval attempts, "
        "2 generation attempts; convergence minimum delta 0.05.",
    ])

    h2("3.3  Arbitration")
    bullets([
        "Action costs: answer 0.10, defer 0.30, refuse 0.60.",
        "Utility = calibrated confidence / action cost.",
        "Lexical-only (BM25) evidence capped at 0.55 confidence.",
        "Maximum clarification depth 2, after which the node is binary "
        "(answer or refuse only).",
        "Zero retrieved chunks refuses unconditionally.",
        "An engine result overrides refusal - a computed figure is never "
        "discarded because surrounding context scored poorly.",
    ])

    h2("3.4  Corpus")
    bullets([
        "Statutes: 967 Pakistani legal documents, section-segmented.",
        "Indexed chunks: criminal 1,735; constitutional 924; civil 396; "
        "family 226.",
        "Case law: 3,230 chunks from reported Lahore High Court judgments.",
        "Bilingual constitutional QA set ingested as both article text and "
        "question-answer pairs.",
    ])

    # --- 4
    h1("4.  Engineering findings worth citing in the paper")
    txt("Each of these was discovered by running the system rather than by "
        "reading the code, which is itself a point worth making in the paper.")

    h2("4.1  Dead abstention path")
    txt("The decision engine and the three-signal scorer were both present, "
        "documented, and imported by nothing. The arbitration verdict was "
        "hardcoded to 'answer' at both entry points, so the refuse and defer "
        "branches were unreachable and the weighted confidence score was never "
        "computed. Any claim about abstention behaviour prior to wiring these "
        "would have described code that could not execute.")

    h2("4.2  Defence bypassed by an alternative path")
    txt("An intent-classification shortcut answered affirmation, stop, and "
        "reformat turns without entering the graph, so the injection gatekeeper "
        "never saw them. A jailbreak string ending in 'Confirm.' was classified "
        "as an affirmation and answered from a canned template, with no audit "
        "record written. The model did not comply, so there was no content "
        "failure - but the attempt was neither blocked nor logged, and any "
        "robustness figure measured in that configuration would have been "
        "computed only over traffic that reached the defended component.")

    h2("4.3  Domain vocabulary collides with attack vocabulary")
    txt("The injection filter matched 'act as an unrestricted agent for my "
        "brother' - a power-of-attorney question in which 'unrestricted' is "
        "standard vocabulary. The pattern now requires the persona adjective to "
        "qualify an AI noun. This generalises: in a specialised domain, "
        "keyword-based safety filters collide with legitimate terminology, and "
        "the false-positive cost is refusing a user with a real problem.")

    h2("4.4  Per-worker state in a scaled deployment")
    txt("Adaptive thresholds and drift statistics were process-local module "
        "state. Under multiple workers each kept private percentiles and a "
        "private warm-up counter, so identical queries could be graded against "
        "different thresholds depending on which worker served them, and a "
        "deploy silently reset warm-up progress to zero.")

    h2("4.5  Pooling depth as a feasibility constraint")
    txt("Retrieval returns up to 20 chunks, averaging 12.4 per record in "
        "measured traffic. Judging every one works out at roughly 50 hours for "
        "1000 records. Pooling to depth 5 reduces that to about 17 hours and "
        "costs nothing for metrics at cut-offs of 5 or below - but the depth "
        "must be recorded, because ranks below it are unjudged rather than "
        "known irrelevant.")

    # --- 5
    h1("5.  Current data position")
    bullets([
        "Provenance records: 21 (18 answer, 1 clarification, 2 blocked).",
        "Labelled: 0.",
        "Target for evaluation set and calibration fitting: ~200 labels.",
        "Target for threshold warm-up: 1000 queries - unlabelled, traffic-driven, "
        "requires no annotation.",
        "Observed verdicts in seed traffic: answer 10, refuse 2, defer 1, "
        "pending 3 (off-topic exits before arbitration).",
        "Winning evidence source: LLM 8, lexical (BM25) 3, none 5.",
        "Grounding failures: 5 of 16 turns at time of measurement.",
    ])
    txt("Note that the seed queries were authored alongside the system. They "
        "are a bootstrap for validating the pipeline, not a benchmark, and this "
        "must be disclosed in Limitations if the final set remains "
        "developer-authored.")

    # --- 6
    h1("6.  Open risks")
    bullets([
        "Calibration is not fitted. Platt and isotonic transforms are identity "
        "until labelled data exists. The title must say 'selective', not "
        "'calibrated', until this changes.",
        "No lawyer-adjudicated gold answers. Relevance judgements are the "
        "author's own.",
        "Single jurisdiction, and a corpus weighted towards statutes over "
        "case law.",
        "The action cost vector is a hand-set prior, not derived. Expect a "
        "reviewer to press on this.",
        "A retrieval failure was observed on a legitimate Roman-Urdu family-law "
        "query, which returned zero chunks and was refused. Investigate before "
        "generating bulk traffic.",
        "The gatekeeper pattern 'you are now X' would flag 'you are now my "
        "lawyer'. Pre-existing, unaddressed.",
    ])

    # --- 7
    h1("7.  Reproducibility")
    bullets([
        "scripts/seed_traffic.py - version-controlled query set across six "
        "categories; --list, --kind, --limit.",
        "scripts/label_provenance.py - resumable labelling; --stats, --label, "
        "--top-k, --export, --export-calibration.",
        "scripts/evaluate_retrieval.py - Hit@K, MRR, nDCG.",
        "scripts/backfill_turn_type.py - schema migration, dry-run by default.",
        "Provenance records store embedding and chunking versions, so a later "
        "run can be checked against the configuration that produced it.",
    ])

    _para(doc, "", size=10)
    _rich(doc, [("Reminder: ", True, False),
                ("delete every red TODO from the paper before submission, and "
                 "confirm the page count after doing so.", False, True)],
          size=11, first_line_indent=None)

    doc.save(path)


if __name__ == "__main__":
    paper = OUT_DIR / "FIT_paper.docx"
    doss  = OUT_DIR / "Attorney_AI_Technical_Dossier.docx"
    build_paper(paper)
    build_dossier(doss)
    print(f"wrote {paper}")
    print(f"wrote {doss}")
