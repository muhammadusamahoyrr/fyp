/* What the lawyer's Cases list shows, and how many: ONE derivation.
 *
 * WHY THIS EXISTS. The chip counts were computed next to the sections they
 * labelled, by separate expressions, and they drifted:
 *   * "New requests" and "Needs me" counted requests whose terms were already
 *     sent — the lawyer is waiting on the CLIENT there, nothing is theirs to do;
 *   * "All" counted closed cases that the All view does not show;
 *   * the Filter preview ("Showing N of M") counted closed cases and ignored
 *     the selected chip.
 * Every count here is the length of the rows its view renders, so a count and
 * its list cannot disagree.
 *
 * Pure: no React, no API. Cases are the page's mapped cases ({ id, title,
 * client, status label, nextHearing "YYYY-MM-DD", caseTypeKey, provinceKey,
 * createdAt }); requests are engagements as the API returns them.
 */

import { pktDayKey } from "./bookingTime.js";

export const CLOSED_LABELS = ["Closed", "Dismissed"];
/** Engagements still being negotiated. */
export const OPEN_REQUEST_STATUSES = ["requested", "terms_proposed"];

const byText = (k) => (a, b) => (a[k] || "").localeCompare(b[k] || "");
export const CASE_SORTERS = {
    // Cases with a date first, soonest first; then the rest by title.
    hearing: (a, b) => (!a.nextHearing - !b.nextHearing) || (a.nextHearing || "").localeCompare(b.nextHearing || "") || byText("title")(a, b),
    newest: (a, b) => (b.createdAt || "").localeCompare(a.createdAt || ""),
    title: byText("title"),
    client: byText("client"),
};
export const REQUEST_SORTERS = {
    hearing: (a, b) => (b.created_at || "").localeCompare(a.created_at || ""),
    newest: (a, b) => (b.created_at || "").localeCompare(a.created_at || ""),
    title: (a, b) => (a.case_title || "").localeCompare(b.case_title || ""),
    client: (a, b) => (a.client_name || "").localeCompare(b.client_name || ""),
};

/** The sections each chip renders, in display order. */
export const VIEW_SECTIONS = {
    all: ["newRequests", "awaitingClient", "notFiled", "active"],
    needs: ["newRequests", "notFiled", "outcomeDue"],
    requests: ["newRequests"],
    nohearing: ["notFiled"],
    active: ["active"],
    history: ["history"],
};

/**
 * @param {object} p
 * @param {string} p.today  PKT "YYYY-MM-DD" (passed in, so tests can freeze it)
 */
export function buildCasesView({ cases = [], requests = [], search = "", types = [], provinces = [],
                                 sortBy = "hearing", today }) {
    const q = String(search || "").trim().toLowerCase();
    const hit = (...xs) => !q || xs.some(x => String(x || "").toLowerCase().includes(q));
    const keepCase = (c) => (!types.length || types.includes(c.caseTypeKey))
        && (!provinces.length || provinces.includes(c.provinceKey));
    // A request carries no province, so a province filter cannot vouch for it.
    const keepRequest = (r) => (!types.length || types.includes(r.case_type)) && !provinces.length;
    const caseSort = CASE_SORTERS[sortBy] || CASE_SORTERS.hearing;
    const reqSort = REQUEST_SORTERS[sortBy] || REQUEST_SORTERS.hearing;

    const reqs = requests
        .filter(r => OPEN_REQUEST_STATUSES.includes(r.status))
        .filter(r => hit(r.case_title, r.case_number, r.client_name))
        .filter(keepRequest)
        .sort(reqSort);
    const shown = cases.filter(keepCase).filter(c => hit(c.title, c.id, c.client));
    const live = shown.filter(c => !CLOSED_LABELS.includes(c.status));

    const sections = {
        // Waiting on the LAWYER: a client asked, no terms sent yet.
        newRequests: reqs.filter(r => r.status === "requested"),
        // Terms sent: waiting on the CLIENT. Listed (the lawyer can withdraw),
        // never counted as something the lawyer must do.
        awaitingClient: reqs.filter(r => r.status === "terms_proposed"),
        notFiled: live.filter(c => !c.nextHearing).sort(caseSort),
        active: live.filter(c => c.nextHearing).sort(caseSort),
        history: shown.filter(c => CLOSED_LABELS.includes(c.status)).sort(caseSort),
    };
    // A hearing date that has passed with no outcome recorded.
    sections.outcomeDue = sections.active.filter(c => today && c.nextHearing.slice(0, 10) < today);

    const counts = {};
    for (const [view, keys] of Object.entries(VIEW_SECTIONS)) {
        counts[view] = keys.reduce((n, k) => n + sections[k].length, 0);
    }
    return { sections, counts };
}

/* ── "Recent & upcoming" on a case's Overview ─────────────────────────────
 *
 * It used to sort every hearing and task by date, LATEST first, and keep five:
 * tasks due next month pushed out a hearing tomorrow, and the most recent
 * held hearing lost to older ones only when the far future was empty.
 *
 * The rule:
 *   upcoming  (on or after today)  nearest first
 *   recent    (before today)       most recent first
 *   ties      hearings before tasks, then by title, then key
 *   slots     up to `upcomingSlots` (3) go to upcoming items, the rest to
 *             recent ones; if either side has fewer, the other fills in.
 *   order     upcoming first, then recent.
 * Items: { key, kind: "hearing" | "task", title, sort: "YYYY-MM-DD", ... }.
 */
const KIND_RANK = { hearing: 0, task: 1 };
const tieBreak = (a, b) => ((KIND_RANK[a.kind] ?? 9) - (KIND_RANK[b.kind] ?? 9))
    || String(a.title || "").localeCompare(String(b.title || ""))
    || String(a.key || "").localeCompare(String(b.key || ""));

export function selectFeed(items, today, { slots = 5, upcomingSlots = 3 } = {}) {
    const day = (x) => String(x.sort || "").slice(0, 10);
    const upcoming = items.filter(x => day(x) >= today)
        .sort((a, b) => day(a).localeCompare(day(b)) || tieBreak(a, b));
    const recent = items.filter(x => day(x) && day(x) < today)
        .sort((a, b) => day(b).localeCompare(day(a)) || tieBreak(a, b));
    let up = Math.min(upcoming.length, upcomingSlots);
    const back = Math.min(recent.length, slots - up);
    up = Math.min(upcoming.length, slots - back);      // unused recent slots go back to upcoming
    return [...upcoming.slice(0, up), ...recent.slice(0, back)];
}

/** Whole Pakistan calendar days from when a request was sent to `today`
 *  (PKT "YYYY-MM-DD"). It sliced the UTC date instead, so a request sent
 *  between 00:00 and 05:00 PKT read "1 day ago" on the day it was sent. */
export function requestAgeDays(createdAt, today) {
    const sent = pktDayKey(createdAt);
    if (!sent || !today) return null;
    const a = Date.parse(`${sent}T12:00:00Z`);
    const b = Date.parse(`${today}T12:00:00Z`);
    return Number.isNaN(a) || Number.isNaN(b) ? null : Math.round((b - a) / 86400000);
}
