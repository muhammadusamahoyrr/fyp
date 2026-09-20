/* ModIntake, mounted. The test that was missing.
 *
 * WHY THIS FILE EXISTS
 *
 * Intake gained ~100 tests across the service layer, the graph, the HTTP
 * contracts and four source-reading frontend files. Two critical defects
 * survived all of them:
 *
 *   the intake token was cleared at CONVERSION while confirmation happened on
 *   the next screen, so a refresh in between started a fresh intake and left
 *   the draft unreachable — and permanently unconfirmable
 *
 *   confirmation scheduled lawyer matching, and the client's category
 *   correction was saved on the screen AFTER it, so matching cached results for
 *   the category they had just rejected
 *
 * Both are ORDERING across a refresh boundary. A service test cannot see the
 * order the browser calls things in; a source-reading test cannot see what a
 * remount restores. Only driving the real component can.
 *
 * So these tests assert on the SEQUENCE of API calls and on what survives a
 * remount, not on rendered markup — markup changes with design, and the
 * ordering is the contract.
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
                    "Element", "Node", "Event", "CustomEvent",
                    "MutationObserver", "getComputedStyle", "localStorage",
                    "requestAnimationFrame", "cancelAnimationFrame", "Blob",
                    "FileReader", "URL"]) {
    define(name, dom.window[name]);
}
define("IS_REACT_ACT_ENVIRONMENT", true);

/* jsdom has no `matchMedia`, and `useIsMobile` calls it on mount (i18n.jsx:53).
 * Stubbed on the window rather than the global because that is where the hook
 * looks. Reports desktop: the intake layout differs by breakpoint and these
 * tests are about call ordering, not layout. */
dom.window.matchMedia = (query) => ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
});

/* Component code uses the GLOBAL timers, which `window.close()` does not
 * release — the process then outlives the runner with every test passing. */
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

const TOKEN = "tok-mounted";
const CASE_ID = "case-mounted";

/* The intake as the server holds it once conversion has happened: completed,
 * with a case that is still a DRAFT awaiting confirmation. */
function convertedIntake(over = {}) {
    return {
        session_token: TOKEN,
        current_step: 5,
        completed: true,
        case_id: CASE_ID,
        case_status: "draft",
        ai_structured_case: {
            summary: "A tenancy arrears claim.",
            applicable_laws: ["PPC Section 302 — example"],
            recommended_actions: ["File a suit"],
            risk_level: "medium",
            grounded: true,
            grounding_status: "grounded",
        },
        steps: {
            1: { province: "punjab", party_role: "plaintiff" },
            2: { case_type: "civil", urgency: "medium" },
            3: { incident_description: "My landlord seized my shop." },
        },
        clarification_qa: [],
        evidence_files: [],
        ...over,
    };
}

async function mountIntake() {
    const { default: ModIntake } =
        await import("../src/components/client/ModIntake.jsx");
    const { CaseProvider } = await import("../src/components/client/CaseContext.jsx");
    const { AuthProvider } = await import("../src/context/AuthContext.jsx");
    const { ToastContainer } = await import("../src/components/shared/Toast.jsx");
    const { DARK } = await import("../src/components/admin/themes.js");
    const { ThemeCtx, HeaderActionsCtx } =
        await import("../src/components/client/theme.js");

    const container = dom.window.document.createElement("div");
    dom.window.document.body.appendChild(container);
    const root = createRoot(container);
    await act(async () => {
        root.render(h(
            AuthProvider, null,
            h(ThemeCtx.Provider, { value: DARK },
              h(HeaderActionsCtx.Provider,
                { value: { setHeaderActions: () => {} } },
                h(ToastContainer, { theme: DARK },
                  h(CaseProvider, null, h(ModIntake)))))));
    });
    await act(async () => { await new Promise(r => setTimeout(r, 40)); });
    return {
        container,
        unmount: async () => {
            await act(async () => { root.unmount(); });
            container.remove();
        },
    };
}

/* The key ModIntake actually reads: user-scoped, per lib/intakeStorage.js. */
const TOKEN_KEY = "aai-intake:u1:aai-intake-token";

function seedToken(value = TOKEN) {
    dom.window.localStorage.setItem(TOKEN_KEY, value);
}

function storedToken() {
    return dom.window.localStorage.getItem(TOKEN_KEY);
}

