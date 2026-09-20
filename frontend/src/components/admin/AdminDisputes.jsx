'use client';
import { useCallback, useEffect, useState } from 'react';

import { listOpenDisputes, resolveDispute } from '@/lib/api.js';

/** The support queue for appointment reports.
 *
 * WHAT A DECISION HERE DOES. `correct_to_completed` changes a real
 * appointment's status, which restores the client's right to review their
 * lawyer — `exists_completed` gates it. That is the only place in the product
 * where anyone may make that correction, and it is deliberately a person's
 * decision rather than a rule: a client who could correct their own record by
 * asserting it could manufacture the eligibility the review system exists to
 * protect.
 *
 * PRIVATE NOTES ARE STRUCTURALLY SEPARATE, not merely styled differently. The
 * client sees the public explanation and never the note; keeping the two in
 * one box invites an officer to write the wrong thing in the wrong field, and
 * the wrong thing here is a private assessment of a lawyer delivered to the
 * client who complained about them.
 *
 * A 409 RELOADS. Two officers working the same queue will sometimes decide one
 * report at the same moment. The loser must see the decision that actually
 * landed — pretending theirs succeeded would tell them they resolved something
 * somebody else resolved differently.
 */
const DECISIONS = [
    { id: 'correct_to_completed',
      label: 'Correct to completed',
      hint: 'Changes the appointment and restores the review right.' },
    { id: 'confirm_no_show',
      label: 'Confirm the record stands',
      hint: 'Leaves the appointment exactly as it is.' },
    { id: 'dismiss_report',
      label: 'Dismiss the report',
      hint: 'Leaves the appointment exactly as it is.' },
];

const PAGE_SIZE = 25;

export function AppointmentDisputes({ T }) {
    const t = T || {};
    const [state, setState] = useState('loading');   // loading | ready | error
    const [items, setItems] = useState([]);
    const [total, setTotal] = useState(0);
    const [pages, setPages] = useState(1);
    const [page, setPage] = useState(1);
    const [busyId, setBusyId] = useState(null);
    const [notice, setNotice] = useState('');

    const load = useCallback(async (which = 1) => {
        setState('loading');
        const { data, error } = await listOpenDisputes({
            page: which, page_size: PAGE_SIZE,
        });
        if (error || !data) {
            // NOT an empty queue. `apiFetch` resolves on failure, so an
            // unchecked result would tell support there is nothing to review
            // when in fact nobody managed to ask.
            setState('error');
            return;
        }
        setItems(data.items || []);
        setTotal(data.total || 0);
        setPages(data.pages || 1);
        setPage(data.page || which);
        setState('ready');
    }, []);

    useEffect(() => { load(1); }, [load]);

    const decide = async (dispute, decision, explanation, supportNote) => {
        if (!explanation.trim()) {
            setNotice('A public explanation is required — the client reads it.');
            return;
        }
        setBusyId(dispute.id);
        setNotice('');
        const { error, status } = await resolveDispute(dispute.id, {
            expected_version: dispute.version,
            decision,
            resolution_explanation: explanation.trim(),
            support_note: supportNote.trim() || null,
        });
        setBusyId(null);
        if (error) {
            if (status === 409) {
                setNotice('Someone else decided this report while you were '
                          + 'working on it. Reloading the queue.');
                await load(page);
                return;
            }
            setNotice(error.message || 'The decision could not be saved.');
            return;
        }
        await load(page);
    };

    if (state === 'loading') {
        return <div style={{ padding: 20, fontSize: 13 }}>Loading reports…</div>;
    }
    if (state === 'error') {
        return (
            <div style={{ padding: 20 }}>
                <div role="alert" style={{ fontSize: 13, marginBottom: 10 }}>
                    The report queue could not be loaded. That is not the same
                    as having none — the request failed.
                </div>
                <button type="button" onClick={() => load(page)} style={btn(t)}>
                    Retry
                </button>
            </div>
        );
    }

    return (
        <div style={{ padding: 20 }}>
            <h2 style={{ fontSize: 18, fontWeight: 700, marginBottom: 4 }}>
                Appointment reports
            </h2>
            <div style={{ fontSize: 12, opacity: 0.75, marginBottom: 14 }}>
                {total} open {total === 1 ? 'report' : 'reports'} · page {page} of {pages}
            </div>

            {notice && (
                <div role="status" style={{
                    fontSize: 12, marginBottom: 12, padding: '8px 10px',
                    borderRadius: 8, border: '1px solid rgba(232,82,106,0.4)',
                }}>{notice}</div>
            )}

            {items.length === 0 && (
                <div style={{ fontSize: 13, opacity: 0.8 }}>
                    No reports are waiting for a decision.
                </div>
            )}

            {items.map(dispute => (
                <DisputeCard key={dispute.id} dispute={dispute} t={t}
                    busy={busyId === dispute.id} onDecide={decide} />
            ))}

            {pages > 1 && (
                <div style={{ display: 'flex', gap: 8, marginTop: 14 }}>
                    <button type="button" disabled={page <= 1}
                        onClick={() => load(page - 1)} style={btn(t)}>Previous</button>
                    <button type="button" disabled={page >= pages}
                        onClick={() => load(page + 1)} style={btn(t)}>Next</button>
                </div>
            )}
        </div>
    );
}

