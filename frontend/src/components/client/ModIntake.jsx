'use client';
import React, { useState, useEffect, useRef, Fragment } from "react";
import { useRouter } from "next/navigation";
import { useT } from "./theme.js";
import { useToast } from "@/components/shared/Toast.jsx";
import { useCase } from "./CaseContext.jsx";
import Ic from "./Ic.jsx";
import { Card, BtnPrimary, BtnOutline, ThemedInput, Badge, Tooltip } from "@/components/shared/shared.jsx";
import { intakeStart, intakeSaveStep, intakeConvert, intakeGet, intakeClarify, transcribeAudio, uploadIntakeEvidence, confirmCase, deleteIntakeEvidence, downloadIntakeEvidence, getResumableIntake } from "@/lib/api.js";
import { useLang, useIsMobile } from "@/lib/i18n.jsx";
import { useAuth } from "@/context/AuthContext.jsx";
import { readIntakeValue, writeIntakeValue, clearIntakeValue } from "@/lib/intakeStorage.js";
import { escapeHtml } from "@/lib/escapeHtml.js";
import { extractionLabel, incompleteFiles, TONE_OK, TONE_WARN, TONE_BAD, TONE_NEUTRAL } from "@/lib/extractionStatus.js";

/* One colour per tone, so a new state cannot arrive looking like a reassurance
 * simply because nobody added it to a ternary. */
const EXTRACTION_TONE_COLOUR = {
    [TONE_OK]: null,          // falls back to the muted body colour
    [TONE_WARN]: "#b45309",
    [TONE_BAD]: "#b91c1c",
    [TONE_NEUTRAL]: null,
};
const EXTRACTION_TONE_ICON = {
    [TONE_OK]: "✓", [TONE_WARN]: "⚠", [TONE_BAD]: "✕", [TONE_NEUTRAL]: "•",
};

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

// Mirrors backend classifier_node._score_query — runs in browser so case type
// is selected before the backend even receives the description.
const quickClassify = (text) => {
    if (!text || text.trim().length < 4) return "";
    const t = text;
    const scores = { family: 0, criminal: 0, civil: 0, constitutional: 0 };

    // Family — English, Romanized Urdu, Urdu script
    if (/\b(divorce|talaq|talaaq|khula|khulaah|nikah|nikaah|marriage|shadi|shaadi|custody|hizanat|maintenance|nafaqa|dowry|jahez|dower|mehr|mehar|inheritance|wirsa|wirasat|MFLO|guardian|iddat|iddah)\b/i.test(t)) scores.family += 0.35;
    if (/(خلع|طلاق|نکاح|شادی|حضانت|نفقہ|مہر|وراثت|خاندان|گھریلو)/.test(t)) scores.family += 0.35;
    if (/\b(wife|husband|biwi|shohar|shauhar|child|bachha|in-laws|susral|sasural)\b/i.test(t)) scores.family += 0.15;

    // Criminal — English, Romanized Urdu, Urdu script
    if (/\b(FIR|murder|qatl|qatal|theft|chori|steal|rob|assault|dacoity|robbery|rape|zina|kidnap|bail|arrest|police|challan|accused|CrPC|PPC|PECA|cybercrime)\b/i.test(t)) scores.criminal += 0.30;
    if (/(قتل|چوری|ڈکیتی|بیل|گرفتاری|مقدمہ|پولیس|ملزم)/.test(t)) scores.criminal += 0.30;
    if (/\b(crime|criminal|jail|prison|sentence|prosecution|qaid)\b/i.test(t)) scores.criminal += 0.20;

    // Civil
    if (/\b(property|tenant|landlord|rent|kiraya|contract|agreement|debt|loan|mortgage|qarz|possession|eviction|damages|injunction|CPC|decree)\b/i.test(t)) scores.civil += 0.30;
    if (/\b(dispute|compensation|nuqsan)\b/i.test(t)) scores.civil += 0.15;

    // Constitutional
    if (/\b(fundamental\s*rights?|article\s*\d+|constitution|Supreme\s*Court|High\s*Court|writ|habeas|mandamus|government|parliament)\b/i.test(t)) scores.constitutional += 0.35;
    if (/\b(rights?|haqooq|azaadi|freedom|liberty|equality|discrimination)\b/i.test(t)) scores.constitutional += 0.15;

    const best = Object.entries(scores).reduce((a, b) => b[1] > a[1] ? b : a);
    return best[1] >= 0.15 ? best[0] : "";
};

const URGENCY_LEVELS = [
    { value: "low",    label: "Low — No immediate deadline" },
    { value: "medium", label: "Medium — Within a month" },
    { value: "high",   label: "High — Within a week" },
    { value: "urgent", label: "Urgent — Immediate action needed" },
];

const RISK_COLORS = { low: "success", medium: "warn", high: "danger", urgent: "danger" };

