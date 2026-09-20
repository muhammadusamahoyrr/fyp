/* Paging the appointment lists, and what "all of them" is allowed to mean.
 *
 * WHAT WAS WRONG. Every caller asked for `page_size: 50` and never requested a
 * second page. Fifty is not "all" — it is the first fifty by the server's sort
 * — so a client or lawyer with a longer history was shown a truncated diary
 * with nothing saying so, and the lawyer dashboard counted the pending and
 * confirmed rows among those fifty and displayed the tally as a TOTAL. The
 * backend has paginated properly all along (`{items, total, page, page_size,
 * pages}`); nobody was reading past page one.
 *
 * THE FOUR INVARIANTS THESE TESTS HOLD.
 *
 *   * Appending, not replacing, and never the same row twice. The backend
 *     pages with skip/limit, so a row inserted or removed between requests
 *     shifts the window and can hand back something already on screen.
 *
 *   * "That is everything" only when the SERVER says so. A short page is not
 *     the signal — rows can be removed between requests — so completeness is
 *     read from `pages`, never inferred.
 *
 *   * A later-page failure keeps what is already shown. Those rows were read
 *     successfully; discarding them to report a partial failure destroys good
 *     data, and to a client it looks like appointments disappearing.
 *
 *   * A stale answer never lands. A filter changed while a request is in
 *     flight would otherwise have the older reply overwrite the newer one.
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

/** One appointment as the API returns it. */
function appt(id, over = {}) {
    const when = new Date(Date.now() + 72 * 36e5);
    when.setUTCMinutes(0, 0, 0);
    return {
        id,
        scheduled_at: when.toISOString(),
        end_at: new Date(when.getTime() + 36e5).toISOString(),
        duration_minutes: 60,
        status: "pending",
        mode: "video",
        lawyer_name: "Adv Ayesha Khan",
        client_name: `Client ${id}`,
        purpose: "Consultation",
        notes: null,
        case_id: null,
        timezone: "Asia/Karachi",
        schedule_version: 0,
        ...over,
    };
}

/** A paginated envelope in the backend's existing shape. */
function pageOf(items, { page = 1, pages = 1, total = items.length } = {}) {
    return { data: { items, total, page, page_size: 25, pages }, error: null, status: 200 };
}
function failed(message = "network down") {
    return { data: null, error: { message }, status: 0 };
}

async function mountLawyer() {
    const { AppointmentsPage } =
        await import("../src/components/lawyer/AppointmentsPage.jsx");
    const { NotifCtx } = await import("../src/components/lawyer/theme.js");

    const container = dom.window.document.createElement("div");
    dom.window.document.body.appendChild(container);
    const root = createRoot(container);
    await act(async () => {
        root.render(h(NotifCtx.Provider, { value: { addNotif: () => {} } },
                      h(AppointmentsPage)));
    });
    await act(async () => { await new Promise(r => realSetTimeout(r, 40)); });

    const buttons = () => [...container.querySelectorAll("button")];
    const byText = (label) => buttons().find(b => b.textContent.trim() === label);

    return {
        container,
        text: () => container.textContent,
        byText,
        // Tab buttons carry a count badge inside them, so their text is
        // "Completed·" rather than "Completed".
        clickStartingWith: async (prefix) => {
            const btn = buttons().find(b => b.textContent.trim().startsWith(prefix));
            assert.ok(btn, `no control starting with ${prefix}`);
            await act(async () => {
                btn.dispatchEvent(new dom.window.MouseEvent(
                    "click", { bubbles: true, cancelable: true }));
            });
            await act(async () => { await new Promise(r => realSetTimeout(r, 40)); });
        },
        click: async (label) => {
            const btn = byText(label);
            assert.ok(btn, `no control labelled ${label}`);
            await act(async () => {
                btn.dispatchEvent(new dom.window.MouseEvent(
                    "click", { bubbles: true, cancelable: true }));
            });
            await act(async () => { await new Promise(r => realSetTimeout(r, 30)); });
        },
        clickNoSettle: (label) => {
            const btn = byText(label);
            assert.ok(btn, `no control labelled ${label}`);
            btn.dispatchEvent(new dom.window.MouseEvent(
                "click", { bubbles: true, cancelable: true }));
        },
        settle: async (ms = 40) => {
            await act(async () => { await new Promise(r => realSetTimeout(r, ms)); });
        },
        unmount: async () => { await act(async () => root.unmount()); },
    };
}

