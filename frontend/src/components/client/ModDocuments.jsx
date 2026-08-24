'use client';
// Paste your ModDocuments.jsx code here
import React, { useState, Fragment, useEffect } from "react";
import { useT, useHeaderActions } from "./theme.js";
import { useToast } from "@/components/shared/Toast.jsx";
import Ic from "./Ic.jsx";
import { Card, BtnPrimary, BtnOutline, ThemedInput, Badge } from "@/components/shared/shared.jsx";
import { useCase } from "./CaseContext.jsx";
import { extractDocumentFields, generateDocument, downloadDocument, submitDocumentForReview, listDocuments, searchLawyers, getCaseTimeline } from "@/lib/api.js";

const STitle = ({ icon, sub, children }) => {
    const t = useT();
    return (
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 16 }}>
            <Ic n={icon} s={18} c={t.primary} />
            <div style={{ fontSize: 15, fontWeight: 700, color: t.text }}>{children}</div>
            {sub && <div style={{ marginLeft: "auto", fontSize: 11, color: t.textMuted }}>{sub}</div>}
        </div>
    );
};

const Lbl = ({ children }) => {
    const t = useT();
    return <div style={{ fontSize: 12, color: t.textMuted, marginBottom: 8, fontWeight: 600, letterSpacing: "0.6px", textTransform: "uppercase" }}>{children}</div>;
};

/* ══════════════════════════════════════════════════════
   MODULE: DOCUMENT AUTOMATION — 5-Step Wizard
══════════════════════════════════════════════════════ */
const DRAFTS_DATA = [
    { name: "Special Power of Attorney", cat: "Civil" },
    { name: "Order I, Rule 10 — Intervenor App.", cat: "Civil" },
    { name: "Joint Venture Agreement", cat: "Corporate" },
    { name: "Condonation Application", cat: "Civil" },
    { name: "Certified Copy Application", cat: "Civil" },
    { name: "Articles of Association — SMC", cat: "Corporate" },
    { name: "Employment Termination Letter", cat: "Employment" },
    { name: "Non-Disclosure Agreement", cat: "Corporate" },
    { name: "Bail Application", cat: "Criminal" },
    { name: "Suit for Recovery of Money", cat: "Civil" },
    { name: "Property Transfer Deed", cat: "Property" },
    { name: "Labour Court Complaint", cat: "Employment" },
];

const DOC_TYPES_DATA = [
    { key: "Plaint", ico: "⚖️", desc: "Civil lawsuit filing", preview: "A formal legal complaint filed in court to initiate a civil lawsuit." },
    { key: "Written Statement", ico: "📝", desc: "Defendant response", preview: "Defendant's formal response to the plaint in court." },
    { key: "Legal Notice", ico: "📮", desc: "Pre-litigation notice", preview: "Formal notice sent before initiating legal proceedings." },
    { key: "Stay Application", ico: "⏸️", desc: "Halt proceedings", preview: "Application to halt court or legal proceedings temporarily." },
    { key: "Settlement Draft", ico: "🤝", desc: "Out-of-court resolution", preview: "Agreement between parties to resolve dispute out of court." },
    { key: "Contract", ico: "📃", desc: "Binding agreement", preview: "Legally binding agreement between two or more parties." },
];

const GEN_STEPS_LABELS = ["Extracting case data…", "Applying AI recommendations…", "Populating template…", "Formatting document…", "Generating draft…"];

const DOC_TYPE_MAP = {
    "Plaint": "plaint_civil",
    "Written Statement": "written_statement",
    "Legal Notice": "legal_notice",
    "Contract": "nda",
    "Settlement Draft": "rental_agreement",
    "Stay Application": null,
};

const EVIDENCE_FILES = [
    { name: "Employment_Contract.pdf", size: "2.4 MB", date: "Feb 10", status: "Processed" },
    { name: "Termination_Letter.pdf", size: "512 KB", date: "Feb 12", status: "Processed" },
    { name: "Pay_Stubs_Dec25.pdf", size: "1.1 MB", date: "Feb 14", status: "Pending" },
    { name: "Offer_Letter_2022.pdf", size: "340 KB", date: "Feb 14", status: "Pending" },
];


