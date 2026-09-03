/* Run: npm run test:trust  (node --test, no test dependency)
 *
 * These cover the rule every trust signal shares: it may only say what the
 * backend can actually support. Overstating is the failure mode that matters —
 * an answer that looks better sourced than it is, a link that promises a
 * document nobody holds, a "supported" verdict on a repealed section.
 */
import test from "node:test";
import assert from "node:assert/strict";

import {
    MATCHED, UNRESOLVED, RETRIEVED, REPEALED,
    CITATION_GROUPS, SUPPORT_ORDER,
    normaliseCitation, normaliseCitations, citationsInGroup, citationSummary,
    repealNote, sortClaims, claimWarnings, shortRequestId, copyText,
    safeExternalUrl, auditNotice,
} from "../src/lib/trust.js";

/* node 24 defines `navigator` as a getter-only global, so it is swapped with
 * defineProperty rather than assignment. */
function withGlobals(values, fn) {
    const saved = Object.entries(values).map(([k]) => [
        k, Object.getOwnPropertyDescriptor(globalThis, k)]);
    for (const [k, v] of Object.entries(values)) {
        Object.defineProperty(globalThis, k, {
            value: v, configurable: true, writable: true });
    }
    const restore = () => {
        for (const [k, d] of saved) {
            if (d) Object.defineProperty(globalThis, k, d);
            else delete globalThis[k];
        }
    };
    return Promise.resolve(fn()).finally(restore);
}

/* ── citation status ──────────────────────────────────────────────────── */

test("a matched citation keeps its status", () => {
    const c = normaliseCitation({ statute: "PPC 1860", section: "302", status: "matched" });
    assert.equal(c.status, MATCHED);
    assert.equal(c.label, "PPC 1860 §302");
});

test("an unknown status degrades to retrieved, never to matched", () => {
    // Overstating what an answer cited is the one direction that misleads.
    for (const status of [undefined, null, "", "verified", "confirmed", "MATCHED", 1]) {
        assert.equal(normaliseCitation({ statute: "X", status }).status, RETRIEVED);
    }
});

test("there is no verified state", () => {
    // A section existing in the corpus is not evidence that it says what the
    // answer claims, nor that it governs the question.
    assert.deepEqual(CITATION_GROUPS.map(g => g.key), [MATCHED, UNRESOLVED, RETRIEVED]);
});

test("cited groups lead, consulted trails", () => {
    assert.equal(CITATION_GROUPS[0].key, MATCHED);
    assert.equal(CITATION_GROUPS.at(-1).key, RETRIEVED);
});

test("every group has wording for both audiences", () => {
    for (const g of CITATION_GROUPS) {
        assert.ok(g.lawyer && g.client, `${g.key} is missing a caption`);
    }
});

test("a citation with no label is dropped rather than rendered blank", () => {
    const out = normaliseCitations([{ statute: "", section: "" }, { statute: "PPC 1860" }]);
    assert.equal(out.length, 1);
});

test("grouping puts each citation in exactly one group", () => {
    const list = normaliseCitations([
        { statute: "A", status: "matched" },
        { statute: "B", status: "unresolved" },
        { statute: "C", status: "retrieved" },
        { statute: "D" },
    ]);
    const sizes = CITATION_GROUPS.map(g => citationsInGroup(list, g.key).length);
    assert.deepEqual(sizes, [1, 1, 2]);
    assert.equal(sizes.reduce((a, b) => a + b), list.length);
});

/* ── the sources toggle must not overstate ────────────────────────────── */

test("the summary counts what was CITED, not what was retrieved", () => {
    // Counting everything retrieved under a "cited" label is the original bug
    // this whole area exists to fix: retrieval telemetry wearing a citation
    // label. 83% of answers cited a section that was never retrieved.
    const list = normaliseCitations([
        { statute: "A", status: "matched" },
        { statute: "B", status: "retrieved" },
        { statute: "C", status: "retrieved" },
    ]);
    const s = citationSummary(list);
    assert.equal(s.cited, 1);
    assert.equal(s.total, 3);
    assert.match(s.label, /Cited in this answer \(1\)/);
});

test("with nothing cited the label says consulted, not cited", () => {
    const list = normaliseCitations([{ statute: "A", status: "retrieved" }]);
    assert.match(citationSummary(list).label, /Sources consulted \(1\)/);
});

