/* listAllCases reads every page of /cases, not the first 50. */
import test from "node:test";
import assert from "node:assert/strict";

const api = await import("./support/api-stub.mjs");
const { listAllCases: listAll, MAX_PAGES } = await import("../src/lib/allCases.js");
const listAllCases = (params) => listAll(api.listCases, params);

const kase = (n) => ({ _id: `c${n}`, title: `Case ${n}` });

test.beforeEach(() => api.__reset());

test("every page is read and joined, in order", async () => {
    api.__respond("listCases", ({ page }) => ({
        data: { items: Array.from({ length: page < 3 ? 50 : 7 }, (_, i) => kase((page - 1) * 50 + i)), total: 107, pages: 3 },
        error: null,
    }));
    const { data, error } = await listAllCases();
    assert.equal(error, null);
    assert.equal(data.items.length, 107);
    assert.equal(data.items[50]._id, "c50");
    assert.equal(data.complete, true);
    assert.deepEqual(api.__calls("listCases").map(c => c.args[0].page), [1, 2, 3]);
});

test("a row repeated across pages is listed once", async () => {
    api.__respond("listCases", ({ page }) => ({
        data: { items: page === 1 ? [kase(1), kase(2)] : [kase(2), kase(3)], pages: 2 }, error: null,
    }));
    const { data } = await listAllCases();
    assert.deepEqual(data.items.map(c => c._id), ["c1", "c2", "c3"]);
});

test("a failed first page is an error, a failed later page is a partial list", async () => {
    api.__respond("listCases", { data: null, error: { message: "down" } });
    assert.equal((await listAllCases()).error.message, "down");

    api.__respond("listCases", ({ page }) => (page === 1
        ? { data: { items: [kase(1)], pages: 2 }, error: null }
        : { data: null, error: { message: "down" } }));
    const { data, error } = await listAllCases();
    assert.equal(error, null);
    assert.deepEqual(data.items.map(c => c._id), ["c1"]);
    assert.equal(data.complete, false);
});

test("the read is bounded", async () => {
    api.__respond("listCases", ({ page }) => ({ data: { items: [kase(page)], pages: 999 }, error: null }));
    const { data } = await listAllCases();
    assert.equal(api.__calls("listCases").length, MAX_PAGES);
    assert.equal(data.complete, false);
});
