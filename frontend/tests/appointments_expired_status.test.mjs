/* The EXPIRED appointment status, on both sides of the same appointment.
 *
 * A request that nobody answered stops holding its slot and ends as `expired`.
 * It is a status neither page had ever seen, and both pages had a fallback that
 * turned an unrecognised status into an ACTIVE one:
 *
 *   * the lawyer's page mapped anything unknown to "Pending", so a lapsed
 *     request sat in the Pending tab wearing Accept and Decline — controls the
 *     server answers with a 409, on a request nobody can act on any more;
 *
 *   * the client's page fell back to `statusStyle.pending`, badging the same
 *     appointment "⏳ Pending Confirmation" — telling the client their request
 *     was still live when it had already ended.
 *
 * Both are tested here, because the two halves of one appointment disagreeing
 * is the specific failure this module keeps producing: `no_show` was reported
 * to the lawyer as "Cancelled" for the same reason, one fallback earlier.
 *
 * The backend sweep that writes this status is DORMANT. These pages are
 * nonetheless the right place for it to be correct first: a status the UI
 * mishandles is a reason not to enable the sweep, and rendering is the half
 * that can be finished safely while the writing half waits for approval.
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
const { pktToday } = await import("../src/lib/bookingTime.js");

const { createElement: h } = React;

/* An instant on TODAY'S PAKISTAN CALENDAR DAY, at a fixed PKT wall-clock time.
 *
 * These fixtures used to be `new Date()` plus two or three hours, which is a
 * different thing entirely: after 22:00 local, "now + 2h" is TOMORROW, so the
 * appointment stopped being today and the assertion that it counts as Today
 * failed. The file broke for two hours every night, on every diff, for a
 * reason that had nothing to do with what it tests.
 *
 * The tests are about STATUS inclusion and exclusion - does an expired request
 * count towards the day, does a confirmed one - and not about an appointment
 * being a couple of hours away. So the fixture is anchored to the day the page
 * itself means by "today": `pktToday()` is the app's own helper, so a machine
 * in any timezone builds the same PKT day the component compares against.
 *
 * `isPktToday` is a day comparison and does not exclude times already past, so
 * a fixed morning hour is stable at every hour of the run, 22:00-00:00
 * included.
 */
function pktInstant(hhmm) {
    return new Date(`${pktToday()}T${hhmm}:00+05:00`).toISOString();
}

/* An appointment as the API returns one. `status` is the BACKEND value; what
 * each page makes of it is the thing under test. */
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
        client_name: "Ayesha Bibi",
        purpose: "Consultation",
        notes: null,
        case_id: null,
        timezone: "Asia/Karachi",
        schedule_version: 0,
        ...over,
    };
}

/* ── the lawyer's page ────────────────────────────────────────────────────── */

async function mountLawyer(items) {
    api.__respond("listAppointments", { data: { items } });
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
    await act(async () => { await new Promise(r => realSetTimeout(r, 30)); });

    return {
        container,
        text: () => container.textContent,
        buttons: () => [...container.querySelectorAll("button")]
            .map(b => b.textContent.trim()),
        // Status badges only, identified structurally: the tab strip and the
        // stat cards render the same words, and a whole-page text scan would
        // report a badge that is not there. A StatusBadge is the only one of
        // the three that wraps a nested dot <span>.
        badges: () => [...container.querySelectorAll("span")]
            .filter(el => el.querySelector("span"))
            .map(el => el.textContent.trim())
            .filter(txt => ["Upcoming", "Pending", "Completed", "Cancelled",
                            "No Show", "Expired", "Unknown"].includes(txt)),
        /** A StatCard's number, by its label.
         *
         * The counters are the only place `DID_NOT_HAPPEN` is observable from
         * outside — a badge assertion cannot see it, which is how an earlier
         * version of the "not counted" test below passed against code that
         * counted it.
         */
        stat: (label) => {
            // A StatCard renders its label then its value, so its whole text
            // is "Today3" — or "Today (loaded)3" while the list is still
            // paging, since the card says so rather than passing a partial
            // count off as the day's complete agenda.
            const pattern = new RegExp("^" + label + "[^0-9]*([0-9]+)$");
            const hit = [...container.querySelectorAll("div")]
                .map(el => el.textContent.trim().match(pattern))
                .find(Boolean);
            assert.ok(hit, `no stat card labelled ${label}`);
            return Number(hit[1]);
        },
        unmount: async () => { await act(async () => root.unmount()); },
    };
}

