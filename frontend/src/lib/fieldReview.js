/* What the AI pulled out of your case, before it becomes a legal document.
 *
 * Generation used to run extraction and rendering back to back:
 *
 *     const fields = extractRes.data?.fields || {};
 *     const viaV2  = await _generateViaV2({ caseId, backendType, fields, ... });
 *
 * A model reads a client's free-text description and decides who the parties
 * are, what the amounts are, which dates matter — and those values went into a
 * plaint or a legal notice without the client ever seeing them. The "User
 * Review" step reviews the finished PDF, and finding a wrong figure in three
 * formatted pages is a different task from seeing `demand: 500000` in a list.
 *
 * This is the last point where a mistake is cheap. After generation it is an
 * immutable revision; after submission it is in a lawyer's queue.
 *
 * The backend always expected this. `DocumentExtractResult` is documented as
 * "Step-1 extraction preview shown to the user for review/edit", the quick-notice
 * route takes `fields` as "user-reviewed overrides", and every generation path
 * re-runs `pleading_rules.check_pleading` on the fields it is handed. Only the
 * client skipped the step.
 */

/* Words that should not be sentence-cased when a field name becomes a label.
 *
 * `no` is deliberately absent. It is short for "number" in `fir_no` and
 * `case_no`, and upper-casing it gives "FIR NO", which reads as the word "no"
 * shouted — the opposite of what the field means. */
const ACRONYMS = new Set([
    "fir", "cnic", "ntn", "cpc", "ppc", "poa", "nic", "id", "url",
]);

/** `recipient_address` -> "Recipient address"; `fir_no` -> "FIR no". */
export function humanise(name) {
    const words = String(name || "").split(/[_\s]+/).filter(Boolean);
    if (!words.length) return "";
    return words
        .map((w, i) => {
            if (ACRONYMS.has(w.toLowerCase())) return w.toUpperCase();
            return i === 0 ? w.charAt(0).toUpperCase() + w.slice(1) : w.toLowerCase();
        })
        .join(" ");
}

/* A value the model returned but which carries no information. Treated as
 * "not found" so the client is asked for it rather than shown a blank they
 * might read as deliberate. */
function isBlank(value) {
    return value === null || value === undefined ||
        (typeof value === "string" && value.trim() === "");
}

export const EXTRACTED = "extracted";
export const EMPTY = "empty";
export const UNUSED = "unused";

/**
 * One row per field, in the order the template declares them.
 *
 * THREE STATES, and the third is the one a careless version would hide:
 *
 *   extracted — the model found a value. Shown, editable.
 *   empty     — the template wants this field and the model found nothing.
 *               Shown empty rather than omitted: a field silently absent from
 *               the form is a field silently absent from the document.
 *   unused    — the model returned a key this template does not consume. The
 *               builder will drop it. Saying so is the difference between a
 *               value the client chose not to use and one the system threw
 *               away without telling them.
 *
 * @param {object} extracted       fields as returned by /documents/extract
 * @param {string[]} templateFields the template's own field list, from the
 *                                  catalogue — the server's truth, not a
 *                                  hardcoded copy
 */
export function buildReviewRows(extracted, templateFields) {
    const values = extracted && typeof extracted === "object" ? extracted : {};
    const declared = Array.isArray(templateFields) ? templateFields : [];

    const rows = declared.map(name => {
        const raw = values[name];
        return {
            name,
            label: humanise(name),
            value: isBlank(raw) ? "" : String(raw),
            status: isBlank(raw) ? EMPTY : EXTRACTED,
            used: true,
        };
    });

    const extra = Object.keys(values)
        .filter(name => !declared.includes(name) && !isBlank(values[name]))
        .sort()
        .map(name => ({
            name,
            label: humanise(name),
            value: String(values[name]),
            status: UNUSED,
            used: false,
        }));

    return [...rows, ...extra];
}

/**
 * The dict to send to generation.
 *
 * Only fields the template actually consumes, and only non-blank ones. A blank
 * is omitted rather than sent as "", because an empty string is a value the
 * renderer would print — a heading followed by nothing — where an absent key
 * lets `pleading_rules` report the field as missing, which is true and is what
 * the client should be told.
 */
export function toSubmittedFields(rows) {
    const out = {};
    for (const row of rows || []) {
        if (!row.used) continue;
        const value = typeof row.value === "string" ? row.value.trim() : row.value;
        if (isBlank(value)) continue;
        out[row.name] = value;
    }
    return out;
}

/** Rows the template needs and still has no value. Never blocks — see below. */
export function missingFields(rows) {
    return (rows || []).filter(r => r.used && isBlank(r.value)).map(r => r.label);
}

/**
 * Whether generation may proceed.
 *
 * ALWAYS TRUE, deliberately. Requiredness is a legal question about a
 * particular instrument, and `template_registry` refuses to carry a per-field
 * "required" flag precisely because inventing one for twenty-two templates
 * would assert statutory requirements nobody checked. `pleading_rules` answers
 * it properly for the four templates the CPC and the Guardians and Wards Act
 * actually speak to, and it runs server-side on whatever is submitted.
 *
 * So the client is WARNED about blanks and never blocked by them. A hard block
 * here would be this module inventing the same requirement the registry
 * declined to invent, in a place with less information.
 */
export function canGenerate() {
    return true;
}

/** Replace one row's value, returning a new array. */
export function editRow(rows, name, value) {
    return (rows || []).map(r => (r.name === name ? { ...r, value } : r));
}

/** True when the client changed anything the model proposed. */
export function hasEdits(rows, extracted) {
    const values = extracted && typeof extracted === "object" ? extracted : {};
    return (rows || []).some(r => {
        const original = isBlank(values[r.name]) ? "" : String(values[r.name]);
        return String(r.value ?? "") !== original;
    });
}
