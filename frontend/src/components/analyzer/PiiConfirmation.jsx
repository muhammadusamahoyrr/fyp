'use client';
/* The lawyer's review before anything is sent to the AI (lawyer-confirm mode).
 *
 * Nothing leaves the server until the owner lawyer has reviewed the EXACT
 * request. Detection can miss a name without flagging it, so the screen shows
 * every sent sentence twice -- the ORIGINAL beside the MASKED text that would
 * be sent -- and the lawyer:
 *   1. decides every flagged (highlighted) span;
 *   2. marks any MISSED name or address by selecting it in the original;
 *   3. reads the server's re-masked preview of the exact final request, with
 *      its hash and the automatic leak checks;
 *   4. attests that they reviewed exactly that request, and submits.
 *
 * The server rebuilds the request and refuses unless it equals the attested
 * one. A marked detail is masked like any other; its words are never sent.
 * The review is NOT a statement that all personal information was removed,
 * and NOT an accuracy approval (the server's notice says so). */
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Btn, Card } from "@/components/client/documents/ui.jsx";
import { confirmPii, getAnalysisText, getPiiConfirmation, idempotencyKey, previewPii } from "@/lib/api.js";

export const PII_REVIEW_REASONS = new Set(["pii_confirmation_required", "pii_review_required", "pii_review_outdated"]);
export const DECISION_LABEL = {
    personal_name: "Personal name",
    address: "Address",
    not_personal: "Not personal information",
    same_person: "Same person as…",
};
/* What a MISSED detail can be marked as (the server's `added_decisions`). */
export const MARK_LABEL = {
    personal_name: "Personal name",
    address: "Address",
    cnic: "ID number (CNIC)",
    phone: "Phone number",
    email: "Email",
    account: "Bank account",
};
const REASON_TEXT = {
    party_name_not_recognised: "Looks like a party's name",
    addressee_not_recognised: "Looks like the addressee's name",
    signer_not_recognised: "Looks like a signer's name",
    address_not_delimited: "Looks like part of an address",
    alias_unlinked: "A shorter form of a masked name",
    name_variant: "A different spelling of a masked name",
    ocr_unmasked: "Looks like a damaged or split name",
    unsupported_script: "Urdu or Arabic script cannot be sent",
};
const LEAK_TEXT = {
    arabic_script: "Urdu or Arabic script",
    email: "an email address",
    iban_shape: "an IBAN-like number",
    long_number: "a long number",
    signature_name: "a name next to a signature",
    title_or_kinship_name: "a name after a title or s/o, d/o, w/o",
};
const ERROR_TEXT = {
    confirmation_outdated: "The text or the masking rules changed. Review the document again.",
    state_changed: "This analysis changed. Reload and review again.",
    preview_changed: "The request changed since your preview. Review it again.",
    unresolved_candidates: "Decide every highlighted detail before continuing.",
    pii_leak_guard: "The final request still looks like it holds personal details. Mark them, then review again.",
    not_attested: "Confirm that you reviewed this exact request.",
    overlapping_spans: "Marked details must not overlap.",
    span_not_sent: "Mark only text that would be sent.",
};

function errorCode(error) {
    return error?.code || error?.detail?.code || null;
}

const spanId = (start, end) => `${start}-${end}`;

/* Character offset of a DOM position inside a sentence element. */
function offsetIn(el, node, offset) {
    const range = document.createRange();
    range.selectNodeContents(el);
    range.setEnd(node, offset);
    return range.toString().length;
}

