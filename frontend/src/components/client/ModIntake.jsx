'use client';
import React, { useState, useEffect, useRef, Fragment } from "react";
import { useRouter } from "next/navigation";
import { useT } from "./theme.js";
import { useToast } from "@/components/shared/Toast.jsx";
import { useCase } from "./CaseContext.jsx";
import Ic from "./Ic.jsx";
import { Card, BtnPrimary, BtnOutline, ThemedInput, Badge, Tooltip } from "@/components/shared/shared.jsx";
import { intakeStart, intakeSaveStep, intakeConvert, intakeGet, intakeClarify, transcribeAudio } from "@/lib/api.js";

// Encode Float32 PCM as 16-bit mono WAV (no ffmpeg on backend)
function _pcmToWav(samples, sampleRate) {
    const buf = new ArrayBuffer(44 + samples.length * 2);
    const view = new DataView(buf);
    const write4 = (off, str) => [...str].forEach((c, i) => view.setUint8(off + i, c.charCodeAt(0)));
    write4(0, "RIFF");  view.setUint32(4, 36 + samples.length * 2, true);
    write4(8, "WAVE");  write4(12, "fmt ");
    view.setUint32(16, 16, true);   view.setUint16(20, 1, true);
    view.setUint16(22, 1, true);    view.setUint32(24, sampleRate, true);
    view.setUint32(28, sampleRate * 2, true);  view.setUint16(32, 2, true);
    view.setUint16(34, 16, true);   write4(36, "data");
    view.setUint32(40, samples.length * 2, true);
    for (let i = 0; i < samples.length; i++)
        view.setInt16(44 + i * 2, Math.max(-32768, Math.min(32767, samples[i] * 32768)), true);
    return new Blob([buf], { type: "audio/wav" });
}

const PROVINCES = [
    { value: "punjab",      label: "Punjab" },
    { value: "sindh",       label: "Sindh" },
    { value: "kpk",         label: "KPK (Khyber Pakhtunkhwa)" },
    { value: "balochistan", label: "Balochistan" },
    { value: "federal",     label: "Federal (ICT / National)" },
];

const CASE_TYPES = [
    { value: "civil",          label: "Civil Law" },
    { value: "criminal",       label: "Criminal Law" },
    { value: "family",         label: "Family Law" },
    { value: "constitutional", label: "Constitutional Law" },
];

const URGENCY_LEVELS = [
    { value: "low",    label: "Low — No immediate deadline" },
    { value: "medium", label: "Medium — Within a month" },
    { value: "high",   label: "High — Within a week" },
    { value: "urgent", label: "Urgent — Immediate action needed" },
];

