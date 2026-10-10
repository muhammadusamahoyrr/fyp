/* The redesigned Documents screens, mounted in a real DOM.
 *
 * DocumentsHome is presentation only, so what matters is the intent it hands
 * ModDocuments. The Vault and Drafts read real server state. The Analyzer is not
 * connected to a backend yet: it is a fictional demonstration, and the P-1 tests
 * below keep every view of it from claiming more than exists. */
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
                    "Element", "Node", "Event", "KeyboardEvent", "CustomEvent",
                    "MutationObserver", "getComputedStyle", "DOMParser"]) {
    define(name, dom.window[name]);
}
define("IS_REACT_ACT_ENVIRONMENT", true);

const React = (await import("react")).default;
const { act } = await import("react");
const { createRoot } = await import("react-dom/client");
const api = await import("./support/api-stub.mjs");
const { default: DocumentsHome, templateMatches } =
    await import("../src/components/client/DocumentsHome.jsx");
const { default: DocsVault, accessOf, formatWhen } =
    await import("../src/components/client/documents/DocsVault.jsx");
const { default: DocsDrafts, placeholderCounts } =
    await import("../src/components/client/documents/DocsDrafts.jsx");
const { default: DocsAnalyzer } =
    await import("../src/components/analyzer/AnalyzerWorkspace.jsx");
const { ToastCtx } = await import("../src/components/shared/Toast.jsx");
// The analyzer is lawyer-owned and reads the lawyer's own toast context.
const { ToastCtx: LawyerToastCtx } = await import("../src/components/lawyer/Toast.jsx");
const toasts = [];

const TEMPLATES = [
    { template_type: "legal_notice", label: "Legal Notice", category: "Civil",
      description: "A formal demand before suing.", fields: ["sender_name", "demand"],
      structured_fields: [], drafting_mode: "ai" },
    { template_type: "affidavit", label: "Affidavit", category: "Civil",
      description: "A sworn statement of facts.", fields: ["deponent_name"],
      structured_fields: [], drafting_mode: "manual" },
    { template_type: "labour_demand", label: "Labour Demand", category: "Employment",
      description: "Dues owed to a worker.", fields: ["dues"],
      structured_fields: ["dues"], drafting_mode: "dedicated" },
];
const draftingMode = spec => spec?.drafting_mode || "ai";
const dedicatedToolHref = () => "/tools?tab=calculators";

async function mount(Component, props) {
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    const render = async (extra = {}) => {
        await act(async () => {
            const show = { show: m => toasts.push(m) };
            root.render(React.createElement(ToastCtx.Provider, { value: show },
                React.createElement(LawyerToastCtx.Provider, { value: show },
                    React.createElement(Component, { ...props, ...extra }))));
        });
        await act(async () => { await new Promise(r => setTimeout(r, 10)); });
    };
    await render();
    return {
        container, render,
        unmount: () => act(async () => root.unmount()).then(() => container.remove()),
    };
}

async function mountHome(extra = {}) {
    const calls = { use: [], plan: [], view: [] };
    const p = await mount(DocumentsHome, {
        templates: TEMPLATES, templateIssue: null, cases: [{ _id: "case-1", title: "A matter" }],
        draftingMode, dedicatedToolHref,
        onUse: (spec, prefill) => calls.use.push({ spec, prefill }),
        onPlan: seed => calls.plan.push(seed),
        onOpenView: v => calls.view.push(v),
        ...extra,
    });
    return { ...p, calls };
}

const buttons = (el, text) => [...el.querySelectorAll("button")]
    .filter(b => b.textContent.includes(text));
const byLabel = (el, label) => [...el.querySelectorAll("button")]
    .find(b => b.getAttribute("aria-label") === label);
const cards = el => [...el.querySelectorAll("[data-template]")].map(a => a.dataset.template);
async function click(el) {
    assert.ok(el, "nothing to click");
    await act(async () => {
        el.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true }));
    });
    await act(async () => { await new Promise(r => setTimeout(r, 10)); });
}
async function type(input, value) {
    const proto = input.tagName === "TEXTAREA"
        ? dom.window.HTMLTextAreaElement.prototype : dom.window.HTMLInputElement.prototype;
    const setter = Object.getOwnPropertyDescriptor(proto, "value").set;
    await act(async () => {
        setter.call(input, value);
        input.dispatchEvent(new dom.window.Event("input", { bubbles: true }));
    });
}

test.beforeEach(() => {
    api.__reset();
    toasts.length = 0;
    api.__respond("pleadingRequirements", { data: {
        covered: true, checked: false, items: [
            { clause: "CPC O.VII r.1", requirement: "The cause of action is stated", status: "to_confirm" },
        ] } });
});
test.after(() => dom.window.close());

/* ── home ─────────────────────────────────────────────────────────────────── */

test("templateMatches searches label, description and category", () => {
    assert.ok(templateMatches(TEMPLATES[0], "notice"));
    assert.ok(templateMatches(TEMPLATES[1], "SWORN"));
    assert.ok(templateMatches(TEMPLATES[2], "employment"));
    assert.ok(!templateMatches(TEMPLATES[0], "affidavit"));
    assert.ok(templateMatches(TEMPLATES[0], "   "));
});

