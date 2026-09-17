/* Client-side appointment cancellation, and the removal of the fake lawyer
 * scheduling controls.
 *
 * TWO HALVES OF ONE PROBLEM.
 *
 * The client's appointments page was read-only, so `cancelled_by: "client"`
 * could never occur: the backend path existed, was tested, and nothing in the
 * product could reach it. Meanwhile the LAWYER's page offered Schedule and
 * Reschedule buttons that only ever mutated React state — a "booked"
 * appointment got `id: Date.now()` and vanished on refresh, and a "reschedule"
 * rewrote the display strings without touching the stored time. One real
 * capability was unreachable and two fake ones were prominent.
 *
 * The cancellation is deliberately NOT optimistic, and these tests are written
 * to fail if it ever becomes so. The server owns the outcome — it refuses
 * inside the two-hour cutoff, and the lawyer may have moved the appointment
 * first — so a local "cancelled" would show a state the database does not hold.
 * Every assertion about the result therefore looks at what the SERVER returned
 * on reload, not at what the click did to local state.
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

test.beforeEach(() => {
    api.__reset();
    api.__respond("bootstrapAuth", true);
    api.__respond("getMe", { data: { _id: "c1", role: "client" } });
    api.__respond("listCases", { data: { items: [] } });
    api.__respond("getNotifications", { data: { items: [] } });
});

test.after(() => {
    for (const id of liveTimers) { realClearInterval(id); realClearTimeout(id); }
    liveTimers.clear();
    dom.window.close();
});

/* ── which appointments offer the action ──────────────────────────────────── */

for (const status of ["pending", "confirmed"]) {
    test(`a ${status} appointment offers cancellation`, async () => {
        serveAppointments([appointment({ status })]);
        const ui = await mountTracking();
        await ui.openAppointments();

        assert.ok(ui.byText("Cancel appointment"),
                  `no cancel control on a ${status} appointment`);
        await ui.unmount();
    });
}

for (const status of ["cancelled", "completed", "no_show"]) {
    test(`a ${status} appointment offers no cancellation`, async () => {
        // The server's transition table makes these terminal, so the control
        // would be a button that always fails.
        serveAppointments([appointment({ status })]);
        const ui = await mountTracking();
        await ui.openAppointments();

        assert.equal(ui.byText("Cancel appointment"), undefined,
                     `cancel offered on a ${status} appointment`);
        await ui.unmount();
    });
}

/* ── confirmation before sending ──────────────────────────────────────────── */

test("the first click confirms rather than cancelling", async () => {
    serveAppointments([appointment()]);
    const ui = await mountTracking();
    await ui.openAppointments();

    await ui.click("Cancel appointment");

    assert.equal(api.__calls("cancelAppointment").length, 0,
                 "the appointment was cancelled without confirmation");
    assert.ok(ui.byText("Yes, cancel it"));
    assert.ok(ui.byText("Keep appointment"));
    await ui.unmount();
});

test("the confirmation explains the two-hour cutoff", async () => {
    // A client who reads it can ring the lawyer instead. One who does not just
    // meets a 422 they cannot act on.
    serveAppointments([appointment()]);
    const ui = await mountTracking();
    await ui.openAppointments();
    await ui.click("Cancel appointment");

    const text = ui.text();
    assert.match(text, /2 hours/);
    assert.match(text, /cannot be undone/i);
    await ui.unmount();
});

test("keeping the appointment sends nothing", async () => {
    serveAppointments([appointment()]);
    const ui = await mountTracking();
    await ui.openAppointments();
    await ui.click("Cancel appointment");

    await ui.click("Keep appointment");

    assert.equal(api.__calls("cancelAppointment").length, 0);
    assert.ok(ui.byText("Cancel appointment"), "the action should be offered again");
    await ui.unmount();
});

/* ── success ──────────────────────────────────────────────────────────────── */

test("a confirmed cancellation calls the existing endpoint with the id", async () => {
    serveAppointments([appointment()], [appointment({ status: "cancelled" })]);
    api.__respond("cancelAppointment", { data: { success: true }, error: null, status: 200 });
    const ui = await mountTracking();
    await ui.openAppointments();
    await ui.click("Cancel appointment");

    await ui.click("Yes, cancel it");

    const calls = api.__calls("cancelAppointment");
    assert.equal(calls.length, 1);
    assert.equal(calls[0].args[0], "apt-1");
    await ui.unmount();
});

test("the status shown after cancelling is the server's, not a local guess", async () => {
    // The server is made to answer with a status the client did NOT ask for.
    // A component that wrote "cancelled" into its own state would show
    // "Cancelled"; one that re-reads shows what the database actually holds.
    serveAppointments(
        [appointment({ status: "pending" })],
        [appointment({ status: "no_show" })],
    );
    api.__respond("cancelAppointment", { data: { success: true }, error: null, status: 200 });
    const ui = await mountTracking();
    await ui.openAppointments();
    await ui.click("Cancel appointment");

    await ui.click("Yes, cancel it");

    assert.match(ui.text(), /No Show/,
                 "the card did not re-read the server after cancelling");
    assert.doesNotMatch(ui.text(), /Cancelled/,
                        "a local cancelled status was invented");
    await ui.unmount();
});

