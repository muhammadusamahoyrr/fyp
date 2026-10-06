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

test("the editor shows the checklist and never claims it was checked", () => {
    assert.match(page, /<RequirementsChecklist t=\{t\} report=\{requirements\} \/>/);
    assert.match(page, /not checked automatically/);
    // A reopened draft carries only the name, so the type is found by name too.
    assert.match(page, /TEMPLATES\.find\(x => x\.name === tmpl\?\.name\)/);
    assert.ok(!/satisfied/i.test(page.slice(page.indexOf("function RequirementsChecklist"),
                                           page.indexOf("function StageEditor"))),
        "the checklist must not speak of requirements as satisfied");
});
