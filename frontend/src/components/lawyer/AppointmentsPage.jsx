'use client';
import { useState, useEffect, useCallback, useRef, forwardRef, useMemo } from "react";
import {
    formatPkt, isPktToday, pktHourMinute, pktDayKey, pktSlotToUtcISO,
    pktMonthGridKeys, pktWeekDayKeys, shiftMonth, pktToday, dayOfMonth,
} from "@/lib/bookingTime.js";
import { useTheme, ThemeCtx } from "./theme.js";
import { DRAFTING_TOKENS_CSS, draftingMode, themeOnTokens } from "./draftingTheme.js";
import { useNotif, useCase } from "./theme.js";
import { onNotification } from "@/lib/notificationTarget.js";
import { useToast } from "@/components/lawyer/Toast.jsx";
import { Card, Btn } from "./components.jsx";
import { Icon, I } from "./icons.jsx";
import {
    listAppointments,
    confirmAppointment as apiConfirm,
    cancelAppointment as apiCancel,
    completeAppointment as apiComplete,
    listPendingOutcomes,
    getMyWorkingHours,
    saveMyWorkingHours,
    markNoShow as apiNoShow,
    setMeetingLink as apiSetMeetingLink,
    listLawyerEvents,
    createLawyerEvent,
    deleteLawyerEvent,
    listCases,
} from "@/lib/api.js";
import { listAllCases } from "@/lib/allCases.js";

// ============================================================
// APPOINTMENTS PAGE
// ============================================================

// How often the page re-reads the clock. Time-based controls (Accept, No Show,
// Done) each become available or unavailable at an instant the server also
// knows about, and nothing else on the page would trigger a re-render when
// that instant arrives — so without this a lawyer sits in front of a stale
// button until some unrelated state change happens to repaint it.
//
// Thirty seconds is chosen against the cost of being wrong, not for precision:
// every one of these controls is re-validated by the server, so the only
// consequence of a late tick is a button that turns on up to half a minute
// after it could have.
export const CLOCK_TICK_MS = 30000;

/** An appointment's end, preferring the server's stored value.
 *
 * `end_at` is authoritative — the backend compares against that stored field
 * when deciding whether a consultation may be completed. The duration
 * arithmetic is only for a response that does not carry it (a row written
 * before the field existed, or a malformed payload), and it is a reconstruction
 * rather than a cross-check: where the two disagree, the server's value is the
 * one the server will enforce.
 */
export function endOf(a) {
    if (!a) return null;
    if (a.end_at) {
        const parsed = new Date(a.end_at);
        if (!Number.isNaN(parsed.getTime())) return parsed;
    }
    if (!a.scheduled_at) return null;
    const start = new Date(a.scheduled_at);
    if (Number.isNaN(start.getTime())) return null;
    return new Date(start.getTime() + (a.duration_minutes || 0) * 60000);
}

const CAL_DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
// The calendar reads every appointment, not the list's current tab and page:
// a month that silently stopped at the first page would look empty when it is
// not. Bounded, and said so on screen when the bound is reached.
const CAL_PAGE_SIZE = 50;     // the server's maximum page size
const CAL_MAX_PAGES = 20;
// A PAKISTAN day, not the browser's. Display was fixed first; grouping and
// the "Today" tally read the same instant through a different clock and so
// could still disagree with the card right next to them.
const _isToday = (d) => isPktToday(d);

// ── Status badge styles — high contrast, clearly visible ─────
const STATUS_STYLES = {
    Upcoming: { bg: "rgba(56,216,196,0.18)", color: "#38d8c4", border: "rgba(56,216,196,0.55)", dot: "#38d8c4" },
    Pending: { bg: "rgba(232,184,75,0.18)", color: "#e8b84b", border: "rgba(232,184,75,0.55)", dot: "#e8b84b" },
    Completed: { bg: "rgba(62,201,154,0.18)", color: "#3ec99a", border: "rgba(62,201,154,0.55)", dot: "#3ec99a" },
    Cancelled: { bg: "rgba(232,82,106,0.18)", color: "#e8526a", border: "rgba(232,82,106,0.55)", dot: "#e8526a" },
    // Distinct from Cancelled on purpose. A cancellation is an appointment that
    // was called off; a no-show is one the client failed to attend. Without its
    // own entry the badge falls through to `STATUS_STYLES.Upcoming` below and a
    // no-show would render in the teal reserved for a live upcoming booking.
    "No Show": { bg: "rgba(158,142,205,0.18)", color: "#9e8ecd", border: "rgba(158,142,205,0.55)", dot: "#9e8ecd" },
    // A request that lapsed before it was answered. Muted and grey, because it
    // is over and nobody acted: it is not a cancellation (no one called it
    // off), not a no-show (nobody failed to attend), and emphatically not
    // Upcoming, which is what it would render as without an entry here.
    Expired: { bg: "rgba(148,158,175,0.16)", color: "#94a2af", border: "rgba(148,158,175,0.5)", dot: "#94a2af" },
    // A status this build does not know — a newer server, or a row written by
    // something else. Shown as itself rather than dressed up as one of the
    // above; see the fallback in `StatusBadge`.
    Unknown: { bg: "rgba(148,158,175,0.12)", color: "#94a2af", border: "rgba(148,158,175,0.4)", dot: "#94a2af" },
};

// Statuses that mean the appointment did not take place. Grouped because the
// "today" and calendar views must exclude both: a no-show is no more a session
// on the day's schedule than a cancellation is. They were already excluded when
// `no_show` was mislabelled "Cancelled"; naming the set keeps that true now that
// the two are distinct.
// Expired belongs here for the same reason: an unanswered request that lapsed
// is not a session on the day's schedule, and counting it as one would tell a
// lawyer their day is busier than it is.
const DID_NOT_HAPPEN = new Set(["Cancelled", "No Show", "Expired"]);


function StatusBadge({ status }) {
    // Neutral, not Upcoming — but DEFENCE IN DEPTH ONLY, and worth being
    // straight about: this branch is currently unreachable. The single caller
    // passes a status produced by `mapApiAppt`, whose range is
    // closed and every member of which has an entry above, including its own
    // "Unknown" fallback. That mapper is where the real fix lives.
    //
    // It stays because the two lines have to agree, and the failure if they
    // ever stop agreeing is a row wearing the teal reserved for a live
    // booking — the one reading a lawyer acts on.
    const s = STATUS_STYLES[status] || STATUS_STYLES.Unknown;
    return (
        <span style={{
            display: "inline-flex", alignItems: "center", gap: 5,
            padding: "4px 11px", borderRadius: 999,
            background: s.bg, color: s.color,
            border: `1.5px solid ${s.border}`,
            fontSize: 11.5, fontWeight: 700, whiteSpace: "nowrap",
            boxShadow: `0 0 8px ${s.dot}30`,
        }}>
            <span style={{ width: 6, height: 6, borderRadius: "50%", background: s.dot, flexShrink: 0, boxShadow: `0 0 4px ${s.dot}` }} />
            {status}
        </span>
    );
}

// ── Stat card ─────────────────────────────────────────────────
/** Consultations this lawyer has finished and never reported an outcome for.
 *
 * READ FROM THE SERVER, NOT FILTERED FROM THE PAGE. The list above fetches
 * fifty appointments and never asks for a second page, so a filter over it
 * would show a backlog that stops exactly where that page ends — and the whole
 * point of this queue is the rows that have fallen off the end of a list
 * nobody scrolls. It has its own endpoint, its own cursor, and its own paging.
 *
 * THREE STATES, KEPT APART. "Loading", "nothing to do" and "we could not ask"
 * look identical if they share a branch, and the third silently becomes the
 * second — a lawyer is told their queue is clear when in fact the request
 * failed. `apiFetch` RESOLVES on failure with `{data: null, error}` rather than
 * throwing, so an unchecked `data?.items || []` renders a confident empty list
 * out of a network error. Each state is therefore its own branch here.
 *
 * Recording an outcome goes through the SAME guarded endpoints the cards above
 * use, and the queue is then re-read from the server rather than patched
 * locally: the server decides whether the transition happened, and a row that
 * failed to move must stay in the queue.
 */
function NeedsOutcome({ t, onRecorded }) {
    const [state, setState] = useState("loading");   // loading | ready | error
    const [items, setItems] = useState([]);
    const [cursor, setCursor] = useState(null);
    const [busyId, setBusyId] = useState(null);
    const [loadingMore, setLoadingMore] = useState(false);
    const [moreError, setMoreError] = useState(null);
    // Why the last record was refused. It used to re-read silently, so a
    // lawyer clicking Done saw the row stay and nothing to say why.
    const [recordError, setRecordError] = useState(null);

    /** Re-read from the first page.
     *
     * Deliberately not an incremental patch of local state. A recorded outcome
     * removes a row from the SERVER'S queue, and re-reading is the only way to
     * see the queue the server now has — including the row that moved up from
     * a page this client had not reached.
     */
    const load = useCallback(async () => {
        setState("loading");
        const { data, error } = await listPendingOutcomes({ page_size: 25 });
        if (error || !data) {
            // NOT an empty queue. Saying "nothing to do" here would tell a
            // lawyer their record is clear on the strength of a failed read.
            setState("error");
            return;
        }
        setItems(data.items || []);
        setCursor(data.next_cursor || null);
        setState("ready");
    }, []);

    useEffect(() => { load(); }, [load]);

    const loadMore = async () => {
        if (!cursor || loadingMore) return;
        setMoreError(null);
        setLoadingMore(true);
        const { data, error } = await listPendingOutcomes({ page_size: 25, cursor });
        setLoadingMore(false);
        if (error || !data) {
            setMoreError(error?.message || "Could not load more outcomes. Please try again.");
            return;                          // the rows already shown stay
        }
        setItems(prev => [...prev, ...(data.items || [])]);
        setCursor(data.next_cursor || null);
    };

    const record = async (id, action) => {
        setBusyId(id);
        setRecordError(null);
        const { error } = action === "complete"
            ? await apiComplete(id)
            : await apiNoShow(id);
        setBusyId(null);
        if (error) {
            // The server refused — a stale row, or one already dealt with in
            // another tab. Re-read rather than guess: the row may still belong
            // in the queue, and removing it here would hide it for ever.
            await load();
            setRecordError(error.message || "That outcome could not be recorded. The list has been refreshed.");
            return;
        }
        await load();
        if (onRecorded) onRecorded();
    };

    const section = (body) => (
        <div>
            <div style={{ fontSize: 12, fontWeight: 700, color: t.textMuted, textTransform: "uppercase", letterSpacing: "1px", marginBottom: 8 }}>
                Needs outcome
            </div>
            {recordError && <div role="alert" style={{ fontSize: 12.5, color: "#e8526a", marginBottom: 8 }}>{recordError}</div>}
            {body}
        </div>
    );

    // Nothing to do, or not known yet: no section at all. A failed read is
    // still shown — it is not the same as an empty queue.
    if (state === "loading") return null;

    if (state === "error") {
        return section(
            <div style={{
                padding: "14px 16px", borderRadius: 12,
                background: "rgba(232,82,106,0.10)",
                border: "1px solid rgba(232,82,106,0.35)",
            }}>
                <div style={{ fontSize: 13, fontWeight: 700, color: "#e8526a" }}>
                    Could not load outstanding outcomes
                </div>
                <div style={{ fontSize: 12, color: t.textMuted, marginTop: 4 }}>
                    This is not the same as having none — the request failed, so
                    we do not know. Try again.
                </div>
                <button onClick={load} style={{
                    marginTop: 10, minHeight: 36, padding: "8px 14px",
                    borderRadius: 8, border: `1px solid ${t.border}`,
                    background: "transparent", color: t.text, fontSize: 12,
                    fontWeight: 700, cursor: "pointer", fontFamily: "inherit",
                }}>Try again</button>
            </div>
        );
    }

    if (items.length === 0) {
        // The refused row may have been the last one; the reason still shows.
        return recordError ? section(null) : null;
    }

    return section(
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {items.map(item => (
                <div key={item.id} style={{
                    padding: "12px 16px", borderRadius: 12, background: t.cardHi,
                    border: `1px solid ${t.border}`, display: "flex",
                    flexWrap: "wrap", gap: 10, alignItems: "center",
                    justifyContent: "space-between",
                }}>
                    <div style={{ minWidth: 0 }}>
                        <div style={{ fontSize: 13, fontWeight: 700, color: t.text }}>
                            {item.client_name || "Client"}
                        </div>
                        <div style={{ fontSize: 12, color: t.textMuted, marginTop: 2 }}>
                            Ended {formatPkt(item.end_at, {
                                day: "numeric", month: "short", year: "numeric",
                                hour: "2-digit", minute: "2-digit",
                            })}
                        </div>
                    </div>
                    <div style={{ display: "flex", gap: 8 }}>
                        <button
                            disabled={busyId === item.id}
                            onClick={() => record(item.id, "complete")}
                            style={{
                                minHeight: 36, padding: "8px 14px", borderRadius: 8,
                                border: "1px solid rgba(62,201,154,0.55)",
                                background: "rgba(62,201,154,0.14)", color: "#3ec99a",
                                fontSize: 12, fontWeight: 700, fontFamily: "inherit",
                                cursor: busyId === item.id ? "wait" : "pointer",
                                opacity: busyId === item.id ? 0.6 : 1,
                            }}>Completed</button>
                        <button
                            disabled={busyId === item.id}
                            onClick={() => record(item.id, "no_show")}
                            style={{
                                minHeight: 36, padding: "8px 14px", borderRadius: 8,
                                border: "1px solid rgba(158,142,205,0.55)",
                                background: "rgba(158,142,205,0.14)", color: "#9e8ecd",
                                fontSize: 12, fontWeight: 700, fontFamily: "inherit",
                                cursor: busyId === item.id ? "wait" : "pointer",
                                opacity: busyId === item.id ? 0.6 : 1,
                            }}>No Show</button>
                    </div>
                </div>
            ))}
            {cursor && (
                <button onClick={loadMore} disabled={loadingMore} style={{
                    minHeight: 36, padding: "8px 14px", borderRadius: 8,
                    border: `1px solid ${t.border}`, background: "transparent",
                    color: t.textMuted, fontSize: 12, fontWeight: 700,
                    fontFamily: "inherit", cursor: "pointer",
                }}>
                    {loadingMore ? "Loading…" : "Load more"}
                </button>
            )}
            {moreError && (
                <div role="alert" style={{ fontSize: 12, color: "#e8526a", padding: "4px 2px" }}>
                    {moreError}
                </div>
            )}
        </div>
    );
}

/** The lawyer's own weekly working hours, and days off.
 *
 * WHY THIS EXISTS. Until now nothing in the product could answer "when does
 * this lawyer work?". The client's booking form offered six hardcoded times,
 * the same for every lawyer and every day, so Sunday 09:00 was offered as
 * readily as Tuesday 10:00 — times nobody had agreed to.
 *
 * THE TIMEZONE IS STATED, ALWAYS. A weekly schedule is wall-clock: "Tuesdays
 * from nine" means nine in Pakistan. A lawyer travelling, or a browser set to
 * another zone, must not have to guess whose nine o'clock this is.
 *
 * SAVED WHOLESALE. The rule that matters most — no two intervals on one
 * weekday may overlap — is about the set as a whole, so the server replaces
 * the schedule rather than patching it, and this form sends all of it.
 *
 * It states plainly when nothing is saved. An empty schedule is NOT rendered
 * as plausible office hours: this product does not get to decide when somebody
 * else works.
 */
// One page of appointments. Smaller than the old fixed 50 because the list
// now pages: a first screen should arrive quickly, and the rest is a click
// away rather than a silent truncation.
const PAGE_SIZE = 25;

const WEEKDAY_LABELS = ["Monday", "Tuesday", "Wednesday", "Thursday",
                        "Friday", "Saturday", "Sunday"];

/** Every half-hour of the day, which is the only grid a start may land on.
 *
 * Not cosmetic: the overlap guarantee is a unique index over discrete
 * half-hours, so an interval beginning at 09:15 would advertise starts the
 * booking path must then refuse.
 */
/** "09:00" -> "9:00 AM". Display only: the value saved stays "HH:MM". */
function label12(hhmm) {
    const [h, m] = hhmm.split(":").map(Number);
    return `${h % 12 === 0 ? 12 : h % 12}:${String(m).padStart(2, "0")} ${h < 12 ? "AM" : "PM"}`;
}

const HALF_HOURS = Array.from({ length: 48 }, (_, i) => {
    const h = String(Math.floor(i / 2)).padStart(2, "0");
    return `${h}:${i % 2 ? "30" : "00"}`;
});

function WorkingHours({ t }) {
    const [state, setState] = useState("loading");   // loading | ready | error
    const [rows, setRows] = useState([]);
    const [days, setDays] = useState([]);
    const [configured, setConfigured] = useState(false);
    const [enforced, setEnforced] = useState(false);
    const [saving, setSaving] = useState(false);
    const [saveError, setSaveError] = useState("");
    const [savedAt, setSavedAt] = useState("");

    const load = useCallback(async () => {
        setState("loading");
        const { data, error } = await getMyWorkingHours();
        if (error || !data) {
            // NOT "no hours set". A failed read tells us nothing about the
            // schedule, and rendering it as an empty one would invite the
            // lawyer to overwrite hours they cannot currently see.
            setState("error");
            return;
        }
        setRows(data.working_hours || []);
        setDays(data.exceptions || []);
        setConfigured(Boolean(data.configured));
        setEnforced(Boolean(data.enforced));
        setState("ready");
    }, []);

    useEffect(() => { load(); }, [load]);

    const addRow = () =>
        setRows(prev => [...prev, { weekday: 0, start: "09:00", end: "17:00" }]);
    const setRow = (index, patch) =>
        setRows(prev => prev.map((r, i) => (i === index ? { ...r, ...patch } : r)));
    const dropRow = (index) =>
        setRows(prev => prev.filter((_, i) => i !== index));

    const addDay = () => setDays(prev => [...prev, { date: "", reason: "" }]);
    const setDay = (index, patch) =>
        setDays(prev => prev.map((d, i) => (i === index ? { ...d, ...patch } : d)));
    const dropDay = (index) =>
        setDays(prev => prev.filter((_, i) => i !== index));

    const save = async () => {
        setSaving(true);
        setSaveError("");
        setSavedAt("");
        const { data, error } = await saveMyWorkingHours({
            working_hours: rows.map(r => ({
                weekday: Number(r.weekday), start: r.start, end: r.end,
            })),
            // A day off with no date is an unfinished row, not an instruction.
            exceptions: days
                .filter(d => (d.date || "").trim())
                .map(d => ({ date: d.date, reason: (d.reason || "").trim() || null })),
        });
        setSaving(false);
        if (error || !data) {
            // The server's message names the offending interval and says why —
            // it is written for the person who has to fix it, so it is shown
            // rather than replaced with something generic.
            setSaveError(error?.message || "Could not save your working hours.");
            return;
        }
        setRows(data.working_hours || []);
        setDays(data.exceptions || []);
        setConfigured(Boolean(data.configured));
        setSavedAt(new Date().toISOString());
    };

    const box = (body, tone) => (
        <div style={{
            padding: "12px 14px", borderRadius: 10,
            background: tone === "bad" ? "rgba(232,82,106,0.10)" : t.cardHi,
            border: `1px solid ${tone === "bad" ? "rgba(232,82,106,0.35)" : t.border}`,
            fontSize: 12, color: tone === "bad" ? "#e8526a" : t.textMuted,
        }}>{body}</div>
    );

    if (state === "loading") return box("Loading your working hours…");
    if (state === "error") {
        return (
            <div>
                {box("We could not load your working hours. That is not the same as " +
                     "having none — please try again before editing, so you do not " +
                     "overwrite a schedule you cannot see.", "bad")}
                <button onClick={load} style={{
                    marginTop: 8, minHeight: 36, padding: "8px 14px", borderRadius: 8,
                    border: `1px solid ${t.border}`, background: "transparent",
                    color: t.text, fontSize: 12, fontWeight: 700,
                    cursor: "pointer", fontFamily: "inherit",
                }}>Reload working hours</button>
            </div>
        );
    }

    const field = {
        minHeight: 36, padding: "6px 10px", borderRadius: 8,
        border: `1px solid ${t.border}`, background: t.inputBg,
        color: t.text, fontSize: 12.5, fontFamily: "inherit",
    };
    const small = {
        ...field, cursor: "pointer", fontWeight: 700, color: t.textMuted,
        background: "transparent",
    };
    // Intervals of one weekday, with their index in the flat `rows` list (which
    // is what is saved — the layout changed, the payload did not).
    const intervalsOf = (weekday) => rows
        .map((row, index) => ({ row, index }))
        .filter(({ row }) => Number(row.weekday) === weekday);
    const toggleDay = (weekday) => {
        if (intervalsOf(weekday).length) {
            setRows(prev => prev.filter(r => Number(r.weekday) !== weekday));
        } else {
            setRows(prev => [...prev, { weekday, start: "09:00", end: "17:00" }]);
        }
    };
    // A split shift starts an hour after the day's latest end (or right at it
    // when the evening is short) — a fixed default could overlap, and the
    // server rejects overlapping hours. null: no room left that day.
    const nextInterval = (weekday) => {
        const ends = intervalsOf(weekday).map(({ row }) => HALF_HOURS.indexOf(row.end));
        const last = Math.max(...ends);
        if (last < 0 || last >= HALF_HOURS.length - 1) return null;
        const start = Math.min(last + 2, HALF_HOURS.length - 2);
        const end = Math.min(start + 4, HALF_HOURS.length - 1);
        return { start: HALF_HOURS[start], end: HALF_HOURS[end] };
    };
    const addInterval = (weekday) => {
        const next = nextInterval(weekday);
        if (next) setRows(prev => [...prev, { weekday, ...next }]);
    };

    return (
        <div className="wh" style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            <p className="wh-lead">
                {enforced ? "Clients can only request times inside these hours." : "Clients see these hours when they book."}{" "}
                Your hearing times stay blocked automatically. All times are <strong>Pakistan Standard
                Time (PKT)</strong>, on the half hour.
            </p>

            {!configured && box(
                "You have not set any working hours yet. Until you do, clients " +
                "are told your availability is not configured — they are not " +
                "shown guessed office hours.")}

            {configured && !enforced && box(
                "These hours are shown to clients, but booking does not enforce " +
                "them yet, so a request outside them is still possible.")}

            <fieldset className="wh-set">
                <legend className="wh-legend">Weekly hours</legend>
                {rows.length === 0 && (
                    <div className="wh-hint">No weekly hours yet. Click a day to open it.</div>
                )}
                {/* WEEKDAY_LABELS runs Monday (0) to Sunday (6). */}
                {[0, 1, 2, 3, 4, 5, 6].map(weekday => {
                    const dayName = WEEKDAY_LABELS[weekday];
                    const intervals = intervalsOf(weekday);
                    const open = intervals.length > 0;
                    const more = open && nextInterval(weekday);
                    return (
                        <div key={dayName} className={`wh-day${open ? "" : " closed"}`}>
                            {/* The day name opens or closes the day. */}
                            <button type="button" className="wh-name" onClick={() => toggleDay(weekday)}
                                aria-pressed={open}
                                aria-label={`${dayName}: ${open ? "open, click to close" : "closed, click to open"}`}
                                title={open ? `Close ${dayName}` : `Open ${dayName}`}>
                                {dayName.slice(0, 3)}
                            </button>
                            {!open && (
                                <button type="button" className="wh-closed" onClick={() => toggleDay(weekday)}
                                    aria-label={`Open ${dayName}`}>
                                    <span>Closed</span><em>Set hours</em>
                                </button>
                            )}
                            {intervals.map(({ row, index }, n) => (
                                <div key={index} className="wh-slot" style={n ? { gridColumn: "2 / -1" } : undefined}>
                                    <select aria-label={`${dayName} start time ${n + 1}`} value={row.start}
                                        onChange={e => setRow(index, { start: e.target.value })}>
                                        {HALF_HOURS.map(h => <option key={h} value={h}>{label12(h)}</option>)}
                                    </select>
                                    <select aria-label={`${dayName} end time ${n + 1}`} value={row.end}
                                        onChange={e => setRow(index, { end: e.target.value })}>
                                        {HALF_HOURS.map(h => <option key={h} value={h}>{label12(h)}</option>)}
                                    </select>
                                    {n === 0 ? (
                                        <button type="button" className="wh-mini" onClick={() => addInterval(weekday)}
                                            aria-label={`Add more hours on ${dayName}`} title="Split shift: add more hours"
                                            disabled={!more}>+</button>
                                    ) : (
                                        <button type="button" className="wh-mini" onClick={() => dropRow(index)}
                                            aria-label={`Remove ${dayName} hours ${n + 1}`} title="Remove these hours">✕</button>
                                    )}
                                </div>
                            ))}
                        </div>
                    );
                })}
            </fieldset>

            <fieldset className="wh-set">
                <legend className="wh-legend">Days off</legend>
                {days.length === 0 && <div className="wh-hint">No days off listed.</div>}
                {days.map((day, index) => (
                    <div key={index} className="wh-off">
                        <label>
                            <span>Date</span>
                            <input type="date" value={day.date || ""}
                                aria-label={`Date for day off ${index + 1}`}
                                onChange={e => setDay(index, { date: e.target.value })} />
                        </label>
                        <label style={{ flex: 1, minWidth: 140 }}>
                            <span>Reason (private, optional)</span>
                            <input type="text" value={day.reason || ""}
                                aria-label={`Reason for day off ${index + 1}`} maxLength={200}
                                onChange={e => setDay(index, { reason: e.target.value })} />
                        </label>
                        <button type="button" className="wh-mini" onClick={() => dropDay(index)}
                            aria-label={`Remove day off ${index + 1}`}>✕</button>
                    </div>
                ))}
                <button type="button" className="wh-add" onClick={addDay}>Add day off</button>
                <div className="wh-hint" style={{ marginTop: 6 }}>Clients see the dates you are away, never the reason.</div>
            </fieldset>

            {/* Save stays in reach however long the week is. */}
            <div className="wh-foot">
                {saveError && <div role="alert" className="wh-error">{saveError}</div>}
                {savedAt && !saveError && <div role="status" className="wh-ok">Working hours saved.</div>}
                <button type="button" className="wh-save" onClick={save} disabled={saving}>
                    {saving ? "Saving…" : "Save hours"}
                </button>
            </div>
        </div>
    );
}

