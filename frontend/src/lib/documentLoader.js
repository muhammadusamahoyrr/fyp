/* Load one document for reopening, from whichever backend holds it.
 *
 * THE BUG THIS FIXES
 *
 * Generation falls back to the legacy route while DOCUMENTS_V2 is off, and the
 * id it returns is remembered for refresh. Restoration then asked ONLY the V2
 * detail route — which answers every request with `404 feature_disabled` while
 * the flag is off. So a document generated a moment ago could not be reopened
 * after a refresh, on the default configuration.
 *
 * THE RULE
 *
 * V2 first. Fall back to the legacy route ONLY on `feature_disabled` — the flag
 * saying "V2 is not here". Every other failure is passed through unchanged:
 *
 *   - a network error must not be retried against a different backend and
 *     reported as that backend's answer;
 *   - 403/404 from V2 is a real verdict about THIS document, and asking the
 *     legacy route instead would turn "you may not see this" into a second
 *     opinion.
 *
 * The functions are injected rather than imported, so this module never pulls
 * the network client into a test that did not ask for it.
 */

export function isFeatureDisabled(res) {
    return res?.status === 404 && res?.error?.code === "feature_disabled";
}

/* A legacy `DocumentOut` in the V2 detail shape `restoreStateFromDocument`
 * reads. `source: "legacy"` is how that function knows there is no revision to
 * name and that `status` — not a revision id — says whether a PDF exists. */
export function legacyDocumentToDetail(doc) {
    if (!doc) return null;
    const id = doc._id ?? doc.id ?? null;
    if (!id) return null;
    return {
        id,
        source: "legacy",
        case_id: doc.case_id ?? null,
        title: doc.title || "",
        review_status: doc.review_status || "none",
        recovery: null,
        legacy_status: doc.status || null,
        // Legacy keeps the lawyer's note in its own field.
        lawyer_note: doc.lawyer_note ?? null,
        compliance: doc.compliance ?? null,
        verification: doc.verification ?? null,
        current_version: 0,
        current_revision: null,
    };
}

export async function loadDocumentDetail(docId, { getV2, getLegacy }) {
    const v2 = await getV2(docId);
    if (!isFeatureDisabled(v2)) return v2;

    const legacy = await getLegacy(docId);
    if (legacy?.error || !legacy?.data) return legacy;
    return { ...legacy, data: legacyDocumentToDetail(legacy.data) };
}

const DECIDED = new Set(["approved", "returned", "rejected"]);

/* The review state a waiting client polls for, from either backend's detail.
 *
 * WHY NOT THE CASE LIST. Polling used `GET /documents/case/{id}` and searched
 * it for this document. That route's response model is the legacy
 * `DocumentOut`, which REQUIRES `status` — a field a V2-native document does
 * not have — so with V2 on the poll failed validation, and a client whose
 * lawyer had already decided kept reading "waiting for lawyer". It also needed
 * a case id, so a caseless document was never polled at all.
 *
 * THE NOTE. V2 keeps one `review_note`: the client's note while the document
 * is submitted, overwritten with the lawyer's when they decide. Reading it
 * before a decision would show the client their own note as the lawyer's
 * reply, so it is the lawyer's note only once the status is a decision.
 * Legacy has a separate `lawyer_note`. */
export function reviewStateFromDetail(detail) {
    if (!detail || !detail.review_status) return null;
    const status = detail.review_status;
    const lawyerNote = detail.source === "legacy"
        ? detail.lawyer_note || ""
        : (DECIDED.has(status) ? detail.review_note || "" : "");
    return { reviewStatus: status, recovery: detail.recovery || null, lawyerNote };
}
