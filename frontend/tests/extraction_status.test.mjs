/**
 * What the client is told about how much of their evidence was read.
 *
 * The defect this guards: a bundle read down to its cover sheet looked exactly
 * like a bundle read in full. Both showed a filename and a size. The analysis
 * then spoke with the same confidence either way.
 *
 * Two rules are load-bearing here and are asserted directly:
 *   - nothing is claimed before extraction has run;
 *   - no page is ever called a scan, because we cannot tell a scanned page from
 *     a blank one.
 */
import test from "node:test";
import assert from "node:assert/strict";

import {
    ALL_STATES,
    extractionLabel,
    incompleteFiles,
    isAnalysed,
    isIncomplete,
    STATE_COMPLETE,
    STATE_ERROR,
    STATE_PARTIAL,
    STATE_PENDING,
    STATE_STORAGE_ONLY,
    STATE_UNREADABLE,
    TONE_OK,
    TONE_WARN,
    TONE_BAD,
} from "../src/lib/extractionStatus.js";

test("a file that has not been extracted yet is pending, not fine", () => {
    for (const input of [{ file_id: "a", filename: "x.pdf" }, {}, null]) {
        const label = extractionLabel(input);
        assert.equal(label.state, STATE_PENDING);
        assert.notEqual(label.tone, TONE_OK, "pending must not read as reassurance");
    }
});

test("an un-extracted file is not counted as incomplete", () => {
    // It is not "fine" either — it is simply not analysed yet, and that must not
    // be shown to the client as a problem they need to act on.
    assert.equal(isIncomplete({ file_id: "a" }), false);
});

test("a fully read file says so and is not flagged", () => {
    const label = extractionLabel({
        extraction_status: "readable", completeness: "complete",
        pages_total: 3, pages_with_text: 3,
    });
    assert.equal(label.tone, TONE_OK);
    assert.equal(label.title, "Read in full");
    assert.equal(isIncomplete({ extraction_status: "readable" }), false);
});

test("a partially read file names how many pages produced nothing", () => {
    const label = extractionLabel({
        extraction_status: "partially_read",
        completeness: "partial_or_uncertain",
        pages_total: 5, pages_with_text: 2,
    });
    assert.equal(label.tone, TONE_WARN);
    assert.equal(label.title, "Partially read");
    assert.match(label.detail, /3 of 5 pages produced no text/);
});

test("singular and plural page wording both read correctly", () => {
    const one = extractionLabel({
        extraction_status: "partially_read", pages_total: 1, pages_with_text: 0,
    });
    assert.match(one.detail, /1 of 1 page produced no text/);
});

test("skipped and failed pages are reported separately", () => {
    const label = extractionLabel({
        extraction_status: "partially_read",
        pages_total: 10, pages_with_text: 4, pages_skipped: 5, pages_failed: 1,
    });
    assert.match(label.detail, /6 of 10 pages produced no text/);
    assert.match(label.detail, /5 not processed/);
    assert.match(label.detail, /1 could not be read/);
});

test("unread document parts are named", () => {
    const label = extractionLabel({
        extraction_status: "partially_read",
        limitations: ["unsupported_part:headers", "extracted_text_cap_reached"],
    });
    assert.match(label.detail, /headers not read/);
    // A non-part limitation is not turned into a sentence it does not fit.
    assert.doesNotMatch(label.detail, /extracted_text_cap_reached/);
});

test("a prompt-budget omission is distinguished from an unreadable file", () => {
    // These are different problems with different remedies: one is fixed by
    // removing another file, the other is not fixable by the client at all.
    const omitted = extractionLabel({ extraction_status: "omitted_limit" });
    const unreadable = extractionLabel({ extraction_status: "unreadable" });

    assert.notEqual(omitted.title, unreadable.title);
    assert.match(omitted.detail, /length limit/);
    assert.equal(unreadable.tone, TONE_BAD);
});

test("a missing file is distinguished from an unreadable one", () => {
    const missing = extractionLabel({ extraction_status: "missing" });
    assert.equal(missing.tone, TONE_BAD);
    assert.match(missing.title, /not found/i);
});

test("an unknown status is reported as unknown, never as fine", () => {
    const label = extractionLabel({ extraction_status: "something_new" });
    assert.notEqual(label.tone, TONE_OK);
    assert.match(label.title, /unknown/i);
});

test("no label ever calls a page a scan or a photo", () => {
    const statuses = ["readable", "partially_read", "omitted_limit", "missing",
                      "unreadable", "invalid_path", "whatever"];
    for (const status of statuses) {
        const label = extractionLabel({
            extraction_status: status, pages_total: 4, pages_with_text: 1,
            pages_skipped: 1, pages_failed: 1,
            limitations: ["unsupported_part:footers"],
        });
        const text = `${label.title} ${label.detail}`.toLowerCase();
        assert.ok(!text.includes("scan"), `"${text}" claims to detect a scan`);
        assert.ok(!text.includes("photo"), `"${text}" claims to detect a photo`);
        assert.ok(!text.includes("image"), `"${text}" claims to know it is an image`);
    }
});