test("a successful cancellation re-reads the list from the server", async () => {
    const served = serveAppointments(
        [appointment()], [appointment({ status: "cancelled" })]);
    api.__respond("cancelAppointment", { data: { success: true }, error: null, status: 200 });
    const ui = await mountTracking();
    await ui.openAppointments();
    const before = served.calls();
    await ui.click("Cancel appointment");

    await ui.click("Yes, cancel it");

    assert.ok(served.calls() > before,
              "no reload was issued after a successful cancellation");
    await ui.unmount();
});

test("the server's status survives a remount", async () => {
    // The durability check. A local status would be gone after unmount anyway;
    // this proves the cancellation reached the server by mounting a fresh tree
    // that knows nothing about the previous one.
    serveAppointments(
        [appointment({ status: "pending" })],
        [appointment({ status: "cancelled" })],
    );
    api.__respond("cancelAppointment", { data: { success: true }, error: null, status: 200 });

    const first = await mountTracking();
    await first.openAppointments();
    await first.click("Cancel appointment");
    await first.click("Yes, cancel it");
    await first.unmount();

    const second = await mountTracking();
    await second.openAppointments();

    assert.match(second.text(), /Cancelled/);
    assert.equal(second.byText("Cancel appointment"), undefined,
                 "a cancelled appointment still offered cancellation after remount");
    await second.unmount();
});

/* ── refusals ─────────────────────────────────────────────────────────────── */

test("a 422 inside the cutoff shows the reason and keeps the appointment", async () => {
    serveAppointments([appointment()]);
    api.__respond("cancelAppointment", {
        data: null, status: 422,
        error: { message: "Appointments can only be cancelled at least 2 hours before the scheduled time." },
    });
    const ui = await mountTracking();
    await ui.openAppointments();
    await ui.click("Cancel appointment");

    await ui.click("Yes, cancel it");

    assert.match(ui.text(), /at least 2 hours/);
    assert.match(ui.text(), /Pending/, "the appointment was removed or restyled");
    await ui.unmount();
});

test("a 422 refreshes too, because it does not prove the status", async () => {
    // The backend checks the two-hour cutoff BEFORE the status transition, so
    // a 422 says only that this request was refused — not that the appointment
    // is still pending. The lawyer may have cancelled it seconds earlier.
    const served = serveAppointments(
        [appointment({ status: "pending" })],
        [appointment({ status: "cancelled" })],
    );
    api.__respond("cancelAppointment", {
        data: null, status: 422,
        error: { message: "Appointments can only be cancelled at least 2 hours before the scheduled time." },
    });
    const ui = await mountTracking();
    await ui.openAppointments();
    const before = served.calls();
    await ui.click("Cancel appointment");

    await ui.click("Yes, cancel it");

    assert.ok(served.calls() > before, "a 422 did not refresh server state");
    assert.match(ui.text(), /Cancelled/, "the refreshed status is not shown");
    // And the reason survives the refresh that replaced the card.
    assert.match(ui.text(), /at least 2 hours/,
                 "the refusal explanation was lost across the refresh");
    await ui.unmount();
});

test("an ambiguous network outcome is verified rather than guessed", async () => {
    // `apiFetch` RESOLVES with status 0 when the request never completed. That
    // is the browser's view: the server may have committed the cancellation and
    // then lost the connection while replying. The client asks instead of
    // asserting.
    serveAppointments(
        [appointment({ status: "pending" })],
        [appointment({ status: "cancelled" })],
    );
    api.__respond("cancelAppointment", {
        data: null, status: 0,
        error: { message: "Network error. Please check your connection." },
    });
    api.__respond("getAppointment", {
        data: appointment({ status: "cancelled" }), error: null, status: 200,
    });

    const ui = await mountTracking();
    await ui.openAppointments();
    await ui.click("Cancel appointment");
    await ui.click("Yes, cancel it");

    assert.equal(api.__calls("getAppointment").length, 1,
                 "the outcome was not verified against the server");
    assert.match(ui.text(), /Cancelled/);
    assert.doesNotMatch(ui.text(), /was not changed/,
                        "the client was told nothing happened when it had");
    await ui.unmount();
});

