/* The lawyer pages' date and time formatters.
 *
 * WHAT WAS WRONG. fmtTime("00:30") read "0:30 AM", and fmtDate used the
 * browser's time zone, so a hearing stored as midnight UTC of its day showed
 * as the previous day in any zone west of UTC.
 */
import test from "node:test";
import assert from "node:assert/strict";

const { fmtDate, fmtTime } = await import("../src/components/lawyer/data.js");

test("12-hour times are right at midnight and noon", () => {
    assert.equal(fmtTime("00:30"), "12:30 AM");
    assert.equal(fmtTime("00:00"), "12:00 AM");
    assert.equal(fmtTime("09:05"), "9:05 AM");
    assert.equal(fmtTime("12:00"), "12:00 PM");
    assert.equal(fmtTime("13:30"), "1:30 PM");
    assert.equal(fmtTime("23:59"), "11:59 PM");
    assert.equal(fmtTime(""), "");
    assert.equal(fmtTime("soon"), "soon", "an unreadable value is shown as written, not as NaN");
});

test("a stored hearing day is that day, whatever the browser's zone", () => {
    const out = fmtDate("2026-11-20T00:00:00Z");
    assert.match(out, /20/);
    assert.match(out, /Nov/);
    assert.equal(fmtDate(null), "—");
    assert.equal(fmtDate("not a date"), "—");
});
