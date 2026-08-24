'use client';
// Property-dispute intake under the Protection of Overseas Pakistanis' Property
// Act 2024 — eligibility, grievance classification, guided detail capture, then
// a drafted petition or a handoff to a lawyer.
//
// Extracted from the former ModOverseas.jsx on 2026-08-24 when the POA and
// attestation desk was removed. Only the dispute wizard survived that cut; it
// has real usage and 38 backing tests, so it needed a home of its own rather
// than to disappear with the module that happened to contain it.
import React, { useEffect, useRef, useState } from "react";
import { useT } from "./theme.js";
import { useToast } from "@/components/shared/Toast.jsx";
import Ic from "./Ic.jsx";
import { Card, BtnPrimary, BtnOutline, ThemedInput } from "@/components/shared/shared.jsx";
import {
    disputeEligibility, disputeClassify, disputeCreate,
    disputeList, disputeDraftPetition, disputeSendToLawyer,
    disputeSpecialCourtProvinces, downloadDocument,
} from "@/lib/api.js";

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


const STEP_LABELS = ["Eligibility", "Your situation", "Details", "Result"];


export default function ModDisputes() {
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

    const loadDisputes = async () => { const { data } = await disputeList(); if (Array.isArray(data)) setDisputes(data); };
    useEffect(() => {
        (async () => {
            const p = await disputeSpecialCourtProvinces();
            const list = (p.data?.provinces || []).filter(x => x.code !== "OTHER");
            setProvinces(list);
            setIntake(i => i.province ? i : { ...i, province: list[0]?.code || "" });
        })();
        loadDisputes();
    }, []);

    const checkElig = async () => {
        const { data } = await disputeEligibility(elig.id_type, parseInt(elig.days_abroad || "0", 10));
        setEligResult(data);
    };
    const runClassify = async () => {
        if (!grievance.trim()) return toast.show("Describe what has happened", "warn");
        setBusy(true);
        const { data, error } = await disputeClassify(grievance.trim());
        setBusy(false);
        if (error || !data || data.error) return toast.show(data?.error || "Could not analyse that", "warn");
        setClassify(data);
    };
    const submit = async () => {
        if (!intake.property_description.trim() || !intake.opposing_party.trim() || !intake.timeline.trim())
            return toast.show("Fill the property, the other party, and when it happened", "warn");
        setBusy(true);
        const { data, error } = await disputeCreate({
            id_type: elig.id_type, days_abroad: parseInt(elig.days_abroad || "0", 10),
            grievance_text: grievance.trim(), intake: { ...intake },
        });
        setBusy(false);
        if (error || !data || data.error) return toast.show(data?.error || error?.detail || "Could not submit", "danger");
        setResult(data); setStep(3); loadDisputes();
    };
    const draftPetition = async () => {
        setBusy(true);
        const { data, error } = await disputeDraftPetition(result.id);
        setBusy(false);
        if (error || !data || data.error) return toast.show(data?.error || error?.detail || "Could not draft", "danger");
        setPetition(data);
        if (data.document_id) await downloadDocument(data.document_id, "special-court-petition");
        toast.show("Draft petition generated", "success");
    };
    const sendToLawyer = async () => {
        if (!result?.id) return;
        setSending(true);
        const { data, error } = await disputeSendToLawyer(result.id);
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
                        <div className="rgrid-2" style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginBottom: 8 }}>
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
