'use client';
import React, { useState, Suspense } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { InputField } from '@/app/UIComponents';
import { AuthLayout } from '@/app/LayoutComponents';
import { Ic } from '@/app/Icons';
import { authForgotPassword, authResetPassword } from '@/lib/api.js';

import { DARK } from '@/components/admin/themes.js';

// This page previously called nothing at all. "Send Reset Link" ran setSub(1)
// and "Set New Password" ran setSub(2) — the buttons only advanced a wizard —
// and the final screen announced "Password updated! Your password has been
// successfully changed." while no request had been made and no password had
// changed. The backend endpoints and the api.js wrappers both already existed.
//
// The real flow has two halves that happen in different sessions: request a
// link by email, then follow that link back here with ?token=... . The old
// three-step wizard pretended both happened in one sitting, which is also why
// it never needed the token.

// Mirrors backend validate_password_strength: >= 8 chars, one digit, one
// uppercase. Checked here only to fail fast — the server is the authority.
const passwordProblem = (pw) => {
  if (pw.length < 8) return 'Use at least 8 characters.';
  if (!/[0-9]/.test(pw)) return 'Include at least one number.';
  if (!/[A-Z]/.test(pw)) return 'Include at least one uppercase letter.';
  return null;
};

const Notice = ({ t, tone = 'error', children }) => {
  const color = tone === 'error' ? t.danger : t.success;
  return (
    <div style={{
      padding: '10px 14px', borderRadius: t.r.md, marginBottom: 16,
      background: tone === 'error' ? 'rgba(233,86,86,.08)' : 'rgba(60,201,154,.07)',
      border: `1px solid ${color}40`, color, fontSize: 12.5, lineHeight: 1.55,
      fontWeight: 600,
    }}>
      {children}
    </div>
  );
};

const PrimaryBtn = ({ t, onClick, disabled, children }) => (
  <button className="aBtn" onClick={onClick} disabled={disabled} style={{
    flex: 2, padding: '11px 0', borderRadius: t.r.md, background: t.grad1, border: 'none',
    color: t.mode === 'dark' ? '#182B32' : '#fff', fontSize: 13, fontWeight: 700,
    display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 7,
    cursor: disabled ? 'not-allowed' : 'pointer', opacity: disabled ? 0.65 : 1,
    boxShadow: `0 4px 16px ${t.primaryGlow}`,
  }}>
    {children}
  </button>
);

const BackBtn = ({ t, onClick, label = 'Back' }) => (
  <button className="aBtn" onClick={onClick} style={{
    flex: 1, padding: '11px 0', borderRadius: t.r.md, background: 'transparent',
    border: `1.5px solid ${t.border}`, color: t.textDim, fontSize: 13, fontWeight: 600,
    display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 7, cursor: 'pointer',
  }}>
    {Ic.arrowL(t.textDim)} {label}
  </button>
);

