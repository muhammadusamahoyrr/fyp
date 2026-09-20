/**
 * How lawyer-matching results are described to a client. One place.
 *
 * The service returns three genuinely different verdicts and the chat surface
 * used to flatten them into a list:
 *
 *   matched          candidates with evidence of fit, each carrying a score
 *   general_listing  nothing qualified — verified lawyers offered for BROWSING,
 *                    with `match_score: null` precisely so nothing can present
 *                    them as ranked
 *   none             no verified lawyers at all
 *
 * Plus one the socket adds: `unavailable` — no case to match against, or the
 * lookup failed. That is not "no lawyers found", and telling a client there are
 * none when we simply could not look is the kind of confident wrong answer this
 * codebase keeps having to remove.
 *
 * THE RULE THAT MATTERS
 *
 * `match_score: null` must never render as "0% match". `Math.round((null || 0) *
 * 100)` produced exactly that — a precise-looking score for a measurement that
 * was never made, attached to a lawyer the service explicitly refused to rank.
 */

export const KIND_MATCHED = "matched";
export const KIND_BROWSING = "general_listing";
export const KIND_NONE = "none";
export const KIND_UNAVAILABLE = "unavailable";

/**
 * The score as a percentage string, or null when there is no score.
 *
 * Null is the service saying "not ranked". It is returned as null rather than a
 * zero or an empty string so a caller has to decide what to show, instead of
 * rendering a falsy value that happens to look like a number.
 */
export function matchScoreLabel(score) {
    if (score === null || score === undefined || score === "") return null;
    const n = Number(score);
    if (!Number.isFinite(n)) return null;
    return `${Math.round(n * 100)}% match`;
}

/** The sub-line under a lawyer's name: province, score when ranked, rating. */
export function lawyerSubtitle(lawyer) {
    const bits = [];
    if (lawyer?.province) bits.push(lawyer.province);

    const score = matchScoreLabel(lawyer?.match_score);
    if (score) bits.push(score);

    const rating = Number(lawyer?.rating);
    if (Number.isFinite(rating) && rating > 0) bits.push(`★ ${rating.toFixed(1)}`);

    return bits.join(" · ");
}

/**
 * The heading above the list, and whether a list should be shown at all.
 *
 * @returns {{show: boolean, title: string, ranked: boolean}}
 */
export function matchHeading(kind, { count = 0, suggestLawyer = false } = {}) {
    if (kind === KIND_BROWSING && count > 0) {
        return {
            show: true, ranked: false,
            // Deliberately not "matches". These were NOT matched — the service
            // found nothing that qualified and is offering verified lawyers to
            // look through.
            title: "No specific match — verified lawyers you can browse",
        };
    }
    if (kind === KIND_MATCHED && count > 0) {
        return {
            show: true, ranked: true,
            title: suggestLawyer
                ? "AI reached its limit — consult a lawyer"
                : "Connect with a lawyer for personalized advice",
        };
    }
    // `none` and `unavailable` both show no list. They differ in what may be
    // SAID, which is the notice's job — not this function's.
    return { show: false, ranked: false, title: "" };
}

/**
 * What to tell the client when no list is shown.
 *
 * `unavailable` must not claim there are no lawyers: we did not find out.
 */
export function matchFallbackNotice(kind, notice) {
    if (typeof notice === "string" && notice.trim()) return notice.trim();
    if (kind === KIND_NONE) return "No verified lawyers are available right now.";
    if (kind === KIND_UNAVAILABLE) {
        return "Lawyer matching is unavailable for this conversation.";
    }
    return "";
}
