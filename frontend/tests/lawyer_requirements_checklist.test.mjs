/* The lawyer's plaint shows what the Code requires — as a checklist, never a verdict.
 *
 * The field-based compliance check cannot judge prose, so a lawyer's plaint got
 * `checked: false` and nothing else. The editor now lists the requirements
 * (served by /documents/requirements, from the same rule set as the check) and
 * says in words that none of them was checked automatically. */
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const read = p => readFileSync(new URL(p, import.meta.url), "utf8");
const api = read("../src/lib/api.js");
const page = read("../src/components/lawyer/DocAutomationPage.jsx");
const { TEMPLATES } = await import("../src/lib/lawyerDraftTemplates.js");

test("the plaint template names the instrument the rules are keyed by", () => {
    const plaint = TEMPLATES.find(t => /Plaint/.test(t.name));
    assert.equal(plaint.template_type, "plaint_civil");
});

test("the client asks the requirements route for that instrument", () => {
    assert.match(api, /export async function pleadingRequirements\(templateType\)/);
    assert.match(api, /\/documents\/requirements\/\$\{encodeURIComponent\(templateType\)\}/);
});

test("the drafter no longer shows the checklist (removed 2026-10-11 as noise)", () => {
    // It certified nothing and the lawyer asked for it to go. If it returns, it
    // must again say that nothing was checked automatically.
    assert.doesNotMatch(page, /RequirementsChecklist/);
    assert.doesNotMatch(page, /pleadingRequirements\(/);
});
