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
    "Retrieval-augmented legal question answering is evaluated almost entirely "
    "on answer quality, leaving two properties that matter more in practice "
    "unmeasured: whether a system knows when not to answer, and whether an "
    "answer can later be audited. We present a governance architecture for "
    "Pakistani law that treats both as first-class - hybrid retrieval over a "
    "bilingual statute corpus, deterministic statutory engines admitted as "
    "evidence by the grounding verifier, Roman-Urdu normalisation, and a single "
    "enforced output path that records every turn - and report what measuring "
    "those properties revealed. Decomposing our own confidence score gives the "
    "principal finding: its highest-weighted component was anti-correlated with "
    "answerability, scoring questions the corpus cannot answer above those it "
    "can by 0.343, a defect that worsened as the corpus grew and that the "
    "aggregate concealed. Correcting it restores the ordering, yet the "
    "answerable and unanswerable distributions still overlap, so no threshold "
    "separates them; we argue abstention here is not a question of degree in "
    "confidence but of the kind of fact requested, and decide it from the query "
    "before evidence is weighed. We further replace a hand-set action-cost "
    "vector with an expected-loss rule over an explicit harm matrix, under "
    "which the operating threshold is the harm ratio by derivation - revealing "
    "that our deployed threshold had implicitly assumed a missed answer to be "
    "four times worse than a misstatement of law. Our second finding concerns "
    "how such systems are evaluated. Fine-tuning the retriever on domain data "
    "yields +26.5 Hit@1 when tested on questions from its own training "
    "distribution and +2.4 when the question style changes; a second model, "
    "trained independently on a tenth as much data from a different source, "
    "shows the same collapse in the opposite direction. Sorting every "
    "retrieval intervention we measured by whether its gain survived a change "
    "of question style produces a clean split: those encoding legal or "
    "document structure transferred, those learning question phrasing did not, "
    "including a general-purpose cross-encoder that moved the correct statute "
    "from rank 3 to rank 10 where a deterministic statutory-scope rule placed "
    "it first in under a millisecond. Three separate contaminations - an index "
    "containing its own test answers, a systematically wrong gold-label join, "
    "and a test set sharing targets with training - each inflated a headline "
    "number until it was checked, and in every case the flattering version was "
    "the wrong one."
)

KEYWORDS = ("legal informatics, retrieval-augmented generation, selective "
            "prediction, abstention, neuro-symbolic systems, low-resource NLP, "
            "code-switching, Urdu")