/* Right-hand drawer for the schedule editor. The editor used to sit inline in
   the middle of the appointments list; it is a setting, edited now and then,
   so it opens on demand. Esc, the backdrop and Close all dismiss it. */
/** Keyboard focus for a modal dialog: move into it on open, keep Tab inside
 *  it, and give focus back to whatever opened it on close. `aria-modal`
 *  alone does none of this. */
function useDialogFocus(ref, initialSelector) {
    useEffect(() => {
        const opener = document.activeElement;
        const node = ref.current;
        const focusables = () => [...(node?.querySelectorAll(
            'button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [href], [tabindex]:not([tabindex="-1"])',
        ) || [])];
        // Here, not with autoFocus: autoFocus moves focus during the commit,
        // before this runs, and the opener recorded above would be lost.
        if (node) ((initialSelector && node.querySelector(initialSelector)) || focusables()[0] || node).focus();
        const onKey = (e) => {
            if (e.key !== "Tab" || !node) return;
            const items = focusables();
            if (!items.length) return;
            const first = items[0];
            const last = items[items.length - 1];
            if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
            else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
        };
        node?.addEventListener("keydown", onKey);
        return () => {
            node?.removeEventListener("keydown", onKey);
            if (opener && typeof opener.focus === "function" && document.contains(opener)) opener.focus();
        };
    }, [ref, initialSelector]);
}

function AvailabilityDrawer({ t, onClose }) {
    const panel = useRef(null);
    useDialogFocus(panel);
    useEffect(() => {
        const onKey = (e) => { if (e.key === "Escape") onClose(); };
        window.addEventListener("keydown", onKey);
        return () => window.removeEventListener("keydown", onKey);
    }, [onClose]);
    return (
        // A card in the middle of the screen (2026-10-09), not a side panel:
        // a setting edited now and then, opened, set, done.
        <div style={{ position: "fixed", inset: 0, zIndex: 9000, display: "flex", alignItems: "center", justifyContent: "center", padding: 16 }}>
            <div onClick={onClose} aria-hidden="true"
                style={{ position: "absolute", inset: 0, background: "rgba(4,14,17,0.55)", backdropFilter: "blur(4px)", WebkitBackdropFilter: "blur(4px)" }} />
            <aside ref={panel} tabIndex={-1} role="dialog" aria-modal="true" aria-label="Working hours" className="wh-card"
                style={{
                    position: "relative", width: "min(460px, 100%)", maxHeight: "min(760px, calc(100vh - 32px))",
                    background: t.surface || t.card, border: `1px solid ${t.border}`, borderRadius: 22,
                    boxShadow: "0 30px 70px -20px rgba(0,0,0,0.6)", overflow: "hidden",
                    display: "flex", flexDirection: "column",
                }}>
                <div className="wh-head">
                    <h2>Working hours</h2>
                    <button type="button" className="wh-done" onClick={onClose}>Done</button>
                </div>
                {/* No bottom padding: the Save bar is sticky at the bottom, and
                    padding under it let the list scroll into view below it. */}
                <div style={{ flex: 1, overflowY: "auto", padding: "10px 22px 0" }}>
                    <WorkingHours t={t} />
                </div>
            </aside>
        </div>
    );
}

// ── Month calendar ────────────────────────────────────────────
// A wall-calendar month: whole Mon-Sun weeks, other months' days faded,
// today in the theme gradient. Two kinds of entry share it:
//   * appointments: booked by clients (POST /appointments is client-only);
//   * diary entries: the lawyer's own meetings and events, private to them.
// Clicking a day selects it and its agenda shows beside the grid.
// A square cell holds two entries. With more, it shows one and "+N more"
// (the line it needs is the second entry's); all of them are in the agenda.
const MONTH_CHIPS = 2;

const DIARY_STYLES = {
    meeting: { bg: "rgba(90,179,255,0.16)", color: "#5ab3ff", dot: "#5ab3ff", label: "Meeting" },
    event: { bg: "rgba(199,146,234,0.16)", color: "#c792ea", dot: "#c792ea", label: "Event" },
};
const PRIORITY_STYLES = {
    high: { color: "#e8526a", label: "High" },
    medium: { color: "#e8b84b", label: "Medium" },
    low: { color: "#3ec99a", label: "Low" },
};

function monthTitle(monthKey) {
    return new Intl.DateTimeFormat("en-GB", { month: "long", year: "numeric", timeZone: "UTC" })
        .format(new Date(`${monthKey}-01T12:00:00Z`));
}

function dayTitle(dayKey) {
    return new Intl.DateTimeFormat("en-GB", { weekday: "long", day: "numeric", month: "long", timeZone: "UTC" })
        .format(new Date(`${dayKey}T12:00:00Z`));
}

/** "11:00 PM – 1:00 AM (next day)": the end time, marked when on a later day. */
function endLabel(start, end) {
    const days = Math.round((new Date(`${pktDayKey(end)}T12:00:00Z`) - new Date(`${pktDayKey(start)}T12:00:00Z`)) / 86400000);
    const time = label12(pktHourMinute(end));
    return days === 1 ? `${time} (next day)` : days > 1 ? `${time} (+${days} days)` : time;
}

/** The day after a day key, as a day key. */
function nextDayKey(dayKey) {
    const d = new Date(`${dayKey}T12:00:00Z`);
    d.setUTCDate(d.getUTCDate() + 1);
    return d.toISOString().slice(0, 10);
}

/** [start, end) of whole Pakistan days, as ISO strings with the offset. */
function pktRange(firstDayKey, lastDayKey) {
    return { start: `${firstDayKey}T00:00:00+05:00`, end: `${nextDayKey(lastDayKey)}T00:00:00+05:00` };
}

/** Calendar entries grouped by Pakistan day, in time order.
 *
 * Appointments that did not take place (cancelled, no-show, expired) are left
 * off, as before. Each entry carries what a cell and the agenda need. */
// A court hearing from the lawyer's cases (2026-10-09): read-only on the
// calendar; it opens its case.
const COURT_STYLE = { bg: "rgba(155,140,240,0.18)", color: "#9b8cf0", dot: "#9b8cf0", label: "Court" };

function calendarDays(appointments, diary, hearings = []) {
    const days = new Map();
    const put = (entry) => {
        const key = pktDayKey(entry.at);
        if (!key) return;
        if (!days.has(key)) days.set(key, []);
        days.get(key).push(entry);
    };
    for (const a of appointments) {
        if (!a.at || DID_NOT_HAPPEN.has(a.status)) continue;
        const s = STATUS_STYLES[a.status] || STATUS_STYLES.Unknown;
        put({ key: `a:${a.id}`, kind: "appointment", at: a.at, title: a.client, style: s, appointment: a });
    }
    for (const e of diary) {
        put({ key: `e:${e.id}`, kind: e.kind, at: new Date(e.starts_at), title: e.title,
              style: DIARY_STYLES[e.kind] || DIARY_STYLES.event, entry: e });
    }
    for (const h of hearings) {
        put({ key: `h:${h.key}`, kind: "court", at: h.at, title: h.title, style: COURT_STYLE, hearing: h });
    }
    for (const list of days.values()) list.sort((x, y) => x.at - y.at);
    return days;
}

function MonthCalendar({ t, month, onMonth, selected, onSelect, days, notices }) {
    const today = pktToday();
    const keys = pktMonthGridKeys(month);
    const onAccent = t.mode === "dark" ? "#0b1c22" : "#fff";
    const navBtn = {
        minWidth: 34, height: 34, padding: "0 12px", borderRadius: 8,
        border: `1px solid ${t.border}`, background: t.card, color: t.text,
        fontSize: 13, fontWeight: 700, cursor: "pointer", fontFamily: "inherit",
    };
    return (
        <Card style={{ overflow: "hidden", padding: 0 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "14px 16px", borderBottom: `1px solid ${t.border}` }}>
                <div style={{ fontSize: 17, fontWeight: 800, color: t.text, flex: 1 }}>{monthTitle(month)}</div>
                <div style={{ display: "flex", gap: 12, marginRight: 8, fontSize: 11, color: t.textMuted }}>
                    {[["Appointment", "#38d8c4"], ["Meeting", DIARY_STYLES.meeting.dot], ["Event", DIARY_STYLES.event.dot], ["Court", COURT_STYLE.dot]].map(([l, c]) => (
                        <span key={l} style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
                            <span style={{ width: 8, height: 8, borderRadius: 2, background: c }} />{l}
                        </span>
                    ))}
                </div>
                <button type="button" aria-label="Previous month" onClick={() => onMonth(shiftMonth(month, -1))} style={navBtn}>‹</button>
                <button type="button" onClick={() => { onMonth(today.slice(0, 7)); onSelect(today); }} style={navBtn}>Today</button>
                <button type="button" aria-label="Next month" onClick={() => onMonth(shiftMonth(month, 1))} style={navBtn}>›</button>
            </div>

            {notices}

            <div style={{ display: "grid", gridTemplateColumns: "repeat(7, minmax(0, 1fr))" }}>
                {CAL_DAYS.map(d => (
                    <div key={d} style={{
                        padding: "12px 6px", textAlign: "center", fontSize: 13, fontWeight: 800,
                        letterSpacing: "0.04em", textTransform: "uppercase", color: t.text,
                        background: t.surface, borderBottom: `1px solid ${t.border}`, borderRight: `1px solid ${t.border}`,
                    }}>{d}</div>
                ))}
                {keys.map(key => {
                    const inMonth = key.slice(0, 7) === month;
                    const isToday = key === today;
                    const isSelected = key === selected;
                    const list = days.get(key) || [];
                    const shown = list.length > MONTH_CHIPS ? MONTH_CHIPS - 1 : list.length;
                    return (
                        <button type="button" key={key} onClick={() => onSelect(key)}
                            aria-label={`${dayTitle(key)}, ${list.length} entr${list.length === 1 ? "y" : "ies"}`}
                            aria-pressed={isSelected}
                            style={{
                                display: "flex", flexDirection: "column", alignItems: "stretch", gap: 3,
                                aspectRatio: "1 / 1", overflow: "hidden", padding: "6px 8px", textAlign: "center", minWidth: 0,
                                border: "none", borderRight: `1px solid ${t.border}`, borderBottom: `1px solid ${t.border}`,
                                background: isToday ? t.grad1 : isSelected ? t.primaryGlow : inMonth ? "transparent" : t.surface,
                                boxShadow: isSelected ? `inset 0 0 0 2px ${t.primary}` : "none",
                                cursor: "pointer", fontFamily: "inherit",
                            }}>
                            <span style={{ fontSize: 15, fontWeight: 700, color: isToday ? onAccent : inMonth ? t.text : t.textFaint }}>
                                {dayOfMonth(key)}
                            </span>
                            {list.slice(0, shown).map(item => (
                                // Text only, no box: the time carries the colour (status for an
                                // appointment, kind for a diary entry), the name stays plain.
                                <span key={item.key} style={{
                                    display: "block", textAlign: "left", fontSize: 10.5, lineHeight: 1.3, minWidth: 0,
                                    color: isToday ? onAccent : item.style.color,
                                }}>
                                    <span style={{ display: "block", fontWeight: 800 }}>{label12(pktHourMinute(item.at))}</span>
                                    <span style={{ display: "block", fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", color: isToday ? onAccent : t.text }}>{item.title}</span>
                                </span>
                            ))}
                            {list.length > shown && (
                                <span style={{ fontSize: 10.5, fontWeight: 700, color: isToday ? onAccent : t.textMuted, textAlign: "left" }}>
                                    +{list.length - shown} more
                                </span>
                            )}
                        </button>
                    );
                })}
            </div>
        </Card>
    );
}

/** One diary entry in the agenda, with a two-step delete. */
function DiaryAgendaItem({ t, entry, onDelete }) {
    const [confirming, setConfirming] = useState(false);
    const [busy, setBusy] = useState(false);
    const s = DIARY_STYLES[entry.kind] || DIARY_STYLES.event;
    const p = PRIORITY_STYLES[entry.priority] || PRIORITY_STYLES.medium;
    const small = {
        minHeight: 28, padding: "4px 10px", borderRadius: 7, fontSize: 11.5, fontWeight: 700,
        cursor: busy ? "wait" : "pointer", fontFamily: "inherit",
    };
    const remove = async () => {
        setBusy(true);
        const ok = await onDelete(entry);
        setBusy(false);
        if (!ok) setConfirming(false);
    };
    return (
        <div style={{ padding: 12, borderRadius: 10, background: t.cardHi, border: `1px solid ${t.border}`, borderLeft: `3px solid ${s.dot}` }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8 }}>
                <div style={{ fontSize: 12.5, fontWeight: 700, color: t.text }}>
                    {label12(pktHourMinute(entry.starts_at))} – {endLabel(entry.starts_at, entry.ends_at)}
                </div>
                <span style={{ padding: "3px 10px", borderRadius: 999, fontSize: 11, fontWeight: 700, background: s.bg, color: s.color, border: `1px solid ${s.dot}55` }}>{s.label}</span>
            </div>
            <div style={{ fontSize: 13, fontWeight: 700, color: t.text, marginTop: 8, overflowWrap: "anywhere" }}>{entry.title}</div>
            {entry.client_name && <div style={{ fontSize: 12, color: t.textMuted, marginTop: 2 }}>With {entry.client_name}</div>}
            {entry.location && <div style={{ fontSize: 12, color: t.textMuted, marginTop: 2, overflowWrap: "anywhere" }}>{entry.location}</div>}
            {entry.notes && <div style={{ fontSize: 12, color: t.textFaint, marginTop: 6, whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{entry.notes}</div>}
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8, marginTop: 10 }}>
                <span style={{ display: "inline-flex", alignItems: "center", gap: 5, fontSize: 11.5, color: t.textMuted }}>
                    <span style={{ width: 7, height: 7, borderRadius: "50%", background: p.color }} />{p.label} priority
                </span>
                {!confirming ? (
                    <button type="button" onClick={() => setConfirming(true)}
                        aria-label={`Delete ${entry.title}`}
                        style={{ ...small, border: `1px solid ${t.border}`, background: "transparent", color: t.textMuted }}>Delete</button>
                ) : (
                    <span style={{ display: "inline-flex", gap: 6 }}>
                        <button type="button" disabled={busy} onClick={() => setConfirming(false)}
                            style={{ ...small, border: `1px solid ${t.border}`, background: "transparent", color: t.text }}>Keep</button>
                        <button type="button" disabled={busy} onClick={remove}
                            style={{ ...small, border: "1px solid rgba(232,82,106,0.6)", background: "rgba(232,82,106,0.15)", color: "#e8526a" }}>
                            {busy ? "Deleting…" : "Confirm delete"}
                        </button>
                    </span>
                )}
            </div>
        </div>
    );
}

/** The selected day's entries, in time order. */
function DayAgenda({ t, dayKey, list, onJoin, onDeleteEntry, onCreate, onOpen, onOpenCase }) {
    return (
        <Card style={{ padding: 16 }}>
            <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 8 }}>
                <div>
                    <div style={{ fontSize: 11, color: t.textMuted, textTransform: "uppercase", letterSpacing: "0.07em", fontWeight: 700 }}>Agenda</div>
                    <div style={{ fontSize: 15, fontWeight: 800, color: t.text, margin: "4px 0 12px" }}>{dayTitle(dayKey)}</div>
                </div>
                <button type="button" onClick={() => onCreate("meeting", dayKey)} aria-label={`Add to ${dayTitle(dayKey)}`}
                    style={{ minHeight: 30, padding: "4px 10px", borderRadius: 8, border: `1px solid ${t.border}`,
                             background: "transparent", color: t.primary, fontSize: 12, fontWeight: 700,
                             cursor: "pointer", fontFamily: "inherit", whiteSpace: "nowrap" }}>+ Add</button>
            </div>
            {list.length === 0 && (
                <div style={{ fontSize: 12.5, color: t.textMuted }}>Nothing on this day.</div>
            )}
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                {list.map(item => item.kind === "court" ? (
                    <div key={item.key} data-court-entry style={{ padding: 12, borderRadius: 10, background: t.cardHi, border: `1px solid ${t.border}`, borderLeft: `3px solid ${COURT_STYLE.dot}` }}>
                        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8 }}>
                            <div style={{ fontSize: 12.5, fontWeight: 700, color: t.text }}>{label12(pktHourMinute(item.at))}</div>
                            <span style={{ padding: "3px 10px", borderRadius: 999, fontSize: 11, fontWeight: 700, background: COURT_STYLE.bg, color: COURT_STYLE.color, border: `1px solid ${COURT_STYLE.dot}55` }}>{item.hearing.held ? "Court · held" : "Court"}</span>
                        </div>
                        <div style={{ fontSize: 13, fontWeight: 700, color: t.text, marginTop: 8 }}>{item.title}</div>
                        <div style={{ fontSize: 12, color: t.textMuted, marginTop: 2 }}>{[item.hearing.purpose, item.hearing.court].filter(Boolean).join(" · ")}</div>
                        {onOpenCase && <button type="button" onClick={() => onOpenCase(item.hearing.caseId)} style={{
                            marginTop: 10, minHeight: 30, padding: "4px 12px", borderRadius: 8, border: `1px solid ${t.border}`,
                            background: "transparent", color: t.primary, fontSize: 12, fontWeight: 700, cursor: "pointer", fontFamily: "inherit",
                        }}>Open case ↗</button>}
                    </div>
                ) : item.kind === "appointment" ? (
                    <div key={item.key} className="ag-appt" role="button" tabIndex={0}
                        aria-label={`Open appointment with ${item.appointment.client}`}
                        onClick={() => onOpen?.(item.appointment)}
                        onKeyDown={e => { if (e.target === e.currentTarget && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); onOpen?.(item.appointment); } }}
                        style={{ padding: 12, borderRadius: 10, background: t.cardHi, border: `1px solid ${t.border}` }}>
                        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8 }}>
                            <div style={{ fontSize: 12.5, fontWeight: 700, color: t.text }}>
                                {label12(pktHourMinute(item.appointment.at))}{item.appointment.endAt ? ` – ${endLabel(item.appointment.at, item.appointment.endAt)}` : ""}
                            </div>
                            <StatusBadge status={item.appointment.status} />
                        </div>
                        <div style={{ fontSize: 13, fontWeight: 700, color: t.text, marginTop: 8 }}>{item.appointment.client}</div>
                        <div style={{ fontSize: 12, color: t.textMuted, marginTop: 2, overflowWrap: "anywhere" }}>{item.appointment.purpose}</div>
                        <div style={{ fontSize: 11.5, color: t.textFaint, marginTop: 6 }}>Appointment · {item.appointment.type} · {item.appointment.duration}</div>
                        {item.appointment.status === "Upcoming" && item.appointment.type === "Video Call"
                            && !(item.appointment.endAt && +item.appointment.endAt <= Date.now()) && (
                            <button type="button" onClick={e => { e.stopPropagation(); onJoin(item.appointment); }} style={{
                                marginTop: 10, width: "100%", padding: "7px 0", borderRadius: 8, border: "none",
                                background: t.primary, color: t.mode === "dark" ? "#0b1c22" : "#fff",
                                fontSize: 12, fontWeight: 700, cursor: "pointer", fontFamily: "inherit",
                            }}>Join call</button>
                        )}
                    </div>
                ) : (
                    <DiaryAgendaItem key={item.key} t={t} entry={item.entry} onDelete={onDeleteEntry} />
                ))}
            </div>
        </Card>
    );
}

/* ONE APPOINTMENT, OPENED (2026-10-09). Clicking an appointment in the day's
 * agenda shows it here, in the agenda's place; ✕ goes back to the agenda.
 * Only what the appointment record holds is shown -- there is no fee or case
 * number on it, so neither is invented -- and every action is the list view's
 * own, gated exactly as it is there. */
const DETAIL_STATUS = {
    Pending: ["Request", "gold"], Upcoming: ["Confirmed", "green"], Completed: ["Completed", "green"],
    Cancelled: ["Cancelled", "red"], "No Show": ["No-show", "red"], Expired: ["Expired", "muted"],
};
const MODE_WORD = { "Video Call": "Video call", "Phone Call": "Phone call", "In-Person": "In person" };

