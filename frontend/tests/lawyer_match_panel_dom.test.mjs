/* LawyerMatchPanel, mounted.
 *
 * The lib tests prove the wording. This proves the RENDER — that the words
 * reach the screen, and in the right relationship to the list.
 *
 * The gap it covers: a `general_listing` means the matcher found nothing that
 * qualified and is offering verified lawyers to browse. The service explains
 * that in `notice`, and the notice was shown only when there were NO
 * candidates — so in the one case where the distinction matters most, a
 * browsing list appeared under a heading with no explanation of why nothing
 * matched. A source-reading test cannot see that; only rendering can.
 *
 * The panel is extracted from ModChatbot precisely so this is possible without
 * a WebSocket harness.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { JSDOM } from "jsdom";

const dom = new JSDOM("<!doctype html><html><body></body></html>",
                      { url: "http://localhost/" });

function define(name, value) {
    Object.defineProperty(globalThis, name, { value, writable: true, configurable: true });
}
for (const name of ["window", "document", "navigator", "HTMLElement", "Element",
                    "Node", "Event", "CustomEvent", "MutationObserver",
                    "getComputedStyle", "localStorage", "requestAnimationFrame",
                    "cancelAnimationFrame"]) {
    define(name, dom.window[name]);
}
define("IS_REACT_ACT_ENVIRONMENT", true);

const React = (await import("react")).default;
const { act } = await import("react");
const { createRoot } = await import("react-dom/client");
const { default: LawyerMatchPanel } =
    await import("../src/components/client/LawyerMatchPanel.jsx");

const { createElement: h } = React;

const THEME = {
    mode: "light", primary: "#00C49F", surface: "#fff", border: "#eee",
    text: "#111", textMuted: "#666", textDim: "#888", textFaint: "#aaa",
};

async function render(message) {
    const container = dom.window.document.createElement("div");
    dom.window.document.body.appendChild(container);
    const root = createRoot(container);
    await act(async () => {
        root.render(h(LawyerMatchPanel, {
            message, theme: THEME, onBook: () => {},
        }));
    });
    return {
        container,
        text: () => container.textContent || "",
        find: sel => container.querySelector(sel),
        all: sel => [...container.querySelectorAll(sel)],
        unmount: async () => {
            await act(async () => { root.unmount(); });
            container.remove();
        },
    };
}

const RANKED = {
    id: "L1", full_name: "Adv Ranked", province: "punjab",
    match_score: 0.83, rating: 4.5, specializations: ["civil"],
};
const UNRANKED = {
    id: "L9", full_name: "Adv Browsing", province: "sindh",
    match_score: null, rating: 4.0, specializations: ["family"],
};

// ── the gap this closes ────────────────────────────────────────────────────

test("a browsing listing shows the service notice BESIDE its candidates", async () => {
    const v = await render({
        matchedLawyers: [UNRANKED],
        matchResultKind: "general_listing",
        matchNotice: "No specific match; showing verified lawyers in your province.",
    });

    // The list is there...
    assert.equal(v.all('[data-testid="match-lawyer"]').length, 1);
    // ...and so is the reason it is not a list of matches.
    const notice = v.find('[data-testid="match-notice"]');
    assert.ok(notice, "the browsing list rendered with no explanation");
    assert.match(notice.textContent, /No specific match/);
    await v.unmount();
});

test("a browsing candidate is never shown a percentage", async () => {
    const v = await render({
        matchedLawyers: [UNRANKED], matchResultKind: "general_listing",
        matchNotice: "No specific match.",
    });

    const subtitle = v.find('[data-testid="match-subtitle"]').textContent;
    assert.doesNotMatch(subtitle, /%/, `"${subtitle}" invented a score`);
    assert.doesNotMatch(v.text(), /0% match/);
    assert.match(subtitle, /sindh/);
    await v.unmount();
});

test("a browsing list is not headed as a match", async () => {
    const v = await render({
        matchedLawyers: [UNRANKED], matchResultKind: "general_listing", matchNotice: "n",
    });

    const heading = v.find('[data-testid="match-heading"]').textContent;
    assert.match(heading, /browse/i);
    assert.doesNotMatch(heading, /personalized advice/);
    await v.unmount();
});

// ── ranked results are unchanged ───────────────────────────────────────────

test("a ranked candidate still shows its percentage", async () => {
    const v = await render({ matchedLawyers: [RANKED], matchResultKind: "matched" });

    assert.match(v.find('[data-testid="match-subtitle"]').textContent, /83% match/);
    assert.match(v.find('[data-testid="match-heading"]').textContent,
                 /Connect with a lawyer/);
    await v.unmount();
});

test("a ranked list carries no browsing notice", async () => {
    // The notice explains why nothing matched. On a list that DID match it
    // would contradict the heading directly above it.
    const v = await render({
        matchedLawyers: [RANKED], matchResultKind: "matched",
        matchNotice: "should not appear",
    });

    assert.equal(v.find('[data-testid="match-notice"]'), null);
    assert.doesNotMatch(v.text(), /should not appear/);
    await v.unmount();
});

test("the max-attempts heading survives", async () => {
    const v = await render({
        matchedLawyers: [RANKED], matchResultKind: "matched", suggestLawyer: true,
    });

    assert.match(v.find('[data-testid="match-heading"]').textContent,
                 /reached its limit/);
    await v.unmount();
});

// ── nothing to show ────────────────────────────────────────────────────────

test("no candidates renders the notice and no list", async () => {
    const v = await render({ matchedLawyers: [], matchResultKind: "none" });

    assert.equal(v.find('[data-testid="match-panel"]'), null);
    assert.match(v.find('[data-testid="match-notice"]').textContent,
                 /No verified lawyers/i);
    await v.unmount();
});

test("unavailable never tells the client there are no lawyers", async () => {
    const v = await render({ matchedLawyers: [], matchResultKind: "unavailable" });

    const text = v.text();
    assert.match(text, /unavailable/i);
    assert.doesNotMatch(text, /No verified lawyers/i,
        "a failed lookup was reported as an absence of lawyers");
    await v.unmount();
});

test("a message with no matching data renders nothing at all", async () => {
    const v = await render({ matchedLawyers: [] });

    assert.equal(v.text(), "");
    await v.unmount();
});

// ── malformed rows must not crash the component ────────────────────────────

test("a lawyer with a non-array specializations does not crash the render", async () => {
    // `.slice(0,2).join()` is a TypeError on a string. The backend coerces this
    // now, but the component must not depend on that being the only producer.
    const v = await render({
        matchedLawyers: [{ ...UNRANKED, specializations: "civil" }],
        matchResultKind: "matched",
    });

    assert.equal(v.all('[data-testid="match-lawyer"]').length, 1);
    await v.unmount();
});

test("missing fields render without throwing", async () => {
    const v = await render({
        matchedLawyers: [{}, { full_name: "Adv X" }],
        matchResultKind: "matched",
    });

    assert.equal(v.all('[data-testid="match-lawyer"]').length, 2);
    assert.match(v.text(), /Adv X/);
    await v.unmount();
});

test("a non-array matchedLawyers is tolerated", async () => {
    const v = await render({ matchedLawyers: "nope", matchResultKind: "matched" });

    assert.equal(v.find('[data-testid="match-panel"]'), null);
    await v.unmount();
});

test.after(() => { dom.window.close(); });
