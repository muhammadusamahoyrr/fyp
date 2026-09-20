'use client';
/* Active sessions — see them, and end them.
 *
 * The backend has listed and revoked sessions since auth hardening landed, and
 * nothing in the UI called any of it. So "sign out everywhere" — the one
 * control that matters after a laptop is lost or a password turns up somewhere
 * it shouldn't — existed, was tested, and was unreachable.
 *
 * TAKES ITS THEME AS A PROP rather than importing one. The client and lawyer
 * shells carry different palettes from different modules, and this panel is
 * mounted in both; importing either would tie a shared component to one shell
 * and render it wrong in the other.
 *
 * LOADING IS NOT EMPTY. A list that says "no other devices" while the request
 * is still in flight tells someone their account is safe before anything has
 * been checked, which is the more dangerous direction to be wrong in. The three
 * states are kept apart and rendered differently.
 */
import { useCallback, useEffect, useState } from "react";
import { listSessions, revokeSession, revokeAllSessions } from "@/lib/api.js";

/** A recognisable device name from a user agent, or an honest fallback. */
export function deviceLabel(userAgent) {
    const ua = String(userAgent || "");
    if (!ua.trim()) return "Unknown device";
    const browser =
        /Edg\//.test(ua) ? "Edge" :
        /OPR\/|Opera/.test(ua) ? "Opera" :
        /Chrome\//.test(ua) ? "Chrome" :
        /Safari\//.test(ua) && !/Chrome\//.test(ua) ? "Safari" :
        /Firefox\//.test(ua) ? "Firefox" : null;
    const platform =
        /Android/.test(ua) ? "Android" :
        /iPhone|iPad|iPod/.test(ua) ? "iOS" :
        /Windows/.test(ua) ? "Windows" :
        /Mac OS X|Macintosh/.test(ua) ? "macOS" :
        /Linux/.test(ua) ? "Linux" : null;
    if (browser && platform) return `${browser} on ${platform}`;
    return browser || platform || "Unknown device";
}

/** "3 minutes ago" — relative, because an absolute UTC stamp means nothing to
 *  someone deciding whether a session is theirs. */
export function whenLabel(value) {
    if (!value) return "";
    const then = new Date(value).getTime();
    if (Number.isNaN(then)) return "";
    const seconds = Math.max(0, Math.round((Date.now() - then) / 1000));
    if (seconds < 60) return "just now";
    const minutes = Math.round(seconds / 60);
    if (minutes < 60) return `${minutes} minute${minutes === 1 ? "" : "s"} ago`;
    const hours = Math.round(minutes / 60);
    if (hours < 24) return `${hours} hour${hours === 1 ? "" : "s"} ago`;
    const days = Math.round(hours / 24);
    return `${days} day${days === 1 ? "" : "s"} ago`;
}

export default function SessionsPanel({ t, onSignedOut }) {
    const [items, setItems] = useState(null);          // null = not loaded yet
    const [error, setError] = useState("");
    const [busyId, setBusyId] = useState("");
    const [confirmAll, setConfirmAll] = useState(false);

    const load = useCallback(async () => {
        setError("");
        const { data, error: err } = await listSessions();
        if (err) {
            // Left as null, so the empty state cannot be shown for a failure.
            setError(err.message || "Could not load your sessions");
            return;
        }
        setItems(Array.isArray(data?.items) ? data.items : []);
    }, []);

    useEffect(() => { load(); }, [load]);

    const endOne = async (session) => {
        setBusyId(session.session_id);
        const { error: err } = await revokeSession(session.session_id);
        setBusyId("");
        if (err) { setError(err.message || "Could not end that session"); return; }
        // Ending the session you are using logs you out here too; the server has
        // already dropped the refresh cookie, so staying on the page would show
        // a signed-in shell backed by nothing.
        if (session.current) { onSignedOut?.(); return; }
        load();
    };

    const endAll = async () => {
        setBusyId("__all__");
        const { error: err } = await revokeAllSessions();
        setBusyId("");
        if (err) { setError(err.message || "Could not sign out everywhere"); return; }
        onSignedOut?.();
    };

    const muted = { fontSize: 12, color: t.textMuted };
    const row = {
        display: "flex", alignItems: "center", gap: 12, padding: "11px 0",
        borderTop: `1px solid ${t.border}`,
    };

    return (
        <div>
            <div style={{ ...muted, marginBottom: 10, lineHeight: 1.6 }}>
                Devices currently signed in to your account. If you do not
                recognise one, end it — and change your password.
            </div>

            {error && (
                <div role="alert" style={{ fontSize: 12, color: t.danger, marginBottom: 10 }}>
                    {error}{" "}
                    <button type="button" onClick={load}
                        style={{ background: "none", border: "none", padding: 0, cursor: "pointer", color: t.danger, textDecoration: "underline", font: "inherit" }}>
                        Try again
                    </button>
                </div>
            )}

            {items === null && !error && <div style={muted}>Loading your sessions…</div>}

            {items !== null && items.length === 0 && (
                <div style={muted}>No active sessions found.</div>
            )}

            {items !== null && items.map(session => (
                <div key={session.session_id} style={row}>
                    <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ fontSize: 13, color: t.text, fontWeight: 600 }}>
                            {deviceLabel(session.user_agent)}
                            {session.current && (
                                <span style={{ marginLeft: 8, fontSize: 10.5, fontWeight: 700, color: t.success, textTransform: "uppercase", letterSpacing: "0.6px" }}>
                                    This device
                                </span>
                            )}
                        </div>
                        <div style={{ ...muted, marginTop: 2 }}>
                            {session.last_used_at
                                ? `Last active ${whenLabel(session.last_used_at)}`
                                : "Not used yet"}
                        </div>
                    </div>
                    <button
                        type="button"
                        disabled={busyId === session.session_id}
                        onClick={() => endOne(session)}
                        style={{ background: "none", border: `1px solid ${t.border}`, borderRadius: 8, padding: "6px 12px", cursor: "pointer", fontSize: 12, color: t.text }}
                    >
                        {busyId === session.session_id ? "Ending…" : "Sign out"}
                    </button>
                </div>
            ))}

            <div style={{ marginTop: 16, paddingTop: 14, borderTop: `1px solid ${t.border}` }}>
                {!confirmAll ? (
                    <button type="button" onClick={() => setConfirmAll(true)}
                        style={{ background: "none", border: `1px solid ${t.danger}`, borderRadius: 8, padding: "8px 14px", cursor: "pointer", fontSize: 12.5, color: t.danger, fontWeight: 600 }}>
                        Sign out everywhere
                    </button>
                ) : (
                    <div>
                        <div style={{ fontSize: 12.5, color: t.text, marginBottom: 9, lineHeight: 1.6 }}>
                            This ends every session including this one. You will
                            need to sign in again.
                        </div>
                        <div style={{ display: "flex", gap: 9 }}>
                            <button type="button" disabled={busyId === "__all__"} onClick={endAll}
                                style={{ background: t.danger, border: `1px solid ${t.danger}`, borderRadius: 8, padding: "8px 14px", cursor: "pointer", fontSize: 12.5, color: "#fff", fontWeight: 600 }}>
                                {busyId === "__all__" ? "Signing out…" : "Yes, sign out everywhere"}
                            </button>
                            <button type="button" disabled={busyId === "__all__"} onClick={() => setConfirmAll(false)}
                                style={{ background: "none", border: `1px solid ${t.border}`, borderRadius: 8, padding: "8px 14px", cursor: "pointer", fontSize: 12.5, color: t.text }}>
                                Cancel
                            </button>
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
}
