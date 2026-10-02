"""Document Analyzer, P3.0 step 2: definitions and the cross-reference graph.

Definitions, uses of defined terms, possible undefined terms and references
to clauses and schedules -- found by rules, anchored at offsets and stable
sentence / clause / block ids, never decided by a model. Statutory citations
are authority references, not edges into the document. Synthetic text only.
"""
from __future__ import annotations

import pytest

from app.ai.docx_structure import extract_docx_structured
from app.services.analyzer import doc_graph as g
from app.services.analyzer import segmentation as seg
from tests._analyzer_support import http, pdf_with, upload  # noqa: F401 -- fixture
from tests._docx_fixtures import abstract, build, lvl, num, p, tbl, tc, tr

AGREEMENT = """SERVICES AGREEMENT
This Agreement is made between Alpha Traders (Pvt) Ltd (the "Company") and Mr. Bilal Khan (hereinafter referred to as the "Consultant").
1. Definitions
1.1 "Services" means the services described in Schedule A.
1.2 "Fee" has the meaning given in Clause 4.
1.3 Business Day means a day on which banks in Lahore are open.
1.4 “Confidential Information” shall mean all information disclosed under this Agreement.
2. Scope
2.1 The Consultant shall perform the Services for the Company in accordance with Clauses 3 and 4.
2.2 Subject to sub-clause (b) of Clause 3, the Consultant shall comply with section 17 of the Registration Act, 1908.
3. Obligations
(a) The Company shall pay the Fee on each Business Day.
(b) The Consultant shall keep the Confidential Information and other information secret.
4. Fee
4.1 The Fee is Rs. 100,000 as set out in Clause 9 and Annexure B, see Clauses 4.1 to 4.3.
SCHEDULE A
Description of the services."""


def graph(text, blocks=None, pages=None):
    clauses, sentences = seg.segment(text, pages or [], blocks)
    rows, summary = g.build(text, clauses, sentences, blocks, pages or [])
    return rows, summary, clauses, sentences


def of(rows, kind):
    return [r for r in rows if r["type"] == kind]


def definitions(text, **kw):
    return {r["term"]: r for r in of(graph(text, **kw)[0], g.ROW_DEFINITION)}


def refs(text, **kw):
    return of(graph(text, **kw)[0], g.ROW_REFERENCE)


def ref(text, written):
    found = [r for r in refs(text) if r["written"] == written]
    assert len(found) == 1, [r["written"] for r in refs(text)]
    return found[0]


# ── definitions ──────────────────────────────────────────────────────────────

def test_definitions_of_every_form_are_found_with_their_kind_and_offsets():
    rows, _, _, sentences = graph(AGREEMENT)
    found = {r["term"]: r for r in of(rows, g.ROW_DEFINITION)}
    assert {t: (r["kind"], r["form"]) for t, r in found.items()} == {
        "Company": (g.DEF_DESIGNATION, g.FORM_PARENTHETICAL),
        "Consultant": (g.DEF_DESIGNATION, g.FORM_PARENTHETICAL),
        "Services": (g.DEF_MEANS, g.FORM_INLINE),
        "Fee": (g.DEF_CROSS_REFERENCE, g.FORM_INLINE),
        "Business Day": (g.DEF_MEANS, g.FORM_INLINE),
        "Confidential Information": (g.DEF_MEANS, g.FORM_INLINE),
    }
    by_id = {s.sentence_id: s for s in sentences}
    for term, r in found.items():
        assert AGREEMENT[r["start"]:r["end"]] == term
        assert r["normalized"] == term.lower() and r["status"] == g.DEFINED
        unit = by_id[r["sentence_id"]]
        assert unit.start <= r["start"] < r["end"] <= unit.end and unit.clause_id == r["clause_id"]
        assert r["scope"] == {"kind": "document", "clause_id": None}


