/* One-line summary of a document's statutory-particulars check, for the
 * final screens.
 *
 * Both final screens used to print "Compliance ✓ Verified" on every document,
 * whatever `pleading_rules` had found. Most templates are never checked at all
 * (`checked: false`), and a checked pleading can be missing required
 * particulars — so the badge was false in exactly the cases that matter. A
 * lawyer's approval is not a statutory check either, and must not be shown as
 * one.
 *
 * This reports what the check actually said, and nothing more:
 *   - not run / not applicable  → "Not checked"   (neutral — not a pass)
 *   - every particular present  → "Complete"
 *   - some missing              → "Missing N particulars"
 *
 * Citation verification is a separate check with its own display; it is
 * deliberately NOT folded in here. */

export function complianceSummary(compliance) {
    if (!compliance || compliance.checked !== true) {
        return { label: "Not checked", tone: "neutral" };
    }
    if (compliance.complete === true) {
        return { label: "Complete", tone: "success" };
    }
    const n = Number(compliance.missing);
    if (Number.isFinite(n) && n > 0) {
        return { label: `Missing ${n} particular${n === 1 ? "" : "s"}`, tone: "warn" };
    }
    // Checked, not complete, but no count: never round that up to a pass.
    return { label: "Incomplete", tone: "warn" };
}
