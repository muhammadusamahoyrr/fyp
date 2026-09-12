/**
 * How much of an uploaded file the analysis actually read — in words.
 *
 * One place, because this wording is a promise. The UI previously showed a file
 * name and a size, which said nothing about whether the analysis had seen the
 * document or only its cover sheet. A client who is told "3 of 5 pages produced
 * no text" knows what to retype; one who is told nothing assumes it was read.
 *
 * SIX STATES, KEPT APART ON PURPOSE
 *
 *   pending       not analysed yet — extraction runs at conversion
 *   complete      the whole document was read
 *   partial       some of it reached the analysis, some did not
 *   unreadable    none of it did
 *   storage_only  kept and downloadable, but no extractor can ever read it
 *   error         the upload itself failed
 *
 * Collapsing any two of these loses something the client needs. `storage_only`
 * is not `unreadable`: nothing is wrong with the file and re-uploading the same
 * format will not help. `pending` is not `complete`: nothing has been read yet.
 * `error` is not `unreadable`: the bytes never arrived at all.
 *
 * TWO THINGS THIS DELIBERATELY NEVER SAYS
 *
 * 1. That a page is a scan. We cannot tell a scanned page from a blank one, and
 *    a label that guesses is worse than one that admits the gap.
 * 2. That a file is fine before extraction has run.
 */

export const TONE_OK = "ok";
export const TONE_WARN = "warn";
export const TONE_BAD = "bad";
export const TONE_NEUTRAL = "neutral";

export const STATE_PENDING = "pending";
export const STATE_COMPLETE = "complete";
export const STATE_PARTIAL = "partial";
export const STATE_UNREADABLE = "unreadable";
export const STATE_STORAGE_ONLY = "storage_only";
export const STATE_ERROR = "error";

/** Every state a file can be shown in. Used by tests to prove none collapse. */
export const ALL_STATES = [
    STATE_PENDING, STATE_COMPLETE, STATE_PARTIAL,
    STATE_UNREADABLE, STATE_STORAGE_ONLY, STATE_ERROR,
];

/** Pages that yielded nothing, as a phrase, or "" when everything yielded text. */
function unreadPages(ef) {
    const total = Number(ef?.pages_total);
    const withText = Number(ef?.pages_with_text);
    if (!Number.isFinite(total) || !Number.isFinite(withText)) return "";
    if (total <= 0 || withText >= total) return "";
    return `${total - withText} of ${total} page${total === 1 ? "" : "s"} produced no text`;
}

function detailFor(ef) {
    const bits = [];
    const unread = unreadPages(ef);
    if (unread) bits.push(unread);

    const skipped = Number(ef?.pages_skipped);
    if (Number.isFinite(skipped) && skipped > 0) {
        bits.push(`${skipped} not processed`);
    }
    const failed = Number(ef?.pages_failed);
    if (Number.isFinite(failed) && failed > 0) {
        bits.push(`${failed} could not be read`);
    }
    for (const note of ef?.limitations || []) {
        if (typeof note === "string" && note.startsWith("unsupported_part:")) {
            bits.push(`${note.slice("unsupported_part:".length)} not read`);
        }
    }
    return bits.join(" · ");
}

/**
 * @returns {{state: string, tone: string, title: string, detail: string}}
 *   Always an object — every file is in exactly one of the six states.
 */
export function extractionLabel(ef) {
    // Checked before anything else: a file whose upload failed has no bytes on
    // the server, so nothing downstream applies to it.
    if (ef?.error) {
        return {
            state: STATE_ERROR, tone: TONE_BAD, title: "Upload failed",
            detail: typeof ef.error === "string" ? ef.error : "",
        };
    }
    if (ef?.uploading) {
        return {
            state: STATE_PENDING, tone: TONE_NEUTRAL, title: "Uploading…",
            detail: "",
        };
    }
    // Known at upload, before any extraction: the format can never be read.
    if (ef?.analysis_support === "storage_only") {
        return {
            state: STATE_STORAGE_ONLY, tone: TONE_WARN,
            title: "Stored, not analysed",
            detail: typeof ef.notice === "string" && ef.notice
                ? ef.notice
                : "this format cannot be read for analysis",
        };
    }

    const status = ef?.extraction_status;
    if (!status) {
        return {
            state: STATE_PENDING, tone: TONE_NEUTRAL, title: "Not analysed yet",
            detail: "",
        };
    }

    switch (status) {
        case "readable":
            // Only ever set when the extractor judged the whole document read.
            return { state: STATE_COMPLETE, tone: TONE_OK, title: "Read in full", detail: "" };

        case "partially_read":
            return {
                state: STATE_PARTIAL, tone: TONE_WARN, title: "Partially read",
                detail: detailFor(ef) || "some of this document could not be read",
            };

        case "omitted_limit":
            // Extracted fine; the analysis simply had no room for it. Fixable by
            // removing another file, unlike anything else in this list — so it
            // must not be collapsed into "could not be read".
            return {
                state: STATE_PARTIAL, tone: TONE_WARN,
                title: "Not included in the analysis",
                detail: "the analysis reached its length limit",
            };

        case "missing":
            return {
                state: STATE_UNREADABLE, tone: TONE_BAD, title: "File not found",
                detail: "it is recorded but missing from storage",
            };

        case "invalid_path":
            return {
                state: STATE_UNREADABLE, tone: TONE_BAD,
                title: "Could not be read", detail: "",
            };

        case "unreadable":
            return {
                state: STATE_UNREADABLE, tone: TONE_BAD, title: "Could not be read",
                detail: detailFor(ef) || "no text could be extracted from this file",
            };

        default:
            // An unknown status is reported as unknown. Guessing here would mean
            // inventing a reassurance for a state we do not understand.
            return {
                state: STATE_UNREADABLE, tone: TONE_WARN,
                title: "Read status unknown", detail: "",
            };
    }
}

/** True when the analysis did not see all of this file's readable content. */
export function isIncomplete(ef) {
    const { state } = extractionLabel(ef);
    return state === STATE_PARTIAL || state === STATE_UNREADABLE
        || state === STATE_STORAGE_ONLY;
}

/**
 * Files the client should be told about on the ANALYSIS screen.
 *
 * `pending` is excluded: nothing has been analysed yet, so there is no gap to
 * report. `error` is excluded too — the file never reached the server, so it is
 * not a hole in the evidence the analysis used.
 */
export function incompleteFiles(files) {
    return (Array.isArray(files) ? files : []).filter(isIncomplete);
}

/** True once extraction has run for this file, whatever the outcome. */
export function isAnalysed(ef) {
    const { state } = extractionLabel(ef);
    return state !== STATE_PENDING && state !== STATE_ERROR;
}