test("an unresolved citation still counts as cited by the answer", () => {
    // It IS what the answer cited; we just cannot show where it came from.
    const list = normaliseCitations([{ statute: "A", status: "unresolved" }]);
    const s = citationSummary(list);
    assert.equal(s.cited, 1);
    assert.equal(s.unresolved, 1);
});

/* ── source links ─────────────────────────────────────────────────────── */

test("a statute is openable only when the server stamped a source_url", () => {
    // The backend stamps it only when the document is really held — about half
    // the corpus by chunk count. Empty means no document, never a 404.
    const held = normaliseCitation({ statute: "PPC 1860", source: "ppc.pdf",
                                     source_url: "/api/v1/ai/source/ppc.pdf" });
    const absent = normaliseCitation({ statute: "Punjab Tenancy Act 1887",
                                       source: "punjab-tenancy-act-1887.pdf" });
    assert.equal(held.sourceUrl, "/api/v1/ai/source/ppc.pdf");
    assert.equal(absent.sourceUrl, "");
});

test("a corpus document is never offered as a plain anchor", () => {
    // /ai/source is bearer-authenticated like every other API route, and a new
    // tab carries no Authorization header — an <a href> would open a 401 page.
    // It has to go through api.openSourceDocument, so `href` stays empty.
    const c = normaliseCitation({ statute: "PPC 1860", source: "ppc.pdf",
                                  source_url: "/api/v1/ai/source/ppc.pdf" });
    assert.equal(c.href, "", "a credentialed API path must not become an anchor");
    assert.ok(c.sourceUrl);
});

test("a source filename is never turned into a link by the client", () => {
    // The filename is metadata; only the server knows whether it resolves.
    const c = normaliseCitation({ statute: "X", source: "some-act.pdf" });
    assert.equal(c.href, "");
    assert.equal(c.sourceUrl, "");
    assert.equal(c.source, "some-act.pdf", "the filename is still shown as text");
});

test("a judgment links to the court's own document", () => {
    // External and public, so a real anchor — it needs none of our credentials.
    const j = normaliseCitation({ type: "judgment", statute: "2026LHC4194",
                                  url: "https://sys.lhc.gov.pk/x.pdf" });
    assert.equal(j.judgment, true);
    assert.equal(j.href, "https://sys.lhc.gov.pk/x.pdf");
    assert.equal(j.sourceUrl, "", "a judgment is not fetched from our corpus route");
});

test("a judgment falls back to its source when no url was sent", () => {
    const j = normaliseCitation({ type: "judgment", statute: "2026LHC4194",
                                  source: "https://sys.lhc.gov.pk/y.pdf" });
    assert.equal(j.href, "https://sys.lhc.gov.pk/y.pdf");
});

test("the linkable count covers both kinds of openable source", () => {
    const list = normaliseCitations([
        { type: "judgment", statute: "J", url: "https://x/y.pdf" },
        { statute: "S", source_url: "/api/v1/ai/source/a.pdf" },
        { statute: "N", source: "not-held.pdf" },
    ]);
    assert.equal(citationSummary(list).linkable, 2);
});

/* ── repeal ───────────────────────────────────────────────────────────── */

test("unknown currency is never treated as in force", () => {
    for (const currency of [undefined, "", "unknown", "in_force", "current"]) {
        assert.equal(normaliseCitation({ statute: "X", currency }).currency, "unknown");
    }
});

test("a repeal note names the instrument and scopes it to its province", () => {
    // A section killed by a Punjab notification is alive in Sindh; asserting it
    // dead nationally would be a false statement of law in three provinces.
    assert.equal(
        repealNote({ currency: REPEALED, instrument: "Act XI of 2015",
                     date: "2015-04-01", jurisdiction: "punjab" }),
        "repealed by Act XI of 2015 2015-04-01 (punjab only)");
});

test("a federal repeal is not scoped to a province", () => {
    const note = repealNote({ currency: REPEALED, instrument: "Act II of 1997",
                              jurisdiction: "federal" });
    assert.equal(note, "repealed by Act II of 1997");
});

test("a repeal we know nothing more about produces no note, not a false one", () => {
    assert.equal(repealNote({ currency: REPEALED }), "");
    assert.equal(repealNote({ currency: "unknown", instrument: "Act X" }), "");
    assert.equal(repealNote(null), "");
});

/* ── claim support ────────────────────────────────────────────────────── */

test("a repealed claim sorts above every support verdict", () => {
    // The source can genuinely say what the claim says and still have been
    // struck from the books.
    const sorted = sortClaims([
        { support: "supported", currency: "unknown" },
        { support: "supported", currency: REPEALED },
        { support: "unsupported", currency: "unknown" },
    ]);
    assert.equal(sorted[0].currency, REPEALED);
    assert.equal(sorted[1].support, "unsupported");
});

