/* LD-06: the AI Assistant's first question when a case is already selected.
 *
 * WHAT WAS WRONG. On mount the page reopened the remembered thread or started
 * an UNBOUND one, because the case list had not loaded yet. The case-change
 * effect skipped its first run and watched `activeCase`, which never changed,
 * so no case-bound thread was ever started. The first question then carried
 * the case's id into an unbound conversation, and the server refused it with
 * a 409 (conversation_service.assert_case_binding), shown as "AI service
 * unavailable".
 *
 * The stub below enforces the same rule as the server: a turn's case_id must
 * equal the conversation's binding.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { JSDOM } from "jsdom";

const dom = new JSDOM("<!doctype html><html><body></body></html>", { url: "http://localhost/" });
function define(name, value) {
    Object.defineProperty(globalThis, name, { value, writable: true, configurable: true });
}
for (const name of ["window", "document", "navigator", "HTMLElement", "HTMLInputElement", "Element",
                    "Node", "Event", "CustomEvent", "MouseEvent", "KeyboardEvent", "MutationObserver",
                    "getComputedStyle", "localStorage", "sessionStorage", "requestAnimationFrame",
                    "cancelAnimationFrame"]) {
    define(name, dom.window[name]);
}
if (!dom.window.HTMLElement.prototype.scrollIntoView) dom.window.HTMLElement.prototype.scrollIntoView = () => {};
define("IS_REACT_ACT_ENVIRONMENT", true);

const React = (await import("react")).default;
const { act } = await import("react");
const { createRoot } = await import("react-dom/client");
const api = await import("./support/api-stub.mjs");
const { AuthProvider } = await import("../src/context/AuthContext.jsx");
const { CaseCtx } = await import("../src/components/lawyer/theme.js");
const { writeActiveSession } = await import("../src/lib/conversations.js");
const { AILegalPage } = await import("../src/components/lawyer/AILegalPage.jsx");
const h = React.createElement;

const settle = (ms = 40) => act(async () => { await new Promise(r => setTimeout(r, ms)); });

const CASE = { _id: "665f00000000000000000001", case_number: "CIV-2026-001", title: "Rent dispute",
               case_type: "civil", province: "punjab", client_name: "Ayesha" };
const USER = { _id: "l1", role: "lawyer", full_name: "Lawyer" };

// A stand-in for the server's conversation binding rule.
let bindings;
function stubServer({ casesDelayMs = 0 } = {}) {
    bindings = {};
    let n = 0;
    api.__reset();
    api.__respond("bootstrapAuth", true);
    api.__respond("getMe", { data: USER, error: null });
    api.__respond("listCases", () => new Promise(r => setTimeout(
        () => r({ data: { items: [CASE] }, error: null }), casesDelayMs)));
    api.__respond("listResearchConversations", { data: { items: [], next_cursor: null }, error: null });
    api.__respond("createResearchConversation", ({ caseId } = {}) => {
        const sid = `s${++n}`;
        bindings[sid] = caseId || null;
        return { data: { session_id: sid }, error: null };
    });
    api.__respond("getResearchConversation", (sid) => ({
        data: { session_id: sid, case_id: bindings[sid] ?? null, messages: [] }, error: null,
    }));
    api.__respond("aiResearch", (q, sid, opts) => {
        if ((bindings[sid] ?? null) !== (opts.case_id ?? null)) {
            return { data: null, status: 409,
                     error: { message: "This conversation is fixed to the case it was started for." } };
        }
        return { data: { answer: "Answer.", citations: [] }, error: null, status: 200 };
    });
}

async function mountAndAsk(question) {
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    await act(async () => {
        root.render(h(AuthProvider, null,
            h(CaseCtx.Provider, { value: { activeCase: CASE.case_number, setActiveCase: () => {} } },
                h(AILegalPage))));
    });
    await settle(250);   // auth, the mount bootstrap and the (delayed) case list all resolve

    const box = container.querySelector('input[placeholder="Ask Attorney AI..."]');
    assert.ok(box, "no question box");
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set;
    await act(async () => {
        setter.call(box, question);
        box.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await act(async () => {
        box.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
    });
    await settle(100);
    await act(async () => root.unmount());
    container.remove();
}

function lastTurn() {
    const turns = api.__calls("aiResearch");
    assert.ok(turns.length >= 1, "the question was never sent");
    const [, sid, opts] = turns.at(-1).args;
    return { sid, caseId: opts.case_id };
}

test.beforeEach(() => { sessionStorage.clear(); });

test("first question with a case selected and a slow case list goes to a thread bound to that case", async () => {
    stubServer({ casesDelayMs: 120 });
    await mountAndAsk("What sections apply?");
    const { sid, caseId } = lastTurn();
    assert.equal(caseId, CASE._id);
    assert.equal(bindings[sid], CASE._id, "the question was sent into a thread bound to another case (409)");
});

test("a remembered unbound thread is not reused for a case question", async () => {
    stubServer();
    bindings.old = null;
    writeActiveSession("research", USER._id, "old");
    await mountAndAsk("Key arguments?");
    const { sid, caseId } = lastTurn();
    assert.equal(caseId, CASE._id);
    assert.notEqual(sid, "old");
    assert.equal(bindings[sid], CASE._id);
});
