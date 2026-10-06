"""The PDF path and BOTH AI engines, through the production code. Synthetic
documents only; the real extractor (in its child process), canonical text
assembly and segmentation; a fake provider; no network.

  * layout fixtures: two columns and adjacent label fields, names across lines
    and sentence edges, a signature row and a table, a party repeated across
    pages, headings, addresses, amounts and deadlines -- rendered to PDF,
    extracted, segmented, labels MAPPED onto the extracted text (never the
    plain-text offsets), masked, reviewed, built into each engine's request;
  * a label that cannot be placed after extraction fails clearly, with counts
    and kinds only;
  * the drafting-question engine sends only its selected, unflagged evidence
    and never changes a scanner status;
  * end to end, for each engine: the lawyer's preview, the worker's wire
    request and the evaluation's request are the same bytes.
"""
from __future__ import annotations

import json

import pytest

from app.services.analyzer import pii_pipeline
from app.services.analyzer import pii_evaluation as ev
from tests._analyzer_support import http  # noqa: F401 -- fixture
from tests.test_analyzer_pii_evaluation import doc

PROD = pii_pipeline.PIPELINE

LAYOUT = doc(
    "TENANCY AGREEMENT\n"
    "Landlord: [[NAME:p1|Nargis Akhtar]]    Tenant: [[NAME:p2|Faisal Mehmood Khan]]\n"
    "CNIC: [[CNIC:c1|35202-1234567-1]]    Phone: [[PHONE:ph1|0300-1234567]]\n"
    "1. The Landlord lets [[ADDRESS:a1|House 12, Street 4, Gulberg, Lahore]] to the Tenant.\n"
    "2. Rent is Rs. 40,000 payable by [[NAME:p2|Faisal Mehmood Khan]] [[DEADLINE:d1|within 7 days]] of each month.\n"
    "3. The keys were received by [[NAME:p2|Faisal\nMehmood Khan]] from [[NAME:p1|Nargis Akhtar]].\n"
    "4. Notices go to [[NAME:p1|Nargis Akhtar]] at the address above.\n"
    "| Party | Name | CNIC |\n"
    "| Landlord | [[NAME:p1|Nargis Akhtar]] | [[CNIC:c1|35202-1234567-1]] |\n"
    "| Tenant | [[NAME:p2|Faisal Mehmood Khan]] | [[CNIC:c2|35202-7654321-2]] |\n"
    "SIGNED\n"
    "[[NAME:p1|Nargis Akhtar]]        [[NAME:p2|Faisal Mehmood Khan]]\n"
    "Witness: [[NAME:p3|Bushra Javed]]\n",
    parties=["p1", "p2"])


def capture(store):
    def send(messages):
        store.append(messages)
        return messages[1]["content"]
    return send


@pytest.fixture(scope="module")
def pdf_doc():
    """The layout fixture on two short pages, through the real extractor."""
    pdf = ev.render_pdf(LAYOUT.text, lines_per_page=7)
    return ev.pdf_document(LAYOUT, pdf=pdf)


def test_labels_are_mapped_onto_the_extracted_text_not_reused(pdf_doc):
    mapped, st = pdf_doc
    assert st.layout == "pdf" and st.rows
    assert len(mapped.spans) == len(LAYOUT.spans)
    for g, h in zip(sorted(LAYOUT.spans, key=lambda s: (s.start, -s.end)), mapped.spans):
        source = " ".join(LAYOUT.text[g.start:g.end].split())
        assert " ".join(mapped.text[h.start:h.end].split()) == source and g.kind == h.kind
    assert any(r["page_spans"] and r["page_spans"][0]["page"] == 2 for r in st.rows)   # a party repeats on page 2


def test_a_label_that_cannot_be_placed_after_extraction_fails_clearly():
    other = ev.render_pdf(LAYOUT.text.replace("Bushra Javed", "B. Javed"))
    with pytest.raises(ev.MappingError) as e:
        ev.pdf_document(LAYOUT, pdf=other)
    assert "NAME" in str(e.value) and "Bushra" not in str(e.value)               # kinds and counts, never text


@pytest.mark.parametrize("engine", ["report", "hypothesis"])
def test_the_layout_pdf_through_each_engine_sends_nothing_labelled(pdf_doc, engine):
    mapped, st = pdf_doc
    sent: list = []
    r = ev.score_document(mapped, capture(sent), mode="review", pipeline=PROD, structure=st, engine=engine)
    assert r["sent"], r["block_reasons"]
    assert sum(s["leak"] for s in r["spans"]) == 0
    body = json.dumps(sent)
    for word in ("Nargis", "Faisal", "Mehmood", "Bushra", "35202", "0300", "Gulberg"):
        assert word not in body, (engine, word)
    if engine == "report":
        assert r["party_consistent"] is True and r["deadlines_preserved"] is True
        assert "Rs. 40,000" in body and "within 7 days" in body