/** Answer `listAppointments` from a table of responses keyed by page. */
function serveByPage(responses, { onCall } = {}) {
    const calls = [];
    api.__respond("listAppointments", (args = {}) => {
        calls.push(args);
        if (onCall) {
            const override = onCall(args, calls.length);
            if (override) return override;
        }
        const page = args.page || 1;
        return responses[page] || pageOf([], { page, pages: page });
    });
    return calls;
}

test.beforeEach(() => {
    api.__reset();
    api.__respond("bootstrapAuth", true);
    api.__respond("getMe", { data: { _id: "l1", role: "lawyer" } });
    api.__respond("listCases", { data: { items: [] } });
    api.__respond("getNotifications", { data: { items: [] } });
    api.__respond("listPendingOutcomes",
                  { data: { items: [], next_cursor: null, cutoff: "2026-10-01T00:00:00Z" }, error: null, status: 200 });
    api.__respond("getMyWorkingHours", {
        data: {
            lawyer_id: "l1", configured: false, enforced: false,
            timezone: "Asia/Karachi", working_hours: [], exceptions: [],
            updated_at: null,
        }, error: null, status: 200,
    });
});

test.after(() => {
    for (const id of liveTimers) { realClearInterval(id); realClearTimeout(id); }
    liveTimers.clear();
    dom.window.close();
});

/* ── two or more pages, appended in order ─────────────────────────────────── */

test("a second page is appended below the first, in server order", async () => {
    serveByPage({
        1: pageOf([appt("a1"), appt("a2")], { page: 1, pages: 2, total: 4 }),
        2: pageOf([appt("a3"), appt("a4")], { page: 2, pages: 2, total: 4 }),
    });
    const ui = await mountLawyer();

    assert.match(ui.text(), /Client a1/);
    assert.ok(!ui.text().includes("Client a3"));

    await ui.click("Load more appointments");

    const shown = ui.text();
    for (const id of ["a1", "a2", "a3", "a4"]) {
        assert.match(shown, new RegExp(`Client ${id}`), `${id} missing`);
    }
    // ORDER: the server's, preserved. Appending must not reshuffle.
    const positions = ["a1", "a2", "a3", "a4"].map(id => shown.indexOf(`Client ${id}`));
    assert.deepEqual(positions, [...positions].sort((x, y) => x - y),
                     "rows were not appended in server order");
    await ui.unmount();
});

test("the first page is not replaced by the second", async () => {
    serveByPage({
        1: pageOf([appt("a1")], { page: 1, pages: 2, total: 2 }),
        2: pageOf([appt("a2")], { page: 2, pages: 2, total: 2 }),
    });
    const ui = await mountLawyer();

    await ui.click("Load more appointments");

    assert.match(ui.text(), /Client a1/, "the first page was replaced");
    assert.match(ui.text(), /Client a2/);
    await ui.unmount();
});

test("a row returned twice is shown once", async () => {
    // The backend pages with skip/limit, so a row inserted or removed between
    // requests shifts the window and can return one already on screen.
    serveByPage({
        1: pageOf([appt("a1"), appt("a2")], { page: 1, pages: 2, total: 4 }),
        2: pageOf([appt("a2"), appt("a3")], { page: 2, pages: 2, total: 4 }),
    });
    const ui = await mountLawyer();

    await ui.click("Load more appointments");

    const shown = ui.text();
    const occurrences = shown.split("Client a2").length - 1;
    assert.equal(occurrences, 1, "a duplicated row was rendered twice");
    assert.match(shown, /Client a3/);
    await ui.unmount();
});

/* ── repeated clicks ──────────────────────────────────────────────────────── */

test("clicking Load more twice does not request the same page twice", async () => {
    // Without the guard the second click requests page 2 again and appends it,
    // duplicating every row on it.
    const calls = serveByPage({
        1: pageOf([appt("a1")], { page: 1, pages: 3, total: 3 }),
        2: pageOf([appt("a2")], { page: 2, pages: 3, total: 3 }),
        3: pageOf([appt("a3")], { page: 3, pages: 3, total: 3 }),
    });
    const ui = await mountLawyer();

    ui.clickNoSettle("Load more appointments");
    ui.clickNoSettle("Load more appointments");
    await ui.settle(60);

    const pagesAsked = calls.filter(c => c.page === 2).length;
    assert.equal(pagesAsked, 1, `page 2 was requested ${pagesAsked} times`);
    await ui.unmount();
});