// Why the recommended actions were not verified against retrieved law. The
// backend distinguishes "we checked and it held" from "we could not check";
// only `grounded` is the former, so every other status gets a visible note.
// Written in the user's terms — they do not know what a retrieval chunk is.
const GROUNDING_NOTE = {
    no_evidence_retrieved: "No matching law was found for this case, so these steps could not be checked against Pakistani legislation. Confirm them with a qualified lawyer before acting.",
    ungrounded: "Some of these steps could not be fully matched to the law sections found for your case. Please confirm them with a qualified lawyer.",
    judge_failed: "The verification step could not run just now, so these steps have not been checked against the law. Please confirm them with a qualified lawyer.",
    pipeline_failed: "Automated analysis was unavailable for this case. Please have a qualified lawyer review your situation.",
    unparseable: "The analysis could not be verified. Please confirm these steps with a qualified lawyer.",
    no_actions: "No specific steps were produced for this case.",
    // A statute was named that does NOT appear in the law found for this case.
    // The generic "not verified" note below would badly undersell that: it
    // reads as a missing check, when what happened is that a citation may be
    // invented. This is the one status a reader most needs stated plainly.
    citations_unverified: "One or more laws cited here could not be matched to any legislation found for your case, and may not exist as stated. Do not rely on these citations — have a qualified lawyer check them.",
    // The verifier passed the analysis but its own per-step assessment
    // contradicted that, so the pass was withdrawn.
    claims_disagree: "The verification of these steps was inconsistent, so they are being treated as unverified. Please confirm them with a qualified lawyer.",
    // Nothing in the analysis rested on a law section that could be resolved,
    // so there was nothing to check it against.
    no_bound_citations: "These steps could not be tied to any specific law section, so they have not been checked. Please confirm them with a qualified lawyer.",
    unverified: "These steps have not been verified against Pakistani law. Please confirm them with a qualified lawyer.",
};

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
    const { T }  = useLang();
    const isMobile = useIsMobile();
    const { completeIntake, addNotification } = useCase();
    const { user } = useAuth();
    const userId = user?._id || user?.id || null;

    // Every remembered intake value is keyed by the signed-in user. See
    // intakeStorage.js for why a shared key left the NEXT account unable to
    // start an intake at all.
    const scopedGet    = (name)        => readIntakeValue(name, userId);
    const scopedSet    = (name, value) => writeIntakeValue(name, userId, value);
    const scopedRemove = (name)        => clearIntakeValue(name, userId);
    const [step, setStep] = useState(1);

    // ── Core intake fields ─────────────────────────────────────────
    const [role, setRole] = useState("");
    const [province, setProvince] = useState("");
    const [caseTypeInput, setCaseTypeInput] = useState("");
    const [urgency, setUrgency] = useState("medium");
    const [description, setDescription] = useState("");

    // ── Backend session ────────────────────────────────────────────
    const [intakeToken, setIntakeToken] = useState(null);
    const [intakeBootError, setIntakeBootError] = useState("");
    const [intakeBooting, setIntakeBooting] = useState(false);
    const intakeBootInFlight = useRef(null);
    const [intakeSubmitting, setIntakeSubmitting] = useState(false);
    const [converting, setConverting] = useState(false);
    // Whether the draft has been promoted. Drives the final screen, which
    // must not claim a case is ready while it is still a draft.
    const [caseConfirmed, setCaseConfirmed] = useState(false);
    const [caseId, setCaseId] = useState(null);
    // The category the CASE currently holds, as opposed to the one selected in
    // the UI. Keeping them apart is what lets the final step tell an actual
    // change from a confirmation and skip a pointless write.
    const [convertedCaseType, setConvertedCaseType] = useState(null);

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
    const [evidenceFiles, setEvidenceFiles]   = useState([]); // [{file_id,filename,size,content_type,uploading,error}]
    const fileInputRef                        = useRef(null);
    const [desiredOutcome, setDesiredOutcome] = useState("");

    // ── UI helpers ─────────────────────────────────────────────────
    const [autosave, setAutosave] = useState(false);
    const steps = [
        T("Select Role", "کردار منتخب کریں"),
        T("Case Input", "کیس کی تفصیل"),
        T("AI Questions", "اے آئی سوالات"),
        T("Case Summary", "کیس کا خلاصہ"),
        T("Categorization", "درجہ بندی"),
    ];
    const completedSteps = Math.max(0, step - 1);
    const progress = (completedSteps / steps.length) * 100;

    // ── Evidence removal, on the SERVER ────────────────────────────
    //
    // The ✕ used to do `setEvidenceFiles(prev => prev.filter(...))` and nothing
    // else. The row vanished, the file stayed on disk and on the intake for
    // ever, the per-intake quota still counted it, and the AI analysis still
    // described it as uploaded. The client had every reason to believe it was
    // gone.
    const [removingFile, setRemovingFile] = useState(null);

    const removeEvidence = async (ef) => {
        // A row that never reached the server (a failed upload) has nothing to
        // delete; drop it locally.
        if (!intakeToken || ef.error || !ef.file_id) {
            setEvidenceFiles(prev => prev.filter(x => x.file_id !== ef.file_id));
            return;
        }
        setRemovingFile(ef.file_id);
        const { error } = await deleteIntakeEvidence(intakeToken, ef.file_id);
        setRemovingFile(null);
        if (error) {
            toast.show(error.message || "Could not remove that file. Please try again.", "error", 3500);
            return;   // keep the row: the file is still there
        }
        setEvidenceFiles(prev => prev.filter(x => x.file_id !== ef.file_id));
        toast.show("File removed.", "success", 2000);
    };

    const downloadEvidence = async (ef) => {
        if (!intakeToken || !ef.file_id) return;
        const result = await downloadIntakeEvidence(
            intakeToken, ef.file_id, ef.filename
        );
        if (result?.error) {
            toast.show(result.error || "Could not download that file.", "error", 3500);
        }
    };

    // ── Export helpers ─────────────────────────────────────────────
    //
    // EVERY value below goes through esc(). The print view is built as a string
    // and handed to document.write(), so an unescaped value is markup: a
    // description containing an <img onerror> tag executed in a popup that
    // shares this origin — able to read the intake token out of localStorage
    // and call the API as the signed-in client.
    //
    // The client's own description is the obvious source, but not the only one:
    // the AI summary, the law list and each citation's note are model output
    // derived from retrieved corpus text, and none of it is trusted markup.
    const esc = escapeHtml;

    const _buildPrintHTML = () => {
        const caseTypeLabel = CASE_TYPES.find(c => c.value === caseTypeInput)?.label || caseTypeInput;
        const provinceLabel = PROVINCES.find(p => p.value === province)?.label || province;
        const date = new Date().toLocaleDateString("en-PK", { year: "numeric", month: "long", day: "numeric" });

        const laws = aiStructured?.applicable_laws?.length
            ? aiStructured.applicable_laws.map((l, i) => `<li>${i + 1}. ${esc(l)}</li>`).join("")
            : "<li>Not available</li>";
        const actions = aiStructured?.recommended_actions?.length
            ? aiStructured.recommended_actions.map((a, i) => `<li>${i + 1}. ${esc(a)}</li>`).join("")
            : "<li>Not available</li>";

        return `<!DOCTYPE html><html><head><meta charset="utf-8"/>
<title>Case Summary — Attorney.AI</title>
<style>
  body{font-family:'Segoe UI',sans-serif;color:#1a1a1a;margin:0;padding:40px;background:#fff;font-size:13px}
  h1{font-size:20px;margin:0 0 4px}
  h2{font-size:13px;font-weight:700;text-transform:uppercase;letter-spacing:1px;color:#00c2a8;margin:22px 0 8px;padding-bottom:6px;border-bottom:1px solid #e5e5e5}
  .header{display:flex;justify-content:space-between;align-items:flex-start;padding-bottom:16px;border-bottom:2px solid #00c2a8;margin-bottom:24px}
  .brand{font-size:18px;font-weight:800;color:#00c2a8}
  .meta{font-size:11px;color:#666;text-align:right;line-height:1.8}
  .grid{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:4px}
  .field{background:#f8f8f8;border-radius:6px;padding:10px 14px}
  .field-label{font-size:10px;text-transform:uppercase;letter-spacing:0.8px;color:#888;margin-bottom:4px}
  .field-value{font-size:13px;font-weight:600;color:#1a1a1a}
  .summary{background:#f8f8f8;border-radius:8px;padding:14px 18px;line-height:1.7;color:#333}
  ul{margin:0;padding-left:18px;line-height:2}
  .risk{display:inline-block;padding:4px 12px;border-radius:20px;font-weight:700;font-size:12px;text-transform:uppercase}
  .risk-low{background:#d1fae5;color:#065f46} .risk-medium{background:#fef3c7;color:#92400e}
  .risk-high{background:#fee2e2;color:#991b1b} .risk-urgent{background:#fee2e2;color:#991b1b}
  .disclaimer{margin-top:32px;padding:12px 16px;background:#fff8e1;border-left:3px solid #f59e0b;font-size:11px;color:#78350f;line-height:1.6;border-radius:0 6px 6px 0}
  @media print{body{padding:20px}button{display:none}}
</style></head><body>
<div class="header">
  <div><div class="brand">Attorney.AI</div><h1>Legal Case Summary</h1></div>
  <div class="meta">
    <div>Case ID: ${caseId ? `…${esc(caseId.slice(-8))}` : "Pending"}</div>
    <div>Date: ${esc(date)}</div>
    <div>Status: Ready</div>
  </div>
</div>

<h2>Case Details</h2>
<div class="grid">
  <div class="field"><div class="field-label">Case Type</div><div class="field-value">${esc(caseTypeLabel)}</div></div>
  <div class="field"><div class="field-label">Province</div><div class="field-value">${esc(provinceLabel)}</div></div>
  <div class="field"><div class="field-label">Your Role</div><div class="field-value">${esc(role || "Not specified")}</div></div>
  <div class="field"><div class="field-label">Urgency</div><div class="field-value">${esc(urgency)}</div></div>
</div>

<h2>Case Summary</h2>
<div class="summary">${esc(aiStructured?.summary || description || "Not available")}</div>

<h2>Applicable Laws</h2>
<ul>${laws}</ul>

<h2>Recommended Actions</h2>
<ul>${actions}</ul>
${aiStructured?.grounding_status && aiStructured.grounding_status !== "grounded"
                ? `<p class="disclaimer" style="margin-top:8px">⚠️ ${esc(GROUNDING_NOTE[aiStructured.grounding_status] || GROUNDING_NOTE.unverified)}</p>`
                : ""}

${aiStructured?.risk_level ? `<h2>Risk Assessment</h2><span class="risk risk-${esc(aiStructured.risk_level)}">${esc(aiStructured.risk_level)} risk</span>` : ""}

<div class="disclaimer">
  <strong>Disclaimer:</strong> This case summary is generated by an AI system for general informational purposes only and does not constitute legal advice. Please consult a qualified Pakistani lawyer before taking any legal action.
</div>
</body></html>`;
    };

    const _buildTextSummary = () => {
        const caseTypeLabel = CASE_TYPES.find(c => c.value === caseTypeInput)?.label || caseTypeInput;
        const provinceLabel = PROVINCES.find(p => p.value === province)?.label || province;
        const date = new Date().toLocaleDateString("en-PK", { year: "numeric", month: "long", day: "numeric" });
        const laws = aiStructured?.applicable_laws?.join("\n  • ") || "Not available";
        const actions = aiStructured?.recommended_actions?.join("\n  • ") || "Not available";
        return [
            `ATTORNEY.AI — LEGAL CASE SUMMARY`,
            `Generated: ${date}`,
            `Case ID: ${caseId || "Pending"}`,
            ``,
            `CASE DETAILS`,
            `Type: ${caseTypeLabel}`,
            `Province: ${provinceLabel}`,
            `Role: ${role || "Not specified"}`,
            `Urgency: ${urgency}`,
            ``,
            `SUMMARY`,
            aiStructured?.summary || description || "Not available",
            ``,
            `APPLICABLE LAWS`,
            `  • ${laws}`,
            ``,
            `RECOMMENDED ACTIONS`,
            `  • ${actions}`,
            aiStructured?.grounding_status && aiStructured.grounding_status !== "grounded"
                ? `  ! ${GROUNDING_NOTE[aiStructured.grounding_status] || GROUNDING_NOTE.unverified}`
                : "",
            aiStructured?.risk_level ? `\nRISK LEVEL: ${aiStructured.risk_level.toUpperCase()}` : "",
            ``,
            `DISCLAIMER: This summary is AI-generated for informational purposes only and does not constitute legal advice. Consult a qualified Pakistani lawyer before taking any action.`,
        ].join("\n");
    };

    const handleDownloadPDF = () => {
        const win = window.open("", "_blank");
        if (!win) { toast.show("Please allow pop-ups to download the PDF", "warn", 3000); return; }
        win.document.write(_buildPrintHTML());
        win.document.close();
        win.onload = () => { win.focus(); win.print(); };
    };

    const handlePrint = () => {
        const win = window.open("", "_blank");
        if (!win) { toast.show("Please allow pop-ups to print", "warn", 3000); return; }
        win.document.write(_buildPrintHTML());
        win.document.close();
        win.onload = () => { win.focus(); win.print(); };
    };

    const handleEmail = () => {
        const subject = encodeURIComponent(`Legal Case Summary — Attorney.AI${caseId ? ` (${caseId.slice(-8)})` : ""}`);
        const body = encodeURIComponent(_buildTextSummary());
        window.location.href = `mailto:?subject=${subject}&body=${body}`;
    };

    // What each step forward actually requires. Steps 3+ used to need only
    // role + province, the same as step 2, so the stepper let a client jump
    // straight from the first screen to the last and reach a "Case Intake
    // Complete" screen with no description, no analysis and no case in the
    // database — the Case ID simply read "Pending".
    //
    // Going BACK is always allowed; only moving ahead of your own progress is
    // gated.
    const stepBlocker = (target) => {
        // A CONVERTED intake cannot be edited. `save_step` refuses a completed
        // intake, so walking back to the questionnaire ends in "Intake already
        // completed" — an error about a screen the stepper invited them onto.
        // Once a case exists, the earlier steps are history.
        if (caseId && target < 4) {
            return "This case has already been analysed — its details can no longer be edited here";
        }
        if (target <= step) return null;
        if (!role) return "Please select your role first";
        if (!province) return "Please select your province";
        if (target >= 3 && !(description.trim() || voiceTranscript.trim()))
            return "Please describe your legal issue before continuing";
        if (target >= 4 && !caseId)
            return "Your case is still being prepared — finish step 3 first";
        // Step 5 is the confirmation screen. Reaching it is safe: the case
        // remains a draft until its final button atomically saves the chosen
        // category and promotes it to open.
        return null;
    };

    const canGoToStep = (target) => stepBlocker(target) === null;

    const tryGoToStep = (target) => {
        const blocker = stepBlocker(target);
        if (blocker) toast.show(blocker, "warn", 2500);
        else setStep(target);
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

    // Put the form back the way the client left it.
    //
    // The token was the ONLY thing a refresh restored, so the browser held a
    // session pointing at a half-filled intake and showed every field blank.
    // The answers were on the server the whole time; nothing asked for them.
    //
    // Only fills fields that are still empty. A restore that overwrote what the
    // client is currently typing would be a worse bug than the one it fixes —
    // this effect can run after the user has already started.
    const restoreFromServer = (data) => {
        const steps = data?.steps || {};
        const s1 = steps["1"] || {};
        const s2 = steps["2"] || {};
        const s3 = steps["3"] || {};
        const s4 = steps["4"] || {};
        const s5 = steps["5"] || {};

        if (s1.party_role) setRole(r => r || (s1.party_role === "plaintiff" ? "Plaintiff" : "Defendant"));
        if (s1.province) setProvince(p => p || s1.province);
        if (s2.case_type) setCaseTypeInput(c => c || s2.case_type);
        if (s2.urgency) setUrgency(u => (u === "medium" ? s2.urgency : u));
        if (s3.incident_description) setDescription(d => d || s3.incident_description);
        if (typeof s4.has_evidence === "boolean") setHasEvidence(h => h || s4.has_evidence);
        if (s4.evidence_description) setEvidenceDesc(e => e || s4.evidence_description);
        if (s5.desired_outcome) setDesiredOutcome(o => o || s5.desired_outcome);

        // Uploaded files, so the ✕ and the list describe what the SERVER holds
        // rather than what this page happens to remember having sent.
        if (Array.isArray(data?.evidence_files) && data.evidence_files.length) {
            setEvidenceFiles(prev => (prev.length ? prev : data.evidence_files));
        }

        // Clarification is an ordered Q&A list; rounds are positions in it.
        const qa = Array.isArray(data?.clarification_qa) ? data.clarification_qa : [];
        if (qa.length) {
            const setQ = [setClarifyQ1, setClarifyQ2, setClarifyQ3, setClarifyQ4];
            const setA = [setClarifyA1, setClarifyA2, setClarifyA3, setClarifyA4];
            qa.slice(0, 4).forEach((entry, i) => {
                if (entry?.q) setQ[i](v => v || entry.q);
                if (entry?.a) setA[i](v => v || entry.a);
            });
            // The round to resume on is the first unanswered question, or done.
            const firstOpen = qa.findIndex(e => !e?.a);
            if (firstOpen === -1) {
                setClarifyDone(true);
                setClarifyRound(5);
            } else {
                setClarifyRound(r => r || Math.min(firstOpen + 1, 4));
            }
        }
    };

    // Start or resume intake session on mount.
    //
    // Waits for the user id: the storage key contains it, so reading before
    // sign-in resolves would miss a resumable token and mint a second session.
    // Everything needed to put the client back into an intake, from one
    // response. Shared by the token path and the server-resume path below, so
    // the two cannot drift into restoring different things.
    const adoptIntake = (data) => {
        // Case data wins over historical step 2 input. The AI may have
        // corrected it, or the client may have confirmed an override later.
        if (data.case_type) {
            setCaseTypeInput(data.case_type);
            setConvertedCaseType(data.case_type);
        } else if (data.ai_case_type) {
            setConvertedCaseType(data.ai_case_type);
        }
        if (data.case_id) {
            setCaseId(data.case_id);
            scopedSet("aai-case-id", data.case_id);
            // The CASE says whether it was confirmed; the intake only says a
            // case was produced. Without this a refresh would offer to confirm
            // an already-open case.
            if (data.case_status && data.case_status !== "draft") {
                setCaseConfirmed(true);
            }
        }
        if (data.ai_structured_case?.summary &&
            data.ai_structured_case.summary !== "pending") {
            setAiStructured(data.ai_structured_case);
        }
        restoreFromServer(data);

        // WHERE they were, not just WHAT they typed.
        //
        // `current_step` was returned by the API and read by nothing, so a
        // refresh mid-intake restored every answer and then showed step 1 — the
        // client had to click forward through screens they had already
        // completed, re-reading their own answers to work out where they were.
        //
        // Capped at 3 for an unfinished intake: step 4 is the analysis screen
        // and needs a case, which only conversion produces.
        if (data.completed) {
            setStep(s => (s < 4 ? 4 : s));
        } else {
            const at = Number(data.current_step) || 1;
            setStep(s => (s > 1 ? s : Math.min(Math.max(at, 1), 3)));
        }
    };

    // ASK THE SERVER, then start fresh only if it has nothing.
    //
    // Resuming used to depend entirely on the token in this browser's storage.
    // Sign-out clears it, clearing site data clears it, and a second device
    // never had it — and after conversion that token is the only route to a
    // draft case awaiting confirmation. So signing out between converting and
    // confirming left a real case its owner could never confirm and this screen
    // could never find. The server knows which intakes are unfinished.
    const resumeOrStart = async () => {
        if (intakeBootInFlight.current) return intakeBootInFlight.current;
        const work = (async () => {
            setIntakeBooting(true);
            setIntakeBootError("");
            const { data: resumable, error: resumeError } = await getResumableIntake();
            if (resumeError) {
                // Unknown is not empty. Starting here would create another
                // intake precisely when the server failed to tell us whether
                // one already exists.
                setIntakeBootError("Could not check your saved intake. Try again when your connection is stable.");
                return;
            }
            if (resumable?.session_token) {
                setIntakeToken(resumable.session_token);
                scopedSet("aai-intake-token", resumable.session_token);
                adoptIntake(resumable);
                return;
            }
            const { data: started, error } = await intakeStart();
            if (started?.session_token) {
                setIntakeToken(started.session_token);
                scopedSet("aai-intake-token", started.session_token);
            } else if (error) {
                setIntakeBootError("Could not start an intake. Please try again.");
            }
        })().finally(() => {
            setIntakeBooting(false);
            intakeBootInFlight.current = null;
        });
        intakeBootInFlight.current = work;
        return work;
    };

    useEffect(() => {
        if (!userId) return;
        const saved = scopedGet("aai-intake-token");
        if (!saved) {
            resumeOrStart();
            return;
        }
        setIntakeToken(saved);
        intakeGet(saved).then(({ data, error }) => {
            if (error || !data) {
                // The token is unusable — expired, or belonging to nobody this
                // account can see. Drop it and ASK THE SERVER rather than
                // starting fresh: an unusable token in storage is exactly the
                // situation where an unfinished intake is most likely to exist.
                scopedRemove("aai-intake-token");
                setIntakeToken(null);
                resumeOrStart();
                return;
            }
            adoptIntake(data);
        });
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [userId]);

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
            // party_role goes with it. The Plaintiff/Defendant choice drove the
            // whole first screen and then lived only in React state — it was
            // never sent anywhere, so nothing downstream could tell which side
            // of the dispute the client was on.
            const { error } = await intakeSaveStep(intakeToken, 1, {
                province,
                party_role: role.toLowerCase(),
            });
            // STOP. This used to warn and advance anyway, so a client whose save
            // failed carried on through the whole questionnaire while the server
            // held none of it — and the loss only surfaced at conversion, as a
            // "steps not completed" error about a step they had filled in.
            if (error) {
                toast.show("Could not save — check your connection and try again.", "error", 3500);
                return;
            }
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
        // Ensure case type is set — fall back to quick JS classify then "civil"
        const effectiveCaseType = caseTypeInput || quickClassify(desc) || "civil";
        if (!caseTypeInput && effectiveCaseType) setCaseTypeInput(effectiveCaseType);

        if (intakeToken) {
            const r2 = await intakeSaveStep(intakeToken, 2, { case_type: effectiveCaseType, urgency });
            const r3 = await intakeSaveStep(intakeToken, 3, {
                incident_description: desc,
                incident_date: null,
                incident_location: null,
            });
            // Same rule as step 1: the description is the single most important
            // thing the client types, and advancing without it stored means the
            // AI analysis later runs on nothing.
            if (r2.error || r3.error) {
                toast.show("Could not save — check your connection and try again.", "error", 3500);
                setClarifyLoading(false);
                return;
            }
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
            // The result was discarded. `convert_to_case` folds the stored Q&A
            // into the text it analyses, so a failure here meant the analysis
            // ran without the client's final answer — and nothing said so. They
            // had just typed it, so its absence is invisible to them.
            const { error: clarifyErr } = await intakeClarify(intakeToken, lastAnswer);
            if (clarifyErr) {
                toast.show(
                    "Could not save your last answer — check your connection and try again.",
                    "error", 4000,
                );
                setConverting(false);
                return;   // do NOT analyse without it
            }
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
            setConvertedCaseType(converted.ai_case_type || null);
            scopedSet("aai-case-id", converted.case_id);
            // THE TOKEN STAYS until the client confirms.
            //
            // It used to be cleared here, at conversion. That was safe while
            // conversion was the last step — but confirmation now happens
            // afterwards, on the next screen, and the token is the only thing
            // that can reopen the intake. Clearing it here meant a refresh
            // between the two started a brand-new intake and left the draft
            // unreachable AND unconfirmable: a case the client owns, that
            // nothing in the UI can ever promote, for the life of the account.
            //
            // `scopedRemove` moved to handleSubmit, where the intake is
            // genuinely finished.

            // If AI corrected the case type, update UI and notify user
            if (converted.type_was_corrected && converted.ai_case_type) {
                const label = { civil: "Civil", criminal: "Criminal", family: "Family", constitutional: "Constitutional" };
                setCaseTypeInput(converted.ai_case_type);
                toast.show(
                    `Case type updated: ${label[converted.user_case_type] || converted.user_case_type} → ${label[converted.ai_case_type] || converted.ai_case_type}`,
                    "info", 5000
                );
            }

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

    // ── Step 4: confirm the draft ──────────────────────────────────
    //
    // This button used to show "✅ Case saved!" and advance the screen. It
    // called nothing: the case had been created and made live back at step 3,
    // so the subtitle inviting the client to "review and confirm before saving"
    // described a save that had already happened and a confirmation with
    // nothing to confirm.
    //
    // The case is now created as a DRAFT, and this is the call that makes it
    // real. Until it lands the case cannot be sent to a lawyer, matched, or
    // booked against.
    const handleContinueToCategory = () => {
        if (!caseId) {
            // No case to confirm — the conversion never completed. Advancing
            // would show a "complete" screen for something that does not exist.
            toast.show("Your case is not ready yet — go back and finish step 3.", "warn", 3500);
            return;
        }
        // The next screen is where the client confirms the authoritative
        // category. Opening the case here allowed matching to observe the old
        // AI category before the client's final choice was persisted.
        setStep(5);
    };

    // ── Final submit (Step 5) ──────────────────────────────────────
    const handleSubmit = async () => {
        setIntakeSubmitting(true);

        if (!caseId || !caseTypeInput) {
            toast.show("Choose a case category before confirming.", "warn", 3000);
            setIntakeSubmitting(false);
            return;
        }

        // One backend CAS stores the category and opens the case. There is no
        // interval in which an open case still carries the superseded type.
        const { error } = await confirmCase(caseId, caseTypeInput);
        if (error) {
            toast.show(error.message || "Could not confirm your case. Please try again.", "error", 4000);
            setIntakeSubmitting(false);
            return;
        }
        setConvertedCaseType(caseTypeInput);
        setCaseConfirmed(true);
        scopedRemove("aai-intake-token");
        setIntakeToken(null);

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
        // WHAT ACTUALLY HAPPENED, not what sounds finished.
        //
        // This said "Case submitted for attorney review!" followed by "You'll
        // hear from us within 2 hours". Conversion creates an OPEN case. It
        // assigns no lawyer, notifies no lawyer, and starts no clock — there is
        // nobody reviewing it and no two-hour commitment behind it. A client who
        // believed that would wait instead of choosing a lawyer, which is the
        // one action that actually moves their matter forward.
        toast.show("Case confirmed — you can now choose a lawyer.", "success", 3000);
        setTimeout(
            () => toast.show(
                "Next: choose a lawyer to send it to — nobody is reviewing it yet.",
                "info", 4500),
            3000,
        );
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
            toast.show(error.message || "Transcription failed. Try again.", "error", 3000);
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
        const detected = quickClassify(voiceTranscript);
        if (detected) setCaseTypeInput(detected);
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
            {intakeBootError && (
                <Card style={{ padding: 16, marginBottom: 16, border: `1px solid ${t.danger}55` }}>
                    <div style={{ color: t.danger, fontSize: 13, marginBottom: 10 }}>{intakeBootError}</div>
                    <BtnOutline disabled={intakeBooting} onClick={resumeOrStart}>
                        {intakeBooting ? "Checking…" : "Try again"}
                    </BtnOutline>
                </Card>
            )}
            {/* Compact horizontal stepper */}
            <div style={{ display: "flex", alignItems: "center", marginBottom: 28, padding: "12px 20px", background: t.card, border: `1px solid ${t.border}`, borderRadius: 12, gap: 0 }}>
                {steps.map((s, i) => {
                    const targetStep = i + 1;
                    const act = step === targetStep;
                    const done = step > targetStep;
                    const locked = !canGoToStep(targetStep) && !done && !act;
                    const isLast = i === steps.length - 1;
                    
                    return (
                        <Fragment key={s}>
                            <div 
                                onClick={() => tryGoToStep(targetStep)}
                                style={{
                                    display: "flex", alignItems: "center", gap: 10,
                                    cursor: locked ? "not-allowed" : "pointer",
                                    opacity: locked ? 0.4 : 1,
                                    transition: "all 0.2s",
                                }}
                            >
                                {/* Step indicator */}
                                <div style={{
                                    width: 28, height: 28, borderRadius: "50%",
                                    background: done ? t.success : act ? t.primary : t.inputBg,
                                    color: (done || act) ? (t.mode === "dark" ? "#1A2E35" : "#fff") : t.textMuted,
                                    fontSize: 12, fontWeight: 800,
                                    display: "flex", alignItems: "center", justifyContent: "center",
                                    boxShadow: act ? `0 0 0 3px ${t.primary}30, 0 4px 12px ${t.primary}25` : "none",
                                    transition: "all 0.2s",
                                }}>
                                    {done ? <Ic n="check" s={13} c={t.mode === "dark" ? "#1A2E35" : "#fff"} /> : targetStep}
                                </div>
                                
                                {/* Step label — circles only on mobile */}
                                {(!isMobile || act) && (
                                    <div style={{
                                        fontSize: 13, fontWeight: act ? 700 : 600,
                                        color: act ? t.primary : done ? t.success : t.text,
                                        whiteSpace: "nowrap",
                                    }}>
                                        {s}
                                    </div>
                                )}
                            </div>
                            
                            {/* Connector line */}
                            {!isLast && (
                                <div style={{
                                    flex: 1, height: 2,
                                    background: done && step > targetStep + 1 ? t.success : t.border,
                                    margin: "0 8px",
                                    transition: "background 0.3s",
                                }} />
                            )}
                        </Fragment>
                    );
                })}
            </div>

            {/* ── STEP 1: Role + Province ─────────────────────────────── */}
            {step === 1 && (
                <Card className="aFadeUp">
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 20, flexWrap: "wrap", gap: 10 }}>
                        <STitle icon="user" sub={T("Your role and province determine how we structure your case", "آپ کا کردار اور صوبہ طے کرتا ہے کہ ہم آپ کا کیس کیسے ترتیب دیں گے")}>{T("Select Your Role & Province", "اپنا کردار اور صوبہ منتخب کریں")}</STitle>
                        <BtnPrimary
                            disabled={!role || !province}
                            onClick={handleStep1Continue}
                            style={{ fontSize: 14, padding: "12px 32px" }}
                        >{T("Continue →", "جاری رکھیں ←")}</BtnPrimary>
                    </div>

                    {/* Role cards */}
                    <div style={{ display: "flex", gap: 16, marginBottom: 24, marginTop: 8, flexDirection: isMobile ? "column" : "row" }}>
                        {["Plaintiff", "Defendant"].map(r => (
                            <div key={r} onClick={() => setRole(r)} style={{ flex: 1, padding: 28, borderRadius: 18, border: `2.5px solid ${role === r ? t.primary : t.border}`, background: role === r ? t.primaryGlow : "transparent", cursor: "pointer", textAlign: "center", transition: "all 0.25s cubic-bezier(0.4, 0, 0.2, 1)", transform: role === r ? "scale(1.05)" : "scale(1)", boxShadow: role === r ? `0 12px 32px ${t.primary}25` : "none" }}>
                                <div style={{ fontSize: 48, marginBottom: 14 }}>{r === "Plaintiff" ? "⚖️" : "🛡️"}</div>
                                <div style={{ fontWeight: 800, color: t.text, fontSize: 18, fontFamily: "'Playfair Display',serif", marginBottom: 4 }}>{r === "Plaintiff" ? T("Plaintiff", "مدعی") : T("Defendant", "مدعا علیہ")}</div>
                                <div style={{ fontSize: 13, color: t.textMuted, marginTop: 6 }}>{r === "Plaintiff" ? T("Filing a legal claim", "قانونی دعویٰ دائر کرنا") : T("Responding to a claim", "دعوے کا جواب دینا")}</div>
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
                        <div style={{ display: "flex", alignItems: "center", gap: 14, padding: "10px 20px", background: t.card, border: `1px solid ${t.border}`, borderRadius: 12 }}>
                            <BtnOutline onClick={() => setStep(1)} style={{ fontSize: 13, padding: "8px 16px", border: "none" }}>← Back</BtnOutline>
                            {/* The REAL case reference, or nothing.
                                This was a hardcoded file number, shown to every
                                client on every intake, on a screen where no case
                                exists yet. A fabricated reference on a legal
                                record is not decoration: a client could quote it
                                to a court or to a lawyer. */}
                            {caseId && (
                                <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "8px 14px", borderRadius: 20, border: `1.5px solid ${t.warn}40`, background: `${t.warn}15`, color: t.warn, fontSize: 12, fontWeight: 700 }}>
                                    📁 Case …{caseId.slice(-8)}
                                </div>
                            )}
                            <div style={{ flex: 1 }}></div>
                            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                                <span style={{ fontSize: 12, fontWeight: 600, color: t.textMuted, whiteSpace: "nowrap" }}>{T("Urgency", "فوری نوعیت")}</span>
                                <select
                                    value={urgency}
                                    onChange={e => setUrgency(e.target.value)}
                                    style={{ fontSize: 13, fontWeight: 600, padding: "7px 12px", borderRadius: 8, border: `1.5px solid ${urgency === "urgent" ? "#ef4444" : urgency === "high" ? "#f97316" : urgency === "medium" ? t.warn : "#22c55e"}`, background: t.inputBg, color: urgency === "urgent" ? "#ef4444" : urgency === "high" ? "#f97316" : urgency === "medium" ? t.warn : "#22c55e", cursor: "pointer", outline: "none" }}
                                >
                                    <option value="low">🟢 {T("Low", "کم")}</option>
                                    <option value="medium">🟡 {T("Medium", "درمیانی")}</option>
                                    <option value="high">🟠 {T("High", "زیادہ")}</option>
                                    <option value="urgent">🔴 {T("Urgent", "فوری")}</option>
                                </select>
                            </div>
                            <BtnPrimary onClick={handleStep2Continue} style={{ fontSize: 13, padding: "8px 18px" }}>{T("Continue →", "جاری رکھیں ←")}</BtnPrimary>
                        </div>


                        <div style={{ display: "grid", gridTemplateColumns: isMobile ? "1fr" : "1.2fr 0.8fr", gap: 24 }}>
                            {/* LEFT PANEL: Input Tab */}
                            <div>
                                <div style={{ display: "inline-flex", background: t.inputBg, borderRadius: 50, padding: 4, marginBottom: 16, border: `1px solid ${t.border}` }}>
                                    {["text", "voice"].map(type => (
                                        <button key={type} onClick={() => setInputType(type)} style={{ display: "flex", alignItems: "center", gap: 8, padding: "8px 20px", borderRadius: 40, border: "none", background: inputType === type ? t.primary : "transparent", color: inputType === type ? (t.mode === "dark" ? "#1A2E35" : "#fff") : t.textMuted, fontSize: 13, fontWeight: 700, cursor: "pointer", transition: "all 0.2s" }}>
                                            <Ic n={type === "text" ? "pen" : "mic"} s={14} c={inputType === type ? (t.mode === "dark" ? "#1A2E35" : "#fff") : t.textMuted} />
                                            {type === "text" ? T("Text Input", "تحریری ان پٹ") : T("Voice Input", "آواز سے ان پٹ")}
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
                                            placeholder={T("Please describe the events leading up to your dispute in detail...", "براہ کرم اپنے تنازعے کے واقعات کی تفصیل لکھیں...")}
                                            value={description}
                                            onChange={e => {
                                                setDescription(e.target.value);
                                                const detected = quickClassify(e.target.value);
                                                if (detected) setCaseTypeInput(detected);
                                            }}
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
                                        <div style={{ fontSize: 15, fontWeight: 700, color: t.text }}>{T("Do you have evidence?", "کیا آپ کے پاس ثبوت ہیں؟")}</div>
                                        <div style={{ fontSize: 11, color: t.textMuted, marginTop: 2 }}>{T("Documents, photos, or witnesses", "دستاویزات، تصاویر یا گواہ")}</div>
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
                                    <div style={{ display: "flex", flexDirection: "column", gap: 10, marginBottom: 16 }}>
                                        {/* Hidden file input */}
                                        <input
                                            ref={fileInputRef}
                                            type="file"
                                            multiple
                                            accept=".pdf,.doc,.docx,.jpg,.jpeg,.png,.gif,.webp"
                                            style={{ display: "none" }}
                                            onChange={async e => {
                                                const files = Array.from(e.target.files || []);
                                                e.target.value = "";
                                                if (!intakeToken) { toast.show("Start intake first to upload files", "error"); return; }
                                                for (const f of files) {
                                                    const tempId = `temp-${Date.now()}-${Math.random()}`;
                                                    setEvidenceFiles(prev => [...prev, { file_id: tempId, filename: f.name, size: f.size, content_type: f.type, uploading: true, error: null }]);
                                                    const { data, error } = await uploadIntakeEvidence(intakeToken, f);
                                                    setEvidenceFiles(prev => prev.map(ef =>
                                                        ef.file_id === tempId
                                                            ? error
                                                                ? { ...ef, uploading: false, error: error?.detail || "Upload failed" }
                                                                : { ...data, uploading: false, error: null }
                                                            : ef
                                                    ));
                                                }
                                            }}
                                        />
                                        {/* Drop zone / upload button */}
                                        <div
                                            onClick={() => fileInputRef.current?.click()}
                                            style={{ border: `1.5px dashed ${t.primary}60`, borderRadius: 10, padding: "14px 12px", display: "flex", alignItems: "center", justifyContent: "center", gap: 8, cursor: "pointer", background: `${t.primary}08`, transition: "background 0.15s" }}
                                            onMouseEnter={e => e.currentTarget.style.background = `${t.primary}14`}
                                            onMouseLeave={e => e.currentTarget.style.background = `${t.primary}08`}
                                        >
                                            <Ic n="file" s={15} c={t.primary} />
                                            <span style={{ fontSize: 12, fontWeight: 700, color: t.primary }}>{T("Upload Files", "فائلیں اپ لوڈ کریں")}</span>
                                            {/* The REAL limits. This said "max 10 MB each" only, so a client hit
     the file-count or total-size cap with no warning that either
     existed — the caption described the one limit it knew about. */}
                                            <span style={{ fontSize: 11, color: t.textMuted }}>PDF, Word, JPG, PNG · max 10 MB each · up to 12 files, 40 MB total</span>
                                        </div>
                                        {/* Uploaded file list */}
                                        {evidenceFiles.length > 0 && (
                                            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                                                {evidenceFiles.map(ef => {
                                                    const icon = ef.content_type?.startsWith("image/") ? "🖼️" : ef.content_type === "application/pdf" ? "📄" : "📝";
                                                    const kb   = ef.size ? `${(ef.size / 1024).toFixed(0)} KB` : "";
                                                    // Absent until the intake has been converted — extraction runs
                                                    // then, and before that there is nothing honest to claim.
                                                    const read = extractionLabel(ef);
                                                    return (
                                                        <div key={ef.file_id} style={{ display: "flex", alignItems: "center", gap: 8, padding: "7px 10px", borderRadius: 8, background: ef.error ? "#fef2f2" : t.inputBg, border: `1px solid ${ef.error ? "#fca5a5" : t.border}` }}>
                                                            <span style={{ fontSize: 15 }}>{icon}</span>
                                                            <div style={{ flex: 1, minWidth: 0 }}>
                                                                <div style={{ fontSize: 12, fontWeight: 600, color: ef.error ? "#ef4444" : t.text, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                                                                    {ef.filename}
                                                                </div>
                                                                <div style={{ fontSize: 10, color: t.textMuted }}>{ef.error || (ef.uploading ? "Uploading…" : kb)}</div>
                                                                {/* Uploading and upload-failure already have the line above;
                                                                    this covers the other five states, including the
                                                                    storage-only one that is known before any extraction runs
                                                                    and the legacy-Urdu-encoding one, which carries its own
                                                                    remedy in the detail line. */}
                                                                {!ef.uploading && !ef.error && (
                                                                    <div data-testid={`extraction-${ef.file_id}`} data-state={read.state} style={{ fontSize: 10, marginTop: 2, whiteSpace: "normal", color: EXTRACTION_TONE_COLOUR[read.tone] || t.textMuted, fontWeight: read.tone === TONE_OK || read.tone === TONE_NEUTRAL ? 400 : 600 }}>
                                                                        {EXTRACTION_TONE_ICON[read.tone] || "•"} {read.title}
                                                                        {read.detail ? ` — ${read.detail}` : ""}
                                                                    </div>
                                                                )}
                                                            </div>
                                                            {ef.uploading && <div style={{ width: 12, height: 12, border: `2px solid ${t.primary}`, borderTopColor: "transparent", borderRadius: "50%", animation: "spin 0.7s linear infinite" }} />}
                                                            {!ef.uploading && !ef.error && (
                                                                <button
                                                                    title="Download"
                                                                    onClick={() => downloadEvidence(ef)}
                                                                    style={{ background: "none", border: "none", cursor: "pointer", color: t.textMuted, fontSize: 13, lineHeight: 1, padding: 2 }}>⭳</button>
                                                            )}
                                                            {!ef.uploading && (
                                                                <button
                                                                    title="Remove"
                                                                    disabled={removingFile === ef.file_id}
                                                                    onClick={() => removeEvidence(ef)}
                                                                    style={{ background: "none", border: "none", cursor: "pointer", color: t.textMuted, fontSize: 14, lineHeight: 1, padding: 2, opacity: removingFile === ef.file_id ? 0.4 : 1 }}>✕</button>
                                                            )}
                                                        </div>
                                                    );
                                                })}
                                            </div>
                                        )}
                                        {/* Optional notes */}
                                        <textarea
                                            placeholder="Optional: add notes about witnesses, context, or additional evidence…"
                                            value={evidenceDesc}
                                            onChange={e => setEvidenceDesc(e.target.value)}
                                            style={{ width: "100%", minHeight: 64, background: t.inputBg, border: `1px solid ${t.border}`, borderRadius: 8, padding: "8px 12px", color: t.text, fontSize: 12, resize: "vertical", outline: "none", fontFamily: "inherit" }}
                                        />
                                    </div>
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
                    <div style={{ display: "flex", alignItems: "center", gap: 14, padding: "10px 20px", background: t.card, border: `1px solid ${t.border}`, borderRadius: 12 }}>
                        <BtnOutline onClick={() => setStep(2)} style={{ fontSize: 13, padding: "8px 16px" }}>← Back</BtnOutline>
                        <div style={{ flex: 1 }} />
                        {/* "Next Question" for rounds 1-3; "Complete & Continue" on round 4 or when done */}
                        {(clarifyRound >= 1 && clarifyRound <= 3) && !clarifyDone ? (
                            <BtnPrimary
                                disabled={clarifyLoading || !getCurrentAnswer().trim()}
                                onClick={handleClarifyNext}
                                style={{ fontSize: 13, padding: "8px 18px" }}
                            >
                                {clarifyLoading ? "Thinking…" : "Next Question →"}
                            </BtnPrimary>
                        ) : (
                            <BtnPrimary
                                disabled={converting || clarifyLoading || (clarifyRound === 4 && !clarifyA4.trim())}
                                onClick={handleConvertAndSummarise}
                                style={{ fontSize: 13, padding: "8px 18px", opacity: converting ? 0.7 : 1 }}
                            >
                                {converting ? "Analysing case…" : clarifyLoading ? "Thinking…" : "Complete & Continue →"}
                            </BtnPrimary>
                        )}
                    </div>
                    <div>
                        <div style={{ fontFamily: "'Fraunces',serif", fontSize: 24, fontWeight: 600, color: t.text, marginBottom: 4 }}>AI Follow-up Questions</div>
                        <div style={{ fontSize: 13, color: t.textMuted, marginBottom: 20 }}>Our AI has analysed your case and identified the most important missing facts.</div>
                    </div>

                    <div style={{ display: "grid", gridTemplateColumns: isMobile ? "1fr" : "1fr 300px", gap: 14 }}>
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
                                        <div style={{ fontSize: 14, fontWeight: 700, color: t.text }}>{T("Question Progress", "سوالات کی پیش رفت")}</div>
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
                                        <div style={{ fontSize: 14, fontWeight: 700, color: t.text }}>{T("Case Preview", "کیس کا جائزہ")}</div>
                                        <div style={{ fontSize: 11, color: t.textMuted }}>{T("Building from answers", "جوابات سے تیار ہو رہا ہے")}</div>
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
                    <div style={{ display: "flex", alignItems: "center", gap: 14, padding: "10px 20px", background: t.card, border: `1px solid ${t.border}`, borderRadius: 12 }}>
                        <BtnOutline onClick={() => setStep(3)} style={{ fontSize: 13, padding: "8px 16px" }}>← Back</BtnOutline>
                        <div style={{ flex: 1 }} />
                        <BtnPrimary onClick={handleContinueToCategory} style={{ fontSize: 13, padding: "8px 18px" }}>{T("Continue to Category →", "درجہ بندی کی طرف جائیں ←")}</BtnPrimary>
                    </div>
                    <div>
                        <div style={{ fontFamily: "'Fraunces',serif", fontSize: 24, fontWeight: 600, color: t.text, marginBottom: 4 }}>AI-Generated <em>Case Summary</em></div>
                        <div style={{ fontSize: 13, color: t.textMuted, marginBottom: 20 }}>Review and confirm your structured case before saving</div>
                    </div>

                    <div style={{ display: "grid", gridTemplateColumns: isMobile ? "1fr" : "1fr 300px", gap: 14 }}>
                        {/* Main panel */}
                        <Card style={{ padding: 0, overflow: "hidden", display: "flex", flexDirection: "column" }}>
                            <div style={{ padding: "16px 20px", borderBottom: `1px solid ${t.border}`, background: t.inputBg, display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                                <div>
                                    <div style={{ fontSize: 14, fontWeight: 600, color: t.text }}>Structured Case Summary — AI-Generated</div>
                                    <div style={{ fontSize: 11, color: t.textMuted, marginTop: 2 }}>
                                        {caseId ? `Case ID: …${caseId.slice(-8)}` : "Processing…"} · Auto-generated by AI
                                    </div>
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

                                        {/* WHAT THE ANALYSIS DID NOT SEE.
                                            Shown beside the summary, not on the upload screen, because
                                            this is the screen where the client decides whether to trust
                                            the analysis. The previous wording — "some uploaded files
                                            could not be read" — was true but unactionable: it never said
                                            which file, or how much of it, so a bundle read down to its
                                            cover sheet looked the same as one missing a blurred photo. */}
                                        {(() => {
                                            const records = Array.isArray(aiStructured.evidence_extraction) ? aiStructured.evidence_extraction : [];
                                            if (!records.length) return null;
                                            const nameOf = id => (evidenceFiles.find(f => f.file_id === id) || {}).filename || "an uploaded file";
                                            const gaps = incompleteFiles(records.map(r => ({ ...r, extraction_status: r.status })));
                                            if (!gaps.length) {
                                                return (
                                                    <div style={{ padding: "10px 14px", borderRadius: 10, background: t.inputBg, border: `1px solid ${t.border}`, fontSize: 12, color: t.textMuted }}>
                                                        ✓ All {records.length} uploaded file(s) were read in full and included in this analysis.
                                                    </div>
                                                );
                                            }
                                            return (
                                                <div data-testid="evidence-gaps" style={{ padding: "12px 14px", borderRadius: 10, background: "#fffbeb", border: "1px solid #fcd34d", fontSize: 12, color: "#78350f" }}>
                                                    <div style={{ fontWeight: 700, marginBottom: 6 }}>
                                                        ⚠ This analysis did not see all of your evidence
                                                    </div>
                                                    <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
                                                        {gaps.map(g => {
                                                            const label = extractionLabel(g);
                                                            return (
                                                                <div key={g.file_id}>
                                                                    <strong>{nameOf(g.file_id)}</strong> — {label.title}
                                                                    {label.detail ? ` (${label.detail})` : ""}
                                                                </div>
                                                            );
                                                        })}
                                                    </div>
                                                    <div style={{ marginTop: 7, lineHeight: 1.6 }}>
                                                        Anything above was not part of the analysis. Type those details into
                                                        your description, upload a text-based copy, or continue knowing they
                                                        were left out.
                                                    </div>
                                                </div>
                                            );
                                        })()}

                                        {/* Applicable Laws */}
                                        {aiStructured.applicable_laws?.length > 0 && (
                                            <div style={{ background: t.inputBg, border: `1px solid ${t.border}`, borderRadius: 12, padding: "16px 20px" }}>
                                                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
                                                    <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: "1px", textTransform: "uppercase", color: t.primary }}>⚖️ Applicable Laws</div>
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
                                                {/* The backend now says whether these actions were actually
                                                    checked against retrieved law. "grounded" is the only
                                                    status that means they were; everything else means the
                                                    check could not run, and that must be visible here rather
                                                    than buried in the summary paragraph. */}
                                                {aiStructured.grounding_status && aiStructured.grounding_status !== "grounded" && (
                                                    <div style={{ marginTop: 12, paddingTop: 10, borderTop: `1px solid ${t.border}`, display: "flex", gap: 8, alignItems: "flex-start" }}>
                                                        <span style={{ fontSize: 13, lineHeight: 1.5 }}>⚠️</span>
                                                        <span style={{ fontSize: 12, color: t.textMuted, lineHeight: 1.55 }}>
                                                            {GROUNDING_NOTE[aiStructured.grounding_status] || GROUNDING_NOTE.unverified}
                                                        </span>
                                                    </div>
                                                )}
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
                                    // `body` carries JSX, not an HTML string. It used to be a
                                    // template literal rendered through dangerouslySetInnerHTML,
                                    // which meant the "Case Description" card — raw text the user
                                    // typed — was parsed as markup. Only the "Parties" card ever
                                    // needed real elements, so it supplies them directly and React
                                    // escapes everything else.
                                    [
                                        {
                                            icon: "👤", title: "Parties", c: t.primary,
                                            body: (
                                                <>
                                                    <strong>Role:</strong> {role}<br />
                                                    <strong>Province:</strong> {PROVINCES.find(p => p.value === province)?.label || province}
                                                </>
                                            ),
                                        },
                                        { icon: "⚖️", title: "Case Type", body: `${CASE_TYPES.find(c => c.value === caseTypeInput)?.label || caseTypeInput} — Urgency: ${urgency}`, c: t.primary },
                                        { icon: "📋", title: "Case Description", body: description || voiceTranscript || "No description provided.", c: t.primary },
                                        { icon: "🎯", title: "Desired Outcome", body: "Legal assistance and representation.", c: t.primary },
                                    ].map((s, idx) => (
                                        <div key={idx} style={{ background: t.inputBg, border: `1px solid ${t.border}`, borderRadius: 12, padding: "16px 20px" }}>
                                            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
                                                <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: "1px", textTransform: "uppercase", color: s.c }}>{s.icon} {s.title}</div>
                                            </div>
                                            <div style={{ fontSize: 13, color: t.textDim, lineHeight: 1.7, whiteSpace: "pre-wrap" }}>{s.body}</div>
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
                    <div style={{ display: "flex", alignItems: "center", gap: 14, padding: "10px 20px", background: t.card, border: `1px solid ${t.border}`, borderRadius: 12 }}>
                        <BtnOutline onClick={() => setStep(4)} style={{ fontSize: 13, padding: "8px 16px" }}>← Back</BtnOutline>
                        <div style={{ flex: 1 }} />
                        <BtnPrimary
                            disabled={intakeSubmitting}
                            onClick={() => { if (!intakeSubmitting) handleSubmit(); }}
                            style={{ fontSize: 13, padding: "8px 18px", opacity: intakeSubmitting ? 0.7 : 1 }}>
                            {intakeSubmitting ? "Confirming…" : "Confirm Category & Open Case →"}
                        </BtnPrimary>
                    </div>
                    <div>
                        <div style={{ fontFamily: "'Fraunces',serif", fontSize: 24, fontWeight: 600, color: t.text, marginBottom: 4 }}>Case <em>Categorization</em></div>
                        <div style={{ fontSize: 13, color: t.textMuted, marginBottom: 20 }}>Confirm your case category before final submission</div>
                    </div>

                    <div style={{ display: "grid", gridTemplateColumns: isMobile ? "1fr" : "1fr 300px", gap: 14 }}>
                        <div>
                            <div style={{ padding: "16px 20px", borderRadius: 16, background: `linear-gradient(135deg, ${t.primary}15, ${t.primary}05)`, border: `1px solid ${t.primary}30`, marginBottom: 16, display: "flex", alignItems: "center", gap: 12 }}>
                                <div style={{ fontSize: 18 }}>🤖</div>
                                <div style={{ fontSize: 13, color: t.textDim, lineHeight: 1.6 }}>
                                    {caseTypeInput
                                        ? <>AI classified your case as <strong style={{ color: t.primary }}>{CASE_TYPES.find(c => c.value === caseTypeInput)?.label || caseTypeInput}</strong>. Confirm or change below.</>
                                        : <>Select the category that best describes your legal issue.</>
                                    }
                                </div>
                            </div>

                            <div style={{ display: "grid", gridTemplateColumns: isMobile ? "1fr" : "repeat(2, 1fr)", gap: 12, marginBottom: 20 }}>
                                {[
                                    { id: "civil",          i: "⚖️",  n: "Civil Law",          d: "Property disputes, contracts, personal injury" },
                                    { id: "criminal",       i: "🚔",  n: "Criminal Law",        d: "FIR filing, bail applications, criminal defense" },
                                    { id: "family",         i: "👨‍👩‍👧",  n: "Family Law",          d: "Divorce, custody, inheritance, guardianship" },
                                    { id: "constitutional", i: "📜",  n: "Constitutional Law",  d: "Fundamental rights, writ petitions" },
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
                                <div style={{ fontFamily: "'Fraunces',serif", fontSize: 18, fontWeight: 600, color: t.primary, marginBottom: 6 }}>{T(caseConfirmed ? "Case Intake Complete" : "Ready to Confirm", "کیس کی تصدیق")}</div>
                                {/* "ready for review" implies somebody is about to review it. Nothing
     is: conversion creates an open case and stops. The next move is the
     client's, and saying so is the difference between them choosing a
     lawyer today and waiting for a call that was never scheduled. */}
                                <div style={{ fontSize: 12, color: t.textMuted, marginBottom: 20 }}>
                                    {caseConfirmed
                                        ? T("Your case is open. Choose a lawyer to send it to — it has not been sent to anyone yet.", "آپ کا کیس کھل چکا ہے۔ اسے بھیجنے کے لیے وکیل منتخب کریں — ابھی یہ کسی کو نہیں بھیجا گیا۔")
                                        : T("Review the category, then confirm it to open your case. Until confirmation succeeds, this remains a draft and cannot be matched or sent.", "درجہ بندی کا جائزہ لیں، پھر کیس کھولنے کے لیے اس کی تصدیق کریں۔ کامیاب تصدیق تک یہ مسودہ رہے گا اور اسے میچ یا بھیجا نہیں جا سکتا۔")}
                                </div>
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
                                        <span style={{ color: t.textMuted }}>Status</span><Badge type={caseConfirmed ? "success" : "warn"}>{caseConfirmed ? "Open" : "Draft"}</Badge>
                                    </div>
                                </div>
                                <BtnPrimary
                                    disabled={!caseConfirmed}
                                    onClick={() => {
                                        if (!caseConfirmed) return;
                                        const dest = caseId ? `/lawyers?case_id=${caseId}` : "/lawyers";
                                        router.push(dest);
                                    }}
                                    style={{ width: "100%", marginTop: 20, padding: 14, fontSize: 14, opacity: caseConfirmed ? 1 : 0.55 }}
                                >{T("Find a Lawyer →", "وکیل تلاش کریں ←")}</BtnPrimary>
                            </Card>

                            <Card style={{ padding: 20 }}>
                                <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 16 }}>
                                    <div style={{ width: 34, height: 34, borderRadius: 10, background: t.inputBg, border: `1px solid ${t.border}`, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 16 }}>📄</div>
                                    <div style={{ fontSize: 14, fontWeight: 700, color: t.text }}>{T("Export Case", "کیس ایکسپورٹ کریں")}</div>
                                </div>
                                <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                                    <BtnOutline onClick={handleDownloadPDF} style={{ padding: "10px", fontSize: 12, justifyContent: "center" }}>📄 Download Case PDF</BtnOutline>
                                    <BtnOutline onClick={handleEmail} style={{ padding: "10px", fontSize: 12, justifyContent: "center" }}>✉️ Email Summary</BtnOutline>
                                    <BtnOutline onClick={handlePrint} style={{ padding: "10px", fontSize: 12, justifyContent: "center" }}>🖨️ Print</BtnOutline>
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
