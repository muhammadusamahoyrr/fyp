'use client';
// Lawyer AI Legal Page — paste your code here
import { useState, useEffect, useRef, useCallback, useMemo } from "react";
import { useTheme, ThemeCtx } from "./theme.js";
import { DRAFTING_TOKENS_CSS, draftingMode, themeOnTokens } from "./draftingTheme.js";
import { useCase } from "./theme.js";
import { Icon, I } from "./icons.jsx";
import {
    listCases, aiResearch, cancelResearchTurn, researchTurnStatus,
    searchResearchConversations, rateAnswer, aiProvenance, openSourceDocument,
    listResearchConversations, createResearchConversation,
    getResearchConversation, renameResearchConversation,
    archiveResearchConversation, deleteResearchConversation,
} from "@/lib/api.js";
import {
    toResearchMessages, groupConversations, readActiveSession,
    writeActiveSession, mergeMessages,
} from "@/lib/conversations.js";
import {
    createGeneration, newAttempt, retryAttempt, isAmbiguousFailure,
} from "@/lib/attempt.js";
import { useAuth } from "@/context/AuthContext.jsx";
/* Shared with the client chatbot and the case-workspace AI tab. Each of the
   three used to map `citations` itself and they had already drifted — the
   workspace tab dropped `url` and `source`, so a judgment that linked to a
   court PDF here was an unclickable label there. */
import {
    CITATION_GROUPS, REPEALED, normaliseCitations, citationsInGroup,
    repealNote, shortRequestId, copyText, auditNotice,
} from "@/lib/trust.js";

/* Calibrated-confidence bands from the server (ai/answer_confidence.py).
   The lawyer surface shows the band AND the raw figure AND which evidence source
   produced it — a research user needs the number; a client does not. */
const CONF_LABEL = { high: "High", moderate: "Moderate", low: "Low" };
const CONF_COLOR = { high: "#22c55e", moderate: "#f59e0b", low: "#ef4444" };

/* Per-claim support verdicts (answer_citations.py). The lawyer wording states
   the legal question precisely rather than reassuringly: "supported" means the
   cited section establishes the proposition, nothing more. It does NOT speak to
   whether the section is still in force — that is citation_verification's
   OMITTED verdict, which runs on the drafting path, not here. */
const CLAIM_UI = {
    supported:   { icon: "✓", color: "#22c55e", label: "Supported",   note: "cited source establishes this" },
    partial:     { icon: "◐", color: "#f59e0b", label: "Partial",     note: "claim goes beyond what the source states" },
    unsupported: { icon: "✕", color: "#ef4444", label: "Unsupported", note: "cited source does not establish this" },
    unassessed:  { icon: "–", color: "#94a3b8", label: "Unassessed",  note: "not checked — no resolvable source" },
};
const CLAIM_ORDER = ["unsupported", "partial", "unassessed", "supported"];

/* Repeal currency (answer_citations.currency_for). Two values only. `unknown`
   is NOT a clean bill of health: repeal data covers 4 of the 43 statutes in the
   corpus and is a self-declared lower bound, amendment is not modelled at all,
   and no statute carries an as-of date. A repealed provision OVERRIDES its
   support verdict — a section can genuinely establish the proposition and still
   have been abolished, which is the fact that decides whether it can be filed.
   REPEALED and repealNote now come from lib/trust.js, so the three AI surfaces
   cannot word the same finding differently. */
const CURRENCY_TEXT = {
    repealed: "Repealed provision \u2014 do not rely on this authority",
    unknown:  "Current status not verified",
};

/* ── Provenance: the machinery behind one answer ──────────────────────────
   Lawyer-only, and deliberately so. A client is shown the FINDINGS — citation
   status, claim support, repeal warnings. This is how they were produced:
   which model answered, which provider failed over on the way, what the
   evidence weighed, and which corpus versions were in force.

   The server returns a whitelist projection (app/services/provenance_view.py),
   so nothing here can render a prompt, a key, or a provider's response body
   even if a future field were added to the stored record. This component
   therefore never has to decide what is safe to show — it shows what arrives. */