def test_a_cross_referenced_definition_points_at_its_reference_edge():
    rows = graph(AGREEMENT)[0]
    fee = next(r for r in rows if r["type"] == g.ROW_DEFINITION and r["term"] == "Fee")
    [edge_id] = fee["refers_to"]
    edge = next(r for r in rows if r.get("edge_id") == edge_id)
    assert (edge["written"], edge["status"]) == ("Clause 4", g.RESOLVED)
    assert AGREEMENT[slice(*_clause_span(rows, edge))].startswith("4. Fee")


def _clause_span(rows, edge):
    clauses, _ = seg.segment(AGREEMENT, [])
    c = next(c for c in clauses if c.clause_id == edge["targets"][0]["clause_id"])
    return c.start, c.end


@pytest.mark.parametrize("sentence, term, kind", [
    ('"Premises" includes the shop and its fixtures.', "Premises", g.DEF_INCLUDES),
    ("‘Rent’ shall mean the monthly amount.", "Rent", g.DEF_MEANS),
    ('"Deposit" shall have the meaning ascribed to it in Clause 5.', "Deposit", g.DEF_CROSS_REFERENCE),
    ('"Term" is defined in the preamble.', "Term", g.DEF_CROSS_REFERENCE),
    ("Working Hours means 9 am to 5 pm.", "Working Hours", g.DEF_MEANS),
    ("The Tenant includes his heirs and assigns.", "Tenant", g.DEF_INCLUDES),
    ('Ahmed Raza (hereinafter called the "Landlord") lets the shop.', "Landlord", g.DEF_DESIGNATION),
    ("Ahmed Raza (hereinafter referred to as the LANDLORD which expression includes his heirs) lets it.",
     "LANDLORD", g.DEF_DESIGNATION),
    ('The parties (each a "Party" and together the "Parties") agree.', "Party", g.DEF_DESIGNATION),
])
def test_definition_forms(sentence, term, kind):
    found = definitions(sentence)
    assert found[term]["kind"] == kind


@pytest.mark.parametrize("sentence", [
    "This Agreement includes the Schedules.",          # "This" opens a sentence, it names nothing
    "It means that the rent is due.",
    'The tenant said "yes" and left.',                 # a quote that defines nothing
    "Rent (payable monthly) is due on the first.",     # a parenthetical that designates nothing
    "the rent includes utilities.",                    # lower-case: not a term
])
def test_text_that_defines_nothing(sentence):
    assert definitions(sentence) == {}


def test_both_quoted_designations_of_a_parenthetical_are_definitions():
    found = definitions('The parties (each a "Party" and together the "Parties") agree.')
    assert set(found) == {"Party", "Parties"}


def test_a_definitions_list_inside_a_definitions_clause():
    text = ("1. Definitions\n(a) Landlord: the owner of the shop.\n(b) “Tenant”: the person renting it.\n"
            "2. Rent\nNote: rent is due monthly.")
    found = definitions(text)
    assert {t: r["form"] for t, r in found.items()} == {"Landlord": g.FORM_LIST, "Tenant": g.FORM_LIST}


def test_a_definition_in_this_clause_is_scoped_to_its_clause():
    text = ('1. Payment\nIn this Clause, "Due Date" means the fifth day of each month. '
            "Rent is paid by the Due Date.\n2. Late payment\nLate rent after the Due Date attracts a fee.")
    rows = graph(text)[0]
    [d] = of(rows, g.ROW_DEFINITION)
    assert d["scope"]["kind"] == "clause" and d["scope"]["clause_id"] == d["clause_id"]
    uses = of(rows, g.ROW_TERM_USE)
    assert [u["status"] for u in uses] == [g.RESOLVED, g.OUT_OF_SCOPE]


# ── duplicates are reported, never resolved by choice ───────────────────────

