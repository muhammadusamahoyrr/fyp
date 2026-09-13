"use client";
import React from "react";
import Ic from "./Ic.jsx";
import {
    lawyerSubtitle,
    matchFallbackNotice,
    matchHeading,
} from "@/lib/lawyerMatch.js";

/**
 * The lawyer-matching card in a chat message.
 *
 * Extracted from ModChatbot so it can be mounted and asserted on directly.
 * Driving it through the chat component would need a WebSocket harness, and the
 * thing worth testing here is what a client is told — not how the socket
 * delivered it.
 *
 * WHY THE NOTICE RENDERS BESIDE THE LIST
 *
 * A `general_listing` means the matcher found nothing that qualified and is
 * offering verified lawyers to browse. The service explains that in `notice`,
 * and the notice was previously shown only when there were NO candidates — so
 * in the one case where the distinction matters most, a browsing list appeared
 * under a heading with no explanation of why nothing matched. The candidates
 * and the reason they are not matches belong on screen together.
 *
 * Purely presentational: no fetching, no state.
 */
export default function LawyerMatchPanel({ message, theme, onBook }) {
    const t = theme;
    const lawyers = Array.isArray(message?.matchedLawyers) ? message.matchedLawyers : [];
    const kind = message?.matchResultKind || "";
    const head = matchHeading(kind, {
        count: lawyers.length,
        suggestLawyer: message?.suggestLawyer,
    });
    const notice = matchFallbackNotice(kind, message?.matchNotice);

    // Nothing to show and nothing to say.
    if (!head.show && !notice) return null;

    // Something to say, but no list. "Unavailable" must not read as
    // "there are none".
    if (!head.show) {
        return (
            <div data-testid="match-notice"
                 style={{ marginTop: 10, fontSize: 11.5, color: t.textMuted }}>
                {notice}
            </div>
        );
    }

    return (
        <div data-testid="match-panel" data-kind={kind} style={{
            marginTop: 12,
            background: t.mode === "dark" ? "rgba(0,196,159,0.07)" : "rgba(0,196,159,0.06)",
            border: `1.5px solid ${t.primary}`,
            borderRadius: 14, padding: "14px 16px",
        }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
                <Ic n="scale" s={15} c={t.primary} />
                <span data-testid="match-heading"
                      style={{ fontSize: 12.5, fontWeight: 700, color: t.primary }}>
                    {head.title}
                </span>
            </div>

            {/* Shown ALONGSIDE the candidates, not instead of them. */}
            {!head.ranked && notice && (
                <div data-testid="match-notice"
                     style={{ fontSize: 11.5, color: t.textMuted, marginBottom: 10 }}>
                    {notice}
                </div>
            )}

            <div style={{ display: "flex", flexDirection: "column", gap: 7, marginBottom: 12 }}>
                {lawyers.map((l, li) => (
                    <div key={l?.id || li} data-testid="match-lawyer" style={{
                        background: t.surface,
                        border: `1px solid ${t.border}`,
                        borderRadius: 10, padding: "9px 12px",
                        display: "flex", justifyContent: "space-between",
                        alignItems: "center", gap: 8,
                    }}>
                        <div style={{ flex: 1, minWidth: 0 }}>
                            <div style={{ fontWeight: 700, fontSize: 13, color: t.text, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                                {l?.full_name}
                            </div>
                            <div data-testid="match-subtitle"
                                 style={{ fontSize: 11, color: t.textMuted, marginTop: 2 }}>
                                {/* `match_score: null` means the service refused to rank
                                    this lawyer. `(null || 0) * 100` rendered that as
                                    "0% match" — a precise-looking number for a
                                    measurement never made. */}
                                {lawyerSubtitle(l)}
                            </div>
                            {Array.isArray(l?.specializations) && l.specializations.length > 0 && (
                                <div style={{ fontSize: 11, color: t.textDim, marginTop: 2 }}>
                                    {l.specializations.slice(0, 2).join(" · ")}
                                </div>
                            )}
                        </div>
                    </div>
                ))}
            </div>

            <button
                onClick={onBook}
                style={{
                    width: "100%", padding: "9px 0",
                    background: t.primary,
                    color: t.mode === "dark" ? "#1A2E35" : "#fff",
                    border: "none", borderRadius: 10,
                    fontSize: 12.5, fontWeight: 700,
                    cursor: "pointer", fontFamily: "'Inter',sans-serif",
                    transition: "opacity 0.2s",
                }}
                onMouseEnter={e => e.currentTarget.style.opacity = "0.85"}
                onMouseLeave={e => e.currentTarget.style.opacity = "1"}
            >
                Book Consultation →
            </button>
        </div>
    );
}
