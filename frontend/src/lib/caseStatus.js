/* What counts as a real case, in one place.
 *
 * WHY THIS MODULE EXISTS
 *
 * Intake creates a case as a DRAFT so the AI analysis has a real `case_id` to
 * run against. It becomes `open` only when the client confirms it at the end of
 * the intake. Until then it is not a case anyone has filed, chosen a lawyer
 * for, or agreed to — the server refuses to match it, engage a lawyer for it,
 * or book against it.
 *
 * The browser had no equivalent rule, and `GET /cases` returns the client's own
 * drafts (correctly — they are theirs). So every screen that listed cases
 * presented drafts as real ones, four different ways:
 *
 *   ModOverview    counted them toward "N cases open" — the exact word a draft
 *                  is not
 *   ModTracking    gave them a "Filed" date, and made the newest one the
 *                  DEFAULT active case, displacing a real matter
 *   ModDocuments   offered them in the case picker for generating documents
 *   ModLawyers     offered them in the hire-a-lawyer picker, where the server
 *                  then refused the request
 *
 * Four ad-hoc filters would have been four chances to miss the fifth screen.
 * This is one predicate, imported by all of them, so adding a surface means
 * finding this module rather than reinventing the rule.
 */

/* Statuses that mean "this case has ended". Kept beside the draft rule because
 * every caller that cares about one cares about the other. */
const ENDED = ["closed", "dismissed"];

/* Every status the server can give a case. Anything outside this set is a case
 * this build does not understand.
 *
 * FAIL CLOSED, NOT OPEN. The first version tested `status !== "draft"`, so a
 * case with a missing or unrecognised status counted as confirmed AND active —
 * it appeared in "N cases open" and in every picker. `create_case` always sets
 * a status, so a case without one is corrupt or comes from a newer server, and
 * neither is something to present to a client as a live legal matter.
 *
 * Hiding a corrupt row is recoverable; presenting one as an open case, in a
 * product where that number means "matters you have running", is not. */
const KNOWN = ["draft", "open", "pending_lawyer", "in_progress", ...ENDED];

function statusOf(c) {
    return c?.status ?? "";
}

export function isDraftCase(c) {
    return statusOf(c) === "draft";
}

export function isEndedCase(c) {
    return ENDED.includes(statusOf(c));
}

/* True when this build does not recognise the case's status at all. */
export function isUnknownCase(c) {
    return !KNOWN.includes(statusOf(c));
}

/* VISIBILITY and CLAIMS are different questions, and an unrecognised status
 * belongs on opposite sides of them.
 *
 * Hiding a case is the worse failure. A client who cannot see their own matter
 * cannot act on it, and a status this build does not recognise — an older
 * fixture, a field the server stopped sending, a state added after this
 * deploy — is not a reason to make their case disappear. An inflated count is
 * cosmetic; a missing case is not.
 *
 * Asserting is the other way round. A count labelled "cases open" is a claim,
 * and it must not include a case whose status we cannot read.
 *
 * The first version failed closed on both and made two ordinary
 * status-less fixtures vanish from the documents screen — which is exactly the
 * harm described above, found by the tests that already covered it. */

/* Cases to SHOW as the client's own: everything except an unconfirmed draft.
 * An ended case stays — a closed matter belongs in a history. So does a case
 * with a status we do not recognise. */
export function confirmedCases(cases) {
    return (Array.isArray(cases) ? cases : []).filter(c => !isDraftCase(c));
}

/* Cases to COUNT as live. Drafts and ended cases are out, and so is an
 * unrecognised status: this number is a statement about what is running. */
export function activeCases(cases) {
    return confirmedCases(cases)
        .filter(c => !isEndedCase(c) && !isUnknownCase(c));
}

/* Cases a lawyer can still be asked to take: live, unassigned, and with no
 * request already pending. `pendingByCase` is keyed by case id. */
export function hireableCases(cases, pendingByCase = {}) {
    return activeCases(cases).filter(
        c => !c.lawyer_id && !pendingByCase[c._id || c.id],
    );
}

export default {
    isDraftCase, isEndedCase, isUnknownCase,
    confirmedCases, activeCases, hireableCases,
};
