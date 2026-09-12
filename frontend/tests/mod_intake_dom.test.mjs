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

test.after(() => {
    for (const id of liveTimers) { realClearTimeout(id); realClearInterval(id); }
    liveTimers.clear();
    dom.window.close();
});
