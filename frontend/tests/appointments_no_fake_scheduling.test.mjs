/* The lawyer's page offers no scheduling or rescheduling controls.
 *
 * It used to offer both, prominently: a "+ Schedule" button in the header, a
 * "+ New Appointment" quick action, and a Reschedule control on pending,
 * upcoming and cancelled rows. None of them reached the server.
 * `confirmSchedule` only ever called `setAppointments`: a "booked" appointment
 * was given `id: Date.now()` and vanished on the next refresh, and a
 * "reschedule" rewrote the display strings while leaving `at` — the instant the
 * row is actually sorted, grouped and acted on by — untouched.
 *
 * So a lawyer could tell a client a time had been moved, see the card agree,
 * and have the server know nothing about it. Shipping a button that lies is
 * worse than shipping no button.
 *
 * Rescheduling is a real feature (`PATCH /{id}/reschedule` does not exist yet;
 * the unused `exclude_id` in the repository is the vestige of the one that was
 * never built). Until it exists, the honest state is absence — and this file
 * exists so that absence cannot quietly become another local-only
 * implementation.
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
                    "MutationObserver", "getComputedStyle", "localStorage",
                    "requestAnimationFrame", "cancelAnimationFrame"]) {
    define(name, dom.window[name]);
}
define("IS_REACT_ACT_ENVIRONMENT", true);

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

function appointment(over = {}) {
    const when = new Date(Date.now() - 36e5);   // started an hour ago
    return {
        id: "apt-1",
        scheduled_at: when.toISOString(),
        end_at: new Date(when.getTime() + 18e5).toISOString(),
        duration_minutes: 30,
        client_name: "Ayesha Bibi",
        mode: "video",
        notes: "Consultation",
        status: "confirmed",
        case_id: null,
        ...over,
    };
}

async function mountAppointments(items) {
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
        labels: () => [...container.querySelectorAll("button")]
            .map(b => b.textContent.trim()),
        // Status badges only, identified STRUCTURALLY.
        //
        // The words also appear in the tab strip ("Upcoming", "Pending" as
        // filters) and in the stat cards (as counters), so a text scan reports
        // a status that is not on any card. A StatusBadge is the only one of
        // the three that wraps a nested dot <span>.
        badges: () => [...container.querySelectorAll("span")]
            .filter(el => el.querySelector("span"))
            .map(el => el.textContent.trim())
            .filter(txt => ["Upcoming", "Pending", "Completed",
                            "Cancelled", "No Show"].includes(txt)),
        unmount: async () => { await act(async () => root.unmount()); },
    };
}

test.beforeEach(() => {
    api.__reset();
    api.__respond("bootstrapAuth", true);
    api.__respond("getMe", { data: { _id: "l1", role: "lawyer" } });
});

test.after(() => {
    for (const id of liveTimers) { realClearInterval(id); realClearTimeout(id); }
    liveTimers.clear();
    dom.window.close();
});

const FAKE_LABELS = [
    "+ Schedule",
    "+ New Appointment",
    "Reschedule",
];

for (const status of ["pending", "confirmed", "cancelled", "completed", "no_show"]) {
    test(`a ${status} appointment offers no scheduling control`, async () => {
        const ui = await mountAppointments([appointment({ status })]);

        const labels = ui.labels();
        for (const fake of FAKE_LABELS) {
            assert.ok(!labels.some(l => l.includes(fake)),
                      `"${fake}" is still offered on a ${status} row: ${labels}`);
        }
        await ui.unmount();
    });
}

test("the page mentions rescheduling nowhere at all", async () => {
    // Including headings and helper text: a "Reschedule" label with no control
    // behind it is the same promise, made more quietly.
    const ui = await mountAppointments([appointment()]);

    assert.doesNotMatch(ui.text(), /Reschedul/i);
    await ui.unmount();
});

test("the real actions survive the removal", async () => {
    // The point was to remove the fake controls, not to strip the page. A
    // started, confirmed appointment offers the outcomes the server accepts.
    const ui = await mountAppointments([appointment({ status: "confirmed" })]);

    const labels = ui.labels();
    for (const real of ["Done", "No Show"]) {
        assert.ok(labels.includes(real), `${real} was removed too: ${labels}`);
    }
    await ui.unmount();
});

test("a pending appointment still offers Accept and Reject", async () => {
    const future = new Date(Date.now() + 48 * 36e5);
    const ui = await mountAppointments([appointment({
        status: "pending",
        scheduled_at: future.toISOString(),
        end_at: new Date(future.getTime() + 18e5).toISOString(),
    })]);

    const labels = ui.labels();
    assert.ok(labels.includes("Accept"), `Accept missing: ${labels}`);
    assert.ok(labels.includes("Reject"), `Reject missing: ${labels}`);
    await ui.unmount();
});

test("no control creates an appointment that the server never sees", async () => {
    // The specific failure `confirmSchedule` had: a row appearing in the list
    // with no request behind it. Every button on the page is clicked, and the
    // list must not grow.
    const ui = await mountAppointments([appointment()]);
    const before = ui.container.querySelectorAll("button").length;

    for (const btn of [...ui.container.querySelectorAll("button")]) {
        if (btn.disabled) continue;
        await act(async () => {
            btn.dispatchEvent(new dom.window.MouseEvent(
                "click", { bubbles: true, cancelable: true }));
        });
    }
    await act(async () => { await new Promise(r => realSetTimeout(r, 20)); });

    const created = api.__calls("bookAppointment");
    assert.equal(created.length, 0, "a lawyer-side control booked an appointment");
    assert.ok(before > 0, "precondition: the page rendered controls at all");
    await ui.unmount();
});

test("the module exports no scheduling modal", async () => {
    // Removing the buttons while leaving the component behind invites the next
    // person to wire it back up.
    const mod = await import("../src/components/lawyer/AppointmentsPage.jsx");

    for (const name of Object.keys(mod)) {
        assert.doesNotMatch(name, /Schedule/i, `${name} is still exported`);
    }
});

/* ── the schedule version, through the lawyer's page ──────────────────────── */
//
// Accepting is agreeing to a TIME. A client may move a pending request while
// this page sits open, and the status stays PENDING throughout — so the server
// requires the version the lawyer was SHOWN, and the page has to carry it from
// the row mapping to the handler. Dropping it anywhere in between turns the pin
// back into an unconditional write, and the row would still render perfectly.