function AppointmentDetail({ apt, now, onClose, gates, actions, onOpenCase, clashes = [] }) {
    const [label, tone] = DETAIL_STATUS[apt.status] || [apt.status, "muted"];
    const day = apt.at ? new Intl.DateTimeFormat("en-GB", { weekday: "long", day: "numeric", month: "short", timeZone: "Asia/Karachi" }).format(apt.at) : "";
    const time = apt.at ? `${label12(pktHourMinute(apt.at))}${apt.endAt ? `–${endLabel(apt.at, apt.endAt)}` : ""}` : "";
    const mode = MODE_WORD[apt.type] || apt.type;
    const ended = apt.endAt && +apt.endAt <= now;
    const where = apt.type === "Video Call" ? (apt.meetingLink ? "Video call · link added" : "Video call · no link yet")
        : apt.type === "Phone Call" ? "Phone call" : "In person";
    const btn = (text, onClick, { disabled = false, title, kind = "" } = {}) => (
        <button type="button" className={`ad-btn${kind ? ` ${kind}` : ""}`} disabled={disabled} title={title} onClick={onClick}>{text}</button>
    );
    const buttons = [];
    if (apt.status === "Pending") {
        buttons.push(btn("Accept", () => actions.accept(apt), { disabled: !gates.canAccept(apt), title: gates.whyNotAccept(apt), kind: "primary" }));
        buttons.push(btn("Decline", () => actions.cancel(apt), { kind: "danger" }));
    }
    if (apt.status === "Upcoming") {
        if (apt.type === "Video Call" && !ended) {
            buttons.push(btn(apt.meetingLink ? "Join call" : "Add joining link", () => actions.join(apt), { kind: "primary" }));
        }
        buttons.push(btn("Mark completed", () => actions.complete(apt), { disabled: !gates.canComplete(apt), title: gates.whyNotComplete(apt) }));
        buttons.push(btn("No-show", () => actions.noShow(apt), { disabled: !gates.canNoShow(apt), title: gates.whyNotNoShow(apt) }));
    }
    if (apt.caseId) buttons.push(btn("Message", () => onOpenCase(apt.caseId)));
    if (apt.status === "Upcoming") buttons.push(btn("Cancel", () => actions.cancel(apt), { kind: "danger" }));

    return (
        <Card style={{ padding: 0 }}>
            <section className="ad" aria-label={`Appointment with ${apt.client}`} data-appointment-detail={apt.id}>
                <div className="ad-top">
                    <span className={`ad-pill ${tone}`}><i />{label}</span>
                    <button type="button" className="ad-x" aria-label="Close appointment details" onClick={onClose}>✕</button>
                </div>
                <div className="ad-kind"><i />Consultation · {mode}</div>
                <h3 className="serif">{mode} consultation</h3>
                <div className="ad-when">{day}{time ? ` · ${time}` : ""}</div>
                <div className="ad-client">
                    <span className="ad-av" aria-hidden="true">{apt.initials}</span>
                    <span><b>{apt.client}</b><small>Client</small></span>
                </div>
                <dl className="ad-rows">
                    <div><dt>Where</dt><dd>{where}</dd></div>
                    <div><dt>Length</dt><dd>{apt.duration}</dd></div>
                    {apt.caseId && (
                        <div><dt>Case</dt><dd><button type="button" className="ad-case" onClick={() => onOpenCase(apt.caseId)}>Open case ↗</button></dd></div>
                    )}
                </dl>
                {apt.note && <blockquote className="ad-note">“{apt.note}”</blockquote>}
                {clashes.length > 0 && (apt.status === "Pending" || apt.status === "Upcoming") && (
                    <div role="alert" className="de-clash" data-clash>
                        <b>{apt.status === "Pending" ? "Accepting this clashes with:" : "Clashes with:"}</b>
                        <ul>{clashes.map(c => <li key={c.key}>{label12(pktHourMinute(c.at))} · {c.title} <span>({c.kind === "court" ? "Court hearing" : c.kind === "appointment" ? "Appointment" : (DIARY_STYLES[c.kind] || DIARY_STYLES.event).label})</span></li>)}</ul>
                    </div>
                )}
                {buttons.length > 0 && <div className="ad-actions">{buttons}</div>}
            </section>
        </Card>
    );
}

// ── Daily / Weekly / Monthly (2026-10-09) ─────────────────────
// The calendar shows one day, one week or one month. Every range reads the
// same data: all appointments, and the diary of the month grid around the
// selected day (whole Mon-Sun weeks), so a week never has unloaded days.
const RANGES = [["day", "Daily"], ["week", "Weekly"], ["month", "Monthly"]];
const WEEK_DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
function shiftDayKey(dayKey, n) {
    const d = new Date(`${dayKey}T12:00:00Z`);
    d.setUTCDate(d.getUTCDate() + n);
    return d.toISOString().slice(0, 10);
}
/** The Monday of the week a day is in. */
function weekStartOf(dayKey) {
    const dow = (new Date(`${dayKey}T12:00:00Z`).getUTCDay() + 6) % 7;
    return shiftDayKey(dayKey, -dow);
}
const fmtDayKey = (dayKey, opts) => new Intl.DateTimeFormat("en-GB", { ...opts, timeZone: "UTC" }).format(new Date(`${dayKey}T12:00:00Z`));

function RangeMenu({ value, onChange }) {
    const [open, setOpen] = useState(false);
    const ref = useRef(null);
    useEffect(() => {
        if (!open) return undefined;
        const away = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
        const esc = (e) => { if (e.key === "Escape") setOpen(false); };
        document.addEventListener("mousedown", away);
        window.addEventListener("keydown", esc);
        return () => { document.removeEventListener("mousedown", away); window.removeEventListener("keydown", esc); };
    }, [open]);
    const current = (RANGES.find(([v]) => v === value) || RANGES[2])[1];
    return (
        <div ref={ref} className="rb-menu">
            <button type="button" className="rb-trigger" aria-haspopup="listbox" aria-expanded={open}
                aria-label={`Calendar range: ${current}`} onClick={() => setOpen(o => !o)}>
                {current}
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"
                    style={{ transform: open ? "rotate(180deg)" : "none", transition: "transform .2s" }}><path d="m6 9 6 6 6-6" /></svg>
            </button>
            {open && (
                <div role="listbox" aria-label="Calendar range" className="rb-list">
                    {RANGES.map(([v, label]) => (
                        <button key={v} type="button" role="option" aria-selected={v === value}
                            onClick={() => { onChange(v); setOpen(false); }}>{label}</button>
                    ))}
                </div>
            )}
        </div>
    );
}

// ── The time grid: hours down, days across (Weekly: 7, Daily: 1) ─────────
const HOUR_PX = 60;
const ALL_DAY_MINUTES = 8 * 60;   // an entry of 8 hours or more reads as all-day
function minutesOfDay(at) {
    const [h, m] = (pktHourMinute(at) || "0:0").split(":").map(Number);
    return h * 60 + m;
}
function itemSpan(item) {
    const end = item.kind === "appointment" ? item.appointment.endAt
        : (item.entry?.ends_at ? new Date(item.entry.ends_at) : null);
    // A hearing has a start and no end on record: shown as an hour.
    let dur = end ? Math.round((+end - +item.at) / 60000) : item.kind === "court" ? 60 : 30;
    if (!(dur > 0)) dur = 30;
    return { start: minutesOfDay(item.at), dur, end };
}
/** Side-by-side lanes for entries that overlap, so none hides another. */
function laneOut(items) {
    const out = items.map(item => ({ item, ...itemSpan(item) })).sort((a, b) => a.start - b.start);
    let cluster = [], clusterEnd = -1;
    const close = () => { const n = Math.max(1, ...cluster.map(x => x.lane + 1)); cluster.forEach(x => { x.lanes = n; }); cluster = []; };
    for (const x of out) {
        if (cluster.length && x.start >= clusterEnd) close();
        const used = cluster.filter(y => y.start + Math.max(y.dur, 30) > x.start).map(y => y.lane);
        let lane = 0; while (used.includes(lane)) lane += 1;
        x.lane = lane;
        cluster.push(x);
        clusterEnd = Math.max(clusterEnd, x.start + Math.max(x.dur, 30));
    }
    if (cluster.length) close();
    return out;
}

/** One entry on the grid: time, who or what, in its own colour. */
function GridEntry({ x, top, height, onOpen }) {
    const s = x.item.style || {};
    const time = label12(pktHourMinute(x.item.at));
    const w = 100 / x.lanes;
    return (
        <button type="button" className={`rb-chip${x.item.kind === "appointment" && x.item.appointment.status === "Pending" ? " tentative" : ""}`} onClick={() => onOpen(x.item)}
            style={{ "--c": s.dot || s.color || "#38d8c4", top, height, left: `calc(${w * x.lane}% + 3px)`, width: `calc(${w}% - 6px)` }}
            title={`${time}${x.end ? `–${endLabel(x.item.at, x.end)}` : ""} · ${x.item.title}`}>
            <span>{x.item.title}</span><b>{time}</b>
        </button>
    );
}

/** Minutes from midnight of "HH:MM". */
const hmToMin = (hm) => { const [h, m] = String(hm || "0:0").split(":").map(Number); return h * 60 + m; };

function TimeGrid({ keys, days, onDayHead, onOpenItem, onSlot, selected, work = null, showHeads = true }) {
    const bodyRef = useRef(null);
    // The half hour under the pointer: shown as "+ 10:30 AM", and what a click adds.
    const [hover, setHover] = useState(null);   // { k, m } minutes from midnight
    // Press and pull down to pick a start AND a length: { k, a, b } half hours.
    const [drag, setDrag] = useState(null);
    const dragged = useRef(false);     // the click that ends a drag is not a second add
    const toHM = (m) => `${String(Math.floor(m / 60)).padStart(2, "0")}:${m % 60 ? "30" : "00"}`;
    useEffect(() => {
        if (!drag) return undefined;
        const up = () => {
            const start = Math.min(drag.a, drag.b), end = Math.max(drag.a, drag.b) + 30;
            if (end - start > 30 && onSlot) { dragged.current = true; onSlot(drag.k, toHM(start), end - start); }
            setDrag(null);
        };
        window.addEventListener("mouseup", up);
        return () => window.removeEventListener("mouseup", up);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [drag]);
    const today = pktToday();
    const perDay = keys.map(k => {
        const list = days.get(k) || [];
        return { k, allDay: list.filter(i => itemSpan(i).dur >= ALL_DAY_MINUTES), timed: list.filter(i => itemSpan(i).dur < ALL_DAY_MINUTES) };
    });
    // 8 AM to 7 PM, widened to fit anything outside it.
    let first = 8, last = 19;
    for (const d of perDay) for (const i of d.timed) {
        const { start, dur } = itemSpan(i);
        first = Math.min(first, Math.floor(start / 60));
        last = Math.max(last, Math.min(23, Math.ceil((start + dur) / 60)));
    }
    const hours = Array.from({ length: last - first + 1 }, (_, i) => first + i);
    const nowMin = minutesOfDay(new Date(Date.now()));
    // Outside working hours, shaded (only once hours are set). Days run
    // Monday (0) to Sunday (6), as the working-hours rows do.
    const isDayOff = (k) => Boolean(work?.daysOff?.includes(k));
    const offBands = (k) => {
        // A day off is closed all day, set hours or not.
        if (isDayOff(k)) return [[first * 60, (last + 1) * 60]];
        if (!work || !work.configured) return [];
        const weekday = (new Date(`${k}T12:00:00Z`).getUTCDay() + 6) % 7;
        const open = work.rows.filter(r => Number(r.weekday) === weekday)
            .map(r => [hmToMin(r.start), hmToMin(r.end)]).sort((a, b) => a[0] - b[0]);
        const out = [];
        let at = first * 60;
        for (const [a, b] of open) {
            if (a > at) out.push([at, Math.min(a, (last + 1) * 60)]);
            at = Math.max(at, b);
        }
        if (at < (last + 1) * 60) out.push([at, (last + 1) * 60]);
        return out.filter(([a, b]) => b > a);
    };
    // Open on what matters: now (when today is shown), else the first entry,
    // else the start of the working day.
    useEffect(() => {
        const el = bodyRef.current;
        if (!el) return;
        let target = keys.includes(pktToday()) ? nowMin : null;
        if (target === null) {
            const starts = perDay.flatMap(d => d.timed.map(i => itemSpan(i).start));
            target = starts.length ? Math.min(...starts) : 9 * 60;
        }
        el.scrollTop = Math.max(0, (target - first * 60) * HOUR_PX / 60 - HOUR_PX);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [keys.join(","), first]);
    const cols = `76px repeat(${keys.length}, minmax(0, 1fr))`;
    return (
        <div className="tg">
            {showHeads && (
                <div className="tg-row tg-heads" style={{ gridTemplateColumns: cols }}>
                    <span />
                    {keys.map(k => (
                        <button key={k} type="button" className={`tg-head${k === selected ? " sel" : ""}${k === today ? " today" : ""}`}
                            aria-pressed={k === selected} onClick={() => onDayHead?.(k)}
                            aria-label={fmtDayKey(k, { weekday: "long", day: "numeric", month: "long" })}>
                            <span>{fmtDayKey(k, { weekday: "short" })}</span><b>{Number(k.slice(8))}</b>
                        </button>
                    ))}
                </div>
            )}
            <div className="tg-row tg-allday" style={{ gridTemplateColumns: cols }}>
                <span className="tg-label">ALL DAY</span>
                {perDay.map(({ k, allDay, timed }) => (
                    <div key={k} className="tg-cell">
                        {allDay.map(i => (
                            <button key={i.key} type="button" className="rb-chip flat" onClick={() => onOpenItem(i)}
                                style={{ "--c": i.style?.dot || i.style?.color || "#38d8c4" }}><span>{i.title}</span></button>
                        ))}
                        {isDayOff(k) && <span className="tg-dayoff">Day off</span>}
                        {!allDay.length && <em>{timed.length ? "No all-day events" : "Nothing on this day."}</em>}
                    </div>
                ))}
            </div>
            <div className="tg-body" ref={bodyRef} style={{ gridTemplateColumns: cols }}>
                <div className="tg-hours">
                    {hours.map(h => <div key={h} style={{ height: HOUR_PX }}>{label12(`${String(h).padStart(2, "0")}:00`).replace(":00", "")}</div>)}
                </div>
                {perDay.map(({ k, timed }) => {
                    // A click on the column itself (not on an entry) picks its half hour.
                    const slotAt = (e) => {
                        const y = e.clientY - e.currentTarget.getBoundingClientRect().top;
                        const m = first * 60 + Math.max(0, Math.floor(y / (HOUR_PX / 2))) * 30;
                        return Math.min(m, 23 * 60 + 30);
                    };
                    const hhmm = (m) => `${String(Math.floor(m / 60)).padStart(2, "0")}:${m % 60 ? "30" : "00"}`;
                    return (
                    <div key={k} className={`rb-col${k === selected ? " sel" : ""}${onSlot ? " can-add" : ""}`} style={{ height: hours.length * HOUR_PX }}
                        data-slot-column={k}
                        role={onSlot ? "button" : undefined} tabIndex={onSlot ? 0 : undefined}
                        aria-label={onSlot ? `Add a meeting or event on ${fmtDayKey(k, { weekday: "long", day: "numeric", month: "long" })}` : undefined}
                        onMouseDown={e => { if (onSlot && e.button === 0 && e.target === e.currentTarget) { e.preventDefault(); const m = slotAt(e); setDrag({ k, a: m, b: m }); } }}
                        onClick={e => {
                            if (dragged.current) { dragged.current = false; return; }
                            if (onSlot && e.target === e.currentTarget) onSlot(k, hhmm(slotAt(e)));
                        }}
                        onKeyDown={e => { if (onSlot && e.target === e.currentTarget && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); onSlot(k, hhmm(first * 60)); } }}
                        onMouseMove={e => {
                            if (!onSlot) return;
                            if (e.target !== e.currentTarget) { if (!drag) setHover(null); return; }
                            const m = slotAt(e);
                            if (drag && drag.k === k) { if (drag.b !== m) setDrag({ ...drag, b: m }); return; }
                            if (!hover || hover.k !== k || hover.m !== m) setHover({ k, m });
                        }}
                        onMouseLeave={() => setHover(null)}>
                        {offBands(k).map(([a, b]) => (
                            <i key={a} className="tg-off" aria-hidden="true"
                                style={{ top: (a - first * 60) * HOUR_PX / 60, height: (b - a) * HOUR_PX / 60 }} />
                        ))}
                        {drag && drag.k === k && (() => {
                            const a = Math.min(drag.a, drag.b), b = Math.max(drag.a, drag.b) + 30;
                            return (
                                <i className="tg-ghost drag" aria-hidden="true" style={{ top: (a - first * 60) * HOUR_PX / 60 + 1, height: (b - a) * HOUR_PX / 60 - 2 }}>
                                    {label12(toHM(a))} – {label12(toHM(b % (24 * 60)))}
                                </i>
                            );
                        })()}
                        {!drag && hover && hover.k === k && (
                            <i className="tg-ghost" aria-hidden="true" style={{ top: (hover.m - first * 60) * HOUR_PX / 60 + 1, height: HOUR_PX / 2 - 2 }}>
                                + {label12(hhmm(hover.m))}
                            </i>
                        )}
                        {k === today && nowMin >= first * 60 && nowMin <= (last + 1) * 60 && (
                            <i className="tg-now" style={{ top: (nowMin - first * 60) * HOUR_PX / 60 }} aria-hidden="true" />
                        )}
                        {laneOut(timed).map(x => (
                            <GridEntry key={x.item.key} x={x} onOpen={onOpenItem}
                                top={(x.start - first * 60) * HOUR_PX / 60 + 2}
                                height={Math.max(26, x.dur * HOUR_PX / 60 - 4)} />
                        ))}
                    </div>
                    );
                })}
            </div>
        </div>
    );
}

function RangeHead({ title, sub, onPrev, onNext, onToday, prevLabel, nextLabel, notices, center = false }) {
    return (
        <>
            <div className={`rb-head${center ? " center" : ""}`}>
                <div className="rb-navs">
                    <button type="button" className="rb-nav" aria-label={prevLabel} onClick={onPrev}>‹</button>
                    <button type="button" className="rb-today" onClick={onToday}>Today</button>
                    <button type="button" className="rb-nav" aria-label={nextLabel} onClick={onNext}>›</button>
                </div>
                <div className="rb-title"><h3>{title}</h3>{sub && <small>{sub}</small>}</div>
            </div>
            {notices}
        </>
    );
}

function WeekBoard({ dayKey, onDay, days, onOpenItem, onSlot, work, notices }) {
    const start = weekStartOf(dayKey);
    const keys = Array.from({ length: 7 }, (_, i) => shiftDayKey(start, i));
    const last = keys[6];
    const title = start.slice(0, 7) === last.slice(0, 7)
        ? `${Number(start.slice(8))} – ${fmtDayKey(last, { day: "numeric", month: "short", year: "numeric" })}`
        : `${fmtDayKey(start, { day: "numeric", month: "short" })} – ${fmtDayKey(last, { day: "numeric", month: "short", year: "numeric" })}`;
    return (
        <Card style={{ padding: 0, overflow: "hidden" }}>
            <RangeHead title={title} prevLabel="Previous week" nextLabel="Next week" notices={notices}
                onPrev={() => onDay(shiftDayKey(dayKey, -7))} onNext={() => onDay(shiftDayKey(dayKey, 7))} onToday={() => onDay(pktToday())} />
            <div data-week-board>
                <TimeGrid keys={keys} days={days} selected={dayKey} onDayHead={onDay} onOpenItem={onOpenItem} onSlot={onSlot} work={work} />
            </div>
        </Card>
    );
}

function DayBoard({ dayKey, onDay, days, onOpenItem, onSlot, work, notices }) {
    return (
        <Card style={{ padding: 0, overflow: "hidden" }}>
            <RangeHead center title={fmtDayKey(dayKey, { weekday: "long", month: "long", day: "numeric", year: "numeric" })}
                sub="FOCUSED DAY VIEW" prevLabel="Previous day" nextLabel="Next day" notices={notices}
                onPrev={() => onDay(shiftDayKey(dayKey, -1))} onNext={() => onDay(shiftDayKey(dayKey, 1))} onToday={() => onDay(pktToday())} />
            <div data-day-board>
                <TimeGrid keys={[dayKey]} days={days} selected={dayKey} onOpenItem={onOpenItem} onSlot={onSlot} work={work} showHeads={false} />
            </div>
        </Card>
    );
}

/** A small month for moving around in the Daily view. */
function MiniMonth({ dayKey, onDay, days }) {
    const [month, setMonth] = useState(dayKey.slice(0, 7));
    useEffect(() => { setMonth(dayKey.slice(0, 7)); }, [dayKey]);
    const keys = pktMonthGridKeys(month);
    const today = pktToday();
    const shift = (n) => {
        const [y, m] = month.split("-").map(Number);
        const d = new Date(Date.UTC(y, m - 1 + n, 1));
        setMonth(d.toISOString().slice(0, 7));
    };
    return (
        <Card style={{ padding: 16 }}>
            <div className="mm" aria-label="Pick a day">
                <div className="mm-head">
                    <button type="button" className="rb-nav" aria-label="Previous month" onClick={() => shift(-1)}>‹</button>
                    <b>{monthTitle(month)}</b>
                    <button type="button" className="rb-nav" aria-label="Next month" onClick={() => shift(1)}>›</button>
                </div>
                <div className="mm-grid">
                    {WEEK_DAYS.map(d => <span key={d} className="mm-dow">{d[0]}</span>)}
                    {keys.map(k => (
                        <button key={k} type="button" onClick={() => onDay(k)} aria-pressed={k === dayKey}
                            className={`mm-day${k.slice(0, 7) !== month ? " out" : ""}${k === dayKey ? " sel" : ""}${k === today ? " today" : ""}`}
                            aria-label={fmtDayKey(k, { weekday: "long", day: "numeric", month: "long" })}>
                            {Number(k.slice(8))}{(days.get(k) || []).length > 0 && <i aria-hidden="true" />}
                        </button>
                    ))}
                </div>
            </div>
        </Card>
    );
}

// ── Create: the lawyer's own meeting or event ─────────────────
const DURATIONS = [15, 30, 45, 60, 90, 120, 180, 240, 480];
const durationLabel = (m) => (m < 60 ? `${m} min` : m % 60 ? `${Math.floor(m / 60)} h ${m % 60} min` : `${m / 60} hour${m === 60 ? "" : "s"}`);

// ── Status tabs ───────────────────────────────────────────────
// Each tab wears its status colour when selected: solid fill, readable text.
const TAB_TONES = {
    All: { solid: "#0f9488", onSolid: "#ffffff", glow: "rgba(15,148,136,0.35)", soft: "rgba(56,216,196,0.14)", edge: "rgba(56,216,196,0.55)", text: "#38d8c4" },
    Upcoming: { solid: "#2f7fd1", onSolid: "#ffffff", glow: "rgba(47,127,209,0.35)", soft: "rgba(90,179,255,0.14)", edge: "rgba(90,179,255,0.55)", text: "#5ab3ff" },
    Pending: { solid: "#d9a536", onSolid: "#2a2108", glow: "rgba(217,165,54,0.35)", soft: "rgba(232,184,75,0.16)", edge: "rgba(232,184,75,0.6)", text: "#e8b84b" },
    Completed: { solid: "#2fa37c", onSolid: "#ffffff", glow: "rgba(47,163,124,0.35)", soft: "rgba(62,201,154,0.14)", edge: "rgba(62,201,154,0.55)", text: "#3ec99a" },
    Cancelled: { solid: "#c9475d", onSolid: "#ffffff", glow: "rgba(201,71,93,0.35)", soft: "rgba(232,82,106,0.14)", edge: "rgba(232,82,106,0.55)", text: "#e8526a" },
    "No Show": { solid: "#7e6cc0", onSolid: "#ffffff", glow: "rgba(126,108,192,0.35)", soft: "rgba(158,142,205,0.14)", edge: "rgba(158,142,205,0.55)", text: "#9e8ecd" },
    Expired: { solid: "#6c7a86", onSolid: "#ffffff", glow: "rgba(108,122,134,0.35)", soft: "rgba(148,158,175,0.14)", edge: "rgba(148,158,175,0.5)", text: "#94a2af" },
};
const ALWAYS_COUNTED = new Set(["All", "Upcoming", "Pending", "Completed"]);

// ── Toolbar pills ─────────────────────────────────────────────
// Rounded toolbar controls: "solid" (the theme gradient, for the main action
// and the active view) or "outline" (everything else).
const PILL_GRADIENT = "linear-gradient(135deg, #12897f 0%, #1c9c66 100%)";

function pillStyle(t, variant = "outline") {
    return {
        display: "inline-flex", alignItems: "center", justifyContent: "center", gap: 8,
        height: 42, padding: "0 18px", borderRadius: 999, whiteSpace: "nowrap",
        fontSize: 13.5, fontWeight: 700, fontFamily: "inherit", cursor: "pointer",
        transition: "border-color .15s, box-shadow .15s, filter .15s",
        ...(variant === "solid"
            ? { border: "1px solid transparent", background: PILL_GRADIENT, color: "#fff",
                boxShadow: "0 4px 14px rgba(28,156,102,0.28)" }
            : { border: `1px solid ${t.border}`, background: "transparent", color: t.text }),
    };
}

const PillButton = forwardRef(function PillButton({ t, variant = "outline", style, children, ...rest }, ref) {
    const base = pillStyle(t, variant);
    return (
        <button ref={ref} type="button" {...rest} style={{ ...base, ...style }}
            onMouseEnter={e => {
                if (variant === "solid") e.currentTarget.style.filter = "brightness(1.08)";
                else e.currentTarget.style.borderColor = t.primary;
            }}
            onMouseLeave={e => {
                if (variant === "solid") e.currentTarget.style.filter = "none";
                else e.currentTarget.style.borderColor = t.border;
            }}>
            {children}
        </button>
    );
});

function CreateMenu({ t, onPick }) {
    const [open, setOpen] = useState(false);
    const ref = useRef(null);
    const trigger = useRef(null);
    useEffect(() => {
        if (!open) return undefined;
        const away = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
        const esc = (e) => { if (e.key === "Escape") setOpen(false); };
        document.addEventListener("mousedown", away);
        window.addEventListener("keydown", esc);
        return () => { document.removeEventListener("mousedown", away); window.removeEventListener("keydown", esc); };
    }, [open]);
    const item = (kind, title, hint) => (
        <button type="button" role="menuitem" onClick={() => { setOpen(false); trigger.current?.focus(); onPick(kind); }} style={{
            display: "flex", gap: 10, alignItems: "flex-start", width: "100%", padding: "10px 12px",
            border: "none", borderRadius: 8, background: "transparent", color: t.text, textAlign: "left",
            cursor: "pointer", fontFamily: "inherit",
        }}
            onMouseEnter={e => { e.currentTarget.style.background = t.cardHi; }}
            onMouseLeave={e => { e.currentTarget.style.background = "transparent"; }}>
            <span style={{ width: 10, height: 10, borderRadius: 3, marginTop: 4, background: DIARY_STYLES[kind].dot, flexShrink: 0 }} />
            <span>
                <span style={{ display: "block", fontSize: 13, fontWeight: 700 }}>{title}</span>
                <span style={{ display: "block", fontSize: 11.5, color: t.textMuted, marginTop: 2 }}>{hint}</span>
            </span>
        </button>
    );
    return (
        <div ref={ref} style={{ position: "relative" }}>
            {/* The page's main action: the theme's green-to-cyan gradient (2026-10-09). */}
            <PillButton ref={trigger} t={t} variant="solid" aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen(o => !o)}
                style={{ background: "linear-gradient(90deg, #3EE0A1, #38CDE0)", color: "#0b1c22", border: "none", fontWeight: 700, boxShadow: "0 8px 18px -12px rgba(46,196,214,0.8)", height: 38, padding: "0 16px", fontSize: 13.5 }}>
                <Icon d={I.plus} size={15} /> Create <Icon d={I.chevronDown} size={14} />
            </PillButton>
            {open && (
                <div role="menu" style={{
                    position: "absolute", right: 0, top: "calc(100% + 6px)", zIndex: 50, width: 260, padding: 6,
                    borderRadius: 12, background: t.card, border: `1px solid ${t.border}`, boxShadow: t.shadowCard,
                }}>
                    {item("meeting", "Meeting", "A meeting with a client or colleague")}
                    {item("event", "Event", "A court visit, deadline, seminar or reminder")}
                    <div style={{ fontSize: 11, color: t.textFaint, padding: "8px 12px 4px", borderTop: `1px solid ${t.border}`, marginTop: 4 }}>
                        Private to your diary. Clients book appointments themselves.
                    </div>
                </div>
            )}
        </div>
    );
}