test("search narrows the cards and an empty result offers a way back", async () => {
    const p = await mountHome();
    assert.deepEqual(cards(p.container), ["legal_notice", "affidavit", "labour_demand"]);
    await type(p.container.querySelector("#tpl-search"), "sworn");
    assert.deepEqual(cards(p.container), ["affidavit"]);
    await type(p.container.querySelector("#tpl-search"), "zzz");
    assert.match(p.container.textContent, /No template matches/);
    await click(buttons(p.container, "Show all templates")[0]);
    assert.equal(cards(p.container).length, 3);
    await p.unmount();
});

test("a category chip filters, and says how many it holds", async () => {
    const p = await mountHome();
    const filter = p.container.querySelector('[aria-label="Filter by category"]');
    // The chips are a row of their own; search sits on the heading row (2026-10-08).
    assert.equal(filter.querySelector("#tpl-search"), null, "search is not in the chip row");
    assert.ok(p.container.querySelector("[data-template-search] #tpl-search"));
    const employment = buttons(filter, "Employment")[0];
    assert.match(employment.textContent, /1$/);
    await click(employment);
    assert.equal(employment.getAttribute("aria-pressed"), "true");
    assert.deepEqual(cards(p.container), ["labour_demand"]);
    await p.unmount();
});

test("Use template proceeds in one click with that template", async () => {
    const p = await mountHome();
    const card = p.container.querySelector('[data-template="affidavit"]');
    await click(buttons(card, "Use template")[0]);
    assert.equal(p.calls.use.length, 1);
    assert.equal(p.calls.use[0].spec.template_type, "affidavit");
    assert.equal(p.calls.use[0].prefill, undefined);
    await p.unmount();
});

test("the preview lists the details and requirements, and starts in one call", async () => {
    const p = await mountHome();
    await click(byLabel(p.container, "Preview Affidavit"));
    const dialog = document.querySelector('[role="dialog"]');
    assert.ok(dialog, "preview did not open");
    assert.equal(p.calls.use.length, 0, "opening the preview started drafting");
    assert.match(dialog.textContent, /Deponent name/);
    assert.match(dialog.textContent, /cause of action is stated/);
    assert.match(dialog.textContent, /not checked automatically/);
    assert.match(dialog.textContent, /2 of 3/);

    await click(buttons(dialog, "Use this template")[0]);
    assert.equal(p.calls.use[0].spec.template_type, "affidavit",
        "onUse must receive the spec — the parent's selection is stale in this click");
    assert.equal(document.querySelector('[role="dialog"]'), null);
    await p.unmount();
});

test("popups render over the whole screen, outside the page", async () => {
    // Inside the page, a transformed ancestor (.aFadeUp) pinned the "fixed"
    // overlay to the scrolled content: it opened far down and left the sidebar
    // uncovered.
    const p = await mountHome();
    await click(byLabel(p.container, "Edit Legal Notice"));
    const dialog = document.querySelector('[aria-label="Customize template"]');
    assert.ok(dialog, "the editor did not open");
    assert.ok(!p.container.contains(dialog), "the editor rendered inside the page again");
    const backdrop = dialog.parentElement;
    assert.equal(backdrop.style.position, "fixed");
    assert.match(backdrop.style.backdropFilter || backdrop.getAttribute("style"), /blur/);
    await p.unmount();
    assert.equal(document.querySelector('[aria-label="Customize template"]'), null, "the portal outlived its page");
});

test("the preview pages through templates and Escape closes it", async () => {
    const p = await mountHome();
    await click(byLabel(p.container, "Preview Legal Notice"));
    await click(byLabel(document.body, "Next template"));
    assert.match(document.querySelector('[role="dialog"]').textContent, /Affidavit/);
    await act(async () => {
        document.dispatchEvent(new dom.window.KeyboardEvent("keydown", { key: "Escape" }));
    });
    assert.equal(document.querySelector('[role="dialog"]'), null);
    await p.unmount();
});

test("the editor opens on an outline, fills details, saves locally and carries them on", async () => {
    dom.window.localStorage.clear();
    const p = await mountHome();
    await click(byLabel(p.container, "Edit Legal Notice"));
    const dialog = document.querySelector('[aria-label="Customize template"]');
    assert.ok(dialog, "the editor did not open");
    const page = dialog.querySelector('[aria-label="Document text"]');
    assert.match(page.innerHTML, /<h1[^>]*>LEGAL NOTICE<\/h1>/);
    assert.match(page.textContent, /\[SENDER NAME\]/, "details must start as placeholders");
    assert.ok(dialog.querySelector('[role="toolbar"] [aria-label="Bold"]'), "no formatting toolbar");
    assert.match(dialog.textContent, /characters · \d+ words/);

    await type(dialog.querySelector("#cz_sender_name"), "Ayesha Khan");
    assert.match(dialog.textContent, /1 of 2 filled/);
    await click(buttons(dialog, "Apply to page")[0]);
    assert.match(page.textContent, /Ayesha Khan/);
    assert.doesNotMatch(page.textContent, /\[SENDER NAME\]/);

    await click(buttons(dialog, "Save changes")[0]);
    const stored = JSON.parse(dom.window.localStorage.getItem("attorney.templateCopy.legal_notice"));
    assert.match(stored.html, /Ayesha Khan/);
    assert.deepEqual(stored.values, { sender_name: "Ayesha Khan" });
    assert.match(dialog.textContent, /Saved on this device/);

    await click(buttons(dialog, "Use template")[0]);
    assert.equal(p.calls.use[0].spec.template_type, "legal_notice");
    assert.deepEqual(p.calls.use[0].prefill, { sender_name: "Ayesha Khan" });
    await p.unmount();
    dom.window.localStorage.clear();
});

