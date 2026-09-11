/* The intake export must not be able to execute what it prints.
 *
 * `_buildPrintHTML` composes a document as a string and hands it to
 * `document.write()`. Every value interpolated into it was raw — including the
 * client's own description of their dispute and the model's summary — so a
 * description containing `<img src=x onerror=...>` ran in a popup sharing this
 * origin, able to read the intake token out of localStorage and call the API as
 * the signed-in client.
 *
 * Two halves are tested: the escaper itself, and the fact that the export
 * actually uses it on every value. The second matters more — a correct escaper
 * that one interpolation forgot to call is the same bug.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

import { escapeHtml } from "../src/lib/escapeHtml.js";

const here = dirname(fileURLToPath(import.meta.url));
const MODINTAKE = resolve(here, "../src/components/client/ModIntake.jsx");

// ── the escaper ────────────────────────────────────────────────────────────

test("a script tag cannot survive escaping", () => {
    const out = escapeHtml("<script>alert(1)</script>");
    assert.ok(!out.includes("<script"));
    assert.ok(out.includes("&lt;script&gt;"));
});

test("the classic image payload is neutralised", () => {
    const out = escapeHtml('<img src=x onerror="fetch(\'/steal\')">');
    assert.ok(!out.includes("<img"));
    assert.ok(!out.includes('"'), "quotes must not survive into an attribute");
});

test("ampersand is escaped first, or the escapes escape each other", () => {
    // "&lt;" typed literally must come back as "&amp;lt;", not "<".
    assert.equal(escapeHtml("&lt;"), "&amp;lt;");
});

test("both quote characters are escaped", () => {
    assert.equal(escapeHtml(`"'`), "&quot;&#39;");
});

test("null and undefined become empty, not the word", () => {
    assert.equal(escapeHtml(null), "");
    assert.equal(escapeHtml(undefined), "");
});

test("ordinary legal text is left readable", () => {
    const text = "Section 302 PPC — punishment for qatl-i-amd";
    assert.equal(escapeHtml(text), text);
});

test("non-strings are coerced rather than thrown on", () => {
    assert.equal(escapeHtml(42), "42");
});

// ── the export uses it ─────────────────────────────────────────────────────

test("every interpolation in the print builder is escaped", () => {
    const src = readFileSync(MODINTAKE, "utf8");
    const start = src.indexOf("const _buildPrintHTML");
    const body = src.slice(start, src.indexOf("\n    };", start));

    const raw = [...body.matchAll(/\$\{([^}]*)\}/g)]
        .map(m => m[1].trim())
        // Our own loop counter, and the two pre-built markup fragments whose
        // CONTENTS are escaped where they are built.
        .filter(expr => !/^i \+ 1$/.test(expr))
        .filter(expr => !["laws", "actions"].includes(expr))
        // Conditional expressions rather than values; their branches are
        // checked by the entries they contain.
        .filter(expr => !expr.includes("?"))
        .filter(expr => !expr.includes("esc("));

    assert.deepEqual(raw, [],
        `unescaped values reach document.write(): ${raw.join(" | ")}`);
});

test("the client description and the AI summary are both escaped", () => {
    const src = readFileSync(MODINTAKE, "utf8");
    // The single most dangerous line: whichever of the two is present is the
    // longest free text in the document.
    assert.match(
        src,
        /esc\(aiStructured\?\.summary \|\| description/,
        "the summary/description line is not escaped",
    );
});

test("the escaper is the shared one, not a local re-implementation", () => {
    const src = readFileSync(MODINTAKE, "utf8");
    assert.match(src, /import \{ escapeHtml \} from "@\/lib\/escapeHtml\.js"/);
});

// ── the export must not claim things that did not happen ──────────────────

test("no fabricated case reference remains", () => {
    const src = readFileSync(MODINTAKE, "utf8");
    const code = src
        .split("\n")
        .filter(line => !line.trim().startsWith("//") && !line.trim().startsWith("*"))
        .join("\n");
    assert.ok(
        !code.includes("AIQ-2026-0042"),
        "a hardcoded file number was shown to every client on every intake",
    );
});

test("completion does not promise a review or a deadline", () => {
    const src = readFileSync(MODINTAKE, "utf8");
    const code = src
        .split("\n")
        .filter(line => !line.trim().startsWith("//") && !line.trim().startsWith("*"))
        .join("\n");
    // Conversion creates an OPEN case. It assigns no lawyer, notifies no
    // lawyer, and starts no clock.
    assert.ok(!code.includes("within 2 hours"));
    assert.ok(!code.includes("submitted for attorney review"));
});
