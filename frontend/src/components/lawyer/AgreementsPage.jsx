'use client';
// Lawyer Agreements — engagement letters and contracts awaiting signature.
// Counterpart of the client's AgreementHub; same backend, lawyer perspective.
import { useState, useEffect, useCallback } from "react";
import { useTheme } from "./theme.js";
import { Card, Btn, Badge } from "./components.jsx";
import { useAuth } from "@/context/AuthContext.jsx";
import { listAgreements, signAgreement, declineAgreement, downloadExecutedAgreement } from "@/lib/api.js";
import { DraftComposer } from "./DraftComposer.jsx";

const STATUS_LABEL = { pending: "Pending", executed: "Executed", cancelled: "Cancelled", draft: "Draft" };
const STATUS_BADGE = { Pending: "warn", Executed: "success", Cancelled: "danger", Draft: "gray" };

function mapAgreement(a, myId) {
    const parties = a.parties || [];
    const me = parties.find(p => p.user_id === myId);
    return {
        id: a.id || a._id,
        title: a.title || "Agreement",
        body: a.body_html || "",
        status: STATUS_LABEL[a.status] || "Pending",
        parties,
        signedCount: parties.filter(p => p.signed).length,
        needsMySig: a.status === "pending" && !!me && !me.signed,
        date: a.created_at ? new Date(a.created_at).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" }) : "",
        counterparts: parties.filter(p => p.user_id !== myId).map(p => p.full_name).join(" · "),
        eto: a.eto_classification,
        isEngagementLetter: !!a.engagement_id,
        // Kept for the editor: `version` drives optimistic concurrency and
        // `raw` is the untouched server copy, which is what the digest is
        // taken over at send time. The mapped view is for DISPLAY; signing
        // reads from the server's own object.
        isDraft: a.status === "draft",
        version: a.version,
        raw: a,
    };
}