test("editor HTML is cleaned before it is stored or exported", async () => {
    const { cleanHtml, countWords, outlineHtml } = await import("../src/components/client/documents/TemplateEditor.jsx");
    const dirty = '<p onclick="x()">Hi<script>alert(1)</script><img src="x" onerror="steal()">'
        + '<a href="javascript:alert(1)">a</a><a href=" JaVaScRiPt:alert(1)">b</a><a href="https://ok.pk">c</a></p><iframe srcdoc="x"></iframe>';
    const out = cleanHtml(dirty);
    assert.doesNotMatch(out, /script|onerror|onclick|javascript|iframe|srcdoc/i);
    assert.match(out, /href="https:\/\/ok\.pk"/);
    assert.deepEqual(countWords("  two words "), { chars: 12, words: 2 });
    // Without a parser the cleaner keeps text only — it must never pass markup through.
    const saved = globalThis.DOMParser;
    try {
        delete globalThis.DOMParser;
        const plain = cleanHtml(dirty);
        assert.doesNotMatch(plain, /<|alert\(1\)<\/script/);
        assert.match(plain, /Hi/);
    } finally { globalThis.DOMParser = saved; }
    assert.deepEqual(countWords(""), { chars: 0, words: 0 });
    // The outline escapes whatever the catalogue says.
    assert.doesNotMatch(outlineHtml({ label: "<b>x</b>", description: "<img src=x onerror=y>", fields: [] }), /<img|<b>x/);
});

test("the templates page replaces the drafting composer with real catalogue totals", async () => {
    const p = await mountHome();
    assert.equal(p.container.querySelector("#docs-need"), null);
    assert.equal(buttons(p.container, "Plan my draft").length, 0);
    const overview = p.container.querySelector('[aria-label="Template overview"]');
    assert.ok(overview);
    assert.match(overview.textContent, /Total templates3/);
    assert.match(overview.textContent, /AI-assisted1/);
    assert.match(overview.textContent, /Categories2/);
    assert.match(overview.textContent, /Available3/);
    assert.deepEqual(p.calls.plan, []);
    await p.unmount();
});

test("a dedicated template links to its calculator and cannot be used here", async () => {
    const p = await mountHome();
    const card = p.container.querySelector('[data-template="labour_demand"]');
    const link = [...card.querySelectorAll("a")].find(a => a.textContent.includes("calculator"));
    assert.equal(link?.getAttribute("href"), "/tools?tab=calculators");
    assert.equal(buttons(card, "Use template").length, 0);
    await p.unmount();
});

test("a catalogue failure is shown as the reason, not as 'no templates'", async () => {
    const p = await mountHome({ templates: [], templateIssue: "Could not load the list of documents." });
    assert.match(p.container.textContent, /Could not load the list of documents/);
    assert.doesNotMatch(p.container.textContent, /No templates found/);
    await p.unmount();
});

/* ── vault ────────────────────────────────────────────────────────────────── */

const ROWS = [
    { id: "d1", title: "Rent notice", template_type: "legal_notice", review_status: "submitted",
      updated_at: "2026-09-20T10:00:00Z", revision_id: "r1", pdf_sha256: "a".repeat(64), downloadable: true, version: 2 },
    { id: "d2", title: "Affidavit draft", template_type: "affidavit", review_status: "none",
      updated_at: "2026-09-21T10:00:00Z", revision_id: null, downloadable: false, version: 0 },
];

test("the vault lists the client's real documents", async () => {
    api.__respond("myDocumentsV2", { data: { items: ROWS, has_more: false } });
    const p = await mount(DocsVault, { onBack: () => {}, onOpen: () => {} });
    const rows = [...p.container.querySelectorAll("[data-vault-row]")].map(r => r.dataset.vaultRow);
    assert.deepEqual(rows, ["d1", "d2"]);
    assert.match(p.container.textContent, /With lawyer/);
    assert.match(p.container.textContent, /Under Review/);
    const noFile = byLabel(p.container, "This document has not been generated yet.");
    assert.ok(noFile?.disabled, "a document without a file offered a download");
    await p.unmount();
});

test("a vault row previews the real file, with Open (edit) and Download (2026-10-08)", async () => {
    api.__respond("myDocumentsV2", { data: { items: ROWS, has_more: false } });
    api.__respond("previewRevisionV2", { data: { url: "blob:rent-notice" } });
    const edited = [];
    const p = await mount(DocsVault, { onBack: () => {}, onEdit: id => edited.push(id) });
    await click(byLabel(p.container, "Preview Rent notice"));
    const preview = p.container.querySelector("[data-vault-preview]");
    assert.ok(preview, "the preview did not open");
    assert.equal(p.container.querySelector("[data-vault-row]"), null, "the list gives way to the preview");
    // The exact revision the row names, by its id and hash.
    const [call] = api.__calls("previewRevisionV2");
    assert.equal(call.args[0], "d1");
    assert.equal(call.args[1], ROWS[0].revision_id);
    assert.equal(call.args[2].expectedPdfSha256, ROWS[0].pdf_sha256);
    assert.equal(preview.querySelector("[data-preview-title]").textContent, "Rent notice");
    assert.match(preview.querySelector("[data-preview-meta]").textContent, /Legal notice.*PDF/i);
    assert.match(preview.querySelector("[data-preview-frame]").getAttribute("src"), /^blob:rent-notice/);
    // Open edits it in the drafting workspace; Download fetches that revision.
    await click(preview.querySelector("[data-preview-open]"));
    assert.deepEqual(edited, ["d1"]);
    await click(preview.querySelector("[data-preview-download]"));
    assert.equal(api.__calls("downloadDocumentFile").slice(-1)[0].args[0], "d1");
    // Back returns to the list.
    await click(byLabel(p.container, "Back to the Vault"));
    assert.ok(p.container.querySelector("[data-vault-row]"));
    await p.unmount();
});