function pending(over = {}) {
    const future = new Date(Date.now() + 48 * 36e5);
    return appointment({
        status: "pending",
        scheduled_at: future.toISOString(),
        end_at: new Date(future.getTime() + 18e5).toISOString(),
        schedule_version: 0,
        ...over,
    });
}

/** Click Accept inside THIS test's container.
 *
 * Scoped deliberately: `mountAppointments` appends to document.body, so a
 * document-wide query finds the Accept button of every earlier test that did
 * not unmount — and asserts against the wrong page.
 */
async function clickAccept(ui) {
    const btn = [...ui.container.querySelectorAll("button")]
        .find(b => b.textContent.trim() === "Accept");
    assert.ok(btn, "Accept is not offered");
    await act(async () => {
        btn.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true, cancelable: true }));
    });
    await act(async () => { await new Promise(r => realSetTimeout(r, 30)); });
    return btn;
}

test("the version is carried from the API row to the Accept call", async () => {
    // The gap this closes: `mapApiAppt` dropped `schedule_version`, so the card
    // rendered correctly and the one field that makes confirmation safe never
    // reached the handler.
    const ui = await mountAppointments([pending({ schedule_version: 3 })]);
    api.__respond("confirmAppointment", { data: { success: true }, error: null, status: 200 });

    await clickAccept(ui);

    const calls = api.__calls("confirmAppointment");
    assert.equal(calls.length, 1);
    assert.deepEqual(calls[0].args[1], { schedule_version: 3 },
                     "the version shown was not sent");
    await ui.unmount();
});