test("a pending read after a lost reply is uncertain, not a failure", async () => {
    // An immediate read RACES the original request. The server may be
    // committing the cancellation at the moment this read returns the old row,
    // so "it is still pending, please try again" turns one unknown into a false
    // certainty — and invites a second cancellation of something already
    // cancelling.
    serveAppointments([appointment({ status: "pending" })]);
    api.__respond("cancelAppointment", {
        data: null, status: 0,
        error: { message: "Network error. Please check your connection." },
    });
    api.__respond("getAppointment", {
        data: appointment({ status: "pending" }), error: null, status: 200,
    });

    const ui = await mountTracking();
    await ui.openAppointments();
    await ui.click("Cancel appointment");
    await ui.click("Yes, cancel it");

    assert.match(ui.text(), /could not confirm/i);
    assert.match(ui.text(), /may still be completing/i);
    assert.doesNotMatch(ui.text(), /was NOT cancelled/,
                        "an unresolved outcome was reported as a failure");
    await ui.unmount();
});

test("get shows pending but the list then shows cancelled", async () => {
    // The race, resolved the other way: the read caught the old row and the
    // list refresh a moment later has the committed cancellation. The card must
    // show the server's cancelled status, and the message must not contradict
    // it by claiming the appointment is still pending.
    let call = 0;
    api.__respond("listAppointments", () => {
        call += 1;
        const status = call === 1 ? "pending" : "cancelled";
        return { data: { items: [appointment({ status })] }, error: null, status: 200 };
    });
    api.__respond("cancelAppointment", {
        data: null, status: 0,
        error: { message: "Network error. Please check your connection." },
    });
    api.__respond("getAppointment", {
        data: appointment({ status: "pending" }), error: null, status: 200,
    });

    const ui = await mountTracking();
    await ui.openAppointments();
    await ui.click("Cancel appointment");
    await ui.click("Yes, cancel it");

    assert.match(ui.text(), /Cancelled/, "the refreshed server status is not shown");
    assert.doesNotMatch(ui.text(), /was NOT cancelled/,
                        "the message contradicts the card beside it");
    assert.doesNotMatch(ui.text(), /it is still pending/i);
    await ui.unmount();
});

test("a completed appointment is never described as cancelled", async () => {
    // The branch used to accept ANY terminal status as proof of cancellation,
    // so an appointment the lawyer had marked completed was reported as
    // "Cancelled, but the list could not be refreshed". Cancelled and completed
    // have opposite consequences for whether the client owes a fee.
    let call = 0;
    api.__respond("listAppointments", () => {
        call += 1;
        if (call === 1) {
            return { data: { items: [appointment({ status: "pending" })] }, error: null, status: 200 };
        }
        return { data: null, status: 0, error: { message: "Network error." } };
    });
    api.__respond("cancelAppointment", {
        data: null, status: 0,
        error: { message: "Network error. Please check your connection." },
    });
    api.__respond("getAppointment", {
        data: appointment({ status: "completed" }), error: null, status: 200,
    });

    const ui = await mountTracking();
    await ui.openAppointments();
    await ui.click("Cancel appointment");
    await ui.click("Yes, cancel it");

    const text = ui.text();
    assert.match(text, /was NOT cancelled/);
    assert.match(text, /completed/);
    assert.doesNotMatch(text, /^Cancelled, but/m,
                        "a completed appointment was reported as cancelled");
    assert.doesNotMatch(text, /Cancelled, but the list could not be refreshed/);
    // And the failed refresh is still admitted rather than hidden.
    assert.match(text, /out of date/i);
    await ui.unmount();
});

test("a no-show is named in words, not as a raw status value", async () => {
    serveAppointments([appointment({ status: "pending" })]);
    api.__respond("cancelAppointment", {
        data: null, status: 0,
        error: { message: "Network error. Please check your connection." },
    });
    api.__respond("getAppointment", {
        data: appointment({ status: "no_show" }), error: null, status: 200,
    });

    const ui = await mountTracking();
    await ui.openAppointments();
    await ui.click("Cancel appointment");
    await ui.click("Yes, cancel it");

    assert.match(ui.text(), /was NOT cancelled/);
    assert.match(ui.text(), /a no-show/);
    assert.doesNotMatch(ui.text(), /no_show/, "a raw enum value reached the client");
    await ui.unmount();
});

test("only a read of cancelled counts as a confirmed cancellation", async () => {
    // The positive case, kept adjacent to the ones above so the distinction is
    // visible: this is the single status that closes the confirmation.
    let call = 0;
    api.__respond("listAppointments", () => {
        call += 1;
        if (call === 1) {
            return { data: { items: [appointment({ status: "pending" })] }, error: null, status: 200 };
        }
        return { data: null, status: 0, error: { message: "Network error." } };
    });
    api.__respond("cancelAppointment", {
        data: null, status: 0,
        error: { message: "Network error. Please check your connection." },
    });
    api.__respond("getAppointment", {
        data: appointment({ status: "cancelled" }), error: null, status: 200,
    });

    const ui = await mountTracking();
    await ui.openAppointments();
    await ui.click("Cancel appointment");
    await ui.click("Yes, cancel it");

    assert.match(ui.text(), /Cancelled, but the list could not be refreshed/);
    assert.doesNotMatch(ui.text(), /was NOT cancelled/);
    await ui.unmount();
});

