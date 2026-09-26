/* The draft client itself — the REAL lib/api.js, with fetch stubbed.
 *
 * agreement_draft_composer.test.mjs mounts the editor and reads the arguments
 * it chose. That cannot see the request those arguments turn into, because the
 * component is served the loader's spy stub. A test importing the client
 * directly from tests/ gets the client itself (see jsx-loader.mjs), so this is
 * where the wire is checked: route, method, and the one header that stops a
 * retry from becoming a second agreement.
 */
import test from "node:test";
import assert from "node:assert/strict";

function define(name, value) {
    Object.defineProperty(globalThis, name, { value, writable: true, configurable: true });
}
define("localStorage", {
    _v: {},
    getItem(k) { return this._v[k] ?? null; },
    setItem(k, v) { this._v[k] = String(v); },
    removeItem(k) { delete this._v[k]; },
});
define("BroadcastChannel", class {
    constructor() { this.onmessage = null; }
    postMessage() {}
    close() {}
});

let calls = [];
let next = { status: 200, body: {} };
define("fetch", async (url, opts = {}) => {
    calls.push({
        url: String(url),
        method: opts.method || "GET",
        headers: opts.headers || {},
        body: opts.body ? JSON.parse(opts.body) : null,
    });
    const response = {
        ok: next.status >= 200 && next.status < 300,
        status: next.status,
        json: async () => next.body,
    };
    // Only when the test says so: a Response that can produce bytes is what
    // distinguishes a raw download from a JSON call parsed by mistake.
    if (next.blob) response.blob = async () => ({ size: 1234 });
    return response;
});

/* The smallest DOM `_saveBlob` needs: an object URL and an anchor to click.
   Returns a record of what it was asked to save. */
function withDomStubs() {
    const saved = { filename: null, clicked: false };
    define("URL", {
        createObjectURL: () => "blob:stub",
        revokeObjectURL: () => {},
    });
    define("document", {
        createElement: () => ({
            set download(v) { saved.filename = v; },
            get download() { return saved.filename; },
            href: "",
            click() { saved.clicked = true; },
            remove() {},
        }),
        body: { appendChild() {} },
    });
    return saved;
}

const api = await import("../src/lib/api.js");

test.beforeEach(() => { calls = []; next = { status: 200, body: {} }; });

const only = () => {
    assert.equal(calls.length, 1, `expected one request, saw ${calls.length}`);
    return calls[0];
};

test("createDraft posts the four fields the server requires, and nothing else", async () => {
    await api.createDraft({
        title: "Retainer", body_html: "Terms.", client_id: "C1", case_id: "CASE9",
    });
    const c = only();
    assert.match(c.url, /\/agreements\/drafts$/);
    assert.equal(c.method, "POST");
    // The schema is extra="forbid": an unexpected key is a 422, not a shrug.
    assert.deepEqual(c.body, {
        title: "Retainer", body_html: "Terms.", client_id: "C1", case_id: "CASE9",
    });
});

test("updateDraft patches, and always states the version it believed it held", async () => {
    await api.updateDraft("D1", { expected_version: 4, title: "T", body_html: "B" });
    const c = only();
    assert.match(c.url, /\/agreements\/drafts\/D1$/);
    assert.equal(c.method, "PATCH");
    assert.equal(c.body.expected_version, 4);
});

test("updateDraft omits fields that were not supplied rather than nulling them", async () => {
    await api.updateDraft("D1", { expected_version: 2, body_html: "Only the body." });
    assert.deepEqual(only().body, { expected_version: 2, body_html: "Only the body." });
});

test("an explicitly null field is omitted too, not sent as null", async () => {
    // An absent field is dropped by JSON.stringify on its own, so testing only
    // that proves nothing about the client. NULL is the case that needs the
    // code: `{"title": null}` reaches the server and fails min_length=1, so a
    // caller saying "I am not changing the title" the other way round would
    // have its save rejected for a field it never meant to touch.
    await api.updateDraft("D1", {
        expected_version: 2, title: null, body_html: "Only the body.",
    });
    assert.deepEqual(only().body, { expected_version: 2, body_html: "Only the body." });
});

test("deleteDraft addresses the draft route, not the agreement route", async () => {
    await api.deleteDraft("D1");
    const c = only();
    assert.match(c.url, /\/agreements\/drafts\/D1$/);
    assert.equal(c.method, "DELETE");
});