function DisputeCard({ dispute, t, busy, onDecide }) {
    const [decision, setDecision] = useState('');
    const [explanation, setExplanation] = useState('');
    const [note, setNote] = useState('');

    return (
        <div style={{
            border: '1px solid rgba(255,255,255,0.12)', borderRadius: 12,
            padding: 16, marginBottom: 12,
        }}>
            <div style={{ fontSize: 12, opacity: 0.75 }}>
                Appointment {dispute.appointment_id} · report {dispute.id}
            </div>
            <div style={{ fontSize: 13, fontWeight: 700, marginTop: 4 }}>
                {dispute.category === 'incorrect_no_show'
                    ? 'Client disputes a no-show'
                    : 'Consultation finished with no outcome recorded'}
            </div>

            <div style={{ marginTop: 10 }}>
                <div style={{ fontSize: 11, textTransform: 'uppercase', opacity: 0.7 }}>
                    What the client said
                </div>
                <div style={{ fontSize: 13, marginTop: 4, whiteSpace: 'pre-wrap' }}>
                    {dispute.statement}
                </div>
            </div>

            <fieldset style={{ border: 'none', padding: 0, margin: '14px 0 0' }}>
                <legend style={{ fontSize: 12, fontWeight: 700, padding: 0 }}>
                    Decision
                </legend>
                {DECISIONS.map(option => (
                    <label key={option.id} style={{ display: 'block', fontSize: 12, marginTop: 6 }}>
                        <input type="radio" name={`decision-${dispute.id}`}
                            value={option.id}
                            checked={decision === option.id}
                            onChange={() => setDecision(option.id)}
                            style={{ marginRight: 8 }} />
                        {option.label}
                        <span style={{ opacity: 0.65 }}> — {option.hint}</span>
                    </label>
                ))}
            </fieldset>

            <label style={{ display: 'block', fontSize: 12, marginTop: 12 }}>
                <span style={{ fontWeight: 700 }}>Explanation for the client</span>
                <span style={{ opacity: 0.7 }}> — they will read this.</span>
                <textarea value={explanation} rows={3} maxLength={2000}
                    aria-label="Explanation for the client"
                    onChange={e => setExplanation(e.target.value)}
                    style={field(t)} />
            </label>

            {/* STRUCTURALLY SEPARATE, in its own bordered block with its own
                heading. Nothing written here reaches the client or the
                lawyer. */}
            <div style={{
                marginTop: 12, padding: 10, borderRadius: 8,
                border: '1px dashed rgba(255,255,255,0.25)',
            }}>
                <label style={{ display: 'block', fontSize: 12 }}>
                    <span style={{ fontWeight: 700 }}>Private support note</span>
                    <span style={{ opacity: 0.7 }}> — internal only. Never shown
                        to the client or the lawyer.</span>
                    <textarea value={note} rows={2} maxLength={2000}
                        aria-label="Private support note"
                        onChange={e => setNote(e.target.value)}
                        style={field(t)} />
                </label>
            </div>

            <button type="button"
                disabled={busy || !decision}
                aria-busy={busy || undefined}
                onClick={() => onDecide(dispute, decision, explanation, note)}
                style={{ ...btn(t), marginTop: 12 }}>
                {busy ? 'Saving…' : 'Save decision'}
            </button>
        </div>
    );
}

function btn() {
    return {
        minHeight: 40, padding: '9px 16px', borderRadius: 9,
        border: '1px solid rgba(255,255,255,0.25)', background: 'transparent',
        color: 'inherit', fontSize: 12, fontWeight: 700, cursor: 'pointer',
        fontFamily: 'inherit',
    };
}

function field() {
    return {
        display: 'block', width: '100%', boxSizing: 'border-box', marginTop: 6,
        padding: '8px 10px', borderRadius: 8,
        border: '1px solid rgba(255,255,255,0.2)', background: 'transparent',
        color: 'inherit', fontSize: 12, fontFamily: 'inherit', resize: 'vertical',
    };
}