def test_two_definitions_of_one_term_are_both_ambiguous_and_uses_point_at_both():
    text = ('1. "Rent" means Rs. 50,000 a month.\n2. "Rent" means Rs. 60,000 a month.\n'
            "3. The Rent is paid in advance.")
    rows = graph(text)[0]
    defs = of(rows, g.ROW_DEFINITION)
    assert [d["status"] for d in defs] == [g.AMBIGUOUS_DEFINITION] * 2
    assert defs[0]["duplicates"] == [defs[1]["definition_id"]]
    [use] = of(rows, g.ROW_TERM_USE)
    assert use["status"] == g.AMBIGUOUS
    assert {t["definition_id"] for t in use["targets"]} == {d["definition_id"] for d in defs}


def test_a_pointer_or_an_extension_is_not_a_second_definition():
    text = ('This Agreement is made with Bilal Khan (the "Supplier").\n'
            '1. "Supplier" has the meaning given in the preamble.\n'
            '2. "Goods" means the items in the order. "Goods" includes their packaging.\n'
            "3. The Supplier delivers the Goods.")
    rows = graph(text)[0]
    assert {d["status"] for d in of(rows, g.ROW_DEFINITION)} == {g.DEFINED}
    uses = {u["term"]: u for u in of(rows, g.ROW_TERM_USE)}
    assert uses["Supplier"]["status"] == g.RESOLVED
    assert [t["definition_id"] for t in uses["Supplier"]["targets"]] == ["d0"]   # the designation
    assert uses["Goods"]["status"] == g.RESOLVED and len(uses["Goods"]["targets"]) == 2


# ── uses of defined terms ────────────────────────────────────────────────────

def test_uses_link_to_their_definitions_by_stable_ids():
    rows = graph(AGREEMENT)[0]
    defs = {d["definition_id"]: d for d in of(rows, g.ROW_DEFINITION)}
    uses = of(rows, g.ROW_TERM_USE)
    assert [AGREEMENT[u["start"]:u["end"]] for u in uses] == [
        "Consultant", "Services", "Company", "Consultant", "Company", "Fee", "Business Day",
        "Consultant", "Confidential Information", "Fee", "Fee"]   # "4. Fee" and "4.1 The Fee"
    for u in uses:
        [t] = u["targets"]
        assert u["status"] == g.RESOLVED and defs[t["definition_id"]]["normalized"] == u["normalized"]
        assert t["sentence_id"] == defs[t["definition_id"]]["sentence_id"]


def test_lower_case_words_headings_and_the_definition_itself_are_not_uses():
    text = ('RENT\n1. "Rent" means Rs. 5,000.\n2. The rent is low. The Rent is paid monthly.')
    uses = of(graph(text)[0], g.ROW_TERM_USE)
    assert [text[u["start"]:u["end"]] for u in uses] == ["Rent"]
    assert uses[0]["start"] == text.rindex("Rent")


def test_the_longest_defined_term_wins_and_capitals_follow_the_definition():
    text = ('Bilal Khan (the "LANDLORD") lets the shop.\n'
            '1. "Information" means facts. "Confidential Information" means secret facts.\n'
            "2. The Landlord's Confidential Information stays secret.")
    uses = of(graph(text)[0], g.ROW_TERM_USE)
    assert [(text[u["start"]:u["end"]], u["normalized"]) for u in uses] == [
        ("Landlord", "landlord"), ("Confidential Information", "confidential information")]


# ── possible undefined terms ─────────────────────────────────────────────────

def test_a_repeated_capitalised_phrase_nothing_defines_is_a_possible_undefined_term():
    text = ("1. The Tenant shall keep the Project Plan updated.\n"
            "2. The landlord reviews the Project Plan monthly.")
    [u] = of(graph(text)[0], g.ROW_UNDEFINED)
    assert (u["term"], u["count"], u["label"]) == ("Project Plan", 2, "Possible undefined term")
    assert [text[o["start"]:o["end"]] for o in u["occurrences"]] == ["Project Plan"] * 2
    assert all(o["sentence_id"] and o["clause_id"] for o in u["occurrences"])


