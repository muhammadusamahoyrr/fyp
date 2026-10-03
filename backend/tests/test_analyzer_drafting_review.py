"""Analyzer Slice 1, step 6: the INTERNAL drafting-question review.

Real pipeline on the replica set (upload -> ... -> hypothesis scan, AI layer
off). What is pinned (ANALYZER_HYPOTHESES_PLAN.md §6, owner's conditions of
2026-10-04): off by default; lawyers only; synthetic sources only; every
response carries the server's evaluation status (not_passed) and the banner;
a decision must echo that status; scanner labels are fixed and "Missing"
appears only as the reviewer's internal outcome, and a decision grants no
approval or label status; the AI signal is a separate field;
decisions are append-only; evidence is cut here and withheld when the text no
longer matches; a missing or over-claiming record fails closed.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from app.core.config import settings
from app.db.collections import (
    get_analysis_hypothesis_decisions_col,
    get_analysis_runs_col,
    get_analysis_sources_col,
)
from app.services.analyzer import deletion, drafting_review, runner
from app.services.analyzer.hypotheses import gate_status
from tests._analyzer_support import http  # noqa: F401 -- fixture
from tests.test_analyzer_ai_config import GOOD
from tests.test_analyzer_report import to_analysis

BASE = "/documents/analyses/runs"


@pytest.fixture
async def done(http, mongo_transactional, monkeypatch):
    for name, value in GOOD.items():
        monkeypatch.setattr(settings, name, value)
    monkeypatch.setattr(settings, "analyzer_ai", False)
    monkeypatch.setattr(settings, "analyzer_engine_hypotheses", True)
    monkeypatch.setattr(settings, "analyzer_hypothesis_review_ui", True)
    client, actor = http
    await get_analysis_runs_col().delete_many({"is_open": True})
    created = await to_analysis(client)
    assert await runner.process_one("w1") == "queued_hypothesis_scan"
    assert await runner.process_one("w1") == "done"
    return client, actor, created["run_id"], monkeypatch


async def review(client, rid):
    return await client.get(f"{BASE}/{rid}/drafting-review")


async def decide(client, rid, key, **body):
    body.setdefault("evaluation_ack", "not_passed")
    return await client.post(f"{BASE}/{rid}/drafting-review/decisions", json=body,
                             headers={"Idempotency-Key": key})


# ── gates ───────────────────────────────────────────────────────────────────

def test_the_review_screen_is_off_by_default():
    assert type(settings).model_fields["analyzer_hypothesis_review_ui"].default is False
    assert type(settings).model_fields["analyzer_engine_hypotheses"].default is False


async def test_off_means_not_found(done):
    client, _, rid, monkeypatch = done
    monkeypatch.setattr(settings, "analyzer_hypothesis_review_ui", False)
    r = await review(client, rid)
    assert r.status_code == 404 and r.json()["error"]["code"] == "feature_disabled"
    r = await decide(client, rid, "key-00000001", question_id="rent_amount", decision="confirm")
    assert r.status_code == 404


async def test_a_client_or_admin_is_refused(done):
    client, actor, rid, _ = done
    for role in ("client", "admin"):
        actor["role"] = role
        assert (await review(client, rid)).status_code == 403
    actor["role"] = "lawyer"


async def test_a_source_not_attested_synthetic_is_refused(done):
    client, _, rid, _ = done
    run = await get_analysis_runs_col().find_one({"_id": rid})
    await get_analysis_sources_col().update_one({"_id": run["source_id"]}, {"$set": {"attestation.synthetic": False}})
    r = await review(client, rid)
    assert r.status_code == 403 and r.json()["error"]["code"] == "synthetic_only"


async def test_an_ai_report_run_has_no_drafting_review(http, mongo_transactional, monkeypatch):
    for name, value in GOOD.items():
        monkeypatch.setattr(settings, name, value)
    monkeypatch.setattr(settings, "analyzer_ai", False)
    monkeypatch.setattr(settings, "analyzer_hypothesis_review_ui", True)
    client, _ = http
    await get_analysis_runs_col().delete_many({"is_open": True})
    rid = (await to_analysis(client))["run_id"]
    assert await runner.process_one("w1") == "done"
    r = await review(client, rid)
    assert r.status_code == 409 and r.json()["error"]["code"] == "not_drafting_review"


# ── the evaluation status, served and enforced by the server ────────────────

async def test_every_review_carries_the_evaluation_status_and_banner(done):
    client, _, rid, _ = done
    body = (await review(client, rid)).json()
    ev = body["evaluation"]
    assert ev["status"] == "not_passed" and ev["passed"] is False and ev["production_approved"] is False
    assert ev["banner"] == "Evaluation not passed — internal review only."
    assert body["mode"] == ev["mode"] == "internal_review_only"
    assert ev["dataset"]["name"] == "validation-2" and ev["weak_questions"]
    assert body["engine_labels"] == ["Automatic drafting check — no AI", "No law applied", "Not lawyer reviewed"]


async def test_a_decision_must_echo_the_servers_evaluation_status(done):
    client, _, rid, _ = done
    for ack in (None, "engineering_passed", "passed"):
        r = await decide(client, rid, "key-00000002", question_id="rent_amount", decision="confirm",
                         evaluation_ack=ack)
        assert r.status_code == 409 and r.json()["error"]["code"] == "evaluation_ack_mismatch"
    assert await get_analysis_hypothesis_decisions_col().count_documents({"run_id": rid}) == 0


async def test_a_missing_or_overclaiming_record_fails_closed(done, tmp_path):
    client, _, rid, monkeypatch = done
    monkeypatch.setattr(gate_status, "RECORD_PATH", tmp_path / "absent.yaml")
    r = await review(client, rid)
    assert r.status_code == 503 and r.json()["error"]["code"] == "evaluation_record_unavailable"
    assert "questions" not in r.json()

    record = yaml.safe_load(Path(gate_status.__file__).with_name("ai_hypothesis_evaluation_record.yaml")
                            .read_text(encoding="utf-8"))
    for change in ({"status": "engineering_passed"},                         # failing checks, validation role
                   {"production_approved": True},
                   {"status": "production_approved"}):
        bad = tmp_path / "bad.yaml"
        bad.write_text(yaml.safe_dump({**record, **change}), encoding="utf-8")
        monkeypatch.setattr(gate_status, "RECORD_PATH", bad)
        assert (await review(client, rid)).status_code == 503


def test_the_committed_record_is_served_as_not_passed():
    ev = gate_status.evaluation_status()
    assert (ev["status"], ev["mode"], ev["production_approved"]) == ("not_passed", "internal_review_only", False)
    assert (ev["attention_precision"], ev["attention_recall"]) == (0.861, 0.941)


# ── what the screen shows ───────────────────────────────────────────────────

async def test_scanner_labels_are_fixed_and_the_ai_signal_is_separate(done):
    client, _, rid, _ = done
    body = (await review(client, rid)).json()
    assert body["questions"]
    for q in body["questions"]:
        assert q["status_label"] == drafting_review.SCANNER_LABELS[q["status"]]
        assert "missing" not in q["status_label"].lower() and "absent" not in q["status_label"].lower()
        assert q["lawyer_outcome"] is None and q["decisions"] == []
        assert q["ai_review"]["label"] == "AI review (separate from the automatic check)"
        assert q["ai_review"]["signal"] is None and q["ai_review"]["signal_label"] == "AI review unavailable"
        for group in q["evidence"]:
            for s in group["sentences"]:
                assert s["withheld"] is None and s["text"]
    statuses = {q["status"] for q in body["questions"]}
    assert "not_located" in statuses and "present" in statuses


async def test_evidence_is_withheld_when_the_text_no_longer_matches(done):
    client, _, rid, _ = done
    await get_analysis_runs_col().update_one({"_id": rid}, {"$set": {"hypotheses.text_sha256": "0" * 64}})
    body = (await review(client, rid)).json()
    assert body["text_intact"] is False
    found = [q for q in body["questions"] if q["evidence"]]
    assert found
    for q in found:
        assert q["evidence_withheld"] == "text_mismatch"
        assert all(s["text"] is None and s["withheld"] == "text_mismatch"
                   for g in q["evidence"] for s in g["sentences"])


# ── decisions: append-only ──────────────────────────────────────────────────

async def not_located(client, rid):
    body = (await review(client, rid)).json()
    return next(q for q in body["questions"]
                if q["status"] == "not_located" and q["polarity"] == "attention_if_absent")


async def test_missing_appears_only_as_the_reviewers_internal_outcome(done):
    client, actor, rid, _ = done
    q = await not_located(client, rid)
    assert q["status_label"] == "Not located automatically" and q["lawyer_outcome"] is None
    r = await decide(client, rid, "key-00000003", question_id=q["question_id"], decision="confirm")
    assert r.status_code == 201
    row = r.json()
    assert (row["decision"], row["scanner_status"], row["actor_user_id"], row["evaluation_status"]) == \
        ("confirm", "not_located", actor["_id"], "not_passed")
    q = next(x for x in (await review(client, rid)).json()["questions"] if x["question_id"] == q["question_id"])
    assert q["lawyer_outcome"] == "Reviewer marked as missing — internal review only"
    assert "confirmed by a lawyer" not in str((await review(client, rid)).json()).lower()
    assert q["status"] == "not_located" and q["status_label"] == "Not located automatically"


async def test_decisions_are_appended_never_changed(done):
    client, _, rid, _ = done
    q = await not_located(client, rid)
    body = (await review(client, rid)).json()
    sid = next(s["sentence_id"] for x in body["questions"] for g in x["evidence"] for s in g["sentences"])
    assert (await decide(client, rid, "key-00000004", question_id=q["question_id"], decision="confirm")).status_code == 201
    assert (await decide(client, rid, "key-00000005", question_id=q["question_id"], decision="dismiss",
                         reason_code="scanner_status_wrong")).status_code == 201
    assert (await decide(client, rid, "key-00000006", question_id=q["question_id"], decision="point_to_evidence",
                         sentence_ids=[sid])).status_code == 201
    q = next(x for x in (await review(client, rid)).json()["questions"] if x["question_id"] == q["question_id"])
    assert [d["decision"] for d in q["decisions"]] == ["confirm", "dismiss", "point_to_evidence"]
    assert q["decisions"][2]["sentence_ids"] == [sid]
    assert q["lawyer_outcome"] == "Reviewer pointed to evidence — internal review only"
    assert await get_analysis_hypothesis_decisions_col().count_documents({"run_id": rid}) == 3
    # No route updates or deletes a decision.
    import app.api.v1.routes.document_analyses as routes
    paths = {(r.path, m) for r in routes.router.routes for m in getattr(r, "methods", ())}
    assert not any("decisions" in p and m in ("PUT", "PATCH", "DELETE") for p, m in paths)


async def test_a_retried_decision_is_recorded_once(done):
    client, _, rid, _ = done
    q = await not_located(client, rid)
    a = await decide(client, rid, "key-00000007", question_id=q["question_id"], decision="confirm")
    b = await decide(client, rid, "key-00000007", question_id=q["question_id"], decision="confirm")
    assert a.status_code == b.status_code == 201 and a.json()["id"] == b.json()["id"]
    c = await decide(client, rid, "key-00000007", question_id=q["question_id"], decision="dismiss",
                     reason_code="other")
    assert c.status_code == 409 and c.json()["error"]["code"] == "idempotency_key_reused"
    assert await get_analysis_hypothesis_decisions_col().count_documents({"run_id": rid}) == 1


@pytest.mark.parametrize("body, code", [
    ({"question_id": "nope", "decision": "confirm"}, "unknown_question"),
    ({"question_id": "rent_amount", "decision": "approve"}, "invalid_decision"),
    ({"question_id": "rent_amount", "decision": "dismiss"}, "invalid_reason"),
    ({"question_id": "rent_amount", "decision": "dismiss", "reason_code": "because"}, "invalid_reason"),
    ({"question_id": "rent_amount", "decision": "confirm", "reason_code": "other"}, "invalid_reason"),
    ({"question_id": "rent_amount", "decision": "point_to_evidence"}, "invalid_evidence"),
    ({"question_id": "rent_amount", "decision": "point_to_evidence", "sentence_ids": ["s999"]}, "invalid_evidence"),
    ({"question_id": "rent_amount", "decision": "confirm", "sentence_ids": ["s1"]}, "invalid_evidence"),
])
async def test_a_bad_decision_is_refused_and_nothing_is_written(done, body, code):
    client, _, rid, _ = done
    r = await decide(client, rid, "key-00000008", **body)
    assert r.status_code == 422 and r.json()["error"]["code"] == code
    assert await get_analysis_hypothesis_decisions_col().count_documents({"run_id": rid}) == 0


async def test_a_missing_idempotency_key_is_refused(done):
    client, _, rid, _ = done
    r = await client.post(f"{BASE}/{rid}/drafting-review/decisions",
                          json={"question_id": "rent_amount", "decision": "confirm", "evaluation_ack": "not_passed"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_idempotency_key"


async def test_the_purge_removes_decisions(done):
    client, _, rid, _ = done
    q = await not_located(client, rid)
    assert (await decide(client, rid, "key-00000009", question_id=q["question_id"], decision="confirm")).status_code == 201
    run = await get_analysis_runs_col().find_one({"_id": rid})
    assert (await client.delete(f"/documents/analyses/{run['source_id']}")).status_code == 204
    while await deletion.purge_source(run["source_id"]) == "waiting":
        pass
    assert await get_analysis_hypothesis_decisions_col().count_documents({"source_id": run["source_id"]}) == 0
    assert (await review(client, rid)).status_code == 404


# ── nothing reaches a client ────────────────────────────────────────────────

def test_only_the_lawyer_analyzer_routes_use_the_review():
    import re

    root = Path(__file__).resolve().parents[1] / "app"
    uses = re.compile(r"import drafting_review|analyzer\.drafting_review\b|drafting_review\.(?!py)")
    users = sorted(str(p.relative_to(root)).replace("\\", "/") for p in root.rglob("*.py")
                   if uses.search(p.read_text(encoding="utf-8")) and p.name != "drafting_review.py")
    assert users == ["api/v1/routes/document_analyses.py"]


async def test_an_internal_decision_grants_no_approval_or_label_status(done):
    """The reviewer is a registered lawyer account, not a verified
    qualification: a decision approves no legal pack, grants no reviewer
    qualification, audits no approval and changes no evaluation status."""
    from app.db.collections import (
        get_analysis_approval_audit_col,
        get_analysis_playbook_approvals_col,
        get_analysis_reviewer_qualifications_col,
    )

    client, actor, rid, _ = done
    record_before = gate_status.RECORD_PATH.read_bytes()
    cols = (get_analysis_playbook_approvals_col(), get_analysis_reviewer_qualifications_col(),
            get_analysis_approval_audit_col())
    before = [await c.count_documents({}) for c in cols]
    q = await not_located(client, rid)
    for n, decision in enumerate(("confirm", "dismiss")):
        extra = {"reason_code": "other"} if decision == "dismiss" else {}
        assert (await decide(client, rid, f"key-0000010{n}", question_id=q["question_id"],
                             decision=decision, **extra)).status_code == 201
    assert [await c.count_documents({}) for c in cols] == before
    assert gate_status.RECORD_PATH.read_bytes() == record_before
    ev = gate_status.evaluation_status()
    assert (ev["status"], ev["label_review"]) == ("not_passed", "developer_only")
    body = (await review(client, rid)).json()
    assert body["evaluation"]["status"] == "not_passed" and body["evaluation"]["label_review"] == "developer_only"
    rows = [d async for d in get_analysis_hypothesis_decisions_col().find({"run_id": rid})]
    assert all(set(d) <= {"_id", "run_id", "source_id", "fence", "question_id", "decision", "reason_code",
                          "sentence_ids", "scanner_status", "catalogue_sha256", "scanner", "evaluation_status",
                          "actor_user_id", "actor_role", "at", "idempotency_key"} for d in rows)
    assert not any("approv" in k or "qualif" in k or "label_review" in k for d in rows for k in d)
