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

async function openSearchHit(container, title) {
    await typeInto(container.querySelector('input[placeholder="Search research"]'), "wall");
    await settle(500);   // the search is debounced
    const hit = [...container.querySelectorAll("div")]
        .find(d => d.children.length === 0 && d.textContent.trim() === title);
    assert.ok(hit, `search hit "${title}" was not rendered`);
    await act(async () => { hit.dispatchEvent(new MouseEvent("click", { bubbles: true })); });
    await settle(100);
}

test("a slow case list does not leave an empty general conversation behind", async () => {
    stubServer({ casesDelayMs: 120 });
    const view = await mountWithCaseState(CASE.case_number);
    const created = api.__calls("createResearchConversation").map(c => c.args[0]?.caseId ?? null);
    assert.deepEqual(created, [CASE._id], "an unbound conversation was created before the case loaded");
    await view.unmount();
});

test("opening a search hit from another case adopts that case, and the next question stays in that thread", async () => {
    stubServer({ cases: [CASE, CASE_B] });
    bindings.sB = CASE_B._id;
    api.__respond("searchResearchConversations",
        { data: { results: [{ session_id: "sB", title: "Wall thread", snippet: "the wall" }] }, error: null });

    const view = await mountWithCaseState(CASE.case_number);
    await openSearchHit(view.container, "Wall thread");
    assert.deepEqual(view.selections, [CASE_B.case_number], "the page did not switch to the thread's case");

    const before = api.__calls("createResearchConversation").length;
    await ask(view.container, "Who owns the wall?");
    const { sid, caseId } = lastTurn();
    assert.equal(sid, "sB", "the question silently went to a different thread");
    assert.equal(caseId, CASE_B._id);
    assert.equal(api.__calls("createResearchConversation").length, before, "a new thread was created on submit");
    await view.unmount();
});

test("a search hit whose case is not loaded shows an explicit notice instead of switching silently", async () => {
    stubServer();
    bindings.sX = "665f0000000000000000dead";
    api.__respond("searchResearchConversations",
        { data: { results: [{ session_id: "sX", title: "Other thread", snippet: "the wall" }] }, error: null });

    const view = await mountWithCaseState(CASE.case_number);
    await openSearchHit(view.container, "Other thread");
    const notice = view.container.querySelector('[role="status"]');
    assert.ok(notice, "no notice was shown");
    assert.match(notice.textContent, /new thread/);
    await view.unmount();
});

