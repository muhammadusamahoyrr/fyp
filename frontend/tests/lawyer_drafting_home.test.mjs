/* The lawyer's Legal Drafting home (2026-10-09): the approved "Document
 * templates" design, showing only what the drafter really has.
 *
 * Guards: only real templates are carded (no usage or page counts); every
 * control does what it says (open, preview, filter, search, sort, layout,
 * bookmark, drafts); "Upload template" is disabled and labelled, never a
 * working-looking dead button; the page follows the lawyer theme. */
import test from "node:test";
import assert from "node:assert/strict";
import { JSDOM } from "jsdom";

const dom = new JSDOM("<!doctype html><html><body></body></html>", { url: "http://localhost/" });
function define(name, value) {
    Object.defineProperty(globalThis, name, { value, writable: true, configurable: true });
}
for (const name of ["window", "document", "navigator", "HTMLElement", "Element", "Node",
                    "Event", "CustomEvent", "KeyboardEvent", "MutationObserver", "getComputedStyle",
                    "localStorage", "requestAnimationFrame", "cancelAnimationFrame"]) {
    define(name, dom.window[name]);
}
define("IS_REACT_ACT_ENVIRONMENT", true);

const React = (await import("react")).default;
const { act } = await import("react");
const { createRoot } = await import("react-dom/client");
const api = await import("./support/api-stub.mjs");
const { default: DraftingHome } = await import("../src/components/lawyer/DraftingHome.jsx");
const { TEMPLATES, BLANK_TEMPLATE } = await import("../src/lib/lawyerDraftTemplates.js");
const { DARK, LIGHT } = await import("../src/components/lawyer/palette.js");
const { AuthProvider } = await import("../src/context/AuthContext.jsx");
const { ToggleCtx } = await import("../src/components/lawyer/theme.js");
let toggles = 0;

const settle = () => act(async () => { await new Promise(r => setTimeout(r, 15)); });
async function click(el) {
    assert.ok(el, "element not found");
    await act(async () => { el.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true })); });
    await settle();
}
async function type(input, value) {
    const setter = Object.getOwnPropertyDescriptor(dom.window.HTMLInputElement.prototype, "value").set;
    await act(async () => { setter.call(input, value); input.dispatchEvent(new dom.window.Event("input", { bubbles: true })); });
    await settle();
}
const buttons = (el, re) => [...el.querySelectorAll("button")].filter(b => re.test(b.textContent));
const cards = c => [...c.querySelectorAll("[data-template]")];

async function mount(props = {}) {
    api.__respond("myDocumentsV2", { data: { items: [], has_more: false } });
    api.__respond("getMe", { data: { _id: "l1", role: "lawyer", full_name: "Ayesha Siddiqui" }, error: null });
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    const opened = [], openedDrafts = [], deleted = [];
    await act(async () => {
        root.render(React.createElement(AuthProvider, null,
            React.createElement(ToggleCtx.Provider, { value: () => { toggles += 1; } },
                React.createElement(DraftingHome, {
                    onSelect: t => opened.push(t), drafts: [], onOpenDraft: d => openedDrafts.push(d),
                    onDeleteDraft: id => deleted.push(id), t: DARK, ...props,
                }))));
    });
    await settle();
    return { container, opened, openedDrafts, deleted,
        unmount: async () => { await act(async () => root.unmount()); container.remove(); } };
}

test.beforeEach(() => { api.__reset?.(); window.localStorage.clear(); document.body.innerHTML = ""; });