test.beforeEach(() => {
    api.__reset();
    api.__respond("bootstrapAuth", true);
    api.__respond("getMe", { data: { _id: "l1", role: "lawyer" } });
    api.__respond("listCases", { data: { items: [] } });
    api.__respond("getNotifications", { data: { items: [] } });
});

test.after(() => {
    for (const id of liveTimers) { realClearInterval(id); realClearTimeout(id); }
    liveTimers.clear();
    dom.window.close();
});

test("the lawyer sees an expired request as Expired, not Pending", async () => {
    const ui = await mountLawyer([appointment({ status: "expired" })]);

    assert.deepEqual(ui.badges(), ["Expired"],
                     "an expired request was not badged Expired");
    await ui.unmount();
});

test("an expired request offers the lawyer no pending-only actions", async () => {
    // THE DEFECT WITH TEETH. Accept and Decline on a row the server will
    // refuse: the lawyer acts, gets a 409, and learns nothing about why.
    const ui = await mountLawyer([appointment({ status: "expired" })]);

    const labels = ui.buttons();
    for (const dead of ["Accept", "Decline", "Complete", "No Show",
                        "Mark No-Show", "Cancel"]) {
        assert.ok(!labels.includes(dead),
                  `an expired request still offers "${dead}"`);
    }
    await ui.unmount();
});

test("a pending request still offers the lawyer its actions", async () => {
    // The control. Suppressing the buttons everywhere would pass the test
    // above and break the page.
    const ui = await mountLawyer([appointment({ status: "pending" })]);

    const labels = ui.buttons().join("|");
    assert.match(labels, /Accept/,
                 "the pending actions were suppressed for everyone");
    await ui.unmount();
});

test("an expired request is filterable rather than only under All", async () => {
    // The tab filter is an exact match on the display status, so a status with
    // no tab is reachable under "All" and nowhere else — it disappears from
    // every filtered view the moment it is set.
    const ui = await mountLawyer([appointment({ status: "expired" })]);

    const tabs = ui.buttons();
    assert.ok(tabs.some(label => label.startsWith("Expired")),
              `no Expired filter tab: ${JSON.stringify(tabs)}`);
    await ui.unmount();
});

test("an expired request is not counted as a session on the day", async () => {
    // It did not happen and will not happen. Counting it would tell a lawyer
    // their day is busier than it is.
    //
    // Asserted on the TODAY COUNTER, which is the only place the exclusion is
    // observable. An earlier version of this test checked that no "Upcoming"
    // badge appeared, which is true whether or not the row is counted — it
    // passed against code that counted it.
    const ui = await mountLawyer([
        appointment({ id: "live", status: "confirmed",
                      scheduled_at: pktInstant("10:00") }),
        appointment({ id: "gone", status: "expired",
                      scheduled_at: pktInstant("11:00") }),
    ]);

    assert.equal(ui.stat("Today"), 1,
                 "an expired request was counted as a session on the day");
    await ui.unmount();
});

test("a confirmed appointment is still counted on the day", async () => {
    // The control: excluding everything would satisfy the test above.
    const ui = await mountLawyer([appointment({
        status: "confirmed", scheduled_at: pktInstant("10:00"),
    })]);

    assert.equal(ui.stat("Today"), 1);
    await ui.unmount();
});

test("an unknown status is not painted as a live booking", async () => {
    // The fallback itself, which is what produced this whole class of bug
    // twice. A status this build has never heard of must not read as a
    // confirmed appointment.
    const ui = await mountLawyer([appointment({ status: "something_new" })]);

    assert.ok(!ui.badges().includes("Upcoming"),
              "an unknown status rendered as a live upcoming booking");
    assert.ok(!ui.badges().includes("Pending"),
              "an unknown status rendered as awaiting the lawyer");
    await ui.unmount();
});

/* ── the client's page ────────────────────────────────────────────────────── */

