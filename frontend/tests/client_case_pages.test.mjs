/* Client case pages show the server's data, and nothing invented.
 *
 * WHAT WAS WRONG.
 *   * Communication read `documents`, which did not exist in that component:
 *     the page threw as soon as its message form rendered.
 *   * It showed "Atty. Ahmad Raza — Online" for every case and labelled every
 *     lawyer message with that name, a fixed "1 Awaiting" badge and two
 *     invented questions.
 *   * A failed send still appeared as sent; the lawyer never received it.
 *   * "Next hearing" was hearing_dates[0]: the OLDEST hearing, never moving on
 *     after an adjournment or a reschedule.
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
                    "Element", "Node", "Event", "CustomEvent", "MouseEvent",
                    "KeyboardEvent", "MutationObserver", "getComputedStyle",
                    "localStorage", "requestAnimationFrame",
                    "cancelAnimationFrame"]) {
    define(name, dom.window[name]);
}
define("IS_REACT_ACT_ENVIRONMENT", true);

// jsdom implements no `matchMedia`, and `useIsMobile` calls it on mount. A
// desktop-width stub keeps the responsive layout on its wide branch, which is
// the one the cancel controls have to work in as well as the narrow one — the
// touch-target assertions below are on the styles themselves, so they hold
// either way.
if (!dom.window.matchMedia) {
    dom.window.matchMedia = (query) => ({
        matches: false, media: query, onchange: null,
        addEventListener() {}, removeEventListener() {},
        addListener() {}, removeListener() {},
        dispatchEvent() { return false; },
    });
}

const liveTimers = new Set();
const realSetInterval = globalThis.setInterval;
const realClearInterval = globalThis.clearInterval;
const realSetTimeout = globalThis.setTimeout;
const realClearTimeout = globalThis.clearTimeout;
define("setInterval", (...a) => { const id = realSetInterval(...a); liveTimers.add(id); return id; });
define("clearInterval", id => { liveTimers.delete(id); return realClearInterval(id); });
define("setTimeout", (...a) => { const id = realSetTimeout(...a); liveTimers.add(id); return id; });
define("clearTimeout", id => { liveTimers.delete(id); return realClearTimeout(id); });

const React = (await import("react")).default;
const { act } = await import("react");
const { createRoot } = await import("react-dom/client");
const api = await import("./support/api-stub.mjs");

const { createElement: h } = React;

/* An appointment as the API returns one. */
function appointment(over = {}) {
    const when = new Date(Date.now() + 72 * 36e5);
    when.setUTCMinutes(0, 0, 0);
    return {
        id: "apt-1",
        scheduled_at: when.toISOString(),
        end_at: new Date(when.getTime() + 36e5).toISOString(),
        duration_minutes: 60,
        status: "pending",
        mode: "video",
        lawyer_name: "Adv Ayesha Khan",
        client_name: "Test Client",
        notes: null,
        case_id: null,
        timezone: "Asia/Karachi",
        ...over,
    };
}

/** Queue one response per successive `listAppointments` call.
 *
 * This is what makes "the reload shows the SERVER's status" testable: the
 * second page of results is different from the first, so a component that
 * patched its own state instead of re-reading would keep showing the first.
 */
function serveAppointments(...pages) {
    let i = 0;
    api.__respond("listAppointments", () => {
        const page = pages[Math.min(i, pages.length - 1)];
        i += 1;
        return { data: { items: page }, error: null, status: 200 };
    });
    return { calls: () => i };
}

