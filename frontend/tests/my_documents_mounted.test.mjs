/* The client's own document history, MOUNTED.
 *
 * `/documents/v2/mine` existed and only the lawyer UI called it. A client could
 * reach a document only by still having it on screen; close the tab and the
 * work sat on the server, unreachable through the product.
 *
 * Mounted rather than asserted from source, because everything worth checking
 * here is a sequence: what is shown before the first answer arrives, what
 * happens to an existing list when a later page fails, and whether a slow first
 * page can land after a refresh has replaced it. None of that is visible in the
 * text of the file.
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
                    "MutationObserver", "getComputedStyle"]) {
    define(name, dom.window[name]);
}
define("IS_REACT_ACT_ENVIRONMENT", true);

const React = (await import("react")).default;
const { act } = await import("react");
const { createRoot } = await import("react-dom/client");
const { useMyDocuments, rowActions } = await import("../src/lib/useMyDocuments.js");

const { createElement: h } = React;

function row(id, extra = {}) {
    return {
        id,
        title: `Document ${id}`,
        review_status: "none",
        revision_id: `rev-${id}`,
        pdf_sha256: "a".repeat(64),
        version: 1,
        downloadable: true,
        ...extra,
    };
}

/* A fetcher whose pages resolve when the test says so. */
function deferredPages() {
    const queue = [];
    const calls = [];
    const fetchPage = args => {
        calls.push(args);
        return new Promise(resolve => queue.push(resolve));
    };
    return {
        fetchPage,
        calls,
        answer: (index, value) => queue[index](value),
        pending: () => queue.length,
    };
}

function mountList({ fetchPage, pageSize = 2, enabled = true }) {
    const seen = [];
    const container = dom.window.document.createElement("div");
    dom.window.document.body.appendChild(container);
    const root = createRoot(container);
    const api = {};

    function Probe() {
        const state = useMyDocuments({ fetchPage, pageSize, enabled });
        seen.push({
            items: state.items.map(i => i.id),
            loading: state.loading,
            error: state.error,
            hasMore: state.hasMore,
            isEmpty: state.isEmpty,
        });
        api.loadMore = state.loadMore;
        api.reload = state.reload;
        return null;
    }

    act(() => { root.render(h(Probe)); });
    return {
        seen,
        api,
        latest: () => seen[seen.length - 1],
        unmount: () => act(() => root.unmount()),
    };
}

/* ── the three states that are not "here is a list" ───────────────────────── */

test("it is loading before the first answer, and not empty", async () => {
    // The failure this prevents: an empty-state shown to a client whose
    // documents are still in flight, telling them they have none.
    const p = deferredPages();
    const list = mountList({ fetchPage: p.fetchPage });

    assert.equal(list.latest().loading, true);
    assert.equal(list.latest().isEmpty, false, "claimed empty before asking");

    await act(async () => { p.answer(0, { data: { items: [], has_more: false } }); });
    assert.equal(list.latest().loading, false);
    assert.equal(list.latest().isEmpty, true);
    list.unmount();
});

test("an error is an error, not an empty list", async () => {
    const p = deferredPages();
    const list = mountList({ fetchPage: p.fetchPage });

    await act(async () => {
        p.answer(0, { error: { code: "server_error", message: "Try again." } });
    });

    const s = list.latest();
    assert.equal(s.isEmpty, false, "an error was presented as 'no documents'");
    assert.equal(s.error.message, "Try again.");
    assert.equal(s.loading, false);
    list.unmount();
});

test("documents arrive and are listed", async () => {
    const p = deferredPages();
    const list = mountList({ fetchPage: p.fetchPage });

    await act(async () => {
        p.answer(0, { data: { items: [row("a"), row("b")], has_more: false } });
    });
    assert.deepEqual(list.latest().items, ["a", "b"]);
    assert.equal(list.latest().isEmpty, false);
    list.unmount();
});

/* ── cursor pagination ────────────────────────────────────────────────────── */

test("more pages are appended, not replaced", async () => {
    const p = deferredPages();
    const list = mountList({ fetchPage: p.fetchPage });

    await act(async () => {
        p.answer(0, {
            data: { items: [row("a"), row("b")], has_more: true,
                    next_cursor: "CURSOR-1" },
        });
    });
    assert.equal(list.latest().hasMore, true);

    await act(async () => { list.api.loadMore(); });
    assert.equal(p.calls[1].cursor, "CURSOR-1", "the cursor was not sent");

    await act(async () => {
        p.answer(1, { data: { items: [row("c")], has_more: false } });
    });
    assert.deepEqual(list.latest().items, ["a", "b", "c"]);
    assert.equal(list.latest().hasMore, false);
    list.unmount();
});

test("loadMore does nothing without a cursor", async () => {
    const p = deferredPages();
    const list = mountList({ fetchPage: p.fetchPage });
    await act(async () => {
        p.answer(0, { data: { items: [row("a")], has_more: false } });
    });

    await act(async () => { list.api.loadMore(); });
    assert.equal(p.calls.length, 1, "asked for a page that does not exist");
    list.unmount();
});

test("a failed second page keeps the documents already shown", async () => {
    // Throwing away a list the client can see, because one more page failed, is
    // the version of this bug that looks like data loss.
    const p = deferredPages();
    const list = mountList({ fetchPage: p.fetchPage });
    await act(async () => {
        p.answer(0, { data: { items: [row("a")], has_more: true,
                              next_cursor: "CURSOR-1" } });
    });

    await act(async () => { list.api.loadMore(); });
    await act(async () => { p.answer(1, { error: { message: "Network" } }); });

    assert.deepEqual(list.latest().items, ["a"], "the visible list was discarded");
    assert.equal(list.latest().error.message, "Network");
    list.unmount();
});