test("a failed verification admits the outcome is unknown", async () => {
    // Both the write and the read failed. Inventing either answer here is how a
    // client ends up at a consultation that was cancelled, or misses one that
    // was not.
    serveAppointments([appointment({ status: "pending" })]);
    api.__respond("cancelAppointment", {
        data: null, status: 0,
        error: { message: "Network error. Please check your connection." },
    });
    api.__respond("getAppointment", {
        data: null, status: 0,
        error: { message: "Network error. Please check your connection." },
    });

    const ui = await mountTracking();
    await ui.openAppointments();
    await ui.click("Cancel appointment");
    await ui.click("Yes, cancel it");

    assert.match(ui.text(), /could not confirm/i);
    assert.match(ui.text(), /Refresh to check/i);
    assert.doesNotMatch(ui.text(), /was not changed/);
    assert.doesNotMatch(ui.text(), /Cancelled/,
                        "an unverified cancellation was reported as done");
    await ui.unmount();
});

test("a successful cancellation whose reload fails is not shown as current", async () => {
    // The cancellation committed; the list read did not. The card on screen
    // still says Pending, and it must be labelled stale rather than trusted.
    let call = 0;
    api.__respond("listAppointments", () => {
        call += 1;
        if (call === 1) {
            return { data: { items: [appointment({ status: "pending" })] }, error: null, status: 200 };
        }
        return { data: null, status: 0, error: { message: "Network error. Please check your connection." } };
    });
    api.__respond("cancelAppointment", { data: { success: true }, error: null, status: 200 });

    const ui = await mountTracking();
    await ui.openAppointments();
    await ui.click("Cancel appointment");
    await ui.click("Yes, cancel it");

    assert.match(ui.text(), /could not be refreshed/i);
    assert.match(ui.text(), /out of date/i);
    await ui.unmount();
});

test("a 409 shows the conflict and refreshes server state", async () => {
    // The appointment moved underneath us — the lawyer cancelled or completed
    // it first — so the card must stop offering an action that no longer
    // applies.
    serveAppointments(
        [appointment({ status: "pending" })],
        [appointment({ status: "completed" })],
    );
    api.__respond("cancelAppointment", {
        data: null, status: 409,
        error: { message: "This appointment is already completed and cannot be changed to cancelled." },
    });
    const ui = await mountTracking();
    await ui.openAppointments();
    await ui.click("Cancel appointment");

    await ui.click("Yes, cancel it");

    assert.match(ui.text(), /already completed/);
    assert.match(ui.text(), /Completed/, "the refreshed status is not shown");
    assert.equal(ui.byText("Cancel appointment"), undefined,
                 "cancellation is still offered on a completed appointment");
    await ui.unmount();
});

test("a thrown client error is also reported as an unknown outcome", async () => {
    // The client RESOLVES on network failure rather than throwing, so this path
    // is only reached if the client itself breaks. The outcome is just as
    // unknown, and the earlier wording — "the appointment was not changed" —
    // asserted the one thing nobody knows.
    serveAppointments([appointment()]);
    api.__respond("cancelAppointment", () => { throw new Error("connection reset"); });
    const ui = await mountTracking();
    await ui.openAppointments();
    await ui.click("Cancel appointment");

    await ui.click("Yes, cancel it");

    assert.match(ui.text(), /could not confirm/i);
    assert.doesNotMatch(ui.text(), /was not changed/);
    assert.match(ui.text(), /Pending/, "the appointment did not survive the failure");
    await ui.unmount();
});

test("the control recovers after a failure", async () => {
    // A refusal must not leave the button stuck in its in-flight state.
    serveAppointments([appointment()]);
    api.__respond("cancelAppointment", {
        data: null, status: 422, error: { message: "Too late to cancel." },
    });
    const ui = await mountTracking();
    await ui.openAppointments();
    await ui.click("Cancel appointment");
    await ui.click("Yes, cancel it");

    const retry = ui.byText("Yes, cancel it");
    assert.ok(retry, "the confirm control vanished after a refusal");
    assert.equal(retry.disabled, false, "the control is stuck disabled");
    await ui.unmount();
});

/* ── double submission ────────────────────────────────────────────────────── */

test("a second click while the request is in flight sends nothing", async () => {
    serveAppointments([appointment()], [appointment({ status: "cancelled" })]);

    let release;
    const pending = new Promise(resolve => { release = resolve; });
    api.__respond("cancelAppointment", () => pending);

    const ui = await mountTracking();
    await ui.openAppointments();
    await ui.click("Cancel appointment");

    const confirm = ui.byText("Yes, cancel it");
    await act(async () => {
        confirm.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true, cancelable: true }));
    });

    // Still in flight: the control says so and refuses further input.
    const inFlight = ui.buttons().find(b => b.textContent.trim() === "Cancelling…");
    assert.ok(inFlight, "the control does not show it is working");
    assert.equal(inFlight.disabled, true);
    assert.equal(inFlight.getAttribute("aria-busy"), "true");

    await act(async () => {
        inFlight.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true, cancelable: true }));
    });

    assert.equal(api.__calls("cancelAppointment").length, 1,
                 "a double click sent two cancellations");

    release({ data: { success: true }, error: null, status: 200 });
    await ui.settle(40);
    await ui.unmount();
});