# IEEE numbered style. Order MUST match first-citation order in the text, and
# must stay in sync with references.bib (which drives the LaTeX build).
# EVERY ENTRY NEEDS VERIFYING against the real paper before submission.
REFERENCES = [
    'P. Lewis et al., "Retrieval-augmented generation for knowledge-intensive NLP tasks," in Proc. Advances in Neural Information Processing Systems (NeurIPS), 2020.',

    'I. Chalkidis, M. Fergadiotis, P. Malakasiotis, N. Aletras, and I. Androutsopoulos, "LEGAL-BERT: The muppets straight out of law school," in Findings of EMNLP, 2020.',

    'N. Guha et al., "LegalBench: A collaboratively built benchmark for measuring legal reasoning in large language models," in Proc. NeurIPS, 2023.',

    'V. Karpukhin et al., "Dense passage retrieval for open-domain question answering," in Proc. EMNLP, 2020.',

    'A. Asai, Z. Wu, Y. Wang, A. Sil, and H. Hajishirzi, "Self-RAG: Learning to retrieve, generate, and critique through self-reflection," in Proc. International Conference on Learning Representations (ICLR), 2024.',

    'R. El-Yaniv and Y. Wiener, "On the foundations of noise-free selective classification," Journal of Machine Learning Research, vol. 11, pp. 1605-1641, 2010.',

    'Y. Geifman and R. El-Yaniv, "Selective classification for deep neural networks," in Proc. NeurIPS, 2017.',

    'C. Guo, G. Pleiss, Y. Sun, and K. Q. Weinberger, "On calibration of modern neural networks," in Proc. International Conference on Machine Learning (ICML), 2017.',

    'J. Platt, "Probabilistic outputs for support vector machines and comparisons to regularized likelihood methods," in Advances in Large Margin Classifiers, MIT Press, 1999.',

    'B. Zadrozny and C. Elkan, "Transforming classifier scores into accurate multiclass probability estimates," in Proc. ACM SIGKDD, 2002.',

    'A. N. Angelopoulos and S. Bates, "A gentle introduction to conformal prediction and distribution-free uncertainty quantification," arXiv preprint, 2021.',

    'S. Kadavath et al., "Language models (mostly) know what they know," arXiv preprint, 2022.',

    'Z. Ji et al., "Survey of hallucination in natural language generation," ACM Computing Surveys, vol. 55, no. 12, 2023.',

    'L. Wang, N. Yang, X. Huang, L. Yang, R. Majumder, and F. Wei, "Multilingual E5 text embeddings: A technical report," arXiv preprint, 2024.',

    'S. Robertson and H. Zaragoza, "The probabilistic relevance framework: BM25 and beyond," Foundations and Trends in Information Retrieval, vol. 3, no. 4, pp. 333-389, 2009.',

    'G. V. Cormack, C. L. A. Clarke, and S. Buttcher, "Reciprocal rank fusion outperforms Condorcet and individual rank learning methods," in Proc. ACM SIGIR, 2009.',

    'F. Perez and I. Ribeiro, "Ignore previous prompt: Attack techniques for language models," in NeurIPS ML Safety Workshop, 2022.',

    'K. Greshake, S. Abdelnabi, S. Mishra, C. Endres, T. Holz, and M. Fritz, "Not what you\'ve signed up for: Compromising real-world LLM-integrated applications with indirect prompt injection," in Proc. ACM Workshop on Artificial Intelligence and Security (AISec), 2023.',

    '"Pakistan Laws Dataset." [Online]. Available: https://huggingface.co/datasets/AyeshaJadoon/Pakistan_Laws_Dataset [VERIFY authorship, citation form and licence]',

    'Ministry of Law and Justice, Government of Pakistan, "Pakistan Code: official consolidated federal legislation." [Online]. Available: https://pakistancode.gov.pk/ (accessed Aug. 6, 2026).',

    '"LEGAL-UQA: A bilingual English-Urdu legal question answering dataset." [Online]. Available: https://huggingface.co/datasets/nlp-anonymous-researcher/LEGAL-UQA [VERIFY authorship, citation form and licence]',

    'K. Jarvelin and J. Kekalainen, "Cumulated gain-based evaluation of IR techniques," ACM Transactions on Information Systems, vol. 20, no. 4, pp. 422-446, 2002.',

    'A. B. Hou, O. Weller, G. Qin, E. Yang, D. Lawrie, N. Holzenberger, A. Blair-Stanek, and B. Van Durme, "CLERC: A dataset for U.S. legal case retrieval and retrieval-augmented analysis generation," in Proc. NAACL, 2025.',

    '"Enhancing legal LLMs through metadata-enriched RAG pipelines and direct preference optimization," arXiv:2603.19251, 2026. [VERIFY author list and venue]',

    '"Towards reliable retrieval in RAG systems for large legal datasets," arXiv:2510.06999, 2025. [VERIFY author list and venue]',
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

    # Author Block (IEEE Conference Format - 2 Authors)
    _rich(doc, [
        ("Muhammad Usama", True, False),
        ("\u00b9", True, False),
        (" and ", False, False),
        ("Muhammad Amir Zarmaan Ullah Khan", True, False),
        ("\u00b2", True, False),
    ], size=11, align="center", space_after=2, first_line_indent=0)

    _para(doc, "\u00b9,\u00b2Department of Computer Science, COMSATS University Islamabad, Pakistan",
          size=10, italic=True, align="center", space_after=2)

    p_email = doc.add_paragraph()
    p_email.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p_email.paragraph_format.space_after = Pt(10)
    p_email.paragraph_format.space_before = Pt(0)
    _add_hyperlink(p_email, "mailto:muhammadusamahoyrr@gmail.com", "muhammadusamahoyrr@gmail.com", font_size=Pt(9), color="000000", underline=True)
    r_sep = p_email.add_run(", ")
    r_sep.font.name = "Times New Roman"
    r_sep.font.size = Pt(9)
    _add_hyperlink(p_email, "mailto:kzari898@gmail.com", "kzari898@gmail.com", font_size=Pt(9), color="000000", underline=True)

    # ── Section 2: two-column body ───────────────────────────────────────────
    s1 = doc.add_section(WD_SECTION.CONTINUOUS)
    _margins(s1)
    _set_columns(s1, 2)

    _rich(doc, [("Abstract", True, True), ("\u2014", True, True), (ABSTRACT, True, True)],
          size=9, first_line_indent=0)
    _rich(doc, [("Keywords", True, True), ("\u2014", True, True), (KEYWORDS, False, True)],
          size=9, first_line_indent=0)

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
        "law built around both. We do not claim a new retrieval or generation "
        "model; the components are largely standard, and deliberately so. The "
        "contribution is a GOVERNANCE ARCHITECTURE - the arrangement that "
        "determines which evidence a verifier will accept, what the system does "
        "when the evidence is weak, which paths may produce output, and what "
        "record survives the turn - and a set of measurements showing that this "
        "arrangement is where the interesting failures live. Every substantive "
        "defect we report was invisible to answer quality and visible only to "
        "the governance layer. Our contributions are: (i) verifier-aware "
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
    _table(doc,
        "TABLE I.\tPOSITIONING AGAINST THE CLOSEST PRIOR WORK. NO "
        "PERFORMANCE FIGURES ARE COMPARED ACROSS ROWS: THE SYSTEMS TARGET "
        "DIFFERENT JURISDICTIONS, LANGUAGES AND TASKS, AND A TABLE OF HEADLINE "
        "ACCURACIES DRAWN FROM DIFFERENT DATASETS WOULD INVITE EXACTLY THE "
        "CROSS-STUDY COMPARISON SECTION VI-B ARGUES AGAINST.",
        [("Line of work", "Representative", "Contribution",
          "What it leaves open here"),
         ("Domain-adapted legal encoders", "[2], [3]",
          "In-domain pretraining and benchmarking for legal text",
          "English common-law/EU text; no abstention decision, and no evidence "
          "that adaptation transfers across question style"),
         ("Retrieval-augmented generation", "[1], [4], [5]",
          "Grounding generated answers in retrieved passages; self-reflection "
          "over retrieval quality",
          "Evaluates the answer produced, not the decision of WHETHER to "
          "answer; retrieval quality is judged, not the query's answerability"),
         ("Selective prediction and calibration", "[6], [7], [8], [11]",
          "Formalises abstention, the risk-coverage trade-off, and "
          "distribution-free coverage",
          "Applied to classifier outputs, rarely to the routing decision "
          "inside a retrieval pipeline; the operating point is tuned rather "
          "than derived from harm"),
         ("Low-resource and hybrid retrieval", "[14], [15], [16]",
          "One index across scripts; lexical-dense fusion where exact "
          "terminology matters",
          "Code-switching is treated as a language-identification problem; no "
          "account of what fusion does to a fine-tuned dense channel"),
         ("Prompt-injection robustness", "[17], [18]",
          "Attack taxonomies and classifier defences",
          "Assumes the defended component is reached; says nothing about "
          "paths that bypass it, which is the failure we report")])
    _body(doc,
        "Table I positions this work against those lines. To our knowledge, no "
        "existing system combines abstention under an "
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
    _figure(doc, "fig1_pipeline.png",
        "The governance pipeline. Two stages carry the argument of this "
        "paper: the answerability gate, which decides from the QUERY whether "
        "the corpus could hold the answer at all, before any evidence is "
        "weighed (Section V-B); and arbitration, whose operating threshold is "
        "derived from a harm ratio rather than tuned (Section V-C). Every "
        "branch terminates at one enforced output path, which is what makes "
        "the provenance record of Fig. 2 complete rather than best-effort.", 1)
    _body(doc,
        "Table II collects the notation used throughout. Four properties "
        "distinguish the design from a standard RAG pipeline: "
        "symbolic evidence admitted by the verifier (Section III-D), "
        "three-signal confidence with an explicit abstention policy "
        "(Sections III-E and III-H), code-switched retrieval (Section III-B), "
        "and per-turn provenance (Section III-K).")

    _table(doc, "TABLE II.	NOTATION USED THROUGHOUT",
           [("Symbol", "Meaning"),
            ("s", "composite confidence, (1)"),
            ("k, e-hat, l-hat", "lexical, embedding and grader signals"),
            ("T, C", "content terms of one query; its candidate set"),
            ("w(t)", "local IDF weight of term t, (2)"),
            ("c", "calibrated confidence entering arbitration"),
            ("d", "disagreement among the three signals"),
            ("L_wrong", "harm of a confident misstatement of law"),
            ("L_missed", "harm of refusing an answerable question"),
            ("L_ask", "friction of one clarification round"),
            ("rho", "harm ratio L_missed / L_wrong, (6)"),
            ("alpha", "target joint error rate, conformal layer"),
            ("Q", "evaluation query set"),
            ("G(q), R(q)", "gold chunks and ranked results for query q")])

    _subheading(doc, "B", "Corpus and Retrieval")
    _body(doc,
        "The statute corpus is drawn from a public collection of 969 Pakistani "
        "legal documents [19], itself converted from Ministry of Law and "
        "Justice publications and distributed under ODC-BY; we segment it by "
        "section and partition it into four collections by legal domain "
        "(civil, criminal, family, constitutional). It is supplemented with "
        "instruments fetched directly from the official consolidated "
        "legislation service [20], including the Code of Civil Procedure 1908 "
        "and twenty family-law statutes that the public collection omitted. "
        "The constitutional collection holds article text authenticated "
        "against the National Assembly publication; a bilingual English-Urdu "
        "constitutional question-answer set [21] supplies evaluation questions "
        "only and is NOT indexed, for reasons Section V-H reports. A separate "
        "corpus of reported judgments from six courts supports case-law "
        "retrieval. Table III reports the indexed chunk counts. Because the "
        "underlying instruments are government publications and the "
        "redistributed collection carries an attribution licence, reuse is "
        "permitted with attribution, which we give here and in the released "
        "ingestion code.")

    _table_corpus(doc)

    _body(doc,
        "Retrieval is hybrid. A BM25 index and a dense index over "
        "multilingual-e5-base embeddings are combined by weighted ensemble with "
        "weights 0.6 and 0.4 respectively, the lexical channel weighted higher "
        "because exact statute and section references carry disproportionate "
        "signal in this domain. Dense retrieval applies the asymmetric query and "
        "passage prefixes the model expects. Both channels are filtered so that "
        "a query for a given province retrieves only that province's provisions "
        "or federal ones - the dense channel by metadata predicate, the lexical "
        "channel by post-retrieval filter, since BM25 admits no index-time "
        "constraint.")
    _body(doc,
        "The filter is a mechanism, not a coverage claim, and we separate the "
        "two because conflating them would overstate the system. Of 10,042 "
        "statutory chunks, 8,434 are federal and 1,608 are provincial, and ALL "
        "of the provincial material is Punjab. A query from Sindh, Khyber "
        "Pakhtunkhwa, Balochistan, Gilgit-Baltistan or Azad Jammu and Kashmir "
        "is therefore served correctly from federal law and silently has no "
        "provincial law to consult. This matters most where devolution matters "
        "most - tenancy, rent restriction, land revenue and local taxation are "
        "provincial subjects - so the jurisdictions absent here are precisely "
        "those whose users would most need the filter to have something to "
        "select. We report the gap rather than the mechanism alone because a "
        "reader could otherwise infer five-province coverage from a filter that "
        "supports it.")
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
        "signals: a lexical score k, an embedding similarity e, and a binary "
        "relevance grade l from a fast language model. The signals are mapped "
        "into probability space by the calibration layer (Section III-F) and "
        "combined additively:")
    _equation(doc, "s = 0.40 k + 0.35 ê + 0.25 l̂", "1")
    _body(doc,
        "with the lexical term weighted highest for the same reason the lexical "
        "retrieval channel is.")
    _body(doc,
        "The lexical signal measures rarity-weighted coverage of the query's "
        "own distinctive terms, and the weighting is essential rather than "
        "cosmetic. Let T be the content terms of the query and C the retrieved "
        "candidate set. Each term t in T is weighted by its discriminating "
        "power within that candidate set:")
    _equation(doc, "w(t) = log(1 + |C| / (1 + df(t, C)))", "2")
    _body(doc,
        "and a chunk scores the share of the total weight that it contains. Two "
        "consequences follow, and Section V-A shows that both are load-bearing. "
        "A term occurring in every candidate carries almost no weight, so it "
        "cannot saturate the score; and a term occurring in no candidate "
        "remains in the denominator permanently, so an unmet requirement of the "
        "question depresses the score for as long as it goes unmet. Because df "
        "is computed over the retrieved pool rather than a fixed vocabulary, "
        "the signal adapts as the corpus grows instead of degrading with it.")
    _body(doc,
        "The embedding signal is recovered from the passage vectors already "
        "stored at ingestion, which makes it a lookup rather than a "
        "re-encoding, and is rescaled onto [0, 1] across the operating band of "
        "the embedding model. Raw multilingual E5 cosines occupy a narrow high "
        "band on this corpus (Section V-A), and passing them through unscaled "
        "would contribute a near-constant offset to every score.")
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
    _body(doc,
        "The transforms are fitted on the labelled set of Section IV. Until "
        "that set reaches sufficient volume they remain identity maps, and we "
        "report accordingly in Section V-E: the scores this paper reports are "
        "ranked, not calibrated. This is why we claim selective prediction "
        "rather than calibrated prediction.")
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
        "The source carrying the highest confidence is selected, and the "
        "action is then chosen for it by minimising expected loss.")
    _body(doc,
        "Two harms are possible and they are not symmetric: L_wrong, a "
        "confident misstatement of law acted on by the user, and L_missed, a "
        "refusal on a question the system could have answered. Writing c for "
        "the calibrated confidence and d for the disagreement among the "
        "confidence signals:")
    _equation(doc, "E[L(ANSWER)] = (1 - c) * L_wrong", "3")
    _equation(doc, "E[L(REFUSE)] = c * L_missed", "4")
    _equation(doc, "E[L(DEFER)] = L_ask + min(E[L(ANSWER)], E[L(REFUSE)]) - g*d", "5")
    _body(doc,
        "where L_ask is the friction of one clarification round and g is how "
        "much of the disagreement a clarification is expected to resolve. "
        "Answering has lower expected loss than refusing exactly when:")
    _equation(doc, "c > L_wrong / (L_wrong + L_missed) = 1 / (1 + rho),"
                   "   rho = L_missed / L_wrong", "6")
    _body(doc,
        "so the operating threshold IS the harm ratio. This matters for "
        "elicitation. A full 3x2 utility matrix has six entries, but only one "
        "degree of freedom is identifiable from behaviour: any assignment with "
        "the same ratio induces the same decision. Asking a practitioner for "
        "six numbers therefore invites answers that cannot be validated "
        "against each other, whereas rho can be elicited directly - how many "
        "unnecessary refusals are worth preventing one misstatement of law - "
        "and maps to a threshold by derivation rather than by tuning.")
    _body(doc,
        "Deferring is priced against disagreement rather than against the loss "
        "itself. A clarification does not reduce the harm of answering a "
        "question the system already understands; it reduces the chance that "
        "the confidence estimate is wrong, which is what signal disagreement "
        "measures. Consequently, when the signals agree there is nothing for a "
        "clarification to resolve and asking is strictly worse than acting. "
        "This is a departure from a threshold rule, under which every query "
        "between a refusal ceiling and a generation floor bought a "
        "clarification round regardless of whether the evidence was internally "
        "consistent.")
    _body(doc,
        "The rule is subject to three overrides. A turn retrieving zero chunks "
        "refuses unconditionally. After a bounded number of consecutive "
        "deferrals the node enters a binary mode in which it must answer or "
        "refuse, so that a mid-confidence query cannot loop indefinitely "
        "asking for clarification. Retry budget is deliberately kept outside "
        "the arbitration node: the node judges evidence, while the graph "
        "decides whether another retrieval pass is affordable. The third "
        "override, the query-side answerability check, precedes the evidence "
        "branches entirely and is described in Section V-B.")
    _body(doc,
        "The single free parameter rho is reported with a sensitivity analysis "
        "in Section V-C, and the value the deployed threshold implicitly "
        "assumes is stated there rather than left to be inferred.")

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
    _body(doc,
        "Closing that gap required distinguishing the shortcuts by what they "
        "do rather than treating them alike. Two of the three emit a fixed "
        "string and invoke no model: an injection routed to an affirmation "
        "receives a canned acknowledgement, so there is nothing for it to "
        "steer and nothing to exfiltrate, and screening those turns with a "
        "classifier would add a model call to every 'ok' while preventing "
        "nothing. The third rewrites the previous answer to a user-supplied "
        "instruction, which places attacker-controlled text into a model "
        "prompt, and it is reachable within the length bound that governs "
        "shortcut eligibility. The regex layer runs on all traffic; the "
        "classifier now additionally runs on that third path. We report the "
        "asymmetry rather than claiming both layers apply uniformly, since the "
        "distinction - screen where a model consumes untrusted text, not where "
        "a constant is returned - is what makes the cost defensible. Blocked "
        "turns record which layer stopped them, so the share of attacks caught "
        "without a model call is measurable rather than assumed.")

    _subheading(doc, "K", "Provenance")
    _verbatim(doc, 'turn_type   : answer\nquery       : "What is the current stamp duty\n               rate ... in Gilgit-Baltistan?"\narbitration : output=answer source=llm conf=0.70\nsignals     : relevance=0.70 variance=0.056\n              bm25=1.00\nstatute_chunks : 20 x Transfer of Property\n              Act 1882 (ss. 2, 130, ...)\ntool_calls  : calculate_court_fee -> FAILED\n              (validation error)\nis_grounded : true\nanswer_sha256: 4df67020...d127ade\nexecution   : 48.7 s, 9 LLM calls,\n              models=[llama-3.1-8b,\n                      llama-3.3-70b]\nversions    : e5-base/v1, chunking v1')
    _para(doc,
        "Fig. 2.  An abridged real provenance record, from the abstention "
        "failure of Section V-A. It is legible as a diagnosis WITHOUT "
        "re-running the system: a stamp-duty question answered at 0.70 "
        "confidence and marked grounded, on twenty chunks of the Transfer of "
        "Property Act, none of which state a rate, with the statutory engine "
        "having failed. The record is what made the defect findable.",
        size=8, align="justify", space_after=6)
    _body(doc,
        "Fig. 2 shows an abridged real record. "
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

    _subheading(doc, "C", "Verified Citation Supervision")
    _body(doc,
        "Fine-tuning a retriever needs query/passage supervision, which for "
        "most of this jurisdiction does not exist. We derive it from a public "
        "corpus of 11,195 Pakistani legal question/answer pairs carrying "
        "machine-parseable citations (PPC s.467, CONST art.203F) and domain "
        "labels. The answers are LLM-generated; the CITATION is what we use, "
        "because a citation is a checkable label and an answer is not. Nothing "
        "from this source is indexed.")
    _body(doc,
        "Four filters are applied in order, and their yield is reported "
        "because the rejection rate is itself informative. (1) Rows seeded "
        "from LEGAL-UQA are dropped (911), since that dataset provides our "
        "evaluation set and training on it would contaminate every other "
        "number in this paper. (2) Citations are resolved against the indexed "
        "corpus; those naming a section we do not hold are dropped (720), "
        "including all 208 civil-procedure rows before the Code of Civil "
        "Procedure was ingested. (3) Each surviving citation is VALIDATED: the "
        "cited section must share rarity-weighted vocabulary with the answer, "
        "because LLM-generated citations are sometimes wrong and a confidently "
        "wrong citation trains the retriever to reproduce the error (203 "
        "dropped). (4) Duplicates are removed. 5,883 pairs survive (52.6%), of "
        "which 32% have Urdu-script queries against English statute - the "
        "code-switched retrieval case this system exists to serve, and one for "
        "which we previously had no training data at all.")
    _body(doc,
        "Validation is deliberately lexical rather than embedding-based. "
        "Scoring candidate pairs with the base model and keeping those it "
        "already agrees with would discard exactly the hard examples that "
        "carry signal, and would flatter the fine-tuning that follows. It also "
        "proved to be an effective corpus check: it flagged citations to "
        "Article 9 as topically inconsistent, and the citations were correct - "
        "the corpus was wrong, indexing 164 Schedule paragraphs as Articles "
        "1-8, which include the fundamental rights and the high-treason "
        "provision. That defect had been serving Schedule text under the "
        "citation of a constitutional right.")

    _subheading(doc, "D", "Metrics")
    _body(doc,
        "Let Q be the evaluation query set and, for a query q, let R(q) = "
        "(c_1, ..., c_k) be the ranked chunk identifiers returned at cut-off k "
        "and G(q) the set of gold chunks. Write rank(q) for the position of "
        "the first relevant chunk, and infinity if none is retrieved. "
        "Retrieval [22] is then reported by:")
    _equation(doc, "Hit@k = (1/|Q|) * SUM_q  1[ rank(q) <= k ]", "7")
    _equation(doc, "MRR = (1/|Q|) * SUM_q  1 / rank(q)", "8")
    _equation(doc, "nDCG@k = (1/|Q|) * SUM_q  DCG(q) / IDCG(q)", "9")
    _para(doc,
          "DCG(q)  = SUM over i=1..k  of  1[ c_i in G(q) ] / log2(i + 1)",
          size=9, align="center", space_after=1)
    _para(doc,
          "IDCG(q) = SUM over i=1..min(|G(q)|, k)  of  1 / log2(i + 1)",
          size=9, align="center", space_after=4)
    _body(doc,
        "where 1[.] is the indicator function and 1/infinity = 0 by "
        "convention, so a query with no relevant chunk in the top k "
        "contributes zero to every metric. We state the ideal-DCG denominator "
        "of (9) explicitly because a fixed denominator of 1 - correct only "
        "when |G(q)| = 1 - is a defect we found in one of our own evaluation "
        "scripts, and it silently deflates nDCG on the multi-gold queries that "
        "matter most.")
    _body(doc,
        "Metrics are computed at cut-offs within the pooling depth. "
        "Selective prediction is reported by "
        "risk-coverage curves, the area under the risk-coverage curve, and "
        "expected calibration error, together with the rate of ungrounded "
        "answers at a given coverage. Robustness is reported as the proportion "
        "of adversarial inputs refused, measured with all bypass paths closed.")

    # V. Results
    _heading(doc, "V", "Results")
    _body(doc,
        "The corpus comprises 10,042 statutory chunks across the four "
        "retrieval collections (Table III) and a separately indexed judgment "
        "corpus of 7,529 chunks drawn from six courts. Three of the four "
        "collections changed materially during this work, and for reasons the "
        "evaluation surfaced rather than planned: the constitutional "
        "collection was rebuilt after 67% of it proved to be generated text "
        "(Subsection H), the Code of Civil Procedure 1908 was found to be "
        "absent entirely, and family law - the smallest collection and the one "
        "where a wrong answer does most harm - grew from 193 to 989 chunks "
        "once twenty statutes listed in the project's own fetch manifest were "
        "actually downloaded. Corpus defects, not model capacity, accounted "
        "for the largest single improvements we made.")
    _body(doc,
        "We report studies that do not require the labelled set. We "
        "distinguish three kinds of "
        "result explicitly, because they carry different evidential weight and "
        "conflating them would overstate the work. DESIGN RESULTS are "
        "properties of the architecture we argue for and demonstrate: that "
        "abstention is decidable from the query (Subsection B), and that a "
        "decision threshold can be derived from a harm ratio rather than tuned "
        "(Subsection C). EMPIRICAL FINDINGS are measurements whose interest "
        "does not depend on this system being well built - the inverted "
        "confidence signal (Subsection A) and the reranking result (Subsection "
        "D) would hold for any system making the same reasonable choices, and "
        "the latter is corroborated independently. IMPLEMENTATION DEFECTS are "
        "bugs we found and fixed; they are reported because their FAILURE "
        "MODES generalise - a malformed model response accepted as a confident "
        "judgement, a cache serving answers that outlived the logic producing "
        "them - but a bug fixed is not a contribution and we do not present it "
        "as one. Subsection I states plainly what remains unmeasured.")

    _subheading(doc, "A", "The Confidence Signal Was Anti-Correlated with "
                          "Answerability")
    _body(doc,
        "A regression prompted this analysis. After the corpus was expanded, a "
        "query the corpus cannot answer - the current stamp-duty rate for "
        "property transfer in Gilgit-Baltistan - became more confident, rising "
        "from 0.57 to 0.70 and moving from ungrounded to grounded. Growing the "
        "evidence base had made the system more assured about a question it "
        "could not answer.")
    _body(doc,
        "Decomposing (1) showed why. Of the three signals, one was defective "
        "and two were constants. The lexical signal, weighted highest at 0.40, "
        "matched the query against a fixed list of general legal terms and "
        "scored a chunk by the fraction of those terms it contained. Almost "
        "every question contains exactly one such term, so the signal collapsed "
        "into a test of whether a chunk mentions that single word - which "
        "nearly every chunk does. 'Property' occurs in every provision of the "
        "Transfer of Property Act; 'court' occurs in most statutes; while "
        "'stamp duty', 'Gilgit-Baltistan' and '2019', the terms that actually "
        "determine whether the corpus holds an answer, were invisible to the "
        "scorer.")
    _body(doc,
        "Table IV gives the effect. Under the fixed-vocabulary signal, the mean "
        "lexical score of the unanswerable queries exceeded that of the "
        "answerable ones by 0.343: confidence was not merely uninformative but "
        "inverted with respect to the system's ability to answer. The failure "
        "also worsened monotonically with corpus growth, because a larger "
        "corpus retrieves more chunks containing the common term. Replacing it "
        "with rarity-weighted coverage restores the ordering to +0.090.")
    _table(doc, "TABLE IV.\tMEAN LEXICAL SCORE, FIXED VOCABULARY VS "
                "RARITY-WEIGHTED COVERAGE",
           [("", "Query", "Fixed", "Weighted"),
            ("A", "punishment for theft (PPC)", "0.438", "0.569"),
            ("A", "eviction without notice", "0.000", "0.358"),
            ("A", "grounds for khula", "0.444", "0.162"),
            ("A", "refusal to register an FIR", "0.053", "0.098"),
            ("A", "fundamental rights", "0.000", "0.184"),
            ("A", "limitation period, civil suit", "0.056", "0.216"),
            ("A", "dishonoured cheque (s. 489-F)", "0.462", "0.160"),
            ("A", "share in Islamic inheritance", "0.000", "0.061"),
            ("U", "current stamp-duty rate", "0.789", "0.118"),
            ("U", "cases pending in the LHC, 2019", "0.733", "0.227"),
            ("U", "my lawyer's phone number", "0.050", "0.063"),
            ("", "mean, answerable (A)", "0.181", "0.226"),
            ("", "mean, unanswerable (U)", "0.524", "0.136"),
            ("", "separation", "-0.343", "+0.090")],
           bold_last_rows=1)
    _body(doc,
        "The second signal was not a signal at all. The ensemble retriever "
        "exposes no per-document scores, so every chunk was assigned a neutral "
        "0.5 embedding similarity: 35% of every confidence score was a fixed "
        "offset, contributed identically to an exact statutory match and to an "
        "unanswerable question. Recovering the ingestion-time passage vectors "
        "costs 26 ms for 19 chunks plus 150 ms for one query encoding, and "
        "yields a signal that does discriminate - though weakly. Averaged per "
        "query, answerable queries score 0.818 (range 0.790-0.848) against "
        "0.789 (0.768-0.801) for unanswerable ones. The bands are narrow and "
        "adjacent, which is why the raw cosine must be rescaled over the "
        "operating range rather than treated as a probability.")
    _body(doc,
        "The third signal was unvalidated. The relevance grader runs on a small "
        "fast-tier model, which was observed returning an array of 130 grades "
        "for 8 chunks; because the scorer pads and truncates its inputs, this "
        "was silently accepted as a judgement that all eight chunks were "
        "irrelevant - a malformed response entering the audit trail "
        "indistinguishably from a considered one. Length-checking the response "
        "and routing failures into the existing neutral degradation path "
        "removes this. We note the general lesson: a signal whose failure mode "
        "is a confident wrong value rather than an absent value is more "
        "dangerous than no signal, and only length validation distinguishes "
        "them.")

    _subheading(doc, "B", "Repairing the Signals Does Not Separate "
                          "Answerability")
    _body(doc,
        "With the lexical signal corrected and the embedding signal supplied, "
        "the aggregate score orders the two classes correctly - mean 0.429 for "
        "answerable against 0.333 for unanswerable - but their ranges overlap. "
        "Answerable queries span 0.309-0.662 and unanswerable ones 0.273-0.412, "
        "so the worst answerable query scores below the best unanswerable one. "
        "No threshold on c separates the classes; each cut only trades false "
        "refusals against false answers.")
    _body(doc,
        "This is the central negative result on abstention: the difference "
        "between these classes is not one of degree in confidence, and treating "
        "it as one is a category error. What distinguishes 'the current "
        "stamp-duty rate' from 'the grounds for khula' is not that the "
        "retrieved law is less similar - it is that no statute states a rate in "
        "force today. Deciding this from the query, before evidence is weighed, "
        "is deterministic and costs nothing. On a set of 27 queries constructed "
        "to stress the boundary, the query-side check admitted 17/17 answerable "
        "queries and identified 10/10 unanswerable ones.")
    _body(doc,
        "That set was written by the author while building the check, and both "
        "figures should be read accordingly. Constructing the boundary cases "
        "and the rule that separates them together is a design activity, not "
        "an evaluation: the numbers establish that the classes are separable by "
        "a deterministic query-side test, which is the claim being made, and "
        "not that this particular rule generalises to queries it was not "
        "written against. We report them here rather than in the Limitations "
        "alone, because a precision figure quoted without its provenance "
        "invites exactly the reading it does not support.")
    _body(doc,
        "Precision matters more than recall here, because a false positive "
        "refuses a question the system could have answered and the user cannot "
        "distinguish that refusal from a genuine gap in the law. Two false "
        "positives found during development are instructive, and both are "
        "near-misses that share surface vocabulary with an unanswerable class: "
        "'how many days do I have to file an appeal' is a limitation question "
        "rather than a court statistic, and 'the procedure to recover my "
        "lawyer's fee' is the law of costs rather than a personal record. Both "
        "are retained as regression tests. Refusals name the reason and "
        "redirect to where the answer does live - the provincial Board of "
        "Revenue for a notified rate, judicial statistics for a pendency figure "
        "- since a bare statement of failure is indistinguishable from a "
        "retrieval miss and simply invites the user to rephrase.")
    _body(doc,
        "One architectural finding accompanies this. Verified end-to-end after "
        "the fix, the stamp-duty query still answered at 0.85 confidence, "
        "because a cache hit routes directly to the finalising node and "
        "bypasses arbitration altogether. An answer produced by the defective "
        "scorer had outlived the correction of that scorer. This is the same "
        "class of defect reported in Section VI for the injection gatekeeper - "
        "a decision point that alternative paths can skip - and it suggests "
        "that any change to a routing authority must be accompanied by an audit "
        "of every path that reaches the output without consulting it.")

    _subheading(doc, "C", "The Harm Ratio and Its Sensitivity")
    _body(doc,
        "The decision rule of (6) has one free parameter. Read in reverse, it "
        "also tells us what an operating threshold set some other way "
        "implicitly assumes, and that is worth doing before anything else. Our "
        "deployed generation floor of 0.20 was seeded as a percentile of a "
        "score distribution and was never a statement about harm. It "
        "corresponds to rho = 4: it commits the system to a missed answer "
        "being FOUR TIMES worse than a misstatement of law, the inverse of the "
        "asymmetry the system is designed around. Nothing connected the "
        "threshold to the harm it encodes until it was written down this way.")
    _body(doc,
        "Table V sweeps rho over the measured confidences. The parameter "
        "behaves as it should - raising the penalty on wrong answers raises "
        "the threshold and reduces coverage - but the columns move TOGETHER. "
        "There is no rho at which the system answers the answerable queries "
        "and refuses the unanswerable ones. This is the same overlap reported "
        "in Subsection B, now visible through the decision rule: because the "
        "two classes are not separated in confidence, no setting of a "
        "confidence-based rule can separate them in action either.")
    _table(doc, "TABLE V.	HARM RATIO VS COVERAGE (A: 9 ANSWERABLE, "
                "U: 4 UNANSWERABLE)",
           [("rho", "threshold", "answered A", "answered U"),
            ("10",   "0.091", "9/9", "4/4"),
            ("4",    "0.200", "9/9", "4/4"),
            ("2",    "0.333", "7/9", "2/4"),
            ("1",    "0.500", "1/9", "0/4"),
            ("0.5",  "0.667", "0/9", "0/4"),
            ("0.1",  "0.909", "0/9", "0/4")])
    _body(doc,
        "Two practical consequences follow. First, rho governs only how "
        "conservative the fallback is BEHIND the query-side check of "
        "Subsection B; it is not the mechanism that distinguishes answerable "
        "from unanswerable, and presenting it as one would misattribute the "
        "result. Second, plausible-looking harm assignments are more "
        "aggressive than they appear. A utility matrix penalising a wrong "
        "answer at -100 against +10 for a correct one, -10 for an unnecessary "
        "refusal and +5 for a correct one - values that read as reasonable - "
        "induces a threshold of 0.84, above every confidence we measured, and "
        "would refuse all traffic. We therefore retain rho = 4, which "
        "preserves the deployed operating point, and report the assumption "
        "rather than presenting a tuned threshold as a principled one.")

    _subheading(doc, "D", "Cross-Encoder Reranking: A Negative Result")
    _body(doc,
        "Adding a cross-encoder reranker is the standard remedy for the symptom "
        "we faced - the correct statute retrieved but ranked below a lexically "
        "similar competitor - so we implemented and measured it rather than "
        "assuming it. Table VI reports the decisive case. The query asks "
        "whether a tenant may be evicted without notice in Punjab; the correct "
        "instrument is the Punjab Rented Premises Act 2009, governing urban "
        "rental, and the competitor is the Punjab Tenancy Act 1887, governing "
        "agricultural tenancy. Both are genuinely about tenants and eviction, "
        "so this is an ambiguity of statutory scope rather than a vocabulary "
        "gap, and it appeared only as the corpus grew to include provincial "
        "law.")
    _table(doc, "TABLE VI.\tRANK OF THE CORRECT STATUTE (PUNJAB RENTED "
                "PREMISES ACT 2009) AND MEDIAN LATENCY, AT BOTH DEPTHS",
           [("Depth", "Configuration", "Rank", "Top-1 statute"),
            ("k=10 (19)", "first stage",       "3",  "Tenancy 1887"),
            ("",          "+ scope rules",     "1",  "Rented Premises 2009"),
            ("",          "+ cross-encoder",   "10", "Tenancy 1887"),
            ("k=50 (58)", "first stage",       "4",  "Tenancy 1887"),
            ("",          "+ scope rules",     "1",  "Rented Premises 2009"),
            ("",          "+ cross-encoder",   "24", "Tenancy 1887")])
    _body(doc,
        "The cross-encoder does not merely fail to help here; it moves the "
        "correct statute AWAY from the top, from rank 3 to rank 10 at the "
        "deployed depth and from 4 to 24 when the pool is widened, and at both "
        "depths it promotes the agricultural statute - precisely the confusion "
        "it was introduced to resolve. The degradation grows with pool size, "
        "which is the signature of a scoring function that is not merely noisy "
        "but systematically ordered against the target: more candidates give it "
        "more opportunities to prefer the wrong one. The deterministic scope "
        "rules place the correct statute first at both depths in under a "
        "millisecond, against 0.73 s and 2.43 s for the reranker.")
    _body(doc,
        "The failure is not uniform, and reporting it as such would overstate "
        "it. Across six queries the reranker improved three (the khula target "
        "from rank 8 to 4, an FIR-registration query from 2 to 1, a theft query "
        "from 3 to 1), left two unchanged, and badly worsened one. But the one "
        "it worsens is the case that motivated it. The queries it improves were "
        "already nearly correct - the right statute was in the top three - so "
        "it is sharpening rankings that did not need sharpening while inverting "
        "the one that did.")
    _body(doc,
        "We attribute this to a train/test distribution shift rather than to "
        "model capacity. The checkpoint is trained on MS MARCO, whose relevance "
        "judgements concern short web passages answering informational queries. "
        "Pakistani statutory text is long, formally structured, and dense in "
        "cross-references, and crucially the distinction the query turns on - "
        "whether 'tenant' means a cultivator under an 1887 revenue statute or "
        "an occupant of urban premises under a 2009 one - is a matter of "
        "legislative scope that is not recoverable from lexical similarity "
        "between the query and the passage. Both statutes discuss tenants, "
        "eviction and notice. A relevance model trained on topical overlap has "
        "no representation of which instrument GOVERNS. Prior work reports the "
        "same direction of effect: cross-encoder reranking has been found to "
        "degrade legal case retrieval, attributed to domain mismatch on long "
        "legal text with a style and length unlike the reranker's training "
        "data [23]. That this reproduces on statutory rather than case-law "
        "retrieval, in a different jurisdiction and language setting, suggests "
        "it is a property of the domain and not of one corpus.")
    _body(doc,
        "Widening first-stage retrieval from 10 to 50 candidates was reverted "
        "alongside it. The two are inseparable: without an effective reranker, "
        "additional depth is additional noise. Under the wider pool the khula "
        "query's target statute fell from rank 8 to rank 14, and as Table VI "
        "shows the reranker's own error grows with the pool it is given.")
    _body(doc,
        "We report this as a negative result rather than omitting it. A "
        "legal-domain cross-encoder, or one fine-tuned on statute-scope pairs, "
        "may well succeed where the generic model failed; the finding is that "
        "the off-the-shelf model is actively harmful on this text, not that "
        "reranking is unsound. The mechanism above is testable, and predicts "
        "that fine-tuning on statute-scope pairs should help where scaling the "
        "generic model would not.")

    _subheading(doc, "E", "Domain Fine-Tuning: Large In-Distribution Gains "
                          "That Do Not Transfer")
    _body(doc,
        "The diagnosis of Subsection D left a specific gap. On 200 held-out "
        "constitutional questions the correct article is retrievable at dense "
        "depth 50 for 89% of them but reaches rank 1 for only 43.5% - a "
        "45-point RANKING deficit rather than a recall one. Reranking having "
        "failed, the remaining hypothesis was that a general-purpose "
        "multilingual embedding model does not know Pakistani statutory "
        "language. We tested it by fine-tuning.")
    _body(doc,
        "Two models were trained, deliberately at different scales and from "
        "different sources, so that any pattern could be checked for "
        "consistency rather than read off a single run. The CONSTITUTIONAL "
        "model uses 471 question/article pairs from LEGAL-UQA. The GENERAL "
        "model uses 4,692 pairs spanning constitutional, criminal, evidence, "
        "civil procedure and family law, built from the citation-annotated "
        "corpus verified in Section IV-C; a third of its queries are in Urdu "
        "script. Both use multilingual-e5-base with multiple-negatives ranking "
        "loss and hard negatives mined from the deployed retriever, and both "
        "are split by connected components over shared gold chunks so that no "
        "gold chunk appears in both halves. Table VII gives the configuration "
        "in full, so that the comparison can be reproduced or contradicted.")
    _table(doc, "TABLE VII.\tFINE-TUNING CONFIGURATION. IDENTICAL "
                "APART FROM THE TRAINING CORPUS, SO THE DIFFERENCE BETWEEN THE "
                "TWO MODELS IS THE DATA AND NOT THE RECIPE.",
           [("Property", "constitutional", "general"),
            ("Training pairs", "471", "4,692"),
            ("Held-out pairs", "121", "1,191"),
            ("Legal domains", "1", "5"),
            ("Urdu-script queries", "0%", "32%"),
            ("Source", "LEGAL-UQA", "citation corpus"),
            ("Base model", "multilingual-e5-base", ""),
            ("Loss", "multiple-negatives ranking", ""),
            ("Hard negatives", "mined from the deployed retriever", ""),
            ("Epochs / batch / lr", "2 / 12 / 2e-5", ""),
            ("Max sequence length", "224 tokens", ""),
            ("Train/test split", "connected components over G(q)", ""),
            ("Significance test", "McNemar, paired on Q", "")])
    _figure(doc, "fig4_transfer_collapse.png",
        "The transfer result. Two models trained independently, on "
        "different sources, at a tenfold difference in scale, lose almost "
        "the whole of their gain when the question style changes. The "
        "left-hand points are what an in-distribution evaluation would "
        "report; the right-hand points are what a deployment would "
        "experience. The constitutional model's apparent 0.766 on its own "
        "distribution is excluded as memorisation and is not plotted "
        "(Section V-H).", 3)
    _table(doc,
        "TABLE VIII.\tHIT@1 PER MODEL, ON ITS OWN TRAINING DISTRIBUTION AND ON "
        "THE OTHER. EACH MODEL'S OUT-OF-DISTRIBUTION COLUMN (ITALICISED IN "
        "TEXT) IS THE HONEST MEASURE OF TRANSFER.",
        [("Test set", "base", "constitutional", "general"),
         ("Citation-style, held out", "0.4148", "0.4114", "0.6801"),
         ("(general's distribution)", "", "-0.3", "+26.5"),
         ("LEGAL-UQA style, held out", "0.5234", "0.7656 (a)", "0.5469"),
         ("(constitutional's dist.)", "", "-", "+2.4")])
    _para(doc,
        "(a) Not reportable: 106 of these 128 questions, and 48 of 59 gold "
        "chunks, were in the constitutional model's training set "
        "(Subsection H).", size=8, align="justify", space_after=4)
    _body(doc,
        "Table VIII reports Hit@1 for every model on both test sets, and "
        "Fig. 3 states the same result as transfer. Measured on its own "
        "distribution the general model gains +26.5 Hit@1, "
        "a 64% relative improvement, significant at p = 0.0005 by McNemar's "
        "test on 531 improved against 123 worsened pairs. Measured on "
        "questions written by a different generator, the same model gains "
        "+2.4, with 31 improved against 22 worsened - close to a coin flip. "
        "The constitutional model shows the same pattern from the other "
        "direction: on its own distribution it gains +16.5 dense and +6.6 once "
        "fused with BM25 (Subsection F); on citation-style questions it gains "
        "-0.3. We verified that this second figure is clean - none of the "
        "1,191 citation-style test questions appear in its training set.")
    _body(doc,
        "Ten times the training data, five legal domains and two scripts "
        "bought a larger in-distribution number and essentially nothing out of "
        "it. The effect replicates across two models trained independently on "
        "different sources at different scales, which is what makes it a "
        "finding about the method rather than about one run.")

    _subheading(doc, "F", "Why the Fusion Layer Absorbs the Gain")
    _body(doc,
        "A second reduction occurs before deployment. The figures above are "
        "dense-only; the deployed retriever fuses BM25 at 0.6 with dense at "
        "0.4. Rebuilding both indexes at identical sequence length so that "
        "only the weights differ, the constitutional model's +16.5 becomes "
        "+6.6 under fusion. The mechanism is visible in the baselines: hybrid "
        "base scores 0.5207 against dense base 0.4380, so BM25 was already "
        "supplying +8.3 points on its own. Much of what fine-tuning teaches "
        "the dense channel, the lexical channel already knew, and overlapping "
        "gains do not add.")
    _body(doc,
        "Fusion also REPAIRS the characteristic damage. Under dense-only "
        "retrieval four queries fell from a found rank to absent, all of them "
        "exact-citation lookups; under fusion the worst regression is rank 1 "
        "to rank 3. A system reporting only its dense ablation would overstate "
        "both the benefit and the harm.")

    _subheading(doc, "G", "Failures Resolved Without Additional Data")
    _body(doc,
        "Three queries that failed before the corpus expansion were re-tested "
        "after it. All three now succeed, and none was fixed by the additional "
        "data. A maintenance query in Roman Urdu failed because a "
        "model-assigned language label overrode the script actually observed; "
        "the eviction query failed on the statutory-scope ambiguity of "
        "Subsection D; and the khula query failed because the classifier's "
        "case-type verdict was computed and then discarded one node later, so "
        "the turn was routed to clarification and never retrieved anything. "
        "Each was a defect in the handling of a signal, not an absence of law, "
        "and we note that a purely data-centric response - ingesting more "
        "statutes - would have resolved none of them while appearing to be the "
        "obvious remedy.")

    _subheading(doc, "H", "Three Contaminations, Each Found by Looking")
    _body(doc,
        "Every fine-tuning result above survived a contamination check that "
        "removed an earlier, better-looking number. We report the three "
        "failures because each was invisible in the metrics and each would "
        "have inflated a headline figure.")
    _body(doc,
        "THE INDEX CONTAINED THE TEST ANSWERS. The constitutional collection "
        "held 619 generated question/answer pairs alongside 305 article "
        "extracts, all tagged as the Constitution, and the generated pairs "
        "contained each evaluation question verbatim. They accounted for "
        "81-100% of retrieved chunks on ordinary constitutional queries. "
        "Evaluating before removing them would have retrieved each question's "
        "own answer at rank 1.")
    _body(doc,
        "THE GOLD LABELS WERE SYSTEMATICALLY WRONG. Joining evaluation "
        "questions to gold passages by section heading produced an off-by-one: "
        "the source PDF's marginal notes are extracted as heading-only stubs, "
        "so the heading of Article 25 matched a stub rather than the chunk "
        "holding its text. Retrieval was returning the correct chunk and the "
        "evaluation scored it as a miss. The signature was Hit@1 of exactly "
        "0.000 across 568 questions - a number implausible enough to prompt a "
        "check. Rebuilding the join on verbatim body n-grams moved MRR from "
        "0.114 to 0.581 with no change to the system.")
    _body(doc,
        "THE TEST SET SHARED TARGETS WITH TRAINING. For the cross-style "
        "evaluation, 99 of 121 candidate questions had gold chunks that were "
        "also training positives for the general model - different questions, "
        "identical targets. This is target leakage rather than question "
        "leakage, and it is not caught by deduplicating queries. Filtering to "
        "genuinely unseen targets across the full 592-question set left 128 "
        "usable questions.")
    _body(doc,
        "A fourth check applies to Table VIII. The constitutional model's "
        "apparent 0.7656 on LEGAL-UQA-style questions is memorisation: 106 of "
        "those 128 questions were in its training set, because that set is "
        "drawn from LEGAL-UQA. Between them the two models had consumed 464 "
        "and 471 of the 592 available questions, leaving only 22 unseen by "
        "both - too few to support a three-way comparison. The "
        "out-of-distribution columns are the only ones we report.")

    _subheading(doc, "I", "What Is Not Yet Measured")
    _body(doc,
        "The ranking and selective-prediction metrics of Section IV - Hit@k, "
        "MRR, nDCG@k, risk-coverage curves and expected calibration error - "
        "require the pooled labelled set, which is not yet of sufficient volume "
        "to report. We state this rather than substitute proxies. The same set "
        "would settle the generalisation question left open in Subsection B: "
        "the query-side check needs to be run against queries authored "
        "independently of it, with the unanswerable classes labelled by someone "
        "who did not write the rules, before its precision can be claimed as a "
        "property of the method rather than of the examples it was built from. "
        "In particular "
        "the calibration transforms remain identity maps: the architecture "
        "places Platt scaling and isotonic regression on the correct path and "
        "the fitted parameters are the only missing component, so the "
        "confidence values reported above are ranked scores and are not claimed "
        "to be calibrated probabilities. This is why the contribution is stated "
        "as selective prediction rather than calibrated prediction.")

    # VI. Discussion and Limitations
    _heading(doc, "VI", "Discussion and Limitations")

    _subheading(doc, "A", "Why Fine-Tuning Did Not Generalise")
    _body(doc,
        "The two fine-tuned models gained +26.5 and +16.5 Hit@1 on their own "
        "distributions and +2.4 and -0.3 outside them. We offer an explanation "
        "that the rest of our results support, and which predicts which "
        "interventions succeed. Sorting every retrieval intervention we "
        "measured by whether its effect survived a change of question style "
        "produces a clean split. TRANSFERRED: statute-scope rules (rank 12 to "
        "1), the query-side answerability check, corpus repairs. DID NOT "
        "TRANSFER: fine-tuned embeddings (+2.4), cross-encoder reranking (rank "
        "3 to 10), fusion-weight tuning (no gain).")
    _body(doc,
        "The dividing line is not complexity or cost. It is WHAT THE "
        "INTERVENTION ENCODES. Everything in the first group encodes a "
        "property of the law or the documents: which instrument governs urban "
        "tenancy as against agricultural tenancy, what kind of fact a statute "
        "can state, what the corpus actually contains. Everything in the "
        "second learns a mapping from question surface form to passage.")
    _body(doc,
        "Legal language is the reason this matters more here than elsewhere. A "
        "statutory corpus is small, highly structured, and written in a "
        "register no user employs; the gap between a question and its answer "
        "is a gap of REGISTER, not of topic. A model fine-tuned on one "
        "generator's phrasing learns to close that specific gap, and a "
        "differently-phrased question reopens it. The rule that the Punjab "
        "Rented Premises Act 2009 governs shops and houses while the Punjab "
        "Tenancy Act 1887 governs cultivators is true regardless of how the "
        "question is worded, and it cost four milliseconds.")
    _body(doc,
        "The failure mode is consistent in the errors as well as the "
        "aggregates. The same query - an exact citation lookup, 'What was "
        "omitted by S.R.O. No. 1278 (1) 85?' - fell from rank 1 to absent "
        "under the cross-encoder, under the constitutional model, and under "
        "the general model. All three interventions traded lexical precision "
        "for semantic similarity, because that is what optimising a dense "
        "objective on paraphrased questions rewards. Fusion with BM25 "
        "partially repairs the damage, which is further evidence that what was "
        "lost was lexical rather than legal.")
    _body(doc,
        "We do not claim fine-tuning cannot work for legal retrieval. We claim "
        "that training on questions from a single generator produces a model "
        "fitted to that generator, that this is invisible when the test set "
        "shares the generator, and that the in-distribution number is "
        "therefore not evidence of deployment benefit. A model trained on "
        "genuinely diverse, human-authored queries might behave differently; "
        "we could not test that, because no such set exists for this "
        "jurisdiction.")

    _subheading(doc, "B", "Leakage-Free Evaluation Is the Load-Bearing "
                          "Component")
    _body(doc,
        "Three of our results were wrong before they were checked (Section "
        "V-H), and in every case the wrong version was the flattering one: a "
        "corpus containing its own test answers, a gold-label join that made "
        "correct retrievals look like failures, and a test set sharing targets "
        "with training. None was visible in the metrics. Two were found only "
        "because a number looked implausible - Hit@1 of exactly 0.000, and two "
        "columns that agreed too closely. We draw three practical conclusions.")
    _body(doc,
        "CONTAMINATION IN RETRIEVAL SYSTEMS HAS MORE SURFACES THAN IN "
        "CLASSIFICATION. A question can leak, a gold label can leak, and - as "
        "here - the INDEX can leak, because the corpus under evaluation is "
        "itself a system component. Deduplicating queries catches none of the "
        "latter two.")
    _body(doc,
        "GENERATED EVALUATION SETS CARRY THEIR GENERATOR'S SIGNATURE. Both "
        "datasets that supplied our labels were LLM-generated against statute. "
        "That makes them usable as training signal, since the citation is a "
        "checkable label, and unreliable as benchmarks, since a model trained "
        "on one generator is tested on its own idiom. The +26.5 to +2.4 "
        "collapse is the size of that effect.")
    _body(doc,
        "THE MEASUREMENT PROTOCOL DETERMINED THE CONCLUSIONS MORE THAN ANY "
        "TECHNIQUE DID. Our largest reported gain, +6.6 Hit@1 under fusion, is "
        "the one that survived every check. The three larger numbers did not "
        "survive. A system paper that reports only its best configuration on "
        "its own evaluation set is not making a weaker claim than ours - it is "
        "making an unfalsifiable one.")

    _subheading(doc, "C", "Future Work")
    _body(doc,
        "The immediate constraint is not method but measurement. Every "
        "evaluation asset used here is either authored by the system's "
        "developer or drawn from a training generator, and the honest "
        "consequence is that we cannot presently prove an end-to-end "
        "improvement.")
    _body(doc,
        "AN INDEPENDENT BENCHMARK, FROZEN BEFORE USE. We have identified 3,852 "
        "Pakistani legal questions used to train none of our models. Labelling "
        "a subset with two annotators, reporting Krippendorff's alpha, and "
        "FREEZING half before any development begins would give the first "
        "evaluation set this work could not have tuned against. "
        "Pre-registering the predicted effect and opening the frozen half once "
        "is what would convert a measurement into evidence.")
    _body(doc,
        "STRUCTURE-AWARE CHUNKING. Our strongest untested lever follows the "
        "principle of Subsection A: it is structural. Between 20 and 27% of "
        "each collection is under 200 characters - heading fragments competing "
        "for retrieval slots - and 11% of failures are recall rather than "
        "ranking. Aligning chunk boundaries to statutory structure and "
        "prepending instrument and section metadata before embedding addresses "
        "both, and should place the citation string inside the passage where "
        "the lexical channel can reach it [24], [25].")
    _body(doc,
        "GENERATION CORRECTNESS. Every number in this paper measures "
        "retrieval. Users receive generated answers, and we verify that "
        "answers are GROUNDED in retrieved text without verifying that they "
        "are CORRECT. Those differ, and the difference is where a legal "
        "assistant causes harm: a fluent answer, correctly grounded in a "
        "correctly retrieved provision, that misstates what the provision "
        "means. Even at perfect retrieval we would have no evidence of legal "
        "correctness. Establishing that requires practitioner adjudication of "
        "emitted answers, and it is the measurement we would prioritise above "
        "all others.")
    _body(doc,
        "FITTING THE CALIBRATION LAYER. The conformal and harm-matrix "
        "machinery of Sections III-F and III-H is implemented and inert "
        "pending labelled data. Once fitted, the coverage guarantee becomes "
        "reportable and the harm ratio can be elicited from practitioners "
        "rather than inherited from a threshold.")

    _subheading(doc, "D", "Observations on the Governance Layer")
    _body(doc,
        "Four further findings from deployment generalise beyond this "
        "system, and each concerns the governance layer rather than any model "
        "in it. First, "
        "defence in depth at a single point in a pipeline is insufficient when "
        "alternative paths exist that skip that point. An "
        "intent-classification shortcut answered certain turns without entering "
        "the graph and so bypassed the injection gatekeeper entirely; the "
        "classifier was not weak, it was simply not consulted. A result cache "
        "produced the same failure at the opposite end of the pipeline, serving "
        "a stored answer without consulting the arbitration node that would "
        "have refused it, so that a correction to the decision logic did not "
        "take effect on cached traffic. Any robustness "
        "figure measured in either configuration is computed only over traffic "
        "that reached the defended component, which is a measurement error "
        "rather than a model error. Second, in a specialised domain, "
        "keyword-based safety filters collide with legitimate vocabulary: our "
        "injection filter matched a power-of-attorney question containing the "
        "phrase 'unrestricted agent'. The cost of a false positive here is "
        "refusing a user with a genuine legal problem, which argues for narrow "
        "patterns backed by a model layer rather than broad ones. Third, a "
        "confidence signal can be inverted rather than merely weak, and an "
        "aggregate score will conceal this: the composite of Section V-A "
        "appeared to behave reasonably while one of its components was "
        "anti-correlated with correctness and two others were effectively "
        "constant. We would encourage reporting per-signal separation, not only "
        "aggregate confidence, in any system that combines heterogeneous "
        "evidence. Fourth, formalising an informal rule changes behaviour, and "
        "not only where expected: replacing the threshold ladder with the "
        "expected-loss rule left the answer/refuse boundary at the same 0.20 "
        "by derivation, but changed when the system asks a clarifying "
        "question, since asking must now earn its friction against the "
        "disagreement it could resolve. Weak but internally consistent "
        "evidence is now refused rather than queried. We regard this as "
        "correct - a clarification cannot improve an estimate the signals "
        "already agree on - but it was not anticipated when the derivation was "
        "undertaken.")
    _body(doc,
        "The work has substantive limitations, which we state rather than leave "
        "to be discovered. CALIBRATION IS NOT FITTED: the Platt and isotonic "
        "transforms are implemented and remain identity maps pending labelled "
        "data, so every confidence value we report is a ranked score and not a "
        "probability, and the split-conformal layer [11] that would supply a "
        "coverage guarantee is likewise implemented and unfitted. This is the "
        "single largest gap between the architecture and the evidence for it. "
        "Relevance judgements are the authors' own, not adjudicated by "
        "qualified practitioners, which is a real constraint on any claim about "
        "legal correctness as opposed to retrieval quality. Evaluation queries "
        "were authored alongside the system, making them a bootstrap rather "
        "than an independent benchmark. The harm ratio rho is not elicited: it "
        "is set to the value implied by the deployed threshold, so (6) makes "
        "the assumption explicit and auditable without making it correct. "
        "Coverage is "
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
    _body(doc,
        "Our measurements argue that the hard part of abstention here is not "
        "estimating confidence better but recognising that confidence is the "
        "wrong quantity. The highest-weighted component of our own confidence "
        "score was anti-correlated with answerability, favouring unanswerable "
        "questions by 0.343; repairing it restored the ordering yet left the "
        "two classes overlapping, and separation was obtained only by asking, "
        "before any evidence was weighed, whether the corpus could hold the "
        "answer at all. That question is answerable deterministically, and in a "
        "domain where a confident wrong answer causes material harm, we would "
        "rather decide it that way than infer it from a score.")
    _body(doc,
        "A second theme runs through the results and, we think, generalises "
        "further. The interventions that improved this system durably were "
        "those encoding something true about the law or the documents - which "
        "instrument governs a dispute, what kind of fact a statute can state, "
        "what the corpus actually contains. The interventions that learned a "
        "mapping from question phrasing to passage produced larger headline "
        "numbers and did not survive a change of question style. That "
        "distinction was only visible because three of our own results were "
        "wrong before they were checked, and the flattering version was the "
        "wrong one every time.")
    _body(doc,
        "We therefore close on the measurement rather than the method. Every "
        "evaluation asset used here is authored by the system's developer or "
        "drawn from a training generator, and the honest consequence is that "
        "we cannot yet prove an end-to-end improvement in the thing users "
        "actually receive: a generated statement of law. Establishing that "
        "requires an independent benchmark frozen before development and "
        "practitioner adjudication of emitted answers. For a system whose "
        "purpose is to tell people what the law says, that is not an extension "
        "of the work. It is the work.")

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
               "Delete any you have not opened. Entries [19] and [21] are "
               "dataset resources whose citation form and licence must be "
               "confirmed.")
    for i, ref in enumerate(REFERENCES, 1):
        p = _para(doc, f"[{i}]\t{ref}", size=8, align="justify", space_after=2)
        p.paragraph_format.left_indent = Inches(0.22)
        p.paragraph_format.first_line_indent = Inches(-0.22)

    doc.save(path)


def _verbatim(doc, text, size=7.5):
    """Monospace block, used for the provenance record."""
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    pf = p.paragraph_format
    pf.space_before = Pt(4)
    pf.space_after = Pt(2)
    pf.line_spacing = 1.0
    pf.left_indent = Inches(0.08)
    run = p.add_run(text)
    run.font.name = "Consolas"
    run.font.size = Pt(size)
    return p


def _figure(doc, filename, caption, number, width_in=3.4):
    """Column-width figure with an IEEE caption. Built by build_figures.py."""
    path = OUT_DIR / "figures" / filename
    if not path.exists():
        raise SystemExit(
            f"missing {path}. Run:  backend/venv/Scripts/python.exe "
            "paper/build_figures.py")
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(6)
    p.paragraph_format.space_after = Pt(2)
    p.add_run().add_picture(str(path), width=Inches(width_in))
    _para(doc, f"Fig. {number}.  {caption}", size=8, align="justify",
          space_after=6)


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


def _table(doc, caption, rows, bold_last_rows=0):
    """IEEE-style small table. rows[0] is the header."""
    _para(doc, caption, size=8, align="center", space_before=6, space_after=3)
    ncol = len(rows[0])
    table = doc.add_table(rows=len(rows), cols=ncol)
    table.style = "Table Grid"
    for i, row in enumerate(rows):
        for j, val in enumerate(row):
            cell = table.cell(i, j)
            cell.text = str(val)
            for para in cell.paragraphs:
                para.paragraph_format.space_after = Pt(0)
                for run in para.runs:
                    run.font.name = "Times New Roman"
                    run.font.size = Pt(8)
                    run.bold = (i == 0) or (i >= len(rows) - bold_last_rows
                                            and bold_last_rows > 0)


def _table_corpus(doc):
    # Counts measured directly from the live index — see paper/README.md for the
    # command. Do NOT hand-edit these; they drift silently otherwise.
    _table(doc, "TABLE III.\tINDEXED CORPUS, BY COLLECTION",
           [("Collection", "Chunks"),
            ("Criminal", "3,304"),
            ("Civil", "4,013"),
            ("Constitutional", "1,736"),
            ("Family", "989"),
            ("Statutory subtotal", "10,042"),
            ("Case law (judgments, 6 courts)", "7,529")])


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
        "RESOLVED: the action cost vector was not merely hand-set, it was "
        "inert - 512 cost vectors over 65 decision points changed no action. "
        "Replaced with an expected-loss rule over an explicit harm matrix; the "
        "threshold is now the harm ratio by derivation. rho remains unelicited.",
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