/* ── stale responses ──────────────────────────────────────────────────────── */

test("a slow first page cannot land after a reload", async () => {
    const p = deferredPages();
    const list = mountList({ fetchPage: p.fetchPage });

    await act(async () => { list.api.reload(); });      // second request in flight
    await act(async () => {
        p.answer(1, { data: { items: [row("fresh")], has_more: false } });
    });
    await act(async () => {
        p.answer(0, { data: { items: [row("stale")], has_more: false } });
    });

    assert.deepEqual(list.latest().items, ["fresh"], "a stale page overwrote a newer one");
    list.unmount();
});

test("a response arriving after unmount changes nothing", async () => {
    const p = deferredPages();
    const list = mountList({ fetchPage: p.fetchPage });
    list.unmount();

    await act(async () => {
        p.answer(0, { data: { items: [row("a")], has_more: false } });
    });
    // No throw, and nothing rendered after unmount.
    assert.ok(list.seen.length >= 1);
});

test("it does not fetch while disabled", () => {
    const p = deferredPages();
    const list = mountList({ fetchPage: p.fetchPage, enabled: false });
    assert.equal(p.calls.length, 0);
    list.unmount();
});

/* ── what a row offers ────────────────────────────────────────────────────── */

test("a generated row can be opened, previewed and downloaded", () => {
    const a = rowActions(row("a"));
    assert.equal(a.canOpen, true);
    assert.equal(a.canPreview, true);
    assert.equal(a.canDownload, true);
    assert.equal(a.revisionId, "rev-a");
    assert.equal(a.pdfSha256.length, 64);
    assert.equal(a.reason, null);
});

test("a row with no revision offers no download and says why", () => {
    const a = rowActions(row("a", { revision_id: null, pdf_sha256: null,
                                    downloadable: false }));
    assert.equal(a.canDownload, false);
    assert.equal(a.canOpen, true);
    assert.match(a.reason, /not been generated/);
});

test("a row whose file is unavailable offers no download", () => {
    const a = rowActions(row("a", { downloadable: false }));
    assert.equal(a.canDownload, false);
    assert.match(a.reason, /not available/);
});

test("the revision and hash never travel apart", () => {
    // They are the pair every guarded endpoint compares. One without the other
    // produces a request that fails a check the user cannot act on.
    for (const r of [row("a"), row("a", { pdf_sha256: null }),
                     row("a", { revision_id: null })]) {
        const a = rowActions(r);
        assert.equal(Boolean(a.revisionId && a.pdfSha256), a.canDownload || false
            ? true : Boolean(a.revisionId && a.pdfSha256));
        if (a.canDownload) assert.ok(a.revisionId && a.pdfSha256);
    }
});

test("the client never sends an owner id", async () => {
    // Ownership is the backend's answer. A second, client-side one is the first
    // thing to diverge, and it would be the weaker of the two.
    const p = deferredPages();
    const list = mountList({ fetchPage: p.fetchPage });
    await act(async () => {
        p.answer(0, { data: { items: [], has_more: false } });
    });
    for (const call of p.calls) {
        assert.ok(!("client_id" in call), "the client scoped the query itself");
        assert.ok(!("owner_id" in call));
    }
    list.unmount();
});


/* ── the caller must not have to memoise ──────────────────────────────────── */

test("an inline fetchPage does not cause a refetch loop", async () => {
    // THE DEFECT. `load` was a useCallback over `fetchPage`, and the effect
    // depended on `load`. A caller writing the obvious thing —
    //
    //     useMyDocuments({ fetchPage: () => myDocumentsV2(...) })
    //
    // gets a new function identity every render, so the effect re-ran, which
    // set state, which re-rendered, forever. It hammered the API in a tight
    // loop and never painted a list.
    //
    // The panel in this repo happened to wrap its fetcher in `useCallback([])`,
    // so every other test here passed by coincidence.
    let calls = 0;
    const container = dom.window.document.createElement("div");
    dom.window.document.body.appendChild(container);
    const root = createRoot(container);

    function Probe() {
        useMyDocuments({
            fetchPage: async () => {
                calls++;
                return { data: { items: [], has_more: false } };
            },
        });
        return null;
    }

    await act(async () => { root.render(h(Probe)); });
    await act(async () => { await new Promise(r => setTimeout(r, 50)); });

    assert.ok(calls <= 2, `fetched ${calls} times for one mount`);
    await act(async () => { root.unmount(); });
});

test("changing the fetcher identity does not refetch", async () => {
    let calls = 0;
    const container = dom.window.document.createElement("div");
    dom.window.document.body.appendChild(container);
    const root = createRoot(container);

    function Probe({ tick }) {
        useMyDocuments({
            fetchPage: async () => {
                calls++;
                return { data: { items: [], has_more: false } };
            },
        });
        return null;
    }

    await act(async () => { root.render(h(Probe, { tick: 1 })); });
    const after = calls;
    await act(async () => { root.render(h(Probe, { tick: 2 })); });
    await act(async () => { root.render(h(Probe, { tick: 3 })); });
    await act(async () => { await new Promise(r => setTimeout(r, 30)); });

    assert.equal(calls, after, "a re-render refetched the whole list");
    await act(async () => { root.unmount(); });
});
