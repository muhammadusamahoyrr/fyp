'use client';
import { useState, useEffect } from "react";
import {
    formatPkt, isPktToday, pktHourMinute, pktDayKey, pktHour,
    pktWeekDayKeys, pktToday, dayOfMonth,
} from "@/lib/bookingTime.js";
import { useTheme } from "./theme.js";
import { useNotif } from "./theme.js";
import { useToast } from "@/components/shared/Toast.jsx";
import { Card, Btn } from "./components.jsx";
import { Icon, I } from "./icons.jsx";
import {
    listAppointments,
    confirmAppointment as apiConfirm,
    cancelAppointment as apiCancel,
    completeAppointment as apiComplete,
    markNoShow as apiNoShow,
    setMeetingLink as apiSetMeetingLink,
} from "@/lib/api.js";

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
const CAL_HOURS = ["9:00", "10:00", "11:00", "12:00", "13:00", "14:00", "15:00", "16:00", "17:00", "18:00"];

// Current week (Mon-Sun) as PAKISTAN day keys. A calendar column is a calendar
// day, not an instant — building these from the browser's `new Date()` put the
// column headers on one clock and the appointments inside them on another.
const _weekDayKeys = pktWeekDayKeys();
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
};

// Statuses that mean the appointment did not take place. Grouped because the
// "today" and calendar views must exclude both: a no-show is no more a session
// on the day's schedule than a cancellation is. They were already excluded when
// `no_show` was mislabelled "Cancelled"; naming the set keeps that true now that
// the two are distinct.
const DID_NOT_HAPPEN = new Set(["Cancelled", "No Show"]);