test("a vault document with no file yet previews as a plain notice, not an empty frame", async () => {
    api.__respond("myDocumentsV2", { data: { items: ROWS, has_more: false } });
    const p = await mount(DocsVault, { onBack: () => {}, onEdit: () => {} });
    await click(byLabel(p.container, "Preview Affidavit draft"));
    const preview = p.container.querySelector("[data-vault-preview]");
    assert.equal(preview.querySelector("[data-preview-frame]"), null);
    assert.match(preview.textContent, /not been generated yet/);
    assert.equal(preview.querySelector("[data-preview-download]").disabled, true);
    assert.equal(api.__calls("previewRevisionV2").length, 0, "nothing to fetch");
    await p.unmount();
});

test("formatSize", async () => {
    const { formatSize } = await import("../src/components/client/documents/VaultPreview.jsx");
    assert.equal(formatSize(491622), "480.10 KB");
    assert.equal(formatSize(3 * 1024 * 1024), "3.00 MB");
    assert.equal(formatSize(0), null);
});

test("an empty vault and a failed load are told apart", async () => {
    api.__respond("myDocumentsV2", { data: { items: [], has_more: false } });
    let p = await mount(DocsVault, { onBack: () => {}, onOpen: () => {} });
    assert.match(p.container.textContent, /Your vault is empty/);
    await p.unmount();

    api.__respond("myDocumentsV2", { data: null, error: { message: "down" } });
    p = await mount(DocsVault, { onBack: () => {}, onOpen: () => {} });
    assert.match(p.container.textContent, /Could not load your documents/);
    assert.doesNotMatch(p.container.textContent, /Your vault is empty/);
    await p.unmount();
});

test("vault helpers", () => {
    assert.equal(accessOf({ review_status: "submitted" }), "With lawyer");
    // A reviewer keeps read access to the version they decided (2026-10-09).
    assert.equal(accessOf({ review_status: "approved" }), "Lawyer reviewed");
    assert.equal(accessOf({ review_status: "returned" }), "Lawyer reviewed");
    assert.equal(accessOf({ review_status: "none" }), "Private");
    assert.equal(formatWhen(null), "—");
    assert.equal(formatWhen("not a date"), "—");
    assert.equal(formatWhen(new Date().toISOString()), "Today");
});

/* ── drafts (not connected) ───────────────────────────────────────────────── */

test("a seeded prompt opens the server plan, never a sample legal document", async () => {
    api.__respond("myDocumentsV2", { data: { items: [], has_more: false } });
    api.__respond("createDraftPlanV2", { data: {
        id: "p1", version: 0, status: "needs_details", title: "NDA draft",
        prompt: "An NDA for a designer", template_type: "nda",
        extraction_status: "ok", fields: { party_a: "ABC Ltd" },
        questions: [{ field: "purpose", question: "Please provide the purpose.", options: [] }],
    } });
    const p = await mount(DocsDrafts, { seed: { prompt: "An NDA for a designer", templateType: "nda" }, templates: TEMPLATES, onBack: () => {}, onOpenView: () => {} });
    assert.ok(p.container.querySelector("[data-draft-plan]"));
    assert.match(p.container.textContent, /Complete document/);
    assert.match(p.container.textContent, /full document is generated after you confirm/);
    assert.match(p.container.textContent, /ABC Ltd/);
    assert.doesNotMatch(p.container.textContent, /Required clauses present|Citations verified|Sample draft/);
    assert.equal(api.__calls("createDraftPlanV2").length, 1);
    await p.unmount();
});

test("drafts history lists the client's real documents and opens them", async () => {
    api.__respond("myDocumentsV2", { data: { items: ROWS, has_more: false } });
    api.__respond("getDocumentWorkspaceV2", { data: {
        document_id: "d1", title: "Rent notice", source: "structured_fields",
        template_type: "legal_notice", fields: { notice_body: "Pay rent" }, body_html: null,
        base_revision_id: "r1", base_version: 2, content_epoch: 0, review_status: "submitted",
    } });
    api.__respond("getDocumentV2", { data: {
        id: "d1", title: "Rent notice", review_status: "submitted", current_version: 2,
        current_revision: { revision_id: "r1", pdf_sha256: "a".repeat(64),
            compliance: { checked: false }, verification: { ran: true, counts: { total: 0 } } } } });
    api.__respond("previewRevisionV2", { data: null, error: { message: "preview unavailable in test" } });
    const p = await mount(DocsDrafts, { seed: null, templates: TEMPLATES, cases: [{ _id: "case-1", title: "A matter" }],
        onBack: () => {}, onOpenView: () => {}, onOpenDocument: () => {} });
    const row = p.container.querySelector('[data-doc="d1"]');
    assert.ok(row, "a real document is missing from History");
    assert.match(row.textContent, /Under Review/);
    assert.doesNotMatch(p.container.textContent, /2 drafts/);
    // The start screen: type, linked case and the prompt, as in the design.
    const caseSelect = p.container.querySelector("#docs-dcase");
    assert.ok([...caseSelect.options].some(o => o.textContent === "Standalone"));
    // The centre is the same prompt card as the Documents home.
    assert.match(p.container.textContent, /What do you need to draft\?/);
    assert.doesNotMatch(p.container.textContent, /Draft your first document/);
    await click(row);
    assert.ok(p.container.querySelector("[data-document-workspace]"));
    assert.match(p.container.textContent, /Frozen for lawyer review/);
    // Frozen: the details panel cannot be opened for editing, and nothing saves.
    assert.equal(p.container.querySelector("[data-placeholders-toggle]").disabled, true);
    assert.equal(p.container.querySelector("[data-save]").disabled, true);
    await p.unmount();
});

