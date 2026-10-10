/* Where a notification leads, and how open pages hear about it.
 *
 * WHAT WAS WRONG. The lawyer's notification panel navigated only when a row
 * carried `payload.route`, which almost none do (two dispute notices). Every
 * appointment, hearing, message and engagement notice marked itself read and
 * went nowhere. Its icons were keyed on types the server never sends
 * ("message", "hearing"), so every row showed the same bell, and the sidebar
 * counted unread "message" rows, a type that does not exist: case messages
 * arrive as "case_message".
 *
 * The server's types are the contract (app/core/constants.py NotificationType).
 */

/** The broad kind of a notification type: drives its icon and colour. */
export function notificationCategory(type) {
    const t = String(type || "");
    if (t === "case_message") return "message";
    if (t === "hearing_scheduled" || t === "hearing_reminder" || t === "causelist_listed") return "hearing";
    if (t.startsWith("appointment_")) return "appointment";
    if (t.startsWith("document_") || t.startsWith("review_request_") || t.startsWith("agreement_")) return "document";
    if (t.startsWith("engagement_") || t === "lawyer_assigned" || t === "case_update") return "case";
    if (t.startsWith("payment_") || t.startsWith("subscription_")) return "payment";
    if (t.startsWith("dispute_")) return "dispute";
    return "info";
}

/** The lawyer page a notification opens, and the case to open on it.
 *  Returns null when there is nowhere better than where the lawyer is. */
export function lawyerNotificationTarget(type, payload = {}) {
    const t = String(type || "");
    const caseId = payload?.case_id || null;
    if (t === "case_message" || t === "case_update" || t === "hearing_scheduled" || t === "hearing_reminder"
        || t === "lawyer_assigned" || t.startsWith("engagement_")) {
        return { page: "cases", caseId };
    }
    if (t.startsWith("appointment_")) return { page: "appointments", caseId: null };
    // The document itself, not just the inbox: Document review opens it (2026-10-09).
    if (t.startsWith("document_")) return { page: "documents", caseId: null, docId: payload?.doc_id || null };
    if (t.startsWith("review_request_")) return { page: "review-queue", caseId: null };
    if (t.startsWith("agreement_")) return { page: "agreements", caseId: null };
    if (t.startsWith("payment_")) return { page: "payments", caseId: null };
    if (t.startsWith("dispute_")) return { page: "overseas-disputes", caseId: null };
    if (t === "causelist_listed") return { page: "causelist", caseId: null };
    if (t.startsWith("kyc_") || t === "review_received") return { page: "profile", caseId: null };
    return null;
}

const EVENT = "aai:notification";

/** Tell every open page a notification arrived (from the live socket). */
export function broadcastNotification(n) {
    if (typeof window === "undefined" || !n) return;
    try { window.dispatchEvent(new window.CustomEvent(EVENT, { detail: n })); } catch { /* no DOM */ }
}

/** Listen for live notifications. Returns the unsubscribe function. */
export function onNotification(handler) {
    if (typeof window === "undefined") return () => {};
    const listener = (ev) => { try { handler(ev.detail || {}); } catch { /* a page's handler must not break others */ } };
    window.addEventListener(EVENT, listener);
    return () => window.removeEventListener(EVENT, listener);
}

/** Delay before reconnect attempt `n` (0-based): 1s, 2s, 4s … capped at 30s. */
export function reconnectDelay(n) {
    return Math.min(30000, 1000 * 2 ** Math.max(0, n));
}