/** Confirm before declining a request or cancelling an appointment.
 *  Both used to happen on one click with no way back, and the client was told
 *  without a reason even though the server carries one into their notice. */
function CancelAppointmentDialog({ t, apt, onClose, onConfirm }) {
    const pending = apt.status === "Pending";
    const [reason, setReason] = useState("");
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState(null);
    const panel = useRef(null);
    useDialogFocus(panel, "#cx-reason");

    useEffect(() => {
        const esc = (e) => { if (e.key === "Escape" && !busy) onClose(); };
        window.addEventListener("keydown", esc);
        return () => window.removeEventListener("keydown", esc);
    }, [busy, onClose]);

    const submit = async () => {
        if (busy) return;
        setBusy(true);
        setError(null);
        const err = await onConfirm(reason.trim() || null);
        // On success the parent closes this dialog; on failure it stays open
        // with the server's reason, and the lawyer can try again or keep it.
        if (err) { setBusy(false); setError(err); }
    };

    const heading = pending ? "Decline this request?" : "Cancel this appointment?";
    const action = pending ? "Decline request" : "Cancel appointment";
    return (
        <div style={{ position: "fixed", inset: 0, zIndex: 9999, display: "flex", alignItems: "center", justifyContent: "center", background: "rgba(0,0,0,0.6)", padding: 16 }}
            onClick={() => { if (!busy) onClose(); }}>
            <div ref={panel} tabIndex={-1} role="dialog" aria-modal="true" aria-label={heading}
                onClick={e => e.stopPropagation()}
                style={{ width: "min(480px, 100%)", background: t.surface, border: `1px solid ${t.border}`, borderRadius: 16, boxShadow: t.shadowCard, overflow: "hidden" }}>
                <div style={{ padding: "20px 24px", borderBottom: `1px solid ${t.border}` }}>
                    <div style={{ fontSize: 18, fontWeight: 800, color: t.text }}>{heading}</div>
                    <div style={{ fontSize: 13, color: t.textMuted, marginTop: 6, lineHeight: 1.5 }}>
                        {apt.client} · {apt.date}, {apt.time}. {apt.client} will be notified{pending ? "" : " that it is cancelled"}. This cannot be undone.
                    </div>
                </div>
                <div style={{ padding: "18px 24px", display: "flex", flexDirection: "column", gap: 8 }}>
                    <label htmlFor="cx-reason" style={{ fontSize: 11, fontWeight: 800, color: t.textMuted, textTransform: "uppercase", letterSpacing: "0.08em" }}>
                        Reason for the client <span style={{ textTransform: "none", letterSpacing: 0, fontWeight: 600 }}>(optional)</span>
                    </label>
                    <textarea id="cx-reason" value={reason} onChange={e => setReason(e.target.value)} maxLength={500} rows={3}
                        placeholder={pending ? "e.g. I am in court that morning. Please pick another time." : "e.g. A hearing was fixed for the same time."}
                        style={{ width: "100%", boxSizing: "border-box", padding: "10px 12px", borderRadius: 10, border: `1px solid ${t.border}`,
                                 background: t.inputBg, color: t.text, fontSize: 13.5, fontFamily: "inherit", resize: "vertical", outline: "none" }} />
                    <div style={{ fontSize: 11.5, color: t.textFaint }}>Included in the notice the client receives.</div>
                    {error && <div role="alert" style={{ fontSize: 12.5, color: "#e8526a" }}>{error}</div>}
                </div>
                <div style={{ display: "flex", justifyContent: "flex-end", gap: 10, padding: "14px 24px 20px" }}>
                    <Btn variant="secondary" size="sm" disabled={busy} onClick={onClose}>{pending ? "Keep request" : "Keep appointment"}</Btn>
                    <Btn variant="danger" size="sm" disabled={busy} onClick={submit}>{busy ? "Working…" : action}</Btn>
                </div>
            </div>
        </div>
    );
}

function DiaryEntryModal({ t, initialKind, initialDay, initialTime = null, initialDuration = null, findClashes = null, onClose, onCreated }) {
    const today = pktToday();
    const [kind, setKind] = useState(initialKind);
    const [title, setTitle] = useState("");
    const [withWhom, setWithWhom] = useState("");
    const [location, setLocation] = useState("");
    // The day that was clicked, even a past one: a diary may record what
    // already happened, and moving it to today without saying so loses it.
    const [day, setDay] = useState(initialDay || today);
    const panel = useRef(null);
    useDialogFocus(panel, "#de-title");
    const [time, setTime] = useState(initialTime && HALF_HOURS.includes(initialTime) ? initialTime : "10:00");
    // A dragged range arrives as minutes; the form offers fixed lengths, so it
    // takes the nearest one that covers the range.
    const [duration, setDuration] = useState(() => {
        if (!initialDuration) return 60;
        return DURATIONS.find(m => m >= initialDuration) || DURATIONS[DURATIONS.length - 1];
    });
    const clashes = findClashes ? findClashes(day, time, duration) : [];
    const [priority, setPriority] = useState("medium");
    const [notes, setNotes] = useState("");
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState(null);

    useEffect(() => {
        const esc = (e) => { if (e.key === "Escape" && !busy) onClose(); };
        window.addEventListener("keydown", esc);
        return () => window.removeEventListener("keydown", esc);
    }, [busy, onClose]);

    const submit = async () => {
        if (busy) return;
        if (!title.trim()) { setError("Give it a title."); return; }
        const startsAt = pktSlotToUtcISO(day, time);
        if (!startsAt) { setError("Pick a date and a start time."); return; }
        setBusy(true);
        setError(null);
        const { data, error: err } = await createLawyerEvent({
            kind, title: title.trim(), starts_at: startsAt, duration_minutes: duration,
            client_name: withWhom.trim() || null, location: location.trim() || null,
            priority, notes: notes.trim() || null,
        });
        setBusy(false);
        if (err || !data) { setError(err?.message || "Could not save it. Try again."); return; }
        onCreated(data);
    };

    const segmented = (options, value, onChange, name) => (
        <div role="radiogroup" aria-label={name} className="de-seg" style={{ gridTemplateColumns: `repeat(${options.length}, 1fr)` }}>
            {options.map(([v, text]) => (
                <button type="button" key={v} role="radio" aria-checked={value === v} onClick={() => onChange(v)}>{text}</button>
            ))}
        </div>
    );
    const isMeeting = kind === "meeting";

    // The same card as Working hours (2026-10-09): one column, labels above
    // fields, one full-width action. It saves to the lawyer's own diary only,
    // so the action says "Create", never "Book" or "notify".
    return (
        <div className="de-backdrop" onClick={() => { if (!busy) onClose(); }}>
            <div ref={panel} tabIndex={-1} role="dialog" aria-modal="true" aria-label={isMeeting ? "New meeting" : "New event"}
                className="de-card" onClick={e => e.stopPropagation()}>
                <div className="de-head">
                    <h2>{isMeeting ? "New meeting" : "New event"}</h2>
                    <button type="button" className="de-cancel" disabled={busy} onClick={onClose}>Cancel</button>
                </div>
                <p className="de-sub">Saved to your diary only. Nobody else is notified.</p>

                <div className="de-body">
                    {segmented([["meeting", "Meeting"], ["event", "Event"]], kind, setKind, "Type")}

                    <div className="de-field">
                        <label htmlFor="de-title">Title <span className="de-req">*</span></label>
                        <input id="de-title" value={title} onChange={e => setTitle(e.target.value)} maxLength={200}
                            placeholder={isMeeting ? "e.g. Case discussion with Mr. Khan" : "e.g. Lahore High Court — file written reply"} />
                    </div>
                    <div className="de-field">
                        <label htmlFor="de-with">{isMeeting ? "With" : "Related client"}</label>
                        <input id="de-with" value={withWhom} onChange={e => setWithWhom(e.target.value)} maxLength={120}
                            placeholder="Client or person (optional)" />
                    </div>
                    <div className="de-two">
                        <div className="de-field">
                            <label htmlFor="de-date">Date <span className="de-req">*</span></label>
                            <input id="de-date" type="date" value={day} onChange={e => setDay(e.target.value)} />
                        </div>
                        <div className="de-field">
                            <label htmlFor="de-time">Start <span className="de-req">*</span></label>
                            <select id="de-time" value={time} onChange={e => setTime(e.target.value)}>
                                {HALF_HOURS.map(h => <option key={h} value={h}>{label12(h)}</option>)}
                            </select>
                        </div>
                    </div>
                    <div className="de-two">
                        <div className="de-field">
                            <label htmlFor="de-where">{isMeeting ? "Location" : "Court / venue"}</label>
                            <input id="de-where" value={location} onChange={e => setLocation(e.target.value)} maxLength={200}
                                placeholder={isMeeting ? "Chambers, video call…" : "Court or place (optional)"} />
                        </div>
                        <div className="de-field">
                            <label htmlFor="de-dur">Length</label>
                            <select id="de-dur" value={duration} onChange={e => setDuration(Number(e.target.value))}>
                                {DURATIONS.map(m => <option key={m} value={m}>{durationLabel(m)}</option>)}
                            </select>
                        </div>
                    </div>
                    <div className="de-field">
                        <label>Priority</label>
                        {segmented([["high", "High"], ["medium", "Medium"], ["low", "Low"]], priority, setPriority, "Priority")}
                    </div>
                    <div className="de-field">
                        <label htmlFor="de-notes">Notes</label>
                        <textarea id="de-notes" value={notes} onChange={e => setNotes(e.target.value)} maxLength={2000} rows={3}
                            placeholder="Optional · documents to bring, points to raise…" />
                    </div>
                    {clashes.length > 0 && (
                        <div role="alert" className="de-clash" data-clash>
                            <b>This time clashes with:</b>
                            <ul>{clashes.map(c => <li key={c.key}>{label12(pktHourMinute(c.at))} · {c.title} <span>({c.kind === "court" ? "Court hearing" : c.kind === "appointment" ? "Appointment" : (DIARY_STYLES[c.kind] || DIARY_STYLES.event).label})</span></li>)}</ul>
                            <small>You can still save it.</small>
                        </div>
                    )}
                    <div className="de-hint">All times are Pakistan time (PKT).</div>
                </div>

                <div className="de-foot">
                    {error && <div role="alert" className="de-error">{error}</div>}
                    <button type="button" className="de-save" disabled={busy} onClick={submit}>
                        {busy ? "Saving…" : isMeeting ? "Create meeting" : "Create event"}
                    </button>
                </div>
            </div>
        </div>
    );
}

// ── Export: a month as a CSV file that opens in Excel ─────────
/** One CSV cell. Quoted always; a leading = + - @ is neutralised so a client
 *  name like "=HYPERLINK(...)" is shown as text, not run as a formula. */
function csvCell(value) {
    let s = value == null ? "" : String(value);
    if (/^[=+\-@\t\r]/.test(s)) s = `'${s}`;
    return `"${s.replace(/"/g, '""')}"`;
}

function monthCsv(monthKey, appointments, diary) {
    const rows = [];
    for (const a of appointments) {
        if (!a.at || pktDayKey(a.at).slice(0, 7) !== monthKey) continue;
        rows.push({ at: a.at, cells: [pktDayKey(a.at), pktHourMinute(a.at), a.endAt ? pktDayKey(a.endAt) : "", a.endAt ? pktHourMinute(a.endAt) : "",
            "Appointment", a.purpose, a.client, a.type, a.status, ""] });
    }
    for (const e of diary) {
        const at = new Date(e.starts_at);
        if (pktDayKey(at).slice(0, 7) !== monthKey) continue;
        rows.push({ at, cells: [pktDayKey(at), pktHourMinute(at), pktDayKey(e.ends_at), pktHourMinute(e.ends_at),
            (DIARY_STYLES[e.kind] || DIARY_STYLES.event).label, e.title, e.client_name || "", e.location || "",
            `${(PRIORITY_STYLES[e.priority] || PRIORITY_STYLES.medium).label} priority`, e.notes || ""] });
    }
    rows.sort((x, y) => x.at - y.at);
    const head = ["Date", "Start (PKT)", "End date", "End (PKT)", "Type", "Title / purpose", "Client", "Mode / location", "Status / priority", "Notes"];
    // BOM so Excel reads UTF-8 (Urdu names), CRLF as Excel expects.
    return "﻿" + [head, ...rows.map(r => r.cells)].map(r => r.map(csvCell).join(",")).join("\r\n") + "\r\n";
}

// ── Overview: the cards above the toolbar ─────────────────────
// Every number here is read from data the page holds; nothing is a mock-up
// figure. Where the data cannot answer (no working hours saved, a count the
// server did not return) the card says so instead of guessing.
const AMBER = "#e8b84b";
const TEAL = "#38d8c4";
// Pending is amber everywhere (tab, badges, week chart); this is its brighter
// tone for the one large figure.
const AMBER_BRIGHT = "#f4c762";
const DAY_LETTERS = ["M", "T", "W", "T", "F", "S", "S"];

// The Cases stage-bar colours (2026-10-09): cyan for what is waiting now,
// green for what is done.
const CYAN = "#6ADDEB";
const GREEN = "#3ec99a";

/* EACH DASHBOARD CARD IN ITS OWN ACCENT (2026-10-09). One family -- every card
 * is the theme surface -- each carrying a light wash of the colour of what it
 * is about: cyan waiting, teal today, blue this week, green done, amber hours.
 * Different enough to find at a glance, close enough to read as one set. */
function tinted(t, rgb, { wash = 9, glow = 0.16, edge = 0.3 } = {}) {
    return {
        background: `radial-gradient(120% 95% at 0% 0%, rgba(${rgb},${glow}) 0%, rgba(${rgb},0) 58%), color-mix(in srgb, rgb(${rgb}) ${wash}%, ${t.card})`,
        border: `1px solid rgba(${rgb},${edge})`,
    };
}
const TINT = { pending: "106,221,235", today: "56,216,196", week: "90,179,255", completed: "62,201,154", hours: "232,184,75" };

function dashCard(t, extra = {}) {
    return {
        position: "relative", overflow: "hidden", minWidth: 0,
        borderRadius: 15, padding: "13px 16px",
        background: t.card, border: `1px solid ${t.border}`,
        ...extra,
    };
}

function DashLabel({ children, color, t }) {
    return (
        <div style={{ fontSize: 11, fontWeight: 800, letterSpacing: "0.12em", textTransform: "uppercase", color: color || t.textMuted }}>
            {children}
        </div>
    );
}

function daysAgo(date, now) {
    const days = Math.floor((now - date.getTime()) / 86400000);
    return days <= 0 ? "today" : days === 1 ? "1 day ago" : `${days} days ago`;
}

function PendingCard({ t, total, items, now, canAccept, onReview, onAcceptAll }) {
    const [step, setStep] = useState("idle");          // idle | confirm | busy
    const acceptable = items.filter(canAccept);
    const oldest = items.reduce((min, a) => (a.createdAt && (!min || a.createdAt < min) ? a.createdAt : min), null);
    const count = Number.isInteger(total) ? total : items.length;
    const initials = items.slice(0, 2).map(a => a.initials);
    const extra = Math.max(count - initials.length, 0);
    const run = async () => {
        setStep("busy");
        await onAcceptAll(acceptable);
        setStep("idle");
    };
    return (
        <section aria-label="Pending requests" data-stat="pending" style={dashCard(t, {
            gridArea: "pending", display: "flex", flexDirection: "column", gap: 9,
            // Amber on a neutral card: the glow stays in one corner. A full amber
            // wash over the teal theme mixes to olive.
            ...tinted(t, TINT.pending, { edge: 0.34 }),
        })}>
            {/* Decorative ring, behind everything. */}
            <div aria-hidden="true" style={{ position: "absolute", right: -65, top: -48, width: 205, height: 205, borderRadius: "50%", border: "29px solid rgba(106,221,235,0.06)", pointerEvents: "none" }} />
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", position: "relative" }}>
                <DashLabel t={t} color={CYAN}>Pending requests</DashLabel>
                <button type="button" onClick={onReview}
                    onMouseEnter={e => { e.currentTarget.style.background = "rgba(255,255,255,0.16)"; }}
                    onMouseLeave={e => { e.currentTarget.style.background = "rgba(255,255,255,0.08)"; }}
                    style={{
                        height: 26, padding: "0 12px", borderRadius: 999,
                        border: "1px solid rgba(255,255,255,0.18)", background: "rgba(255,255,255,0.08)",
                        color: "#e6efff", fontSize: 11.5, fontWeight: 700, cursor: "pointer", fontFamily: "inherit",
                        transition: "background .15s",
                    }}>View all →</button>
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 14, position: "relative" }}>
                {/* The display serif (Cormorant Garamond, as the page headings)
                    for the figure and its headline; DM Sans for everything else. */}
                <span data-value className="serif" style={{ fontSize: 62, lineHeight: 0.85, fontWeight: 700, color: CYAN, textShadow: "0 2px 18px rgba(106,221,235,0.35)" }}>{count}</span>
                <div>
                    <div className="serif" style={{ fontSize: 25, lineHeight: 1.1, fontWeight: 700, color: t.text }}>{count === 1 ? "request waiting" : "requests waiting"}</div>
                    <div style={{ fontSize: 12.5, color: t.textMuted, marginTop: 4 }}>
                        {count === 0 ? "You're all caught up." : oldest ? `oldest sent ${daysAgo(oldest, now)}` : ""}
                    </div>
                </div>
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 6, position: "relative" }}>
                {items.slice(0, 3).map(a => {
                    const passed = !canAccept(a);
                    return (
                        <div key={a.id} style={{
                            display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12,
                            padding: "8px 12px", borderRadius: 10, background: "rgba(0,0,0,0.18)",
                            borderLeft: `3px solid ${passed ? "#e8526a" : "rgba(106,221,235,0.7)"}`,
                        }}>
                            <div style={{ minWidth: 0 }}>
                                <div style={{ fontSize: 13.5, fontWeight: 600, color: t.text, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{a.purpose}</div>
                                <div style={{ fontSize: 12, color: t.textMuted, marginTop: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{a.client} · {a.type}</div>
                            </div>
                            <div style={{ textAlign: "right", flexShrink: 0 }}>
                                <div style={{ fontSize: 12.5, fontWeight: 700, color: passed ? "#e8526a" : t.text }}>
                                    {a.at ? new Intl.DateTimeFormat("en-GB", { weekday: "short", day: "numeric", month: "short", timeZone: "Asia/Karachi" }).format(a.at) : "No time"}
                                </div>
                                <div style={{ fontSize: 12, color: passed ? "#e8526a" : t.textMuted, marginTop: 1 }}>
                                    {a.at ? (passed ? "time passed" : label12(pktHourMinute(a.at))) : ""}
                                </div>
                            </div>
                        </div>
                    );
                })}
            </div>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8, flexWrap: "wrap", position: "relative", marginTop: "auto" }}>
                <div style={{ display: "flex" }}>
                    {initials.map((ini, i) => (
                        <span key={i} style={{ width: 28, height: 28, borderRadius: "50%", marginLeft: i ? -7 : 0, display: "inline-flex", alignItems: "center", justifyContent: "center", fontSize: 10, fontWeight: 800, color: TEAL, background: "#1f4b52", border: `2px solid ${t.card}` }}>{ini}</span>
                    ))}
                    {extra > 0 && (
                        <span style={{ width: 28, height: 28, borderRadius: "50%", marginLeft: -7, display: "inline-flex", alignItems: "center", justifyContent: "center", fontSize: 10, fontWeight: 800, color: CYAN, background: "#173c43", border: `2px solid ${t.card}` }}>+{extra}</span>
                    )}
                </div>
                <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                    {step === "idle" && (<>
                        <button type="button" disabled={acceptable.length === 0} onClick={() => setStep("confirm")}
                            title={acceptable.length === 0 ? "No request can be accepted: none, or their times have passed" : undefined}
                            style={{ ...pillStyle(t), height: 33, padding: "0 14px", fontSize: 12.5, opacity: acceptable.length === 0 ? 0.5 : 1, cursor: acceptable.length === 0 ? "not-allowed" : "pointer" }}>Accept all</button>
                        <button type="button" onClick={onReview} style={{ ...pillStyle(t), height: 33, padding: "0 16px", fontSize: 12.5, border: "none", background: CYAN, color: "#0b1c22", boxShadow: "0 4px 14px rgba(106,221,235,0.28)" }}>Review requests</button>
                    </>)}
                    {step !== "idle" && (<>
                        <span style={{ fontSize: 12.5, color: t.textMuted }}>
                            Accept {acceptable.length} request{acceptable.length === 1 ? "" : "s"}{acceptable.length < items.length ? ` (${items.length - acceptable.length} already passed)` : ""}?
                        </span>
                        <button type="button" disabled={step === "busy"} onClick={() => setStep("idle")} style={{ ...pillStyle(t), height: 33, padding: "0 14px", fontSize: 12.5 }}>Cancel</button>
                        <button type="button" disabled={step === "busy"} onClick={run} style={{ ...pillStyle(t), height: 33, padding: "0 16px", fontSize: 12.5, border: "none", background: CYAN, color: "#0b1c22" }}>
                            {step === "busy" ? "Accepting…" : "Confirm"}
                        </button>
                    </>)}
                </div>
            </div>
        </section>
    );
}

