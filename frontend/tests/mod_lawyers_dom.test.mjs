/* ModLawyers — the real component, mounted.
 *
 * The backend matcher has 83 tests. This file had none, and the defects that
 * mattered most to a user were all on this side of the wire: a fabricated
 * `BAR-API-001` shown as a bar council registration number, "null km" printed
 * as a distance, a "Find Nearby" button with no handler, and a constant
 * "Mon–Fri: 9am–5pm" presented as each lawyer's own office hours. None of those
 * are visible from a backend test, and `next build` proving the file parses is
 * not the same as knowing what it renders.
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
                    "requestAnimationFrame", "cancelAnimationFrame"]) {
    define(name, dom.window[name]);
}
define("IS_REACT_ACT_ENVIRONMENT", true);

/* Component code uses the GLOBAL timers, which `window.close()` does not
 * release — the process then outlives the runner with every test passing.
 * Same tracking as mod_documents_dom. */
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

/* Set a controlled input's value the way a user does.
 *
 * React installs its own `value` setter on the element and tracks the last
 * value it wrote; assigning `el.value` directly updates the DOM but leaves that
 * tracker unchanged, so React treats the following `input` event as a no-op and
 * the component never re-renders. Going through the prototype setter is what
 * makes the change visible to React.
 */
function setNativeValue(el, value) {
    const proto = Object.getPrototypeOf(el);
    const desc = Object.getOwnPropertyDescriptor(proto, "value");
    if (desc && desc.set) desc.set.call(el, value);
    else el.value = value;
}

/* A lawyer as the BACKEND actually returns one: `lawyer_profile` is a
 * pass-through dict, so absent fields are simply absent. The fabrication bugs
 * all lived in what the UI substituted for these. */
function lawyer(id, over = {}) {
    return {
        _id: id,
        full_name: `Adv ${id}`,
        role: "lawyer",
        province: "punjab",
        is_active: true,
        lawyer_profile: {
            specializations: ["criminal"],
            rating: 4.5,
            total_reviews: 5,
            availability: true,
            experience_years: 10,
            ...over,
        },
    };
}

async function mountLawyers() {
    const { default: ModLawyers } =
        await import("../src/components/client/ModLawyers.jsx");
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
                  h(CaseProvider, null, h(ModLawyers)))))));
    });
    await act(async () => { await new Promise(r => setTimeout(r, 30)); });
    return {
        container,
        text: () => container.textContent,
        settle: async (ms = 60) => {
            await act(async () => { await new Promise(r => setTimeout(r, ms)); });
        },
        unmount: async () => { await act(async () => root.unmount()); },
    };
}

/* Click through to a lawyer's profile.
 *
 * Several fields the fabrication bugs lived in — office hours, bar number,
 * reviews — appear ONLY on the profile view, so a list-only assertion about
 * them cannot fail and proves nothing. Finds the lawyer's name and clicks the
 * nearest ancestor carrying a click handler.
 */
async function openProfile(ui) {
    const nameNode = [...ui.container.querySelectorAll("div")]
        .reverse()
        .find(el => /^Adv /.test(el.textContent.trim())
                    && el.children.length === 0);
    assert.ok(nameNode, "no lawyer card was rendered to open");

    let node = nameNode;
    for (let i = 0; i < 8 && node; i++) {
        await act(async () => {
            node.dispatchEvent(new dom.window.MouseEvent(
                "click", { bubbles: true, cancelable: true }));
        });
        await ui.settle(30);
        if (/Working Hours|Bar No:/.test(ui.text())) return;
        node = node.parentElement;
    }
    throw new Error("could not open the lawyer profile view");
}

test.beforeEach(() => {
    api.__reset();
    api.__respond("bootstrapAuth", true);
    api.__respond("getMe", { data: { _id: "u1", role: "client" } });
    api.__respond("listCases", { data: [] });
    api.__respond("listEngagements", { data: [] });
});

test.after(() => {
    for (const id of liveTimers) { realClearInterval(id); realClearTimeout(id); }
    liveTimers.clear();
    dom.window.close();
});

/* ── fabricated data ──────────────────────────────────────────────────────── */

