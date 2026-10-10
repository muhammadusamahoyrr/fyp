/* LD-01: the lawyer Documents inbox, mounted for real.
 *
 * WHAT WAS WRONG. The four stat cards read `counts["Pending Review"]` and
 * friends. `counts` is null until the first queue page answers (and always on
 * the legacy queue), so the inbox threw on its very first render, before any
 * request could return. Even with counts present the keys were display labels,
 * while the server sends statuses (`submitted`, `approved`, ...), so every
 * card would have been blank.
 *
 * The existing Documents tests read this file as text, so nothing ever mounted
 * it. These do.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { JSDOM } from "jsdom";

const dom = new JSDOM("<!doctype html><html><body></body></html>", { url: "http://localhost/" });
function define(name, value) {
    Object.defineProperty(globalThis, name, { value, writable: true, configurable: true });
}
for (const name of ["window", "document", "navigator", "HTMLElement", "Element", "Node",
                    "Event", "CustomEvent", "MouseEvent", "KeyboardEvent", "MutationObserver",
                    "getComputedStyle", "localStorage", "sessionStorage"]) {
    define(name, dom.window[name]);
}
define("IS_REACT_ACT_ENVIRONMENT", true);

const React = (await import("react")).default;
const { act } = await import("react");
const { createRoot } = await import("react-dom/client");
const api = await import("./support/api-stub.mjs");
const { AuthProvider } = await import("../src/context/AuthContext.jsx");
const { DocWorkflowApp } = await import("../src/components/lawyer/DocumentsPage.jsx");
const h = React.createElement;

const settle = (ms = 30) => act(async () => { await new Promise(r => setTimeout(r, ms)); });

async function mount() {
    const errors = [];
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container, {
        onUncaughtError: e => errors.push(e),
        onCaughtError: e => errors.push(e),
    });
    await act(async () => { root.render(h(AuthProvider, null, h(DocWorkflowApp))); });
    await settle();
    return {
        container, errors,
        unmount: async () => { await act(async () => root.unmount()); container.remove(); },
    };
}

// The stat cards' numbers, in order: Pending Review, Approved, Returned, Rejected.
function cardValues(container) {
    return [...container.querySelectorAll("[data-inbox-stat] [data-stat-value]")]
        .map(d => d.textContent.trim());
}

const row = (id, review_status) => ({
    id, title: `Doc ${id}`, client_name: "Client", case_id: `case${id}`,
    template_type: "plaint_civil", review_status,
});

test.beforeEach(() => {
    api.__reset();
    api.__respond("bootstrapAuth", true);
    api.__respond("getMe", { data: { _id: "l1", role: "lawyer", full_name: "Lawyer" } });
});

test("the inbox renders while the queue is still loading, with unknown counts as —", async () => {
    // The queue never answers during this test: the first render is the one that crashed.
    api.__respond("reviewQueueV2", () => new Promise(() => {}));
    const view = await mount();
    assert.deepEqual(view.errors, [], `the inbox threw: ${view.errors[0]}`);
    assert.deepEqual(cardValues(view.container), ["—", "—", "—", "—"]);
    await view.unmount();
});

test("V2: the cards show the server's per-status totals", async () => {
    api.__respond("reviewQueueV2", {
        data: { items: [row("a", "submitted")], next_cursor: null, status: "all",
                counts: { all: 9, submitted: 4, approved: 3, returned: 1, rejected: 0 } },
        error: null, status: 200,
    });
    const view = await mount();
    assert.deepEqual(view.errors, []);
    // A real zero is shown as 0, not as "unknown".
    assert.deepEqual(cardValues(view.container), ["4", "3", "1", "0"]);
    await view.unmount();
});

test("legacy queue (V2 off): the cards count the loaded documents", async () => {
    api.__respond("reviewQueueV2", {
        data: null, status: 404,
        error: { code: "feature_disabled", message: "not enabled" },
    });
    api.__respond("listReviewQueue", {
        data: [row("a", "submitted"), row("b", "submitted"), row("c", "approved"), row("d", "rejected")],
        error: null, status: 200,
    });
    const view = await mount();
    assert.deepEqual(view.errors, []);
    assert.deepEqual(cardValues(view.container), ["2", "1", "0", "1"]);
    await view.unmount();
});

test("a document whose wording the client edited is marked in the inbox (2026-10-08)", async () => {
    api.__respond("reviewQueueV2", {
        data: { items: [{ ...row("e", "submitted"), text_edited: true }, row("p", "submitted")],
                next_cursor: null, status: "all", counts: { all: 2, submitted: 2, approved: 0, returned: 0, rejected: 0 } },
        error: null, status: 200,
    });
    const view = await mount();
    assert.deepEqual(view.errors, []);
    const badges = view.container.querySelectorAll("[data-wording-edited]");
    assert.equal(badges.length, 1, "exactly the edited document carries the badge");
    assert.match(badges[0].textContent, /Wording edited/);
    await view.unmount();
});


/* ── the improved inbox layout (2026-10-09) ───────────────────────────── */

test("the filter cards ARE the tabs: one control, and choosing one asks the server", async () => {
    api.__respond("reviewQueueV2", {
        data: { items: [row("a", "submitted")], next_cursor: null, status: "all",
                counts: { all: 9, submitted: 4, approved: 3, returned: 1, rejected: 0 } },
        error: null, status: 200,
    });
    const view = await mount();
    const tabs = [...view.container.querySelectorAll('[role="tablist"][aria-label="Review status"] [role="tab"]')];
    assert.deepEqual(tabs.map(b => b.querySelector(".l").textContent),
        ["All documents", "Pending Review", "Approved", "Returned", "Rejected"]);
    assert.equal(tabs[0].querySelector(".v").textContent, "9");
    await act(async () => { tabs[2].dispatchEvent(new window.MouseEvent("click", { bubbles: true })); });
    await settle();
    assert.equal(tabs[2].getAttribute("aria-selected"), "true");
    assert.equal(api.__calls("reviewQueueV2").at(-1).args[0].status, "approved");
    await view.unmount();
});

