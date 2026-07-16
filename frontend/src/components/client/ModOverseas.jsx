'use client';
// Overseas Desk — the POA lifecycle-safety layer for the diaspora:
//   1. My POAs — plain-English drafting + live fraud-risk check, attestation
//      lifecycle, point-of-use verify link, attested-doc check, OPPPA status
//   2. Attestation Navigator — objection-aware apostille vs legacy consular chain
//   3. Special Courts — the Protection of Overseas Pakistanis' Property Act 2024 remedy
import React, { useEffect, useRef, useState } from "react";
import { useT } from "./theme.js";
import { useToast } from "@/components/shared/Toast.jsx";
import Ic from "./Ic.jsx";
import { Card, BtnPrimary, BtnOutline, ThemedInput } from "@/components/shared/shared.jsx";
import {
    overseasCreatePoa, overseasListPoas, overseasRevokePoa,
    overseasSetExecution, overseasAcknowledge, downloadDocument,
    overseasAttestationCountries, overseasAttestationPath,
    overseasSpecialCourtProvinces, overseasSpecialCourtPath,
    overseasSuggestPoa, overseasPoaRisk, overseasOpppaGuidance,
    overseasSetOpppa, overseasVerifyAttested, overseasVerifyQrUrl,
    overseasDisputeEligibility, overseasDisputeClassify, overseasDisputeCreate,
    overseasDisputeList, overseasDraftPetition, overseasSendDisputeToLawyer,
} from "@/lib/api.js";

const POWERS = [
    { code: "manage", label: "Manage & administer", disp: false },
    { code: "rent", label: "Rent out & collect rent", disp: false },
    { code: "collect", label: "Receive payments / give receipts", disp: false },
    { code: "litigate", label: "Represent in court (litigation)", disp: false },
    { code: "bank", label: "Operate related bank accounts", disp: false },
    { code: "register", label: "Sign & present for registration", disp: false },
    { code: "tax", label: "Deal with tax / utilities", disp: false },
    { code: "sell", label: "Sell property", disp: true },
    { code: "transfer", label: "Transfer title", disp: true },
    { code: "gift", label: "Gift property", disp: true },
    { code: "mortgage", label: "Mortgage property", disp: true },
];

const EXEC_STEPS = [
    ["drafted", "Drafted"],
    ["notarized", "Notarised"],
    ["mission_attested", "Mission attested"],
    ["mofa_attested", "MOFA attested"],
    ["registered", "Registered"],
];

const STATUS_COLOR = { active: "#10b981", revoked: "#ef4444", expired: "#9ca3af" };
const RISK_COLOR = { low: "#10b981", medium: "#f59e0b", high: "#f97316", critical: "#ef4444" };
const SEV_COLOR = { critical: "#ef4444", high: "#f97316", medium: "#f59e0b" };
const OPPPA_LABEL = { not_registered: "Not registered", in_progress: "Registering", registered: "Registered" };

// Fixed vocabularies — mirror the backend DisputeIntake allow-lists.
const ID_TYPES = [["nicop", "NICOP"], ["cnic", "CNIC"], ["passport", "Passport"], ["poc", "POC"], ["opf", "OPF card"]];
const DISPUTE_DOCUMENTS = [
    ["title_deed_fard", "Title deed / fard"], ["power_of_attorney", "Power of attorney"],
    ["cnic_nicop", "CNIC / NICOP"], ["sale_agreement", "Sale agreement"],
    ["fir", "FIR"], ["tax_receipts", "Tax receipts"],
];
const DISPUTE_RELIEFS = [
    ["restore_possession", "Restore my possession"], ["cancel_transfer_or_poa", "Cancel the transfer / POA"],
    ["declare_ownership", "Declare me the owner"], ["injunction", "Stop them dealing with it (injunction)"],
    ["other", "Other"],
];
const DISPUTE_CAT_LABEL = {
    illegal_occupation: "illegal occupation", poa_misuse: "misuse of a power of attorney",
    fraudulent_transfer: "a fraudulent sale or transfer", inheritance_dispute: "an inheritance dispute",
    encroachment: "an encroachment", sale_agreement_dispute: "a sale-agreement dispute",
};

const Lbl = ({ children }) => {
    const t = useT();
    return <div style={{ fontSize: 11.5, color: t.textMuted, marginBottom: 6, fontWeight: 600, letterSpacing: "0.5px", textTransform: "uppercase" }}>{children}</div>;
};

const Pill = ({ text, color, t }) => (
    <span style={{ fontSize: 10.5, fontWeight: 700, padding: "3px 10px", borderRadius: 20, background: (color || "#888") + "22", color: color || t.textMuted }}>{text}</span>
);

const selectStyle = (t) => ({
    width: "100%", height: 42, borderRadius: 10, border: `1.5px solid ${t.border}`,
    background: t.inputBg, color: t.text, fontSize: 13.5, padding: "0 12px", fontFamily: "inherit",
});

const DraftBanner = () => {
    const t = useT();
    return (
        <div style={{ border: `1px solid #B0002050`, background: "#B0002012", borderRadius: 10, padding: "10px 14px", marginBottom: 16, fontSize: 12, color: t.text }}>
            <b style={{ color: "#e05260" }}>Draft for legal review.</b> Generated POAs are unexecuted drafts — not valid until signed, notarised, attested and, for property, registered. Have a qualified Pakistani lawyer review before use.
        </div>
    );
};