@pytest.mark.parametrize("phrase", [
    "Mr. Ahmed Raza",                    # a person
    "Alpha Traders Ltd",                 # a company
    "Contract Act",                      # a statute
    "High Court",                        # a court
    "CNIC",                              # an acronym
    "January",                           # a date
    "Pak Rupees",                        # a currency
    "Lahore",                            # a place
    "Clause",                            # a document noun
])
def test_names_places_statutes_dates_and_acronyms_are_not_undefined_terms(phrase):
    text = f"1. The tenant informed {phrase} today.\n2. The landlord also informed {phrase} later."
    assert of(graph(text)[0], g.ROW_UNDEFINED) == []


def test_sentence_openers_single_uses_headings_and_defined_terms_are_not_undefined_terms():
    text = ('TERMINATION\n1. Termination is by notice. Termination ends the lease.\n'
            '2. The Tenant pays the Water Charges once.\n'
            '3. "Deposit" means Rs. 10,000. The tenant pays the Deposit. The landlord holds the Deposit.\n'
            "4. The tenant reads the TERMINATION terms. The tenant reads the Termination terms.")
    terms = {u["term"] for u in of(graph(text)[0], g.ROW_UNDEFINED)}
    assert terms == set()


# ── references to clauses ────────────────────────────────────────────────────

def test_clause_references_resolve_to_stable_clause_ids():
    rows, _, clauses, _ = graph(AGREEMENT)
    by_id = {c.clause_id: c for c in clauses}
    found = {(r["written"], r["label"]): r for r in of(rows, g.ROW_REFERENCE)}
    three, four = found[("3", "3")], found[("4", "4")]
    assert (three["group_start"], three["group_end"]) == (four["group_start"], four["group_end"])
    assert AGREEMENT[three["group_start"]:three["group_end"]] == "Clauses 3 and 4"
    assert by_id[three["targets"][0]["clause_id"]].number == "3."
    assert by_id[four["targets"][0]["clause_id"]].number == "4."
    sub = found[("sub-clause (b) of Clause 3", "3(b)")]
    assert sub["status"] == g.RESOLVED and by_id[sub["targets"][0]["clause_id"]].number == "(b)"


def test_a_broken_reference_is_unresolved_and_a_range_resolves_label_by_label():
    found = {(r["written"], str(r["label"])): r for r in refs(AGREEMENT)}
    assert found[("Clause 9", "9")]["status"] == g.UNRESOLVED
    assert found[("Clause 9", "9")]["reason"] == "label_not_found"
    assert found[("Clause 9", "9")]["targets"] == []
    assert [(found[("Clauses 4.1 to 4.3", lab)]["status"]) for lab in ("4.1", "4.2", "4.3")] == [
        g.RESOLVED, g.UNRESOLVED, g.UNRESOLVED]
    assert found[("Clauses 4.1 to 4.3", "4.1")]["range"] == "4.1 to 4.3"


@pytest.mark.parametrize("written, label, status, precision", [
    ("Clause 2.1", "2.1", g.RESOLVED, "exact"),
    ("clause 2(a)", "2(a)", g.RESOLVED, "exact"),
    ("Clause 2.1(c)", "2.1(c)", g.RESOLVED, "parent_clause"),   # (c) is inline, not a clause
    ("Clause 7", "7", g.UNRESOLVED, "exact"),
])
def test_numbering_variants(written, label, status, precision):
    text = ("1. Rent\nRent is due monthly.\n2. Use\n(a) Shop use only.\n2.1 No subletting. "
            f"See {written} for details.")
    r = ref(text, written)
    assert (r["label"], r["status"], r.get("precision")) == (label, status, precision)


def test_a_bare_sub_label_resolves_within_its_own_clause_first():
    text = ("1. Rent\n(a) Rent is due monthly.\n2. Use\n(a) Shop use only.\n"
            "(b) Subject to paragraph (a) above, no noise.")
    r = ref_by_label(text, "(a)")
    clauses, _ = seg.segment(text, [])
    target = next(c for c in clauses if c.clause_id == r["targets"][0]["clause_id"])
    assert r["status"] == g.RESOLVED and text[target.start:target.end] == "(a) Shop use only."