async function mountClient(items) {
    api.__respond("listAppointments", { data: { items }, error: null, status: 200 });
    const Module7 = (await import("../src/components/client/ModTracking.jsx")).default;
    const { CaseCtx } = await import("../src/components/shared/CaseContext.jsx");

    const container = dom.window.document.createElement("div");
    dom.window.document.body.appendChild(container);
    const root = createRoot(container);
    const ctx = {
        notifications: [],
        markNotificationDone: () => {},
        markAllNotificationsDone: () => {},
        appointmentMilestones: [],
    };
    await act(async () => {
        root.render(h(CaseCtx.Provider, { value: ctx },
                      h(Module7, { isDark: true })));
    });
    await act(async () => { await new Promise(r => realSetTimeout(r, 30)); });

    const buttons = () => [...container.querySelectorAll("button")];
    const byText = (label) => buttons().find(b => b.textContent.trim() === label);

    return {
        container,
        text: () => container.textContent,
        byText,
        openAppointments: async () => {
            const nav = [...container.querySelectorAll("div")]
                .find(el => el.textContent.trim() === "Appointments");
            assert.ok(nav, "no Appointments nav control");
            await act(async () => {
                nav.dispatchEvent(new dom.window.MouseEvent(
                    "click", { bubbles: true, cancelable: true }));
            });
            await act(async () => { await new Promise(r => realSetTimeout(r, 20)); });
        },
        unmount: async () => { await act(async () => root.unmount()); },
    };
}

test("the client sees an expired request as Expired, not Pending Confirmation",
     async () => {
    api.__respond("getMe", { data: { _id: "c1", role: "client" } });
    const ui = await mountClient([appointment({ status: "expired" })]);
    await ui.openAppointments();

    assert.match(ui.text(), /Expired/);
    assert.ok(!ui.text().includes("Pending Confirmation"),
              "an expired request was shown to the client as still pending");
    await ui.unmount();
});

test("the client is told why an expired request ended", async () => {
    // A badge reading "Expired" alone invites the wrong inference — that the
    // client missed something, or that the lawyer refused.
    api.__respond("getMe", { data: { _id: "c1", role: "client" } });
    const ui = await mountClient([appointment({ status: "expired" })]);
    await ui.openAppointments();

    assert.match(ui.text(), /expired before it was confirmed/i);
    await ui.unmount();
});

test("an expired request is not described to the client as cancelled",
     async () => {
    // Nobody called it off. A client told their request was cancelled would
    // reasonably ask who by — and `cancelled_by` names no one, because there
    // is no one to name.
    api.__respond("getMe", { data: { _id: "c1", role: "client" } });
    const ui = await mountClient([appointment({
        status: "expired", cancelled_by: null, cancel_reason: null,
    })]);
    await ui.openAppointments();

    assert.ok(!/cancelled this appointment/i.test(ui.text()),
              "an expired request was attributed to a canceller");
    await ui.unmount();
});

test("an expired request offers the client no cancel or reschedule", async () => {
    // Both are pending-only server-side; offering them here is a button that
    // always fails.
    api.__respond("getMe", { data: { _id: "c1", role: "client" } });
    const ui = await mountClient([appointment({ status: "expired" })]);
    await ui.openAppointments();

    assert.equal(ui.byText("Cancel appointment"), undefined,
                 "cancel offered on an expired request");
    assert.equal(ui.byText("Reschedule"), undefined,
                 "reschedule offered on an expired request");
    await ui.unmount();
});

test("an unknown status is not shown to the client as still pending", async () => {
    // THE FALLBACK ITSELF. `expired` now has its own entry, so it no longer
    // reaches the default — only a status this build has never heard of does,
    // and that is the case that has to be exercised to test the default at
    // all. The old default was `statusStyle.pending`, which badged anything
    // unrecognised "⏳ Pending Confirmation".
    api.__respond("getMe", { data: { _id: "c1", role: "client" } });
    const ui = await mountClient([appointment({ status: "something_new" })]);
    await ui.openAppointments();

    assert.ok(!ui.text().includes("Pending Confirmation"),
              "an unrecognised status was shown to the client as pending");
    await ui.unmount();
});

test("a pending request still offers the client its actions", async () => {
    // The control, again: the suppression must be about the status.
    api.__respond("getMe", { data: { _id: "c1", role: "client" } });
    const ui = await mountClient([appointment({ status: "pending" })]);
    await ui.openAppointments();

    assert.ok(ui.byText("Cancel appointment"),
              "the client actions were suppressed for everyone");
    await ui.unmount();
});

test("an expired video request does not promise a joining link", async () => {
    // "Your lawyer will add it" is a statement about the future, and for this
    // request there is no future: nobody is going to add a link to a request
    // that has ended.
    api.__respond("getMe", { data: { _id: "c1", role: "client" } });
    const ui = await mountClient([appointment({
        status: "expired", mode: "video", meeting_link: null,
    })]);
    await ui.openAppointments();

    assert.ok(!ui.text().includes("Joining link not shared yet"),
              "an expired request still promised a joining link");
    await ui.unmount();
});
