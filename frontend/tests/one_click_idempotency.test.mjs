/* The one-click document tools send one Idempotency-Key per user intent.
 *
 * The backend accepted a key on these seven routes, but nothing sent one, so
 * the server minted a fresh key every time and a retry after a lost response
 * still made a second document. See src/lib/intentKey.js.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import { keyForIntent } from "../src/lib/intentKey.js";

/* ── the rule ──────────────────────────────────────────────────────────── */

test("the same request keeps its key — a retry or double click is one intent", () => {
    const ref = { current: null };
    const a = keyForIntent(ref, { name: "A", amount: 5 });
    assert.equal(keyForIntent(ref, { name: "A", amount: 5 }), a);
});

test("a changed request gets a new key — it is a different document", () => {
    const ref = { current: null };
    const a = keyForIntent(ref, { name: "A" });
    const b = keyForIntent(ref, { name: "B" });
    assert.notEqual(a, b);
    // And going back is a new intent too, not a replay of the first.
    assert.notEqual(keyForIntent(ref, { name: "A" }), a);
});

test("keys are valid Idempotency-Keys: printable, no spaces, bounded", () => {
    const ref = { current: null };
    const k = keyForIntent(ref, {});
    assert.match(k, /^[\x21-\x7e]{1,200}$/);
});

test("an unserialisable request never shares a key", () => {
    const ref = { current: null };
    const loop = {}; loop.self = loop;
    assert.notEqual(keyForIntent(ref, loop), keyForIntent(ref, loop));
});

/* ── every helper sends it ─────────────────────────────────────────────── */

async function loadApi() {
    globalThis.BroadcastChannel = class {
        constructor() { this.onmessage = null; }
        postMessage() {}
        close() {}
    };
    globalThis.localStorage = {
        _v: {},
        getItem(k) { return this._v[k] ?? null; },
        setItem(k, v) { this._v[k] = String(v); },
        removeItem(k) { delete this._v[k]; },
    };
    return import("../src/lib/api.js");
}

const HELPERS = [
    ["inheritanceSettlementPdf", (api, k) => api.inheritanceSettlementPdf({ estate_value: 1 }, k), "/inheritance/settlement-pdf"],
    ["inheritanceDemandLetter", (api, k) => api.inheritanceDemandLetter({}, k), "/inheritance/demand-letter"],
    ["wasiyyatPdf", (api, k) => api.wasiyyatPdf({}, k), "/inheritance/wasiyyat-pdf"],
    ["labourDemandPdf", (api, k) => api.labourDemandPdf({}, k), "/calculators/labour-demand-pdf"],
    ["quickNotice", (api, k) => api.quickNotice("text here!", "legal_notice", null, k), "/documents/quick-notice"],
    ["pleadingUrduPdf", (api, k) => api.pleadingUrduPdf({ urdu_text: "x" }, k), "/ai/pleading-urdu/pdf"],
    ["disputeDraftPetition", (api, k) => api.disputeDraftPetition("d1", k), "/disputes/d1/petition"],
];

for (const [name, call, path] of HELPERS) {
    test(`${name} sends the Idempotency-Key it is given`, async () => {
        const seen = [];
        globalThis.fetch = async (url, options = {}) => {
            seen.push({ url: String(url), headers: options.headers || {} });
            return new Response("{}", { status: 200, headers: { "content-type": "application/json" } });
        };
        const api = await loadApi();
        await call(api, "intent-key-123");
        const req = seen.find(r => r.url.includes(path));
        assert.ok(req, `no request to ${path}`);
        assert.equal(req.headers["Idempotency-Key"], "intent-key-123");
    });
}

/* ── the screens use it ─────────────────────────────────────────────────── */

const read = (p) => readFileSync(new URL(p, import.meta.url), "utf8");

test("every one-click flow passes a per-intent key", () => {
    const tools = read("../src/components/client/ModTools.jsx");
    for (const call of ["inheritanceSettlementPdf(req, keyForIntent(",
                        "inheritanceDemandLetter(req, keyForIntent(",
                        "wasiyyatPdf(req, keyForIntent(",
                        "labourDemandPdf(req, keyForIntent(",
                        "keyForIntent(noticeKey"]) {
        assert.ok(tools.includes(call), `ModTools: ${call}`);
    }
    assert.match(read("../src/components/client/ModDisputes.jsx"),
                 /disputeDraftPetition\(\s*result\.id, keyForIntent\(petitionKey/);
    assert.match(read("../src/components/lawyer/DocAutomationPage.jsx"),
                 /pleadingUrduPdf\(payload, urduKeyRef\.current\)/);
});

test("the lawyer downloads the petition revision that was shared", () => {
    const inbox = read("../src/components/lawyer/DisputesInboxPage.jsx");
    assert.match(inbox, /revisionId: brief\.petition\.revision_id/);
    assert.match(inbox, /expectedPdfSha256: brief\.petition\.pdf_sha256/);
    assert.doesNotMatch(inbox, /\bdownloadDocument\(/);
});

test("a finished generation retires its key, so an edit is a new render", () => {
    const docs = read("../src/components/client/ModDocuments.jsx");
    const i = docs.indexOf("setGenPct(100);");
    const block = docs.slice(i, docs.indexOf("setGenDone(true)", i));
    assert.match(block, /generateKeyRef\.current = null;/);
});