def ref_by_label(text, label):
    [r] = [r for r in refs(text) if r["label"] == label]
    return r


def test_a_label_two_clauses_share_is_ambiguous_and_no_target_is_chosen():
    text = ("1. Rent\nRent is due monthly.\n2. Use\nShop use only.\nANNEX\n1. Inventory\nTwo chairs.\n"
            "3. Notices\nNotices follow Clause 1.")
    r = ref(text, "Clause 1")
    assert r["status"] == g.AMBIGUOUS and r["reason"] == "label_used_more_than_once"
    assert len(r["targets"]) == 2


def test_the_label_word_and_this_narrow_a_shared_label_by_text_alone():
    text = ("ARTICLE 5\nWarranties apply.\nSCHEDULE A\n5. Sample row.\n"
            "ARTICLE 6\nBreach of Article 5 ends the licence.")
    assert ref(text, "Article 5")["status"] == g.RESOLVED
    assert ref(text, "Article 5")["reason"] == "matched_label_word"
    text = ("1. Rent\nRent is due.\n2. Use\n2.1 This Clause 2 survives.\nANNEX\n2. Row two.")
    r = ref(text, "Clause 2")
    assert (r["status"], r["reason"]) == (g.RESOLVED, "this_enclosing_clause")


def test_a_document_without_structure_resolves_no_clause_reference():
    text = "plain words. See Clause 4 for rent.\n\nmore plain words."
    rows, summary, _, _ = graph(text)
    [r] = of(rows, g.ROW_REFERENCE)
    assert (r["status"], r["reason"]) == (g.UNRESOLVED, "no_clause_structure_detected")
    assert summary["limitations"] == ["no_clause_structure_detected"]


@pytest.mark.parametrize("sentence", [
    "Rent rises by 5 percent under Clause 2 and 30 days notice applies.",   # "30 days" is no label
])
def test_quantities_after_a_conjunction_are_not_labels(sentence):
    text = "1. Rent\nRent is due.\n2. Increase\n" + sentence
    assert [r["label"] for r in refs(text)] == ["2"]


@pytest.mark.parametrize("text", [
    "ARTICLES OF ASSOCIATION\n1. The company is private.",
    "1. Delivery\nThe supplier sends the schedule(s) of delivery.",
    "1. Payment\nThe payment schedule is agreed separately.",
])
def test_words_that_only_look_like_references(text):
    assert refs(text) == []


def test_the_letters_of_and_are_never_labels():
    text = "1. Fees\n4. Price\n(c) one.\n(d) two.\n5. Cap\nCALCULATED UNDER SECTIONS 4(c) AND 4(d) ONLY."
    assert sorted(r["label"] for r in refs(text)) == ["4(c)", "4(d)"]


# ── schedules and annexures ──────────────────────────────────────────────────

def test_schedules_resolve_to_their_heading_and_missing_ones_are_reported():
    found = {r["written"]: r for r in refs(AGREEMENT)}
    a = found["Schedule A"]
    assert a["status"] == g.RESOLVED and AGREEMENT[a["targets"][0]["start"]:].startswith("SCHEDULE A")
    b = found["Annexure B"]
    assert (b["status"], b["reason"], b["targets"]) == (g.UNRESOLVED, "schedule_not_located", [])


@pytest.mark.parametrize("written, status", [
    ("Annexure-A", g.RESOLVED), ("Annex A", g.RESOLVED), ("Schedule B", g.UNRESOLVED),
    ("Exhibit 1", g.UNRESOLVED)])
def test_schedule_label_forms(written, status):
    text = f"1. Inventory\nThe items are listed in {written} hereto.\nANNEXURE – A\nTwo chairs."
    assert ref(text, written)["status"] == status


