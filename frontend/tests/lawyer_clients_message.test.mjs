/* LD-05: Clients -> Message opens the client's case workspace.
 *
 * WHAT WAS WRONG. Each client row stored `caseId: c.id`, but the cases API
 * serialises the id as `_id`, so `caseId` was undefined and Message just went
 * to the case list. The workspace finds a case by `case_number || _id`
 * (CasesPage `_mapApiCase`), so that is the key Message must hand over.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { JSDOM } from "jsdom";

const dom = new JSDOM("<!doctype html><html><body></body></html>", { url: "http://localhost/" });
function define(name, value) {
    Object.defineProperty(globalThis, name, { value, writable: true, configurable: true });
}
for (const name of ["window", "document", "navigator", "HTMLElement", "Element", "Node", "Event",
                    "CustomEvent", "MouseEvent", "KeyboardEvent", "MutationObserver",
                    "getComputedStyle", "localStorage", "sessionStorage"]) {
    define(name, dom.window[name]);
}
define("IS_REACT_ACT_ENVIRONMENT", true);

const React = (await import("react")).default;
const { act } = await import("react");
const { createRoot } = await import("react-dom/client");
const api = await import("./support/api-stub.mjs");
const { CaseCtx, NotifCtx } = await import("../src/components/lawyer/theme.js");
const { ClientsPage } = await import("../src/components/lawyer/ClientsPage.jsx");
const h = React.createElement;

const settle = (ms = 30) => act(async () => { await new Promise(r => setTimeout(r, ms)); });

async function clickMessageFor(cases, clientName) {
    api.__reset();
    api.__respond("listCases", { data: { items: cases }, error: null });
    const opened = [];
    const pages = [];
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    await act(async () => {
        root.render(h(NotifCtx.Provider, { value: { addNotif: () => {} } },
            h(CaseCtx.Provider, { value: { setOpenCaseId: id => opened.push(id), setPage: p => pages.push(p) } },
                h(ClientsPage))));
    });
    await settle();
    // One client per test, so the page has exactly one Message button.
    assert.match(container.textContent, new RegExp(clientName));
    const message = [...container.querySelectorAll("button")].find(b => b.textContent.includes("Message"));
    assert.ok(message, `no Message button for ${clientName}`);
    await act(async () => { message.dispatchEvent(new MouseEvent("click", { bubbles: true })); });
    await act(async () => root.unmount());
    container.remove();
    return { opened, pages };
}

const base = { client_id: "cl1", client_name: "Ayesha", province: "punjab",
               created_at: "2026-09-01T00:00:00Z", title: "Rent dispute" };

test("Message opens the workspace by case number when the case has one", async () => {
    const { opened, pages } = await clickMessageFor(
        [{ ...base, _id: "665f00000000000000000001", case_number: "CIV-2026-001" }], "Ayesha");
    assert.deepEqual(opened, ["CIV-2026-001"]);
    assert.deepEqual(pages, ["cases"]);
});

test("Message falls back to the database id when there is no case number", async () => {
    const { opened } = await clickMessageFor(
        [{ ...base, _id: "665f00000000000000000002" }], "Ayesha");
    assert.deepEqual(opened, ["665f00000000000000000002"]);
});
