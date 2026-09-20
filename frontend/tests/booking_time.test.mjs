/**
 * Appointment times are Pakistan times, not the browser's.
 *
 * Two defects are pinned here.
 *
 * `new Date().toISOString().split("T")[0]` is the UTC calendar date. Between
 * 00:00 and 05:00 PKT that is the PREVIOUS day, so the booking modal opened on
 * a date already gone and the picker's `min` allowed selecting it. The window
 * is five hours wide, every night — not an edge case anyone would notice from
 * a daytime demo.
 *
 * `new Date("2026-09-20T15:00:00")` — no offset — is parsed as the BROWSER's
 * local time. The value then sent to the server was whatever instant that
 * happened to mean on that machine, which is only the client's intended time on
 * a laptop that is already set to PKT.
 */
import test from "node:test";
import assert from "node:assert/strict";

import {
    BOOKING_TZ,
    PKT_OFFSET,
    pktToday,
    pktSlotToDate,
    pktSlotToUtcISO,
    isPktSlotPast,
    formatPkt,
    pktDayKey,
    isSamePktDay,
    isPktToday,
    pktHourMinute,
    pktHour,
    pktWeekDayKeys,
    dayOfMonth,
} from "../src/lib/bookingTime.js";

test("the booking zone is Pakistan and its offset has no DST", () => {
    assert.equal(BOOKING_TZ, "Asia/Karachi");
    // Pakistan abolished DST in 2009. A fixed offset is correct here, and this
    // asserts the assumption rather than leaving it in a comment.
    assert.equal(PKT_OFFSET, "+05:00");
    const jan = new Date("2026-01-15T12:00:00Z");
    const jul = new Date("2026-07-15T12:00:00Z");
    const hour = d => formatPkt(d, { hour: "2-digit", hour12: false });
    assert.equal(hour(jan), hour(jul), "PKT must not shift across the year");
});

test("today is the Pakistan date, not the UTC one", () => {
    // 21:00 UTC on the 20th is 02:00 PKT on the 21st. The old code reported the
    // 20th — a date the client could no longer book.
    const lateUtc = new Date("2026-09-20T21:00:00Z");
    assert.equal(pktToday(lateUtc), "2026-09-21");
});

test("the Pakistan date is stable through the rest of the day", () => {
    assert.equal(pktToday(new Date("2026-09-20T06:00:00Z")), "2026-09-20");
    assert.equal(pktToday(new Date("2026-09-20T18:59:00Z")), "2026-09-20");
});

test("a picked slot is read as Pakistan wall-clock time", () => {
    // 15:00 in Karachi is 10:00Z. Not 15:00Z, and not 15:00 wherever the
    // browser happens to be.
    assert.equal(pktSlotToUtcISO("2026-09-20", "15:00"), "2026-09-20T10:00:00.000Z");
});

test("an early-morning slot belongs to the previous UTC day", () => {
    // The instant the availability window used to miss entirely.
    assert.equal(pktSlotToUtcISO("2026-09-20", "02:00"), "2026-09-19T21:00:00.000Z");
});

test("the value sent to the server always carries an offset", () => {
    // The server refuses an offsetless timestamp with a 422, because it cannot
    // know what was meant. This must never produce one.
    const iso = pktSlotToUtcISO("2026-09-20", "09:00");
    assert.match(iso, /(Z|[+-]\d{2}:\d{2})$/);
});

test("an incomplete selection is not an instant", () => {
    for (const [d, t] of [["", "10:00"], ["2026-09-20", ""], [null, null]]) {
        assert.equal(pktSlotToDate(d, t), null);
        assert.equal(pktSlotToUtcISO(d, t), null);
    }
});

test("a slot is past or future by Pakistan time", () => {
    const now = new Date("2026-09-20T10:00:00Z"); // 15:00 PKT
    assert.equal(isPktSlotPast("2026-09-20", "14:00", now), true);
    assert.equal(isPktSlotPast("2026-09-20", "16:00", now), false);
});

test("a slot exactly now counts as past", () => {
    const now = new Date("2026-09-20T10:00:00Z");
    assert.equal(isPktSlotPast("2026-09-20", "15:00", now), true);
});