test("unassessed is not sorted as if it were support", () => {
    // A missing verdict is not evidence of support.
    assert.ok(SUPPORT_ORDER.indexOf("unassessed") < SUPPORT_ORDER.indexOf("supported"));
});

test("warnings count what a user must see without opening a panel", () => {
    const w = claimWarnings([
        { support: "supported", currency: REPEALED },
        { support: "unsupported", currency: "unknown" },
        { support: "partial", currency: "unknown" },
        { support: "supported", currency: "unknown" },
    ]);
    assert.deepEqual(w, { repealed: 1, unsupported: 1, partial: 1 });
});

test("no claims produces no warnings rather than throwing", () => {
    assert.deepEqual(claimWarnings(null), { repealed: 0, unsupported: 0, partial: 0 });
    assert.deepEqual(sortClaims(undefined), []);
    assert.deepEqual(normaliseCitations(undefined), []);
    assert.equal(citationSummary(null).total, 0);
});

/* ── the request id ───────────────────────────────────────────────────── */

test("a long request id is shortened for display", () => {
    assert.equal(shortRequestId("abcdefgh12345678"), "abcdefgh…");
});

test("a short request id is shown whole", () => {
    assert.equal(shortRequestId("req-abc"), "req-abc");
    assert.equal(shortRequestId(null), "");
});

test("copy falls back when the clipboard API is unavailable", async () => {
    // navigator.clipboard is undefined outside a secure context, which includes
    // the plain-http LAN setup this project is demoed on.
    const calls = [];
    await withGlobals({
        navigator: {},
        document: {
            createElement: () => ({ setAttribute() {}, select() {}, style: {} }),
            body: { appendChild: () => calls.push("append"),
                    removeChild: () => calls.push("remove") },
            execCommand: (cmd) => { calls.push(cmd); return true; },
        },
    }, async () => {
        assert.equal(await copyText("req-abc123"), true);
        assert.deepEqual(calls, ["append", "copy", "remove"]);
    });
});

test("copy uses the clipboard API when it is available", async () => {
    let written = null;
    await withGlobals({
        navigator: { clipboard: { writeText: async (v) => { written = v; } } },
    }, async () => {
        assert.equal(await copyText("req-abc123"), true);
        assert.equal(written, "req-abc123");
    });
});

test("copying nothing is not reported as a success", async () => {
    assert.equal(await copyText(""), false);
    assert.equal(await copyText(null), false);
});


/* ── external URLs ─────────────────────────────────────────────────────────
 *
 * A judgment's URL is court-published data that reaches the browser through the
 * citator and the API, and this is the last point before it becomes an `href`.
 * The server applies the same rule; both, deliberately, because a cached answer
 * written before the server-side rule existed still passes through this one. */

const UNSAFE = [
    "javascript:alert(document.cookie)",
    "JavaScript:alert(1)",
    "  javascript:alert(1)  ",
    "\tjavascript:alert(1)",
    "data:text/html,<script>fetch('/api/v1/cases')</script>",
    "data:application/pdf;base64,AAAA",
    "file:///etc/passwd",
    "vbscript:msgbox(1)",
    "//evil.example/x.pdf",
    "/relative/path.pdf",
    "https://",
    "http:///x.pdf",
    "not a url at all",
    "",
    "   ",
];

for (const url of UNSAFE) {
    test(`an unsafe judgment url is not rendered as a link: ${JSON.stringify(url)}`, () => {
        assert.equal(safeExternalUrl(url), "");
        const c = normaliseCitation({ type: "judgment", statute: "2026LHC4194", url });
        assert.equal(c.href, "", "an unsafe url reached href");
    });
}

test("a scheme-relative url is refused rather than resolved against the page", () => {
    // `new URL(x)` with no base must FAIL for these. Passing a base would
    // silently turn //evil.example into https://evil.example.
    assert.equal(safeExternalUrl("//evil.example/x.pdf"), "");
    assert.equal(safeExternalUrl("/appjudgments/x.pdf"), "");
});

test("a real court url survives untouched", () => {
    const url = "https://sys.lhc.gov.pk/appjudgments/2026LHC4194.pdf";
    assert.equal(safeExternalUrl(url), url);
    assert.equal(normaliseCitation({ type: "judgment", statute: "X", url }).href, url);
});

