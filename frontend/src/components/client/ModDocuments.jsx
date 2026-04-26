'use client';
// Paste your ModDocuments.jsx code here
import React, { useState, Fragment, useEffect } from "react";
import { useT, useHeaderActions } from "./theme.js";
import { useToast } from "@/components/shared/Toast.jsx";
import Ic from "./Ic.jsx";
import { Card, BtnPrimary, BtnOutline, ThemedInput, Badge } from "@/components/shared/shared.jsx";

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
    { name: "Special Power of Attorney", cat: "Civil", views: 120, dl: 113, free: true },
    { name: "Order I, Rule 10 — Intervenor App.", cat: "Civil", views: 39, dl: 44, free: false },
    { name: "Joint Venture Agreement", cat: "Corporate", views: 16, dl: 27, free: true },
    { name: "Condonation Application", cat: "Civil", views: 21, dl: 70, free: true },
    { name: "Certified Copy Application", cat: "Civil", views: 28, dl: 49, free: false },
    { name: "Articles of Association — SMC", cat: "Corporate", views: 9, dl: 15, free: true },
    { name: "Employment Termination Letter", cat: "Employment", views: 55, dl: 88, free: true },
    { name: "Non-Disclosure Agreement", cat: "Corporate", views: 102, dl: 95, free: false },
    { name: "Bail Application", cat: "Criminal", views: 44, dl: 38, free: true },
    { name: "Suit for Recovery of Money", cat: "Civil", views: 67, dl: 52, free: true },
    { name: "Property Transfer Deed", cat: "Property", views: 33, dl: 28, free: false },
    { name: "Labour Court Complaint", cat: "Employment", views: 29, dl: 41, free: true },
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

const EVIDENCE_FILES = [
    { name: "Employment_Contract.pdf", size: "2.4 MB", date: "Feb 10", status: "Processed" },
    { name: "Termination_Letter.pdf", size: "512 KB", date: "Feb 12", status: "Processed" },
    { name: "Pay_Stubs_Dec25.pdf", size: "1.1 MB", date: "Feb 14", status: "Pending" },
    { name: "Offer_Letter_2022.pdf", size: "340 KB", date: "Feb 14", status: "Pending" },
];


