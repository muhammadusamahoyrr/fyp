/* Reporting a wrong appointment record, and adjudicating the report.
 *
 * THE GAP. A lawyer can mark a client absent, or never record an outcome at
 * all. Either quietly removes the client's right to review that lawyer —
 * `exists_completed` gates it — and the client had nowhere to go.
 *
 * THE RULE BOTH SURFACES MUST RESPECT. Filing a report changes NOTHING about
 * the appointment. The client is told so before they write a word, because
 * someone who believed their record had been corrected would stop pursuing it.
 * Only support may change it, and only deliberately.
 *
 * AND THE ONE THAT MATTERS MOST HERE. The private support note is written by an
 * officer about a lawyer, and must never reach the client. It is kept in its
 * own field, in its own block, labelled as internal — because the failure mode
 * is not a subtle bug, it is an officer typing an assessment of a lawyer into
 * the box a client reads.
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

const PRIVATE = "INTERNAL: third complaint about this lawyer";
const STATEMENT = "I attended the whole consultation.";

function ok(data) { return { data, error: null, status: 200 }; }
function failed(message, status = 0) {
    return { data: null, error: { message }, status };
}

function appt(over = {}) {
    const ended = new Date(Date.now() - 5 * 36e5);
    return {
        id: "apt-1",
        scheduled_at: new Date(ended.getTime() - 36e5).toISOString(),
        end_at: ended.toISOString(),
        duration_minutes: 60,
        status: "no_show",
        mode: "video",
        lawyer_name: "Adv Ayesha Khan",
        client_name: "Client One",
        timezone: "Asia/Karachi",
        schedule_version: 0,
        ...over,
    };
}

function dispute(over = {}) {
    return {
        id: "dsp_1", appointment_id: "apt-1", category: "incorrect_no_show",
        statement: STATEMENT, status: "open", version: 0,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        decision: null, resolution_explanation: null, resolved_at: null,
        ...over,
    };
}

/* ── the client's surface ─────────────────────────────────────────────────── */