test("the AI drafting history column collapses and returns like the analyzer sidebar", async () => {
    api.__respond("myDocumentsV2", { data: { items: [], has_more: false } });
    const p = await mount(DocsDrafts, { seed: null, templates: TEMPLATES, cases: [], onBack: () => {}, onOpenView: () => {} });
    assert.ok(p.container.querySelector('[aria-label="Draft history"]'));
    await click(byLabel(p.container, "Hide history"));
    assert.equal(p.container.querySelector('[aria-label="Draft history"]'), null);
    await click(byLabel(p.container, "Show history"));
    assert.ok(p.container.querySelector('[aria-label="Draft history"]'));
    await p.unmount();
});

test("planning from the drafts prompt card starts a draft with that description", async () => {
    api.__respond("myDocumentsV2", { data: { items: [], has_more: false } });
    api.__respond("createDraftPlanV2", ({ prompt, templateType }) => ({ data: {
        id: "p2", version: 0, status: "ready", title: "Affidavit draft",
        prompt, template_type: templateType, extraction_status: "ok",
        fields: { deponent_name: "Ali" }, questions: [],
    } }));
    const p = await mount(DocsDrafts, { seed: null, templates: TEMPLATES, cases: [], onBack: () => {}, onOpenView: () => {} });
    await click(buttons(p.container, "Affidavit")[0]);
    await click(buttons(p.container, "Plan my draft")[0]);
    assert.ok(p.container.querySelector("[data-draft-plan]"), "no server plan was opened");
    // The editor layout (2026-10-07): the history column stays beside the plan.
    assert.ok(p.container.querySelector('[aria-label="Draft history"]'), "the plan lost its history column");
    assert.match(api.__calls("createDraftPlanV2")[0].args[0].prompt, /Affidavit/i);
    await p.unmount();
});

test("a confirmed plan generates and opens its real document workspace", async () => {
    api.__respond("myDocumentsV2", { data: { items: [], has_more: false } });
    api.__respond("createDraftPlanV2", { data: {
        id: "p3", version: 0, status: "ready", title: "Legal notice draft",
        prompt: "Demand unpaid fees", template_type: "legal_notice",
        extraction_status: "ok", fields: { sender_name: "Ayesha", demand: "Pay Rs 50,000" },
        questions: [],
    } });
    api.__respond("confirmDraftPlanV2", { data: {
        id: "p3", version: 1, status: "confirmed", title: "Legal notice draft",
        prompt: "Demand unpaid fees", template_type: "legal_notice",
        extraction_status: "ok", fields: { sender_name: "Ayesha", demand: "Pay Rs 50,000" },
        questions: [],
    } });
    api.__respond("generateDraftPlanV2", { data: {
        id: "p3", version: 2, status: "generated", generation: { document_id: "d3" },
    } });
    api.__respond("getDocumentWorkspaceV2", { data: {
        document_id: "d3", title: "Legal notice draft", source: "structured_fields",
        template_type: "legal_notice", fields: { sender_name: "Ayesha", demand: "Pay Rs 50,000" },
        body_html: null, base_revision_id: "r3", base_version: 1,
        content_epoch: 0, review_status: "none",
    } });
    api.__respond("getDocumentV2", { data: {
        id: "d3", title: "Legal notice draft", review_status: "none", current_version: 1,
        current_revision: { revision_id: "r3", pdf_sha256: "b".repeat(64),
            compliance: { checked: false }, verification: { ran: false } },
    } });
    api.__respond("previewRevisionV2", { data: null, error: { message: "preview unavailable in test" } });

    const p = await mount(DocsDrafts, {
        seed: null, templates: TEMPLATES, cases: [], onBack: () => {},
        onOpenView: () => {}, onOpenDocument: () => {},
    });
    await type(p.container.querySelector("#docs-need"), "Demand unpaid fees");
    await click(buttons(p.container, "Plan my draft")[0]);
    await click(buttons(p.container, "Confirm plan")[0]);
    await click(buttons(p.container, "Generate document")[0]);

    assert.ok(p.container.querySelector("[data-document-workspace]"));
    assert.match(p.container.textContent, /Legal notice draft/);
    assert.equal(api.__calls("confirmDraftPlanV2")[0].args[1].expectedVersion, 0);
    assert.equal(api.__calls("generateDraftPlanV2")[0].args[1].expectedVersion, 1);
    assert.equal(api.__calls("getDocumentWorkspaceV2")[0].args[0], "d3");
    // The details panel opens from the toolbar (2026-10-08 layout).
    await click(p.container.querySelector("[data-placeholders-toggle]"));
    assert.ok(p.container.querySelector('[aria-label="Complete document"]'));
    assert.equal(p.container.querySelector("#ph_sender_name").disabled, false, "the details are editable");
    await p.unmount();
});