/* ═══════════ TAB 1 — MY POAs ═══════════ */
function MyPoas() {
    const t = useT();
    const toast = useToast();
    const [poas, setPoas] = useState([]);
    const [loading, setLoading] = useState(true);
    const [showForm, setShowForm] = useState(false);
    const [busy, setBusy] = useState(false);
    const [intent, setIntent] = useState("");
    const [suggesting, setSuggesting] = useState(false);
    const [suggestNote, setSuggestNote] = useState(null);   // {reasoning, warnings}
    const [risk, setRisk] = useState(null);
    const [form, setForm] = useState({
        poa_type: "special", attorney_name: "", attorney_cnic: "", attorney_relation: "", attorney_address: "",
        subject: "", powers: ["manage"], restrictions: "", country_of_execution: "", expiry_date: "",
    });

    const load = async () => {
        const { data } = await overseasListPoas();
        if (Array.isArray(data)) setPoas(data);
        setLoading(false);
    };
    useEffect(() => { load(); }, []);

    // Live fraud-risk check — debounced, only while the form is open.
    useEffect(() => {
        if (!showForm) { setRisk(null); return; }
        const id = setTimeout(async () => {
            const { data } = await overseasPoaRisk({
                poa_type: form.poa_type, powers: form.powers, subject: form.subject,
                expiry_date: form.expiry_date, attorney_relation: form.attorney_relation,
            });
            if (data && typeof data.score === "number") setRisk(data);
        }, 500);
        return () => clearTimeout(id);
    }, [showForm, form.poa_type, form.powers, form.subject, form.expiry_date, form.attorney_relation]);

    const isGeneral = form.poa_type === "general";
    const togglePower = (code, disp) => {
        if (isGeneral && disp) return toast.show("Property sale/gift/mortgage needs a Special POA", "warn");
        setForm(f => ({ ...f, powers: f.powers.includes(code) ? f.powers.filter(p => p !== code) : [...f.powers, code] }));
    };

    const runSuggest = async () => {
        if (!intent.trim()) return toast.show("Describe what you want your attorney to do", "warn");
        setSuggesting(true);
        const { data, error } = await overseasSuggestPoa(intent.trim());
        setSuggesting(false);
        if (error || !data || data.error) return toast.show(data?.error || error?.detail || "Could not analyse that", "warn");
        setForm(f => ({ ...f, poa_type: data.poa_type, powers: data.powers.length ? data.powers : f.powers, subject: data.subject || f.subject }));
        setSuggestNote({ reasoning: data.reasoning, warnings: data.warnings || [] });
        toast.show("Structure suggested — review before generating", "success");
    };

    const submit = async () => {
        if (!form.attorney_name.trim()) return toast.show("Enter the attorney's name", "warn");
        if (!form.powers.length) return toast.show("Select at least one power", "warn");
        if (form.poa_type === "special" && !form.subject.trim()) return toast.show("A Special POA needs the property/matter", "warn");
        setBusy(true);
        const { data, error } = await overseasCreatePoa(form);
        setBusy(false);
        if (error || !data) return toast.show("❌ " + (error?.detail || "Could not create POA"), "danger");
        toast.show("✅ POA generated", "success");
        if (data.document_id) await downloadDocument(data.document_id, "power-of-attorney");
        setShowForm(false); setSuggestNote(null); setIntent("");
        setForm(f => ({ ...f, attorney_name: "", subject: "" }));
        load();
    };

    const revoke = async (p) => {
        if (!confirm("Revoke this Power of Attorney? A revocation deed will be generated.")) return;
        const { data, error } = await overseasRevokePoa(p.id);
        if (error) return toast.show("❌ " + (error?.detail || "Revoke failed"), "danger");
        toast.show("POA revoked", "info");
        if (data?.revocation_document_id) await downloadDocument(data.revocation_document_id, "poa-revocation");
        load();
    };
    const advance = async (p) => {
        const idx = EXEC_STEPS.findIndex(s => s[0] === p.execution_status);
        const next = EXEC_STEPS[Math.min(idx + 1, EXEC_STEPS.length - 1)][0];
        if (next === p.execution_status) return;
        const { error } = await overseasSetExecution(p.id, next);
        if (error) return toast.show("❌ " + (error?.detail || "Failed"), "danger");
        load();
    };
    const ack = async (p) => {
        const { error } = await overseasAcknowledge(p.id);
        if (error) return toast.show("❌ " + (error?.detail || "Failed"), "danger");
        load();
    };

    const field = (k, ph) => <ThemedInput value={form[k]} onChange={e => setForm(f => ({ ...f, [k]: e.target.value }))} placeholder={ph} />;

    return (
        <div>
            <DraftBanner />
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 14 }}>
                <div style={{ fontSize: 14, fontWeight: 700, color: t.text }}>Your Powers of Attorney</div>
                <BtnPrimary onClick={() => setShowForm(s => !s)}>{showForm ? "Close" : "+ New POA"}</BtnPrimary>
            </div>

            {showForm && (
                <Card style={{ padding: 18, marginBottom: 16 }}>
                    {/* Plain-English -> structure */}
                    <Lbl>Describe it in plain English</Lbl>
                    <div style={{ display: "flex", gap: 8, marginBottom: 4 }}>
                        <ThemedInput value={intent} onChange={e => setIntent(e.target.value)}
                            placeholder='e.g. "let my brother sell my flat in DHA Lahore and handle the paperwork"' />
                        <BtnOutline onClick={runSuggest} disabled={suggesting}>{suggesting ? "…" : "Suggest"}</BtnOutline>
                    </div>
                    {suggestNote && (
                        <div style={{ margin: "8px 0 14px", fontSize: 12, color: t.textMuted }}>
                            {suggestNote.reasoning && <div style={{ marginBottom: suggestNote.warnings.length ? 6 : 0 }}>{suggestNote.reasoning}</div>}
                            {suggestNote.warnings.map((w, i) => (
                                <div key={i} style={{ color: "#f97316", display: "flex", gap: 6, marginTop: 4 }}><span>⚠</span><span>{w}</span></div>
                            ))}
                        </div>
                    )}

                    <Lbl>Type</Lbl>
                    <div style={{ display: "flex", gap: 8, marginBottom: 14 }}>
                        {[["special", "Special (one property/matter)"], ["general", "General (broad, non-property)"]].map(([v, l]) => (
                            <button key={v} onClick={() => setForm(f => ({ ...f, poa_type: v, powers: v === "general" ? f.powers.filter(p => !POWERS.find(x => x.code === p)?.disp) : f.powers }))}
                                style={{ flex: 1, height: 40, borderRadius: 9, fontSize: 12.5, fontWeight: 700, cursor: "pointer", fontFamily: "inherit",
                                    border: `1.5px solid ${form.poa_type === v ? t.primary : t.border}`, background: form.poa_type === v ? t.primary + "18" : "transparent", color: form.poa_type === v ? t.primary : t.textMuted }}>{l}</button>
                        ))}
                    </div>

                    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginBottom: 8 }}>
                        {field("attorney_name", "Attorney (agent) full name *")}
                        {field("attorney_relation", "Relationship e.g. brother")}
                        {field("attorney_cnic", "Attorney CNIC")}
                        {field("attorney_address", "Attorney address in Pakistan")}
                    </div>
                    {form.poa_type === "special" && <div style={{ marginBottom: 8 }}>{field("subject", "Property / matter e.g. House No.5, Model Town, Lahore")}</div>}
                    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginBottom: 12 }}>
                        {field("country_of_execution", "Your country of residence")}
                        <ThemedInput type="date" value={form.expiry_date} onChange={e => setForm(f => ({ ...f, expiry_date: e.target.value }))} placeholder="Expiry (optional)" />
                    </div>

                    <Lbl>Powers granted</Lbl>
                    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6, marginBottom: 12 }}>
                        {POWERS.map(p => {
                            const on = form.powers.includes(p.code);
                            const blocked = isGeneral && p.disp;
                            return (
                                <label key={p.code} onClick={() => togglePower(p.code, p.disp)}
                                    style={{ display: "flex", alignItems: "center", gap: 8, padding: "8px 10px", borderRadius: 8, cursor: blocked ? "not-allowed" : "pointer", opacity: blocked ? 0.4 : 1,
                                        border: `1px solid ${on ? t.primary : t.border}`, background: on ? t.primary + "12" : "transparent", fontSize: 12.5, color: t.text }}>
                                    <input type="checkbox" readOnly checked={on} style={{ accentColor: t.primary }} /> {p.label}{p.disp && <span style={{ fontSize: 9, color: t.textMuted }}>(Special only)</span>}
                                </label>
                            );
                        })}
                    </div>
                    {field("restrictions", "Restrictions / conditions (optional)")}

                    {/* Live fraud-risk panel */}
                    {risk && (
                        <div style={{ marginTop: 14, padding: "12px 14px", borderRadius: 10, border: `1px solid ${(RISK_COLOR[risk.level] || t.border)}55`, background: (RISK_COLOR[risk.level] || t.border) + "10" }}>
                            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                                <span style={{ fontSize: 12, fontWeight: 800, textTransform: "uppercase", letterSpacing: "0.5px", color: RISK_COLOR[risk.level] }}>{risk.level} risk</span>
                                <span style={{ fontSize: 11, color: t.textMuted }}>· {risk.score}/100</span>
                            </div>
                            {risk.flags.map((f, i) => (
                                <div key={i} style={{ display: "flex", gap: 6, marginTop: 8, fontSize: 12, color: t.text }}>
                                    <span style={{ color: SEV_COLOR[f.severity] || t.textMuted, fontWeight: 700 }}>•</span>
                                    <span>{f.message}</span>
                                </div>
                            ))}
                            {risk.flags.length === 0 && <div style={{ fontSize: 12, color: t.textMuted, marginTop: 6 }}>No fraud-risk indicators on this structure.</div>}
                        </div>
                    )}

                    <div style={{ marginTop: 14 }}>
                        <BtnPrimary onClick={submit} disabled={busy}>{busy ? "Generating…" : "Generate & download POA"}</BtnPrimary>
                    </div>
                </Card>
            )}

            {loading && <div style={{ fontSize: 13, color: t.textMuted }}>Loading…</div>}
            {!loading && poas.length === 0 && !showForm && (
                <Card style={{ padding: 28, textAlign: "center", fontSize: 13.5, color: t.textMuted }}>No Powers of Attorney yet. Click <b>New POA</b> to draft one.</Card>
            )}

            {poas.map(p => <PoaCard key={p.id} p={p} onChange={load} advance={advance} ack={ack} revoke={revoke} />)}
        </div>
    );
}

