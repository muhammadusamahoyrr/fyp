'use client';
/* THE INVITED SIGNER'S PAGE, and the only screen in the app that works with no
 * account at all.
 *
 * It lives OUTSIDE `(client)`/`(lawyer)` on purpose: those groups are wrapped in
 * ProtectedRoute, and the whole point of an invitation is that the person
 * holding it has nowhere to log in to. The token in the query string is the
 * entire authority to sign one slot, so it is read once, kept in memory, and
 * sent in the request BODY — never appended to another URL, never stored.
 *
 * What this page must not do is imply the signer's identity was checked. We can
 * show a link was created for an address; we cannot show who opened it, and the
 * copy here says so in both the header and the consent line. */
import React, { Suspense, useEffect, useRef, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import { DARK } from '@/components/shared/themes.js';
import { viewAgreementByInvitation, signAgreementByInvitation } from '@/lib/api.js';
import SignaturePad from '@/components/shared/SignaturePad.jsx';

const t = DARK;

/* `borderColor` is resolved into the shorthand rather than spread alongside it.
 * Mixing the two spellings is what made the shared Card warn in the console --
 * see the note there. Nothing on this page animates its border, so it would not
 * warn today; it is written this way so it cannot start. */
const Card = ({ children, style = {} }) => {
  const { border, borderColor, ...rest } = style;
  return (
    <div style={{
      background: t.card,
      border: border ?? `1px solid ${borderColor ?? t.border}`,
      borderRadius: 16,
      padding: '20px 22px', boxShadow: t.shadowCard, ...rest,
    }}>{children}</div>
  );
};

const Field = ({ label, children }) => (
  <div style={{ marginBottom: 14 }}>
    <div style={{
      fontSize: 10.5, fontWeight: 700, color: t.textMuted, letterSpacing: '0.7px',
      textTransform: 'uppercase', marginBottom: 6,
    }}>{label}</div>
    {children}
  </div>
);

const Shell = ({ children }) => (
  <div style={{ minHeight: '100vh', background: t.bg, padding: '32px 16px' }}>
    <div style={{ maxWidth: 780, margin: '0 auto' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 20 }}>
        <span style={{ fontSize: 22 }}>⚖️</span>
        <span style={{ fontSize: 16, fontWeight: 800, color: t.text }}>Attorney.AI</span>
      </div>
      {children}
    </div>
  </div>
);

const Notice = ({ tone = 'warn', children }) => (
  <Card style={{ background: t[tone] + '12', borderColor: t[tone] + '40' }}>
    <div style={{ fontSize: 13.5, color: t.text, lineHeight: 1.7 }}>{children}</div>
  </Card>
);

function InvitationSigner() {
  const params = useSearchParams();
  // Held in a ref, not state: it should never end up in a render key, a log
  // line or a dependency array that someone later serialises.
  const tokenRef = useRef(params.get('token') || '');

  const [state, setState] = useState({ loading: true, error: '', doc: null });
  // {method, data} from SignaturePad. This page offered a typed name only,
  // while the person who SENT the agreement could draw or upload. The
  // backend accepted all three on this path the whole time.
  const [sig, setSig] = useState({ method: 'canvas', data: '' });
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);

  useEffect(() => {
    if (!tokenRef.current) {
      setState({ loading: false, error: 'This link is missing its signing token. Ask the sender for a new one.', doc: null });
      return;
    }
    let live = true;
    viewAgreementByInvitation(tokenRef.current).then(({ data, error }) => {
      if (!live) return;
      setState({
        loading: false,
        error: error ? (error.message || error.detail || 'This link is no longer valid.') : '',
        doc: data || null,
      });

    });
    return () => { live = false; };
  }, []);

  const submit = async () => {
    if (!sig.data) return;
    setBusy(true);
    const { data, error } = await signAgreementByInvitation({
      token: tokenRef.current,
      method: sig.method,
      signature_data: sig.data,
      consent: true,
    });
    setBusy(false);
    if (error) {
      setState(s => ({ ...s, error: error.message || error.detail || 'Could not record your signature.' }));
      return;
    }
    setDone(true);
    setState(s => ({ ...s, doc: data || s.doc, error: '' }));
  };

  if (state.loading) {
    return <Shell><Card><div style={{ color: t.textMuted, fontSize: 13.5 }}>Opening the agreement…</div></Card></Shell>;
  }

  if (!state.doc) {
    return (
      <Shell>
        <Notice tone="danger">
          <strong style={{ display: 'block', marginBottom: 6 }}>This signing link cannot be opened</strong>
          {state.error || 'The link may have expired, been withdrawn, or already been used.'}
        </Notice>
      </Shell>
    );
  }

  const { doc } = state;
  const you = doc.you || {};
  const already = done || you.signed;

  return (
    <Shell>
      {already && (
        <Card style={{ background: t.success + '12', borderColor: t.success + '40', marginBottom: 16 }}>
          <div style={{ fontSize: 14, fontWeight: 700, color: t.success, marginBottom: 4 }}>✅ Your signature is recorded</div>
          <div style={{ fontSize: 12.5, color: t.textMuted, lineHeight: 1.7 }}>
            Nothing further is needed from you. The sender can see that you signed.
          </div>
        </Card>
      )}

      <Card style={{ marginBottom: 16 }}>
        <div style={{ fontSize: 17, fontWeight: 800, color: t.text, marginBottom: 6 }}>{doc.title || 'Agreement'}</div>
        <div style={{ fontSize: 12, color: t.textMuted, lineHeight: 1.7 }}>
          You were invited to sign this at <strong style={{ color: t.text }}>{you.email}</strong>.
          {/* SAID TO THE SIGNER, not only recorded. Whoever relies on this
              signature later should not be the first person to learn that we
              never checked who opened the link. */}
          {' '}We can show this link was created for that address — we do not verify who signs it.
        </div>
        {doc.expires_at && !already && (
          <div style={{ fontSize: 12, color: t.warn, marginTop: 8 }}>
            ⏰ This link stops working on {new Date(doc.expires_at).toLocaleDateString()}.
          </div>
        )}
      </Card>

      <Card style={{ marginBottom: 16, padding: 0, overflow: 'hidden' }}>
        <div style={{
          padding: '12px 20px', borderBottom: `1px solid ${t.border}`,
          background: t.surface, fontSize: 12.5, fontWeight: 700, color: t.textMuted,
        }}>The document</div>
        <div style={{
          padding: '20px 24px', fontSize: 13.5, lineHeight: 1.85, color: t.text,
          fontFamily: "Georgia, 'Times New Roman', serif", maxHeight: 420,
          overflowY: 'auto', whiteSpace: 'pre-wrap',
        }}>{doc.body_html || '(No content)'}</div>
      </Card>

      {Array.isArray(doc.parties) && doc.parties.length > 0 && (
        <Card style={{ marginBottom: 16 }}>
          <div style={{ fontSize: 12.5, fontWeight: 700, color: t.text, marginBottom: 10 }}>Who signs this</div>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            {doc.parties.map((p, i) => (
              <div key={i} style={{
                display: 'flex', alignItems: 'center', gap: 7, padding: '6px 11px',
                borderRadius: 10, background: p.signed ? t.success + '12' : t.inputBg,
                border: `1px solid ${p.signed ? t.success + '40' : t.border}`,
              }}>
                <span style={{ fontSize: 11 }}>{p.signed ? '✅' : '⏰'}</span>
                <span style={{ fontSize: 12, color: t.text }}>{p.full_name || 'Invited signer'}</span>
                <span style={{ fontSize: 10, color: p.signed ? t.success : t.textMuted }}>
                  {p.signed ? 'signed' : 'pending'}
                </span>
              </div>
            ))}
          </div>
        </Card>
      )}

      {!already && (
        <Card>
          <div style={{ fontSize: 14, fontWeight: 800, color: t.text, marginBottom: 14 }}>Sign</div>
          <Field label="Draw, type or upload your signature">
            <SignaturePad height={150} onChange={setSig} />
          </Field>

          <label style={{ display: 'flex', gap: 10, alignItems: 'flex-start', cursor: 'pointer', marginBottom: 16 }}>
            <input type="checkbox" checked={consent} onChange={e => setConsent(e.target.checked)}
              style={{ marginTop: 3, accentColor: t.primary, width: 16, height: 16 }} />
            <span style={{ fontSize: 12.5, color: t.textMuted, lineHeight: 1.7 }}>
              I have read this document and I intend the signature above to be my
              signature on it.
            </span>
          </label>

          {state.error && (
            <div style={{
              padding: '10px 13px', borderRadius: 10, marginBottom: 14,
              background: t.danger + '14', border: `1px solid ${t.danger}40`,
              fontSize: 12.5, color: t.danger,
            }}>{state.error}</div>
          )}

          <button disabled={busy || !consent || !sig.data} onClick={submit}
            style={{
              width: '100%', padding: '13px 20px', borderRadius: 12, border: 'none',
              background: (!consent || !sig.data) ? t.border : t.primary,
              color: (!consent || !sig.data) ? t.textMuted : '#1A2E35',
              fontSize: 14, fontWeight: 800,
              cursor: (busy || !consent || !sig.data) ? 'not-allowed' : 'pointer',
            }}>
            {busy ? 'Recording…' : 'Sign this agreement'}
          </button>

          <div style={{ fontSize: 11, color: t.textMuted, marginTop: 12, lineHeight: 1.7 }}>
            On submission we record your signature, the time, your IP address where
            it can be determined, and a hash of the document text.
            {' '}Signature encrypted at rest with AES-256-GCM.
          </div>
        </Card>
      )}
    </Shell>
  );
}

export default function SignPage() {
  // useSearchParams needs a Suspense boundary for the static export.
  return (
    <Suspense fallback={<Shell><Card><div style={{ color: t.textMuted, fontSize: 13.5 }}>Loading…</div></Card></Shell>}>
      <InvitationSigner />
    </Suspense>
  );
}