def test_the_hypothesis_engine_sends_only_selected_unflagged_evidence(pdf_doc):
    mapped, st = pdf_doc
    from app.services.analyzer.hypotheses import review
    results = ev._hypothesis_results(mapped, st)
    before = [(x["question_id"], x["status"]) for x in results]
    decisions = ev.simulated_decisions(mapped, structure=st, engine="hypothesis")
    composed = pii_pipeline.compose_hypothesis(mapped.text, st.rows, st.suspect, decisions, results)
    items, _ = review.select(results, st.suspect)
    assert composed.items == items and composed.send_ids == {sid for i in items for sid in i["sentence_ids"]}
    assert composed.send_ids < {r["sentence_id"] for r in st.rows}               # never the whole document
    assert not composed.send_ids & st.suspect                                    # never a flagged sentence
    assert [(x["question_id"], x["status"]) for x in results] == before          # scanner statuses untouched
    assert composed.sendable


# ── end to end: preview == worker == evaluation, for each engine ───────────

PAGES = ["TENANCY AGREEMENT",
         "Landlord: Nargis Akhtar    Tenant: Faisal Mehmood Khan",
         "1. The Landlord lets the flat to the Tenant.",
         "2. Rent is payable as agreed between Faisal Mehmood Khan and Nargis Akhtar.",
         "3. The Tenant shall pay a security of ______ within 7 days.",
         "4. Notices go to Nargis Akhtar at House 12, Street 4, Gulberg, Lahore."]
PEOPLE = {"p1": "Nargis Akhtar", "p2": "Faisal Mehmood Khan"}


def _gold(text):
    spans = []
    for entity, name in PEOPLE.items():
        at = -1
        while (at := text.find(name, at + 1)) != -1:
            spans.append(ev.Span("NAME", entity, at, at + len(name)))
    a = text.find("House 12, Street 4, Gulberg, Lahore")
    spans.append(ev.Span("ADDRESS", "a1", a, a + len("House 12, Street 4, Gulberg, Lahore")))
    return sorted(spans, key=lambda s: (s.start, -s.end))


@pytest.mark.parametrize("engine", ["report", "hypothesis"])
async def test_preview_worker_and_evaluation_send_the_same_request(http, mongo_transactional, monkeypatch, engine):
    from app.core.config import settings
    from app.db.collections import get_analysis_runs_col
    from app.services.analyzer import ai_stage, hypothesis_review_stage as hrs, runner
    from tests._analyzer_support import pdf_with
    from tests.test_analyzer_ai_config import GOOD
    from tests.test_analyzer_pii_confirmation import BASE, preview, raw_provider, submit, view_of
    from tests.test_analyzer_pii_mask import to_ai_report

    for name, value in GOOD.items():
        monkeypatch.setattr(settings, name, value)
    monkeypatch.setattr(settings, "analyzer_pii_review_required", True)
    if engine == "hypothesis":
        monkeypatch.setattr(settings, "analyzer_engine_hypotheses", True)
    await get_analysis_runs_col().delete_many({"is_open": True})
    client, _ = http
    bodies: list = []

    def signals(prompt):
        import re
        from app.services.analyzer.hypotheses import review
        return {"schema_version": review.SCHEMA_VERSION, "prompt_version": review.PROMPT_VERSION,
                "reviews": [{"question_id": q, "signal": "supports", "explanation": "Named in the wording."}
                            for q in re.findall(r"^## item (\w+)$", prompt, re.M)]}

    if engine == "hypothesis":
        monkeypatch.setattr(hrs, "TRANSPORT", raw_provider(bodies, signals))
        rid = await to_ai_report(client, PAGES, expect="queued_hypothesis_scan")
        assert await runner.process_one("w1") == "queued_hypothesis_review"
        assert await runner.process_one("w1") == "done"
    else:
        monkeypatch.setattr(ai_stage, "TRANSPORT", raw_provider(bodies))
        rid = await to_ai_report(client, PAGES)
        assert await runner.process_one("w1") == "done"
    assert bodies == []                                                          # nothing before approval

    # The evaluation reads the SAME PDF through the production extractor.
    text = (await client.get(f"{BASE}/{rid}/text")).json()["text"]
    mapped, st = await ev.pdf_document_async(ev.Doc("e2e", "tenancy", [], list(PEOPLE), text, _gold(text)),
                                             pdf=pdf_with(PAGES))
    assert mapped.text == text                                                   # the app's canonical text, exactly
    evaluated: list = []
    r = ev.score_document(mapped, capture(evaluated), mode="review", pipeline=PROD, structure=st, engine=engine)
    assert r["sent"], r["block_reasons"]
    decisions = ev.simulated_decisions(mapped, structure=st, engine=engine)

    view = await view_of(client, rid)
    p = (await preview(client, rid, view, decisions)).json()
    assert p["request"] == evaluated[0]                                          # preview == evaluation
    assert (await submit(client, rid, view, decisions)).status_code == 201
    assert await runner.process_one("w1") == "done"
    [raw] = bodies
    assert json.loads(raw)["messages"] == p["request"]                           # worker == preview
    wire = raw.decode("utf-8") if isinstance(raw, bytes) else raw
    assert not any(w in wire for w in ("Nargis", "Faisal", "Gulberg"))
    ai_stage.TRANSPORT = None
    hrs.TRANSPORT = None


