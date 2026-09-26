/* Reopening a document from whichever backend holds it.
 *
 * The legacy route is asked ONLY when V2 says it is switched off. Any other
 * V2 failure — offline, forbidden, not found — is the answer, not a cue to ask
 * somebody else. See src/lib/documentLoader.js.
 */
import test from "node:test";
import assert from "node:assert/strict";

import {
    loadDocumentDetail, legacyDocumentToDetail, isFeatureDisabled,
} from "../src/lib/documentLoader.js";
import { restoreStateFromDocument } from "../src/lib/documentResume.js";

const DISABLED = { data: null, status: 404, error: { code: "feature_disabled", message: "Not found." } };
const LEGACY = {
    _id: "doc-1", case_id: "case-1", title: "Legal Notice", template_type: "legal_notice",
    status: "generated", review_status: null,
    compliance: { checked: true, complete: false, missing: 2 },
    verification: { ran: true, counts: { verified: 1 } },
};

function spies(v2, legacy) {
    const calls = { v2: 0, legacy: 0 };
    return {
        calls,
        getV2: async () => { calls.v2 += 1; return v2; },
        getLegacy: async () => { calls.legacy += 1; return legacy; },
    };
}

test("V2's own answer is returned untouched", async () => {
    const ok = { data: { id: "doc-1", current_revision: null }, status: 200, error: null };
    const s = spies(ok, null);
    assert.equal(await loadDocumentDetail("doc-1", s), ok);
    assert.equal(s.calls.legacy, 0);
});

test("feature_disabled falls back to legacy and normalises the result", async () => {
    const s = spies(DISABLED, { data: LEGACY, status: 200, error: null });
    const res = await loadDocumentDetail("doc-1", s);
    assert.equal(s.calls.legacy, 1);
    assert.equal(res.data.id, "doc-1");
    assert.equal(res.data.source, "legacy");
    assert.equal(res.data.case_id, "case-1");
});

test("no other V2 failure reaches the legacy route", async () => {
    for (const failure of [
        { data: null, status: 0, error: { message: "Network error." } },
        { data: null, status: 403, error: { code: "forbidden", message: "No." } },
        { data: null, status: 404, error: { code: "not_found", message: "Not found." } },
        { data: null, status: 503, error: { code: "unavailable", message: "Busy." } },
    ]) {
        const s = spies(failure, { data: LEGACY });
        assert.equal(await loadDocumentDetail("doc-1", s), failure);
        assert.equal(s.calls.legacy, 0, `fell back on ${failure.status}`);
    }
});

test("a legacy failure is passed through as-is", async () => {
    const gone = { data: null, status: 404, error: { code: "not_found", message: "Gone." } };
    const s = spies(DISABLED, gone);
    assert.equal(await loadDocumentDetail("doc-1", s), gone);
});

test("isFeatureDisabled needs both the status and the code", () => {
    assert.equal(isFeatureDisabled(DISABLED), true);
    assert.equal(isFeatureDisabled({ status: 404, error: { code: "not_found" } }), false);
    assert.equal(isFeatureDisabled({ status: 500, error: { code: "feature_disabled" } }), false);
    assert.equal(isFeatureDisabled(null), false);
});

/* ── the restored state ─────────────────────────────────────────────────── */

test("a generated legacy document reopens at the preview, with its checks", () => {
    const r = restoreStateFromDocument(legacyDocumentToDetail(LEGACY));
    assert.equal(r.docId, "doc-1");
    assert.equal(r.caseId, "case-1");
    assert.equal(r.genDone, true);
    assert.equal(r.step, 2);
    // No revision: preview, download and submit take the legacy route.
    assert.equal(r.docRevisionId, null);
    assert.equal(r.docPdfSha256, null);
    assert.deepEqual(r.compliance, LEGACY.compliance);
    assert.deepEqual(r.verification, LEGACY.verification);
});

test("a submitted legacy document reopens at the review panel", () => {
    const r = restoreStateFromDocument(legacyDocumentToDetail(
        { ...LEGACY, review_status: "submitted" }));
    assert.equal(r.reviewSent, true);
    assert.equal(r.reviewStatus, "submitted");
    assert.equal(r.step, 3);
});

test("a legacy document whose PDF failed is not presented as generated", () => {
    for (const status of ["failed", "pending"]) {
        const r = restoreStateFromDocument(legacyDocumentToDetail({ ...LEGACY, status }));
        assert.equal(r.genDone, false, status);
        assert.equal(r.step, 1, status);
    }
});

test("a legacy document with no id is not restorable", () => {
    assert.equal(legacyDocumentToDetail({ title: "x" }), null);
    assert.equal(restoreStateFromDocument(legacyDocumentToDetail(null)), null);
});