function OriginalSentence({ t, text, sentence, flagged, added, focus, onFocus }) {
    const marks = useMemo(() => [
        ...flagged.filter(c => c.start >= sentence.start && c.end <= sentence.end).map(c => ({ ...c, type: "flagged" })),
        ...added.filter(c => c.start >= sentence.start && c.end <= sentence.end).map(c => ({ ...c, type: "added" })),
    ].sort((a, b) => a.start - b.start), [flagged, added, sentence]);
    const parts = [];
    let at = sentence.start;
    marks.forEach(m => {
        if (m.start < at) return;
        if (m.start > at) parts.push(<span key={`g${at}`}>{text.slice(at, m.start)}</span>);
        const id = spanId(m.start, m.end);
        parts.push(
            <mark key={id} data-pii-candidate={m.type === "flagged" ? id : undefined} data-pii-added={m.type === "added" ? id : undefined}
                tabIndex={0} role="button" aria-current={focus === id ? "true" : undefined}
                onClick={() => onFocus(id)}
                onKeyDown={e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onFocus(id); } }}
                style={{ background: m.type === "added" ? "#cfe8ff" : (focus === id ? "#f6d58a" : "#fbecc4"),
                         borderRadius: 3, cursor: "pointer" }}>
                {text.slice(m.start, m.end)}
            </mark>);
        at = m.end;
    });
    if (at < sentence.end) parts.push(<span key={`g${at}`}>{text.slice(at, sentence.end)}</span>);
    return <div data-pii-original={sentence.sentence_id} data-start={sentence.start}
        style={{ whiteSpace: "pre-wrap", fontSize: 13.5, lineHeight: 1.6 }}>{parts}</div>;
}

