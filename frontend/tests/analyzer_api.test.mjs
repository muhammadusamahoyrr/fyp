/* The Document Analyzer client functions in the REAL api.js, against a mocked
 * fetch: the request each one sends is exactly what the server expects. */
import test from "node:test";
import assert from "node:assert/strict";

async function loadApi(calls, { status = 200, body = {} } = {}) {
    globalThis.BroadcastChannel = class { constructor() { this.onmessage = null; } postMessage() {} close() {} };
    globalThis.localStorage = {
        _v: {}, getItem(k) { return this._v[k] ?? null; },
        setItem(k, v) { this._v[k] = String(v); }, removeItem(k) { delete this._v[k]; },
    };
    globalThis.fetch = async (url, options = {}) => {
        calls.push({ url: String(url), options });
        return new Response(status === 204 ? null : JSON.stringify(body),
                            { status, headers: { "content-type": "application/json" } });
    };
    return import("../src/lib/api.js");
}

test("an upload carries the attestation and key as headers, the file as multipart", async () => {
    const calls = [];
    const api = await loadApi(calls, { status: 202, body: { source_id: "s", run_id: "r" } });
    const file = new File(["%PDF-1.4"], "lease.pdf", { type: "application/pdf" });
    const r = await api.createAnalysis(file, { side: "landlord", depth: "deep" }, "synthetic-v1", "key-12345678");
    assert.equal(r.status, 202);
    const [call] = calls;
    assert.match(call.url, /\/documents\/analyses$/);
    assert.equal(call.options.method, "POST");
    const h = call.options.headers;
    assert.equal(h["X-Synthetic-Data-Attested"], "true");
    assert.equal(h["X-Synthetic-Attestation-Version"], "synthetic-v1");
    assert.equal(h["Idempotency-Key"], "key-12345678");
    assert.equal(h["Content-Type"], undefined, "a fixed Content-Type would drop the multipart boundary");
    const form = call.options.body;
    assert.ok(form instanceof FormData);
    assert.equal(form.get("file").name, "lease.pdf");
    assert.equal(form.get("side"), "landlord");
    assert.equal(form.get("depth"), "deep");
    assert.equal(form.get("synthetic_data_attested"), null, "the attestation must not ride in the body");
});

test("confirmations send the expected state version and only the fields asked for", async () => {
    const calls = [];
    const api = await loadApi(calls);
    await api.confirmAnalysisOcr("r 1", 3);
    await api.confirmAnalysisOcr("r1", 3, "fixed");
    await api.confirmAnalysisDocument("r1", 4, "tenancy", "punjab");
    await api.confirmAnalysisTerms("r1", 5, { term_months: { value: 11, sentence_ids: [] } });
    assert.match(calls[0].url, /\/runs\/r%201\/ocr-text$/, "the run id was not encoded");
    assert.deepEqual(JSON.parse(calls[0].options.body), { expected_state_version: 3 });
    assert.deepEqual(JSON.parse(calls[1].options.body), { expected_state_version: 3, text: "fixed" });
    assert.deepEqual(JSON.parse(calls[2].options.body),
                     { expected_state_version: 4, document_type: "tenancy", jurisdiction: "punjab" });
    assert.deepEqual(JSON.parse(calls[3].options.body),
                     { expected_state_version: 5, terms: { term_months: { value: 11, sentence_ids: [] } } });
});

test("history pages with a cursor and delete tolerates an empty 204", async () => {
    const calls = [];
    let api = await loadApi(calls, { body: { items: [], next: null } });
    await api.listAnalyses({ before: "s9", limit: 5 });
    assert.match(calls[0].url, /\/documents\/analyses\?limit=5&before=s9$/);
    const calls2 = [];
    api = await loadApi(calls2, { status: 204 });
    const r = await api.deleteAnalysis("s1");
    assert.equal(r.error, null);
    assert.equal(calls2[0].options.method, "DELETE");
});
