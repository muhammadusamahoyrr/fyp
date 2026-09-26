/* How a stored citation check is shown in the lawyer drafter.
 *
 * The server checks every citation in a draft when it is SAVED, and again —
 * frozen on the artifact — when it is saved to Documents. Both results came
 * back in the API response and neither was ever displayed: the only citation
 * note a lawyer saw was the transient one after an AI reply. Reopening a draft
 * showed nothing at all.
 *
 * Two different things, kept apart on screen:
 *
 *   - the DRAFT check: over the text as last saved. It describes the editor
 *     only until the next keystroke, so the editor marks it stale on edit;
 *   - the DOCUMENT check: frozen on the saved copy. It never goes stale — it
 *     describes that copy, not the editor.
 *
 * `ran: false` is "not checked", never a pass. Existence only, always.
 */

export function verificationView(v) {
    if (!v) return null;
    if (v.ran === false) {
        return { tone: "warn", headline: "Citations not checked",
                 detail: v.reason || "The checker did not run. This is not a finding that they are sound." };
    }
    const c = v.counts || {};
    const n = (k) => Number(c[k]) || 0;
    const parts = [];
    if (n("not_in_corpus")) parts.push(`${n("not_in_corpus")} not found in the corpus`);
    if (n("omitted")) parts.push(`${n("omitted")} cite repealed or omitted provisions`);
    if (n("unverifiable")) parts.push(`${n("unverifiable")} could not be checked`);

    if (n("total") === 0) {
        return { tone: "neutral", headline: "No citations found to check", detail: "" };
    }
    if (n("not_in_corpus") || n("omitted")) {
        return { tone: "danger", headline: parts.join(" · "),
                 detail: `${n("verified")} of ${n("total")} found. Existence only — read every authority.` };
    }
    if (n("unverifiable")) {
        return { tone: "warn", headline: `${n("verified")} of ${n("total")} found · ${parts.join(" · ")}`,
                 detail: "Existence only — read every authority." };
    }
    return { tone: "ok", headline: `${n("verified")} of ${n("total")} found in the corpus`,
             detail: "Existence only — a lawyer must still read every authority." };
}
