/* Rich agreement bodies in the browser (2026-10-11).
 *
 * The server is the authority: it sanitises a rich (`body_format: "html"`) body
 * with an allowlist and refuses one that is not already canonical (see
 * backend/app/services/agreement_html.py). This file is the second layer:
 * anything shown from an agreement is cleaned again here with the SAME
 * allowlist before it reaches the page, so a row that somehow skipped the
 * server's check still cannot run a script or load a resource.
 */

const ALLOWED = new Set([
    "P", "DIV", "BR", "H1", "H2", "H3",
    "STRONG", "B", "EM", "I", "U", "S", "STRIKE", "SUB", "SUP", "SPAN", "A",
    "UL", "OL", "LI", "BLOCKQUOTE", "HR",
]);
const ALIGNABLE = new Set(["P", "DIV", "H1", "H2", "H3", "LI", "BLOCKQUOTE"]);
// The toolbar's font families, by the name it writes (as on the server).
export const AGREEMENT_FONTS = ["georgia", "times new roman", "garamond", "arial", "verdana",
    "tahoma", "trebuchet ms", "calibri", "courier new"];
const COLOR = /^(#[0-9a-f]{3}|#[0-9a-f]{6}|rgb\(\s*\d{1,3}\s*,\s*\d{1,3}\s*,\s*\d{1,3}\s*\))$/i;
const SIZE = /^(\d{1,2}(?:\.\d+)?)px$/i;
const URL_OK = /^(https?:\/\/|mailto:)[^\s"'<>]+$/i;

/* Only the allowed properties, with values that match, in a fixed form. */
function cleanStyle(tag, raw) {
    const found = {};
    for (const decl of String(raw || "").split(";")) {
        const at = decl.indexOf(":");
        if (at < 0) continue;
        const prop = decl.slice(0, at).trim().toLowerCase();
        const value = decl.slice(at + 1).trim();
        if (prop === "text-align" && ALIGNABLE.has(tag) && /^(left|center|right|justify)$/i.test(value)) {
            found["text-align"] = value.toLowerCase();
        } else if (tag === "SPAN" && prop === "color" && COLOR.test(value)) {
            found.color = value.toLowerCase();
        } else if (tag === "SPAN" && prop === "font-size") {
            const m = SIZE.exec(value);
            if (m && +m[1] >= 8 && +m[1] <= 48) found["font-size"] = `${Math.round(+m[1])}px`;
        } else if (tag === "SPAN" && prop === "font-family") {
            const first = value.split(",")[0].trim().replace(/^['"]|['"]$/g, "").toLowerCase();
            if (AGREEMENT_FONTS.includes(first)) found["font-family"] = first;
        }
    }
    return ["text-align", "font-family", "font-size", "color"]
        .filter(k => found[k]).map(k => `${k}:${found[k]}`).join(";");
}
const DROP_WITH_CONTENT = new Set(["SCRIPT", "STYLE", "TEMPLATE", "IFRAME", "OBJECT", "EMBED", "SVG", "MATH"]);

const escapeHtml = (s) => String(s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

function cleanNode(node, doc) {
    for (const child of [...node.childNodes]) {
        if (child.nodeType === 3) continue;                    // text
        if (child.nodeType !== 1) { child.remove(); continue; } // comments etc.
        const tag = child.tagName.toUpperCase();
        if (DROP_WITH_CONTENT.has(tag)) { child.remove(); continue; }
        cleanNode(child, doc);
        if (!ALLOWED.has(tag)) {
            // Unwrap: keep the words, lose the element.
            while (child.firstChild) node.insertBefore(child.firstChild, child);
            child.remove();
            continue;
        }
        const style = cleanStyle(tag, child.getAttribute("style"));
        const href = tag === "A" ? (child.getAttribute("href") || "").trim() : "";
        for (const attr of [...child.attributes]) child.removeAttribute(attr.name);
        if (style) child.setAttribute("style", style);
        if (href && URL_OK.test(href)) {
            child.setAttribute("href", href);
            // A link in an agreement opens elsewhere, never in place of it.
            child.setAttribute("target", "_blank");
            child.setAttribute("rel", "noopener noreferrer");
        }
    }
}

/* The allowlisted form of `html`, safe to put into the page. Without a DOM
 * (a server render) it returns the text escaped, never raw markup. */
export function cleanAgreementHtml(html) {
    const src = String(html || "");
    if (typeof DOMParser === "undefined") return escapeHtml(src.replace(/<[^>]*>/g, " "));
    const doc = new DOMParser().parseFromString(`<body>${src}</body>`, "text/html");
    cleanNode(doc.body, doc);
    return doc.body.innerHTML;
}

/* A plain-text body (a template, or an old agreement) as the editor's HTML:
 * one paragraph per line, every character escaped. */
export function textToAgreementHtml(text) {
    return String(text || "")
        .replace(/\r\n?/g, "\n")
        .split("\n")
        .filter(line => line.trim())
        .map(line => `<p>${escapeHtml(line)}</p>`)
        .join("");
}

/* The words in a rich body: for "is there any text?" checks only. */
export function agreementPlainText(html) {
    return String(html || "").replace(/<[^>]*>/g, " ")
        .replace(/&nbsp;/g, " ").replace(/&lt;/g, "<").replace(/&gt;/g, ">")
        .replace(/&amp;/g, "&").replace(/\s+/g, " ").trim();
}