/* ── mobile and keyboard ──────────────────────────────────────────────────── */

test("the controls are real buttons, reachable by keyboard", async () => {
    // Not divs with onClick. A real <button> is focusable and fires on Enter
    // and Space without any handler of our own.
    serveAppointments([appointment()]);
    const ui = await mountTracking();
    await ui.openAppointments();

    const open = ui.byText("Cancel appointment");
    assert.equal(open.tagName, "BUTTON");
    assert.equal(open.getAttribute("type"), "button",
                 "an untyped button submits any form it is inside");
    assert.ok(open.tabIndex >= 0, "the control cannot be focused");

    await ui.click("Cancel appointment");
    for (const label of ["Yes, cancel it", "Keep appointment"]) {
        const el = ui.byText(label);
        assert.equal(el.tagName, "BUTTON", `${label} is not a button`);
        assert.equal(el.getAttribute("type"), "button");
    }
    await ui.unmount();
});

test("the confirm controls have a touch-sized target and wrap on narrow screens", async () => {
    serveAppointments([appointment()]);
    const ui = await mountTracking();
    await ui.openAppointments();
    await ui.click("Cancel appointment");

    for (const label of ["Yes, cancel it", "Keep appointment"]) {
        const el = ui.byText(label);
        assert.equal(el.style.minHeight, "44px", `${label} is under the touch target`);
    }
    const row = ui.byText("Yes, cancel it").parentElement;
    assert.equal(row.style.flexWrap, "wrap",
                 "the buttons cannot stack on a narrow screen");
    await ui.unmount();
});

test("an error is announced rather than only coloured", async () => {
    serveAppointments([appointment()]);
    api.__respond("cancelAppointment", {
        data: null, status: 422, error: { message: "Too late to cancel." },
    });
    const ui = await mountTracking();
    await ui.openAppointments();
    await ui.click("Cancel appointment");
    await ui.click("Yes, cancel it");

    const alert = ui.container.querySelector('[role="alert"]');
    assert.ok(alert, "the failure is not exposed to assistive technology");
    assert.match(alert.textContent, /Too late/);
    await ui.unmount();
});

/* ── a failed read is not an empty diary ──────────────────────────────────── */
//
// `listAppointments` RESOLVES with `{data: null, error, status}` on failure; it
// usually does not throw. The loader's `data?.items || data || []` therefore
// turned every failed read into an empty array, and the page said "No
// appointments yet" — a lie about the client's own legal engagements, and one
// indistinguishable from the truth.

test("a first read that fails says so instead of claiming no appointments", async () => {
    api.__respond("listAppointments", {
        data: null, status: 0,
        error: { message: "Network error. Please check your connection." },
    });
    const ui = await mountTracking();
    await ui.openAppointments();

    assert.doesNotMatch(ui.text(), /No appointments yet/,
                        "a failed read was reported as an empty diary");
    assert.match(ui.text(), /Could not load your appointments/);
    await ui.unmount();
});

test("a 500 on the list is reported as a failure, not as emptiness", async () => {
    api.__respond("listAppointments", {
        data: null, status: 500, error: { message: "Internal server error" },
    });
    const ui = await mountTracking();
    await ui.openAppointments();

    assert.doesNotMatch(ui.text(), /No appointments yet/);
    assert.match(ui.text(), /Could not load your appointments/);
    await ui.unmount();
});

test("a malformed 200 body is not read as zero appointments", async () => {
    // A success whose body is not a list is a read we cannot use. Treating it
    // as an empty diary is the same lie by a different route.
    api.__respond("listAppointments", {
        data: { unexpected: "shape" }, error: null, status: 200,
    });
    const ui = await mountTracking();
    await ui.openAppointments();

    assert.doesNotMatch(ui.text(), /No appointments yet/);
    assert.match(ui.text(), /could not be read/i);
    await ui.unmount();
});

test("a failed refresh preserves the rows already on screen", async () => {
    // The last thing the server actually said is better than nothing — but it
    // is labelled as possibly out of date rather than presented as current.
    let call = 0;
    api.__respond("listAppointments", () => {
        call += 1;
        if (call === 1) {
            return { data: { items: [appointment({ status: "pending" })] }, error: null, status: 200 };
        }
        return { data: null, status: 0, error: { message: "Network error. Please check your connection." } };
    });
    const ui = await mountTracking();
    await ui.openAppointments();
    assert.match(ui.text(), /Pending/, "precondition: the first read worked");

    // A second read, triggered by the refresh control in the banner path.
    await ui.click("Cancel appointment");
    await ui.click("Keep appointment");
    api.__respond("cancelAppointment", { data: { success: true }, error: null, status: 200 });
    await ui.click("Cancel appointment");
    await ui.click("Yes, cancel it");

    assert.match(ui.text(), /Pending/, "the preserved row was dropped");
    assert.doesNotMatch(ui.text(), /No appointments yet/);
    await ui.unmount();
});