function TodayCard({ t, items, workMinutes, now, pendingCount }) {
    const today = pktToday();
    const bookedMin = items.reduce((m, a) => m + (a.at && a.endAt ? (a.endAt - a.at) / 60000 : 0), 0);
    const hours = bookedMin / 60;
    const hoursText = `${Number.isInteger(hours) ? hours : hours.toFixed(1)}h`;
    const share = workMinutes > 0 ? Math.min(bookedMin / workMinutes, 1) : 0;
    const next = items.filter(a => a.at && a.at.getTime() > now).sort((x, y) => x.at - y.at)[0];
    const R = 27, C = 2 * Math.PI * R;
    const message = next ? `Next: ${label12(pktHourMinute(next.at))} with ${next.client}.`
        : items.length ? "No more meetings today."
        : pendingCount > 0 ? "Day is free — good time to clear requests." : "Day is free.";
    return (
        <section aria-label="Today" data-stat="today" style={dashCard(t, { gridArea: "today", display: "flex", flexDirection: "column", gap: 9, ...tinted(t, TINT.today) })}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <DashLabel t={t} color="#38d8c4">Today</DashLabel>
                <span style={{ fontSize: 13, fontWeight: 700, color: t.textMuted }}>
                    {new Intl.DateTimeFormat("en-GB", { weekday: "short", day: "numeric", timeZone: "UTC" }).format(new Date(`${today}T12:00:00Z`))}
                </span>
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
                <svg width="66" height="66" viewBox="0 0 66 66" role="img"
                    aria-label={workMinutes > 0 ? `${hoursText} booked of ${Math.round(workMinutes / 60)}h working hours` : `${hoursText} booked`}>
                    <circle cx="33" cy="33" r={R} fill="none" stroke="rgba(255,255,255,0.08)" strokeWidth="6" />
                    {share > 0 && (
                        <circle cx="33" cy="33" r={R} fill="none" stroke={TEAL} strokeWidth="6" strokeLinecap="round"
                            strokeDasharray={`${C * share} ${C}`} transform="rotate(-90 33 33)" />
                    )}
                    <circle cx="33" cy="6" r="3" fill={TEAL} />
                    <text x="33" y="38" textAnchor="middle" fontSize="13" fontWeight="800" fill={t.text}>{hoursText}</text>
                </svg>
                <div>
                    <div data-value style={{ fontSize: 28, lineHeight: 1, fontWeight: 700, color: items.length ? TEAL : t.textMuted }}>{items.length}</div>
                    <div style={{ fontSize: 12.5, color: t.textMuted, marginTop: 3 }}>{items.length === 1 ? "meeting booked" : "meetings booked"}</div>
                </div>
            </div>
            <div style={{ fontSize: 12.5, color: t.textMuted, lineHeight: 1.45 }}>{message}</div>
        </section>
    );
}

function WeekCard({ t, items }) {
    const keys = pktWeekDayKeys();
    const today = pktToday();
    const days = keys.map(key => {
        const list = items.filter(a => a.at && pktDayKey(a.at) === key);
        return {
            key,
            requests: list.filter(a => a.status === "Pending").length,
            confirmed: list.filter(a => a.status === "Upcoming" || a.status === "Completed").length,
        };
    });
    const confirmedTotal = days.reduce((n, d) => n + d.confirmed, 0);
    const max = Math.max(1, ...days.map(d => d.requests + d.confirmed));
    const BAR = 40;
    const hatch = `repeating-linear-gradient(135deg, ${AMBER} 0 5px, rgba(232,184,75,0.35) 5px 10px)`;
    return (
        <section aria-label="This week" style={dashCard(t, { gridArea: "week", display: "flex", flexDirection: "column", gap: 9, ...tinted(t, TINT.week) })}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <DashLabel t={t} color="#5ab3ff">This week</DashLabel>
                <span style={{ fontSize: 13, fontWeight: 700, color: t.textMuted }}>
                    <span style={{ color: "#5ab3ff", fontSize: 14.5 }}>{confirmedTotal}</span> confirmed
                </span>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(7, 1fr)", gap: 7, alignItems: "end", height: BAR + 20, flex: 1 }}>
                {days.map((d, i) => {
                    const isToday = d.key === today;
                    const reqH = d.requests ? Math.max(10, (d.requests / max) * BAR) : 0;
                    const conH = d.confirmed ? Math.max(10, (d.confirmed / max) * BAR) : 0;
                    return (
                        <div key={d.key} title={`${d.requests} request${d.requests === 1 ? "" : "s"}, ${d.confirmed} confirmed`}
                            style={{ display: "flex", flexDirection: "column", alignItems: "stretch", justifyContent: "flex-end", gap: 3, height: "100%" }}>
                            {reqH > 0 && <div style={{ height: reqH, borderRadius: 6, background: hatch }} />}
                            {conH > 0 && <div style={{ height: conH, borderRadius: 6, background: TEAL }} />}
                            {!reqH && !conH && <div style={{ height: 5, borderRadius: 3, background: isToday ? TEAL : "rgba(255,255,255,0.10)" }} />}
                            <div style={{ textAlign: "center", fontSize: 11, fontWeight: 700, marginTop: 4, color: isToday ? TEAL : t.textMuted }}>{DAY_LETTERS[i]}</div>
                        </div>
                    );
                })}
            </div>
            <div style={{ display: "flex", gap: 14, fontSize: 11.5, color: t.textMuted }}>
                <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}><span style={{ width: 11, height: 11, borderRadius: 3, background: hatch }} />Requests</span>
                <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}><span style={{ width: 11, height: 11, borderRadius: 3, background: TEAL }} />Confirmed</span>
            </div>
        </section>
    );
}

function CompletedCard({ t, items }) {
    const month = pktToday().slice(0, 7);
    const inMonth = items.filter(a => a.at && pktDayKey(a.at).slice(0, 7) === month);
    const done = inMonth.filter(a => a.status === "Completed").length;
    const noShows = inMonth.filter(a => a.status === "No Show").length;
    return (
        <section aria-label="Completed" data-stat="completed" style={dashCard(t, { gridArea: "completed", display: "flex", flexDirection: "column", gap: 6,
            ...tinted(t, TINT.completed, { edge: 0.34 }) })}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <DashLabel t={t} color={GREEN}>Completed</DashLabel>
                <span style={{ fontSize: 13, fontWeight: 700, color: t.textMuted }}>{monthTitle(month).split(" ")[0]}</span>
            </div>
            <div data-value style={{ fontSize: 28, lineHeight: 1.1, fontWeight: 700, color: done ? GREEN : t.textMuted }}>{done}</div>
            <div style={{ fontSize: 12.5, color: t.textMuted }}>
                {done === 0 && noShows === 0 ? "No outcomes recorded yet"
                    : `consultation${done === 1 ? "" : "s"} completed this month${noShows ? ` · ${noShows} no-show${noShows === 1 ? "" : "s"}` : ""}`}
            </div>
        </section>
    );
}

function HoursCard({ t, hours, onOpen }) {
    const configured = hours.state === "ready" && hours.configured;
    const days = configured ? new Set(hours.rows.map(r => Number(r.weekday))).size : 0;
    const weekly = configured ? hours.rows.reduce((m, r) => m + (HALF_HOURS.indexOf(r.end) - HALF_HOURS.indexOf(r.start)) * 30, 0) / 60 : 0;
    return (
        <section aria-label="Working hours" style={dashCard(t, {
            gridArea: "hours", display: "flex", flexDirection: "column", gap: 8,
            ...(configured ? tinted(t, TINT.hours, { wash: 7 }) : { border: "1.5px dashed rgba(232,184,75,0.45)", background: "color-mix(in srgb, rgb(232,184,75) 5%, transparent)" }),
        })}>
            <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                <span style={{ width: 30, height: 30, borderRadius: 9, flexShrink: 0, display: "inline-flex", alignItems: "center", justifyContent: "center", background: "rgba(232,184,75,0.12)", color: AMBER }}>
                    <Icon d={I.clock} size={16} />
                </span>
                <div style={{ fontSize: 14, fontWeight: 800, color: t.text }}>{configured ? "Working hours set" : "Set your working hours"}</div>
            </div>
            <div style={{ fontSize: 12.5, color: t.textMuted, lineHeight: 1.45 }}>
                {hours.state === "error" ? "Could not load your working hours."
                    : hours.state === "loading" ? "Loading…"
                    : configured ? `${days} day${days === 1 ? "" : "s"} a week · ${Number.isInteger(weekly) ? weekly : weekly.toFixed(1)} hours`
                    : "Until you do, clients are told your availability is not set."}
            </div>
            <div style={{ flex: 1 }} />
            <button type="button" onClick={onOpen} style={{ ...pillStyle(t), alignSelf: "flex-start", height: 31, padding: "0 14px", fontSize: 12.5, border: "none", background: "#f2f2ec", color: "#16262b" }}>
                {configured ? "Edit hours" : "Set up · 2 min"}
            </button>
        </section>
    );
}

// ── Video consultation modal ──────────────────────────────────
/** What a lawyer sees for a video consultation.
 *
 * THIS USED TO INVENT A ROOM. It displayed
 * `https://meet.attorney.ai/room/{id}-{firstname}` — a host this product does
 * not own and a room nobody had created — listed the platform as
 * "Zoom / Google Meet", and gave Copy and Launch buttons with no handlers at
 * all. A lawyer could read that URL to a client over the phone and both would
 * arrive nowhere.
 *
 * Now it shows the STORED link or says there is none, and every control does
 * what it says. Nothing here claims a provider: the link is whatever the
 * lawyer pasted, which is the only thing anyone actually knows about it.
 */
function JoinCallModal({ apt, onClose, onSaveLink, t }) {
    const [link, setLink] = useState("");
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState(null);
    const [copied, setCopied] = useState(false);

    const stored = apt.meetingLink || null;

    const copy = async () => {
        try {
            await navigator.clipboard.writeText(stored);
            setCopied(true);
            setTimeout(() => setCopied(false), 2000);
        } catch {
            // Clipboard access can be refused outright. Saying so beats a
            // button that silently does nothing — which is what the previous
            // Copy button did in every browser.
            setError("Could not copy — select the link and copy it manually.");
        }
    };

    const save = async () => {
        if (busy) return;
        const value = link.trim();
        if (!value) { setError("Paste the joining link first."); return; }
        if (!/^https:\/\/.+\..+/i.test(value)) {
            // Mirrors the server's rule so the common mistake is caught before
            // a round trip. The server is still the authority.
            setError("The link must start with https:// and include a host.");
            return;
        }
        setBusy(true);
        setError(null);
        const { error: err } = await onSaveLink(apt.id, value);
        setBusy(false);
        if (err) { setError(err.message || "Could not save the link."); return; }
        setLink("");
    };

    const row = { display: "flex", justifyContent: "space-between", padding: "5px 0", borderBottom: `1px solid color-mix(in srgb, ${t.border} 13%, transparent)` };

    return (
        <div style={{ position: "fixed", inset: 0, zIndex: 9999, display: "flex", alignItems: "center", justifyContent: "center", background: "rgba(0,0,0,0.65)", padding: 16 }} onClick={onClose}>
            <div onClick={e => e.stopPropagation()} role="dialog" aria-label="Video consultation" style={{
                background: t.card, border: `1px solid ${t.primary}40`,
                borderRadius: 18, padding: 26, width: "100%", maxWidth: 420,
                boxShadow: `0 20px 60px rgba(0,0,0,0.4), 0 0 0 1px ${t.primary}20`,
            }}>
                <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 18 }}>
                    <div style={{
                        width: 44, height: 44, borderRadius: 12,
                        background: `${t.primary}20`, border: `1.5px solid ${t.primary}50`,
                        display: "flex", alignItems: "center", justifyContent: "center", fontSize: 20,
                    }}>📹</div>
                    <div>
                        <div style={{ fontSize: 16, fontWeight: 700, color: t.text }}>Video consultation</div>
                        <div style={{ fontSize: 12, color: t.textMuted }}>with {apt.client}</div>
                    </div>
                    <button type="button" onClick={onClose} aria-label="Close" style={{ marginLeft: "auto", background: "none", border: "none", color: t.textMuted, cursor: "pointer", fontSize: 18, minHeight: 44, minWidth: 44 }}>✕</button>
                </div>

                <div style={{ background: t.cardHi, borderRadius: 12, padding: "12px 16px", marginBottom: 16 }}>
                    {/* No "Platform" row. This product does not know which
                        service the link belongs to, and the old one asserted
                        "Zoom / Google Meet" regardless. */}
                    {[["📅 Date", apt.date], ["⏰ Time", `${apt.time} · ${apt.duration}`]].map(([k, v]) => (
                        <div key={k} style={row}>
                            <span style={{ fontSize: 12, color: t.textFaint }}>{k}</span>
                            <span style={{ fontSize: 12, fontWeight: 600, color: t.text }}>{v}</span>
                        </div>
                    ))}
                </div>

                {error && (
                    <div role="alert" style={{ marginBottom: 12, fontSize: 12, color: t.danger, fontWeight: 600 }}>
                        {error}
                    </div>
                )}

                {stored ? (
                    <>
                        <div style={{
                            display: "flex", alignItems: "center", gap: 8, padding: "10px 14px",
                            borderRadius: 10, background: `${t.primary}10`,
                            border: `1px solid ${t.primary}30`, marginBottom: 16, flexWrap: "wrap",
                        }}>
                            <span style={{ fontSize: 12, color: t.primary, fontFamily: "monospace", flex: "1 1 180px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                                {stored}
                            </span>
                            <button type="button" onClick={copy} style={{
                                padding: "8px 12px", minHeight: 44, borderRadius: 7, border: "none",
                                background: t.primary, color: t.mode === "dark" ? "#0b1c22" : "#fff",
                                fontSize: 11, fontWeight: 700, cursor: "pointer", fontFamily: "inherit",
                            }}>{copied ? "Copied" : "Copy"}</button>
                        </div>
                        <div className="rgrid-2" style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
                            <button type="button" onClick={onClose} style={{
                                padding: "10px", minHeight: 44, borderRadius: 10, border: `1px solid ${t.border}`,
                                background: "transparent", color: t.textMuted,
                                fontSize: 13, fontWeight: 600, fontFamily: "inherit", cursor: "pointer",
                            }}>Close</button>
                            {/* A real anchor to the stored link. The old
                                "Launch Call" button had no handler at all. */}
                            <a href={stored} target="_blank" rel="noreferrer" style={{
                                padding: "10px", minHeight: 44, borderRadius: 10,
                                background: `linear-gradient(135deg,${t.primary},#22a898)`,
                                color: t.mode === "dark" ? "#0b1c22" : "#fff",
                                fontSize: 13, fontWeight: 700, cursor: "pointer",
                                display: "inline-flex", alignItems: "center", justifyContent: "center",
                                textDecoration: "none", boxShadow: `0 4px 14px ${t.primary}50`,
                            }}>📹 Open link</a>
                        </div>
                    </>
                ) : (
                    <>
                        <div style={{ fontSize: 12, color: t.textMuted, lineHeight: 1.5, marginBottom: 12 }}>
                            <strong style={{ color: t.text }}>No joining link yet.</strong>{" "}
                            This product does not host video calls — paste the link
                            from whichever service you are using, and your client
                            will see it on their appointment.
                        </div>
                        <input
                            type="url"
                            value={link}
                            onChange={e => setLink(e.target.value)}
                            placeholder="https://…"
                            disabled={busy}
                            aria-label="Joining link"
                            style={{
                                width: "100%", minHeight: 44, padding: "10px 12px",
                                borderRadius: 9, border: `1px solid ${t.border}`,
                                background: t.inputBg, color: t.text,
                                fontSize: 13, fontFamily: "inherit", marginBottom: 12,
                            }} />
                        <div className="rgrid-2" style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
                            <button type="button" onClick={onClose} disabled={busy} style={{
                                padding: "10px", minHeight: 44, borderRadius: 10, border: `1px solid ${t.border}`,
                                background: "transparent", color: t.textMuted,
                                fontSize: 13, fontWeight: 600, fontFamily: "inherit", cursor: "pointer",
                            }}>Close</button>
                            <button type="button" onClick={save} disabled={busy} aria-busy={busy} style={{
                                padding: "10px", minHeight: 44, borderRadius: 10, border: "none",
                                background: `linear-gradient(135deg,${t.primary},#22a898)`,
                                color: t.mode === "dark" ? "#0b1c22" : "#fff",
                                fontSize: 13, fontWeight: 700, fontFamily: "inherit",
                                cursor: busy ? "not-allowed" : "pointer", opacity: busy ? 0.6 : 1,
                            }}>{busy ? "Saving…" : "Save link"}</button>
                        </div>
                    </>
                )}
            </div>
        </div>
    );
}

// ── Main page ─────────────────────────────────────────────────
/* Appointments on the lawyer document theme (2026-10-09), like Cases: type,
 * ground and neutral colours from draftingTheme.js; layout and logic as they
 * were. The page fills <main> itself (App.jsx gives it no padding), so the
 * ground reaches the edges. */