test("a lawyer with no bar number is not given a generated one", async () => {
    // THE defect. `BAR-API-${idx+1}` was displayed as a bar council
    // registration number for a real, KYC-verified advocate — and numbered by
    // position in the page, so the same lawyer's "registration number" changed
    // when the list was re-sorted. Inventing a professional registration is not
    // a display placeholder.
    api.__respond("searchLawyers", { data: { items: [lawyer("L1")] } });
    const ui = await mountLawyers();
    await ui.settle();

    assert.ok(!/BAR-API-/.test(ui.text()),
              "a bar council registration number was fabricated");
    await ui.unmount();
});

test("a real bar number is still shown", async () => {
    api.__respond("searchLawyers",
        { data: { items: [lawyer("L1", { bar_number: "PBC/12345/2019" })] } });
    const ui = await mountLawyers();
    await ui.settle();

    assert.match(ui.text(), /PBC\/12345\/2019/);
    await ui.unmount();
});

test("office hours are not invented on the profile", async () => {
    // Every profile used to claim "Mon–Fri: 9am–5pm" as that lawyer's own
    // schedule. Nothing collects office hours anywhere in the product, and a
    // client could act on it and find a closed office.
    //
    // This MUST open the profile. Office hours are not on the list view at all,
    // so a list-only assertion passes whether or not the bug is present —
    // verified by restoring the bug and watching it still pass. A test that
    // cannot fail is worse than no test.
    api.__respond("searchLawyers", { data: { items: [lawyer("L1")] } });
    const ui = await mountLawyers();
    await ui.settle();
    await openProfile(ui);

    assert.match(ui.text(), /Working Hours/,
                 "the profile view did not open — the assertion below is vacuous");
    assert.ok(!/9am[\s–-]*5pm/.test(ui.text()),
              "a fixed office-hours string was presented as the lawyer's own");
    assert.match(ui.text(), /Not provided/,
                 "an absent field was not labelled unavailable");
    await ui.unmount();
});

test("an absent bar number is labelled on the profile, not filled in", async () => {
    api.__respond("searchLawyers", { data: { items: [lawyer("L1")] } });
    const ui = await mountLawyers();
    await ui.settle();
    await openProfile(ui);

    assert.match(ui.text(), /Bar No:/);
    assert.ok(!/BAR-API-/.test(ui.text()));
    await ui.unmount();
});

test("review text absent is not shown as no reviews", async () => {
    // `reviewList` is null (there is no endpoint for review text) and [] means
    // genuinely none. Collapsing the two would tell a client that a lawyer with
    // five reviews has none.
    api.__respond("searchLawyers",
        { data: { items: [lawyer("L1", { total_reviews: 5, rating: 4.6 })] } });
    const ui = await mountLawyers();
    await ui.settle();
    await openProfile(ui);

    assert.ok(!/No reviews yet/.test(ui.text()),
              "a lawyer with 5 reviews was shown as having none");
    assert.match(ui.text(), /Loading 5 reviews/);
    await ui.unmount();
});

/* ── location honesty ─────────────────────────────────────────────────────── */

test("no distance is rendered, and never the string null", async () => {
    // `distance` was hardcoded null and interpolated straight into the markup,
    // so the page showed "null km" and "nullkm" to users.
    api.__respond("searchLawyers", { data: { items: [lawyer("L1")] } });
    const ui = await mountLawyers();
    await ui.settle();

    const text = ui.text();
    assert.ok(!/null/i.test(text), `"null" leaked into the UI: ${text.slice(0, 200)}`);
    assert.ok(!/\bkm\b/.test(text), "a distance was shown though none is computed");
    await ui.unmount();
});

test("proximity sorting is not offered when no distance exists", async () => {
    // The option compared `null - null` for every pair, returned the list
    // untouched, and presented that as a proximity ranking.
    api.__respond("searchLawyers", { data: { items: [lawyer("L1")] } });
    const ui = await mountLawyers();
    await ui.settle();

    assert.ok(!/Distance: Nearest/.test(ui.text()));
    await ui.unmount();
});

/* ── filters reach the server ─────────────────────────────────────────────── */

test("the directory is fetched on mount", async () => {
    api.__respond("searchLawyers", { data: { items: [lawyer("L1")] } });
    const ui = await mountLawyers();
    await ui.settle();

    assert.ok(api.__calls("searchLawyers").length >= 1,
              "the lawyer directory was never requested");
    await ui.unmount();
});

test("a lawyer returned by the server is rendered", async () => {
    api.__respond("searchLawyers",
        { data: { items: [lawyer("L1"), lawyer("L2")] } });
    const ui = await mountLawyers();
    await ui.settle();

    assert.match(ui.text(), /Adv L1/);
    assert.match(ui.text(), /Adv L2/);
    await ui.unmount();
});