export default function PiiConfirmation({ t, runId, onQueued }) {
    const [view, setView] = useState(null);
    const [text, setText] = useState(null);
    const [issue, setIssue] = useState(null);
    const [flagged, setFlagged] = useState([]);          // every span masking flagged, kept once seen
    const [choices, setChoices] = useState({});          // flagged id -> {decision, target?}
    const [added, setAdded] = useState([]);              // missed details the lawyer marked
    const [preview, setPreview] = useState(null);
    const [previewKey, setPreviewKey] = useState(null);  // the decisions the preview was made for
    const [selection, setSelection] = useState(null);
    const [focus, setFocus] = useState(null);
    const [attested, setAttested] = useState(false);
    const [busy, setBusy] = useState(false);
    const [notice, setNotice] = useState(null);
    const [tick, setTick] = useState(0);
    const panes = useRef(null);

    useEffect(() => {
        let live = true;
        Promise.all([getPiiConfirmation(runId), getAnalysisText(runId)]).then(([v, tx]) => {
            if (!live) return;
            if (v.error) { setIssue(v.error.message || "The review could not be loaded."); return; }
            if (tx.error) { setIssue(tx.error.message || "The text could not be loaded."); return; }
            const data = v.data;
            setIssue(null);
            setView(data);
            setText(tx.data.text);
            setPreview(data);
            setFlagged(data.candidates);
            const made = data.decisions_made || [];
            const flaggedIds = new Set(data.candidates.map(c => c.id));
            setChoices(Object.fromEntries(made.filter(d => flaggedIds.has(spanId(d.start, d.end)))
                .map(d => [spanId(d.start, d.end), d])));
            setAdded(made.filter(d => !flaggedIds.has(spanId(d.start, d.end))));
            setPreviewKey(JSON.stringify(made));
            setAttested(false);
        });
        return () => { live = false; };
    }, [runId, tick]);

    const decisions = useMemo(() => [
        ...flagged.filter(c => choices[c.id]).map(c => ({ start: c.start, end: c.end, ...choices[c.id] })),
        ...added.map(a => ({ start: a.start, end: a.end, decision: a.decision,
                             ...(a.target_start !== undefined ? { target_start: a.target_start, target_end: a.target_end } : {}) })),
    ].sort((a, b) => a.start - b.start), [flagged, choices, added]);
    const key = JSON.stringify(decisions);
    const fresh = preview && previewKey === key;

    const refresh = useCallback(async () => {
        if (!view) return;
        setBusy(true);
        setNotice(null);
        const r = await previewPii(runId, { textSha256: view.text_sha256, policySha256: view.policy_sha256, decisions });
        setBusy(false);
        if (r.error) {
            const code = errorCode(r.error);
            if (code === "confirmation_outdated") setTick(n => n + 1);
            setNotice(ERROR_TEXT[code] || r.error.message || "The preview could not be made.");
            return;
        }
        setPreview(r.data);
        setPreviewKey(key);
        setAttested(false);
        setFlagged(prev => {
            const seen = new Set(prev.map(c => c.id));
            return [...prev, ...r.data.candidates.filter(c => !seen.has(c.id))];
        });
    }, [runId, view, decisions, key]);

    const readSelection = () => {
        const sel = window.getSelection?.();
        if (!sel || sel.isCollapsed || !panes.current) { setSelection(null); return; }
        const box = el => el?.nodeType === 1 ? el.closest?.("[data-pii-original]") : el?.parentElement?.closest?.("[data-pii-original]");
        const a = box(sel.anchorNode), b = box(sel.focusNode);
        if (!a || a !== b) { setSelection(null); return; }
        const base = Number(a.dataset.start);
        let s = base + offsetIn(a, sel.anchorNode, sel.anchorOffset);
        let e = base + offsetIn(a, sel.focusNode, sel.focusOffset);
        if (s > e) [s, e] = [e, s];
        while (s < e && /\s/.test(text[s])) s += 1;
        while (e > s && /\s/.test(text[e - 1])) e -= 1;
        setSelection(e > s ? { start: s, end: e } : null);
    };

    if (issue) return <Card role="alert" data-pii-confirmation-error style={{ padding: 12 }}>{issue}</Card>;
    if (!view || text === null || !preview) return <div style={{ color: t.textMuted }}>Loading the review…</div>;

    const names = (preview.tokens || []).filter(n => n.kind === "NAME");
    const remaining = preview.candidates || [];
    const masked = Object.fromEntries((preview.sentences || []).map(s => [s.sentence_id, s.masked]));
    const userMessage = (preview.request || []).filter(m => m.role !== "system").map(m => m.content).join("\n");
    const systemMessage = (preview.request || []).filter(m => m.role === "system").map(m => m.content).join("\n");
    const canSubmit = fresh && preview.ready && remaining.length === 0 && attested && !busy;

    const mark = decision => {
        if (!selection) return;
        if ([...added, ...flagged].some(c => c.start < selection.end && selection.start < c.end)) {
            setNotice(ERROR_TEXT.overlapping_spans);
            return;
        }
        setAdded(prev => [...prev, { ...selection, decision }]);
        setSelection(null);
        window.getSelection?.()?.removeAllRanges?.();
    };
    const choose = (id, decision, target) => {
        setChoices(prev => ({ ...prev, [id]: decision === "same_person"
            ? { decision, target_start: target?.start, target_end: target?.end }
            : { decision } }));
        setFocus(id);
    };

    const submit = async () => {
        setBusy(true);
        setNotice(null);
        const r = await confirmPii(runId, {
            textSha256: view.text_sha256, policySha256: view.policy_sha256, expectedStateVersion: view.state_version,
            decisions, previewSha256: preview.request_sha256, attested,
        }, idempotencyKey());
        setBusy(false);
        if (r.error) {
            const code = errorCode(r.error);
            if (code === "confirmation_outdated" || code === "state_changed") setTick(n => n + 1);
            setNotice(ERROR_TEXT[code] || r.error.message || "The review was not saved.");
            return;
        }
        onQueued?.();
    };

    return (
        <Card data-pii-confirmation={view.stage} style={{ padding: 14, display: "flex", flexDirection: "column", gap: 12 }}>
            <div style={{ fontWeight: 800, fontSize: 15 }}>Review what will be sent to the AI</div>
            <div style={{ fontSize: 13 }}>
                Nothing is sent until you approve the exact request. Compare each original sentence with its masked
                version, decide every highlighted detail, and select any name or address that was missed.
            </div>
            {view.previous_confirmation_outdated && (
                <div data-pii-outdated role="note" style={{ fontSize: 13 }}>
                    An earlier review was made against a different text or masking rule, so it no longer applies.
                </div>
            )}

            <div ref={panes} onMouseUp={readSelection} onKeyUp={readSelection} data-pii-panes
                data-lenis-prevent style={{ maxHeight: 420, overflowY: "auto", border: `1px solid ${t.border}`, borderRadius: 10 }}>
                <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) minmax(0,1fr)", gap: 0, fontSize: 12,
                    fontWeight: 700, color: t.textMuted, padding: "8px 12px", borderBottom: `1px solid ${t.border}` }}>
                    <div>Original</div><div>Would be sent</div>
                </div>
                {view.sentences.map(s => (
                    <div key={s.sentence_id} data-pii-pair={s.sentence_id} style={{ display: "grid",
                        gridTemplateColumns: "minmax(0,1fr) minmax(0,1fr)", gap: 12, padding: "8px 12px",
                        borderBottom: `1px solid ${t.border}` }}>
                        <OriginalSentence t={t} text={text} sentence={s} flagged={flagged} added={added}
                            focus={focus} onFocus={setFocus} />
                        <div data-pii-masked={s.sentence_id} style={{ whiteSpace: "pre-wrap", fontSize: 13.5, lineHeight: 1.6,
                            opacity: fresh ? 1 : 0.55 }}>{masked[s.sentence_id] ?? ""}</div>
                    </div>
                ))}
            </div>

            <div data-pii-marker style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", fontSize: 13 }}>
                <span>{selection ? <>Selected: <b>“{text.slice(selection.start, selection.end)}”</b>. Mark as:</>
                                 : "Select any missed personal detail in the original text to mark it."}</span>
                {(view.added_decisions || []).filter(d => MARK_LABEL[d]).map(d => (
                    <Btn key={d} data-pii-mark={d} disabled={!selection} onClick={() => mark(d)}>{MARK_LABEL[d]}</Btn>
                ))}
            </div>

            {flagged.length > 0 && (
                <ol data-pii-flagged style={{ margin: 0, paddingLeft: 18, display: "flex", flexDirection: "column", gap: 8 }}>
                    {flagged.map(c => {
                        const choice = choices[c.id];
                        return (
                            <li key={c.id} data-pii-row={c.id} aria-current={focus === c.id ? "true" : undefined}>
                                <div style={{ fontSize: 13.5 }}>
                                    <b>“{text.slice(c.start, c.end)}”</b>{" "}
                                    <span style={{ color: t.textMuted }}>({REASON_TEXT[c.reason] || c.reason})</span>
                                </div>
                                {c.kind === "SCRIPT" ? (
                                    <div data-pii-policy style={{ fontSize: 13 }}>
                                        This cannot be sent: Urdu and Arabic script are not supported yet.
                                    </div>
                                ) : (
                                    <div role="radiogroup" aria-label={`Decide “${text.slice(c.start, c.end)}”`}
                                        style={{ display: "flex", gap: 12, flexWrap: "wrap", fontSize: 13 }}>
                                        {view.decisions.map(d => (
                                            <label key={d} style={{ display: "inline-flex", gap: 4, alignItems: "center" }}>
                                                <input type="radio" name={`pii-${c.id}`} value={d} data-pii-decision={d}
                                                    checked={choice?.decision === d}
                                                    disabled={d === "same_person" && names.length === 0}
                                                    onChange={() => choose(c.id, d, d === "same_person" ? names.find(n => n.start !== c.start) : undefined)} />
                                                {DECISION_LABEL[d] || d}
                                            </label>
                                        ))}
                                        {choice?.decision === "same_person" && (
                                            <select data-pii-target value={`${choice.target_start}-${choice.target_end}`}
                                                onChange={e => { const n = names.find(x => spanId(x.start, x.end) === e.target.value);
                                                                 choose(c.id, "same_person", n); }}>
                                                {names.filter(n => n.start !== c.start).map(n => (
                                                    <option key={n.token} value={spanId(n.start, n.end)}>
                                                        {n.token} — {text.slice(n.start, n.end)}
                                                    </option>
                                                ))}
                                            </select>
                                        )}
                                    </div>
                                )}
                            </li>
                        );
                    })}
                </ol>
            )}

            {added.length > 0 && (
                <ul data-pii-added-list style={{ margin: 0, paddingLeft: 18, fontSize: 13 }}>
                    {added.map(a => (
                        <li key={spanId(a.start, a.end)}>
                            You marked <b>“{text.slice(a.start, a.end)}”</b> as {(MARK_LABEL[a.decision] || a.decision).toLowerCase()}{" "}
                            <Btn data-pii-unmark={spanId(a.start, a.end)}
                                onClick={() => setAdded(prev => prev.filter(x => x !== a))}>Remove</Btn>
                        </li>
                    ))}
                </ul>
            )}

            <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
                <Btn data-pii-preview disabled={busy || fresh} onClick={refresh}>Update the preview</Btn>
                {!fresh && <span role="status" style={{ fontSize: 12.5 }}>Your changes are not in the preview yet.</span>}
            </div>

            <div data-pii-request style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                <div style={{ fontWeight: 700, fontSize: 13.5 }}>The exact request</div>
                {remaining.length > 0 && (
                    <div role="note" data-pii-remaining style={{ fontSize: 13 }}>
                        {remaining.length} highlighted detail{remaining.length === 1 ? "" : "s"} still to decide.
                        The request is shown once nothing is uncertain.
                    </div>
                )}
                {preview.request_error && <div role="alert" style={{ fontSize: 13 }}>This request cannot be prepared ({preview.request_error}).</div>}
                {preview.request && (
                    <>
                        <pre data-pii-request-body data-lenis-prevent style={{ maxHeight: 260, overflow: "auto", margin: 0, padding: 10,
                            borderRadius: 8, border: `1px solid ${t.border}`, background: t.inputBg, whiteSpace: "pre-wrap",
                            fontSize: 12.5, opacity: fresh ? 1 : 0.55 }}>{userMessage}</pre>
                        <details style={{ fontSize: 12.5 }}>
                            <summary>Instructions sent with it</summary>
                            <pre style={{ whiteSpace: "pre-wrap", fontSize: 12 }}>{systemMessage}</pre>
                        </details>
                        <div data-pii-request-hash style={{ fontSize: 12, color: t.textMuted }}>
                            Request fingerprint: <code>{preview.request_sha256?.slice(0, 16)}…</code>
                        </div>
                    </>
                )}
                {preview.leak_guard?.length > 0 && (
                    <div role="alert" data-pii-leak style={{ fontSize: 13 }}>
                        The automatic check still sees {preview.leak_guard.map(c => LEAK_TEXT[c] || c).join(", ")} in
                        this request. Mark it in the original text; this request cannot be sent as it is.
                    </div>
                )}
            </div>

            <label style={{ display: "flex", gap: 8, alignItems: "flex-start", fontSize: 13 }}>
                <input type="checkbox" data-pii-attest checked={attested}
                    disabled={!fresh || !preview.ready} onChange={e => setAttested(e.target.checked)} />
                <span>{view.attestation}</span>
            </label>
            {notice && <div role="alert" data-pii-submit-error style={{ fontSize: 13 }}>{notice}</div>}
            <div data-pii-notice style={{ fontSize: 12.5, color: t.textMuted }}>{view.notice}</div>
            <div>
                <Btn kind="primary" data-pii-submit disabled={!canSubmit} onClick={submit}>Approve and send this request</Btn>
            </div>
        </Card>
    );
}
