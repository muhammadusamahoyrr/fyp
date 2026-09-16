/**
 * Appointment times are Pakistan times.
 *
 * The browser's zone is not the booking zone, and on this product they are the
 * same thing only by luck. Two defects came out of treating them as one:
 *
 *   - `new Date().toISOString().split("T")[0]` is the UTC calendar date. Between
 *     00:00 and 05:00 PKT that is YESTERDAY, so the booking modal opened on a
 *     past date and the picker's `min` allowed a day already gone.
 *   - `new Date("2026-09-20T10:00:00")` — no offset — is parsed by JS as the
 *     BROWSER's local time. On a laptop set to any other zone the client booked
 *     an instant they never chose.
 *
 * Everything here names Asia/Karachi explicitly so neither depends on where the
 * machine thinks it is.
 */

export const BOOKING_TZ = "Asia/Karachi";

/**
 * Pakistan's UTC offset, as an ISO suffix.
 *
 * A fixed constant is correct rather than lazy: Pakistan abolished DST in 2009
 * and PKT has been UTC+5 year-round since, so there is no gap or fold for a
 * wall-clock time to fall into. If that ever changes this constant is the one
 * place that has to know, and `pktToday` below does not depend on it at all.
 */
export const PKT_OFFSET = "+05:00";

/** Today's date in Pakistan, as YYYY-MM-DD. */
export function pktToday(now = new Date()) {
    // en-CA formats as YYYY-MM-DD, which is the value a <input type="date">
    // wants. Deriving it through Intl rather than from PKT_OFFSET means the
    // day boundary stays right even if the offset constant ever goes stale.
    return new Intl.DateTimeFormat("en-CA", {
        timeZone: BOOKING_TZ,
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
    }).format(now);
}

/**
 * A picked date + time, read as Pakistan wall-clock, as a Date.
 * Returns null when either half is missing or unparseable.
 */
export function pktSlotToDate(dateStr, timeStr) {
    if (!dateStr || !timeStr) return null;
    const d = new Date(`${dateStr}T${timeStr}:00${PKT_OFFSET}`);
    return Number.isNaN(d.getTime()) ? null : d;
}

/**
 * The same slot as the UTC instant the API is given.
 *
 * The server refuses a timestamp with no offset (it cannot know what was meant),
 * so this always produces one.
 */
export function pktSlotToUtcISO(dateStr, timeStr) {
    const d = pktSlotToDate(dateStr, timeStr);
    return d ? d.toISOString() : null;
}

/** True when the slot is in the past. */
export function isPktSlotPast(dateStr, timeStr, now = new Date()) {
    const d = pktSlotToDate(dateStr, timeStr);
    return d ? d.getTime() <= now.getTime() : false;
}

/**
 * The Pakistan calendar day an instant falls on, as YYYY-MM-DD.
 *
 * Grouping and counting need this, not just display. Formatting an appointment
 * correctly while deciding whether it is "today" with the browser's own
 * `toDateString()` puts a 23:00 PKT appointment on the wrong day for anyone
 * outside PKT — the card reads right and the "Today" tally is still wrong.
 */
export function pktDayKey(value) {
    if (!value) return "";
    const d = value instanceof Date ? value : new Date(value);
    return Number.isNaN(d.getTime()) ? "" : pktToday(d);
}

/** True when two instants fall on the same Pakistan day. */
export function isSamePktDay(a, b) {
    const ka = pktDayKey(a);
    return ka !== "" && ka === pktDayKey(b);
}

/** True when an instant falls on today's Pakistan day. */
export function isPktToday(value, now = new Date()) {
    return isSamePktDay(value, now);
}

/**
 * The seven Pakistan day keys (Mon–Sun) of the week containing `now`.
 *
 * A calendar column is a CALENDAR DAY, not an instant, so these are day-key
 * strings rather than Dates. Building them from `new Date()` and comparing with
 * `toDateString()` mixed the two: the column headers came from the browser's
 * week while the appointments in them were being placed by a different clock.
 */
export function pktWeekDayKeys(now = new Date()) {
    // Noon UTC on the PKT day, so adding and subtracting days is pure calendar
    // arithmetic that no offset can push across a boundary.
    const anchor = new Date(`${pktToday(now)}T12:00:00Z`);
    const mondayOffset = (anchor.getUTCDay() + 6) % 7;
    return Array.from({ length: 7 }, (_, i) => {
        const d = new Date(anchor);
        d.setUTCDate(anchor.getUTCDate() - mondayOffset + i);
        return d.toISOString().slice(0, 10);
    });
}

/** The day-of-month shown on a calendar column, from a day key. */
export function dayOfMonth(dayKey) {
    return dayKey ? Number(dayKey.slice(8, 10)) : NaN;
}

/** An instant's Pakistan hour, 0-23, for slotting into an hourly grid. */
export function pktHour(value) {
    const hm = pktHourMinute(value);
    return hm ? Number(hm.slice(0, 2)) : NaN;
}

/** An instant's Pakistan wall-clock time as "HH:MM", for slot keys. */
export function pktHourMinute(value) {
    if (!value) return "";
    const d = value instanceof Date ? value : new Date(value);
    if (Number.isNaN(d.getTime())) return "";
    return new Intl.DateTimeFormat("en-GB", {
        timeZone: BOOKING_TZ, hour: "2-digit", minute: "2-digit", hour12: false,
    }).format(d);
}

/**
 * An instant from the API rendered as Pakistan wall-clock time.
 *
 * Used wherever a stored `scheduled_at` is shown, so a lawyer and a client
 * reading the same appointment read the same clock face.
 */
export function formatPkt(value, opts = {}) {
    if (!value) return "";
    const d = value instanceof Date ? value : new Date(value);
    if (Number.isNaN(d.getTime())) return "";
    return new Intl.DateTimeFormat("en-PK", { timeZone: BOOKING_TZ, ...opts }).format(d);
}