/* ─── single POA card (verify link, attested-doc check, OPPPA status) ─── */
function PoaCard({ p, onChange, advance, ack, revoke }) {
    const t = useT();
    const toast = useToast();
    const fileRef = useRef(null);
    const [report, setReport] = useState(null);
    const [checking, setChecking] = useState(false);
    const [showQr, setShowQr] = useState(false);
    const execIdx = EXEC_STEPS.findIndex(s => s[0] === p.execution_status);
    const verifyToken = (p.verify_url || "").split("/verify/")[1] || "";

    const copyVerify = async () => {
        if (!p.verify_url) return;
        try { await navigator.clipboard.writeText(p.verify_url); toast.show("Verification link copied", "success"); }
        catch { toast.show(p.verify_url, "info"); }
    };

    const onAttestedFile = async (e) => {
        const file = e.target.files?.[0];
        e.target.value = "";
        if (!file) return;
        setChecking(true); setReport(null);
        const { data, error } = await overseasVerifyAttested(p.id, file);
        setChecking(false);
        if (error || !data) return toast.show("❌ " + (error?.detail || "Could not read the document"), "danger");
        setReport(data);
    };

    const setOpppa = async (status) => {
        const { error } = await overseasSetOpppa(p.id, status);
        if (error) return toast.show("❌ " + (error?.detail || "Failed"), "danger");
        toast.show("OPPPA status updated", "info");
        onChange();
    };

    return (
        <Card style={{ padding: 16, marginBottom: 12 }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 10, flexWrap: "wrap" }}>
                <div style={{ flex: 1, minWidth: 220 }}>
                    <div style={{ fontSize: 14, fontWeight: 700, color: t.text }}>
                        {p.poa_type === "special" ? "Special" : "General"} POA → {p.attorney_name}
                    </div>
                    <div style={{ fontSize: 12, color: t.textMuted, marginTop: 2 }}>{p.subject || "—"}{p.expiry_date ? ` · expires ${new Date(p.expiry_date).toLocaleDateString()}` : ""}</div>
                    {p.document_sha256 && <div style={{ fontSize: 10, color: t.textFaint, marginTop: 3, fontFamily: "monospace" }}>SHA256 {p.document_sha256.slice(0, 16)}…</div>}
                </div>
                <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
                    <Pill text={p.status} color={STATUS_COLOR[p.status]} t={t} />
                    {p.expiring_soon && <Pill text="expiring soon" color="#f59e0b" t={t} />}
                    <Pill text={p.attorney_ack_status === "acknowledged" ? "acknowledged" : "unacknowledged"} color={p.attorney_ack_status === "acknowledged" ? "#10b981" : undefined} t={t} />
                    <Pill text={`OPPPA: ${OPPPA_LABEL[p.opppa_status] || "not registered"}`} color={p.opppa_status === "registered" ? "#10b981" : undefined} t={t} />
                </div>
            </div>

            {/* execution stepper */}
            <div style={{ display: "flex", gap: 4, marginTop: 12, flexWrap: "wrap" }}>
                {EXEC_STEPS.map(([code, label], i) => (
                    <span key={code} style={{ fontSize: 10, fontWeight: 700, padding: "3px 8px", borderRadius: 6, background: i <= execIdx ? t.primary + "22" : t.border, color: i <= execIdx ? t.primary : t.textMuted }}>{label}</span>
                ))}
            </div>

            <div style={{ display: "flex", gap: 8, marginTop: 12, flexWrap: "wrap" }}>
                {p.document_id && <BtnOutline onClick={() => downloadDocument(p.document_id, "power-of-attorney")}>Download POA</BtnOutline>}
                {p.verify_url && <BtnOutline onClick={copyVerify}>Copy verify link</BtnOutline>}
                {verifyToken && <BtnOutline onClick={() => setShowQr(q => !q)}>{showQr ? "Hide QR" : "Show QR"}</BtnOutline>}
                <BtnOutline onClick={() => fileRef.current?.click()}>{checking ? "Checking…" : "Check attested copy"}</BtnOutline>
                <input ref={fileRef} type="file" accept=".pdf,.docx,.txt" onChange={onAttestedFile} style={{ display: "none" }} />
                {p.status === "active" && execIdx < EXEC_STEPS.length - 1 && <BtnOutline onClick={() => advance(p)}>Mark {EXEC_STEPS[execIdx + 1][1]} ✓</BtnOutline>}
                {p.status === "active" && p.attorney_ack_status !== "acknowledged" && <BtnOutline onClick={() => ack(p)}>Mark acknowledged</BtnOutline>}
                {p.status === "active" && <BtnOutline onClick={() => revoke(p)}>Revoke</BtnOutline>}
                {p.revocation_document_id && <BtnOutline onClick={() => downloadDocument(p.revocation_document_id, "poa-revocation")}>Revocation deed</BtnOutline>}
            </div>

            {/* Verify QR — the counterparty scans this (also printed on the PDF) */}
            {showQr && verifyToken && (
                <div style={{ marginTop: 12, padding: 14, borderRadius: 10, border: `1px solid ${t.border}`, background: "#fff", display: "inline-flex", flexDirection: "column", alignItems: "center", gap: 6 }}>
                    <img src={overseasVerifyQrUrl(verifyToken)} alt="POA verification QR" width={150} height={150} style={{ display: "block" }} />
                    <div style={{ fontSize: 10.5, color: "#555" }}>Scan to verify status</div>
                </div>
            )}

            {/* OPPPA status control */}
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 10 }}>
                <span style={{ fontSize: 11, color: t.textMuted }}>OPPPA registration:</span>
                <select value={p.opppa_status || "not_registered"} onChange={e => setOpppa(e.target.value)}
                    style={{ height: 30, borderRadius: 8, border: `1px solid ${t.border}`, background: t.inputBg, color: t.text, fontSize: 12, padding: "0 8px", fontFamily: "inherit" }}>
                    <option value="not_registered">Not registered</option>
                    <option value="in_progress">Registering</option>
                    <option value="registered">Registered</option>
                </select>
            </div>

            {/* attested-doc report */}
            {report && (
                <div style={{ marginTop: 12, padding: "12px 14px", borderRadius: 10, border: `1px solid ${t.border}`, background: t.inputBg }}>
                    <div style={{ fontSize: 12.5, fontWeight: 700, color: t.text, marginBottom: 6 }}>
                        Attested-copy check {report.matches_record ? "— matches this POA ✓" : "— review below"}
                    </div>
                    <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 8 }}>
                        {(report.attestation_markers || []).map(m => <Pill key={m} text={m.replace(/_/g, " ")} color="#10b981" t={t} />)}
                        {(report.attestation_markers || []).length === 0 && <Pill text="no attestation markers" color="#f97316" t={t} />}
                    </div>
                    {(report.concerns || []).map((c, i) => (
                        <div key={i} style={{ fontSize: 12, color: "#f97316", display: "flex", gap: 6, marginTop: 4 }}><span>⚠</span><span>{c}</span></div>
                    ))}
                    <div style={{ fontSize: 10.5, color: t.textFaint, marginTop: 8 }}>{report.disclaimer}</div>
                </div>
            )}
        </Card>
    );
}