async function mountTracking() {
    const Module7 = (await import("../src/components/client/ModTracking.jsx")).default;
    const { CaseCtx } = await import("../src/components/shared/CaseContext.jsx");

    const container = dom.window.document.createElement("div");
    dom.window.document.body.appendChild(container);
    const root = createRoot(container);

    // The context this page actually reads. `useCase` throws without a
    // provider, so the minimum real shape is supplied rather than mocking the
    // component's own module.
    const ctx = {
        notifications: [],
        markNotificationDone: () => {},
        markAllNotificationsDone: () => {},
        appointmentMilestones: [],
    };

    await act(async () => {
        root.render(h(CaseCtx.Provider, { value: ctx }, h(Module7, { isDark: true })));
    });
    await act(async () => { await new Promise(r => realSetTimeout(r, 30)); });

    const buttons = () => [...container.querySelectorAll("button")];
    const byText = (label) => buttons().find(b => b.textContent.trim() === label);

    const click = async (labelOrEl) => {
        const isLabel = typeof labelOrEl === "string";
        const el = isLabel ? byText(labelOrEl) : labelOrEl;
        // The message is built only from a string label. A template literal is
        // evaluated eagerly even when the assertion passes, and
        // `JSON.stringify` on a DOM node throws on its circular structure —
        // which turned every test in this file into the same misleading error.
        assert.ok(el, isLabel ? `no control labelled ${labelOrEl}` : "no control to click");
        await act(async () => {
            el.dispatchEvent(new dom.window.MouseEvent(
                "click", { bubbles: true, cancelable: true }));
        });
        await act(async () => { await new Promise(r => realSetTimeout(r, 20)); });
    };

    const ui = {
        container, buttons, byText, click,
        text: () => container.textContent,
        /** Open the Appointments page through the real navigation.
         *
         * The sidebar entries are `<div onClick>` rather than buttons — a
         * pre-existing accessibility gap in the navigation, untouched here
         * because this change is about the cancel action. It is why this looks
         * for a div and not a button; if the nav is ever made keyboard-usable,
         * this helper is the thing that should start failing.
         */
        openPage: async (label) => {
            const nav = [...container.querySelectorAll("div")].find(el => el.textContent.trim() === label);
            assert.ok(nav, `no ${label} nav control`);
            await click(nav);
            await act(async () => { await new Promise(r => realSetTimeout(r, 60)); });
        },
        openAppointments: async () => {
            const nav = [...container.querySelectorAll("div")]
                .find(el => el.textContent.trim() === "Appointments");
            assert.ok(nav, "no Appointments nav control");
            await click(nav);
        },
        settle: async (ms = 30) => {
            await act(async () => { await new Promise(r => realSetTimeout(r, ms)); });
        },
        unmount: async () => { await act(async () => root.unmount()); },
    };
    return ui;
}


const { pktToday } = await import("../src/lib/bookingTime.js");
function addDays(n) {
    const d = new Date(`${pktToday()}T12:00:00Z`);
    d.setUTCDate(d.getUTCDate() + n);
    return d.toISOString().slice(0, 10);
}
const CASE = {
    _id: "case1", title: "Rent dispute", status: "in_progress", case_type: "civil", lawyer_id: "law1",
    created_at: "2026-09-01T00:00:00Z", milestones: [],
    hearing_dates: [
        { _id: "old", date: `${addDays(-20)}T00:00:00Z`, time: "09:00", court: "Old Court", outcome: "adjourned" },
        { _id: "late", date: `${addDays(30)}T00:00:00Z`, time: "11:00", court: "Late Court", outcome: null },
        { _id: "soon", date: `${addDays(9)}T00:00:00Z`, time: "10:30", court: "Civil Court Lahore", outcome: null },
    ],
};

test.beforeEach(() => {
    api.__reset();
    api.__respond("bootstrapAuth", true);
    api.__respond("getMe", { data: { _id: "c1", role: "client" } });
    api.__respond("listCases", { data: { items: [CASE] } });
    api.__respond("getNotifications", { data: { items: [] } });
    api.__respond("getCaseTimeline", { data: { case_id: "case1", milestones: [], hearing_dates: CASE.hearing_dates }, error: null });
    api.__respond("listMessages", { data: [
        { _id: "m1", sender_role: "lawyer", sender_name: "Adv Sana Malik", text: "Please bring the deed.", created_at: "2026-10-01T05:00:00Z" },
        { _id: "m2", sender_role: "client", sender_name: "Client", text: "Is the date fixed?", created_at: "2026-10-02T05:00:00Z" },
    ], error: null });
});

test.after(() => {
    for (const id of liveTimers) { realClearInterval(id); realClearTimeout(id); }
    liveTimers.clear();
    dom.window.close();
});

test("Communication renders the real conversation, with no invented names or questions", async () => {
    const errors = [];
    const realError = console.error;
    console.error = (...a) => errors.push(a.map(String).join(" "));
    try {
        const ui = await mountTracking();
        await ui.openPage("Communication");
        const text = ui.text();
        assert.ok(!errors.some(e => /documents is not defined|ReferenceError/.test(e)), errors.join("\n"));
        assert.match(text, /Adv Sana Malik/);
        assert.doesNotMatch(text, /Ahmad Raza|Exhibit C|Online/);
        assert.match(text, /1 awaiting reply/);
        assert.match(text, /Is the date fixed\?/);
        await ui.unmount();
    } finally {
        console.error = realError;
    }
});

