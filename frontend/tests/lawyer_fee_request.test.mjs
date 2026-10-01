/* A lawyer's fee request names the Hire it is billed under.
 *
 * The server now refuses a fee request that does not name a valid engagement
 * (AGREEMENTS_PRODUCT_PLAN.md §17 R5-5): this lawyer's, for this case, with
 * this client, accepted or completed — never terminated. It validates the id;
 * this page only has to FIND it, from the lawyer's own engagements, and never
 * send a request without one.
 *
 * The failure worth guarding here is the one this page had before: it sent
 * `engagement_id` as nothing at all, so the server stored whatever it was given.
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

function setNativeValue(el, value) {
    const proto = Object.getPrototypeOf(el);
    const desc = Object.getOwnPropertyDescriptor(proto, "value");
    if (desc && desc.set) desc.set.call(el, value);
    else el.value = value;
}

async function settle(ms = 40) {
    await act(async () => { await new Promise(r => realSetTimeout(r, ms)); });
}

async function mountPayments() {
    const { PaymentsPage } =
        await import("../src/components/lawyer/PaymentsPage.jsx");
    const { ToastContainer } = await import("../src/components/shared/Toast.jsx");
    const { DARK } = await import("../src/components/admin/themes.js");

    const container = dom.window.document.createElement("div");
    dom.window.document.body.appendChild(container);
    const root = createRoot(container);
    await act(async () => {
        root.render(h(ToastContainer, { theme: DARK }, h(PaymentsPage)));
    });
    await settle();

    const click = async (label) => {
        const btn = [...container.querySelectorAll("button")]
            .find(b => b.textContent.trim().startsWith(label));
        assert.ok(btn, `no "${label}" button`);
        await act(async () => {
            btn.dispatchEvent(new dom.window.MouseEvent(
                "click", { bubbles: true, cancelable: true }));
        });
        await settle();
    };
    const type = async (el, value) => {
        await act(async () => {
            setNativeValue(el, value);
            el.dispatchEvent(new dom.window.Event("input", { bubbles: true }));
        });
        await settle(10);
    };
    const pick = async (el, value) => {
        await act(async () => {
            setNativeValue(el, value);
            el.dispatchEvent(new dom.window.Event("change", { bubbles: true }));
        });
        await settle(10);
    };

    return {
        container,
        text: () => dom.window.document.body.textContent,
        click, type, pick,
        caseSelect: () => container.querySelector("select"),
        amountInput: () => container.querySelector('input[inputmode="numeric"]'),
        unmount: async () => { await act(async () => root.unmount()); },
    };
}

async function raiseFee(ui, { caseId = null, amount = "5000" } = {}) {
    await ui.click("+ Raise fee");
    if (caseId) await ui.pick(ui.caseSelect(), caseId);
    await ui.type(ui.amountInput(), amount);
    await ui.click("Send request");
}

function eng(id, caseId, status = "accepted") {
    return { id, case_id: caseId, lawyer_id: "l1", client_id: "c1", status };
}

test.beforeEach(() => {
    api.__reset();
    api.__respond("paymentSummary", { data: { earned: 0, net: 0, pending: 0 } });
    api.__respond("listPayments", { data: [] });
    api.__respond("listCases", { data: { items: [
        { _id: "K1", title: "Case one" }, { _id: "K2", title: "Case two" },
    ] } });
    api.__respond("createFeeRequest", { data: { id: "P1" } });
});

test.after(() => {
    for (const id of liveTimers) { realClearInterval(id); realClearTimeout(id); }
    liveTimers.clear();
    dom.window.close();
});

test("the fee request names the case's accepted engagement", async () => {
    api.__respond("listEngagements", { data: [eng("E1", "K1"), eng("E2", "K2")] });
    const ui = await mountPayments();
    await raiseFee(ui, { caseId: "K2" });

    const calls = api.__calls("createFeeRequest");
    assert.equal(calls.length, 1);
    assert.equal(calls[0].args[0].engagement_id, "E2");
    assert.equal(calls[0].args[0].case_id, "K2");
    await ui.unmount();
});

test("a completed engagement is still billed under", async () => {
    api.__respond("listEngagements", { data: [eng("E1", "K1", "completed")] });
    const ui = await mountPayments();
    await raiseFee(ui);

    assert.equal(api.__calls("createFeeRequest")[0].args[0].engagement_id, "E1");
    await ui.unmount();
});

test("a terminated engagement is never sent as the one to bill", async () => {
    api.__respond("listEngagements", { data: [eng("E1", "K1", "terminated")] });
    const ui = await mountPayments();
    await raiseFee(ui);

    assert.equal(api.__calls("createFeeRequest").length, 0);
    assert.match(ui.text(), /no active engagement/);
    await ui.unmount();
});

test("a case with no engagement sends no request", async () => {
    api.__respond("listEngagements", { data: [eng("E2", "K2")] });
    const ui = await mountPayments();
    await raiseFee(ui, { caseId: "K1" });

    assert.equal(api.__calls("createFeeRequest").length, 0);
    await ui.unmount();
});

test("a failed engagements read is not reported as no engagement", async () => {
    api.__respond("listEngagements",
        { data: null, error: { message: "network down" }, status: 0 });
    const ui = await mountPayments();
    await raiseFee(ui);

    assert.equal(api.__calls("createFeeRequest").length, 0);
    assert.ok(!/no active engagement/.test(ui.text()),
              "a read failure was presented as a fact about the case");
    assert.match(ui.text(), /Could not load your engagements/);
    await ui.unmount();
});