def test_the_unlabelled_schedule_resolves_only_when_there_is_one():
    one = "1. Rent\nRent is in the Schedule.\nTHE SCHEDULE\nRs. 5,000."
    assert ref(one, "Schedule")["status"] == g.RESOLVED
    none = "1. Rent\nRent is in the Schedule."
    assert ref(none, "Schedule")["status"] == g.UNRESOLVED
    two = "1. Rent\nRent is in the Schedule.\nSCHEDULE A\nRs. 5,000.\nSCHEDULE B\nRs. 6,000."
    r = ref(two, "Schedule")
    assert r["status"] == g.AMBIGUOUS and len(r["targets"]) == 2


# ── authority citations are not edges into the document ─────────────────────

@pytest.mark.parametrize("sentence, written", [
    ("Registration follows section 17 of the Registration Act, 1908.", "section 17"),
    ("The cheque falls under Section 489-F PPC.", "Section 489"),
    ("Relief lies under Article 199 of the Constitution.", "Article 199"),
    ("FILED UNDER SECTION 22 OF DIVORCE ACT 1869.", "SECTION 22"),
    ("Notice is given under section 106 of the Transfer of Property Act.", "section 106"),
])
def test_statutory_citations_are_external_references(sentence, written):
    text = "1. Rent\nRent is due.\n17. Notices\n" + sentence
    found = [r for r in refs(text) if r["written"].startswith(written)]
    assert found and all(r["status"] == g.EXTERNAL and r["targets"] == [] for r in found)


def test_references_into_another_document_or_a_schedule_are_not_guessed():
    text = ("1. Rent\nRent is due.\n2. Notices\nHere, Clause 1 of the Lease Agreement dated 1 May applies. "
            "Clause 2 of Schedule A applies. Clause 1 of this Agreement applies.\nSCHEDULE A\n2. Row.")
    found = [(r["written"], r["status"], r["reason"]) for r in refs(text)]
    assert ("Clause 1", g.UNSUPPORTED, "document_not_identified") in found
    assert ("Clause 2", g.UNSUPPORTED, "reference_into_schedule") in found
    assert ("Clause 1", g.RESOLVED, None) in found


def test_a_clause_heading_is_not_a_reference_to_itself():
    text = "Clause 1 Rent\nRent is due.\nClause 2 Use\nShop only, see Clause 1."
    assert [r["written"] for r in refs(text)] == ["Clause 1"]


# ── DOCX: Word numbering, headings and definition tables ─────────────────────

STYLES = """<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style>
<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/>
  <w:pPr><w:outlineLvl w:val="0"/></w:pPr></w:style>"""


def docx(tmp_path, body, numbering=""):
    r = extract_docx_structured(build(tmp_path / "d.docx", body, numbering=numbering, styles=STYLES))
    return r.text, r.blocks


def test_a_definitions_table_is_read_and_anchored_at_its_cells(tmp_path):
    text, blocks = docx(tmp_path, "".join([
        p("Definitions", style="Heading1"),
        tbl(tr(tc("Term"), tc("Meaning")),
            tr(tc("Premises"), tc("The shop at the address in the Schedule.")),
            tr(tc("“Monthly Rent”"), tc("Rs. 85,000 payable in advance."))),
        p("Use", style="Heading1"),
        p("The tenant uses the Premises and pays the Monthly Rent.")]))
    rows = graph(text, blocks=blocks)[0]
    defs = {d["term"]: d for d in of(rows, g.ROW_DEFINITION)}
    assert set(defs) == {"Premises", "Monthly Rent"}
    block_ids = {b["block_id"] for b in blocks}
    for d in defs.values():
        assert d["form"] == g.FORM_TABLE and d["block_id"] in block_ids
        assert text[d["start"]:d["end"]] == d["term"] and d["meaning_sentence_ids"]
    uses = of(rows, g.ROW_TERM_USE)
    assert [u["term"] for u in uses] == ["Premises", "Monthly Rent"]
    assert all(u["block_id"] in block_ids for u in uses)