function reset() {
    api.__reset();
    try { dom.window.localStorage.clear(); } catch { /* ignore */ }
    api.__respond("getMe", { data: { _id: "u1", role: "client", full_name: "C" } });
    api.__respond("bootstrapAuth", { data: { _id: "u1", role: "client" } });
    api.__respond("getNotifications", { data: [] });
    api.__respond("listCases", { data: { items: [] } });
    api.__respond("listAppointments", { data: { items: [] } });
    api.__respond("intakeStart", { data: { session_token: TOKEN } });
    api.__respond("intakeGet", { data: convertedIntake() });
    api.__respond("intakeSaveStep", { data: { current_step: 2 } });
    api.__respond("intakeClarify", { data: { question: null, done: true, round: 0 } });
    api.__respond("intakeConvert", { data: { case_id: CASE_ID, completed: true } });
    api.__respond("confirmCase", { data: { _id: CASE_ID, status: "open" } });
    api.__respond("updateCase", { data: { _id: CASE_ID, status: "open" } });
    // Default: the server has nothing to resume. Tests that care override it.
    api.__respond("getResumableIntake", { data: null });
}

function names() {
    return api.__calls().map(c => c.name);
}

function findButton(container, text) {
    return [...container.querySelectorAll("button")]
        .find(b => (b.textContent || "").includes(text));
}

async function click(el) {
    await act(async () => {
        el.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true }));
    });
    await act(async () => { await new Promise(r => setTimeout(r, 30)); });
}

async function confirmFinalCategory(container) {
    await click(findButton(container, "Continue to Category"));
    const complete = findButton(container, "Confirm Category & Open Case");
    assert.ok(complete, "the final category confirmation screen did not open");
    await click(complete);
}

// ── #1: the draft must stay reachable across a refresh ─────────────────────

test("the intake token survives conversion, so a refresh can still reach the draft", async () => {
    reset();
    seedToken();
    const { unmount } = await mountIntake();

    // Resuming a CONVERTED intake whose case is still a draft — the state a
    // refresh on the review screen lands in. The token must still be stored: it
    // is the only route back to an unconfirmed draft.
    assert.ok(storedToken() === TOKEN,
        "the intake token was cleared before confirmation — a refresh here "
        + "starts a new intake and the draft becomes unconfirmable for ever");
    await unmount();
});

test("a remount after conversion resumes the intake rather than starting a new one", async () => {
    reset();
    seedToken();
    const first = await mountIntake();
    await first.unmount();

    // Re-stub everything EXCEPT localStorage: the point is that the browser
    // still holds the token across the remount. Auth included — without it
    // `user` is null and the resume effect returns before it can run.
    api.__reset();
    api.__respond("bootstrapAuth", { data: { _id: "u1", role: "client" } });
    api.__respond("getMe", { data: { _id: "u1", role: "client" } });
    api.__respond("getNotifications", { data: [] });
    api.__respond("listCases", { data: { items: [] } });
    api.__respond("listAppointments", { data: { items: [] } });
    api.__respond("intakeGet", { data: convertedIntake() });
    api.__respond("intakeStart", { data: { session_token: "tok-SHOULD-NOT-HAPPEN" } });

    const second = await mountIntake();

    assert.equal(api.__calls("intakeStart").length, 0,
        "the refresh minted a NEW intake, abandoning the draft");
    assert.ok(api.__calls("intakeGet").length >= 1,
        "the refresh did not resume the existing intake");
    await second.unmount();
});

test("the token is cleared only once the case is confirmed", async () => {
    reset();
    seedToken();
    const { container, unmount } = await mountIntake();

    await confirmFinalCategory(container);

    assert.equal(api.__calls("confirmCase").length, 1,
        "the confirm button did not call the server");

    assert.equal(storedToken(), null, "the token outlived the completed intake");
    await unmount();
});

