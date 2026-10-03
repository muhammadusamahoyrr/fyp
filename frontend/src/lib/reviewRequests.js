/* Document review requests, client side: what the UI says and allows.
 *
 * Pure functions only, so every wording and every rule is testable without a
 * DOM (DOCUMENT_REVIEW_REQUEST_PLAN.md §10). No fee, price, urgency or
 * reply-time element exists anywhere in this feature -- by decision, not by
 * omission. */

export const NOTE_MAX = 2000;
export const FOCUS_MAX_ITEMS = 5;
export const FOCUS_ITEM_MAX = 120;

/* D4, shown before the Submit button. */
export const CANCEL_LIMIT_NOTICE =
    "Once the lawyer accepts this request you cannot cancel it here; you can cancel only until then.";

export const NO_ENGAGEMENT_NOTICE =
    "You have no active engagement with a lawyer. Hire a lawyer first to share documents.";

/* How a request reads to its client: a label, a pill tone, and a sentence. */
export function requestStatusView(request) {
    const status = request?.status;
    switch (status) {
        case "draft":
            return { label: "Draft", tone: "muted", detail: "Only you can see this." };
        case "submitted":
            return { label: "Sent", tone: "info", detail: "Sent to your lawyer. They have not opened it yet." };
        case "viewed":
            return { label: "Opened by the lawyer", tone: "info", detail: "Your lawyer has opened this request." };
        case "accepted":
            return { label: "Accepted", tone: "low", detail: "Your lawyer has agreed to review this version." };
        case "declined":
            return {
                label: "Declined", tone: "high",
                detail: request?.decline_reason
                    ? `Your lawyer declined: ${request.decline_reason}`
                    : "Your lawyer declined this request.",
            };
        case "cancelled":
            return { label: "Cancelled", tone: "muted", detail: cancelWhy(request?.cancel_reason) };
        default:
            return { label: "Unknown", tone: "muted", detail: "" };
    }
}

export function cancelWhy(reason) {
    if (reason === "client_cancelled") return "You cancelled this request.";
    if (reason === "engagement_ended") return "Cancelled because the engagement with this lawyer ended.";
    if (reason === "document_deleted") return "Cancelled because the document was deleted.";
    return "This request was cancelled.";
}

/* What the client may do with a request in its current state (§10). */
export function requestActions(request) {
    const status = request?.status;
    return {
        edit: status === "draft",
        delete: status === "draft",
        submit: status === "draft",
        cancel: status === "submitted" || status === "viewed",
    };
}

/* Errors with their own wording (§10). `code` is the server's machine code. */
export function requestErrorMessage(code, fallback) {
    switch (code) {
        case "revision_changed":
            return "This version of the document changed since you loaded it. Reload and choose a version again.";
        case "engagement_not_active":
            return "That engagement is no longer active. Choose another lawyer you have engaged.";
        case "open_request_exists":
            return "There is already an open request for this document with this lawyer.";
        case "case_mismatch":
            return "This document belongs to a case. Send it through the engagement on that case.";
        case "stale_state":
            return "This request changed since you loaded it. It has been reloaded — please try again.";
        case "request_accepted":
            return "The lawyer has already accepted this request, so it can no longer be cancelled.";
        case "request_deleted":
            return "That draft was deleted. Start a new request.";
        case "document_unavailable":
            return "The document of this draft no longer exists. Delete the draft.";
        case "transactions_unavailable":
            return "Review requests are temporarily unavailable. Try again shortly.";
        case "not_found":
            return "That request could not be found.";
        default:
            return fallback || "Something went wrong. Please try again.";
    }
}

/* A network failure (status 0) or a 503 may or may not have happened on the
 * server: retrying with the SAME key is safe and is the only right move. */
export function isSafeRetry(status) {
    return status === 0 || status === 503;
}

/* Focus items as the server wants them: trimmed, non-empty, at most five of at
 * most 120 characters. Returns { items, problem }. */
export function normaliseFocus(items) {
    const clean = (items || []).map(s => String(s ?? "").trim()).filter(Boolean);
    if (clean.length > FOCUS_MAX_ITEMS) return { items: clean, problem: `At most ${FOCUS_MAX_ITEMS} focus points.` };
    if (clean.some(s => s.length > FOCUS_ITEM_MAX)) {
        return { items: clean, problem: `Each focus point is at most ${FOCUS_ITEM_MAX} characters.` };
    }
    return { items: clean, problem: null };
}

/* "1,950 / 2,000" — shown always, highlighted near the limit. */
export function counterText(length, max) {
    return `${length.toLocaleString("en-US")} / ${max.toLocaleString("en-US")}`;
}

/* The versions a client may share: generated, with a published file, newest
 * first; the current one first of all. */
export function shareableVersions(revisions, currentRevisionId = null) {
    const ok = (revisions || []).filter(r => r && r.status === "generated" && r.pdf_sha256 && r.revision_id);
    return ok.sort((a, b) => {
        if (a.revision_id === currentRevisionId) return -1;
        if (b.revision_id === currentRevisionId) return 1;
        return (b.version || 0) - (a.version || 0);
    });
}

