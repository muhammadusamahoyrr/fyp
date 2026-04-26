'use client';
import { createContext, useContext, useState } from "react";

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
    // ── Intake (Module 2) ───────────────────────────────────────
    intakeDone: false,          // true once Step 5 is submitted
    caseRef: "AIQ-2026-0042",
    role: "",             // "Plaintiff" | "Defendant"
    caseType: "",             // e.g. "Employment Law"
    caseSubtype: "",             // e.g. "Wrongful Termination"
    description: "",
    evidenceDocs: [],             // [{name, size, type}]

    // ── Lawyer (Module 4) ───────────────────────────────────────
    selectedLawyer: null,         // full lawyer object from ModLawyers
    appointment: null,            // {date, time, details, status}

    // ── Tracking (Module 7) ─────────────────────────────────────
    // Milestones added by appointment booking land here so Module 7
    // can consume them without its own hard-coded array.
    appointmentMilestones: [],    // [{id, event, date, time, desc, tag, status, milestoneId}]

    // ── Notifications (Module 7.3) ──────────────────────────────
    notifications: [
        { id: "n1", type: "hearing", urgency: "critical", title: "Court Hearing", date: "Feb 25", time: "9:00 AM", desc: "Pre-trial conference — attend in person", done: false },
        { id: "n2", type: "deadline", urgency: "overdue", title: "Pre-Trial Brief", date: "Feb 20", time: "Due", desc: "Response to opposition motion — 1 day overdue", done: false },
        { id: "n3", type: "deadline", urgency: "urgent", title: "Witness List Sign-off", date: "Feb 23", time: "EOD", desc: "Confirm final witness list with your lawyer", done: false },
        { id: "n4", type: "reminder", urgency: "normal", title: "Review Exhibit C", date: "Feb 23", time: "9:00 AM", desc: "Review pages 8–14 before the hearing", done: false },
        { id: "n5", type: "document", urgency: "info", title: "Document Updated", date: "Feb 18", time: "11:00 AM", desc: "Pre-Trial Brief revised — v3 now available", done: true },
        { id: "n6", type: "response", urgency: "info", title: "Lawyer Response", date: "Feb 19", time: "2:30 PM", desc: "Atty. Ahmad Raza replied about Exhibit C", done: true },
    ],
};

/* ─── Provider ──────────────────────────────────────────────── */
export const CaseProvider = ({ children }) => {
    const [caseData, setCaseData] = useState(INITIAL);

    /* Generic field updater — merges partial updates */
    const updateCase = (patch) =>
        setCaseData(prev => ({ ...prev, ...patch }));

    /* ── Intake helpers ─────────────────────────────────────── */
    const completeIntake = ({ role, caseType, caseSubtype, description, evidenceDocs }) => {
        updateCase({ intakeDone: true, role, caseType, caseSubtype, description, evidenceDocs });
    };

    /* ── Lawyer / appointment helpers ──────────────────────── */
    const selectLawyer = (lawyer) => updateCase({ selectedLawyer: lawyer });

    /**
     * confirmAppointment — called by ModLawyers when user confirms booking.
     * Writes appointment data AND creates a milestone entry so Module 7
     * timeline displays it immediately (Fix #5).
     */
    const confirmAppointment = ({ date, time, details }) => {
        const milestoneId = `appt-${Date.now()}`;
        const milestone = {
            id: milestoneId,
            status: "active",
            event: `Consultation — ${caseData.selectedLawyer?.name ?? "Lawyer"}`,
            date,
            time,
            desc: details || "Initial consultation appointment confirmed.",
            tag: "appointment",
            milestoneId,
        };
        updateCase({
            appointment: { date, time, details, status: "confirmed" },
            appointmentMilestones: [...caseData.appointmentMilestones, milestone],
        });
    };

    /* ── Notification helpers ───────────────────────────────── */
    const markNotificationDone = (id) =>
        updateCase({
            notifications: caseData.notifications.map(n =>
                n.id === id ? { ...n, done: true } : n
            ),
        });

    const markAllNotificationsDone = () =>
        updateCase({
            notifications: caseData.notifications.map(n => ({ ...n, done: true })),
        });

    const addNotification = (notif) =>
        updateCase({
            notifications: [{ id: `n-${Date.now()}`, done: false, ...notif }, ...caseData.notifications],
        });

    const unreadCount = caseData.notifications.filter(n => !n.done).length;

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
            unreadCount,
        }}>
            {children}
        </CaseCtx.Provider>
    );
};