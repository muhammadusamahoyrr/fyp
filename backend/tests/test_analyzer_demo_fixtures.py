"""The three synthetic demo PDFs (scripts/analyzer_demo_fixtures.py) show what
the runbook says they show, through the real pipeline with the simulated provider: the local
checks (two deliberately "not located", the legal pack awaiting approval),
names and identity numbers masked, the scanner-missed details the lawyer
marks, the alias the lawyer links, and an amount and a deadline that reach
the (simulated) provider exactly as written."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

from tests._analyzer_support import http, upload  # noqa: F401 -- fixture

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import analyzer_demo_fixtures as F  # noqa: E402

BASE = "/documents/analyses/runs"
PACK = {"tenancy": "tenancy_punjab", "nda": "nda", "employment": "employment"}


def test_the_pdfs_are_reproducible_and_marked_synthetic():
    from pypdf import PdfReader
    import io
    for spec in F.FIXTURES.values():
        data = F.pdf_bytes(spec)
        assert data == F.pdf_bytes(spec)                                      # byte-identical every time
        text = PdfReader(io.BytesIO(data)).pages[0].extract_text()
        assert text.count("SYNTHETIC DEMONSTRATION DOCUMENT") == 2 and "99" in spec["identifier"][:2]


def _span(text, needle):
    """Where `needle` is in the extracted text (a PDF line may wrap inside it)."""
    m = re.search(r"\s+".join(map(re.escape, needle.split())), text)
    return m.start(), m.end()


@pytest.mark.parametrize("name", list(F.FIXTURES))
async def test_each_fixture_walks_the_demo_flow(http, mongo_transactional, monkeypatch, name):
    from app.core.config import settings
    from app.db.collections import get_analysis_runs_col
    from app.services.analyzer import runner
    from tests.test_analyzer_pii_confirmation import preview, submit, view_of

    for key, value in {"analyzer_ai": True, "analyzer_ai_provider": "simulated", "analyzer_ai_synthetic_only": True,
                       "analyzer_pii_review_required": True,
                       "mongodb_url": "mongodb://127.0.0.1:27018/?replicaSet=rs0"}.items():
        monkeypatch.setattr(settings, key, value)
    spec = F.FIXTURES[name]
    await get_analysis_runs_col().delete_many({"is_open": True})
    client, _ = http
    rid = (await upload(client, content=F.pdf_bytes(spec), name=name)).json()["run_id"]
    assert await runner.process_one("w1") == "queued_segmentation"
    assert await runner.process_one("w1") == "needs_document_confirmation"
    run = (await client.get(f"{BASE}/{rid}")).json()
    assert run["document_review"]["document_type"]["value"] == spec["document_type"]     # detected
    await client.post(f"{BASE}/{rid}/document", json={"expected_state_version": run["state_version"],
                      "document_type": spec["document_type"], "jurisdiction": "punjab"})
    assert await runner.process_one("w1") == "needs_terms_confirmation"
    run = (await client.get(f"{BASE}/{rid}")).json()
    await client.post(f"{BASE}/{rid}/terms", json={"expected_state_version": run["state_version"],
                      "terms": {k: {"value": v, "sentence_ids": []} for k, v in spec["terms"].items()}})
    assert await runner.process_one("w1") == "queued_ai_report"
    assert await runner.process_one("w1") == "done"                        # waits for the lawyer

    report = (await client.get(f"{BASE}/{rid}/report")).json()
    general = {c["check_id"]: c["check_result"] for c in report["legal_checks"] if c["pack_id"] == "general"}
    assert general["disputes"] == general["governing_law"] == "not_located"
    assert general["parties_named"] == general["payment_terms"] == "present"
    packs = {p["pack_id"]: p["status"] for p in report["packs"]}
    assert packs[PACK[spec["document_type"]]] == "awaiting_approval"      # never run unapproved
    assert report["pii_evaluation"]["authorizes_real_documents"] is False

    text = (await client.get(f"{BASE}/{rid}/text")).json()["text"]
    view = await view_of(client, rid)
    decisions = [{"start": c["start"], "end": c["end"], "decision": "personal_name"} for c in view["candidates"]]
    flagged = {(d["start"], d["end"]) for d in decisions}
    p = (await preview(client, rid, view, decisions)).json()
    missed = [n for n in spec["names"] if n in p["request"][-1]["content"]] + [spec["missed"]]
    for needle in missed:                                                  # the lawyer marks what was missed
        s, e = _span(text, needle)
        if (s, e) not in flagged:
            decisions.append({"start": s, "end": e, "decision": "personal_name"})
    alias, target = spec["alias"]
    ts, te = _span(text, target)
    if (ts, te) not in flagged and target not in missed:
        decisions.append({"start": ts, "end": te, "decision": "personal_name"})
    s, e = _span(text, alias)
    decisions.append({"start": s, "end": e, "decision": "same_person", "target_start": ts, "target_end": te})

    p = (await preview(client, rid, view, decisions)).json()
    assert p["ready"], p
    body = p["request"][-1]["content"]
    for hidden in spec["names"] + [spec["identifier"], spec["missed"], alias]:
        assert hidden not in body, hidden
    for kept in spec["kept"]:
        assert kept in body, kept                                          # amount and deadline survive
    group = next(g for g in p["people_groups"] if [ts, te] in g["mentions"])
    assert [s, e] in group["mentions"]                                     # alias linked: one person, one token
    assert (await submit(client, rid, view, decisions)).status_code == 201
    assert await runner.process_one("w1") == "done"

    report = (await client.get(f"{BASE}/{rid}/report")).json()
    assert report["ai"]["status"] == "complete" and report["ai"]["simulated"] is True
    blank = [r for r in report["model_risks"] if r["category"] == "missing_detail"]
    assert blank and "______" in blank[0]["evidence"][0]["text"]
    stated = [o for o in report["obligations"] if o["deadline_status"] == "stated"]
    assert any(o["deadline"] in spec["kept"] for o in stated), report["obligations"]
    assert spec["identifier"] not in json.dumps(report["obligations"] + report["model_risks"])