/* ── Deep links (notifications) ──────────────────────────────────────────────
 *
 * A notification links to /client/review-requests/{id}, which redirects to
 *   /documents?tab=review-requests&request={id}
 * The target is ALWAYS this one same-origin path, built from constants: the id
 * enters only as a validated query VALUE, never as part of a path or a URL, so
 * no input can turn the redirect into a jump elsewhere (no open redirect). */
export const DOCUMENTS_PATH = "/documents";
export const REVIEW_REQUESTS_TAB = "review-requests";

/* Request ids are server-minted uuid4 hex: 32 lowercase hex characters. */
const REQUEST_ID = /^[0-9a-f]{32}$/;
export function isRequestId(value) {
    return typeof value === "string" && REQUEST_ID.test(value);
}

export function reviewRequestDeepLink(id) {
    const params = new URLSearchParams({ tab: REVIEW_REQUESTS_TAB });
    if (isRequestId(id)) params.set("request", id);
    else params.set("missing", "1");            // malformed: the page says "not found"
    return `${DOCUMENTS_PATH}?${params.toString()}`;
}

/* What the Documents page was asked to show. `requestId` is set only for a
 * well-formed id; anything else is `invalid` and is never sent to the server. */
export function readReviewRequestLink(search) {
    const params = new URLSearchParams(typeof search === "string" ? search : "");
    if (params.get("tab") !== REVIEW_REQUESTS_TAB) return { open: false, requestId: null, invalid: false };
    const raw = params.get("request");
    const requestId = isRequestId(raw) ? raw : null;
    return { open: true, requestId, invalid: params.get("missing") === "1" || (raw !== null && !requestId) };
}

export const REQUEST_NOT_FOUND = "Review request not found. It may have been deleted, or the link is not for your account.";
export const DRAFT_LOCKED_NOTICE =
    "The version and the lawyer of a draft cannot be changed. To change them, delete this draft and start a new request.";

/* ── The lawyer's side (Phase 2 Review Queue) ─────────────────────────────── */

export const DECLINE_REASON_MAX = 500;
export const REVIEW_QUEUE_PATH = "/lawyer/documents/review-queue";

/* Lawyer notification deep link: /lawyer/review-requests/{id} redirects here.
 * Same rules as the client's: a fixed path, a validated id as a query value. */
export function lawyerReviewRequestDeepLink(id) {
    const params = new URLSearchParams();
    if (isRequestId(id)) params.set("request", id);
    else params.set("missing", "1");
    return `${REVIEW_QUEUE_PATH}?${params.toString()}`;
}

export function readLawyerReviewLink(search) {
    const params = new URLSearchParams(typeof search === "string" ? search : "");
    const raw = params.get("request");
    const requestId = isRequestId(raw) ? raw : null;
    return { requestId, invalid: params.get("missing") === "1" || (raw !== null && !requestId) };
}

/* A request as its lawyer sees it. */
export function lawyerStatusView(request) {
    switch (request?.status) {
        case "submitted": return { label: "New", tone: "info", detail: "Not opened yet." };
        case "viewed": return { label: "Opened", tone: "info", detail: "You have opened this request." };
        case "accepted": return { label: "Accepted", tone: "low", detail: "You agreed to review this version." };
        case "declined": return { label: "Declined", tone: "high", detail: "You declined this request." };
        case "cancelled": return {
            label: "Cancelled", tone: "muted",
            detail: request?.cancel_reason === "engagement_ended"
                ? "Cancelled because the engagement ended."
                : request?.cancel_reason === "document_deleted"
                    ? "Cancelled because the client deleted the document."
                    : "The client cancelled this request.",
        };
        default: return { label: "Unknown", tone: "muted", detail: "" };
    }
}

/* What the lawyer may do now. Download follows the server's own answer. */
export function lawyerActions(request) {
    const open = request?.status === "submitted" || request?.status === "viewed";
    return {
        markViewed: request?.status === "submitted",
        accept: open,
        decline: open,
        download: Boolean(request?.document_available),
    };
}

export function lawyerErrorMessage(code, fallback) {
    switch (code) {
        case "stale_state":
            return "This request changed while you were looking at it (the client may have cancelled). It has been reloaded.";
        case "invalid_transition":
            return "This request is no longer open, so it cannot be accepted or declined.";
        case "engagement_not_active":
            return "The engagement with this client is no longer active.";
        case "integrity":
            return "The stored file does not match the version the client sent, so it was not downloaded. Please report this.";
        case "artifact_unavailable":
            return "The file for this version could not be read. Try again later.";
        case "not_found":
            return "This request is not available.";
        default:
            return requestErrorMessage(code, fallback);
    }
}

export const LAWYER_REQUEST_NOT_FOUND =
    "Review request not found. It may have been withdrawn, or it was not sent to you.";

/* The Analyzer is synthetic-only: a client's real document is never sent to it
 * from here, and no "Open in Analyzer" control exists until a real-document AI
 * policy, consent and retention are approved. Exported so a test can pin it. */
export const ANALYZER_HANDOFF_ENABLED = false;
