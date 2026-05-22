'use client';
import { createContext, useContext, useEffect, useState } from "react";
import { useAuth } from "@/context/AuthContext.jsx";
import { getNotifications, markNotificationRead, markAllNotificationsRead, listCases, listAppointments } from "@/lib/api.js";

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
};

const normalizeNotificationType = (type) => {
    if (!type) return "info";
    if (type.startsWith("appointment_")) return "appointment";
    if (type === "appointment") return "appointment";
    if (type === "hearing_scheduled") return "hearing";
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

    const updateCase = (patch) =>
        setCaseData(prev => ({ ...prev, ...patch }));

    const completeIntake = ({ role, caseType, caseSubtype, province, caseId, description, evidenceDocs }) => {
        updateCase({ intakeDone: true, role, caseType, caseSubtype, province, caseId, description, evidenceDocs });
    };

    const selectLawyer = (lawyer) => updateCase({ selectedLawyer: lawyer });

    const confirmAppointment = ({ date, time, details }) => {
        const milestoneId = `appt-${Date.now()}`;
        setCaseData(prev => {
            const milestone = {
                id: milestoneId,
                status: "active",
                event: `Consultation — ${prev.selectedLawyer?.name ?? "Lawyer"}`,
                date,
                time,
                desc: details || "Initial consultation appointment confirmed.",
                tag: "appointment",
                milestoneId,
            };
            return {
                ...prev,
                appointment: { date, time, details, status: "confirmed" },
                appointmentMilestones: [...prev.appointmentMilestones, milestone],
            };
        });
    };

    const markNotificationDone = async (id) => {
        updateCase({
            notifications: caseData.notifications.map(n =>
                n.id === id ? { ...n, done: true } : n
            ),
        });

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
            notifications: [{ id: `n-${Date.now()}`, done: false, ...notif }, ...prev.notifications],
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
            if (notifRes.data)  patch.notifications = notifRes.data.map(mapNotification);
            if (casesRes.data)  patch.cases         = casesRes.data.items || casesRes.data || [];
            if (apptsRes.data)  patch.appointments  = apptsRes.data.items || apptsRes.data || [];
            if (Object.keys(patch).length) updateCase(patch);
        };

        const connectLiveNotifications = () => {
            const token = typeof window !== "undefined" ? localStorage.getItem("aai-token") : "";
            if (!user?._id || !token) return;

            const wsBase = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1")
                .replace(/\/api\/v1$/, "")
                .replace(/^http/, "ws");
            const wsUrl = `${wsBase}/ws/notifications/${user._id}?token=${encodeURIComponent(token)}`;

            ws = new WebSocket(wsUrl);
            ws.onmessage = (event) => {
                try {
                    const message = JSON.parse(event.data);
                    if (message?.type === "notification" && message.notification) {
                        const incoming = mapNotification(message.notification);
                        setCaseData(prev => ({
                            ...prev,
                            notifications: [incoming, ...prev.notifications.filter(n => n.id !== incoming.id)],
                        }));
                    }
                } catch (error) {
                    console.warn("⚠️ Failed to parse notification websocket message:", error);
                }
            };
            ws.onerror = () => {
                console.warn("⚠️ Notification websocket connection failed");
            };
        };

        fetchAll();
        connectLiveNotifications();
        return () => {
            cancelled = true;
            try { ws?.close(); } catch {}
        };
    }, [user?._id]);

    const refreshAppointments = async () => {
        const { data } = await listAppointments({ page_size: 50 });
        if (data) updateCase({ appointments: data.items || data || [] });
    };

    return (
        <CaseCtx.Provider value={{
            ...caseData,
            updateCase,
            completeIntake,
            selectLawyer,
            confirmAppointment,
            markNotificationDone,
            markAllNotificationsDone,
            addNotification,
            refreshAppointments,
            unreadCount,
        }}>
            {children}
        </CaseCtx.Provider>
    );
};