test("OCR text must be reviewed and confirmed before analysis can continue", async () => {
    reset();
    seedToken();
    const paused = convertedIntake({
        completed: false,
        case_id: null,
        case_status: null,
        ai_structured_case: null,
        ocr_review_required: true,
        evidence_files: [{
            file_id: "file-ocr",
            filename: "notice-scan.pdf",
            content_type: "application/pdf",
            ocr_review_required: true,
        }],
    });
    api.__respond("intakeGet", { data: paused });
    api.__respond("getIntakeOcrReview", { data: [{
        revision_id: "rev-1",
        file_id: "file-ocr",
        page_number: 1,
        source_sha256: "a".repeat(64),
        text_sha256: "b".repeat(64),
        text: "The flne is 1000 rupees",
        confirmed: false,
        review_state: "pending_confirmation",
    }] });
    api.__respond("confirmIntakeOcrPage", { data: {
        revision_id: "rev-1", confirmed: true,
    } });
    api.__respond("intakeConvert", { data: {
        case_id: CASE_ID, completed: true, ai_case_type: "civil",
    } });

    const mounted = await mountIntake();
    assert.match(mounted.container.textContent, /Review Extracted Text/);
    const editor = mounted.container.querySelector(
        'textarea[aria-label="Extracted text page 1"]');
    assert.ok(editor, "the OCR page text is not visible for review");
    assert.equal(editor.value, "The flne is 1000 rupees");

    const continueButton = findButton(mounted.container, "Continue analysis");
    assert.equal(continueButton.disabled, true,
        "analysis can continue before the OCR page is confirmed");
    await click(findButton(mounted.container, "Confirm this page"));
    assert.equal(api.__calls("confirmIntakeOcrPage").length, 1);
    assert.equal(continueButton.disabled, false);

    await click(continueButton);
    assert.equal(api.__calls("intakeConvert").length, 1,
        "confirmation did not resume the paused conversion");
    await mounted.unmount();
});

test("a failed OCR-review load has a visible retry and does not strand the intake", async () => {
    reset();
    seedToken();
    api.__respond("intakeGet", { data: convertedIntake({
        completed: false,
        case_id: null,
        case_status: null,
        ai_structured_case: null,
        ocr_review_required: true,
        evidence_files: [{
            file_id: "file-ocr", filename: "notice-scan.pdf",
            content_type: "application/pdf", ocr_review_required: true,
        }],
    }) });
    let attempts = 0;
    api.__respond("getIntakeOcrReview", () => {
        attempts += 1;
        if (attempts === 1) return { error: { message: "temporarily offline" } };
        return { data: [{
            revision_id: "rev-retry", file_id: "file-ocr", page_number: 1,
            source_sha256: "a".repeat(64), text_sha256: "b".repeat(64),
            text: "Recovered extracted text", confirmed: false,
        }] };
    });

    const mounted = await mountIntake();
    const retry = findButton(mounted.container, "Try loading again");
    assert.ok(retry, "a transient review failure left no recovery control");
    assert.equal(findButton(mounted.container, "Continue analysis").disabled, true);

    await click(retry);
    assert.equal(api.__calls("getIntakeOcrReview").length, 2);
    assert.ok(mounted.container.querySelector(
        'textarea[aria-label="Extracted text page 1"]'));
    await mounted.unmount();
});

test("one loaded OCR file cannot hide a missing second file", async () => {
    reset();
    seedToken();
    api.__respond("intakeGet", { data: convertedIntake({
        completed: false,
        case_id: null,
        case_status: null,
        ai_structured_case: null,
        ocr_review_required: true,
        evidence_files: ["file-a", "file-b"].map(file_id => ({
            file_id, filename: `${file_id}.pdf`,
            content_type: "application/pdf", ocr_review_required: true,
        })),
    }) });
    api.__respond("getIntakeOcrReview", (_token, fileId) => ({
        data: fileId === "file-a" ? [{
            revision_id: "rev-a", file_id: "file-a", page_number: 1,
            source_sha256: "a".repeat(64), text_sha256: "b".repeat(64),
            text: "Only the first file loaded", confirmed: true,
        }] : [],
    }));

    const mounted = await mountIntake();
    assert.match(
        mounted.container.textContent,
        /one or more extracted files has no current review pages/i,
    );
    assert.equal(findButton(mounted.container, "Continue analysis").disabled, true);
    assert.equal(
        mounted.container.querySelectorAll('[aria-label^="Extracted text page"]').length,
        0,
        "a partial response was rendered as if the review set were complete",
    );
    await mounted.unmount();
});

// ── #2: the category must be saved before matching is triggered ────────────

