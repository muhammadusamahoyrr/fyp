'use client';
import React, { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { DARK, LIGHT } from '@/components/shared/themes.js';
import { authLogin } from '@/lib/api.js';
import { useAuth } from '@/context/AuthContext';

/* ─── SVG helpers ─────────────────────────────────────────────── */
const Svg = ({ size = 16, color, strokeWidth = 1.8, fill = 'none', children }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill={fill} stroke={color}
    strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round"
    style={{ display: 'inline-block', flexShrink: 0 }}>
    {children}
  </svg>
);
const IcEye = ({ size, color }) => (
  <Svg size={size} color={color}>
    <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
    <circle cx="12" cy="12" r="3" />
  </Svg>
);
const IcEyeOff = ({ size, color }) => (
  <Svg size={size} color={color}>
    <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94" />
    <path d="M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19" />
    <line x1="1" y1="1" x2="23" y2="23" />
  </Svg>
);
const IcUser = ({ size, color }) => (
  <Svg size={size} color={color}>
    <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
    <circle cx="12" cy="7" r="4" />
  </Svg>
);

/* ─── Mesh background ─────────────────────────────────────────── */
function MeshBg() {
  const nodes = [
    [80, 80], [220, 140], [400, 60], [520, 190], [170, 270],
    [310, 320], [460, 300], [60, 390], [270, 430], [500, 410],
    [370, 185], [145, 200], [440, 105], [560, 320], [35, 210],
    [620, 150], [680, 380], [720, 80], [750, 260], [600, 450],
  ];
  const edges = [
    [0, 1], [0, 14], [1, 2], [1, 4], [1, 11], [2, 12], [2, 3], [3, 6], [3, 10],
    [4, 5], [4, 11], [5, 6], [5, 8], [6, 9], [7, 8], [8, 9], [10, 3], [10, 5],
    [10, 12], [11, 4], [12, 3], [13, 6], [13, 9], [14, 4], [15, 2], [15, 12],
    [16, 9], [16, 13], [17, 15], [18, 16], [18, 13], [19, 16],
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

/* ─── Main page ───────────────────────────────────────────────── */
export default function LoginPage() {
  const router = useRouter();
  const { login, user, loading: authLoading } = useAuth();
  const D = DARK;
  const L = LIGHT;

  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPw, setShowPw] = useState(false);
  const [remember, setRemember] = useState(true);
  const [loading, setLoading] = useState(false);
  const [apiError, setApiError] = useState('');

  useEffect(() => {
    if (!authLoading && user) {
      router.replace(user.role === 'lawyer' ? '/lawyer' : user.role === 'admin' ? '/admin' : '/dashboard');
    }
  }, [authLoading, user]);

  async function handleSignIn() {
    if (!email || !password) { setApiError('Please enter your email and password.'); return; }
    setLoading(true);
    setApiError('');
    const { data, error } = await authLogin(email, password);
    setLoading(false);
    if (error) {
      setApiError(error.message || 'Invalid email or password.');
      return;
    }
    login(data); // sets user in AuthContext immediately
    router.push(data.role === 'lawyer' ? '/lawyer' : data.role === 'admin' ? '/admin' : '/dashboard');
  }

  return (
    <>
      <style>{`
        *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
        html, body { height: 100%; overflow: hidden; }
        .si-btn { transition: opacity .18s, transform .18s; cursor: pointer; }
        .si-btn:hover { opacity: .88; transform: translateY(-1px); }
        .si-field:focus-within { border-color: ${D.primary} !important; box-shadow: 0 0 0 3px ${D.primaryGlow2} !important; }
        .si-input { outline: none; }
        .si-social:hover { background: ${L.cardHi} !important; }
        .chk { accent-color: ${L.primary}; width: 15px; height: 15px; cursor: pointer; flex-shrink: 0; }
        .role-pill { transition: background .2s, color .2s; }

        /* Auth shell — flex row on desktop, stacks on tablet/mobile.
           Kept in CSS (not inline) so the media queries below can win. */
        .auth-shell {
          height: 100vh; overflow: hidden;
          display: flex; align-items: center; justify-content: center;
          gap: 48px; padding: 0 64px;
        }
        .auth-hero {
          flex: 1 1 460px; max-width: 460px; z-index: 1;
          display: flex; flex-direction: column; align-items: flex-start;
        }
        .auth-card-wrap { flex: 0 0 420px; width: 420px; max-width: 100%; z-index: 1; }

        @media (max-width: 1024px) {
          html, body { height: auto; overflow: auto; }
          .auth-shell {
            height: auto; min-height: 100vh; overflow-y: auto;
            flex-direction: column; justify-content: flex-start;
            gap: 28px; padding: 40px 20px;
          }
          .auth-hero { flex: none; max-width: 100%; align-items: center; text-align: center; }
          .auth-hero-extras { display: none; }
          .auth-hero img { width: 84px !important; height: 84px !important; }
          .auth-hero > div:first-child { margin-bottom: 0 !important; }
          .auth-card-wrap { flex: none; width: 100%; max-width: 420px; }
        }
        @media (max-width: 420px) {
          .auth-shell { padding: 24px 14px; }
        }
      `}</style>

      {/* ── Full dark background ─────────────────────────────── */}
      <div className="auth-shell" style={{
        width: '100%',
        background: `linear-gradient(140deg, ${D.bg} 0%, #162E38 55%, #0E2028 100%)`,
        fontFamily: "'Inter', sans-serif",
        position: 'relative',
      }}>
        <MeshBg />

        {/* Glow orbs */}
        <div style={{
          position: 'absolute', width: 600, height: 600, borderRadius: '50%',
          background: `radial-gradient(circle, ${D.primaryGlow2} 0%, transparent 65%)`,
          top: -160, left: -100, pointerEvents: 'none',
        }} />
        <div style={{
          position: 'absolute', width: 400, height: 400, borderRadius: '50%',
          background: `radial-gradient(circle, rgba(64,240,220,0.06) 0%, transparent 65%)`,
          bottom: -80, right: 340, pointerEvents: 'none',
        }} />

        {/* ── LEFT — hero text ─────────────────────────────────── */}
        <div className="auth-hero">
          {/* Logo + brand */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginBottom: 36 }}>
            <img src="/logo.png" alt="AttorneyAI"
              style={{
                width: 150, height: 150, objectFit: 'contain',
                filter: `drop-shadow(0 2px 16px ${D.primaryGlow})`,
              }} />
            <div>
              <div style={{
                fontFamily: 'Georgia, serif',
                fontSize: 26, fontWeight: 800,
                color: D.text, letterSpacing: '-0.01em', lineHeight: 1,
              }}>
                Attorney<span style={{ color: D.primary }}>AI</span>
              </div>
              <div style={{ fontSize: 10, color: D.textFaint, letterSpacing: '0.18em', textTransform: 'uppercase', marginTop: 3 }}>
                Legal Intelligence Platform
              </div>
            </div>
          </div>

          <div className="auth-hero-extras">
          {/* Main heading */}
          <h1 style={{
            fontSize: 'clamp(32px, 3.2vw, 48px)',
            fontWeight: 800, color: D.text,
            lineHeight: 1.12, letterSpacing: '-0.02em',
            marginBottom: 18, maxWidth: 420,
          }}>
            The Ultimate<br />AI Co-Counsel
          </h1>

          {/* Subtitle */}
          <p style={{
            fontSize: 15, color: D.textMuted,
            lineHeight: 1.7, maxWidth: 360, marginBottom: 32,
          }}>
            AI-powered legal guidance grounded in Pakistani law —
            PPC, CrPC, Family Code & the Constitution.
          </p>

          {/* INSTANT | ACCURATE | SECURE */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 28 }}>
            {['INSTANT', 'ACCURATE', 'SECURE'].map((w, i) => (
              <React.Fragment key={w}>
                <span style={{ fontSize: 11, fontWeight: 700, color: D.textFaint, letterSpacing: '0.14em' }}>{w}</span>
                {i < 2 && <span style={{ color: D.border, fontSize: 12 }}>|</span>}
              </React.Fragment>
            ))}
          </div>

          {/* Badge */}
          <div style={{
            display: 'inline-flex', alignItems: 'center', gap: 8,
            background: 'rgba(64,240,220,0.07)',
            border: `1px solid ${D.primaryGlow}`,
            borderRadius: 999, padding: '9px 18px',
          }}>
            <span style={{ fontSize: 13 }}>⚡</span>
            <span style={{ fontSize: 12.5, color: D.textDim, fontWeight: 500 }}>
              Powered by 400k case laws and statutes.
            </span>
          </div>
          </div>
        </div>

        {/* ── RIGHT — floating white card ───────────────────────── */}
        <div className="auth-card-wrap">
          <div style={{
            background: L.surface,
            borderRadius: 28,
            padding: '22px 28px 18px',
            boxShadow: `0 24px 80px rgba(0,0,0,0.45), 0 0 0 1px rgba(255,255,255,0.08)`,
          }}>

            {/* Avatar */}
            <div style={{ display: 'flex', justifyContent: 'center', marginBottom: 8 }}>
              <div style={{
                width: 40, height: 40, borderRadius: '50%',
                background: L.badgePrimary.bg,
                display: 'flex', alignItems: 'center', justifyContent: 'center',
              }}>
                <IcUser size={18} color={L.primary} />
              </div>
            </div>

            {/* Heading */}
            <h2 style={{
              textAlign: 'center', fontSize: 19, fontWeight: 800,
              color: L.text, letterSpacing: '-0.01em', marginBottom: 2,
            }}>
              Welcome Back!
            </h2>
            <p style={{ textAlign: 'center', fontSize: 12.5, color: L.textMuted, marginBottom: 14 }}>
              Please sign in to your account.
            </p>

            {/* Social buttons */}
            <div style={{ display: 'flex', gap: 8, marginBottom: 10 }}>
              <button className="si-social si-btn" style={{
                flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6,
                background: L.surface, border: `1.5px solid ${L.border}`,
                borderRadius: L.r.md, padding: '7px 0',
              }}>
                <svg width="15" height="15" viewBox="0 0 24 24">
                  <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" />
                  <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" />
                  <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" />
                  <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.47 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" />
                </svg>
                <span style={{ fontSize: 12, fontWeight: 600, color: L.textDim }}>Google</span>
              </button>

              <button className="si-social si-btn" style={{
                flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6,
                background: L.surface, border: `1.5px solid ${L.border}`,
                borderRadius: L.r.md, padding: '7px 0',
              }}>
                <svg width="15" height="15" viewBox="0 0 24 24">
                  <path fill="#1877F2" d="M24 12.073C24 5.405 18.627 0 12 0S0 5.405 0 12.073C0 18.1 4.388 23.094 10.125 24v-8.437H7.078v-3.49h3.047V9.413c0-3.026 1.791-4.697 4.533-4.697 1.313 0 2.686.235 2.686.235v2.97h-1.514c-1.491 0-1.956.93-1.956 1.886v2.266h3.328l-.532 3.49h-2.796V24C19.612 23.094 24 18.1 24 12.073z" />
                </svg>
                <span style={{ fontSize: 12, fontWeight: 600, color: L.textDim }}>Facebook</span>
              </button>
            </div>

            {/* Divider */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10 }}>
              <div style={{ flex: 1, height: 1, background: L.border }} />
              <span style={{ fontSize: 11, color: L.textFaint, fontWeight: 600, letterSpacing: '0.07em', textTransform: 'uppercase', whiteSpace: 'nowrap' }}>
                or continue with
              </span>
              <div style={{ flex: 1, height: 1, background: L.border }} />
            </div>

            {/* Email */}
            <div style={{ marginBottom: 8 }}>
              <label style={{ display: 'block', fontSize: 11, fontWeight: 600, color: L.textDim, marginBottom: 3 }}>
                Email
              </label>
              <div className="si-field" style={{
                background: L.inputBg, border: `1.5px solid transparent`,
                borderRadius: L.r.md, padding: '8px 11px',
                transition: 'border-color .2s, box-shadow .2s',
              }}>
                <input className="si-input" type="email" placeholder="attorneyai@gmail.com"
                  value={email} onChange={e => setEmail(e.target.value)}
                  style={{ width: '100%', background: 'none', border: 'none', fontSize: 12.5, color: L.text, fontFamily: 'inherit' }} />
              </div>
            </div>

            {/* Password */}
            <div style={{ marginBottom: 10 }}>
              <label style={{ display: 'block', fontSize: 11, fontWeight: 600, color: L.textDim, marginBottom: 3 }}>
                Password
              </label>
              <div className="si-field" style={{
                background: L.inputBg, border: `1.5px solid transparent`,
                borderRadius: L.r.md, padding: '8px 11px',
                display: 'flex', alignItems: 'center', gap: 8,
                transition: 'border-color .2s, box-shadow .2s',
              }}>
                <input className="si-input" type={showPw ? 'text' : 'password'}
                  placeholder="••••••••••••" value={password} onChange={e => setPassword(e.target.value)}
                  style={{ flex: 1, background: 'none', border: 'none', fontSize: 12.5, color: L.text, fontFamily: 'inherit' }} />
                <button onClick={() => setShowPw(p => !p)}
                  style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 0, lineHeight: 0 }}>
                  {showPw ? <IcEyeOff size={14} color={L.textFaint} /> : <IcEye size={14} color={L.textFaint} />}
                </button>
              </div>
            </div>

            {/* Error banner */}
            {apiError && (
              <div style={{
                background: 'rgba(217,54,84,0.08)', border: `1px solid rgba(217,54,84,0.3)`,
                borderRadius: L.r.md, padding: '8px 12px', marginBottom: 8,
                fontSize: 12, color: '#D93654', fontWeight: 500,
              }}>
                {apiError}
              </div>
            )}

            {/* Remember + Forgot */}
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
              <label style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer' }}>
                <input type="checkbox" className="chk" checked={remember} onChange={e => setRemember(e.target.checked)} />
                <span style={{ fontSize: 11.5, color: L.textMuted, fontWeight: 500, userSelect: 'none' }}>
                  Remember me for 90 days
                </span>
              </label>
              <button className="si-btn" onClick={() => router.push('/reset-password')}
                style={{ background: 'none', border: 'none', fontSize: 11.5, color: D.primary, fontWeight: 700, padding: 0 }}>
                Forgot Password?
              </button>
            </div>

            {/* Sign In CTA */}
            <button className="si-btn" onClick={handleSignIn} disabled={loading || authLoading} style={{
              width: '100%', padding: '10px 0',
              background: `linear-gradient(135deg, ${L.primary} 0%, ${L.primaryDim} 100%)`,
              border: 'none', borderRadius: L.r.md,
              fontSize: 13.5, fontWeight: 700, color: '#fff',
              letterSpacing: '0.03em',
              boxShadow: `0 4px 18px ${L.primaryGlow}`,
              marginBottom: 12,
              opacity: (loading || authLoading) ? 0.7 : 1, cursor: (loading || authLoading) ? 'not-allowed' : 'pointer',
            }}>
              {authLoading ? 'Checking session…' : loading ? 'Signing In…' : 'Sign In'}
            </button>

            {/* Register */}
            <p style={{ textAlign: 'center', fontSize: 12, color: L.textMuted, margin: 0 }}>
              Don't have an account?{' '}
              <button className="si-btn" onClick={() => router.push('/register')}
                style={{ background: 'none', border: 'none', fontSize: 12, color: L.primary, fontWeight: 700, padding: 0 }}>
                Sign Up
              </button>
            </p>

          </div>
        </div>

      </div>
    </>
  );
}
