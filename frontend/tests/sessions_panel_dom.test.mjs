/* SessionsPanel — the real component, rendered into a real DOM.
 *
 * These endpoints existed for months and nothing called them, so the risk here
 * is not a subtle bug: it is a panel that looks fine and does nothing, or one
 * that reassures before it has checked anything.
 *
 * The specific failures guarded against:
 *   * saying "no active sessions" while the request is still in flight, or
 *     after it FAILED — telling someone their account is clean when nothing
 *     has been looked at is the dangerous direction to be wrong in;
 *   * "sign out everywhere" firing on a single click, with no confirmation;
 *   * ending your own session and leaving the page looking signed in.
 *
 * Assertions are on text and elements a user would see, not internal state.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { JSDOM } from "jsdom";

const dom = new JSDOM("<!doctype html><html><body></body></html>",
                      { url: "http://localhost/" });
function define(name, value) {
    Object.defineProperty(globalThis, name, {
        value, writable: true, configurable: true,
    });
}
for (const name of ["window", "document", "navigator", "HTMLElement",
                    "Element", "Node", "Event", "CustomEvent",
                    "MutationObserver", "getComputedStyle"]) {
    define(name, dom.window[name]);
}
define("IS_REACT_ACT_ENVIRONMENT", true);

const React = (await import("react")).default;
const { act } = await import("react");
const { createRoot } = await import("react-dom/client");
const api = await import("./support/api-stub.mjs");
const mod = await import("../src/components/shared/SessionsPanel.jsx");
const SessionsPanel = mod.default;
const { deviceLabel, whenLabel } = mod;

const { createElement: h } = React;

const T = {
    text: "#fff", textMuted: "#999", border: "#333",
    danger: "#FF6B7A", success: "#4DD4A3", primary: "#5AB3FF",
};

const SESSIONS = [
    {
        session_id: "sess-current", current: true,
        user_agent: "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0",
        last_used_at: new Date(Date.now() - 120000).toISOString(),
    },
    {
        session_id: "sess-other", current: false,
        user_agent: "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0) Safari/605.1",
        last_used_at: new Date(Date.now() - 7200000).toISOString(),
    },
];

async function mount(props = {}) {
    const host = dom.window.document.createElement("div");
    dom.window.document.body.appendChild(host);
    const root = createRoot(host);
    await act(async () => {
        root.render(h(SessionsPanel, { t: T, ...props }));
    });
    return {
        host,
        text: () => host.textContent,
        buttons: () => [...host.querySelectorAll("button")],
        button: (label) => [...host.querySelectorAll("button")]
            .find(b => b.textContent.trim().toLowerCase().includes(label.toLowerCase())),
        click: async (label) => {
            const btn = [...host.querySelectorAll("button")]
                .find(b => b.textContent.trim().toLowerCase().includes(label.toLowerCase()));
            assert.ok(btn, `no button matching ${label}`);
            await act(async () => { btn.dispatchEvent(new dom.window.Event("click", { bubbles: true })); });
        },
        unmount: () => act(async () => root.unmount()),
    };
}

test.beforeEach(() => api.__reset());

// ── it actually calls the endpoints nobody was calling ───────────────────────

test("it loads the session list on mount", async () => {
    api.__respond("listSessions", { data: { items: SESSIONS }, error: null });
    const ui = await mount();
    assert.equal(api.__calls("listSessions").length, 1);
    assert.match(ui.text(), /Chrome on Windows/);
    assert.match(ui.text(), /Safari on iOS/);
    await ui.unmount();
});

test("the session you are using is marked, so you do not end it by accident", async () => {
    api.__respond("listSessions", { data: { items: SESSIONS }, error: null });
    const ui = await mount();
    assert.match(ui.text(), /This device/);
    await ui.unmount();
});

// ── loading and failure are NOT emptiness ────────────────────────────────────

test("while loading it does not claim there are no sessions", async () => {
    let release;
    api.__respond("listSessions", () => new Promise(r => { release = r; }));
    const ui = await mount();
    assert.doesNotMatch(ui.text(), /No active sessions/i,
        "claimed the account had no sessions before the request returned");
    assert.match(ui.text(), /Loading/i);
    release({ data: { items: SESSIONS }, error: null });
    await ui.unmount();
});

test("a failed load reports the error and does not claim there are no sessions",
     async () => {
    api.__respond("listSessions", { data: null, error: { message: "Network down" } });
    const ui = await mount();
    assert.match(ui.text(), /Network down/);
    assert.doesNotMatch(ui.text(), /No active sessions/i,
        "a failed request rendered as an empty, reassuring list");
    assert.ok(ui.host.querySelector('[role="alert"]'), "no alert role on the error");
    await ui.unmount();
});

test("an empty list is only shown when the server really returned none", async () => {
    api.__respond("listSessions", { data: { items: [] }, error: null });
    const ui = await mount();
    assert.match(ui.text(), /No active sessions/i);
    await ui.unmount();
});

// ── revoking one ─────────────────────────────────────────────────────────────

test("signing out another device calls revoke with that session id", async () => {
    api.__respond("listSessions", { data: { items: SESSIONS }, error: null });
    api.__respond("revokeSession", { data: { success: true }, error: null });
    const ui = await mount();
    const rows = ui.buttons().filter(b => /sign out$/i.test(b.textContent.trim()));
    assert.equal(rows.length, 2, "expected one Sign out button per session");
    await act(async () => { rows[1].dispatchEvent(new dom.window.Event("click", { bubbles: true })); });
    const calls = api.__calls("revokeSession");
    assert.equal(calls.length, 1);
    assert.equal(calls[0].args[0], "sess-other");
    await ui.unmount();
});

test("ending your OWN session signs you out of the page too", async () => {
    api.__respond("listSessions", { data: { items: SESSIONS }, error: null });
    api.__respond("revokeSession", { data: { success: true }, error: null });
    let signedOut = 0;
    const ui = await mount({ onSignedOut: () => { signedOut += 1; } });
    const rows = ui.buttons().filter(b => /sign out$/i.test(b.textContent.trim()));
    await act(async () => { rows[0].dispatchEvent(new dom.window.Event("click", { bubbles: true })); });
    assert.equal(api.__calls("revokeSession")[0].args[0], "sess-current");
    assert.equal(signedOut, 1,
        "revoked the current session and left the page looking signed in");
    await ui.unmount();
});

test("a failed revoke surfaces the error rather than silently doing nothing", async () => {
    api.__respond("listSessions", { data: { items: SESSIONS }, error: null });
    api.__respond("revokeSession", { data: null, error: { message: "Session not found" } });
    const ui = await mount();
    const rows = ui.buttons().filter(b => /sign out$/i.test(b.textContent.trim()));
    await act(async () => { rows[1].dispatchEvent(new dom.window.Event("click", { bubbles: true })); });
    assert.match(ui.text(), /Session not found/);
    await ui.unmount();
});

// ── revoke-all is guarded ────────────────────────────────────────────────────

test("sign out everywhere needs a confirmation before it fires", async () => {
    api.__respond("listSessions", { data: { items: SESSIONS }, error: null });
    api.__respond("revokeAllSessions", { data: { revoked: 2 }, error: null });
    const ui = await mount();
    await ui.click("Sign out everywhere");
    assert.equal(api.__calls("revokeAllSessions").length, 0,
        "one click ended every session with no confirmation");
    assert.match(ui.text(), /ends every session/i);
    await ui.unmount();
});

test("confirming sign out everywhere calls it, once, and signs the page out", async () => {
    api.__respond("listSessions", { data: { items: SESSIONS }, error: null });
    api.__respond("revokeAllSessions", { data: { revoked: 2 }, error: null });
    let signedOut = 0;
    const ui = await mount({ onSignedOut: () => { signedOut += 1; } });
    await ui.click("Sign out everywhere");
    await ui.click("Yes, sign out everywhere");
    assert.equal(api.__calls("revokeAllSessions").length, 1);
    assert.equal(signedOut, 1);
    await ui.unmount();
});

test("cancelling the confirmation calls nothing", async () => {
    api.__respond("listSessions", { data: { items: SESSIONS }, error: null });
    const ui = await mount();
    await ui.click("Sign out everywhere");
    await ui.click("Cancel");
    assert.equal(api.__calls("revokeAllSessions").length, 0);
    await ui.unmount();
});

// ── the labels ───────────────────────────────────────────────────────────────

test("device labels are recognisable, and unknown stays honest", () => {
    assert.equal(deviceLabel("Mozilla/5.0 (Windows NT 10.0) Chrome/120.0"), "Chrome on Windows");
    assert.equal(deviceLabel("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0) Safari/605.1"), "Safari on iOS");
    assert.equal(deviceLabel("Mozilla/5.0 (Macintosh) Firefox/121.0"), "Firefox on macOS");
    assert.equal(deviceLabel(""), "Unknown device");
    assert.equal(deviceLabel(null), "Unknown device");
    assert.equal(deviceLabel("something-unparseable"), "Unknown device");
});

test("Edge and Opera are not reported as Chrome", () => {
    // Both send Chrome in the UA. Reporting "Chrome on Windows" for an Edge
    // session makes it harder to recognise your own device, which is the one
    // job of this column.
    assert.equal(deviceLabel("Mozilla/5.0 (Windows NT 10.0) Chrome/120 Edg/120"), "Edge on Windows");
    assert.equal(deviceLabel("Mozilla/5.0 (Windows NT 10.0) Chrome/120 OPR/106"), "Opera on Windows");
});

test("relative times read the way a person would say them", () => {
    const ago = ms => new Date(Date.now() - ms).toISOString();
    assert.equal(whenLabel(ago(5000)), "just now");
    assert.equal(whenLabel(ago(60000)), "1 minute ago");
    assert.equal(whenLabel(ago(180000)), "3 minutes ago");
    assert.equal(whenLabel(ago(3600000)), "1 hour ago");
    assert.equal(whenLabel(ago(86400000)), "1 day ago");
    assert.equal(whenLabel(null), "");
    assert.equal(whenLabel("not a date"), "");
});