test("confirmation calls the server exactly once per press", async () => {
    reset();
    seedToken();
    const { container, unmount } = await mountIntake();

    await confirmFinalCategory(container);
    assert.equal(api.__calls("confirmCase").length, 1);
    assert.equal(api.__calls("confirmCase")[0].args[1], "civil",
        "the authoritative category was not part of the opening transition");
    await unmount();
});

test("a restored authoritative category is what confirmation submits", async () => {
    reset();
    seedToken();
    api.__respond("intakeGet", {
        data: convertedIntake({ case_type: "criminal", ai_case_type: "criminal" }),
    });
    const { container, unmount } = await mountIntake();
    await confirmFinalCategory(container);
    assert.equal(api.__calls("confirmCase")[0].args[1], "criminal");
    await unmount();
});

test("a failed confirmation does not advance or clear the token", async () => {
    reset();
    seedToken();
    api.__respond("confirmCase", { error: { message: "server said no" } });
    const { container, unmount } = await mountIntake();

    await confirmFinalCategory(container);

    assert.equal(storedToken(), TOKEN,
        "the token was cleared even though the case is still a draft");
    // Still on the category screen, so the same final action can be retried.
    assert.ok(findButton(container, "Confirm Category & Open Case"));
    await unmount();
});

// ── #4: a refresh restores WHERE they were ─────────────────────────────────

test("an unfinished intake resumes past step 1", async () => {
    reset();
    api.__respond("intakeGet", {
        data: convertedIntake({
            completed: false, case_id: null, case_status: null, current_step: 3,
            ai_structured_case: null,
        }),
    });
    seedToken();
    const { container, unmount } = await mountIntake();

    // Step 1 asks for a role. If we resumed correctly we are past it.
    const onStepOne = !!findButton(container, "Plaintiff");
    assert.equal(onStepOne, false,
        "a mid-intake refresh restored the answers but dropped the client back "
        + "to step 1, with no indication of where they had got to");
    await unmount();
});

test("a restored intake refills the description the client typed", async () => {
    reset();
    api.__respond("intakeGet", {
        data: convertedIntake({
            completed: false, case_id: null, case_status: null, current_step: 2,
            ai_structured_case: null,
        }),
    });
    seedToken();
    const { container, unmount } = await mountIntake();

    // Step 2 opens in VOICE mode, so the description textarea is not rendered
    // until the client switches. Clicking through is what a returning client
    // does to see what they had written.
    const textMode = findButton(container, "Text Input");
    assert.ok(textMode, "step 2 did not render an input-mode switch");
    await click(textMode);

    const restored = [...container.querySelectorAll("textarea")]
        .some(t => (t.value || "").includes("My landlord seized my shop"));
    assert.ok(restored, "the client's own description was not restored");
    await unmount();
});

// ── the logout route to the same orphaning ────────────────────────────────

test("with NO stored token the server is asked before a new intake is started", async () => {
    /* Sign-out clears the token. Keeping it until confirmation closed the
     * REFRESH route to an unconfirmable draft and left this one open: log out
     * between converting and confirming and the draft became unreachable for
     * ever, because nothing but that token could find it. */
    reset();
    // localStorage deliberately empty — this is the post-logout state.
    const { unmount } = await mountIntake();

    assert.ok(api.__calls("getResumableIntake").length >= 1,
        "no token, and the server was never asked whether anything is unfinished");
    await unmount();
});

test("a resumable draft is adopted instead of starting fresh", async () => {
    reset();
    api.__respond("getResumableIntake", { data: convertedIntake() });
    const { container, unmount } = await mountIntake();

    assert.equal(api.__calls("intakeStart").length, 0,
        "a fresh intake was minted while a draft was waiting to be confirmed");
    assert.equal(storedToken(), TOKEN, "the resumed token was not stored");
    assert.ok(findButton(container, "Continue to Category"),
        "the resumed draft did not land on the screen that can confirm it");
    await unmount();
});

test("the resumed draft is confirmable — the orphaning is closed", async () => {
    reset();
    api.__respond("getResumableIntake", { data: convertedIntake() });
    const { container, unmount } = await mountIntake();

    await confirmFinalCategory(container);

    const confirmed = api.__calls("confirmCase");
    assert.equal(confirmed.length, 1, "the resumed draft could not be confirmed");
    assert.equal(confirmed[0].args[0], CASE_ID);
    await unmount();
});