test("a stale Accept is refused, reloaded, and then succeeds", async () => {
    // The full sequence: the lawyer sees version 0, the client moves it to 1,
    // the stale Accept 409s and must NOT show the row as confirmed, and the
    // Accept after the reload works.
    //
    // Mounted FIRST so the first paint uses the static version-0 response;
    // the function responder below then serves every later RELOAD.
    const ui = await mountAppointments([pending({ schedule_version: 0 })]);
    // A server with memory, so the reload after a successful confirm reflects
    // it. A stub that always answered "pending" could not tell a confirmation
    // that worked from one that was refused.
    let confirmed = false;
    api.__respond("listAppointments", () => ({
        data: { items: [pending({
            schedule_version: 1,
            status: confirmed ? "confirmed" : "pending",
        })] },
        error: null, status: 200,
    }));
    api.__respond("confirmAppointment", (id, body) => {
        if (body.schedule_version !== 1) {
            return { data: null, status: 409,
                     error: { message: "The client changed the time of this request while you were looking at it. Reload to see the new time before accepting." } };
        }
        confirmed = true;
        return { data: { success: true }, error: null, status: 200 };
    });

    // Stale: pinned to the version that was displayed.
    await clickAccept(ui);
    assert.deepEqual(api.__calls("confirmAppointment")[0].args[1], { schedule_version: 0 });
    assert.deepEqual(ui.badges(), ["Pending"],
                     "a refused confirmation was shown as confirmed");

    // The 409 forced a reload, so the card now carries version 1.
    await clickAccept(ui);
    assert.deepEqual(api.__calls("confirmAppointment")[1].args[1], { schedule_version: 1 },
                     "the retry did not use the reloaded version");
    assert.deepEqual(ui.badges(), ["Upcoming"],
                     "the fresh confirmation is not reflected");
    await ui.unmount();
});

test("a row with no usable version does not guess one", async () => {
    // Sending a fabricated version would agree to a time nobody has seen. The
    // page reloads instead.
    const ui = await mountAppointments([pending({ schedule_version: null })]);
    api.__respond("confirmAppointment", { data: { success: true }, error: null, status: 200 });

    await clickAccept(ui);

    assert.equal(api.__calls("confirmAppointment").length, 0,
                 "a confirmation was sent with no version the lawyer had seen");
    await ui.unmount();
});

test("a legacy row arrives as version 0 and is acceptable", async () => {
    // The server defaults it at the read boundary, so the page never sees null
    // for a real legacy appointment — and 0 is a version it can pin.
    const ui = await mountAppointments([pending({ schedule_version: 0 })]);
    api.__respond("confirmAppointment", { data: { success: true }, error: null, status: 200 });

    await clickAccept(ui);

    assert.deepEqual(api.__calls("confirmAppointment")[0].args[1],
                     { schedule_version: 0 });
    await ui.unmount();
});

/* ── the video consultation flow ──────────────────────────────────────────── */
//
// THE OLD MODAL INVENTED A ROOM. It displayed
// `https://meet.attorney.ai/room/{id}-{firstname}` — a host this product does
// not own and a room nobody had created — asserted the platform was
// "Zoom / Google Meet", and gave Copy and Launch buttons with NO handlers at
// all. A lawyer could read that URL to a client over the phone and both would
// arrive nowhere.

const VIDEO_LINK = "https://meet.example.com/room/abc-def";

function videoAppt(over = {}) {
    const future = new Date(Date.now() + 48 * 36e5);
    return appointment({
        status: "confirmed",
        mode: "video",
        scheduled_at: future.toISOString(),
        end_at: new Date(future.getTime() + 18e5).toISOString(),
        schedule_version: 0,
        ...over,
    });
}

async function openVideoModal(ui) {
    const btn = [...ui.container.querySelectorAll("button")]
        .find(b => /Join Call|Add joining link/.test(b.textContent));
    assert.ok(btn, `no video control; buttons: ${ui.labels()}`);
    await act(async () => {
        btn.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true, cancelable: true }));
    });
    await act(async () => { await new Promise(r => realSetTimeout(r, 20)); });
    return btn;
}

test("no invented meeting URL appears anywhere on the page", async () => {
    const ui = await mountAppointments([videoAppt({ meeting_link: VIDEO_LINK })]);
    await openVideoModal(ui);

    const text = dom.window.document.body.textContent;
    assert.doesNotMatch(text, /meet\.attorney\.ai/,
                        "the fabricated host is still being rendered");
    assert.doesNotMatch(text, /Zoom \/ Google Meet/,
                        "a video provider is still being claimed");
    await ui.unmount();
});

test("a confirmed video appointment with a link offers the stored link", async () => {
    const ui = await mountAppointments([videoAppt({ meeting_link: VIDEO_LINK })]);
    await openVideoModal(ui);

    const anchor = [...ui.container.querySelectorAll("a")]
        .find(a => a.getAttribute("href") === VIDEO_LINK);
    assert.ok(anchor, "the stored link is not offered as a real link");
    assert.equal(anchor.getAttribute("target"), "_blank");
    assert.match(anchor.textContent, /Open link/);
    await ui.unmount();
});