test("the control exposes its loading state and is a real button", async () => {
    serveByPage({
        1: pageOf([appt("a1")], { page: 1, pages: 2, total: 2 }),
        2: pageOf([appt("a2")], { page: 2, pages: 2, total: 2 }),
    });
    const ui = await mountLawyer();

    const btn = ui.byText("Load more appointments");
    assert.ok(btn, "no Load more control");
    assert.equal(btn.tagName, "BUTTON", "not keyboard-reachable");
    assert.equal(btn.getAttribute("type"), "button");
    assert.ok(!btn.disabled);
    await ui.unmount();
});

/* ── end of list, honestly ────────────────────────────────────────────────── */

test("no Load more when the server says this is the only page", async () => {
    serveByPage({ 1: pageOf([appt("a1")], { page: 1, pages: 1, total: 1 }) });
    const ui = await mountLawyer();

    assert.equal(ui.byText("Load more appointments"), undefined);
    assert.match(ui.text(), /that is all of them/i);
    await ui.unmount();
});

test("completeness is never inferred from a short page", async () => {
    // A page can be short because rows were removed between requests. Saying
    // "that is everything" on that basis is a claim the server never made.
    serveByPage({
        1: pageOf([appt("a1")], { page: 1, pages: 4, total: 40 }),
    });
    const ui = await mountLawyer();

    assert.ok(ui.byText("Load more appointments"),
              "a short page was treated as the end of the list");
    assert.ok(!/that is all of them/i.test(ui.text()));
    await ui.unmount();
});

test("the count shown is the server's total, not the rows in hand", async () => {
    serveByPage({ 1: pageOf([appt("a1"), appt("a2")], { page: 1, pages: 5, total: 97 }) });
    const ui = await mountLawyer();

    assert.match(ui.text(), /Showing 2 of 97/);
    await ui.unmount();
});

/* ── failures ─────────────────────────────────────────────────────────────── */

test("a later-page failure keeps the rows already shown", async () => {
    serveByPage({ 1: pageOf([appt("a1")], { page: 1, pages: 2, total: 2 }) },
                { onCall: (args) => (args.page === 2 ? failed() : null) });
    const ui = await mountLawyer();

    await ui.click("Load more appointments");

    assert.match(ui.text(), /Client a1/, "a later failure erased earlier rows");
    assert.match(ui.text(), /already shown are unaffected/i);
    await ui.unmount();
});

test("a first-page failure is not an empty list", async () => {
    // `apiFetch` RESOLVES on failure, so an unchecked `data?.items || []` here
    // is how a network error becomes "no appointments".
    api.__respond("listAppointments", (args = {}) =>
        (args.page_size === 1 ? pageOf([], { total: 0 }) : failed()));
    const ui = await mountLawyer();

    assert.match(ui.text(), /could not read the list/i);
    assert.ok(!/No appointments found/i.test(ui.text()),
              "a failed read was reported as an empty list");
    await ui.unmount();
});

/* ── filter changes ───────────────────────────────────────────────────────── */

test("changing the tab asks the server and resets to page one", async () => {
    const calls = serveByPage({
        1: pageOf([appt("a1")], { page: 1, pages: 2, total: 2 }),
        2: pageOf([appt("a2")], { page: 2, pages: 2, total: 2 }),
    });
    const ui = await mountLawyer();
    await ui.click("Load more appointments");

    const before = calls.length;
    await ui.clickStartingWith("Completed");

    const after = calls.slice(before).filter(c => c.page_size !== 1);
    assert.ok(after.length >= 1, "changing the tab did not re-query the server");
    assert.equal(after[0].page, 1, "the new filter did not reset to page one");
    assert.equal(after[0].status, "completed",
                 "the tab was not applied server-side");
    await ui.unmount();
});