test("an id with URL-significant characters is encoded", async () => {
    await api.deleteDraft("a/b?c");
    assert.match(only().url, /\/agreements\/drafts\/a%2Fb%3Fc$/);
});

test("sendDraft carries the Idempotency-Key header as a string", async () => {
    await api.sendDraft("D1", {
        expected_version: 3,
        expected_body_sha256: "a".repeat(64),
        signature_data: "Adv Khan",
        consent: true,
    }, "key-123");
    const c = only();
    assert.match(c.url, /\/agreements\/drafts\/D1\/send$/);
    assert.equal(c.method, "POST");
    assert.equal(c.headers["Idempotency-Key"], "key-123");
    assert.equal(typeof c.headers["Idempotency-Key"], "string",
        "a Promise or object here reaches the server as [object Object] and " +
        "silently defeats the key");
    assert.equal(c.body.method, "typed", "the default signature method");
    assert.equal(c.body.expected_body_sha256.length, 64);
});

test("the send route is the only agreements call that is rate limited server-side", async () => {
    // D6: sending is the operation that reaches another person. Editing is not
    // throttled, so an autosave loop cannot lose a lawyer's work — this pins
    // that the client keeps them as separate routes rather than collapsing an
    // edit-then-send into one call that would inherit the limit.
    await api.updateDraft("D1", { expected_version: 1, body_html: "x" });
    assert.ok(!calls[0].url.endsWith("/send"));
    assert.equal(calls[0].headers["Idempotency-Key"], undefined,
        "an edit needs no key: it is not observable by anyone else");
});

test("idempotencyKey returns a fresh string each time it is called", async () => {
    const a = api.idempotencyKey();
    const b = api.idempotencyKey();
    assert.equal(typeof a, "string");
    assert.ok(a.length >= 10);
    assert.notEqual(a, b, "two intents must not share a key");
});

// ── Gate 3F: the list is a page, not a bare array ───────────────────────────

test("listAgreements asks for a page and defaults to a bounded size", async () => {
    await api.listAgreements();
    const c = only();
    assert.match(c.url, /\/agreements\?/);
    const q = new URL(c.url).searchParams;
    assert.equal(q.get("page"), "1");
    assert.ok(Number(q.get("page_size")) > 0);
    assert.equal(q.get("status"), null, "no status filter unless asked for");
});

test("a status filter is passed through, and nothing else is", async () => {
    await api.listAgreements({ page: 3, page_size: 10, status: "pending" });
    const q = new URL(only().url).searchParams;
    assert.equal(q.get("page"), "3");
    assert.equal(q.get("page_size"), "10");
    assert.equal(q.get("status"), "pending");
    assert.deepEqual([...q.keys()].sort(), ["page", "page_size", "status"],
        "a list parameter may describe the slice, never whose rows come back");
});

test("a null status is omitted rather than sent as the string 'null'", async () => {
    // URLSearchParams stringifies whatever it is given, so `status=null`
    // would reach the server as a real filter value and be refused as an
    // unknown status -- turning "show me everything" into an error.
    await api.listAgreements({ status: null });
    assert.equal(new URL(only().url).searchParams.get("status"), null);
});

// ── Gate 3E: downloading the executed agreement ─────────────────────────────

test("downloadExecutedAgreement asks the pdf route for raw bytes", async () => {
    // ASSERTS THE OUTCOME, not just the URL. An earlier version checked only
    // the path and method, so removing `returnResponse: true` -- which is the
    // whole point of this call -- changed nothing it could see and the guard
    // could not be proven. Without it apiFetch parses the PDF as JSON, hands
    // back a plain object with no `blob()`, and the download silently fails.
    const saved = withDomStubs();
    next = { status: 200, body: {}, blob: true };

    const result = await api.downloadExecutedAgreement("A1", "retainer.pdf");

    const c = calls[0];
    assert.match(c.url, /\/agreements\/A1\/pdf$/);
    assert.equal(c.method, "GET");
    assert.equal(c.body, null, "a download sends no payload");

    assert.equal(result.error, undefined,
        "the response was parsed as JSON instead of read as bytes");
    assert.equal(result.data, true);
    assert.equal(saved.filename, "retainer.pdf",
        "the caller's filename must reach the download");
});

test("the agreement id is encoded into the pdf path", async () => {
    await api.downloadExecutedAgreement("a/b?c").catch(() => {});
    assert.match(calls[0].url, /\/agreements\/a%2Fb%3Fc\/pdf$/);
});