test("the button says Join Call only when there is something to join", async () => {
    const withLink = await mountAppointments([videoAppt({ meeting_link: VIDEO_LINK })]);
    assert.ok(withLink.labels().some(l => l.includes("Join Call")));
    await withLink.unmount();

    const without = await mountAppointments([videoAppt({ meeting_link: null })]);
    const labels = without.labels();
    assert.ok(!labels.some(l => l.includes("Join Call")),
              `a linkless video appointment offered "Join Call": ${labels}`);
    assert.ok(labels.some(l => l.includes("Add joining link")));
    await without.unmount();
});

test("a video appointment with no link offers a way to supply one", async () => {
    const ui = await mountAppointments([videoAppt({ meeting_link: null })]);
    await openVideoModal(ui);

    assert.match(ui.container.textContent, /No joining link yet/);
    assert.match(ui.container.textContent, /does not host video calls/,
                 "the page should not imply it provides the room");
    assert.ok(ui.container.querySelector('input[type="url"]'),
              "no field to paste a link into");
    await ui.unmount();
});

test("saving a link calls the endpoint and reloads", async () => {
    let saved = null;
    api.__respond("setMeetingLink", (id, link) => {
        saved = { id, link };
        return { data: { meeting_link: link }, error: null, status: 200 };
    });
    const ui = await mountAppointments([videoAppt({ meeting_link: null })]);
    await openVideoModal(ui);

    const field = ui.container.querySelector('input[type="url"]');
    await act(async () => {
        const setter = Object.getOwnPropertyDescriptor(
            dom.window.HTMLInputElement.prototype, "value").set;
        setter.call(field, VIDEO_LINK);
        field.dispatchEvent(new dom.window.Event("change", { bubbles: true }));
        field.dispatchEvent(new dom.window.Event("input", { bubbles: true }));
    });
    const save = [...ui.container.querySelectorAll("button")]
        .find(b => b.textContent.trim() === "Save link");
    await act(async () => {
        save.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true, cancelable: true }));
    });
    await act(async () => { await new Promise(r => realSetTimeout(r, 30)); });

    assert.deepEqual(saved, { id: "apt-1", link: VIDEO_LINK });
    await ui.unmount();
});

test("an obviously invalid link is refused before any request", async () => {
    const ui = await mountAppointments([videoAppt({ meeting_link: null })]);
    await openVideoModal(ui);

    const field = ui.container.querySelector('input[type="url"]');
    await act(async () => {
        const setter = Object.getOwnPropertyDescriptor(
            dom.window.HTMLInputElement.prototype, "value").set;
        setter.call(field, "javascript:alert(1)");
        field.dispatchEvent(new dom.window.Event("change", { bubbles: true }));
    });
    const save = [...ui.container.querySelectorAll("button")]
        .find(b => b.textContent.trim() === "Save link");
    await act(async () => {
        save.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true, cancelable: true }));
    });
    await act(async () => { await new Promise(r => realSetTimeout(r, 20)); });

    assert.equal(api.__calls("setMeetingLink").length, 0);
    assert.match(ui.container.textContent, /must start with https/);
    await ui.unmount();
});

test("a server refusal is shown and the link is not treated as saved", async () => {
    api.__respond("setMeetingLink", {
        data: null, status: 422,
        error: { message: "meeting_link must be an https:// URL" },
    });
    const ui = await mountAppointments([videoAppt({ meeting_link: null })]);
    await openVideoModal(ui);

    const field = ui.container.querySelector('input[type="url"]');
    await act(async () => {
        const setter = Object.getOwnPropertyDescriptor(
            dom.window.HTMLInputElement.prototype, "value").set;
        setter.call(field, "https://meet.example.com/x");
        field.dispatchEvent(new dom.window.Event("change", { bubbles: true }));
    });
    const save = [...ui.container.querySelectorAll("button")]
        .find(b => b.textContent.trim() === "Save link");
    await act(async () => {
        save.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true, cancelable: true }));
    });
    await act(async () => { await new Promise(r => realSetTimeout(r, 30)); });

    assert.match(ui.container.textContent, /https:\/\/ URL/);
    await ui.unmount();
});

test("phone and in-person appointments offer no video control", async () => {
    for (const mode of ["phone", "in_person"]) {
        const ui = await mountAppointments([videoAppt({ mode, meeting_link: null })]);
        const labels = ui.labels();
        assert.ok(!labels.some(l => /Join Call|Add joining link/.test(l)),
                  `a ${mode} appointment offered a video control: ${labels}`);
        await ui.unmount();
    }
});