const RISK_COLORS = { low: "success", medium: "warn", high: "danger", urgent: "danger" };

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
    const t      = useT();
    const toast  = useToast();
    const router = useRouter();
    const { completeIntake, addNotification } = useCase();
    const [step, setStep] = useState(1);

    // ── Core intake fields ─────────────────────────────────────────
    const [role, setRole] = useState("");
    const [province, setProvince] = useState("");
    const [caseTypeInput, setCaseTypeInput] = useState("civil");
    const [urgency, setUrgency] = useState("medium");
    const [description, setDescription] = useState("");

    // ── Backend session ────────────────────────────────────────────
    const [intakeToken, setIntakeToken] = useState(null);
    const [intakeSubmitting, setIntakeSubmitting] = useState(false);
    const [converting, setConverting] = useState(false);
    const [caseId, setCaseId] = useState(null);

    // ── AI output ─────────────────────────────────────────────────
    const [aiStructured, setAiStructured] = useState(null);

    // ── P2: Multi-round AI clarification ──────────────────────────
    const [clarifyLoading, setClarifyLoading] = useState(false);
    const [clarifyQ1, setClarifyQ1]           = useState("");
    const [clarifyA1, setClarifyA1]           = useState("");
    const [clarifyQ2, setClarifyQ2]           = useState("");
    const [clarifyA2, setClarifyA2]           = useState("");
    const [clarifyQ3, setClarifyQ3]           = useState("");
    const [clarifyA3, setClarifyA3]           = useState("");
    const [clarifyQ4, setClarifyQ4]           = useState("");
    const [clarifyA4, setClarifyA4]           = useState("");
    const [clarifyRound, setClarifyRound]     = useState(0);  // 0=loading 1=Q1 2=Q2 3=Q3 4=Q4 5=done
    const [clarifyDone, setClarifyDone]       = useState(false);

    // ── Evidence + desired outcome (collected in step 2, saved on convert) ──
    const [hasEvidence, setHasEvidence]       = useState(false);
    const [evidenceDesc, setEvidenceDesc]     = useState("");
    const [desiredOutcome, setDesiredOutcome] = useState("");

    // ── UI helpers ─────────────────────────────────────────────────
    const [autosave, setAutosave] = useState(false);
    const steps = ["Select Role", "Case Input", "AI Questions", "Case Summary", "Categorization"];
    const completedSteps = Math.max(0, step - 1);
    const progress = (completedSteps / steps.length) * 100;

    const canGoToStep = (target) => {
        if (target <= step) return true;
        if (target === 2) return !!role && !!province;
        if (target >= 3) return !!role && !!province;
        return false;
    };

    const tryGoToStep = (target) => {
        if (canGoToStep(target)) {
            setStep(target);
        } else {
            if (!role) toast.show("Please select your role first", "warn", 2500);
            else if (!province) toast.show("Please select your province", "warn", 2500);
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

    // Start or resume intake session on mount
    useEffect(() => {
        const saved = typeof window !== "undefined" && localStorage.getItem("aai-intake-token");
        if (saved) {
            setIntakeToken(saved);
        } else {
            intakeStart().then(({ data, error }) => {
                if (data?.session_token) {
                    setIntakeToken(data.session_token);
                    localStorage.setItem("aai-intake-token", data.session_token);
                } else if (error) {
                    console.warn("Intake start failed:", error);
                }
            });
        }
    }, []);

    // Trigger clarify fetch whenever step 3 is reached via tab navigation
    // (handleStep2Continue sets clarifyLoading=true before its own fetch, so this
    // guard prevents double-firing on the normal Continue → path)
    useEffect(() => {
        if (step !== 3 || clarifyDone || clarifyRound !== 0 || clarifyLoading || !intakeToken) return;
        setClarifyLoading(true);
        intakeClarify(intakeToken, null).then(({ data, error }) => {
            if (error || !data) { setClarifyDone(true); setClarifyRound(5); }
            else if (data.done)  { setClarifyDone(true); setClarifyRound(5); }
            else if (data.question) { setClarifyQ1(data.question); setClarifyRound(1); }
            setClarifyLoading(false);
        });
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [step, intakeToken]);

    // ── Step 1 → 2: save province ─────────────────────────────────
    const handleStep1Continue = async () => {
        if (!role)     { toast.show("Please select your role first", "warn", 2500); return; }
        if (!province) { toast.show("Please select your province", "warn", 2500); return; }
        if (intakeToken) {
            const { error } = await intakeSaveStep(intakeToken, 1, { province });
            if (error) toast.show("Could not save — check your connection and try again.", "error", 3000);
        }
        setStep(2);
    };

    // ── Step 2 → 3: save case_type + urgency + description, fetch Q1 ──
    const handleStep2Continue = async () => {
        const desc = description.trim() || voiceTranscript.trim();
        if (!desc) {
            toast.show("Please describe your legal issue before continuing.", "warn", 2500);
            return;
        }
        if (intakeToken) {
            const r2 = await intakeSaveStep(intakeToken, 2, { case_type: caseTypeInput, urgency });
            const r3 = await intakeSaveStep(intakeToken, 3, {
                incident_description: desc,
                incident_date: null,
                incident_location: null,
            });
            if (r2.error || r3.error) toast.show("Could not save — check your connection and try again.", "error", 3000);
        }
        setStep(3);
        // P2 — fetch Q1 immediately after entering step 3
        if (intakeToken) {
            setClarifyLoading(true);
            setClarifyRound(0);
            const { data, error } = await intakeClarify(intakeToken, null);
            if (error || !data) {
                // API failure — skip clarification so user can still proceed
                setClarifyDone(true);
                setClarifyRound(5);
            } else if (data.done) {
                setClarifyDone(true);
                setClarifyRound(5);
            } else if (data.question) {
                setClarifyQ1(data.question);
                setClarifyRound(1);
            }
            setClarifyLoading(false);
        }
    };

    // ── Step 3: current answer getter ─────────────────────────────
    const getCurrentAnswer = () => {
        if (clarifyRound === 1) return clarifyA1;
        if (clarifyRound === 2) return clarifyA2;
        if (clarifyRound === 3) return clarifyA3;
        return "";
    };

    // ── Step 3 Qn answered → fetch next question (rounds 1–3) ────
    const handleClarifyNext = async () => {
        if (!getCurrentAnswer().trim()) {
            toast.show("Please answer the question before continuing.", "warn", 2000);
            return;
        }
        if (!intakeToken) { setClarifyRound(5); setClarifyDone(true); return; }
        setClarifyLoading(true);
        const { data, error } = await intakeClarify(intakeToken, getCurrentAnswer());
        if (error || !data || data.done || !data.question) {
            setClarifyDone(true);
            setClarifyRound(5);
        } else {
            if (clarifyRound === 1) { setClarifyQ2(data.question); setClarifyRound(2); }
            else if (clarifyRound === 2) { setClarifyQ3(data.question); setClarifyRound(3); }
            else if (clarifyRound === 3) { setClarifyQ4(data.question); setClarifyRound(4); }
        }
        setClarifyLoading(false);
    };

    // ── Step 3 → 4: save remaining steps, convert, fetch AI ───────
    const handleConvertAndSummarise = async () => {
        if (caseId) { setStep(4); return; } // already converted

        if (!intakeToken) {
            toast.show("Questionnaire complete", "success");
            setStep(4);
            return;
        }

        setConverting(true);

        // Save final answer to clarification_qa BEFORE convert.
        // convert_to_case reads clarification_qa and appends Q&A to the description itself.
        const lastAnswer = clarifyA4.trim() || clarifyA3.trim() || clarifyA2.trim();
        if (intakeToken && lastAnswer) {
            await intakeClarify(intakeToken, lastAnswer);
        }
        const r4 = await intakeSaveStep(intakeToken, 4, {
            has_evidence: hasEvidence,
            evidence_description: evidenceDesc.trim() || null,
            opposing_party: null,
        });
        const r5 = await intakeSaveStep(intakeToken, 5, {
            desired_outcome: desiredOutcome.trim() || "Legal assistance and representation",
            additional_notes: null,
        });
        if (r4.error || r5.error) {
            toast.show("Could not save case details — check your connection and try again.", "error", 3000);
            setConverting(false);
            return;
        }

        const savedToken = intakeToken;
        const { data: converted, error: convErr } = await intakeConvert(savedToken, {
            language: voiceLang?.code || "en",
            urgency,
        });

        if (convErr) {
            // Print exact server error so mismatches are visible in the console
            const msg = convErr?.error || convErr?.detail || JSON.stringify(convErr);
            console.error("Intake /convert error:", msg);
            toast.show(`Convert failed: ${msg}`, "error", 5000);
            setConverting(false);
            return; // do not advance to step 4 on failure
        }

        if (converted?.case_id) {
            setCaseId(converted.case_id);
            localStorage.setItem("aai-case-id", converted.case_id);
            localStorage.removeItem("aai-intake-token");
            setIntakeToken(null);

            // Fetch the AI-structured case data
            const { data: intake } = await intakeGet(savedToken);
            if (intake?.ai_structured_case?.summary && intake.ai_structured_case.summary !== "pending") {
                setAiStructured(intake.ai_structured_case);
            }
        }

        setConverting(false);
        toast.show("✅ Case analysis complete", "success", 3000);
        setStep(4);
    };

    // ── Final submit (Step 5) ──────────────────────────────────────
    const handleSubmit = async () => {
        setIntakeSubmitting(true);
        completeIntake({
            role,
            caseType:    caseTypeInput,
            province,
            caseId,
            description: description.trim() || voiceTranscript.trim(),
            evidenceDocs: [],
        });
        addNotification({
            type: "status",
            urgency: "info",
            title: "Case Intake Complete",
            date: new Date().toLocaleDateString("en-US", { month: "short", day: "numeric" }),
            time: new Date().toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" }),
            desc: `Case structured — ${role} · ${CASE_TYPES.find(c => c.value === caseTypeInput)?.label || caseTypeInput} · ${province}`,
        });
        toast.show("Case submitted for attorney review!", "success", 3000);
        setTimeout(() => toast.show("You'll hear from us within 2 hours", "info", 2000), 3000);
        setIntakeSubmitting(false);
    };

    // ── Voice state ────────────────────────────────────────────────
    const [inputType, setInputType] = useState("voice");
    const [voiceStatus, setVoiceStatus] = useState("idle");
    const isRecording  = voiceStatus === "recording";
    const transcribing = voiceStatus === "transcribing";
    const [recTime, setRecTime] = useState(0);
    const [voiceTranscript, setVoiceTranscript] = useState("");
    const [voiceLang, setVoiceLang] = useState(null);
    const mediaRecorderRef = useRef(null);
    const audioChunksRef  = useRef([]);
    const recTimerRef     = useRef(null);
    const MAX_REC_SECS    = 120;
    const formatTime = (s) => `${Math.floor(s / 60)}:${(s % 60).toString().padStart(2, '0')}`;

    useEffect(() => () => clearInterval(recTimerRef.current), []);

    const startRecording = async () => {
        if (!navigator.mediaDevices?.getUserMedia) {
            toast.show("Microphone not supported in this browser.", "error", 3000);
            return;
        }
        try {
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            audioChunksRef.current = [];
            const mimeType = MediaRecorder.isTypeSupported("audio/webm") ? "audio/webm" : "";
            const mr = new MediaRecorder(stream, mimeType ? { mimeType } : {});
            mr.ondataavailable = e => { if (e.data.size > 0) audioChunksRef.current.push(e.data); };
            mr.start(250);
            mediaRecorderRef.current = mr;
            setVoiceStatus("recording");
            setRecTime(0);
            recTimerRef.current = setInterval(() => {
                setRecTime(prev => {
                    const next = prev + 1;
                    if (next >= MAX_REC_SECS) {
                        clearInterval(recTimerRef.current);
                        try {
                            mediaRecorderRef.current?.stop();
                            mediaRecorderRef.current?.stream?.getTracks().forEach(tr => tr.stop());
                        } catch {}
                        setVoiceStatus("stopped");
                        return MAX_REC_SECS;
                    }
                    return next;
                });
            }, 1000);
        } catch {
            toast.show("Microphone access denied. Please allow mic permission.", "error", 3000);
        }
    };

    const stopRecording = () => {
        if (!mediaRecorderRef.current || !isRecording) return;
        mediaRecorderRef.current.stop();
        mediaRecorderRef.current.stream.getTracks().forEach(tr => tr.stop());
        clearInterval(recTimerRef.current);
        setVoiceStatus("stopped");
    };

    const handleConvert = async () => {
        if (!audioChunksRef.current.length) {
            toast.show("No recording found. Tap the mic to start.", "warn", 2000);
            return;
        }
        setVoiceStatus("transcribing");
        const rawBlob = new Blob(audioChunksRef.current, {
            type: mediaRecorderRef.current?.mimeType || "audio/webm",
        });
        let sendBlob = rawBlob;
        try {
            const ctx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 16000 });
            const decoded = await ctx.decodeAudioData(await rawBlob.arrayBuffer());
            sendBlob = _pcmToWav(decoded.getChannelData(0), 16000);
        } catch { /* fallback: send raw blob */ }
        const { data, error } = await transcribeAudio(sendBlob);
        if (error) {
            setVoiceStatus("error");
            toast.show(error.detail || "Transcription failed. Try again.", "error", 3000);
            return;
        }
        setVoiceTranscript(data.transcript || "");
        if (data.transcript) {
            setVoiceLang({ name: data.language_name, code: data.language, prob: data.language_probability });
            setVoiceStatus("ready");
            toast.show(`Transcript ready — detected ${data.language_name} (${Math.round(data.language_probability * 100)}%)`, "success", 3000);
        } else {
            setVoiceStatus("error");
        }
    };

    const handleSubmitVoice = () => {
        if (!voiceTranscript.trim()) { toast.show("No transcript to submit.", "warn", 2000); return; }
        setDescription(voiceTranscript);
        setVoiceStatus("idle");
        setInputType("text");
        toast.show("Voice transcript added to your case.", "success", 2000);
    };

    const VOICE_UI = {
        idle:         { icon: "🎙️", text: "Tap mic to start recording",          color: t.textMuted,  badgeType: null },
        recording:    { icon: "🎤", text: "Recording…",                           color: t.danger,     badgeType: "danger",  badgeLabel: "● REC" },
        stopped:      { icon: "⏸️", text: "Stopped — click Convert to Text",      color: t.warn,       badgeType: "warn",    badgeLabel: "STOPPED" },
        transcribing: { icon: "⏳", text: "Transcribing…",                        color: t.primary,    badgeType: "info",    badgeLabel: "⏳ PROCESSING" },
        ready:        { icon: "✅", text: "Transcript ready — review and submit", color: t.success,    badgeType: "success", badgeLabel: "✅ READY" },
        error:        { icon: "❌", text: "Failed — try again",                   color: t.danger,     badgeType: "danger",  badgeLabel: "❌ FAILED" },
    };
    const vui = VOICE_UI[voiceStatus] || VOICE_UI.idle;

    const selectStyle = {
        width: "100%", padding: "10px 14px", borderRadius: 8,
        border: `1px solid ${t.border}`, background: t.inputBg,
        color: t.text, fontSize: 13, outline: "none", cursor: "pointer",
    };

    return (
        <div>
            {/* Progress bar */}
            <div style={{ marginBottom: 24 }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
                    <h3 style={{ fontSize: 14, fontWeight: 700, color: t.text }}>Case Intake Progress</h3>
                    <span style={{ fontSize: 13, fontWeight: 700, color: t.primary }}>{Math.round(progress)}%</span>
                </div>
                <div style={{ height: 6, background: t.inputBg, borderRadius: 4, overflow: "hidden" }}>
                    <div style={{ width: `${progress}%`, height: "100%", background: t.grad1, borderRadius: 4, transition: "width 0.5s cubic-bezier(0.4, 0, 0.2, 1)" }} />
                </div>
            </div>

            {/* Step tabs */}
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

            {/* ── STEP 1: Role + Province ─────────────────────────────── */}
            {step === 1 && (
                <Card className="aFadeUp">
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 20 }}>
                        <STitle icon="user" sub="Your role and province determine how we structure your case">Select Your Role & Province</STitle>
                        <BtnPrimary
                            disabled={!role || !province}
                            onClick={handleStep1Continue}
                            style={{ fontSize: 14, padding: "12px 32px" }}
                        >Continue →</BtnPrimary>
                    </div>

                    {/* Role cards */}
                    <div style={{ display: "flex", gap: 16, marginBottom: 24, marginTop: 8 }}>
                        {["Plaintiff", "Defendant"].map(r => (
                            <div key={r} onClick={() => setRole(r)} style={{ flex: 1, padding: 28, borderRadius: 18, border: `2.5px solid ${role === r ? t.primary : t.border}`, background: role === r ? t.primaryGlow : "transparent", cursor: "pointer", textAlign: "center", transition: "all 0.25s cubic-bezier(0.4, 0, 0.2, 1)", transform: role === r ? "scale(1.05)" : "scale(1)", boxShadow: role === r ? `0 12px 32px ${t.primary}25` : "none" }}>
                                <div style={{ fontSize: 48, marginBottom: 14 }}>{r === "Plaintiff" ? "⚖️" : "🛡️"}</div>
                                <div style={{ fontWeight: 800, color: t.text, fontSize: 18, fontFamily: "'Playfair Display',serif", marginBottom: 4 }}>{r}</div>
                                <div style={{ fontSize: 13, color: t.textMuted, marginTop: 6 }}>{r === "Plaintiff" ? "Filing a legal claim" : "Responding to a claim"}</div>
                            </div>
                        ))}
                    </div>

                    {/* Province dropdown */}
                    <div style={{ background: t.inputBg, border: `1.5px solid ${province ? t.primary : t.border}`, borderRadius: 14, padding: "18px 20px" }}>
                        <label style={{ fontSize: 11, fontWeight: 700, color: t.textMuted, textTransform: "uppercase", letterSpacing: "1px", display: "block", marginBottom: 8 }}>
                            Province / Territory *
                        </label>
                        <select
                            value={province}
                            onChange={e => setProvince(e.target.value)}
                            style={{ ...selectStyle, border: `1.5px solid ${province ? t.primary : t.border}`, color: province ? t.text : t.textMuted }}
                        >
                            <option value="">— Select your province —</option>
                            {PROVINCES.map(p => <option key={p.value} value={p.value}>{p.label}</option>)}
                        </select>
                        <div style={{ fontSize: 11, color: t.textMuted, marginTop: 6 }}>
                            Used to apply the correct jurisdiction and legal framework to your case.
                        </div>
                    </div>
                </Card>
            )}

            {/* ── STEP 2: Case Type + Description ─────────────────────── */}
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
                            <BtnPrimary onClick={handleStep2Continue} style={{ fontSize: 13, padding: "10px 24px" }}>Continue →</BtnPrimary>
                        </div>

                        {/* Case Type + Urgency row */}
                        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, padding: "18px 20px", background: t.card, border: `1.5px solid ${t.border}`, borderRadius: 16 }}>
                            <div>
                                <label style={{ fontSize: 11, fontWeight: 700, color: t.textMuted, textTransform: "uppercase", letterSpacing: "1px", display: "block", marginBottom: 8 }}>
                                    Case Type *
                                </label>
                                <select value={caseTypeInput} onChange={e => setCaseTypeInput(e.target.value)} style={selectStyle}>
                                    {CASE_TYPES.map(c => <option key={c.value} value={c.value}>{c.label}</option>)}
                                </select>
                            </div>
                            <div>
                                <label style={{ fontSize: 11, fontWeight: 700, color: t.textMuted, textTransform: "uppercase", letterSpacing: "1px", display: "block", marginBottom: 8 }}>
                                    Urgency *
                                </label>
                                <select value={urgency} onChange={e => setUrgency(e.target.value)} style={selectStyle}>
                                    {URGENCY_LEVELS.map(u => <option key={u.value} value={u.value}>{u.label}</option>)}
                                </select>
                            </div>
                        </div>

                        <div style={{ display: "grid", gridTemplateColumns: "1.2fr 0.8fr", gap: 24 }}>
                            {/* LEFT PANEL: Input Tab */}
                            <div>
                                <div style={{ display: "inline-flex", background: t.inputBg, borderRadius: 50, padding: 4, marginBottom: 16, border: `1px solid ${t.border}` }}>
                                    {["text", "voice"].map(type => (
                                        <button key={type} onClick={() => setInputType(type)} style={{ display: "flex", alignItems: "center", gap: 8, padding: "8px 20px", borderRadius: 40, border: "none", background: inputType === type ? t.primary : "transparent", color: inputType === type ? (t.mode === "dark" ? "#1A2E35" : "#fff") : t.textMuted, fontSize: 13, fontWeight: 700, cursor: "pointer", transition: "all 0.2s" }}>
                                            <Ic n={type === "text" ? "pen" : "mic"} s={14} c={inputType === type ? (t.mode === "dark" ? "#1A2E35" : "#fff") : t.textMuted} />
                                            {type === "text" ? "Text Input" : "Voice Input"}
                                        </button>
                                    ))}
                                </div>

                                {inputType === "voice" ? (
                                    <div style={{ width: "100%", display: "flex", flexDirection: "column", gap: 16 }}>
                                        <Card style={{ padding: "40px", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", minHeight: 260 }}>
                                            <div style={{ width: 80, height: 80, borderRadius: "50%", background: t.primaryGlow, border: `2px solid ${t.primary}50`, display: "flex", alignItems: "center", justifyContent: "center", marginBottom: 20, boxShadow: `0 0 20px ${t.primaryGlow}`, cursor: "pointer", position: "relative" }} onClick={() => isRecording ? stopRecording() : startRecording()}>
                                                <div style={{ position: "absolute", inset: -10, borderRadius: "50%", background: `${t.primary}20`, animation: isRecording ? "pulse 1.5s infinite" : "none" }} />
                                                <Ic n="mic" s={32} c={t.primary} />
                                            </div>
                                            {isRecording ? (
                                                <div style={{ display: "flex", gap: 4, marginBottom: 16 }}>
                                                    {[0,1,2,3,4,5,6,7].map(i => <div key={i} style={{ width: 6, height: 6, borderRadius: "50%", background: t.primary, animation: `pulse 1s ${i * 0.1}s infinite` }} />)}
                                                </div>
                                            ) : (
                                                <div style={{ display: "flex", gap: 4, marginBottom: 16 }}>
                                                    {[0,1,2,3,4,5,6,7].map(i => <div key={i} style={{ width: 6, height: 6, borderRadius: "50%", background: t.primary + "50" }} />)}
                                                </div>
                                            )}
                                            <div style={{ fontSize: 28, fontWeight: 800, fontFamily: "'JetBrains Mono',monospace", color: t.primary, marginBottom: 8 }}>{formatTime(recTime)}</div>
                                            <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13, fontWeight: voiceStatus !== "idle" ? 600 : 400, color: vui.color }}>
                                                <span>{vui.icon}</span>
                                                <span>{vui.text}</span>
                                                {isRecording && recTime >= MAX_REC_SECS - 15 && (
                                                    <span style={{ fontSize: 11, opacity: 0.8 }}>({MAX_REC_SECS - recTime}s left)</span>
                                                )}
                                            </div>
                                            <div style={{ display: "flex", gap: 12, marginTop: 16 }}>
                                                <BtnOutline onClick={stopRecording} disabled={!isRecording} style={{ padding: "8px 16px", fontSize: 12, border: `1px solid ${t.border}`, color: isRecording ? t.danger : t.textMuted, display: "flex", alignItems: "center", gap: 6, opacity: isRecording ? 1 : 0.45, cursor: isRecording ? "pointer" : "not-allowed" }}><div style={{ width: 8, height: 8, background: isRecording ? t.danger : t.textMuted }} /> Stop</BtnOutline>
                                                <BtnOutline onClick={handleConvert} disabled={transcribing || isRecording || recTime === 0 || voiceStatus === "ready"} style={{ padding: "8px 16px", fontSize: 12, border: `1px solid ${t.primary}`, color: t.primary, display: "flex", alignItems: "center", gap: 6, opacity: (transcribing || isRecording || recTime === 0 || voiceStatus === "ready") ? 0.45 : 1, cursor: (transcribing || isRecording || recTime === 0 || voiceStatus === "ready") ? "not-allowed" : "pointer" }}>{transcribing ? "Converting…" : "↻ Convert to Text"}</BtnOutline>
                                            </div>
                                        </Card>

                                        <Card style={{ padding: 20, border: `1px solid ${t.primary}50`, borderTop: `2px solid ${t.primary}`, display: "flex", flexDirection: "column" }}>
                                            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
                                                <div style={{ fontSize: 11, fontWeight: 800, color: t.primary, display: "flex", alignItems: "center", gap: 8, letterSpacing: "0.5px" }}><Ic n="bot" s={14} c={t.primary} /> AI TRANSCRIPTION</div>
                                                <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                                                    {vui.badgeType && <Badge type={vui.badgeType} style={{ padding: "4px 8px", fontSize: 10 }}>{vui.badgeLabel}</Badge>}
                                                    {voiceLang && <span style={{ fontSize: 10, padding: "3px 7px", borderRadius: 6, background: t.inputBg, color: t.textMuted, fontWeight: 600, letterSpacing: "0.3px" }}>{voiceLang.name} · {Math.round(voiceLang.prob * 100)}%</span>}
                                                </div>
                                            </div>
                                            <div style={{ fontSize: 13, color: t.text, lineHeight: 1.8, marginBottom: 16, flex: 1, minHeight: 80 }}>
                                                {transcribing ? (
                                                    <span style={{ color: t.textMuted, fontStyle: "italic" }}>Transcribing audio…</span>
                                                ) : voiceTranscript ? (
                                                    <textarea value={voiceTranscript} onChange={e => setVoiceTranscript(e.target.value)}
                                                        style={{ width: "100%", minHeight: 80, background: "transparent", border: "none", outline: "none", color: t.text, fontSize: 13, resize: "none", fontFamily: "inherit", lineHeight: 1.8 }} />
                                                ) : (
                                                    <span style={{ color: t.textFaint, fontStyle: "italic" }}>Record audio above then click "Convert to Text" to see the transcript here.</span>
                                                )}
                                            </div>
                                            <div style={{ display: "flex", gap: 12 }}>
                                                <BtnOutline onClick={handleSubmitVoice} disabled={!voiceTranscript.trim() || transcribing} style={{ padding: "8px 16px", fontSize: 12, borderColor: t.primary, color: t.primary, opacity: (!voiceTranscript.trim() || transcribing) ? 0.45 : 1, cursor: (!voiceTranscript.trim() || transcribing) ? "not-allowed" : "pointer" }}>Submit Voice Input ↑</BtnOutline>
                                                <BtnOutline onClick={() => { setVoiceTranscript(""); setVoiceLang(null); audioChunksRef.current = []; setRecTime(0); setVoiceStatus("idle"); }} disabled={transcribing} style={{ padding: "8px 16px", fontSize: 12, borderColor: t.border, color: t.textMuted, opacity: transcribing ? 0.45 : 1, cursor: transcribing ? "not-allowed" : "pointer" }}>Clear</BtnOutline>
                                            </div>
                                        </Card>
                                    </div>
                                ) : (
                                    <Card style={{ padding: "40px", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", minHeight: 260 }}>
                                        <textarea
                                            placeholder="Please describe the events leading up to your dispute in detail..."
                                            value={description}
                                            onChange={e => setDescription(e.target.value)}
                                            style={{ width: "100%", height: "100%", minHeight: 180, background: "transparent", border: "none", outline: "none", color: t.text, fontSize: 14, resize: "none", fontFamily: "inherit" }} />
                                    </Card>
                                )}
                            </div>

                            {/* RIGHT PANEL: Evidence + Desired Outcome */}
                            <Card style={{ padding: "20px 24px", display: "flex", flexDirection: "column", gap: 0 }}>
                                {/* Evidence toggle */}
                                <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 16 }}>
                                    <div style={{ width: 36, height: 36, borderRadius: 10, background: t.inputBg, display: "flex", alignItems: "center", justifyContent: "center" }}><Ic n="file" s={16} c={t.textMuted} /></div>
                                    <div>
                                        <div style={{ fontSize: 15, fontWeight: 700, color: t.text }}>Do you have evidence?</div>
                                        <div style={{ fontSize: 11, color: t.textMuted, marginTop: 2 }}>Documents, photos, or witnesses</div>
                                    </div>
                                </div>
                                <div style={{ display: "flex", gap: 10, marginBottom: 14 }}>
                                    {[{ v: true, label: "Yes, I have evidence" }, { v: false, label: "No evidence yet" }].map(({ v, label }) => (
                                        <button key={String(v)} onClick={() => setHasEvidence(v)} style={{
                                            flex: 1, padding: "10px 8px", borderRadius: 10,
                                            border: `1.5px solid ${hasEvidence === v ? t.primary : t.border}`,
                                            background: hasEvidence === v ? t.primaryGlow : "transparent",
                                            color: hasEvidence === v ? t.primary : t.textMuted,
                                            fontSize: 12, fontWeight: 700, cursor: "pointer", fontFamily: "inherit",
                                        }}>{label}</button>
                                    ))}
                                </div>
                                {hasEvidence && (
                                    <textarea
                                        placeholder="Describe your evidence: medical records, photos, contracts, witness names…"
                                        value={evidenceDesc}
                                        onChange={e => setEvidenceDesc(e.target.value)}
                                        style={{ width: "100%", minHeight: 90, background: t.inputBg, border: `1px solid ${t.border}`, borderRadius: 8, padding: "10px 12px", color: t.text, fontSize: 13, resize: "vertical", outline: "none", fontFamily: "inherit", marginBottom: 16 }}
                                    />
                                )}

                                {/* Desired outcome */}
                                <div style={{ paddingTop: 14, borderTop: `1.5px solid ${t.border}` }}>
                                    <label style={{ fontSize: 11, fontWeight: 700, color: t.textMuted, textTransform: "uppercase", letterSpacing: "1px", display: "block", marginBottom: 8 }}>
                                        Desired Outcome *
                                    </label>
                                    <textarea
                                        placeholder="e.g. File FIR and seek bail, recover unpaid wages, gain custody of children…"
                                        value={desiredOutcome}
                                        onChange={e => setDesiredOutcome(e.target.value)}
                                        style={{ width: "100%", minHeight: 88, background: t.inputBg, border: `1.5px solid ${desiredOutcome.trim() ? t.primary : t.border}`, borderRadius: 8, padding: "10px 12px", color: t.text, fontSize: 13, resize: "vertical", outline: "none", fontFamily: "inherit" }}
                                    />
                                    <div style={{ fontSize: 11, color: t.textMuted, marginTop: 6 }}>
                                        Sent to the AI pipeline — helps generate a more targeted case analysis.
                                    </div>
                                </div>
                            </Card>
                        </div>
                    </div>
                </Fragment>
            )}

            {/* ── STEP 3: AI Follow-up Questions (dynamic) ────────────── */}
            {step === 3 && (
                <div className="aFadeUp" style={{ display: "flex", flexDirection: "column", gap: 16 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 14, padding: "14px 20px", background: t.card, border: `1.5px solid ${t.border}`, borderRadius: 16 }}>
                        <BtnOutline onClick={() => setStep(2)} style={{ fontSize: 13, padding: "10px 20px" }}>← Back</BtnOutline>
                        <div style={{ flex: 1 }} />
                        {/* "Next Question" for rounds 1-3; "Complete & Continue" on round 4 or when done */}
                        {(clarifyRound >= 1 && clarifyRound <= 3) && !clarifyDone ? (
                            <BtnPrimary
                                disabled={clarifyLoading || !getCurrentAnswer().trim()}
                                onClick={handleClarifyNext}
                                style={{ fontSize: 13, padding: "10px 22px" }}
                            >
                                {clarifyLoading ? "Thinking…" : "Next Question →"}
                            </BtnPrimary>
                        ) : (
                            <BtnPrimary
                                disabled={converting || clarifyLoading || (clarifyRound === 4 && !clarifyA4.trim())}
                                onClick={handleConvertAndSummarise}
                                style={{ fontSize: 13, padding: "10px 22px", opacity: converting ? 0.7 : 1 }}
                            >
                                {converting ? "Analysing case…" : clarifyLoading ? "Thinking…" : "Complete & Continue →"}
                            </BtnPrimary>
                        )}
                    </div>
                    <div>
                        <div style={{ fontFamily: "'Fraunces',serif", fontSize: 24, fontWeight: 600, color: t.text, marginBottom: 4 }}>AI <em>Follow-up Questions</em></div>
                        <div style={{ fontSize: 13, color: t.textMuted, marginBottom: 20 }}>Our AI has analysed your case and identified the most important missing facts.</div>
                    </div>

                    <div style={{ display: "grid", gridTemplateColumns: "1fr 300px", gap: 14 }}>
                        <div>
                            <div style={{ padding: "16px 20px", borderRadius: 16, background: `linear-gradient(135deg, ${t.primary}15, ${t.primary}05)`, border: `1px solid ${t.primary}30`, marginBottom: 16, display: "flex", alignItems: "flex-start", gap: 12 }}>
                                <div style={{ width: 36, height: 36, borderRadius: "50%", background: t.primaryGlow, border: `1.5px solid ${t.primary}40`, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 18, flexShrink: 0 }}>🤖</div>
                                <div style={{ fontSize: 13, color: t.textDim, lineHeight: 1.6 }}>
                                    {clarifyLoading && clarifyRound === 0
                                        ? "Analysing your case description…"
                                        : clarifyDone
                                            ? "All key facts collected. Click Complete & Continue to run AI analysis."
                                            : clarifyRound > 0
                                                ? `Question ${clarifyRound} of up to 4 — answer each to strengthen your case.`
                                                : "Preparing follow-up questions…"}
                                </div>
                            </div>

                            {/* Q1 */}
                            {clarifyRound >= 1 && clarifyQ1 && (
                                <Card style={{ padding: 16, marginBottom: 12, border: `1px solid ${t.primary}50` }}>
                                    <div style={{ display: "flex", alignItems: "flex-start", gap: 10, marginBottom: 12 }}>
                                        <div style={{ width: 24, height: 24, borderRadius: "50%", background: clarifyA1 ? t.success : t.primaryGlow, border: `1.5px solid ${clarifyA1 ? t.success : t.primary}40`, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 11, fontWeight: 700, color: clarifyA1 ? "#fff" : t.primary, flexShrink: 0 }}>
                                            {clarifyA1 ? "✓" : "1"}
                                        </div>
                                        <div style={{ fontSize: 13, color: t.text, lineHeight: 1.5, fontWeight: 600 }}>{clarifyQ1}</div>
                                    </div>
                                    <textarea
                                        placeholder="Your answer…"
                                        value={clarifyA1}
                                        onChange={e => setClarifyA1(e.target.value)}
                                        disabled={clarifyRound > 1}
                                        style={{ width: "100%", minHeight: 72, background: t.inputBg, border: `1px solid ${t.border}`, borderRadius: 8, padding: "8px 12px", color: t.text, fontSize: 13, resize: "vertical", outline: "none", fontFamily: "inherit", opacity: clarifyRound > 1 ? 0.7 : 1 }}
                                    />
                                </Card>
                            )}

                            {/* Q2 */}
                            {clarifyRound >= 2 && clarifyQ2 && (
                                <Card style={{ padding: 16, marginBottom: 12, border: `1px solid ${t.primary}50` }}>
                                    <div style={{ display: "flex", alignItems: "flex-start", gap: 10, marginBottom: 12 }}>
                                        <div style={{ width: 24, height: 24, borderRadius: "50%", background: clarifyA2 ? t.success : t.primaryGlow, border: `1.5px solid ${clarifyA2 ? t.success : t.primary}40`, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 11, fontWeight: 700, color: clarifyA2 ? "#fff" : t.primary, flexShrink: 0 }}>
                                            {clarifyA2 ? "✓" : "2"}
                                        </div>
                                        <div style={{ fontSize: 13, color: t.text, lineHeight: 1.5, fontWeight: 600 }}>{clarifyQ2}</div>
                                    </div>
                                    <textarea
                                        placeholder="Your answer…"
                                        value={clarifyA2}
                                        onChange={e => setClarifyA2(e.target.value)}
                                        disabled={clarifyRound > 2}
                                        style={{ width: "100%", minHeight: 72, background: t.inputBg, border: `1px solid ${t.border}`, borderRadius: 8, padding: "8px 12px", color: t.text, fontSize: 13, resize: "vertical", outline: "none", fontFamily: "inherit", opacity: clarifyRound > 2 ? 0.7 : 1 }}
                                    />
                                </Card>
                            )}

                            {/* Q3 */}
                            {clarifyRound >= 3 && clarifyQ3 && (
                                <Card style={{ padding: 16, marginBottom: 12, border: `1px solid ${t.primary}50` }}>
                                    <div style={{ display: "flex", alignItems: "flex-start", gap: 10, marginBottom: 12 }}>
                                        <div style={{ width: 24, height: 24, borderRadius: "50%", background: clarifyA3 ? t.success : t.primaryGlow, border: `1.5px solid ${clarifyA3 ? t.success : t.primary}40`, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 11, fontWeight: 700, color: clarifyA3 ? "#fff" : t.primary, flexShrink: 0 }}>
                                            {clarifyA3 ? "✓" : "3"}
                                        </div>
                                        <div style={{ fontSize: 13, color: t.text, lineHeight: 1.5, fontWeight: 600 }}>{clarifyQ3}</div>
                                    </div>
                                    <textarea
                                        placeholder="Your answer…"
                                        value={clarifyA3}
                                        onChange={e => setClarifyA3(e.target.value)}
                                        disabled={clarifyRound > 3}
                                        style={{ width: "100%", minHeight: 72, background: t.inputBg, border: `1px solid ${t.border}`, borderRadius: 8, padding: "8px 12px", color: t.text, fontSize: 13, resize: "vertical", outline: "none", fontFamily: "inherit", opacity: clarifyRound > 3 ? 0.7 : 1 }}
                                    />
                                </Card>
                            )}

                            {/* Q4 */}
                            {clarifyRound >= 4 && clarifyQ4 && (
                                <Card style={{ padding: 16, marginBottom: 12, border: `1px solid ${t.primary}50` }}>
                                    <div style={{ display: "flex", alignItems: "flex-start", gap: 10, marginBottom: 12 }}>
                                        <div style={{ width: 24, height: 24, borderRadius: "50%", background: clarifyA4 ? t.success : t.primaryGlow, border: `1.5px solid ${clarifyA4 ? t.success : t.primary}40`, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 11, fontWeight: 700, color: clarifyA4 ? "#fff" : t.primary, flexShrink: 0 }}>
                                            {clarifyA4 ? "✓" : "4"}
                                        </div>
                                        <div style={{ fontSize: 13, color: t.text, lineHeight: 1.5, fontWeight: 600 }}>{clarifyQ4}</div>
                                    </div>
                                    <textarea
                                        placeholder="Your answer…"
                                        value={clarifyA4}
                                        onChange={e => setClarifyA4(e.target.value)}
                                        style={{ width: "100%", minHeight: 72, background: t.inputBg, border: `1px solid ${t.border}`, borderRadius: 8, padding: "8px 12px", color: t.text, fontSize: 13, resize: "vertical", outline: "none", fontFamily: "inherit" }}
                                    />
                                </Card>
                            )}

                            {/* Loading skeleton while fetching first question */}
                            {clarifyLoading && clarifyRound === 0 && (
                                <Card style={{ padding: 16, marginBottom: 12 }}>
                                    <div style={{ height: 14, width: "70%", borderRadius: 6, background: t.inputBg, marginBottom: 10 }} />
                                    <div style={{ height: 72, borderRadius: 8, background: t.inputBg }} />
                                </Card>
                            )}

                            {clarifyDone && !clarifyQ1 && (
                                <Card style={{ padding: 20, border: `1px solid ${t.success}40`, background: `${t.success}08` }}>
                                    <div style={{ fontSize: 13, color: t.success, fontWeight: 600 }}>All critical facts already present — no additional questions needed.</div>
                                </Card>
                            )}

                        </div>

                        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
                            {/* Question progress — driven by real clarify state */}
                            <Card style={{ padding: 20 }}>
                                <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 16 }}>
                                    <div style={{ width: 34, height: 34, borderRadius: 10, background: t.primaryGlow, border: `1px solid ${t.primary}40`, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 16 }}>📊</div>
                                    <div>
                                        <div style={{ fontSize: 14, fontWeight: 700, color: t.text }}>Question Progress</div>
                                        <div style={{ fontSize: 11, color: t.textMuted }}>AI-generated follow-up</div>
                                    </div>
                                </div>
                                <div style={{ height: 6, borderRadius: 6, background: t.inputBg, overflow: "hidden", marginBottom: 6 }}>
                                    <div style={{ height: "100%", borderRadius: 6, background: `linear-gradient(90deg, ${t.primary}, ${t.primaryHover || t.primary})`, transition: "width 0.4s ease",
                                        width: clarifyDone ? "100%" : clarifyRound === 4 ? "75%" : clarifyRound === 3 ? "50%" : clarifyRound === 2 ? "25%" : "0%" }} />
                                </div>
                                <div style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 11, color: t.primary, fontWeight: 700, marginBottom: 16 }}>
                                    {clarifyDone ? "All answered" :
                                        clarifyA3 ? "3 / 4 Answered" :
                                        clarifyA2 ? "2 / 4 Answered" :
                                        clarifyA1 ? "1 / 4 Answered" : "0 / 4 Answered"}
                                </div>
                                {[
                                    { n: clarifyQ1 || (clarifyDone ? "Not required" : "Q1 — loading…"), s: clarifyA1 ? "Done" : clarifyRound >= 1 ? "Pending" : clarifyDone ? "N/A" : "Loading" },
                                    { n: clarifyQ2 || (clarifyDone && !clarifyQ2 ? "N/A — skipped" : "Q2 — after Q1"), s: clarifyA2 ? "Done" : clarifyRound === 2 ? "Pending" : clarifyDone ? "N/A" : "Upcoming" },
                                    { n: clarifyQ3 || (clarifyDone && !clarifyQ3 ? "N/A — skipped" : "Q3 — after Q2"), s: clarifyA3 ? "Done" : clarifyRound === 3 ? "Pending" : clarifyDone ? "N/A" : "Upcoming" },
                                    { n: clarifyQ4 || (clarifyDone && !clarifyQ4 ? "N/A — skipped" : "Q4 — after Q3"), s: clarifyA4 ? "Done" : clarifyRound === 4 ? "Pending" : clarifyDone ? "N/A" : "Upcoming" },
                                ].map((item, idx) => (
                                    <div key={idx} style={{ display: "flex", alignItems: "center", gap: 10, padding: "10px 12px", borderRadius: 10, background: t.inputBg, border: `1px solid ${item.s === "Done" ? t.success + "40" : t.border}`, marginBottom: 6 }}>
                                        <div style={{ width: 8, height: 8, borderRadius: "50%", background: item.s === "Done" ? t.success : item.s === "Pending" ? t.warn : t.border }} />
                                        <span style={{ fontSize: 11, color: t.text, flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{item.n}</span>
                                        <Badge type={item.s === "Done" ? "success" : item.s === "Pending" ? "warn" : "default"} style={{ fontSize: 10, padding: "2px 6px", flexShrink: 0 }}>{item.s}</Badge>
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
                                    <span style={{ color: t.textMuted }}>Case Type</span>
                                    <Badge type="info">{CASE_TYPES.find(c => c.value === caseTypeInput)?.label || caseTypeInput}</Badge>
                                </div>
                                <div style={{ display: "flex", justifyContent: "space-between", padding: "8px 0", borderBottom: `1px solid ${t.border}`, fontSize: 12 }}>
                                    <span style={{ color: t.textMuted }}>Your Role</span><Badge type="primary">{role}</Badge>
                                </div>
                                <div style={{ display: "flex", justifyContent: "space-between", padding: "8px 0", borderBottom: `1px solid ${t.border}`, fontSize: 12 }}>
                                    <span style={{ color: t.textMuted }}>Province</span><span style={{ color: t.text, fontWeight: 600 }}>{PROVINCES.find(p => p.value === province)?.label || province}</span>
                                </div>
                                <div style={{ display: "flex", justifyContent: "space-between", padding: "8px 0", fontSize: 12 }}>
                                    <span style={{ color: t.textMuted }}>Urgency</span>
                                    <Badge type={urgency === "urgent" || urgency === "high" ? "danger" : urgency === "medium" ? "warn" : "success"}>{urgency}</Badge>
                                </div>
                            </Card>
                        </div>
                    </div>
                </div>
            )}

            {/* ── STEP 4: AI Case Summary ──────────────────────────────── */}
            {step === 4 && (
                <div className="aFadeUp" style={{ display: "flex", flexDirection: "column", gap: 16 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 14, padding: "14px 20px", background: t.card, border: `1.5px solid ${t.border}`, borderRadius: 16 }}>
                        <BtnOutline onClick={() => setStep(3)} style={{ fontSize: 13, padding: "10px 20px" }}>← Back</BtnOutline>
                        <div style={{ flex: 1 }} />
                        <BtnPrimary onClick={() => { toast.show("✅ Case saved!", "success"); setStep(5); }} style={{ fontSize: 13, padding: "10px 22px" }}>Confirm & Save Case →</BtnPrimary>
                    </div>
                    <div>
                        <div style={{ fontFamily: "'Fraunces',serif", fontSize: 24, fontWeight: 600, color: t.text, marginBottom: 4 }}>AI-Generated <em>Case Summary</em></div>
                        <div style={{ fontSize: 13, color: t.textMuted, marginBottom: 20 }}>Review and confirm your structured case before saving</div>
                    </div>

                    <div style={{ display: "grid", gridTemplateColumns: "1fr 300px", gap: 14 }}>
                        {/* Main panel */}
                        <Card style={{ padding: 0, overflow: "hidden", display: "flex", flexDirection: "column" }}>
                            <div style={{ padding: "16px 20px", borderBottom: `1px solid ${t.border}`, background: t.inputBg, display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                                <div>
                                    <div style={{ fontSize: 14, fontWeight: 600, color: t.text }}>Structured Case Summary — AI-Generated</div>
                                    <div style={{ fontSize: 11, color: t.textMuted, marginTop: 2 }}>
                                        {caseId ? `Case ID: …${caseId.slice(-8)}` : "Processing…"} · Auto-generated by AI
                                    </div>
                                </div>
                                <div style={{ display: "flex", gap: 8 }}>
                                    <BtnOutline onClick={() => toast.show("✏️ Edit mode")} style={{ padding: "6px 12px", fontSize: 11 }}>✏️ Edit All</BtnOutline>
                                    <BtnOutline onClick={() => toast.show("💾 Case saved")} style={{ padding: "6px 12px", fontSize: 11 }}>💾 Save</BtnOutline>
                                </div>
                            </div>

                            <div style={{ padding: 20, maxHeight: 480, overflowY: "auto", display: "flex", flexDirection: "column", gap: 12 }}>
                                {aiStructured ? (
                                    <>
                                        {/* AI Summary */}
                                        <div style={{ background: t.inputBg, border: `1px solid ${t.border}`, borderRadius: 12, padding: "16px 20px" }}>
                                            <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: "1px", textTransform: "uppercase", color: t.primary, marginBottom: 10 }}>📋 Case Summary</div>
                                            <div style={{ fontSize: 13, color: t.textDim, lineHeight: 1.7 }}>{aiStructured.summary}</div>
                                        </div>

                                        {/* Applicable Laws */}
                                        {aiStructured.applicable_laws?.length > 0 && (
                                            <div style={{ background: t.inputBg, border: `1px solid ${t.border}`, borderRadius: 12, padding: "16px 20px" }}>
                                                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
                                                    <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: "1px", textTransform: "uppercase", color: t.primary }}>⚖️ Applicable Laws</div>
                                                    <span onClick={() => toast.show("Editing...")} style={{ fontSize: 11, color: t.textMuted, padding: "4px 10px", borderRadius: 20, border: `1px solid ${t.border}`, cursor: "pointer" }}>✏️ Edit</span>
                                                </div>
                                                <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                                                    {aiStructured.applicable_laws.map((law, i) => (
                                                        <div key={i} style={{ fontSize: 13, color: t.textDim, lineHeight: 1.6 }}>
                                                            {i + 1}. {law}
                                                        </div>
                                                    ))}
                                                </div>
                                            </div>
                                        )}

                                        {/* Recommended Actions */}
                                        {aiStructured.recommended_actions?.length > 0 && (
                                            <div style={{ background: t.inputBg, border: `1px solid ${t.border}`, borderRadius: 12, padding: "16px 20px" }}>
                                                <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: "1px", textTransform: "uppercase", color: t.primary, marginBottom: 10 }}>🎯 Recommended Actions</div>
                                                <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                                                    {aiStructured.recommended_actions.map((action, i) => (
                                                        <div key={i} style={{ fontSize: 13, color: t.textDim, lineHeight: 1.6 }}>
                                                            {i + 1}. {action}
                                                        </div>
                                                    ))}
                                                </div>
                                            </div>
                                        )}

                                        {/* Risk Level */}
                                        {aiStructured.risk_level && (
                                            <div style={{ background: t.inputBg, border: `1px solid ${t.border}`, borderRadius: 12, padding: "16px 20px" }}>
                                                <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: "1px", textTransform: "uppercase", color: t.primary, marginBottom: 10 }}>⚠️ Risk Assessment</div>
                                                <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                                                    <Badge type={RISK_COLORS[aiStructured.risk_level] || "warn"} style={{ fontSize: 12, padding: "6px 14px", fontWeight: 700, textTransform: "uppercase" }}>
                                                        {aiStructured.risk_level} risk
                                                    </Badge>
                                                    <span style={{ fontSize: 12, color: t.textMuted }}>Informational only — not legal advice.</span>
                                                </div>
                                            </div>
                                        )}
                                    </>
                                ) : (
                                    // Static fallback when AI analysis not available
                                    [
                                        { icon: "👤", title: "Parties", body: `<strong>Role:</strong> ${role}<br/><strong>Province:</strong> ${PROVINCES.find(p => p.value === province)?.label || province}`, c: t.primary },
                                        { icon: "⚖️", title: "Case Type", body: `${CASE_TYPES.find(c => c.value === caseTypeInput)?.label || caseTypeInput} — Urgency: ${urgency}`, c: t.primary },
                                        { icon: "📋", title: "Case Description", body: description || voiceTranscript || "No description provided.", c: t.primary },
                                        { icon: "🎯", title: "Desired Outcome", body: "Legal assistance and representation.", c: t.primary },
                                    ].map((s, idx) => (
                                        <div key={idx} style={{ background: t.inputBg, border: `1px solid ${t.border}`, borderRadius: 12, padding: "16px 20px" }}>
                                            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
                                                <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: "1px", textTransform: "uppercase", color: s.c }}>{s.icon} {s.title}</div>
                                                <span onClick={() => toast.show("Editing...")} style={{ fontSize: 11, color: t.textMuted, padding: "4px 10px", borderRadius: 20, border: `1px solid ${t.border}`, cursor: "pointer" }}>✏️ Edit</span>
                                            </div>
                                            <div style={{ fontSize: 13, color: t.textDim, lineHeight: 1.7 }} dangerouslySetInnerHTML={{ __html: s.body }} />
                                        </div>
                                    ))
                                )}
                            </div>
                        </Card>

                        {/* Sidebar */}
                        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
                            <Card style={{ padding: 20, border: `1px solid ${t.primary}50`, background: t.primaryGlow }}>
                                <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 16 }}>
                                    <div style={{ width: 34, height: 34, borderRadius: 10, background: t.primaryGlow, border: `1px solid ${t.primary}40`, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 16 }}>📊</div>
                                    <div>
                                        <div style={{ fontSize: 14, fontWeight: 700, color: t.text }}>Case Overview</div>
                                        <div style={{ fontSize: 11, color: t.textMuted }}>Confirm details</div>
                                    </div>
                                </div>
                                <div style={{ display: "flex", justifyContent: "space-between", padding: "8px 0", borderBottom: `1px solid ${t.border}`, fontSize: 12 }}>
                                    <span style={{ color: t.textMuted }}>Case ID</span>
                                    <span style={{ fontFamily: "'JetBrains Mono',monospace", color: t.text, fontWeight: 600, fontSize: 11 }}>
                                        {caseId ? `…${caseId.slice(-8)}` : "Pending"}
                                    </span>
                                </div>
                                <div style={{ display: "flex", justifyContent: "space-between", padding: "8px 0", borderBottom: `1px solid ${t.border}`, fontSize: 12 }}>
                                    <span style={{ color: t.textMuted }}>Type</span>
                                    <Badge type="info">{CASE_TYPES.find(c => c.value === caseTypeInput)?.label || caseTypeInput}</Badge>
                                </div>
                                <div style={{ display: "flex", justifyContent: "space-between", padding: "8px 0", borderBottom: `1px solid ${t.border}`, fontSize: 12 }}>
                                    <span style={{ color: t.textMuted }}>Role</span><Badge type="primary">{role}</Badge>
                                </div>
                                <div style={{ display: "flex", justifyContent: "space-between", padding: "8px 0", borderBottom: `1px solid ${t.border}`, fontSize: 12 }}>
                                    <span style={{ color: t.textMuted }}>Province</span>
                                    <span style={{ color: t.text, fontWeight: 600 }}>{PROVINCES.find(p => p.value === province)?.label || province}</span>
                                </div>
                                <div style={{ display: "flex", justifyContent: "space-between", padding: "8px 0", fontSize: 12 }}>
                                    <span style={{ color: t.textMuted }}>Urgency</span>
                                    <Badge type={urgency === "urgent" || urgency === "high" ? "danger" : urgency === "medium" ? "warn" : "success"}>{urgency}</Badge>
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
                                    {aiStructured?.applicable_laws?.length > 0
                                        ? aiStructured.applicable_laws.slice(0, 4).map((law, i) => (
                                            <div key={i} style={{ padding: "10px 14px", borderRadius: 10, background: t.inputBg, border: `1px solid ${t.border}` }}>
                                                <div style={{ fontSize: 12, fontWeight: 700, color: t.primary }}>{law}</div>
                                            </div>
                                        ))
                                        : [
                                            { t: "Relevant Pakistani Statute", d: "AI analysis pending or unavailable" },
                                        ].map(lw => (
                                            <div key={lw.t} style={{ padding: "10px 14px", borderRadius: 10, background: t.inputBg, border: `1px solid ${t.border}` }}>
                                                <div style={{ fontSize: 12, fontWeight: 700, color: t.primary, marginBottom: 2 }}>{lw.t}</div>
                                                <div style={{ fontSize: 11, color: t.textMuted }}>{lw.d}</div>
                                            </div>
                                        ))
                                    }
                                </div>
                            </Card>
                        </div>
                    </div>
                </div>
            )}

            {/* ── STEP 5: Categorization + Final Submit ────────────────── */}
            {step === 5 && (
                <div className="aFadeUp" style={{ display: "flex", flexDirection: "column", gap: 16 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 14, padding: "14px 20px", background: t.card, border: `1.5px solid ${t.border}`, borderRadius: 16 }}>
                        <BtnOutline onClick={() => setStep(4)} style={{ fontSize: 13, padding: "10px 20px" }}>← Back</BtnOutline>
                        <div style={{ flex: 1 }} />
                        <BtnPrimary
                            disabled={intakeSubmitting}
                            onClick={() => { if (!intakeSubmitting) { toast.show("🎉 Case fully structured!"); handleSubmit(); } }}
                            style={{ fontSize: 13, padding: "10px 22px", opacity: intakeSubmitting ? 0.7 : 1 }}>
                            {intakeSubmitting ? "Submitting…" : "🎉 Complete Case Intake →"}
                        </BtnPrimary>
                    </div>
                    <div>
                        <div style={{ fontFamily: "'Fraunces',serif", fontSize: 24, fontWeight: 600, color: t.text, marginBottom: 4 }}>Case <em>Categorization</em></div>
                        <div style={{ fontSize: 13, color: t.textMuted, marginBottom: 20 }}>Confirm your case category before final submission</div>
                    </div>

                    <div style={{ display: "grid", gridTemplateColumns: "1fr 300px", gap: 14 }}>
                        <div>
                            <div style={{ padding: "16px 20px", borderRadius: 16, background: `linear-gradient(135deg, ${t.primary}15, ${t.primary}05)`, border: `1px solid ${t.primary}30`, marginBottom: 16, display: "flex", alignItems: "center", gap: 12 }}>
                                <div style={{ fontSize: 18 }}>🤖</div>
                                <div style={{ fontSize: 13, color: t.textDim, lineHeight: 1.6 }}>
                                    AI identified your case as <strong style={{ color: t.primary }}>{CASE_TYPES.find(c => c.value === caseTypeInput)?.label || caseTypeInput}</strong>. Confirm or select a different category.
                                </div>
                            </div>

                            <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 12, marginBottom: 20 }}>
                                {[
                                    { id: "civil",          i: "⚖️",  n: "Civil Law",          d: "Property disputes, contracts, personal injury" },
                                    { id: "criminal",       i: "🚔",  n: "Criminal Law",        d: "FIR filing, bail applications, criminal defense" },
                                    { id: "family",         i: "👨‍👩‍👧",  n: "Family Law",          d: "Divorce, custody, inheritance, guardianship" },
                                    { id: "constitutional", i: "📜",  n: "Constitutional Law",  d: "Fundamental rights, writ petitions" },
                                    { id: "property",       i: "🏠",  n: "Property Law",        d: "Land disputes, ownership, title deed" },
                                    { id: "corporate",      i: "🏢",  n: "Corporate Law",       d: "Business disputes, NDA breaches, partnerships" },
                                ].map(c => {
                                    const sel = c.id === caseTypeInput;
                                    return (
                                        <Card key={c.id} onClick={() => setCaseTypeInput(c.id)} style={{ padding: "20px 16px", textAlign: "center", cursor: "pointer", border: sel ? `1.5px solid ${t.primary}` : `1.5px solid ${t.border}`, background: sel ? `linear-gradient(135deg, ${t.primary}15, ${t.primaryGlow})` : t.card, boxShadow: sel ? `0 0 20px ${t.primary}30` : t.shadowCard }}>
                                            {sel && <div style={{ position: "absolute", top: 12, right: 12, width: 22, height: 22, borderRadius: "50%", background: t.primary, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 10, color: "#071a1a", fontWeight: 700 }}>✓</div>}
                                            <div style={{ fontSize: 26, marginBottom: 12 }}>{c.i}</div>
                                            <div style={{ fontSize: 14, fontWeight: 700, color: sel ? t.primary : t.text, marginBottom: 4 }}>{c.n}</div>
                                            <div style={{ fontSize: 11, color: t.textMuted, lineHeight: 1.5 }}>{c.d}</div>
                                        </Card>
                                    );
                                })}
                            </div>
                        </div>

                        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
                            <Card style={{ padding: 20, border: `1px solid ${t.primary}50`, background: t.primaryGlow, textAlign: "center" }}>
                                <div style={{ fontSize: 40, marginBottom: 12 }}>✅</div>
                                <div style={{ fontFamily: "'Fraunces',serif", fontSize: 18, fontWeight: 600, color: t.primary, marginBottom: 6 }}>Case Intake Complete</div>
                                <div style={{ fontSize: 12, color: t.textMuted, marginBottom: 20 }}>Your case is structured and ready for review</div>
                                <div style={{ textAlign: "left" }}>
                                    <div style={{ display: "flex", justifyContent: "space-between", padding: "8px 0", borderBottom: `1px solid ${t.border}`, fontSize: 12 }}>
                                        <span style={{ color: t.textMuted }}>Case ID</span>
                                        <span style={{ fontFamily: "'JetBrains Mono',monospace", color: t.text, fontWeight: 600, fontSize: 11 }}>
                                            {caseId ? `…${caseId.slice(-8)}` : "Pending"}
                                        </span>
                                    </div>
                                    <div style={{ display: "flex", justifyContent: "space-between", padding: "8px 0", borderBottom: `1px solid ${t.border}`, fontSize: 12 }}>
                                        <span style={{ color: t.textMuted }}>Category</span><Badge type="info">{CASE_TYPES.find(c => c.value === caseTypeInput)?.label || caseTypeInput}</Badge>
                                    </div>
                                    <div style={{ display: "flex", justifyContent: "space-between", padding: "8px 0", borderBottom: `1px solid ${t.border}`, fontSize: 12 }}>
                                        <span style={{ color: t.textMuted }}>Province</span>
                                        <span style={{ color: t.text, fontWeight: 600 }}>{PROVINCES.find(p => p.value === province)?.label || province}</span>
                                    </div>
                                    <div style={{ display: "flex", justifyContent: "space-between", padding: "8px 0", borderBottom: `1px solid ${t.border}`, fontSize: 12 }}>
                                        <span style={{ color: t.textMuted }}>Status</span><Badge type="success">Ready</Badge>
                                    </div>
                                </div>
                                <BtnPrimary
                                    onClick={() => {
                                        const dest = caseId ? `/lawyers?case_id=${caseId}` : "/lawyers";
                                        router.push(dest);
                                    }}
                                    style={{ width: "100%", marginTop: 20, padding: 14, fontSize: 14 }}
                                >Find a Lawyer →</BtnPrimary>
                            </Card>

                            <Card style={{ padding: 20 }}>
                                <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 16 }}>
                                    <div style={{ width: 34, height: 34, borderRadius: 10, background: t.inputBg, border: `1px solid ${t.border}`, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 16 }}>📄</div>
                                    <div style={{ fontSize: 14, fontWeight: 700, color: t.text }}>Export Case</div>
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
            )}
        </div>
    );
};

export default ModIntake;
