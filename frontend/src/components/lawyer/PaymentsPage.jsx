'use client';
// Payments — lawyer raises peshi/professional fee requests on their cases and
// tracks what's been collected. The client pays securely (Safepay; mock in dev).
import { useEffect, useState } from "react";
import { useTheme } from "./theme.js";
import { useToast } from "@/components/shared/Toast.jsx";
import {
    listPayments, paymentSummary, createFeeRequest, downloadReceipt, listCases,
} from "@/lib/api.js";

const STATUS_STYLE = {
    paid:    { bg: "#10b98122", fg: "#10b981", label: "Paid" },
    pending: { bg: "#f59e0b22", fg: "#f59e0b", label: "Awaiting payment" },
    created: { bg: "#6366f122", fg: "#6366f1", label: "Sent" },
    expired: { bg: "#6b728022", fg: "#9ca3af", label: "Expired" },
    failed:  { bg: "#ef444422", fg: "#ef4444", label: "Failed" },
    cancelled:{ bg: "#6b728022", fg: "#9ca3af", label: "Cancelled" },
};

function StatusChip({ status }) {
    const s = STATUS_STYLE[status] || STATUS_STYLE.created;
    return <span style={{ fontSize: 10.5, fontWeight: 700, padding: "2px 9px", borderRadius: 10, background: s.bg, color: s.fg }}>{s.label}</span>;
}

function Tile({ t, label, value, accent }) {
    return (
        <div style={{ flex: 1, minWidth: 150, background: t.card, border: `1px solid ${t.border}`, borderRadius: 12, padding: 14 }}>
            <div style={{ fontSize: 10.5, fontWeight: 700, color: t.textFaint, textTransform: "uppercase", letterSpacing: "0.06em" }}>{label}</div>
            <div style={{ fontSize: 22, fontWeight: 800, color: accent || t.text, marginTop: 4 }}>PKR {Number(value || 0).toLocaleString()}</div>
        </div>
    );
}

function RaiseFeeModal({ t, cases, onClose, onDone }) {
    const toast = useToast();
    const [caseId, setCaseId] = useState(cases[0]?._id || "");
    const [amount, setAmount] = useState("");
    const [purpose, setPurpose] = useState("peshi_fee");
    const [note, setNote] = useState("");
    const [busy, setBusy] = useState(false);

    const submit = async () => {
        const amt = Number(amount);
        if (!caseId) return toast.show("Pick a case", "error", 2500);
        if (!amt || amt <= 0) return toast.show("Enter a valid amount", "error", 2500);
        setBusy(true);
        const { data, error } = await createFeeRequest({ case_id: caseId, amount: amt, purpose, note });
        setBusy(false);
        if (error) return toast.show("❌ " + (error.message || "Failed to raise fee"), "error", 3000);
        toast.show("✅ Fee request sent to the client", "success", 2500);
        onDone(data);
    };

    const field = { width: "100%", height: 40, padding: "0 12px", borderRadius: 9, border: `1.5px solid ${t.border}`, background: t.inputBg, color: t.text, fontSize: 13.5, outline: "none", fontFamily: "inherit" };

    return (
        <div onClick={onClose} style={{ position: "fixed", inset: 0, background: "#0008", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 1000, padding: 16 }}>
            <div onClick={e => e.stopPropagation()} style={{ width: 460, maxWidth: "100%", background: t.card, border: `1px solid ${t.border}`, borderRadius: 16, padding: 22 }}>
                <div className="serif" style={{ fontSize: 18, fontWeight: 700, color: t.text, marginBottom: 14 }}>Raise a fee</div>

                <label style={{ fontSize: 11, fontWeight: 700, color: t.textFaint }}>CASE</label>
                <select value={caseId} onChange={e => setCaseId(e.target.value)} style={{ ...field, marginTop: 4, marginBottom: 12 }}>
                    {cases.length === 0 && <option value="">No cases assigned to you</option>}
                    {cases.map(c => <option key={c._id} value={c._id}>{c.title || c.case_number || c._id}</option>)}
                </select>

                <label style={{ fontSize: 11, fontWeight: 700, color: t.textFaint }}>PURPOSE</label>
                <div style={{ display: "flex", gap: 8, margin: "4px 0 12px" }}>
                    {[["peshi_fee", "Appearance (Peshi)"], ["professional_fee", "Professional fee"]].map(([v, l]) => (
                        <button key={v} onClick={() => setPurpose(v)} style={{
                            flex: 1, height: 38, borderRadius: 9, fontSize: 12.5, fontWeight: 700, cursor: "pointer", fontFamily: "inherit",
                            border: `1.5px solid ${purpose === v ? t.primary : t.border}`,
                            background: purpose === v ? t.primary + "18" : "transparent",
                            color: purpose === v ? t.primary : t.textMuted,
                        }}>{l}</button>
                    ))}
                </div>

                <label style={{ fontSize: 11, fontWeight: 700, color: t.textFaint }}>AMOUNT (PKR)</label>
                <input value={amount} onChange={e => setAmount(e.target.value.replace(/[^\d]/g, ""))} inputMode="numeric" placeholder="e.g. 5000" style={{ ...field, marginTop: 4, marginBottom: 12 }} />

                <label style={{ fontSize: 11, fontWeight: 700, color: t.textFaint }}>NOTE (optional)</label>
                <input value={note} onChange={e => setNote(e.target.value)} placeholder="e.g. Hearing on 10 July" style={{ ...field, marginTop: 4, marginBottom: 18 }} />

                <div style={{ display: "flex", gap: 10, justifyContent: "flex-end" }}>
                    <button onClick={onClose} style={{ padding: "0 18px", height: 40, borderRadius: 9, border: `1px solid ${t.border}`, background: "transparent", color: t.textMuted, fontSize: 13, fontWeight: 700, cursor: "pointer", fontFamily: "inherit" }}>Cancel</button>
                    <button onClick={submit} disabled={busy || cases.length === 0} style={{ padding: "0 22px", height: 40, borderRadius: 9, border: "none", background: (busy || cases.length === 0) ? t.border : t.primary, color: t.mode === "dark" ? "#111B1F" : "#fff", fontSize: 13, fontWeight: 700, cursor: busy ? "default" : "pointer", fontFamily: "inherit" }}>{busy ? "Sending…" : "Send request"}</button>
                </div>
            </div>
        </div>
    );
}