test("a fresh intake is started only when the server has nothing", async () => {
    reset();
    api.__respond("getResumableIntake", { data: null });
    const { unmount } = await mountIntake();

    assert.equal(api.__calls("intakeStart").length, 1,
        "a client with nothing unfinished did not get a new intake");
    await unmount();
});

test("a resume failure never creates a duplicate intake", async () => {
    reset();
    api.__respond("getResumableIntake", { error: { message: "offline" } });
    const { container, unmount } = await mountIntake();
    assert.equal(api.__calls("intakeStart").length, 0);
    assert.ok((container.textContent || "").includes("Could not check your saved intake"));
    assert.ok(findButton(container, "Try again"));
    await unmount();
});

test("an unusable stored token falls back to the server rather than dead-ending", async () => {
    /* A token pointing at nothing is exactly when an unfinished intake is most
     * likely to exist — it used to be dropped and replaced with a new session. */
    reset();
    seedToken("tok-STALE");
    api.__respond("intakeGet", { error: { message: "not found" } });
    api.__respond("getResumableIntake", { data: convertedIntake() });

    const { unmount } = await mountIntake();

    assert.ok(api.__calls("getResumableIntake").length >= 1);
    assert.equal(storedToken(), TOKEN, "the stale token was not replaced by the real one");
    await unmount();
});

// ── the call ORDER, which is what both defects were about ─────────────────

test("no lawyer-facing call is made while the case is still a draft", async () => {
    reset();
    seedToken();
    const { unmount } = await mountIntake();

    const lawyerFacing = names().filter(
        n => ["matchLawyers", "requestEngagement", "bookAppointment"].includes(n));
    assert.deepEqual(lawyerFacing, [],
        `an unconfirmed draft reached a lawyer flow: ${lawyerFacing.join(", ")}`);
    await unmount();
});

test("confirmCase is never called without a case id", async () => {
    reset();
    api.__respond("intakeGet", {
        data: convertedIntake({ completed: false, case_id: null, case_status: null }),
    });
    seedToken();
    const { container, unmount } = await mountIntake();

    const confirm = findButton(container, "Continue to Category");
    if (confirm) await click(confirm);

    assert.equal(api.__calls("confirmCase").length, 0,
        "confirmation was attempted for a case that does not exist");
    await unmount();
});

// ── the analysis must disclose what it did not read ────────────────────────
//
// The unit tests for `extractionStatus.js` prove the wording. These prove the
// wiring, which is the half that silently does not happen: a perfectly correct
// label helper that no screen renders discloses nothing at all.

test("a partially read file is disclosed on the screen showing the analysis", async () => {
    reset();
    const intake = convertedIntake({
        evidence_files: [{
            file_id: "f-bundle", filename: "court-bundle.pdf",
            content_type: "application/pdf", size: 84000,
            extraction_status: "partially_read",
            completeness: "partial_or_uncertain",
            pages_total: 5, pages_with_text: 2,
        }],
    });
    intake.ai_structured_case.evidence_extraction = [{
        file_id: "f-bundle", status: "partially_read",
        completeness: "partial_or_uncertain",
        pages_total: 5, pages_with_text: 2,
    }];
    api.__respond("intakeGet", { data: intake });
    seedToken();

    const { container, unmount } = await mountIntake();
    const text = container.textContent || "";

    assert.match(text, /did not see all of your evidence/i,
        "the analysis screen did not disclose the gap");
    assert.match(text, /court-bundle\.pdf/,
        "the client is not told WHICH file was short-read");
    assert.match(text, /3 of 5 pages produced no text/,
        "the client is not told how much was missed");
    await unmount();
});

test("a fully read bundle is not given a warning it does not deserve", async () => {
    reset();
    const intake = convertedIntake({
        evidence_files: [{
            file_id: "f-ok", filename: "typed.pdf",
            content_type: "application/pdf", size: 1200,
            extraction_status: "readable", completeness: "complete",
            pages_total: 2, pages_with_text: 2,
        }],
    });
    intake.ai_structured_case.evidence_extraction = [{
        file_id: "f-ok", status: "readable", completeness: "complete",
        pages_total: 2, pages_with_text: 2,
    }];
    api.__respond("intakeGet", { data: intake });
    seedToken();

    const { container, unmount } = await mountIntake();
    const text = container.textContent || "";

    assert.doesNotMatch(text, /did not see all of your evidence/i);
    assert.match(text, /read in full/i);
    await unmount();
});

