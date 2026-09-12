/* A draft must never be presented as a real case — on ANY screen.
 *
 * WHY THIS FILE IS SHAPED LIKE THIS
 *
 * The backend refuses to match, engage or book a draft, and those guards were
 * tested. The browser had no equivalent rule, and `GET /cases` returns the
 * client's own drafts, so four separate screens each presented one as real:
 * counted toward "N cases open", given a "Filed" date and made the default
 * active matter, offered for document generation, and offered in the
 * hire-a-lawyer picker.
 *
 * The audit that was supposed to catch this checked the service guards and one
 * of the four screens. So the important test here is not the predicate — it is
 * `every client screen that lists cases applies the rule`, which reads the
 * source and fails on a screen that forgot. A per-screen test would have to be
 * remembered for the fifth screen; this one cannot be.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve, join } from "node:path";

import {
    activeCases,
    confirmedCases,
    hireableCases,
    isDraftCase,
    isEndedCase,
    isUnknownCase,
} from "../src/lib/caseStatus.js";

const here = dirname(fileURLToPath(import.meta.url));
const CLIENT_DIR = resolve(here, "../src/components/client");

const DRAFT = { _id: "c1", status: "draft" };
const OPEN = { _id: "c2", status: "open" };
const PENDING = { _id: "c3", status: "pending_lawyer" };
const CLOSED = { _id: "c4", status: "closed" };
const ASSIGNED = { _id: "c5", status: "in_progress", lawyer_id: "L1" };

// ── the predicate ──────────────────────────────────────────────────────────

test("a draft is recognised as a draft", () => {
    assert.equal(isDraftCase(DRAFT), true);
    assert.equal(isDraftCase(OPEN), false);
});

test("a case with no status is not presented as a real one", () => {
    /* THE COMMENT USED TO CONTRADICT THE ASSERTION.
     *
     * It said "not counted as active, which is the safer direction" directly
     * above `assert.deepEqual(activeCases([{}]), [{}])` — which asserts the
     * opposite: that a statusless case IS active. The prose described the
     * behaviour we wanted; the assertion pinned the behaviour we had.
     *
     * The behaviour is now what the prose claimed. `create_case` always sets a
     * status, so a case without one is corrupt or from a newer server, and
     * neither belongs in a count labelled "cases open". */
    assert.equal(isDraftCase({}), false);          // it is not a draft…
    assert.equal(isUnknownCase({}), true);         // …it is unrecognised
    // NOT COUNTED as open: that number is a claim about what is running.
    assert.deepEqual(activeCases([{}]), []);
    // But STILL SHOWN. Hiding a client's own case is the worse failure — they
    // cannot act on a matter they cannot see. Excluding it here made two
    // ordinary fixtures vanish from the documents screen.
    assert.deepEqual(confirmedCases([{}]), [{}]);
});

test("an unrecognised status is not counted as open but is still shown", () => {
    const future = [{ _id: "x", status: "under_appeal" }];
    assert.deepEqual(activeCases(future), []);
    assert.deepEqual(confirmedCases(future), future);
});

test("every status the server can set is recognised", () => {
    /* The allowlist and the backend enum must not drift: a status the server
     * starts using that this list does not know would make real cases vanish
     * from the client's own screens. */
    const serverStatuses = ["draft", "open", "in_progress", "pending_lawyer",
                            "closed", "dismissed"];
    const unrecognised = serverStatuses.filter(st => isUnknownCase({ status: st }));
    assert.deepEqual(unrecognised, [],
        `these real statuses are not in KNOWN: ${unrecognised.join(", ")}`);
});

test("confirmed excludes drafts and keeps ended cases", () => {
    const out = confirmedCases([DRAFT, OPEN, CLOSED]);
    assert.deepEqual(out.map(c => c._id), ["c2", "c4"]);
});

test("active excludes drafts AND ended cases", () => {
    const out = activeCases([DRAFT, OPEN, PENDING, CLOSED]);
    assert.deepEqual(out.map(c => c._id), ["c2", "c3"]);
});

test("a draft never counts toward an open-case total", () => {
    // The literal defect: "N cases open" included unconfirmed intakes.
    assert.equal(activeCases([DRAFT]).length, 0);
    assert.equal(activeCases([DRAFT, OPEN]).length, 1);
});

test("hireable excludes drafts, ended, assigned and already-requested", () => {
    const out = hireableCases([DRAFT, OPEN, CLOSED, ASSIGNED, PENDING],
                              { c3: { status: "requested" } });
    assert.deepEqual(out.map(c => c._id), ["c2"]);
});

test("a non-array is handled rather than thrown on", () => {
    assert.deepEqual(activeCases(null), []);
    assert.deepEqual(confirmedCases(undefined), []);
});

// ── every screen applies the rule ──────────────────────────────────────────

function clientScreens() {
    return readdirSync(CLIENT_DIR)
        .filter(f => f.endsWith(".jsx"))
        .map(f => ({ name: f, src: readFileSync(join(CLIENT_DIR, f), "utf8") }));
}

/* A screen "lists cases" if it pulls them from the API or the shared context.
 * Both routes hand back the client's drafts. */
function listsCases(src) {
    return /listCases\s*\(/.test(src)
        || /const\s*\{[^}]*\bcases\b[^}]*\}\s*=\s*useCase\(\)/.test(src);
}

test("at least one client screen lists cases, or this test is checking nothing", () => {
    const screens = clientScreens().filter(s => listsCases(s.src));
    assert.ok(screens.length >= 3,
        `found only ${screens.length} case-listing screens — the detector has probably stopped matching`);
});

test("every client screen that lists cases applies the draft rule", () => {
    const offenders = clientScreens()
        .filter(s => listsCases(s.src))
        .filter(s => !s.src.includes("@/lib/caseStatus.js"))
        .map(s => s.name);

    assert.deepEqual(offenders, [],
        `these screens list cases without excluding drafts: ${offenders.join(", ")}. `
        + "Import the rule from lib/caseStatus.js rather than re-implementing it.");
});

test("no screen hand-rolls the draft comparison", () => {
    /* Four ad-hoc filters are four chances to miss the fifth screen — which is
     * exactly how this shipped. The rule lives in one module. */
    const offenders = clientScreens()
        .filter(s => !s.name.startsWith("ModIntake"))   // intake owns the draft it creates
        .filter(s => /["']draft["']/.test(s.src))
        .filter(s => !s.src.includes("isDraftCase"))
        .map(s => s.name);

    assert.deepEqual(offenders, [],
        `these compare against "draft" directly: ${offenders.join(", ")}`);
});
