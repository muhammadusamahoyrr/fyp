/* Toast types: "error" is a failure, and looks like one.
 *
 * WHAT WAS WRONG. ToastContainer knew success / danger / warn / info. Many
 * call sites (client and lawyer) pass "error", which had no entry and fell back
 * to the informational palette, so a failure read as a neutral notice.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { JSDOM } from "jsdom";

const dom = new JSDOM("<!doctype html><html><body></body></html>", { url: "http://localhost/" });
function define(name, value) {
    Object.defineProperty(globalThis, name, { value, writable: true, configurable: true });
}
for (const name of ["window", "document", "navigator", "HTMLElement", "Element", "Node", "Event",
                    "CustomEvent", "MouseEvent", "MutationObserver", "getComputedStyle"]) {
    define(name, dom.window[name]);
}
define("IS_REACT_ACT_ENVIRONMENT", true);

const React = (await import("react")).default;
const { act, useEffect } = await import("react");
const { createRoot } = await import("react-dom/client");
const { ToastContainer, useToast } = await import("../src/components/shared/Toast.jsx");
const { DARK } = await import("../src/components/admin/themes.js");
const h = React.createElement;

const rgb = (hex) => `rgb(${parseInt(hex.slice(1, 3), 16)}, ${parseInt(hex.slice(3, 5), 16)}, ${parseInt(hex.slice(5, 7), 16)})`;

async function colourOf(type) {
    function Fire() {
        const toast = useToast();
        useEffect(() => { toast.show(`a ${type} toast`, type, 0); }, []);
        return null;
    }
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    await act(async () => { root.render(h(ToastContainer, { theme: DARK }, h(Fire))); });
    const span = [...container.querySelectorAll("span")].find(s => s.textContent === `a ${type} toast`);
    assert.ok(span, `the ${type} toast did not render`);
    const colour = span.style.color;
    await act(async () => root.unmount());
    container.remove();
    return colour;
}

test('"error" toasts use the danger palette, not the info one', async () => {
    assert.equal(await colourOf("error"), rgb(DARK.badgeDanger.color));
    assert.notEqual(await colourOf("error"), rgb(DARK.badgeInfo.color));
});

test("the existing types keep their palettes", async () => {
    assert.equal(await colourOf("danger"), rgb(DARK.badgeDanger.color));
    assert.equal(await colourOf("success"), rgb(DARK.badgeSuccess.color));
    assert.equal(await colourOf("info"), rgb(DARK.badgeInfo.color));
});
