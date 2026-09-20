/* Escaping values that are about to become markup.
 *
 * WHY THIS IS ITS OWN MODULE
 *
 * The intake export builds a document as a string and hands it to
 * `document.write()`. Every value interpolated into it is markup unless it is
 * escaped, and the values come from the two least trustworthy places in the
 * product: what the client typed about their own dispute, and what a language
 * model wrote from retrieved corpus text.
 *
 * A description containing `<img src=x onerror=...>` executed in a popup that
 * shares the app's origin — able to read the intake token out of localStorage
 * and call the API as the signed-in client. It is "self-XSS" only until the
 * text arrives from somewhere the client did not type it: a pasted document, a
 * voice transcript, or the model's own summary.
 *
 * It lives here rather than inside the component so it can be tested directly.
 * A security control that is only reachable through a mounted React tree is a
 * control nobody writes a test for.
 */

/* The five characters that can break out of either an element body or a quoted
 * attribute value. Ampersand first, or the escapes escape each other. */
export function escapeHtml(value) {
    return String(value ?? "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;");
}

export default escapeHtml;