/* ═══════════ TAB 2 — ATTESTATION NAVIGATOR (backend-driven) ═══════════ */
function AttestationNavigator() {
    const t = useT();
    const [countries, setCountries] = useState([]);
    const [country, setCountry] = useState("");
    const [path, setPath] = useState(null);
    const [loading, setLoading] = useState(false);

    useEffect(() => {
        (async () => {
            const { data } = await overseasAttestationCountries();
            const list = data?.countries || [];
            setCountries(list);
            if (list.length) setCountry(list.find(c => c.code === "GB")?.code || list[0].code);
        })();
    }, []);

    useEffect(() => {
        if (!country) return;
        setLoading(true);
        (async () => {
            const { data } = await overseasAttestationPath(country, true);
            setPath(data || null);
            setLoading(false);
        })();
    }, [country]);

    const isApostille = path?.route === "apostille";
    return (
        <Card style={{ padding: 20, maxWidth: 760 }}>
            <div style={{ fontSize: 15, fontWeight: 700, color: t.text, marginBottom: 4 }}>Attesting a POA from abroad</div>
            <div style={{ fontSize: 12.5, color: t.textMuted, marginBottom: 16 }}>A POA executed overseas must be legalised before it can be used in Pakistan. The correct route depends on your country — objections to Pakistan's accession mean some members still use the older chain.</div>
            <Lbl>Where you will sign the POA</Lbl>
            <select value={country} onChange={e => setCountry(e.target.value)} style={{ ...selectStyle(t), marginBottom: 16 }}>
                {countries.map(c => <option key={c.code} value={c.code}>{c.name}</option>)}
            </select>

            {loading && <div style={{ fontSize: 13, color: t.textMuted }}>Resolving…</div>}
            {path && !loading && (
                <>
                    <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 14, flexWrap: "wrap" }}>
                        <Pill text={isApostille ? "Apostille route" : "Consular legalisation"} color={isApostille ? "#10b981" : "#f59e0b"} t={t} />
                        {path.reason === "article_12_objection" && <span style={{ fontSize: 11.5, color: t.textMuted }}>objected to Pakistan's accession</span>}
                        {path.reason === "political_non_recognition" && <span style={{ fontSize: 11.5, color: t.textMuted }}>apostille not recognised</span>}
                    </div>
                    {path.issuing_authority && (
                        <div style={{ fontSize: 12.5, color: t.text, marginBottom: 12 }}>Apostille issued by <b>{path.issuing_authority}</b>.</div>
                    )}
                    {(path.steps || []).map((s, i) => (
                        <div key={i} style={{ display: "flex", gap: 12, marginBottom: 12 }}>
                            <div style={{ flexShrink: 0, width: 26, height: 26, borderRadius: "50%", background: t.primary + "22", color: t.primary, display: "flex", alignItems: "center", justifyContent: "center", fontWeight: 700, fontSize: 13 }}>{i + 1}</div>
                            <div style={{ fontSize: 13, color: t.text, lineHeight: 1.5, paddingTop: 2 }}>{s}</div>
                        </div>
                    ))}
                    {path.note && <div style={{ fontSize: 12, color: t.textMuted, marginTop: 8 }}>{path.note}</div>}
                    <div style={{ fontSize: 11, color: t.textFaint, marginTop: 12, paddingTop: 12, borderTop: `1px solid ${t.border}` }}>
                        {path.legal_basis} · as of {path.effective_as_of}. {path.verify}
                    </div>
                </>
            )}
        </Card>
    );
}