def _two_column_pdf() -> bytes:
    """A TRUE two-column layout: separate text objects at two x positions on one
    line (not spaces) -- the extractor puts each column on its own line."""
    import io

    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setFont("Helvetica", 10)
    y = 800
    c.drawString(36, y, "TENANCY AGREEMENT")
    for a, b in (("Landlord: Nargis Akhtar", "Tenant: Faisal Mehmood Khan"),
                 ("CNIC: 35202-1234567-1", "CNIC: 35202-7654321-2"), ("Nargis Akhtar", "Faisal Mehmood Khan")):
        y -= 20
        c.drawString(36, y, a)
        c.drawString(300, y, b)
    c.drawString(36, y - 20, "Faisal Mehmood Khan pays Nargis Akhtar Rs. 40,000 within 7 days.")
    c.save()
    return buf.getvalue()


TWO_COLUMN = doc(
    "TENANCY AGREEMENT\nLandlord: [[NAME:p1|Nargis Akhtar]]\nTenant: [[NAME:p2|Faisal Mehmood Khan]]\n"
    "CNIC: [[CNIC:c1|35202-1234567-1]]\nCNIC: [[CNIC:c2|35202-7654321-2]]\n[[NAME:p1|Nargis Akhtar]]\n"
    "[[NAME:p2|Faisal Mehmood Khan]]\n[[NAME:p2|Faisal Mehmood Khan]] pays [[NAME:p1|Nargis Akhtar]] Rs. 40,000 "
    "[[DEADLINE:d1|within 7 days]].", parties=["p1", "p2"])


@pytest.mark.parametrize("engine", ["report", "hypothesis"])
def test_a_true_two_column_pdf_keeps_one_token_per_person(engine):
    mapped, st = ev.pdf_document(TWO_COLUMN, pdf=_two_column_pdf())
    sent: list = []
    r = ev.score_document(mapped, capture(sent), mode="review", pipeline=PROD, structure=st, engine=engine)
    assert r["sent"] and sum(s["leak"] for s in r["spans"]) == 0, r["block_reasons"]
    assert not any(w in json.dumps(sent) for w in ("Nargis", "Faisal", "35202"))
    if engine == "report":
        assert r["party_consistent"] is True and r["person_consistent"] is True and r["deadlines_preserved"] is True


def test_the_production_paths_evaluation_on_a_development_set():
    """identity-dev (DEVELOPMENT) through every production path; the gate is
    computed on the required PDF paths with the unchanged thresholds."""
    ds = ev.load_dataset("identity-dev")
    out = ev.evaluate_production(ds, capture([]))
    assert set(out["paths"]) == {"pdf/report/auto", "pdf/report/manual", "pdf/report/review",
                                 "pdf/hypothesis/review", "text/report/review"}
    assert out["gate"]["required_paths"] == ["pdf/report", "pdf/hypothesis"]
    assert out["pins"]["pipeline"] == PROD and out["pins"]["processing_sha256"]
    assert "never by reusing plain-text offsets" in out["label_mapping"]
    review = out["paths"]["pdf/report/review"]
    print("UNMAPPED", out["unmapped"], "GATE", out["gate"]["status"], out["gate"]["checks"],
          {k: (v["documents"], v["sent"], v["leaks"], v["party_consistency"], v["documents_outside_path"])
           for k, v in out["paths"].items()})
    assert review["leaks"] == 0


def test_an_urdu_script_document_is_scored_on_text_and_blocked_never_unmapped():
    urdu = doc("Landlord: [[NAME:p1|Nargis Akhtar]]\nKiraya [[NAME:p1|نرگس اختر]] ko diya jaye ga "
               "[[DEADLINE:d1|within 7 days]].", parties=["p1"])
    plain = doc("Landlord: [[NAME:p1|Nargis Akhtar]]\nRent is paid to [[NAME:p1|Nargis Akhtar]] "
                "[[DEADLINE:d1|within 7 days]].", parties=["p1"])
    urdu.id, plain.id = "u1", "t1"
    ds = ev.Dataset("adhoc", [urdu, plain], "x")
    out = ev.evaluate_production(ds, capture([]))
    assert out["text_fallback"] == [{"id": "u1", "reason": "unsupported_script"}] and out["unmapped"] == []
    review = out["paths"]["pdf/report/review"]
    assert review["documents"] == 2 and review["sent"] == 1                       # counted, and blocked by policy
    assert review["blocked_by_reason"] == {"unsupported_script": 1} and review["leaks"] == 0
