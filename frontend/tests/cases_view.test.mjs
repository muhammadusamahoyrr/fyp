/* buildCasesView: every chip count is the length of the rows its view shows. */
import test from "node:test";
import assert from "node:assert/strict";

const { buildCasesView, VIEW_SECTIONS } = await import("../src/lib/casesView.js");

const TODAY = "2026-11-10";               // frozen, so the test never depends on the clock
const c = (id, over = {}) => ({ id, _id: `db-${id}`, title: `Matter ${id}`, client: `Client ${id}`, status: "In Progress",
    nextHearing: "", caseTypeKey: "civil", provinceKey: "punjab", createdAt: "2026-10-01T00:00:00Z", ...over });
const r = (id, status, over = {}) => ({ id, status, case_title: `Request ${id}`, case_number: `R-${id}`, client_name: `Asker ${id}`,
    case_type: "family", created_at: "2026-11-01T00:00:00Z", ...over });

const CASES = [
    c("A", { nextHearing: "2026-11-20" }),                   // active, upcoming
    c("B", { nextHearing: "2026-11-05" }),                   // active, outcome due
    c("C"),                                                  // not filed yet
    c("D", { status: "Closed", nextHearing: "2026-09-01" }), // history
    c("E", { status: "Dismissed" }),                         // history
];
const REQUESTS = [r(1, "requested"), r(2, "terms_proposed"), r(3, "declined"), r(4, "accepted")];
const view = (over = {}) => buildCasesView({ cases: CASES, requests: REQUESTS, today: TODAY, ...over });

test("each count equals the rows its view renders", () => {
    const { sections, counts } = view();
    for (const [name, keys] of Object.entries(VIEW_SECTIONS)) {
        assert.equal(counts[name], keys.reduce((n, k) => n + sections[k].length, 0), name);
    }
});

test("New requests counts only requests waiting on the lawyer, not terms already sent", () => {
    const { sections, counts } = view();
    assert.deepEqual(sections.newRequests.map(x => x.id), [1]);
    assert.deepEqual(sections.awaitingClient.map(x => x.id), [2]);
    assert.equal(counts.requests, 1);
});

test("Needs me is requests to answer, cases with no date, and outcomes due — nothing passive", () => {
    const { counts, sections } = view();
    assert.deepEqual(sections.outcomeDue.map(x => x.id), ["B"]);
    assert.equal(counts.needs, 1 + 1 + 1);          // request 1, case C, case B
});

test("All does not count closed cases; History does", () => {
    const { counts } = view();
    assert.equal(counts.all, 1 + 1 + 1 + 2);        // request 1, request 2 (awaiting), C, A + B
    assert.equal(counts.history, 2);
});

test("filters and search apply to every view the same way", () => {
    assert.equal(view({ types: ["family"] }).counts.all, 2, "only the two family requests");
    assert.equal(view({ provinces: ["sindh"] }).counts.all, 0, "a province filter cannot vouch for a request");
    assert.equal(view({ search: "matter c" }).counts.all, 1);
    assert.equal(view({ search: "matter d" }).counts.history, 1);
});

test("outcome due is decided against the given day, not the clock", () => {
    assert.equal(view({ today: "2026-11-21" }).sections.outcomeDue.length, 2);
    assert.equal(view({ today: "2026-11-01" }).sections.outcomeDue.length, 0);
});

/* ── selectFeed: Recent & upcoming ─────────────────────────────────────── */
const { selectFeed } = await import("../src/lib/casesView.js");
const item = (key, kind, sort, title = key) => ({ key, kind, sort, title });

test("a hearing tomorrow is not pushed out by tasks due next month", () => {
    const feed = selectFeed([
        item("h-tomorrow", "hearing", "2026-11-11"),
        ...[1, 2, 3, 4, 5, 6].map(n => item(`t${n}`, "task", `2026-12-0${n}`)),
    ], TODAY);
    assert.equal(feed[0].key, "h-tomorrow");
    assert.equal(feed.length, 5);
});

test("upcoming nearest first, then recent past most recent first, 3 + 2 slots", () => {
    const feed = selectFeed([
        item("u3", "task", "2026-11-30"), item("u1", "hearing", "2026-11-12"), item("u2", "task", "2026-11-20"),
        item("u4", "task", "2026-12-20"),
        item("p-old", "hearing", "2026-09-01"), item("p-new", "hearing", "2026-11-08"), item("p-mid", "task", "2026-10-15"),
    ], TODAY);
    assert.deepEqual(feed.map(x => x.key), ["u1", "u2", "u3", "p-new", "p-mid"]);
});

test("unused slots on one side are filled from the other", () => {
    const onlyFuture = selectFeed([1, 2, 3, 4, 5, 6].map(n => item(`u${n}`, "task", `2026-11-1${n}`)), TODAY);
    assert.deepEqual(onlyFuture.map(x => x.key), ["u1", "u2", "u3", "u4", "u5"]);
    const onlyPast = selectFeed([1, 2, 3, 4, 5, 6].map(n => item(`p${n}`, "hearing", `2026-10-0${n}`)), TODAY);
    assert.deepEqual(onlyPast.map(x => x.key), ["p6", "p5", "p4", "p3", "p2"]);
    const oneUp = selectFeed([item("u", "hearing", "2026-11-12"),
        ...[1, 2, 3, 4, 5].map(n => item(`p${n}`, "task", `2026-10-0${n}`))], TODAY);
    assert.deepEqual(oneUp.map(x => x.key), ["u", "p5", "p4", "p3", "p2"]);
});

test("ties: hearing before task on the same day, then title; today counts as upcoming", () => {
    const feed = selectFeed([item("t", "task", TODAY, "A task"), item("h", "hearing", TODAY, "Z hearing"),
                             item("t2", "task", TODAY, "B task")], TODAY);
    assert.deepEqual(feed.map(x => x.key), ["h", "t", "t2"]);
});

/* ── requestAgeDays: whole Pakistan calendar days since a request ──────── */
const { requestAgeDays } = await import("../src/lib/casesView.js");

test("a request's age is counted in Pakistan calendar days, not UTC ones", () => {
    // 00:30 PKT on the 10th is 19:30 UTC on the 9th: the old code read the UTC
    // date and said "1 day ago" until 05:00 PKT.
    assert.equal(requestAgeDays("2026-11-09T19:30:00Z", "2026-11-10"), 0);
    assert.equal(requestAgeDays("2026-11-09T18:59:59Z", "2026-11-10"), 1, "23:59:59 PKT the day before");
    assert.equal(requestAgeDays("2026-11-10T00:00:00Z", "2026-11-10"), 0, "UTC midnight is 05:00 PKT the same day");
    assert.equal(requestAgeDays("2026-11-07T10:00:00Z", "2026-11-10"), 3);
    assert.equal(requestAgeDays(null, "2026-11-10"), null);
    assert.equal(requestAgeDays("not a date", "2026-11-10"), null);
});