test("work order: undecided first; urgent, then priority, then the longest waiting", async () => {
    const { workOrder } = await import("../src/components/lawyer/DocumentsPage.jsx");
    const d = (id, status, urgency, submittedAt) => ({ id, status, urgency, submittedAt });
    const rows = [
        d("approved", "Approved", "Urgent", "2026-10-01T00:00:00Z"),
        d("normal-old", "Pending Review", "Normal", "2026-10-01T00:00:00Z"),
        d("urgent-new", "Pending Review", "Urgent", "2026-10-08T00:00:00Z"),
        d("urgent-old", "Pending Review", "Urgent", "2026-10-02T00:00:00Z"),
        d("priority", "Pending Review", "Priority", "2026-10-03T00:00:00Z"),
    ];
    assert.deepEqual(workOrder(rows).map(r => r.id), ["urgent-old", "urgent-new", "priority", "normal-old", "approved"]);
});

test("waiting time reads in a lawyer's words", async () => {
    const { sinceWords } = await import("../src/components/lawyer/DocumentsPage.jsx");
    const now = Date.parse("2026-10-09T12:00:00Z");
    assert.equal(sinceWords("2026-10-09T11:59:30Z", now), "just now");
    assert.equal(sinceWords("2026-10-09T09:00:00Z", now), "3 h");
    assert.equal(sinceWords("2026-10-06T12:00:00Z", now), "3 days");
    assert.equal(sinceWords(null, now), null);
});

test("the filter beside the search narrows the rows, and says when nothing matches", async () => {
    api.__respond("reviewQueueV2", {
        data: { items: [{ ...row("u", "submitted"), urgency: "urgent" }, { ...row("n", "submitted"), urgency: "normal" }],
                next_cursor: null, status: "all", counts: { all: 2, submitted: 2, approved: 0, returned: 0, rejected: 0 } },
        error: null, status: 200,
    });
    const view = await mount();
    const rows = () => [...view.container.querySelectorAll("[data-inbox-row]")].map(r => r.dataset.inboxRow);
    assert.deepEqual(rows(), ["u", "n"], "urgent should come first");
    const select = view.container.querySelector("[data-inbox-filter]");
    await act(async () => { select.value = "normal"; select.dispatchEvent(new window.Event("change", { bubbles: true })); });
    await settle();
    assert.deepEqual(rows(), ["n"]);
    await act(async () => { select.value = "edited"; select.dispatchEvent(new window.Event("change", { bubbles: true })); });
    await settle();
    assert.deepEqual(rows(), []);
    assert.match(view.container.textContent, /Nothing matches with “Wording edited”/);
    await view.unmount();
});


/* ── the client's note is the client's (2026-10-09) ───────────────────── */

test("a decided row quotes the CLIENT's note, never the lawyer's own decision note", async () => {
    // Both notes used to live in review_note: after a decision the lawyer's
    // inbox showed their own words in the client's quote.
    api.__respond("reviewQueueV2", {
        data: { items: [
            { ...row("d", "returned"), queue_role: "decided", client_note: "urgent, filing Monday", review_note: "fix para 3" },
            { ...row("p", "submitted"), queue_role: "pending", client_note: "please check the dates", review_note: null },
        ], next_cursor: null, status: "all", counts: { all: 2, submitted: 1, approved: 0, returned: 1, rejected: 0 } },
        error: null, status: 200,
    });
    const view = await mount();
    assert.deepEqual(view.errors, []);
    const notes = [...view.container.querySelectorAll("[data-client-note]")].map(n => n.textContent);
    assert.ok(notes.some(n => /urgent, filing Monday/.test(n)), "the client's note on the decided row is missing");
    assert.ok(notes.some(n => /please check the dates/.test(n)));
    assert.ok(!notes.some(n => /fix para 3/.test(n)), "the lawyer's note is shown as the client's");
    await view.unmount();
});

test("arriving from a notification opens that document, not just the inbox (2026-10-09)", async () => {
    sessionStorage.setItem("attorney:lawyer-open-doc", "n1");
    api.__respond("reviewQueueV2", {
        data: { items: [row("a", "submitted"), { ...row("n1", "submitted"), queue_role: "pending" }],
                next_cursor: null, status: "all", counts: { all: 2, submitted: 2, approved: 0, returned: 0, rejected: 0 } },
        error: null, status: 200,
    });
    const view = await mount();
    await settle(60);
    assert.deepEqual(view.errors, []);
    assert.equal(view.container.querySelector("[data-inbox-row]"), null, "still on the inbox");
    assert.match(view.container.textContent, /Doc n1/);
    assert.equal(sessionStorage.getItem("attorney:lawyer-open-doc"), null, "the request is not consumed");
    await view.unmount();
});

test("a live document notification re-reads the queue while the lawyer is on it (2026-10-09)", async () => {
    api.__respond("reviewQueueV2", {
        data: { items: [row("a", "submitted")], next_cursor: null, status: "all",
                counts: { all: 1, submitted: 1, approved: 0, returned: 0, rejected: 0 } },
        error: null, status: 200,
    });
    const view = await mount();
    const before = api.__calls("reviewQueueV2").length;
    const { broadcastNotification } = await import("../src/lib/notificationTarget.js");
    await act(async () => { broadcastNotification({ type: "document_submitted", payload: { doc_id: "z" } }); });
    await settle();
    assert.ok(api.__calls("reviewQueueV2").length > before, "the queue was not re-read");
    await view.unmount();
});