test("a non-string url is not a link", () => {
    for (const v of [null, undefined, 123, {}, [], true]) {
        assert.equal(safeExternalUrl(v), "");
    }
});

test("an unsafe url in the source fallback is refused too", () => {
    // normaliseCitation falls back to `source` when `url` is absent, so the
    // fallback is held to the same rule as the field it stands in for.
    const c = normaliseCitation({ type: "judgment", statute: "X",
                                  source: "javascript:alert(1)" });
    assert.equal(c.href, "");
});

test("a judgment with an unsafe url keeps its citation", () => {
    // The citation is the trust signal; the link is a convenience. Dropping the
    // chip would hide a judgment the answer actually relied on.
    const list = normaliseCitations([
        { type: "judgment", statute: "2026LHC4194", url: "javascript:alert(1)",
          status: "matched" },
    ]);
    assert.equal(list.length, 1);
    assert.equal(list[0].label, "2026LHC4194");
    assert.equal(list[0].status, MATCHED);
    assert.equal(list[0].href, "");
});

test("an unsafe url is not counted as linkable", () => {
    const list = normaliseCitations([
        { type: "judgment", statute: "A", url: "javascript:alert(1)" },
        { type: "judgment", statute: "B", url: "https://sys.lhc.gov.pk/x.pdf" },
    ]);
    assert.equal(citationSummary(list).linkable, 1);
});

test("a statute never receives a judgment's external href", () => {
    // Keeps the two link kinds from converging: a corpus document must go
    // through the authenticated opener, never an anchor.
    const c = normaliseCitation({ statute: "PPC 1860", url: "https://evil/x.pdf",
                                  source: "https://evil/y.pdf" });
    assert.equal(c.href, "");
    assert.equal(c.sourceUrl, "");
});

test("the browser and the server agree on every url in this file", () => {
    // A rule enforced in two places that disagree is worse than one place. The
    // divergence that motivated this: WHATWG parsing repairs an empty
    // authority (`http:///x.pdf` -> `http://x.pdf/`) while Python's urlsplit
    // rejects it. The same strings are asserted in
    // backend/tests/test_trust_surface.py::test_an_unsafe_judgment_url_is_not_a_link.
    const sharedUnsafe = [
        "javascript:alert(document.cookie)",
        "JavaScript:alert(1)",
        "  javascript:alert(1)  ",
        "file:///etc/passwd",
        "vbscript:msgbox(1)",
        "//evil.example/x.pdf",
        "https://",
        "http:///x.pdf",
        "not a url at all",
        "",
        "   ",
    ];
    for (const url of sharedUnsafe) {
        assert.equal(safeExternalUrl(url), "", `${JSON.stringify(url)} was allowed`);
    }
    for (const url of ["https://sys.lhc.gov.pk/appjudgments/2026LHC4194.pdf",
                       "http://sys.lhc.gov.pk/x.pdf"]) {
        assert.equal(safeExternalUrl(url), url);
    }
});

/* ══════════════════════════════════════════════════════════════════════════
 * Audit status — what an answer says about its own auditability
 * ══════════════════════════════════════════════════════════════════════════ */

test("a safely recorded answer says nothing at all", () => {
    // The overwhelmingly common case. A badge on every answer confirming the
    // system worked is noise, and noise is exactly what stops people reading
    // the one badge that matters.
    assert.equal(auditNotice({ auditSaved: true, auditPending: false }), null);
});

test("a queued record says it is pending, without alarm", () => {
    const notice = auditNotice({ auditSaved: true, auditPending: true });
    assert.equal(notice.tone, "info");
    assert.match(notice.label, /pending/i);
});

test("an unrecorded answer warns clearly", () => {
    const notice = auditNotice({ auditSaved: false, auditPending: false });
    assert.equal(notice.tone, "warn");
    assert.match(notice.label, /not recorded/i);
    // And says what the user can do about it, since they cannot fix the
    // database.
    assert.match(notice.detail, /save a copy/i);
});

test("an answer stored before the status existed is not warned about", () => {
    // Absent fields mean "we did not record this", not "it failed". Warning
    // about every old answer on a suspicion the data cannot support is how a
    // warning becomes background noise.
    assert.equal(auditNotice({}), null);
    assert.equal(auditNotice({ auditSaved: undefined }), null);
});

test("lost outranks pending", () => {
    // A record that gave up may still carry a stale pending flag. The user
    // needs the worse fact.
    const notice = auditNotice({ auditSaved: false, auditPending: true });
    assert.equal(notice.tone, "warn");
});
