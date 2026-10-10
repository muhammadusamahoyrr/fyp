/* Phase 2.6a: the AI Assistant says which failure happened.
 *
 * WHAT WAS WRONG.
 *   * Every failed research turn read "AI service unavailable", including a
 *     question too long to send (413), a case the lawyer lost access to (403)
 *     and a conversation tied to another matter (409). The code read
 *     `error.detail`, which these errors never carry.
 *   * A rating showed "feedback recorded" before the request was made, and the
 *     `.catch` could never fire because apiFetch resolves with {error}.
 *   * Rename, archive and delete ignored their result entirely.
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
dom.window.confirm = () => true;
define("confirm", dom.window.confirm);
define("IS_REACT_ACT_ENVIRONMENT", true);

const React = (await import("react")).default;
const { act } = await import("react");
const { createRoot } = await import("react-dom/client");
const api = await import("./support/api-stub.mjs");
const { AuthProvider } = await import("../src/context/AuthContext.jsx");
const { CaseCtx } = await import("../src/components/lawyer/theme.js");
const { AILegalPage } = await import("../src/components/lawyer/AILegalPage.jsx");
const h = React.createElement;

const settle = (ms = 40) => act(async () => { await new Promise(r => setTimeout(r, ms)); });

function serve({ turn, rows = [] } = {}) {
    api.__reset();
    api.__respond("bootstrapAuth", true);
    api.__respond("getMe", { data: { _id: "l1", role: "lawyer", full_name: "Lawyer" }, error: null });
    api.__respond("listCases", { data: { items: [] }, error: null });
    api.__respond("listResearchConversations", { data: { conversations: rows, next_cursor: null }, error: null });
    api.__respond("createResearchConversation", { data: { session_id: "s1" }, error: null });
    api.__respond("getResearchConversation", (sid) => ({ data: { session_id: sid, case_id: null, messages: [] }, error: null }));
    if (turn) api.__respond("aiResearch", turn);
}

async function mount() {
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    await act(async () => {
        root.render(h(AuthProvider, null,
            h(CaseCtx.Provider, { value: { activeCase: null, setActiveCase: () => {} } }, h(AILegalPage))));
    });
    await settle(150);
    return { container, unmount: async () => { await act(async () => root.unmount()); container.remove(); } };
}

async function ask(container, question = "What applies?") {
    const box = container.querySelector('input[placeholder="Ask Attorney AI..."]');
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set;
    await act(async () => { setter.call(box, question); box.dispatchEvent(new Event("input", { bubbles: true })); });
    await act(async () => { box.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true })); });
    await settle(100);
}

const failing = (status, message) => ({ data: null, status, error: { message } });

for (const [status, serverMsg, expected] of [
    [413, "Request too large", /too long to send/],
    [403, "Forbidden", /don't have access to that case/],
    [409, "This conversation is fixed to the case it was started for.", /fixed to the case it was started for/],
    [500, "Internal Server Error", /AI service unavailable/],
]) {
    test(`a ${status} turn is reported as what it is`, async () => {
        serve({ turn: failing(status, serverMsg) });
        const view = await mount();
        await ask(view.container);
        assert.match(view.container.textContent, expected);
        if (status !== 500) assert.doesNotMatch(view.container.textContent, /AI service unavailable/);
        await view.unmount();
    });
}

async function answerAndRate(rateResult) {
    serve({ turn: { data: { answer: "An answer.", citations: [] }, error: null, status: 200 } });
    api.__respond("rateAnswer", rateResult);
    const view = await mount();
    await ask(view.container);
    const up = [...view.container.querySelectorAll("button")].find(b => b.textContent === "👍");
    assert.ok(up, "no rating button");
    await act(async () => { up.dispatchEvent(new MouseEvent("click", { bubbles: true })); });
    await settle();
    return view;
}

test("a rating that fails to save is not shown as recorded", async () => {
    const view = await answerAndRate({ data: null, status: 500, error: { message: "nope" } });
    assert.doesNotMatch(view.container.textContent, /feedback recorded/);
    assert.match(view.container.textContent, /feedback not saved/);
    await view.unmount();
});

test("a rating is shown as recorded once the server has it", async () => {
    const view = await answerAndRate({ data: { success: true }, error: null, status: 200 });
    assert.match(view.container.textContent, /feedback recorded/);
    await view.unmount();
});

test("a failed delete is reported and does not discard the open thread", async () => {
    serve({ rows: [{ session_id: "s1", title: "My thread", updated_at: new Date().toISOString() }] });
    api.__respond("deleteResearchConversation", { data: null, status: 500, error: { message: "Could not delete right now." } });
    const view = await mount();
    // Delete sits in the thread's "…" menu.
    const more = view.container.querySelector('button[title="More actions"]');
    assert.ok(more, "no thread menu button");
    await act(async () => { more.dispatchEvent(new MouseEvent("click", { bubbles: true })); });
    const del = [...view.container.querySelectorAll('button[title="Delete"]')][0];
    assert.ok(del, "no delete button");
    const created = api.__calls("createResearchConversation").length;
    await act(async () => { del.dispatchEvent(new MouseEvent("click", { bubbles: true })); });
    await settle();
    assert.match(view.container.textContent, /Could not delete right now/);
    assert.equal(api.__calls("createResearchConversation").length, created, "a new thread replaced the one that was not deleted");
    await view.unmount();
});