test("the disclosure never claims a page was a scan", async () => {
    reset();
    const intake = convertedIntake({
        evidence_files: [{
            file_id: "f-x", filename: "bundle.pdf",
            content_type: "application/pdf",
            extraction_status: "partially_read",
            pages_total: 4, pages_with_text: 1,
        }],
    });
    intake.ai_structured_case.evidence_extraction = [{
        file_id: "f-x", status: "partially_read",
        pages_total: 4, pages_with_text: 1,
    }];
    api.__respond("intakeGet", { data: intake });
    seedToken();

    const { container, unmount } = await mountIntake();
    const disclosure = container.querySelector('[data-testid="evidence-gaps"]');

    assert.ok(disclosure, "no disclosure block rendered");
    const text = (disclosure.textContent || "").toLowerCase();
    assert.ok(!text.includes("scan"), "the UI claimed to detect a scan");
    assert.ok(!text.includes("photo"), "the UI claimed to detect a photo");
    await unmount();
});

// ── mounted: the screen must not announce a success it cannot support ──────

test("a truncated file is never announced as read in full and included", async () => {
    reset();
    const intake = convertedIntake({
        evidence_files: [{
            file_id: "f-trunc", filename: "long-contract.pdf",
            content_type: "application/pdf", size: 90000,
            extraction_status: "readable", completeness: "complete",
            pages_total: 8, pages_with_text: 8, prompt_truncated: true,
        }],
    });
    // Every page was read; the ANALYSIS was shown only the beginning. The
    // optimistic reading of that is the one a client would never question.
    intake.ai_structured_case.evidence_extraction = [{
        file_id: "f-trunc", status: "readable", completeness: "complete",
        pages_total: 8, pages_with_text: 8, truncated: true,
    }];
    api.__respond("intakeGet", { data: intake });
    seedToken();

    const { container, unmount } = await mountIntake();
    const text = container.textContent || "";

    assert.doesNotMatch(text, /were read in full and included in this analysis/,
        "a truncated file produced an all-clear");
    assert.match(text, /did not see all of your evidence/i);
    await unmount();
});

test("a storage-only file survives a restore without becoming an error", async () => {
    reset();
    const intake = convertedIntake({
        evidence_files: [{
            file_id: "f-doc", filename: "affidavit.doc",
            content_type: "application/msword", size: 40000,
            analysis_support: "storage_only",
            notice: "Saved, but legacy Word (.doc) files cannot be read for analysis.",
            extraction_status: "storage_only",
        }],
    });
    intake.ai_structured_case.evidence_extraction = [
        { file_id: "f-doc", status: "storage_only" }];
    api.__respond("intakeGet", { data: intake });
    seedToken();

    const { container, unmount } = await mountIntake();
    const text = container.textContent || "";

    assert.match(text, /Stored, not analysed/i);
    assert.doesNotMatch(text, /Could not be read/i,
        "a perfectly fine file was reported as a failure after a reload");
    await unmount();
});

test("an unknown page count is never rendered as a confident zero", async () => {
    reset();
    const intake = convertedIntake({
        evidence_files: [{
            file_id: "f-unk", filename: "bundle.pdf",
            content_type: "application/pdf",
            extraction_status: "partially_read",
            pages_total: 6, pages_with_text: null,
        }],
    });
    intake.ai_structured_case.evidence_extraction = [{
        file_id: "f-unk", status: "partially_read",
        pages_total: 6, pages_with_text: null,
    }];
    api.__respond("intakeGet", { data: intake });
    seedToken();

    const { container, unmount } = await mountIntake();
    const text = container.textContent || "";

    assert.doesNotMatch(text, /6 of 6 pages produced no text/,
        "an unknown counter was rendered as a definite claim");
    assert.doesNotMatch(text, /NaN/);
    await unmount();
});

test("a genuinely complete analysis may still say so", async () => {
    // The guards must not have made every outcome a warning; a real all-clear
    // that can no longer be given is its own kind of dishonesty.
    reset();
    const intake = convertedIntake({
        evidence_files: [{
            file_id: "f-ok", filename: "typed.pdf",
            content_type: "application/pdf",
            extraction_status: "readable", completeness: "complete",
            pages_total: 2, pages_with_text: 2, prompt_truncated: false,
        }],
    });
    intake.ai_structured_case.evidence_extraction = [{
        file_id: "f-ok", status: "readable", completeness: "complete",
        pages_total: 2, pages_with_text: 2, truncated: false,
    }];
    api.__respond("intakeGet", { data: intake });
    seedToken();

    const { container, unmount } = await mountIntake();
    const text = container.textContent || "";

    assert.match(text, /were read in full and included in this analysis/);
    assert.doesNotMatch(text, /did not see all of your evidence/i);
    await unmount();
});

