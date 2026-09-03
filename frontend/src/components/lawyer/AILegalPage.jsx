'use client';
// Lawyer AI Legal Page — paste your code here
import { useState, useEffect, useRef, useCallback } from "react";
import { useTheme } from "./theme.js";
import { useCase } from "./theme.js";
import { Icon, I } from "./icons.jsx";
import {
    listCases, aiResearch, cancelResearchTurn, researchTurnStatus, rateAnswer, aiProvenance, openSourceDocument,
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
                           error: error?.detail || "Audit record not available" });
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
function AILegalPage() {
    const { t } = useTheme();
    const { activeCase } = useCase();
    const { user } = useAuth();
    const firstName = user?.full_name?.split(" ")[0] || "Counselor";
    const [apiCases, setApiCases] = useState([]);
    const [msgs, setMsgs] = useState([]);

    useEffect(() => {
        listCases({ page_size: 50 }).then(({ data }) => {
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
        });
    }, []);

    const activeCaseObj = apiCases.find(c => c.id === activeCase) || null;
    const [query, setQuery] = useState("");
    const [loading, setLoading] = useState(false);
    const [sideOpen, setSideOpen] = useState(true);
    const [lang, setLang] = useState("EN");
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
    const firstCaseRender = useRef(true);
    useEffect(() => {
        if (firstCaseRender.current) { firstCaseRender.current = false; return; }
        setQuery("");
        startConversation(activeCaseObj ? (activeCaseObj._id || null) : null);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [activeCase]);

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
        setListCursor(data.next_cursor || null);
        setListMore(!!data.has_more);
    }, [activeCaseObj, showArchived, listGeneration]);

    const refreshHistory = useCallback(
        () => loadHistory({ term: search || null }), [loadHistory, search]);

    const loadMoreHistory = useCallback(
        () => loadHistory({ after: listCursor, term: search || null }),
        [loadHistory, listCursor, search]);

    useEffect(() => {
        const timer = setTimeout(
            () => { loadHistory({ term: search || null }); }, 250);
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
        const { data, error } = await getResearchConversation(
            id, { beforeSeq: olderCursor, pageSize: THREAD_PAGE_SIZE });
        if (!openGeneration.isCurrent(ticket)) return;
        setLoadingOlder(false);
        if (error || !data) return;

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

    const openConversation = useCallback(async (id) => {
        if (!id) return;
        const ticket = openGeneration.next();
        const thread = await loadThread(id, ticket);
        if (!openGeneration.isCurrent(ticket)) return;   // the user moved on
        if (!thread) {
            writeActiveSession("research", user?._id, null);
            setMsgs([]);
            setPendingQuestion(null);
            return;
        }
        const { header, messages: restored } = thread;
        setOlderCursor(thread.olderCursor);
        setHasOlder(thread.hasOlder);
        sessionIdRef.current = id;
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
    }, [user?._id, recoverPending, loadThread, openGeneration]);


    const startConversation = useCallback(async (caseId) => {
        const { data, error } = await createResearchConversation({ caseId: caseId || null });
        if (error || !data?.session_id) return null;
        sessionIdRef.current = data.session_id;
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
    useEffect(() => {
        let live = true;
        (async () => {
            // No user yet: the bootstrap re-runs when the account resolves.
            if (!user?._id) return;
            const remembered = readActiveSession("research", user._id);
            if (remembered) {
                await openConversation(remembered);
                if (live) refreshHistory();
                return;
            }
            await startConversation(null);
            if (live) refreshHistory();
        })();
        return () => { live = false; };
        // Re-runs on an ACCOUNT CHANGE only: a new user must not inherit the
        // previous one's open thread.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [user?._id]);

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
        if (!sid) {
            sid = await startConversation(activeCaseObj ? (activeCaseObj._id || null) : null);
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
            if (error || !data) throw new Error(error?.detail || "request failed");

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
                : { content: "AI service unavailable. Please try again." });
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

    return (
        <div style={{ display: "flex", flex: 1, overflow: "hidden", borderRadius: 0, border: "none", background: t.card, boxShadow: "none" }}>

            {/* ── SIDEBAR ── */}
            <div style={{
                width: sideOpen ? 200 : 0, minWidth: sideOpen ? 200 : 0, flexShrink: 0, overflow: "hidden",
                transition: "width .3s cubic-bezier(.4,0,.2,1),min-width .3s cubic-bezier(.4,0,.2,1)",
                background: t.surface, borderRight: `1px solid ${t.border}`, display: "flex", flexDirection: "column"
            }}>

                {/* New Chat button */}
                <div style={{ padding: "14px 12px 10px" }}>
                    <button
                        onClick={() => startConversation(
                            activeCaseObj ? (activeCaseObj._id || null) : null)}
                        title={activeCaseObj
                            ? `Start a new thread for ${activeCaseObj.id}`
                            : "Start a new general research thread"}
                        style={{
                        width: "100%", padding: "9px 14px", borderRadius: 50,
                        background: t.primary, color: t.mode === "dark" ? "#111B1F" : "#fff",
                        border: "none", fontSize: 13, fontWeight: 700, cursor: "pointer",
                        display: "flex", alignItems: "center", justifyContent: "center", gap: 7,
                        boxShadow: `0 4px 14px ${t.primaryGlow}`, transition: "opacity .2s", whiteSpace: "nowrap"
                    }}
                        onMouseEnter={e => e.currentTarget.style.opacity = ".85"}
                        onMouseLeave={e => e.currentTarget.style.opacity = "1"}>
                        <svg width={14} height={14} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><circle cx="12" cy="12" r="10" /><line x1="12" y1="8" x2="12" y2="16" /><line x1="8" y1="12" x2="16" y2="12" /></svg>
                        New Chat
                    </button>
                </div>

                {/* History header */}
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "4px 14px 4px" }}>
                    <span style={{ fontSize: 13, fontWeight: 700, color: t.text }}>
                        {activeCaseObj ? "Case research" : "General research"}
                    </span>
                    <div style={{ display: "flex", gap: 4, alignItems: "center" }}>
                        <button
                            onClick={() => startConversation(activeCaseObj ? (activeCaseObj._id || null) : null)}
                            title={activeCaseObj
                                ? `New research thread for ${activeCaseObj.id}`
                                : "New general research thread"}
                            style={{ background: "none", border: `1px solid ${t.border}`, cursor: "pointer", padding: "2px 7px", borderRadius: 7, color: t.textMuted, fontSize: 11 }}>
                            + New
                        </button>
                        <button
                            onClick={() => setShowArchived(v => !v)}
                            title={showArchived ? "Hide archived threads" : "Show archived threads"}
                            style={{ background: showArchived ? t.cardHi : "none", border: `1px solid ${t.border}`, cursor: "pointer", padding: "2px 7px", borderRadius: 7, color: t.textMuted, fontSize: 11 }}>
                            🗄
                        </button>
                    </div>
                </div>

                {/* Search. Matches the thread title and the question that
                    named it — not message bodies, which live in another
                    collection. A search covering some of a thread's text but
                    not the rest would be worse than one whose scope is
                    obvious. */}
                <div style={{ padding: "0 12px 6px" }}>
                    <input
                        value={search}
                        onChange={e => setSearch(e.target.value)}
                        placeholder="Search research"
                        aria-label="Search research conversations"
                        style={{
                            width: "100%", padding: "6px 10px", fontSize: 12,
                            borderRadius: 8, background: t.card,
                            border: `1px solid ${t.border}`, color: t.text,
                            outline: "none",
                        }} />
                </div>

                {/* History list */}
                <div style={{ flex: 1, overflowY: "auto", padding: "4px 8px 8px" }}>
                    {history.map((g, gi) => (
                        <div key={gi} style={{ marginBottom: 12 }}>
                            <div style={{
                                fontSize: 10, fontWeight: 700, color: t.textMuted, padding: "5px 6px 3px",
                                textTransform: "uppercase", letterSpacing: "0.07em", display: "flex", alignItems: "center", gap: 4
                            }}>
                                <svg width={9} height={9} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="6 9 12 15 18 9" /></svg>
                                {g.group}
                            </div>
                            {/* Real conversations. Clicking one reopens it with its
                                messages and any question it was waiting on. */}
                            {g.items.map((item) => {
                                const active = item.session_id === sessionId;
                                return (
                                    <div key={item.session_id}
                                        onClick={() => openConversation(item.session_id)}
                                        title={item.title}
                                        style={{
                                            padding: "7px 9px", borderRadius: 9, fontSize: 12,
                                            color: active ? t.text : t.textMuted, cursor: "pointer",
                                            marginBottom: 2, transition: "all .15s",
                                            background: active ? t.cardHi : "transparent",
                                            display: "flex", alignItems: "center", gap: 5,
                                        }}
                                        onMouseEnter={e => { e.currentTarget.style.background = t.cardHi; }}
                                        onMouseLeave={e => { e.currentTarget.style.background = active ? t.cardHi : "transparent"; }}>
                                        {/* A thread that stopped on a question, not an answer. */}
                                        {item.awaiting_clarification && (
                                            <span title="Waiting on your answer" style={{ color: "#f59e0b", fontSize: 10 }}>?</span>
                                        )}
                                        <span style={{ flex: 1, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                                            {item.title}
                                        </span>
                                        <button title="Rename" onClick={(e) => {
                                            e.stopPropagation();
                                            const next = window.prompt("Rename this research thread", item.title);
                                            if (next && next.trim()) {
                                                renameResearchConversation(item.session_id, next.trim())
                                                    .then(refreshHistory);
                                            }
                                        }} style={{ border: "none", background: "transparent", cursor: "pointer", color: t.textFaint, fontSize: 11, padding: "0 1px" }}>✎</button>
                                        {/* Archive keeps the thread and its messages and
                                            drops it out of the default list — closing a
                                            file rather than shredding it. */}
                                        <button title={item.archived ? "Unarchive" : "Archive"} onClick={(e) => {
                                            e.stopPropagation();
                                            archiveResearchConversation(item.session_id, !item.archived)
                                                .then(refreshHistory);
                                        }} style={{ border: "none", background: "transparent", cursor: "pointer", color: t.textFaint, fontSize: 11, padding: "0 1px" }}>
                                            {item.archived ? "↩" : "🗄"}
                                        </button>
                                        <button title="Delete" onClick={(e) => {
                                            e.stopPropagation();
                                            if (!window.confirm("Delete this thread and its messages?")) return;
                                            deleteResearchConversation(item.session_id).then(async () => {
                                                if (item.session_id === sessionIdRef.current) {
                                                    writeActiveSession("research", user?._id, null);
                                                    await startConversation(activeCaseObj ? (activeCaseObj._id || null) : null);
                                                }
                                                refreshHistory();
                                            });
                                        }} style={{ border: "none", background: "transparent", cursor: "pointer", color: t.textFaint, fontSize: 11, padding: "0 1px" }}>🗑</button>
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
                        <div style={{
                            padding: "10px 6px", fontSize: 11.5, color: t.textFaint,
                        }}>
                            {search ? "No threads match that search."
                                    : "No research threads yet."}
                        </div>
                    )}
                </div>

                {/* Sidebar footer */}
                <div style={{ padding: "8px 12px 12px", borderTop: `1px solid ${t.border}` }}>
                    <button onClick={() => setSideOpen(false)} style={{
                        width: "100%", padding: "8px", borderRadius: 9, fontSize: 12,
                        background: "transparent", border: `1px solid ${t.border}`, color: t.textMuted, cursor: "pointer",
                        display: "flex", alignItems: "center", justifyContent: "center", gap: 5, transition: "all .2s"
                    }}
                        onMouseEnter={e => { e.currentTarget.style.borderColor = t.primary; e.currentTarget.style.color = t.primary; }}
                        onMouseLeave={e => { e.currentTarget.style.borderColor = t.border; e.currentTarget.style.color = t.textMuted; }}>
                        <svg width={12} height={12} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M15 18l-6-6 6-6" /></svg>
                        Collapse
                    </button>
                </div>
            </div>

            {/* ── MAIN CHAT AREA ── */}
            <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden", position: "relative" }}>

                {/* Floating top bar */}
                <div style={{
                    position: "absolute", top: 0, left: 0, right: 0, zIndex: 10,
                    display: "flex", alignItems: "center", justifyContent: "space-between",
                    padding: "14px 20px 0", pointerEvents: "none"
                }}>
                    {/* Left: expand btn + Chat label */}
                    <div style={{ display: "flex", alignItems: "center", gap: 10, pointerEvents: "auto" }}>
                        {!sideOpen && (
                            <button onClick={() => setSideOpen(true)} style={{
                                width: 34, height: 34, borderRadius: "50%",
                                background: t.primary, border: "none", display: "flex", alignItems: "center", justifyContent: "center",
                                cursor: "pointer", boxShadow: `0 4px 14px ${t.primaryGlow}`, transition: "opacity .2s"
                            }}
                                onMouseEnter={e => e.currentTarget.style.opacity = ".85"}
                                onMouseLeave={e => e.currentTarget.style.opacity = "1"}>
                                <svg width={14} height={14} viewBox="0 0 24 24" fill="none" stroke={t.mode === "dark" ? "#111B1F" : "#fff"} strokeWidth="2.5"><path d="M9 18l6-6-6-6" /></svg>
                            </button>
                        )}
                        <span className="serif" style={{ fontSize: 17, fontWeight: 700, color: t.text }}>Chat</span>
                    </div>
                    {/* Right: Upgrade Plan pill */}
                    <button style={{
                        background: t.primary, color: t.mode === "dark" ? "#111B1F" : "#fff",
                        border: "none", borderRadius: 50, padding: "9px 20px", fontSize: 12, fontWeight: 700,
                        cursor: "pointer", boxShadow: `0 4px 14px ${t.primaryGlow}`, transition: "opacity .2s",
                        pointerEvents: "auto"
                    }}
                        onMouseEnter={e => e.currentTarget.style.opacity = ".85"}
                        onMouseLeave={e => e.currentTarget.style.opacity = "1"}>
                        Upgrade Plan
                    </button>
                </div>

                {/* Messages / Welcome */}
                <div style={{
                    flex: 1, overflowY: "auto",
                    display: "flex", flexDirection: "column", alignItems: "center",
                    justifyContent: hasMessages ? "flex-start" : "center",
                    padding: hasMessages ? "68px 24px 16px" : "0 24px"
                }}>

                    {!hasMessages ? (
                        /* Welcome screen */
                        <div style={{ textAlign: "center", maxWidth: 640, width: "100%", padding: "0 16px" }}>
                            <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 14, marginBottom: 16 }}>
                                <span style={{ fontSize: 42 }}>{greetEmoji}</span>
                                <h2 className="serif" style={{ fontSize: 26, fontWeight: 700, color: t.text, margin: 0 }}>{greetWord}, {firstName}!</h2>
                            </div>
                            {/* Active case context pill */}
                            {activeCaseObj && (
                                <div style={{
                                    display: "inline-flex", alignItems: "center", gap: 8, padding: "8px 16px", borderRadius: 50,
                                    background: t.primaryGlow, border: `1px solid ${t.primary}40`, marginBottom: 16
                                }}>
                                    <div style={{ width: 7, height: 7, borderRadius: "50%", background: t.primary }} />
                                    <span style={{ fontSize: 12, color: t.primary, fontWeight: 600 }}>Context: {activeCaseObj.id} — {activeCaseObj.title}</span>
                                </div>
                            )}
                            <p className="serif" style={{ fontSize: activeCaseObj ? 22 : 30, fontWeight: 700, color: t.text, marginBottom: 32, lineHeight: 1.35 }}>{greetSub}</p>
                            {/* Quick prompt chips — case-aware when active */}
                            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", justifyContent: "center" }}>
                                {(activeCaseObj ? [
                                    `What sections apply to ${activeCaseObj.type} cases in Pakistan?`,
                                    `Key arguments for ${activeCaseObj.title}`,
                                    `Documents needed for next hearing at ${activeCaseObj.court}`,
                                    `Recent precedents for ${activeCaseObj.type} law`
                                ] : [
                                    "Relevant sections for property dispute",
                                    "PPC sections for cheque bounce",
                                    "Bail conditions under CrPC 1898",
                                    "Contempt of court procedure in Pakistan"
                                ]).map((p, i) => (
                                    <button key={i} onClick={() => setQuery(p)} style={{
                                        padding: "9px 16px", borderRadius: 50,
                                        border: `1px solid ${t.border}`, background: t.cardHi, color: t.textMuted, cursor: "pointer",
                                        fontSize: 12, fontWeight: 500, transition: "all .15s", textAlign: "left"
                                    }}
                                        onMouseEnter={e => { e.currentTarget.style.borderColor = t.primary; e.currentTarget.style.color = t.primary; e.currentTarget.style.background = t.primaryGlow2; }}
                                        onMouseLeave={e => { e.currentTarget.style.borderColor = t.border; e.currentTarget.style.color = t.textMuted; e.currentTarget.style.background = t.cardHi; }}>
                                        {p}
                                    </button>
                                ))}
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
                                                                        if (c.href) {
                                                                            return <a key={ci} href={c.href} target="_blank" rel="noopener noreferrer" style={chipStyle} title={`${title}${title ? " · " : ""}opens the judgment`}>{text} ↗</a>;
                                                                        }
                                                                        if (c.sourceUrl) {
                                                                            return <SourceChip key={ci} citation={c} text={text} style={chipStyle} title={title} />;
                                                                        }
                                                                        return <span key={ci} style={chipStyle} title={title}>{text}</span>;
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
                                                        <span style={{ display: "inline-flex", gap: 3 }}>
                                                            {["up", "down"].map(r => (
                                                                <button key={r}
                                                                    onClick={() => {
                                                                        setMsgs(prev => prev.map((x, xi) => xi === i ? { ...x, rated: r } : x));
                                                                        rateAnswer({
                                                                            session_id: sessionIdRef.current,
                                                                            rating: r,
                                                                            answer_preview: (m.content || "").slice(0, 300),
                                                                            question_preview: (msgs[i - 1]?.content || "").slice(0, 300),
                                                                            source: "research",
                                                                        }).catch(() => {});
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
                <div style={{ padding: "0 24px 18px", display: "flex", flexDirection: "column", alignItems: "center", flexShrink: 0 }}>
                    <div style={{
                        width: "100%", maxWidth: 800,
                        background: t.mode === "dark" ? "rgba(20,42,50,0.97)" : t.surface,
                        border: `1.5px solid ${t.border}`, borderRadius: 18,
                        padding: "13px 15px 11px 18px", boxShadow: t.shadowCard
                    }}>

                        {/* Text input */}
                        <input value={query} onChange={e => setQuery(e.target.value)}
                            onKeyDown={e => e.key === "Enter" && !e.shiftKey && send()}
                            placeholder="Ask Attorney AI..."
                            style={{
                                width: "100%", background: "transparent", border: "none", outline: "none",
                                color: t.text, fontSize: 14, padding: "3px 0 10px", lineHeight: 1.6
                            }} />

                        {/* Toolbar row */}
                        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                            {/* Search globe button */}
                            <button style={{
                                display: "flex", alignItems: "center", gap: 6,
                                background: t.inputBg, border: `1px solid ${t.border}`, borderRadius: 50,
                                padding: "6px 14px", fontSize: 12, color: t.textMuted, cursor: "pointer", transition: "all .15s"
                            }}
                                onMouseEnter={e => { e.currentTarget.style.borderColor = t.primary; e.currentTarget.style.color = t.primary; }}
                                onMouseLeave={e => { e.currentTarget.style.borderColor = t.border; e.currentTarget.style.color = t.textMuted; }}>
                                <svg width={13} height={13} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                                    <circle cx="12" cy="12" r="10" /><path d="M2 12h20" /><ellipse cx="12" cy="12" rx="4" ry="10" />
                                </svg>
                                Search
                            </button>

                            {/* Right controls */}
                            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                                {/* Clock / history */}
                                <button style={{ background: "none", border: "none", cursor: "pointer", padding: 6, borderRadius: 8, color: t.textMuted, display: "flex", transition: "all .15s" }}
                                    onMouseEnter={e => { e.currentTarget.style.background = t.cardHi; e.currentTarget.style.color = t.primary; }}
                                    onMouseLeave={e => { e.currentTarget.style.background = "none"; e.currentTarget.style.color = t.textMuted; }}>
                                    <Icon d={I.clock} size={16} />
                                </button>

                                {/* Pro badge */}
                                <span style={{ fontSize: 11, fontWeight: 700, color: t.textMuted, background: t.inputBg, border: `1px solid ${t.border}`, borderRadius: 6, padding: "3px 9px" }}>Pro</span>

                                {/* EN / UR language toggle */}
                                <div style={{ display: "flex", borderRadius: 8, overflow: "hidden", border: `1px solid ${t.border}`, background: t.inputBg }}>
                                    {["EN", "UR"].map(l => (
                                        <button key={l} onClick={() => setLang(l)}
                                            style={{
                                                padding: "4px 11px", fontSize: 11, fontWeight: 700, border: "none", cursor: "pointer",
                                                background: lang === l ? t.primary : "transparent",
                                                color: lang === l ? (t.mode === "dark" ? "#111B1F" : "#fff") : t.textMuted,
                                                transition: "all .15s"
                                            }}>
                                            {l}
                                        </button>
                                    ))}
                                </div>

                                {/* Mic */}
                                <button style={{ background: "none", border: "none", cursor: "pointer", padding: 6, borderRadius: 8, color: t.textMuted, display: "flex", transition: "all .15s" }}
                                    onMouseEnter={e => { e.currentTarget.style.background = t.cardHi; e.currentTarget.style.color = t.primary; }}
                                    onMouseLeave={e => { e.currentTarget.style.background = "none"; e.currentTarget.style.color = t.textMuted; }}>
                                    <svg width={16} height={16} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                                        <rect x="9" y="2" width="6" height="11" rx="3" /><path d="M19 10a7 7 0 01-14 0" /><line x1="12" y1="19" x2="12" y2="22" /><line x1="8" y1="22" x2="16" y2="22" />
                                    </svg>
                                </button>

                                {/* Send button */}
                                <button onClick={send} style={{
                                    width: 36, height: 36, borderRadius: 10,
                                    background: query.trim() ? t.primary : t.inputBg,
                                    border: `1.5px solid ${query.trim() ? t.primary : t.border}`,
                                    display: "flex", alignItems: "center", justifyContent: "center",
                                    cursor: query.trim() ? "pointer" : "default",
                                    transition: "all .2s", transform: "rotate(45deg)",
                                    boxShadow: query.trim() ? `0 4px 12px ${t.primaryGlow}` : "none"
                                }}>
                                    <Icon d={I.send} size={15} style={{ color: query.trim() ? (t.mode === "dark" ? "#111B1F" : "#fff") : t.textMuted }} />
                                </button>
                            </div>
                        </div>
                    </div>
                    <div style={{ marginTop: 7, fontSize: 11, color: t.textFaint, textAlign: "center" }}>
                        Authentic citations only. Verify applicability before use.
                    </div>
                </div>
            </div>
        </div>
    );
}
export { AILegalPage };