test("placeholderCounts", () => {
    const keys = ["party_a", "party_b"];
    assert.deepEqual(placeholderCounts({}, {}, keys), { total: 2, filled: 0, applied: 0, remaining: 2 });
    assert.deepEqual(placeholderCounts({ party_a: " x " }, { party_a: "x" }, keys), { total: 2, filled: 1, applied: 1, remaining: 1 });
});

/* ── analyzer: a fictional demonstration (plan P-1) ─────────────────────── */

test("the analyzer offers no way to hand over a real file", async () => {
    const p = await mount(DocsAnalyzer, { onBack: () => {} });
    assert.equal(p.container.querySelector('input[type="file"]'), null, "a file picker is on screen");
    assert.match(p.container.textContent, /Real document upload is not available yet\./);
    // A drop must not navigate the tab to the file, and must say it was not read.
    const zone = p.container.querySelector("[data-upload-unavailable]");
    const drop = new dom.window.Event("drop", { bubbles: true, cancelable: true });
    await act(async () => { zone.dispatchEvent(drop); });
    assert.equal(drop.defaultPrevented, true, "a dropped file would open in the tab");
    assert.ok(toasts.some(m => /your file was not read/.test(m)), "the user was not told their file was not read");
    assert.equal(buttons(p.container, "Open fictional analysis")[0].disabled, true, "something other than the sample is ready");
    await p.unmount();
});

test("the sample is labelled as fictional once loaded", async () => {
    const p = await mount(DocsAnalyzer, { onBack: () => {}, userName: "Test User" });
    const analyze = buttons(p.container, "Open fictional analysis")[0];
    assert.equal(analyze.disabled, true, "Analyze must wait for the sample");
    await click(buttons(p.container, "Use the fictional sample rent agreement")[0]);
    assert.match(p.container.textContent, /\(fictional sample\)/);
    assert.equal(buttons(p.container, "Open fictional analysis")[0].disabled, false);
    await p.unmount();
});

test("the start screen greets the user and explains what exists", async () => {
    const { greetingFor } = await import("../src/components/analyzer/AnalyzerWorkspace.jsx");
    const p = await mount(DocsAnalyzer, { onBack: () => {}, userName: "Test User" });
    assert.match(p.container.textContent, /Good (Morning|Afternoon|Evening), Test!/);
    assert.match(p.container.textContent, /Document review/);
    assert.match(p.container.textContent, /Open the sample review/);
    assert.ok(p.container.querySelector('[aria-label="Analysis history"]'));
    await p.unmount();
    assert.equal(greetingFor(new Date(2026, 0, 1, 9)).text, "Good Morning");
    assert.equal(greetingFor(new Date(2026, 0, 1, 14)).text, "Good Afternoon");
    assert.equal(greetingFor(new Date(2026, 0, 1, 21)).night, true);
    // Each time of day has its own line, as in the reference design.
    assert.equal(greetingFor(new Date(2026, 0, 1, 14)).sub, "See how a document review will look.");
    assert.equal(greetingFor(new Date(2026, 0, 1, 14)).icon, "cloud");
    assert.equal(greetingFor(new Date(2026, 0, 1, 21)).sub, "Take a look at a fictional document review.");
    assert.equal(greetingFor(new Date(2026, 0, 1, 9)).sub, "Explore a fictional document review.");
});
test("the editor opens in its light teal look", async () => {
    const { EDITOR_LIGHT } = await import("../src/components/client/documents/TemplateEditor.jsx");
    const p = await mountHome();
    await click(byLabel(p.container, "Edit Legal Notice"));
    const dialog = document.querySelector('[aria-label="Customize template"]');
    // jsdom normalises colours to rgb(); compare against the palette's surface.
    const probe = document.createElement("div");
    probe.style.background = EDITOR_LIGHT.surface;
    assert.equal(dialog.style.background, probe.style.background, "the editor is not on its light surface");
    await p.unmount();
});

/* ── analysis dashboard (fictional sample) ────────────────────────────────── */

const DASHBOARD_PROPS = { sample: "Shop rent agreement", side: "Tenant", depth: "deep",
    onDepth: () => {}, onBack: () => {}, onReanalyze: () => {} };

test("the analysis dashboard has a tab per finding, with counts", async () => {
    const { AnalysisDashboard } = await import("../src/components/analyzer/AnalyzerWorkspace.jsx");
    const depth = [];
    const p = await mount(AnalysisDashboard, { ...DASHBOARD_PROPS, onDepth: k => depth.push(k) });
    const tabs = [...p.container.querySelectorAll('[role="tab"]')].map(b => b.textContent.trim());
    assert.deepEqual(tabs, ["Summary", "Key Clauses3", "Risks4", "Obligations4", "Illustrative checks4", "Document"]);
    assert.match(p.container.textContent, /Aggregated Dashboard/);
    assert.match(p.container.textContent, /Aggregated Executive Summary/);
    assert.match(p.container.textContent, /\d+ high\/critical/);
    assert.match(p.container.textContent, /\(fictional sample\)/, "the dashboard must say whose analysis this is");
    await click(buttons(p.container, "Quick scan")[0]);
    assert.deepEqual(depth, ["quick"]);
    await p.unmount();
});

