/* How a document's review status is presented.
 *
 * WHY THIS IS A MODULE AND NOT A TERNARY
 *
 * The label used to be built inline, as a chain of ternaries ending in
 * `: "Under Review"`. That default arm is the problem: every status nobody had
 * thought about landed in it and was displayed as work in progress. When the
 * migration introduced `needs_reapproval` and `migration_unrecoverable`, both
 * were silently absorbed — one screen called them "Under Review", another
 * called them "Complete" — and a client had no way to learn that their document
 * needed anything at all.
 *
 * Those two mistakes point in the most expensive direction available. "Under
 * Review" makes someone wait for a lawyer who has nothing to review. "Complete"
 * makes someone believe they hold an approved legal document when the approval
 * is precisely what could not be carried across.
 *
 * So the mapping is explicit, unknown statuses are treated as unknown rather
 * than as progress, and the recovery states carry the words the API gave them.
 *
 * WHERE THE WORDING COMES FROM
 *
 * The headline and explanation are the API's (`recovery.headline`,
 * `recovery.explanation`), which are the migration policy's. A component must
 * not paraphrase them: the migration decided what it could and could not prove
 * about someone's legal document, and that judgement is the message. This
 * module decides presentation only — label, tone, and whether to offer the way
 * out. */

export const RECOVERY_ACTION = "regenerate_and_resubmit";

/* Last-resort wording for a recovery status that arrives without its block —
 * an older cached response, or a list endpoint yet to be updated. Deliberately
 * plain and deliberately not reassuring: the failure being guarded against is a
 * document that looks finished when it is not. */
const FALLBACK = {
    needs_reapproval: {
        headline: "Needs approval again",
        explanation: "This document needs to be approved again before it can be used. "
            + "Generate it again and send it for review.",
    },
    migration_unrecoverable: {
        headline: "Needs to be sent again",
        explanation: "This document is not with a lawyer and nobody is working on it. "
            + "Generate it again and send it for review.",
    },
};

const ORDINARY = {
    submitted: { label: "Under Review", tone: "info", done: false },
    approved: { label: "Final", tone: "ok", done: true },
    returned: { label: "Returned", tone: "warn", done: true },
    rejected: { label: "Rejected", tone: "danger", done: true },
    none: { label: "Draft", tone: "muted", done: false },
};

/**
 * @param {{review_status?: string, recovery?: object}} doc
 * @returns {{label: string, tone: string, done: boolean, isRecovery: boolean,
 *           headline: string|null, explanation: string|null,
 *           action: string|null, actionLabel: string|null}}
 */
export function documentStatusView(doc) {
    const status = (doc && doc.review_status) || "none";
    const recovery = (doc && doc.recovery) || FALLBACK[status] || null;

    if (FALLBACK[status]) {
        return {
            label: recovery.headline,
            tone: "warn",
            done: false,          // NEVER done: something is still required.
            isRecovery: true,
            headline: recovery.headline,
            explanation: recovery.explanation,
            action: RECOVERY_ACTION,
            actionLabel: "Generate again and send for review",
        };
    }

    const ordinary = ORDINARY[status] || {
        // An unrecognised status is reported as itself. Guessing is what put
        // two recovery states behind the word "Complete".
        label: status,
        tone: "muted",
        done: false,
    };

    return {
        ...ordinary,
        isRecovery: false,
        headline: null,
        explanation: null,
        action: null,
        actionLabel: null,
    };
}