def test_a_table_without_definitions_defines_nothing(tmp_path):
    text, blocks = docx(tmp_path, tbl(tr(tc("Item"), tc("Qty")), tr(tc("Chairs"), tc("Two"))))
    assert of(graph(text, blocks=blocks)[0], g.ROW_DEFINITION) == []


def test_references_resolve_to_word_numbered_clauses_with_their_blocks(tmp_path):
    numbering = abstract("1", lvl(0, "decimal", "%1."), lvl(1, "lowerLetter", "%2)")) + num("1", "1")
    text, blocks = docx(tmp_path, "".join([
        p("Rent", num=("1", 0)), p("Rent is due monthly.", num=("1", 1)),
        p("Termination", num=("1", 0)), p("Late rent under Clause 1 ends the lease.", num=("1", 1))]),
        numbering)
    [r] = refs(text, blocks=blocks)
    assert r["status"] == g.RESOLVED and r["targets"][0]["block_id"]
    assert r["block_id"] and r["block_id"] != r["targets"][0]["block_id"]


# ── stable identity ──────────────────────────────────────────────────────────

def test_the_graph_is_deterministic_and_every_anchor_is_sound():
    pages = [{"page": 1, "start": 0, "end": 400, "coverage": "text_found", "origin": "native"},
             {"page": 2, "start": 401, "end": len(AGREEMENT), "coverage": "text_found", "origin": "native"}]
    first = graph(AGREEMENT, pages=pages)
    second = graph(AGREEMENT, pages=pages)
    assert first[0] == second[0] and first[1] == second[1]
    rows, _, clauses, sentences = first
    by_s = {s.sentence_id: s for s in sentences}
    assert [r["ordinal"] for r in rows] == list(range(len(rows)))
    ids = [r.get("definition_id") or r.get("edge_id") or r.get("undefined_id") for r in rows]
    assert len(ids) == len(set(ids)) and None not in ids
    for r in rows:
        for a in r.get("occurrences") or [r]:
            s = by_s[a["sentence_id"]]
            assert s.start <= a["start"] < a["end"] <= s.end and s.clause_id == a["clause_id"]
            assert all(a["start"] <= span["start"] < span["end"] <= a["end"] for span in a["page_spans"])
            assert a["page_spans"]


def test_the_summary_counts_what_was_found():
    _, summary, _, _ = graph(AGREEMENT)
    assert summary == {"definitions": 6, "ambiguous_definitions": 0, "term_uses": 11,
                       "references": {g.EXTERNAL: 1, g.RESOLVED: 6, g.UNRESOLVED: 4},
                       "schedules_located": 1, "possible_undefined_terms": 0, "limitations": []}


# ── the stage: published, swept and purged with the segmentation ────────────

GRAPH_PAGES = ['SUPPLY AGREEMENT made at Lahore between Bilal Khan (the "Supplier") and Ahmed Raza.',
               '1. "Goods" means the chairs. 2. The Supplier delivers the Goods under Clause 9.']


@pytest.fixture
async def segmented(http, mongo_transactional):
    from app.db.collections import get_analysis_runs_col
    from app.services.analyzer import runner
    client, actor = http
    await get_analysis_runs_col().delete_many({"is_open": True})
    created = (await upload(client, content=pdf_with(GRAPH_PAGES))).json()
    assert await runner.process_one("w1") == "queued_segmentation"
    return client, actor, created


