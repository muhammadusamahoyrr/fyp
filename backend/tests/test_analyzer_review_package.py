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
    assert set(manifest["playbooks"]) == {"tenancy_punjab", "nda", "employment"}
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
    for pid in ("tenancy_punjab", "nda", "employment"):
        raw = (playbook_engine.PLAYBOOK_DIR / f"{pid}.yaml").read_text(encoding="utf-8")
        first_check = re.search(r"^\s*- id: (\S+)", raw, re.M).group(1)
        assert first_check in review
    assert "Punjab Code, Government of the Punjab" in review and "authority_status" not in review
    assert "does not confirm that no later amendment exists" in review


def test_the_employment_request_marks_its_list_as_unverified(built):
    request = built[2]["03_employment_coverage_request.html"]
    assert "employment.no_employment_statute" in request and "NOT verified" in request
    for name in package.EMPLOYMENT_CANDIDATES:
        assert package.esc(name) in request


def test_the_script_refuses_to_write_inside_the_repository(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["analyzer_review_package.py", "--out", str(BACKEND / "review_out")])
    assert package.main() == 2
    assert "outside the repository" in capsys.readouterr().out
    assert not (BACKEND / "review_out").exists()