const ModDocuments = () => {
    const t = useT();
    const toast = useToast();

    /* ── State ── */
    const [step, setStep] = useState(0);                       // 0–4
    const [selectedDraft, setSelectedDraft] = useState(null);
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
    // Step 3 — review / edit
    const [editMode, setEditMode] = useState(false);
    const [docContent, setDocContent] = useState(null);       // null until generated
    const [userApproved, setUserApproved] = useState(false);
    // Step 4 — lawyer submission
    const [selLawyer, setSelLawyer] = useState(null);
    const [reviewNote, setReviewNote] = useState("");
    const [urgency, setUrgency] = useState("Normal");
    const [reviewSent, setReviewSent] = useState(false);
    const [lawyerAction, setLawyerAction] = useState(null);   // null | "editing" | "approved"
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
    const statusColors = { Draft: "gray", "Under Review": "warn", Approved: "success", Final: "info" };
    const docStatus = genDone ? (reviewSent ? (lawyerAction === "approved" ? "Final" : "Under Review") : userApproved ? "Approved" : "Draft") : "Draft";
    const lawyers = [
        { name: "Ahmad Raza Khan", spec: "Employment Law", rating: 4.9, avail: true, avatar: "AR", fee: "PKR 5,000", cases: 148, eta: "~2 hrs" },
        { name: "Sara Malik", spec: "Civil Litigation", rating: 4.8, avail: true, avatar: "SM", fee: "PKR 4,500", cases: 97, eta: "~3 hrs" },
        { name: "Bilal Chaudhry", spec: "Corporate Law", rating: 4.7, avail: false, avatar: "BC", fee: "PKR 6,000", cases: 203, eta: "Unavailable" },
    ];
    const GEN_STEPS = ["Extracting case data…", "Applying AI recommendations…", "Populating template…", "Formatting document…", "Finalising draft…"];

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
        if (step < STEPS.length - 1) setStep(s => s + 1);
    };
    const prevStep = () => { if (step > 0) setStep(s => s - 1); };

    const pickDraft = i => {
        if (!DRAFTS_DATA[i].free) { toast.show("🔒 Upgrade to Pro", "warn"); return; }
        setSelectedDraft(i);
        if (selectedType) setDocTitle(DRAFTS_DATA[i].name + " — " + selectedType);
    };
    const pickType = key => {
        setSelectedType(key);
        if (selectedDraft !== null) setDocTitle(DRAFTS_DATA[selectedDraft].name + " — " + key);
    };

    const handleGenerate = () => {
        setGenerating(true); setGenPct(0); setGenDone(false);
        let pct = 0, si = 0;
        const iv = setInterval(() => {
            pct += 20; si++;
            setGenPct(pct);
            if (pct >= 100) {
                clearInterval(iv);
                setTimeout(() => { setGenerating(false); setGenDone(true); toast.show("✅ Draft generated!", "success"); }, 400);
            }
        }, 400);
    };

    /* ── Header actions ── */
    const { setHeaderActions } = useHeaderActions();
    useEffect(() => {
        setHeaderActions(
            <>
                {step === 0 && (
                    <BtnPrimary onClick={() => toast.show("⚡ Upgrade to unlock all templates!", "success")} style={{ fontSize: 11, padding: "7px 18px", background: "linear-gradient(135deg,#0fa,#0d9)" }}>⚡ Upgrade to Pro</BtnPrimary>
                )}
                {step > 0 && <BtnOutline onClick={prevStep} style={{ fontSize: 11, padding: "7px 14px" }}>← Back</BtnOutline>}
                {step > 0 && <BtnOutline onClick={() => toast.show("💾 Draft saved!", "success")} style={{ fontSize: 11, padding: "7px 14px" }}>💾 Save Draft</BtnOutline>}
                {step > 0 && step < 4 && <BtnPrimary onClick={nextStep} style={{ fontSize: 11, padding: "7px 18px" }}>Continue →</BtnPrimary>}
            </>
        );
        return () => setHeaderActions(null);
    });

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
        { label: "Lawyer Review", active: reviewSent && lawyerAction === null, done: lawyerAction !== null },
        { label: "Lawyer Edit / Approve", active: lawyerAction === "editing", done: lawyerAction === "approved" },
        { label: "Final Version", active: lawyerAction === "approved" && !exported, done: exported },
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
                        <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 10, marginBottom: 14 }}>
                            {[["Total Templates", "30", "📄", t.primary], ["Recent", "5", "🕐", t.warn], ["Categories", "6", "📁", t.success], ["Free", "6", "⬇️", t.info]].map(([label, val, ico, col]) => (
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
                        <div style={{ display: "grid", gridTemplateColumns: "repeat(3,minmax(0,1fr))", gap: 14 }}>
                            {filteredDrafts.length ? filteredDrafts.map(d => {
                                const gi = DRAFTS_DATA.indexOf(d);
                                const sel = selectedDraft === gi;
                                return (
                                    <div key={gi} onClick={() => d.free && pickDraft(gi)} style={{ background: sel ? t.primaryGlow : t.card, border: `2px solid ${sel ? t.primary : t.border}`, borderRadius: 18, padding: 18, cursor: d.free ? "pointer" : "not-allowed", transition: "all 0.2s", position: "relative", display: "flex", flexDirection: "column", minHeight: 200, opacity: !d.free ? 0.6 : 1, boxShadow: sel ? `0 0 0 1px ${t.primary}, ${t.shadowCard}` : t.shadowCard }}
                                        onMouseEnter={e => { if (d.free && !sel) { e.currentTarget.style.borderColor = t.primary + "60"; e.currentTarget.style.background = t.primaryGlow + "50"; } }}
                                        onMouseLeave={e => { if (d.free && !sel) { e.currentTarget.style.borderColor = t.border; e.currentTarget.style.background = t.card; } }}
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
                                        {/* Stats */}
                                        <div style={{ display: "flex", gap: 12, fontSize: 11, color: t.textMuted, marginBottom: 10 }}><span>👁 {d.views}</span><span>⬇️ {d.dl}</span></div>
                                        {/* Action buttons */}
                                        <div style={{ display: "flex", gap: 7 }}>
                                            <button onClick={e => { e.stopPropagation(); toast.show("🔍 Template preview", "info"); }} style={{ flex: 1, padding: "7px", borderRadius: 10, border: `1.5px solid ${t.border}`, background: t.card, color: t.textMuted, fontSize: 11, fontWeight: 600, cursor: "pointer", fontFamily: "'Inter',sans-serif" }}>🔍 Preview</button>
                                            <button onClick={e => { e.stopPropagation(); d.free ? (sel ? nextStep() : pickDraft(gi)) : toast.show("🔒 Upgrade to access", "warn"); }} style={{ flex: 1, padding: "7px", borderRadius: 10, border: `1.5px solid ${sel ? t.primary : t.border}`, background: sel ? t.primary : t.card, color: sel ? (t.mode === "dark" ? "#1A2E35" : "#fff") : t.textMuted, fontSize: 11, fontWeight: 600, cursor: d.free || sel ? "pointer" : "not-allowed", fontFamily: "'Inter',sans-serif", transition: "all 0.2s" }}>{sel ? "✓ Use Template" : d.free ? "Select" : "🔒 Pro"}</button>
                                        </div>
                                        {/* Pro lock overlay */}
                                        {!d.free && <div style={{ position: "absolute", inset: 0, borderRadius: 17, background: `${t.card}cc`, backdropFilter: "blur(2px)", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 4 }}><span style={{ fontSize: 20 }}>🔒</span><span style={{ fontSize: 11, color: t.textMuted, fontWeight: 600 }}>Pro Only</span></div>}
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
                                <div><Lbl>Case Reference No.</Lbl><ThemedInput value={caseRef} onChange={e => setCaseRef(e.target.value)} placeholder="e.g. CASE-2026-00142" /></div>
                                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
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

                            {/* AI readiness strip */}
                            <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "10px 13px", borderRadius: 10, background: t.primaryGlow, border: `1px solid ${t.primary}30`, marginTop: 12 }}>
                                <div style={{ width: 8, height: 8, borderRadius: "50%", background: t.success, flexShrink: 0 }} />
                                <span style={{ fontSize: 11.5, color: t.textMuted, flex: 1 }}>Case data extracted · AI recommendations ready</span>
                                <Badge type="success">✓ Ready</Badge>
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

                            {!genDone ? (
                                <BtnPrimary onClick={handleGenerate} disabled={generating} style={{ width: "100%", marginTop: 13, fontSize: 13, padding: "13px", borderRadius: 12, justifyContent: "center" }}>
                                    {generating ? "⏳ Generating…" : "✨ Generate Draft"}
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
                    <div style={{ display: "grid", gridTemplateColumns: "1fr 280px", gap: 18 }}>

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
                                    <button onClick={() => toast.show("➕ Clause added", "info")} style={tbBtn}>➕ Clause</button>
                                    <button onClick={() => toast.show("🗑 Section removed", "warn")} style={tbBtn}>🗑 Remove</button>
                                    <button onClick={() => toast.show("💾 Saved!", "success")} style={{ ...tbBtn, color: t.primary, borderColor: t.primary, background: t.primaryGlow }}>💾 Save</button>
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
                                <BtnOutline onClick={() => toast.show("📄 PDF generated!", "success")} style={{ flex: 1, fontSize: 11, padding: "9px", borderRadius: 10 }}>📄 PDF</BtnOutline>
                                <BtnOutline onClick={() => toast.show("📥 Downloading…", "info")} style={{ flex: 1, fontSize: 11, padding: "9px", borderRadius: 10 }}>📥 Download</BtnOutline>
                                <BtnOutline onClick={() => toast.show("✉️ Email sent!", "success")} style={{ flex: 1, fontSize: 11, padding: "9px", borderRadius: 10 }}>✉️ Email</BtnOutline>
                                <BtnOutline onClick={() => toast.show("🖨️ Printing…", "info")} style={{ flex: 1, fontSize: 11, padding: "9px", borderRadius: 10 }}>🖨️ Print</BtnOutline>
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
                                        <BtnPrimary onClick={() => { setUserApproved(true); toast.show("✅ Document approved!", "success"); }} style={{ width: "100%", fontSize: 12, padding: "10px", borderRadius: 10, justifyContent: "center" }}>✅ Approve Draft</BtnPrimary>
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
                    <div style={{ display: "grid", gridTemplateColumns: "1fr 300px", gap: 18 }}>

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
                                <STitle icon="scale" sub="Select a lawyer to review your document">Choose Lawyer</STitle>
                                <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                                    {lawyers.map((l, i) => (
                                        <div key={i} onClick={() => l.avail && setSelLawyer(i)} style={{ display: "flex", alignItems: "center", gap: 13, padding: "13px 15px", borderRadius: 13, border: `2px solid ${selLawyer === i ? t.primary : t.border}`, background: selLawyer === i ? t.primaryGlow : t.inputBg, cursor: l.avail ? "pointer" : "not-allowed", transition: "all 0.2s", opacity: l.avail ? 1 : 0.45, position: "relative" }}>
                                            <div style={{ width: 44, height: 44, borderRadius: "50%", background: selLawyer === i ? t.primary : `${t.primary}18`, border: `2px solid ${selLawyer === i ? t.primary : t.border}`, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 13, fontWeight: 800, color: selLawyer === i ? (t.mode === "dark" ? "#1A2E35" : "#fff") : t.primary, flexShrink: 0, transition: "all 0.2s" }}>{l.avatar}</div>
                                            <div style={{ flex: 1, minWidth: 0 }}>
                                                <div style={{ fontSize: 13, fontWeight: 700, color: t.text, marginBottom: 3 }}>{l.name}</div>
                                                <div style={{ fontSize: 11, color: t.textMuted, marginBottom: 4 }}>{l.spec}</div>
                                                <div style={{ display: "flex", gap: 10, fontSize: 11 }}>
                                                    <span style={{ color: t.warn }}>⭐ {l.rating}</span>
                                                    <span style={{ color: t.textMuted }}>💼 {l.cases} cases</span>
                                                    <span style={{ color: t.success, fontWeight: 600 }}>{l.fee}/review</span>
                                                </div>
                                            </div>
                                            <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 5 }}>
                                                <Badge type={l.avail ? "success" : "gray"}>{l.avail ? "● Available" : "○ Busy"}</Badge>
                                                <div style={{ fontSize: 10, color: t.textFaint }}>{l.eta}</div>
                                            </div>
                                            {selLawyer === i && <div style={{ position: "absolute", top: 8, right: 8, width: 20, height: 20, borderRadius: "50%", background: t.primary, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 10, fontWeight: 800, color: t.mode === "dark" ? "#1A2E35" : "#fff" }}>✓</div>}
                                        </div>
                                    ))}
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
                            <Card style={{ minHeight: 90, display: "flex", alignItems: selLawyer === null ? "center" : "flex-start" }}>
                                {selLawyer === null ? (
                                    <div style={{ textAlign: "center", color: t.textMuted, fontSize: 12, width: "100%" }}><div style={{ fontSize: 24, marginBottom: 5 }}>👤</div>Select a lawyer</div>
                                ) : (
                                    <div style={{ width: "100%" }}>
                                        <div style={{ fontSize: 10, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.8px", color: t.textMuted, marginBottom: 8 }}>Assigned Lawyer</div>
                                        <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "9px 11px", borderRadius: 11, background: t.primaryGlow, border: `1px solid ${t.primary}40` }}>
                                            <div style={{ width: 34, height: 34, borderRadius: "50%", background: t.primary, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 12, fontWeight: 800, color: t.mode === "dark" ? "#1A2E35" : "#fff", flexShrink: 0 }}>{lawyers[selLawyer].avatar}</div>
                                            <div>
                                                <div style={{ fontSize: 12, fontWeight: 700, color: t.text }}>{lawyers[selLawyer].name}</div>
                                                <div style={{ fontSize: 10, color: t.primary }}>{lawyers[selLawyer].spec}</div>
                                            </div>
                                        </div>
                                    </div>
                                )}
                            </Card>

                            {/* Urgency */}
                            <Card>
                                <STitle icon="clock" sub="Response time">Urgency</STitle>
                                {[["Normal", "2–4 hours", "Standard", t.success], ["Priority", "1–2 hours", "+25%", t.warn], ["Urgent", "< 1 hour", "+60%", t.danger]].map(([lvl, eta, fee, col]) => (
                                    <div key={lvl} onClick={() => setUrgency(lvl)} style={{ display: "flex", alignItems: "center", gap: 10, padding: "10px 12px", borderRadius: 10, border: `1.5px solid ${urgency === lvl ? col : t.border}`, background: urgency === lvl ? `${col}10` : t.inputBg, cursor: "pointer", marginBottom: 7, transition: "all 0.2s" }}>
                                        <div style={{ width: 13, height: 13, borderRadius: "50%", border: `2px solid ${urgency === lvl ? col : t.border}`, background: urgency === lvl ? col : "transparent", flexShrink: 0 }} />
                                        <div style={{ flex: 1 }}>
                                            <div style={{ fontSize: 12, fontWeight: urgency === lvl ? 700 : 500, color: urgency === lvl ? col : t.text }}>{lvl}</div>
                                            <div style={{ fontSize: 10, color: t.textFaint }}>{eta}</div>
                                        </div>
                                        <span style={{ fontSize: 10, fontWeight: 600, color: urgency === lvl ? col : t.textMuted }}>{fee}</span>
                                    </div>
                                ))}
                            </Card>

                            {/* Fee */}
                            {selLawyer !== null && (
                                <div style={{ padding: "12px 14px", borderRadius: 12, background: t.inputBg, border: `1px solid ${t.border}` }}>
                                    <div style={{ fontSize: 10, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.8px", color: t.textMuted, marginBottom: 8 }}>Fee Summary</div>
                                    {[["Base fee", lawyers[selLawyer].fee], ["Urgency", urgency === "Priority" ? "+25%" : urgency === "Urgent" ? "+60%" : "—"]].map(([k, v]) => (
                                        <div key={k} style={{ display: "flex", justifyContent: "space-between", padding: "5px 0", borderBottom: `1px solid ${t.border}`, fontSize: 11.5 }}>
                                            <span style={{ color: t.textMuted }}>{k}</span><span style={{ fontWeight: 600, color: t.text }}>{v}</span>
                                        </div>
                                    ))}
                                    <div style={{ display: "flex", justifyContent: "space-between", padding: "7px 0 0", fontSize: 13, fontWeight: 800 }}>
                                        <span style={{ color: t.text }}>Total</span>
                                        <span style={{ color: t.primary }}>{urgency === "Priority" ? "PKR 5,625" : urgency === "Urgent" ? "PKR 8,000" : lawyers[selLawyer].fee}</span>
                                    </div>
                                </div>
                            )}

                            <BtnPrimary onClick={() => {
                                if (selLawyer === null) { toast.show("⚠️ Select a lawyer first", "warn"); return; }
                                setReviewSent(true);
                                toast.show(`📤 Sent to ${lawyers[selLawyer].name}`, "success");
                            }} style={{ width: "100%", fontSize: 13, padding: "14px", borderRadius: 12, justifyContent: "center", boxShadow: `0 6px 20px ${t.primaryGlow}`, opacity: selLawyer === null ? 0.5 : 1 }}>
                                📤 Submit to Lawyer
                            </BtnPrimary>
                            <BtnOutline onClick={() => toast.show("💾 Saved as draft", "success")} style={{ width: "100%", fontSize: 12, padding: "10px", borderRadius: 10 }}>
                                💾 Save as Draft
                            </BtnOutline>
                        </div>
                    </div>
                )}

                {/* ── Lawyer Review in Progress ── */}
                {step === 3 && reviewSent && (
                    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 18 }}>

                        {/* Left: live tracking */}
                        <Card>
                            <div style={{ textAlign: "center", padding: "18px 0 16px", borderBottom: `1px solid ${t.border}`, marginBottom: 16 }}>
                                <div style={{ width: 60, height: 60, borderRadius: "50%", background: t.primaryGlow, border: `2px solid ${t.primary}40`, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 26, margin: "0 auto 12px" }}>📬</div>
                                <div style={{ fontSize: 16, fontWeight: 800, color: t.text, fontFamily: "'Playfair Display',serif", marginBottom: 5 }}>Submitted for Legal Review</div>
                                <div style={{ display: "inline-flex", alignItems: "center", gap: 8, marginTop: 6, padding: "7px 14px", borderRadius: 50, background: t.primaryGlow, border: `1px solid ${t.primary}40` }}>
                                    <div style={{ width: 24, height: 24, borderRadius: "50%", background: t.primary, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 10, fontWeight: 800, color: t.mode === "dark" ? "#1A2E35" : "#fff" }}>{lawyers[selLawyer].avatar}</div>
                                    <span style={{ fontSize: 13, fontWeight: 700, color: t.primary }}>{lawyers[selLawyer].name}</span>
                                </div>
                            </div>

                            <div style={{ fontSize: 10, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.8px", color: t.textMuted, marginBottom: 14 }}>Review Progress</div>
                            <div style={{ position: "relative" }}>
                                <div style={{ position: "absolute", left: 13, top: 26, bottom: 26, width: 2, background: `linear-gradient(${t.primary}, ${t.border})`, borderRadius: 2 }} />
                                {[
                                    { ico: "✅", label: "Document submitted", sub: "Just now", done: true, active: false },
                                    { ico: "🔔", label: "Lawyer notified", sub: "Just now", done: true, active: false },
                                    { ico: "🔍", label: "Lawyer review", sub: urgency === "Urgent" ? "< 1 hr" : urgency === "Priority" ? "1–2 hrs" : "2–4 hrs", done: false, active: lawyerAction === null },
                                    { ico: "✏️", label: "Lawyer edit / modify", sub: "If changes needed", done: lawyerAction === "approved", active: lawyerAction === "editing" },
                                    { ico: "✅", label: "Lawyer approved", sub: "Final sign-off", done: lawyerAction === "approved", active: false },
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

                            {/* Simulate lawyer actions */}
                            {lawyerAction === null && (
                                <div style={{ marginTop: 4, padding: "12px 14px", borderRadius: 12, background: `${t.warn}10`, border: `1px solid ${t.warn}30` }}>
                                    <div style={{ fontSize: 11, fontWeight: 700, color: t.warn, marginBottom: 8 }}>Simulate Lawyer Response</div>
                                    <div style={{ display: "flex", gap: 8 }}>
                                        <BtnOutline onClick={() => { setLawyerAction("editing"); toast.show("✏️ Lawyer is editing…", "info"); }} style={{ flex: 1, fontSize: 11, padding: "8px", borderRadius: 9, borderColor: t.warn, color: t.warn }}>✏️ Lawyer Edits</BtnOutline>
                                        <BtnPrimary onClick={() => { setLawyerAction("approved"); toast.show("✅ Lawyer approved!", "success"); }} style={{ flex: 1, fontSize: 11, padding: "8px", borderRadius: 9, justifyContent: "center" }}>✅ Lawyer Approves</BtnPrimary>
                                    </div>
                                </div>
                            )}
                            {lawyerAction === "editing" && (
                                <BtnPrimary onClick={() => { setLawyerAction("approved"); toast.show("✅ Lawyer approved after edits!", "success"); }} style={{ width: "100%", fontSize: 12, padding: "11px", borderRadius: 11, justifyContent: "center", marginTop: 4 }}>
                                    ✅ Lawyer Approves After Edit
                                </BtnPrimary>
                            )}
                            {lawyerAction === "approved" && (
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
                                {[["Lawyer", lawyers[selLawyer].name], ["Urgency", urgency], ["Type", selectedType], ["Status", null]].map(([k, v]) => (
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
                                <STitle icon="dl" sub="Export your document">Export</STitle>
                                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
                                    {[["📄", "Generate PDF"], ["📥", "Download"], ["✉️", "Email"], ["🖨️", "Print"]].map(([ico, lbl]) => (
                                        <div key={lbl} onClick={() => toast.show(`${ico} ${lbl}…`, "success")} style={{ display: "flex", alignItems: "center", gap: 8, padding: "10px 12px", borderRadius: 11, border: `1.5px solid ${t.border}`, background: t.inputBg, cursor: "pointer", transition: "all 0.2s" }}
                                            onMouseEnter={e => { e.currentTarget.style.borderColor = t.primary; e.currentTarget.style.background = t.primaryGlow; }}
                                            onMouseLeave={e => { e.currentTarget.style.borderColor = t.border; e.currentTarget.style.background = t.inputBg; }}>
                                            <span style={{ fontSize: 15 }}>{ico}</span>
                                            <span style={{ fontSize: 11, fontWeight: 600, color: t.textMuted }}>{lbl}</span>
                                        </div>
                                    ))}
                                </div>
                            </Card>

                            <div style={{ padding: "12px 15px", borderRadius: 13, background: `${t.success}10`, border: `1px solid ${t.success}30`, display: "flex", gap: 11, alignItems: "center" }}>
                                <div style={{ width: 30, height: 30, borderRadius: "50%", background: `${t.success}20`, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 14, flexShrink: 0 }}>🔔</div>
                                <div>
                                    <div style={{ fontSize: 12, fontWeight: 700, color: t.text, marginBottom: 2 }}>You'll be notified</div>
                                    <div style={{ fontSize: 11, color: t.textMuted }}>Alert when {lawyers[selLawyer].name} completes review.</div>
                                </div>
                            </div>
                        </div>
                    </div>
                )}

                {/* ════════════════════════════════════════════════
            STEP 5 — Final Version + Export
        ════════════════════════════════════════════════ */}
                {step === 4 && (
                    <div style={{ display: "grid", gridTemplateColumns: "1fr 300px", gap: 18 }}>

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
                                    <span>🏛 Approved by {selLawyer !== null ? lawyers[selLawyer].name : "Lawyer"}</span>
                                    <span>📅 {new Date().toLocaleDateString("en-GB")}</span>
                                </div>
                            </div>

                            {/* Export actions */}
                            <div style={{ marginTop: 14 }}>
                                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr 1fr", gap: 8, marginBottom: 8 }}>
                                    {[["📄", "Generate PDF"], ["📥", "Download"], ["✉️", "Email"], ["🖨️", "Print"]].map(([ico, lbl]) => (
                                        <div key={lbl} onClick={() => { setExported(true); toast.show(`${ico} ${lbl}…`, "success"); }} style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 6, padding: "12px 8px", borderRadius: 12, border: `1.5px solid ${t.border}`, background: t.inputBg, cursor: "pointer", transition: "all 0.2s" }}
                                            onMouseEnter={e => { e.currentTarget.style.borderColor = t.primary; e.currentTarget.style.background = t.primaryGlow; }}
                                            onMouseLeave={e => { e.currentTarget.style.borderColor = t.border; e.currentTarget.style.background = t.inputBg; }}>
                                            <span style={{ fontSize: 20 }}>{ico}</span>
                                            <span style={{ fontSize: 10, fontWeight: 600, color: t.textMuted, textAlign: "center" }}>{lbl}</span>
                                        </div>
                                    ))}
                                </div>
                            </div>
                        </Card>

                        {/* Right: summary + completed workflow */}
                        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>

                            {/* Completion badge */}
                            <div style={{ textAlign: "center", padding: "20px 16px", borderRadius: 16, background: `linear-gradient(135deg,${t.primaryGlow},${t.card})`, border: `1px solid ${t.primary}30` }}>
                                <div style={{ fontSize: 42, marginBottom: 10 }}>🎉</div>
                                <div style={{ fontSize: 14, fontWeight: 800, color: t.text, fontFamily: "'Playfair Display',serif", marginBottom: 5 }}>Document Complete</div>
                                <div style={{ fontSize: 11, color: t.textMuted, marginBottom: 12 }}>Reviewed and approved by {selLawyer !== null ? lawyers[selLawyer].name : "your lawyer"}</div>
                                <Badge type="info" style={{ fontSize: 12, padding: "5px 14px" }}>● Final Version</Badge>
                            </div>

                            {/* Document summary */}
                            <Card>
                                <div style={{ fontSize: 10, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.8px", color: t.textMuted, marginBottom: 10 }}>Document Summary</div>
                                {[["Type", selectedType || "—"], ["Template", selectedDraft !== null ? DRAFTS_DATA[selectedDraft].name : "—"], ["Case Ref", caseRef || "—"], ["Reviewer", selLawyer !== null ? lawyers[selLawyer].name : "—"], ["Status", null], ["Compliance", null]].map(([k, v]) => (
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
    const [question, setQuestion] = useState("");
    const [notifs, setNotifs] = useState([
        { id: 1, text: "Court Hearing scheduled for Feb 25", read: false, type: "danger" },
        { id: 2, text: "Ahmad Raza Khan responded to your question", read: false, type: "info" },
        { id: 3, text: "NDA Agreement has been signed", read: true, type: "success" },
    ]);
    const milestones = [
        { t: "Case Filed", d: "Feb 10", s: "done", desc: "Case registered with court." },
        { t: "Evidence Review", d: "Feb 15", s: "done", desc: "All documents verified." },
        { t: "Lawyer Assigned", d: "Feb 18", s: "done", desc: "Ahmad Raza Khan assigned." },
        { t: "Court Hearing", d: "Feb 25", s: "active", desc: "Initial hearing scheduled." },
        { t: "Verdict", d: "Mar 15", s: "pending", desc: "Awaiting court decision." },
    ];
    const deadlines = [
        { title: "Submit Evidence", date: "Feb 23", days: 1 },
        { title: "File Plaint", date: "Mar 1", days: 8 },
        { title: "Pay Court Fees", date: "Mar 5", days: 12 },
    ];
    const qa = [
        { q: "What are my chances of winning?", a: "Based on evidence strength, approximately 75–80%. Strong documentation is your biggest asset.", done: true },
        { q: "Can I get interim relief?", a: null, done: false },
    ];
    const markRead = (id) => setNotifs(n => n.map(x => x.id === id ? { ...x, read: true } : x));
    return (
        <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr", gap: 18 }}>
            <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
                <Card>
                    <STitle icon="clock" sub="Case C-001 — Employment Dispute">Case Timeline</STitle>
                    <div style={{ position: "relative", paddingLeft: 20 }}>
                        <div style={{ position: "absolute", left: 28, top: 0, bottom: 0, width: 2, background: t.border, borderRadius: 2 }} />
                        {milestones.map((m, i) => {
                            const isDone = m.s === "done", isActive = m.s === "active";
                            return (
                                <div key={i} style={{ display: "flex", gap: 16, alignItems: "flex-start", marginBottom: 24, position: "relative" }}>
                                    <div style={{ width: 22, height: 22, borderRadius: "50%", background: isDone ? t.success : isActive ? t.primary : t.inputBg, border: `2px solid ${isDone ? t.success : isActive ? t.primary : t.border}`, display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0, zIndex: 1, boxShadow: isActive ? `0 0 14px ${t.primaryGlow}` : "none" }}>
                                        {isDone && <Ic n="check" s={11} c={t.mode === "dark" ? "#1A2E35" : "#fff"} />}
                                        {isActive && <div style={{ width: 8, height: 8, background: t.mode === "dark" ? "#1A2E35" : "#fff", borderRadius: "50%" }} />}
                                    </div>
                                    <div style={{ flex: 1, paddingTop: 1 }}>
                                        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                                            <div style={{ fontWeight: isActive ? 700 : 600, color: isActive ? t.primary : isDone ? t.text : t.textMuted, fontSize: 13 }}>{m.t}</div>
                                            <div style={{ fontSize: 11, color: t.textMuted }}>{m.d}</div>
                                        </div>
                                        <div style={{ fontSize: 12, color: t.textMuted, marginTop: 3 }}>{m.desc}</div>
                                        {!isDone && <button style={{ marginTop: 6, background: "none", border: "none", color: t.primary, fontSize: 11, cursor: "pointer", padding: 0 }}>+ Add Note</button>}
                                    </div>
                                </div>
                            );
                        })}
                    </div>
                </Card>
                <Card>
                    <STitle icon="msg" sub="Questions sent to your assigned lawyer">Lawyer Q&A</STitle>
                    {qa.map((item, i) => (
                        <div key={i} style={{ marginBottom: 18, background: t.inputBg, borderRadius: 14, padding: 14 }}>
                            <div style={{ fontSize: 13, fontWeight: 600, color: t.text, marginBottom: 8 }}>Q: {item.q}</div>
                            {item.a
                                ? <div style={{ fontSize: 12, color: t.textMuted, lineHeight: 1.7, padding: "10px 14px", background: item.done ? `${t.success}12` : t.inputBg, borderRadius: 10, border: `1px solid ${item.done ? t.success + "30" : t.border}` }}>A: {item.a}</div>
                                : <Badge type="warn">Awaiting Response</Badge>}
                        </div>
                    ))}
                    <div style={{ display: "flex", gap: 10, marginTop: 8 }}>
                        <ThemedInput value={question} onChange={e => setQuestion(e.target.value)} placeholder="Ask your lawyer a question..." style={{ flex: 1 }} />
                        <BtnPrimary onClick={() => setQuestion("")} style={{ padding: "10px 16px", borderRadius: 12 }}><Ic n="send" s={15} c={t.mode === "dark" ? "#1A2E35" : "#fff"} /></BtnPrimary>
                    </div>
                </Card>
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
                <Card>
                    <STitle icon="cal" sub="Upcoming legal deadlines">Deadlines</STitle>
                    {deadlines.map(d => (
                        <div key={d.title} style={{ padding: "12px 14px", borderRadius: 12, background: d.days <= 3 ? `${t.danger}12` : t.inputBg, border: `1px solid ${d.days <= 3 ? t.danger + "30" : t.border}`, marginBottom: 10 }}>
                            <div style={{ fontWeight: 600, fontSize: 13, color: d.days <= 3 ? t.danger : t.text }}>{d.title}</div>
                            <div style={{ display: "flex", justifyContent: "space-between", marginTop: 5 }}>
                                <span style={{ fontSize: 11, color: t.textMuted }}>{d.date}</span>
                                <span style={{ fontSize: 11, fontWeight: 700, color: d.days <= 3 ? t.danger : t.warn }}>{d.days}d left</span>
                            </div>
                        </div>
                    ))}
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
                        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
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