/* ── empty and failed results ─────────────────────────────────────────────── */

test("an empty directory does not crash or invent a lawyer", async () => {
    api.__respond("searchLawyers", { data: { items: [] } });
    const ui = await mountLawyers();
    await ui.settle();

    assert.ok(!/BAR-API-/.test(ui.text()));
    assert.ok(!/Adv /.test(ui.text()), "a lawyer appeared from nowhere");
    await ui.unmount();
});

test("a failed directory fetch does not crash the page", async () => {
    api.__respond("searchLawyers", { data: null, error: { detail: "boom" } });
    const ui = await mountLawyers();
    await ui.settle();

    assert.ok(ui.container.textContent.length > 0, "the page rendered nothing");
    await ui.unmount();
});

test("a malformed payload is tolerated", async () => {
    // The component accepts either a bare array or {items}. Neither shape may
    // throw when the server returns something else entirely.
    api.__respond("searchLawyers", { data: { unexpected: true } });
    const ui = await mountLawyers();
    await ui.settle();

    assert.ok(ui.container.textContent.length > 0);
    await ui.unmount();
});

/* ── reviews now have a read endpoint ─────────────────────────────────────── */

test("loaded reviews are rendered on the profile", async () => {
    // The rating and the count were always reachable; the review TEXT had no
    // read endpoint at all, so a client saw "4.6 (5)" with nothing behind it.
    api.__respond("searchLawyers", { data: { items: [lawyer("L1")] } });
    api.__respond("getLawyerReviews", { data: { items: [
        { id: "r1", stars: 5, comment: "Clear advice, well prepared.",
          created_at: "2026-08-01T00:00:00Z", reviewer: "Muhammad K." },
    ], total: 1, page: 1, page_size: 10, pages: 1 } });

    const ui = await mountLawyers();
    await ui.settle();
    await openProfile(ui);
    await ui.settle();

    assert.match(ui.text(), /Clear advice, well prepared\./);
    assert.match(ui.text(), /Muhammad K\./);
    await ui.unmount();
});

test("a lawyer with genuinely no reviews says so", async () => {
    api.__respond("searchLawyers", { data: { items: [lawyer("L1")] } });
    api.__respond("getLawyerReviews",
        { data: { items: [], total: 0, page: 1, page_size: 10, pages: 0 } });

    const ui = await mountLawyers();
    await ui.settle();
    await openProfile(ui);
    await ui.settle();

    assert.match(ui.text(), /No reviews yet/);
    await ui.unmount();
});

test("a failed review fetch does not claim there are none", async () => {
    // The distinction that matters: "could not load" is not "has none", and
    // saying the latter misrepresents a lawyer whose count says otherwise.
    api.__respond("searchLawyers", { data: { items: [lawyer("L1")] } });
    api.__respond("getLawyerReviews", { data: null, error: { detail: "boom" } });

    const ui = await mountLawyers();
    await ui.settle();
    await openProfile(ui);
    await ui.settle();

    assert.ok(!/No reviews yet/.test(ui.text()),
              "a failed fetch was reported as the lawyer having no reviews");
    await ui.unmount();
});

test("a reviewer is never identified beyond what the API returns", async () => {
    api.__respond("searchLawyers", { data: { items: [lawyer("L1")] } });
    api.__respond("getLawyerReviews", { data: { items: [
        { id: "r1", stars: 4, comment: "Good.", created_at: "2026-08-01T00:00:00Z",
          reviewer: "Ayesha B." },
    ], total: 1, page: 1, page_size: 10, pages: 1 } });

    const ui = await mountLawyers();
    await ui.settle();
    await openProfile(ui);
    await ui.settle();

    assert.match(ui.text(), /Ayesha B\./);
    assert.ok(!/@/.test(ui.text()), "an email address reached the review list");
    await ui.unmount();
});

/* ── directory paging, and the filters that used to be page-local ─────────── */
//
// The page fetched `page_size: 20` and nothing else, then applied the search
// box, the price and experience sliders and all seven sort options IN THE
// BROWSER to those 20 rows. Each answered a question about one page while
// appearing to answer it about the directory, and the 21st lawyer was
// unreachable by any combination of controls.

function pageOf(items, { page = 1, total = 40, pages = 2 } = {}) {
    return { data: { items, total, pages, page, page_size: 20 } };
}

