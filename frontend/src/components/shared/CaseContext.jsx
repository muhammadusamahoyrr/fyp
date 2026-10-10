'use client';
import { createContext, useContext, useEffect, useRef, useState } from "react";
import { useAuth } from "@/context/AuthContext.jsx";
import { getNotifications, markNotificationRead, markAllNotificationsRead, listCases, listAppointments, openNotificationSocket } from "@/lib/api.js";
import { broadcastNotification, reconnectDelay } from "@/lib/notificationTarget.js";

/* ═══════════════════════════════════════════════════════════════
   GLOBAL CASE CONTEXT  —  Fix #1
   Single shared state that every module reads from / writes to.
   Eliminates the disconnect between Intake → Lawyers → Agreements
   → Tracking identified in the design review.
═══════════════════════════════════════════════════════════════ */

export const CaseCtx = createContext(null);

/** Hook — throws if used outside <CaseProvider> */
export const useCase = () => {
    const ctx = useContext(CaseCtx);
    if (!ctx) throw new Error("useCase must be used inside <CaseProvider>");
    return ctx;
};

/* ─── Initial shape ─────────────────────────────────────────── */
const INITIAL = {
    intakeDone: false,
    caseId: null,
    caseRef: "AIQ-2026-0042",
    role: "",
    caseType: "",
    caseSubtype: "",
    province: "",
    description: "",
    evidenceDocs: [],

    selectedLawyer: null,
    appointment: null,

    appointmentMilestones: [],
    notifications: [],
    cases: [],
    appointments: [],
    // `null` until the server answers: NOT `false`, which would show a "load
    // more" control before anything has been read, and NOT `true`, which
    // would claim completeness nobody has established.
    appointmentsComplete: null,
    appointmentsTotal: null,
};

const normalizeNotificationType = (type) => {
    if (!type) return "info";
    if (type.startsWith("appointment_")) return "appointment";
    if (type === "appointment") return "appointment";
    if (type === "hearing_scheduled" || type === "hearing_reminder") return "hearing";
    if (type === "document_ready") return "document";
    if (type === "case_update") return "status";
    if (type === "lawyer_assigned") return "status";
    return type;
};

const formatNotificationTimestamp = (value) => {
    if (!value) return { date: "", time: "" };
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) return { date: "", time: "" };

    return {
        date: new Intl.DateTimeFormat("en-US", {
            month: "short",
            day: "numeric",
            year: "numeric",
        }).format(parsed),
        time: new Intl.DateTimeFormat("en-US", {
            hour: "2-digit",
            minute: "2-digit",
        }).format(parsed),
    };
};

const mapNotification = (notif) => ({
    id: notif._id || notif.id,
    type: normalizeNotificationType(notif.type),
    rawType: notif.type || "",
    urgency: notif.urgency || "info",
    title: notif.title || "Notification",
    ...formatNotificationTimestamp(notif.created_at || notif.date),
    desc: notif.body || notif.description || "",
    done: Boolean(notif.read),
    payload: notif.payload || {},
});

