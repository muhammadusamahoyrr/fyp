/* How a document's review status is presented to the person who owns it.
 *
 * The migration can leave a document in `needs_reapproval` or
 * `migration_unrecoverable`. Neither was handled anywhere in the UI, so both
 * fell through to the default arm of a chain of ternaries and were displayed as
 * "Under Review" — and, on the progress list, as "Complete".
 *
 * Both are false, and false in the direction that costs the most: a client
 * looking at "Under Review" waits for a lawyer who has nothing to review, and a
 * client looking at "Complete" believes they have an approved legal document
 * when the approval is exactly what could not be carried over. Neither is told
 * that the way out is to generate it again.
 *
 * The wording itself comes from the API (`recovery.headline` /
 * `recovery.explanation`), which gets it from the migration policy — so the
 * explanation a client reads is the one the migration decided, not a guess made
 * in a component. This module decides only PRESENTATION: label, tone, and
 * whether to offer the way out. */
import test from "node:test";
import assert from "node:assert/strict";

import {
    documentStatusView,
    RECOVERY_ACTION,
} from "../src/lib/documentStatus.js";

const NEEDS = {
    review_status: "needs_reapproval",
    recovery: {
        state: "needs_reapproval",
        headline: "Needs approval again",
        explanation: "This document was approved before, but we could not carry that approval forward.",
        next_action: "regenerate_and_resubmit",
        blocks_use: true,
    },
};

const UNRECOVERABLE = {
    review_status: "migration_unrecoverable",
    recovery: {
        state: "migration_unrecoverable",
        headline: "Needs to be sent again",
        explanation: "This document was waiting for a lawyer, but the version that was sent could not be recovered.",
        next_action: "regenerate_and_resubmit",
        blocks_use: true,
    },
};

/* ── the ordinary states still read the way they always did ───────────────── */

test("the ordinary review states keep their labels", () => {
    assert.equal(documentStatusView({ review_status: "submitted" }).label, "Under Review");
    assert.equal(documentStatusView({ review_status: "approved" }).label, "Final");
    assert.equal(documentStatusView({ review_status: "returned" }).label, "Returned");
    assert.equal(documentStatusView({ review_status: "rejected" }).label, "Rejected");
    assert.equal(documentStatusView({ review_status: "none" }).label, "Draft");
    assert.equal(documentStatusView({}).label, "Draft");
});

test("an ordinary state is not a recovery state", () => {
    for (const s of ["none", "submitted", "approved", "returned", "rejected"]) {
        const view = documentStatusView({ review_status: s });
        assert.equal(view.isRecovery, false, s);
        assert.equal(view.action, null, s);
        assert.equal(view.explanation, null, s);
    }
});

/* ── the recovery states are never dressed up as progress ─────────────────── */

for (const [name, doc] of [["needs_reapproval", NEEDS],
                           ["migration_unrecoverable", UNRECOVERABLE]]) {
    test(`${name} is never shown as pending, approved or complete`, () => {
        const view = documentStatusView(doc);
        for (const forbidden of ["Under Review", "Final", "Complete",
                                 "Approved", "Pending", "In progress"]) {
            assert.notEqual(view.label, forbidden);
        }
        assert.equal(view.isRecovery, true);
        assert.equal(view.done, false);
        assert.equal(view.tone, "warn");
    });

    test(`${name} shows the API's own explanation`, () => {
        // Not wording invented here: the client must read what the migration
        // policy decided, so every surface says the same thing.
        const view = documentStatusView(doc);
        assert.equal(view.label, doc.recovery.headline);
        assert.equal(view.explanation, doc.recovery.explanation);
    });

    test(`${name} offers the way out`, () => {
        const view = documentStatusView(doc);
        assert.equal(view.action, RECOVERY_ACTION);
        assert.ok(view.actionLabel.length > 0);
    });
}

/* ── the states are recognised even without the API block ─────────────────── */

test("a recovery status with no recovery block still refuses to look normal", () => {
    // An older cached response, or a list endpoint that has not been updated.
    // Falling through to "Under Review" is the exact bug being fixed, so the
    // fallback must be safe rather than pretty.
    const view = documentStatusView({ review_status: "needs_reapproval" });
    assert.equal(view.isRecovery, true);
    assert.notEqual(view.label, "Under Review");
    assert.equal(view.action, RECOVERY_ACTION);
    assert.ok(view.explanation);
});

/* ── the surfaces actually use it ─────────────────────────────────────────── */

import { readFileSync } from "node:fs";

const CLIENT_DOCS = readFileSync(
    new URL("../src/components/client/ModDocuments.jsx", import.meta.url), "utf8");
const LAWYER_DOCS = readFileSync(
    new URL("../src/components/lawyer/MyDocuments.jsx", import.meta.url), "utf8");

test("the client document surface uses the shared status view", () => {
    assert.ok(/documentStatusView/.test(CLIENT_DOCS),
              "ModDocuments must derive its label from the shared helper");
});

test("the owner list uses the shared status view", () => {
    assert.ok(/documentStatusView/.test(LAWYER_DOCS),
              "MyDocuments must derive its label from the shared helper");
});

test("the client surface no longer defaults every unknown status to Under Review", () => {
    // The original chain ended in `: "Under Review"`, which is what swallowed
    // both recovery states.
    assert.ok(!/reviewStatus === "rejected" \? "Rejected" : "Under Review"/
              .test(CLIENT_DOCS));
});