async def test_the_stage_publishes_the_graph_with_the_segmentation(segmented):
    from app.db.collections import get_analysis_doc_graph_col, get_analysis_runs_col
    from app.services.analyzer import runner
    client, _, created = segmented
    assert await runner.process_one("w1") == "needs_document_confirmation"
    run = await get_analysis_runs_col().find_one({"_id": created["run_id"]})
    fence = run["published"]["segment"]
    rows = [r async for r in get_analysis_doc_graph_col().find(
        {"run_id": run["_id"], "stage": "segment", "fence": fence}).sort("ordinal", 1)]
    assert rows and all(r["text_version_id"] == run["text_version_id"]
                        and r["source_id"] == created["source_id"] for r in rows)
    assert run["doc_graph"]["definitions"] == 2
    assert run["doc_graph"]["references"] == {g.UNRESOLVED: 1}

    view = (await client.get(f"/documents/analyses/runs/{created['run_id']}/graph")).json()
    text = (await client.get(f"/documents/analyses/runs/{created['run_id']}/text")).json()["text"]
    assert view["summary"] == run["doc_graph"]
    assert [r["ordinal"] for r in view["rows"]] == list(range(len(rows)))
    assert all(k not in r for r in view["rows"] for k in ("_id", "run_id", "fence", "source_id"))
    sentence_ids = {s["sentence_id"] for s in
                    (await client.get(f"/documents/analyses/runs/{created['run_id']}/text")).json()["sentences"]}
    goods = next(r for r in view["rows"] if r["type"] == g.ROW_DEFINITION and r["term"] == "Goods")
    assert text[goods["start"]:goods["end"]] == "Goods" and goods["sentence_id"] in sentence_ids
    [broken] = [r for r in view["rows"] if r["type"] == g.ROW_REFERENCE]
    assert text[broken["start"]:broken["end"]] == "Clause 9" and broken["page_spans"][0]["page"] == 2


async def test_another_owner_cannot_read_the_graph(segmented, monkeypatch):
    from app.services.analyzer import confirmation, runner
    from app.services.analyzer.errors import AnalyzerNotFound
    _, _, created = segmented
    await runner.process_one("w1")
    with pytest.raises(AnalyzerNotFound):
        await confirmation.get_graph(owner_id="someone-else", run_id=created["run_id"])


async def test_a_stolen_segmentation_leaves_its_graph_unpublished_and_swept(segmented, monkeypatch):
    from datetime import datetime, timedelta, timezone

    from app.db.collections import get_analysis_doc_graph_col, get_analysis_runs_col
    from app.services.analyzer import outputs, runner, worker
    _, _, created = segmented
    real_commit = worker.commit_stage

    async def commit_after_theft(lease, **kwargs):
        await get_analysis_runs_col().update_one(
            {"_id": created["run_id"]},
            {"$set": {"lease_expires_at": datetime.now(timezone.utc) - timedelta(seconds=1)}})
        await worker.reclaim("thief")
        return await real_commit(lease, **kwargs)

    monkeypatch.setattr(worker, "commit_stage", commit_after_theft)
    assert await runner.process_one("w1") == "lost"
    run = await get_analysis_runs_col().find_one({"_id": created["run_id"]})
    assert "segment" not in run.get("published", {}) and "doc_graph" not in run
    graph_rows = get_analysis_doc_graph_col()
    assert await graph_rows.count_documents({"run_id": created["run_id"]}) > 0
    await graph_rows.update_many({"run_id": created["run_id"]},
                                 {"$set": {"created_at": datetime.now(timezone.utc) - timedelta(hours=2)}})
    assert await outputs.sweep_unpublished_run_outputs() > 0
    assert await graph_rows.count_documents({"run_id": created["run_id"]}) == 0


async def test_the_purge_removes_the_graph(segmented):
    from app.db.collections import get_analysis_doc_graph_col
    from app.services.analyzer import deletion, runner
    _, actor, created = segmented
    await runner.process_one("w1")
    assert await get_analysis_doc_graph_col().count_documents({"source_id": created["source_id"]}) > 0
    await deletion.delete_analysis(owner_id=actor["_id"], source_id=created["source_id"])
    assert await deletion.purge_source(created["source_id"]) == "done"
    assert await get_analysis_doc_graph_col().count_documents({"source_id": created["source_id"]}) == 0
