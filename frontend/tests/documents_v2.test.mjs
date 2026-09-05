/* The V2 document client: idempotency, error codes, revision-safe preview.
 *
 * The legacy calls carry no version, no hash and no idempotency key. A retry of
 * a lost response there generates a second document or applies a review twice,
 * and a preview fetches "the current file" rather than the revision whose hash
 * and verdict the reader is looking at.
 *
 * These are the contracts that stop that, checked at the client boundary. */
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const api = readFileSync(new URL("../src/lib/api.js", import.meta.url), "utf8");

/* formatResponseError is module-private, so it is lifted out and evaluated
   rather than imported — the alternative is exporting it purely to test it,
   which widens the module's surface for no caller's benefit. */
function loadFormatter() {
    const body = api.slice(api.indexOf("function formatResponseError"),
                           api.indexOf("// ─── Core fetch wrapper"));
    return new Function(`return ${body.trim()}`)();
}

test("the machine-readable envelope reaches the user as words", () => {
    // This branch used to be String() on an object, so every V2 error the
    // backend carefully coded arrived as "[object Object]".
    const formatted = loadFormatter()({
        error: { code: "revision_changed", message: "This document was regenerated." },
        status_code: 409,
    });
    assert.equal(formatted.message, "This document was regenerated.");
    assert.equal(formatted.code, "revision_changed");
    assert.ok(!/\[object Object\]/.test(formatted.message));
});

test("a code-bearing detail is understood too", () => {
    // Reached when a route raises HTTPException with a dict and no global
    // handler reshapes it — the shape the feature-flag 404 uses.
    const formatted = loadFormatter()({
        detail: { code: "feature_disabled", message: "Not found." },
    });
    assert.equal(formatted.message, "Not found.");
    assert.equal(formatted.code, "feature_disabled");
});

test("plain-string errors are unchanged", () => {
    // Every legacy caller depends on this path.
    assert.equal(loadFormatter()({ detail: "Session expired." }).message,
                 "Session expired.");
});

test("every mutating V2 call takes an idempotency key", () => {
    // A key minted per transmission rather than per intent makes the whole
    // mechanism unreachable from the UI — the same bug the chat surfaces had.
    for (const fn of ["createDocumentV2", "generateRevisionV2", "submitDocumentV2",
                      "reviewDocumentV2", "withdrawDocumentV2"]) {
        const body = api.slice(api.indexOf(`export async function ${fn}`));
        const head = body.slice(0, body.indexOf("\n}"));
        assert.match(head, /v2Headers\(key\)/, `${fn} sends no Idempotency-Key`);
    }
});

test("no read-only V2 call sends an idempotency key", () => {
    // A key on a GET is noise that implies a write.
    for (const fn of ["getDocumentV2", "listRevisionsV2", "reviewQueueV2"]) {
        const body = api.slice(api.indexOf(`export async function ${fn}`));
        const head = body.slice(0, body.indexOf("\n}"));
        assert.ok(!/v2Headers/.test(head), `${fn} sends an Idempotency-Key`);
    }
});

