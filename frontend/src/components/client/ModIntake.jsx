'use client';
// Paste your ModIntake.jsx code here
import React, { useState, useEffect, Fragment } from "react";
import { useT } from "./theme.js";
import { useToast } from "@/components/shared/Toast.jsx";
import { useCase } from "./CaseContext.jsx";
import Ic from "./Ic.jsx";
import { Card, BtnPrimary, BtnOutline, ThemedInput, Badge, Tooltip } from "@/components/shared/shared.jsx";

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

/* ══════════════════════════════════════════════════════
   MODULE: LEGAL INTAKE
══════════════════════════════════════════════════════ */
const ModIntake = () => {
    const t = useT();
    const toast = useToast();
    const { completeIntake, addNotification } = useCase();
    const [step, setStep] = useState(1);
    const [role, setRole] = useState("");
    const [description, setDescription] = useState("");
    const [autosave, setAutosave] = useState(false);
    const steps = ["Select Role", "Case Input", "AI Questions", "Case Summary", "Categorization"];

    // Fix #3: progress starts at 0, only reaches 100 on final submission
    // Formula: completed steps / total steps, where step 1 counts as 0 until role chosen
    const completedSteps = Math.max(0, step - 1);
    const progress = (completedSteps / steps.length) * 100;

    // Fix #3: validation rules — what must be true to ENTER each step
    const canGoToStep = (target) => {
        if (target <= step) return true;          // always allow going back or staying
        if (target === 2) return !!role;          // must pick role before case input
        if (target === 3) return !!role;          // description optional but role required
        if (target === 4) return !!role;
        if (target === 5) return !!role;
        return false;
    };

    const tryGoToStep = (target) => {
        if (canGoToStep(target)) {
            setStep(target);
        } else {
            if (target >= 2 && !role) toast.show("Please select your role first", "warn", 2500);
        }
    };

    useEffect(() => {
        if (step > 1) {
            setAutosave(true);
            const timer = setTimeout(() => {
                toast.show("Form auto-saved", "success", 2000);
                setAutosave(false);
            }, 500);
            return () => clearTimeout(timer);
        }
    }, [step]);

    const handleSubmit = () => {
        // Fix #3 + Fix #1: write completed intake data into global CaseContext
        completeIntake({
            role,
            caseType: "Employment Law",
            caseSubtype: "Wrongful Termination",
            description,
            evidenceDocs: [],
        });
        // Add a notification so the bell shows intake completion
        addNotification({
            type: "status",
            urgency: "info",
            title: "Case Intake Complete",
            date: new Date().toLocaleDateString("en-US", { month: "short", day: "numeric" }),
            time: new Date().toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" }),
            desc: `Case AIQ-2026-0042 structured and ready — ${role} · Employment Law`,
        });
        toast.show("Case submitted for attorney review! ✨", "success", 3000);
        setTimeout(() => toast.show("You'll hear from us within 2 hours", "info", 2000), 3000);
    };

    const [inputType, setInputType] = useState("voice");
    const [isRecording, setIsRecording] = useState(false);
    const [recTime, setRecTime] = useState(25);
    const formatTime = (s) => `${Math.floor(s / 60)}:${(s % 60).toString().padStart(2, '0')}`;

    return (
        <div>
            {/* Progress bar — starts at 0%, reaches 100% only after final submit */}
            <div style={{ marginBottom: 24 }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
                    <h3 style={{ fontSize: 14, fontWeight: 700, color: t.text }}>Case Intake Progress</h3>
                    <span style={{ fontSize: 13, fontWeight: 700, color: t.primary }}>{Math.round(progress)}%</span>
                </div>
                <div style={{ height: 6, background: t.inputBg, borderRadius: 4, overflow: "hidden" }}>
                    <div style={{ width: `${progress}%`, height: "100%", background: t.grad1, borderRadius: 4, transition: "width 0.5s cubic-bezier(0.4, 0, 0.2, 1)" }} />
                </div>
            </div>

            {/* Step tabs — Fix #3: locked steps show padlock, blocked clicks show toast */}
            <div style={{ display: "flex", marginBottom: 28, background: t.card, border: `1.5px solid ${t.border}`, borderRadius: 16, overflow: "hidden", boxShadow: t.shadowCard }}>
                {steps.map((s, i) => {
                    const targetStep = i + 1;
                    const act = step === targetStep;
                    const done = step > targetStep;
                    const locked = !canGoToStep(targetStep) && !done && !act;
                    return (
                        <div key={s} onClick={() => tryGoToStep(targetStep)}
                            style={{
                                flex: 1, padding: "14px 10px", textAlign: "center",
                                cursor: locked ? "not-allowed" : "pointer",
                                background: act ? t.primaryGlow : "transparent",
                                borderBottom: act ? `2.5px solid ${t.primary}` : done ? `2.5px solid ${t.success}` : "2.5px solid transparent",
                                transition: "all 0.2s",
                                opacity: locked ? 0.45 : 1,
                            }}>
                            <div style={{
                                width: 26, height: 26, borderRadius: "50%",
                                background: done ? t.success : act ? t.primary : t.inputBg,
                                color: (done || act) ? (t.mode === "dark" ? "#1A2E35" : "#fff") : t.textMuted,
                                fontSize: 11, fontWeight: 800, margin: "0 auto 6px",
                                display: "flex", alignItems: "center", justifyContent: "center",
                            }}>
                                {done ? <Ic n="check" s={12} c={t.mode === "dark" ? "#1A2E35" : "#fff"} /> : locked ? "🔒" : targetStep}
                            </div>
                            <div style={{ fontSize: 12, fontWeight: act ? 700 : 500, color: act ? t.primary : done ? t.success : t.textMuted }}>{s}</div>
                        </div>
                    );
                })}
            </div>

            {step === 1 && (
                <Card className="aFadeUp">
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 20 }}>
                        <STitle icon="user" sub="Your role determines how we structure your legal case">Select Your Role</STitle>
                        <BtnPrimary disabled={!role} onClick={() => setStep(2)} style={{ fontSize: 14, padding: "12px 32px" }}>Continue →</BtnPrimary>
                    </div>
                    <div style={{ display: "flex", gap: 16, marginBottom: 12, marginTop: 8 }}>
                        {["Plaintiff", "Defendant"].map(r => (
                            <div key={r} onClick={() => setRole(r)} style={{ flex: 1, padding: 28, borderRadius: 18, border: `2.5px solid ${role === r ? t.primary : t.border}`, background: role === r ? t.primaryGlow : "transparent", cursor: "pointer", textAlign: "center", transition: "all 0.25s cubic-bezier(0.4, 0, 0.2, 1)", transform: role === r ? "scale(1.05)" : "scale(1)", boxShadow: role === r ? `0 12px 32px ${t.primary}25` : "none" }}>
                                <div style={{ fontSize: 48, marginBottom: 14 }}>{r === "Plaintiff" ? "⚖️" : "🛡️"}</div>
                                <div style={{ fontWeight: 800, color: t.text, fontSize: 18, fontFamily: "'Playfair Display',serif", marginBottom: 4 }}>{r}</div>
                                <div style={{ fontSize: 13, color: t.textMuted, marginTop: 6 }}>{r === "Plaintiff" ? "Filing a legal claim" : "Responding to a claim"}</div>
                            </div>
                        ))}
                    </div>
                </Card>
            )}
            {step === 2 && (
                <Fragment>
                    <div className="aFadeUp" style={{ display: "flex", flexDirection: "column", gap: 24 }}>
                        {/* Top nav bar */}
                        <div style={{ display: "flex", alignItems: "center", gap: 14, padding: "14px 20px", background: t.card, border: `1.5px solid ${t.border}`, borderRadius: 16 }}>
                            <BtnOutline onClick={() => setStep(1)} style={{ fontSize: 13, padding: "10px 20px", border: "none" }}>← Back</BtnOutline>
                            <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "8px 14px", borderRadius: 20, border: `1.5px solid ${t.warn}40`, background: `${t.warn}15`, color: t.warn, fontSize: 12, fontWeight: 700 }}>
                                📁 Case AIQ-2026-0042
                            </div>
                            <div style={{ flex: 1 }}></div>
                            <BtnOutline onClick={() => toast.show("Draft saved!", "success")} style={{ fontSize: 13, padding: "10px 20px" }}>💾 Save Draft</BtnOutline>
                            <BtnPrimary onClick={() => setStep(3)} style={{ fontSize: 13, padding: "10px 24px" }}>Continue →</BtnPrimary>
                        </div>


                        <div style={{ display: "grid", gridTemplateColumns: "1.2fr 0.8fr", gap: 24 }}>
                            {/* LEFT PANEL: Input Tab */}
                            <div>
                                {/* Tabs */}
                                <div style={{ display: "inline-flex", background: t.inputBg, borderRadius: 50, padding: 4, marginBottom: 16, border: `1px solid ${t.border}` }}>
                                    {["text", "voice"].map(type => (
                                        <button key={type} onClick={() => setInputType(type)} style={{ display: "flex", alignItems: "center", gap: 8, padding: "8px 20px", borderRadius: 40, border: "none", background: inputType === type ? t.primary : "transparent", color: inputType === type ? (t.mode === "dark" ? "#1A2E35" : "#fff") : t.textMuted, fontSize: 13, fontWeight: 700, cursor: "pointer", transition: "all 0.2s" }}>
                                            <Ic n={type === "text" ? "pen" : "mic"} s={14} c={inputType === type ? (t.mode === "dark" ? "#1A2E35" : "#fff") : t.textMuted} />
                                            {type === "text" ? "Text Input" : "Voice Input"}
                                        </button>
                                    ))}
                                </div>

                                {/* Input Area */}
                                {inputType === "voice" ? (
                                    <div style={{ width: "100%", display: "flex", flexDirection: "column", gap: 16 }}>
                                        <Card style={{ padding: "40px", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", minHeight: 260 }}>
                                            <div style={{ width: 80, height: 80, borderRadius: "50%", background: t.primaryGlow, border: `2px solid ${t.primary}50`, display: "flex", alignItems: "center", justifyContent: "center", marginBottom: 20, boxShadow: `0 0 20px ${t.primaryGlow}`, cursor: "pointer", position: "relative" }} onClick={() => setIsRecording(!isRecording)}>
                                                <div style={{ position: "absolute", inset: -10, borderRadius: "50%", background: `${t.primary}20`, animation: isRecording ? "pulse 1.5s infinite" : "none" }} />
                                                <Ic n="mic" s={32} c={t.primary} />
                                            </div>
                                            {isRecording ? (
                                                <div style={{ display: "flex", gap: 4, marginBottom: 16 }}>
                                                    {[0, 1, 2, 3, 4, 5, 6, 7].map(i => <div key={i} style={{ width: 6, height: 6, borderRadius: "50%", background: t.primary, animation: `pulse 1s ${i * 0.1}s infinite` }} />)}
                                                </div>
                                            ) : (
                                                <div style={{ display: "flex", gap: 4, marginBottom: 16 }}>
                                                    {[0, 1, 2, 3, 4, 5, 6, 7].map(i => <div key={i} style={{ width: 6, height: 6, borderRadius: "50%", background: t.primary + "50" }} />)}
                                                </div>
                                            )}
                                            <div style={{ fontSize: 28, fontWeight: 800, fontFamily: "'JetBrains Mono',monospace", color: t.primary, marginBottom: 8 }}>{formatTime(recTime)}</div>
                                            <div style={{ fontSize: 13, color: t.textMuted }}>{isRecording ? "Recording in progress..." : "Recording stopped — FR-2.1.3.2. Ready to convert."}</div>

                                            <div style={{ display: "flex", gap: 12, marginTop: 16 }}>
                                                <BtnOutline style={{ padding: "8px 16px", fontSize: 12, border: `1px solid ${t.border}`, color: t.textMuted, display: "flex", alignItems: "center", gap: 6 }}><div style={{ width: 8, height: 8, background: t.textMuted }} /> Stop — FR-2.1.3.2</BtnOutline>
                                                <BtnOutline style={{ padding: "8px 16px", fontSize: 12, border: `1px solid ${t.primary}`, color: t.primary, display: "flex", alignItems: "center", gap: 6 }}>↻ Convert to Text</BtnOutline>
                                            </div>
                                        </Card>

                                        <Card style={{ padding: 20, border: `1px solid ${t.primary}50`, borderTop: `2px solid ${t.primary}`, display: "flex", flexDirection: "column" }}>
                                            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
                                                <div style={{ fontSize: 11, fontWeight: 800, color: t.primary, display: "flex", alignItems: "center", gap: 8, letterSpacing: "0.5px" }}><Ic n="bot" s={14} c={t.primary} /> AI TRANSCRIPTION — FR-2.1.3.4</div>
                                                <Badge type="success" style={{ background: `${t.success}15`, color: t.success, border: `1px solid ${t.success}40`, padding: "4px 8px", fontSize: 10 }}>LIVE</Badge>
                                            </div>
                                            <div style={{ fontSize: 13, color: t.text, lineHeight: 1.8, marginBottom: 24, flex: 1 }}>
                                                I am filing this case against my former employer XYZ Corporation for unlawful termination. I was employed from January 2022 until my termination on December 15, 2025 without any prior notice or show-cause notice as required by IERA 2012...
                                            </div>
                                            <div style={{ display: "flex", gap: 12 }}>
                                                <BtnOutline style={{ padding: "8px 16px", fontSize: 12, borderColor: t.primary, color: t.primary }}>Submit Voice Input ↑</BtnOutline>
                                                <BtnOutline style={{ padding: "8px 16px", fontSize: 12, borderColor: t.border, color: t.textMuted }}>Clear</BtnOutline>
                                            </div>
                                        </Card>
                                    </div>
                                ) : (
                                    <Card style={{ padding: "40px", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", minHeight: 260 }}>
                                        <textarea placeholder="Please describe the events leading up to your dispute in detail..." style={{ width: "100%", height: "100%", minHeight: 180, background: "transparent", border: "none", outline: "none", color: t.text, fontSize: 14, resize: "none" }} />
                                    </Card>
                                )}
                            </div>

                            {/* RIGHT PANEL: Evidence */}
                            <Card style={{ padding: "20px 24px" }}>
                                <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 20 }}>
                                    <div style={{ width: 36, height: 36, borderRadius: 10, background: t.inputBg, display: "flex", alignItems: "center", justifyContent: "center" }}><Ic n="file" s={16} c={t.textMuted} /></div>
                                    <div>
                                        <div style={{ fontSize: 15, fontWeight: 700, color: t.text }}>Attach Evidence</div>
                                        <div style={{ fontSize: 11, color: t.textMuted, marginTop: 2 }}>FR-2.1.4 — Upload & manage documents</div>
                                    </div>
                                </div>

                                <div style={{ border: `1.5px dashed ${t.border}`, borderRadius: 14, padding: "30px 20px", textAlign: "center", cursor: "pointer", transition: "all 0.2s", marginBottom: 16 }}
                                    onMouseEnter={e => { e.currentTarget.style.borderColor = t.primary; e.currentTarget.style.background = t.primaryGlow; }}
                                    onMouseLeave={e => { e.currentTarget.style.borderColor = t.border; e.currentTarget.style.background = "transparent"; }}>
                                    <div style={{ fontSize: 32, marginBottom: 12 }}>📁</div>
                                    <div style={{ fontSize: 13, color: t.textMuted, marginBottom: 4 }}>Select documents from storage</div>
                                    <div style={{ fontSize: 11, color: t.textFaint }}>PDF · DOCX · JPG · Max 25 MB</div>
                                </div>

                                {/* Uploaded Files */}
                                <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                                    {[
                                        { name: "Employment_Contract.pdf", size: "2.4 MB", type: "PDF", status: "Uploaded", statColor: "success", meta: "Signed Jan 2022", c1: t.danger },
                                        { name: "Termination_Letter.pdf", size: "512 KB", type: "PDF", status: "Uploaded", statColor: "success", meta: "Dated Dec 15, 2025", c1: t.warn },
                                        { name: "Pay_Stubs_2025.pdf", size: "1.1 MB", type: "PDF", status: "Processing", statColor: "warn", meta: "Last 3 months pay stubs", c1: t.primary },
                                    ].map((f, i) => (
                                        <div key={i} style={{ background: t.inputBg, border: `1.5px solid ${t.border}`, borderRadius: 12, padding: 14, position: "relative" }}>
                                            <div onClick={() => toast.show("File removed", "info")} style={{ position: "absolute", top: 14, right: 14, width: 24, height: 24, borderRadius: 8, background: t.card, display: "flex", alignItems: "center", justifyContent: "center", cursor: "pointer", border: `1px solid ${t.danger}40`, color: t.danger }}>✕</div>
                                            <div style={{ display: "flex", gap: 12, marginBottom: 12 }}>
                                                <div style={{ width: 34, height: 34, borderRadius: 8, background: t.card, border: `1px solid ${t.border}`, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 16 }}>
                                                    <div style={{ width: 14, height: 16, background: f.c1, borderRadius: 3 }} />
                                                </div>
                                                <div>
                                                    <div style={{ fontSize: 13, fontWeight: 700, color: t.text, marginBottom: 4 }}>{f.name}</div>
                                                    <div style={{ fontSize: 11, color: t.textMuted, display: "flex", gap: 8, alignItems: "center" }}>{f.size} · {f.type} <Badge type={f.statColor} style={{ fontSize: 10, padding: "2px 6px" }}>{f.status}</Badge></div>
                                                </div>
                                            </div>
                                            <ThemedInput defaultValue={f.meta} style={{ fontSize: 12, padding: "8px 12px", height: 32 }} />
                                        </div>
                                    ))}
                                </div>

                                {/* Footer */}
                                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 20, paddingTop: 16, borderTop: `1.5px solid ${t.border}` }}>
                                    <div style={{ fontSize: 11, color: t.textMuted }}>3 docs · 4.0 MB total — FR-2.1.4.3</div>
                                    <BtnOutline style={{ padding: "6px 14px", fontSize: 12, borderColor: t.primary, color: t.primary, borderRadius: 20, borderTopLeftRadius: 6, borderBottomLeftRadius: 20, borderTopRightRadius: 20, borderBottomRightRadius: 20 }}>+ Add More</BtnOutline>
                                </div>
                            </Card>
                        </div>
                    </div>


                </Fragment>
            )
            }
            {
                step === 3 && (
                    <div className="aFadeUp" style={{ display: "flex", flexDirection: "column", gap: 16 }}>
                        {/* Top nav */}
                        <div style={{ display: "flex", alignItems: "center", gap: 14, padding: "14px 20px", background: t.card, border: `1.5px solid ${t.border}`, borderRadius: 16 }}>
                            <BtnOutline onClick={() => setStep(2)} style={{ fontSize: 13, padding: "10px 20px" }}>← Back</BtnOutline>
                            <div style={{ flex: 1 }} />
                            <BtnPrimary onClick={() => { toast.show("✅ Questionnaire complete", "success"); setStep(4); }} style={{ fontSize: 13, padding: "10px 22px" }}>Complete & Continue →</BtnPrimary>
                        </div>
                        <div>
                            <div style={{ fontFamily: "'Fraunces',serif", fontSize: 24, fontWeight: 600, color: t.text, marginBottom: 4 }}>AI <em>Follow-up Questions</em></div>
                            <div style={{ fontSize: 13, color: t.textMuted, marginBottom: 20 }}>Our AI reviewed your input and generated targeted questions to strengthen your case — FR-2.1.5.1</div>
                        </div>

                        <div style={{ display: "grid", gridTemplateColumns: "1fr 300px", gap: 14 }}>
                            <div>
                                <div style={{ padding: "16px 20px", borderRadius: 16, background: `linear-gradient(135deg, ${t.primary}15, ${t.primary}05)`, border: `1px solid ${t.primary}30`, marginBottom: 16, display: "flex", alignItems: "flex-start", gap: 12 }}>
                                    <div style={{ width: 36, height: 36, borderRadius: "50%", background: t.primaryGlow, border: `1.5px solid ${t.primary}40`, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 18, flexShrink: 0, boxShadow: `0 0 10px ${t.primaryGlow}` }}>🤖</div>
                                    <div style={{ fontSize: 13, color: t.textDim, lineHeight: 1.6 }}>Based on your case description, I've identified <strong style={{ color: t.primary }}>6 targeted questions</strong> to strengthen your case. Answer required questions; optional ones may be skipped. — <strong style={{ color: t.primary }}>FR-2.1.5.1</strong></div>
                                </div>

                                {/* Q1 */}
                                <Card style={{ padding: 16, marginBottom: 12, border: `1px solid ${t.primary}50` }}>
                                    <div style={{ position: "absolute", top: 12, right: 12, width: 22, height: 22, borderRadius: "50%", background: t.success, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 10, color: "#071a1a", fontWeight: 700 }}>✓</div>
                                    <div style={{ display: "flex", alignItems: "flex-start", gap: 10, marginBottom: 12 }}>
                                        <div style={{ width: 24, height: 24, borderRadius: "50%", background: t.primaryGlow, border: `1.5px solid ${t.primary}40`, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 11, fontWeight: 700, color: t.primary, flexShrink: 0 }}>1</div>
                                        <div>
                                            <div style={{ fontSize: 13, color: t.text, lineHeight: 1.5, fontWeight: 600, paddingRight: 24 }}>What was your exact position at XYZ Corporation and what were your primary responsibilities?</div>
                                            <div style={{ fontSize: 11, color: t.textMuted, marginTop: 4 }}>Required · FR-2.1.5.2</div>
                                        </div>
                                    </div>
                                    <ThemedInput defaultValue="Senior Software Engineer — led backend development team of 6 members" style={{ marginBottom: 10 }} />
                                    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                                        <div style={{ width: 32, height: 32, borderRadius: "50%", border: `1.5px solid ${t.primary}40`, background: t.primaryGlow, display: "flex", alignItems: "center", justifyContent: "center", cursor: "pointer", fontSize: 14 }}>🎙</div>
                                        <span style={{ fontSize: 11, color: t.textMuted }}>or answer by voice — FR-2.1.5.2</span>
                                    </div>
                                </Card>

                                {/* Q2 */}
                                <Card style={{ padding: 16, marginBottom: 12, border: `1px solid ${t.primary}50` }}>
                                    <div style={{ position: "absolute", top: 12, right: 12, width: 22, height: 22, borderRadius: "50%", background: t.success, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 10, color: "#071a1a", fontWeight: 700 }}>✓</div>
                                    <div style={{ display: "flex", alignItems: "flex-start", gap: 10, marginBottom: 12 }}>
                                        <div style={{ width: 24, height: 24, borderRadius: "50%", background: t.primaryGlow, border: `1.5px solid ${t.primary}40`, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 11, fontWeight: 700, color: t.primary, flexShrink: 0 }}>2</div>
                                        <div>
                                            <div style={{ fontSize: 13, color: t.text, lineHeight: 1.5, fontWeight: 600, paddingRight: 24 }}>Were you given any prior warning, performance improvement plan, or show-cause notice before the termination?</div>
                                            <div style={{ fontSize: 11, color: t.textMuted, marginTop: 4 }}>Required · FR-2.1.5.2</div>
                                        </div>
                                    </div>
                                    <select style={{ width: "100%", padding: "10px 14px", borderRadius: 8, border: `1px solid ${t.border}`, background: t.inputBg, color: t.text, fontSize: 13, outline: "none", cursor: "pointer" }}>
                                        <option selected>No — No prior warning or notice was given</option>
                                        <option>Yes — Received a warning but not formal notice</option>
                                        <option>Yes — Full show-cause process was followed</option>
                                    </select>
                                    <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 10 }}>
                                        <div style={{ width: 32, height: 32, borderRadius: "50%", border: `1px solid ${t.border}`, background: t.inputBg, display: "flex", alignItems: "center", justifyContent: "center", cursor: "pointer", fontSize: 14 }}>🎙</div>
                                    </div>
                                </Card>

                                {/* Q3 */}
                                <Card style={{ padding: 16, marginBottom: 12 }}>
                                    <div style={{ display: "flex", alignItems: "flex-start", gap: 10, marginBottom: 12 }}>
                                        <div style={{ width: 24, height: 24, borderRadius: "50%", background: t.primaryGlow, border: `1.5px solid ${t.primary}40`, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 11, fontWeight: 700, color: t.primary, flexShrink: 0 }}>3</div>
                                        <div>
                                            <div style={{ fontSize: 13, color: t.text, lineHeight: 1.5, fontWeight: 600, paddingRight: 24 }}>What was your last drawn salary and are there any outstanding dues — gratuity, EOBI, or earned leave encashment?</div>
                                            <div style={{ fontSize: 11, color: t.textMuted, marginTop: 4 }}>Required · FR-2.1.5.2</div>
                                        </div>
                                    </div>
                                    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, marginBottom: 12 }}>
                                        <div>
                                            <div style={{ fontSize: 10, fontWeight: 700, letterSpacing: "1px", color: t.textMuted, textTransform: "uppercase", marginBottom: 6 }}>Monthly Salary (PKR)</div>
                                            <ThemedInput placeholder="e.g. 150,000" />
                                        </div>
                                        <div>
                                            <div style={{ fontSize: 10, fontWeight: 700, letterSpacing: "1px", color: t.textMuted, textTransform: "uppercase", marginBottom: 6 }}>Outstanding Dues</div>
                                            <ThemedInput placeholder="e.g. 3 months gratuity" />
                                        </div>
                                    </div>
                                    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                                        <div style={{ width: 32, height: 32, borderRadius: "50%", border: `1px solid ${t.border}`, background: t.inputBg, display: "flex", alignItems: "center", justifyContent: "center", cursor: "pointer", fontSize: 14 }}>🎙</div>
                                        <span style={{ fontSize: 11, color: t.textMuted }}>or by voice</span>
                                        <div style={{ flex: 1 }} />
                                        <span style={{ fontSize: 11, color: t.textMuted, cursor: "pointer" }}>Skip › — FR-2.1.5.3</span>
                                    </div>
                                </Card>

                            </div>

                            {/* Sidebar Q Progress */}
                            <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
                                <Card style={{ padding: 20 }}>
                                    <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 16 }}>
                                        <div style={{ width: 34, height: 34, borderRadius: 10, background: t.primaryGlow, border: `1px solid ${t.primary}40`, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 16 }}>📊</div>
                                        <div>
                                            <div style={{ fontSize: 14, fontWeight: 700, color: t.text }}>Question Progress</div>
                                            <div style={{ fontSize: 11, color: t.textMuted }}>FR-2.1.5.4 — Complete required</div>
                                        </div>
                                    </div>

                                    <div style={{ height: 6, borderRadius: 6, background: t.inputBg, overflow: "hidden", marginBottom: 6 }}>
                                        <div style={{ height: "100%", width: "33%", background: `linear-gradient(90deg, ${t.primary}, ${t.primaryHover || t.primary})`, borderRadius: 6 }} />
                                    </div>
                                    <div style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 11, color: t.primary, fontWeight: 700, marginBottom: 16 }}>2 / 6 Answered</div>

                                    {[
                                        { n: "Designation & Role", s: "Done", sc: t.success },
                                        { n: "Warning / Notice", s: "Done", sc: t.success },
                                        { n: "Salary & Dues", s: "Required", sc: t.warn },
                                        { n: "Reason for Termination", s: "Optional", sc: t.textMuted },
                                        { n: "Internal Reporting", s: "Optional", sc: t.textMuted },
                                        { n: "Legal Remedy Sought", s: "Required", sc: t.warn },
                                    ].map((item, idx) => (
                                        <div key={idx} style={{ display: "flex", alignItems: "center", gap: 10, padding: "10px 12px", borderRadius: 10, background: t.inputBg, border: `1px solid ${item.s === "Done" ? t.success + "40" : t.border}`, marginBottom: 6 }}>
                                            <div style={{ width: 8, height: 8, borderRadius: "50%", background: item.s === "Done" ? t.success : (item.s === "Required" ? t.warn : t.border), boxShadow: item.s === "Done" ? `0 0 6px ${t.success}60` : "none" }} />
                                            <span style={{ fontSize: 12, color: t.text, flex: 1 }}>{item.n}</span>
                                            <Badge type={item.s === "Done" ? "success" : (item.s === "Required" ? "warn" : "default")} style={{ fontSize: 10, padding: "2px 6px" }}>{item.s}</Badge>
                                        </div>
                                    ))}
                                </Card>

                                <Card style={{ padding: 20, border: `1px solid ${t.primary}50`, background: t.primaryGlow }}>
                                    <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 16 }}>
                                        <div style={{ width: 34, height: 34, borderRadius: 10, background: t.primaryGlow, border: `1px solid ${t.primary}40`, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 16 }}>📋</div>
                                        <div>
                                            <div style={{ fontSize: 14, fontWeight: 700, color: t.text }}>Case Preview</div>
                                            <div style={{ fontSize: 11, color: t.textMuted }}>Building from answers</div>
                                        </div>
                                    </div>

                                    <div style={{ display: "flex", justifyContent: "space-between", padding: "8px 0", borderBottom: `1px solid ${t.border}`, fontSize: 12 }}>
                                        <span style={{ color: t.textMuted }}>Case Type</span><Badge type="info">Employment</Badge>
                                    </div>
                                    <div style={{ display: "flex", justifyContent: "space-between", padding: "8px 0", borderBottom: `1px solid ${t.border}`, fontSize: 12 }}>
                                        <span style={{ color: t.textMuted }}>Your Role</span><Badge type="primary">Plaintiff</Badge>
                                    </div>
                                    <div style={{ display: "flex", justifyContent: "space-between", padding: "8px 0", borderBottom: `1px solid ${t.border}`, fontSize: 12 }}>
                                        <span style={{ color: t.textMuted }}>Evidence</span><span style={{ color: t.text, fontWeight: 600 }}>3 documents</span>
                                    </div>
                                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", paddingTop: 8, fontSize: 12 }}>
                                        <span style={{ color: t.textMuted }}>AI Confidence</span>
                                        <div style={{ flex: 1, margin: "0 10px", height: 6, borderRadius: 6, background: t.inputBg, overflow: "hidden" }}>
                                            <div style={{ height: "100%", width: "68%", background: `linear-gradient(90deg, ${t.primary}, ${t.primaryHover || t.primary})` }} />
                                        </div>
                                        <span style={{ fontFamily: "'JetBrains Mono',monospace", color: t.primary, fontWeight: 700 }}>68%</span>
                                    </div>
                                </Card>
                            </div>
                        </div>
                    </div>
                )
            }
            {
                step === 4 && (
                    <div className="aFadeUp" style={{ display: "flex", flexDirection: "column", gap: 16 }}>
                        {/* Top nav */}
                        <div style={{ display: "flex", alignItems: "center", gap: 14, padding: "14px 20px", background: t.card, border: `1.5px solid ${t.border}`, borderRadius: 16 }}>
                            <BtnOutline onClick={() => setStep(3)} style={{ fontSize: 13, padding: "10px 20px" }}>← Back</BtnOutline>
                            <div style={{ flex: 1 }} />
                            <BtnPrimary onClick={() => { toast.show("✅ Case saved! Ref: AIQ-2026-0042", "success"); setStep(5); }} style={{ fontSize: 13, padding: "10px 22px" }}>Confirm & Save Case →</BtnPrimary>
                        </div>
                        <div>
                            <div style={{ fontFamily: "'Fraunces',serif", fontSize: 24, fontWeight: 600, color: t.text, marginBottom: 4 }}>AI-Generated <em>Case Summary</em></div>
                            <div style={{ fontSize: 13, color: t.textMuted, marginBottom: 20 }}>Review, edit and confirm your structured case before saving — Module 2.2</div>
                        </div>

                        <div style={{ display: "grid", gridTemplateColumns: "1fr 300px", gap: 14 }}>
                            <Card style={{ padding: 0, overflow: "hidden", display: "flex", flexDirection: "column" }}>
                                <div style={{ padding: "16px 20px", borderBottom: `1px solid ${t.border}`, background: t.inputBg, display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                                    <div>
                                        <div style={{ fontSize: 14, fontWeight: 600, letterSpacing: "-0.2px", color: t.text }}>Structured Case Summary — FR-2.2.1.5</div>
                                        <div style={{ fontSize: 11, color: t.textMuted, marginTop: 2 }}>Ref: AIQ-2026-0042 · Auto-generated by AI</div>
                                    </div>
                                    <div style={{ display: "flex", gap: 8 }}>
                                        <BtnOutline onClick={() => toast.show("✏️ Edit mode")} style={{ padding: "6px 12px", fontSize: 11 }}>✏️ Edit All</BtnOutline>
                                        <BtnOutline onClick={() => toast.show("➕ Field added")} style={{ padding: "6px 12px", fontSize: 11 }}>➕ Add</BtnOutline>
                                        <BtnOutline onClick={() => toast.show("💾 Case saved")} style={{ padding: "6px 12px", fontSize: 11 }}>💾 Save</BtnOutline>
                                    </div>
                                </div>
                                <div style={{ padding: 20, maxHeight: 480, overflowY: "auto", display: "flex", flexDirection: "column", gap: 12 }}>

                                    {[
                                        { icon: "👤", title: "Parties — FR-2.2.2.1", body: "<strong>Plaintiff:</strong> Muhammad Usama, Senior Software Engineer, Lahore<br/><strong>Defendant:</strong> XYZ Corporation (Pvt.) Ltd., SECP Reg. No. 1234, Islamabad", c: t.primary },
                                        { icon: "⚖️", title: "Legal Issues — FR-2.2.1.3", body: "1. Unlawful termination without show-cause notice (Section 25-B, IERA 2012)<br/>2. Non-payment of statutory dues: Gratuity, EOBI contributions<br/>3. Violation of due process under Industrial & Employment Relations Act 2012<br/>4. Breach of employment contract dated January 2022", c: t.primary },
                                        { icon: "📋", title: "Legal Facts — FR-2.2.1.2", body: "<strong>Employment Period:</strong> January 2022 – December 15, 2025 (~4 years)<br/><strong>Termination Date:</strong> December 15, 2025<br/><strong>Notice Given:</strong> None — No show-cause notice, no prior warning<br/><strong>Outstanding Dues:</strong> Gratuity (3 months), EOBI contributions, earned leave<br/><strong>Applicable Law:</strong> IERA 2012, Contract Act 1872", c: t.primary },
                                        { icon: "📝", title: "Case Description — FR-2.2.2.2", body: "The plaintiff M. Usama was employed by XYZ Corporation from January 2022 as Senior Software Engineer. On December 15, 2025, the plaintiff was abruptly terminated without any prior notice, show-cause proceedings, or opportunity to be heard, in direct violation of Section 25-B of IERA 2012. The defendant also failed to pay statutory dues including gratuity and EOBI contributions. The plaintiff seeks reinstatement and full compensation for unlawful termination.", c: t.primary },
                                        { icon: "⚠️", title: "Missing Information — FR-2.2.2.3", body: `<span style="color: ${t.warn}">• Exact salary amount not provided — recommended to add for stronger claim<br/>• Witness details not included — optional but strengthens case</span>`, c: t.warn, b: `${t.warn}15`, border: `${t.warn}40` },
                                        { icon: "🎯", title: "Relief Sought — FR-2.2.2.1", body: "1. Reinstatement to former position with back pay<br/>2. Payment of all outstanding statutory dues (Gratuity, EOBI)<br/>3. Compensation for wrongful termination damages<br/>4. Legal costs of proceedings", c: t.primary },
                                    ].map((s, idx) => (
                                        <div key={idx} style={{ background: s.b || t.inputBg, border: `1px solid ${s.border || t.border}`, borderRadius: 12, padding: "16px 20px" }}>
                                            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
                                                <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: "1px", textTransform: "uppercase", color: s.c }}>{s.icon} {s.title}</div>
                                                <span onClick={() => toast.show("Editing...")} style={{ fontSize: 11, color: t.textMuted, padding: "4px 10px", borderRadius: 20, border: `1px solid ${t.border}`, cursor: "pointer" }}>✏️ Edit</span>
                                            </div>
                                            <div style={{ fontSize: 13, color: t.textDim, lineHeight: 1.7 }} dangerouslySetInnerHTML={{ __html: s.body }} />
                                        </div>
                                    ))}

                                </div>

                            </Card>

                            <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
                                <Card style={{ padding: 20, border: `1px solid ${t.primary}50`, background: t.primaryGlow }}>
                                    <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 16 }}>
                                        <div style={{ width: 34, height: 34, borderRadius: 10, background: t.primaryGlow, border: `1px solid ${t.primary}40`, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 16 }}>📊</div>
                                        <div>
                                            <div style={{ fontSize: 14, fontWeight: 700, color: t.text }}>Case Overview</div>
                                            <div style={{ fontSize: 11, color: t.textMuted }}>FR-2.2.2.4 — Confirm details</div>
                                        </div>
                                    </div>

                                    <div style={{ display: "flex", justifyContent: "space-between", padding: "8px 0", borderBottom: `1px solid ${t.border}`, fontSize: 12 }}>
                                        <span style={{ color: t.textMuted }}>Case Ref</span><span style={{ fontFamily: "'JetBrains Mono',monospace", color: t.text, fontWeight: 600 }}>AIQ-2026-0042</span>
                                    </div>
                                    <div style={{ display: "flex", justifyContent: "space-between", padding: "8px 0", borderBottom: `1px solid ${t.border}`, fontSize: 12 }}>
                                        <span style={{ color: t.textMuted }}>Type</span><Badge type="info">Employment</Badge>
                                    </div>
                                    <div style={{ display: "flex", justifyContent: "space-between", padding: "8px 0", borderBottom: `1px solid ${t.border}`, fontSize: 12 }}>
                                        <span style={{ color: t.textMuted }}>Role</span><Badge type="primary">Plaintiff</Badge>
                                    </div>
                                    <div style={{ display: "flex", justifyContent: "space-between", padding: "8px 0", borderBottom: `1px solid ${t.border}`, fontSize: 12 }}>
                                        <span style={{ color: t.textMuted }}>Evidence</span><span style={{ color: t.text, fontWeight: 600 }}>3 documents</span>
                                    </div>
                                    <div style={{ display: "flex", justifyContent: "space-between", padding: "8px 0", borderBottom: `1px solid ${t.border}`, fontSize: 12 }}>
                                        <span style={{ color: t.textMuted }}>Legal Issues</span><span style={{ color: t.text, fontWeight: 600 }}>4 identified</span>
                                    </div>
                                    <div style={{ display: "flex", justifyContent: "space-between", padding: "8px 0", borderBottom: `1px solid ${t.border}`, fontSize: 12 }}>
                                        <span style={{ color: t.textMuted }}>Relief</span><span style={{ color: t.text, fontWeight: 600 }}>Reinstatement + Comp.</span>
                                    </div>
                                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", paddingTop: 8, fontSize: 12 }}>
                                        <span style={{ color: t.textMuted }}>AI Confidence</span>
                                        <div style={{ flex: 1, margin: "0 10px", height: 6, borderRadius: 6, background: t.inputBg, overflow: "hidden" }}>
                                            <div style={{ height: "100%", width: "87%", background: `linear-gradient(90deg, ${t.primary}, ${t.primaryHover || t.primary})` }} />
                                        </div>
                                        <span style={{ fontFamily: "'JetBrains Mono',monospace", color: t.primary, fontWeight: 700 }}>87%</span>
                                    </div>
                                </Card>

                                <Card style={{ padding: 20 }}>
                                    <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 16 }}>
                                        <div style={{ width: 34, height: 34, borderRadius: 10, background: t.inputBg, border: `1px solid ${t.border}`, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 16 }}>🔍</div>
                                        <div>
                                            <div style={{ fontSize: 14, fontWeight: 700, color: t.text }}>Applicable Laws</div>
                                            <div style={{ fontSize: 11, color: t.textMuted }}>AI-identified statutes</div>
                                        </div>
                                    </div>

                                    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                                        {[
                                            { t: "Section 25-B IERA 2012", d: "Show-cause notice requirements" },
                                            { t: "Section 46 IERA 2012", d: "Employer obligations on termination" },
                                            { t: "Contract Act 1872 — S.73", d: "Compensation for breach of contract" },
                                        ].map(lw => (
                                            <div key={lw.t} style={{ padding: "10px 14px", borderRadius: 10, background: t.inputBg, border: `1px solid ${t.border}` }}>
                                                <div style={{ fontSize: 12, fontWeight: 700, color: t.primary, marginBottom: 2 }}>{lw.t}</div>
                                                <div style={{ fontSize: 11, color: t.textMuted }}>{lw.d}</div>
                                            </div>
                                        ))}
                                    </div>
                                </Card>
                            </div>
                        </div>
                    </div>
                )}
            {step === 5 && (
                <div className="aFadeUp" style={{ display: "flex", flexDirection: "column", gap: 16 }}>
                    {/* Top nav */}
                    <div style={{ display: "flex", alignItems: "center", gap: 14, padding: "14px 20px", background: t.card, border: `1.5px solid ${t.border}`, borderRadius: 16 }}>
                        <BtnOutline onClick={() => setStep(4)} style={{ fontSize: 13, padding: "10px 20px" }}>← Back</BtnOutline>
                        <div style={{ flex: 1 }} />
                        <BtnPrimary onClick={() => { toast.show("🎉 Case fully structured!"); handleSubmit(); }} style={{ fontSize: 13, padding: "10px 22px" }}>🎉 Complete Case Intake →</BtnPrimary>
                    </div>
                    <div>
                        <div style={{ fontFamily: "'Fraunces',serif", fontSize: 24, fontWeight: 600, color: t.text, marginBottom: 4 }}>Case <em>Categorization</em></div>
                        <div style={{ fontSize: 13, color: t.textMuted, marginBottom: 20 }}>AI identified your case category. Confirm or update to reveal category-specific legal fields — Module 2.2.3</div>
                    </div>

                    <div style={{ display: "grid", gridTemplateColumns: "1fr 300px", gap: 14 }}>
                        <div>
                            <div style={{ padding: "16px 20px", borderRadius: 16, background: `linear-gradient(135deg, ${t.primary}15, ${t.primary}05)`, border: `1px solid ${t.primary}30`, marginBottom: 16, display: "flex", alignItems: "center", gap: 12 }}>
                                <div style={{ fontSize: 18 }}>🤖</div>
                                <div style={{ fontSize: 13, color: t.textDim, lineHeight: 1.6 }}>AI identified your case as <strong style={{ color: t.primary }}>Employment Law</strong> based on your description. Confirm or select a different category — <strong style={{ color: t.primary }}>FR-2.2.3.1</strong></div>
                            </div>

                            {/* Category Grid */}
                            <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 12, marginBottom: 20 }}>
                                {[
                                    { id: "civil", i: "⚖️", n: "Civil Law", d: "Property disputes, contracts, personal injury, defamation" },
                                    { id: "criminal", i: "🚔", n: "Criminal Law", d: "FIR filing, bail applications, criminal defense matters" },
                                    { id: "employment", i: "💼", n: "Employment Law", d: "Wrongful termination, labour disputes, workplace rights", sel: true },
                                    { id: "property", i: "🏠", n: "Property Law", d: "Land disputes, ownership, title deed issues, rental" },
                                    { id: "family", i: "👨‍👩‍👧", n: "Family Law", d: "Divorce, custody, inheritance, guardianship matters" },
                                    { id: "corporate", i: "🏢", n: "Corporate Law", d: "Business disputes, NDA breaches, partnership issues" },
                                ].map(c => (
                                    <Card key={c.id} style={{ padding: "20px 16px", textAlign: "center", cursor: "pointer", border: c.sel ? `1.5px solid ${t.primary}` : `1.5px solid ${t.border}`, background: c.sel ? `linear-gradient(135deg, ${t.primary}15, ${t.primaryGlow})` : t.card, boxShadow: c.sel ? `0 0 20px ${t.primary}30` : t.shadowCard }}>
                                        {c.sel && <div style={{ position: "absolute", top: 12, right: 12, width: 22, height: 22, borderRadius: "50%", background: t.primary, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 10, color: "#071a1a", fontWeight: 700 }}>✓</div>}
                                        <div style={{ fontSize: 26, marginBottom: 12 }}>{c.i}</div>
                                        <div style={{ fontSize: 14, fontWeight: 700, color: c.sel ? t.primary : t.text, marginBottom: 4 }}>{c.n}</div>
                                        <div style={{ fontSize: 11, color: t.textMuted, lineHeight: 1.5 }}>{c.d}</div>
                                    </Card>
                                ))}
                            </div>

                            <Card style={{ padding: 24 }}>
                                <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 20 }}>
                                    <div style={{ width: 34, height: 34, borderRadius: 10, background: t.inputBg, border: `1px solid ${t.border}`, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 16 }}>💼</div>
                                    <div>
                                        <div style={{ fontSize: 14, fontWeight: 700, color: t.text }}>Employment Law — Specific Fields</div>
                                        <div style={{ fontSize: 11, color: t.textMuted }}>FR-2.2.3.3 — Category-specific information</div>
                                    </div>
                                </div>

                                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
                                    <div>
                                        <label style={{ fontSize: 11, fontWeight: 700, letterSpacing: "1px", color: t.textMuted, textTransform: "uppercase", display: "block", marginBottom: 6 }}>Type of Labour Dispute</label>
                                        <select style={{ width: "100%", padding: "10px 14px", borderRadius: 8, border: `1px solid ${t.border}`, background: t.inputBg, color: t.text, fontSize: 13, outline: "none", cursor: "pointer" }}><option>Wrongful Termination</option><option>Salary Dispute</option></select>
                                    </div>
                                    <div>
                                        <label style={{ fontSize: 11, fontWeight: 700, letterSpacing: "1px", color: t.textMuted, textTransform: "uppercase", display: "block", marginBottom: 6 }}>Court / Forum</label>
                                        <select style={{ width: "100%", padding: "10px 14px", borderRadius: 8, border: `1px solid ${t.border}`, background: t.inputBg, color: t.text, fontSize: 13, outline: "none", cursor: "pointer" }}><option>NIRC / Labour Court</option><option>High Court</option></select>
                                    </div>
                                    <div>
                                        <label style={{ fontSize: 11, fontWeight: 700, letterSpacing: "1px", color: t.textMuted, textTransform: "uppercase", display: "block", marginBottom: 6 }}>Employment Duration</label>
                                        <ThemedInput defaultValue="4 Years (Jan 2022 – Dec 2025)" />
                                    </div>
                                    <div>
                                        <label style={{ fontSize: 11, fontWeight: 700, letterSpacing: "1px", color: t.textMuted, textTransform: "uppercase", display: "block", marginBottom: 6 }}>Applicable Statute</label>
                                        <select style={{ width: "100%", padding: "10px 14px", borderRadius: 8, border: `1px solid ${t.border}`, background: t.inputBg, color: t.text, fontSize: 13, outline: "none", cursor: "pointer" }}><option>IERA 2012</option><option>Factories Act 1934</option></select>
                                    </div>
                                </div>

                            </Card>
                        </div>

                        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
                            <Card style={{ padding: 20, border: `1px solid ${t.primary}50`, background: t.primaryGlow, textAlign: "center" }}>
                                <div style={{ fontSize: 40, marginBottom: 12 }}>✅</div>
                                <div style={{ fontFamily: "'Fraunces',serif", fontSize: 18, fontWeight: 600, color: t.primary, marginBottom: 6 }}>Case Intake Complete</div>
                                <div style={{ fontSize: 12, color: t.textMuted, marginBottom: 20 }}>Your case is structured and ready for review</div>

                                <div style={{ textAlign: "left" }}>
                                    <div style={{ display: "flex", justifyContent: "space-between", padding: "8px 0", borderBottom: `1px solid ${t.border}`, fontSize: 12 }}>
                                        <span style={{ color: t.textMuted }}>Case Ref</span><span style={{ fontFamily: "'JetBrains Mono',monospace", color: t.text, fontWeight: 600 }}>AIQ-2026-0042</span>
                                    </div>
                                    <div style={{ display: "flex", justifyContent: "space-between", padding: "8px 0", borderBottom: `1px solid ${t.border}`, fontSize: 12 }}>
                                        <span style={{ color: t.textMuted }}>Category</span><Badge type="info">Employment Law</Badge>
                                    </div>
                                    <div style={{ display: "flex", justifyContent: "space-between", padding: "8px 0", borderBottom: `1px solid ${t.border}`, fontSize: 12 }}>
                                        <span style={{ color: t.textMuted }}>Sub-type</span><span style={{ color: t.text, fontWeight: 600 }}>Wrongful Termination</span>
                                    </div>
                                    <div style={{ display: "flex", justifyContent: "space-between", padding: "8px 0", borderBottom: `1px solid ${t.border}`, fontSize: 12 }}>
                                        <span style={{ color: t.textMuted }}>Status</span><Badge type="success">Ready</Badge>
                                    </div>
                                </div>

                                <BtnPrimary onClick={() => toast.show("Finding matching lawyers...")} style={{ width: "100%", marginTop: 20, padding: 14, fontSize: 14 }}>Find a Lawyer →</BtnPrimary>
                            </Card>

                            <Card style={{ padding: 20 }}>
                                <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 16 }}>
                                    <div style={{ width: 34, height: 34, borderRadius: 10, background: t.inputBg, border: `1px solid ${t.border}`, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 16 }}>📄</div>
                                    <div>
                                        <div style={{ fontSize: 14, fontWeight: 700, color: t.text }}>Export Case</div>
                                    </div>
                                </div>

                                <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                                    <BtnOutline onClick={() => toast.show("Generating PDF...")} style={{ padding: "10px", fontSize: 12, justifyContent: "center" }}>📄 Download Case PDF</BtnOutline>
                                    <BtnOutline onClick={() => toast.show("Opening email client...")} style={{ padding: "10px", fontSize: 12, justifyContent: "center" }}>✉️ Email Summary</BtnOutline>
                                    <BtnOutline onClick={() => toast.show("Printing...")} style={{ padding: "10px", fontSize: 12, justifyContent: "center" }}>🖨️ Print</BtnOutline>
                                </div>
                            </Card>
                        </div>
                    </div>
                </div>
            )
            }
        </div >
    );
};

export default ModIntake;