test("a stale answer from the previous filter is ignored", async () => {
    // The old filter's reply arrives after the new one's. Letting it land
    // would show rows from a tab the lawyer has already left.
    let resolveSlow;
    api.__respond("listAppointments", (args = {}) => {
        if (args.page_size === 1) return pageOf([], { total: 0 });
        if (args.status === undefined) {
            return new Promise(res => { resolveSlow = () => res(
                pageOf([appt("stale")], { page: 1, pages: 1, total: 1 })); });
        }
        return pageOf([appt("fresh")], { page: 1, pages: 1, total: 1 });
    });

    const ui = await mountLawyer();          // "All" request is pending
    await ui.clickStartingWith("Completed"); // newer request resolves at once
    resolveSlow?.();                         // the older one lands late
    await ui.settle(60);

    assert.match(ui.text(), /Client fresh/);
    assert.ok(!ui.text().includes("Client stale"),
              "a stale response from the previous filter overwrote the list");
    await ui.unmount();
});

/* ── the dashboard ────────────────────────────────────────────────────────── */

test("the dashboard total comes from the server, not the first page", async () => {
    // It used to fetch fifty rows, count the pending and confirmed ones among
    // them, and show that as "Appointments — Pending + Confirmed". For anyone
    // with more than fifty it under-reported work, silently.
    const { DashboardPage } =
        await import("../src/components/lawyer/DashboardPage.jsx");
    const { NotifCtx, CaseCtx } = await import("../src/components/lawyer/theme.js");
    const { AuthProvider } = await import("../src/context/AuthContext.jsx");

    const seen = [];
    api.__respond("listAppointments", (args = {}) => {
        seen.push(args);
        if (args.status === "pending") return pageOf([appt("p")], { total: 61, pages: 61 });
        if (args.status === "confirmed") return pageOf([appt("c")], { total: 12, pages: 12 });
        return pageOf([], { total: 73, pages: 3 });
    });
    api.__respond("listCases", { data: { items: [] } });

    const container = dom.window.document.createElement("div");
    dom.window.document.body.appendChild(container);
    const root = createRoot(container);
    await act(async () => {
        root.render(h(AuthProvider, null,
            h(NotifCtx.Provider, { value: { addNotif: () => {} } },
                h(CaseCtx.Provider, {
                    value: {
                        setActiveCase: () => {}, setOpenCaseId: () => {},
                        setPage: () => {},
                    },
                }, h(DashboardPage)))));
    });
    await act(async () => { await new Promise(r => realSetTimeout(r, 80)); });

    // 61 + 12 = 73, which no single page of rows could have told it.
    assert.match(container.textContent, /73/,
                 "the dashboard did not use the server's totals");
    const counted = seen.filter(a => a.status && a.page_size === 1);
    assert.equal(counted.length, 2, "totals were not read with bounded requests");
    await act(async () => root.unmount());
});

test("the dashboard labels its agenda as a preview", async () => {
    const { DashboardPage } =
        await import("../src/components/lawyer/DashboardPage.jsx");
    const { NotifCtx, CaseCtx } = await import("../src/components/lawyer/theme.js");
    const { AuthProvider } = await import("../src/context/AuthContext.jsx");

    api.__respond("listAppointments", (args = {}) =>
        (args.status ? pageOf([], { total: 0 }) : pageOf([], { total: 0, pages: 1 })));
    api.__respond("listCases", { data: { items: [] } });

    const container = dom.window.document.createElement("div");
    dom.window.document.body.appendChild(container);
    const root = createRoot(container);
    await act(async () => {
        root.render(h(AuthProvider, null,
            h(NotifCtx.Provider, { value: { addNotif: () => {} } },
                h(CaseCtx.Provider, {
                    value: {
                        setActiveCase: () => {}, setOpenCaseId: () => {},
                        setPage: () => {},
                    },
                }, h(DashboardPage)))));
    });
    await act(async () => { await new Promise(r => realSetTimeout(r, 80)); });

    assert.match(container.textContent, /Preview/i,
                 "a bounded agenda was presented as the complete one");
    await act(async () => root.unmount());
});

/* ── CaseContext ──────────────────────────────────────────────────────────── */

