'use client';
// Lawyer — Overseas Property Disputes inbox.
// Read/handoff only: a client sends a dispute's case brief here; the lawyer opens
// the full brief (eligibility, grievance, intake, jurisdiction) and downloads the
// draft petition when one exists. No fee negotiation, engagement letter or payment —
// that is the separate hiring flow.
import { useState, useEffect, useCallback } from "react";
import { useTheme } from "./theme.js";
import { Card, Btn, Badge } from "./components.jsx";
import { disputeLawyerInbox, disputeBrief, downloadDocument } from "@/lib/api.js";

const STATE_META = {
    ready_for_drafting: { label: "Ready to draft", type: "success" },
    held_for_lawyer_triage: { label: "Held for your review", type: "warn" },
};
const fmtDate = (iso) => iso ? new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" }) : "";

function Field({ label, value, T }) {
    return (
        <div style={{ marginBottom: 10 }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: T.textMuted, textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 2 }}>{label}</div>
            <div style={{ fontSize: 13.5, color: T.text }}>{value || "—"}</div>
        </div>
    );
}

function Section({ title, children, T }) {
    return (
        <div style={{ marginBottom: 18 }}>
            <div style={{ fontSize: 12.5, fontWeight: 700, color: T.primary, marginBottom: 8, paddingBottom: 5, borderBottom: `1px solid ${T.border}` }}>{title}</div>
            {children}
        </div>
    );
}

