"""The estate survey. Synthetic fixtures only -- no Mongo, no network.

The survey exists to unblock two decisions that were wrongly gated behind a
snapshot: the four owner-policy behaviours and the blocked-record count. Both
need magnitude, not determinism.

The tests that matter most are the ones asserting it reuses
document_migration.classify() rather than reimplementing the decision matrix.
A second copy would drift, and the owner would then approve behaviour that
differs from what the migration actually does.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.db import v2_capture_contract as contract  # noqa: E402
from app.services import document_migration  # noqa: E402

from v2_fakes import (  # noqa: E402
    FakeClient, READ_ONLY_STATUS, READ_WRITE_STATUS, UNAUTHENTICATED_STATUS,
    estate, row,
)

_SPEC = importlib.util.spec_from_file_location(
    "v2_estate_survey", BACKEND / "scripts" / "v2_estate_survey.py")
survey = importlib.util.module_from_spec(_SPEC)
sys.modules["v2_estate_survey"] = survey
_SPEC.loader.exec_module(survey)


@pytest.fixture()
def upload_root(tmp_path):
    (tmp_path / "docs").mkdir()
    return tmp_path


def _pdf(upload_root: Path, name: str, body: bytes = b"%PDF") -> Path:
    path = upload_root / "docs" / name
    path.write_bytes(body)
    return path


def _legacy(doc_id, status, file_path=None, submitted_to=None,
            client_id="c1", template_type="affidavit"):
    doc = {"_id": doc_id, "review_status": status, "client_id": client_id,
           "template_type": template_type}
    if file_path is not None:
        doc["file_path"] = str(file_path)
    if submitted_to is not None:
        doc["submitted_to"] = submitted_to
    return doc


def _argv(upload_root, **extra):
    argv = ["--mongo-uri", "mongodb://localhost:27017",
            "--db", "attorney_ai_snapshot",
            "--upload-root", str(upload_root)]
    for key, value in extra.items():
        flag = "--" + key.replace("_", "-")
        argv.append(flag) if value is True else argv.extend([flag, str(value)])
    return argv


# ── it counts what the migration would actually do ───────────────────────────

def _plan_semantics(docs, docs_root, revision_owner=None):
    """_plan_one()'s rules, written out here as the reference.

    Deliberately independent of the survey's implementation: if both were
    derived from the same helper the comparison would be circular. This is read
    from document_migration._plan_one and asserts nothing about how the survey
    computes it.
    """
    from app.services.document_migration import (
        BLOCK_DUPLICATE_PLAN, BLOCK_ID_COLLISION, BLOCK_NO_CLIENT,
        BLOCK_NO_TEMPLATE_TYPE, BLOCK_UNREADABLE_FILE,
        BLOCK_UNSUPPORTED_STATUS, BLOCKING_CODES, classify,
        is_supported_status, planned_revision_id)

    revision_owner = revision_owner or {}
    outcomes, approvals, occurrences = {}, {}, {}
    blocked, seen = 0, {}

    for doc in docs:
        if doc.get("schema_version") == 2:
            continue                       # the planner never selects these
        codes = []
        if not doc.get("template_type"):
            codes.append(BLOCK_NO_TEMPLATE_TYPE)
        if not doc.get("client_id"):
            codes.append(BLOCK_NO_CLIENT)
        plan_id = planned_revision_id(doc["_id"])
        owner = revision_owner.get(plan_id, ...)
        if owner is not ... and owner != doc["_id"]:
            codes.append(BLOCK_ID_COLLISION)
        if plan_id in seen:
            codes.append(BLOCK_DUPLICATE_PLAN)
        seen[plan_id] = doc["_id"]

        observed = contract.classify_source(doc.get("file_path"), docs_root)
        if observed["source_state"] == contract.SRC_UNREADABLE:
            codes.append(BLOCK_UNREADABLE_FILE)
        if not is_supported_status(doc.get("review_status")):
            codes.append(BLOCK_UNSUPPORTED_STATUS)

        blocking = [c for c in codes if c in BLOCKING_CODES]
        for code in blocking:
            occurrences[code] = occurrences.get(code, 0) + 1
        if blocking:
            blocked += 1
            continue
        outcome = classify(
            doc, file_present=observed["source_state"] == contract.SRC_READABLE)
        outcomes[outcome.code] = outcomes.get(outcome.code, 0) + 1
        if outcome.requires_owner_approval:
            approvals[outcome.code] = approvals.get(outcome.code, 0) + 1

    return {"outcomes": outcomes, "requires_owner_approval": approvals,
            "blocked_documents": blocked,
            "blocking_condition_occurrences": occurrences}


def _assert_matches_planner(docs, docs_root, revisions=None):
    result = survey.survey(estate(docs, revisions=revisions or []), docs_root)
    expected = _plan_semantics(
        docs, docs_root,
        {r["_id"]: r.get("document_id") for r in (revisions or [])})
    for key, value in expected.items():
        assert result[key] == value, key
    return result


def test_outcomes_match_plan_one_for_a_mixed_estate(upload_root):
    pdf = _pdf(upload_root, "a.pdf")
    gone = upload_root / "docs" / "gone.pdf"
    docs = [
        _legacy("a", "draft", pdf),
        _legacy("b", "submitted", pdf, submitted_to="l1"),
        _legacy("c", "submitted", gone, submitted_to="l1"),
        _legacy("d", "approved", gone, submitted_to="l1"),
        _legacy("e", "approved", pdf, submitted_to=None),
    ]
    result = _assert_matches_planner(docs, upload_root / "docs")
    assert result["legacy_documents_surveyed"] == 5


def test_the_survey_does_not_redefine_the_decision_matrix():
    source = (BACKEND / "scripts" / "v2_estate_survey.py").read_text(
        encoding="utf-8")
    for forbidden in ("def classify", "OUTCOME_SUBMITTED_NO_FILE =",
                      "def is_supported_status", "def planned_revision_id",
                      "BLOCKING_CODES ="):
        assert forbidden not in source, (
            f"the survey defines {forbidden!r} locally; it must use "
            "document_migration")


# ── V2 rows never enter any count ────────────────────────────────────────────

def test_v2_documents_are_excluded_and_reported_separately(upload_root):
    """A migrated row has already had its fate decided. Counting it under a
    policy decision would ask the owner to approve something already done."""
    gone = upload_root / "docs" / "gone.pdf"
    v2 = _legacy("v2", "approved", gone, submitted_to="l1")
    v2["schema_version"] = 2
    legacy = _legacy("a", "draft", _pdf(upload_root, "a.pdf"))

    result = survey.survey(estate([legacy, v2]), upload_root / "docs")

    assert result["legacy_documents_surveyed"] == 1
    assert result["v2_documents_excluded"] == 1
    # approved + missing file would be approved_no_file, which needs approval.
    assert result["requires_owner_approval"] == {}
    assert result["approval_affected_documents"] == 0
    assert "approved_no_file" not in result["outcomes"]


def test_a_v2_document_with_every_blocker_is_still_excluded(upload_root):
    directory = upload_root / "docs" / "dir.pdf"
    directory.mkdir()
    v2 = _legacy("v2", "nonsense_status", directory, client_id=None,
                 template_type=None)
    v2["schema_version"] = 2

    result = survey.survey(estate([v2]), upload_root / "docs")

    assert result["legacy_documents_surveyed"] == 0
    assert result["blocked_documents"] == 0
    assert result["blocking_condition_occurrences"] == {}
    assert result["v2_documents_excluded"] == 1


# ── a blocked document gets no outcome and no approval count ─────────────────

def test_a_blocked_document_records_no_outcome(upload_root):
    """_plan_one sets outcome_code = None for anything blocking. An approved
    document with no client_id must NOT appear under approved_no_file."""
    gone = upload_root / "docs" / "gone.pdf"
    blocked = _legacy("a", "approved", gone, submitted_to="l1", client_id=None)

    result = _assert_matches_planner([blocked], upload_root / "docs")

    assert result["blocked_documents"] == 1
    assert result["outcomes"] == {}
    assert result["requires_owner_approval"] == {}
    assert result["approval_affected_documents"] == 0


def test_one_document_with_three_blockers_is_one_blocked_document(upload_root):
    """The distinction the old lower-bound number destroyed: three conditions
    on one document is ONE blocked document and THREE occurrences."""
    directory = upload_root / "docs" / "unreadable.pdf"
    directory.mkdir()
    trio = _legacy("a", "some_unknown_status", directory,
                   client_id=None, template_type="affidavit")

    result = _assert_matches_planner([trio], upload_root / "docs")

    assert result["blocked_documents"] == 1
    assert result["blocking_condition_occurrences"] == {
        "missing_client_id": 1,
        "source_file_unreadable": 1,
        "unsupported_legacy_review_status": 1,
    }
    assert sum(result["blocking_condition_occurrences"].values()) == 3
    assert result["unblocked_documents"] == 0


def test_four_blockers_on_one_document(upload_root):
    directory = upload_root / "docs" / "unreadable.pdf"
    directory.mkdir()
    quad = _legacy("a", "nonsense", directory, client_id=None,
                   template_type=None)

    result = _assert_matches_planner([quad], upload_root / "docs")

    assert result["blocked_documents"] == 1
    assert sum(result["blocking_condition_occurrences"].values()) == 4


def test_blocked_and_unblocked_documents_partition_the_estate(upload_root):
    directory = upload_root / "docs" / "unreadable.pdf"
    directory.mkdir()
    docs = [
        _legacy("a", "draft", _pdf(upload_root, "ok.pdf")),
        _legacy("b", "draft", directory),
        _legacy("c", "draft", None, client_id=None),
    ]
    result = _assert_matches_planner(docs, upload_root / "docs")

    assert result["blocked_documents"] == 2
    assert result["unblocked_documents"] == 1
    assert (result["blocked_documents"] + result["unblocked_documents"]
            == result["legacy_documents_surveyed"])


def test_a_revision_owned_by_another_document_is_a_collision(upload_root):
    from app.services.document_migration import planned_revision_id
    doc = _legacy("a", "draft", _pdf(upload_root, "a.pdf"))
    revisions = [{"_id": planned_revision_id("a"), "document_id": "someone-else"}]

    result = _assert_matches_planner(doc and [doc], upload_root / "docs",
                                     revisions=revisions)

    assert result["blocked_documents"] == 1
    assert result["blocking_condition_occurrences"] == {
        "planned_revision_id_collision": 1}


def test_a_revision_already_owned_by_this_document_is_not_a_blocker(upload_root):
    """already_planned is a FLAG in the planner, not a blocking code."""
    from app.services.document_migration import planned_revision_id
    doc = _legacy("a", "draft", _pdf(upload_root, "a.pdf"))
    revisions = [{"_id": planned_revision_id("a"), "document_id": "a"}]

    result = _assert_matches_planner([doc], upload_root / "docs",
                                     revisions=revisions)

    assert result["blocked_documents"] == 0
    assert result["outcomes"] == {"draft_with_file": 1}


# ── owner-approval counts ────────────────────────────────────────────────────

def test_owner_approval_counts_are_the_number_the_decision_needs(upload_root):
    missing = upload_root / "docs" / "gone.pdf"
    docs = [
        _legacy("a", "submitted", missing, submitted_to="l1"),
        _legacy("b", "submitted", missing, submitted_to="l1"),
        _legacy("c", "approved", missing, submitted_to="l1"),
        _legacy("d", "draft", _pdf(upload_root, "ok.pdf")),
    ]
    result = _assert_matches_planner(docs, upload_root / "docs")

    assert result["requires_owner_approval"]["submitted_no_file"] == 2
    assert result["requires_owner_approval"]["approved_no_file"] == 1
    assert result["approval_affected_documents"] == 3


def test_an_estate_with_nothing_to_approve_says_so(upload_root):
    pdf = _pdf(upload_root, "a.pdf")
    docs = [_legacy("a", "draft", pdf),
            _legacy("b", "submitted", pdf, submitted_to="l1")]
    result = _assert_matches_planner(docs, upload_root / "docs")
    assert result["requires_owner_approval"] == {}
    assert result["approval_affected_documents"] == 0


# ── source states ────────────────────────────────────────────────────────────

def test_source_states_use_the_shared_classifier(upload_root):
    directory = upload_root / "docs" / "dir.pdf"
    directory.mkdir()
    docs = [
        _legacy("a", "draft", _pdf(upload_root, "ok.pdf")),
        _legacy("b", "draft", None),
        _legacy("c", "draft", upload_root / "docs" / "gone.pdf"),
        _legacy("d", "draft", directory),
    ]
    result = survey.survey(estate(docs), upload_root / "docs")
    assert result["source_states"] == {
        survey.SRC_READABLE: 1, survey.SRC_ABSENT_PATH: 1,
        survey.SRC_MISSING: 1, survey.SRC_UNREADABLE: 1}


# ── the credential never enters process arguments ────────────────────────────

def test_a_production_uri_on_the_command_line_is_refused(upload_root, capsys):
    """argv is readable by every other process on the host and is kept in shell
    history. A local throwaway target can live with that; a production
    credential cannot."""
    calls = []
    argv = ["--mongo-uri", "mongodb+srv://user:secret@c0.abc.mongodb.net",
            "--db", "attorney_ai", "--upload-root", str(upload_root),
            "--acknowledge-production-read"]
    code = survey.main(argv, client_factory=lambda u: calls.append(u))

    assert code == survey.EXIT_REFUSED
    err = capsys.readouterr().err
    assert "process arguments" in err.lower()
    assert "secret" not in err, "the refusal echoed the credential"
    assert calls == []


def test_a_local_uri_on_the_command_line_is_allowed(upload_root):
    """The restriction is about production, not about ceremony."""
    db = estate([row("a", _pdf(upload_root, "a.pdf"))])
    assert survey.main(_argv(upload_root),
                       client_factory=lambda u: FakeClient(db)) == survey.EXIT_OK


def test_the_environment_variable_form_is_accepted(upload_root, monkeypatch):
    monkeypatch.setenv("V2_SURVEY_URI", "mongodb://localhost:27017")
    db = estate([row("a", _pdf(upload_root, "a.pdf"))])
    argv = ["--mongo-uri-env", "V2_SURVEY_URI", "--db", "attorney_ai_snapshot",
            "--upload-root", str(upload_root)]
    assert survey.main(argv, client_factory=lambda u: FakeClient(db)) == survey.EXIT_OK


def test_an_unset_environment_variable_is_refused(upload_root, monkeypatch, capsys):
    monkeypatch.delenv("V2_SURVEY_URI", raising=False)
    argv = ["--mongo-uri-env", "V2_SURVEY_URI", "--db", "attorney_ai_snapshot",
            "--upload-root", str(upload_root)]
    code = survey.main(argv, client_factory=lambda u: None)
    assert code == survey.EXIT_REFUSED
    assert "unset or empty" in capsys.readouterr().err


def test_the_hidden_prompt_form_is_accepted(upload_root, monkeypatch):
    monkeypatch.setattr(survey.getpass, "getpass",
                        lambda *_: "mongodb://localhost:27017")
    db = estate([row("a", _pdf(upload_root, "a.pdf"))])
    argv = ["--prompt-uri", "--db", "attorney_ai_snapshot",
            "--upload-root", str(upload_root)]
    assert survey.main(argv, client_factory=lambda u: FakeClient(db)) == survey.EXIT_OK


def test_an_empty_prompt_is_refused(upload_root, monkeypatch, capsys):
    monkeypatch.setattr(survey.getpass, "getpass", lambda *_: "   ")
    argv = ["--prompt-uri", "--db", "attorney_ai_snapshot",
            "--upload-root", str(upload_root)]
    assert survey.main(argv, client_factory=lambda u: None) == survey.EXIT_REFUSED
    assert "no connection string" in capsys.readouterr().err


@pytest.mark.parametrize("extra", [
    [],                                                    # none given
    ["--mongo-uri", "mongodb://localhost:27017",
     "--mongo-uri-env", "V2_SURVEY_URI"],                  # two given
    ["--prompt-uri", "--mongo-uri", "mongodb://localhost:27017"],
])
def test_exactly_one_credential_source_is_required(upload_root, extra, capsys):
    argv = ["--db", "attorney_ai_snapshot", "--upload-root", str(upload_root),
            *extra]
    assert survey.main(argv, client_factory=lambda u: None) == survey.EXIT_REFUSED
    assert "exactly one" in capsys.readouterr().err


def test_the_uri_source_is_recorded_but_the_uri_is_not(upload_root, tmp_path,
                                                       monkeypatch):
    monkeypatch.setenv("V2_SURVEY_URI", "mongodb://someone:hunter2@localhost:27017")
    db = estate([row("a", _pdf(upload_root, "a.pdf"))])
    out = tmp_path / "survey.json"
    argv = ["--mongo-uri-env", "V2_SURVEY_URI", "--db", "attorney_ai_snapshot",
            "--upload-root", str(upload_root), "--out", str(out)]
    survey.main(argv, client_factory=lambda u: FakeClient(db))
    blob = out.read_text(encoding="utf-8")

    assert "environment (V2_SURVEY_URI)" in blob
    assert "hunter2" not in blob
    assert "someone" not in blob


# ── it is read-only, and refuses anything that is not ────────────────────────

def test_a_write_capable_credential_is_refused(upload_root, capsys):
    db = estate([], status=READ_WRITE_STATUS)
    code = survey.main(_argv(upload_root), client_factory=lambda u: FakeClient(db))
    assert code == survey.EXIT_REFUSED
    assert "readWrite" in capsys.readouterr().err


def test_an_unauthenticated_target_is_refused(upload_root, capsys):
    db = estate([], status=UNAUTHENTICATED_STATUS)
    code = survey.main(_argv(upload_root), client_factory=lambda u: FakeClient(db))
    assert code == survey.EXIT_REFUSED
    assert "unauthenticated" in capsys.readouterr().err


@pytest.mark.parametrize("uri, db_name", [
    ("mongodb://localhost:27017", "attorney_ai"),
    ("mongodb+srv://c0.abc.mongodb.net", "attorney_ai"),
])
def test_production_is_refused_unless_acknowledged(upload_root, uri, db_name):
    calls = []
    argv = _argv(upload_root)
    argv[argv.index("--mongo-uri") + 1] = uri
    argv[argv.index("--db") + 1] = db_name
    code = survey.main(argv, client_factory=lambda u: calls.append(u))
    assert code == survey.EXIT_REFUSED
    assert calls == [], "a refused target must never be connected to"


def test_acknowledged_production_proceeds_via_the_environment(upload_root,
                                                              monkeypatch):
    """argv is refused for production, so the credential arrives out of band."""
    monkeypatch.setenv("V2_SURVEY_URI", "mongodb+srv://u:p@c0.abc.mongodb.net")
    db = estate([row("a", _pdf(upload_root, "a.pdf"))])
    argv = ["--mongo-uri-env", "V2_SURVEY_URI", "--db", "attorney_ai",
            "--upload-root", str(upload_root), "--acknowledge-production-read"]
    assert survey.main(argv, client_factory=lambda u: FakeClient(db)) == survey.EXIT_OK


def test_the_survey_calls_no_write_api():
    source = (BACKEND / "scripts" / "v2_estate_survey.py").read_text(
        encoding="utf-8")
    for forbidden in ("insert_one", "insert_many", "update_one", "update_many",
                      "replace_one", "delete_one", "delete_many", "drop(",
                      "create_index", "bulk_write", "find_one_and", "approve(",
                      "apply(", "rollback("):
        assert forbidden not in source


# ── it does not pretend to be a dry-run ──────────────────────────────────────

def test_the_report_says_it_is_not_a_dry_run(upload_root, tmp_path):
    db = estate([row("a", _pdf(upload_root, "a.pdf"))])
    out = tmp_path / "survey.json"
    survey.main(_argv(upload_root, out=out), client_factory=lambda u: FakeClient(db))
    report = json.loads(out.read_text(encoding="utf-8"))

    assert report["is_a_dry_run"] is False
    assert "drift" in report["caveat"]
    for absent in ("manifest", "fingerprint", "rollback_token", "approved"):
        assert absent not in report


def test_document_revisions_emptiness_is_reported(upload_root, tmp_path):
    """The 'revisions are empty and static while the flag is off' assumption,
    checked rather than asserted."""
    db = estate([row("a", _pdf(upload_root, "a.pdf"))],
                revisions=[{"_id": "r1"}])
    out = tmp_path / "survey.json"
    survey.main(_argv(upload_root, out=out), client_factory=lambda u: FakeClient(db))
    report = json.loads(out.read_text(encoding="utf-8"))

    assert report["document_revisions"] == 1
    assert report["document_revisions_empty"] is False


def test_the_report_carries_no_document_ids_or_paths(upload_root, tmp_path):
    """Aggregates only. A count needs no identifiers, so it carries none."""
    _pdf(upload_root, "Khula-Petition-Ayesha.pdf")
    db = estate([row("secret-doc-id",
                     upload_root / "docs" / "Khula-Petition-Ayesha.pdf")])
    out = tmp_path / "survey.json"
    survey.main(_argv(upload_root, out=out), client_factory=lambda u: FakeClient(db))
    blob = out.read_text(encoding="utf-8")

    assert "Ayesha" not in blob
    assert "secret-doc-id" not in blob
