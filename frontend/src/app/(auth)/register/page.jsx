'use client';
import React, { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { DARK, LIGHT } from '@/components/shared/themes.js';
import { ONBOARDED_KEY } from '@/components/lawyer/OnboardingPage.jsx';
import { authRegister, authLogin } from '@/lib/api.js';
import { useAuth } from '@/context/AuthContext';

/* ─── SVG helpers ─────────────────────────────────────────────── */
const Svg = ({ size = 16, color, strokeWidth = 1.8, fill = 'none', children }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill={fill} stroke={color}
    strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round"
    style={{ display: 'inline-block', flexShrink: 0 }}>
    {children}
  </svg>
);
const IcEye     = ({ s, c }) => <Svg size={s} color={c}><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></Svg>;
const IcEyeOff  = ({ s, c }) => <Svg size={s} color={c}><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94"/><path d="M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19"/><line x1="1" y1="1" x2="23" y2="23"/></Svg>;
const IcUser    = ({ s, c }) => <Svg size={s} color={c}><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></Svg>;
const IcMail    = ({ s, c }) => <Svg size={s} color={c}><rect x="2" y="4" width="20" height="16" rx="2"/><path d="M22 7l-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 7"/></Svg>;
const IcPhone   = ({ s, c }) => <Svg size={s} color={c}><path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07A19.5 19.5 0 0 1 4.69 12a19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 3.6 1.27h3a2 2 0 0 1 2 1.72c.127.96.361 1.903.7 2.81a2 2 0 0 1-.45 2.11L7.91 8.82a16 16 0 0 0 5.89 5.89l1.87-1.87a2 2 0 0 1 2.11-.45c.907.339 1.85.573 2.81.7A2 2 0 0 1 22 16.92z"/></Svg>;
const IcLock    = ({ s, c }) => <Svg size={s} color={c}><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></Svg>;
const IcCert    = ({ s, c }) => <Svg size={s} color={c}><circle cx="12" cy="8" r="6"/><path d="M15.477 12.89L17 22l-5-3-5 3 1.523-9.11"/></Svg>;
const IcCheck   = ({ s, c }) => <Svg size={s} color={c} strokeWidth={2.5}><polyline points="20,6 9,17 4,12"/></Svg>;
const IcArrow   = ({ s, c }) => <Svg size={s} color={c} strokeWidth={2.2}><line x1="5" y1="12" x2="19" y2="12"/><polyline points="12,5 19,12 12,19"/></Svg>;
const IcScale   = ({ s, c }) => <Svg size={s} color={c}><path d="M12 2v20M3 6l9-4 9 4M4 10l8 4 8-4M4 18l8 4 8-4"/></Svg>;

/* ─── Mesh background ─────────────────────────────────────────── */
function MeshBg() {
  const nodes = [
    [80,80],[220,140],[400,60],[520,190],[170,270],
    [310,320],[460,300],[60,390],[270,430],[500,410],
    [370,185],[145,200],[440,105],[560,320],[35,210],
    [620,150],[680,380],[720,80],[750,260],[600,450],
  ];
  const edges = [
    [0,1],[0,14],[1,2],[1,4],[1,11],[2,12],[2,3],[3,6],[3,10],
    [4,5],[4,11],[5,6],[5,8],[6,9],[7,8],[8,9],[10,3],[10,5],
    [10,12],[11,4],[12,3],[13,6],[13,9],[14,4],[15,2],[15,12],
    [16,9],[16,13],[17,15],[18,16],[18,13],[19,16],
  ];
  return (
    <svg style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', opacity: 0.12 }}
      viewBox="0 0 800 500" preserveAspectRatio="xMidYMid slice" aria-hidden>
      {edges.map(([a, b], i) => (
        <line key={i} x1={nodes[a][0]} y1={nodes[a][1]} x2={nodes[b][0]} y2={nodes[b][1]}
          stroke={DARK.primary} strokeWidth="0.8" />
      ))}
      {nodes.map(([x, y], i) => (
        <circle key={i} cx={x} cy={y} r={i % 3 === 0 ? 3 : 2}
          fill={DARK.primary} opacity={i % 3 === 0 ? 0.85 : 0.45} />
      ))}
    </svg>
  );
}

/* ─── Small input field ───────────────────────────────────────── */
function Field({ label, children }) {
  return (
    <div>
      <label style={{ display: 'block', fontSize: 11, fontWeight: 600, color: LIGHT.textDim, marginBottom: 3 }}>
        {label}
      </label>
      {children}
    </div>
  );
}

function Input({ type = 'text', placeholder, value, onChange, icon, right }) {
  const L = LIGHT;
  return (
    <div className="rg-field" style={{
      background: L.inputBg, border: '1.5px solid transparent',
      borderRadius: L.r.md, padding: '7px 10px',
      display: 'flex', alignItems: 'center', gap: 7,
      transition: 'border-color .2s, box-shadow .2s',
    }}>
      {icon && icon}
      <input type={type} placeholder={placeholder} value={value} onChange={onChange}
        className="rg-input"
        style={{ flex: 1, background: 'none', border: 'none', outline: 'none', fontSize: 12.5, color: L.text, fontFamily: 'inherit' }} />
      {right && right}
    </div>
  );
}

/* ─── Main page ───────────────────────────────────────────────── */
export default function RegisterPage() {
  const router = useRouter();
  const { login, user, loading: authLoading } = useAuth();
  const D = DARK;
  const L = LIGHT;

  const [role,      setRole]      = useState('client');
  const [firstName, setFirstName] = useState('');
  const [lastName,  setLastName]  = useState('');
  const [email,     setEmail]     = useState('');
  const [phone,     setPhone]     = useState('');
  const [cnic,      setCnic]      = useState('');
  const [password,  setPassword]  = useState('');
  const [showPw,    setShowPw]    = useState(false);
  const [terms,     setTerms]     = useState(false);
  const [loading,   setLoading]   = useState(false);
  const [apiError,  setApiError]  = useState('');

  // Redirect already-authenticated users (only after auth hydration finishes)
  useEffect(() => {
    if (!authLoading && user) {
      router.replace(user.role === 'lawyer' ? '/lawyer' : user.role === 'admin' ? '/admin' : '/dashboard');
    }
  }, [authLoading, user]);

  const strength = password.length === 0 ? 0
    : password.length < 8 ? 1
    : (password.length >= 12 && /[A-Z]/.test(password) && /[0-9]/.test(password)) ? 3 : 2;
  const sColors = [D.border, D.danger, D.warn, D.success];
  const sLabels = ['', 'Weak — use 8+ characters', 'Good — add numbers', 'Strong ✓'];

  async function handleCreate() {
    if (!firstName || !email || !password) { setApiError('First name, email and password are required.'); return; }
    if (!terms) { setApiError('Please accept the Terms and Conditions.'); return; }
    setLoading(true);
    setApiError('');
    const { error: regError } = await authRegister({
      full_name: `${firstName} ${lastName}`.trim(),
      email,
      password,
      role: role === 'lawyer' ? 'lawyer' : 'client',
      phone: phone || null,
    });
    if (regError) {
      setLoading(false);
      setApiError(regError.detail || regError.message || 'Registration failed. Please try again.');
      return;
    }
    // Auto-login after successful registration
    const { data: tokenData, error: loginError } = await authLogin(email, password);
    setLoading(false);
    if (loginError) {
      // Registration succeeded but login failed — send to login page
      router.push('/login');
      return;
    }
    if (role === 'lawyer') { try { localStorage.removeItem(ONBOARDED_KEY); } catch {} }
    login(tokenData);
    router.push(tokenData.role === 'lawyer' ? '/lawyer' : '/dashboard');
  }

  const isLawyer = role === 'lawyer';

  return (
    <>
      <style>{`
        *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
        html, body { height: 100%; overflow: hidden; }
        .rg-btn  { transition: opacity .18s, transform .18s; cursor: pointer; }
        .rg-btn:hover  { opacity: .88; transform: translateY(-1px); }
        .rg-field:focus-within { border-color: ${D.primary} !important; box-shadow: 0 0 0 3px ${D.primaryGlow2} !important; }
        .rg-input { outline: none; }
        .role-pill { transition: background .2s, color .2s; }
        .chk { accent-color: ${L.primary}; width: 14px; height: 14px; cursor: pointer; flex-shrink: 0; margin-top: 1px; }
        .rg-card::-webkit-scrollbar { display: none; }
        .rg-card { scrollbar-width: none; -ms-overflow-style: none; }
      `}</style>

      {/* ── Full dark background ─────────────────────────────── */}
      <div style={{
        height: '100vh', width: '100vw', overflow: 'hidden',
        background: `linear-gradient(140deg, ${D.bg} 0%, #162E38 55%, #0E2028 100%)`,
        fontFamily: "'Inter', sans-serif",
        position: 'relative',
      }}>
        <MeshBg />

        {/* Glow orbs */}
        <div style={{ position: 'absolute', width: 600, height: 600, borderRadius: '50%', background: `radial-gradient(circle, ${D.primaryGlow2} 0%, transparent 65%)`, top: -160, left: -100, pointerEvents: 'none' }} />
        <div style={{ position: 'absolute', width: 400, height: 400, borderRadius: '50%', background: 'radial-gradient(circle, rgba(64,240,220,0.06) 0%, transparent 65%)', bottom: -80, right: 340, pointerEvents: 'none' }} />

        {/* ── LEFT — hero ────────────────────────────────────── */}
        <div style={{
          position: 'absolute',
          left: 64, top: '50%', transform: 'translateY(-50%)',
          maxWidth: 440, zIndex: 1,
          display: 'flex', flexDirection: 'column', alignItems: 'flex-start',
        }}>
          {/* Logo + brand */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginBottom: 32 }}>
            <img src="/logo.png" alt="AttorneyAI"
              style={{ width: 170, height: 170, objectFit: 'contain', filter: `drop-shadow(0 2px 16px ${D.primaryGlow})` }} />
            <div>
              <div style={{ fontFamily: 'Georgia, serif', fontSize: 35, fontWeight: 800, color: D.text, letterSpacing: '-0.01em', lineHeight: 1 }}>
                Attorney.<span style={{ color: D.primary }}>AI</span>
              </div>
              <div style={{ fontSize: 10, color: D.textFaint, letterSpacing: '0.18em', textTransform: 'uppercase', marginTop: 3 }}>
                Legal Intelligence Platform
              </div>
            </div>
          </div>

          <h1 style={{ fontSize: 'clamp(28px, 3vw, 42px)', fontWeight: 800, color: D.text, lineHeight: 1.12, letterSpacing: '-0.02em', marginBottom: 16, maxWidth: 380 }}>
            Start Your<br />Legal Journey
          </h1>

          <p style={{ fontSize: 14.5, color: D.textMuted, lineHeight: 1.7, maxWidth: 340, marginBottom: 28 }}>
            Join thousands of Pakistanis getting instant, AI-powered legal guidance — grounded in PPC, CrPC & the Constitution.
          </p>

          {/* Feature list */}
          {[
            'AI legal research in seconds',
            'Document generation & e-signature',
            'Matched with verified lawyers',
          ].map(f => (
            <div key={f} style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10 }}>
              <div style={{ width: 20, height: 20, borderRadius: '50%', background: `rgba(64,240,220,0.12)`, border: `1px solid ${D.primaryGlow}`, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
                <IcCheck s={10} c={D.primary} />
              </div>
              <span style={{ fontSize: 13, color: D.textDim }}>{f}</span>
            </div>
          ))}

          {/* Badge */}
          <div style={{ display: 'inline-flex', alignItems: 'center', gap: 8, background: 'rgba(64,240,220,0.07)', border: `1px solid ${D.primaryGlow}`, borderRadius: 999, padding: '8px 16px', marginTop: 20 }}>
            <span style={{ fontSize: 13 }}>⚡</span>
            <span style={{ fontSize: 12, color: D.textDim, fontWeight: 500 }}>Free to get started — no credit card required</span>
          </div>
        </div>

        {/* ── RIGHT — floating white card ──────────────────────── */}
        <div style={{
          position: 'absolute',
          right: 72, top: '50%', transform: 'translateY(-50%)',
          width: 440, zIndex: 1,
        }}>
          <div className="rg-card" style={{
            background: L.surface,
            borderRadius: 28,
            padding: '22px 26px 18px',
            boxShadow: '0 24px 80px rgba(0,0,0,0.45), 0 0 0 1px rgba(255,255,255,0.08)',
            maxHeight: 'calc(100vh - 60px)',
            overflowY: 'auto',
          }}>

            {/* Heading */}
            <h2 style={{ fontSize: 18, fontWeight: 800, color: L.text, letterSpacing: '-0.01em', marginBottom: 2 }}>
              {isLawyer ? 'Create Lawyer Profile' : 'Create Account'}
            </h2>
            <p style={{ fontSize: 12, color: L.textMuted, marginBottom: 14 }}>
              Let's get started — it's free.
            </p>

            {/* Role toggle */}
            <div style={{ display: 'flex', background: L.bg, border: `1.5px solid ${L.border}`, borderRadius: 999, padding: 2, marginBottom: 14, gap: 2 }}>
              {[['client', 'Client'], ['lawyer', 'Lawyer']].map(([val, label]) => (
                <button key={val} className="role-pill rg-btn" onClick={() => setRole(val)} style={{
                  flex: 1, padding: '5px 0', borderRadius: 999, border: 'none',
                  background: role === val ? L.primary : 'transparent',
                  color: role === val ? '#fff' : L.textMuted,
                  fontSize: 11.5, fontWeight: 700, letterSpacing: '0.04em',
                }}>
                  {label}
                </button>
              ))}
            </div>

            {/* Fields */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: 9 }}>

              {/* Name row */}
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 9 }}>
                <Field label="First Name">
                  <Input placeholder="Ahmad" value={firstName} onChange={e => setFirstName(e.target.value)}
                    icon={<IcUser s={13} c={L.textFaint} />} />
                </Field>
                <Field label="Last Name">
                  <Input placeholder="Khan" value={lastName} onChange={e => setLastName(e.target.value)} />
                </Field>
              </div>

              <Field label="Email Address">
                <Input type="email" placeholder="you@lawfirm.com" value={email} onChange={e => setEmail(e.target.value)}
                  icon={<IcMail s={13} c={L.textFaint} />} />
              </Field>

              <Field label="Phone Number">
                <Input type="tel" placeholder="+92 300 000 0000" value={phone} onChange={e => setPhone(e.target.value)}
                  icon={<IcPhone s={13} c={L.textFaint} />} />
              </Field>

              {isLawyer && (
                <Field label="CNIC / Bar Council ID">
                  <Input placeholder="BCI/PNJ/2019/12345" value={cnic} onChange={e => setCnic(e.target.value)}
                    icon={<IcCert s={13} c={L.textFaint} />} />
                </Field>
              )}

              <Field label="Password">
                <Input type={showPw ? 'text' : 'password'} placeholder="Min. 8 characters"
                  value={password} onChange={e => setPassword(e.target.value)}
                  icon={<IcLock s={13} c={L.textFaint} />}
                  right={
                    <button onClick={() => setShowPw(p => !p)}
                      style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 0, lineHeight: 0 }}>
                      {showPw ? <IcEyeOff s={13} c={L.textFaint} /> : <IcEye s={13} c={L.textFaint} />}
                    </button>
                  } />
                {/* Strength bar */}
                {password.length > 0 && (
                  <div style={{ marginTop: 5 }}>
                    <div style={{ display: 'flex', gap: 3, marginBottom: 3 }}>
                      {[1, 2, 3].map(n => (
                        <div key={n} style={{ flex: 1, height: 2.5, borderRadius: 2, transition: 'background .3s', background: n <= strength ? sColors[strength] : L.border }} />
                      ))}
                    </div>
                    <span style={{ fontSize: 10.5, color: sColors[strength], fontWeight: 600 }}>{sLabels[strength]}</span>
                  </div>
                )}
              </Field>

            </div>

            {/* Optional links */}
            <div style={{ display: 'flex', gap: 14, marginTop: 10 }}>
              {['Have referral?', 'Redeem coupon?', ...(isLawyer ? ['Joined a Firm?'] : [])].map(l => (
                <span key={l} style={{ fontSize: 11.5, color: D.primary, cursor: 'pointer', fontWeight: 500 }}>{l}</span>
              ))}
            </div>

            {/* Terms */}
            <label style={{ display: 'flex', alignItems: 'flex-start', gap: 8, cursor: 'pointer', marginTop: 10 }}>
              <input type="checkbox" className="chk" checked={terms} onChange={() => setTerms(v => !v)} />
              <span style={{ fontSize: 11.5, color: L.textMuted, lineHeight: 1.5 }}>
                I agree to the <span style={{ color: L.primary, fontWeight: 600 }}>Terms and Conditions</span>
              </span>
            </label>

            {/* Error banner */}
            {apiError && (
              <div style={{
                background: 'rgba(217,54,84,0.08)', border: '1px solid rgba(217,54,84,0.3)',
                borderRadius: L.r.md, padding: '8px 12px', marginTop: 6,
                fontSize: 12, color: '#D93654', fontWeight: 500,
              }}>
                {apiError}
              </div>
            )}

            {/* Create button */}
            <button className="rg-btn" onClick={handleCreate} disabled={loading || authLoading} style={{
              width: '100%', marginTop: 14, padding: '10px 0',
              background: `linear-gradient(135deg, ${L.primary} 0%, ${L.primaryDim} 100%)`,
              border: 'none', borderRadius: L.r.md,
              fontSize: 13.5, fontWeight: 700, color: '#fff',
              letterSpacing: '0.03em',
              boxShadow: `0 4px 18px ${L.primaryGlow}`,
              display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8,
              opacity: (loading || authLoading) ? 0.7 : 1, cursor: (loading || authLoading) ? 'not-allowed' : 'pointer',
            }}>
              {loading ? 'Creating Account…' : (isLawyer ? 'Create Lawyer Profile' : 'Create Account')}
              {!loading && <IcArrow s={14} c="#fff" />}
            </button>

            {/* Sign in link */}
            <p style={{ textAlign: 'center', fontSize: 12, color: L.textMuted, margin: '10px 0 0 0' }}>
              Already have an account?{' '}
              <button className="rg-btn" onClick={() => router.push('/login')}
                style={{ background: 'none', border: 'none', fontSize: 12, color: L.primary, fontWeight: 700, padding: 0 }}>
                Sign In
              </button>
            </p>

          </div>
        </div>

      </div>
    </>
  );
}
