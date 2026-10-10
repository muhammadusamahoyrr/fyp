/* The AI Assistant's history list, with a case selected, ends filtered to
 * that case. Found in the live smoke test: the search debounce (and the mount
 * bootstrap) refreshed the list with a closure from the first render, before
 * the case list had loaded; firing last, the unfiltered request won and the
 * sidebar listed general threads under a selected case.
 *
 * Kept in its own file: it is a timing race, and earlier tests sharing a
 * module instance and timers masked it.
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
function stubServer({ casesDelayMs = 0, cases = [CASE] } = {}) {
    bindings = {};
    let n = 0;
    api.__reset();
    api.__respond("bootstrapAuth", true);
    api.__respond("getMe", { data: USER, error: null });
    api.__respond("listCases", () => new Promise(r => setTimeout(
        () => r({ data: { items: cases }, error: null }), casesDelayMs)));
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

/* ── Follow-up: no stray threads, no silent switches ─────────────────────── */

const CASE_B = { _id: "665f00000000000000000002", case_number: "CIV-2026-002", title: "Boundary wall",
                 case_type: "civil", province: "punjab", client_name: "Bilal" };

// The real App keeps the selected case in state; so does this host, so that
// adopting a conversation's case actually changes what the page sends.
async function mountWithCaseState(initialCase) {
    const selections = [];
    function Host() {
        const [activeCase, setActive] = React.useState(initialCase);
        const setActiveCase = (v) => { selections.push(v); setActive(v); };
        return h(CaseCtx.Provider, { value: { activeCase, setActiveCase } }, h(AILegalPage));
    }
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    await act(async () => { root.render(h(AuthProvider, null, h(Host))); });
    await settle(250);
    return { container, selections,
             unmount: async () => { await act(async () => root.unmount()); container.remove(); } };
}

async function typeInto(input, value) {
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set;
    await act(async () => {
        setter.call(input, value);
        input.dispatchEvent(new Event("input", { bubbles: true }));
    });
}

async function ask(container, question) {
    const box = container.querySelector('input[placeholder="Ask Attorney AI..."]');
    await typeInto(box, question);
    await act(async () => {
        box.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
    });
    await settle(100);
}

// The sidebar has no search box any more: a thread is opened from the list.
async function openSearchHit(container, title) {
    await settle(300);
    const hit = container.querySelector(`.cv[title="${title}"]`);
    assert.ok(hit, `history row "${title}" was not rendered`);
    await act(async () => { hit.dispatchEvent(new MouseEvent("click", { bubbles: true })); });
    await settle(100);
}

test("with a case selected, the history list ends filtered to that case (smoke-test finding)", async () => {
    // The mount bootstrap refreshed the list with the closure from the first
    // render, when the case was still unknown; as the last request it won, so
    // general threads were listed under a selected case.
    // Cases answer faster than the 250 ms search debounce, as they do locally.
    stubServer({ casesDelayMs: 20 });
    const view = await mountWithCaseState(CASE.case_number);
    await settle(400);
    const lists = api.__calls("listResearchConversations").map(c => c.args[0]?.caseId);
    assert.ok(lists.length > 0, "the history list was never loaded");
    assert.equal(lists.at(-1), CASE._id, `the last history request was for ${lists.at(-1)}`);
    await view.unmount();
});
