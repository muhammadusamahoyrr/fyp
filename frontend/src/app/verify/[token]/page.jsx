'use client';
// PUBLIC point-of-use verification page. A counterparty holding a POA (buyer's
// lawyer, sub-registrar) opens the printed link/QR to confirm the POA's live
// status, exact authorised scope, and tamper-hash. No login — the token is the
// capability. Self-contained styling (renders outside the dashboard theme).
import React, { useEffect, useState } from 'react';
import { useParams } from 'next/navigation';
import { overseasVerifyToken } from '@/lib/api.js';

const STATUS = {
  active:  { label: 'ACTIVE',   color: '#0f9d6b', bg: '#e7f6ef', note: 'This Power of Attorney is currently in force.' },
  revoked: { label: 'REVOKED',  color: '#d64545', bg: '#fdecec', note: 'This Power of Attorney has been REVOKED and must not be acted upon.' },
  expired: { label: 'EXPIRED',  color: '#7a7f87', bg: '#eef0f2', note: 'This Power of Attorney has expired and is no longer valid.' },
};

const fmt = (d) => {
  if (!d) return null;
  try { return new Date(d).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' }); }
  catch { return String(d); }
};

const Row = ({ label, children }) => (
  <div style={{ display: 'grid', gridTemplateColumns: '132px 1fr', gap: 12, padding: '11px 0', borderTop: '1px solid #ececf0', fontSize: 14 }}>
    <div style={{ color: '#8a8f98', fontWeight: 600, fontSize: 12.5, letterSpacing: '.02em' }}>{label}</div>
    <div style={{ color: '#1c2430' }}>{children}</div>
  </div>
);

export default function VerifyPage() {
  const { token } = useParams();
  const [state, setState] = useState({ loading: true, data: null });

  useEffect(() => {
    (async () => {
      const { data } = await overseasVerifyToken(token);
      setState({ loading: false, data: data || { found: false, message: 'Verification failed.' } });
    })();
  }, [token]);

  const { loading, data } = state;
  const s = data && data.found ? (STATUS[data.status] || STATUS.expired) : null;

  return (
    <div style={{ minHeight: '100vh', background: '#f5f6f8', display: 'flex', flexDirection: 'column', alignItems: 'center', padding: '40px 18px', fontFamily: '-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif' }}>
      <div style={{ width: '100%', maxWidth: 560 }}>
        {/* Brand */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 9, marginBottom: 18 }}>
          <div style={{ width: 30, height: 30, borderRadius: 8, background: '#0ea5a4', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#fff', fontWeight: 800, fontSize: 15 }}>A</div>
          <div style={{ fontWeight: 800, fontSize: 17, color: '#1c2430' }}>Attorney<span style={{ color: '#0ea5a4' }}>.AI</span></div>
          <div style={{ marginLeft: 'auto', fontSize: 11.5, color: '#8a8f98', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '.06em' }}>POA Verification</div>
        </div>

        <div style={{ background: '#fff', borderRadius: 16, boxShadow: '0 1px 3px rgba(16,24,40,.06), 0 8px 28px rgba(16,24,40,.06)', overflow: 'hidden' }}>
          {loading && <div style={{ padding: 40, textAlign: 'center', color: '#8a8f98', fontSize: 14 }}>Checking…</div>}

          {!loading && data && !data.found && (
            <div style={{ padding: 34, textAlign: 'center' }}>
              <div style={{ fontSize: 40, marginBottom: 8 }}>🔍</div>
              <div style={{ fontSize: 16, fontWeight: 700, color: '#1c2430', marginBottom: 6 }}>Not found</div>
              <div style={{ fontSize: 13.5, color: '#8a8f98', maxWidth: 360, margin: '0 auto' }}>{data.message || 'No Power of Attorney matches this verification code.'}</div>
            </div>
          )}

          {!loading && data && data.found && (
            <>
              {/* Status banner */}
              <div style={{ background: s.bg, padding: '20px 24px', display: 'flex', alignItems: 'center', gap: 14 }}>
                <div style={{ width: 12, height: 12, borderRadius: '50%', background: s.color, flexShrink: 0, boxShadow: `0 0 0 4px ${s.color}22` }} />
                <div>
                  <div style={{ fontSize: 20, fontWeight: 800, color: s.color, letterSpacing: '.02em' }}>{s.label}</div>
                  <div style={{ fontSize: 13, color: '#4a515c', marginTop: 2 }}>{s.note}</div>
                </div>
              </div>

              <div style={{ padding: '8px 24px 22px' }}>
                <Row label="Type">{data.poa_type === 'special' ? 'Special Power of Attorney' : 'General Power of Attorney'}</Row>
                <Row label="Principal">{data.principal_name || '—'}</Row>
                <Row label="Attorney">{data.attorney_name || '—'}{data.attorney_relation ? ` (${data.attorney_relation})` : ''}</Row>
                {data.subject && <Row label="Authorised for">{data.subject}</Row>}
                {Array.isArray(data.powers) && data.powers.length > 0 && (
                  <Row label="Powers">
                    <ul style={{ margin: 0, paddingLeft: 16 }}>
                      {data.powers.map((p, i) => <li key={i} style={{ marginBottom: 3, lineHeight: 1.4 }}>{p}</li>)}
                    </ul>
                  </Row>
                )}
                <Row label="Issued">{data.issue_date || '—'}</Row>
                {data.expiry_date && <Row label="Expires">{fmt(data.expiry_date)}</Row>}
                {data.revoked_at && <Row label="Revoked on">{fmt(data.revoked_at)}</Row>}
                {data.document_sha256 && (
                  <Row label="Document hash">
                    <span style={{ fontFamily: 'ui-monospace,Menlo,Consolas,monospace', fontSize: 11.5, color: '#4a515c', wordBreak: 'break-all' }}>{data.document_sha256}</span>
                    <div style={{ fontSize: 11, color: '#8a8f98', marginTop: 3 }}>Compare against the original document to detect tampering.</div>
                  </Row>
                )}
              </div>

              {data.verified_note && (
                <div style={{ padding: '14px 24px', borderTop: '1px solid #ececf0', fontSize: 12, color: '#8a8f98', lineHeight: 1.5 }}>{data.verified_note}</div>
              )}
            </>
          )}
        </div>

        <div style={{ textAlign: 'center', fontSize: 11.5, color: '#a4a9b2', marginTop: 16 }}>
          This confirms the Power of Attorney recorded with Attorney.AI and its current status. Always also inspect the original stamped / attested document.
        </div>
      </div>
    </div>
  );
}