export const APPTS_THEME_CSS = `[data-appts-ws]{height:100%;box-sizing:border-box;padding:24px;color:var(--ink);font-family:"Hanken Grotesk",system-ui,sans-serif;-webkit-font-smoothing:antialiased;background:radial-gradient(900px 360px at 25% -80px,var(--glow),transparent 70%) no-repeat,var(--bg)}
[data-appts-ws][data-mode="dark"]{--bg:#39494a}
[data-appts-ws] .serif{font-family:"Literata",Georgia,serif!important;letter-spacing:-.01em}
[data-appts-ws] input,[data-appts-ws] select,[data-appts-ws] textarea,[data-appts-ws] button{font-family:inherit}
[data-appts-ws] .wh-lead{margin:0;font-size:15px;line-height:1.6;color:var(--ink)}
[data-appts-ws] .wh-lead strong{font-weight:700}
[data-appts-ws] .wh-set{border:0;padding:0;margin:0;display:flex;flex-direction:column;gap:12px}
[data-appts-ws] .wh-legend{padding:0;margin-bottom:10px;font-size:11.5px;font-weight:800;letter-spacing:.14em;text-transform:uppercase;color:var(--muted)}
[data-appts-ws] .wh-hint{font-size:13px;color:var(--muted)}
[data-appts-ws] .wh-day{display:grid;grid-template-columns:62px 1fr;gap:10px 12px;align-items:center}
[data-appts-ws] .wh-name{justify-self:start;padding:6px 0;border:0;background:none;color:var(--ink);font:inherit;font-size:16px;font-weight:700;cursor:pointer;border-radius:6px}
[data-appts-ws] .wh-name:hover{color:var(--hover-ink)}
[data-appts-ws] .wh-day.closed .wh-name{color:var(--ink)}
[data-appts-ws] .wh-closed{justify-self:start;display:inline-flex;align-items:center;gap:10px;padding:6px 0;border:0;background:none;color:var(--ink);font:inherit;font-size:16px;cursor:pointer}
[data-appts-ws] .wh-closed em{font-style:normal;font-size:13px;font-weight:700;color:var(--brand-text);opacity:0;transition:opacity .15s}
[data-appts-ws] .wh-closed:hover em,[data-appts-ws] .wh-closed:focus-visible em{opacity:1}
[data-appts-ws] .wh-slot{grid-column:2;display:grid;grid-template-columns:1fr 1fr 36px;gap:12px;align-items:center}
[data-appts-ws] .wh-slot select{appearance:none;-webkit-appearance:none;width:100%;height:56px;padding:0 40px 0 22px;border-radius:16px;border:1px solid var(--line);background:var(--input) url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='16' height='16' viewBox='0 0 24 24' fill='none' stroke='%23E5EAF0' stroke-width='2.4' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='m6 9 6 6 6-6'/%3E%3C/svg%3E") no-repeat right 16px center;color:var(--ink);font:inherit;font-size:17px;cursor:pointer;outline:none;transition:border-color .15s,box-shadow .15s}
[data-appts-ws][data-mode="light"] .wh-slot select{background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='16' height='16' viewBox='0 0 24 24' fill='none' stroke='%23334' stroke-width='2.4' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='m6 9 6 6 6-6'/%3E%3C/svg%3E")}
[data-appts-ws] .wh-slot select:hover{border-color:var(--hover-line)}
[data-appts-ws] .wh-slot select:focus{border-color:var(--focus);box-shadow:0 0 0 3px var(--brand-soft)}
[data-appts-ws] .wh-slot select option{background:var(--surface);color:var(--ink)}
[data-appts-ws] .wh-mini{width:36px;height:36px;display:grid;place-items:center;border-radius:10px;border:1px solid var(--line);background:transparent;color:var(--muted);font:inherit;font-size:16px;font-weight:700;cursor:pointer;transition:color .15s,border-color .15s,background .15s}
[data-appts-ws] .wh-mini:hover:not(:disabled){color:var(--hover-ink);border-color:var(--hover-line);background:var(--hover-tint)}
[data-appts-ws] .wh-mini:disabled{opacity:.35;cursor:not-allowed}
[data-appts-ws] .wh-off{display:flex;gap:10px;flex-wrap:wrap;align-items:flex-end;padding:12px;border-radius:14px;border:1px solid var(--line);background:var(--surface-2)}
[data-appts-ws] .wh-off label{display:flex;flex-direction:column;gap:4px;font-size:12px;color:var(--muted)}
[data-appts-ws] .wh-off input{height:42px;padding:0 12px;border-radius:12px;border:1px solid var(--line);background:var(--input);color:var(--ink);font:inherit;font-size:14px;outline:none;box-sizing:border-box;color-scheme:light dark}
[data-appts-ws] .wh-off input:focus{border-color:var(--focus)}
[data-appts-ws] .wh-add{align-self:flex-start;height:38px;padding:0 14px;border-radius:12px;border:1px dashed var(--line-strong);background:transparent;color:var(--ink);font:inherit;font-size:13.5px;font-weight:700;cursor:pointer}
[data-appts-ws] .wh-add:hover{border-color:var(--hover-line);color:var(--hover-ink);background:var(--hover-tint)}
[data-appts-ws] .wh-foot{position:sticky;bottom:0;margin:0 -22px;padding:14px 22px 20px;display:flex;flex-direction:column;gap:8px;background:var(--surface)}
[data-appts-ws] .wh-error{padding:10px 12px;border-radius:10px;background:var(--danger-soft);border:1px solid color-mix(in srgb,var(--danger) 40%,transparent);font-size:13px;color:var(--danger)}
[data-appts-ws] .wh-ok{font-size:13px;font-weight:600;color:#3ec99a}
[data-appts-ws] .wh-save{height:56px;border:0;border-radius:16px;background:var(--brand-solid);color:var(--on-brand);font:inherit;font-size:17px;font-weight:700;cursor:pointer;box-shadow:0 12px 26px -12px rgba(46,196,214,.8);transition:transform .15s,background .15s}
[data-appts-ws] .wh-save:hover:not(:disabled){background:var(--brand-solid-hover);transform:translateY(-1px)}
[data-appts-ws] .wh-save:disabled{opacity:.6;cursor:wait}
[data-appts-ws] .de-backdrop{position:fixed;inset:0;z-index:9999;display:flex;align-items:center;justify-content:center;padding:16px;background:rgba(4,14,17,.55);backdrop-filter:blur(4px);-webkit-backdrop-filter:blur(4px)}
[data-appts-ws] .de-card{width:min(460px,100%);max-height:calc(100vh - 32px);display:flex;flex-direction:column;overflow:hidden;border-radius:22px;border:1px solid var(--line);background:var(--surface);box-shadow:0 30px 70px -20px rgba(0,0,0,.6);animation:whIn .22s cubic-bezier(.34,1.56,.64,1)}
[data-appts-ws] .de-head{display:flex;align-items:center;justify-content:space-between;padding:18px 22px 0}
[data-appts-ws] .de-head h2{margin:0;font-size:17px;font-weight:700;color:var(--ink)}
[data-appts-ws] .de-cancel{border:0;background:none;padding:4px 0;color:var(--brand-text);font:inherit;font-size:14px;font-weight:700;cursor:pointer}
[data-appts-ws] .de-cancel:hover{color:var(--hover-ink);text-decoration:underline;text-underline-offset:3px}
[data-appts-ws] .de-sub{margin:3px 22px 0;font-size:12px;color:var(--muted)}
[data-appts-ws] .de-body{overflow-y:auto;padding:14px 22px 4px;display:flex;flex-direction:column;gap:12px}
[data-appts-ws] .de-field{display:flex;flex-direction:column;gap:6px;min-width:0}
[data-appts-ws] .de-field > label{font-size:13px;font-weight:600;color:var(--muted)}
[data-appts-ws] .de-req{color:var(--danger)}
[data-appts-ws] .de-two{display:grid;grid-template-columns:1fr 1fr;gap:12px}
[data-appts-ws] .de-field input,[data-appts-ws] .de-field select,[data-appts-ws] .de-field textarea{width:100%;box-sizing:border-box;min-height:42px;padding:0 13px;border-radius:12px;border:1px solid var(--line);background:var(--input);color:var(--ink);font:inherit;font-size:14px;outline:none;transition:border-color .15s,box-shadow .15s;color-scheme:light dark}
[data-appts-ws] .de-field textarea{padding:10px 13px;min-height:64px;resize:vertical;line-height:1.5}
[data-appts-ws] .de-field select{appearance:none;-webkit-appearance:none;padding-right:34px;cursor:pointer;background:var(--input) url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='16' height='16' viewBox='0 0 24 24' fill='none' stroke='%23E5EAF0' stroke-width='2.4' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='m6 9 6 6 6-6'/%3E%3C/svg%3E") no-repeat right 14px center}
[data-appts-ws][data-mode="light"] .de-field select{background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='16' height='16' viewBox='0 0 24 24' fill='none' stroke='%23334' stroke-width='2.4' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='m6 9 6 6 6-6'/%3E%3C/svg%3E")}
[data-appts-ws] .de-field select option{background:var(--surface);color:var(--ink)}
[data-appts-ws] .de-field input::placeholder,[data-appts-ws] .de-field textarea::placeholder{color:var(--faint)}
[data-appts-ws] .de-field input:hover,[data-appts-ws] .de-field select:hover,[data-appts-ws] .de-field textarea:hover{border-color:var(--hover-line)}
[data-appts-ws] .de-field input:focus,[data-appts-ws] .de-field select:focus,[data-appts-ws] .de-field textarea:focus{border-color:var(--brand-text);box-shadow:0 0 0 3px var(--brand-soft)}
[data-appts-ws] .de-seg{display:grid;gap:8px}
[data-appts-ws] .de-seg button{min-height:40px;border-radius:12px;border:1px solid var(--line);background:var(--input);color:var(--ink);font:inherit;font-size:13.5px;font-weight:700;cursor:pointer;transition:border-color .15s,background .15s,color .15s}
[data-appts-ws] .de-seg button:hover{border-color:var(--hover-line)}
[data-appts-ws] .de-seg button[aria-checked="true"]{border-color:var(--brand-text);background:color-mix(in srgb,var(--brand-text) 16%,var(--input));color:var(--ink)}
[data-appts-ws] .de-hint{font-size:12px;color:var(--faint)}
[data-appts-ws] .de-foot{padding:10px 22px 18px;display:flex;flex-direction:column;gap:8px}
[data-appts-ws] .de-error{font-size:13px;color:var(--danger)}
[data-appts-ws] .de-save{height:46px;border:0;border-radius:13px;background:linear-gradient(90deg,#3EE0A1,#38CDE0);color:#0b1c22;font:inherit;font-size:15px;font-weight:700;cursor:pointer;box-shadow:0 12px 26px -12px rgba(46,196,214,.8);transition:transform .15s,filter .15s}
[data-appts-ws] .de-save:hover:not(:disabled){filter:brightness(1.06);transform:translateY(-1px)}
[data-appts-ws] .de-save:disabled{opacity:.6;cursor:wait}
[data-appts-ws] .ad{padding:20px 22px 22px;display:flex;flex-direction:column;gap:12px;animation:whIn .2s ease}
[data-appts-ws] .ad-top{display:flex;align-items:center;justify-content:space-between}
[data-appts-ws] .ad-pill{display:inline-flex;align-items:center;gap:6px;height:26px;padding:0 11px;border-radius:999px;font-size:12.5px;font-weight:700}
[data-appts-ws] .ad-pill i,[data-appts-ws] .ad-kind i{width:6px;height:6px;border-radius:50%;background:currentColor}
[data-appts-ws] .ad-pill.green{color:#3ec99a;background:rgba(62,201,154,.14);border:1px solid rgba(62,201,154,.4)}
[data-appts-ws] .ad-pill.gold{color:#e8b84b;background:rgba(232,184,75,.14);border:1px solid rgba(232,184,75,.4)}
[data-appts-ws] .ad-pill.red{color:var(--danger);background:var(--danger-soft);border:1px solid color-mix(in srgb,var(--danger) 40%,transparent)}
[data-appts-ws] .ad-pill.muted{color:var(--muted);background:var(--chip-n);border:1px solid var(--line)}
[data-appts-ws] .ad-x{width:34px;height:34px;border-radius:10px;border:1px solid var(--line);background:transparent;color:var(--muted);font:inherit;font-size:14px;cursor:pointer}
[data-appts-ws] .ad-x:hover{color:var(--hover-ink);border-color:var(--hover-line);background:var(--hover-tint)}
[data-appts-ws] .ad-kind{display:inline-flex;align-items:center;gap:6px;font-size:12.5px;font-weight:700;color:var(--brand-text)}
[data-appts-ws] .ad h3{margin:0;font-size:24px;line-height:1.2;font-weight:600;color:var(--ink)}
[data-appts-ws] .ad-when{margin-top:-6px;font-size:13.5px;color:var(--muted)}
[data-appts-ws] .ad-client{display:flex;align-items:center;gap:12px;margin-top:4px}
[data-appts-ws] .ad-av{width:40px;height:40px;flex:none;border-radius:50%;display:grid;place-items:center;font-size:13px;font-weight:800;color:#fff;background:#6c5ce7}
[data-appts-ws] .ad-client b{display:block;font-size:15px;color:var(--ink)}
[data-appts-ws] .ad-client small{display:block;font-size:12.5px;color:var(--muted)}
[data-appts-ws] .ad-rows{margin:4px 0 0;display:grid;gap:10px}
[data-appts-ws] .ad-rows > div{display:flex;justify-content:space-between;align-items:center;gap:12px;font-size:14px}
[data-appts-ws] .ad-rows dt{color:var(--muted)}
[data-appts-ws] .ad-rows dd{margin:0;text-align:right;color:var(--ink)}
[data-appts-ws] .ad-case{padding:3px 10px;border-radius:8px;border:1px solid var(--line-strong);background:var(--surface-2);color:var(--brand-text);font:600 12.5px "JetBrains Mono",monospace;cursor:pointer}
[data-appts-ws] .ad-case:hover{border-color:var(--hover-line);color:var(--hover-ink)}
[data-appts-ws] .ad-note{margin:4px 0 0;padding:12px 14px;border-radius:12px;border:1px solid var(--line);background:var(--surface-2);font-size:13.5px;line-height:1.55;color:var(--ink)}
[data-appts-ws] .ad-actions{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:6px}
[data-appts-ws] .ad-btn{height:42px;border-radius:12px;border:1px solid var(--line-strong);background:transparent;color:var(--ink);font:inherit;font-size:14px;font-weight:700;cursor:pointer;transition:border-color .15s,background .15s,color .15s}
[data-appts-ws] .ad-btn:hover:not(:disabled){border-color:var(--hover-line);background:var(--hover-tint);color:var(--hover-ink)}
[data-appts-ws] .ad-btn:disabled{opacity:.45;cursor:not-allowed}
[data-appts-ws] .ad-btn.primary{border:0;background:linear-gradient(90deg,#3EE0A1,#38CDE0);color:#0b1c22}
[data-appts-ws] .ad-btn.primary:hover:not(:disabled){filter:brightness(1.06);color:#0b1c22}
[data-appts-ws] .ad-btn.danger{color:var(--danger)}
[data-appts-ws] .ad-btn.danger:hover:not(:disabled){border-color:var(--danger);background:var(--danger-soft);color:var(--danger)}
[data-appts-ws] .ag-appt{cursor:pointer;transition:border-color .15s,background .15s}
[data-appts-ws] .ag-appt:hover{border-color:var(--hover-line)!important;background:var(--hover-tint)!important}
[data-appts-ws] .rb-menu{position:relative}
[data-appts-ws] .rb-trigger{display:inline-flex;align-items:center;gap:10px;height:42px;padding:0 18px 0 22px;border-radius:999px;border:1px solid var(--line-strong);background:transparent;color:var(--ink);font:inherit;font-size:14.5px;font-weight:700;cursor:pointer;transition:border-color .15s}
[data-appts-ws] .rb-trigger:hover{border-color:var(--hover-line)}
[data-appts-ws] .rb-list{position:absolute;right:0;top:calc(100% + 8px);z-index:60;min-width:170px;padding:7px;display:flex;flex-direction:column;gap:3px;border-radius:16px;border:1px solid var(--line);background:var(--surface);box-shadow:0 18px 40px -16px rgba(0,0,0,.6);animation:whIn .16s ease}
[data-appts-ws] .rb-list button{height:40px;padding:0 16px;border:0;border-radius:11px;background:transparent;color:var(--ink);font:inherit;font-size:15px;font-weight:600;text-align:left;cursor:pointer}
[data-appts-ws] .rb-list button:hover{background:var(--hover-tint)}
[data-appts-ws] .rb-list button[aria-selected="true"]{background:var(--surface-2);font-weight:800}
[data-appts-ws] .rb-head{display:flex;align-items:center;gap:8px;padding:14px 16px;border-bottom:1px solid var(--line)}
[data-appts-ws] .rb-head h3{margin:0 0 0 8px;font-size:17px;font-weight:800;color:var(--ink)}
[data-appts-ws] .rb-nav,[data-appts-ws] .rb-today{height:34px;min-width:34px;padding:0 12px;border-radius:9px;border:1px solid var(--line);background:var(--surface-2);color:var(--ink);font:inherit;font-size:14px;font-weight:700;cursor:pointer}
[data-appts-ws] .rb-nav:hover,[data-appts-ws] .rb-today:hover{border-color:var(--hover-line);color:var(--hover-ink)}
[data-appts-ws] .rb-week{display:grid;grid-template-columns:repeat(7,minmax(0,1fr));min-height:360px}
[data-appts-ws] .rb-col{border-right:1px solid var(--line);display:flex;flex-direction:column;min-width:0}
[data-appts-ws] .rb-col:last-child{border-right:0}
[data-appts-ws] .rb-col.sel{background:color-mix(in srgb,var(--brand-text) 6%,transparent)}
[data-appts-ws] .rb-colhead{display:flex;flex-direction:column;align-items:center;gap:2px;padding:10px 4px 8px;border:0;border-bottom:1px solid var(--line);background:transparent;color:var(--muted);font:inherit;cursor:pointer}
[data-appts-ws] .rb-colhead span{font-size:12px;font-weight:700}
[data-appts-ws] .rb-colhead b{font-size:19px;color:var(--ink);width:34px;height:34px;display:grid;place-items:center;border-radius:50%}
[data-appts-ws] .rb-col.today .rb-colhead b{background:linear-gradient(90deg,#3EE0A1,#38CDE0);color:#0b1c22}
[data-appts-ws] .rb-colhead:hover b{outline:1px solid var(--hover-line)}
[data-appts-ws] .rb-colbody{display:flex;flex-direction:column;gap:6px;padding:8px 6px}
[data-appts-ws] .rb-none{text-align:center;color:var(--faint);font-size:12px;padding-top:6px}
[data-appts-ws] .rb-chip{display:flex;flex-direction:column;align-items:flex-start;gap:1px;width:100%;padding:6px 8px;border-radius:9px;border:1px solid color-mix(in srgb,var(--c) 40%,transparent);border-left:3px solid var(--c);background:color-mix(in srgb,var(--c) 14%,transparent);color:var(--ink);font:inherit;text-align:left;cursor:pointer;transition:transform .12s}
[data-appts-ws] .rb-chip:hover{transform:translateY(-1px)}
[data-appts-ws] .rb-chip b{font-size:11.5px;color:var(--c)}
[data-appts-ws] .rb-chip span{font-size:12.5px;font-weight:600;max-width:100%;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
[data-appts-ws] .rb-day{display:flex;flex-direction:column;gap:8px;padding:14px 16px;min-height:300px}
[data-appts-ws] .rb-empty{color:var(--muted);font-size:13.5px;padding:8px 2px}
[data-appts-ws] .rb-row{display:flex;align-items:stretch;gap:14px;width:100%;padding:12px 14px;border-radius:12px;border:1px solid var(--line);border-left:4px solid var(--c);background:var(--surface-2);color:var(--ink);font:inherit;text-align:left;cursor:pointer;transition:border-color .15s,background .15s}
[data-appts-ws] .rb-row:hover{background:var(--hover-tint)}
[data-appts-ws] .rb-time{width:78px;flex:none;font-size:14px;font-weight:800;color:var(--c)}
[data-appts-ws] .rb-time small{display:block;font-size:11.5px;font-weight:600;color:var(--muted)}
[data-appts-ws] .rb-what b{display:block;font-size:14.5px}
[data-appts-ws] .rb-what small{display:block;font-size:12.5px;color:var(--muted);margin-top:2px}
[data-appts-ws] .ap-crumbs{font-size:13.5px;color:var(--muted)}
[data-appts-ws] .ap-crumbs b{color:var(--ink);font-weight:600}
[data-appts-ws] .ap-title{margin:6px 0 0;font:600 clamp(32px,3.6vw,42px)/1.05 "Literata",Georgia,serif;letter-spacing:-.01em;color:var(--ink)}
[data-appts-ws] .rb-head.center{flex-direction:column-reverse;align-items:center;gap:10px;padding:16px}
[data-appts-ws] .rb-navs{display:flex;gap:8px}
[data-appts-ws] .rb-title{display:flex;flex-direction:column}
[data-appts-ws] .rb-head:not(.center) .rb-title{margin-left:8px}
[data-appts-ws] .rb-head.center .rb-title{align-items:center}
[data-appts-ws] .rb-title h3{margin:0;font-size:17px;font-weight:800;color:var(--ink)}
[data-appts-ws] .rb-head.center .rb-title h3{font-size:19px}
[data-appts-ws] .rb-title small{margin-top:4px;font-size:11.5px;font-weight:700;letter-spacing:.24em;color:var(--muted)}
[data-appts-ws] .tg{overflow-x:auto}
[data-appts-ws] .tg-row{display:grid;border-bottom:1px solid var(--line)}
[data-appts-ws] .tg-heads > span{border-right:1px solid var(--line)}
[data-appts-ws] .tg-head{display:flex;flex-direction:column;align-items:center;gap:2px;padding:10px 4px;border:0;border-right:1px solid var(--line);background:transparent;color:var(--muted);font:inherit;cursor:pointer}
[data-appts-ws] .tg-head:last-child{border-right:0}
[data-appts-ws] .tg-head span{font-size:13px;font-weight:700;color:var(--ink)}
[data-appts-ws] .tg-head b{font-size:17px;font-weight:600;color:var(--ink);width:32px;height:32px;display:grid;place-items:center;border-radius:50%}
[data-appts-ws] .tg-head.today b{background:linear-gradient(90deg,#3EE0A1,#38CDE0);color:#0b1c22}
[data-appts-ws] .tg-head.sel{background:color-mix(in srgb,var(--brand-text) 7%,transparent)}
[data-appts-ws] .tg-head:hover b{outline:1px solid var(--hover-line)}
[data-appts-ws] .tg-label{display:grid;place-items:center;border-right:1px solid var(--line);font-size:11px;font-weight:800;letter-spacing:.2em;color:var(--muted)}
[data-appts-ws] .tg-cell{min-height:56px;padding:6px;display:flex;flex-direction:column;gap:4px;justify-content:center;border-right:1px solid var(--line);background:var(--surface-2)}
[data-appts-ws] .tg-cell:last-child{border-right:0}
[data-appts-ws] .tg-cell em{font-style:normal;font-size:12px;color:var(--faint);text-align:center}
[data-appts-ws] .tg-body{display:grid;max-height:620px;overflow-y:auto}
[data-appts-ws] .tg-hours{border-right:1px solid var(--line)}
[data-appts-ws] .tg-hours > div{display:flex;justify-content:center;padding-top:6px;box-sizing:border-box;border-bottom:1px solid var(--line);font-size:13px;font-weight:600;color:var(--ink)}
[data-appts-ws] .tg-body .rb-col{position:relative;border-right:1px solid var(--line);background:repeating-linear-gradient(180deg,transparent 0 59px,var(--line) 59px 60px)}
[data-appts-ws] .tg-body .rb-col:last-child{border-right:0}
[data-appts-ws] .tg-body .rb-col.sel{background-color:color-mix(in srgb,var(--brand-text) 5%,transparent)}
[data-appts-ws] .tg-body .rb-col.can-add{cursor:pointer}
[data-appts-ws] .tg-body .rb-col.can-add:focus-visible{outline:2px solid var(--brand-text);outline-offset:-2px}
[data-appts-ws] .tg-ghost{position:absolute;left:3px;right:3px;z-index:0;display:flex;align-items:center;padding:0 8px;border-radius:8px;border:1px dashed var(--brand-text);background:color-mix(in srgb,var(--brand-text) 12%,transparent);color:var(--brand-text);font-style:normal;font-size:12px;font-weight:700;pointer-events:none}
[data-appts-ws] .tg-off{position:absolute;left:0;right:0;z-index:0;pointer-events:none;background:repeating-linear-gradient(135deg,rgba(255,255,255,.035) 0 6px,transparent 6px 12px),color-mix(in srgb,var(--bg) 35%,transparent)}
[data-appts-ws][data-mode="light"] .tg-off{background:repeating-linear-gradient(135deg,rgba(0,0,0,.04) 0 6px,transparent 6px 12px),rgba(0,0,0,.025)}
[data-appts-ws] .tg .rb-chip.tentative{border-style:dashed;border-left-style:dashed;background:repeating-linear-gradient(135deg,color-mix(in srgb,var(--c) 16%,transparent) 0 6px,color-mix(in srgb,var(--c) 8%,transparent) 6px 12px)}
[data-appts-ws] .tg-ghost.drag{z-index:3;border-style:solid;background:color-mix(in srgb,var(--brand-text) 22%,transparent);align-items:flex-start;padding-top:4px}
[data-appts-ws] .tg-dayoff{align-self:center;padding:2px 10px;border-radius:999px;font-size:11.5px;font-weight:800;color:#e8b84b;background:rgba(232,184,75,.14);border:1px solid rgba(232,184,75,.4)}
[data-appts-ws] .de-clash{padding:10px 12px;border-radius:12px;border:1px solid rgba(232,184,75,.45);background:rgba(232,184,75,.1);color:var(--ink);font-size:13px}
[data-appts-ws] .de-clash b{display:block;color:#e8b84b;font-size:13px}
[data-appts-ws] .de-clash ul{margin:6px 0 0;padding-left:18px}
[data-appts-ws] .de-clash li span{color:var(--muted)}
[data-appts-ws] .de-clash small{display:block;margin-top:6px;color:var(--muted);font-size:12px}
[data-appts-ws] .tg-now{position:absolute;left:0;right:0;height:2px;background:#e8526a;z-index:2;pointer-events:none}
[data-appts-ws] .tg-now::before{content:"";position:absolute;left:-4px;top:-3px;width:8px;height:8px;border-radius:50%;background:#e8526a}
[data-appts-ws] .tg .rb-chip{position:absolute;overflow:hidden;z-index:1}
[data-appts-ws] .tg .rb-chip.flat{position:static;width:100%}
[data-appts-ws] .tg .rb-chip span{font-size:12.5px;font-weight:700}
[data-appts-ws] .tg .rb-chip b{font-size:11px;font-weight:600}
[data-appts-ws] .mm-head{display:flex;align-items:center;justify-content:space-between;margin-bottom:12px}
[data-appts-ws] .mm-head b{font-size:15px;color:var(--ink)}
[data-appts-ws] .mm-grid{display:grid;grid-template-columns:repeat(7,1fr);gap:3px}
[data-appts-ws] .mm-dow{text-align:center;font-size:11.5px;font-weight:700;color:var(--muted);padding-bottom:4px}
[data-appts-ws] .mm-day{position:relative;height:34px;border:0;border-radius:9px;background:var(--surface-2);color:var(--ink);font:inherit;font-size:13px;font-weight:600;cursor:pointer}
[data-appts-ws] .mm-day.out{color:var(--faint);background:transparent}
[data-appts-ws] .mm-day:hover{background:var(--hover-tint)}
[data-appts-ws] .mm-day.today{color:var(--brand-text);font-weight:800}
[data-appts-ws] .mm-day.sel{background:linear-gradient(90deg,#3EE0A1,#38CDE0);color:#0b1c22}
[data-appts-ws] .mm-day i{position:absolute;bottom:4px;left:50%;width:4px;height:4px;margin-left:-2px;border-radius:50%;background:var(--brand-text)}
[data-appts-ws] .mm-day.sel i{background:#0b1c22}
[data-appts-ws] .wh-card{animation:whIn .22s cubic-bezier(.34,1.56,.64,1)}
@keyframes whIn{from{opacity:0;transform:translateY(10px) scale(.98)}to{opacity:1;transform:none}}
@media (prefers-reduced-motion:reduce){[data-appts-ws] .wh-card{animation:none}}
[data-appts-ws] .wh-head{display:flex;align-items:center;justify-content:space-between;padding:22px 22px 6px}
[data-appts-ws] .wh-head h2{margin:0;font-size:22px;font-weight:700;color:var(--ink)}
[data-appts-ws] .wh-done{border:0;background:none;padding:6px 2px;color:var(--brand-text);font:inherit;font-size:16px;font-weight:700;cursor:pointer}
[data-appts-ws] .wh-done:hover{color:var(--hover-ink);text-decoration:underline;text-underline-offset:3px}
/* Compact (2026-10-09): the same weight as the Create form. */
[data-appts-ws] .wh-head{padding:18px 22px 4px}
[data-appts-ws] .wh-head h2{font-size:17px}
[data-appts-ws] .wh-done{font-size:14px}
[data-appts-ws] .wh-lead{font-size:13px;line-height:1.55;color:var(--muted)}
[data-appts-ws] .wh-lead strong{color:var(--ink)}
[data-appts-ws] .wh{gap:12px!important}
[data-appts-ws] .wh > div[style*="12px 14px"]{padding:9px 12px!important;font-size:12px!important;line-height:1.5}
[data-appts-ws] .wh-set{gap:8px}
[data-appts-ws] .wh-legend{margin-bottom:6px;font-size:11px}
[data-appts-ws] .wh-hint{font-size:12px}
[data-appts-ws] .wh-day{grid-template-columns:48px 1fr;gap:6px 10px}
[data-appts-ws] .wh-name,[data-appts-ws] .wh-closed{font-size:14px;padding:4px 0}
[data-appts-ws] .wh-closed em{font-size:12px}
[data-appts-ws] .wh-slot{grid-template-columns:1fr 1fr 32px;gap:8px}
[data-appts-ws] .wh-slot select{height:40px;padding:0 32px 0 13px;border-radius:12px;font-size:14px;background-position:right 11px center}
[data-appts-ws] .wh-mini{width:32px;height:32px;border-radius:9px;font-size:14px}
[data-appts-ws] .wh-off{padding:10px;gap:8px}
[data-appts-ws] .wh-off input{height:38px;font-size:13px}
[data-appts-ws] .wh-add{height:34px;font-size:12.5px}
[data-appts-ws] .wh-foot{padding:10px 22px 16px}
[data-appts-ws] .wh-save{height:46px;border-radius:13px;font-size:15px}`;

