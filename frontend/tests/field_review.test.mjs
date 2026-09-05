/* Reviewing what the AI extracted, before it becomes a legal document.
 *
 * Generation ran extraction and rendering back to back: a model decided who
 * the parties were and what the amounts were, and those values entered a
 * plaint without the client seeing them. The finished-PDF review that follows
 * is a poor substitute — finding a wrong figure in three formatted pages is a
 * different task from seeing `demand: 500000` in a list.
 */
import test from "node:test";
import assert from "node:assert/strict";

import {
    buildReviewRows, toSubmittedFields, missingFields, canGenerate,
    editRow, hasEdits, humanise, EXTRACTED, EMPTY, UNUSED,
} from "../src/lib/fieldReview.js";

/* The real field list for legal_notice, as /documents/templates returns it. */
const NOTICE_FIELDS = [
    "sender_name", "sender_address", "recipient_name", "recipient_address",
    "notice_body", "demand", "response_days", "date",
];

/* ── labels ───────────────────────────────────────────────────────────────── */

test("field names become readable labels", () => {
    assert.equal(humanise("recipient_address"), "Recipient address");
    assert.equal(humanise("notice_body"), "Notice body");
    assert.equal(humanise("date"), "Date");
});

test("acronyms are not sentence-cased into nonsense", () => {
    // "Fir no" reads as a word; this is an FIR number, on a bail application.
    // "no" stays lower-case though — it is short for "number", and "FIR NO"
    // reads as the word "no" shouted.
    assert.equal(humanise("fir_no"), "FIR no");
    assert.equal(humanise("cnic"), "CNIC");
    assert.equal(humanise("case_no"), "Case no");
});

test("a missing or empty name does not throw", () => {
    assert.equal(humanise(""), "");
    assert.equal(humanise(null), "");
    assert.equal(humanise(undefined), "");
});

/* ── the three states ─────────────────────────────────────────────────────── */

test("extracted values are shown for review", () => {
    const rows = buildReviewRows(
        { sender_name: "Ayesha Khan", demand: "500000" }, NOTICE_FIELDS);

    const sender = rows.find(r => r.name === "sender_name");
    assert.equal(sender.value, "Ayesha Khan");
    assert.equal(sender.status, EXTRACTED);
    assert.equal(sender.label, "Sender name");
});

test("a field the template wants but the model missed is shown empty", () => {
    // Omitting it would be the same bug in a different place: a field absent
    // from the form is a field absent from the document, silently.
    const rows = buildReviewRows({ sender_name: "Ayesha Khan" }, NOTICE_FIELDS);
    const demand = rows.find(r => r.name === "demand");

    assert.ok(demand, "a declared field vanished from the review");
    assert.equal(demand.value, "");
    assert.equal(demand.status, EMPTY);
});

test("blank-ish values count as missing, not as deliberate blanks", () => {
    const rows = buildReviewRows(
        { sender_name: "   ", demand: null, date: undefined }, NOTICE_FIELDS);

    for (const name of ["sender_name", "demand", "date"]) {
        assert.equal(rows.find(r => r.name === name).status, EMPTY, name);
    }
});

test("a value the template cannot use says so instead of vanishing", () => {
    // The builder drops it. Saying so is the difference between a value the
    // client chose not to use and one the system threw away without telling.
    const rows = buildReviewRows(
        { sender_name: "A", court_name: "LHC Lahore" }, NOTICE_FIELDS);

    const extra = rows.find(r => r.name === "court_name");
    assert.ok(extra, "an unusable extracted value was silently discarded");
    assert.equal(extra.status, UNUSED);
    assert.equal(extra.used, false);
});

test("declared fields keep the template's own order", () => {
    const rows = buildReviewRows({}, NOTICE_FIELDS);
    assert.deepEqual(rows.map(r => r.name), NOTICE_FIELDS);
});

test("unusable values sort after the real ones", () => {
    const rows = buildReviewRows(
        { zzz_extra: "x", sender_name: "A" }, NOTICE_FIELDS);
    assert.equal(rows[rows.length - 1].name, "zzz_extra");
});