test.after(() => {
    for (const id of liveTimers) { realClearTimeout(id); realClearInterval(id); }
    liveTimers.clear();
    dom.window.close();
});

// ── the legacy-Urdu-encoding status, as the client actually sees it ─────────
//
// The backend can report that a file HAS a text layer which decodes to nothing
// usable. Before the UI knew that status it fell through to the default arm and
// rendered "Read status unknown" — which tells the client nothing, implies we
// never looked, and offers no remedy. A source-reading test cannot catch that:
// the fall-through only happens once the component is mounted with real data.

const LEGACY_FILE = {
    file_id: "f-urdu",
    filename: "PCS_Act_1974.pdf",
    content_type: "application/pdf",
    size: 204800,
    extraction_status: "unextractable_encoding",
    completeness: "none",
    pages_total: 9,
    pages_with_text: 0,
    pages_text_untrusted: 9,
};

function extractionLine(container, fileId) {
    return container.querySelector(`[data-testid="extraction-${fileId}"]`);
}

/* The evidence list lives on the upload screen, behind "do you have evidence".
   A converted intake lands past it, so these tests restore an UNFINISHED one
   sitting on that step with files already uploaded. */
function intakeOnEvidenceStep(files) {
    const data = convertedIntake({ evidence_files: files });
    return {
        ...data,
        completed: false,
        case_id: null,
        case_status: null,
        current_step: 2,
        steps: { ...data.steps, 4: { has_evidence: true } },
    };
}

test("a legacy-encoding file renders its own status, not 'Read status unknown'", async () => {
    reset();
    seedToken();
    api.__respond("intakeGet", {
        data: intakeOnEvidenceStep([LEGACY_FILE]),
    });
    const { container, unmount } = await mountIntake();

    const line = extractionLine(container, "f-urdu");
    assert.ok(line, "the extraction status line was not rendered at all");
    assert.equal(line.getAttribute("data-state"), "legacy_encoding");
    assert.match(line.textContent, /Unsupported legacy Urdu encoding/);
    assert.doesNotMatch(line.textContent, /Read status unknown/);

    await unmount();
});

test("the mounted UI tells the client what would actually help", async () => {
    reset();
    seedToken();
    api.__respond("intakeGet", {
        data: intakeOnEvidenceStep([LEGACY_FILE]),
    });
    const { container, unmount } = await mountIntake();

    const text = extractionLine(container, "f-urdu").textContent;

    assert.match(text, /typed text or an English translation/);
    // Urdu OCR is unavailable, so a scan would be exactly as unreadable.
    assert.doesNotMatch(text, /scan/i);
    assert.doesNotMatch(text, /photo/i);

    await unmount();
});

test("no raw extracted mojibake reaches the mounted UI", async () => {
    reset();
    seedToken();
    api.__respond("intakeGet", {
        data: intakeOnEvidenceStep([LEGACY_FILE]),
    });
    const { container, unmount } = await mountIntake();

    const body = container.textContent;
    for (const fragment of ["Z}5i]w", "!!!!", "%^&*l1", "}[O5i#w"]) {
        assert.ok(!body.includes(fragment),
            `raw extracted mojibake reached the page: ${fragment}`);
    }

    await unmount();
});

test("a readable file is still shown as read in full", async () => {
    reset();
    seedToken();
    api.__respond("intakeGet", {
        data: intakeOnEvidenceStep([{
            file_id: "f-ok", filename: "notice.pdf",
            content_type: "application/pdf", size: 1024,
            extraction_status: "readable", completeness: "complete",
            pages_total: 2, pages_with_text: 2,
        }]),
    });
    const { container, unmount } = await mountIntake();

    const line = extractionLine(container, "f-ok");
    assert.equal(line.getAttribute("data-state"), "complete");
    assert.match(line.textContent, /Read in full/);

    await unmount();
});