export function DisputesInboxPage() {
    const { t: T } = useTheme();
    const [items, setItems] = useState([]);
    const [loading, setLoading] = useState(true);
    const [brief, setBrief] = useState(null);
    const [openingId, setOpeningId] = useState(null);
    const [busyDoc, setBusyDoc] = useState(false);
    const [toast, setToast] = useState(null);
    const showToast = (m) => { setToast(m); setTimeout(() => setToast(null), 3000); };

    const reload = useCallback(() => {
        setLoading(true);
        disputeLawyerInbox().then(({ data }) => {
            if (Array.isArray(data)) setItems(data);
            setLoading(false);
        }).catch(() => setLoading(false));
    }, []);
    useEffect(() => { reload(); }, [reload]);

    const openBrief = async (id) => {
        setOpeningId(id); setBrief(null);
        const { data, error } = await disputeBrief(id);
        setOpeningId(null);
        if (error || !data || data.error) return showToast("❌ Could not load the case brief");
        setBrief(data);
    };

    const downloadPetition = async () => {
        if (!brief?.petition?.document_id) return;
        setBusyDoc(true);
        await downloadDocument(brief.petition.document_id, "special-court-petition");
        setBusyDoc(false);
    };

    // ── Brief detail view ────────────────────────────────────────────────────
    if (brief) {
        const g = brief.grievance || {}, j = brief.jurisdiction || {}, ik = brief.intake || {}, el = brief.eligibility || {};
        const sm = STATE_META[brief.state] || { label: brief.state, type: "gray" };
        return (
            <div style={{ display: "flex", flexDirection: "column", gap: 16, fontFamily: "'DM Sans', system-ui, sans-serif", maxWidth: 860 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                    <Btn variant="ghost" size="sm" onClick={() => setBrief(null)}>← Back to inbox</Btn>
                    <Badge type={sm.type}>{sm.label}</Badge>
                </div>
                <div>
                    <div style={{ fontSize: 22, fontWeight: 700, color: T.text, fontFamily: "Georgia, serif" }}>Property dispute — case brief</div>
                    <div style={{ fontSize: 13, color: T.textMuted, marginTop: 3 }}>
                        From {brief.client?.name || "an overseas Pakistani client"} · sent {fmtDate(brief.assignment?.sent_at)}
                    </div>
                </div>

                {(brief.hold_reasons || []).length > 0 && (
                    <Card style={{ padding: 14, borderColor: T.warn }}>
                        <div style={{ fontSize: 12.5, fontWeight: 700, color: T.warn, marginBottom: 6 }}>Held for your review because:</div>
                        <ul style={{ margin: 0, paddingLeft: 18 }}>
                            {brief.hold_reasons.map((r, i) => <li key={i} style={{ fontSize: 12.5, color: T.textMuted, marginBottom: 4 }}>{r}</li>)}
                        </ul>
                    </Card>
                )}

                <Card style={{ padding: 18 }}>
                    <Section title="Overseas-Pakistani eligibility" T={T}>
                        <Field label="Qualifies" value={el.eligible ? "Yes" : "Not established"} T={T} />
                        {(el.reasons || []).length > 0 && <Field label="Notes" value={el.reasons.join(" ")} T={T} />}
                    </Section>

                    <Section title="Grievance classification" T={T}>
                        <div style={{ display: "flex", gap: 24, flexWrap: "wrap" }}>
                            <Field label="Type" value={g.category_label || g.category} T={T} />
                            <Field label="Confidence" value={g.confidence} T={T} />
                            <Field label="Needs triage" value={g.needs_triage ? "Yes — ambiguous" : "No — clear"} T={T} />
                        </div>
                        {(g.alternatives || []).length > 0 && <Field label="Other possibilities" value={g.alternatives.join(", ")} T={T} />}
                        {g.reasoning && <Field label="Reasoning" value={g.reasoning} T={T} />}
                    </Section>

                    <Section title="The facts (as entered)" T={T}>
                        <Field label="Property" value={ik.property_description} T={T} />
                        <div style={{ display: "flex", gap: 24, flexWrap: "wrap" }}>
                            <Field label="Opposing party" value={ik.opposing_party + (ik.opposing_party_relation ? ` (${ik.opposing_party_relation})` : "")} T={T} />
                            <Field label="Khasra / registry" value={ik.khasra_number} T={T} />
                        </div>
                        <Field label="Timeline" value={ik.timeline} T={T} />
                        <Field label="Documents held" value={(ik.documents_held || []).join(", ")} T={T} />
                        <Field label="Relief sought" value={ik.relief_wanted} T={T} />
                    </Section>

                    <Section title="Jurisdiction (Special Court, 2024 Act)" T={T}>
                        <div style={{ display: "flex", gap: 24, flexWrap: "wrap" }}>
                            <Field label="Province" value={j.province} T={T} />
                            <Field label="Court status" value={j.court_status} T={T} />
                            <Field label="Appeal window" value={j.appeal_days ? `${j.appeal_days} days` : "confirm with court"} T={T} />
                            <Field label="Disposal" value={j.disposal_days ? `${j.disposal_days} days (from leave to defend)` : "—"} T={T} />
                        </div>
                    </Section>

                    <Section title="Draft petition" T={T}>
                        {brief.petition ? (
                            <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
                                <Btn variant="primary" size="sm" onClick={downloadPetition} disabled={busyDoc}>
                                    {busyDoc ? "Downloading…" : "⤓ Download draft petition (PDF)"}
                                </Btn>
                                <span style={{ fontSize: 11.5, color: T.textMuted }}>Drafted {fmtDate(brief.petition.drafted_at)} — a DRAFT for you to review, complete and file.</span>
                            </div>
                        ) : (
                            <div style={{ fontSize: 13, color: T.textMuted }}>No petition drafted — this dispute was held for your review before drafting.</div>
                        )}
                    </Section>
                </Card>

                {toast && <div style={{ position: "fixed", bottom: 24, right: 24, background: T.card, border: `1px solid ${T.border}`, color: T.text, padding: "10px 16px", borderRadius: 10, fontSize: 13, zIndex: 100 }}>{toast}</div>}
            </div>
        );
    }

    // ── Inbox list ───────────────────────────────────────────────────────────
    return (
        <div style={{ display: "flex", flexDirection: "column", gap: 18, fontFamily: "'DM Sans', system-ui, sans-serif" }}>
            <div>
                <div style={{ fontSize: 22, fontWeight: 700, color: T.text, fontFamily: "Georgia, serif" }}>Overseas Property Disputes</div>
                <div style={{ fontSize: 13, color: T.textMuted, marginTop: 3 }}>
                    Case briefs sent to you by overseas Pakistanis — open one to see the whole case in one place.
                </div>
            </div>

            {loading ? (
                <div style={{ fontSize: 13, color: T.textMuted }}>Loading…</div>
            ) : items.length === 0 ? (
                <Card style={{ padding: 28, textAlign: "center" }}>
                    <div style={{ fontSize: 14, color: T.text, fontWeight: 600, marginBottom: 4 }}>No case briefs yet</div>
                    <div style={{ fontSize: 12.5, color: T.textMuted }}>When a client sends you a property dispute, it will appear here.</div>
                </Card>
            ) : (
                <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                    {items.map(d => {
                        const sm = STATE_META[d.state] || { label: d.state, type: "gray" };
                        return (
                            <Card key={d.dispute_id} onClick={() => openBrief(d.dispute_id)} style={{ padding: 16, cursor: "pointer" }}>
                                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
                                    <div>
                                        <div style={{ fontSize: 14.5, fontWeight: 600, color: T.text, marginBottom: 3 }}>{d.category_label || "Property dispute"}</div>
                                        <div style={{ fontSize: 12, color: T.textMuted }}>
                                            {d.province || "—"} · sent {fmtDate(d.sent_at)}
                                        </div>
                                    </div>
                                    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                                        {d.has_petition && <Badge type="info">Petition ready</Badge>}
                                        <Badge type={sm.type}>{sm.label}</Badge>
                                        <span style={{ fontSize: 13, color: T.primary, fontWeight: 600 }}>
                                            {openingId === d.dispute_id ? "Opening…" : "Open →"}
                                        </span>
                                    </div>
                                </div>
                            </Card>
                        );
                    })}
                </div>
            )}

            {toast && <div style={{ position: "fixed", bottom: 24, right: 24, background: T.card, border: `1px solid ${T.border}`, color: T.text, padding: "10px 16px", borderRadius: 10, fontSize: 13, zIndex: 100 }}>{toast}</div>}
        </div>
    );
}
