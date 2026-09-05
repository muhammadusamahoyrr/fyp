/* The single derivation of "which case is this screen in".
 *
 * Three copies of this logic disagreed. The one that mattered: opening a
 * case-B document moved the internal case to B while the selector stayed on A,
 * and generation re-derived from the selector — so extraction pulled case A's
 * facts into a document belonging to case B.
 *
 * And `NO_CASE` is a non-empty string, so `Boolean(NO_CASE)` is true. That is
 * how a screen came to report Ready for a selection `resolveCaseId` turns into
 * null and generation then refuses: a control the user could pick and could
 * not complete.
 */
import test from "node:test";
import assert from "node:assert/strict";

import { caseSelection, NO_CASE } from "../src/lib/caseSelection.js";

const CASES = [{ _id: "case-1" }, { _id: "case-2" }];

/* ── before the case list has settled ─────────────────────────────────────── */

test("nothing is generatable while the case list is still loading", () => {
    // `cases` is [] before the request answers, which is indistinguishable from
    // "this user has no cases" unless readiness is carried separately.
    const s = caseSelection({ selectedCaseId: "", cases: [], casesReady: false });
    assert.equal(s.canGenerate, false);
    assert.equal(s.blockedReason, "loading");
});

test("a loading list does not claim the user has no cases", () => {
    const s = caseSelection({ selectedCaseId: "", cases: [], casesReady: false });
    assert.notEqual(s.blockedReason, "no_cases");
});

/* ── settled ──────────────────────────────────────────────────────────────── */

test("the first case is adopted when nothing is chosen", () => {
    const s = caseSelection({ selectedCaseId: "", cases: CASES, casesReady: true });
    assert.equal(s.activeCaseId, "case-1");
    assert.equal(s.canGenerate, true);
    assert.equal(s.blockedReason, null);
});

test("an explicit choice wins", () => {
    const s = caseSelection({ selectedCaseId: "case-2", cases: CASES,
                              casesReady: true });
    assert.equal(s.activeCaseId, "case-2");
    assert.equal(s.canGenerate, true);
});

test("a user with zero cases cannot generate, and is told why", () => {
    const s = caseSelection({ selectedCaseId: "", cases: [], casesReady: true });
    assert.equal(s.activeCaseId, null);
    assert.equal(s.canGenerate, false);
    assert.equal(s.blockedReason, "no_cases");
    assert.equal(s.hasCases, false);
});

/* ── the standalone sentinel ──────────────────────────────────────────────── */

test("NO_CASE is never mistaken for a real case", () => {
    // THE DEFECT. The sentinel is a non-empty string, so any `Boolean(selected)`
    // check read it as "a case is selected".
    const s = caseSelection({ selectedCaseId: NO_CASE, cases: CASES,
                              casesReady: true });
    assert.equal(s.activeCaseId, null);
    assert.equal(s.isStandalone, true);
});

test("a screen that cannot create standalone documents says so and refuses", () => {
    // Reporting Ready and then refusing on click is the shape being removed:
    // an option the user can pick and cannot complete.
    const s = caseSelection({ selectedCaseId: NO_CASE, cases: CASES,
                              casesReady: true, allowStandaloneCreation: false });
    assert.equal(s.canGenerate, false, "reported ready for a selection it refuses");
    assert.equal(s.blockedReason, "standalone_unsupported");
});

test("a screen that does support standalone creation may generate", () => {
    // The flag exists so the contract is stated per screen rather than assumed.
    const s = caseSelection({ selectedCaseId: NO_CASE, cases: CASES,
                              casesReady: true, allowStandaloneCreation: true });
    assert.equal(s.canGenerate, true);
    assert.equal(s.blockedReason, null);
    assert.equal(s.activeCaseId, null, "standalone must not adopt a case");
});

test("standalone with no cases at all is still standalone, not 'no cases'", () => {
    const s = caseSelection({ selectedCaseId: NO_CASE, cases: [],
                              casesReady: true });
    assert.equal(s.isStandalone, true);
    assert.equal(s.blockedReason, "standalone_unsupported");
});

/* ── readiness and target never disagree ──────────────────────────────────── */

test("whatever can be generated is what generation targets", () => {
    // The invariant the three separate derivations broke. If `canGenerate` is
    // true then `activeCaseId` is the case that will actually be used — or the
    // screen has explicitly opted into standalone.
    const inputs = [
        { selectedCaseId: "", cases: CASES, casesReady: true },
        { selectedCaseId: "case-2", cases: CASES, casesReady: true },
        { selectedCaseId: NO_CASE, cases: CASES, casesReady: true },
        { selectedCaseId: NO_CASE, cases: CASES, casesReady: true,
          allowStandaloneCreation: true },
        { selectedCaseId: "", cases: [], casesReady: true },
        { selectedCaseId: "", cases: [], casesReady: false },
    ];
    for (const input of inputs) {
        const s = caseSelection(input);
        if (s.canGenerate) {
            assert.ok(s.activeCaseId || (s.isStandalone && input.allowStandaloneCreation),
                      `canGenerate with no target: ${JSON.stringify(input)}`);
            assert.equal(s.blockedReason, null);
        } else {
            assert.ok(s.blockedReason, `refused with no reason given: ${JSON.stringify(input)}`);
        }
    }
});

test("a malformed case list does not throw", () => {
    for (const cases of [null, undefined, "nonsense"]) {
        const s = caseSelection({ selectedCaseId: "", cases, casesReady: true });
        assert.equal(s.activeCaseId, null);
        assert.equal(s.canGenerate, false);
    }
});