const ModDocuments = () => {
    const t = useT();
    const toast = useToast();
    const { cases } = useCase();

    /* ── State ── */
    const [step, setStep] = useState(0);                       // 0–4
    const [selectedDraft, setSelectedDraft] = useState(null);
    const [selectedCaseId, setSelectedCaseId] = useState("");
    const [docId, setDocId] = useState(null);
    const [selectedCat, setSelectedCat] = useState("All");
    const [searchQ, setSearchQ] = useState("");
    const [selectedType, setSelectedType] = useState(null);   // chosen doc type
    const [docTitle, setDocTitle] = useState("");
    const [caseRef, setCaseRef] = useState("");
    const [jurisdiction, setJurisdiction] = useState("Lahore High Court");
    const [language, setLanguage] = useState("English");
    const [instructions, setInstructions] = useState("");
    const [generating, setGenerating] = useState(false);
    const [genPct, setGenPct] = useState(0);
    const [genDone, setGenDone] = useState(false);
    // Statutory completeness of the generated draft, returned by the API.
    const [compliance, setCompliance] = useState(null);
    // Step 3 — review / edit
    const [editMode, setEditMode] = useState(false);
    const [docContent, setDocContent] = useState(null);       // null until generated
    const [userApproved, setUserApproved] = useState(false);
    // Step 4 — lawyer submission (real pipeline: submit → lawyer reviews → notified)
    const [selLawyer, setSelLawyer] = useState(null);         // _id of the chosen lawyer
    const [revLawyers, setRevLawyers] = useState([]);         // verified lawyers from the API
    const [caseLawyerId, setCaseLawyerId] = useState(null);   // assigned lawyer of the linked case, if any
    const [genCaseId, setGenCaseId] = useState(null);         // case the document was generated for
    const [reviewNote, setReviewNote] = useState("");
    const [urgency, setUrgency] = useState("Normal");
    const [reviewSent, setReviewSent] = useState(false);
    const [submitting, setSubmitting] = useState(false);
    const [reviewStatus, setReviewStatus] = useState(null);   // submitted | approved | returned | rejected
    const [lawyerNote, setLawyerNote] = useState("");         // lawyer's note from the review
    const [revLawyerName, setRevLawyerName] = useState("");   // display name of the reviewing lawyer
    // Step 5 — final
    const [exported, setExported] = useState(false);

    /* ── Data ── */
    const STEPS = [
        { label: "Select Template", icon: "📋" },
        { label: "AI Generate Draft", icon: "✨" },
        { label: "Review & Edit", icon: "✏️" },
        { label: "Submit to Lawyer", icon: "⚖️" },
        { label: "Final & Export", icon: "📤" },
    ];
    const categories = ["All", "Civil", "Criminal", "Corporate", "Employment", "Property"];
    const catIcons = { All: "📋", Civil: "⚖️", Criminal: "🔒", Corporate: "🏢", Employment: "💼", Property: "🏠" };
    const statusColors = { Draft: "gray", "Under Review": "warn", Approved: "success", Returned: "warn", Rejected: "danger", Final: "info" };
    const docStatus = genDone
        ? (reviewSent
            ? (reviewStatus === "approved" ? "Final" : reviewStatus === "returned" ? "Returned" : reviewStatus === "rejected" ? "Rejected" : "Under Review")
            : userApproved ? "Approved" : "Draft")
        : "Draft";
    const GEN_STEPS = ["Extracting case data…", "Applying AI recommendations…", "Populating template…", "Formatting document…", "Finalising draft…"];

    // Real verified lawyers for the review step
    useEffect(() => {
        if (step !== 3 || revLawyers.length) return;
        searchLawyers({ page_size: 50 }).then(({ data }) => {
            const items = Array.isArray(data) ? data : (data?.items || []);
            setRevLawyers(items.map(l => ({
                _id: l._id,
                name: l.full_name || "Lawyer",
                spec: ((l.lawyer_profile?.specializations || [])[0] || "General Practice").replace(/_/g, " "),
                rating: l.lawyer_profile?.rating || 0,
                avail: !!l.lawyer_profile?.availability,
                avatar: (l.full_name || "L").split(" ").map(w => w[0]).join("").slice(0, 2).toUpperCase(),
            })));
        }).catch(() => { });
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [step]);

    // If the linked case already has a lawyer, the document goes to them
    useEffect(() => {
        const c = cases.find(x => (x._id || x.id) === genCaseId);
        setCaseLawyerId(c?.lawyer_id || null);
        if (c?.lawyer_id) setSelLawyer(c.lawyer_id);
    }, [genCaseId, cases]);

    // Poll the real review status while waiting for the lawyer
    useEffect(() => {
        if (!reviewSent || !docId || !genCaseId) return;
        if (reviewStatus && reviewStatus !== "submitted") return; // terminal state reached
        const refresh = async () => {
            const { data } = await listDocuments(genCaseId);
            const d = (Array.isArray(data) ? data : []).find(x => x._id === docId);
            if (d?.review_status) {
                setReviewStatus(d.review_status);
                setLawyerNote(d.lawyer_note || "");
            }
        };
        refresh();
        const iv = setInterval(refresh, 12000);
        return () => clearInterval(iv);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [reviewSent, docId, genCaseId, reviewStatus]);

    const submitToLawyer = async () => {
        if (!docId) { toast.show("⚠️ Generate the document first (Step 2)", "warn"); return; }
        if (!selLawyer) { toast.show("⚠️ Select a lawyer first", "warn"); return; }
        setSubmitting(true);
        const { data, error } = await submitDocumentForReview(docId, {
            lawyer_id: selLawyer,
            note: reviewNote.trim() || null,
            urgency: urgency.toLowerCase(),
        });
        setSubmitting(false);
        if (error) {
            toast.show("❌ " + (error.message || "Submission failed"), "danger", 4000);
            return;
        }
        setReviewStatus("submitted");
        setLawyerNote("");
        setRevLawyerName(data?.lawyer_name || revLawyers.find(l => l._id === selLawyer)?.name || "your lawyer");
        setReviewSent(true);
        toast.show(`📤 Submitted — ${data?.lawyer_name || "the lawyer"} has been notified`, "success", 3500);
    };

    const filteredDrafts = DRAFTS_DATA.filter(d =>
        (selectedCat === "All" || d.cat === selectedCat) &&
        d.name.toLowerCase().includes(searchQ.toLowerCase())
    );

    /* ── Helpers ── */
    const catBadgeColor = c => c === "Civil" ? "success" : c === "Criminal" ? "danger" : c === "Employment" ? "warn" : "gray";
    const pillStyle = active => ({
        padding: "7px 15px", borderRadius: 50, fontSize: 12, fontWeight: active ? 700 : 500, cursor: "pointer",
        border: `1.5px solid ${active ? t.primary : t.border}`, background: active ? t.primaryGlow : "transparent",
        color: active ? t.primary : t.textMuted, transition: "all 0.2s", fontFamily: "'Inter',sans-serif",
    });
    const tbBtn = { padding: "5px 10px", borderRadius: 8, border: `1px solid ${t.border}`, background: t.card, color: t.textMuted, fontSize: 12, fontWeight: 600, cursor: "pointer", fontFamily: "'Inter',sans-serif" };

    const goTo = n => setStep(n);
    const nextStep = () => {
        if (step === 0 && selectedDraft === null) {
            toast.show("⚠️ Select a template first", "warn"); return;
        }
        // The final step is only reachable once the lawyer has actually approved
        if (step === 3 && reviewStatus !== "approved") {
            toast.show("⚠️ The final version unlocks after your lawyer approves the document", "warn", 3500); return;
        }
        if (step < STEPS.length - 1) setStep(s => s + 1);
    };
    const prevStep = () => { if (step > 0) setStep(s => s - 1); };

    const pickDraft = i => {
        setSelectedDraft(i);
        if (selectedType) setDocTitle(DRAFTS_DATA[i].name + " — " + selectedType);
    };
    const pickType = key => {
        setSelectedType(key);
        if (selectedDraft !== null) setDocTitle(DRAFTS_DATA[selectedDraft].name + " — " + key);
    };

    // The one fact the whole draft step depends on: is there a case to draft
    // from? handleGenerate resolves the id exactly this way, so the readiness
    // strip and the button can never disagree with what the handler will do.
    const activeCaseId = selectedCaseId || (cases[0]?._id || cases[0]?.id) || "";
    const activeCase = cases.find(c => (c._id || c.id) === activeCaseId);
    const activeCaseTitle = activeCase?.title || activeCase?.case_type || "your case";
    const unsupportedType = Boolean(selectedType && DOC_TYPE_MAP[selectedType] === null);
    const canGenerate = Boolean(activeCaseId) && !unsupportedType;

    const handleGenerate = async () => {
        const templateKey = DOC_TYPE_MAP[selectedType];
        if (selectedType && templateKey === null) {
            toast.show("⚠️ This document type is not yet supported by the AI", "warn"); return;
        }
        const caseId = selectedCaseId || (cases[0]?._id || cases[0]?.id);
        if (!caseId) {
            toast.show("⚠️ No case found — complete your legal intake first", "warn"); return;
        }
        const backendType = templateKey || "plaint_civil";
        setGenerating(true); setGenPct(10); setGenDone(false); setDocId(null);
        setGenCaseId(caseId);
        // A regenerated document restarts the review pipeline
        setReviewSent(false); setReviewStatus(null); setLawyerNote(""); setUserApproved(false);
        try {
            // Phase 1 — AI field extraction
            const extractRes = await extractDocumentFields(caseId, backendType);
            setGenPct(45);
            if (extractRes.error) {
                toast.show("❌ " + (extractRes.error?.detail || "Field extraction failed"), "danger");
                setGenerating(false); return;
            }
            // Phase 2 — PDF generation
            const fields = extractRes.data?.fields || {};
            const genRes = await generateDocument(caseId, backendType, fields);
            setGenPct(90);
            if (genRes.error) {
                toast.show("❌ " + (genRes.error?.detail || "PDF generation failed"), "danger");
                setGenerating(false); return;
            }
            const newDocId = genRes.data?._id || genRes.data?.doc_id;
            setDocId(newDocId);
            if (genRes.data?.title) setDocTitle(genRes.data.title);
            setCompliance(genRes.data?.compliance || null);
            setGenPct(100);
            setTimeout(() => { setGenerating(false); setGenDone(true); toast.show("✅ Draft generated!", "success"); }, 300);
        } catch {
            toast.show("❌ Generation failed — check backend connection", "danger");
            setGenerating(false);
        }
    };

    /* ── Header actions ── */
    const { setHeaderActions } = useHeaderActions();
    useEffect(() => {
        setHeaderActions(
            <>
                {step > 0 && <BtnOutline onClick={prevStep} style={{ fontSize: 11, padding: "7px 14px" }}>← Back</BtnOutline>}
                {step > 0 && step < 4 && <BtnPrimary onClick={nextStep} style={{ fontSize: 11, padding: "7px 18px" }}>Continue →</BtnPrimary>}
            </>
        );
        return () => setHeaderActions(null);
    }, [step, setHeaderActions]);

    /* ── Stepper ── */
    const Stepper = () => (
        <div style={{ display: "flex", alignItems: "center", paddingBottom: 22, flexShrink: 0 }}>
            {STEPS.map((s, i) => {
                const done = i < step, active = i === step;
                return (
                    <Fragment key={s.label}>
                        <div onClick={() => i < step && goTo(i)} style={{ display: "flex", alignItems: "center", gap: 7, cursor: i < step ? "pointer" : "default", padding: "4px 8px", borderRadius: 50 }}>
                            <div style={{
                                width: 28, height: 28, borderRadius: "50%", display: "flex", alignItems: "center", justifyContent: "center",
                                fontSize: done ? 11 : 12, fontWeight: 800, flexShrink: 0, transition: "all 0.25s",
                                background: done ? t.primary : active ? t.primaryGlow : "transparent",
                                color: done ? (t.mode === "dark" ? "#1A2E35" : "#fff") : active ? t.primary : t.textMuted,
                                border: `2px solid ${done ? t.primary : active ? t.primary : t.border}`,
                                boxShadow: active ? `0 0 0 4px ${t.primaryGlow}` : "none",
                            }}>{done ? "✓" : s.icon}</div>
                            <span style={{ fontSize: 12.5, fontWeight: active ? 700 : 500, color: done ? t.primary : active ? t.text : t.textMuted, whiteSpace: "nowrap" }}>{s.label}</span>
                        </div>
                        {i < STEPS.length - 1 && <div style={{ flex: 1, height: 2, background: done ? t.primary : t.border, margin: "0 4px", minWidth: 12, transition: "background 0.4s" }} />}
                    </Fragment>
                );
            })}
        </div>
    );

    /* ── Workflow sidebar — always visible from step 1+ ── */
    const FLOW = [
        { label: "Template Selection", active: step === 0, done: step > 0 },
        { label: "AI Generate Draft", active: step === 1 && !genDone, done: genDone },
        { label: "Draft Status: Created", active: step === 1 && genDone && !userApproved, done: userApproved },
        { label: "User Review", active: step === 2 && !userApproved, done: step > 2 || userApproved },
        { label: "User Edit / Modify", active: step === 2 && editMode, done: step > 2 },
        { label: "Submit to Lawyer", active: step === 3 && !reviewSent, done: reviewSent },
        { label: "Lawyer Review", active: reviewSent && reviewStatus === "submitted", done: reviewSent && reviewStatus !== "submitted" && reviewStatus !== null },
        { label: "Lawyer Decision", active: false, done: ["approved", "returned", "rejected"].includes(reviewStatus) },
        { label: "Final Version", active: reviewStatus === "approved" && !exported, done: exported },
        { label: "Export", active: exported, done: exported },
    ];

    return (
        <div style={{ display: "flex", flexDirection: "column" }}>
            <Stepper />

            <div style={{ flex: 1, overflow: "auto", paddingBottom: 8 }} className="aFadeUp" key={step}>

                {/* ════════════════════════════════════════════════
            STEP 1 — Template Selection (full width)
        ════════════════════════════════════════════════ */}
                {step === 0 && (
                    <div>
                        {/* Stats bar */}
                        <div className="rgrid-2" style={{ display: "grid", gridTemplateColumns: "repeat(2,1fr)", gap: 10, marginBottom: 14 }}>
                            {[["Templates", String(DRAFTS_DATA.length), "📄", t.primary], ["Categories", String(new Set(DRAFTS_DATA.map(d => d.cat)).size), "📁", t.success]].map(([label, val, ico, col]) => (
                                <div key={label} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "14px 18px", borderRadius: 14, background: t.card, border: `1px solid ${t.border}` }}>
                                    <div>
                                        <div style={{ fontSize: 11, color: t.textMuted, marginBottom: 4 }}>{label}</div>
                                        <div style={{ fontSize: 22, fontWeight: 800, color: t.text, fontFamily: "'Playfair Display',serif" }}>{val}</div>
                                    </div>
                                    <div style={{ width: 40, height: 40, borderRadius: 12, background: `${col}18`, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 20 }}>{ico}</div>
                                </div>
                            ))}
                        </div>

                        {/* Filters + search row */}
                        <div style={{ display: "flex", gap: 7, marginBottom: 14, alignItems: "center", flexWrap: "wrap" }}>
                            {categories.map(c => (
                                <button key={c} onClick={() => setSelectedCat(c)} style={pillStyle(selectedCat === c)}>{catIcons[c]} {c}</button>
                            ))}
                            <div style={{ flex: 1, minWidth: 200, display: "flex", alignItems: "center", gap: 9, padding: "8px 14px", borderRadius: 12, border: `1.5px solid ${t.border}`, background: t.card }}>
                                <Ic n="search" s={14} c={t.textMuted} />
                                <input value={searchQ} onChange={e => setSearchQ(e.target.value)} placeholder="Search legal drafts…" style={{ flex: 1, background: "transparent", border: "none", outline: "none", fontFamily: "'Inter',sans-serif", fontSize: 12.5, color: t.text }} />
                            </div>
                        </div>

                        {/* Template grid — 3 columns, full width */}
                        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: 14 }}>
                            {filteredDrafts.length ? filteredDrafts.map(d => {
                                const gi = DRAFTS_DATA.indexOf(d);
                                const sel = selectedDraft === gi;
                                return (
                                    <div key={gi} onClick={() => pickDraft(gi)} style={{ background: sel ? t.primaryGlow : t.card, border: `2px solid ${sel ? t.primary : t.border}`, borderRadius: 18, padding: 18, cursor: "pointer", transition: "all 0.2s", position: "relative", display: "flex", flexDirection: "column", minHeight: 200, boxShadow: sel ? `0 0 0 1px ${t.primary}, ${t.shadowCard}` : t.shadowCard }}
                                        onMouseEnter={e => { if (!sel) { e.currentTarget.style.borderColor = t.primary + "60"; e.currentTarget.style.background = t.primaryGlow + "50"; } }}
                                        onMouseLeave={e => { if (!sel) { e.currentTarget.style.borderColor = t.border; e.currentTarget.style.background = t.card; } }}
                                    >
                                        {/* Selected badge */}
                                        {sel && <div style={{ position: "absolute", top: 12, left: 12, width: 22, height: 22, borderRadius: "50%", background: t.primary, color: t.mode === "dark" ? "#1A2E35" : "#fff", fontSize: 10, fontWeight: 800, display: "flex", alignItems: "center", justifyContent: "center", boxShadow: `0 2px 8px ${t.primaryGlow}` }}>✓</div>}
                                        {/* PDF badge */}
                                        <div style={{ position: "absolute", top: 12, right: 12 }}><Badge type="gray">PDF</Badge></div>
                                        {/* Icon */}
                                        <div style={{ width: 46, height: 46, borderRadius: 12, background: sel ? `${t.primary}25` : `${t.danger}12`, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 22, marginBottom: 10, marginTop: 4 }}>{sel ? "📗" : "📕"}</div>
                                        {/* Category */}
                                        <Badge type={catBadgeColor(d.cat)} style={{ marginBottom: 7, alignSelf: "flex-start", fontSize: 10 }}>{d.cat}</Badge>
                                        {/* Name */}
                                        <div style={{ fontSize: 13, fontWeight: 700, color: sel ? t.primary : t.text, lineHeight: 1.35, marginBottom: 6, flex: 1 }}>{d.name}</div>
                                        {/* Action */}
                                        <div style={{ display: "flex", gap: 7 }}>
                                            <button onClick={e => { e.stopPropagation(); sel ? nextStep() : pickDraft(gi); }} style={{ flex: 1, padding: "7px", borderRadius: 10, border: `1.5px solid ${sel ? t.primary : t.border}`, background: sel ? t.primary : t.card, color: sel ? (t.mode === "dark" ? "#1A2E35" : "#fff") : t.textMuted, fontSize: 11, fontWeight: 600, cursor: "pointer", fontFamily: "'Inter',sans-serif", transition: "all 0.2s" }}>{sel ? "✓ Use Template" : "Select"}</button>
                                        </div>
                                    </div>
                                );
                            }) : <div style={{ gridColumn: "span 3", textAlign: "center", padding: 48, color: t.textMuted, fontSize: 13 }}>No templates found.</div>}
                        </div>

                        {/* Bottom CTA bar — shows when template selected */}
                        {selectedDraft !== null && (
                            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "14px 20px", marginTop: 16, borderRadius: 14, background: t.primaryGlow, border: `1.5px solid ${t.primary}` }}>
                                <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                                    <div style={{ width: 34, height: 34, borderRadius: 9, background: t.primary, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 16 }}>📗</div>
                                    <div>
                                        <div style={{ fontSize: 12, fontWeight: 700, color: t.text }}>{DRAFTS_DATA[selectedDraft].name}</div>
                                        <div style={{ fontSize: 10, color: t.textMuted }}>Template selected · Ready to proceed</div>
                                    </div>
                                </div>
                                <BtnPrimary onClick={nextStep} style={{ fontSize: 12, padding: "10px 22px", borderRadius: 12, boxShadow: `0 4px 16px ${t.primaryGlow}` }}>
                                    Continue to AI Generation →
                                </BtnPrimary>
                            </div>
                        )}
                    </div>
                )}

                {/* ════════════════════════════════════════════════
            STEP 2 — AI Generate Draft
        ════════════════════════════════════════════════ */}
                {step === 1 && (
                    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>

                        {/* Doc identity */}
                        <Card>
                            <STitle icon="sparkle" sub="Configure your document before AI drafting">Generation Settings</STitle>
                            <div style={{ display: "flex", flexDirection: "column", gap: 11 }}>
                                <div><Lbl>Document Title</Lbl><ThemedInput value={docTitle} onChange={e => setDocTitle(e.target.value)} placeholder={`${selectedDraft !== null ? DRAFTS_DATA[selectedDraft].name : "Employment Dispute"} — ${selectedType || "Plaint"}`} /></div>
                                {cases.length > 0 && (
                                    <div>
                                        <Lbl>Linked Case</Lbl>
                                        <select value={selectedCaseId} onChange={e => setSelectedCaseId(e.target.value)} style={{ background: t.inputBg, border: `1.5px solid ${t.border}`, color: t.text, borderRadius: 12, padding: "11px 13px", width: "100%", outline: "none", fontSize: 12.5, fontFamily: "'Inter',sans-serif" }}>
                                            <option value="">Select a case…</option>
                                            {cases.map(c => <option key={c._id || c.id} value={c._id || c.id}>{c.title || c.case_type || (c._id || c.id)}</option>)}
                                        </select>
                                    </div>
                                )}
                                <div><Lbl>Case Reference No.</Lbl><ThemedInput value={caseRef} onChange={e => setCaseRef(e.target.value)} placeholder="e.g. CASE-2026-00142" /></div>
                                <div className="rgrid-2" style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
                                    <div><Lbl>Jurisdiction</Lbl>
                                        <select value={jurisdiction} onChange={e => setJurisdiction(e.target.value)} style={{ background: t.inputBg, border: `1.5px solid ${t.border}`, color: t.text, borderRadius: 12, padding: "11px 13px", width: "100%", outline: "none", fontSize: 12.5 }}>
                                            <option>Lahore High Court</option><option>Islamabad High Court</option><option>Sindh High Court</option><option>Supreme Court</option>
                                        </select>
                                    </div>
                                    <div><Lbl>Language</Lbl>
                                        <select value={language} onChange={e => setLanguage(e.target.value)} style={{ background: t.inputBg, border: `1.5px solid ${t.border}`, color: t.text, borderRadius: 12, padding: "11px 13px", width: "100%", outline: "none", fontSize: 12.5 }}>
                                            <option>English</option><option>Urdu</option><option>Both</option>
                                        </select>
                                    </div>
                                </div>
                                <div><Lbl>Special Instructions</Lbl>
                                    <textarea value={instructions} onChange={e => setInstructions(e.target.value)} placeholder="e.g. Emphasise wrongful termination, cite Labour Act 1934, include salary dues…" rows={3} style={{ background: t.inputBg, border: `1.5px solid ${t.border}`, color: t.text, borderRadius: 12, padding: "11px 13px", width: "100%", outline: "none", fontSize: 12.5, resize: "vertical", fontFamily: "'Inter',sans-serif", lineHeight: 1.6, boxSizing: "border-box" }} />
                                </div>
                            </div>

                            {/* Readiness strip — reflects real state.
                                This used to be hardcoded to "Case data extracted · AI
                                recommendations ready / ✓ Ready" regardless of whether a
                                case existed. It told users everything was ready, they
                                pressed Generate, and handleGenerate bailed before making
                                any request because there was no case to generate from.
                                A panel that asserts state it never checks turns a working
                                feature into a dead button. */}
                            <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "10px 13px", borderRadius: 10, background: canGenerate ? t.primaryGlow : t.inputBg, border: `1px solid ${canGenerate ? t.primary + "30" : t.border}`, marginTop: 12 }}>
                                <div style={{ width: 8, height: 8, borderRadius: "50%", background: canGenerate ? t.success : t.warn, flexShrink: 0 }} />
                                <span style={{ fontSize: 11.5, color: t.textMuted, flex: 1 }}>
                                    {canGenerate
                                        ? `Linked to "${activeCaseTitle}" · ready to draft`
                                        : "No case linked yet — complete your Legal Intake first, then come back to draft a document."}
                                </span>
                                <Badge type={canGenerate ? "success" : "warn"}>{canGenerate ? "✓ Ready" : "Not ready"}</Badge>
                            </div>

                            {/* Progress bar */}
                            {(generating || genDone) && (
                                <div style={{ marginTop: 12 }}>
                                    <div style={{ height: 6, borderRadius: 6, background: t.inputBg, overflow: "hidden", marginBottom: 6 }}>
                                        <div style={{ height: "100%", background: t.grad1, borderRadius: 6, width: `${genPct}%`, transition: "width 0.4s ease" }} />
                                    </div>
                                    <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, color: t.textMuted }}>
                                        <span>{genDone ? "✅ Draft created successfully" : GEN_STEPS[Math.min(Math.floor(genPct / 20), 4)]}</span>
                                        <span>{genPct}%</span>
                                    </div>
                                </div>
                            )}

                            {/* What the Code requires, and what this draft is missing.
                                Deterministic and cited — Order VII Rule 1 CPC lists the
                                particulars a plaint must contain, and Order VI Rule 3
                                makes the Appendix A forms mandatory. Advisory: it reports,
                                it does not block. */}
                            {genDone && compliance?.checked && (
                                <div style={{ marginTop: 13, padding: 13, borderRadius: 11,
                                    background: compliance.complete ? `${t.success}12` : `${t.warn}12`,
                                    border: `1.5px solid ${compliance.complete ? t.success : t.warn}45` }}>
                                    <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 7 }}>
                                        <span style={{ fontSize: 12.5, fontWeight: 700, color: compliance.complete ? t.success : t.warn }}>
                                            {compliance.complete
                                                ? "✓ Contains every particular the Code requires"
                                                : `${compliance.missing} required particular${compliance.missing === 1 ? "" : "s"} missing`}
                                        </span>
                                    </div>
                                    <div style={{ fontSize: 10.5, color: t.textMuted, marginBottom: compliance.complete ? 0 : 9 }}>
                                        Checked against {compliance.basis}
                                    </div>
                                    {compliance.items.filter(i => i.status === "missing").map(i => (
                                        <div key={i.clause} style={{ marginBottom: 8, paddingLeft: 10, borderLeft: `2px solid ${t.warn}55` }}>
                                            <div style={{ fontSize: 11.5, color: t.text, fontWeight: 600 }}>
                                                {i.clause} — {i.requirement}
                                            </div>
                                            <div style={{ fontSize: 11, color: t.textMuted, marginTop: 2 }}>{i.hint}</div>
                                        </div>
                                    ))}
                                    <div style={{ fontSize: 10, color: t.textMuted, marginTop: 6, fontStyle: "italic" }}>
                                        {compliance.advisory}
                                    </div>
                                </div>
                            )}

                            {!genDone ? (
                                <BtnPrimary onClick={handleGenerate} disabled={generating || !canGenerate} style={{ width: "100%", marginTop: 13, fontSize: 13, padding: "13px", borderRadius: 12, justifyContent: "center" }}>
                                    {generating
                                        ? "⏳ Generating…"
                                        : !activeCaseId
                                            ? "Link a case to generate"
                                            : unsupportedType
                                                ? `${selectedType} isn't supported yet`
                                                : "✨ Generate Draft"}
                                </BtnPrimary>
                            ) : (
                                <div style={{ display: "flex", gap: 8, marginTop: 13 }}>
                                    <BtnOutline onClick={() => { setGenDone(false); setGenPct(0); }} style={{ flex: 1, fontSize: 11, padding: "11px", borderRadius: 12 }}>🔄 Regenerate</BtnOutline>
                                    <BtnPrimary onClick={() => { goTo(2); }} style={{ flex: 2, fontSize: 12, padding: "11px", borderRadius: 12, justifyContent: "center" }}>Review Draft →</BtnPrimary>
                                </div>
                            )}
                        </Card>

                    </div>
                )}

                {/* ════════════════════════════════════════════════
            STEP 3 — User Review & Edit
        ════════════════════════════════════════════════ */}
                {step === 2 && (
                    <div className="rgrid" style={{ display: "grid", gridTemplateColumns: "1fr 280px", gap: 18 }}>

                        {/* Left: editable document */}
                        <Card style={{ display: "flex", flexDirection: "column", minHeight: 540 }}>
                            <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 14 }}>
                                <div style={{ width: 36, height: 36, borderRadius: 10, background: t.primaryGlow, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 16, flexShrink: 0 }}>📄</div>
                                <div style={{ flex: 1 }}>
                                    <div style={{ fontWeight: 700, color: t.text, fontSize: 14 }}>{docTitle || "Generated Document"}</div>
                                    <div style={{ fontSize: 11, color: t.textMuted }}>{selectedType} · {caseRef || "No ref"}</div>
                                </div>
                                <Badge type={statusColors[docStatus]}>{docStatus}</Badge>
                                <button onClick={() => setEditMode(m => !m)} style={{ padding: "6px 13px", borderRadius: 10, border: `1.5px solid ${editMode ? t.primary : t.border}`, background: editMode ? t.primaryGlow : t.card, color: editMode ? t.primary : t.textMuted, fontSize: 11, fontWeight: 700, cursor: "pointer", transition: "all 0.2s" }}>
                                    {editMode ? "✏️ Editing" : "✏️ Edit"}
                                </button>
                            </div>

                            {/* Formatting toolbar — only in edit mode */}
                            {editMode && (
                                <div style={{ display: "flex", alignItems: "center", gap: 4, padding: "8px 12px", borderBottom: `1px solid ${t.border}`, background: t.inputBg, flexWrap: "wrap", flexShrink: 0, borderRadius: "10px 10px 0 0", marginBottom: 0 }}>
                                    <span style={{ fontSize: 10, fontWeight: 700, color: t.textMuted, marginRight: 4 }}>FORMAT:</span>
                                    {[["B", "bold"], ["I", "italic"], ["U", "underline"]].map(([label, cmd]) => (
                                        <button key={cmd} onClick={() => { try { document.execCommand(cmd); } catch (e) { } }} style={tbBtn}>{label}</button>
                                    ))}
                                    <div style={{ width: 1, height: 16, background: t.border, margin: "0 4px" }} />
                                    {[["≡L", "justifyLeft"], ["≡C", "justifyCenter"]].map(([label, cmd]) => (
                                        <button key={cmd} onClick={() => { try { document.execCommand(cmd); } catch (e) { } }} style={tbBtn}>{label}</button>
                                    ))}
                                    <div style={{ width: 1, height: 16, background: t.border, margin: "0 4px" }} />
                                </div>
                            )}

                            <div style={{ flex: 1, border: `1.5px solid ${editMode ? t.primary : t.border}`, borderRadius: editMode ? "0 0 12px 12px" : 12, overflow: "hidden", transition: "border-color 0.2s" }}>
                                <div contentEditable={editMode} suppressContentEditableWarning style={{ padding: "20px 24px", fontSize: 13, lineHeight: 2.1, color: t.text, minHeight: 380, outline: "none", fontFamily: "Georgia,serif", background: editMode ? t.inputBg : t.card, cursor: editMode ? "text" : "default", overflowY: "auto" }}>
                                    <p style={{ textAlign: "center", fontWeight: 700, fontSize: 15, marginBottom: 8 }}>IN THE COURT OF CIVIL JUDGE, LAHORE</p>
                                    <p style={{ textAlign: "center", fontSize: 12, color: t.textMuted, marginBottom: 16 }}>Employment Dispute — {selectedType || "Plaint"} No. ___/2026</p>
                                    <p style={{ marginBottom: 8 }}><strong>Plaintiff:</strong> M. Usama, S/O [Father Name], CNIC [__________], R/O [Address], Rawalpindi.</p>
                                    <p style={{ marginBottom: 14 }}><strong>Defendant:</strong> XYZ Corporation (Pvt.) Ltd., [Registered Address], Islamabad.</p>
                                    <p style={{ marginBottom: 10 }}><strong>PLAINT UNDER ORDER VII RULE 1 CPC</strong></p>
                                    <p style={{ marginBottom: 8 }}>1. That the plaintiff was employed with the defendant company as [Designation] since [Date], vide Employment Contract dated [__________].</p>
                                    <p style={{ marginBottom: 8 }}>2. That on February 12, 2026, the defendant unlawfully terminated the plaintiff's services without lawful cause and without serving the required notice period.</p>
                                    <p style={{ marginBottom: 8 }}>3. That the plaintiff is entitled to receive salary in lieu of notice period, unpaid dues, and compensation for wrongful termination.</p>
                                    {editMode && <p style={{ marginBottom: 14, fontStyle: "italic", color: t.textMuted }}><em>[Editing enabled — click to modify any text above…]</em></p>}
                                    <p style={{ marginBottom: 6 }}><strong>PRAYER:</strong></p>
                                    <p>The plaintiff respectfully prays that this Honourable Court may be pleased to award PKR 500,000 as compensation together with costs of the suit.</p>
                                </div>
                            </div>

                            <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
                                <BtnOutline onClick={() => { if (docId) { downloadDocument(docId, docTitle || "document"); } else { toast.show("⚠️ Generate the document first", "warn"); } }} style={{ flex: 1, fontSize: 11, padding: "9px", borderRadius: 10 }}>📥 Download</BtnOutline>
                            </div>
                        </Card>

                        {/* Right: review controls + workflow */}
                        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>

                            {/* Compliance */}
                            <Card>
                                <STitle icon="check" sub="Automated checks">Legal Compliance</STitle>
                                {[["Legal Compliance", "success", "✓ Verified"], ["Case Details", "success", "✓ Verified"], ["Factual Info", "warn", "⚠ Review"], ["Format", "success", "✓ Passed"]].map(([lbl, type, s]) => (
                                    <div key={lbl} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "8px 10px", borderRadius: 9, background: t.inputBg, border: `1px solid ${t.border}`, marginBottom: 6 }}>
                                        <span style={{ fontSize: 11.5, color: t.text }}>{lbl}</span>
                                        <Badge type={type}>{s}</Badge>
                                    </div>
                                ))}
                            </Card>

                            {/* User review decision */}
                            <Card>
                                <STitle icon="eye" sub="Your review decision">User Review</STitle>
                                <div style={{ padding: "10px 12px", borderRadius: 10, background: userApproved ? `${t.success}12` : t.inputBg, border: `1.5px solid ${userApproved ? t.success : t.border}`, marginBottom: 10, textAlign: "center" }}>
                                    <div style={{ fontSize: 18, marginBottom: 4 }}>{userApproved ? "✅" : "👀"}</div>
                                    <div style={{ fontSize: 12, fontWeight: 600, color: userApproved ? t.success : t.text }}>{userApproved ? "Approved by you" : "Awaiting your review"}</div>
                                    <div style={{ fontSize: 10, color: t.textMuted, marginTop: 2 }}>{userApproved ? "Ready to submit to lawyer" : "Review the document and approve or edit"}</div>
                                </div>
                                {!userApproved ? (
                                    <div style={{ display: "flex", flexDirection: "column", gap: 7 }}>
                                        <BtnPrimary onClick={() => { setUserApproved(true); toast.show("Marked as approved by you. Send it to a lawyer for their review.", "success", 4000); }} style={{ width: "100%", fontSize: 12, padding: "10px", borderRadius: 10, justifyContent: "center" }}>✅ Approve Draft</BtnPrimary>
                                        <BtnOutline onClick={() => { setEditMode(true); toast.show("✏️ Edit mode enabled", "info"); }} style={{ width: "100%", fontSize: 12, padding: "10px", borderRadius: 10 }}>✏️ Edit / Modify</BtnOutline>
                                    </div>
                                ) : (
                                    <BtnPrimary onClick={() => goTo(3)} style={{ width: "100%", fontSize: 12, padding: "11px", borderRadius: 10, justifyContent: "center", boxShadow: `0 4px 16px ${t.primaryGlow}` }}>
                                        ⚖️ Submit to Lawyer →
                                    </BtnPrimary>
                                )}
                            </Card>


                        </div>
                    </div>
                )}

                {/* ════════════════════════════════════════════════
            STEP 4 — Submit to Lawyer → Lawyer Review
        ════════════════════════════════════════════════ */}
                {step === 3 && !reviewSent && (
                    <div className="rgrid" style={{ display: "grid", gridTemplateColumns: "1fr 300px", gap: 18 }}>

                        {/* Left: lawyer selection */}
                        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
                            {/* Doc strip */}
                            <div style={{ display: "flex", alignItems: "center", gap: 13, padding: "13px 18px", borderRadius: 14, background: `linear-gradient(135deg,${t.primaryGlow},${t.card})`, border: `1px solid ${t.primary}30` }}>
                                <div style={{ width: 38, height: 46, borderRadius: 8, background: t.card, border: `1.5px solid ${t.primary}40`, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 18, flexShrink: 0 }}>📄</div>
                                <div style={{ flex: 1, minWidth: 0 }}>
                                    <div style={{ fontSize: 13, fontWeight: 700, color: t.text, marginBottom: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{docTitle || "Employment Dispute"}</div>
                                    <div style={{ fontSize: 11, color: t.textMuted }}>{selectedType} · {caseRef || "No ref"}</div>
                                </div>
                                <Badge type="success">✓ User Approved</Badge>
                            </div>

                            <Card>
                                <STitle icon="scale" sub={caseLawyerId ? "Your case lawyer will review this document" : "Select a verified lawyer to review your document"}>Choose Lawyer</STitle>
                                <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                                    {caseLawyerId && (
                                        <div style={{ fontSize: 11.5, color: t.textMuted, padding: "8px 12px", borderRadius: 10, background: t.primaryGlow, border: `1px solid ${t.primary}30`, lineHeight: 1.55 }}>
                                            This case already has an engaged lawyer — documents for it are reviewed by them.
                                        </div>
                                    )}
                                    {(caseLawyerId ? revLawyers.filter(l => l._id === caseLawyerId) : revLawyers).map(l => (
                                        <div key={l._id} onClick={() => setSelLawyer(l._id)} style={{ display: "flex", alignItems: "center", gap: 13, padding: "13px 15px", borderRadius: 13, border: `2px solid ${selLawyer === l._id ? t.primary : t.border}`, background: selLawyer === l._id ? t.primaryGlow : t.inputBg, cursor: "pointer", transition: "all 0.2s", position: "relative" }}>
                                            <div style={{ width: 44, height: 44, borderRadius: "50%", background: selLawyer === l._id ? t.primary : `${t.primary}18`, border: `2px solid ${selLawyer === l._id ? t.primary : t.border}`, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 13, fontWeight: 800, color: selLawyer === l._id ? (t.mode === "dark" ? "#1A2E35" : "#fff") : t.primary, flexShrink: 0, transition: "all 0.2s" }}>{l.avatar}</div>
                                            <div style={{ flex: 1, minWidth: 0 }}>
                                                <div style={{ fontSize: 13, fontWeight: 700, color: t.text, marginBottom: 3 }}>{l.name}</div>
                                                <div style={{ fontSize: 11, color: t.textMuted, marginBottom: 4, textTransform: "capitalize" }}>{l.spec}</div>
                                                <div style={{ display: "flex", gap: 10, fontSize: 11 }}>
                                                    {l.rating > 0 && <span style={{ color: t.warn }}>⭐ {l.rating}</span>}
                                                    <span style={{ color: l.avail ? t.success : t.textMuted }}>{l.avail ? "● Available" : "○ Busy"}</span>
                                                </div>
                                            </div>
                                            {selLawyer === l._id && <div style={{ position: "absolute", top: 8, right: 8, width: 20, height: 20, borderRadius: "50%", background: t.primary, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 10, fontWeight: 800, color: t.mode === "dark" ? "#1A2E35" : "#fff" }}>✓</div>}
                                        </div>
                                    ))}
                                    {caseLawyerId && !revLawyers.some(l => l._id === caseLawyerId) && (
                                        <div style={{ display: "flex", alignItems: "center", gap: 13, padding: "13px 15px", borderRadius: 13, border: `2px solid ${t.primary}`, background: t.primaryGlow }}>
                                            <div style={{ width: 44, height: 44, borderRadius: "50%", background: t.primary, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 13, fontWeight: 800, color: t.mode === "dark" ? "#1A2E35" : "#fff", flexShrink: 0 }}>⚖️</div>
                                            <div style={{ fontSize: 13, fontWeight: 700, color: t.text }}>Your engaged case lawyer</div>
                                        </div>
                                    )}
                                    {!caseLawyerId && !revLawyers.length && (
                                        <div style={{ fontSize: 12, color: t.textMuted, textAlign: "center", padding: "18px 0" }}>Loading verified lawyers…</div>
                                    )}
                                </div>
                            </Card>

                            <Card>
                                <STitle icon="edit" sub="Optional notes for the reviewer">Note to Lawyer</STitle>
                                <textarea value={reviewNote} onChange={e => setReviewNote(e.target.value)} placeholder="e.g. Please check wrongful termination clauses, verify PKR 500,000 compensation, confirm notice period…" rows={3} style={{ width: "100%", background: t.inputBg, border: `1.5px solid ${t.border}`, color: t.text, borderRadius: 11, padding: "11px 13px", fontSize: 12.5, outline: "none", resize: "vertical", fontFamily: "'Inter',sans-serif", lineHeight: 1.65, boxSizing: "border-box" }} onFocus={e => e.target.style.borderColor = t.primary} onBlur={e => e.target.style.borderColor = t.border} />
                            </Card>
                        </div>

                        {/* Right: config + send */}
                        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>

                            {/* Selected lawyer preview */}
                            <Card style={{ minHeight: 90, display: "flex", alignItems: !selLawyer ? "center" : "flex-start" }}>
                                {!selLawyer ? (
                                    <div style={{ textAlign: "center", color: t.textMuted, fontSize: 12, width: "100%" }}><div style={{ fontSize: 24, marginBottom: 5 }}>👤</div>Select a lawyer</div>
                                ) : (() => {
                                    const l = revLawyers.find(x => x._id === selLawyer);
                                    return (
                                        <div style={{ width: "100%" }}>
                                            <div style={{ fontSize: 10, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.8px", color: t.textMuted, marginBottom: 8 }}>Reviewing Lawyer</div>
                                            <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "9px 11px", borderRadius: 11, background: t.primaryGlow, border: `1px solid ${t.primary}40` }}>
                                                <div style={{ width: 34, height: 34, borderRadius: "50%", background: t.primary, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 12, fontWeight: 800, color: t.mode === "dark" ? "#1A2E35" : "#fff", flexShrink: 0 }}>{l?.avatar || "⚖️"}</div>
                                                <div>
                                                    <div style={{ fontSize: 12, fontWeight: 700, color: t.text }}>{l?.name || "Your case lawyer"}</div>
                                                    <div style={{ fontSize: 10, color: t.primary, textTransform: "capitalize" }}>{l?.spec || (caseLawyerId ? "Engaged on this case" : "")}</div>
                                                </div>
                                            </div>
                                        </div>
                                    );
                                })()}
                            </Card>

                            {/* Urgency — tells the lawyer how quickly you need this back */}
                            <Card>
                                <STitle icon="clock" sub="How urgent is this review?">Urgency</STitle>
                                {[["Normal", "No rush", t.success], ["Priority", "Needed soon", t.warn], ["Urgent", "Time-critical", t.danger]].map(([lvl, desc, col]) => (
                                    <div key={lvl} onClick={() => setUrgency(lvl)} style={{ display: "flex", alignItems: "center", gap: 10, padding: "10px 12px", borderRadius: 10, border: `1.5px solid ${urgency === lvl ? col : t.border}`, background: urgency === lvl ? `${col}10` : t.inputBg, cursor: "pointer", marginBottom: 7, transition: "all 0.2s" }}>
                                        <div style={{ width: 13, height: 13, borderRadius: "50%", border: `2px solid ${urgency === lvl ? col : t.border}`, background: urgency === lvl ? col : "transparent", flexShrink: 0 }} />
                                        <div style={{ flex: 1 }}>
                                            <div style={{ fontSize: 12, fontWeight: urgency === lvl ? 700 : 500, color: urgency === lvl ? col : t.text }}>{lvl}</div>
                                            <div style={{ fontSize: 10, color: t.textFaint }}>{desc}</div>
                                        </div>
                                    </div>
                                ))}
                            </Card>

                            <BtnPrimary onClick={submitToLawyer} disabled={submitting} style={{ width: "100%", fontSize: 13, padding: "14px", borderRadius: 12, justifyContent: "center", boxShadow: `0 6px 20px ${t.primaryGlow}`, opacity: !selLawyer || submitting ? 0.6 : 1 }}>
                                {submitting ? "⏳ Submitting…" : "📤 Submit to Lawyer"}
                            </BtnPrimary>
                            <div style={{ fontSize: 11, color: t.textMuted, lineHeight: 1.6, textAlign: "center" }}>
                                The lawyer is notified immediately and you'll get a notification when they respond.
                            </div>
                        </div>
                    </div>
                )}

                {/* ── Lawyer Review in Progress ── */}
                {step === 3 && reviewSent && (
                    <div className="rgrid" style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 18 }}>

                        {/* Left: live tracking */}
                        <Card>
                            <div style={{ textAlign: "center", padding: "18px 0 16px", borderBottom: `1px solid ${t.border}`, marginBottom: 16 }}>
                                <div style={{ width: 60, height: 60, borderRadius: "50%", background: t.primaryGlow, border: `2px solid ${t.primary}40`, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 26, margin: "0 auto 12px" }}>📬</div>
                                <div style={{ fontSize: 16, fontWeight: 800, color: t.text, fontFamily: "'Playfair Display',serif", marginBottom: 5 }}>Submitted for Legal Review</div>
                                <div style={{ display: "inline-flex", alignItems: "center", gap: 8, marginTop: 6, padding: "7px 14px", borderRadius: 50, background: t.primaryGlow, border: `1px solid ${t.primary}40` }}>
                                    <div style={{ width: 24, height: 24, borderRadius: "50%", background: t.primary, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 10, fontWeight: 800, color: t.mode === "dark" ? "#1A2E35" : "#fff" }}>⚖️</div>
                                    <span style={{ fontSize: 13, fontWeight: 700, color: t.primary }}>{revLawyerName}</span>
                                </div>
                            </div>

                            <div style={{ fontSize: 10, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.8px", color: t.textMuted, marginBottom: 14 }}>Review Progress</div>
                            <div style={{ position: "relative" }}>
                                <div style={{ position: "absolute", left: 13, top: 26, bottom: 26, width: 2, background: `linear-gradient(${t.primary}, ${t.border})`, borderRadius: 2 }} />
                                {[
                                    { ico: "✅", label: "Document submitted", sub: "Done", done: true, active: false },
                                    { ico: "🔔", label: "Lawyer notified", sub: "Done", done: true, active: false },
                                    { ico: "🔍", label: "Lawyer review", sub: reviewStatus === "submitted" ? "In progress — updates automatically" : "Complete", done: reviewStatus !== "submitted", active: reviewStatus === "submitted" },
                                    {
                                        ico: reviewStatus === "approved" ? "✅" : reviewStatus === "returned" ? "↩️" : reviewStatus === "rejected" ? "❌" : "⚖️",
                                        label: reviewStatus === "approved" ? "Approved by lawyer" : reviewStatus === "returned" ? "Returned with changes" : reviewStatus === "rejected" ? "Rejected by lawyer" : "Lawyer decision",
                                        sub: reviewStatus === "submitted" ? "Pending" : "Recorded",
                                        done: ["approved", "returned", "rejected"].includes(reviewStatus), active: false,
                                    },
                                ].map((item, i) => (
                                    <div key={i} style={{ display: "flex", gap: 13, marginBottom: 14, alignItems: "flex-start", position: "relative" }}>
                                        <div style={{ width: 28, height: 28, borderRadius: "50%", background: item.done ? t.primary : item.active ? t.primaryGlow : t.inputBg, border: `2px solid ${item.done ? t.primary : item.active ? t.primary : t.border}`, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 12, flexShrink: 0, zIndex: 1, boxShadow: item.active ? `0 0 0 4px ${t.primaryGlow}` : "none" }}>{item.ico}</div>
                                        <div style={{ flex: 1, paddingTop: 3 }}>
                                            <div style={{ fontSize: 12.5, fontWeight: item.done || item.active ? 700 : 500, color: item.done ? t.primary : item.active ? t.text : t.textMuted }}>{item.label}</div>
                                            <div style={{ fontSize: 10, color: item.active ? t.primary : t.textFaint, marginTop: 1 }}>{item.sub}</div>
                                        </div>
                                        {item.active && <div style={{ width: 8, height: 8, borderRadius: "50%", background: t.primary, marginTop: 10, flexShrink: 0, boxShadow: `0 0 0 3px ${t.primaryGlow}` }} />}
                                    </div>
                                ))}
                            </div>

                            {/* Real status-driven actions */}
                            {reviewStatus === "submitted" && (
                                <div style={{ marginTop: 4, padding: "12px 14px", borderRadius: 12, background: t.primaryGlow, border: `1px solid ${t.primary}30`, fontSize: 11.5, color: t.textMuted, lineHeight: 1.6 }}>
                                    ⏳ Waiting for {revLawyerName} to review. This page checks automatically —
                                    you'll also get a notification the moment they respond.
                                </div>
                            )}
                            {(reviewStatus === "returned" || reviewStatus === "rejected") && (
                                <div style={{ marginTop: 4 }}>
                                    <div style={{ padding: "12px 14px", borderRadius: 12, background: reviewStatus === "returned" ? `${t.warn}10` : `${t.danger}10`, border: `1px solid ${reviewStatus === "returned" ? t.warn : t.danger}30`, marginBottom: 8 }}>
                                        <div style={{ fontSize: 11, fontWeight: 700, color: reviewStatus === "returned" ? t.warn : t.danger, marginBottom: 4 }}>
                                            {reviewStatus === "returned" ? "↩️ Lawyer requested changes" : "❌ Lawyer rejected this document"}
                                        </div>
                                        <div style={{ fontSize: 12, color: t.text, lineHeight: 1.6 }}>{lawyerNote || "No note provided."}</div>
                                    </div>
                                    {reviewStatus === "returned" && (
                                        <BtnPrimary onClick={() => { setReviewSent(false); setReviewStatus(null); goTo(1); }} style={{ width: "100%", fontSize: 12, padding: "11px", borderRadius: 11, justifyContent: "center" }}>
                                            ✏️ Revise & Regenerate →
                                        </BtnPrimary>
                                    )}
                                </div>
                            )}
                            {reviewStatus === "approved" && (
                                <BtnPrimary onClick={() => goTo(4)} style={{ width: "100%", fontSize: 13, padding: "13px", borderRadius: 12, justifyContent: "center", marginTop: 4, boxShadow: `0 4px 18px ${t.primaryGlow}` }}>
                                    🏛 View Final Version →
                                </BtnPrimary>
                            )}
                        </Card>

                        {/* Right: submission details + export */}
                        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
                            <Card>
                                <STitle icon="file" sub="Submission overview">Details</STitle>
                                <div style={{ padding: "9px 12px", borderRadius: 10, background: t.primaryGlow, border: `1px solid ${t.primary}30`, marginBottom: 10 }}>
                                    <div style={{ fontSize: 12, fontWeight: 700, color: t.text, marginBottom: 1 }}>{docTitle || "Employment Dispute"}</div>
                                    <div style={{ fontSize: 11, color: t.textMuted }}>{selectedType} · {caseRef || "No ref"}</div>
                                </div>
                                {[["Lawyer", revLawyerName], ["Urgency", urgency], ["Type", selectedType], ["Status", null]].map(([k, v]) => (
                                    <div key={k} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "7px 0", borderBottom: `1px solid ${t.border}`, fontSize: 12 }}>
                                        <span style={{ color: t.textMuted }}>{k}</span>
                                        {k === "Status" ? <Badge type={statusColors[docStatus]}>{docStatus}</Badge>
                                            : k === "Urgency" ? <Badge type={urgency === "Urgent" ? "danger" : urgency === "Priority" ? "warn" : "success"}>{urgency}</Badge>
                                                : <span style={{ fontWeight: 600, color: t.text }}>{v}</span>}
                                    </div>
                                ))}
                                {reviewNote ? <div style={{ marginTop: 9, padding: "9px 11px", borderRadius: 9, background: t.inputBg, fontSize: 11, color: t.textMuted, fontStyle: "italic" }}>📝 "{reviewNote.slice(0, 90)}{reviewNote.length > 90 ? "…" : ""}"</div> : null}
                            </Card>

                            <Card>
                                <STitle icon="dl" sub="Download the generated PDF">Export</STitle>
                                <BtnOutline
                                    onClick={() => { if (docId) { downloadDocument(docId, docTitle || "document"); } else { toast.show("Generate the document first", "warn"); } }}
                                    disabled={!docId}
                                    style={{ width: "100%", fontSize: 12, padding: "11px", borderRadius: 11, justifyContent: "center" }}>
                                    {docId ? "📥 Download PDF" : "Generate the document first"}
                                </BtnOutline>
                            </Card>

                            <div style={{ padding: "12px 15px", borderRadius: 13, background: `${t.success}10`, border: `1px solid ${t.success}30`, display: "flex", gap: 11, alignItems: "center" }}>
                                <div style={{ width: 30, height: 30, borderRadius: "50%", background: `${t.success}20`, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 14, flexShrink: 0 }}>🔔</div>
                                <div>
                                    <div style={{ fontSize: 12, fontWeight: 700, color: t.text, marginBottom: 2 }}>You'll be notified</div>
                                    <div style={{ fontSize: 11, color: t.textMuted }}>Alert when {revLawyerName} completes review.</div>
                                </div>
                            </div>
                        </div>
                    </div>
                )}

                {/* ════════════════════════════════════════════════
            STEP 5 — Final Version + Export
        ════════════════════════════════════════════════ */}
                {step === 4 && (
                    <div className="rgrid" style={{ display: "grid", gridTemplateColumns: "1fr 300px", gap: 18 }}>

                        {/* Left: final document */}
                        <Card style={{ display: "flex", flexDirection: "column" }}>
                            <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 16 }}>
                                <div style={{ width: 36, height: 36, borderRadius: 10, background: `${t.success}20`, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 18, flexShrink: 0 }}>🏛</div>
                                <div style={{ flex: 1 }}>
                                    <div style={{ fontWeight: 700, color: t.text, fontSize: 14 }}>Final Legal Document</div>
                                    <div style={{ fontSize: 11, color: t.textMuted }}>{docTitle || "Employment Dispute"}</div>
                                </div>
                                <Badge type="info">Final</Badge>
                            </div>

                            {/* Final doc preview (read-only) */}
                            <div style={{ flex: 1, border: `1.5px solid ${t.success}40`, borderRadius: 12, background: t.card, padding: "20px 24px", fontSize: 13, lineHeight: 2.1, color: t.text, fontFamily: "Georgia,serif", overflowY: "auto", minHeight: 360 }}>
                                <p style={{ textAlign: "center", fontWeight: 700, fontSize: 15, marginBottom: 8 }}>IN THE COURT OF CIVIL JUDGE, LAHORE</p>
                                <p style={{ textAlign: "center", fontSize: 12, color: t.textMuted, marginBottom: 16 }}>Employment Dispute — {selectedType || "Plaint"} No. ___/2026</p>
                                <p style={{ marginBottom: 8 }}><strong>Plaintiff:</strong> M. Usama, S/O [Father Name], CNIC [__________], R/O [Address], Rawalpindi.</p>
                                <p style={{ marginBottom: 14 }}><strong>Defendant:</strong> XYZ Corporation (Pvt.) Ltd., [Registered Address], Islamabad.</p>
                                <p style={{ marginBottom: 10 }}><strong>PLAINT UNDER ORDER VII RULE 1 CPC</strong></p>
                                <p style={{ marginBottom: 8 }}>1. That the plaintiff was employed with the defendant company as [Designation] since [Date], vide Employment Contract dated [__________].</p>
                                <p style={{ marginBottom: 8 }}>2. That on February 12, 2026, the defendant unlawfully terminated the plaintiff's services without lawful cause and without serving the required notice period.</p>
                                <p style={{ marginBottom: 8 }}>3. That the plaintiff is entitled to receive salary in lieu of notice period, unpaid dues, and compensation for wrongful termination.</p>
                                <p style={{ marginBottom: 6 }}><strong>PRAYER:</strong></p>
                                <p style={{ marginBottom: 20 }}>The plaintiff respectfully prays that this Honourable Court may be pleased to award PKR 500,000 as compensation together with costs of the suit.</p>
                                <div style={{ borderTop: `1px solid ${t.border}`, paddingTop: 14, display: "flex", justifyContent: "space-between", fontSize: 11, color: t.textMuted }}>
                                    <span>🏛 Approved by {revLawyerName || "Lawyer"}</span>
                                    <span>📅 {new Date().toLocaleDateString("en-GB")}</span>
                                </div>
                            </div>

                            {/* Export actions */}
                            <div style={{ marginTop: 14 }}>
                                {/* Only Download was ever wired. Generate PDF / Email /
                                    Print each toasted a completed action and did none of
                                    it — and the PDF already exists by this point, so
                                    "generate" was meaningless too. */}
                                <div style={{ marginBottom: 8 }}>
                                    <BtnOutline
                                        onClick={() => { if (docId) { setExported(true); downloadDocument(docId, docTitle || "document"); } else { toast.show("Generate the document first", "warn"); } }}
                                        disabled={!docId}
                                        style={{ width: "100%", fontSize: 12, padding: "12px", borderRadius: 11, justifyContent: "center" }}>
                                        {docId ? "📥 Download PDF" : "Generate the document first"}
                                    </BtnOutline>
                                </div>
                            </div>
                        </Card>

                        {/* Right: summary + completed workflow */}
                        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>

                            {/* Completion badge */}
                            <div style={{ textAlign: "center", padding: "20px 16px", borderRadius: 16, background: `linear-gradient(135deg,${t.primaryGlow},${t.card})`, border: `1px solid ${t.primary}30` }}>
                                <div style={{ fontSize: 42, marginBottom: 10 }}>🎉</div>
                                <div style={{ fontSize: 14, fontWeight: 800, color: t.text, fontFamily: "'Playfair Display',serif", marginBottom: 5 }}>Document Complete</div>
                                <div style={{ fontSize: 11, color: t.textMuted, marginBottom: 12 }}>Reviewed and approved by {revLawyerName || "your lawyer"}</div>
                                <Badge type="info" style={{ fontSize: 12, padding: "5px 14px" }}>● Final Version</Badge>
                            </div>

                            {/* Document summary */}
                            <Card>
                                <div style={{ fontSize: 10, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.8px", color: t.textMuted, marginBottom: 10 }}>Document Summary</div>
                                {[["Type", selectedType || "—"], ["Template", selectedDraft !== null ? DRAFTS_DATA[selectedDraft].name : "—"], ["Case Ref", caseRef || "—"], ["Reviewer", revLawyerName || "—"], ["Status", null], ["Compliance", null]].map(([k, v]) => (
                                    <div key={k} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "7px 0", borderBottom: `1px solid ${t.border}`, fontSize: 12 }}>
                                        <span style={{ color: t.textMuted }}>{k}</span>
                                        {k === "Status" ? <Badge type="info">Final</Badge> : k === "Compliance" ? <Badge type="success">✓ Verified</Badge> : <span style={{ fontWeight: 600, color: t.text, textAlign: "right", maxWidth: 140, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{v}</span>}
                                    </div>
                                ))}
                            </Card>

                            {/* Completed workflow */}
                            <Card>
                                <div style={{ fontSize: 10, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.8px", color: t.textMuted, marginBottom: 12 }}>Workflow Complete</div>
                                {FLOW.map((f, i) => (
                                    <div key={i} style={{ display: "flex", gap: 9, marginBottom: i < FLOW.length - 1 ? 8 : 0 }}>
                                        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", flexShrink: 0 }}>
                                            <div style={{ width: 18, height: 18, borderRadius: "50%", background: t.primary, border: `2px solid ${t.primary}`, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 7, fontWeight: 800, color: t.mode === "dark" ? "#1A2E35" : "#fff" }}>✓</div>
                                            {i < FLOW.length - 1 && <div style={{ width: 1, height: 12, background: t.primary, marginTop: 1 }} />}
                                        </div>
                                        <div style={{ fontSize: 10.5, color: t.primary, fontWeight: 500, paddingTop: 1 }}>{f.label}</div>
                                    </div>
                                ))}
                            </Card>
                        </div>
                    </div>
                )}

            </div>
        </div>
    );
};