function AppointmentsPage() {
    const { t } = useTheme();
    const themed = useMemo(() => themeOnTokens(t), [t]);
    return (
        <ThemeCtx.Provider value={themed}>
            <div data-appts-ws data-drafting-theme data-mode={draftingMode(t)}>
                <style>{`${DRAFTING_TOKENS_CSS}\n${APPTS_THEME_CSS}`}</style>
                <AppointmentsScreen />
            </div>
        </ThemeCtx.Provider>
    );
}

function AppointmentsScreen() {
    const { t } = useTheme();
    const { addNotif } = useNotif();
    const toast = useToast();
    const [viewMode, setViewMode] = useState("list");
    const [hoursOpen, setHoursOpen] = useState(false);
    const [hoursVersion, setHoursVersion] = useState(0);
    // Closing the drawer re-reads the schedule: it may just have been saved.
    const closeHours = useCallback(() => { setHoursOpen(false); setHoursVersion(v => v + 1); }, []);
    const [hours, setHours] = useState({ state: "loading", configured: false, rows: [] });
    // Hearings from the lawyer's cases, for the calendar. A failed read leaves
    // the calendar without them rather than saying something about them.
    const [hearings, setHearings] = useState([]);
    useEffect(() => {
        let off = false;
        Promise.resolve().then(() => listAllCases(listCases)).then(res => {
            if (off || !res || res.error || !Array.isArray(res.data?.items)) return;
            const out = [];
            for (const c of res.data.items) {
                (c.hearing_dates || []).forEach((h, i) => {
                    const day = typeof h.date === "string" ? h.date.slice(0, 10) : new Date(h.date).toISOString().slice(0, 10);
                    const iso = pktSlotToUtcISO(day, h.time || "10:00");
                    if (!iso) return;
                    out.push({ key: `${c._id}-${h._id || i}`, at: new Date(iso), title: c.title || "Case",
                               purpose: h.purpose || "", court: h.court || "", caseId: c._id, held: Boolean(h.outcome) });
                });
            }
            setHearings(out);
        }).catch(() => {});
        return () => { off = true; };
    }, []);
    const [statusF, setStatusF] = useState("All");
    // PAGING STATE, kept beside the list rather than inside it.
    //
    // Every caller used to ask for `page_size: 50` and stop. Fifty is not
    // "all" — it is the first fifty by the server's sort — so a lawyer with a
    // longer history saw a truncated diary with nothing saying so.
    //
    // `pagesTotal === null` means the server has not told us yet; it is NOT
    // the same as "one page", and the list must not claim to be complete on
    // that basis.
    const [pageNo, setPageNo] = useState(1);
    const [pagesTotal, setPagesTotal] = useState(null);
    const [listTotal, setListTotal] = useState(null);
    const [loadingMore, setLoadingMore] = useState(false);
    const [moreError, setMoreError] = useState(null);
    const [firstPageError, setFirstPageError] = useState(null);
    // Per-status totals, read from the server rather than counted from the
    // rows on screen. `null` means "not known", which is not zero.
    const [statusTotals, setStatusTotals] = useState({});
    const [appointments, setAppointments] = useState([]);
    const [loading, setLoading] = useState(true);
    // Read once at mount rather than called inline during render, so every
    // control on a single paint is decided against ONE instant. Calling
    // `Date.now()` per button would let two buttons on the same row disagree
    // about whether a boundary had passed.
    const [now, setNow] = useState(() => Date.now());
    const [joinModal, setJoinModal] = useState(null);
    const [cancelFor, setCancelFor] = useState(null);   // row awaiting decline/cancel confirmation
    // Month calendar. Its own data: every appointment, whatever the list tab.
    const [calMonth, setCalMonth] = useState(() => pktToday().slice(0, 7));
    const [calDay, setCalDay] = useState(() => pktToday());
    // The appointment opened from the day's agenda (by id, so it follows a
    // reload), and the way to its case.
    const [detailId, setDetailId] = useState(null);
    // Daily / Weekly / Monthly.
    const RANGE_KEY = "attorney:lawyer-appts-range";
    const [calRange, setCalRangeState] = useState(() => {
        try { const v = localStorage.getItem(RANGE_KEY); return ["day", "week", "month"].includes(v) ? v : "month"; } catch { return "month"; }
    });
    const setCalRange = (v) => { setCalRangeState(v); try { localStorage.setItem(RANGE_KEY, v); } catch { /* storage off */ } };
    // A different day closes an open appointment; the month follows the day,
    // so the diary loaded is always the one around it.
    const pickDay = (k) => { setCalDay(k); setDetailId(null); if (k.slice(0, 7) !== calMonth) setCalMonth(k.slice(0, 7)); };
    // From a week or day board: an appointment opens its detail; a meeting or
    // an event selects its day, whose agenda shows it.
    const openItem = (item) => {
        if (item.kind === "court") { openCase(item.hearing.caseId); return; }
        const k = pktDayKey(item.at);
        if (k) { setCalDay(k); if (k.slice(0, 7) !== calMonth) setCalMonth(k.slice(0, 7)); }
        setDetailId(item.kind === "appointment" ? item.appointment.id : null);
    };
    const { setPage: goToPage, setOpenCaseId } = useCase();
    const openCase = (caseId) => { setOpenCaseId?.(caseId); goToPage?.("cases"); };
    const [calItems, setCalItems] = useState([]);
    const [calState, setCalState] = useState("loading");   // loading | ready | error
    const [calPartial, setCalPartial] = useState(false);
    const [calVersion, setCalVersion] = useState(0);
    const [diaryVersion, setDiaryVersion] = useState(0);
    // The lawyer's own meetings and events for the month on screen.
    const [calDiary, setCalDiary] = useState([]);
    const [diaryState, setDiaryState] = useState("loading");   // loading | ready | error
    const [createKind, setCreateKind] = useState(null);        // null | "meeting" | "event"
    const [createDay, setCreateDay] = useState(null);
    const [createTime, setCreateTime] = useState(null);   // a slot clicked on the grid
    const [createDuration, setCreateDuration] = useState(null);   // minutes, from a drag
    const [exporting, setExporting] = useState(false);
    // "No Show" earns a tab because it is now its own status. The tab filter is
    // an exact match on the display status, so without one a no-show would be
    // reachable under "All" and nowhere else — it would simply disappear from
    // every filtered view the moment it was marked.
    // "Expired" earns a tab on the same reasoning as "No Show": the filter is
    // an exact match on the display status, so a status without a tab is
    // reachable under "All" and nowhere else.
    const tabs = ["All", "Upcoming", "Pending", "Completed", "Cancelled", "No Show", "Expired"];

    const calDays = calendarDays(calItems, calDiary, hearings);

    const mapApiAppt = (a) => ({
        id: a.id,
        // The STORED joining link, or null. The modal used to construct a
        // meet.attorney.ai URL from the id and the client's first name — a host
        // this product does not own and a room nobody had created.
        meetingLink: a.meeting_link || null,
        // Carried through so Accept can pin the schedule the lawyer was shown.
        // Dropping it here was the gap: the row rendered correctly and the one
        // field that makes the confirmation safe never reached the handler.
        scheduleVersion: Number.isInteger(a.schedule_version) ? a.schedule_version : null,
        at: a.scheduled_at ? new Date(a.scheduled_at) : null,
        // When the consultation is over. The server will not accept a
        // completion before this instant, so the row has to carry it — the
        // display `duration` beside it is the string "30 min" and cannot be
        // compared to anything.
        //
        // `end_at` is the AUTHORITATIVE value: the server stores it on the
        // appointment and decides completion against that stored field, so
        // recomputing it here could only ever disagree with the authority. The
        // arithmetic below is a FALLBACK for a response that lacks it — a
        // legacy row written before the field, or a malformed payload — and it
        // is a guess, not a second opinion. Where both exist, `end_at` wins.
        endAt: endOf(a),
        client: a.client_name || "Client",
        initials: (a.client_name || "??").split(" ").map(w => w[0]).join("").slice(0, 2).toUpperCase(),
        purpose: a.notes || "Consultation",
        // The client's note as written ("" when none), for the detail panel.
        note: a.notes || "",
        // Rendered in PKT, not the browser's zone. The stored instant used to
        // come back from Mongo without an offset, which JS then read as LOCAL
        // time — so an appointment displayed correctly when it was created and
        // five hours early after a refresh, and the lawyer and the client could
        // read two different clock faces off the same row.
        date: formatPkt(a.scheduled_at, { month: "short", day: "numeric", year: "numeric" }),
        time: formatPkt(a.scheduled_at, { hour: "2-digit", minute: "2-digit" }),
        duration: `${a.duration_minutes} min`,
        type: a.mode === "video" ? "Video Call" : a.mode === "phone" ? "Phone Call" : "In-Person",
        // `no_show` is NOT "Cancelled". It was mapped that way, which told the
        // lawyer their own client had cancelled when in fact the client did not
        // turn up — a different fact, and the only one of the two that is the
        // client's fault. The client's own view (ModTracking) has always shown
        // "No Show" correctly, so the two sides of one appointment disagreed.
        // `expired` is mapped explicitly, and the fallback no longer lies.
        // Defaulting an unrecognised status to "Pending" put lapsed requests
        // in the Pending tab wearing Accept and Decline — controls the server
        // answers with a 409, on a request nobody can act on any more.
        status: ({ confirmed: "Upcoming", pending: "Pending", completed: "Completed", cancelled: "Cancelled", no_show: "No Show", expired: "Expired" })[a.status] || "Unknown",
        caseId: a.case_id,
        // When the client sent the request ("oldest sent 3 days ago").
        createdAt: a.created_at ? new Date(a.created_at) : null,
    });

    // One loader, reused by the effect and by every handler that has to
    // re-read after the server refused something.
    // Display tab -> the status the SERVER understands. "All" sends none.
    const API_STATUS = {
        Upcoming: "confirmed", Pending: "pending", Completed: "completed",
        Cancelled: "cancelled", "No Show": "no_show", Expired: "expired",
    };

    // Only the newest request may write. A tab changed while a request is in
    // flight would otherwise have the older answer land on top of the newer
    // one, showing rows from a filter the lawyer has already left.
    const requestToken = useRef(0);
    // A REF, NOT THE `loadingMore` STATE. Two clicks in the same tick both read
    // the state before React has re-rendered, so both pass the guard and both
    // request the same page — appending it twice. A ref updates synchronously,
    // which is the only thing that can stop re-entry within one tick.
    const moreInFlight = useRef(false);

    const reload = async (tab = statusF) => {
        const mine = ++requestToken.current;
        try {
            const { data, error } = await listAppointments({
                status: API_STATUS[tab], page: 1, page_size: PAGE_SIZE,
            });
            if (mine !== requestToken.current) return;
            // The client resolves on failure rather than throwing, so an error
            // here is a value. Keep whatever is on screen: an empty list would
            // read as "no appointments" when the read simply failed.
            if (error || !data?.items) {
                setFirstPageError(
                    error?.message || "Could not load appointments.");
                return;
            }
            setAppointments(data.items.map(mapApiAppt));
            setPageNo(1);
            setPagesTotal(Number.isInteger(data.pages) ? data.pages : null);
            setListTotal(Number.isInteger(data.total) ? data.total : null);
            setFirstPageError(null);
            setMoreError(null);
        } catch {
            // Same rule.
        } finally {
            if (mine === requestToken.current) setLoading(false);
        }
    };

    /** Append the next page. */
    const loadMore = async () => {
        // The guard, not a nicety: a second click would request the same page
        // again and append it, duplicating every row on it.
        if (moreInFlight.current || pagesTotal === null || pageNo >= pagesTotal) return;
        moreInFlight.current = true;
        setLoadingMore(true);
        setMoreError(null);
        const mine = requestToken.current;
        const next = pageNo + 1;
        const { data, error } = await listAppointments({
            status: API_STATUS[statusF], page: next, page_size: PAGE_SIZE,
        });
        moreInFlight.current = false;
        if (mine !== requestToken.current) { setLoadingMore(false); return; }
        setLoadingMore(false);
        if (error || !data?.items) {
            // KEEP WHAT IS SHOWN. Those rows were read successfully; throwing
            // them away to report a later failure destroys good data.
            setMoreError(error?.message || "Could not load more appointments.");
            return;
        }
        setAppointments(prev => {
            // The backend pages with skip/limit, so a row inserted or removed
            // between requests can shift the window and hand back something
            // already on screen.
            const seen = new Set(prev.map(a => a.id));
            return [...prev, ...data.items.map(mapApiAppt)
                .filter(a => !seen.has(a.id))];
        });
        setPageNo(next);
        setPagesTotal(Number.isInteger(data.pages) ? data.pages : pagesTotal);
        setListTotal(Number.isInteger(data.total) ? data.total : listTotal);
    };

    // THE STAT CARDS COME FROM THE SERVER'S `total`, NOT FROM COUNTING ROWS.
    //
    // Counting the loaded page was wrong twice over once the list pages: it
    // reported the first page's tally as a total, and with the tab applied
    // server-side it would have reported the CURRENT TAB's tally under every
    // card. One bounded request per status reads the real figure without
    // pulling an appointment history into the browser to count it.
    useEffect(() => {
        let cancelled = false;
        Promise.all(["confirmed", "pending", "completed"].map(
            status => listAppointments({ status, page_size: 1 })
        )).then(results => {
            if (cancelled) return;
            const next = {};
            ["confirmed", "pending", "completed"].forEach((status, i) => {
                const { data, error } = results[i];
                next[status] = (!error && Number.isInteger(data?.total))
                    ? data.total : null;
            });
            setStatusTotals(next);
        });
        return () => { cancelled = true; };
        // Re-read after every change (calVersion): read once at mount, the
        // Pending figure stayed at its old value after accepting a request.
    }, [calVersion]);

    // A booking, a cancellation or a client's reschedule arriving while this
    // page is open: re-read the list, the calendar and the totals.
    useEffect(() => onNotification((n) => {
        if (!String(n.type || "").startsWith("appointment_")) return;
        reload();
        setCalVersion(v => v + 1);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }), [statusF]);

    useEffect(() => { setLoading(true); reload(statusF); },
        // eslint-disable-next-line react-hooks/exhaustive-deps
        [statusF]);

    /** Every appointment, every status, every page (bounded). Used by the
     *  calendar and by Export, which must not stop at the list's first page. */
    const fetchAllAppointments = async () => {
        const items = new Map();
        let page = 1;
        let pages = 1;
        while (page <= pages && page <= CAL_MAX_PAGES) {
            const { data, error } = await listAppointments({ page, page_size: CAL_PAGE_SIZE });
            if (error || !data?.items) return { error: error?.message || "Could not load appointments." };
            for (const a of data.items) items.set(a.id, mapApiAppt(a));
            pages = Number.isInteger(data.pages) ? data.pages : page;
            page += 1;
        }
        return { items: [...items.values()], partial: pages > CAL_MAX_PAGES };
    };

    // Every appointment, read on mount (the overview cards need them), again
    // when the calendar is opened, and after any action changes one.
    useEffect(() => {
        let cancelled = false;
        setCalState("loading");
        fetchAllAppointments().then(result => {
            if (cancelled) return;
            // Keep what was on screen: an empty month would read as "no
            // appointments" when the read failed.
            if (result.error) { setCalState("error"); return; }
            setCalItems(result.items);
            setCalPartial(result.partial);
            setCalState("ready");
        });
        return () => { cancelled = true; };
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [viewMode, calVersion]);

    // The diary is read per month: exactly the days the grid shows.
    useEffect(() => {
        if (viewMode !== "calendar") return undefined;
        let cancelled = false;
        const keys = pktMonthGridKeys(calMonth);
        setDiaryState("loading");
        // Not the previous month's entries meanwhile: the grid's edge days
        // overlap, and a failed read would leave them looking current.
        setCalDiary([]);
        listLawyerEvents(pktRange(keys[0], keys[keys.length - 1])).then(({ data, error }) => {
            if (cancelled) return;
            if (error || !Array.isArray(data)) { setDiaryState("error"); return; }
            setCalDiary(data);
            setDiaryState("ready");
        });
        return () => { cancelled = true; };
    }, [viewMode, calMonth, calVersion, diaryVersion]);

    useEffect(() => {
        let cancelled = false;
        getMyWorkingHours().then(({ data, error }) => {
            if (cancelled) return;
            if (error || !data) { setHours({ state: "error", configured: false, rows: [] }); return; }
            setHours({ state: "ready", configured: !!data.configured, rows: data.working_hours || [],
                       daysOff: (data.exceptions || []).map(d => String(d.date || "").slice(0, 10)).filter(Boolean) });
        });
        return () => { cancelled = true; };
    }, [hoursVersion]);

    const goToDate = (value) => {
        // While a year is being typed the browser reports 0002-, 0020-, 0202-
        // ... as complete dates. Act on a real year only, or every keystroke
        // jumps the view and asks the server for a month in year 2.
        if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return;
        const year = Number(value.slice(0, 4));
        if (year < 2000 || year > 2099) return;
        setCalDay(value);
        setCalMonth(value.slice(0, 7));
        setViewMode("calendar");
    };

    const openCreate = (kind, day = calDay, time = null, minutes = null) => {
        setCreateDay(day); setCreateTime(time); setCreateDuration(minutes); setCreateKind(kind);
    };
    /** Entries on `day` overlapping [time, time + minutes): appointments not
     *  cancelled, court hearings, meetings and events. `skipKey` leaves out
     *  the entry being asked about. */
    const clashesAt = (day, time, minutes, skipKey = null) => {
        const iso = day && time ? pktSlotToUtcISO(day, time) : null;
        if (!iso) return [];
        const s0 = +new Date(iso), e0 = s0 + minutes * 60000;
        return (calDays.get(day) || []).filter(i => {
            if (i.key === skipKey) return false;
            const st = +i.at, en = st + itemSpan(i).dur * 60000;
            return st < e0 && en > s0;
        });
    };
    const clashesFor = (apt) => {
        if (!apt.at) return [];
        const minutes = apt.endAt ? Math.max(1, Math.round((+apt.endAt - +apt.at) / 60000)) : 30;
        return clashesAt(pktDayKey(apt.at), pktHourMinute(apt.at), minutes, `a:${apt.id}`);
    };
    const closeCreate = useCallback(() => setCreateKind(null), []);
    const onCreated = (entry) => {
        setCreateKind(null);
        const day = pktDayKey(entry.starts_at);
        toast.show(`${entry.kind === "meeting" ? "Meeting" : "Event"} added to your diary.`, "success", 3000);
        goToDate(day);
        setDiaryVersion(v => v + 1);      // the diary only: appointments did not change
    };
    const onDeleteEntry = async (entry) => {
        const { error } = await deleteLawyerEvent(entry.id);
        if (error) {
            toast.show(error.message || "Could not delete it. Try again.", "danger", 4000);
            return false;
        }
        setCalDiary(prev => prev.filter(e => e.id !== entry.id));
        toast.show("Deleted from your diary.", "success", 3000);
        return true;
    };

    const exportMonth = async () => {
        if (exporting) return;
        setExporting(true);
        try {
            const [all, diary] = await Promise.all([
                fetchAllAppointments(),
                listLawyerEvents({ start: `${calMonth}-01T00:00:00+05:00`,
                                   end: `${shiftMonth(calMonth, 1)}-01T00:00:00+05:00` }),
            ]);
            if (all.error || diary.error || !Array.isArray(diary.data)) {
                toast.show("Could not export: loading failed. Try again.", "danger", 4000);
                return;
            }
            const blob = new Blob([monthCsv(calMonth, all.items, diary.data)], { type: "text/csv;charset=utf-8" });
            const url = URL.createObjectURL(blob);
            const link = document.createElement("a");
            link.href = url;
            link.download = `attorney-ai-diary-${calMonth}.csv`;
            document.body.appendChild(link);
            link.click();
            link.remove();
            setTimeout(() => URL.revokeObjectURL(url), 1000);
            toast.show(`Exported ${monthTitle(calMonth)}${all.partial ? " (first 1000 appointments only)" : ""}.`, "success", 3000);
        } finally {
            setExporting(false);
        }
    };

    // The clock, as state.
    //
    // Three controls below turn on or off at an instant — an appointment
    // starting, ending, or slipping into the past. React has no reason to
    // re-render when that instant arrives, so the buttons were correct only
    // until the moment they mattered, and a lawyer watching the page would see
    // No Show still greyed out after the client failed to appear.
    //
    // The cleanup is not a formality: this interval holds a closure over
    // component state, so leaving it running after unmount means setting state
    // on a dead component on every tick, for as long as the tab is open.
    useEffect(() => {
        const id = setInterval(() => setNow(Date.now()), CLOCK_TICK_MS);
        return () => clearInterval(id);
    }, []);

    // Each of these mirrors a rule the server enforces, evaluated against the
    // single `now` above. They answer "may this be done yet", never "is this
    // the right kind of appointment" — the status gate is the surrounding JSX,
    // and keeping the two separate is what stopped Done and No Show from
    // inheriting each other's conditions.
    //
    // A row with no usable time is treated as NOT actionable. The alternative
    // is offering a control whose precondition cannot be evaluated, which is
    // how these buttons behaved before they were gated at all.
    const startedAt = (apt) => (apt.at ? apt.at.getTime() : null);
    const endedAt = (apt) => (apt.endAt ? apt.endAt.getTime() : null);

    const canAccept = (apt) => startedAt(apt) !== null && now < startedAt(apt);
    const canNoShow = (apt) => startedAt(apt) !== null && now >= startedAt(apt);
    const canComplete = (apt) => endedAt(apt) !== null && now >= endedAt(apt);

    const whyNotAccept = (apt) => (canAccept(apt) ? undefined
        : startedAt(apt) === null ? "This appointment has no scheduled time"
        : "This time has already passed — cancel the request instead");
    const whyNotNoShow = (apt) => (canNoShow(apt) ? undefined
        : startedAt(apt) === null ? "This appointment has no scheduled time"
        : "Available once the appointment has started");
    const whyNotComplete = (apt) => (canComplete(apt) ? undefined
        : endedAt(apt) === null ? "This appointment has no end time"
        : "Available once the consultation has ended");

    /** Record a status change on screen. On a filtered tab the row no longer
     *  belongs there, so it leaves (it used to stay, e.g. a cancelled request
     *  still listed under Pending). */
    const applyStatus = (id, status) => {
        if (statusF !== "All" && statusF !== status) {
            setAppointments(prev => prev.filter(a => a.id !== id));
            setListTotal(n => (Number.isInteger(n) && n > 0 ? n - 1 : n));
        } else {
            setAppointments(prev => prev.map(a => a.id === id ? { ...a, status } : a));
        }
    };

    const handleAccept = async (id) => {
        const apt = appointments.find(a => a.id === id);

        // THE VERSION DISPLAYED WHEN ACCEPT WAS CLICKED, not one read fresh.
        //
        // Confirming is agreeing to a TIME. The client may move a pending
        // request while this page sits open, and the status stays PENDING
        // throughout — so re-reading the version here would defeat the pin: it
        // would agree to whatever the appointment says now, which is exactly
        // the time the lawyer has not seen.
        if (!Number.isInteger(apt?.scheduleVersion)) {
            // Nothing safe to send. Reload rather than guess a version.
            toast.show("Reload this page before accepting — its details are out of date.",
                       "warn", 4000);
            await reload();
            return;
        }

        const { error, status } = await apiConfirm(id, {
            schedule_version: apt.scheduleVersion,
        });

        if (error) {
            const errMsg = error.message || "Could not confirm appointment";
            toast.show(errMsg, "danger", 4000);
            addNotif({ type: "appointment", title: "Failed to Confirm", body: errMsg, time: "Just now" });
            // A 409 means the request moved underneath us — most often the
            // client changed the time. The row must be re-read so the lawyer
            // sees what they would actually be accepting, and NOT marked
            // Upcoming: reporting success for a confirmation that did not
            // happen is how a lawyer ends up holding a slot nobody agreed to.
            if (status === 409) await reload();
            return;
        }

        // Re-read rather than patching local state: the server owns the
        // outcome, and the confirmed row carries the version any later action
        // has to pin against.
        await reload();
        setCalVersion(v => v + 1);
        const msg = `✅ Appointment confirmed with ${apt?.client}`;
        toast.show(msg, "success", 3000);
        addNotif({ type: "appointment", title: "Appointment Accepted", body: msg, time: "Just now" });
    };

    const handleSaveMeetingLink = async (id, link) => {
        const result = await apiSetMeetingLink(id, link);
        if (!result.error) {
            await reload();
            // Keep the modal open on the refreshed row so the lawyer sees the
            // stored link rather than the one they typed.
            setJoinModal(prev => (prev && prev.id === id
                ? { ...prev, meetingLink: link } : prev));
            toast.show("Joining link saved — your client can see it now.", "success", 3000);
        }
        return result;
    };

    /** Decline a pending request or cancel a confirmed appointment, after the
     *  dialog. Returns an error message to show in it, or null on success. The
     *  wording follows what actually happened: cancelling a confirmed
     *  appointment used to be reported as "rejected". */
    const handleReject = async (id, reason) => {
        const apt = appointments.find(a => a.id === id) || calItems.find(a => a.id === id);
        const declined = apt?.status === "Pending";
        const { error } = await apiCancel(id, reason);
        if (error) {
            const errMsg = error.message || (declined ? "Could not decline the request" : "Could not cancel the appointment");
            toast.show(errMsg, "danger", 4000);
            return errMsg;
        }
        setCancelFor(null);
        applyStatus(id, "Cancelled");
        setCalVersion(v => v + 1);
        const msg = declined ? `Request from ${apt?.client} declined` : `Appointment with ${apt?.client} cancelled`;
        toast.show(msg, "warn", 3000);
        addNotif({ type: "appointment", title: declined ? "Request Declined" : "Appointment Cancelled", body: msg, time: "Just now" });
        return null;
    };
    const handleComplete = async (id) => {
        const apt = appointments.find(a => a.id === id);
        const { error } = await apiComplete(id);
        if (error) {
            const errMsg = error.message || "Could not mark as complete";
            toast.show(errMsg, "danger", 4000);
            addNotif({ type: "appointment", title: "Failed", body: errMsg, time: "Just now" });
            return;
        }
        applyStatus(id, "Completed");
        setCalVersion(v => v + 1);
        const msg = `✓ Session completed with ${apt?.client}`;
        toast.show(msg, "success", 3000);
        addNotif({ type: "appointment", title: "Appointment Completed", body: msg, time: "Just now" });
    };
    const handleNoShow = async (id) => {
        // Uses the existing PATCH /appointments/{id}/no-show. The endpoint, the
        // API client function and the NO_SHOW status all already existed; the
        // lawyer — the only person who can record a no-show — simply had no way
        // to reach them.
        const apt = appointments.find(a => a.id === id);
        const { error } = await apiNoShow(id);
        if (error) {
            // The server allows this only on a CONFIRMED appointment, so a
            // stale card (one already completed or cancelled in another tab)
            // lands here. Say what the server said and leave the row alone.
            const errMsg = error.message || "Could not mark as no-show";
            toast.show(errMsg, "danger", 4000);
            addNotif({ type: "appointment", title: "Failed", body: errMsg, time: "Just now" });
            return;
        }
        applyStatus(id, "No Show");
        setCalVersion(v => v + 1);
        const msg = `${apt?.client || "The client"} did not attend`;
        toast.show(msg, "warn", 3000);
        addNotif({ type: "appointment", title: "Marked as No Show", body: msg, time: "Just now" });
    };

    /** Accept several pending requests, each pinned to the version shown,
     *  one at a time. Each is the same guarded confirm as the single Accept,
     *  so a request the client moved (409) or one that clashes is refused by
     *  the server and reported, not forced through. */
    const acceptAll = async (targets) => {
        let ok = 0;
        let failed = 0;
        for (const a of targets) {
            if (!Number.isInteger(a.scheduleVersion)) { failed += 1; continue; }
            const { error } = await apiConfirm(a.id, { schedule_version: a.scheduleVersion });
            if (error) failed += 1; else ok += 1;
        }
        await reload();
        setCalVersion(v => v + 1);
        toast.show(failed
            ? `Accepted ${ok}; ${failed} could not be accepted — check them in the list.`
            : `Accepted ${ok} request${ok === 1 ? "" : "s"}.`, failed ? "warn" : "success", 4000);
        if (ok) addNotif({ type: "appointment", title: "Appointments Accepted", body: `${ok} request${ok === 1 ? "" : "s"} confirmed`, time: "Just now" });
    };
    const reviewRequests = () => { setViewMode("list"); setStatusF("Pending"); };
    // Tab counts from every appointment. Not shown while loading, or when the
    // read stopped at its bound: a count of the first 1000 is not the total.
    const tabCounts = calState === "ready" && !calPartial ? Object.fromEntries(tabs.map(tab => [
        tab, tab === "All" ? calItems.length : calItems.filter(a => a.status === tab).length,
    ])) : null;
    // Whether the list holds every row of its tab (for its footer).
    const listComplete = pagesTotal !== null && pageNo >= pagesTotal;

    // The overview reads every appointment (calItems), not the list's page.
    const pendingItems = calItems.filter(a => a.status === "Pending").sort((x, y) => (x.at || 0) - (y.at || 0));
    const todayItems = calItems.filter(a => a.at && _isToday(a.at) && !DID_NOT_HAPPEN.has(a.status));
    const todayWeekday = (new Date(`${pktToday()}T12:00:00Z`).getUTCDay() + 6) % 7;
    const todayWorkMinutes = hours.configured ? hours.rows
        .filter(r => Number(r.weekday) === todayWeekday)
        .reduce((m, r) => m + (HALF_HOURS.indexOf(r.end) - HALF_HOURS.indexOf(r.start)) * 30, 0) : 0;

    return (
        <div style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}>
            <div style={{ flex: 1, overflowY: "auto" }}>
                <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>

                    {/* ── Modals ──────────────────────────────────── */}
                    {cancelFor && (
                        <CancelAppointmentDialog t={t} apt={cancelFor}
                            onClose={() => setCancelFor(null)}
                            onConfirm={(reason) => handleReject(cancelFor.id, reason)} />
                    )}
                    {joinModal && (
                        <JoinCallModal apt={joinModal} onClose={() => setJoinModal(null)}
                            onSaveLink={handleSaveMeetingLink} t={t} />
                    )}

                    {/* ── Header ──────────────────────────────────── */}
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 16 }}>
                        <div>
                            <nav className="ap-crumbs" aria-label="Breadcrumb">Practice / <b>Appointments</b></nav>
                            <h1 className="ap-title">Appointments</h1>
                        </div>
                        {/* Export and Create sit top right, above the week card (2026-10-09). */}
                        <div style={{ display: "flex", alignItems: "center", gap: 10, flexShrink: 0 }}>
                            <PillButton t={t} variant="solid" onClick={exportMonth} disabled={exporting}
                                title={`Download ${monthTitle(calMonth)} as a CSV file that opens in Excel`}
                                style={{ cursor: exporting ? "wait" : "pointer", height: 38, padding: "0 16px", fontSize: 13.5 }}>
                                <Icon d={I.download} size={15} /> {exporting ? "Exporting…" : "Export Excel"}
                            </PillButton>
                            <CreateMenu t={t} onPick={kind => openCreate(kind)} />
                        </div>
                    </div>

                    {hoursOpen && <AvailabilityDrawer t={t} onClose={closeHours} />}
                    {createKind && (
                        <DiaryEntryModal t={t} initialKind={createKind} initialDay={createDay} initialTime={createTime}
                            initialDuration={createDuration} findClashes={(d, hm, m) => clashesAt(d, hm, m)}
                            onClose={closeCreate} onCreated={onCreated} />
                    )}

                    {/* ── Overview, in both views ── */}
                    <div data-overview style={{
                        display: "grid", gap: 12,
                        gridTemplateColumns: "minmax(0, 1.45fr) minmax(0, 1fr) minmax(0, 1.2fr)",
                        gridTemplateAreas: '"pending today week" "pending completed hours"',
                        marginBottom: 10,      // breathing room above the toolbar
                    }}>
                        <PendingCard t={t} total={statusTotals.pending} items={pendingItems} now={now}
                            canAccept={canAccept} onReview={reviewRequests} onAcceptAll={acceptAll} />
                        <TodayCard t={t} items={todayItems} workMinutes={todayWorkMinutes} now={now}
                            pendingCount={pendingItems.length} />
                        <WeekCard t={t} items={calItems} />
                        <CompletedCard t={t} items={calItems} />
                        <HoursCard t={t} hours={hours} onOpen={() => setHoursOpen(true)} />
                    </div>

                    {/* ── Toolbar: go-to-date left; the view and the actions right. ── */}
                    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 16, flexWrap: "wrap" }}>
                        <div style={{ display: "flex", alignItems: "center", flex: "1 1 auto", minWidth: 0 }}>
                            <label style={{ ...pillStyle(t), cursor: "text", padding: "0 14px 0 20px", background: t.surface }}>
                                <input type="date" aria-label="Go to date" value={calDay}
                                    onChange={e => goToDate(e.target.value)}
                                    style={{ border: "none", background: "transparent", color: t.text, fontSize: 14, fontWeight: 600,
                                             fontFamily: "inherit", outline: "none", colorScheme: t.mode, cursor: "pointer" }} />
                            </label>
                        </div>

                        {/* View. Status is filtered by the tabs above the list. */}
                        <div role="group" aria-label="View" style={{
                            display: "flex", gap: 4, padding: 4, borderRadius: 999, flexShrink: 0,
                            background: t.surface, border: `1px solid ${t.border}`,
                            boxShadow: "inset 0 1px 3px rgba(0,0,0,0.25)",
                        }}>
                            {[["calendar", "Calendar", I.calendar], ["list", "List", I.list]].map(([v, label, icon]) => {
                                const on = viewMode === v;
                                return (
                                    <button key={v} type="button" aria-pressed={on} onClick={() => setViewMode(v)} style={{
                                        ...pillStyle(t, on ? "solid" : "outline"), height: 36, padding: "0 18px",
                                        ...(on ? {} : { border: "1px solid transparent", color: t.textMuted }),
                                    }}>
                                        <Icon d={icon} size={15} /> {label}
                                    </button>
                                );
                            })}
                        </div>

                        <div style={{ display: "flex", justifyContent: "flex-end", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
                            <RangeMenu value={calRange} onChange={v => { setCalRange(v); setViewMode("calendar"); }} />
                        </div>
                    </div>

                    {viewMode === "list" ? (
                        <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr)", gap: 18 }}>
                            <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>

                                {/* ── Needs outcome (hidden when empty) ── */}
                                <NeedsOutcome t={t} onRecorded={() => { reload(); setCalVersion(v => v + 1); }} />

                                {/* ── Filter tabs ─────────────────────── */}
                                <div role="tablist" aria-label="Filter by status" style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
                                    {tabs.map(tab => {
                                        const on = statusF === tab;
                                        const tone = TAB_TONES[tab] || TAB_TONES.All;
                                        const n = tabCounts ? tabCounts[tab] : null;
                                        // Pending asks for attention while anything waits,
                                        // even when another tab is selected.
                                        const nudge = !on && tab === "Pending" && n > 0;
                                        const showCount = Number.isInteger(n) && (ALWAYS_COUNTED.has(tab) || n > 0);
                                        return (
                                            <button key={tab} type="button" role="tab" aria-selected={on} onClick={() => setStatusF(tab)} style={{
                                                display: "inline-flex", alignItems: "center", gap: 5,
                                                height: 36, padding: "0 16px", borderRadius: 999, cursor: "pointer",
                                                fontSize: 13, fontWeight: 700, fontFamily: "inherit", whiteSpace: "nowrap",
                                                transition: "background .15s, border-color .15s, color .15s",
                                                ...(on
                                                    ? { background: tone.solid, border: `1px solid ${tone.solid}`, color: tone.onSolid, boxShadow: `0 4px 14px ${tone.glow}` }
                                                    : nudge
                                                        ? { background: tone.soft, border: `1px solid ${tone.edge}`, color: tone.text }
                                                        : { background: "rgba(10,30,34,0.55)", border: "1px solid rgba(56,216,196,0.16)", color: "#a9d8d2" }),
                                            }}
                                                onMouseEnter={e => { if (!on) e.currentTarget.style.borderColor = tone.edge; }}
                                                onMouseLeave={e => { if (!on) e.currentTarget.style.borderColor = nudge ? tone.edge : "rgba(56,216,196,0.16)"; }}>
                                                {tab}
                                                {showCount && <span style={{ fontWeight: 600, opacity: on ? 0.9 : 0.75 }}>({n})</span>}
                                            </button>
                                        );
                                    })}
                                </div>

                                {/* ── Appointment cards ───────────────── */}
                                <div className="rgrid-2" style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                                    {appointments.map(apt => (
                                        <Card key={apt.id} style={{ padding: 16 }}>
                                            {/* Card header */}
                                            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 10 }}>
                                                <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
                                                    <div style={{
                                                        width: 40, height: 40, borderRadius: 11,
                                                        background: t.primaryGlow2,
                                                        display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0,
                                                    }}>
                                                        <Icon d={I.user} size={16} style={{ color: t.primary }} />
                                                    </div>
                                                    <div>
                                                        <div style={{ fontSize: 14, fontWeight: 700, color: t.text }}>{apt.client}</div>
                                                        <div style={{ fontSize: 12, color: t.textMuted, marginTop: 1 }}>{apt.purpose}</div>
                                                    </div>
                                                </div>
                                                {/* Visible status badge */}
                                                <StatusBadge status={apt.status} />
                                            </div>

                                            {/* Meta row */}
                                            <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginBottom: 12 }}>
                                                <span style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 11, color: t.textFaint }}>
                                                    <Icon d={I.calendar} size={11} />{apt.date}
                                                </span>
                                                <span style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 11, color: t.textFaint }}>
                                                    <Icon d={I.clock} size={11} />{apt.time} · {apt.duration}
                                                </span>
                                                <span style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 11, color: t.textFaint }}>
                                                    {apt.type === "Video Call" ? <Icon d={I.video} size={11} /> : <Icon d={I.map} size={11} />}
                                                    {apt.type}
                                                </span>
                                            </div>

                                            {/* Action buttons */}
                                            <div style={{ display: "flex", gap: 8 }}>
                                                {apt.status === "Pending" && (<>
                                                    {/* The server refuses to confirm a slot that has
                                                        already passed — it would only produce a confirmed
                                                        row for a meeting that cannot happen. Reject stays
                                                        enabled, because clearing the stale request is the
                                                        action that remains. */}
                                                    <Btn variant="success" size="sm" style={{ flex: 1 }}
                                                        disabled={!canAccept(apt)}
                                                        title={whyNotAccept(apt)}
                                                        onClick={() => handleAccept(apt.id)}>
                                                        <Icon d={I.check} size={12} /> Accept
                                                    </Btn>
                                                    <Btn variant="danger" size="sm" style={{ flex: 1 }} onClick={() => setCancelFor(apt)}>
                                                        <Icon d={I.x} size={12} /> Reject
                                                    </Btn>
                                                </>)}

                                                {apt.status === "Upcoming" && (<>
                                                    {/* Not once it has ended: there is no call left to join. */}
                                                    {apt.type === "Video Call" && !(apt.endAt && +apt.endAt <= now) ? (
                                                        <button
                                                            onClick={() => setJoinModal(apt)}
                                                            style={{
                                                                flex: 1, display: "inline-flex", alignItems: "center", justifyContent: "center", gap: 6,
                                                                padding: "7px 0", borderRadius: 9, border: "none",
                                                                background: `linear-gradient(135deg,${t.primary},#22a898)`,
                                                                color: t.mode === "dark" ? "#0b1c22" : "#fff",
                                                                fontSize: 12, fontWeight: 700, fontFamily: "inherit", cursor: "pointer",
                                                                boxShadow: `0 3px 10px ${t.primary}45`,
                                                            }}>
                                                            {/* The label follows the DATA. A video
                                                                appointment with no stored link has
                                                                nothing to join, and saying "Join Call"
                                                                would promise a room that does not
                                                                exist. */}
                                                            {apt.meetingLink ? "📹 Join Call" : "📹 Add joining link"}
                                                        </button>
                                                    ) : null /* "View Details" had no handler and there
                                                        is no detail view; the card already shows the
                                                        appointment's details. */}
                                                    {/* Both of these are offered on Upcoming only, because
                                                        that is the display status for `confirmed` and the
                                                        server accepts neither outcome on anything else.

                                                        They are now ALSO gated on the clock, which reverses
                                                        an earlier decision here. That note said the server
                                                        had no "is it past?" rule and that inventing one
                                                        client-side would refuse actions the API allowed.
                                                        The server has those rules now — an outcome cannot
                                                        be declared for a meeting that has not happened — so
                                                        the choice is no longer between gating and not
                                                        gating. It is between a disabled button and a button
                                                        that always fails. */}
                                                    <Btn variant="success" size="sm"
                                                        disabled={!canComplete(apt)}
                                                        title={whyNotComplete(apt)}
                                                        onClick={() => handleComplete(apt.id)}>
                                                        <Icon d={I.check} size={12} /> Done
                                                    </Btn>
                                                    <Btn variant="secondary" size="sm"
                                                        disabled={!canNoShow(apt)}
                                                        title={whyNotNoShow(apt)}
                                                        onClick={() => handleNoShow(apt.id)}>
                                                        No Show
                                                    </Btn>
                                                    <Btn variant="danger" size="sm" aria-label="Cancel appointment" title="Cancel appointment" onClick={() => setCancelFor(apt)}>
                                                        <Icon d={I.x} size={12} />
                                                    </Btn>
                                                </>)}

                                            </div>
                                        </Card>
                                    ))}

                                    {loading && (
                                        <div style={{ gridColumn: "1 / -1", textAlign: "center", padding: 40, color: t.textMuted, fontSize: 14 }}>
                                            Loading appointments…
                                        </div>
                                    )}
                                    {!loading && appointments.length === 0 && !firstPageError && (
                                        <div style={{ gridColumn: "1 / -1", textAlign: "center", padding: 40, color: t.textMuted, fontSize: 14 }}>
                                            No appointments found for "{statusF}" filter.
                                        </div>
                                    )}

                                    {/* FIRST-PAGE FAILURE. Distinct from an
                                        empty list: one says there is nothing
                                        to show, the other that we could not
                                        find out. */}
                                    {!loading && firstPageError && (
                                        <div role="alert" style={{ gridColumn: "1 / -1", textAlign: "center", padding: 30, color: "#e8526a", fontSize: 13 }}>
                                            {firstPageError} This is not the same as having
                                            none — we could not read the list.
                                            <div>
                                                <button type="button" onClick={() => reload(statusF)} style={{
                                                    marginTop: 10, minHeight: 36, padding: "8px 14px", borderRadius: 8,
                                                    border: `1px solid ${t.border}`, background: "transparent",
                                                    color: t.text, fontSize: 12, fontWeight: 700,
                                                    cursor: "pointer", fontFamily: "inherit",
                                                }}>Retry appointments</button>
                                            </div>
                                        </div>
                                    )}

                                    {/* LATER-PAGE FAILURE. The rows above were
                                        read successfully and stay. */}
                                    {moreError && (
                                        <div role="alert" style={{ gridColumn: "1 / -1", padding: "10px 12px", color: "#e8526a", fontSize: 12 }}>
                                            {moreError} The appointments already shown are
                                            unaffected.
                                        </div>
                                    )}

                                    {/* END OF LIST, only when the SERVER says
                                        so. A short page is not the signal:
                                        rows can be removed between requests,
                                        and "that is everything" would then be
                                        a claim the server never made. */}
                                    {!loading && !firstPageError && appointments.length > 0 && (
                                        <div style={{ gridColumn: "1 / -1", textAlign: "center", paddingTop: 6 }}>
                                            {!listComplete && (
                                                <button type="button" onClick={loadMore} disabled={loadingMore}
                                                    aria-busy={loadingMore || undefined}
                                                    style={{
                                                        minHeight: 40, padding: "9px 18px", borderRadius: 9,
                                                        border: `1px solid ${t.border}`, background: "transparent",
                                                        color: t.text, fontSize: 12, fontWeight: 700,
                                                        cursor: loadingMore ? "wait" : "pointer",
                                                        opacity: loadingMore ? 0.6 : 1, fontFamily: "inherit",
                                                    }}>
                                                    {loadingMore ? "Loading…" : "Load more appointments"}
                                                </button>
                                            )}
                                            <div style={{ fontSize: 11, color: t.textFaint, marginTop: 8 }}>
                                                {Number.isInteger(listTotal)
                                                    ? `Showing ${appointments.length} of ${listTotal}`
                                                    : `Showing ${appointments.length}`}
                                                {listComplete ? " — that is all of them." : ""}
                                            </div>
                                        </div>
                                    )}
                                </div>
                            </div>

                        </div>
                    ) : (
                        /* ── Calendar view ──────────────────────────── */
                        <div className="rgrid" style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) 300px", gap: 18, alignItems: "start" }}>
                            {(() => {
                                const notices = <>
                                    {calState === "error" && (
                                        <div role="alert" style={{ display: "flex", alignItems: "center", gap: 10, padding: "10px 16px", fontSize: 12.5, color: "#e8526a", borderBottom: `1px solid ${t.border}` }}>
                                            Could not load appointments for the calendar.
                                            <button type="button" onClick={() => setCalVersion(v => v + 1)} style={{ minHeight: 28, padding: "0 12px", borderRadius: 8, border: `1px solid ${t.border}`, background: t.card, color: t.text, fontSize: 12, fontWeight: 700, cursor: "pointer", fontFamily: "inherit" }}>Retry</button>
                                        </div>
                                    )}
                                    {diaryState === "error" && (
                                        <div role="alert" style={{ padding: "10px 16px", fontSize: 12.5, color: "#e8526a", borderBottom: `1px solid ${t.border}` }}>
                                            Could not load your meetings and events.
                                        </div>
                                    )}
                                    {(calState === "loading" || diaryState === "loading") && (
                                        <div style={{ padding: "8px 16px", fontSize: 12, color: t.textMuted, borderBottom: `1px solid ${t.border}` }}>Loading…</div>
                                    )}
                                    {calPartial && (
                                        <div style={{ padding: "8px 16px", fontSize: 12, color: t.textMuted, borderBottom: `1px solid ${t.border}` }}>
                                            Only your first {CAL_MAX_PAGES * CAL_PAGE_SIZE} appointments are shown; later ones may be missing.
                                        </div>
                                    )}
</>;
                                if (calRange === "week") return <WeekBoard dayKey={calDay} onDay={pickDay} days={calDays} onOpenItem={openItem} onSlot={(k, hm, m) => openCreate("meeting", k, hm, m)} work={hours} notices={notices} />;
                                if (calRange === "day") return <DayBoard dayKey={calDay} onDay={pickDay} days={calDays} onOpenItem={openItem} onSlot={(k, hm, m) => openCreate("meeting", k, hm, m)} work={hours} notices={notices} />;
                                return (
                                    <MonthCalendar t={t} month={calMonth} onMonth={setCalMonth}
                                        selected={calDay} onSelect={k => { setCalDay(k); setDetailId(null); }} days={calDays}
                                        notices={notices} />
                                );
                            })()}
                            {(() => {
                                const open = detailId && calItems.find(a => a.id === detailId);
                                if (!open && calRange === "day") return <MiniMonth dayKey={calDay} onDay={pickDay} days={calDays} />;
                                return open ? (
                                    <AppointmentDetail apt={open} now={now} onClose={() => setDetailId(null)} onOpenCase={openCase} clashes={clashesFor(open)}
                                        gates={{ canAccept, whyNotAccept, canComplete, whyNotComplete, canNoShow, whyNotNoShow }}
                                        actions={{
                                            accept: a => handleAccept(a.id), cancel: a => setCancelFor(a),
                                            complete: a => handleComplete(a.id), noShow: a => handleNoShow(a.id), join: a => setJoinModal(a),
                                        }} />
                                ) : (
                                    <DayAgenda t={t} dayKey={calDay} list={calDays.get(calDay) || []}
                                        onJoin={setJoinModal} onDeleteEntry={onDeleteEntry} onCreate={openCreate}
                                        onOpen={a => setDetailId(a.id)} onOpenCase={openCase} />
                                );
                            })()}
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
}

export { AppointmentsPage };