test("the overview offers a real control that loads page two", async () => {
    // EXPOSING `loadMoreAppointments` IS NOT ENOUGH. Until something a user
    // can click calls it, the shared cache is still the first fifty rows
    // presented as the whole set — which is what `apptCount` displayed.
    const { CaseProvider } = await import("../src/components/shared/CaseContext.jsx");
    const ModOverview = (await import("../src/components/client/ModOverview.jsx")).default;
    const { AuthProvider } = await import("../src/context/AuthContext.jsx");

    const asked = [];
    api.__respond("listAppointments", (args = {}) => {
        asked.push(args);
        return (args.page || 1) === 1
            ? pageOf([appt("first")], { page: 1, pages: 2, total: 2 })
            : pageOf([appt("second")], { page: 2, pages: 2, total: 2 });
    });
    api.__respond("listCases", { data: { items: [] } });
    api.__respond("getNotifications", { data: [] });

    const container = dom.window.document.createElement("div");
    dom.window.document.body.appendChild(container);
    const root = createRoot(container);
    await act(async () => {
        root.render(h(AuthProvider, null,
            h(CaseProvider, null, h(ModOverview))));
    });
    await act(async () => { await new Promise(r => realSetTimeout(r, 80)); });

    const button = [...container.querySelectorAll("button")]
        .find(b => b.textContent.trim().startsWith("Load more appointments"));
    assert.ok(button, "no user-accessible control loads the next page");
    assert.equal(button.tagName, "BUTTON", "not keyboard-reachable");

    await act(async () => {
        button.dispatchEvent(new dom.window.MouseEvent(
            "click", { bubbles: true, cancelable: true }));
    });
    await act(async () => { await new Promise(r => realSetTimeout(r, 80)); });

    const pagesAsked = asked.filter(a => a.page === 2);
    assert.equal(pagesAsked.length, 1,
                 `page two was not requested: ${JSON.stringify(asked)}`);

    // And once the server says that is everything, the control goes.
    const after = [...container.querySelectorAll("button")]
        .find(b => b.textContent.trim().startsWith("Load more appointments"));
    assert.equal(after, undefined,
                 "the control remained after the server reported the last page");
    await act(async () => root.unmount());
});

test("the overview count is the server's total, not the cached page", async () => {
    const { CaseProvider } = await import("../src/components/shared/CaseContext.jsx");
    const ModOverview = (await import("../src/components/client/ModOverview.jsx")).default;
    const { AuthProvider } = await import("../src/context/AuthContext.jsx");

    api.__respond("listAppointments", () =>
        pageOf([appt("a1"), appt("a2")], { page: 1, pages: 4, total: 87 }));
    api.__respond("listCases", { data: { items: [] } });
    api.__respond("getNotifications", { data: [] });

    const container = dom.window.document.createElement("div");
    dom.window.document.body.appendChild(container);
    const root = createRoot(container);
    await act(async () => {
        root.render(h(AuthProvider, null,
            h(CaseProvider, null, h(ModOverview))));
    });
    await act(async () => { await new Promise(r => realSetTimeout(r, 80)); });

    assert.match(container.textContent, /87/,
                 "the overview counted the cached page instead of the total");
    await act(async () => root.unmount());
});

test("CaseContext records whether its cached list is complete", async () => {
    // The cache is the FIRST PAGE. Every consumer read it as the whole set;
    // now it carries the flag so a surface that needs certainty can ask.
    const { readFileSync } = await import("node:fs");
    const source = readFileSync(
        new URL("../src/components/shared/CaseContext.jsx", import.meta.url),
        "utf8");

    assert.match(source, /appointmentsComplete/,
                 "CaseContext still treats the first page as the complete set");
    assert.match(source, /loadMoreAppointments/,
                 "CaseContext offers no way to load the rest");
    assert.match(source, /pages\s*<=\s*1/,
                 "completeness is not read from the server's page count");
});

test("CaseContext does not fetch further pages on its own", async () => {
    // Pulling an unbounded history into memory on mount is a cost every screen
    // pays for one screen's benefit.
    const { readFileSync } = await import("node:fs");
    const source = readFileSync(
        new URL("../src/components/shared/CaseContext.jsx", import.meta.url),
        "utf8");

    const autoLoop = /while\s*\(|for\s*\(\s*let\s+page/.test(source);
    assert.ok(!autoLoop, "CaseContext loops over pages automatically");
});