test("only the real templates are carded, with no usage or page counts", async () => {
    const p = await mount();
    assert.equal(cards(p.container).length, TEMPLATES.length);
    const text = p.container.textContent;
    assert.doesNotMatch(text, /\buses\b|\bpages?\b·/i, "an invented usage or page count is shown");
    for (const tmpl of TEMPLATES) assert.match(text, new RegExp(tmpl.law.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
    assert.match(p.container.querySelector("[data-result-line]").textContent, new RegExp(`Showing ${TEMPLATES.length} of ${TEMPLATES.length}`));
    await p.unmount();
});

test("Upload template has no backend: disabled and labelled, never a working action", async () => {
    const p = await mount();
    const up = p.container.querySelector("[data-upload-template]");
    assert.equal(up.disabled, true);
    assert.match(up.textContent, /Soon/);
    await p.unmount();
});

test("New document, Blank document and Draft with AI open the editor; AI asks for the facts first", async () => {
    const p = await mount();
    await click(p.container.querySelector("[data-new-document]"));
    await click(buttons(p.container, /Blank document/)[0]);
    await click(p.container.querySelector("[data-draft-with-ai]"));
    assert.deepEqual(p.opened.map(t => t.id), [BLANK_TEMPLATE.id, BLANK_TEMPLATE.id, BLANK_TEMPLATE.id]);
    assert.equal(p.opened[2].aiFirst, true, "Draft with AI did not open ready for the facts");
    await p.unmount();
});

test("Use template opens that template; Preview shows its own starter body", async () => {
    const p = await mount();
    const plaint = cards(p.container).find(c => /Plaint/.test(c.textContent));
    await click(buttons(plaint, /Preview/)[0]);
    const dlg = document.querySelector('[role="dialog"]');
    assert.ok(dlg, "the preview did not open");
    assert.match(dlg.querySelector("[data-preview-text]").textContent, /ORDER VII RULE 1/i);
    await click(buttons(dlg, /Use template/)[0]);
    assert.equal(document.querySelector('[role="dialog"]'), null, "the preview stayed open");
    await click(buttons(cards(p.container).find(c => /Plaint/.test(c.textContent)), /Use template/)[0]);
    assert.deepEqual(p.opened.map(t => t.name), ["Plaint — Civil Suit", "Plaint — Civil Suit"]);
    await p.unmount();
});

test("category chips, search and Clear filters narrow the real list", async () => {
    const p = await mount();
    const fam = buttons(p.container, /^Family/)[0];
    await click(fam);
    assert.equal(fam.getAttribute("aria-pressed"), "true");
    assert.deepEqual(cards(p.container).map(c => c.querySelector("h3").textContent), ["Dissolution of Marriage Application"]);
    await click(buttons(p.container, /Clear filters/)[0]);
    assert.equal(cards(p.container).length, TEMPLATES.length);
    await type(p.container.querySelector('input[type="search"]'), "order vii");
    assert.deepEqual(cards(p.container).map(c => c.querySelector("h3").textContent), ["Plaint — Civil Suit"], "search does not read the law");
    await type(p.container.querySelector('input[type="search"]'), "zzz");
    assert.match(p.container.textContent, /No templates match/);
    await p.unmount();
});

test("a bookmark saves a template in this browser, and the Saved chip lists it", async () => {
    const p = await mount();
    const plaint = cards(p.container).find(c => /Plaint/.test(c.textContent));
    await click(plaint.querySelector("button[aria-pressed]"));
    assert.equal(plaint.querySelector("button[aria-pressed]").getAttribute("aria-pressed"), "true");
    await click(buttons(p.container, /^Saved/)[0]);
    assert.deepEqual(cards(p.container).map(c => c.querySelector("h3").textContent), ["Plaint — Civil Suit"]);
    assert.deepEqual(JSON.parse(window.localStorage.getItem("attorney:lawyer-saved-templates")), [2]);
    await p.unmount();
});

test("list view and name sort", async () => {
    const p = await mount();
    await click(p.container.querySelector('[aria-label="List view"]'));
    assert.match(p.container.querySelector("[data-template-grid]").className, /\blist\b/);
    const sel = p.container.querySelector("#dh-sort");
    await act(async () => { sel.value = "name"; sel.dispatchEvent(new dom.window.Event("change", { bubbles: true })); });
    await settle();
    const names = cards(p.container).map(c => c.querySelector("h3").textContent);
    assert.deepEqual(names, [...names].sort((a, b) => a.localeCompare(b)));
    await p.unmount();
});

test("My Drafts lists the saved drafts with working Open and Delete", async () => {
    const draft = { id: "d1", title: "My plaint", updated_at: "2026-09-20T10:00:00Z" };
    const p = await mount({ drafts: [draft] });
    await click(buttons(p.container, /My Drafts/)[0]);
    await click(buttons(p.container, /^\s*Open\s*$/)[0]);
    await click(buttons(p.container, /^\s*Delete\s*$/)[0]);
    assert.deepEqual(p.openedDrafts.map(d => d.id), ["d1"]);
    assert.deepEqual(p.deleted, ["d1"]);
    await p.unmount();
});

test("the page follows the lawyer theme, its Theme button switches it, and its CSS is scoped to it", async () => {
    const p = await mount({ t: LIGHT });
    assert.equal(p.container.querySelector("[data-drafting-home]").dataset.mode, "light");
    const before = toggles;
    await click(p.container.querySelector("[data-theme-toggle]"));
    assert.equal(toggles, before + 1, "the Theme button does not switch the app theme");
    assert.ok(p.container.querySelector("[data-account]"), "the account is not shown in the top bar");
    await p.unmount();
    const { DRAFTING_HOME_CSS } = await import("../src/components/lawyer/DraftingHome.jsx");
    for (const rule of DRAFTING_HOME_CSS.replace(/@import url\([^)]*\);/, "").replace(/@keyframes[^{]+\{(?:[^{}]*\{[^{}]*\})*[^{}]*\}/g, "").replace(/@media[^{]+\{([\s\S]*)\}\s*$/m, "$1").split("}")) {
        const sel = rule.split("{")[0].trim();
        if (!sel) continue;
        for (const part of sel.split(",")) assert.match(part.trim(), /^\[data-drafting-home\]/, `unscoped: ${part}`);
    }
});