/* ═══════════ TAB 3 — SPECIAL COURTS (Act 2024) ═══════════ */
const COURT_COLOR = { operational: "#10b981", enacted_pending: "#f59e0b", none_yet: "#9ca3af", unknown: "#9ca3af" };

function SpecialCourts() {
    const t = useT();
    const [provinces, setProvinces] = useState([]);
    const [province, setProvince] = useState("");
    const [res, setRes] = useState(null);
    const [opppa, setOpppa] = useState(null);
    const [loading, setLoading] = useState(false);

    useEffect(() => {
        (async () => {
            const { data } = await overseasSpecialCourtProvinces();
            const list = data?.provinces || [];
            setProvinces(list);
            if (list.length) setProvince(list[0].code);
            const g = await overseasOpppaGuidance();
            setOpppa(g.data || null);
        })();
    }, []);

    useEffect(() => {
        if (!province) return;
        setLoading(true);
        (async () => {
            const { data } = await overseasSpecialCourtPath(province);
            setRes(data || null);
            setLoading(false);
        })();
    }, [province]);

    return (
        <div style={{ maxWidth: 760 }}>
            {/* OPPPA: protect first */}
            {opppa && (
                <Card style={{ padding: 18, marginBottom: 16 }}>
                    <div style={{ fontSize: 14, fontWeight: 700, color: t.text, marginBottom: 4 }}>Protect first — register with {opppa.authority}</div>
                    <div style={{ fontSize: 12.5, color: t.textMuted, marginBottom: 10 }}>{opppa.why}</div>
                    <ol style={{ margin: 0, paddingLeft: 20, listStyleType: "decimal", listStylePosition: "outside" }}>
                        {opppa.steps.map((s, i) => <li key={i} style={{ display: "list-item", fontSize: 12.5, color: t.text, marginBottom: 5 }}>{s}</li>)}
                    </ol>
                    <div style={{ fontSize: 11, color: t.textFaint, marginTop: 10 }}>{opppa.legal_basis} · as of {opppa.effective_as_of}. {opppa.verify}</div>
                </Card>
            )}

            <Card style={{ padding: 20 }}>
                <div style={{ fontSize: 15, fontWeight: 700, color: t.text, marginBottom: 4 }}>Special Court for your property dispute</div>
                <div style={{ fontSize: 12.5, color: t.textMuted, marginBottom: 16 }}>The Protection of Overseas Pakistanis' Property Act 2024 sets up dedicated courts with e-filing and video-link hearings. It is rolling out province by province.</div>
                <Lbl>Where is the property</Lbl>
                <select value={province} onChange={e => setProvince(e.target.value)} style={{ ...selectStyle(t), marginBottom: 16 }}>
                    {provinces.map(p => <option key={p.code} value={p.code}>{p.name}</option>)}
                </select>

                {loading && <div style={{ fontSize: 13, color: t.textMuted }}>Resolving…</div>}
                {res && !loading && (
                    <>
                        <div style={{ fontSize: 13, color: t.text, marginBottom: 12 }}>{res.remedy_summary}</div>
                        <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 14, flexWrap: "wrap" }}>
                            <Pill text={(res.court_status || "unknown").replace(/_/g, " ")} color={COURT_COLOR[res.court_status]} t={t} />
                            {res.can_efile_now && <Pill text="e-filing available" color="#10b981" t={t} />}
                            {res.disposal_days && <Pill text={`~${res.disposal_days}-day decision`} color={t.primary} t={t} />}
                            {res.appeal_days && <Pill text={`${res.appeal_days}-day appeal`} color={t.primary} t={t} />}
                        </div>
                        {(res.steps || []).map((s, i) => (
                            <div key={i} style={{ display: "flex", gap: 12, marginBottom: 12 }}>
                                <div style={{ flexShrink: 0, width: 26, height: 26, borderRadius: "50%", background: t.primary + "22", color: t.primary, display: "flex", alignItems: "center", justifyContent: "center", fontWeight: 700, fontSize: 13 }}>{i + 1}</div>
                                <div style={{ fontSize: 13, color: t.text, lineHeight: 1.5, paddingTop: 2 }}>{s}</div>
                            </div>
                        ))}
                        {res.note && <div style={{ fontSize: 12, color: t.textMuted, marginTop: 8 }}>{res.note}</div>}
                        <div style={{ fontSize: 11, color: t.textFaint, marginTop: 12, paddingTop: 12, borderTop: `1px solid ${t.border}` }}>As of {res.effective_as_of}. {res.verify}</div>
                    </>
                )}
            </Card>
        </div>
    );
}

