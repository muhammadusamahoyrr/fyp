"""Document Analyzer: the lawyer-review package names exactly what is reviewed.

Built offline into a temporary directory: every evaluation document and
label, every legal playbook with the hashes an approval must quote, the
employment coverage request, and a manifest whose hashes match the files.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import re
from pathlib import Path

import pytest

from app.services.analyzer import evaluation, playbook_engine

BACKEND = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("analyzer_review_package",
                                              BACKEND / "scripts" / "analyzer_review_package.py")
package = importlib.util.module_from_spec(spec)
spec.loader.exec_module(package)


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    out = tmp_path_factory.mktemp("review")
    manifest = package.build(out, generated="2026-10-02")
    return out, manifest, {p.name: p.read_text(encoding="utf-8") for p in out.iterdir()}


def test_the_manifest_hashes_every_file_and_names_the_dataset_and_packs(built):
    out, manifest, files = built
    assert set(files) == {"01_dataset_labels_review.html", "02_playbooks_review.html",
                          "03_employment_coverage_request.html", "manifest.json"}
    for name, digest in manifest["files"].items():
        assert hashlib.sha256(files[name].encode("utf-8")).hexdigest() == digest
    assert manifest["dataset"]["sha256"] == evaluation.load_dataset().sha256
    packs = {p.id: p for p in playbook_engine.load_packs()}
    for pid, entry in manifest["playbooks"].items():
        assert (entry["content_hash"], entry["authorities_hash"]) == (packs[pid].content_hash,
                                                                      packs[pid].authorities_hash)
    assert set(manifest["playbooks"]) == {"tenancy_punjab", "nda"}
    assert manifest["not_for_approval"]["employment"]["content_hash"] == packs["employment"].content_hash
    assert "employment.no_employment_statute" in manifest["release_blockers"]
    assert json.loads(files["manifest.json"]) == manifest


def test_every_document_and_label_is_in_the_dataset_sheet(built):
    _, manifest, files = built
    sheet = files["01_dataset_labels_review.html"]
    dataset = evaluation.load_dataset()
    assert manifest["dataset"]["sha256"] in sheet
    for doc in dataset.documents:
        assert doc.id in sheet and doc.sha256 in sheet
        risks, obligations = len(doc.expected["risks"]), len(doc.expected["obligations"])
        section = sheet.split(f"<h2>{doc.id} ")[1].split("<h2>")[0]
        assert len(re.findall(r"<td>Risk \d+</td>", section)) == risks
        assert len(re.findall(r"<td>Obligation \d+</td>", section)) == obligations
    assert "developer_only" in sheet and "SYNTHETIC" in sheet


def test_document_text_is_escaped_never_injected_into_the_page(built):
    sheet = built[2]["01_dataset_labels_review.html"]
    assert "&lt;&lt;SYSTEM&gt;&gt;" in sheet and "<<SYSTEM>>" not in sheet


def test_each_playbook_is_shown_whole_with_its_official_text(built):
    review = built[2]["02_playbooks_review.html"]
    for pid in ("tenancy_punjab", "nda"):
        raw = (playbook_engine.PLAYBOOK_DIR / f"{pid}.yaml").read_text(encoding="utf-8")
        first_check = re.search(r"^\s*- id: (\S+)", raw, re.M).group(1)
        assert first_check in review
    employment = next(p for p in playbook_engine.load_packs() if p.id == "employment")
    assert employment.content_hash not in review and "Sign-off: playbook employment" not in review
    assert "Punjab Code, Government of the Punjab" in review and "authority_status" not in review
    assert "does not confirm that no later amendment exists" in review


def test_the_employment_request_marks_its_list_as_unverified(built):
    request = built[2]["03_employment_coverage_request.html"]
    assert "employment.no_employment_statute" in request and "NOT verified" in request
    assert "Please do not approve the current employment playbook" in request
    assert "not a playbook approval" in request
    for name, found in package.EMPLOYMENT_CANDIDATES:
        assert package.esc(name) in request and package.esc(found) in request
    # Both AI reviews: this title could not be verified; it is flagged, never relied on.
    flagged = dict(package.EMPLOYMENT_CANDIDATES)["Punjab Terms of Employment (Standing Orders) Act, 2012"]
    assert flagged.startswith("unable_to_verify")
    assert "public servants" in request


def test_the_script_refuses_to_write_inside_the_repository(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["analyzer_review_package.py", "--out", str(BACKEND / "review_out")])
    assert package.main() == 2
    assert "outside the repository" in capsys.readouterr().out
    assert not (BACKEND / "review_out").exists()


def test_the_employment_request_offers_decisions_never_an_approval(built):
    request = built[2]["03_employment_coverage_request.html"]
    decision = re.search(r"<th>Decision \(([^)]*)\)</th>", request).group(1)
    assert decision.split(" / ") == ["coverage_decision_complete", "changes_requested",
                                     "unable_to_determine", "specialist_review_required"]
    assert "approve" not in decision


def test_footnotes_are_shown_apart_from_the_section_text(built):
    review = built[2]["02_playbooks_review.html"]
    s28 = review.split("Contract Act 1872, s.28")[1].split("<h3>")[0]
    text = s28.split("<pre>")[1].split("</pre>")[0]
    assert "Partnership Act" not in text
    assert "Publisher's footnotes" in s28 and "Specific Relief Act" in s28
    assert "marker not in the section text" in review          # Registration Act footnote 2
    assert "Notes SHA-256" in review


def test_open_questions_are_put_to_the_reviewer_not_applied(built):
    review, sheet = built[2]["02_playbooks_review.html"], built[2]["01_dataset_labels_review.html"]
    assert "now cut from the PUNJAB Code" in review and "s.1(3)" in review
    assert "sections 2-3 of the Punjab Rented Premises Act" in review
    for asked in package.DATASET_POLICY_QUESTIONS:
        assert package.esc(asked) in sheet
    for change in package.DATASET_CHANGES:
        assert package.esc(change) in sheet
    assert "particulars to be sufficient" in review
    assert "Non-solicitation" in review
    for doc_id, asked in package.DATASET_QUESTIONS.items():
        section = sheet.split(f"<h2>{doc_id} ")[1].split("<h2>")[0]
        assert "not applied" in section
        for q in asked:
            assert package.esc(q) in section
    assert "party: Each Party" in sheet and "party: party;" not in sheet


def test_a_rebuilt_package_names_the_one_it_supersedes(tmp_path):
    old = "bcfe238d85079440eb0089f36d62c16db5d625a05a3cc355a1b5a983f209aa3f"
    manifest = package.build(tmp_path, generated="2026-10-02", supersedes=old)
    assert manifest["supersedes"] == {"zip_sha256": old}
    assert manifest["review_status"] == {"lawyer_reviewed": False, "legal_pack_approved": False}
    for name in manifest["files"]:
        assert old in (tmp_path / name).read_text(encoding="utf-8")
    with pytest.raises(ValueError, match="64 hex"):
        package.build(tmp_path, supersedes="BCFE238D")