test("an empty list from a SUCCESSFUL read still says there are none", async () => {
    // The honest empty state must survive: suppressing it whenever anything
    // went wrong would hide the real "you have no appointments" case.
    api.__respond("listAppointments", { data: { items: [] }, error: null, status: 200 });
    const ui = await mountTracking();
    await ui.openAppointments();

    assert.match(ui.text(), /No appointments yet/);
    await ui.unmount();
});

test("the failed-read state offers a way to try again", async () => {
    let call = 0;
    api.__respond("listAppointments", () => {
        call += 1;
        if (call === 1) {
            return { data: null, status: 0, error: { message: "Network error." } };
        }
        return { data: { items: [appointment()] }, error: null, status: 200 };
    });
    const ui = await mountTracking();
    await ui.openAppointments();
    assert.match(ui.text(), /Could not load your appointments/);

    await ui.click("Try again");

    assert.match(ui.text(), /Pending/, "the retry did not recover the list");
    assert.doesNotMatch(ui.text(), /Could not load your appointments/);
    await ui.unmount();
});

/* ── rescheduling a pending request ───────────────────────────────────────── */
//
// The client may move their own PENDING request and nothing else. A confirmed
// appointment is an agreement between two people; moving it unilaterally is not
// rescheduling, it is telling the other party where to be. The server refuses
// that too — the control is kept off the card so it cannot be a button that
// always fails.
//
// The card NEVER moves optimistically. The slot may be taken, the cutoff may
// have passed, the lawyer may have confirmed — so the new time appears only
// after the server confirms it on reload.

const NEW_DATE = "2026-12-01";
const NEW_TIME = "15:30";
// 15:30 PKT is 10:30Z — PKT is UTC+5 year-round, with no DST since 2009.
const NEW_ISO = "2026-12-01T10:30:00.000Z";

async function openReschedule(ui) {
    await ui.click("Change time");
    const date = ui.container.querySelector('input[type="date"]');
    const time = ui.container.querySelector("select");
    assert.ok(date && time, "the reschedule form did not open");
    await act(async () => {
        nativeSet(date, NEW_DATE);
        date.dispatchEvent(new dom.window.Event("change", { bubbles: true }));
        nativeSet(time, NEW_TIME, "HTMLSelectElement");
        time.dispatchEvent(new dom.window.Event("change", { bubbles: true }));
    });
    return { date, time };
}

/* React installs its own value setter on inputs, so assigning `.value`
 * directly is swallowed. This reaches the prototype setter the way a real
 * keystroke does. */
function nativeSet(el, value, kind = "HTMLInputElement") {
    const proto = dom.window[kind].prototype;
    Object.getOwnPropertyDescriptor(proto, "value").set.call(el, value);
}

test("only a pending request offers a time change", async () => {
    serveAppointments([appointment({ status: "pending" })]);
    const ui = await mountTracking();
    await ui.openAppointments();

    assert.ok(ui.byText("Change time"));
    await ui.unmount();
});

for (const status of ["confirmed", "cancelled", "completed", "no_show"]) {
    test(`a ${status} appointment offers no time change`, async () => {
        serveAppointments([appointment({ status })]);
        const ui = await mountTracking();
        await ui.openAppointments();

        assert.equal(ui.byText("Change time"), undefined,
                     `a ${status} appointment could be moved`);
        await ui.unmount();
    });
}

test("the form is pre-filled with the appointment's own PKT time", async () => {
    // Not blank, and not the browser's zone: the client edits the time they
    // were shown.
    serveAppointments([appointment({
        status: "pending", scheduled_at: "2026-11-20T09:00:00.000Z",
    })]);
    const ui = await mountTracking();
    await ui.openAppointments();
    await ui.click("Change time");

    const date = ui.container.querySelector('input[type="date"]');
    const time = ui.container.querySelector("select");
    assert.equal(date.value, "2026-11-20");
    assert.equal(time.value, "14:00", "09:00Z is 14:00 in Karachi");
    await ui.unmount();
});