/* ═══════════ TAB 4 — PROPERTY DISPUTE (5a/5b/5c) ═══════════ */
const STEP_LABELS = ["Eligibility", "Your situation", "Details", "Result"];

function DisputeFlow() {
    const t = useT();
    const toast = useToast();
    const [provinces, setProvinces] = useState([]);
    const [disputes, setDisputes] = useState([]);
    const [step, setStep] = useState(0);          // 0..2 wizard, 3 = result
    const [busy, setBusy] = useState(false);
    const [elig, setElig] = useState({ id_type: "nicop", days_abroad: "" });
    const [eligResult, setEligResult] = useState(null);
    const [grievance, setGrievance] = useState("");
    const [classify, setClassify] = useState(null);
    const [intake, setIntake] = useState({
        property_description: "", province: "", khasra_number: "", opposing_party: "",
        opposing_party_relation: "", timeline: "", documents_held: [], relief_wanted: "restore_possession",
    });
    const [result, setResult] = useState(null);
    const [petition, setPetition] = useState(null);
    const [sending, setSending] = useState(false);

    const loadDisputes = async () => { const { data } = await overseasDisputeList(); if (Array.isArray(data)) setDisputes(data); };
    useEffect(() => {
        (async () => {
            const p = await overseasSpecialCourtProvinces();
            const list = (p.data?.provinces || []).filter(x => x.code !== "OTHER");
            setProvinces(list);
            setIntake(i => i.province ? i : { ...i, province: list[0]?.code || "" });
        })();
        loadDisputes();
    }, []);

    const checkElig = async () => {
        const { data } = await overseasDisputeEligibility(elig.id_type, parseInt(elig.days_abroad || "0", 10));
        setEligResult(data);
    };
    const runClassify = async () => {
        if (!grievance.trim()) return toast.show("Describe what has happened", "warn");
        setBusy(true);
        const { data, error } = await overseasDisputeClassify(grievance.trim());
        setBusy(false);
        if (error || !data || data.error) return toast.show(data?.error || "Could not analyse that", "warn");
        setClassify(data);
    };
    const submit = async () => {
        if (!intake.property_description.trim() || !intake.opposing_party.trim() || !intake.timeline.trim())
            return toast.show("Fill the property, the other party, and when it happened", "warn");
        setBusy(true);
        const { data, error } = await overseasDisputeCreate({
            id_type: elig.id_type, days_abroad: parseInt(elig.days_abroad || "0", 10),
            grievance_text: grievance.trim(), intake: { ...intake },
        });
        setBusy(false);
        if (error || !data || data.error) return toast.show(data?.error || error?.detail || "Could not submit", "danger");
        setResult(data); setStep(3); loadDisputes();
    };
    const draftPetition = async () => {
        setBusy(true);
        const { data, error } = await overseasDraftPetition(result.id);
        setBusy(false);
        if (error || !data || data.error) return toast.show(data?.error || error?.detail || "Could not draft", "danger");
        setPetition(data);
        if (data.document_id) await downloadDocument(data.document_id, "special-court-petition");
        toast.show("Draft petition generated", "success");
    };
    const sendToLawyer = async () => {
        if (!result?.id) return;
        setSending(true);
        const { data, error } = await overseasSendDisputeToLawyer(result.id);
        setSending(false);
        if (error || !data || data.error) return toast.show(data?.error || error?.detail || "Could not send to a lawyer", "danger");
        // reflect the sent state locally so the button can't be clicked again
        setResult(r => ({ ...r, assigned_lawyer_id: data.assigned_lawyer?.id, assigned_lawyer: data.assigned_lawyer, sent_to_lawyer_at: data.sent_to_lawyer_at }));
        toast.show(data.already_sent ? `Already with ${data.assigned_lawyer?.name || "a lawyer"}` : `Sent to ${data.assigned_lawyer?.name || "a verified lawyer"}`, "success");
        loadDisputes();
    };
    // Open a prior dispute back into the result view so it can be sent / drafted.
    const openDispute = (d) => { setResult(d); setPetition(null); setStep(3); };
    const restart = () => {
        setStep(0); setEligResult(null); setGrievance(""); setClassify(null); setResult(null); setPetition(null);
        setIntake(i => ({ ...i, property_description: "", opposing_party: "", opposing_party_relation: "", timeline: "", khasra_number: "", documents_held: [] }));
    };
    const toggleDoc = (code) => setIntake(i => ({ ...i, documents_held: i.documents_held.includes(code) ? i.documents_held.filter(d => d !== code) : [...i.documents_held, code] }));
    const iField = (k, ph) => <ThemedInput value={intake[k]} onChange={e => setIntake(i => ({ ...i, [k]: e.target.value }))} placeholder={ph} />;

    // Case-brief handoff — either state can be sent to a lawyer. Once sent, the button
    // is replaced with the sent state (a lawyer already has it; don't re-send).
    const handoffBlock = () => (
        result?.assigned_lawyer_id ? (
            <div style={{ marginTop: 14, padding: "12px 14px", borderRadius: 10, border: `1px solid #3b82f655`, background: "#3b82f610", fontSize: 12.5, color: t.text }}>
                <b style={{ color: "#3b82f6" }}>✓ Sent to {result.assigned_lawyer?.name || "a verified lawyer"}</b>
                {" — they can now open your full case brief"}{result.petition_shared ? " and the draft petition" : ""}. They'll be in touch through the platform.
            </div>
        ) : (
            <div style={{ marginTop: 14 }}>
                <BtnOutline onClick={sendToLawyer} disabled={sending}>{sending ? "Sending…" : "Send my case to a lawyer →"}</BtnOutline>
                <div style={{ fontSize: 11.5, color: t.textMuted, marginTop: 6 }}>
                    Packages everything — your eligibility, the classification, the facts you entered, the court, and the draft petition if there is one — for one verified lawyer to review.
                </div>
            </div>
        )
    );

    return (
        <div style={{ maxWidth: 760 }}>
            <div style={{ fontSize: 12.5, color: t.textMuted, marginBottom: 14 }}>
                Property grabbed, POA misused, or a fraudulent transfer? The Protection of Overseas Pakistanis' Property Act 2024
                gives a fast-track court remedy. Answer a few questions — if it's clear-cut we prepare a draft petition; if it's
                not, we route you to a lawyer rather than guess.
            </div>

            {/* prior disputes */}
            {disputes.length > 0 && step === 0 && (
                <Card style={{ padding: 14, marginBottom: 14 }}>
                    <div style={{ fontSize: 12, fontWeight: 700, color: t.textMuted, marginBottom: 8 }}>YOUR DISPUTES</div>
                    {disputes.map(d => (
                        <div key={d.id} onClick={() => openDispute(d)} title="Open this dispute"
                            onMouseEnter={e => e.currentTarget.style.background = t.primary + "0c"}
                            onMouseLeave={e => e.currentTarget.style.background = "transparent"}
                            style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8, padding: "8px 6px", borderTop: `1px solid ${t.border}`, cursor: "pointer", borderRadius: 6, transition: "background .12s" }}>
                            <span style={{ fontSize: 13, color: t.text }}>{d.intake?.property_description?.slice(0, 40) || "Dispute"}</span>
                            <div style={{ display: "flex", gap: 6, flexShrink: 0, alignItems: "center" }}>
                                {d.assigned_lawyer_id && <Pill text="sent to lawyer" color="#3b82f6" t={t} />}
                                <Pill text={d.state === "ready_for_drafting" ? "ready" : "with a lawyer"} color={d.state === "ready_for_drafting" ? "#10b981" : "#f59e0b"} t={t} />
                                <span style={{ fontSize: 12, fontWeight: 700, color: t.primary }}>Open →</span>
                            </div>
                        </div>
                    ))}
                </Card>
            )}

            {/* stepper */}
            <div style={{ display: "flex", gap: 6, marginBottom: 16, flexWrap: "wrap" }}>
                {STEP_LABELS.map((lbl, i) => (
                    <span key={lbl} style={{ fontSize: 10.5, fontWeight: 700, padding: "4px 10px", borderRadius: 6, background: i <= step ? t.primary + "22" : t.border, color: i <= step ? t.primary : t.textMuted }}>{i + 1}. {lbl}</span>
                ))}
            </div>

            <Card style={{ padding: 18 }}>
                {/* STEP 1 — eligibility */}
                {step === 0 && (
                    <>
                        <Lbl>Your Pakistani identity document</Lbl>
                        <select value={elig.id_type} onChange={e => setElig(s => ({ ...s, id_type: e.target.value }))} style={{ ...selectStyle(t), marginBottom: 12 }}>
                            {ID_TYPES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                        </select>
                        <Lbl>Days spent abroad in this tax year</Lbl>
                        <ThemedInput type="number" value={elig.days_abroad} onChange={e => setElig(s => ({ ...s, days_abroad: e.target.value }))} placeholder="e.g. 300" />
                        <div style={{ marginTop: 12, display: "flex", gap: 8, alignItems: "center" }}>
                            <BtnOutline onClick={checkElig}>Check eligibility</BtnOutline>
                            {eligResult && <span style={{ fontSize: 12.5, color: eligResult.eligible ? "#10b981" : "#f59e0b" }}>
                                {eligResult.eligible ? "✓ You qualify as an overseas Pakistani" : "⚠ " + (eligResult.reasons?.[0] || "May not qualify — a lawyer will confirm")}
                            </span>}
                        </div>
                        <div style={{ marginTop: 16 }}>
                            <BtnPrimary onClick={() => setStep(1)}>Continue</BtnPrimary>
                        </div>
                    </>
                )}

                {/* STEP 2 — grievance + classify */}
                {step === 1 && (
                    <>
                        <Lbl>Describe what has happened to the property</Lbl>
                        <textarea value={grievance} onChange={e => setGrievance(e.target.value)} rows={4}
                            placeholder="e.g. A man with no claim broke the lock and moved into my house in Lahore and refuses to leave."
                            style={{ width: "100%", borderRadius: 10, border: `1.5px solid ${t.border}`, background: t.inputBg, color: t.text, fontSize: 13.5, padding: 10, fontFamily: "inherit", resize: "vertical" }} />
                        <div style={{ marginTop: 10 }}><BtnOutline onClick={runClassify} disabled={busy}>{busy ? "Analysing…" : "Analyse"}</BtnOutline></div>
                        {classify && (
                            <div style={{ marginTop: 12, padding: "12px 14px", borderRadius: 10, border: `1px solid ${(classify.needs_triage ? "#f59e0b" : "#10b981")}55`, background: (classify.needs_triage ? "#f59e0b" : "#10b981") + "10", fontSize: 13, color: t.text }}>
                                {classify.needs_triage ? (
                                    <span><b style={{ color: "#f59e0b" }}>A lawyer should confirm this.</b> {classify.alternatives?.length
                                        ? `From your description this could be ${[classify.category, ...classify.alternatives].map(c => DISPUTE_CAT_LABEL[c] || c).join(" or ")} — which one it is changes the legal claim, so we won't guess.`
                                        : "We couldn't identify the type of dispute confidently from this."}</span>
                                ) : (
                                    <span><b style={{ color: "#10b981" }}>Identified.</b> This looks like {DISPUTE_CAT_LABEL[classify.category] || classify.category}. You can continue.</span>
                                )}
                            </div>
                        )}
                        <div style={{ marginTop: 16, display: "flex", gap: 8 }}>
                            <BtnOutline onClick={() => setStep(0)}>Back</BtnOutline>
                            <BtnPrimary onClick={() => setStep(2)}>Continue</BtnPrimary>
                        </div>
                    </>
                )}

                {/* STEP 3 — guided intake */}
                {step === 2 && (
                    <>
                        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginBottom: 8 }}>
                            {iField("property_description", "The property (e.g. House 5, Model Town, Lahore) *")}
                            <select value={intake.province} onChange={e => setIntake(i => ({ ...i, province: e.target.value }))} style={selectStyle(t)}>
                                {provinces.map(p => <option key={p.code} value={p.code}>{p.name}</option>)}
                            </select>
                            {iField("khasra_number", "Khasra / registry no. (optional)")}
                            {iField("opposing_party", "Who is doing this (name) *")}
                            {iField("opposing_party_relation", "Their relation to you (optional)")}
                            {iField("timeline", "When did it start / key dates *")}
                        </div>
                        <Lbl>Documents you hold</Lbl>
                        <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 12 }}>
                            {DISPUTE_DOCUMENTS.map(([code, label]) => {
                                const on = intake.documents_held.includes(code);
                                return <button key={code} onClick={() => toggleDoc(code)} style={{ fontSize: 12, padding: "6px 10px", borderRadius: 8, cursor: "pointer", fontFamily: "inherit", border: `1px solid ${on ? t.primary : t.border}`, background: on ? t.primary + "18" : "transparent", color: on ? t.primary : t.textMuted }}>{label}</button>;
                            })}
                        </div>
                        <Lbl>What you want the court to do</Lbl>
                        <select value={intake.relief_wanted} onChange={e => setIntake(i => ({ ...i, relief_wanted: e.target.value }))} style={selectStyle(t)}>
                            {DISPUTE_RELIEFS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                        </select>
                        <div style={{ marginTop: 16, display: "flex", gap: 8 }}>
                            <BtnOutline onClick={() => setStep(1)}>Back</BtnOutline>
                            <BtnPrimary onClick={submit} disabled={busy}>{busy ? "Submitting…" : "Submit dispute"}</BtnPrimary>
                        </div>
                    </>
                )}

                {/* RESULT */}
                {step === 3 && result && (
                    result.state === "ready_for_drafting" ? (
                        <>
                            <div style={{ fontSize: 15, fontWeight: 700, color: "#10b981", marginBottom: 4 }}>Ready to draft ✓</div>
                            <div style={{ fontSize: 13, color: t.text, marginBottom: 12 }}>
                                Your dispute qualifies for the {result.jurisdiction?.province} special court. We can prepare a DRAFT petition for a lawyer to review and file.
                            </div>
                            <BtnPrimary onClick={draftPetition} disabled={busy}>{busy ? "Drafting…" : "Draft petition (PDF)"}</BtnPrimary>
                            {petition && (
                                <div style={{ marginTop: 14, padding: "12px 14px", borderRadius: 10, border: `1px solid ${t.border}`, background: t.inputBg }}>
                                    <div style={{ fontSize: 13, fontWeight: 700, color: t.text, marginBottom: 6 }}>{petition.title} — downloaded</div>
                                    <div style={{ fontSize: 11.5, color: t.textMuted }}>{petition.disclaimer}</div>
                                </div>
                            )}
                            {handoffBlock()}
                        </>
                    ) : (
                        <>
                            <div style={{ fontSize: 15, fontWeight: 700, color: "#f59e0b", marginBottom: 4 }}>A lawyer should review this first</div>
                            <div style={{ fontSize: 13, color: t.text, marginBottom: 10 }}>We've held your dispute for a lawyer rather than auto-drafting, because:</div>
                            <ul style={{ margin: "0 0 12px", paddingLeft: 18, listStyleType: "disc" }}>
                                {(result.hold_reasons || []).map((r, i) => <li key={i} style={{ display: "list-item", fontSize: 12.5, color: t.textMuted, marginBottom: 5 }}>{r}</li>)}
                            </ul>
                            <div style={{ fontSize: 12.5, color: t.textMuted, marginBottom: 12 }}>{result.triage_notified_at ? "We've sent you a notification with the next step." : ""}</div>
                            <BtnPrimary onClick={() => { window.location.href = "/lawyers"; }}>Find a verified lawyer →</BtnPrimary>
                            {handoffBlock()}
                        </>
                    )
                )}
            </Card>

            {step === 3 && <div style={{ marginTop: 12 }}><BtnOutline onClick={restart}>Start another dispute</BtnOutline></div>}
        </div>
    );
}