function PaymentsPage() {
    const { t } = useTheme();
    const toast = useToast();
    const [summary, setSummary] = useState(null);
    const [payments, setPayments] = useState([]);
    const [cases, setCases] = useState([]);
    const [showModal, setShowModal] = useState(false);
    const [loading, setLoading] = useState(true);

    const load = async () => {
        const [s, p] = await Promise.all([paymentSummary(), listPayments()]);
        if (s.data) setSummary(s.data);
        if (Array.isArray(p.data)) setPayments(p.data);
        setLoading(false);
    };

    useEffect(() => {
        load();
        listCases({ page_size: 50 }).then(({ data }) => { if (data?.items) setCases(data.items); });
    }, []);

    return (
        <div style={{ maxWidth: 860 }}>
            <div className="fade-up" style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 12, marginBottom: 16, flexWrap: "wrap" }}>
                <div>
                    <div className="serif" style={{ fontSize: 22, fontWeight: 700, color: t.text }}>Payments</div>
                    <div style={{ fontSize: 13, color: t.textMuted, marginTop: 3 }}>Collect appearance (peshi) and professional fees from your clients</div>
                </div>
                <button onClick={() => setShowModal(true)} style={{ padding: "0 18px", height: 42, borderRadius: 10, border: "none", background: t.primary, color: t.mode === "dark" ? "#111B1F" : "#fff", fontSize: 13, fontWeight: 700, cursor: "pointer", fontFamily: "inherit" }}>+ Raise fee</button>
            </div>

            <div style={{ display: "flex", gap: 12, flexWrap: "wrap", marginBottom: 16 }}>
                <Tile t={t} label="Received" value={summary?.earned} accent="#10b981" />
                <Tile t={t} label="Net (after fee)" value={summary?.net} />
                <Tile t={t} label="Awaiting" value={summary?.pending} accent="#f59e0b" />
            </div>

            <div style={{ background: t.card, border: `1px solid ${t.border}`, borderRadius: 14, padding: 8 }}>
                {loading && <div style={{ padding: 20, fontSize: 13, color: t.textMuted }}>Loading…</div>}
                {!loading && payments.length === 0 && (
                    <div style={{ padding: 24, textAlign: "center", fontSize: 13, color: t.textMuted }}>
                        No fee requests yet. Click <b>Raise fee</b> to bill a client for a hearing or your professional fee.
                    </div>
                )}
                {payments.map(p => (
                    <div key={p.id} style={{ display: "flex", alignItems: "center", gap: 12, padding: "12px 12px", borderBottom: `1px solid ${t.border}`, flexWrap: "wrap" }}>
                        <div style={{ flex: 1, minWidth: 200 }}>
                            <div style={{ fontSize: 13.5, fontWeight: 700, color: t.text }}>
                                PKR {Number(p.amount).toLocaleString()}
                                <span style={{ fontSize: 11, fontWeight: 500, color: t.textMuted }}> · {p.purpose === "peshi_fee" ? "Peshi" : "Professional"}</span>
                            </div>
                            <div style={{ fontSize: 11.5, color: t.textMuted, marginTop: 2 }}>
                                {(p.case_snapshot?.title) || "—"} · {p.payer_snapshot?.name || "Client"}
                                {p.status === "paid" && <span style={{ color: "#10b981" }}> · net PKR {Number(p.net_to_payee).toLocaleString()}</span>}
                            </div>
                        </div>
                        <StatusChip status={p.status} />
                        {p.status === "paid" && (
                            <button onClick={() => downloadReceipt(p.id, `receipt-${p.id}.pdf`)} style={{ fontSize: 11, fontWeight: 700, color: t.primary, border: `1px solid ${t.primary}40`, borderRadius: 8, padding: "5px 10px", background: "transparent", cursor: "pointer", fontFamily: "inherit" }}>Receipt ↓</button>
                        )}
                    </div>
                ))}
            </div>

            {showModal && (
                <RaiseFeeModal t={t} cases={cases} onClose={() => setShowModal(false)}
                    onDone={() => { setShowModal(false); load(); }} />
            )}
        </div>
    );
}

export { PaymentsPage };
