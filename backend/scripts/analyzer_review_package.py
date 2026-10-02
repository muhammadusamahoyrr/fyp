"""Build the lawyer-review package for the Document Analyzer.

    python scripts/analyzer_review_package.py --out <directory outside the repository>

Writes four files for a qualified reviewer, each bound to exact hashes so an
approval names precisely what was read:

  01_dataset_labels_review.html   every evaluation document as numbered
                                  evidence units, its expected labels, a
                                  decision column per label and a sign-off
                                  for the dataset SHA-256
  02_playbooks_review.html        the tenancy and NDA playbooks' exact text
                                  with their content_hash and authorities_hash,
                                  and the official text they cite (source,
                                  snapshot date, authority status, currency).
                                  The employment pack is NOT offered for
                                  approval until its coverage is decided.
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
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.services.analyzer import approvals, authorities, evaluation, playbook_engine  # noqa: E402

#: Packs offered for APPROVAL. The employment pack is deliberately not one:
#: its statutes, province and checks are decided first (the coverage
#: request), which changes its content and authorities hashes and needs a
#: new package. It appears only in the coverage request, marked not for
#: approval.
REVIEW_PACKS = ("tenancy_punjab", "nda")
NOT_FOR_APPROVAL = ("employment",)

#: Statute NAMES offered to the reviewer as a starting point for the
#: employment coverage decision, each with what two independent AI reviews
#: found on the official Punjab Code / Pakistan Code. The developer has NOT
#: verified any of it; the reviewer confirms, rejects or replaces each.
EMPLOYMENT_CANDIDATES = (
    ("Punjab Terms of Employment (Standing Orders) Act, 2012",
     "unable_to_verify: no Act of this title was found on the Punjab Code; the title matches "
     "Sindh's Terms of Employment (Standing Orders) Act. Do not rely on it."),
    ("Industrial and Commercial Employment (Standing Orders) Ordinance, 1968",
     "found on the Punjab Code; listed for repeal by the Punjab Labour Code 2026, s.435"),
    ("Punjab Shops and Establishments Ordinance, 1969",
     "title differs: the Punjab Code lists \"West Pakistan Shops and Establishments Ordinance, 1969\"; "
     "listed for repeal by the Punjab Labour Code 2026, s.435"),
    ("Payment of Wages Act, 1936",
     "found on the Punjab Code; listed for repeal by the Punjab Labour Code 2026, s.435"),
    ("Punjab Minimum Wages Act, 2019",
     "found on the Punjab Code; listed for repeal by the Punjab Labour Code 2026, s.435"),
    ("Punjab Industrial Relations Act, 2010",
     "found on the Punjab Code; listed for repeal by the Punjab Labour Code 2026, s.435"),
    ("Employees' Old-Age Benefits Act, 1976",
     "federal Act (Pakistan Code); its application in the Punjab after devolution is for you"),
    ("Punjab Employees Social Security Ordinance, 1965",
     "title differs: the Punjab Code lists \"Provincial Employees' Social Security Ordinance, 1965\""),
    ("Factories Act, 1934",
     "found on the Punjab Code; listed for repeal by the Punjab Labour Code 2026, s.435"),
    ("Punjab Labour Code 2026 (IX of 2026)",
     "NOT on the original list; found on the Punjab Code. It comes into force on a date notified "
     "in the Gazette (s.1(3)); no commencement notification was found. Its s.435 repeals six of "
     "the laws above once in force."),
)

#: Changes made to the dataset because two independent AI reviews (Codex and
#: Claude) agreed on them. Shown to the reviewer, who may still reverse them.
DATASET_CHANGES = (
    "employment-06 Obligation 2: deadline \"thirty days' notice\" became \"thirty days' notice "
    "before resigning\" (the full timing words of s4).",
    "tenancy-08: added one_sided_term on s3 (the Landlord alone may increase the rent), alongside "
    "the existing ambiguity label.",
    "tenancy-08: added an obligation on s4 (party Tenant, deadline not stated: \"the Tenant shall "
    "bear their cost\").",
    "nda-09: added one_sided_term on s5 (the duty lasts as long as the Discloser wishes), alongside "
    "the existing ambiguity label.",
)

#: Labelling-policy questions: the two AI reviews disagreed on 13 labels mostly
#: because no written rule settles these. Your answer becomes the guideline.
DATASET_POLICY_QUESTIONS = [
    "When a document states a duration or deadline only vaguely (\"promptly\", \"a reasonable "
    "period\", \"a suitable period\"), should the obligation's deadline read \"not stated\" (with "
    "the vagueness labelled as an ambiguity risk), or record the vague words as a stated but "
    "ambiguous deadline?",
    "When a duty and its duration are in different sentences (nda-01 s3 and s4), should the "
    "obligation cite both evidence units?",
    "How should something ABSENT from a document (no term, no date of execution) be labelled: "
    "on which evidence unit, and should it be labelled at all in documents not of the "
    "\"incomplete\" variant (tenancy-06 to -10 also state no term)?",
    "Should a missing-detail label say exactly what is missing (e.g. \"rent amount stated; due "
    "date and mode not stated\"), or is the category with its evidence unit enough?",
]

#: Points raised by one AI review only, or on which the two disagreed. NOT
#: applied: each is put to the reviewer as a question.
DATASET_QUESTIONS = {
    "tenancy-03": ["No date, place of execution or term is stated. Should these be labelled, and on "
                   "which unit (one review: s1 and s0-s1; the other: s2)?",
                   "Should Risks 1-3 say precisely what is missing (Risk 1: due date and mode; Risk 2: "
                   "notice length, form, effective date; Risk 3: deposit return and deductions)?"],
    "tenancy-04": ["No date and no term are stated. Should either be labelled, and on which unit?",
                   "Risk 1: should it say the premises lacks an identifying number or fuller address?"],
    "tenancy-08": ["Risk 3: should it say the amount and period are stated but no due date or mode is?"],
    "tenancy-10": ["Risk 2: should it say the amount and period are stated but no due date or mode is?"],
    "nda-01": ["Obligation 1: should it cite s3 and s4 and record the duration \"three years from the "
               "date of this Agreement\"?"],
    "nda-02": ["Obligation 1: should it cite s3 and s4 (two years after the tasting project ends)?",
               "Is the undefined end of \"the tasting project\" an ambiguity to label (s2, s4)?"],
    "nda-03": ["No duration of confidentiality is stated. Should that be labelled (s2, s3)?"],
    "nda-04": ["No duration of confidentiality is stated. Should that be labelled (s2, s4)?"],
    "nda-05": ["The only duty stated is not to copy marked documents (s4); there is no general duty of "
               "non-disclosure. Should that be labelled missing_detail?"],
    "nda-07": ["Obligation 1: is \"a reasonable period\" (s4) a stated but ambiguous duration, or "
               "\"not stated\"? (See policy question 1.)"],
    "nda-08": ["Obligation 1: is \"promptly\" a stated but ambiguous deadline, or \"not stated\"? "
               "(See policy question 1.)",
               "The agreement states no basic duty of confidentiality, only a permission to disclose "
               "(s2). Should that be labelled missing_detail?"],
    "nda-09": ["Obligation 1: should it cite s5 too, recording a duration controlled by the Discloser?"],
    "nda-10": ["s4 (liability to pay any amount the Company decides): should it also be an obligation "
               "on the Recipient?"],
    "employment-04": ["s4: only the Company may terminate. Is that also a one_sided_term, as in "
                      "employment-09 s5 and tenancy-10 s5?"],
    "employment-08": ["Risk 3 / s4: the post-employment restriction is labelled ambiguity. Should it "
                      "also be one_sided_term, and should the possible restraint-of-trade question be "
                      "noted (as a drafting point only)?",
                      "Obligation 2: is \"a suitable period\" a stated but ambiguous duration, or "
                      "\"not stated\"? (See policy question 1.)",
                      "s2 states no pay date (labelled missing_detail elsewhere, e.g. employment-04 s3). "
                      "Should it be labelled here?"],
    "employment-10": ["Obligation 1 rests on s4 (\"a salary to be decided later\"). Is that an "
                      "obligation, or only a missing detail?",
                      "s2 offers the role with no start date. Should that be labelled missing_detail, as "
                      "in employment-03?"],
}

#: Questions put to the reviewer of each legal playbook. Answers can change
#: the playbook or the cited text, and so its hashes: put them before approving.
PLAYBOOK_QUESTIONS = {
    "tenancy_punjab": [
        "Scope: the pack runs on any tenancy confirmed as in the Punjab. Which premises and "
        "relationships do sections 2-3 of the Punjab Rented Premises Act include or exclude, and "
        "should the pack ask about them before it runs? Are premises in a cantonment governed by "
        "this Act or another rent law?",
        "Section 6(1)(a) asks for \"particulars of the landlord and the tenant\". The check "
        "locates only identity-card, parentage or residence wording; a name alone is not located. "
        "What must an agreement state for its particulars to be sufficient? The check is "
        "deliberately left unchanged until you answer.",
        "The Registration Act s.17(1) and Transfer of Property Act ss.1 and 107 are now cut from "
        "the PUNJAB Code (as amended in the Punjab: TPA s.1 substituted by Punjab Act VIII of "
        "2011; Registration Act amended by Punjab Acts XIX of 2011, XXVI of 2018 and XL of 2026), "
        "not from Pakistan Code. Is this the text in force? Which notifications under TPA s.1(3) "
        "and (4), and orders under the proviso to s.17(1), are in force, and where does s.107 "
        "operate in the Punjab (the publisher's footnote: municipalities, notified areas and "
        "cantonments; s.1(5))?",
        "Registration reminders: is a lease from year to year, or one \"reserving a yearly rent\", "
        "correctly told apart from a monthly rent quoted as an annual total? Is a term of exactly "
        "12 months correctly treated as not exceeding one year?",
        "Should the Rent Registrar reminder also mention s.5(6) (later agreements must also be "
        "presented) and the s.9 consequence of a tenancy that does not conform (not held in the "
        "library)?",
        "Stamp duty (Stamp Act 1899 and the Punjab finance laws) is not held. Should it be, and "
        "from which official text?",
        "s6_bank_particulars is a reminder shown on every Punjab tenancy. Should it instead show "
        "only when the agreement provides for payment through a bank?",
        "A footnote marked \"marker not in the section text\" is shown because it bears on the "
        "section although its marker is elsewhere -- here the Transfer of Property Act's title "
        "footnote, which records the Act's extent. Please confirm it.",
        "The locators were tightened after two AI reviews: a duration counts as the term unless "
        "it is a notice period; deposits and ages no longer count as the term; due date, mode, "
        "purpose and deposit checks need rent or letting context. Are these the right limits?",
    ],
    "nda": [
        "Non-solicitation and wording such as \"not disclose to any competitor\" are no longer "
        "located by non_compete_restraint: only wording restraining the carrying on of a trade or "
        "business is. Should a non-solicitation clause be raised to the user, and if so how?",
        "How does s.27 apply to a restraint that runs during the relationship compared with one "
        "after it ends, and to an NDA governed by a foreign law? Should this pack run only when "
        "Pakistani law governs the agreement?",
        "Under s.28, how should absolute bars, exclusive-jurisdiction (forum) clauses, arbitration "
        "clauses, claim-notification periods and contractual limitation periods be told apart?",
        "The s.28 text includes the paragraph \"Suits barred by such Contracts\", which the "
        "publisher's footnote says was repealed by the Specific Relief Act 1877. Should it be "
        "shown at all?",
        "duration_of_confidentiality is a drafting point, not a statutory one. Should it move out "
        "of this legal pack into the general drafting checks?",
    ],
}

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


def page(title: str, body: str, generated: str, supersedes: str | None = None) -> str:
    replaces = (f"<div class=\"note\"><p>This package replaces the earlier package whose ZIP SHA-256 is "
                f"<code>{esc(supersedes)}</code>. That package is superseded and must not be used.</p></div>"
                if supersedes else "")
    return (f"<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
            f"<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
            f"<title>{esc(title)}</title><style>{CSS}</style></head><body>"
            f"<h1>{esc(title)}</h1><p>Generated {esc(generated)} from the Attorney.AI repository.</p>"
            f"{replaces}{body}</body></html>\n")


APPROVAL_DECISIONS = ("approve", "approve with changes", "reject")
#: A coverage request asks for a DECISION, not an approval: nothing in it can
#: be approved, so "approve" is never offered.
COVERAGE_DECISIONS = ("coverage_decision_complete", "changes_requested", "unable_to_determine",
                      "specialist_review_required")


def questions(items: list[str]) -> str:
    rows = "".join(f"<tr><td>Q{n}</td><td>{esc(q)}</td><td></td></tr>" for n, q in enumerate(items, 1))
    return f"<table><tr><th>#</th><th>Question</th><th>Your answer</th></tr>{rows}</table>"


def sign_off(subject: str, bound_to: str, decisions: tuple[str, ...] = APPROVAL_DECISIONS) -> str:
    rows = "".join(f"<tr><th>{esc(label)}</th><td></td></tr>" for label in (
        "Reviewer name", "Qualification / enrolment no.", f"Decision ({' / '.join(decisions)})",
        "Date", "Signature"))
    return (f"<h2>Sign-off: {esc(subject)}</h2><p>This sign-off applies only to the exact version "
            f"identified by <code>{esc(bound_to)}</code>. Any later change produces a new hash and needs "
            f"a new review.</p><table class=\"sign\">{rows}</table>")


# ── 1. dataset labels ────────────────────────────────────────────────────────

def dataset_review(dataset, generated: str, supersedes: str | None = None) -> str:
    parts = [
        "<div class=\"note\"><p><b>What you are asked to review.</b> These 30 documents are SYNTHETIC "
        "(written for this test set; no real party or document). For each, the developer labelled the "
        "general drafting points a careful reader should notice and the obligations the document states. "
        "Please mark each label <i>approve</i>, <i>change</i> (say how) or <i>remove</i>, and list anything "
        "missing. The labels describe drafting points only; none says what the law requires.</p>"
        "<p>Labels are currently <b>developer_only</b>. They become <b>lawyer_reviewed</b> only through "
        "your signed decision, recorded with your name and the date.</p></div>",
        f"<p>Dataset <b>{esc(dataset.version)}</b>, SHA-256 <code>{esc(dataset.sha256)}</code>, "
        f"{len(dataset.documents)} documents.</p>",
        "<h2>Changed after two independent AI reviews</h2><p>Both reviews (Codex and Claude) agreed on "
        "these, so they were applied. You may reverse any of them.</p><ul>"
        + "".join(f"<li>{esc(c)}</li>" for c in DATASET_CHANGES) + "</ul>",
        "<h2>Labelling policy: please decide first</h2><p>The two AI reviews disagreed on 13 labels, "
        "mostly because no written rule settles these points. Your answers become the labelling "
        "guideline.</p>" + questions(DATASET_POLICY_QUESTIONS)]
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
        asked = (f"<h3>Questions for you (raised by one AI review, or disputed between the two; not applied)</h3>"
                 f"{questions(DATASET_QUESTIONS[doc.id])}" if doc.id in DATASET_QUESTIONS else "")
        injection = (f"<p><b>Malicious variant:</b> the document embeds an instruction aimed at the AI, "
                     f"marked by the canary <code>{esc(doc.canary)}</code>. It is a test of the AI, "
                     f"not a drafting point.</p>" if doc.canary else "")
        parts.append(
            f"<h2>{esc(doc.id)} &middot; {esc(doc.document_type)} &middot; {esc(doc.variant)}</h2>"
            f"<p>Document SHA-256 <code>{esc(doc.sha256)}</code></p>{injection}"
            f"<h3>Text, as numbered evidence units</h3><table><tr><th>Unit</th><th>Text</th></tr>{units}</table>"
            f"<h3>Expected labels</h3><table><tr><th>Label</th><th>Category / detail</th><th>Evidence units</th>"
            f"<th>Decision</th><th>Your note</th></tr>{''.join(labels)}</table>{asked}"
            f"<p>Missing items: ______________________________________________</p>")
    parts.append(sign_off("evaluation dataset labels", f"dataset {dataset.version} sha256 {dataset.sha256}"))
    return page("Evaluation dataset: label review", "".join(parts), generated, supersedes)


# ── 2. legal playbooks ───────────────────────────────────────────────────────

def footnotes(notes: list[dict]) -> str:
    """The publisher's footnotes, shown apart from the section: they are
    editorial notes (amendment history, extent), not the enacted text."""
    if not notes:
        return ""
    rows = "".join(
        f"<tr><td>p.{esc(n['page'])}, footnote {esc(n['marker'])}"
        f"{'' if n['marker_in_text'] else '<br><i>marker not in the section text</i>'}</td>"
        f"<td>{esc(n['text'])}</td></tr>" for n in notes)
    return ("<p><b>Publisher's footnotes</b> (editorial notes printed with the official text; "
            "not part of the section):</p>"
            f"<table><tr><th>Where</th><th>Note</th></tr>{rows}</table>")

def playbook_review(packs: list[dict], authority: dict, generated: str,
                    supersedes: str | None = None) -> str:
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
                f"<tr><th>Text SHA-256</th><td><code>{esc(c['text_sha256'])}</code></td></tr>"
                + (f"<tr><th>Notes SHA-256</th><td><code>{esc(c['notes_sha256'])}</code></td></tr>"
                   if c["notes"] else "")
                + f"</table><pre>{esc(c['text'])}</pre>" + footnotes(c["notes"]))
        parts.append(
            f"<h2>{esc(pack['id'])} (version {esc(pack['version'])})</h2>"
            f"<table><tr><th>Required qualification</th><td><code>{esc(pack['required_qualification'])}</code></td></tr>"
            f"<tr><th>content_hash</th><td><code>{esc(pack['content_hash'])}</code></td></tr>"
            f"<tr><th>authorities_hash</th><td><code>{esc(pack['authorities_hash'])}</code></td></tr></table>"
            f"<h3>Playbook text (exactly as it runs)</h3><pre>{esc(pack['text'])}</pre>"
            f"<h3>Official text it cites</h3>{''.join(cited)}"
            + (f"<h3>Questions for you before approving</h3>{questions(PLAYBOOK_QUESTIONS[pack['id']])}"
               if pack["id"] in PLAYBOOK_QUESTIONS else "")
            + sign_off(f"playbook {pack['id']}",
                       f"content_hash {pack['content_hash']} + authorities_hash {pack['authorities_hash']}"))
    gaps = "".join(
        f"<tr><td>{esc(t)}</td><td>{esc(g['id'])}</td><td>{esc(g['text'])}</td>"
        f"<td>{'yes' if g['release_blocker'] else 'no'}</td></tr>"
        for t, entry in authority["coverage"].items() for g in entry["gaps"])
    parts.append(f"<h2>Known coverage gaps</h2><table><tr><th>Type</th><th>Gap</th><th>Description</th>"
                 f"<th>Release blocker</th></tr>{gaps}</table>")
    return page("Legal playbooks: review for approval", "".join(parts), generated, supersedes)


# ── 3. employment coverage ───────────────────────────────────────────────────

def employment_request(employment: dict, authority: dict, generated: str,
                       supersedes: str | None = None) -> str:
    blocker = next(g for g in authority["coverage"]["employment"]["gaps"] if g["release_blocker"])
    cited = ", ".join(f"{c['statute']} s.{c['section']}" for c in employment["cited_provisions"])
    candidates = "".join(f"<tr><td>{esc(name)}</td><td><i>{esc(found)}</i></td><td></td><td></td><td></td></tr>"
                         for name, found in EMPLOYMENT_CANDIDATES)
    body = (
        f"<div class=\"note\"><p><b>Open release blocker</b> <code>{esc(blocker['id'])}</code>: "
        f"{esc(blocker['text'])}</p></div>"
        f"<p>The current employment playbook (content_hash <code>{esc(employment['content_hash'])}</code>) "
        f"cites only: {esc(cited)}. No employment statute's text is in the authority library, so the "
        f"employment legal checklist cannot be released, whatever the AI layer does.</p>"
        "<div class=\"note\"><p><b>Please do not approve the current employment playbook.</b> It is "
        "shown for context only. Once you decide the statutes, province and checks below, the playbook "
        "and its cited text change, its hashes change, and a new review package is sent for approval."
        "</p></div>"
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
        "any official source. Two independent AI reviews checked them against the Punjab Code and Pakistan "
        "Code; what they found is shown, NOT verified. Please confirm, reject or replace each, and add what "
        "is missing.</p>"
        "<table><tr><th>Statute (as named by the developer)</th><th>What the AI reviews found (unverified)</th>"
        f"<th>Include? (yes / no)</th><th>Provisions</th><th>Official source</th></tr>{candidates}"
        "<tr><td>Other: ______________________</td><td></td><td></td><td></td><td></td></tr></table>"
        "<h2>Further questions</h2>"
        + questions(["Which jurisdictions (Punjab, other provinces, Islamabad Capital Territory) and which "
                     "private-sector categories belong in the first employment checklist?",
                     "Which categories must be excluded from a generic private-employment checklist "
                     "(e.g. public servants and other statutory service regimes)?",
                     "Is the Punjab Labour Code 2026 in force, and from what date?"])
        + sign_off("employment coverage decision (not a playbook approval)",
                   f"coverage request for employment playbook content_hash {employment['content_hash']}",
                   COVERAGE_DECISIONS))
    return page("Employment law coverage: request for a decision", body, generated, supersedes)


# ── the package ──────────────────────────────────────────────────────────────

def _commit() -> str | None:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=BACKEND, capture_output=True, text=True,
                              timeout=20).stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def _uncommitted() -> bool | None:
    """True when tracked files differ from the commit: the package then
    does NOT reproduce from `commit` alone, and the manifest says so."""
    try:
        status = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=BACKEND,
                                capture_output=True, text=True, timeout=20)
        return bool(status.stdout.strip()) if status.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def build(out: Path, generated: str | None = None, supersedes: str | None = None) -> dict:
    generated = generated or date.today().isoformat()
    if supersedes is not None and not re.fullmatch(r"[0-9a-f]{64}", supersedes):
        raise ValueError("supersedes must be the earlier package's ZIP SHA-256 (64 hex digits)")
    out.mkdir(parents=True, exist_ok=True)
    dataset = evaluation.load_dataset()
    unknown = set(DATASET_QUESTIONS) - {d.id for d in dataset.documents}
    if unknown:
        raise ValueError(f"questions for documents not in the dataset: {sorted(unknown)}")
    packs = [approvals.playbook_text(pid) for pid in REVIEW_PACKS]
    employment = approvals.playbook_text("employment")
    authority = authorities.current_metadata()
    files = {
        "01_dataset_labels_review.html": dataset_review(dataset, generated, supersedes),
        "02_playbooks_review.html": playbook_review(packs, authority, generated, supersedes),
        "03_employment_coverage_request.html": employment_request(employment, authority, generated,
                                                                  supersedes),
    }
    for name, content in files.items():
        (out / name).write_text(content, encoding="utf-8", newline="\n")
    manifest = {
        "generated": generated, "commit": _commit(), "uncommitted_changes": _uncommitted(),
        "review_status": {"lawyer_reviewed": False, "legal_pack_approved": False},
        "supersedes": {"zip_sha256": supersedes} if supersedes else None,
        "dataset": {"version": dataset.version, "sha256": dataset.sha256, "documents": len(dataset.documents)},
        "playbooks": {p["id"]: {"version": p["version"], "content_hash": p["content_hash"],
                                "authorities_hash": p["authorities_hash"],
                                "required_qualification": p["required_qualification"]} for p in packs},
        "not_for_approval": {"employment": {"content_hash": employment["content_hash"],
                                            "authorities_hash": employment["authorities_hash"],
                                            "reason": "coverage decision pending"}},
        "release_blockers": [b["id"] for b in authority["release_blockers"]],
        "files": {name: hashlib.sha256(content.encode("utf-8")).hexdigest() for name, content in files.items()},
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8", newline="\n")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--supersedes", help="ZIP SHA-256 of the package this one replaces")
    args = parser.parse_args()
    if args.out.resolve().is_relative_to(BACKEND.parent.resolve()):
        print("REFUSED: write the package outside the repository")
        return 2
    manifest = build(args.out, supersedes=args.supersedes.lower() if args.supersedes else None)
    for name, digest in manifest["files"].items():
        print(f"{digest}  {name}")
    print(f"dataset {manifest['dataset']['sha256']}")
    for pid, p in manifest["playbooks"].items():
        print(f"{pid}: content {p['content_hash']}  authorities {p['authorities_hash']}")
    print(f"release blockers: {', '.join(manifest['release_blockers']) or 'none'}")
    if manifest["uncommitted_changes"] is not False:
        print(f"WARNING: built from uncommitted changes on top of {manifest['commit']}; "
              "commit and rebuild before sending")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