test("a successful change sends PKT converted to UTC, with the version", async () => {
    serveAppointments(
        [appointment({ status: "pending", schedule_version: 3 })],
        [appointment({ status: "pending", schedule_version: 4, scheduled_at: NEW_ISO })],
    );
    api.__respond("rescheduleAppointment", {
        data: appointment({ status: "pending", scheduled_at: NEW_ISO, schedule_version: 4 }),
        error: null, status: 200,
    });
    const ui = await mountTracking();
    await ui.openAppointments();
    await openReschedule(ui);

    await ui.click("Confirm new time");

    const calls = api.__calls("rescheduleAppointment");
    assert.equal(calls.length, 1);
    assert.equal(calls[0].args[0], "apt-1");
    assert.equal(new Date(calls[0].args[1].scheduled_at).toISOString(), NEW_ISO);
    assert.equal(calls[0].args[1].schedule_version, 3,
                 "the version the client was looking at was not sent");
    await ui.unmount();
});

test("the new time shown is the server's, after a reload", async () => {
    // The server is made to answer with a time the client did NOT choose. A
    // component that moved the card itself would show the chosen time.
    const serverTime = "2026-12-05T06:00:00.000Z";   // 11:00 PKT
    serveAppointments(
        [appointment({ status: "pending" })],
        [appointment({ status: "pending", scheduled_at: serverTime })],
    );
    api.__respond("rescheduleAppointment", { data: {}, error: null, status: 200 });
    const ui = await mountTracking();
    await ui.openAppointments();
    await openReschedule(ui);

    await ui.click("Confirm new time");

    assert.match(ui.text(), /11:00/, "the card does not show the server's time");
    assert.doesNotMatch(ui.text(), /03:30/, "a locally chosen time was displayed");
    await ui.unmount();
});

test("the server's new time survives a remount", async () => {
    const serverTime = "2026-12-05T06:00:00.000Z";
    serveAppointments(
        [appointment({ status: "pending" })],
        [appointment({ status: "pending", scheduled_at: serverTime })],
    );
    api.__respond("rescheduleAppointment", { data: {}, error: null, status: 200 });

    const first = await mountTracking();
    await first.openAppointments();
    await openReschedule(first);
    await first.click("Confirm new time");
    await first.unmount();

    const second = await mountTracking();
    await second.openAppointments();

    assert.match(second.text(), /11:00/);
    await second.unmount();
});

test("a slot conflict is explained and the card is refreshed", async () => {
    serveAppointments(
        [appointment({ status: "pending" })],
        [appointment({ status: "confirmed" })],
    );
    api.__respond("rescheduleAppointment", {
        data: null, status: 409,
        error: { message: "That time has just been taken. Please choose another." },
    });
    const ui = await mountTracking();
    await ui.openAppointments();
    await openReschedule(ui);

    await ui.click("Confirm new time");

    assert.match(ui.text(), /just been taken/);
    assert.match(ui.text(), /Confirmed/, "the refreshed status is not shown");
    await ui.unmount();
});

test("the cutoff refusal is shown and the list refreshed", async () => {
    // A 422 does not prove the status either — the cutoff is checked before
    // anything else — so this refreshes as well.
    const served = serveAppointments([appointment({ status: "pending" })]);
    api.__respond("rescheduleAppointment", {
        data: null, status: 422,
        error: { message: "Appointments can only be rescheduled at least 2 hours before the scheduled time." },
    });
    const ui = await mountTracking();
    await ui.openAppointments();
    const before = served.calls();
    await openReschedule(ui);

    await ui.click("Confirm new time");

    assert.match(ui.text(), /at least 2 hours/);
    assert.ok(served.calls() > before, "a 422 did not refresh server state");
    await ui.unmount();
});

test("a stale version is reported without moving the card", async () => {
    serveAppointments(
        [appointment({ status: "pending", schedule_version: 0 })],
        [appointment({ status: "pending", schedule_version: 2, scheduled_at: NEW_ISO })],
    );
    api.__respond("rescheduleAppointment", {
        data: null, status: 409,
        error: { message: "This appointment was changed a moment ago. Reload it and try again so you are working from the current time." },
    });
    const ui = await mountTracking();
    await ui.openAppointments();
    await openReschedule(ui);

    await ui.click("Confirm new time");

    assert.match(ui.text(), /changed a moment ago/);
    await ui.unmount();
});

test("a lost reply is verified rather than assumed", async () => {
    // Status 0 is the BROWSER's view. The server may have moved the appointment
    // and lost the connection while replying.
    serveAppointments(
        [appointment({ status: "pending" })],
        [appointment({ status: "pending", scheduled_at: NEW_ISO })],
    );
    api.__respond("rescheduleAppointment", {
        data: null, status: 0,
        error: { message: "Network error. Please check your connection." },
    });
    api.__respond("getAppointment", {
        data: appointment({ status: "pending", scheduled_at: NEW_ISO }),
        error: null, status: 200,
    });
    const ui = await mountTracking();
    await ui.openAppointments();
    await openReschedule(ui);

    await ui.click("Confirm new time");

    assert.equal(api.__calls("getAppointment").length, 1,
                 "the outcome was not verified");
    assert.doesNotMatch(ui.text(), /could not confirm/i,
                        "a verified move was still reported as uncertain");
    await ui.unmount();
});

