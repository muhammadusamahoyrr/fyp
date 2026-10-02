"""Build the lawyer-review package for the Document Analyzer.

    python scripts/analyzer_review_package.py --out <directory outside the repository>

Writes four files for a qualified reviewer, each bound to exact hashes so an
approval names precisely what was read:

  01_dataset_labels_review.html   every evaluation document as numbered
                                  evidence units, its expected labels, a
                                  decision column per label and a sign-off
                                  for the dataset SHA-256
  02_playbooks_review.html        each legal playbook's exact text with its
                                  content_hash and authorities_hash, and the
                                  official text it cites (source, snapshot
                                  date, authority status, currency)
  03_employment_coverage_request.html
                                  the open employment-law release blocker
                                  and what the reviewer is asked to decide
  manifest.json                   SHA-256 of every file, the dataset hash,
                                  each pack's hashes, the commit, the date

Read-only on the repository; nothing here approves anything. Approvals of
playbooks happen in the application against the two hashes; approval of the
dataset labels is recorded by a reviewed commit to the evaluation record.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.services.analyzer import approvals, authorities, evaluation, playbook_engine  # noqa: E402

LEGAL_PACKS = ("tenancy_punjab", "nda", "employment")

#: Statute NAMES offered to the reviewer as a starting point for the
#: employment coverage decision. Not verified by the developer against any
#: official source; the reviewer confirms, rejects or replaces each.
EMPLOYMENT_CANDIDATES = (
    "Punjab Terms of Employment (Standing Orders) Act, 2012",
    "Industrial and Commercial Employment (Standing Orders) Ordinance, 1968",
    "Punjab Shops and Establishments Ordinance, 1969",
    "Payment of Wages Act, 1936",
    "Punjab Minimum Wages Act, 2019",
    "Punjab Industrial Relations Act, 2010",
    "Employees' Old-Age Benefits Act, 1976",
    "Punjab Employees Social Security Ordinance, 1965",
    "Factories Act, 1934",
)

CSS = """
body{font-family:Georgia,'Times New Roman',serif;max-width:960px;margin:24px auto;padding:0 16px;color:#111;line-height:1.5}
h1{font-size:22px}h2{font-size:18px;border-top:2px solid #333;padding-top:12px;margin-top:32px}h3{font-size:15px}
code,pre{font-family:Consolas,monospace;font-size:12.5px}pre{white-space:pre-wrap;background:#f6f6f6;padding:10px;border:1px solid #ddd}
table{border-collapse:collapse;width:100%;margin:8px 0}td,th{border:1px solid #999;padding:5px 7px;vertical-align:top;font-size:13.5px}
th{background:#eee;text-align:left}.unit{font-family:Consolas,monospace;color:#555}.note{background:#fff8e1;border:1px solid #e0c060;padding:8px 12px}
.sign td{height:34px}@media print{h2{page-break-before:always}}
"""


def esc(value) -> str:
    return html.escape("" if value is None else str(value))


def page(title: str, body: str, generated: str) -> str:
    return (f"<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
            f"<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
            f"<title>{esc(title)}</title><style>{CSS}</style></head><body>"
            f"<h1>{esc(title)}</h1><p>Generated {esc(generated)} from the Attorney.AI repository.</p>"
            f"{body}</body></html>\n")


def sign_off(subject: str, bound_to: str) -> str:
    rows = "".join(f"<tr><th>{label}</th><td></td></tr>" for label in (
        "Reviewer name", "Qualification / enrolment no.", "Decision (approve / approve with changes / reject)",
        "Date", "Signature"))
    return (f"<h2>Sign-off: {esc(subject)}</h2><p>This sign-off applies only to the exact version "
            f"identified by <code>{esc(bound_to)}</code>. Any later change produces a new hash and needs "
            f"a new review.</p><table class=\"sign\">{rows}</table>")


# ── 1. dataset labels ────────────────────────────────────────────────────────

def dataset_review(dataset, generated: str) -> str:
    parts = [
        "<div class=\"note\"><p><b>What you are asked to review.</b> These 30 documents are SYNTHETIC "
        "(written for this test set; no real party or document). For each, the developer labelled the "
        "general drafting points a careful reader should notice and the obligations the document states. "
        "Please mark each label <i>approve</i>, <i>change</i> (say how) or <i>remove</i>, and list anything "
        "missing. The labels describe drafting points only; none says what the law requires.</p>"
        "<p>Labels are currently <b>developer_only</b>. They become <b>lawyer_reviewed</b> only through "
        "your signed decision, recorded with your name and the date.</p></div>",
        f"<p>Dataset <b>{esc(dataset.version)}</b>, SHA-256 <code>{esc(dataset.sha256)}</code>, "
        f"{len(dataset.documents)} documents.</p>"]
    for doc in dataset.documents:
        evaluation.prepare(doc)
        units = "".join(
            f"<tr><td class=\"unit\">{esc(u['sentence_id'])}</td><td>{esc(doc.text[u['start']:u['end']])}</td></tr>"
            for u in doc.rows)
        labels = []
        for n, r in enumerate(doc.expected["risks"], 1):
            labels.append(f"<tr><td>Risk {n}</td><td>{esc(r.get('category') or 'other_drafting')}</td>"
                          f"<td>{esc(', '.join(r['sentence_ids']))}</td><td></td><td></td></tr>")
        for n, o in enumerate(doc.expected["obligations"], 1):
            detail = f"party: {o['party']}; deadline: {o.get('deadline') or 'not stated'}"
            labels.append(f"<tr><td>Obligation {n}</td><td>{esc(detail)}</td>"
                          f"<td>{esc(', '.join(o['sentence_ids']))}</td><td></td><td></td></tr>")
        if not labels:
            labels.append("<tr><td colspan=\"5\">No drafting points or obligations labelled.</td></tr>")
        injection = (f"<p><b>Malicious variant:</b> the document embeds an instruction aimed at the AI, "
                     f"marked by the canary <code>{esc(doc.canary)}</code>. It is a test of the AI, "
                     f"not a drafting point.</p>" if doc.canary else "")
        parts.append(
            f"<h2>{esc(doc.id)} &middot; {esc(doc.document_type)} &middot; {esc(doc.variant)}</h2>"
            f"<p>Document SHA-256 <code>{esc(doc.sha256)}</code></p>{injection}"
            f"<h3>Text, as numbered evidence units</h3><table><tr><th>Unit</th><th>Text</th></tr>{units}</table>"
            f"<h3>Expected labels</h3><table><tr><th>Label</th><th>Category / detail</th><th>Evidence units</th>"
            f"<th>Decision</th><th>Your note</th></tr>{''.join(labels)}</table>"
            f"<p>Missing items: ______________________________________________</p>")
    parts.append(sign_off("evaluation dataset labels", f"dataset {dataset.version} sha256 {dataset.sha256}"))
    return page("Evaluation dataset: label review", "".join(parts), generated)


# ── 2. legal playbooks ───────────────────────────────────────────────────────

def playbook_review(packs: list[dict], authority: dict, generated: str) -> str:
    parts = ["<div class=\"note\"><p><b>What you are asked to review.</b> Each legal playbook below runs "
             "only after a qualified reviewer approves its EXACT text and the EXACT official text it cites. "
             "An approval in the application quotes both hashes shown here; editing either the playbook or "
             "the cited text changes a hash and the approval stops counting. Until then the application "
             "reports each pack as awaiting approval and does not run it.</p></div>"]
    for pack in packs:
        cited = []
        for c in pack["cited_provisions"]:
            src = c["source"]
            cited.append(
                f"<h3>{esc(c['statute'])}, s.{esc(c['section'])} &mdash; {esc(c['heading'])}</h3>"
                f"<table><tr><th>Source</th><td>{esc(src['publisher'])}, pages {esc(', '.join(map(str, c['pages'])))}"
                f"<br><a href=\"{esc(src['url'])}\">{esc(src['url'])}</a></td></tr>"
                f"<tr><th>Authority status</th><td>{esc(src['authority_status'])}</td></tr>"
                f"<tr><th>Snapshot date</th><td>{esc(src['snapshot_date'])}; amended up to: "
                f"{esc(src['amended_up_to'] or 'not stated by the source')}</td></tr>"
                f"<tr><th>Currency</th><td>{esc(src['currency']['status'])}"
                f"{(' (checked ' + esc(src['currency']['last_checked']) + ')') if src['currency']['last_checked'] else ''}"
                f"<br><i>{esc(src['currency']['caveat'])}</i></td></tr>"
                f"<tr><th>Text SHA-256</th><td><code>{esc(c['text_sha256'])}</code></td></tr></table>"
                f"<pre>{esc(c['text'])}</pre>")
        parts.append(
            f"<h2>{esc(pack['id'])} (version {esc(pack['version'])})</h2>"
            f"<table><tr><th>Required qualification</th><td><code>{esc(pack['required_qualification'])}</code></td></tr>"
            f"<tr><th>content_hash</th><td><code>{esc(pack['content_hash'])}</code></td></tr>"
            f"<tr><th>authorities_hash</th><td><code>{esc(pack['authorities_hash'])}</code></td></tr></table>"
            f"<h3>Playbook text (exactly as it runs)</h3><pre>{esc(pack['text'])}</pre>"
            f"<h3>Official text it cites</h3>{''.join(cited)}"
            + sign_off(f"playbook {pack['id']}",
                       f"content_hash {pack['content_hash']} + authorities_hash {pack['authorities_hash']}"))
    gaps = "".join(
        f"<tr><td>{esc(t)}</td><td>{esc(g['id'])}</td><td>{esc(g['text'])}</td>"
        f"<td>{'yes' if g['release_blocker'] else 'no'}</td></tr>"
        for t, entry in authority["coverage"].items() for g in entry["gaps"])
    parts.append(f"<h2>Known coverage gaps</h2><table><tr><th>Type</th><th>Gap</th><th>Description</th>"
                 f"<th>Release blocker</th></tr>{gaps}</table>")
    return page("Legal playbooks: review for approval", "".join(parts), generated)


# ── 3. employment coverage ───────────────────────────────────────────────────

def employment_request(employment: dict, authority: dict, generated: str) -> str:
    blocker = next(g for g in authority["coverage"]["employment"]["gaps"] if g["release_blocker"])
    cited = ", ".join(f"{c['statute']} s.{c['section']}" for c in employment["cited_provisions"])
    candidates = "".join(f"<tr><td>{esc(name)}</td><td></td><td></td><td></td></tr>"
                         for name in EMPLOYMENT_CANDIDATES)
    body = (
        f"<div class=\"note\"><p><b>Open release blocker</b> <code>{esc(blocker['id'])}</code>: "
        f"{esc(blocker['text'])}</p></div>"
        f"<p>The employment playbook (content_hash <code>{esc(employment['content_hash'])}</code>) currently "
        f"cites only: {esc(cited)}. No employment statute's text is in the authority library, so the "
        f"employment legal checklist cannot be released, whatever the AI layer does.</p>"
        "<h2>What we ask you to decide</h2><ol>"
        "<li>Which statutes and exact provisions should the library hold for employment agreements and "
        "offer letters, and for which province(s) or federal territory?</li>"
        "<li>For each, the official publication to cut the text from (Punjab Code, Pakistan Code or the "
        "relevant official gazette).</li>"
        "<li>Which checks the employment playbook should make against them, and which conditions decide "
        "whether a check applies.</li></ol>"
        "<p>We will then cut the exact text from the official source with a pinned file hash, rebuild the "
        "library and the playbook, and send them back to you with their new content_hash and "
        "authorities_hash for approval. Nothing is added on the developer's own reading of the law.</p>"
        "<h2>Starting list (names only, NOT verified)</h2>"
        "<p>The developer has not checked these names, their current status or their applicability against "
        "any official source. Please confirm, reject or replace each, and add what is missing.</p>"
        "<table><tr><th>Statute (as named by the developer)</th><th>Include? (yes / no)</th>"
        f"<th>Provisions</th><th>Official source</th></tr>{candidates}"
        "<tr><td>Other: ______________________</td><td></td><td></td><td></td></tr></table>"
        + sign_off("employment coverage decision", f"employment playbook content_hash {employment['content_hash']}"))
    return page("Employment law coverage: request for a decision", body, generated)


# ── the package ──────────────────────────────────────────────────────────────

def _commit() -> str | None:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=BACKEND, capture_output=True, text=True,
                              timeout=20).stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def build(out: Path, generated: str | None = None) -> dict:
    generated = generated or date.today().isoformat()
    out.mkdir(parents=True, exist_ok=True)
    dataset = evaluation.load_dataset()
    packs = [approvals.playbook_text(pid) for pid in LEGAL_PACKS]
    authority = authorities.current_metadata()
    files = {
        "01_dataset_labels_review.html": dataset_review(dataset, generated),
        "02_playbooks_review.html": playbook_review(packs, authority, generated),
        "03_employment_coverage_request.html": employment_request(packs[-1], authority, generated),
    }
    for name, content in files.items():
        (out / name).write_text(content, encoding="utf-8", newline="\n")
    manifest = {
        "generated": generated, "commit": _commit(),
        "dataset": {"version": dataset.version, "sha256": dataset.sha256, "documents": len(dataset.documents)},
        "playbooks": {p["id"]: {"version": p["version"], "content_hash": p["content_hash"],
                                "authorities_hash": p["authorities_hash"],
                                "required_qualification": p["required_qualification"]} for p in packs},
        "release_blockers": [b["id"] for b in authority["release_blockers"]],
        "files": {name: hashlib.sha256(content.encode("utf-8")).hexdigest() for name, content in files.items()},
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8", newline="\n")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    if args.out.resolve().is_relative_to(BACKEND.parent.resolve()):
        print("REFUSED: write the package outside the repository")
        return 2
    manifest = build(args.out)
    for name, digest in manifest["files"].items():
        print(f"{digest}  {name}")
    print(f"dataset {manifest['dataset']['sha256']}")
    for pid, p in manifest["playbooks"].items():
        print(f"{pid}: content {p['content_hash']}  authorities {p['authorities_hash']}")
    print(f"release blockers: {', '.join(manifest['release_blockers']) or 'none'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