test("the directory reports the total, not just the page size", async () => {
    api.__respond("searchLawyers",
        pageOf([lawyer("L1"), lawyer("L2")], { total: 42, pages: 3 }));
    const ui = await mountLawyers();
    await ui.settle();

    // "Showing 2 of 42 lawyers" — it used to say only "Showing 2 lawyers"
    // whether the directory held 2 or 2000.
    assert.match(ui.text(), /of\s*42\s*lawyers/);
    await ui.unmount();
});

test("pagination controls appear only when there is more than one page", async () => {
    api.__respond("searchLawyers",
        pageOf([lawyer("L1")], { total: 1, pages: 1 }));
    const one = await mountLawyers();
    await one.settle();
    assert.ok(!/Previous/.test(one.text()), "paging offered for a single page");
    await one.unmount();

    api.__reset();
    api.__respond("bootstrapAuth", true);
    api.__respond("getMe", { data: { _id: "u1", role: "client" } });
    api.__respond("listCases", { data: [] });
    api.__respond("listEngagements", { data: [] });
    api.__respond("searchLawyers",
        pageOf([lawyer("L1")], { total: 40, pages: 2 }));
    const many = await mountLawyers();
    await many.settle();
    assert.match(many.text(), /Previous/);
    assert.match(many.text(), /Next/);
    await many.unmount();
});

test("Next asks the server for the following page", async () => {
    // THE defect: lawyers past the first page had no route to the screen.
    api.__respond("searchLawyers",
        pageOf([lawyer("L1")], { total: 40, pages: 2 }));
    const ui = await mountLawyers();
    await ui.settle();

    const next = [...ui.container.querySelectorAll("button")]
        .find(b => /Next/.test(b.textContent));
    assert.ok(next, "no Next control");
    await act(async () => {
        next.dispatchEvent(new dom.window.MouseEvent(
            "click", { bubbles: true, cancelable: true }));
    });
    await ui.settle(400);

    const pages = api.__calls("searchLawyers").map(c => c.args[0]?.page);
    assert.ok(pages.includes(2), `never requested page 2; asked for ${pages}`);
    await ui.unmount();
});

test("the search box is sent to the server, not applied to the page", async () => {
    api.__respond("searchLawyers", pageOf([lawyer("L1")]));
    const ui = await mountLawyers();
    await ui.settle();

    const box = [...ui.container.querySelectorAll("input")]
        .find(i => /search/i.test(i.getAttribute("placeholder") || ""));
    assert.ok(box, "no search input found");
    await act(async () => {
        setNativeValue(box, "Bilal");
        box.dispatchEvent(new dom.window.Event("input", { bubbles: true }));
    });
    await ui.settle(500);

    const sent = api.__calls("searchLawyers").map(c => c.args[0]?.q).filter(Boolean);
    assert.ok(sent.includes("Bilal"),
              `the query never reached the server; sent: ${JSON.stringify(sent)}`);
    await ui.unmount();
});

test("a sort choice is sent as a server sort key", async () => {
    // Sorting a page is not sorting a list: the cheapest lawyer overall is
    // very unlikely to be among the 20 rows the client happens to hold.
    api.__respond("searchLawyers", pageOf([lawyer("L1")]));
    const ui = await mountLawyers();
    await ui.settle();

    const select = [...ui.container.querySelectorAll("select")]
        .find(s => [...s.options].some(o => /Price: Low to High/.test(o.textContent)));
    assert.ok(select, "no sort control found");
    await act(async () => {
        setNativeValue(select, "Price: Low to High");
        select.dispatchEvent(new dom.window.Event("change", { bubbles: true }));
    });
    await ui.settle(500);

    const sorts = api.__calls("searchLawyers").map(c => c.args[0]?.sort);
    assert.ok(sorts.includes("fee_asc"),
              `sort was not sent to the server; sent: ${JSON.stringify(sorts)}`);
    await ui.unmount();
});

test("the first request carries a page and a sort", async () => {
    api.__respond("searchLawyers", pageOf([lawyer("L1")]));
    const ui = await mountLawyers();
    await ui.settle();

    const first = api.__calls("searchLawyers")[0].args[0];
    assert.equal(first.page, 1);
    assert.equal(first.page_size, 20);
    assert.equal(first.sort, "rating_desc");
    // Fee and experience are not filters, so no bound is ever sent for them.
    for (const gone of ["min_fee", "max_fee", "min_experience", "max_experience"]) {
        assert.equal(first[gone], undefined, `${gone} is still being sent`);
    }
    await ui.unmount();
});

