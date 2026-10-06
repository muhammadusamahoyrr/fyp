/* Opening a KYC document (and a citation source) in a new tab — the REAL
 * lib/api.js, with fetch and the window stubbed.
 *
 * WHAT WAS WRONG (branch review, finding 3). adminOpenKycDocument fetched,
 * then called window.open without checking it and without catching a failed
 * res.blob(); a strict pop-up blocker made the button do nothing while the
 * helper reported success. It now shares the source-document helper — which
 * itself passed "noopener", making window.open return null on SUCCESS too, so
 * a working open was reported as blocked and its URL revoked under the tab.
 */
import test from "node:test";
import assert from "node:assert/strict";

function define(name, value) {
    Object.defineProperty(globalThis, name, { value, writable: true, configurable: true });
}
define("localStorage", { getItem: () => null, setItem() {}, removeItem() {} });
define("BroadcastChannel", class { postMessage() {} close() {} });

let next;
define("fetch", async () => ({
    ok: next.status >= 200 && next.status < 300,
    status: next.status,
    json: async () => next.body ?? {},
    blob: next.blobFails ? async () => { throw new Error("body stream already read"); }
                         : async () => ({ size: 3 }),
}));
const revoked = [];
define("URL", Object.assign(function () {}, {
    createObjectURL: () => "blob:kyc",
    revokeObjectURL: (u) => revoked.push(u),
}));
let openResult;
const opened = [];
define("window", { open: (...args) => { opened.push(args); return openResult; } });

const api = await import("../src/lib/api.js");

test.beforeEach(() => { revoked.length = 0; opened.length = 0; next = { status: 200 }; });

test("a blocked new tab is reported, not treated as success", async () => {
    openResult = null;
    const res = await api.adminOpenKycDocument("l1", "bar_certificate");
    assert.match(res.error || "", /blocked the new tab/);
    assert.deepEqual(revoked, ["blob:kyc"], "the object URL was not released");
});

test("an unreadable body is reported", async () => {
    next = { status: 200, blobFails: true };
    const res = await api.adminOpenKycDocument("l1", "bar_certificate");
    assert.match(res.error || "", /Could not open/);
    assert.equal(opened.length, 0);
});

test("a successful open is a success, and the opener link is cut", async () => {
    const tab = { opener: "parent" };
    openResult = tab;
    const res = await api.adminOpenKycDocument("l1", "bar_certificate");
    assert.equal(res.error, undefined);
    assert.equal(res.data, true);
    assert.equal(tab.opener, null);
    // No "noopener" feature: it makes window.open return null even on success.
    assert.ok(!String(opened[0][2] || "").includes("noopener"));
    assert.deepEqual(revoked, [], "the URL was revoked under the open tab");
});

test("a server refusal is reported with its message", async () => {
    next = { status: 404, body: { detail: "Document not found" } };
    const res = await api.adminOpenKycDocument("l1", "bar_certificate");
    assert.match(res.error || "", /not found/i);
});
