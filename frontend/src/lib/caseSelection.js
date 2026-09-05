/* One answer to "which case is this screen working in", for every consumer.
 *
 * There were three derivations of it — the resume hook's, the selector's, and
 * generation's — and they could disagree. The worst pairing: opening a case-B
 * document moved the internal case to B while the selector stayed on A, and
 * generation re-derived from the selector, so extraction pulled case A's facts
 * into a document belonging to case B.
 *
 * A NOTE ON THE STANDALONE SENTINEL
 *
 * `NO_CASE` is a non-empty string, so `Boolean(NO_CASE)` is true. That is
 * exactly how a screen came to report "Ready" for a selection that
 * `resolveCaseId` turns into `null` and that generation then refuses — a
 * control the user could pick and could not complete. Truthiness of the
 * sentinel is never a proxy for "a case is selected"; `isStandalone` is.
 */

import { NO_CASE, resolveCaseId } from "./useDocumentResume.js";

export { NO_CASE };

/**
 * Everything a screen needs to know about the current case, derived once.
 *
 * @param {object} input
 * @param {string} input.selectedCaseId  the selector's value ("" | id | NO_CASE)
 * @param {Array}  input.cases           the case list
 * @param {boolean} input.casesReady     the list has been answered for
 * @param {boolean} input.allowStandaloneCreation
 *        whether THIS screen can create a document with no case. False on the
 *        client document screen: every path there is case-driven — extraction
 *        reads the case description — and with DOCUMENTS_V2 off the legacy
 *        generator requires a case id too. Offering it would be a control that
 *        cannot complete for anybody.
 */
export function caseSelection({
    selectedCaseId, cases, casesReady, allowStandaloneCreation = false,
}) {
    const list = Array.isArray(cases) ? cases : [];
    const isStandalone = selectedCaseId === NO_CASE;
    const caseId = resolveCaseId(selectedCaseId, list);

    // WHICH CASE THE SCREEN IS IN — the single value the resume hook, the
    // selector and generation all read.
    const activeCaseId = isStandalone ? null : caseId;

    // Generation needs a real case unless this screen supports standalone
    // creation. `activeCaseId` being null covers both "standalone selected" and
    // "no cases exist", and neither can be generated from here.
    const canGenerate = Boolean(
        casesReady && (activeCaseId || (isStandalone && allowStandaloneCreation)));

    return {
        activeCaseId,
        isStandalone,
        canGenerate,
        casesReady,
        hasCases: list.length > 0,
        // Why the screen cannot generate, in the user's terms. Null when it can.
        blockedReason: blockedReason({
            casesReady, activeCaseId, isStandalone, allowStandaloneCreation,
            hasCases: list.length > 0,
        }),
    };
}

function blockedReason({ casesReady, activeCaseId, isStandalone,
                         allowStandaloneCreation, hasCases }) {
    if (!casesReady) return "loading";
    if (activeCaseId) return null;
    if (isStandalone && allowStandaloneCreation) return null;
    // A standalone selection this screen cannot act on is reported as such
    // rather than as "no case", so the message can say the true thing.
    if (isStandalone) return "standalone_unsupported";
    return hasCases ? "no_case_selected" : "no_cases";
}