test("a finding opens its clause on the Document tab", async () => {
    const { AnalysisDashboard } = await import("../src/components/analyzer/AnalyzerWorkspace.jsx");
    const p = await mount(AnalysisDashboard, DASHBOARD_PROPS);
    await click([...p.container.querySelectorAll('[role="tab"]')].find(b => b.textContent.trim().startsWith("Risks")));
    await click(buttons(p.container, "View in document")[0]);
    const selected = [...p.container.querySelectorAll('[role="tab"]')].find(b => b.getAttribute("aria-selected") === "true");
    assert.equal(selected.textContent.trim(), "Document");
    assert.match(p.container.querySelector("article").textContent, /TENANCY AGREEMENT/);
    await p.unmount();
});

test("the sample in History opens its dashboard in one click", async () => {
    const p = await mount(DocsAnalyzer, { onBack: () => {} });
    await click(p.container.querySelector("[data-history-sample]"));
    assert.match(p.container.textContent, /Aggregated Dashboard/);
    assert.match(p.container.textContent, /\(fictional sample\)/);
    await p.unmount();
});

/* ── P-1 honesty: nothing on any analyzer view claims more than exists ───── *
 *
 * Every view of the sample is collected -- the start screen (empty + loaded),
 * the animated reading view with each of its tabs, and the dashboard with each
 * of its tabs -- and each must carry the banner (result views) and none of the
 * forbidden claims or controls. Both layouts are mounted because each had its
 * own Ask box and its own dead actions. */

const FORBIDDEN_TEXT = [
    [/verified/i, "a legal source is called verified"],
    [/missing/i, "an absence is asserted (the real analyzer says 'not located')"],
    [/never used for training|private to you/i, "an unbacked privacy promise"],
    [/one click/i, "a one-click lawyer promise"],
    [/Precedents?/, "a Precedents surface"],
    [/Ask (AI|about)/i, "an Ask surface"],
    [/\.DOC\b|\bDOC\b|photo|50 ?MB/i, "an advertised upload capability"],
    [/Governing law detected/i, "a detected-law claim"],
    [/Job offer letter|Freelancer NDA/, "a sample that cannot run"],
    [/Analyze Document|insights from your file|review your documents|dig into the file/i, "a promise to analyse the user's own file"],
];
const FORBIDDEN_CONTROLS = ["Fix in a new draft", "Send to lawyer", "Resources", "Add Resource",
    "Select Files", "Ask", "Send question", "Precedents", "اردو"];

function assertHonest(container, where) {
    const text = container.textContent;
    for (const [re, why] of FORBIDDEN_TEXT) {
        assert.doesNotMatch(text, re, `${where}: ${why}`);
    }
    const labels = [...container.querySelectorAll("button, [role=tab]")]
        .map(b => (b.getAttribute("aria-label") || b.textContent || "").trim());
    for (const name of FORBIDDEN_CONTROLS) {
        assert.ok(!labels.some(l => l === name || l.startsWith(name + " ") || l === `${name}0`),
            `${where}: dead control "${name}" is back`);
    }
    assert.equal(container.querySelector('input[type="file"]'), null, `${where}: a file picker is back`);
    assert.equal(container.querySelector("textarea"), null, `${where}: an input that goes nowhere is back`);
}

const hasBanner = el => {
    const b = el.querySelector("[data-fictional-banner]");
    return Boolean(b && /Fictional demonstration — no uploaded document was analysed\./.test(b.textContent));
};

async function visitTabs(p, where) {
    const names = [...p.container.querySelectorAll('[role="tab"]')].map(b => b.textContent.trim());
    assert.ok(names.length > 1, `${where}: no tabs to visit`);
    for (const name of names) {
        await click([...p.container.querySelectorAll('[role="tab"]')].find(b => b.textContent.trim() === name));
        assertHonest(p.container, `${where} / ${name}`);
        assert.ok(hasBanner(p.container), `${where} / ${name}: the fictional banner is missing from a result view`);
    }
}

test("P-1: the start screen, empty and with the sample loaded, is honest", async () => {
    const p = await mount(DocsAnalyzer, { onBack: () => {}, userName: "Test User" });
    assertHonest(p.container, "start screen");
    assert.ok(hasBanner(p.container));
    await click(buttons(p.container, "Use the fictional sample rent agreement")[0]);
    assertHonest(p.container, "start screen (sample loaded)");
    await p.unmount();
});

test("P-1: the reading view carries the banner and no dead actions, on every tab", async () => {
    const p = await mount(DocsAnalyzer, { onBack: () => {} });
    await click(buttons(p.container, "Use the fictional sample rent agreement")[0]);
    await click(buttons(p.container, "Open fictional analysis")[0]);
    assert.match(p.container.textContent, /Reading the fictional sample/, "the reading view did not open");
    await visitTabs(p, "reading view");
    await p.unmount();
});

test("P-1: the dashboard carries the banner and no invented claims, on every tab", async () => {
    const { AnalysisDashboard } = await import("../src/components/analyzer/AnalyzerWorkspace.jsx");
    const p = await mount(AnalysisDashboard, DASHBOARD_PROPS);
    await visitTabs(p, "dashboard");
    // Sources are marked as not checked (they show on Summary, Risks and Checks).
    await click([...p.container.querySelectorAll('[role="tab"]')].find(b => b.textContent.trim() === "Summary"));
    assert.match(p.container.textContent, /Illustrative only — legal source not checked\./);
    await p.unmount();
});