test("nothing extracted still produces a full, empty form", () => {
    for (const extracted of [null, undefined, {}]) {
        const rows = buildReviewRows(extracted, NOTICE_FIELDS);
        assert.equal(rows.length, NOTICE_FIELDS.length);
        assert.ok(rows.every(r => r.status === EMPTY));
    }
});

test("an unknown template does not crash the review", () => {
    assert.deepEqual(buildReviewRows({ a: 1 }, null).map(r => r.name), ["a"]);
    assert.deepEqual(buildReviewRows({}, undefined), []);
});

/* ── editing ──────────────────────────────────────────────────────────────── */

test("an edit replaces one value and leaves the rest alone", () => {
    const rows = buildReviewRows({ sender_name: "Ayesha", demand: "500000" },
                                 NOTICE_FIELDS);
    const edited = editRow(rows, "demand", "50000");

    assert.equal(edited.find(r => r.name === "demand").value, "50000");
    assert.equal(edited.find(r => r.name === "sender_name").value, "Ayesha");
    assert.equal(rows.find(r => r.name === "demand").value, "500000",
                 "the original array was mutated");
});

test("edits are detectable, so the UI can say the draft is yours", () => {
    const extracted = { sender_name: "Ayesha", demand: "500000" };
    const rows = buildReviewRows(extracted, NOTICE_FIELDS);

    assert.equal(hasEdits(rows, extracted), false);
    assert.equal(hasEdits(editRow(rows, "demand", "50000"), extracted), true);
});

test("filling a field the model missed counts as an edit", () => {
    const extracted = { sender_name: "Ayesha" };
    const rows = buildReviewRows(extracted, NOTICE_FIELDS);
    assert.equal(hasEdits(editRow(rows, "demand", "50000"), extracted), true);
});

/* ── what actually gets submitted ─────────────────────────────────────────── */

test("only fields the template consumes are submitted", () => {
    const rows = buildReviewRows(
        { sender_name: "Ayesha", court_name: "LHC" }, NOTICE_FIELDS);

    const out = toSubmittedFields(rows);
    assert.equal(out.sender_name, "Ayesha");
    assert.ok(!("court_name" in out), "an unusable field was sent to the builder");
});

test("blanks are omitted, not sent as empty strings", () => {
    // An empty string is a value the renderer prints — a heading with nothing
    // under it. An absent key lets pleading_rules report the field as missing,
    // which is true and is what the client should be told.
    const rows = buildReviewRows({ sender_name: "Ayesha" }, NOTICE_FIELDS);
    const out = toSubmittedFields(rows);

    assert.deepEqual(Object.keys(out), ["sender_name"]);
    assert.ok(!("demand" in out));
});

test("values are trimmed on the way out", () => {
    const rows = editRow(buildReviewRows({}, NOTICE_FIELDS),
                         "sender_name", "  Ayesha Khan  ");
    assert.equal(toSubmittedFields(rows).sender_name, "Ayesha Khan");
});

test("an edited value is what gets submitted", () => {
    const rows = buildReviewRows({ demand: "500000" }, NOTICE_FIELDS);
    const out = toSubmittedFields(editRow(rows, "demand", "50000"));
    assert.equal(out.demand, "50000", "the client's correction was discarded");
});

/* ── warn, never block ────────────────────────────────────────────────────── */

test("missing fields are reported by name", () => {
    const rows = buildReviewRows({ sender_name: "Ayesha" }, NOTICE_FIELDS);
    const missing = missingFields(rows);

    assert.ok(missing.includes("Demand"));
    assert.ok(!missing.includes("Sender name"));
});

test("blanks warn but never block generation", () => {
    // Requiredness is a legal question. `template_registry` refuses to carry a
    // per-field "required" flag rather than assert statutory requirements
    // nobody checked, and `pleading_rules` answers it server-side for the four
    // templates the CPC and the Guardians and Wards Act speak to. Blocking here
    // would invent the same requirement the registry declined to invent, with
    // less information.
    const rows = buildReviewRows({}, NOTICE_FIELDS);
    assert.equal(missingFields(rows).length, NOTICE_FIELDS.length);
    assert.equal(canGenerate(rows), true);
});

test("an unusable field is never reported as missing", () => {
    const rows = buildReviewRows({ court_name: "LHC" }, NOTICE_FIELDS);
    assert.ok(!missingFields(rows).includes("Court name"));
});
