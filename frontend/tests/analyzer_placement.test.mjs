/* Where the Document Analyzer lives (decision of 2026-10-03): ONLY on the
 * lawyer dashboard, with the same workspace, flow and design it had before.
 * The client dashboard offers it nowhere, and the old client URL redirects. */
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync, existsSync } from "node:fs";
import { JSDOM } from "jsdom";

const dom = new JSDOM("<!doctype html><html><body></body></html>", { url: "http://localhost/" });
function define(name, value) {
    Object.defineProperty(globalThis, name, { value, writable: true, configurable: true });
}
for (const name of ["window", "document", "navigator", "HTMLElement", "Element", "Node",
                    "Event", "KeyboardEvent", "CustomEvent", "MutationObserver",
                    "getComputedStyle", "DOMParser", "File"]) {
    define(name, dom.window[name]);
}
define("IS_REACT_ACT_ENVIRONMENT", true);

const React = (await import("react")).default;
const { act } = await import("react");
const { createRoot } = await import("react-dom/client");
const api = await import("./support/api-stub.mjs");
const { ToastCtx } = await import("../src/components/lawyer/Toast.jsx");
const lawyerTheme = await import("../src/components/lawyer/theme.js");
const { DocAnalyzerPage } = await import("../src/components/lawyer/DocAnalyzerPage.jsx");
const nav = await import("../src/lib/documentsNav.js");

const src = path => readFileSync(new URL(`../src/${path}`, import.meta.url), "utf8");
const ATTESTATION = { version: "synthetic-v1",
    text: "Demo only — do not upload real client or confidential documents. I confirm this document is synthetic (made up for testing)." };

// ── the client dashboard: no analyzer anywhere ──────────────────────────────

test("the client Documents menu, module and drafting screen offer no analyzer", () => {
    assert.doesNotMatch(src("components/client/Dashboard.jsx"), /view: "analyzer"/, "the sidebar still offers it");
    const module = src("components/client/ModDocuments.jsx");
    assert.doesNotMatch(module, /AnalyzerWorkspace|DocsAnalyzer|view === "analyzer"/, "the module still mounts it");
    assert.doesNotMatch(src("components/client/documents/DocsDrafts.jsx"), /onOpenView\("analyzer"\)/);
    assert.equal(existsSync(new URL("../src/components/client/documents/DocsAnalyzer.jsx", import.meta.url)), false,
        "a client copy of the analyzer remains");
});

test("a request for the analyzer view is ignored on the client", () => {
    assert.ok(!nav.DOCUMENTS_VIEWS.includes("analyzer"));
    assert.equal(nav.peekPendingDocumentsView(), null);
    nav.requestDocumentsView("analyzer");
    assert.equal(nav.peekPendingDocumentsView(), null, "an analyzer request was queued");
});

test("the old client analyzer URL redirects to Documents", () => {
    const page = src("app/(client)/documents/analyzer/page.jsx");
    assert.match(page, /redirect\("\/documents"\)/);
});

// ── the lawyer dashboard: the same workspace ────────────────────────────────

test("the lawyer dashboard lists the Document Analyzer and routes to it", () => {
    assert.match(src("components/lawyer/layout.jsx"), /\{ id: "doc-analyzer", label: "Document Analyzer"/);
    assert.match(src("components/lawyer/App.jsx"), /"doc-analyzer": DocAnalyzerPage/);
    assert.match(src("app/lawyer/documents/analyzer/page.jsx"), /<App initialPage="doc-analyzer" \/>/);
});

async function mountLawyer(theme) {
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    const pages = [];
    await act(async () => {
        root.render(React.createElement(ToastCtx.Provider, { value: { show: () => {} } },
            React.createElement(lawyerTheme.ThemeCtx.Provider, { value: theme },
                React.createElement(lawyerTheme.CaseCtx.Provider, { value: { setPage: p => pages.push(p) } },
                    React.createElement(DocAnalyzerPage)))));
    });
    await act(async () => { await new Promise(r => setTimeout(r, 15)); });
    return { container, pages, unmount: () => act(async () => root.unmount()).then(() => container.remove()) };
}

test("the lawyer page mounts the same analyzer workspace, live when the server offers it", async () => {
    api.__respond("analyzerAttestation", { data: ATTESTATION, error: null, status: 200 });
    api.__respond("listAnalyses", { data: { items: [], next: null } });
    const p = await mountLawyer(lawyerTheme.DARK);
    assert.ok(p.container.querySelector("[data-lawyer-analyzer]"));
    assert.ok(p.container.querySelector("[data-analyzer-live]"), "the live analyzer is not shown to the lawyer");
    await p.unmount();
});

test("the lawyer page follows the lawyer's theme", async () => {
    api.__respond("analyzerAttestation", { data: null, error: { code: "feature_disabled" }, status: 404 });
    const dark = await mountLawyer(lawyerTheme.DARK);
    const light = await mountLawyer(lawyerTheme.LIGHT);
    assert.ok(dark.container.querySelector("[data-fictional-banner]"), "the demonstration is not shown when off");
    assert.notEqual(dark.container.innerHTML, light.container.innerHTML, "the theme did not reach the workspace");
    await dark.unmount();
    await light.unmount();
});

test("no analyzer screen claims a KYC or verification status (none exists yet)", () => {
    for (const file of ["components/analyzer/AnalyzerWorkspace.jsx", "components/analyzer/AnalyzerLive.jsx",
                        "components/lawyer/DocAnalyzerPage.jsx"]) {
        assert.doesNotMatch(src(file), /KYC|verified lawyer|KYC approved/i, `${file} claims a verification`);
    }
});