function StatusBadge({ status }) {
    const s = STATUS_STYLES[status] || STATUS_STYLES.Upcoming;
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
function StatCard({ label, value, color, bg, border }) {
    return (
        <div style={{
            padding: "16px 20px", borderRadius: 14,
            background: bg, border: `1.5px solid ${border}`,
            display: "flex", justifyContent: "space-between", alignItems: "center",
            transition: "transform .15s", cursor: "pointer",
        }}
            onMouseEnter={e => e.currentTarget.style.transform = "translateY(-2px)"}
            onMouseLeave={e => e.currentTarget.style.transform = "translateY(0)"}
        >
            <span style={{ fontSize: 13, color: "rgba(190,215,225,0.8)", fontWeight: 500 }}>{label}</span>
            <span style={{ fontSize: 26, fontWeight: 700, color }}>{value}</span>
        </div>
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

    const row = { display: "flex", justifyContent: "space-between", padding: "5px 0", borderBottom: `1px solid ${t.border}20` };

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
function AppointmentsPage() {
    const { t } = useTheme();
    const { addNotif } = useNotif();
    const toast = useToast();
    const [viewMode, setViewMode] = useState("list");
    const [statusF, setStatusF] = useState("All");
    const [search, setSearch] = useState("");
    const [appointments, setAppointments] = useState([]);
    const [loading, setLoading] = useState(true);
    // Read once at mount rather than called inline during render, so every
    // control on a single paint is decided against ONE instant. Calling
    // `Date.now()` per button would let two buttons on the same row disagree
    // about whether a boundary had passed.
    const [now, setNow] = useState(() => Date.now());
    const [joinModal, setJoinModal] = useState(null);
    // "No Show" earns a tab because it is now its own status. The tab filter is
    // an exact match on the display status, so without one a no-show would be
    // reachable under "All" and nowhere else — it would simply disappear from
    // every filtered view the moment it was marked.
    const tabs = ["All", "Upcoming", "Pending", "Completed", "Cancelled", "No Show"];

    const filtered = appointments.filter(a =>
        (statusF === "All" || a.status === statusF) &&
        (a.client.toLowerCase().includes(search.toLowerCase()) ||
            a.purpose.toLowerCase().includes(search.toLowerCase()))
    );

    const nextApt = appointments
        .filter(a => a.at && a.at > new Date() && (a.status === "Upcoming" || a.status === "Pending"))
        .sort((x, y) => x.at - y.at)[0];
    const bookedToday = new Set(
        appointments
            .filter(a => a.at && _isToday(a.at) && !DID_NOT_HAPPEN.has(a.status))
            .map(a => pktHourMinute(a.at))
    );

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
        status: ({ confirmed: "Upcoming", pending: "Pending", completed: "Completed", cancelled: "Cancelled", no_show: "No Show" })[a.status] || "Pending",
        caseId: a.case_id,
    });

    // One loader, reused by the effect and by every handler that has to
    // re-read after the server refused something.
    const reload = async () => {
        try {
            const { data, error } = await listAppointments({ page_size: 50 });
            // The client resolves on failure rather than throwing, so an error
            // here is a value. Keep whatever is on screen: an empty list would
            // read as "no appointments" when the read simply failed.
            if (!error && data?.items) setAppointments(data.items.map(mapApiAppt));
        } catch {
            // Same rule.
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => { reload(); }, []);

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

    const handleReject = async (id) => {
        const apt = appointments.find(a => a.id === id);
        const { error } = await apiCancel(id);
        if (error) {
            const errMsg = error.message || "Could not cancel appointment";
            toast.show(errMsg, "danger", 4000);
            addNotif({ type: "appointment", title: "Failed to Cancel", body: errMsg, time: "Just now" });
            return;
        }
        setAppointments(prev => prev.map(a => a.id === id ? { ...a, status: "Cancelled" } : a));
        const msg = `❌ Appointment rejected with ${apt?.client}`;
        toast.show(msg, "warn", 3000);
        addNotif({ type: "appointment", title: "Appointment Rejected", body: msg, time: "Just now" });
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
        setAppointments(prev => prev.map(a => a.id === id ? { ...a, status: "Completed" } : a));
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
        setAppointments(prev => prev.map(a => a.id === id ? { ...a, status: "No Show" } : a));
        const msg = `${apt?.client || "The client"} did not attend`;
        toast.show(msg, "warn", 3000);
        addNotif({ type: "appointment", title: "Marked as No Show", body: msg, time: "Just now" });
    };

    const statCounts = {
        today: appointments.filter(a => a.at && _isToday(a.at) && !DID_NOT_HAPPEN.has(a.status)).length,
        upcoming: appointments.filter(a => a.status === "Upcoming").length,
        pending: appointments.filter(a => a.status === "Pending").length,
        completed: appointments.filter(a => a.status === "Completed").length,
    };

    return (
        <div style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}>
            <div style={{ flex: 1, overflowY: "auto" }}>
                <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>

                    {/* ── Modals ──────────────────────────────────── */}
                    {joinModal && (
                        <JoinCallModal apt={joinModal} onClose={() => setJoinModal(null)}
                            onSaveLink={handleSaveMeetingLink} t={t} />
                    )}

                    {/* ── Header ──────────────────────────────────── */}
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                        <div>
                            <div style={{ fontSize: 22, fontWeight: 700, color: t.text, fontFamily: "Georgia,serif" }}>Appointments</div>
                            <div style={{ fontSize: 13, color: t.textMuted, marginTop: 3 }}>Manage consultations and client meetings</div>
                        </div>
                    </div>

                    {/* ── Enhanced Filter row ──────────────────────────────── */}
                    <div style={{
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "space-between",
                        gap: 16,
                        padding: "12px 16px",
                        background: `${t.cardHi}`,
                        borderRadius: 12,
                        border: `1px solid ${t.border}`,
                        flexWrap: "wrap"
                    }}>
                        {/* Left side - Search and Status together */}
                        <div style={{ display: "flex", gap: 12, alignItems: "center", flex: 1, minWidth: 0 }}>
                            <div style={{ position: "relative", flex: 1, maxWidth: 280 }}>
                                <span style={{
                                    position: "absolute", left: 12, top: "50%", transform: "translateY(-50%)",
                                    fontSize: 13, color: t.textMuted, pointerEvents: "none", zIndex: 1
                                }}>
                                    <Icon d={I.search} size={13} />
                                </span>
                                <input
                                    value={search}
                                    onChange={e => setSearch(e.target.value)}
                                    placeholder="Search appointments, clients, or cases..."
                                    style={{
                                        width: "100%", height: 38,
                                        paddingLeft: 36, paddingRight: 14,
                                        borderRadius: 8,
                                        border: `1.5px solid ${t.border}`,
                                        background: t.card,
                                        color: t.text,
                                        fontSize: 12.5,
                                        outline: "none",
                                        fontFamily: "inherit",
                                        transition: "border-color .15s",
                                        boxSizing: "border-box"
                                    }}
                                    onFocus={e => e.target.style.borderColor = t.primary}
                                    onBlur={e => e.target.style.borderColor = t.border}
                                />
                            </div>

                            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                                <span style={{ fontSize: 12, color: t.textMuted, fontWeight: 500, whiteSpace: "nowrap" }}>Status:</span>
                                <select
                                    value={statusF}
                                    onChange={e => setStatusF(e.target.value)}
                                    style={{
                                        height: 38,
                                        padding: "0 12px",
                                        borderRadius: 8,
                                        border: `1.5px solid ${t.border}`,
                                        background: t.card,
                                        color: t.text,
                                        fontSize: 12.5,
                                        cursor: "pointer",
                                        fontFamily: "inherit",
                                        outline: "none",
                                        minWidth: 140,
                                        transition: "border-color .15s"
                                    }}
                                    onFocus={e => e.target.style.borderColor = t.primary}
                                    onBlur={e => e.target.style.borderColor = t.border}
                                >
                                    {tabs.map(s => <option key={s} value={s}>{s === "All" ? "All Status" : s}</option>)}
                                </select>
                            </div>
                        </div>

                        {/* Right side - View toggle */}
                        <div style={{ display: "flex", alignItems: "center", gap: 10, flexShrink: 0 }}>
                            <span style={{ fontSize: 12, color: t.textMuted, fontWeight: 500, whiteSpace: "nowrap" }}>View:</span>
                            <div style={{ display: "flex", background: t.card, borderRadius: 8, border: `1.5px solid ${t.border}`, padding: 2 }}>
                                {["list", "calendar"].map(v => (
                                    <button
                                        key={v}
                                        onClick={() => setViewMode(v)}
                                        style={{
                                            padding: "6px 12px",
                                            border: "none",
                                            background: viewMode === v ? t.primary : "transparent",
                                            color: viewMode === v ? (t.mode === "dark" ? "#0b1c22" : "#fff") : t.textMuted,
                                            cursor: "pointer",
                                            fontSize: 12,
                                            fontWeight: viewMode === v ? 600 : 500,
                                            borderRadius: 6,
                                            transition: "all .15s",
                                            fontFamily: "inherit",
                                            whiteSpace: "nowrap"
                                        }}
                                        onMouseEnter={e => {
                                            if (viewMode !== v) {
                                                e.currentTarget.style.background = `${t.primary}15`;
                                                e.currentTarget.style.color = t.primary;
                                            }
                                        }}
                                        onMouseLeave={e => {
                                            if (viewMode !== v) {
                                                e.currentTarget.style.background = "transparent";
                                                e.currentTarget.style.color = t.textMuted;
                                            }
                                        }}
                                    >
                                        {v.charAt(0).toUpperCase() + v.slice(1)}
                                        {v === "list" ? " 📋" : " 📅"}
                                    </button>
                                ))}
                            </div>
                        </div>
                    </div>

                    {viewMode === "list" ? (
                        <div className="rgrid" style={{ display: "grid", gridTemplateColumns: "1fr 260px", gap: 18 }}>
                            <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>

                                {/* ── Stat cards ──────────────────────── */}
                                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: 10 }}>
                                    <StatCard label="Today" value={statCounts.today} color="#38d8c4" bg="rgba(56,216,196,0.12)" border="rgba(56,216,196,0.30)" />
                                    <StatCard label="Upcoming" value={statCounts.upcoming} color="#5ab3ff" bg="rgba(90,179,255,0.12)" border="rgba(90,179,255,0.30)" />
                                    <StatCard label="Pending" value={statCounts.pending} color="#e8b84b" bg="rgba(232,184,75,0.12)" border="rgba(232,184,75,0.30)" />
                                    <StatCard label="Completed" value={statCounts.completed} color="#3ec99a" bg="rgba(62,201,154,0.12)" border="rgba(62,201,154,0.30)" />
                                </div>

                                {/* ── Filter tabs ─────────────────────── */}
                                <div style={{ display: "flex", gap: 4, padding: "6px 0", borderTop: `1px solid ${t.border}`, borderBottom: `1px solid ${t.border}` }}>
                                    {tabs.map(tab => (
                                        <button key={tab} onClick={() => setStatusF(tab)} style={{
                                            padding: "5px 14px", borderRadius: 8, border: "none", cursor: "pointer",
                                            fontSize: 12, fontWeight: 600, fontFamily: "inherit",
                                            background: statusF === tab ? t.primaryGlow : "transparent",
                                            color: statusF === tab ? t.primary : t.textMuted,
                                            transition: "all .15s",
                                        }}>
                                            {tab}
                                            {tab !== "All" && (
                                                <span style={{
                                                    marginLeft: 5, fontSize: 10, padding: "1px 5px", borderRadius: 6,
                                                    background: statusF === tab ? `${t.primary}22` : t.cardHi,
                                                    color: statusF === tab ? t.primary : t.textFaint,
                                                }}>
                                                    {appointments.filter(a => a.status === tab).length}
                                                </span>
                                            )}
                                        </button>
                                    ))}
                                </div>

                                {/* ── Appointment cards ───────────────── */}
                                <div className="rgrid-2" style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                                    {filtered.map(apt => (
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
                                                    <Btn variant="danger" size="sm" style={{ flex: 1 }} onClick={() => handleReject(apt.id)}>
                                                        <Icon d={I.x} size={12} /> Reject
                                                    </Btn>
                                                </>)}

                                                {apt.status === "Upcoming" && (<>
                                                    {apt.type === "Video Call" ? (
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
                                                    ) : (
                                                        <Btn variant="primary" size="sm" style={{ flex: 1 }}>
                                                            <Icon d={I.map} size={12} /> View Details
                                                        </Btn>
                                                    )}
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
                                                    <Btn variant="danger" size="sm" onClick={() => handleReject(apt.id)}>
                                                        <Icon d={I.x} size={12} />
                                                    </Btn>
                                                </>)}

                                                {apt.status === "Completed" && (
                                                    <Btn variant="secondary" size="sm" style={{ flex: 1 }}>
                                                        <Icon d={I.eye} size={12} /> View Summary
                                                    </Btn>
                                                )}
                                            </div>
                                        </Card>
                                    ))}

                                    {loading && (
                                        <div style={{ gridColumn: "1 / -1", textAlign: "center", padding: 40, color: t.textMuted, fontSize: 14 }}>
                                            Loading appointments…
                                        </div>
                                    )}
                                    {!loading && filtered.length === 0 && (
                                        <div style={{ gridColumn: "1 / -1", textAlign: "center", padding: 40, color: t.textMuted, fontSize: 14 }}>
                                            No appointments found for "{statusF}" filter.
                                        </div>
                                    )}
                                </div>
                            </div>

                            {/* ── Right sidebar ──────────────────────── */}
                            <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
                                <Card style={{ padding: 16 }}>
                                    <div style={{ fontSize: 12, fontWeight: 700, color: t.textFaint, letterSpacing: "0.1em", textTransform: "uppercase", textAlign: "center", marginBottom: 12 }}>
                                        TODAY'S SCHEDULE
                                    </div>
                                    <div className="rgrid-2" style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 5, marginBottom: 14 }}>
                                        {["09:00", "09:30", "10:00", "10:30", "11:00", "11:30", "12:00", "12:30", "13:00", "13:30", "14:00", "14:30", "15:00", "15:30", "16:00", "16:30"].map(slot => {
                                            const booked = bookedToday.has(slot);
                                            return (
                                                <button key={slot} disabled={booked} style={{
                                                    padding: "6px 4px", borderRadius: 7, fontSize: 11, fontWeight: 500,
                                                    border: `1px solid ${booked ? t.border : t.borderHi}`,
                                                    background: booked ? t.cardHi : t.primaryGlow2,
                                                    color: booked ? t.textFaint : t.primary,
                                                    cursor: booked ? "not-allowed" : "pointer",
                                                    textDecoration: booked ? "line-through" : "none",
                                                }}>{slot}</button>
                                            );
                                        })}
                                    </div>
                                    <div style={{ borderRadius: 10, background: t.primaryGlow2, border: `1px solid ${t.primary}30`, padding: 14, textAlign: "center" }}>
                                        <div style={{ fontSize: 11, color: t.textMuted, textTransform: "uppercase", letterSpacing: "0.07em", fontWeight: 600, marginBottom: 4 }}>Next Meeting</div>
                                        <div style={{ fontSize: 20, fontWeight: 700, color: t.text, fontFamily: "Georgia,serif" }}>{nextApt ? nextApt.client : "No upcoming meeting"}</div>
                                        <div style={{ fontSize: 16, fontWeight: 700, color: t.primary, marginTop: 3 }}>{nextApt ? `${nextApt.date} · ${nextApt.time}` : "—"}</div>
                                    </div>
                                </Card>

                                <Card style={{ padding: 16 }}>
                                    <div style={{ fontSize: 12, fontWeight: 700, color: t.textFaint, letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: 12 }}>
                                        Quick Actions
                                    </div>
                                    <div style={{ display: "flex", flexDirection: "column", gap: 7 }}>
                                        <Btn variant="secondary" full size="sm">
                                            <Icon d={I.clock} size={13} /> Block Time
                                        </Btn>
                                    </div>
                                </Card>
                            </div>
                        </div>
                    ) : (
                        /* ── Calendar view ──────────────────────────── */
                        <div className="rgrid" style={{ display: "grid", gridTemplateColumns: "1fr 280px", gap: 18 }}>
                            <Card style={{ overflow: "hidden" }}>
                                <div style={{ overflowX: "auto" }}>
                                    <table style={{ width: "100%", borderCollapse: "collapse", minWidth: 650 }}>
                                        <thead>
                                            <tr>
                                                <th style={{ width: 56, padding: "10px 8px", borderBottom: `1px solid ${t.border}`, borderRight: `1px solid ${t.border}`, background: t.surface }} />
                                                {CAL_DAYS.map((d, i) => (
                                                    <th key={d} style={{ padding: "10px 6px", borderBottom: `1px solid ${t.border}`, borderRight: `1px solid ${t.border}`, background: t.surface, textAlign: "center", minWidth: 95 }}>
                                                        <div style={{ fontSize: 10, color: t.textFaint, fontWeight: 600, textTransform: "uppercase" }}>{d} Day</div>
                                                        <div style={{ fontSize: 18, fontWeight: 700, color: _weekDayKeys[i] === pktToday() ? t.primary : t.text, marginTop: 1 }}>{dayOfMonth(_weekDayKeys[i])}</div>
                                                    </th>
                                                ))}
                                            </tr>
                                        </thead>
                                        <tbody>
                                            {CAL_HOURS.map(hr => (
                                                <tr key={hr}>
                                                    <td style={{ padding: "6px 8px", fontSize: 11, color: t.textFaint, borderRight: `1px solid ${t.border}`, borderBottom: `1px solid ${t.border}`, fontWeight: 500, textAlign: "right", verticalAlign: "top", whiteSpace: "nowrap" }}>{hr}</td>
                                                    {CAL_DAYS.map((_, di) => {
                                                        const evs = appointments.filter(a =>
                                                            a.at && !DID_NOT_HAPPEN.has(a.status) &&
                                                            pktDayKey(a.at) === _weekDayKeys[di] &&
                                                            pktHour(a.at) === parseInt(hr)
                                                        );
                                                        return (
                                                            <td key={di} style={{ padding: 3, borderRight: `1px solid ${t.border}`, borderBottom: `1px solid ${t.border}`, verticalAlign: "top", height: 50 }}>
                                                                {evs.map((ev, ei) => (
                                                                    <div key={ei} style={{
                                                                        background: ev.type === "Video Call" ? `${t.info}22` : `${t.primary}18`,
                                                                        border: `1px solid ${ev.type === "Video Call" ? t.info : t.primary}40`,
                                                                        borderRadius: 6, padding: "4px 6px", marginBottom: 2, cursor: "pointer",
                                                                    }}>
                                                                        <div style={{ fontSize: 11, fontWeight: 600, color: t.text, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{ev.client}</div>
                                                                        <div style={{ fontSize: 10, color: t.textMuted, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{ev.purpose}</div>
                                                                    </div>
                                                                ))}
                                                            </td>
                                                        );
                                                    })}
                                                </tr>
                                            ))}
                                        </tbody>
                                    </table>
                                </div>
                            </Card>

                            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                                <Card style={{ padding: 16 }}>
                                    <div style={{ fontSize: 13, fontWeight: 700, color: t.text, marginBottom: 10 }}>Quick Summary</div>
                                    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(110px, 1fr))", gap: 8, marginBottom: 12 }}>
                                        {[{ l: "Upcoming", v: statCounts.upcoming, c: "#5ab3ff" }, { l: "Pending", v: statCounts.pending, c: "#e8b84b" }, { l: "Done", v: statCounts.completed, c: "#3ec99a" }].map(s => (
                                            <div key={s.l} style={{ padding: "8px 6px", borderRadius: 8, background: t.cardHi, border: `1px solid ${t.border}`, textAlign: "center" }}>
                                                <div style={{ fontSize: 15, fontWeight: 700, color: s.c }}>{s.v}</div>
                                                <div style={{ fontSize: 10, color: t.textMuted, marginTop: 2 }}>{s.l}</div>
                                            </div>
                                        ))}
                                    </div>
                                    {appointments.slice(0, 4).map((a, i) => (
                                        <div key={i} style={{ display: "flex", gap: 8, alignItems: "center", padding: "7px 0", borderBottom: i < 3 ? `1px solid ${t.border}` : "none" }}>
                                            <div style={{ width: 28, height: 28, borderRadius: 8, background: t.grad1, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 9, fontWeight: 700, color: t.mode === "dark" ? "#111B1F" : "#fff", flexShrink: 0 }}>{a.initials}</div>
                                            <div style={{ flex: 1, minWidth: 0 }}>
                                                <div style={{ fontSize: 12, fontWeight: 600, color: t.text, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{a.client}</div>
                                                <div style={{ fontSize: 10, color: t.textFaint }}>{a.purpose.slice(0, 22)}…</div>
                                            </div>
                                        </div>
                                    ))}
                                </Card>
                            </div>
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
}

export { AppointmentsPage };