async function mountClient(items) {
    api.__respond("listAppointments",
                  ok({ items, total: items.length, page: 1, page_size: 25, pages: 1 }));
    const ModTracking = (await import("../src/components/client/ModTracking.jsx")).default;
    const { CaseCtx } = await import("../src/components/shared/CaseContext.jsx");

    const container = dom.window.document.createElement("div");
    dom.window.document.body.appendChild(container);
    const root = createRoot(container);
    await act(async () => {
        root.render(h(CaseCtx.Provider, {
            value: {
                notifications: [], markNotificationDone: () => {},
                markAllNotificationsDone: () => {}, appointmentMilestones: [],
            },
        }, h(ModTracking, { isDark: true })));
    });
    await act(async () => { await new Promise(r => realSetTimeout(r, 40)); });

    const buttons = () => [...container.querySelectorAll("button")];
    const byText = (label) => buttons().find(b => b.textContent.trim() === label);

    const ui = {
        container,
        text: () => container.textContent,
        byText,
        click: async (label) => {
            const btn = byText(label);
            assert.ok(btn, `no control labelled ${label}`);
            await act(async () => {
                btn.dispatchEvent(new dom.window.MouseEvent(
                    "click", { bubbles: true, cancelable: true }));
            });
            await act(async () => { await new Promise(r => realSetTimeout(r, 30)); });
        },
        type: async (text) => {
            const area = container.querySelector("textarea");
            assert.ok(area, "no text field");
            const setter = Object.getOwnPropertyDescriptor(
                dom.window.HTMLTextAreaElement.prototype, "value").set;
            await act(async () => {
                setter.call(area, text);
                area.dispatchEvent(new dom.window.Event("input", { bubbles: true }));
            });
        },
        openAppointments: async () => {
            const nav = [...container.querySelectorAll("div")]
                .find(el => el.textContent.trim() === "Appointments");
            assert.ok(nav, "no Appointments nav control");
            await act(async () => {
                nav.dispatchEvent(new dom.window.MouseEvent(
                    "click", { bubbles: true, cancelable: true }));
            });
            await act(async () => { await new Promise(r => realSetTimeout(r, 40)); });
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
    api.__respond("listAppointmentDisputes", ok([]));
});

test.after(() => {
    for (const id of liveTimers) { realClearInterval(id); realClearTimeout(id); }
    liveTimers.clear();
    dom.window.close();
});

test("a no-show appointment offers a report control", async () => {
    const ui = await mountClient([appt({ status: "no_show" })]);
    await ui.openAppointments();

    assert.ok(ui.byText("Report an issue"));
    await ui.unmount();
});

test("an unrecorded outcome offers a report control", async () => {
    const ui = await mountClient([appt({ status: "confirmed" })]);
    await ui.openAppointments();

    assert.ok(ui.byText("Report an issue"));
    await ui.unmount();
});

test("appointments with nothing to report offer no control", async () => {
    // A control offered where the server would refuse is a button that always
    // fails.
    for (const status of ["pending", "cancelled", "completed", "expired"]) {
        const ui = await mountClient([appt({ status })]);
        await ui.openAppointments();
        assert.equal(ui.byText("Report an issue"), undefined,
                     `a ${status} appointment offered a report control`);
        await ui.unmount();
    }
});

test("a confirmed appointment inside the grace period offers no control", async () => {
    const ended = new Date(Date.now() - 30 * 60e3).toISOString();
    const ui = await mountClient([appt({ status: "confirmed", end_at: ended })]);
    await ui.openAppointments();

    assert.equal(ui.byText("Report an issue"), undefined);
    await ui.unmount();
});

test("the form says filing does not change the appointment", async () => {
    // Said BEFORE they write anything: a client who believed the record had
    // been corrected would stop pursuing it.
    const ui = await mountClient([appt()]);
    await ui.openAppointments();
    await ui.click("Report an issue");

    assert.match(ui.text(), /does not change the appointment/i);
    await ui.unmount();
});

test("submitting sends the report and says so", async () => {
    api.__respond("openAppointmentDispute", { ...ok(dispute()), status: 201 });
    const ui = await mountClient([appt()]);
    await ui.openAppointments();
    await ui.click("Report an issue");
    await ui.type(STATEMENT);
    await ui.click("Send report");

    const calls = api.__calls("openAppointmentDispute");
    assert.equal(calls.length, 1);
    assert.equal(calls[0].args[1].statement, STATEMENT);
    assert.equal(calls[0].args[1].category, "incorrect_no_show");
    await ui.unmount();
});

test("an empty report is refused before it is sent", async () => {
    const ui = await mountClient([appt()]);
    await ui.openAppointments();
    await ui.click("Report an issue");
    await ui.click("Send report");

    assert.equal(api.__calls("openAppointmentDispute").length, 0);
    assert.match(ui.text(), /describe what happened/i);
    await ui.unmount();
});

test("a conflict is distinguished from a failure", async () => {
    api.__respond("openAppointmentDispute",
                  failed("You already have an open report for this appointment.", 409));
    const ui = await mountClient([appt()]);
    await ui.openAppointments();
    await ui.click("Report an issue");
    await ui.type("Something different.");
    await ui.click("Send report");

    assert.match(ui.text(), /already have an open report/i);
    await ui.unmount();
});

test("a failed submission is not reported as success", async () => {
    // `apiFetch` RESOLVES on failure, so an unchecked result would tell the
    // client a complaint was filed that nobody ever received.
    api.__respond("openAppointmentDispute", failed("network down"));
    const ui = await mountClient([appt()]);
    await ui.openAppointments();
    await ui.click("Report an issue");
    await ui.type(STATEMENT);
    await ui.click("Send report");

    assert.match(ui.text(), /could not be sent/i);
    assert.ok(!/Report sent/i.test(ui.text()));
    await ui.unmount();
});

test("an existing open report is shown instead of the form", async () => {
    api.__respond("listAppointmentDisputes", ok([dispute()]));
    const ui = await mountClient([appt()]);
    await ui.openAppointments();

    assert.match(ui.text(), /with support/i);
    assert.equal(ui.byText("Report an issue"), undefined);
    await ui.unmount();
});

test("a decided report shows the public explanation only", async () => {
    api.__respond("listAppointmentDisputes", ok([dispute({
        status: "resolved", decision: "correct_to_completed",
        resolution_explanation: "We corrected the record.",
    })]));
    const ui = await mountClient([appt()]);
    await ui.openAppointments();

    assert.match(ui.text(), /We corrected the record\./);
    assert.ok(!ui.text().includes("INTERNAL"));
    await ui.unmount();
});

/* ── the support surface ──────────────────────────────────────────────────── */

async function mountAdmin() {
    const { AppointmentDisputes } =
        await import("../src/components/admin/AdminDisputes.jsx");

    const container = dom.window.document.createElement("div");
    dom.window.document.body.appendChild(container);
    const root = createRoot(container);
    await act(async () => { root.render(h(AppointmentDisputes, { T: {} })); });
    await act(async () => { await new Promise(r => realSetTimeout(r, 40)); });

    const buttons = () => [...container.querySelectorAll("button")];
    return {
        container,
        text: () => container.textContent,
        buttons,
        byText: (label) => buttons().find(b => b.textContent.trim() === label),
        click: async (label) => {
            const btn = buttons().find(b => b.textContent.trim() === label);
            assert.ok(btn, `no control labelled ${label}`);
            await act(async () => {
                btn.dispatchEvent(new dom.window.MouseEvent(
                    "click", { bubbles: true, cancelable: true }));
            });
            await act(async () => { await new Promise(r => realSetTimeout(r, 30)); });
        },
        choose: async (value) => {
            const radio = container.querySelector(`input[value="${value}"]`);
            assert.ok(radio, `no decision option ${value}`);
            await act(async () => {
                radio.click();
            });
        },
        fill: async (label, text) => {
            const area = [...container.querySelectorAll("textarea")]
                .find(el => el.getAttribute("aria-label") === label);
            assert.ok(area, `no field labelled ${label}`);
            const setter = Object.getOwnPropertyDescriptor(
                dom.window.HTMLTextAreaElement.prototype, "value").set;
            await act(async () => {
                setter.call(area, text);
                area.dispatchEvent(new dom.window.Event("input", { bubbles: true }));
            });
        },
        unmount: async () => { await act(async () => root.unmount()); },
    };
}

function queue(items, over = {}) {
    return ok({ items, total: items.length, page: 1, page_size: 25, pages: 1, ...over });
}

test("the queue lists an open report with the client's statement", async () => {
    api.__respond("listOpenDisputes", queue([dispute()]));
    const ui = await mountAdmin();

    assert.match(ui.text(), /Client disputes a no-show/);
    assert.match(ui.text(), new RegExp(STATEMENT));
    await ui.unmount();
});

test("a failed queue read is not an empty queue", async () => {
    api.__respond("listOpenDisputes", failed("down"));
    const ui = await mountAdmin();

    assert.match(ui.text(), /could not be loaded/i);
    assert.ok(!/No reports are waiting/i.test(ui.text()));
    await ui.unmount();
});

test("the private note is a separate, labelled field", async () => {
    // The failure mode is an officer typing an assessment of a lawyer into the
    // box the client reads.
    api.__respond("listOpenDisputes", queue([dispute()]));
    const ui = await mountAdmin();

    const labels = [...ui.container.querySelectorAll("textarea")]
        .map(el => el.getAttribute("aria-label"));
    assert.deepEqual(labels, ["Explanation for the client",
                              "Private support note"]);
    assert.match(ui.text(), /internal only/i);
    assert.match(ui.text(), /Never shown\s+to the client or the lawyer/i);
    await ui.unmount();
});

test("a decision sends the version it was read at", async () => {
    api.__respond("listOpenDisputes", queue([dispute({ version: 3 })]));
    api.__respond("resolveDispute", ok(dispute({ status: "resolved" })));
    const ui = await mountAdmin();

    await ui.choose("correct_to_completed");
    await ui.fill("Explanation for the client", "Corrected after review.");
    await ui.fill("Private support note", PRIVATE);
    await ui.click("Save decision");

    const calls = api.__calls("resolveDispute");
    assert.equal(calls.length, 1);
    assert.equal(calls[0].args[1].expected_version, 3);
    assert.equal(calls[0].args[1].decision, "correct_to_completed");
    assert.equal(calls[0].args[1].support_note, PRIVATE);
    await ui.unmount();
});

test("a decision requires a public explanation", async () => {
    api.__respond("listOpenDisputes", queue([dispute()]));
    const ui = await mountAdmin();

    await ui.choose("dismiss_report");
    await ui.click("Save decision");

    assert.equal(api.__calls("resolveDispute").length, 0);
    assert.match(ui.text(), /explanation is required/i);
    await ui.unmount();
});

test("a 409 reloads rather than claiming success", async () => {
    // Two officers working the same queue will sometimes decide one report at
    // the same moment. The loser must see what actually landed.
    api.__respond("listOpenDisputes", queue([dispute()]));
    api.__respond("resolveDispute", failed("decided by someone else", 409));
    const ui = await mountAdmin();

    await ui.choose("dismiss_report");
    await ui.fill("Explanation for the client", "Dismissed.");
    await ui.click("Save decision");

    assert.match(ui.text(), /Someone else decided this report/i);
    assert.ok(api.__calls("listOpenDisputes").length >= 2,
              "the queue was not reloaded after the conflict");
    await ui.unmount();
});

test("the decision options say what each one does to the appointment", async () => {
    api.__respond("listOpenDisputes", queue([dispute()]));
    const ui = await mountAdmin();

    assert.match(ui.text(), /Changes the appointment and restores the review right/i);
    assert.match(ui.text(), /Leaves the appointment exactly as it is/i);
    await ui.unmount();
});

test("the queue pages when the server says there is more", async () => {
    api.__respond("listOpenDisputes", queue([dispute()], { total: 60, pages: 3 }));
    const ui = await mountAdmin();

    assert.ok(ui.byText("Next"), "no way to reach the rest of the queue");
    assert.match(ui.text(), /60 open reports/);
    await ui.unmount();
});