function ForgotPw({ t, goBack }) {
  const params = useSearchParams();
  const token = params?.get('token') || '';

  // With a token in the URL the user has followed the emailed link, so they
  // start at the "set a new password" step. Without one they start by asking
  // for the link.
  const [stage, setStage] = useState(token ? 'reset' : 'request');
  const [email, setEmail] = useState('');
  const [pw, setPw] = useState('');
  const [confirm, setConfirm] = useState('');
  const [spw, setSPW] = useState(false);
  const [scf, setSCF] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const sendLink = async () => {
    setError(null);
    if (!email.trim()) { setError('Enter the email you registered with.'); return; }
    setBusy(true);
    const { error: err } = await authForgotPassword(email.trim());
    setBusy(false);
    if (err) { setError(err.message || 'Could not send the reset link. Please try again.'); return; }
    setStage('sent');
  };

  const submitNewPassword = async () => {
    setError(null);
    const problem = passwordProblem(pw);
    if (problem) { setError(problem); return; }
    if (pw !== confirm) { setError('The two passwords do not match.'); return; }
    setBusy(true);
    const { error: err } = await authResetPassword(token, pw);
    setBusy(false);
    if (err) {
      // Covers an expired or already-used token, which is the common failure
      // and needs to send the user back to the start rather than retry here.
      setError(err.message || 'Could not reset the password. The link may have expired.');
      return;
    }
    setStage('done');
  };

  // ── request a link ─────────────────────────────────────────────────────────
  if (stage === 'request') return (
    <AuthLayout t={t} fullCard={true}>
      <div style={{ animation: 'scaleUp .35s ease both' }}>
        <button onClick={goBack} className="aBtn" style={{ display: 'flex', alignItems: 'center', gap: 7, background: 'none', border: 'none', cursor: 'pointer', color: t.textMuted, fontSize: 13, fontWeight: 500, marginBottom: 22, padding: 0 }}>
          {Ic.arrowL(t.textFaint)} Back to login
        </button>
        <div style={{ textAlign: 'center', marginBottom: 22 }}>
          <div style={{ width: 60, height: 60, borderRadius: '50%', margin: '0 auto 14px', background: t.primaryGlow2, border: `2px solid ${t.primary}40`, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>{Ic.shield(t.primary)}</div>
          <h1 style={{ fontFamily: "'Cormorant Garamond',serif", fontSize: 26, fontWeight: 700, color: t.text, marginBottom: 5 }}>Reset your password</h1>
          <p style={{ color: t.textMuted, fontSize: 13, lineHeight: 1.6 }}>Enter your registered email and we&apos;ll send you a secure reset link.</p>
        </div>
        {error && <Notice t={t}>{error}</Notice>}
        <InputField label="Registered Email" type="email" placeholder="you@lawfirm.com" t={t} d={0}
          icon={Ic.mail(t.textFaint)} value={email} onChange={e => setEmail(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') sendLink(); }} autoComplete="email" />
        <div style={{ display: 'flex', gap: 10, marginTop: 14 }}>
          <BackBtn t={t} onClick={goBack} />
          <PrimaryBtn t={t} onClick={sendLink} disabled={busy}>
            {busy ? 'Sending…' : 'Send Reset Link'} {!busy && Ic.arrowR(t.mode === 'dark' ? '#182B32' : '#fff')}
          </PrimaryBtn>
        </div>
      </div>
    </AuthLayout>
  );

  // ── link sent ──────────────────────────────────────────────────────────────
  if (stage === 'sent') return (
    <AuthLayout t={t} fullCard={true}>
      <div style={{ textAlign: 'center', animation: 'scaleUp .4s ease both', padding: '16px 0' }}>
        <div style={{ width: 76, height: 76, borderRadius: '50%', margin: '0 auto 20px', background: 'rgba(60,201,154,.1)', border: `2.5px solid ${t.success}`, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          {Ic.mail(t.success)}
        </div>
        <h2 style={{ fontFamily: "'Cormorant Garamond',serif", fontSize: 26, fontWeight: 700, color: t.text, marginBottom: 8 }}>Check your email</h2>
        {/* Deliberately does not confirm whether the address is registered —
            the endpoint answers the same either way so it cannot be used to
            discover who has an account. */}
        <p style={{ color: t.textMuted, fontSize: 13, lineHeight: 1.7, marginBottom: 24 }}>
          If <strong style={{ color: t.text }}>{email}</strong> belongs to an account, a reset link is on its way.<br />
          Open the link on this device to choose a new password. It expires in one hour.
        </p>
        <div style={{ display: 'flex', gap: 10 }}>
          <BackBtn t={t} onClick={() => setStage('request')} label="Use another email" />
          <PrimaryBtn t={t} onClick={goBack}>Return to Sign In</PrimaryBtn>
        </div>
      </div>
    </AuthLayout>
  );

  // ── set a new password (reached via the emailed link) ──────────────────────
  if (stage === 'reset') return (
    <AuthLayout t={t} fullCard={true}>
      <div style={{ animation: 'scaleUp .35s ease both' }}>
        <h2 style={{ fontFamily: "'Cormorant Garamond',serif", fontSize: 24, fontWeight: 700, color: t.text, marginBottom: 4 }}>Set new password</h2>
        <p style={{ color: t.textMuted, fontSize: 13, marginBottom: 16 }}>
          At least 8 characters, with a number and a capital letter.
        </p>
        {error && <Notice t={t}>{error}</Notice>}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <InputField label="New Password" type={spw ? 'text' : 'password'} placeholder="Min. 8 characters" t={t} d={.06}
            icon={Ic.lock(t.textFaint)} value={pw} onChange={e => setPw(e.target.value)} autoComplete="new-password"
            right={<button onClick={() => setSPW(p => !p)} style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 0, color: t.textFaint, display: 'flex' }}>{spw ? Ic.eyeOff(t.textFaint) : Ic.eye(t.textFaint)}</button>} />
          <InputField label="Confirm New Password" type={scf ? 'text' : 'password'} placeholder="Re-enter password" t={t} d={.11}
            icon={Ic.lock(t.textFaint)} value={confirm} onChange={e => setConfirm(e.target.value)} autoComplete="new-password"
            onKeyDown={e => { if (e.key === 'Enter') submitNewPassword(); }}
            right={<button onClick={() => setSCF(p => !p)} style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 0, color: t.textFaint, display: 'flex' }}>{scf ? Ic.eyeOff(t.textFaint) : Ic.eye(t.textFaint)}</button>} />
        </div>
        <div style={{ display: 'flex', gap: 10, marginTop: 14 }}>
          <BackBtn t={t} onClick={goBack} label="Cancel" />
          <PrimaryBtn t={t} onClick={submitNewPassword} disabled={busy}>
            {busy ? 'Saving…' : 'Set New Password'} {!busy && Ic.arrowR(t.mode === 'dark' ? '#182B32' : '#fff')}
          </PrimaryBtn>
        </div>
      </div>
    </AuthLayout>
  );

  // ── done ───────────────────────────────────────────────────────────────────
  return (
    <AuthLayout t={t} fullCard={true}>
      <div style={{ textAlign: 'center', animation: 'scaleUp .4s ease both', padding: '16px 0' }}>
        <div style={{ position: 'relative', width: 76, height: 76, margin: '0 auto 20px' }}>
          <div style={{ position: 'absolute', inset: -10, borderRadius: '50%', background: 'rgba(60,201,154,.08)', animation: 'pulse 2s infinite' }} />
          <div style={{ width: 76, height: 76, borderRadius: '50%', background: 'rgba(60,201,154,.1)', border: `2.5px solid ${t.success}`, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <svg width="30" height="30" viewBox="0 0 24 24" fill="none" stroke={t.success} strokeWidth="2"><path d="M20 12v6a2 2 0 01-2 2H6a2 2 0 01-2-2V6a2 2 0 012-2h9" /><path d="M9 12l2 2 8-8" strokeLinecap="round" strokeLinejoin="round" /></svg>
          </div>
        </div>
        {/* Only reachable after /auth/reset-password returned success. */}
        <h2 style={{ fontFamily: "'Cormorant Garamond',serif", fontSize: 26, fontWeight: 700, color: t.text, marginBottom: 8 }}>Password updated</h2>
        <p style={{ color: t.textMuted, fontSize: 13, lineHeight: 1.7, marginBottom: 24 }}>Your password has been changed and every other session has been signed out.<br />You can now sign in with your new credentials.</p>
        <button className="aBtn" onClick={goBack} style={{ width: '100%', padding: '12px 0', borderRadius: t.r.md, background: t.grad1, border: 'none', color: t.mode === 'dark' ? '#182B32' : '#fff', fontSize: 13.5, fontWeight: 700, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 7, cursor: 'pointer', boxShadow: `0 4px 16px ${t.primaryGlow}` }}>
          Return to Sign In {Ic.arrowR(t.mode === 'dark' ? '#182B32' : '#fff')}
        </button>
      </div>
    </AuthLayout>
  );
}

export default function ResetPasswordPage() {
  const router = useRouter();
  // useSearchParams needs a Suspense boundary during static prerender.
  return (
    <Suspense fallback={null}>
      <ForgotPw t={DARK} goBack={() => router.push('/login')} />
    </Suspense>
  );
}
