'use client';
/* The processing receipt of one analysis (owner-only API, ANALYZER_PROCESSING_RECEIPT.md).
 *
 * Shows what the server RECORDED about each AI step: whether it was a
 * simulated (offline demo) or live provider, each attempt and its outcome,
 * the request fingerprint, provider/model, masking version, how many
 * sentences were sent, and whether the receipt's hash chain is intact.
 *
 * Never shown (and never in the API): prompts, document text, personal
 * values, the encrypted map, credentials, storage paths, model output.
 * A fingerprint is an integrity identifier for the exact request recorded
 * before it was sent -- not proof that a provider deleted anything, and a
 * recorded attempt is not proof of delivery. */
import React, { useState } from "react";
import { Btn, Card } from "@/components/client/documents/ui.jsx";
import { getProcessingReceipt } from "@/lib/api.js";

export const STAGE_TEXT = { ai_report: "AI drafting notes", hypothesis_review: "Drafting-question review" };
export const OUTCOME_TEXT = {
    complete: "Completed",
    partial: "Completed (some items removed by validation)",
    failed: "Failed",
    in_progress: "In progress",
    delivery_or_outcome_unknown: "Delivery/outcome unknown",
};

const short = sha => (sha ? `${sha.slice(0, 16)}…` : "—");

export function receiptMode(receipt) {
    const attempts = (receipt?.entries || []).filter(e => e.kind === "ai_attempt");
    if (attempts.length === 0) return "none";
    return attempts.every(e => e.provider === "simulated") ? "simulated" : "live";
}

export default function ProcessingReceipt({ t, runId }) {
    const [receipt, setReceipt] = useState(null);
    const [issue, setIssue] = useState(null);
    const [busy, setBusy] = useState(false);

    const load = async () => {
        setBusy(true);
        const r = await getProcessingReceipt(runId);
        setBusy(false);
        if (r.error) { setIssue(r.error.message || "The processing receipt could not be loaded."); return; }
        setIssue(null);
        setReceipt(r.data);
    };

    if (!receipt) {
        return (
            <Card data-receipt="closed" style={{ padding: 12, display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
                <b style={{ fontSize: 13.5 }}>Processing receipt</b>
                <span style={{ fontSize: 12.5, color: t.textMuted }}>What the server recorded about each AI step.</span>
                <Btn data-receipt-open disabled={busy} onClick={load}>{busy ? "Loading…" : "Show the receipt"}</Btn>
                {issue && <div role="alert" style={{ fontSize: 13 }}>{issue}</div>}
            </Card>
        );
    }

    const mode = receiptMode(receipt);
    const entries = receipt.entries || [];
    const attemptBySeq = Object.fromEntries(entries.filter(e => e.kind === "ai_attempt").map(e => [e.seq, e]));
    const chain = receipt.chain || {};
    return (
        <Card data-receipt="open" data-receipt-mode={mode} style={{ padding: 14, display: "flex", flexDirection: "column", gap: 10 }}>
            <div style={{ fontWeight: 800, fontSize: 14 }}>Processing receipt</div>
            {mode === "simulated" && (
                <div role="note" data-receipt-simulated style={{ fontSize: 13, fontWeight: 700 }}>
                    Demo mode — simulated provider. No external AI service was called; an offline simulation
                    answered the approved request.
                </div>
            )}
            {mode === "live" && (
                <div role="note" data-receipt-live style={{ fontSize: 13 }}>Live provider.</div>
            )}
            <div data-receipt-chain={chain.intact ? "intact" : "broken"} style={{ fontSize: 13 }}>
                {chain.intact
                    ? `Integrity check passed: ${chain.entries} entries, hash chain intact.`
                    : `Integrity check FAILED (${chain.reason || "chain_broken"}). Do not rely on this receipt.`}
            </div>
            {(receipt.attempts || []).length === 0 && (
                <div data-receipt-no-attempt style={{ fontSize: 13 }}>No request was sent for this analysis.</div>
            )}
            {(receipt.attempts || []).map(a => {
                const e = attemptBySeq[a.attempt_seq] || {};
                return (
                    <div key={`${a.stage}-${a.attempt_seq}`} data-receipt-attempt={a.status}
                        style={{ border: `1px solid ${t.border}`, borderRadius: 8, padding: 10, fontSize: 13 }}>
                        <div><b>{STAGE_TEXT[a.stage] || a.stage}</b> — {OUTCOME_TEXT[a.status] || a.status}</div>
                        {a.label && <div data-receipt-unknown style={{ color: t.textMuted }}>{a.label}</div>}
                        <div data-receipt-fingerprint>Request fingerprint: <code>{short(a.request_sha256)}</code></div>
                        <div data-receipt-provider>
                            {e.provider === "simulated" ? "Simulated provider" : "Provider"}: {e.provider || "—"} · model {e.model || "—"}
                        </div>
                        <div>Masking: {e.masking?.masking_version || "—"} · sentences sent: {e.sent?.sentence_count ?? "—"}</div>
                    </div>
                );
            })}
            {entries.filter(e => e.kind === "not_sent").map(e => (
                <div key={`ns-${e.seq}`} data-receipt-not-sent style={{ fontSize: 12.5, color: t.textMuted }}>
                    {STAGE_TEXT[e.stage] || e.stage}: not sent ({e.reason || "no reason recorded"}).
                </div>
            ))}
            <div style={{ fontSize: 12, color: t.textMuted }}>
                A request fingerprint identifies the exact request recorded before it was sent. It is an integrity
                identifier — not proof that a provider deleted anything, and a recorded attempt is not proof of delivery.
                {" "}{receipt.notice}
            </div>
        </Card>
    );
}
