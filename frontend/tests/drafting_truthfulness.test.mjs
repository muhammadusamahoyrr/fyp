/* Drafting: what the final screens and the lawyer catalogue claim.
 *
 * Three things here said more than the product had done:
 *
 *   1. Both final screens printed "Compliance ✓ Verified" on every document,
 *      whatever `pleading_rules` found — including templates it never checks
 *      and pleadings missing required particulars.
 *   2. The lawyer's final screen offered PDF / Download / Email / Print buttons
 *      with no handlers, and dated the approval with today's date.
 *   3. The lawyer drafter advertised fourteen document types; twelve opened
 *      the same generic court-petition scaffold under a different title.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import { complianceSummary } from "../src/lib/complianceSummary.js";
import { restoreStateFromDocument } from "../src/lib/documentResume.js";
import {
    TEMPLATES, CATEGORIES, BLANK_TEMPLATE, buildContent,
} from "../src/lib/lawyerDraftTemplates.js";

const read = (p) => readFileSync(new URL(p, import.meta.url), "utf8");
const clientPage = read("../src/components/client/ModDocuments.jsx");
const lawyerPage = read("../src/components/lawyer/DocumentsPage.jsx");

/* ── complianceSummary ─────────────────────────────────────────────────── */

test("an unchecked document is 'Not checked', never a pass", () => {
    for (const c of [null, undefined, {}, { checked: false }, { checked: false, complete: true }]) {
        assert.deepEqual(complianceSummary(c), { label: "Not checked", tone: "neutral" });
    }
});

test("a checked, complete document is 'Complete'", () => {
    assert.deepEqual(complianceSummary({ checked: true, complete: true, missing: 0 }),
                     { label: "Complete", tone: "success" });
});

test("missing particulars are counted", () => {
    assert.equal(complianceSummary({ checked: true, complete: false, missing: 1 }).label,
                 "Missing 1 particular");
    assert.equal(complianceSummary({ checked: true, complete: false, missing: 3 }).label,
                 "Missing 3 particulars");
    assert.equal(complianceSummary({ checked: true, complete: false, missing: 3 }).tone, "warn");
});

test("checked-but-incomplete without a count is not rounded up to a pass", () => {
    assert.deepEqual(complianceSummary({ checked: true, complete: false }),
                     { label: "Incomplete", tone: "warn" });
});

test("no summary ever uses the word 'Verified'", () => {
    const inputs = [null, { checked: false }, { checked: true, complete: true },
                    { checked: true, complete: false, missing: 2 }, { checked: true }];
    for (const c of inputs) assert.doesNotMatch(complianceSummary(c).label, /verif/i);
});

/* ── the final screens ─────────────────────────────────────────────────── */

test("neither final screen hardcodes a compliance verdict", () => {
    // As a string literal or JSX text — a comment recording the old lie is fine.
    for (const src of [clientPage, lawyerPage]) {
        assert.doesNotMatch(src, /["'`>]\s*✓ Verified/);
        assert.match(src, /complianceSummary\(/);
    }
});

function screenFinal() {
    const start = lawyerPage.indexOf("function ScreenFinal(");
    assert.ok(start > 0);
    return lawyerPage.slice(start, lawyerPage.indexOf("\nfunction ", start + 10));
}

test("the lawyer final screen offers only the export that works", () => {
    const body = screenFinal();
    assert.doesNotMatch(body, /"Email"|"Print"|"PDF"\]/);
    assert.match(body, /downloadDocumentFile\(doc\.id/);
    assert.match(body, /revisionId: doc\.viewRevisionId/);
    assert.match(body, /expectedPdfSha256: doc\.viewPdfSha256/);
    // Every button on the screen does something.
    const buttons = body.match(/<button\b[^>]*>/g) || [];
    for (const b of buttons) assert.match(b, /onClick=/, `inert button: ${b}`);
});

test("the approval date is the recorded one, not today's", () => {
    const body = screenFinal();
    assert.doesNotMatch(body, /new Date\(\)\.toLocale/);
    assert.match(body, /doc\?\.reviewedAt/);
    assert.match(lawyerPage, /reviewedAt: d\.reviewed_at \?\? null/);
});

/* ── resume keeps the frozen checks ────────────────────────────────────── */

test("a restored document carries its revision's compliance and verification", () => {
    const compliance = { checked: true, complete: false, missing: 2 };
    const verification = { ran: true, counts: { verified: 1, not_in_corpus: 0 } };
    const r = restoreStateFromDocument({
        id: "d1", review_status: "approved",
        current_revision: { revision_id: "r1", pdf_sha256: "h", compliance, verification },
    });
    assert.deepEqual(r.compliance, compliance);
    assert.deepEqual(r.verification, verification);
});

test("no revision means no checks to restore", () => {
    const r = restoreStateFromDocument({ id: "d1", current_revision: null });
    assert.equal(r.compliance, null);
    assert.equal(r.verification, null);
});

/* ── the lawyer catalogue ──────────────────────────────────────────────── */

test("every named template has a body of its own", () => {
    const generic = buildContent(BLANK_TEMPLATE, null);
    for (const tmpl of TEMPLATES) {
        if (tmpl.id === BLANK_TEMPLATE.id) continue;
        const body = buildContent(tmpl, null);
        assert.notEqual(body, generic, `${tmpl.name} is the generic scaffold`);
        assert.doesNotMatch(body, /1\. INTRODUCTION/, `${tmpl.name} is the generic scaffold`);
    }
});

test("the generic scaffold is offered under an honest name", () => {
    assert.ok(TEMPLATES.includes(BLANK_TEMPLATE));
    assert.match(BLANK_TEMPLATE.name, /blank/i);
    assert.match(BLANK_TEMPLATE.desc, /generic/i);
});

test("no card claims an instrument the system does not have", () => {
    const names = TEMPLATES.map(t => t.name.toLowerCase()).join(" | ");
    for (const absent of ["vakalatnama", "wakalatnama", "sale deed", "nda",
                          "employment", "affidavit", "power of attorney", "rti"]) {
        assert.ok(!names.includes(absent), `catalogue still lists ${absent}`);
    }
});

test("every category pill has at least one template", () => {
    for (const c of CATEGORIES.filter(c => c !== "All")) {
        assert.ok(TEMPLATES.some(t => t.cat === c), `empty category ${c}`);
    }
});

test("case data and titles are escaped, and no fake case number is invented", () => {
    const evil = { id: "<b>x</b>", client: "<img src=x onerror=1>", court: "\"c\"" };
    for (const tmpl of TEMPLATES) {
        const body = buildContent(tmpl, evil);
        assert.doesNotMatch(body, /<img|<b>/);
    }
    assert.doesNotMatch(buildContent({ id: 99, name: "<script>" }, null), /<script>/);
    for (const tmpl of TEMPLATES) {
        assert.doesNotMatch(buildContent(tmpl, null), /CS-2024-089/);
    }
});