test("a message that fails to send is not shown as sent, and the text is kept", async () => {
    api.__respond("sendMessage", { data: null, error: { message: "This case is closed, so it can no longer be changed." }, status: 409 });
    const ui = await mountTracking();
    await ui.openPage("Communication");
    const input = ui.container.querySelector('input[placeholder^="Ask your lawyer"]');
    assert.ok(input, "no message box");
    const setter = Object.getOwnPropertyDescriptor(dom.window.HTMLInputElement.prototype, "value").set;
    await act(async () => { setter.call(input, "Hello?"); input.dispatchEvent(new dom.window.Event("input", { bubbles: true })); });
    await ui.click(ui.buttons().find(b => b.textContent.includes("Send")));
    await ui.settle(40);
    assert.match(ui.text(), /can no longer be changed/);
    assert.equal(ui.container.querySelector('input[placeholder^="Ask your lawyer"]').value, "Hello?");
    assert.doesNotMatch(ui.text(), /✓ Sent/);
    await ui.unmount();
});

test("the next hearing is the next upcoming one, not the first ever added", async () => {
    const { nextHearingOf } = await import("../src/components/client/ModTracking.jsx");
    assert.equal(nextHearingOf(CASE.hearing_dates)._id, "soon");
    assert.equal(nextHearingOf([{ _id: "x", date: `${addDays(-3)}T00:00:00Z`, outcome: null }]), null, "a past hearing is not 'next'");
    const ui = await mountTracking();
    await ui.settle(60);
    const text = ui.text();
    assert.match(text, /10:30/);
    assert.doesNotMatch(text, /Old Court/);
    await ui.unmount();
});

test("a lawyer's reply arriving live is shown on Communication; another case's is not", async () => {
    const { broadcastNotification } = await import("../src/lib/notificationTarget.js");
    const ui = await mountTracking();
    await ui.openPage("Communication");
    const reads = () => api.__calls("listMessages").length;
    const before = reads();
    await act(async () => { broadcastNotification({ type: "case_message", payload: { case_id: "other-case" } }); });
    await ui.settle(40);
    assert.equal(reads(), before, "a message on another case re-read this thread");
    await act(async () => { broadcastNotification({ type: "case_message", payload: { case_id: "case1" } }); });
    await ui.settle(40);
    assert.ok(reads() > before, "the thread was not re-read when the lawyer replied");
    await ui.unmount();
});

test("a rescheduled hearing shows the client where it moved from, and why", async () => {
    const { mapApiHearing } = await import("../src/components/client/ModTracking.jsx");
    const row = mapApiHearing({ _id: "h1", date: "2026-11-20T00:00:00Z", court: "Civil Court Lahore", outcome: null,
        reschedules: [{ from_date: "2026-11-12T00:00:00Z", to_date: "2026-11-20T00:00:00Z", reason: "Judge on leave" }] }, 0);
    const { formatPkt } = await import("../src/lib/bookingTime.js");
    const from = formatPkt("2026-11-12T00:00:00Z", { month: "short", day: "numeric" });
    assert.equal(row.desc, `Civil Court Lahore · Moved from ${from} — Judge on leave`);
    const plain = mapApiHearing({ _id: "h2", date: "2026-11-20T00:00:00Z", court: "Civil Court Lahore" }, 1);
    assert.doesNotMatch(plain.desc, /Moved/);
});

/* ── Documents: every control does something ──────────────────────────── */

const DOCS = [
    { _id: "d1", title: "Affidavit", template_type: "affidavit", created_at: "2026-09-01T05:00:00Z" },
    { _id: "d2", title: "Legal notice", template_type: "legal_notice", created_at: "2026-10-01T05:00:00Z" },
];

test("documents list newest first, sort by name, and Download fetches the real file", async () => {
    api.__respond("listDocuments", { data: DOCS, error: null });
    api.__respond("downloadDocument", { data: true });
    const ui = await mountTracking();
    await ui.openPage("Documents");
    const names = () => [...ui.container.querySelectorAll("[data-doc]")].map(el => el.getAttribute("data-doc"));
    assert.deepEqual(names(), ["d2", "d1"], "newest first");
    const sort = ui.container.querySelector('select[aria-label="Sort documents"]');
    await act(async () => {
        Object.getOwnPropertyDescriptor(dom.window.HTMLSelectElement.prototype, "value").set.call(sort, "name");
        sort.dispatchEvent(new dom.window.Event("change", { bubbles: true }));
    });
    assert.deepEqual(names(), ["d1", "d2"], "Affidavit before Legal notice");
    const row = ui.container.querySelector('[data-doc="d1"]');
    await ui.click([...row.querySelectorAll("button")].find(b => b.textContent.includes("Download")));
    assert.deepEqual(api.__calls("downloadDocument").map(c => c.args), [["d1", "Affidavit.pdf"]]);
    assert.doesNotMatch(ui.text(), /Seen by lawyer|Not yet seen|Version History/);
    await ui.unmount();
});

