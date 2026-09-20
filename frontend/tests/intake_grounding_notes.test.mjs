/* Every grounding status the backend emits must have something to say.
 *
 * `GROUNDING_NOTE` falls back to the generic "not verified" line for anything
 * it does not know. That fallback is safe but it is not always HONEST: when
 * the backend reports `citations_unverified` it means a statute was named that
 * does not appear in the law found for the case — a citation that may be
 * invented — and "these steps have not been verified" reads as a missing check
 * rather than a fabricated authority.
 *
 * The backend gained three statuses when intake grounding was rewritten, and
 * the map did not. Nothing failed: the fallback absorbed them silently, which
 * is exactly why this test reads the STATUS LIST OUT OF THE BACKEND SOURCE
 * rather than restating it here. A restated list would drift the same way.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const JUDGE = resolve(here, "../../backend/app/ai/nodes/intake_hallucination_node.py");
const UI = resolve(here, "../src/components/client/ModIntake.jsx");

/* Statuses the judge actually writes: `grounding_status` is always set to a
 * literal in this file, so the literals are the contract. */
function backendStatuses() {
    const src = readFileSync(JUDGE, "utf8");
    const found = new Set();
    for (const m of src.matchAll(/"grounding_status":\s*"([a-z_]+)"/g)) found.add(m[1]);
    for (const m of src.matchAll(/_finish\(\s*parsed[^,]*,\s*"([a-z_]+)"/g)) found.add(m[1]);
    for (const m of src.matchAll(/status\s*=\s*"([a-z_]+)"\s*if/g)) found.add(m[1]);
    for (const m of src.matchAll(/else\s*"([a-z_]+)"/g)) found.add(m[1]);
    return found;
}

function uiNotes() {
    const src = readFileSync(UI, "utf8");
    const block = src.slice(src.indexOf("const GROUNDING_NOTE"));
    const body = block.slice(0, block.indexOf("};"));
    return new Set([...body.matchAll(/^\s{4}([a-z_]+):/gm)].map(m => m[1]));
}

test("the backend really does emit more than one status", () => {
    const statuses = backendStatuses();
    assert.ok(statuses.size >= 6,
        `only found ${statuses.size} statuses — the scraper has probably stopped matching`);
});

test("every status the judge emits has a note, except the pass", () => {
    const notes = uiNotes();
    const missing = [...backendStatuses()]
        // `grounded` needs no caution, and `no_answer` never reaches the UI:
        // an empty answer lands the conversion on the pipeline_failed path.
        .filter(s => s !== "grounded" && s !== "no_answer")
        .filter(s => !notes.has(s));

    assert.deepEqual(missing, [],
        `these statuses would fall back to the generic note: ${missing.join(", ")}`);
});

test("a fabricated citation is not described as a missing check", () => {
    const src = readFileSync(UI, "utf8");
    const block = src.slice(src.indexOf("citations_unverified:"));
    const line = block.slice(0, block.indexOf("\n"));
    // The distinguishing claim: the citation itself may be wrong, not merely
    // unchecked. Without this the reader is told the steps are unverified and
    // has no reason to doubt the law named beside them.
    assert.match(line, /could not be matched|may not exist|do not rely/i);
});

test("the generic fallback still exists for anything unforeseen", () => {
    assert.ok(uiNotes().has("unverified"));
});