export function AgreementsPage() {
    const { t: T } = useTheme();
    const { user } = useAuth();
    const [items, setItems] = useState([]);
    const [loading, setLoading] = useState(true);
    const [active, setActive] = useState(null);
    const [signName, setSignName] = useState("");
    const [busy, setBusy] = useState(false);
    // Same two-step guard as the client screen. The backend authorises decline
    // by PARTY, not by role -- a lawyer is a party and may refuse -- so the
    // destructive path needs the same protection here.
    const [declineOpen, setDeclineOpen] = useState(false);
    const [declineReason, setDeclineReason] = useState("");
    const [toast, setToast] = useState(null);
    const showToast = (msg) => { setToast(msg); setTimeout(() => setToast(null), 3200); };
    // `composing` is either "new" or the draft being edited. A draft never
    // opens the signing modal: it has nothing to sign yet, and the only way to
    // sign it is to send it.
    const [composing, setComposing] = useState(null);

    const reload = useCallback(() => {
        // 3F: the response is a page, not a bare array. Reading `data.items`
        // rather than `data` -- an `Array.isArray(data)` check would now be
        // false for every successful response and the screen would render
        // "no agreements" to someone who has forty.
        listAgreements({ page_size: 50 }).then(({ data }) => {
            const rows = data?.items;
            if (Array.isArray(rows)) setItems(rows.map(a => mapAgreement(a, user?._id)));
            setLoading(false);
        }).catch(() => setLoading(false));
    }, [user?._id]);
    useEffect(() => { reload(); }, [reload]);

    const doSign = async () => {
        if (!signName.trim()) { showToast("⚠️ Type your full name to sign"); return; }
        setBusy(true);
        const { data, error } = await signAgreement(active.id, "typed", signName.trim());
        setBusy(false);
        if (error) { showToast("❌ " + (error.message || "Failed to sign")); return; }
        showToast(data?.status === "executed" ? "🎉 Agreement fully executed — both parties notified" : "✅ Signed — awaiting the other party");
        setActive(null);
        reload();
    };

    const doDecline = async () => {
        setBusy(true);
        const { error } = await declineAgreement(active.id, declineReason);
        setBusy(false);
        if (error) { showToast("❌ " + (error.message || "Failed to decline")); return; }
        showToast("Agreement declined — the other party has been notified");
        setActive(null);
        setDeclineOpen(false);
        setDeclineReason("");
        reload();
    };

    const doDownload = async () => {
        setBusy(true);
        const { error } = await downloadExecutedAgreement(active.id, `${active.title || "agreement"}.pdf`);
        setBusy(false);
        if (error) { showToast("❌ " + error); return; }
        showToast("⬇ Downloaded");
    };

    const closeModal = () => { setActive(null); setDeclineOpen(false); setDeclineReason(""); };

    const awaitingMe = items.filter(a => a.needsMySig);
    // Only ever this lawyer's own: the server does not return anyone else's.
    const drafts = items.filter(a => a.isDraft);

    return (
        <div style={{ display: "flex", flexDirection: "column", gap: 18, fontFamily: "'DM Sans', system-ui, sans-serif" }}>
            <div style={{ display: "flex", alignItems: "flex-start", gap: 14, flexWrap: "wrap" }}>
                <div style={{ flex: 1, minWidth: 220 }}>
                    <div style={{ fontSize: 22, fontWeight: 700, color: T.text, fontFamily: "Georgia, serif" }}>Agreements</div>
                    <div style={{ fontSize: 13, color: T.textMuted, marginTop: 3 }}>
                        Engagement letters and contracts — signed electronically under ETO 2002
                    </div>
                </div>
                <Btn variant="primary" onClick={() => setComposing("new")}>+ New agreement</Btn>
            </div>

            {/* Stats */}
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 12 }}>
                {[
                    { l: "Drafts", v: drafts.length, c: T.textMuted, ic: "📝" },
                    { l: "Awaiting My Signature", v: awaitingMe.length, c: awaitingMe.length ? T.warn : T.success, ic: "✍️" },
                    { l: "Pending Others", v: items.filter(a => a.status === "Pending" && !a.needsMySig).length, c: T.info, ic: "⏰" },
                    { l: "Executed", v: items.filter(a => a.status === "Executed").length, c: T.success, ic: "✅" },
                ].map(s => (
                    <Card key={s.l} style={{ padding: 16 }}>
                        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                            <div>
                                <div style={{ fontSize: 11, color: T.textMuted, marginBottom: 6, textTransform: "uppercase", letterSpacing: "0.05em", fontWeight: 600 }}>{s.l}</div>
                                <div style={{ fontSize: 28, fontWeight: 700, color: s.c, lineHeight: 1 }}>{s.v}</div>
                            </div>
                            <span style={{ fontSize: 20 }}>{s.ic}</span>
                        </div>
                    </Card>
                ))}
            </div>

            {/* List */}
            <Card style={{ padding: 0, overflow: "hidden" }}>
                {loading ? (
                    <div style={{ padding: 40, textAlign: "center", color: T.textMuted, fontSize: 13 }}>Loading agreements…</div>
                ) : items.length === 0 ? (
                    <div style={{ padding: 40, textAlign: "center" }}>
                        <div style={{ fontSize: 32, marginBottom: 10 }}>📜</div>
                        <div style={{ fontSize: 14, color: T.textMuted }}>
                            No agreements yet. Accepting a client&apos;s case request creates an
                            engagement letter here automatically — or write one yourself with
                            &ldquo;New agreement&rdquo;.
                        </div>
                    </div>
                ) : items.map((a, i) => (
                    <div key={a.id} onClick={() => {
                        if (a.isDraft) { setComposing(a.raw); return; }
                        setActive(a); setSignName(user?.full_name || "");
                    }} style={{
                        display: "flex", alignItems: "center", gap: 14, padding: "14px 20px",
                        borderBottom: i < items.length - 1 ? `1px solid ${T.border}` : "none",
                        cursor: "pointer", transition: "background .12s",
                    }}
                        onMouseEnter={e => e.currentTarget.style.background = "rgba(64,240,220,0.04)"}
                        onMouseLeave={e => e.currentTarget.style.background = "transparent"}
                    >
                        <span style={{ fontSize: 20, flexShrink: 0 }}>{a.isEngagementLetter ? "⚖️" : "📄"}</span>
                        <div style={{ flex: 1, minWidth: 0 }}>
                            <div style={{ fontSize: 13.5, fontWeight: 700, color: T.text, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{a.title}</div>
                            <div style={{ fontSize: 11.5, color: T.textMuted, marginTop: 2 }}>
                                With {a.counterparts || "—"} · {a.signedCount}/{a.parties.length} signed · {a.date}
                            </div>
                        </div>
                        {a.needsMySig && (
                            <span style={{ fontSize: 11, fontWeight: 700, color: T.warn, background: `${T.warn}18`, borderRadius: 20, padding: "3px 10px", flexShrink: 0 }}>
                                ✍️ Your signature needed
                            </span>
                        )}
                        <Badge type={STATUS_BADGE[a.status] || "gray"}>{a.status}</Badge>
                    </div>
                ))}
            </Card>

            {/* Detail / sign modal */}
            {active && (
                <div onClick={closeModal} style={{
                    position: "fixed", inset: 0, zIndex: 9999, background: "rgba(0,0,0,0.6)",
                    display: "flex", alignItems: "center", justifyContent: "center", padding: 20,
                }}>
                    <div onClick={e => e.stopPropagation()} style={{
                        background: T.card, border: `1px solid ${T.border}`, borderRadius: 16,
                        width: "100%", maxWidth: 640, maxHeight: "88vh", display: "flex", flexDirection: "column", overflow: "hidden",
                        boxShadow: T.shadowCard,
                    }}>
                        <div style={{ display: "flex", alignItems: "center", gap: 12, padding: "16px 20px", borderBottom: `1px solid ${T.border}` }}>
                            <span style={{ fontSize: 20 }}>{active.isEngagementLetter ? "⚖️" : "📄"}</span>
                            <div style={{ flex: 1, minWidth: 0 }}>
                                <div style={{ fontSize: 15, fontWeight: 700, color: T.text, fontFamily: "Georgia,serif", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{active.title}</div>
                                <div style={{ fontSize: 11, color: T.textMuted }}>{active.eto || "Awaiting first signature"}</div>
                            </div>
                            <Badge type={STATUS_BADGE[active.status] || "gray"}>{active.status}</Badge>
                            <button onClick={closeModal} style={{ background: "none", border: `1px solid ${T.border}`, borderRadius: 8, width: 28, height: 28, cursor: "pointer", color: T.textMuted, fontSize: 14 }}>✕</button>
                        </div>

                        <div style={{ flex: 1, overflowY: "auto", padding: "16px 20px" }}>
                            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 14 }}>
                                {active.parties.map(p => (
                                    <div key={p.user_id} style={{ display: "flex", alignItems: "center", gap: 7, padding: "6px 11px", borderRadius: 9, background: p.signed ? `${T.success}14` : T.cardHi, border: `1px solid ${p.signed ? T.success + "40" : T.border}` }}>
                                        <span style={{ fontSize: 11 }}>{p.signed ? "✅" : "⏰"}</span>
                                        <span style={{ fontSize: 12, fontWeight: 600, color: T.text }}>{p.full_name}</span>
                                        <span style={{ fontSize: 10, color: p.signed ? T.success : T.textMuted }}>{p.signed ? "signed" : "pending"}</span>
                                    </div>
                                ))}
                            </div>
                            <div style={{ background: T.cardHi, border: `1px solid ${T.border}`, borderRadius: 10, padding: "16px 18px", fontSize: 13, lineHeight: 1.8, color: T.text, whiteSpace: "pre-wrap", fontFamily: "Georgia,serif" }}>
                                {active.body || "No content."}
                            </div>

                            {/* Only once EXECUTED. There is no document to
                                download before both parties have signed, and
                                the server refuses one -- offering the button
                                early would promise a file that does not
                                exist. */}
                            {active.status === "Executed" && (
                                <div style={{ marginTop: 14 }}>
                                    <Btn variant="secondary" disabled={busy} onClick={doDownload}>
                                        ⬇ Download signed copy
                                    </Btn>
                                    <div style={{ fontSize: 10.5, color: T.textFaint, marginTop: 6, lineHeight: 1.5 }}>
                                        Includes the signature record: who signed, how, when the
                                        server recorded it, and the digest of the signed text.
                                    </div>
                                </div>
                            )}
                        </div>

                        {active.needsMySig && (
                            <div style={{ padding: "12px 20px 16px", borderTop: `1px solid ${T.border}`, background: T.surface }}>
                                <div style={{ fontSize: 10.5, fontWeight: 700, color: T.textMuted, textTransform: "uppercase", letterSpacing: "0.07em", marginBottom: 7 }}>
                                    Sign — type your full legal name
                                </div>
                                <div style={{ display: "flex", gap: 10 }}>
                                    <input value={signName} onChange={e => setSignName(e.target.value)} placeholder="Your full name"
                                        style={{ flex: 1, height: 38, border: `1px solid ${T.border}`, borderRadius: 9, background: T.inputBg, color: T.text, fontSize: 13, padding: "0 12px", outline: "none", fontFamily: "inherit" }} />
                                    <Btn variant="accent" disabled={busy} onClick={doSign}>{busy ? "Signing…" : "✍️ Sign Agreement"}</Btn>
                                </div>
                                <div style={{ fontSize: 10.5, color: T.textFaint, marginTop: 7, lineHeight: 1.5 }}>
                                    Recorded with timestamp and IP in the audit log; classified under the Electronic Transactions Ordinance 2002.
                                </div>

                                {!declineOpen ? (
                                    <button type="button" onClick={() => setDeclineOpen(true)}
                                        style={{ marginTop: 11, background: "none", border: "none", padding: 0, cursor: "pointer", fontSize: 12, color: T.textMuted, textDecoration: "underline", fontFamily: "inherit" }}>
                                        I do not want to sign this
                                    </button>
                                ) : (
                                    <div style={{ marginTop: 12, paddingTop: 12, borderTop: `1px solid ${T.border}` }}>
                                        <div style={{ fontSize: 10.5, fontWeight: 700, color: T.danger, textTransform: "uppercase", letterSpacing: "0.07em", marginBottom: 7 }}>
                                            Decline — this ends the agreement and cannot be undone
                                        </div>
                                        <input value={declineReason} maxLength={2000}
                                            onChange={e => setDeclineReason(e.target.value)}
                                            placeholder="Reason (optional — the other party will see this)"
                                            style={{ width: "100%", height: 38, border: `1px solid ${T.border}`, borderRadius: 9, background: T.inputBg, color: T.text, fontSize: 13, padding: "0 12px", outline: "none", fontFamily: "inherit" }} />
                                        <div style={{ display: "flex", gap: 9, marginTop: 9 }}>
                                            <button type="button" disabled={busy} onClick={doDecline}
                                                style={{ background: T.danger, border: `1px solid ${T.danger}`, borderRadius: 9, padding: "9px 15px", cursor: "pointer", fontSize: 12.5, color: "#fff", fontWeight: 700, fontFamily: "inherit" }}>
                                                {busy ? "Declining…" : "Confirm decline"}
                                            </button>
                                            <button type="button" disabled={busy} onClick={() => { setDeclineOpen(false); setDeclineReason(""); }}
                                                style={{ background: "none", border: `1px solid ${T.border}`, borderRadius: 9, padding: "9px 15px", cursor: "pointer", fontSize: 12.5, color: T.text, fontFamily: "inherit" }}>
                                                Keep reviewing
                                            </button>
                                        </div>
                                    </div>
                                )}
                            </div>
                        )}
                    </div>
                </div>
            )}

            {composing && (
                <DraftComposer
                    draft={composing === "new" ? null : composing}
                    onSaved={reload}
                    onClose={(msg) => { setComposing(null); if (msg) showToast(msg); }}
                />
            )}

            {toast && (
                <div style={{
                    position: "fixed", bottom: 28, left: "50%", transform: "translateX(-50%)", zIndex: 10000,
                    background: T.card, border: `1px solid ${T.border}`, borderRadius: 10,
                    padding: "10px 20px", fontSize: 13, color: T.text, boxShadow: T.shadowCard,
                }}>{toast}</div>
            )}
        </div>
    );
}
