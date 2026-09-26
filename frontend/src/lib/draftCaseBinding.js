/* Which case a lawyer's draft belongs to, decided ONCE when the editor opens.
 *
 * THE BUG THIS REPLACES
 *
 * The editor read its case from the page's "Case context" selector on every
 * render. Opening a draft saved under Case A while Case B was selected meant:
 * the AI was grounded in Case B's facts, Save rewrote the draft's `case_id` to
 * B, and "Save to Documents" filed it with no case at all. The server could not
 * catch any of it — the lawyer may legitimately act on both cases, so every
 * request was individually authorised. Two matters' facts mixed silently.
 *
 * THE RULE
 *
 *   - A saved draft is bound to ITS OWN `case_id`, including an explicit null
 *     (a caseless draft stays caseless — it is never adopted by whatever case
 *     happens to be selected).
 *   - A new document is bound to the case selected at the moment it is opened.
 *   - The binding does not change while the editor is open.
 *   - If a draft's case cannot be loaded, the binding is "unavailable" and the
 *     case-dependent actions are blocked rather than silently re-pointed.
 *
 * States: "none" (no case, by choice), "bound", "loading", "unavailable".
 */

export const NO_CASE = Object.freeze({ state: "none", caseId: null, caseObj: null });

export function bindingForNewDocument(selectedCaseObj) {
    return selectedCaseObj
        ? { state: "bound", caseId: selectedCaseObj._id, caseObj: selectedCaseObj }
        : NO_CASE;
}

/* The binding to show while `bindingForDraft` is still resolving. */
export function pendingBindingForDraft(draft) {
    const caseId = draft?.case_id ?? null;
    return caseId ? { state: "loading", caseId, caseObj: null } : NO_CASE;
}

/* `cases` is the page's (possibly partial) case list; `fetchCase(id)` resolves
 * `{ data, error }` for one case; `mapCase` shapes a raw case like the list. A
 * case missing from the list is fetched, not assumed gone — the list is one
 * page, and "not on page one" is not "no access". */
export async function bindingForDraft(draft, cases, fetchCase, mapCase) {
    const caseId = draft?.case_id ?? null;
    if (!caseId) return NO_CASE;

    const listed = (cases || []).find(c => c._id === caseId);
    if (listed) return { state: "bound", caseId, caseObj: listed };

    try {
        const { data, error } = await fetchCase(caseId);
        if (data && !error) return { state: "bound", caseId, caseObj: mapCase(data) };
    } catch {
        /* treated as unavailable below */
    }
    return { state: "unavailable", caseId, caseObj: null };
}

/* Save, AI drafting and Save-to-Documents all write or read case-bound data;
 * none may run until the case is known. */
export function caseActionsBlocked(binding) {
    return !binding || binding.state === "loading" || binding.state === "unavailable";
}

/* The case id to send with a request. Only ever the binding's own. */
export function boundCaseId(binding) {
    return binding?.state === "bound" ? binding.caseId : null;
}