/* ══════════════════════════════════════════════════════
   MODULE: CASE TRACKING
══════════════════════════════════════════════════════ */
const ModTracking = () => {
    const t = useT();
    const [notifs, setNotifs] = useState([
        { id: 1, text: "Court Hearing scheduled for Feb 25", read: false, type: "danger" },
        { id: 2, text: "Ahmad Raza Khan responded to your question", read: false, type: "info" },
        { id: 3, text: "NDA Agreement has been signed", read: true, type: "success" },
    ]);
    // Case timeline and hearing dates, from the case itself.
    //
    // These were three hardcoded arrays presented as the user's own case:
    // milestones ("Court Hearing — Feb 25", "Ahmad Raza Khan assigned"),
    // deadlines ("Submit Evidence — 1 day left", "Pay Court Fees — Mar 5") and
    // a Lawyer Q&A whose sample answer put a fabricated "approximately 75-80%"
    // win probability in the client's hands. A client can act on a court date
    // and miss a real one; nobody should ever read an invented probability as
    // their lawyer's opinion. The Q&A card is gone entirely — there is no
    // backend for it, and case messaging already exists under Tracking.
    const [timeline, setTimeline] = useState({ milestones: [], hearing_dates: [] });
    const timelineCaseId = genCaseId || activeCaseId;
    useEffect(() => {
        if (!timelineCaseId) { setTimeline({ milestones: [], hearing_dates: [] }); return; }
        getCaseTimeline(timelineCaseId).then(({ data }) => {
            if (data) setTimeline({ milestones: data.milestones || [], hearing_dates: data.hearing_dates || [] });
        });
    }, [timelineCaseId]);
    const milestones = timeline.milestones;
    const deadlines = timeline.hearing_dates;
    const markRead = (id) => setNotifs(n => n.map(x => x.id === id ? { ...x, read: true } : x));
    return (
        <div className="rgrid" style={{ display: "grid", gridTemplateColumns: "2fr 1fr", gap: 18 }}>
            <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
                <Card>
                    <STitle icon="clock" sub={timelineCaseId ? activeCaseTitle : "No case linked"}>Case Timeline</STitle>
                    {!milestones.length && (
                        <div style={{ padding: "14px 4px", fontSize: 12.5, color: t.textMuted }}>
                            {timelineCaseId
                                ? "No milestones recorded yet. Your lawyer adds these as the case progresses."
                                : "Link a case to see its timeline."}
                        </div>
                    )}
                    <div style={{ position: "relative", paddingLeft: 20 }}>
                        <div style={{ position: "absolute", left: 28, top: 0, bottom: 0, width: 2, background: t.border, borderRadius: 2 }} />
                        {milestones.map((m, i) => {
                            const isDone = Boolean(m.completed);
                            // The first not-yet-completed milestone is the live one.
                            const isActive = !isDone && milestones.findIndex(x => !x.completed) === i;
                            return (
                                <div key={i} style={{ display: "flex", gap: 16, alignItems: "flex-start", marginBottom: 24, position: "relative" }}>
                                    <div style={{ width: 22, height: 22, borderRadius: "50%", background: isDone ? t.success : isActive ? t.primary : t.inputBg, border: `2px solid ${isDone ? t.success : isActive ? t.primary : t.border}`, display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0, zIndex: 1, boxShadow: isActive ? `0 0 14px ${t.primaryGlow}` : "none" }}>
                                        {isDone && <Ic n="check" s={11} c={t.mode === "dark" ? "#1A2E35" : "#fff"} />}
                                        {isActive && <div style={{ width: 8, height: 8, background: t.mode === "dark" ? "#1A2E35" : "#fff", borderRadius: "50%" }} />}
                                    </div>
                                    <div style={{ flex: 1, paddingTop: 1 }}>
                                        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                                            <div style={{ fontWeight: isActive ? 700 : 600, color: isActive ? t.primary : isDone ? t.text : t.textMuted, fontSize: 13 }}>{m.title}</div>
                                            <div style={{ fontSize: 11, color: t.textMuted }}>{m.date ? new Date(m.date).toLocaleDateString("en-PK", { day: "numeric", month: "short" }) : ""}</div>
                                        </div>
                                        <div style={{ fontSize: 12, color: t.textMuted, marginTop: 3 }}>{m.description || ""}</div>
                                        {!isDone && <button style={{ marginTop: 6, background: "none", border: "none", color: t.primary, fontSize: 11, cursor: "pointer", padding: 0 }}>+ Add Note</button>}
                                    </div>
                                </div>
                            );
                        })}
                    </div>
                </Card>
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
                <Card>
                    <STitle icon="cal" sub="Scheduled hearings for this case">Hearings</STitle>
                    {!deadlines.length && (
                        <div style={{ padding: "14px 4px", fontSize: 12.5, color: t.textMuted }}>
                            {timelineCaseId ? "No hearings scheduled yet." : "Link a case to see its hearings."}
                        </div>
                    )}
                    {deadlines.map((d, i) => {
                        const when = d.date ? new Date(d.date) : null;
                        const days = when ? Math.ceil((when - new Date()) / 86400000) : null;
                        const soon = days !== null && days <= 3;
                        return (
                            <div key={d.id || i} style={{ padding: "12px 14px", borderRadius: 12, background: soon ? `${t.danger}12` : t.inputBg, marginBottom: 9 }}>
                                <div style={{ fontWeight: 600, fontSize: 13, color: soon ? t.danger : t.text }}>{d.purpose || d.court || "Hearing"}</div>
                                <div style={{ display: "flex", justifyContent: "space-between", marginTop: 5 }}>
                                    <span style={{ fontSize: 11, color: t.textMuted }}>{when ? when.toLocaleDateString("en-PK", { day: "numeric", month: "short", year: "numeric" }) : "Date not set"}</span>
                                    {days !== null && days >= 0 && (
                                        <span style={{ fontSize: 11, fontWeight: 700, color: soon ? t.danger : t.warn }}>{days}d left</span>
                                    )}
                                </div>
                            </div>
                        );
                    })}
                </Card>
                <Card>
                    <STitle icon="bell" sub="Hearing, status & alert updates">Notifications</STitle>
                    {notifs.map(n => (
                        <div key={n.id} onClick={() => markRead(n.id)} style={{ display: "flex", gap: 10, padding: "10px 0", borderBottom: `1px solid ${t.border}`, cursor: "pointer", opacity: n.read ? 0.55 : 1 }}>
                            <div style={{ width: 8, height: 8, borderRadius: "50%", background: n.read ? "transparent" : t[n.type] || t.primary, flexShrink: 0, marginTop: 5 }} />
                            <div style={{ fontSize: 12, color: t.text, lineHeight: 1.6, flex: 1 }}>{n.text}</div>
                        </div>
                    ))}
                </Card>
                <Card>
                    <STitle icon="clock" sub="Set custom reminders for deadlines">Reminders</STitle>
                    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                        <div><Lbl>Description</Lbl><ThemedInput placeholder="e.g. File plaint tomorrow" /></div>
                        <div className="rgrid-2" style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
                            <div><Lbl>Date</Lbl><ThemedInput type="date" /></div>
                            <div><Lbl>Time</Lbl><ThemedInput type="time" /></div>
                        </div>
                        <BtnPrimary style={{ fontSize: 13, padding: "12px" }}>Set Reminder</BtnPrimary>
                    </div>
                </Card>
            </div>
        </div>
    );
};

export default ModDocuments;