/* ─── Provider ──────────────────────────────────────────────── */
export const CaseProvider = ({ children }) => {
    const { user } = useAuth();
    const [caseData, setCaseData] = useState(INITIAL);
    /* HAS THE CASE LIST BEEN ANSWERED FOR, as opposed to merely being empty.
     *
     * `cases` starts as `[]`, so `Array.isArray(cases)` was true from the first
     * render — before `listCases` had been called, let alone replied. Every
     * consumer therefore read "this user has no cases" during the moment the
     * app was still asking, and a document screen keyed off that restored a
     * standalone draft a beat before the user's real case arrived.
     *
     * Settles on FAILURE too: a load that errored leaves the list exactly as
     * unknown as a pending one, but leaving `casesReady` false forever means
     * every consumer waits for an answer that will never come. Ready-with-an-
     * error is the honest pair — we finished asking, and we did not find out. */
    const [casesReady, setCasesReady] = useState(false);
    const [casesError, setCasesError] = useState(null);
    const [casesReloading, setCasesReloading] = useState(false);
    /* The retry in flight, if any.
     *
     * A ref rather than the state above, because two clicks land in the same
     * render and would both see `casesReloading === false`. Holding the promise
     * lets every caller await the SAME load and get the same answer, instead of
     * the second request racing the first and the later reply winning
     * regardless of which is fresher. */
    const casesInFlight = useRef(null);
    // The latest state, for callbacks created once (the socket's).
    const caseDataRef = useRef(caseData);
    caseDataRef.current = caseData;

    const updateCase = (patch) =>
        setCaseData(prev => ({ ...prev, ...patch }));

    const completeIntake = ({ role, caseType, caseSubtype, province, caseId, description, evidenceDocs }) => {
        updateCase({ intakeDone: true, role, caseType, caseSubtype, province, caseId, description, evidenceDocs });
    };

    const selectLawyer = (lawyer) => updateCase({ selectedLawyer: lawyer });

    /* A booking was SENT. It is a request the lawyer has not accepted, so it
     * is recorded as pending, and no timeline milestone is invented for it:
     * one used to be added saying the consultation was "confirmed", which it
     * was not, and it lived only in this browser. The appointment itself comes
     * from the server (re-read here), which also sends the client's notice. */
    const confirmAppointment = ({ date, time, details, appointmentId = null }) => {
        updateCase({ appointment: { date, time, details, appointmentId, status: "pending" } });
        refreshAppointments().catch(() => {});
    };

    const markNotificationDone = async (id) => {
        const row = caseData.notifications.find(n => n.id === id);
        updateCase({
            notifications: caseData.notifications.map(n =>
                n.id === id ? { ...n, done: true } : n
            ),
        });
        // A notice made in this browser has no server row: its made-up id
        // used to be sent to the server, which refused it.
        if (row?.local) return;

        const { error } = await markNotificationRead(id);
        if (error) console.error("❌ Failed to mark notification read:", error);
    };

    const markAllNotificationsDone = async () => {
        updateCase({
            notifications: caseData.notifications.map(n => ({ ...n, done: true })),
        });

        const { error } = await markAllNotificationsRead();
        if (error) console.error("❌ Failed to mark all notifications read:", error);
    };

    const addNotification = (notif) =>
        setCaseData(prev => ({
            ...prev,
            notifications: [{ ...notif, id: `local-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`, done: false, local: true }, ...prev.notifications],
        }));

    const unreadCount = caseData.notifications.filter(n => !n.done).length;

    useEffect(() => {
        let cancelled = false;
        let ws;

        const fetchAll = async () => {
            const [notifRes, casesRes, apptsRes] = await Promise.all([
                getNotifications(),
                listCases({ page_size: 50 }),
                listAppointments({ page_size: 50 }),
            ]);
            if (cancelled) return;

            const patch = {};
            if (notifRes.data) {
                // Server rows replace what is shown; this browser's own notices stay.
                const local = (caseDataRef.current?.notifications || []).filter(n => n.local);
                patch.notifications = [...notifRes.data.map(mapNotification), ...local];
            }
            if (casesRes.data)  patch.cases         = casesRes.data.items || casesRes.data || [];
            if (apptsRes.data) {
                patch.appointments = apptsRes.data.items || apptsRes.data || [];
                // WHETHER THIS IS ALL OF THEM, recorded rather than assumed.
                //
                // The cached list is the FIRST PAGE. Fifty is not "all" — it
                // is the first fifty by the server's sort — and every consumer
                // of `caseData.appointments` was reading it as the complete
                // set. Carrying the flag means a surface that needs certainty
                // can ask for more instead of quietly being wrong.
                patch.appointmentsComplete = Number.isInteger(apptsRes.data.pages)
                    ? apptsRes.data.pages <= 1 : false;
                patch.appointmentsTotal = Number.isInteger(apptsRes.data.total)
                    ? apptsRes.data.total : null;
            }
            if (Object.keys(patch).length) updateCase(patch);

            // AFTER the answer, whichever way it went.
            setCasesError(casesRes.error || null);
            setCasesReady(true);
        };

        // Re-read what a live notification is about, so open pages show it.
        const refreshFor = async (rawType) => {
            const t = String(rawType || "");
            if (t.startsWith("appointment_")) {
                const { data } = await listAppointments({ page_size: 50 });
                if (cancelled || !data) return;
                updateCase({
                    appointments: data.items || data || [],
                    appointmentsComplete: Number.isInteger(data.pages) ? data.pages <= 1 : false,
                    appointmentsTotal: Number.isInteger(data.total) ? data.total : null,
                });
            } else if (t.startsWith("engagement_") || t === "lawyer_assigned"
                       || t === "case_update" || t === "hearing_scheduled") {
                const { data } = await listCases({ page_size: 50 });
                if (cancelled || !data) return;
                updateCase({ cases: data.items || data || [] });
            }
        };

        // The socket used to be opened once: when it closed (server restart,
        // network drop, laptop asleep) nothing arrived until a reload. It now
        // reconnects with backoff and re-reads everything when it is back.
        let attempt = 0;
        let retryTimer = null;
        const scheduleRetry = () => {
            if (cancelled || !user?._id) return;
            retryTimer = setTimeout(connectLiveNotifications, reconnectDelay(attempt));
            attempt += 1;
        };
        const connectLiveNotifications = async () => {
            if (!user?._id || cancelled) return;
            let sock;
            try {
                sock = await openNotificationSocket((message) => {
                    if (message?.type === "notification" && message.notification) {
                        const incoming = mapNotification(message.notification);
                        setCaseData(prev => ({
                            ...prev,
                            notifications: [incoming, ...prev.notifications.filter(n => n.id !== incoming.id)],
                        }));
                        broadcastNotification({ id: incoming.id, type: incoming.rawType, payload: incoming.payload });
                        refreshFor(incoming.rawType);
                    }
                });
            } catch { sock = null; }
            if (cancelled) { try { sock?.close(); } catch {} return; }
            if (!sock) { scheduleRetry(); return; }
            ws = sock;
            sock.addEventListener?.("open", () => {
                if (attempt > 0) fetchAll();   // catch up on what was missed
                attempt = 0;
            });
            sock.addEventListener?.("error", () => console.warn("⚠️ Notification websocket connection failed"));
            sock.addEventListener?.("close", () => { if (ws === sock) { ws = null; scheduleRetry(); } });
        };

        fetchAll();
        connectLiveNotifications();
        return () => {
            cancelled = true;
            clearTimeout(retryTimer);
            try { ws?.close(); } catch {}
        };
    }, [user?._id]);

    /* Ask again after a failure. Returns the error, or null on success, so a
     * caller can decide what to show without re-reading context.
     *
     * ONE FLIGHT AT A TIME. An impatient click on a slow network would
     * otherwise start a second load racing the first, and whichever replied
     * last would win — so a stale answer could overwrite a fresher one. Extra
     * callers join the request already running.
     *
     * A FAILED RETRY KEEPS WHAT WE HAVE. `cases` is only replaced on success:
     * emptying the list because a refresh failed would tell a user their
     * matters are gone when nobody managed to look. The error is retained for
     * the same reason. */
    const reloadCases = async () => {
        if (casesInFlight.current) return casesInFlight.current;

        setCasesReloading(true);
        const flight = (async () => {
            try {
                const { data, error } = await listCases({ page_size: 50 });
                if (data) updateCase({ cases: data.items || data || [] });
                setCasesError(error || null);
                setCasesReady(true);
                return error || null;
            } finally {
                casesInFlight.current = null;
                setCasesReloading(false);
            }
        })();
        casesInFlight.current = flight;
        return flight;
    };

    const refreshAppointments = async () => {
        const { data } = await listAppointments({ page_size: 50 });
        if (data) {
            updateCase({
                appointments: data.items || data || [],
                appointmentsComplete: Number.isInteger(data.pages)
                    ? data.pages <= 1 : false,
                appointmentsTotal: Number.isInteger(data.total) ? data.total : null,
            });
        }
    };

    /** Fetch one more page of appointments, ON REQUEST.
     *
     * Deliberately not automatic. This cache feeds selectors across the app,
     * and pulling an unbounded history into memory on mount to make a list
     * feel complete is a cost every screen pays for one screen's benefit.
     *
     * A failed page changes NOTHING. The choices already loaded stay exactly
     * as they were: discarding them because a later page failed would destroy
     * good data to report a partial failure, and a selector would empty itself
     * under the user.
     */
    const loadMoreAppointments = async () => {
        const loaded = caseData.appointments || [];
        if (caseData.appointmentsComplete) return false;
        // Pages are fifty rows; whatever is loaded came from whole pages.
        const nextPage = Math.ceil(loaded.length / 50) + 1;
        const { data, error } = await listAppointments({
            page: nextPage, page_size: 50,
        });
        if (error || !data || !Array.isArray(data.items)) return false;

        const seen = new Set(loaded.map(a => a?.id));
        const fresh = data.items.filter(a => a?.id === undefined || !seen.has(a.id));
        updateCase({
            appointments: [...loaded, ...fresh],
            appointmentsComplete: Number.isInteger(data.pages)
                ? data.page >= data.pages : false,
            appointmentsTotal: Number.isInteger(data.total) ? data.total : null,
        });
        return true;
    };

    return (
        <CaseCtx.Provider value={{
            ...caseData,
            updateCase,
            completeIntake,
            selectLawyer,
            confirmAppointment,
            loadMoreAppointments,
            markNotificationDone,
            markAllNotificationsDone,
            addNotification,
            refreshAppointments,
            casesReady,
            casesError,
            casesReloading,
            reloadCases,
            unreadCount,
        }}>
            {children}
        </CaseCtx.Provider>
    );
};
