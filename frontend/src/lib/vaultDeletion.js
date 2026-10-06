/* Recoverable Vault deletion: what the client is told. Pure, so testable.
 * The warnings come from the server's deletion preview, never guessed. */

const day = iso => {
    const d = new Date(iso);
    return Number.isNaN(d.getTime()) ? "—"
        : d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
};

/* The sentences shown before "Delete", most important first. */
export function deletionWarnings(preview) {
    if (!preview) return [];
    const out = [];
    if (preview.blocked) return [preview.blocked];
    out.push(`It moves to “Recently deleted”. You can restore it for ${preview.recoverable_days} days`
             + ` (until ${day(preview.purge_after)}); after that it is removed for good.`);
    const open = preview.open_review_requests || 0;
    if (open > 0) {
        out.push(`${open === 1 ? "Your open review request" : `Your ${open} open review requests`} for this`
                 + " document will be cancelled, and your lawyer will be told. Restoring the document does not reopen"
                 + (open === 1 ? " it." : " them."));
    }
    for (const a of preview.accepted_reviews || []) {
        out.push(`${a.lawyer_name} accepted a review of version ${a.version} and keeps read-only access to that`
                 + ` version until ${day(a.read_only_until)}, even if you delete the document.`);
    }
    return out;
}

export function deletionErrorMessage(code, fallback) {
    switch (code) {
        case "document_under_review":
            return "This document is with a lawyer for review. Withdraw it from review before deleting it.";
        case "recovery_expired":
            return "This document can no longer be restored: its recovery period has ended.";
        case "not_found":
            return "That document could not be found.";
        default:
            return fallback || "Something went wrong. Please try again.";
    }
}

export function purgeDayText(item) {
    if (!item?.restorable) return "Being removed — it can no longer be restored.";
    return `Restorable until ${day(item.purge_after)}.`;
}