/* ═══════════ SHELL ═══════════ */
const TABS = [
    { id: "poas", label: "My Powers of Attorney", icon: "file" },
    { id: "attest", label: "Attestation Navigator", icon: "map" },
    { id: "court", label: "Special Courts", icon: "shield" },
    { id: "dispute", label: "Property Dispute", icon: "shield" },
];

export default function ModOverseas() {
    const t = useT();
    const [tab, setTab] = useState("poas");
    return (
        <div>
            <div style={{ marginBottom: 8 }}>
                <div style={{ fontSize: 20, fontWeight: 800, color: t.text }}>Overseas Desk</div>
                <div style={{ fontSize: 13, color: t.textMuted, marginTop: 2 }}>Manage your Pakistani property & affairs from abroad — the right POA, verified, and protected.</div>
            </div>
            <div style={{ display: "flex", gap: 8, margin: "16px 0", flexWrap: "wrap" }}>
                {TABS.map(x => (
                    <button key={x.id} onClick={() => setTab(x.id)} style={{
                        display: "flex", alignItems: "center", gap: 8, padding: "9px 16px", borderRadius: 10,
                        border: `1.5px solid ${tab === x.id ? t.primary : t.border}`, background: tab === x.id ? `${t.primary}15` : "transparent",
                        color: tab === x.id ? t.primary : t.textMuted, fontSize: 13, fontWeight: 700, cursor: "pointer", fontFamily: "inherit",
                    }}>
                        <Ic n={x.icon} s={15} c={tab === x.id ? t.primary : t.textMuted} /> {x.label}
                    </button>
                ))}
            </div>
            {tab === "poas" && <MyPoas />}
            {tab === "attest" && <AttestationNavigator />}
            {tab === "court" && <SpecialCourts />}
            {tab === "dispute" && <DisputeFlow />}
        </div>
    );
}