test("preview names the revision in the path and can assert its hash", () => {
    // "Current" cannot express "the one I was looking at". The hash the caller
    // read is what the server compares against.
    const body = api.slice(api.indexOf("export async function previewRevisionV2"));
    const head = body.slice(0, body.indexOf("\n}\n"));
    assert.match(head, /\/revisions\//);
    assert.match(head, /expected_pdf_sha256/);
    assert.match(head, /returnResponse: true/);
    // And it hands back what actually arrived, not what was asked for.
    assert.match(head, /etag:/);
    assert.match(head, /revisionId:/);
});

test("a retry is only offered where the outcome is genuinely unknown", async () => {
    const { isRetryable } = await import("../src/lib/api.js");
    // The work may or may not have happened — the case an idempotency key is for.
    assert.equal(isRetryable(503, {}), true);
    assert.equal(isRetryable(0, {}), true);
    // A decision. Repeating it changes nothing.
    assert.equal(isRetryable(409, { code: "revision_changed" }), false);
    assert.equal(isRetryable(422, { code: "validation_error" }), false);
    // The one 409 that must never be retried: the same key with different
    // content is a client bug, and retrying hides it.
    assert.equal(isRetryable(503, { code: "idempotency_mismatch" }), false);
});

test("errorCode reads the code without every caller knowing the shape", async () => {
    const { errorCode } = await import("../src/lib/api.js");
    assert.equal(errorCode({ code: "backlog_unavailable" }), "backlog_unavailable");
    assert.equal(errorCode({}), null);
    assert.equal(errorCode(null), null);
});

test("keys are unique per call", async () => {
    const { idempotencyKey } = await import("../src/lib/api.js");
    const keys = new Set(Array.from({ length: 200 }, () => idempotencyKey()));
    assert.equal(keys.size, 200);
});

/* ══════════════════════════════════════════════════════════════════════════
 * The document screens no longer claim to do things they cannot
 * ══════════════════════════════════════════════════════════════════════════ */

const client = readFileSync(
    new URL("../src/components/client/ModDocuments.jsx", import.meta.url), "utf8");
const lawyer = readFileSync(
    new URL("../src/components/lawyer/DocumentsPage.jsx", import.meta.url), "utf8");

test("the client cannot pretend to format a PDF", () => {
    // The Edit toggle revealed bold/italic/underline buttons calling
    // document.execCommand on a PDF in an iframe. Nothing could be changed and
    // nothing was ever saved — so a user could believe their edits existed and
    // submit a document that never contained them.
    const code = client.replace(/\/\*[\s\S]*?\*\/|\{\/\*[\s\S]*?\*\/\}/g, "");
    assert.ok(!/execCommand/.test(code),
        "the formatting toolbar is still wired to a PDF");
    assert.ok(!/editMode/.test(code),
        "dead edit state remains, so a step that can never happen is displayed");
});

test("the client offers the edit the format actually supports", () => {
    // Changing the answers and regenerating IS the edit, and it maps onto how
    // the document is versioned: a change produces a new revision.
    assert.match(client, /Change answers/);
    assert.ok(!/✏️ Edit<\/button>/.test(client));
});

test("the lawyer asks for changes rather than implying they can make them", () => {
    // A reviewer who could alter the artifact would be reviewing something
    // nobody else saw — the submitted bytes have a hash.
    assert.match(lawyer, /Request changes/);
    assert.ok(!/\? "👁 Preview" : "✏️ Edit"/.test(lawyer),
        "the toggle still says Edit");
});

test("the client preview asks for an exact revision and survives unmount", () => {
    // Two bugs in one effect: it fetched "the current file", and a URL that
    // arrived after unmount was never revoked because the cleanup's local was
    // still null.
    const effect = client.slice(client.indexOf("fetchRevisionPreview"));
    const body = effect.slice(0, effect.indexOf("}, [docId"));
    // Named, not "whatever is current". The `viewRev ||` prefix is the version
    // history browser; docRevisionId is still what it falls back to, which is
    // the property that matters — the pane never asks for an unnamed file.
    assert.match(body, /revisionId: viewRev\?\.revision_id \|\| docRevisionId/);
    assert.match(body, /expectedPdfSha256: viewRev\?\.pdf_sha256 \|\| docPdfSha256/);
    assert.match(body, /if \(!live\)[\s\S]{0,200}revokeObjectURL/,
        "a late-arriving preview URL is still leaked");
    assert.match(body, /revision_changed/,
        "a regenerated document is not reported to the user");
});

/* ══════════════════════════════════════════════════════════════════════════
 * The lawyer review flow on V2
 * ══════════════════════════════════════════════════════════════════════════ */

test("a decision sends the expected version and hash", () => {
    // The server guards its atomic update on exactly this pair. Sending
    // anything else — or nothing — means the decision matches nothing, and a
    // decision that cannot be validated is one that could land on bytes the
    // lawyer never read.
    const fn = lawyer.slice(lawyer.indexOf("const handleDecide"));
    const body = fn.slice(0, fn.indexOf("\n    };"));
    assert.match(body, /expectedVersion: activeDoc\.submittedVersion/);
    assert.match(body, /expectedPdfSha256: activeDoc\.submittedPdfSha256/);
    assert.match(body, /reviewDocumentV2\(/);
});

test("the idempotency key is minted per decision and reused by the retry", () => {
    // A fresh key per attempt makes the receipt machinery unreachable: two
    // presses of Approve would record two transitions.
    const fn = lawyer.slice(lawyer.indexOf("const handleDecide"));
    const body = fn.slice(0, fn.indexOf("\n    };"));
    assert.match(body, /const idemKey = key \|\| idempotencyKey\(\);/);
    assert.match(body, /setRetry\(\{ action, note, key: idemKey \}\)/,
        "the retry does not carry the original key");
    assert.match(lawyer, /handleDecide\(retry\.action, retry\.note, retry\.key\)/,
        "the retry button mints a new key");
});

test("a stale document blocks the decision instead of reporting a failure", () => {
    // The lawyer must look at what is actually there before deciding. A
    // generic error would leave them to guess, and a toast would vanish.
    const fn = lawyer.slice(lawyer.indexOf("const handleDecide"));
    const body = fn.slice(0, fn.indexOf("\n    };"));
    assert.match(body, /status === 409/);
    assert.match(body, /setStaleWarning\(/);
    // And the banner is blocking, with a way out that reloads.
    assert.match(lawyer, /\{staleWarning && \(/);
    assert.match(lawyer, /Reload queue/);
});

test("each V2 error class is handled distinctly", () => {
    const fn = lawyer.slice(lawyer.indexOf("const handleDecide"));
    const body = fn.slice(0, fn.indexOf("\n    };"));
    // 409 blocks, 503 offers a retry with the same key, everything else shows
    // the server's own words rather than an invented message.
    assert.match(body, /status === 503/);
    assert.match(body, /errorCode\(error\)/);
    assert.match(body, /error\.message/);
});

test("the lawyer preview is pinned to the revision under review", () => {
    // The legacy path fetched "the current file", so a client who regenerated
    // after submitting had the lawyer reading the NEW bytes while deciding on
    // the submitted ones.
    // `viewRevisionId` is the submitted revision on a pending row and the
    // decided one on a decided row — the field widened so the Approved,
    // Returned and Rejected tabs can be opened at all. What this still pins is
    // that a NAMED revision is asked for, never "the current file".
    assert.match(lawyer, /revisionId: doc\.viewRevisionId/);
    assert.match(lawyer, /expectedPdfSha256: doc\.viewPdfSha256/);
    const stale = lawyer.replace(/\/\*[\s\S]*?\*\/|\{\/\*[\s\S]*?\*\/\}|\/\/[^\n]*/g, "");
    assert.ok(!/fetchDocumentPreviewUrl/.test(stale),
        "a preview still fetches whatever the document currently is");
});

test("a late preview URL is revoked on both lawyer screens", () => {
    // Two effects, same bug: the cleanup revoked a local still null when the
    // fetch resolved after unmount.
    const guards = lawyer.match(/if \(!live\)[\s\S]{0,160}revokeObjectURL/g) || [];
    assert.equal(guards.length, 2,
        `${guards.length} of 2 lawyer previews revoke a late arrival`);
});

test("the queue row carries what a decision needs", () => {
    assert.match(lawyer, /submittedVersion: d\.submitted_version/);
    assert.match(lawyer, /submittedRevisionId: d\.submitted_revision_id/);
    assert.match(lawyer, /submittedPdfSha256: d\.submitted_pdf_sha256/);
});

test("the legacy path remains while the flag is off", () => {
    // DOCUMENTS_V2 defaults off, so the queue returns no submitted_* fields and
    // the screen must still work. Removing the fallback would break review
    // entirely the moment this shipped.
    const fn = lawyer.slice(lawyer.indexOf("const handleDecide"));
    const body = fn.slice(0, fn.indexOf("\n    };"));
    assert.match(body, /const canUseV2 = activeDoc\.submittedVersion != null/);
    assert.match(body, /: await reviewDocument\(activeDoc\.id, \{ action, note \}\)/);
});

/* ══════════════════════════════════════════════════════════════════════════
 * The client half: generate and submit through V2
 * ══════════════════════════════════════════════════════════════════════════ */

test("generation stores the revision id, hash and version", () => {
    // Without all three the preview cannot be pinned and the submission cannot
    // be validated — the two things the whole V2 path exists to make possible.
    assert.match(client, /setDocRevisionId\(viaV2\.revisionId\)/);
    assert.match(client, /setDocPdfSha256\(viaV2\.pdfSha256\)/);
    assert.match(client, /setDocVersion\(viaV2\.version\)/);
});

test("submit sends the expected version and hash", () => {
    const fn = client.slice(client.indexOf("const submitToLawyer"));
    const body = fn.slice(0, fn.indexOf("\n    };"));
    assert.match(body, /expectedVersion: docVersion/);
    assert.match(body, /expectedPdfSha256: docPdfSha256/);
    assert.match(body, /submitDocumentV2\(/);
});

test("one key per logical action, held across retries", () => {
    // A key minted per HTTP call makes idempotency unreachable: the retry looks
    // like a new intent and the server renders a second revision. Refs, not
    // state, so a re-render between failure and retry cannot lose them.
    assert.match(client, /const generateKeyRef = useRef\(null\)/);
    assert.match(client, /const submitKeyRef = useRef\(null\)/);
    assert.match(client, /generateKeyRef\.current = retryKey \|\| idempotencyKey\(\)/);
    assert.match(client,
        /submitKeyRef\.current = retryKey \|\| submitKeyRef\.current \|\| idempotencyKey\(\)/);
});

test("an automatic retry never mints a new key", () => {
    // The retry button passes the stored key back in. A fresh key there would
    // be a second charge for one intent.
    assert.match(client, /submitToLawyer\(submitKeyRef\.current\)/);
    assert.match(client, /handleGenerate\(generateKeyRef\.current\)/);
});

test("a new generation is a new intent", () => {
    // "Change answers" then Generate must produce a NEW revision rather than
    // reusing the one on screen. A fresh key is how that intent is expressed,
    // and the stale submit intent is dropped with it.
    const fn = client.slice(client.indexOf("const handleGenerate"));
    const body = fn.slice(0, fn.indexOf("const _generateViaV2"));
    assert.match(body, /submitKeyRef\.current = null/,
        "a stale submit intent survives a regeneration");
});

test("regenerating clears the revision being previewed", () => {
    // Otherwise the preview pairs a new document id with an old revision id —
    // a request that either 404s or renders the wrong draft under the new
    // document's heading.
    const fn = client.slice(client.indexOf("const handleGenerate"));
    const body = fn.slice(0, fn.indexOf("const _generateViaV2"));
    assert.match(body,
        /setDocRevisionId\(null\); setDocPdfSha256\(null\); setDocVersion\(null\)/);
});

test("each V2 error class is handled and none is reported as success", () => {
    // A draft the user believes exists, and then submits, is worse than a
    // visible failure.
    const gen = client.slice(client.indexOf("const handleGenerate"),
                             client.indexOf("const _v2Issue"));
    assert.match(gen, /setDocIssue\(viaV2\.issue\)/);
    assert.match(gen, /return;/);

    const sub = client.slice(client.indexOf("const submitToLawyer"));
    const body = sub.slice(0, sub.indexOf("\n    };"));
    assert.match(body, /status === 409/);
    assert.match(body, /issue\.retryable/);

    // Only 503-class failures offer a retry; 409/422 are decisions.
    assert.match(client, /retryable: isRetryable\(status, error\)/);
});

test("the legacy path still works when the flag is off", () => {
    // DOCUMENTS_V2 defaults off, so create returns feature_disabled and the
    // screen must fall through. Removing this would break generation entirely
    // the moment it shipped.
    assert.match(client, /if \(viaV2\.unavailable\)/);
    assert.match(client, /await generateDocument\(caseId, backendType, fields\)/);
    assert.match(client, /errorCode\(created\.error\) === "feature_disabled"/);

    const sub = client.slice(client.indexOf("const submitToLawyer"));
    assert.match(sub.slice(0, sub.indexOf("\n    };")),
        /: await submitDocumentForReview\(docId, \{/);
});

test("submit only uses V2 when the document actually has a revision", () => {
    // Sending a null version and hash is what the server refuses; gating on
    // their presence is what keeps every legacy draft submittable.
    const sub = client.slice(client.indexOf("const submitToLawyer"));
    assert.match(sub, /const viaV2 = docRevisionId && docPdfSha256 && docVersion != null/);
});

/* ══════════════════════════════════════════════════════════════════════════
 * The lawyer inbox: paginated
 * ══════════════════════════════════════════════════════════════════════════ */

test("the inbox loads one page at a time", () => {
    // The queue it replaces returned every document ever submitted to this
    // lawyer in one response — no cursor, no bound. Fine on a demo account, a
    // cliff on a real one.
    // The status is now part of the call — see "the selected tab is sent to
    // the server". What this test still pins is that the page is BOUNDED.
    assert.match(lawyer, /reviewQueueV2\(\{ status: wanted/);
    assert.match(lawyer, /limit: QUEUE_PAGE/);
    assert.match(lawyer, /const QUEUE_PAGE = 25;/);
    assert.match(lawyer, /setQueueCursor\(cursor\)/);
});

test("the load-more control follows the cursor, not the row count", () => {
    // A page can come back short after filtering and still have a next one.
    assert.match(lawyer, /hasMore=\{!!queueCursor\}/);
    assert.match(lawyer, /onLoadMore=\{\(\) => load\(queueCursor\)\}/);
    assert.match(lawyer, /Load more/);
});

test("appending a page de-duplicates", () => {
    // A document that moves between pages can legitimately appear twice, and
    // rendering it twice looks like data corruption.
    const fn = lawyer.slice(lawyer.indexOf("const load = async"));
    const body = fn.slice(0, fn.indexOf("useEffect(() => { load()"));
    assert.match(body, /const merged = after \? \[\.\.\.prev, \.\.\.mapped\] : mapped/);
    assert.match(body, /seen\.has\(d\.id\)/);
});

test("a stale page cannot land on a fresher one", () => {
    // A decision reloads the queue; a page request already in flight when that
    // happens must be dropped rather than painted over the newer result.
    const fn = lawyer.slice(lawyer.indexOf("const load = async"));
    const body = fn.slice(0, fn.indexOf("useEffect(() => { load()"));
    assert.match(body, /const ticket = queueGeneration\.next\(\)/);
    assert.match(body, /if \(!queueGeneration\.isCurrent\(ticket\)\) return;/);
});

test("the legacy queue still serves while the flag is off", () => {
    // It is unpaginated by nature, so there is nothing to continue from — one
    // read, no cursor. Removing this would empty every lawyer's inbox.
    const fn = lawyer.slice(lawyer.indexOf("const load = async"));
    const body = fn.slice(0, fn.indexOf("useEffect(() => { load()"));
    assert.match(body, /errorCode\(v2\.error\) === "feature_disabled"/);
    assert.match(body, /await listReviewQueue\(\)/);
    assert.match(body, /cursor = null;/);
});

test("a queue failure is reported, not silently shown as empty", () => {
    // An empty inbox and an unreachable one look identical to a lawyer, and
    // only one of them means there is nothing to do.
    const fn = lawyer.slice(lawyer.indexOf("const load = async"));
    const body = fn.slice(0, fn.indexOf("useEffect(() => { load()"));
    assert.match(body, /Could not load the queue/);
});

/* ══════════════════════════════════════════════════════════════════════════
 * Withdrawal
 *
 * A client who submits to the wrong lawyer, or spots a mistake a minute later,
 * had no way back: the endpoint existed and nothing on either screen reached
 * it. The document sat in a stranger's queue until they decided on it.
 * ══════════════════════════════════════════════════════════════════════════ */

const revhist = readFileSync(
    new URL("../src/components/shared/RevisionHistory.jsx", import.meta.url), "utf8");

function clientFn(name) {
    const fn = client.slice(client.indexOf(`const ${name} = async`));
    return fn.slice(0, fn.indexOf("\n    };"));
}

test("withdrawal carries its own idempotency key", () => {
    // Reusing the submit key would have the server treat the withdrawal as a
    // replay of the submission it undoes, and return the submission receipt —
    // a success response for the opposite of what was asked.
    const body = clientFn("withdrawFromReview");
    assert.match(body, /withdrawKeyRef\.current = retryKey \|\| withdrawKeyRef\.current \|\| idempotencyKey\(\)/);
    assert.match(body, /withdrawDocumentV2\(docId, withdrawKeyRef\.current\)/);
    assert.ok(!/submitKeyRef\.current\)/.test(body.split("if (error)")[0]),
        "the withdrawal is sent under the submit key");
});

test("a withdrawal clears the submit key so re-submitting is a new intent", () => {
    // Otherwise the next Submit replays the withdrawn submission's receipt and
    // the client is told it was sent when nothing was.
    const body = clientFn("withdrawFromReview");
    const success = body.slice(body.lastIndexOf("setReviewSent(false)") - 400);
    assert.match(success, /submitKeyRef\.current = null/);
    assert.match(success, /withdrawKeyRef\.current = null/);
});

test("a race with the lawyer's decision is explained, not retried", () => {
    // 409 here means they decided while the click was in flight. Repeating it
    // cannot succeed, so offering a retry would loop the user on a dead action.
    const body = clientFn("withdrawFromReview");
    assert.match(body, /status === 409/);
    assert.match(body, /already responded/);
    assert.match(body, /status === 404 && errorCode\(error\) === "feature_disabled"/);
});

test("the withdraw button only exists while the document is under review", () => {
    // A decided document cannot be un-decided; the server refuses, and a button
    // that is certain to be refused reads as a broken screen rather than a rule.
    const body = clientFn("withdrawFromReview");
    assert.match(body, /reviewStatus !== "submitted"\) return;/);
    assert.match(client, /Withdraw from review/);
    const panel = client.slice(client.indexOf('reviewStatus === "submitted" && ('));
    assert.match(panel.slice(0, 1400), /withdrawFromReview\(\)/);
});

test("the click event never becomes an idempotency key", () => {
    // `onClick={withdrawFromReview}` passes the React event as `retryKey`, and
    // the ref would hold a synthetic event where a UUID belongs.
    assert.ok(!/onClick=\{withdrawFromReview\}/.test(client),
        "the handler is passed bare to onClick");
});

/* ══════════════════════════════════════════════════════════════════════════
 * Version history
 * ══════════════════════════════════════════════════════════════════════════ */

test("browsing history never changes what is submitted or decided", () => {
    // THE point of the separate viewRev state. The submit sends the document's
    // real current version and hash; the lawyer's decision sends the SUBMITTED
    // pair. Neither reads the revision someone happens to be looking at.
    const submit = clientFn("submitToLawyer");
    assert.ok(!/viewRev/.test(submit),
        "the client submits whichever revision is on screen");

    const decide = lawyer.slice(lawyer.indexOf("const handleDecide"));
    assert.ok(!/viewRev/.test(decide.slice(0, decide.indexOf("\n    };"))),
        "the lawyer decides on whichever revision is on screen");
});

test("both surfaces say so while an older draft is displayed", () => {
    // Without the banner the pane silently shows different text under the same
    // verdict panel, which is the exact confusion revision pinning exists to
    // prevent.
    assert.match(client, /Showing an earlier version/);
    assert.match(client, /Submitting still sends the latest/);
    assert.match(lawyer, /Reading an earlier draft/);
    assert.match(lawyer, /applies to the version the client submitted/);
});

test("a regeneration drops the pinned older revision", () => {
    // Otherwise a new draft lands behind a superseded one still on screen.
    const fn = client.slice(client.indexOf("const handleGenerate"));
    assert.match(fn.slice(0, 2000), /setViewRev\(null\)/);
});

test("the history list reloads on new revisions, not on every click", () => {
    // `currentRevisionId` is what the caller is DISPLAYING and changes on each
    // click; re-reading on it refetches the whole history while browsing it.
    const effect = revhist.slice(revhist.indexOf("useEffect(()"));
    assert.match(effect, /\}, \[docId, reloadKey\]\);/);
});

test("an unverified revision is never shown as checked", () => {
    // "not verified" and "verified and passed" are different facts. Collapsing
    // them into a tick is the most expensive lie this list could tell.
    const fn = revhist.slice(revhist.indexOf("function _verdict"));
    assert.match(fn, /return "Not verified"/);
    assert.match(fn, /extraction_status && rev\.extraction_status !== "ok"/);
    assert.match(fn, /verdict === "pass"/);
});

test("the history is silent when the feature is off", () => {
    // feature_disabled is the flag saying "not here" — not an error worth
    // showing someone who was never offered the feature.
    assert.match(revhist, /errorCode\(error\) === "feature_disabled"/);
    assert.match(revhist, /\? null/);
});

test("a revision with no file is shown, not hidden", () => {
    // A gap in the version numbers is more alarming than a row that explains
    // itself, and it is not previewable — there are no bytes to fetch.
    assert.match(revhist, /No file was produced for this version/);
    assert.match(revhist, /onClick=\{\(\) => !failed && onPreview\?\.\(rev\)\}/);
});

/* ══════════════════════════════════════════════════════════════════════════
 * The template catalogue
 *
 * `pickType` existed and NOTHING CALLED IT. `selectedType` was therefore never
 * set, `canGenerate` was permanently false, and the Generate button sat
 * disabled saying "select a document type" with no way to select one anywhere
 * on the screen. Client document generation was unreachable.
 * ══════════════════════════════════════════════════════════════════════════ */

test("the client can actually choose a document type", () => {
    // The whole flow hinged on this one missing control.
    assert.match(client, /Document Type/);
    assert.match(client, /if \(spec\) pickType\(spec\)/);
    assert.match(client, /Select a document type/);
});

test("the picker is fed by the server, not a list in this file", () => {
    // Two screens each hardcoding their own list is how one came to offer a
    // "Settlement Draft" nothing could build and a "Contract" wired to the NDA
    // builder.
    assert.match(client, /listTemplates\(\)/);
    assert.ok(!/DOC_TYPE_MAP/.test(client), "the hardcoded type map survives");
    assert.ok(!/DOC_TYPES_DATA/.test(client), "the hardcoded type list survives");
});

test("generation sends the server's own template key", () => {
    // Deriving a template key from a display name is exactly the mapping step
    // that used to send "Contract" to the NDA builder.
    assert.match(client, /const templateKey = selectedType\?\.template_type;/);
});

test("a catalogue that fails to load says so rather than falling back", () => {
    // A stale hardcoded list is how this screen came to offer documents nothing
    // could render. An empty picker that explains itself is recoverable; a
    // wrong one that looks right is not.
    const effect = client.slice(client.indexOf("listTemplates()"));
    const body = effect.slice(0, effect.indexOf("}, []);"));
    assert.match(body, /setTemplates\(\[\]\)/);
    assert.match(body, /setTemplateIssue\(/);
    assert.ok(!/DRAFTS_DATA/.test(body), "it falls back to a local list");
});

test("the picker shows what the builder actually emits", () => {
    // Several entries are narrower than their name suggests — the Vakalatnama
    // entry is an execution checklist and says so. A user who picks it
    // expecting an appointment instrument must read that before drafting.
    assert.match(client, /selectedType\?\.description && \(/);
});

/* ══════════════════════════════════════════════════════════════════════════
 * Answers that went nowhere
 * ══════════════════════════════════════════════════════════════════════════ */

test("an unused answer is reported to the client who typed it", () => {
    // The document rendered with an empty line exactly where the user believes
    // they supplied something, and nothing anywhere said so.
    assert.match(client, /fieldShape\?\.unknown\?\.length > 0/);
    assert.match(client, /not used/);
    assert.match(client, /check the document before submitting/);
});

test("and to the lawyer who signs it off", () => {
    // The reviewer carries the cost of a document with a hole in it.
    assert.match(lawyer, /fieldShape\?\.unknown\?\.length > 0/);
    assert.match(lawyer, /Answers not in this document/);
    assert.match(lawyer, /fieldShape: d\.field_shape/);
});

test("the legacy path clears the shape report rather than keeping a stale one", () => {
    // It produces none. Leaving the previous V2 generation's report on screen
    // would read it against different bytes.
    const fn = client.slice(client.indexOf("const handleGenerate"));
    const body = fn.slice(0, fn.indexOf("\n    };"));
    assert.match(body, /setFieldShape\(null\)/);
    assert.match(body, /setFieldShape\(viaV2\.fieldShape \|\| null\)/);
});

test("the shape finding is never rendered as a compliance verdict", () => {
    // Requiredness belongs to pleading_rules, which is grounded in enumerated
    // statutory clauses. A shape pass shown as a compliance pass would assert a
    // statutory requirement nobody checked.
    // Bounded by the panel that follows it — a fixed character window runs into
    // the compliance panel and tests that one instead.
    for (const [src, next] of [[client, "compliance?.checked"],
                               [lawyer, "Statutory completeness"]]) {
        const idx = src.indexOf("fieldShape?.unknown?.length > 0");
        const panel = src.slice(idx, src.indexOf(next, idx));
        assert.ok(panel.length > 200, "the panel window is empty");
        assert.ok(!/complete/i.test(panel), "the shape panel claims completeness");
        assert.ok(!/compliant/i.test(panel), "the shape panel claims compliance");
    }
});

/* ══════════════════════════════════════════════════════════════════════════
 * Downloading
 *
 * `/documents/{id}/download` serves `file_path`, and a V2 document has none —
 * its bytes live in the artifact store under a revision id, and
 * `repoint_document` never writes a path back. So the Download button 404'd on
 * every document this pipeline produced. Verified against a live database
 * before the fix: "LEGACY DOWNLOAD FAILED: 404, file_path: None".
 * ══════════════════════════════════════════════════════════════════════════ */

test("a download names the revision rather than asking for a file path", () => {
    const fn = api.slice(api.indexOf("export async function downloadDocumentFile"));
    const body = fn.slice(0, fn.indexOf("\n}\n"));
    assert.match(body, /\/documents\/v2\//);
    assert.match(body, /\/revisions\//);
    assert.match(body, /expected_pdf_sha256/);
    // And still falls back, so a legacy document keeps working.
    assert.match(body, /return downloadDocument\(docId, filename\)/);
});

test("only the feature flag falls back, not a real failure", () => {
    // Retrying a genuine error against a route that cannot serve this document
    // either turns one honest failure into a confusing second one.
    const fn = api.slice(api.indexOf("export async function downloadDocumentFile"));
    const body = fn.slice(0, fn.indexOf("\n}\n"));
    assert.match(body, /status === 404 && errorCode\(error\) === 'feature_disabled'/);
});

test("no screen still calls the raw legacy download", () => {
    for (const [name, src] of [["client", client], ["lawyer", lawyer]]) {
        assert.ok(!/[^A-Za-z]downloadDocument\(/.test(src),
            `the ${name} screen still downloads through the legacy route`);
        assert.match(src, /downloadDocumentFile\(/);
    }
});

test("the client saves the revision it is showing", () => {
    // Browsing history and then downloading must save the file on screen.
    const idx = client.indexOf("downloadDocumentFile(");
    const call = client.slice(idx, idx + 300);
    assert.match(call, /viewRev\?\.revision_id \|\| docRevisionId/);
});

test("the lawyer saves the SUBMITTED revision, whatever is on screen", () => {
    // A reviewer who downloads while reading v1 and files what they saved would
    // file a draft nobody submitted.
    const idx = lawyer.indexOf("downloadDocumentFile(");
    const call = lawyer.slice(idx, idx + 300);
    // The row's OWN revision — submitted while pending, decided once decided.
    // Never `viewRev`, which is whichever older draft is being browsed.
    assert.match(call, /revisionId: doc\.viewRevisionId/);
    assert.ok(!/viewRev\?/.test(call), "the lawyer downloads the browsed revision");
});

/* ══════════════════════════════════════════════════════════════════════════
 * The lawyer's drafting page
 *
 * The one place this page produced a real document — the court-Urdu pleading —
 * went through `generate_standalone`, which takes no idempotency key. A second
 * click made a second document and a second PDF, and a failure returned
 * silently.
 * ══════════════════════════════════════════════════════════════════════════ */

const automation = readFileSync(
    new URL("../src/components/lawyer/DocAutomationPage.jsx", import.meta.url), "utf8");

test("one pleading is one key across create and render", () => {
    // They are two calls only because a create that also rendered would make
    // the retry of a failed render create a second document. Keying them
    // separately reintroduces exactly the duplicate this replaces.
    const fn = api.slice(api.indexOf("export async function pleadingUrduDocumentV2"));
    const body = fn.slice(0, fn.indexOf("\n}\n"));
    assert.match(body, /createDocumentV2\(\{[\s\S]*?\}, key\)/);
    assert.match(body, /generateRevisionV2\(docId, \{[\s\S]*?\}, key\)/);
});

test("a new translation gets a new key", () => {
    // Reusing it would replay the old revision and hand the lawyer a PDF of
    // text they had already replaced.
    const fn = automation.slice(automation.indexOf("const downloadUrduPdf"));
    const body = fn.slice(0, fn.indexOf("\n    };"));
    assert.match(body, /urduKeyedTextRef\.current !== urduText/);
    assert.match(body, /urduKeyRef\.current = null/);
});

test("the key survives a failed attempt so the retry is the same intent", () => {
    const fn = automation.slice(automation.indexOf("const downloadUrduPdf"));
    const body = fn.slice(0, fn.indexOf("\n    };"));
    assert.match(body, /urduKeyRef\.current = urduKeyRef\.current \|\| idempotencyKey\(\)/);
});

test("only the flag falls back to the un-idempotent legacy route", () => {
    // It still works; it just cannot be retried safely, which is why it is the
    // fallback and not the default.
    const fn = automation.slice(automation.indexOf("const downloadUrduPdf"));
    const body = fn.slice(0, fn.indexOf("\n    };"));
    assert.match(body, /v2\.status === 404 && v2\.code === "feature_disabled"/);
    assert.match(body, /await pleadingUrduPdf\(payload\)/);
});

test("a failed pleading download says so", () => {
    // The old code returned silently on error.
    const fn = automation.slice(automation.indexOf("const downloadUrduPdf"));
    const body = fn.slice(0, fn.indexOf("\n    };"));
    assert.match(body, /setUrduIssue\(/);
    assert.match(automation, /\{urduIssue \|\| "Machine-assisted/);
});

test("the pleading is downloaded by revision, not by file path", () => {
    // A V2 document has no file_path; the legacy download route 404s on it.
    const fn = automation.slice(automation.indexOf("const downloadUrduPdf"));
    const body = fn.slice(0, fn.indexOf("\n    };"));
    assert.match(body, /revisionId: v2\.revisionId/);
    assert.match(body, /expectedPdfSha256: v2\.pdfSha256/);
});

/* ══════════════════════════════════════════════════════════════════════════
 * Filing a draft as a document
 *
 * The page's output could only leave as a .doc export: outside the system, no
 * hash, no revision, no authority ever checked. A lawyer could file it and
 * nothing recorded what had been filed.
 * ══════════════════════════════════════════════════════════════════════════ */

test("filing a draft is idempotent and re-keys on edit", () => {
    // Republishing edited prose under the old key returns the OLD revision and
    // tells the lawyer their edits were filed when they were not.
    const fn = automation.slice(automation.indexOf("const publishAsDocument"));
    const body = fn.slice(0, fn.indexOf("\n    };"));
    assert.match(body, /publishedHtmlRef\.current !== bodyHtml/);
    assert.match(body, /publishKeyRef\.current = null/);
    assert.match(body, /publishKeyRef\.current = publishKeyRef\.current \|\| idempotencyKey\(\)/);
});

test("the export is kept, not replaced", () => {
    // Export hands someone a file they will edit; filing fixes an artifact the
    // system can reproduce. They are not alternatives.
    assert.match(automation, /const handleExport = \(\) => \{/);
    assert.match(automation, /Export Word/);
    // Renamed: "File as Document" implied filing with a court, which nothing
    // here does. See "nothing on the drafting page claims to file with a court".
    assert.match(automation, /Save to Documents/);
});

test("an empty draft is refused before a request is made", () => {
    const fn = automation.slice(automation.indexOf("const publishAsDocument"));
    const body = fn.slice(0, fn.indexOf("\n    };"));
    assert.match(body, /nothing in the draft to save/);
});

test("the flag being off is explained, not reported as a failure", () => {
    const fn = automation.slice(automation.indexOf("const publishAsDocument"));
    const body = fn.slice(0, fn.indexOf("\n    };"));
    assert.match(body, /res\.status === 404 && res\.code === "feature_disabled"/);
    assert.match(body, /use Export/);
});

test("the filed PDF is fetched by revision and hash", () => {
    const idx = automation.indexOf("published && (");
    const panel = automation.slice(idx, idx + 900);
    assert.match(panel, /revisionId: published\.revisionId/);
    assert.match(panel, /expectedPdfSha256: published\.pdfSha256/);
});

test("free prose is not offered in the template picker", () => {
    // Listing it among twenty named instruments would imply the system knows
    // what it produces. It renders whatever was typed.
    const fn = api.slice(api.indexOf("export async function listTemplates"));
    const body = fn.slice(0, fn.indexOf("\n}\n"));
    assert.match(body, /include_lawyer_authored/);
    // The client picker never asks for it.
    const effect = client.slice(client.indexOf("listTemplates()"));
    assert.match(effect.slice(0, 200), /listTemplates\(\)/);
    assert.ok(!/includeLawyerAuthored/.test(client),
        "the client picker asks for lawyer-authored prose");
});

/* ══════════════════════════════════════════════════════════════════════════
 * The lawyer's queue tabs
 *
 * The queue was fetched with the default status ("submitted") and the tabs then
 * filtered client-side over that one page. Approved / Returned / Rejected were
 * therefore permanently empty and their counts read 0 while the work existed —
 * and on the server side, return and reject clear `submitted_to`, so no query
 * could have found them however the tab was filtered.
 * ══════════════════════════════════════════════════════════════════════════ */

const myDocs = readFileSync(
    new URL("../src/components/lawyer/MyDocuments.jsx", import.meta.url), "utf8");

test("the selected tab is sent to the server", () => {
    const fn = lawyer.slice(lawyer.indexOf("const load = async"));
    const body = fn.slice(0, fn.indexOf("useEffect(() => { load()"));
    assert.match(body, /const wanted = QUEUE_STATUS_OF\[tab\] \|\| "all"/);
    assert.match(body, /reviewQueueV2\(\{ status: wanted/);
});

test("every tab maps to a status the server accepts", async () => {
    const { QUEUE_FILTERS } = await import("../src/lib/api.js");
    const table = lawyer.slice(lawyer.indexOf("const QUEUE_STATUS_OF"));
    const mapped = [...table.slice(0, table.indexOf("};")).matchAll(/: "([a-z]+)"/g)]
        .map(m => m[1]);
    assert.ok(mapped.length >= 5, "the tab table is missing entries");
    for (const status of mapped) {
        assert.ok(QUEUE_FILTERS.includes(status),
            status + " is not a filter the server allows");
    }
});

test("changing tabs resets the cursor and clears the rows", () => {
    // The cursor names a position in the tab being LEFT and means nothing in
    // the one being entered; leaving the rows up shows documents that are not
    // in the tab just chosen.
    const fn = lawyer.slice(lawyer.indexOf("const changeTab = "));
    const body = fn.slice(0, fn.indexOf("\n    };"));
    assert.match(body, /setQueueCursor\(null\)/);
    assert.match(body, /setDocs\(\[\]\)/);
    assert.match(body, /load\(null, tab\)/);
});

test("a response for a tab the user has left is dropped", () => {
    // A generation ticket catches a response overtaken by a newer request, but
    // not one still "current" by ticket while being about an abandoned tab —
    // two rapid clicks can resolve in either order.
    const fn = lawyer.slice(lawyer.indexOf("const load = async"));
    const body = fn.slice(0, fn.indexOf("useEffect(() => { load()"));
    assert.match(body, /const answered = v2\.data\?\.status;/);
    assert.match(body, /if \(answered && answered !== wanted\) return;/);
    assert.match(body, /if \(!queueGeneration\.isCurrent\(ticket\)\) return;/);
});

test("the tab is not fetched from stale state", () => {
    // Reading statusF inside load would fetch the tab being LEFT, because the
    // setState has not landed in the tick the click happens in.
    const fn = lawyer.slice(lawyer.indexOf("const load = async"));
    assert.match(fn.slice(0, 200), /load = async \(after = null, tab = statusF\)/);
});

test("counts come from the server, not from the loaded page", () => {
    // Counting what a client happens to have loaded is wrong the moment the
    // queue is paginated, and wrong in the direction that hides work.
    const fn = lawyer.slice(lawyer.indexOf("function _tabCount"));
    const body = fn.slice(0, fn.indexOf("\n}"));
    assert.match(body, /if \(counts && counts\[status\] != null\) return counts\[status\]/);
    // The client-side count survives ONLY for the legacy queue, which is
    // unpaginated, so counting what is loaded is accurate there.
    assert.match(body, /if \(!serverFiltered\)/);
});

test("an unknown count renders as unknown, never as zero", () => {
    // Counts arrive with the first page only; a continuation carries null
    // meaning "unchanged". Rendering that as 0 announces an empty queue on
    // every "load more".
    const fn = lawyer.slice(lawyer.indexOf("function _tabCount"));
    const body = fn.slice(0, fn.indexOf("\n}"));
    assert.match(body, /return "—"/);
    assert.ok(!/return 0/.test(body), "an unknown count falls back to zero");
});

test("counts are only overwritten when the server sends them", () => {
    const fn = lawyer.slice(lawyer.indexOf("const load = async"));
    const body = fn.slice(0, fn.indexOf("useEffect(() => { load()"));
    assert.match(body, /if \(counts\) setQueueCounts\(counts\)/);
});

test("the inbox no longer owns the tab or invents its own counts", () => {
    const fn = lawyer.slice(lawyer.indexOf("function ScreenInbox"));
    const body = fn.slice(0, fn.indexOf("function ScreenReview"));
    assert.ok(!/useState\("All"\)/.test(body), "the inbox still owns the tab");
    assert.ok(!/const counts = Object\.fromEntries/.test(body),
        "the inbox still computes its own counts");
});

test("the legacy queue still filters client-side", () => {
    // It takes no status parameter and returns everything unpaginated, so with
    // the flag off the filtering has to happen in the client.
    const fn = lawyer.slice(lawyer.indexOf("function ScreenInbox"));
    const body = fn.slice(0, fn.indexOf("function ScreenReview"));
    assert.match(body, /serverFiltered \|\| statusF === "All" \|\| d\.status === statusF/);
});

/* ══════════════════════════════════════════════════════════════════════════
 * My Documents
 * ══════════════════════════════════════════════════════════════════════════ */

test("a lawyer can find documents they saved earlier", () => {
    // They were reachable only by id, in the session that created them.
    assert.match(myDocs, /myDocumentsV2\(\{ cursor: after \}\)/);
    assert.match(myDocs, /My Documents/);
    assert.match(automation, /<MyDocuments t=\{t\} \/>/);
});

test("the list is paginated rather than fetching everything", () => {
    assert.match(myDocs, /setCursor\(data\?\.next_cursor \|\| null\)/);
    assert.match(myDocs, /Load more/);
});

test("a saved document downloads by revision and hash", () => {
    // A V2 document has no file_path; the legacy download route 404s on it.
    const fn = myDocs.slice(myDocs.indexOf("const download = async"));
    const body = fn.slice(0, fn.indexOf("\n    };"));
    assert.match(body, /revisionId: row\.revision_id/);
    assert.match(body, /expectedPdfSha256: row\.pdf_sha256/);
});

test("a document with no bytes is not offered as a download", () => {
    // An unexplained failure reads as the file having been lost.
    assert.match(myDocs, /row\.downloadable \?/);
    assert.match(myDocs, /No file/);
});

test("the section is silent when the feature is off", () => {
    assert.match(myDocs, /errorCode\(error\) === "feature_disabled"/);
    assert.match(myDocs, /if \(!items \|\| \(items\.length === 0 && !issue\)\) return null;/);
});

/* ══════════════════════════════════════════════════════════════════════════
 * Wording
 * ══════════════════════════════════════════════════════════════════════════ */

test("nothing on the drafting page claims to file with a court", () => {
    // Filing is what a court accepts, and nothing here goes near one. On a
    // legal product that is the kind of wrong word a user acts on.
    const visible = automation.replace(/\/\*[\s\S]*?\*\/|\{\/\*[\s\S]*?\*\/\}/g, "");
    assert.ok(!/File as Document/.test(visible));
    assert.ok(!/Filed PDF/.test(visible));
    assert.ok(!/Filing/.test(visible));

    assert.match(automation, /Save to Documents/);
    assert.match(automation, /Saved PDF/);
});

/* ══════════════════════════════════════════════════════════════════════════
 * Multiple review cycles
 *
 * A decided row has no `submitted_*` at all: the decision cleared them, and the
 * server deliberately does not substitute the document's live pointers, because
 * after a return-and-resubmit those describe somebody else's review.
 * ══════════════════════════════════════════════════════════════════════════ */

test("a decided row can still be opened", () => {
    // Reading submittedRevisionId on a decided row asks for null and falls
    // through to the legacy download route, which 404s on every V2 document.
    const fn = lawyer.slice(lawyer.indexOf("function _mapQueueDoc"));
    const body = fn.slice(0, fn.indexOf("\n}"));
    assert.match(body, /viewRevisionId: d\.submitted_revision_id \?\? d\.reviewed_revision_id/);
    assert.match(body, /viewPdfSha256: d\.submitted_pdf_sha256 \?\? d\.reviewed_pdf_sha256/);
});

test("preview and download read the viewable revision", () => {
    assert.match(lawyer, /revisionId: doc\.viewRevisionId/);
    assert.match(lawyer, /expectedPdfSha256: doc\.viewPdfSha256/);
    // and no preview still asks for the submitted pointer
    assert.ok(!/revisionId: doc\.submittedRevisionId/.test(lawyer));
});

test("the decision still reads the submitted pair, and only that", () => {
    // They are null on a decided row precisely because a decided document
    // cannot be decided again — falling back to the reviewed pair here would
    // let a lawyer re-decide something already closed.
    const fn = lawyer.slice(lawyer.indexOf("const handleDecide"));
    const body = fn.slice(0, fn.indexOf("\n    };"));
    assert.match(body, /expectedPdfSha256: activeDoc\.submittedPdfSha256/);
    assert.match(body, /expectedVersion: activeDoc\.submittedVersion/);
    assert.ok(!/viewPdfSha256/.test(body), "a decided row could be re-decided");
});

/* ══════════════════════════════════════════════════════════════════════════
 * The review limit
 *
 * A 409 like any other on the wire, and completely unlike any other in what a
 * caller should do about it: every other conflict here means "reload and try
 * again", and this one is permanent for that document.
 * ══════════════════════════════════════════════════════════════════════════ */

test("a review limit is never retried", async () => {
    const { isRetryable } = await import("../src/lib/api.js");
    assert.equal(isRetryable(409, { code: "review_limit_reached" }), false);
    // And a 503 carrying it is still not retryable — the code decides, not the
    // status, because retrying loops forever whatever the transport said.
    assert.equal(isRetryable(503, { code: "review_limit_reached" }), false);
});

test("the lawyer is not told to reload when reloading cannot help", () => {
    // The generic 409 branch says "This document changed after you opened it.
    // Reload the queue" — advice that can never work for a document that has
    // been reviewed as many times as it can be.
    const fn = lawyer.slice(lawyer.indexOf("const handleDecide"));
    const body = fn.slice(0, fn.indexOf("\n    };"));

    const limitAt = body.indexOf('code === "review_limit_reached"');
    const genericAt = body.indexOf('status === 409 || code === "conflict"');
    assert.ok(limitAt !== -1, "the review limit is not handled at all");
    assert.ok(limitAt < genericAt,
        "the generic conflict branch swallows the review limit");
    // Split across a string concatenation in the source, so matched in pieces
    // rather than with a regex that has to model the line break.
    assert.ok(body.includes("Ask the client to start a new document"));
    assert.ok(body.includes("will not change this"));
});