test("the server's page is rendered as given, not re-filtered locally", async () => {
    // Re-applying the filters to a server page can only remove rows the server
    // has already decided belong, leaving a short page and a count that
    // disagrees with it.
    api.__respond("searchLawyers", pageOf(
        [lawyer("A1", { experience_years: 1, hourly_rate: 100, rating: 1.0 }),
         lawyer("A2", { experience_years: 40, hourly_rate: 99999, rating: 5.0 })],
        { total: 2, pages: 1 }));
    const ui = await mountLawyers();
    await ui.settle();

    assert.match(ui.text(), /Adv A1/);
    assert.match(ui.text(), /Adv A2/);
    await ui.unmount();
});

test("matching is untouched by the directory changes", async () => {
    // matchLawyers must keep its own call shape.
    api.__respond("searchLawyers", pageOf([lawyer("L1")]));
    const ui = await mountLawyers();
    await ui.settle();
    assert.equal(api.__calls("matchLawyers").length, 0,
                 "the directory fetch triggered a match request");
    await ui.unmount();
});

/* ── directions and location honesty ──────────────────────────────────────── */
//
// `_inject_coords` fills a missing pin with a province centre plus a
// deterministic offset of up to 0.4 degrees — roughly 44 km — and wrote it into
// the same lat/lng fields as a genuinely geocoded address. The UI could not
// tell them apart and offered "Get Directions" for both, so a client could be
// given turn-by-turn navigation to a point this system invented. The address
// fallback was no better: `encodeURIComponent(null)` is the string "null",
// which was being sent to Google Maps as the destination.

function openedUrls() {
    return (globalThis.__opened ||= []);
}

// Stub `dom.window.open`, NOT `globalThis.open`. The component calls
// `window.open(...)`, and `window` here is the jsdom window — so a stub on
// globalThis is never consulted and every maps URL sails past unrecorded,
// leaving the assertions below unable to fail.
Object.defineProperty(dom.window, "open", {
    value: (url) => { openedUrls().push(url); return null; },
    writable: true, configurable: true,
});

test.beforeEach(() => { openedUrls().length = 0; });

test("a lawyer with a real address is offered directions", async () => {
    api.__respond("searchLawyers", { data: { items: [lawyer("L1", {
        address: "12 Mall Road, Lahore", lat: 31.5497, lng: 74.3436,
        location_precision: "exact",
    })] }, total: 1, pages: 1 });
    const ui = await mountLawyers();
    await ui.settle();
    await openProfile(ui);

    assert.match(ui.text(), /Get Directions/);
    await ui.unmount();
});

test("directions navigate to the geocoded point, never to the string null",
     async () => {
    api.__respond("searchLawyers", { data: { items: [lawyer("L1", {
        address: "12 Mall Road, Lahore", lat: 31.5497, lng: 74.3436,
        location_precision: "exact",
    })] }, total: 1, pages: 1 });
    const ui = await mountLawyers();
    await ui.settle();
    await openProfile(ui);

    const btn = [...ui.container.querySelectorAll("button")]
        .find(b => /Get Directions/.test(b.textContent));
    await act(async () => {
        btn.dispatchEvent(new dom.window.MouseEvent(
            "click", { bubbles: true, cancelable: true }));
    });

    const url = openedUrls().at(-1) || "";
    assert.match(url, /destination=31\.5497,74\.3436/);
    assert.ok(!/null/.test(url), `"null" reached a maps URL: ${url}`);
    await ui.unmount();
});

test("an approximate pin is NOT offered directions", async () => {
    // THE defect. This coordinate is a province centre plus an invented offset;
    // routing a client to it would send them up to ~44 km from their lawyer.
    api.__respond("searchLawyers", { data: { items: [lawyer("L1", {
        lat: 31.1704, lng: 72.7097, location_precision: "approximate",
    })] }, total: 1, pages: 1 });
    const ui = await mountLawyers();
    await ui.settle();
    await openProfile(ui);

    assert.ok(!/Get Directions/.test(ui.text()),
              "directions were offered to a fabricated coordinate");
    assert.ok(!/View on Map/.test(ui.text()));
    await ui.unmount();
});

