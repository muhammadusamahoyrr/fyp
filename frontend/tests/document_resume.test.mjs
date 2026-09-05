/* Coming back to a document you were part-way through.
 *
 * `docId` lived only in React state, so a refresh — or a phone locking, or a
 * tab restored the next morning — dropped it. The document itself was never
 * lost: it was on the server the whole time, with its revision, its hash and
 * its review status. The client simply had no way to say which one it had been
 * looking at, so the user was returned to an empty Step 1 and their only
 * recourse was to generate the whole thing again.
 *
 * That is worse than it sounds. A second generation is a second render, a
 * second version number, and — for a document already sent for review — a
 * second thing in a lawyer's queue that the client cannot tell apart from the
 * first.
 *
 * `getDocumentV2` existed and was exported and was called from nowhere. These
 * are the two pure halves of using it: remembering WHICH document, and turning
 * the server's answer back into where the user was.
 */
import test from "node:test";
import assert from "node:assert/strict";

import {
    rememberDraft, recallDraft, forgetDraft,
    restoreStateFromDocument, DRAFT_KEY_PREFIX,
} from "../src/lib/documentResume.js";

/* A localStorage that behaves, and one that does not. Both are real: private
   windows, cleared site data and storage-blocking settings all make the second
   one the live case, and it must never take the page down with it. */
function fakeStorage() {
    const map = new Map();
    return {
        getItem: k => (map.has(k) ? map.get(k) : null),
        setItem: (k, v) => map.set(k, String(v)),
        removeItem: k => map.delete(k),
        _map: map,
    };
}

function hostileStorage() {
    return {
        getItem() { throw new Error("SecurityError"); },
        setItem() { throw new Error("SecurityError"); },
        removeItem() { throw new Error("SecurityError"); },
    };
}

/* ── remembering which document ───────────────────────────────────────────── */

test("a remembered draft comes back for the same case", () => {
    const s = fakeStorage();
    rememberDraft("case-1", "doc-abc", s);
    assert.equal(recallDraft("case-1", s), "doc-abc");
});

test("drafts are scoped per case", () => {
    // Two matters open in two tabs must not overwrite each other's progress.
    const s = fakeStorage();
    rememberDraft("case-1", "doc-abc", s);
    rememberDraft("case-2", "doc-xyz", s);
    assert.equal(recallDraft("case-1", s), "doc-abc");
    assert.equal(recallDraft("case-2", s), "doc-xyz");
});

test("an unknown case remembers nothing", () => {
    assert.equal(recallDraft("case-never-seen", fakeStorage()), null);
});

test("forgetting removes it", () => {
    const s = fakeStorage();
    rememberDraft("case-1", "doc-abc", s);
    forgetDraft("case-1", s);
    assert.equal(recallDraft("case-1", s), null);
});

test("the key is namespaced", () => {
    // localStorage is one flat namespace shared with everything else the app
    // stores; an unprefixed "case-1" would collide with anybody's.
    const s = fakeStorage();
    rememberDraft("case-1", "doc-abc", s);
    const [key] = [...s._map.keys()];
    assert.ok(key.startsWith(DRAFT_KEY_PREFIX));
});

test("storage that throws is survived, not propagated", () => {
    // A page that white-screens in a private window because it could not save a
    // convenience is a worse failure than not saving it.
    const s = hostileStorage();
    assert.doesNotThrow(() => rememberDraft("case-1", "doc-abc", s));
    assert.equal(recallDraft("case-1", s), null);
    assert.doesNotThrow(() => forgetDraft("case-1", s));
});

test("a missing storage is survived", () => {
    // Server-side render: there is no localStorage at all.
    assert.doesNotThrow(() => rememberDraft("case-1", "doc-abc", undefined));
    assert.equal(recallDraft("case-1", undefined), null);
});

/* ── turning the server's answer back into where the user was ─────────────── */

const GENERATED = {
    id: "doc-abc",
    title: "A notice",
    review_status: "none",
    current_version: 2,
    current_revision: { revision_id: "rev-2", pdf_sha256: "a".repeat(64) },
};

test("a generated document resumes at the preview step", () => {
    const s = restoreStateFromDocument(GENERATED);
    assert.equal(s.docId, "doc-abc");
    assert.equal(s.docRevisionId, "rev-2");
    assert.equal(s.docPdfSha256, "a".repeat(64));
    assert.equal(s.genDone, true);
    assert.equal(s.reviewSent, false);
    assert.equal(s.step, 2);
});