test("an incomplete selection is not reported as past", () => {
    // Guarding the empty modal: nothing is chosen yet, so nothing is expired,
    // and the grid must not render every slot struck through.
    assert.equal(isPktSlotPast("", "", new Date()), false);
});

test("a stored instant displays as the Pakistan clock face it was booked at", () => {
    // The refresh bug: booked at 15:00 PKT, shown as 10:00 after a reload
    // because the stored value came back without an offset and was read local.
    const shown = formatPkt("2026-09-20T10:00:00Z", {
        hour: "2-digit", minute: "2-digit", hour12: false,
    });
    assert.match(shown, /15:00/);
});

test("an offset-bearing instant and its UTC equivalent display identically", () => {
    const opts = { hour: "2-digit", minute: "2-digit", hour12: false };
    assert.equal(
        formatPkt("2026-09-20T15:00:00+05:00", opts),
        formatPkt("2026-09-20T10:00:00Z", opts),
    );
});

test("a missing or unparseable instant renders as nothing, not as Invalid Date", () => {
    assert.equal(formatPkt(null), "");
    assert.equal(formatPkt(""), "");
    assert.equal(formatPkt("not a date"), "");
});

// ── Grouping and counting, not just display ─────────────────────────────────
//
// Formatting a card correctly while deciding which DAY it belongs to with the
// browser's own clock is the subtler half of the same bug: the card reads right
// and the "Today" tally beside it is still wrong.

test("the day an instant belongs to is its Pakistan day", () => {
    // 21:00Z on the 19th is 02:00 PKT on the 20th. The browser in UTC would
    // group this under the 19th.
    assert.equal(pktDayKey("2026-09-19T21:00:00Z"), "2026-09-20");
    // 18:00Z on the 20th is 23:00 PKT the same day.
    assert.equal(pktDayKey("2026-09-20T18:00:00Z"), "2026-09-20");
});

test("two instants five hours apart can share one Pakistan day", () => {
    assert.equal(isSamePktDay("2026-09-19T21:00:00Z", "2026-09-20T18:00:00Z"), true);
});

test("an instant is today by the Pakistan calendar", () => {
    const now = new Date("2026-09-20T02:00:00Z"); // 07:00 PKT on the 20th
    assert.equal(isPktToday("2026-09-19T21:00:00Z", now), true, "02:00 PKT on the 20th is today");
    assert.equal(isPktToday("2026-09-19T10:00:00Z", now), false);
});

test("a missing instant belongs to no day and is not today", () => {
    assert.equal(pktDayKey(null), "");
    assert.equal(pktDayKey("not a date"), "");
    assert.equal(isSamePktDay(null, null), false, "two unknowns are not the same day");
    assert.equal(isPktToday(null), false);
});

test("slot keys are Pakistan wall-clock, zero-padded, 24-hour", () => {
    assert.equal(pktHourMinute("2026-09-20T10:00:00Z"), "15:00");
    assert.equal(pktHourMinute("2026-09-19T21:30:00Z"), "02:30");
    assert.equal(pktHour("2026-09-19T21:30:00Z"), 2);
});

test("the calendar week is seven Pakistan days, Monday first", () => {
    // 2026-09-20 is a Sunday, so its Monday-first week starts on the 14th.
    const keys = pktWeekDayKeys(new Date("2026-09-20T06:00:00Z"));
    assert.equal(keys.length, 7);
    assert.equal(keys[0], "2026-09-14");
    assert.equal(keys[6], "2026-09-20");
});

test("the calendar week is taken from the Pakistan day, not the UTC one", () => {
    // 21:00Z Sunday is already Monday 02:00 in Karachi — a new week.
    const keys = pktWeekDayKeys(new Date("2026-09-20T21:00:00Z"));
    assert.equal(keys[0], "2026-09-21", "the PKT week had already rolled over");
});

test("a week spanning a month boundary still numbers its columns correctly", () => {
    const keys = pktWeekDayKeys(new Date("2026-10-01T06:00:00Z")); // Thursday
    assert.equal(keys[0], "2026-09-28");
    assert.equal(dayOfMonth(keys[0]), 28);
    assert.equal(dayOfMonth(keys[3]), 1, "1 October, not 31 September");
});