test("a lost reply whose read shows the old time stays uncertain", async () => {
    // The read RACES the original request, so the old time is not proof the
    // move failed.
    serveAppointments([appointment({ status: "pending" })]);
    api.__respond("rescheduleAppointment", {
        data: null, status: 0,
        error: { message: "Network error. Please check your connection." },
    });
    api.__respond("getAppointment", {
        data: appointment({ status: "pending" }), error: null, status: 200,
    });
    const ui = await mountTracking();
    await ui.openAppointments();
    await openReschedule(ui);

    await ui.click("Confirm new time");

    assert.match(ui.text(), /could not confirm/i);
    assert.match(ui.text(), /may still be completing/i);
    assert.doesNotMatch(ui.text(), /Moved,/, "an unverified move was reported as done");
    await ui.unmount();
});

test("a failed verification admits the outcome is unknown", async () => {
    serveAppointments([appointment({ status: "pending" })]);
    api.__respond("rescheduleAppointment", {
        data: null, status: 0, error: { message: "Network error." },
    });
    api.__respond("getAppointment", {
        data: null, status: 0, error: { message: "Network error." },
    });
    const ui = await mountTracking();
    await ui.openAppointments();
    await openReschedule(ui);

    await ui.click("Confirm new time");

    assert.match(ui.text(), /could not confirm whether the time changed/i);
    assert.match(ui.text(), /Refresh to check/i);
    await ui.unmount();
});

test("a second click while the change is in flight sends nothing", async () => {
    serveAppointments([appointment({ status: "pending" })]);
    let release;
    const pending = new Promise(resolve => { release = resolve; });
    api.__respond("rescheduleAppointment", () => pending);

    const ui = await mountTracking();
    await ui.openAppointments();
    await openReschedule(ui);

    const confirm = ui.byText("Confirm new time");
    await act(async () => {
        confirm.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true, cancelable: true }));
    });

    const inFlight = ui.buttons().find(b => b.textContent.trim() === "Changing…");
    assert.ok(inFlight, "the control does not show it is working");
    assert.equal(inFlight.disabled, true);
    assert.equal(inFlight.getAttribute("aria-busy"), "true");

    await act(async () => {
        inFlight.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true, cancelable: true }));
    });
    assert.equal(api.__calls("rescheduleAppointment").length, 1,
                 "a double click sent two reschedules");

    release({ data: {}, error: null, status: 200 });
    await ui.settle(40);
    await ui.unmount();
});

test("an incomplete selection is refused before any request", async () => {
    serveAppointments([appointment({ status: "pending" })]);
    const ui = await mountTracking();
    await ui.openAppointments();
    await ui.click("Change time");

    // Clear the pre-filled time and submit.
    const time = ui.container.querySelector("select");
    await act(async () => {
        nativeSet(time, "", "HTMLSelectElement");
        time.dispatchEvent(new dom.window.Event("change", { bubbles: true }));
    });
    await ui.click("Confirm new time");

    assert.equal(api.__calls("rescheduleAppointment").length, 0);
    assert.match(ui.text(), /Choose both a date and a time/);
    await ui.unmount();
});

test("keeping the current time sends nothing", async () => {
    serveAppointments([appointment({ status: "pending" })]);
    const ui = await mountTracking();
    await ui.openAppointments();
    await openReschedule(ui);

    await ui.click("Keep current time");

    assert.equal(api.__calls("rescheduleAppointment").length, 0);
    assert.ok(ui.byText("Change time"), "the control should be offered again");
    await ui.unmount();
});

test("the time picker offers only half-hour slots", async () => {
    // Alignment is what lets the unique slot index detect an overlap at all, so
    // an off-grid time is refused by the server with a 422.
    serveAppointments([appointment({ status: "pending" })]);
    const ui = await mountTracking();
    await ui.openAppointments();
    await ui.click("Change time");

    const options = [...ui.container.querySelectorAll("option")]
        .map(o => o.value).filter(Boolean);
    assert.ok(options.length > 0);
    for (const value of options) {
        assert.match(value, /^\d{2}:(00|30)$/, `${value} is not on the half hour`);
    }
    await ui.unmount();
});

test("the reschedule controls are keyboard-reachable with touch targets", async () => {
    serveAppointments([appointment({ status: "pending" })]);
    const ui = await mountTracking();
    await ui.openAppointments();

    const open = ui.byText("Change time");
    assert.equal(open.tagName, "BUTTON");
    assert.equal(open.getAttribute("type"), "button");
    assert.equal(open.style.minHeight, "44px");

    await ui.click("Change time");
    for (const label of ["Confirm new time", "Keep current time"]) {
        const el = ui.byText(label);
        assert.equal(el.tagName, "BUTTON", `${label} is not a button`);
        assert.equal(el.getAttribute("type"), "button");
        assert.equal(el.style.minHeight, "44px");
    }
    await ui.unmount();
});