test("the case lists its V2 documents too, and opens/downloads the exact revision (2026-10-09)", async () => {
    // The legacy case listing drops V2 rows by design, and nothing here asked
    // the V2 routes: a drafted, even approved, document never showed on its case.
    api.__respond("listDocuments", { data: DOCS, error: null });
    api.__respond("myDocumentsV2", { data: { items: [
        { id: "v1", title: "Plaint", template_type: "plaint_civil", case_id: "c1", review_status: "approved",
          revision_id: "r7", pdf_sha256: "abc", downloadable: true, created_at: "2026-10-05T05:00:00Z" },
    ], has_more: false }, error: null });
    api.__respond("downloadDocumentFile", { data: true });
    const ui = await mountTracking();
    await ui.openPage("Documents");
    const row = ui.container.querySelector('[data-doc="v1"]');
    assert.ok(row, "the V2 document is missing from the case");
    assert.equal(api.__calls("myDocumentsV2")[0].args[0].caseId !== undefined, true, "not narrowed to the case");
    assert.ok(row.querySelector("[data-doc-status]"), "its review status is not shown");
    await ui.click([...row.querySelectorAll("button")].find(b => b.textContent.includes("Download")));
    assert.deepEqual(api.__calls("downloadDocumentFile").map(c => c.args),
        [["v1", "Plaint.pdf", { revisionId: "r7", expectedPdfSha256: "abc" }]]);
    assert.equal(api.__calls("downloadDocument").length, 0, "the legacy route 404s on a V2 document");
    await ui.unmount();
});

test("a failed Open says why on that document", async () => {
    api.__respond("listDocuments", { data: DOCS, error: null });
    api.__respond("fetchDocumentPreviewUrl", { error: "Preview failed" });
    const ui = await mountTracking();
    await ui.openPage("Documents");
    const row = ui.container.querySelector('[data-doc="d2"]');
    await ui.click([...row.querySelectorAll("button")].find(b => b.textContent.includes("Open")));
    assert.match(ui.container.querySelector('[data-doc="d2"]').textContent, /Preview failed/);
    await ui.unmount();
});

test("a failed documents read is not shown as an empty case", async () => {
    api.__respond("listDocuments", { data: null, error: { message: "Server unavailable" } });
    const ui = await mountTracking();
    await ui.openPage("Documents");
    assert.match(ui.text(), /Server unavailable/);
    assert.doesNotMatch(ui.text(), /No documents on this case yet/);
    await ui.unmount();
});

test("switching case while the first case is still loading never shows the first case's hearings", async () => {
    const A = { ...CASE, _id: "caseA", title: "Case Alpha", hearing_dates: [] };
    const B = { ...CASE, _id: "caseB", title: "Case Beta", hearing_dates: [] };
    api.__respond("listCases", { data: { items: [A, B] } });
    api.__respond("getCaseTimeline", async (id) => {
        // Alpha's answer is slow and arrives AFTER Beta's.
        if (id === "caseA") await new Promise(r => realSetTimeout(r, 250));
        const court = id === "caseA" ? "Alpha Court" : "Beta Court";
        return { data: { case_id: id, milestones: [], hearing_dates: [
            { _id: `h-${id}`, date: `${addDays(5)}T00:00:00Z`, time: "10:00", court, outcome: null },
        ] }, error: null };
    });
    const ui = await mountTracking();
    const switcher = ui.buttons().find(b => b.textContent.includes("Case Alpha"));
    await ui.click(switcher);
    const beta = [...ui.container.querySelectorAll("div")].find(d => d.style.cursor === "pointer" && d.textContent.includes("Case Beta"));
    await ui.click(beta);
    await ui.settle(400);
    assert.match(ui.text(), /Beta Court/);
    assert.doesNotMatch(ui.text(), /Alpha Court/, "the previous case's late answer was shown under the new case");
    await ui.unmount();
});