function ProvenancePanel({ requestId, onClose, t }) {
    const [state, setState] = useState({ loading: true, error: "", view: null });

    useEffect(() => {
        let live = true;
        setState({ loading: true, error: "", view: null });
        aiProvenance(requestId).then(({ data, error }) => {
            if (!live) return;
            if (error || !data) {
                setState({ loading: false, view: null,
                           error: error?.message || "Audit record not available" });
            } else {
                setState({ loading: false, error: "", view: data });
            }
        });
        return () => { live = false; };
    }, [requestId]);

    const v = state.view;
    const row = (label, value) => (
        <div style={{ display: "flex", gap: 10, padding: "3px 0", fontSize: 11.5 }}>
            <span style={{ color: t.textFaint, minWidth: 132, flexShrink: 0 }}>{label}</span>
            <span className="mono" style={{ color: t.text, wordBreak: "break-word" }}>
                {value === null || value === undefined || value === "" ? "—" : String(value)}
            </span>
        </div>
    );
    const section = (title, children) => (
        <div style={{ marginBottom: 12 }}>
            <div style={{ fontSize: 10, fontWeight: 700, color: t.textMuted, textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 4 }}>
                {title}
            </div>
            {children}
        </div>
    );

    return (
        <div style={{ marginTop: 8, padding: "12px 14px", borderRadius: 10, background: t.card, border: `1px solid ${t.border}` }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
                <span style={{ fontSize: 12, fontWeight: 700, color: t.text }}>Audit trail</span>
                <button onClick={onClose} style={{ border: "none", background: "transparent", color: t.textMuted, cursor: "pointer", fontSize: 14, lineHeight: 1 }}>×</button>
            </div>

            {state.loading && <div style={{ fontSize: 11.5, color: t.textMuted }}>Loading…</div>}
            {state.error && <div style={{ fontSize: 11.5, color: "#f59e0b" }}>{state.error}</div>}

            {v && (
                <>
                    {section("Answer", <>
                        {row("Request", v.request_id)}
                        {row("Recorded", v.created_at)}
                        {row("Turn", v.turn_type)}
                        {/* Lets a lawyer prove the text they are holding is the
                            text this record describes, without the audit store
                            keeping a second copy of it. */}
                        {row("Answer digest", v.answer?.sha256)}
                    </>)}

                    {section("Model", <>
                        {row("Answered by", v.model?.answered_by
                            ? `${v.model.answered_by.provider} · ${v.model.answered_by.model}`
                            : "no generation this turn")}
                        {row("Origin", v.model?.origin)}
                        {(v.model?.attempts || []).length > 1 && (
                            <div style={{ marginTop: 4 }}>
                                {v.model.attempts.map((a, i) => (
                                    <div key={i} style={{ fontSize: 11, color: a.outcome === "failure" ? "#f59e0b" : t.textMuted, paddingLeft: 2 }}>
                                        {a.outcome === "failure" ? "✕" : "✓"} {a.provider} · {a.model}
                                        {a.is_fallback ? " (fallback)" : ""}
                                        {/* A classified reason, never the provider's
                                            response body — those carry account ids. */}
                                        {a.reason ? ` — ${a.reason}` : ""}
                                    </div>
                                ))}
                            </div>
                        )}
                    </>)}

                    {section("Decision", <>
                        {row("Verdict", v.decision?.verdict)}
                        {row("Evidence source", v.decision?.source)}
                        {row("Calibrated confidence", v.decision?.confidence)}
                        {row("Grounded", String(!!v.decision?.grounded))}
                        {row("Served from cache", String(!!v.decision?.cache_hit))}
                        {row("Convergence", v.decision?.convergence)}
                    </>)}

                    {section("Citation grounding", v.citation_grounding?.measurable ? <>
                        {row("Cited", v.citation_grounding.cited_count)}
                        {row("Found in evidence", v.citation_grounding.grounded_count)}
                        {row("Could not place", (v.citation_grounding.ungrounded || []).join(", "))}
                        <div style={{ fontSize: 10, color: t.textFaint, marginTop: 4, lineHeight: 1.5 }}>
                            A measurement, not an error rate. Correct law recalled from the
                            model&apos;s own memory counts as ungrounded here.
                        </div>
                    </> : (
                        <div style={{ fontSize: 11, color: t.textMuted }}>
                            {v.citation_grounding?.reason || "Not measurable for this answer."}
                        </div>
                    ))}

                    {section("Evidence", <>
                        {row("Statute chunks", (v.evidence?.statutes || []).length)}
                        {row("Judgments", (v.evidence?.judgments || []).length)}
                        {row("Tools", (v.evidence?.tools || []).map(x => `${x.tool}${x.ok ? "" : " (failed)"}`).join(", "))}
                        {row("Web search", String(!!v.evidence?.web_search_used))}
                    </>)}

                    {v.case?.case_id && section("Case", <>
                        {row("Case", v.case.case_id)}
                        {/* Identifies WHICH context was used without the audit
                            becoming a second copy of privileged case material. */}
                        {row("Context digest", v.case.context_hash)}
                        {row("Record version", v.case.record_version)}
                        {row("Used by", (v.case.used_by || []).join(", "))}
                    </>)}

                    {section("Reproducibility", <>
                        {row("Embedding model", v.versions?.embedding_model)}
                        {row("Chunking", v.versions?.chunking)}
                        {row("Schema", v.versions?.schema)}
                        {row("Total time", v.execution?.total_ms ? `${v.execution.total_ms} ms` : null)}
                    </>)}

                    {v.invariant_violation && (
                        <div style={{ fontSize: 11, color: "#f59e0b", borderTop: `1px solid ${t.border}`, paddingTop: 8 }}>
                            ⚠ This turn ran under a repaired contract: {v.invariant_violation}.
                            The answer reached you, but it was produced from suspect state.
                        </div>
                    )}
                </>
            )}
        </div>
    );
}

/* A citation whose source document we hold.
   Owns its own failure state: the chip is rendered inside the message list, and
   a failure to open one source is about that chip, not about the answer — it
   must not be reported where an answer-level error goes. */
function SourceChip({ citation, text, style, title }) {
    const [failed, setFailed] = useState("");
    return (
        <button
            style={{ ...style, cursor: "pointer", fontFamily: "inherit" }}
            title={failed || `${title}${title ? " · " : ""}opens the source document`}
            onClick={async () => {
                setFailed("");
                const res = await openSourceDocument(citation.sourceUrl, citation.label);
                if (res.error) {
                    setFailed(res.error);
                    setTimeout(() => setFailed(""), 4000);
                }
            }}>
            {text} {failed ? "⚠" : "↗"}
        </button>
    );
}

/* The id that names one answer. Copyable because the two things a lawyer does
   with it — quote it in a report, and open its audit trail — both need the
   whole string, and the display form is truncated. */
function RequestIdChip({ requestId, open, onToggle, t }) {
    const [copied, setCopied] = useState(false);
    return (
        <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
            <button
                onClick={async () => {
                    const ok = await copyText(requestId);
                    setCopied(ok);
                    setTimeout(() => setCopied(false), 1600);
                }}
                title={`Copy request id ${requestId}`}
                className="mono"
                style={{
                    border: `1px solid ${t.border}`, background: "transparent",
                    color: t.textFaint, borderRadius: 5, cursor: "pointer",
                    fontSize: 10, padding: "1px 6px", fontFamily: "inherit",
                }}>
                {copied ? "copied ✓" : `id ${shortRequestId(requestId)}`}
            </button>
            <button
                onClick={onToggle}
                title="Show how this answer was produced"
                style={{
                    border: `1px solid ${t.border}`, background: open ? t.primaryGlow : "transparent",
                    color: open ? t.primary : t.textFaint, borderRadius: 5,
                    cursor: "pointer", fontSize: 10, padding: "1px 6px",
                }}>
                audit {open ? "▴" : "▾"}
            </button>
        </span>
    );
}

// ============================================================
// AI LEGAL PAGE — Full chatbot UI with case context injection
// ============================================================
/* What to tell the lawyer when a research turn fails. Every failure used to
   read "AI service unavailable", including the ones a lawyer can act on: a
   question too long to send, a case they no longer have access to, or a
   conversation tied to a different matter. */
function researchErrorText(e) {
    const server = e?.fromServer ? e.message : "";
    switch (e?.status) {
        case 403: return "You don't have access to that case any more, so this question was not sent.";
        case 409: return server || "This conversation can't take that question. Start a new thread and try again.";
        case 413: return "That question is too long to send. Please shorten it and try again.";
        case 422: return server ? `The question couldn't be processed: ${server}` : "The question couldn't be processed.";
        default: return "AI service unavailable. Please try again.";
    }
}

/* The AI Assistant on the lawyer document theme (2026-10-09), like Cases and
 * Appointments: type, ground and neutral colours from draftingTheme.js;
 * layout and behaviour as they were. */
export const AI_THEME_CSS = `[data-ai-ws]{height:100%;min-height:0;display:flex;flex-direction:column;color:var(--ink);font-family:"Hanken Grotesk",system-ui,sans-serif;-webkit-font-smoothing:antialiased;background:radial-gradient(900px 360px at 25% -80px,var(--glow),transparent 70%) no-repeat,var(--bg)}
[data-ai-ws] > div:not(style){flex:1;min-height:0}
[data-ai-ws] .serif{font-family:"Literata",Georgia,serif!important;letter-spacing:-.01em}
[data-ai-ws] input,[data-ai-ws] select,[data-ai-ws] textarea,[data-ai-ws] button{font-family:inherit}
[data-ai-ws]{--well:#0F2429;--input:#16323A;--teal-line:rgba(150,215,220,.16);--line-strong:rgba(150,215,220,.22);--faint:#93A4A8;--mint:#5EE6B0;--grad:linear-gradient(135deg,#3EE0A1,#2EC4D6);--on-grad:#04212A}
[data-ai-ws][data-mode="light"]{--well:#EEF4F5;--input:#F3F8F8;--teal-line:#CFDFE2;--line-strong:#C5D0D3;--faint:#6E7F85;--mint:#0E7A55;--grad:linear-gradient(135deg,#0E8A5F,#0B7A8C);--on-grad:#fff}
[data-ai-ws] .ai-convs{position:relative;flex-shrink:0;overflow:hidden;display:flex;flex-direction:column;background:var(--surface);border:0;border-right:1px solid var(--line);border-radius:0;transition:width .3s cubic-bezier(.4,0,.2,1),min-width .3s cubic-bezier(.4,0,.2,1)}
[data-ai-ws] .cv-top{padding:14px 12px 12px;border-bottom:1px solid var(--line);min-width:200px}
[data-ai-ws] .ai-new{width:100%;height:38px;display:flex;align-items:center;justify-content:center;gap:7px;border-radius:999px;border:0;background:var(--grad);color:var(--on-grad);font-size:13.5px;font-weight:700;cursor:pointer;box-shadow:0 8px 18px -10px rgba(46,196,214,.6);transition:filter .15s,transform .15s}
[data-ai-ws] .ai-new:hover{filter:brightness(1.08);transform:translateY(-1px)}
[data-ai-ws] .cv-head{display:flex;align-items:center;justify-content:space-between;gap:8px;padding:12px 8px 6px 14px;min-width:200px}
[data-ai-ws] .cv-head b{font-size:16px;font-weight:700;color:var(--ink)}
[data-ai-ws] .cv-head b small{font-size:12px;font-weight:600;color:var(--faint)}
[data-ai-ws] .ai-icon{width:30px;height:30px;display:grid;place-items:center;border:0;border-radius:8px;background:none;color:var(--ink);cursor:pointer}
[data-ai-ws] .ai-icon:hover{color:var(--hover-ink);background:var(--hover-tint)}
[data-ai-ws] .ai-menu{position:absolute;right:0;top:calc(100% + 6px);z-index:30;min-width:190px;padding:4px;display:flex;flex-direction:column;border-radius:10px;border:1px solid var(--line-strong);background:var(--surface);box-shadow:0 18px 36px -12px rgba(0,0,0,.6)}
[data-ai-ws] .ai-menu button{text-align:left;padding:8px 10px;border:0;border-radius:7px;background:none;color:var(--ink);font-size:13px;cursor:pointer}
[data-ai-ws] .ai-menu button:hover{background:var(--well)}
[data-ai-ws] .proj{display:flex;align-items:center;gap:10px;padding:8px 10px;border-radius:10px;border:1px solid var(--teal-line);background:var(--well)}
[data-ai-ws] .proj .ic{width:28px;height:28px;border-radius:8px;display:grid;place-items:center;background:var(--input);color:var(--mint);flex:none}
[data-ai-ws] .proj b{display:block;font-size:13.5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
[data-ai-ws] .proj small{display:block;font-size:11.5px;color:var(--faint)}
[data-ai-ws] .newchat{display:flex;align-items:center;gap:8px;height:38px;padding:0 12px;border-radius:10px;border:1px solid var(--line-strong);background:var(--surface);color:var(--ink);font-weight:600;font-size:13.5px;width:100%;cursor:pointer}
[data-ai-ws] .newchat:hover{border-color:rgba(62,224,161,.55);color:var(--hover-ink);background:var(--hover-tint)}
[data-ai-ws] .cv-search{margin:0 14px 6px;min-width:192px;display:flex;align-items:center;gap:8px;height:36px;padding:0 10px;border-radius:10px;background:var(--input);border:1px solid var(--teal-line);color:var(--faint)}
[data-ai-ws] .cv-search:focus-within{border-color:var(--mint)}
[data-ai-ws] .cv-search input{flex:1;min-width:0;border:0;background:none;outline:none;font-size:13px;color:var(--ink)}
[data-ai-ws] .cv-search input::placeholder{color:var(--faint)}
[data-ai-ws] .cv-list{flex:1;overflow:auto;padding:6px 8px 10px;min-width:200px;scrollbar-width:thin}
[data-ai-ws] .cv-g{font-size:11px;letter-spacing:.09em;text-transform:uppercase;color:var(--faint);font-weight:600;padding:12px 8px 6px}
[data-ai-ws] .cv{display:flex;align-items:center;gap:4px;padding:8px 9px;border-radius:10px;border:1px solid transparent;margin-bottom:2px;font-size:13px;font-weight:600;color:var(--muted);cursor:pointer}
[data-ai-ws] .cv:hover{background:var(--hover-tint);color:var(--ink)}
[data-ai-ws] .cv.on{background:var(--well);border-color:var(--teal-line);color:var(--ink)}
[data-ai-ws] .cv-more{flex:none;width:24px;height:24px;display:grid;place-items:center;border:0;border-radius:7px;background:none;color:var(--faint);cursor:pointer;opacity:0}
[data-ai-ws] .cv:hover .cv-more,[data-ai-ws] .cv.on .cv-more,[data-ai-ws] .cv-more[aria-expanded="true"]{opacity:1}
[data-ai-ws] .cv-more:hover,[data-ai-ws] .cv-more[aria-expanded="true"]{background:var(--input);color:var(--ink)}
[data-ai-ws] .cv-menu{z-index:60;width:max-content;min-width:0;padding:3px;border-radius:9px}
[data-ai-ws] .cv-menu button{display:flex;align-items:center;gap:7px;padding:5px 12px 5px 8px;font-size:12.5px;border-radius:6px}
[data-ai-ws] .cv-menu button svg{width:13px;height:13px}
[data-ai-ws] .cv-menu button svg{color:var(--faint)}
[data-ai-ws] .cv-menu button.danger,[data-ai-ws] .cv-menu button.danger svg{color:#F28B80}
[data-ai-ws] .cv-empty{padding:6px 8px;font-size:14px;color:var(--faint)}
[data-ai-ws] .cv-empty .ic{width:38px;height:38px;border-radius:11px;display:grid;place-items:center;background:var(--well);border:1px solid var(--teal-line);color:var(--mint)}
[data-ai-ws] .cv-empty b{font-size:14px;color:var(--ink)}
[data-ai-ws] .cv-empty p{margin:0;font-size:12.5px;color:var(--muted);line-height:1.55}
[data-ai-ws] .cv-foot{padding:10px 12px 10px;font-size:11.5px!important;border-top:1px solid var(--line);font-size:12px;color:var(--faint);display:flex;justify-content:space-between;min-width:200px;white-space:nowrap}
[data-ai-ws] .ai-edge{position:absolute;bottom:14px;z-index:20;width:32px;height:32px;display:grid;place-items:center;border:0;border-radius:50%;background:var(--grad);color:var(--on-grad);cursor:pointer;box-shadow:0 0 0 3px var(--bg),0 8px 18px -10px rgba(46,196,214,.6);transition:left .3s cubic-bezier(.4,0,.2,1),filter .15s}
[data-ai-ws] .ai-edge:hover{filter:brightness(1.1)}
[data-ai-ws] .ch-head{display:flex;align-items:center;gap:12px;padding:4px 10px 10px;flex-wrap:wrap;flex-shrink:0}
[data-ai-ws] .ch-head h1{margin:0;font-family:"Literata",Georgia,serif;font-size:21px;font-weight:600;color:var(--ink);min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;flex:1 1 200px}
[data-ai-ws] .scope{display:flex;gap:6px;flex-wrap:wrap}
[data-ai-ws] .chipbtn{display:inline-flex;align-items:center;gap:6px;height:32px;padding:0 11px;border-radius:999px;border:1px solid var(--teal-line);background:var(--well);color:var(--muted);font-size:12.5px;font-weight:600;cursor:pointer;white-space:nowrap}
[data-ai-ws] .chipbtn:hover{border-color:rgba(62,224,161,.55);color:var(--hover-ink)}
[data-ai-ws] .chipbtn b{color:var(--ink);font-weight:600}
[data-ai-ws] .chipbtn.case b{font-family:"JetBrains Mono",ui-monospace,monospace;font-size:11.5px;color:var(--mint)}
[data-ai-ws] .chipbtn .x{color:var(--faint);margin-left:2px}
[data-ai-ws] .ai-welcome{width:100%;max-width:1000px;display:grid;gap:4px;text-align:left}
[data-ai-ws] .ai-welcome .hi{font-size:14px;color:var(--muted);display:flex;align-items:center;gap:9px}
[data-ai-ws] .ai-welcome .hi i{width:8px;height:8px;border-radius:50%;background:var(--mint);box-shadow:0 0 0 4px color-mix(in srgb,var(--mint) 18%,transparent)}
[data-ai-ws] .ai-welcome h2{margin:2px 0 0;font-family:"Literata",Georgia,serif;font-weight:600;font-size:clamp(28px,3.2vw,40px);line-height:1.15;color:var(--ink)}
[data-ai-ws] .ai-welcome h2 span{color:var(--mint)}
[data-ai-ws] .ai-box{width:100%;max-width:1000px;box-sizing:border-box;padding:10px 12px 8px 16px;border-radius:18px;border:1px solid var(--line-strong);background:var(--surface);box-shadow:0 30px 60px -30px rgba(0,0,0,.8)}
[data-ai-ws] .ai-box:focus-within{border-color:color-mix(in srgb,var(--mint) 55%,transparent)}
[data-ai-ws] .ai-box input::placeholder{color:var(--faint)}
[data-ai-ws] .ai-chip{display:inline-flex;align-items:center;gap:6px;height:30px;padding:0 11px;border-radius:999px;background:var(--well);border:1px solid var(--teal-line);color:var(--ink);font-size:13px;font-weight:600}
[data-ai-ws] .lang{display:flex;padding:3px;border-radius:9px;background:var(--well);border:1px solid var(--teal-line)}
[data-ai-ws] .lang button{height:26px;padding:0 9px;border:0;border-radius:6px;background:none;font-size:12px;font-weight:700;color:var(--faint);cursor:pointer}
[data-ai-ws] .lang button[aria-pressed="true"]{background:var(--surface);color:var(--ink);box-shadow:inset 0 0 0 1px var(--line)}
[data-ai-ws] .ai-send{width:34px;height:34px;display:grid;place-items:center;border-radius:10px;border:1px solid var(--teal-line);background:var(--well);color:var(--faint);cursor:default;transition:background .15s,color .15s}
[data-ai-ws] .ai-send.on{border-color:transparent;background:var(--grad);color:var(--on-grad);cursor:pointer;box-shadow:0 8px 18px -10px rgba(46,196,214,.6)}
[data-ai-ws] .disc{max-width:1000px;margin:8px auto 0;font-size:11.5px;color:var(--faint);text-align:center}
[data-ai-ws] .ai-start{width:100%;max-width:1000px;margin:auto 0;display:grid;gap:26px;padding:12px 0}
[data-ai-ws] .ai-below{width:100%;display:grid;gap:12px}
[data-ai-ws] .ai-scroll,[data-ai-ws] .cv-list{scrollbar-width:none;-ms-overflow-style:none}
[data-ai-ws] .ai-scroll::-webkit-scrollbar,[data-ai-ws] .cv-list::-webkit-scrollbar{display:none}
[data-ai-ws] .ai-sources{width:300px;flex-shrink:0;margin:14px 0;display:flex;flex-direction:column;min-height:0;overflow:hidden;background:var(--surface);border:1px solid var(--line);border-radius:14px;animation:aiSrcIn .2s ease-out}
@keyframes aiSrcIn{from{opacity:0;transform:translateX(12px)}to{opacity:1;transform:none}}
[data-ai-ws] .src-h{padding:12px 12px 12px 16px;border-bottom:1px solid var(--line);display:flex;justify-content:space-between;align-items:center}
[data-ai-ws] .src-h h3{margin:0;font-size:15px;font-weight:700;color:var(--ink);display:flex;gap:8px;align-items:center}
[data-ai-ws] .src-h .n{font-family:"JetBrains Mono",ui-monospace,monospace;font-size:11px;padding:0 7px;border-radius:999px;background:var(--well);color:var(--muted)}
[data-ai-ws] .src-list{flex:1;overflow:auto;padding:10px;display:grid;gap:8px;align-content:start;scrollbar-width:none}
[data-ai-ws] .src-list::-webkit-scrollbar{display:none}
[data-ai-ws] .src{padding:11px 12px;border-radius:10px;background:var(--well);border:1px solid var(--teal-line);display:grid;gap:5px;transition:border-color .15s}
[data-ai-ws] .src.hl{border-color:var(--mint)}
[data-ai-ws] .src .top{display:flex;gap:8px;align-items:center}
[data-ai-ws] .src .num{font-family:"JetBrains Mono",ui-monospace,monospace;font-size:10.5px;color:var(--mint);min-width:20px;height:18px;display:grid;place-items:center;border-radius:5px;border:1px solid var(--teal-line)}
[data-ai-ws] .src .kind{font-size:10.5px;letter-spacing:.06em;text-transform:uppercase;color:var(--faint);font-weight:700}
[data-ai-ws] .src .dead{margin-left:auto;font-size:10.5px;font-weight:700;color:#F28B80}
[data-ai-ws] .src b{font-size:13.5px;font-weight:600;color:var(--ink)}
[data-ai-ws] .src p{margin:0;font-size:12.5px;color:var(--muted);line-height:1.5}
[data-ai-ws] .src p.where{font-size:11.5px;color:var(--faint);word-break:break-all}
[data-ai-ws] .src p.dead-note{color:#F28B80}
[data-ai-ws] .src-acts{display:flex;flex-wrap:wrap;gap:12px;margin-top:2px}
[data-ai-ws] .src-acts a,[data-ai-ws] .src-acts button{background:none;border:0;padding:0;font-size:12px;font-weight:600;color:var(--mint);text-decoration:none;cursor:pointer;font-family:inherit}
[data-ai-ws] .src-acts a:hover,[data-ai-ws] .src-acts button:hover{text-decoration:underline}
[data-ai-ws] .ai-mic{width:34px;height:34px;display:grid;place-items:center;border:1px solid transparent;border-radius:50%;background:none;color:var(--faint);cursor:pointer;transition:color .15s,background .15s}
[data-ai-ws] .ai-mic:hover{border-color:var(--line-strong);color:var(--hover-ink)}
[data-ai-ws] .ai-mic.on{color:#F28B80;background:rgba(242,139,128,.14);border-color:rgba(242,139,128,.45);animation:aiMic 1.2s ease-in-out infinite}
@keyframes aiMic{0%,100%{box-shadow:0 0 0 0 rgba(242,139,128,.35)}50%{box-shadow:0 0 0 6px rgba(242,139,128,0)}}
[data-ai-ws] .ai-attach{width:32px;height:32px;display:grid;place-items:center;border:1px solid transparent;border-radius:9px;background:none;color:var(--faint);cursor:pointer}
[data-ai-ws] .ai-attach:hover{border-color:var(--line-strong);color:var(--hover-ink)}
[data-ai-ws] .ctx-h{display:flex;justify-content:space-between;align-items:baseline;font-size:11px;letter-spacing:.09em;text-transform:uppercase;color:var(--faint);font-weight:600}
[data-ai-ws] .ctx-h button{background:none;border:0;padding:0;color:var(--mint);font-size:12.5px;letter-spacing:0;text-transform:none;font-weight:600;cursor:pointer}
[data-ai-ws] .ctx{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}
[data-ai-ws] .cx{display:grid;gap:8px;align-content:start;padding:14px;border-radius:14px;border:1px solid var(--line);background:var(--surface);color:var(--ink);text-align:left;cursor:pointer;transition:border-color .15s,transform .15s}
[data-ai-ws] .cx:hover{border-color:rgba(62,224,161,.55);transform:translateY(-1px)}
[data-ai-ws] .cx .top{display:flex;justify-content:space-between;align-items:center;gap:8px}
[data-ai-ws] .cx .when{font-size:11.5px;font-weight:700}
[data-ai-ws] .cx .case{font-family:"JetBrains Mono",ui-monospace,monospace;font-size:10.5px;color:var(--mint);padding:1px 6px;border-radius:5px;border:1px solid var(--teal-line);white-space:nowrap}
[data-ai-ws] .cx b{font-size:13.5px;font-weight:600;line-height:1.35}
[data-ai-ws] .cx small{font-size:12px;color:var(--faint);text-transform:capitalize}
[data-ai-ws] .pop{display:flex;gap:10px;align-items:center;font-size:12.5px;color:var(--faint);min-width:0}
[data-ai-ws] .pop > span{flex:none}
[data-ai-ws] .pop-rail{flex:1;min-width:0;display:flex;gap:8px;overflow-x:auto;scrollbar-width:none;-webkit-mask-image:linear-gradient(90deg,transparent,#000 24px,#000 calc(100% - 40px),transparent);mask-image:linear-gradient(90deg,transparent,#000 24px,#000 calc(100% - 40px),transparent)}
[data-ai-ws] .pop-rail::-webkit-scrollbar{display:none}
[data-ai-ws] .pop-rail button{flex:none;white-space:nowrap}
[data-ai-ws] .pop button{height:30px;padding:0 11px;border-radius:999px;border:1px solid var(--line);background:none;color:var(--muted);font-size:12.5px;cursor:pointer}
[data-ai-ws] .pop button:hover{border-color:rgba(62,224,161,.55);color:var(--hover-ink)}
`;

/* Dictation into the question box, using the browser's speech recognition
   (Chrome / Edge). Where the browser has none the button is not shown — a mic
   that does nothing would be worse than no mic. */
function VoiceButton({ onText }) {
    // Looked up after mount, so the server render and the first client render agree.
    const [Rec, setRec] = useState(null);
    useEffect(() => { setRec(() => window.SpeechRecognition || window.webkitSpeechRecognition || null); }, []);
    const recRef = useRef(null);
    const [on, setOn] = useState(false);
    const [err, setErr] = useState("");
    useEffect(() => () => { try { recRef.current?.abort(); } catch { /* already stopped */ } }, []);
    if (!Rec) return null;
    const toggle = () => {
        if (on) { recRef.current?.stop(); return; }
        setErr("");
        const rec = new Rec();
        rec.lang = "en-PK";
        rec.interimResults = true;
        rec.continuous = false;
        rec.onresult = (e) => {
            const text = Array.from(e.results).map(r => r[0].transcript).join(" ").trim();
            if (text) onText(text);
        };
        rec.onerror = (e) => {
            setErr(e.error === "not-allowed" ? "Microphone permission was refused" : "Could not hear that — try again");
        };
        rec.onend = () => setOn(false);
        recRef.current = rec;
        try { rec.start(); setOn(true); } catch { setOn(false); }
    };
    return (
        <button type="button" className={`ai-mic${on ? " on" : ""}`} onClick={toggle}
            aria-pressed={on} aria-label={on ? "Stop dictation" : "Dictate your question"}
            title={err || (on ? "Listening… click to stop" : "Speak your question")}>
            <svg width={16} height={16} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><rect x="9" y="3" width="6" height="11" rx="3" /><path d="M5 11a7 7 0 0 0 14 0M12 18v3" /></svg>
        </button>
    );
}

function PromptRail({ prompts, onPick }) {
    const ref = useRef(null);
    const paused = useRef(false);
    useEffect(() => {
        const el = ref.current;
        if (!el) return undefined;
        if (typeof requestAnimationFrame !== "function") return undefined;   // no animation frames (tests)
        if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) return undefined;
        let raf = 0, pos = el.scrollLeft;
        const step = () => {
            if (!paused.current && el.scrollWidth > el.clientWidth) {
                pos += 0.35;
                const half = el.scrollWidth / 2;          // the list is drawn twice
                if (pos >= half) pos -= half;
                el.scrollLeft = pos;
            } else {
                pos = el.scrollLeft;
            }
            raf = requestAnimationFrame(step);
        };
        raf = requestAnimationFrame(step);
        return () => cancelAnimationFrame(raf);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [prompts.join("|")]);
    const stop = () => { paused.current = true; };
    const go = () => { paused.current = false; };
    const onWheel = (e) => {
        const el = ref.current;
        if (el && Math.abs(e.deltaY) > Math.abs(e.deltaX)) el.scrollLeft += e.deltaY;
    };
    return (
        <div className="pop">
            <span>Try:</span>
            <div className="pop-rail" ref={ref} onMouseEnter={stop} onMouseLeave={go} onFocus={stop} onBlur={go} onWheel={onWheel}>
                {[...prompts, ...prompts].map((p, i) => (
                    <button type="button" key={i} tabIndex={i < prompts.length ? 0 : -1}
                        aria-hidden={i < prompts.length ? undefined : true} onClick={() => onPick(p)}>{p}</button>
                ))}
            </div>
        </div>
    );
}

function AILegalPage() {
    const { t } = useTheme();
    const themed = useMemo(() => themeOnTokens(t), [t]);
    return (
        <ThemeCtx.Provider value={themed}>
            <div data-ai-ws data-drafting-theme data-mode={draftingMode(t)}>
                <style>{`${DRAFTING_TOKENS_CSS}
${AI_THEME_CSS}`}</style>
                <AILegalScreen />
            </div>
        </ThemeCtx.Provider>
    );
}

function AILegalScreen() {
    const { t } = useTheme();
    const { activeCase, setActiveCase, setPage } = useCase();
    const { user } = useAuth();
    const firstName = user?.full_name?.split(" ")[0] || "Counselor";
    const [apiCases, setApiCases] = useState([]);
    const [msgs, setMsgs] = useState([]);
    const [conversationError, setConversationError] = useState(null);
    // Shown when an opened conversation belongs to a case this page cannot
    // select (not among the loaded cases), so the switch is never silent.
    const [caseNotice, setCaseNotice] = useState(null);
    // Has the case list answered (either way)? The mount bootstrap waits for it
    // when a case is selected, so it can start the thread bound to that case
    // instead of an unbound one that is immediately replaced and left empty.
    const [casesLoaded, setCasesLoaded] = useState(false);

    useEffect(() => {
        listCases({ page_size: 50 }).then(({ data }) => {
            setCasesLoaded(true);
            if (!data?.items) return;
            setApiCases(data.items.map(c => ({
                id: c.case_number || c._id,
                _id: c._id,
                title: c.title || "Untitled Case",
                type: c.case_type || "general",
                client: c.client_name || "Client",
                court: c.province || "Court",
                // Kept separate from `court`: that field carries a "Court" display
                // fallback, which is not a province and must never reach retrieval.
                // The stored value is already the pipeline's Province enum
                // (punjab | sindh | kpk | balochistan | federal), so it passes
                // through untranslated.
                province: c.province || null,
                nextHearing: c.hearing_dates?.find(h => !h.outcome)?.date?.split("T")[0] || "TBD",
            })));
        }).catch(() => setCasesLoaded(true));
    }, []);

    const activeCaseObj = apiCases.find(c => c.id === activeCase) || null;
    const apiCasesRef = useRef(apiCases);
    apiCasesRef.current = apiCases;
    const [query, setQuery] = useState("");
    // A question typed on the dashboard arrives once, ready to send.
    useEffect(() => {
        try {
            const q = sessionStorage.getItem("attorney:ai-prefill");
            if (q) { sessionStorage.removeItem("attorney:ai-prefill"); setQuery(q); }
        } catch { /* storage off */ }
    }, []);
    const [loading, setLoading] = useState(false);
    const [sideOpen, setSideOpen] = useState(true);
    const [lang] = useState("EN");
    // Real research conversations from the server, grouped by recency. The
    // previous list held the raw text of past questions and clicking one only
    // refilled the input box, because nothing was stored to reopen.
    const [history, setHistory] = useState([]);
    // The rows themselves, ungrouped: appending a page has to happen on the
    // flat list, since `groupConversations` buckets by date for display.
    const [rows, setRows] = useState([]);
    const [listCursor, setListCursor] = useState(null);
    const [listMore, setListMore] = useState(false);
    const [listLoading, setListLoading] = useState(false);
    const [search, setSearch] = useState("");
    // Below this a message search matches most of a corpus and ranks none of
    // it usefully, and costs a text query per keystroke.
    const MIN_SEARCH_CHARS = 2;
    // Threads matched by what was SAID in them, kept apart from `rows` because
    // a message match carries the sentence that matched and a title match does
    // not — merging them would drop the only part that explains the result.
    const [messageHits, setMessageHits] = useState([]);
    const [unsearchable, setUnsearchable] = useState(false);
    // "Is this list response still wanted?" A search typed quickly issues
    // several requests, and the slowest must not paint over the newest.
    const listGeneration = useRef(createGeneration()).current;
    const [showArchived, setShowArchived] = useState(false);
    // Set when the last turn ended by asking for facts instead of answering.
    // A display hint: the LangGraph checkpoint decides whether the turn is
    // really interrupted, and /ai/research consults it before every turn. A
    // stale banner costs nothing; a resumed answer in the wrong conversation
    // would not, which is why this never drives the resume.
    const [pendingQuestion, setPendingQuestion] = useState(null);
    // The session id is a server fact now, so it starts empty and is filled by
    // the bootstrap effect below — restored from the last one this tab used, or
    // created. A browser-minted id meant a refresh silently started a new
    // conversation and orphaned the previous one.
    const sessionIdRef = useRef(null);
    // The case the open conversation is BOUND to (its _id, or null for general
    // research); undefined while none is open. The server refuses (409) a turn
    // whose case_id differs from the binding, so every send checks it.
    const boundCaseRef = useRef(undefined);
    const [sessionId, setSessionId] = useState(null);
    // "Is this response still wanted?" Selecting thread A then B used to let
    // A's slower page loop call setMsgs last, so B was the active thread with
    // A's messages on screen. See lib/attempt.
    const openGeneration = useRef(createGeneration()).current;
    const attemptRef = useRef(null);
    // Set by Stop, so the request that returns afterwards knows its answer is
    // no longer wanted and does not paint it over the notice.
    const cancelledRef = useRef(false);
    // What the server said the Stop actually did, shown instead of a guess.
    const stopNoticeRef = useRef("Stopped.");
    // Walking BACKWARDS through a thread. `olderCursor` is the sequence of the
    // oldest message on screen; the next request asks for what precedes it.
    const [olderCursor, setOlderCursor] = useState(null);
    const [hasOlder, setHasOlder] = useState(false);
    const [loadingOlder, setLoadingOlder] = useState(false);
    // What the pipeline is doing, for the answer currently being written.
    const [stage, setStage] = useState(null);
    const stagePollRef = useRef(null);
    // An answer this conversation is still owed after a refresh.
    const [recovering, setRecovering] = useState(false);
    const recoverRef = useRef(null);
    const bottomRef = useRef(null);
    useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: "smooth" }); }, [msgs]);

    // Inject cursor-blink keyframe once
    useEffect(() => {
        const id = "ai-blink-kf";
        if (document.getElementById(id)) return;
        const s = document.createElement("style");
        s.id = id;
        s.textContent = `@keyframes aiBlink{0%,100%{opacity:1}50%{opacity:0}}`;
        document.head.appendChild(s);
    }, []);

    // Switching case starts a fresh conversation. The case FACTS are no longer
    // pre-filled into the prompt box: they are sent as `case_id` and fetched
    // server-side after an authorization check, so the browser no longer
    // decides what the model believes about the matter — and the context
    // cannot fall out of the last-four-message history window a few turns in,
    // which is how it used to stop applying silently.
    // A conversation belongs to one matter, so switching case starts a new one
    // BOUND to that case — the server verifies the binding before storing it,
    // so what the conversation records is a checked fact rather than a claim.
    //
    // Keyed on the RESOLVED case id, not `activeCase`: the case list loads after
    // mount, so `activeCaseObj` is null on the first render even when a case is
    // selected. The old effect skipped its first run and fired on `activeCase`,
    // leaving the mount-time thread unbound while sends carried a case_id — a
    // 409 on the lawyer's first question. Only a thread whose binding differs
    // is replaced; one already bound to this case is kept.
    const wantedCaseId = activeCaseObj?._id || null;
    // Read by the mount bootstrap, whose closure would see the first render's null.
    const wantedCaseRef = useRef(null);
    wantedCaseRef.current = wantedCaseId;
    useEffect(() => {
        if (boundCaseRef.current === undefined) return;   // the mount bootstrap decides
        if (boundCaseRef.current === wantedCaseId) return;
        setQuery("");
        startConversation(wantedCaseId);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [wantedCaseId]);

    /* ── Conversations ────────────────────────────────────────────────── */

    // The case switcher doubles as the conversation filter: "none" is general
    // research, a case id is that matter's. Passing a case id here grants
    // nothing — the server filters conversations this lawyer already owns.
    /* One page of research threads. See the client sidebar for why this is a
       cursor and not an offset; the difficulty unique to this surface is that
       threads on revoked cases are filtered out server-side AFTER the read, so
       a page can come back empty while more accessible threads wait behind it.
       The server's cursor advances over those, which is why "load more" must
       follow `has_more` rather than "did this page return anything". */
    const loadHistory = useCallback(async ({ after = null, term = null } = {}) => {
        const ticket = listGeneration.next();
        setListLoading(true);
        const { data } = await listResearchConversations({
            caseId: activeCaseObj ? (activeCaseObj._id || null) : "none",
            includeArchived: showArchived,
            limit: 30, after, search: term ?? null,
        });
        if (!listGeneration.isCurrent(ticket)) return;
        setListLoading(false);
        if (!data) return;

        const incoming = data.conversations || [];
        setRows(prev => {
            const merged = after ? [...prev, ...incoming] : incoming;
            const seen = new Set();
            const unique = merged.filter(r => {
                if (seen.has(r.session_id)) return false;
                seen.add(r.session_id);
                return true;
            });
            setHistory(groupConversations(unique));
            return unique;
        });

        // Message-body search, alongside the title search above.
        //
        // Two searches because they answer different questions: the list is
        // "threads called this", these are "threads where I said this". Under
        // the SAME ticket, so a stale response cannot paint results for a term
        // the lawyer has moved on from.
        //
        // The server re-checks case access on every result before returning
        // it, because a snippet is message text — ownership of the thread is
        // not authority to read what is in it.
        const phrase = (term || "").trim();
        if (phrase.length >= MIN_SEARCH_CHARS) {
            const { data: found } = await searchResearchConversations(phrase);
            if (!listGeneration.isCurrent(ticket)) return;
            setMessageHits(found?.results || []);
            setUnsearchable(!!found?.has_unsearchable_history);
        } else {
            setMessageHits([]);
            setUnsearchable(false);
        }

        setListCursor(data.next_cursor || null);
        setListMore(!!data.has_more);
    }, [activeCaseObj, showArchived, listGeneration]);

    const refreshHistory = useCallback(
        () => loadHistory({ term: search || null }), [loadHistory, search]);
    // The mount bootstrap is async and outlives the render it started in; it
    // must refresh with the CURRENT filter. Its own closure held the first
    // render's (case still unknown), and as the last list request it won —
    // leaving general threads listed under a selected case (smoke test).
    const refreshHistoryRef = useRef(refreshHistory);
    refreshHistoryRef.current = refreshHistory;

    const loadMoreHistory = useCallback(
        () => loadHistory({ after: listCursor, term: search || null }),
        [loadHistory, listCursor, search]);

    useEffect(() => {
        const timer = setTimeout(
            // Through the ref: this timer is set on mount, and the closure it
            // captured predates the case list, so it reloaded the list
            // unfiltered — and, firing last, it won.
            () => { refreshHistoryRef.current(); }, 250);
        return () => clearTimeout(timer);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [search]);

    /* Watch a thread until the turn it is waiting on lands.
       Bounded: a worker that dies without settling its turn must not leave the
       browser polling forever, so this gives up and says so. */

    /* How many messages one page of a thread holds, in both directions. */
    const THREAD_PAGE_SIZE = 50;

    /* How long the browser watches for an interrupted turn to land, and how
       often it looks. Bounded on purpose: a worker that dies without settling
       its turn must not leave the page polling forever. */
    const RECOVER_TRIES = 40;
    const RECOVER_INTERVAL_MS = 3000;

    /* A whole thread, every page of it.
       Extracted because recovery needs the SAME thing opening does. Recovery
       used to re-read one page and call setMsgs with it, so a thread longer
       than a page came back truncated the moment an interrupted turn landed —
       the earlier half of the conversation simply disappeared. Two callers,
       one loop, so they cannot drift again.
       Returns null when the thread is gone, or when the caller's ticket went
       stale mid-read and the result is no longer wanted. */
    const loadThread = useCallback(async (id, ticket) => {
        // ONE page, the NEWEST.
        //
        // This used to walk forward from the thread's first message until
        // `has_more` went false — every page of a two-year matter, before
        // anything appeared. A lawyer reopens a thread to read the last answer,
        // which is at the end, so that is the end the fetch starts from. Older
        // pages arrive when they are asked for.
        //
        // `pending_turn` still reaches recovery because the server reports it
        // on the OPENING read — the one with no cursor in either direction —
        // and this is that read.
        const { data, error } = await getResearchConversation(
            id, { pageSize: THREAD_PAGE_SIZE });
        if (!openGeneration.isCurrent(ticket)) return null;   // moved on
        if (error || !data) return null;
        return {
            header: data,
            messages: toResearchMessages(data.messages),
            olderCursor: data.older_cursor ?? null,
            hasOlder: !!data.has_older,
        };
    }, [openGeneration]);

    /* Older messages, on demand.

       `current()` and not `next()`: claiming a generation here would invalidate
       the open this fetch belongs to. The check still matters — this is an
       await, and a lawyer switching threads mid-flight would otherwise have
       another matter's history prepended to the one on screen. */
    const loadOlder = useCallback(async () => {
        const id = sessionIdRef.current;
        if (!id || !olderCursor || loadingOlder) return;
        const ticket = openGeneration.current();
        setLoadingOlder(true);
        setConversationError(null);
        const { data, error } = await getResearchConversation(
            id, { beforeSeq: olderCursor, pageSize: THREAD_PAGE_SIZE });
        if (!openGeneration.isCurrent(ticket)) return;
        setLoadingOlder(false);
        if (error || !data) {
            setConversationError(error?.message || "Could not load earlier messages. Please try again.");
            return;
        }

        // `mergeMessages` sorts by the server-allocated `seq`, so the order is
        // decided by the sequence rather than by which side this is passed on.
        setMsgs(current => mergeMessages(
            current, toResearchMessages(data.messages)));
        setOlderCursor(data.older_cursor ?? null);
        setHasOlder(!!data.has_older);
    }, [olderCursor, loadingOlder, openGeneration]);

    const recoverPending = useCallback(async (id, ticket) => {
        for (let tries = 0; tries < RECOVER_TRIES; tries += 1) {
            await new Promise(r => {
                recoverRef.current = setTimeout(r, RECOVER_INTERVAL_MS);
            });
            if (!openGeneration.isCurrent(ticket)) return;      // moved on
            const { data } = await getResearchConversation(id, { pageSize: 1 });
            if (!openGeneration.isCurrent(ticket)) return;
            if (!data) continue;
            if (data.pending_turn) continue;                    // still working

            // Settled. Whatever it produced is in the stored history, so the
            // history IS the answer — no re-ask, no second charge. Reloaded in
            // full rather than from the one page this poll read, which used to
            // replace an entire thread with its first hundred messages.
            const thread = await loadThread(id, ticket);
            if (!openGeneration.isCurrent(ticket)) return;
            setRecovering(false);
            if (thread) {
                // The recovered answer is the NEWEST message, so the newest
                // page is exactly the right thing to reload — and the older
                // cursor is reset with it, because the thread has grown and
                // the previous boundary no longer describes it.
                setMsgs(thread.messages);
                setOlderCursor(thread.olderCursor);
                setHasOlder(thread.hasOlder);
            }
            return;
        }
        // Gave up. Said out loud, because a banner that simply vanishes leaves
        // the lawyer believing an answer is still on its way.
        if (!openGeneration.isCurrent(ticket)) return;
        setRecovering(false);
        setMsgs(p => [...p, {
            role: "assistant", notice: true,
            content: "That question didn't finish, and no answer was saved. "
                   + "Please ask it again.",
        }]);
    }, [openGeneration, loadThread]);

    // `adopt`: the lawyer picked this conversation (history or search), so the
    // page follows it to its case rather than keeping a selection the thread
    // does not belong to — which would make the next question start a different
    // thread without saying so. The mount restore does not adopt: a case chosen
    // elsewhere (e.g. from the Cases page) wins over a remembered thread.
    const openConversation = useCallback(async (id, { adopt = false } = {}) => {
        if (!id) return;
        setConversationError(null);
        const ticket = openGeneration.next();
        const thread = await loadThread(id, ticket);
        if (!openGeneration.isCurrent(ticket)) return;   // the user moved on
        if (!thread) {
            setConversationError("Could not open that conversation. Your existing chat has not been cleared; please try again.");
            return;
        }
        const { header, messages: restored } = thread;
        setOlderCursor(thread.olderCursor);
        setHasOlder(thread.hasOlder);
        sessionIdRef.current = id;
        boundCaseRef.current = header?.case_id || null;
        setCaseNotice(null);
        if (adopt && boundCaseRef.current !== wantedCaseRef.current) {
            const bound = boundCaseRef.current;
            const match = bound ? apiCasesRef.current.find(c => c._id === bound) : null;
            if (!bound) setActiveCase?.(null);
            else if (match) setActiveCase?.(match.id);
            else setCaseNotice("This conversation belongs to a case that isn't in your loaded case list. "
                + "Your next question will start a new thread for the case selected here.");
        }
        setSessionId(id);
        writeActiveSession("research", user?._id, id);
        setMsgs(restored);
        setPendingQuestion(header?.pending_question || null);

        // An answer this thread is still owed.
        //
        // A refresh mid-turn loses the request, not the turn: the worker keeps
        // running and files the answer against the conversation. Re-asking
        // would be a second question at a second cost, so instead we watch for
        // the answer the first one is already producing.
        clearTimeout(recoverRef.current);
        setRecovering(!!header?.pending_turn);
        if (header?.pending_turn) recoverPending(id, ticket);
    }, [user?._id, recoverPending, loadThread, openGeneration, setActiveCase]);


    const startConversation = useCallback(async (caseId) => {
        setConversationError(null);
        const { data, error } = await createResearchConversation({ caseId: caseId || null });
        if (error || !data?.session_id) {
            setConversationError(error?.message || "Could not start a new conversation. Please try again.");
            return null;
        }
        sessionIdRef.current = data.session_id;
        boundCaseRef.current = caseId || null;
        setCaseNotice(null);
        setSessionId(data.session_id);
        writeActiveSession("research", user?._id, data.session_id);
        setMsgs([]);
        setPendingQuestion(null);
        return data.session_id;
        // Depends on the user because it WRITES the remembered-session key,
        // which is scoped by user id. With `[]` it captured the first render's
        // null user and remembered nothing at all.
    }, [user?._id]);

    // Restore on mount: the conversation this tab was last in, or a new one.
    // With a case selected it waits for the case list, which is what turns the
    // selection into a case id the new thread can be bound to.
    const casesReady = !activeCase || casesLoaded;
    const bootedFor = useRef(null);
    useEffect(() => {
        let live = true;
        (async () => {
            // No user yet: the bootstrap re-runs when the account resolves.
            if (!user?._id || !casesReady) return;
            if (bootedFor.current === user._id) return;
            bootedFor.current = user._id;
            const remembered = readActiveSession("research", user._id);
            if (remembered) await openConversation(remembered);
            else await startConversation(wantedCaseRef.current);
            // The case list may have resolved while this ran; the case-change
            // effect skipped it (nothing was open yet), so reconcile here.
            if (live && boundCaseRef.current !== undefined
                && boundCaseRef.current !== wantedCaseRef.current) {
                await startConversation(wantedCaseRef.current);
            }
            if (live) refreshHistoryRef.current();
        })();
        return () => { live = false; };
        // Runs once per ACCOUNT (a new user must not inherit the previous one's
        // open thread); `casesReady` only delays that one run.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [user?._id, casesReady]);

    useEffect(() => { refreshHistory(); }, [refreshHistory]);

    const h = new Date().getHours();
    const greetEmoji = h < 12 ? "🌅" : h < 17 ? "⛅" : "🌙";
    const greetWord = h < 12 ? "Good Morning" : h < 17 ? "Good Afternoon" : "Good Evening";
    const greetSub = activeCaseObj ? `Working on: ${activeCaseObj.id} — ${activeCaseObj.title}` : "The details are in the dark. Let's find them.";

    /* How often the page asks what the pipeline is doing.
       Slow enough to be a rounding error against a turn that takes tens of
       seconds; fast enough that a stage change is visible while it is still
       true. */
    const STAGE_POLL_MS = 2000;

    /* Watch one turn's progress until it settles.

       This surface has no socket — `/ai/research` is one long POST — so the
       stage is recorded on the turn and read from here. Stops on ANY terminal
       condition, including the request finishing, because a poll that outlives
       its turn is a request per two seconds forever. */
    const watchStage = useCallback((sid, attemptId) => {
        clearInterval(stagePollRef.current);
        if (!sid || !attemptId) return;
        stagePollRef.current = setInterval(async () => {
            // The attempt moved on, or ended. Either way this poll is stale.
            if (attemptRef.current?.id !== attemptId) {
                clearInterval(stagePollRef.current);
                return;
            }
            const { data } = await researchTurnStatus(sid, attemptId);
            if (!data) return;
            if (data.status && data.status !== "in_progress") {
                clearInterval(stagePollRef.current);
                setStage(null);
                return;
            }
            if (attemptRef.current?.id === attemptId) setStage(data.label || null);
        }, STAGE_POLL_MS);
    }, []);

    const stopWatchingStage = useCallback(() => {
        clearInterval(stagePollRef.current);
        setStage(null);
    }, []);

    const send = async () => {
        if (!query.trim() || loading) return;
        const q = query.trim();
        setQuery("");
        // The conversation is the unit of storage AND the LangGraph thread key,
        // so a turn cannot run before one exists.
        let sid = sessionIdRef.current;
        // A thread bound to a different case (a remembered one, or one opened
        // from search) would be refused with a 409: start one for this case.
        if (!sid || boundCaseRef.current !== wantedCaseId) {
            sid = await startConversation(wantedCaseId);
            if (!sid) { setMsgs(p => [...p, { role: "assistant", content: "Could not start a conversation. Please try again." }]); return; }
        }
        const now = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
        setMsgs(p => [...p, { role: "user", content: q, time: now }]);
        // The list comes from the server — the first question becomes the
        // conversation's title, which is why a send changes what it shows.
        setTimeout(refreshHistory, 400);
        setLoading(true);
        cancelledRef.current = false;
        // Reset with it: a stale notice from a previous Stop must not
        // be shown against a turn that failed for some other reason.
        stopNoticeRef.current = "Stopped.";

        const aiTime = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
        const msgHistory = msgs.filter(m => m.role !== "system").map(m => ({ role: m.role, content: m.content }));

        // Insert placeholder immediately (filled when the pipeline answers)
        setMsgs(p => [...p, { role: "assistant", content: "", time: aiTime, streaming: true }]);

        const fill = (patch) => setMsgs(p => {
            const next = [...p];
            const last = next[next.length - 1];
            if (last?.streaming) next[next.length - 1] = { ...last, streaming: false, ...patch };
            return next;
        });

        try {
            // Province comes from the active case. Without it the pipeline resolves
            // province to "unknown", and the retriever's filter then matches only
            // federal-tagged chunks — hiding every provincial statute in the corpus
            // (~1,600 Punjab sections) unless the lawyer happens to name a city in
            // the query text. The case record already knows the jurisdiction.
            // One id per ATTEMPT, not per transmission. The server
            // deduplicates on it, so resending the same attempt replays the
            // first answer rather than running the graph and paying a provider
            // again. Minting a fresh id per send made the idempotency
            // mechanism unreachable from here.
            let attempt = newAttempt();
            attemptRef.current = attempt;
            // Start watching what the pipeline is doing. This surface has no
            // socket to push stages down, so the stage is recorded on the turn
            // and read back while the request is in flight.
            watchStage(sid, attempt.id);

            // One send, with a deadline, retried ONCE keeping the same id.
            //
            // The retry is only safe because the id is stable: the server
            // claimed this turn before the graph ran, so a second request under
            // the same id replays the first answer rather than paying a
            // provider again. A fresh id here would be a second question.
            const send = async (a) => {
                const timer = setTimeout(
                    () => a.controller?.abort(), RESEARCH_TIMEOUT_MS);
                try {
                    return await aiResearch(q, sid, {
                        client_message_id: a.id,
                        language: lang === "UR" ? "ur" : "en",
                        province: activeCaseObj?.province || null,
                        history: msgHistory,
                        // The DATABASE id only. `.id` is the display case
                        // number shown in the UI ("CIV-2026-001"); falling back
                        // to it would send an identifier the server cannot look
                        // up, which now surfaces as a generic "case not
                        // available" rather than working by accident.
                        case_id: activeCaseObj?._id || null,
                        signal: a.controller?.signal || null,
                    });
                } finally {
                    clearTimeout(timer);
                }
            };

            let { data, error, status } = await send(attempt);

            // Ambiguous means the server may or may not have run it — a dropped
            // connection, a timeout, a gateway error. Those are exactly the
            // failures worth retrying, and exactly the ones a new id would turn
            // into a duplicate charge. A 4xx is a decision; repeating it
            // changes nothing.
            if ((error || !data) && isAmbiguousFailure(status)
                    && !cancelledRef.current) {
                attempt = retryAttempt(attempt);
                attemptRef.current = attempt;
                // Same id, so the same turn — but re-armed, because the
                // previous poll stopped when the attempt object changed.
                watchStage(sid, attempt.id);
                ({ data, error, status } = await send(attempt));
            }

            if (cancelledRef.current) {
                fill({ content: stopNoticeRef.current, notice: true });
                return;
            }
            if (error || !data) {
                // Carried to the catch below so the lawyer is told WHICH failure
                // this was. `.message` is the formatted string; `.detail` is the
                // raw body field and was never set on these errors.
                const failure = new Error(error?.message || "request failed");
                failure.status = status;
                failure.fromServer = !!error;
                throw failure;
            }

            if (data.type === "clarification") {
                // A clarifying question is an emitted output with its own
                // provenance record, so it carries an id like any answer.
                fill({ content: data.question, clarification: true,
                       requestId: data.request_id || "" });
                // Recorded on the thread too, so reopening it later says the
                // conversation is waiting rather than looking like it stopped.
                setPendingQuestion(data.question || null);
            } else {
                setPendingQuestion(null);
                fill({
                    content: data.answer || "No response received.",
                    // matched | unresolved | retrieved, repeal currency, and a
                    // source link where the document is actually held.
                    citations: normaliseCitations(data.citations),
                    claims: data.claims || [],
                    confidence: data.confidence,
                    confidenceBand: data.confidence_band,
                    modelConfidence: data.model_confidence,
                    arbitrationSource: data.arbitration_source,
                    jurisdiction: data.jurisdiction,
                    jurisdictionBasis: data.jurisdiction_basis,
                    convergenceStatus: data.convergence_status,
                    // The turn ran and the answer is real, but it was not
                    // filed. A lawyer relying on it needs to know it will not
                    // be in the thread tomorrow.
                    historySaved: data.history_saved !== false,
                    // Whether this turn reached the audit trail. Identical
                    // wording to the restored path, so a live answer and the
                    // same answer after a reload cannot report different
                    // things about their own auditability.
                    auditSaved: data.audit_saved !== false,
                    auditPending: data.audit_pending === true,
                    // Names this turn's audit record. Without it a lawyer
                    // looking at an answer could neither open its provenance
                    // nor quote it when reporting a bad one.
                    requestId: data.request_id || "",
                });
            }
        } catch (e) {
            // A deliberate Stop aborts the fetch, which lands here. It is not a
            // service failure and must not be reported as one.
            fill(cancelledRef.current || e?.name === "AbortError"
                ? { content: stopNoticeRef.current, notice: true }
                : { content: researchErrorText(e) });
        } finally {
            // Settled either way: answered, refused, timed out or stopped.
            // Leaving `attemptRef` set would keep the composer locked on a turn
            // that has already ended.
            attemptRef.current = null;
            // Stopped HERE rather than in each branch: a poll that outlives its
            // turn is a request every two seconds forever, and the branch that
            // forgot would be the rare one nobody exercises.
            stopWatchingStage();
            setLoading(false);
        }
    };

    /* How long to wait for one research answer before giving up on it.
       Longer than the server's own turn timeout, so its honest explanation wins
       whenever it can produce one. */
    const RESEARCH_TIMEOUT_MS = 150000;

    /* ── Stop ──────────────────────────────────────────────────────────────
       Two separate things, and both are needed. Aborting the fetch ends the
       WAIT; the server-side cancel discards the ANSWER, by clearing the turn's
       lease so the running worker's fenced completion matches nothing. Without
       the second, the answer would still be filed and would reappear on the
       next reload — which is not what "stop" means. */
    const stop = useCallback(async () => {
        const waiting = attemptRef.current;
        const sid = sessionIdRef.current;
        if (!waiting || !sid) return;
        cancelledRef.current = true;
        try { waiting.controller?.abort(); } catch { /* already settled */ }
        // The server says what actually happened — stopped, already answered,
        // already ended. Displaying "Stopped." regardless is a claim the next
        // reload contradicts: the answer it says was discarded is sitting in
        // the thread.
        const { data } = await cancelResearchTurn(sid, waiting.id);
        stopNoticeRef.current = data?.message || "Stopped.";
    }, []);

    const hasMessages = msgs.length > 0;
    // The "…" menu holds the less-used history actions.
    const [histMenu, setHistMenu] = useState(false);
    const [histOpen, setHistOpen] = useState(true);   // ^ folds the list
    // The Sources panel on the right: one answer's citations, one in focus.
    const [srcPanel, setSrcPanel] = useState(null);   // { list, focus }
    useEffect(() => { setSrcPanel(null); }, [sessionId]);
    // Hands a citation to the Legal library (Case Law), which runs it as a search.
    const openInLibrary = (c) => {
        const term = (c.label || "").replace(/§\s*/g, "section ").trim();
        try { sessionStorage.setItem("attorney:caselaw-query", term); } catch { /* storage off */ }
        setPage?.("caselaw");
    };
    // One thread's "…" menu: { item, x, y } within the sidebar card.
    const [rowMenu, setRowMenu] = useState(null);
    useEffect(() => {
        if (!rowMenu) return undefined;
        const close = (e) => { if (!e.target.closest?.("[data-row-menu]")) setRowMenu(null); };
        const esc = (e) => { if (e.key === "Escape") setRowMenu(null); };
        document.addEventListener("mousedown", close);
        document.addEventListener("keydown", esc);
        return () => { document.removeEventListener("mousedown", close); document.removeEventListener("keydown", esc); };
    }, [rowMenu]);
    // Cases with a hearing coming up, soonest first: the "From your cases"
    // cards. Dates are the case's own next unheard hearing, nothing invented.
    const todayKey = new Date().toISOString().slice(0, 10);
    const weekKey = new Date(Date.now() + 7 * 864e5).toISOString().slice(0, 10);
    const upcoming = apiCases
        .filter(c => c.nextHearing !== "TBD" && c.nextHearing >= todayKey)
        .sort((a, b) => a.nextHearing.localeCompare(b.nextHearing));
    const hearingsThisWeek = upcoming.filter(c => c.nextHearing <= weekKey).length;
    const caseCards = (upcoming.length ? upcoming : apiCases).slice(0, 3);
    const whenLabel = (d) => {
        if (!d || d === "TBD") return { text: "No hearing set", c: "var(--faint)" };
        const days = Math.round((new Date(d) - new Date(todayKey)) / 864e5);
        if (days === 0) return { text: "Hearing today", c: "var(--amber, #F2C35E)" };
        if (days === 1) return { text: "Tomorrow", c: "var(--amber, #F2C35E)" };
        return { text: new Date(d).toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" }), c: "#3CCFE0" };
    };
    const threadTitle = hasMessages ? (rows.find(r => r.session_id === sessionId)?.title || "Research") : "New research";

    return (
        <div className="ai-shell" style={{ display: "flex", flex: 1, overflow: "hidden", gap: 14, padding: "0 14px 0 0", position: "relative" }}>

            {/* ── SIDEBAR ── */}
            <section aria-label="Conversations" className="ai-convs" style={{
                width: sideOpen ? 200 : 0, minWidth: sideOpen ? 200 : 0, borderWidth: sideOpen ? 1 : 0,
            }}>

                <div className="cv-top">
                    <button type="button" className="ai-new"
                        onClick={() => startConversation(activeCaseObj ? (activeCaseObj._id || null) : null)}
                        title={activeCaseObj ? `Start a new thread for ${activeCaseObj.id}` : "Start a new general research thread"}>
                        <svg width={16} height={16} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M21 12a9 9 0 0 1-13.5 7.8L3 21l1.2-4.5A9 9 0 1 1 21 12z" /><path d="M8 10.5h8M8 14h5" /></svg>
                        New Chat
                    </button>
                </div>
                <div className="cv-head">
                    <b>History{showArchived && <small> · Archived</small>}</b>
                    <div style={{ display: "flex", gap: 2, alignItems: "center", position: "relative" }}>
                        <button type="button" className="ai-icon" aria-expanded={histOpen}
                            aria-label={histOpen ? "Fold history" : "Show history"} title={histOpen ? "Fold history" : "Show history"}
                            onClick={() => setHistOpen(v => !v)}>
                            <svg width={16} height={16} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"
                                style={{ transform: histOpen ? "none" : "rotate(180deg)", transition: "transform .2s" }}><path d="m6 15 6-6 6 6" /></svg>
                        </button>
                        <button type="button" className="ai-icon" aria-haspopup="menu" aria-expanded={histMenu}
                            aria-label="History options" title="History options" onClick={() => setHistMenu(v => !v)}>
                            <svg width={18} height={18} viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><circle cx="5" cy="12" r="1.9" /><circle cx="12" cy="12" r="1.9" /><circle cx="19" cy="12" r="1.9" /></svg>
                        </button>
                        {histMenu && (
                            <div role="menu" className="ai-menu" onMouseLeave={() => setHistMenu(false)}>
                                <button type="button" role="menuitem"
                                    title={showArchived ? "Hide archived threads" : "Show archived threads"}
                                    onClick={() => { setHistMenu(false); setShowArchived(v => !v); }}>
                                    {showArchived ? "Hide archived threads" : "Show archived threads"}
                                </button>
                            </div>
                        )}
                    </div>
                </div>
                {/* Found in what was SAID.
                    Separate from the list above because it carries the
                    sentence that matched, which is the only part that tells a
                    lawyer why this thread came back. */}
                {messageHits.length > 0 && (
                    <div style={{ padding: "0 10px 8px" }}>
                        <div style={{
                            fontSize: 11, fontWeight: 600, color: t.textMuted,
                            padding: "6px 6px 4px", textTransform: "uppercase",
                            letterSpacing: "0.6px",
                        }}>
                            Found in messages
                        </div>
                        {messageHits.map(hit => (
                            <div key={`hit-${hit.session_id}`}
                                 onClick={() => openConversation(hit.session_id, { adopt: true })}
                                 style={{
                                     padding: "7px 8px", borderRadius: 8,
                                     cursor: "pointer", marginBottom: 2,
                                 }}>
                                <div style={{
                                    fontSize: 12.5, color: t.text,
                                    whiteSpace: "nowrap", overflow: "hidden",
                                    textOverflow: "ellipsis",
                                }}>
                                    {hit.title}
                                </div>
                                <div style={{
                                    fontSize: 11, color: t.textMuted,
                                    marginTop: 2, lineHeight: 1.45,
                                }}>
                                    {hit.snippet}
                                </div>
                            </div>
                        ))}
                    </div>
                )}

                {unsearchable && (
                    <div style={{
                        margin: "0 16px 8px", padding: "6px 9px",
                        borderRadius: 8, fontSize: 11,
                        color: t.textMuted, background: t.surface,
                        border: `1px solid ${t.border}`,
                    }}>
                        Some older threads can only be found by their title, not
                        by what was said in them.
                    </div>
                )}

                {/* History list */}
                <div className="cv-list" style={{ display: histOpen ? "block" : "none" }}>
                    {history.map((g, gi) => (
                        <div key={gi} style={{ marginBottom: 12 }}>
                            <div className="cv-g">{g.group}</div>
                            {/* Real conversations. Clicking one reopens it with its
                                messages and any question it was waiting on. */}
                            {g.items.map((item) => {
                                const active = item.session_id === sessionId;
                                return (
                                    <div key={item.session_id}
                                        onClick={() => openConversation(item.session_id, { adopt: true })}
                                        title={item.title}
                                        className={`cv${active ? " on" : ""}`}>
                                        {/* A thread that stopped on a question, not an answer. */}
                                        {item.awaiting_clarification && (
                                            <span title="Waiting on your answer" style={{ color: "#f59e0b", fontSize: 10 }}>?</span>
                                        )}
                                        <span style={{ flex: 1, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                                            {item.title}
                                        </span>
                                        <button type="button" className="cv-more" title="More actions"
                                            aria-label={`Actions for ${item.title}`} aria-haspopup="menu"
                                            aria-expanded={rowMenu?.item.session_id === item.session_id}
                                            onClick={(e) => {
                                                e.stopPropagation();
                                                // Placed inside the sidebar card, under the button
                                                // (or above it near the bottom).
                                                const r = e.currentTarget.getBoundingClientRect();
                                                const box = e.currentTarget.closest(".ai-convs").getBoundingClientRect();
                                                const below = r.bottom - box.top + 4;
                                                const y = below + 92 > box.height ? r.top - box.top - 92 : below;
                                                setRowMenu(m => m?.item.session_id === item.session_id ? null
                                                    : { item, x: r.right - box.left - 112, y });
                                            }}>
                                            <svg width={15} height={15} viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><circle cx="5" cy="12" r="1.8" /><circle cx="12" cy="12" r="1.8" /><circle cx="19" cy="12" r="1.8" /></svg>
                                        </button>
                                    </div>
                                );
                            })}
                        </div>
                    ))}
                    {/* Follows `has_more`, NOT "did this page return rows".
                        Threads on revoked cases are filtered out server-side
                        AFTER the read, so a page can legitimately come back
                        empty while more accessible threads wait behind it —
                        the server's cursor advances over them. */}
                    {listMore && (
                        <button
                            onClick={loadMoreHistory}
                            disabled={listLoading}
                            style={{
                                width: "100%", marginTop: 4, padding: "7px 10px",
                                fontSize: 11.5, borderRadius: 8, cursor: "pointer",
                                background: "none", color: t.textMuted,
                                border: `1px dashed ${t.border}`,
                            }}>
                            {listLoading ? "Loading\u2026" : "Load older threads"}
                        </button>
                    )}
                    {!listMore && !listLoading && rows.length === 0 && (
                        search ? (
                            <div style={{ padding: "10px 8px", fontSize: 13, color: "var(--faint)" }}>No threads match that search.</div>
                        ) : (
                            <div className="cv-empty">{showArchived ? "No archived chats." : "Your chat history is empty."}</div>
                        )
                    )}
                </div>
                {rowMenu && (() => {
                    const item = rowMenu.item;
                    return (
                        <div role="menu" data-row-menu className="ai-menu cv-menu"
                            style={{ position: "absolute", left: Math.max(8, rowMenu.x), top: Math.max(8, rowMenu.y), right: "auto" }}>
                            <button type="button" role="menuitem" title="Rename" onClick={() => {
                                setRowMenu(null);
                                const next = window.prompt("Rename this research thread", item.title);
                                if (next && next.trim()) {
                                    renameResearchConversation(item.session_id, next.trim())
                                        .then(({ error }) => {
                                            if (error) setConversationError(error.message || "Could not rename the thread.");
                                            refreshHistory();
                                        });
                                }
                            }}>
                                <svg width={15} height={15} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M12 20h9" /><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z" /></svg>
                                Rename
                            </button>
                            {/* Archive keeps the thread and its messages and
                                drops it out of the default list — closing a
                                file rather than shredding it. */}
                            <button type="button" role="menuitem" title={item.archived ? "Unarchive" : "Archive"} onClick={() => {
                                setRowMenu(null);
                                archiveResearchConversation(item.session_id, !item.archived)
                                    .then(({ error }) => {
                                        if (error) setConversationError(error.message || "Could not update the thread.");
                                        refreshHistory();
                                    });
                            }}>
                                <svg width={15} height={15} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><rect x="3" y="4" width="18" height="4" rx="1" /><path d="M5 8v11a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8M10 12h4" /></svg>
                                {item.archived ? "Unarchive" : "Archive"}
                            </button>
                            <button type="button" role="menuitem" title="Delete" className="danger" onClick={() => {
                                setRowMenu(null);
                                if (!window.confirm("Delete this thread and its messages?")) return;
                                deleteResearchConversation(item.session_id).then(async ({ error }) => {
                                    if (error) {
                                        setConversationError(error.message || "Could not delete the thread.");
                                        return;
                                    }
                                    if (item.session_id === sessionIdRef.current) {
                                        writeActiveSession("research", user?._id, null);
                                        await startConversation(activeCaseObj ? (activeCaseObj._id || null) : null);
                                    }
                                    refreshHistory();
                                });
                            }}>
                                <svg width={15} height={15} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6" /></svg>
                                Delete
                            </button>
                        </div>
                    );
                })()}
                <div className="cv-foot"><span>Chats are private to you</span><span>{rows.length}{listMore ? "+" : ""} chat{rows.length === 1 ? "" : "s"}</span></div>
            </section>
            {/* Fold or open the sidebar: one round button on its edge. */}
            <button type="button" className="ai-edge" onClick={() => setSideOpen(v => !v)}
                aria-label={sideOpen ? "Collapse history" : "Open history"} title={sideOpen ? "Hide history" : "Show history"}
                style={{ left: sideOpen ? 200 - 16 : 8 }}>
                <svg width={13} height={13} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                    <path d={sideOpen ? "M15 18l-6-6 6-6" : "M9 18l6-6-6-6"} />
                </svg>
            </button>

            {/* ── MAIN CHAT AREA ── */}
            <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden", position: "relative" }}>

                <div className="ch-head" style={{ paddingTop: 14, paddingLeft: sideOpen ? 10 : 40 }}>
                    {!sideOpen && (
                        <button type="button" className="chipbtn" onClick={() => setSideOpen(true)} aria-label="Open history">
                            <svg width={14} height={14} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true"><rect x="3" y="4" width="18" height="16" rx="2" /><path d="M9 4v16" /></svg>
                            History
                        </button>
                    )}
                    <h1 title={threadTitle}>{threadTitle}</h1>
                    <div className="scope">
                        <span className="chipbtn" title="Answers come from the statutes and reported judgments in the library">Sources <b>Statutes &amp; case law</b></span>
                        {activeCaseObj ? (
                            <button type="button" className="chipbtn case" onClick={() => setActiveCase?.(null)} title="Unlink this case (starts a general thread)">
                                Case <b>{activeCaseObj.id}</b><span className="x" aria-hidden="true">×</span>
                            </button>
                        ) : apiCases.length > 0 && (
                            <label className="chipbtn" style={{ position: "relative" }}>
                                + Link case
                                <select aria-label="Link a case" value="" onChange={e => e.target.value && setActiveCase?.(e.target.value)}
                                    style={{ position: "absolute", inset: 0, opacity: 0, cursor: "pointer" }}>
                                    <option value="">Link a case</option>
                                    {apiCases.map(c => <option key={c._id} value={c.id}>{c.id} — {c.title}</option>)}
                                </select>
                            </label>
                        )}
                    </div>
                </div>

                {/* Messages / Welcome */}
                <div className="ai-scroll" style={{
                    flex: 1, minHeight: 0, overflowY: "auto",
                    display: "flex", flexDirection: "column", alignItems: "center",
                    padding: "8px 24px 16px"
                }}>

                    {conversationError && (
                        <div role="alert" style={{
                            width: "100%", maxWidth: 800, marginBottom: 12,
                            padding: "10px 13px", borderRadius: 10,
                            color: "#e8526a", background: "rgba(232,82,106,0.10)",
                            border: "1px solid rgba(232,82,106,0.35)", fontSize: 12,
                        }}>
                            {conversationError}
                        </div>
                    )}
                    {caseNotice && (
                        <div role="status" style={{
                            width: "100%", maxWidth: 800, marginBottom: 12,
                            padding: "10px 13px", borderRadius: 10,
                            color: t.warn, background: `${t.warn}14`,
                            border: `1px solid ${t.warn}55`, fontSize: 12,
                        }}>
                            {caseNotice}
                        </div>
                    )}

                    {!hasMessages ? (
                        /* Welcome screen */
                        <div className="ai-start">
                        <div className="ai-welcome">
                            <div className="hi"><i aria-hidden="true" />{greetWord.charAt(0) + greetWord.slice(1).toLowerCase()}, {firstName}{hearingsThisWeek > 0 ? ` · ${hearingsThisWeek} case${hearingsThisWeek === 1 ? "" : "s"} with a hearing this week` : ""}</div>
                            <h2>{activeCaseObj
                                ? <>Research for <span>{activeCaseObj.id}</span></>
                                : <>Ask anything about <span>Pakistani law</span></>}</h2>
                        </div>
                            <div className="ai-below">
                                {caseCards.length > 0 && (
                                    <>
                                        <div className="ctx-h">
                                            <span>From your cases</span>
                                        </div>
                                        <div className="ctx">
                                            {caseCards.map(c => {
                                                const w = whenLabel(c.nextHearing);
                                                return (
                                                    <button type="button" key={c._id} className="cx"
                                                        title={`Research for ${c.id}`}
                                                        onClick={() => { setActiveCase?.(c.id); setQuery(`Key arguments and authorities for ${c.title}`); }}>
                                                        <span className="top"><span className="when" style={{ color: w.c }}>{w.text}</span><span className="case">{c.id}</span></span>
                                                        <b>{c.title}</b>
                                                        <small>{[c.type, c.client].filter(Boolean).join(" · ")}</small>
                                                    </button>
                                                );
                                            })}
                                        </div>
                                    </>
                                )}
                                <PromptRail onPick={setQuery} prompts={activeCaseObj ? [
                                        `What sections apply to ${activeCaseObj.type} cases in Pakistan?`,
                                        `Key arguments for ${activeCaseObj.title}`,
                                        `Recent precedents for ${activeCaseObj.type} law`,
                                    ] : [
                                        "PPC sections for cheque dishonour",
                                        "Bail conditions under CrPC 1898",
                                        "Eviction grounds, Punjab Rent Act 2009",
                                        "Contempt of court procedure",
                                    ]} />
                            </div>
                        </div>
                    ) : (
                        /* Message thread */
                        <div style={{ width: "100%", maxWidth: 800, display: "flex", flexDirection: "column", gap: 18 }}>
                            {/* Older messages, on demand.
                                A conversation opens at its END, so this is the
                                only way back — and it is at the TOP of the
                                transcript because that is where the history it
                                loads belongs. */}
                            {hasOlder && (
                                <div style={{ display: "flex", justifyContent: "center",
                                              padding: "2px 0 10px" }}>
                                    <button
                                        onClick={loadOlder}
                                        disabled={loadingOlder}
                                        style={{
                                            padding: "5px 14px", fontSize: 11.5,
                                            borderRadius: 999, cursor: "pointer",
                                            background: "none", color: t.textMuted,
                                            border: `1px solid ${t.border}`,
                                        }}>
                                        {loadingOlder ? "Loading\u2026" : "Load earlier messages"}
                                    </button>
                                </div>
                            )}
                            {msgs.map((m, i) => (
                                <div key={i} style={{ display: "flex", flexDirection: m.role === "user" ? "row-reverse" : "row", gap: 10, alignItems: "flex-start" }} className="fade-in">
                                    {m.role === "assistant" && (
                                        <div style={{ width: 34, height: 34, borderRadius: 10, background: t.primaryGlow, display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
                                            <Icon d={I.ai} size={16} style={{ color: t.primary }} />
                                        </div>
                                    )}
                                    <div style={{ maxWidth: "75%" }}>
                                        <div style={{
                                            background: m.role === "user" ? t.grad1 : t.surface,
                                            // A clarification is a QUESTION to the lawyer, not advice.
                                            // Rendered identically to an answer it reads as one, which is
                                            // the worst possible confusion on a legal surface.
                                            border: m.role === "assistant" ? `1px solid ${m.clarification ? t.primary : t.border}` : "none",
                                            borderRadius: m.role === "user" ? "18px 18px 6px 18px" : "18px 18px 18px 6px",
                                            padding: "12px 16px", fontSize: 13.5, lineHeight: 1.8,
                                            color: m.role === "user" ? (t.mode === "dark" ? "#111B1F" : "#fff") : t.text,
                                            whiteSpace: "pre-wrap", minHeight: m.streaming && !m.content ? 20 : undefined,
                                        }}>
                                            {m.clarification && (
                                                <div style={{ fontSize: 11, color: t.primary, fontWeight: 700, marginBottom: 6, textTransform: "uppercase", letterSpacing: "0.5px" }}>
                                                    Clarification needed
                                                </div>
                                            )}
                                            {m.content || (m.streaming ? "" : "No response received.")}
                                            {m.streaming && <span style={{ display: "inline-block", width: 2, height: "1em", background: t.primary, marginLeft: 2, verticalAlign: "text-bottom", animation: "aiBlink 1s step-end infinite" }} />}
                                            {/* A way out of a long wait. Stops
                                                the waiting AND discards the
                                                answer server-side, so it does
                                                not reappear on reload. */}
                                            {/* What the pipeline is doing.
                                                A blinking cursor for ninety
                                                seconds is indistinguishable
                                                from a hang; the stage says
                                                whether a long wait is a hard
                                                search or a shaky answer being
                                                re-checked. */}
                                            {m.streaming && stage && (
                                                <span style={{
                                                    marginLeft: 10, fontSize: 11.5,
                                                    color: t.textMuted,
                                                }}>
                                                    {stage}
                                                </span>
                                            )}
                                            {m.streaming && (
                                                <button onClick={stop}
                                                        title="Stop generating"
                                                        style={{
                                                            marginLeft: 10, background: "none",
                                                            border: `1px solid ${t.border}`,
                                                            borderRadius: 8, padding: "2px 9px",
                                                            fontSize: 11, cursor: "pointer",
                                                            color: t.textMuted,
                                                        }}>
                                                    Stop
                                                </button>
                                            )}
                                            {/* Claim-level support. Above the citation chips on
                                                purpose: which proposition rests on which section,
                                                and whether that section carries it, is the research
                                                question — the chip list only says what was cited. */}
                                            {m.role === "assistant" && !m.streaming && m.claims?.length > 0 && (() => {
                                                const counts = m.claims.reduce((acc, c) => {
                                                    acc[c.support] = (acc[c.support] || 0) + 1; return acc;
                                                }, {});
                                                const repealed = m.claims.filter(c => c.currency === REPEALED);
                                                const sorted = [...m.claims].sort(
                                                    (a, b) => CLAIM_ORDER.indexOf(a.support) - CLAIM_ORDER.indexOf(b.support));
                                                return (
                                                    <div style={{ marginTop: 10, paddingTop: 10, borderTop: `1px solid ${t.border}` }}>
                                                        {repealed.length > 0 && (
                                                            <div style={{
                                                                fontSize: 11.5, color: "#ef4444", fontWeight: 700,
                                                                marginBottom: 7, padding: "7px 10px", borderRadius: 7,
                                                                background: "#ef444414", border: "1px solid #ef444455",
                                                            }}>
                                                                {"\u26D4"} {CURRENCY_TEXT.repealed}
                                                                <div style={{ fontWeight: 400, fontSize: 10.5, marginTop: 3, color: t.text }}>
                                                                    {repealed.length} claim{repealed.length === 1 ? "" : "s"} rest
                                                                    {repealed.length === 1 ? "s" : ""} on a repealed section. Do not file on this
                                                                    without substituting the provision now in force.
                                                                </div>
                                                            </div>
                                                        )}
                                                        <div style={{
                                                            fontSize: 10, color: t.textMuted, marginBottom: 6,
                                                            textTransform: "uppercase", letterSpacing: "0.06em", fontWeight: 700,
                                                            display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center",
                                                        }}>
                                                            <span>Claim support ({m.claims.length})</span>
                                                            {CLAIM_ORDER.filter(k => counts[k]).map(k => (
                                                                <span key={k} style={{ color: CLAIM_UI[k].color, fontWeight: 700 }}>
                                                                    {counts[k]} {CLAIM_UI[k].label.toLowerCase()}
                                                                </span>
                                                            ))}
                                                        </div>
                                                        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                                                            {sorted.map((c, ci) => {
                                                                const dead = c.currency === REPEALED;
                                                                const ui = dead
                                                                    ? { icon: "\u26D4", color: "#ef4444", label: "Repealed",
                                                                        note: "do not rely on this authority" }
                                                                    : (CLAIM_UI[c.support] || CLAIM_UI.unassessed);
                                                                const notes = (c.sources || []).map(repealNote).filter(Boolean);
                                                                return (
                                                                    <div key={ci} style={{
                                                                        borderLeft: `2px solid ${ui.color}`, paddingLeft: 9,
                                                                    }}>
                                                                        <div style={{ fontSize: 12, color: t.text, lineHeight: 1.55 }}>
                                                                            “{c.text}”
                                                                        </div>
                                                                        <div style={{ fontSize: 10.5, marginTop: 3, display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center" }}>
                                                                            <span style={{ color: ui.color, fontWeight: 700 }}>
                                                                                {ui.icon} {ui.label}
                                                                            </span>
                                                                            <span style={{ color: t.textFaint }}>— {ui.note}</span>
                                                                            {dead && notes.length > 0 && (
                                                                                <span style={{ color: "#ef4444" }}>{notes.join("; ")}</span>
                                                                            )}
                                                                            {c.sources?.length > 0 && (
                                                                                <span className="mono" style={{ color: t.primary }}>
                                                                                    {c.sources.map(sc => `[${sc.id}] ${[sc.statute, sc.section ? `§${sc.section}` : ""].filter(Boolean).join(" ")}`).join("  ")}
                                                                                </span>
                                                                            )}
                                                                            {c.unresolved?.length > 0 && (
                                                                                <span style={{ color: "#f59e0b" }}>
                                                                                    cites {c.unresolved.map(u => [u.statute, u.section ? `§${u.section}` : ""].filter(Boolean).join(" ")).join("; ")} — not in retrieved evidence
                                                                                </span>
                                                                            )}
                                                                        </div>
                                                                    </div>
                                                                );
                                                            })}
                                                        </div>
                                                        <div style={{ fontSize: 10, color: t.textFaint, marginTop: 7 }}>
                                                            Support is judged against the retrieved sources only. Where a
                                                            section is not marked repealed its current status is NOT verified —
                                                            repeal data covers 4 of 43 statutes and is a lower bound, and
                                                            amendment is not checked at all.
                                                        </div>
                                                    </div>
                                                );
                                            })()}
                                            {m.role === "assistant" && !m.streaming && m.citations?.length > 0 && (
                                                <div style={{ marginTop: 10, paddingTop: 10, borderTop: `1px solid ${t.border}` }}>
                                                    {CITATION_GROUPS.map(({ key, lawyer: caption }) => {
                                                        const tone = key === "matched" ? t.primary
                                                            : key === "unresolved" ? "#f59e0b" : t.textFaint;
                                                        const group = citationsInGroup(m.citations, key);
                                                        if (!group.length) return null;
                                                        return (
                                                            <div key={key} style={{ marginBottom: 8 }}>
                                                                <div style={{ fontSize: 10, color: tone, marginBottom: 4, fontWeight: key === "unresolved" ? 700 : 500 }}>
                                                                    {caption}
                                                                </div>
                                                                <div style={{ display: "flex", flexWrap: "wrap", gap: 5 }}>
                                                                    {group.map((c, ci) => {
                                                                        // Repeal outranks match status on the chip too: being
                                                                        // cited AND retrieved says nothing about whether the
                                                                        // provision still exists.
                                                                        const chipDead = c.currency === REPEALED;
                                                                        // `href` is an external court PDF (a real anchor);
                                                                        // `sourceUrl` is our own bearer-authenticated corpus
                                                                        // route, which a new tab cannot open by itself.
                                                                        const openable = c.href || c.sourceUrl;
                                                                        const icon = chipDead ? "⛔" : c.judgment ? "⚖️" : key === "matched" ? "✓" : key === "unresolved" ? "?" : "📖";
                                                                        const chipStyle = {
                                                                            fontSize: 11, padding: "3px 9px", borderRadius: 7,
                                                                            background: chipDead ? "#ef444414" : t.cardHi,
                                                                            border: `1px solid ${chipDead ? "#ef444466" : key === "unresolved" ? "#f59e0b55" : t.border}`,
                                                                            color: chipDead ? "#ef4444" : (openable ? t.primary : (key === "unresolved" ? "#f59e0b" : t.textMuted)),
                                                                            textDecoration: "none", fontWeight: (chipDead || openable) ? 700 : 400,
                                                                        };
                                                                        // `href` is set only when the source document is really
                                                                        // held — about half the corpus by chunk count — so a chip
                                                                        // is a link exactly when there is something to open. The
                                                                        // filename still shows in the tooltip either way, which is
                                                                        // strictly more than the previous chip said.
                                                                        const title = chipDead
                                                                            ? (repealNote(c) || "repealed")
                                                                            : [c.province, c.source, c.chunkId].filter(Boolean).join(" · ");
                                                                        const text = `${icon} ${c.label}${chipDead ? " — repealed" : ""}`;
                                                                        const on = srcPanel?.focus === c;
                                                                        return (
                                                                            <button key={ci} type="button"
                                                                                style={{ ...chipStyle, cursor: "pointer", fontFamily: "inherit", outline: on ? "2px solid var(--mint)" : "none", outlineOffset: 1 }}
                                                                                title={`${title}${title ? " · " : ""}show in Sources`}
                                                                                onClick={() => setSrcPanel({ list: m.citations, focus: c })}>
                                                                                {text}
                                                                            </button>
                                                                        );
                                                                    })}
                                                                </div>
                                                            </div>
                                                        );
                                                    })}
                                                </div>
                                            )}
                                        </div>
                                        {m.time && (
                                            <div style={{ fontSize: 10, color: t.textFaint, marginTop: 4, textAlign: m.role === "user" ? "right" : "left", display: "flex", alignItems: "center", gap: 8, justifyContent: m.role === "user" ? "flex-end" : "flex-start" }}>
                                                {m.time}
                                                {m.role === "assistant" && !m.streaming && !m.clarification && !m.notice && m.content && (
                                                    m.confidenceBand ? (
                                                        <span style={{ color: CONF_COLOR[m.confidenceBand] || t.textFaint }}
                                                              title={m.modelConfidence != null ? `model self-report: ${Math.round(m.modelConfidence * 100)}% (diagnostic, not calibrated)` : undefined}>
                                                            ⬤ {CONF_LABEL[m.confidenceBand]} confidence · {Math.round(m.confidence * 100)}%
                                                            {m.arbitrationSource ? ` (evidence: ${m.arbitrationSource})` : ""}
                                                        </span>
                                                    ) : (
                                                        <span style={{ color: t.textFaint }}>Confidence not calibrated</span>
                                                    )
                                                )}
                                                {m.role === "assistant" && !m.streaming && !m.clarification && !m.notice && m.content && (
                                                    m.rated ? <span>feedback recorded ✓</span> : (
                                                        <span style={{ display: "inline-flex", gap: 3, alignItems: "center" }}>
                                                            {m.rateError && <span style={{ color: t.danger }}>feedback not saved</span>}
                                                            {["up", "down"].map(r => (
                                                                <button key={r}
                                                                    onClick={() => {
                                                                        // "Recorded" only once the server has it.
                                                                        // apiFetch resolves with {error} rather than
                                                                        // rejecting, so a .catch never saw a failure.
                                                                        rateAnswer({
                                                                            session_id: sessionIdRef.current,
                                                                            rating: r,
                                                                            answer_preview: (m.content || "").slice(0, 300),
                                                                            question_preview: (msgs[i - 1]?.content || "").slice(0, 300),
                                                                            source: "research",
                                                                        }).then(({ error }) => setMsgs(prev => prev.map((x, xi) => xi === i
                                                                            ? (error ? { ...x, rateError: true } : { ...x, rated: r, rateError: false })
                                                                            : x)));
                                                                    }}
                                                                    style={{ border: `1px solid ${t.border}`, background: "transparent", borderRadius: 6, cursor: "pointer", fontSize: 10, padding: "1px 6px" }}
                                                                >{r === "up" ? "👍" : "👎"}</button>
                                                            ))}
                                                        </span>
                                                    )
                                                )}
                                                {/* Names this turn's audit record. Shown on
                                                    clarifications too — a clarifying question is
                                                    an emitted output with a record of its own. */}
                                                {(() => {
                                                    // An answer still being
                                                    // written has no audit
                                                    // record yet, and saying so
                                                    // would be reporting a
                                                    // failure that has not
                                                    // happened.
                                                    if (m.role !== "assistant"
                                                        || m.streaming) return null;
                                            // Nothing at all when the record is
                                            // safely written — which is almost
                                            // always. A badge on every answer
                                            // confirming the system worked is
                                            // noise, and noise is what stops
                                            // people reading the one that
                                            // matters.
                                            const notice = auditNotice(m);
                                            if (!notice) return null;
                                            const warn = notice.tone === "warn";
                                            return (
                                                <div title={notice.detail} style={{
                                                    marginTop: 6, padding: "6px 10px",
                                                    borderRadius: 8, fontSize: 11.5,
                                                    background: warn ? "#f59e0b14" : "#64748b14",
                                                    border: `1px solid ${warn ? "#f59e0b55" : "#64748b44"}`,
                                                    color: warn ? t.text : t.textMuted,
                                                }}>
                                                    {warn ? "\u26a0 " : ""}{notice.label}
                                                </div>
                                            );
                                        })()}
                                                {m.role === "assistant" && !m.streaming && m.requestId && (
                                                    <RequestIdChip
                                                        requestId={m.requestId}
                                                        open={!!m.auditOpen}
                                                        onToggle={() => setMsgs(prev => prev.map(
                                                            (x, xi) => xi === i ? { ...x, auditOpen: !x.auditOpen } : x))}
                                                        t={t}
                                                    />
                                                )}
                                            </div>
                                        )}
                                        {/* Produced but not filed. A lawyer
                                            relying on this answer needs to know
                                            it will not be in the thread
                                            tomorrow — silence here meant they
                                            found out by its absence. */}
                                        {m.role === "assistant" && !m.streaming
                                            && m.historySaved === false && (
                                            <div style={{
                                                marginTop: 6, padding: "6px 10px",
                                                borderRadius: 8, fontSize: 11.5,
                                                background: "#f59e0b14",
                                                border: "1px solid #f59e0b55",
                                                color: t.text,
                                            }}>
                                                ⚠ This answer was not saved to the
                                                conversation. Copy anything you need —
                                                it will not be here after a refresh.
                                            </div>
                                        )}
                                        {m.auditOpen && m.requestId && (
                                            <ProvenancePanel
                                                requestId={m.requestId}
                                                onClose={() => setMsgs(prev => prev.map(
                                                    (x, xi) => xi === i ? { ...x, auditOpen: false } : x))}
                                                t={t}
                                            />
                                        )}
                                    </div>
                                </div>
                            ))}
                            {/* This thread is still owed an answer from before
                                the refresh. Said plainly, because the only other
                                option a lawyer has is to ask again — which costs
                                a second run for the same question. */}
                            {recovering && (
                                <div style={{
                                    margin: "8px 0", padding: "8px 12px", borderRadius: 10,
                                    fontSize: 12, color: t.textMuted,
                                    background: t.surface, border: `1px solid ${t.border}`,
                                }}>
                                    An answer to your last question is still being
                                    written. It will appear here — no need to ask again.
                                </div>
                            )}
                            {loading && !msgs.some(m => m.streaming) && (
                                <div style={{ display: "flex", gap: 10, alignItems: "flex-start" }}>
                                    <div style={{ width: 34, height: 34, borderRadius: 10, background: t.primaryGlow, display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
                                        <Icon d={I.ai} size={16} style={{ color: t.primary }} />
                                    </div>
                                    <div style={{ background: t.surface, border: `1px solid ${t.border}`, borderRadius: "18px 18px 18px 6px", padding: "14px 18px", display: "flex", gap: 5, alignItems: "center" }}>
                                        {[0, 1, 2].map(d => <div key={d} style={{ width: 7, height: 7, borderRadius: "50%", background: t.primary, animation: `pulse 1.2s ease ${d * .2}s infinite` }} />)}
                                    </div>
                                </div>
                            )}
                            {/* Reopened mid-question. This thread ended by asking for
                                facts rather than answering, and without saying so the
                                conversation just looks like it stopped.

                                A display hint only: the graph checkpoint decides
                                whether the turn is really interrupted, and the next
                                message is routed by that, not by this banner. A stale
                                banner costs a line of text; resuming into the wrong
                                conversation would cost rather more. */}
                            {pendingQuestion && !loading && (
                                <div style={{
                                    margin: "6px 0", padding: "8px 12px", borderRadius: 9,
                                    background: `${t.primary}12`, border: `1px solid ${t.primary}40`,
                                    fontSize: 11.5, color: t.text, display: "flex", gap: 8,
                                }}>
                                    <span style={{ color: t.primary, fontWeight: 700 }}>?</span>
                                    <span>
                                        This thread is waiting on your answer to:{" "}
                                        <strong>{pendingQuestion}</strong>
                                    </span>
                                </div>
                            )}
                            <div ref={bottomRef} />
                        </div>
                    )}
                </div>

                {/* ── Rich input box ── */}
                <div style={{ padding: "0 24px 10px", display: "flex", flexDirection: "column", alignItems: "center", flexShrink: 0 }}>
                    <div className="ai-box">

                        {/* Text input */}
                        <input value={query} onChange={e => setQuery(e.target.value)}
                            onKeyDown={e => e.key === "Enter" && !e.shiftKey && send()}
                            placeholder="Ask Attorney AI..."
                            style={{
                                width: "100%", background: "transparent", border: "none", outline: "none",
                                color: t.text, fontSize: 15, padding: "2px 2px 8px", lineHeight: 1.5
                            }} />

                        {/* Toolbar row */}
                        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10 }}>
                            {/* What answers: the research assistant, on the corpus. */}
                            <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
                            {setPage && (
                                <button type="button" className="ai-attach" onClick={() => setPage("doc-analyzer")}
                                    aria-label="Attach a document" title="Attach a document (opens Document review)">
                                    <svg width={17} height={17} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="m21.4 11.1-9.2 9.2a6 6 0 0 1-8.5-8.5l9.2-9.2a4 4 0 0 1 5.7 5.7l-9.2 9.2a2 2 0 0 1-2.8-2.8l8.5-8.5" /></svg>
                                </button>
                            )}
                            <span className="ai-chip" title="Answers from Pakistani statutes and case law in the library">
                                <svg width={15} height={15} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M2 5.5A2.5 2.5 0 0 1 4.5 3H10v16H4.5A2.5 2.5 0 0 0 2 21.5zM22 5.5A2.5 2.5 0 0 0 19.5 3H14v16h5.5a2.5 2.5 0 0 1 2.5 2.5z" /></svg>
                                AttorneyAI
                            </span>
                            </span>

                            {/* Right controls */}
                            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                                {/* Voice: dictates into the box; the lawyer still reads and sends. */}
                                <VoiceButton onText={setQuery} />


                                {/* Send button */}
                                <button onClick={send} aria-label="Send" className={`ai-send${query.trim() ? " on" : ""}`}>
                                    <svg width={17} height={17} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M12 19V5M5 12l7-7 7 7" /></svg>
                                </button>
                            </div>
                        </div>
                    </div>
                    <p className="disc">Answers cite Pakistani statutes and reported judgments. Check the cited text before relying on it in court.</p>
                </div>
            </div>

            {/* ── SOURCES ── one answer's citations; opened from a chip. */}
            {srcPanel && (
                <aside className="ai-sources" aria-label="Sources">
                    <div className="src-h">
                        <h3>Sources <span className="n">{srcPanel.list.length}</span></h3>
                        <button type="button" className="ai-icon" aria-label="Hide sources" title="Close" onClick={() => setSrcPanel(null)}>
                            <svg width={16} height={16} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" aria-hidden="true"><path d="M18 6 6 18M6 6l12 12" /></svg>
                        </button>
                    </div>
                    <div className="src-list">
                        {srcPanel.list.map((c, i) => {
                            const dead = c.currency === REPEALED;
                            const where = [c.province, c.source].filter(Boolean).join(" · ");
                            const status = CITATION_GROUPS.find(g => g.key === (c.status || "retrieved"));
                            return (
                                <div key={i} className={`src${srcPanel.focus === c ? " hl" : ""}`}
                                    ref={el => { if (el && srcPanel.focus === c) el.scrollIntoView({ block: "nearest" }); }}>
                                    <div className="top">
                                        <span className="num">{i + 1}</span>
                                        <span className="kind">{c.judgment ? "Judgment" : "Statute"}</span>
                                        {dead && <span className="dead">Repealed</span>}
                                    </div>
                                    <b>{c.label}</b>
                                    {status && <p>{status.lawyer}</p>}
                                    {dead && repealNote(c) && <p className="dead-note">{repealNote(c)}</p>}
                                    {where && <p className="where">{where}</p>}
                                    <div className="src-acts">
                                        {c.href && (
                                            <a href={c.href} target="_blank" rel="noopener noreferrer">Court PDF ↗</a>
                                        )}
                                        {!c.href && c.sourceUrl && (
                                            <SourceChip citation={c} text="Open document" style={{ background: "none", border: 0, padding: 0, color: "var(--mint)", fontSize: 12, fontWeight: 600 }} title={where} />
                                        )}
                                        {setPage && (
                                            <button type="button" onClick={() => openInLibrary(c)}>Open in Legal library →</button>
                                        )}
                                    </div>
                                </div>
                            );
                        })}
                    </div>
                </aside>
            )}
        </div>
    );
}
export { AILegalPage };