test("incompleteFiles returns only the files with something missing", () => {
    const files = [
        { file_id: "a", extraction_status: "readable" },
        { file_id: "b", extraction_status: "partially_read", pages_total: 3, pages_with_text: 1 },
        { file_id: "c" },                                   // not extracted yet
        { file_id: "d", extraction_status: "unreadable" },
        { file_id: "e", analysis_support: "storage_only" },
        { file_id: "f", error: "Upload failed" },           // never reached the server
    ];
    // `c` is pending and `f` never arrived — neither is a hole in the evidence
    // the analysis actually used.
    assert.deepEqual(incompleteFiles(files).map(f => f.file_id), ["b", "d", "e"]);
});

test("incompleteFiles tolerates rubbish input", () => {
    assert.deepEqual(incompleteFiles(null), []);
    assert.deepEqual(incompleteFiles(undefined), []);
    assert.deepEqual(incompleteFiles("nope"), []);
});

test("missing page counters do not produce NaN wording", () => {
    const label = extractionLabel({ extraction_status: "partially_read" });
    assert.ok(!label.detail.includes("NaN"));
    assert.ok(label.detail.length > 0, "a warning with no detail still explains itself");
});

// ── the six states stay six ────────────────────────────────────────────────
//
// Collapsing any two loses something the client needs: `storage_only` is not
// `unreadable` (nothing is wrong with the file, and re-uploading the same format
// will not help), `pending` is not `complete` (nothing has been read yet), and
// `error` is not `unreadable` (the bytes never arrived).

const SAMPLES = {
    pending: { file_id: "p" },
    complete: { file_id: "c", extraction_status: "readable" },
    partial: { file_id: "pa", extraction_status: "partially_read", pages_total: 4, pages_with_text: 1 },
    unreadable: { file_id: "u", extraction_status: "unreadable" },
    storage_only: { file_id: "s", analysis_support: "storage_only", notice: "Saved, but images cannot be read." },
    error: { file_id: "e", error: "Upload failed" },
};

test("every one of the six states is reachable and distinct", () => {
    const seen = Object.fromEntries(
        Object.entries(SAMPLES).map(([name, ef]) => [name, extractionLabel(ef).state]));

    assert.deepEqual(seen, {
        pending: STATE_PENDING,
        complete: STATE_COMPLETE,
        partial: STATE_PARTIAL,
        unreadable: STATE_UNREADABLE,
        storage_only: STATE_STORAGE_ONLY,
        error: STATE_ERROR,
    });
    assert.equal(new Set(Object.values(seen)).size, ALL_STATES.length,
        "two states collapsed into one");
});

test("no two states share a title", () => {
    const titles = Object.values(SAMPLES).map(ef => extractionLabel(ef).title);
    assert.equal(new Set(titles).size, titles.length,
        `two states read identically to a client: ${titles.join(" / ")}`);
});

test("a storage-only file is not described as broken", () => {
    // Nothing is wrong with it. Telling the client it "could not be read"
    // invites them to re-upload the same format and hit the same wall.
    const label = extractionLabel(SAMPLES.storage_only);

    assert.equal(label.state, STATE_STORAGE_ONLY);
    assert.doesNotMatch(label.title, /could not be read/i);
    assert.match(label.title, /stored/i);
});

test("a storage-only file still counts as a gap in the evidence", () => {
    // It was not analysed, so the analysis is incomplete — even though the file
    // itself is fine.
    assert.equal(isIncomplete(SAMPLES.storage_only), true);
});

test("an upload error is never confused with an unreadable file", () => {
    const error = extractionLabel(SAMPLES.error);
    const unreadable = extractionLabel(SAMPLES.unreadable);

    assert.notEqual(error.state, unreadable.state);
    assert.match(error.title, /upload/i);
});

test("an upload error is not treated as analysed", () => {
    assert.equal(isAnalysed(SAMPLES.error), false);
    assert.equal(isAnalysed(SAMPLES.pending), false);
    assert.equal(isAnalysed(SAMPLES.complete), true);
    assert.equal(isAnalysed(SAMPLES.storage_only), true);
});

test("an upload failure outranks every other signal", () => {
    // A stale extraction_status on a row whose re-upload just failed must not
    // keep claiming the file was read.
    const label = extractionLabel({
        error: "Upload failed", extraction_status: "readable",
        analysis_support: "storage_only",
    });
    assert.equal(label.state, STATE_ERROR);
});

test("only `readable` ever produces the complete state", () => {
    // The one rule that must not bend: `partial_or_uncertain` cannot become
    // `complete` by passing through this function.
    for (const status of ["partially_read", "omitted_limit", "unreadable",
                          "missing", "invalid_path", "anything_else"]) {
        const label = extractionLabel({
            extraction_status: status, completeness: "complete",
        });
        assert.notEqual(label.state, STATE_COMPLETE,
            `status ${status} was upgraded to complete`);
    }
});
