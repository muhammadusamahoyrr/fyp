/* Role-neutral document helpers: plain functions, no screen, no role.
 * Used by the client Vault and review-request screens AND the lawyer Review
 * Queue -- which previously imported the whole client Vault screen for this. */

/** "Today", or a short date ("7 Oct 2026"); "—" for a missing or invalid value. */
export function formatWhen(value, now = new Date()) {
    if (!value) return "—";
    const d = new Date(value);
    if (Number.isNaN(d.getTime())) return "—";
    const sameDay = d.toDateString() === now.toDateString();
    if (sameDay) return "Today";
    return d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}