test("P-1: the sample's legal source lines are all illustrative", async () => {
    const { readFileSync } = await import("node:fs");
    const src = readFileSync(new URL("../src/components/analyzer/AnalyzerWorkspace.jsx", import.meta.url), "utf8");
    // Every `cite:` and every `law:` is the illustrative marker (or null).
    const cites = [...src.matchAll(/\b(cite|law):\s*([^,}]+)/g)].map(m => m[2].trim());
    assert.ok(cites.length >= 6, "the sample's sources were not found");
    for (const c of cites) assert.ok(c === "ILLUSTRATIVE" || c === "null", `a real-looking source slipped in: ${c}`);
    assert.doesNotMatch(src, /color:\s*t\.success\s*}}>\{(r\.cite|c\.law)\}/, "a source line is styled as a success");
});

test("the analyzer history column collapses and comes back", async () => {
    const p = await mount(DocsAnalyzer, { onBack: () => {} });
    assert.ok(p.container.querySelector('[aria-label="Analysis history"]'));
    await click(byLabel(p.container, "Hide history"));
    assert.equal(p.container.querySelector('[aria-label="Analysis history"]'), null);
    await click(byLabel(p.container, "Show history"));
    assert.ok(p.container.querySelector("[data-history-sample]"), "history did not come back with its sample");
    await click(buttons(p.container, "Samples")[0]);
    assert.equal(p.container.querySelector("[data-history-sample]"), null, "the group did not fold");
    await p.unmount();
});

test("the history menu deletes the history after confirming, and it can be restored", async () => {
    dom.window.localStorage.removeItem("attorney.analyzer.historyCleared");
    const realConfirm = dom.window.confirm;
    try {
        const p = await mount(DocsAnalyzer, { onBack: () => {} });
        await click(byLabel(p.container, "History options"));
        const menu = p.container.querySelector('[role="menu"]');
        assert.ok(menu, "the options menu did not open");

        // Cancelled: nothing is deleted.
        dom.window.confirm = () => false;
        await click(buttons(menu, "Delete")[0]);
        assert.ok(p.container.querySelector("[data-history-sample]"), "deleted without confirmation");

        // Confirmed: the list empties, and stays empty on the next visit.
        await click(byLabel(p.container, "History options"));
        dom.window.confirm = () => true;
        await click(buttons(p.container.querySelector('[role="menu"]'), "Delete")[0]);
        assert.equal(p.container.querySelector("[data-history-sample]"), null);
        assert.ok(p.container.querySelector("[data-history-empty]"));
        assert.equal(dom.window.localStorage.getItem("attorney.analyzer.historyCleared"), "1");

        await click(buttons(p.container, "Restore sample")[0]);
        assert.ok(p.container.querySelector("[data-history-sample]"), "restore did not bring the sample back");
        await p.unmount();
    } finally {
        dom.window.confirm = realConfirm;
        dom.window.localStorage.removeItem("attorney.analyzer.historyCleared");
    }
});

test("the vault header, stats and sort follow the reference layout", async () => {
    const { addedThisWeek, sortRows } = await import("../src/components/client/documents/DocsVault.jsx");
    const now = new Date("2026-09-29T12:00:00Z");
    assert.equal(addedThisWeek([{ created_at: "2026-09-28T10:00:00Z" }, { created_at: "2026-09-01T10:00:00Z" }, {}], now), 1);
    const rows = [
        { id: "a", title: "Beta", updated_at: "2026-09-20T00:00:00Z" },
        { id: "b", title: "alpha", updated_at: "2026-09-25T00:00:00Z" },
    ];
    assert.deepEqual(sortRows(rows, "newest").map(r => r.id), ["b", "a"]);
    assert.deepEqual(sortRows(rows, "oldest").map(r => r.id), ["a", "b"]);
    assert.deepEqual(sortRows(rows, "name").map(r => r.id), ["b", "a"]);

    api.__respond("myDocumentsV2", { data: { items: ROWS, has_more: false } });
    const p = await mount(DocsVault, { onBack: () => {}, onOpen: () => {} });
    assert.match(p.container.textContent, /Upload, organize, done\./);
    assert.match(p.container.textContent, /Manage Your Documents/);
    const stats = [...p.container.querySelectorAll("[data-vault-stat]")].map(s => s.dataset.vaultStat);
    assert.deepEqual(stats, ["Total Documents", "Folders Created", "Storage Used"]);
    assert.match(p.container.querySelector('[data-vault-stat="Total Documents"]').textContent, /2/);
    // Storage is not known to the server: it must not be invented.
    assert.match(p.container.querySelector('[data-vault-stat="Storage Used"]').textContent, /—/);

    await click(byLabel(p.container, "Sort documents"));
    await click(buttons(p.container.querySelector('[role="menu"]'), "Name (A–Z)")[0]);
    const order = [...p.container.querySelectorAll("[data-vault-row]")].map(r => r.dataset.vaultRow);
    assert.deepEqual(order, ["d2", "d1"], "Affidavit draft sorts before Rent notice");
    await p.unmount();
});

test("a template card is balanced: name and facts, no description paragraph (2026-10-08)", async () => {
    const p = await mountHome();
    const card = p.container.querySelector('[data-template="legal_notice"]');
    assert.doesNotMatch(card.textContent, /A formal demand before suing/, "the description is not repeated on the card");
    assert.equal(card.getAttribute("title"), "A formal demand before suing.", "it is the card's tooltip");
    assert.match(card.textContent, /Civil.*Legal Notice.*2 details to fill.*PDF.*Use template/s);
    await p.unmount();
});