test("an approximate pin explains itself instead", async () => {
    api.__respond("searchLawyers", { data: { items: [lawyer("L1", {
        lat: 31.1704, lng: 72.7097, location_precision: "approximate",
    })] }, total: 1, pages: 1 });
    const ui = await mountLawyers();
    await ui.settle();
    await openProfile(ui);

    assert.match(ui.text(), /has not published an office address/);
    assert.match(ui.text(), /directions are not available/);
    await ui.unmount();
});

test("no maps URL is ever opened for a lawyer without a real address",
     async () => {
    api.__respond("searchLawyers", { data: { items: [lawyer("L1", {
        lat: 31.1704, lng: 72.7097, location_precision: "approximate",
    })] }, total: 1, pages: 1 });
    const ui = await mountLawyers();
    await ui.settle();
    await openProfile(ui);

    for (const b of [...ui.container.querySelectorAll("button")]) {
        await act(async () => {
            b.dispatchEvent(new dom.window.MouseEvent(
                "click", { bubbles: true, cancelable: true }));
        });
    }
    assert.deepEqual(openedUrls().filter(u => /google\.com\/maps/.test(u)), [],
                     "a maps link was opened for an invented location");
    await ui.unmount();
});

test("a missing address is labelled, not rendered blank", async () => {
    api.__respond("searchLawyers", { data: { items: [lawyer("L1", {
        lat: 31.1704, lng: 72.7097, location_precision: "approximate",
    })] }, total: 1, pages: 1 });
    const ui = await mountLawyers();
    await ui.settle();
    await openProfile(ui);

    assert.match(ui.text(), /Not provided/);
    await ui.unmount();
});

test("the map list button is labelled for what it does", async () => {
    // It read "Directions" and opened the profile — it has never navigated.
    api.__respond("searchLawyers", { data: { items: [lawyer("L1")] },
                                     total: 1, pages: 1 });
    const ui = await mountLawyers();
    await ui.settle();

    const src = await import("node:fs");
    const file = src.readFileSync(
        "src/components/client/ModLawyers.jsx", "utf8");
    assert.ok(!/>Directions<\/BtnOutline>/.test(file),
              "a button still says Directions while only opening the profile");
    await ui.unmount();
});

/* ── the demo dataset, end to end ─────────────────────────────────────────── */
//
// Six seeded lawyers carry a real office address with pinned coordinates and
// must offer directions; six carry none and must not. Both halves are asserted
// against the SAME component, using payloads shaped exactly as the seeded rows
// reach the client.

test("a seeded lawyer with a real office offers directions to it", async () => {
    // Kamran Aziz Malik, Jinnah Avenue, Blue Area, Islamabad.
    api.__respond("searchLawyers", { data: { items: [lawyer("L1", {
        address: "Jinnah Avenue, Blue Area, Islamabad",
        lat: 33.723619, lng: 73.081890, location_precision: "exact",
    })] }, total: 1, pages: 1 });
    const ui = await mountLawyers();
    await ui.settle();
    await openProfile(ui);

    assert.match(ui.text(), /Jinnah Avenue, Blue Area, Islamabad/);
    assert.match(ui.text(), /Get Directions/);

    const btn = [...ui.container.querySelectorAll("button")]
        .find(b => /Get Directions/.test(b.textContent));
    await act(async () => {
        btn.dispatchEvent(new dom.window.MouseEvent(
            "click", { bubbles: true, cancelable: true }));
    });

    const url = openedUrls().at(-1) || "";
    assert.match(url, /destination=33\.723619,73\.08189/);
    await ui.unmount();
});

test("a seeded lawyer with no office still cannot generate directions",
     async () => {
    // Rabia Kazmi (sindh) — no address in the roster, so the backend supplies a
    // province-centre pin and marks it approximate. The demo must not relax it.
    api.__respond("searchLawyers", { data: { items: [lawyer("L1", {
        lat: 25.8943, lng: 68.5247, location_precision: "approximate",
    })] }, total: 1, pages: 1 });
    const ui = await mountLawyers();
    await ui.settle();
    await openProfile(ui);

    assert.ok(!/Get Directions/.test(ui.text()));
    assert.match(ui.text(), /directions are not available/);
    await ui.unmount();
});

test("a lawyer with no location at all cannot generate directions", async () => {
    api.__respond("searchLawyers", { data: { items: [lawyer("L1", {
        location_precision: "none",
    })] }, total: 1, pages: 1 });
    const ui = await mountLawyers();
    await ui.settle();
    await openProfile(ui);

    assert.ok(!/Get Directions/.test(ui.text()));
    await ui.unmount();
});