test("a document under review resumes at the review step", () => {
    const s = restoreStateFromDocument({
        ...GENERATED, review_status: "submitted", submitted_to: "lawyer-1",
    });
    assert.equal(s.reviewSent, true);
    assert.equal(s.reviewStatus, "submitted");
    assert.equal(s.step, 3);
});

for (const status of ["approved", "returned", "rejected"]) {
    test(`a ${status} document resumes with its decision`, () => {
        const s = restoreStateFromDocument({ ...GENERATED, review_status: status });
        assert.equal(s.reviewStatus, status);
        assert.equal(s.reviewSent, true);
        assert.equal(s.step, 3);
    });
}

test("a recovery state resumes where the explanation is shown", () => {
    // Not at Step 1: the user needs to READ what happened before being asked to
    // do it again, or the regenerate button looks like the app losing their work.
    const s = restoreStateFromDocument({
        ...GENERATED,
        review_status: "migration_unrecoverable",
        recovery: { state: "migration_unrecoverable", headline: "Needs to be sent again",
                    explanation: "…", next_action: "regenerate_and_resubmit",
                    blocks_use: true },
    });
    assert.equal(s.reviewSent, true);
    assert.equal(s.step, 3);
    assert.equal(s.reviewRecovery.state, "migration_unrecoverable");
});

test("a document with no revision resumes at the form", () => {
    const s = restoreStateFromDocument({
        id: "doc-abc", review_status: "none", current_version: 0,
        current_revision: null,
    });
    assert.equal(s.genDone, false);
    assert.equal(s.step, 1);
    assert.equal(s.docRevisionId, null);
});

test("nothing to restore returns null", () => {
    // The caller must be able to tell "no saved document" from "a saved
    // document with empty fields", or it would clear state it should keep.
    assert.equal(restoreStateFromDocument(null), null);
    assert.equal(restoreStateFromDocument(undefined), null);
    assert.equal(restoreStateFromDocument({}), null);
});

test("the restored hash and revision always travel together", () => {
    // They are the pair `submit` is guarded by. Restoring one without the other
    // produces a submission that fails a staleness check the user cannot act on.
    const s = restoreStateFromDocument(GENERATED);
    assert.ok((s.docRevisionId && s.docPdfSha256) ||
              (!s.docRevisionId && !s.docPdfSha256));
});

/* The surface's own wiring is covered by `document_resume_mounted.test.mjs`,
 * which mounts the restoration lifecycle and drives it through remounts, case
 * switches and out-of-order responses.
 *
 * A source-presence test used to sit here, asserting `getDocumentV2` appeared
 * somewhere in ModDocuments. It did appear, and it never ran: restoration keyed
 * off a case id that only generation ever set, so after a refresh the effect
 * returned early every single time. The test passed throughout. It was deleted
 * rather than repaired — it could only ever confirm that some text was present,
 * which is not the property anybody cared about.
 */

/* ── the document's own case travels with it (issue 4) ────────────────────── */

test("a restored document carries its own case id", () => {
    // The API returns `case_id` and this dropped it, so a document opened from
    // My Documents was remembered under whatever case happened to be selected.
    // Open a case-B document while case A is on screen and the pointer for A
    // now names a document belonging to B — so the next refresh of case A
    // restores the wrong matter's draft.
    const s = restoreStateFromDocument({ ...GENERATED, case_id: "case-B" });
    assert.equal(s.caseId, "case-B");
});

test("a document with no case restores a null case, not undefined", () => {
    // Standalone drafts are real. The caller has to be able to tell "no case"
    // from "the field was not returned" without guessing.
    const s = restoreStateFromDocument({ ...GENERATED, case_id: null });
    assert.equal(s.caseId, null);

    const absent = restoreStateFromDocument(GENERATED);
    assert.equal(absent.caseId, null);
});

/* ── the explicit no-case selection (issue 1/4) ───────────────────────────── */

import { resolveCaseId, NO_CASE } from "../src/lib/useDocumentResume.js";

const CASES = [{ _id: "case-1" }, { _id: "case-2" }];

test("an explicit no-case selection resolves to no case", () => {
    // "" is not good enough: it falls through to the first case in the list,
    // which drags a standalone document into a matter it does not belong to.
    assert.equal(resolveCaseId(NO_CASE, CASES), null);
    assert.equal(resolveCaseId("", CASES), "case-1");
});

test("an explicit selection still wins over the first case", () => {
    assert.equal(resolveCaseId("case-2", CASES), "case-2");
});

test("no cases at all resolves to no case", () => {
    assert.equal(resolveCaseId("", []), null);
    assert.equal(resolveCaseId(NO_CASE, []), null);
});
