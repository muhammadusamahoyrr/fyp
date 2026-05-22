'use client';

import { useState, Suspense, useRef, useEffect, memo } from 'react';
import { Canvas } from '@react-three/fiber';
import { motion, AnimatePresence } from 'framer-motion';
import Lenis from 'lenis';
import CourtroomScene from './CourtroomScene';

const INITIAL_TRANSCRIPT = [
  { speaker: 'COURT OFFICER', text: 'All rise. The Honourable Court is now in session.' },
  { speaker: 'JUDGE', text: 'Please be seated. This court is convened in the matter before it.' },
  { speaker: "PLAINTIFF'S COUNSEL", text: 'Your Honour, we are prepared to proceed with opening submissions.' },
  { speaker: 'DEFENCE COUNSEL', text: 'Defence is ready, Your Honour.' },
  { speaker: 'JUDGE', text: 'Very well. Counsel may proceed with opening submissions.' },
];

// ─── Theme palette (matches lawyer dashboard DARK theme) ─────────────────────
const T = {
  bg:         '#0F1115',
  surface:    '#16191E',
  card:       '#1C2127',
  border:     '#2D333B',
  primary:    '#D4AF37', // Polished Gold
  primaryDim: 'rgba(212,175,55,0.12)',
  text:       '#F2F2EC',
  textDim:    '#D4D4CE',
  textMuted:  '#8B8B85',
  textFaint:  '#5A5A54',
  success:    '#4DD4A3',
  danger:     '#FF6B7A',
  dangerDim:  'rgba(255,107,122,0.12)',
};

// ─── Styles ──────────────────────────────────────────────────────────────────
const ROOT = {
  display: 'flex',
  width: '100vw',
  height: '100vh',
  background: '#0D1A1E',
  overflow: 'hidden',
  fontFamily: '"Inter", "SF Pro Display", system-ui, sans-serif',
};

const PANEL = {
  flex: '0 0 240px',
  minWidth: 240,
  maxWidth: 240,
  display: 'flex',
  flexDirection: 'column',
  background: 'rgba(15, 17, 21, 0.85)',
  backdropFilter: 'blur(12px)',
  borderRight: `1px solid ${T.border}`,
  color: T.text,
  overflow: 'hidden',
  zIndex: 10,
};

function SectionLabel({ label }) {
  return (
    <div style={{
      fontSize: '0.58rem',
      letterSpacing: '0.22em',
      color: T.textFaint,
      textTransform: 'uppercase',
      marginBottom: 10,
      fontWeight: 600,
    }}>
      {label}
    </div>
  );
}

// ─── Button ──────────────────────────────────────────────────────────────────
function Btn({ onClick, disabled, danger, children }) {
  if (disabled) {
    return (
      <button disabled style={{
        padding: '9px 13px',
        border: `1px solid ${T.border}`,
        background: T.surface,
        color: T.textFaint,
        cursor: 'not-allowed',
        fontFamily: 'inherit',
        fontSize: '0.76rem',
        letterSpacing: '0.04em',
        textAlign: 'left',
        borderRadius: 7,
        width: '100%',
        opacity: 0.5,
      }}>
        {children}
      </button>
    );
  }
  if (danger) {
    return (
      <button onClick={onClick} style={{
        padding: '9px 13px',
        border: `1px solid ${T.danger}55`,
        background: T.dangerDim,
        color: T.danger,
        cursor: 'pointer',
        fontFamily: 'inherit',
        fontSize: '0.76rem',
        letterSpacing: '0.04em',
        textAlign: 'left',
        borderRadius: 7,
        width: '100%',
        transition: 'all 0.15s ease',
      }}
        onMouseEnter={e => { e.currentTarget.style.background = 'rgba(255,107,122,0.2)'; e.currentTarget.style.borderColor = T.danger; }}
        onMouseLeave={e => { e.currentTarget.style.background = T.dangerDim; e.currentTarget.style.borderColor = `${T.danger}55`; }}
      >
        {children}
      </button>
    );
  }
  return (
    <button onClick={onClick} style={{
      padding: '9px 13px',
      border: `1px solid ${T.primary}40`,
      background: T.primaryDim,
      color: T.primary,
      cursor: 'pointer',
      fontFamily: 'inherit',
      fontSize: '0.76rem',
      letterSpacing: '0.04em',
      textAlign: 'left',
      borderRadius: 7,
      width: '100%',
      transition: 'all 0.15s ease',
    }}
      onMouseEnter={e => { e.currentTarget.style.background = 'rgba(212,175,55,0.2)'; e.currentTarget.style.borderColor = T.primary; }}
      onMouseLeave={e => { e.currentTarget.style.background = T.primaryDim; e.currentTarget.style.borderColor = `${T.primary}40`; }}
    >
      {children}
    </button>
  );
}

// ─── Transcript entry ────────────────────────────────────────────────────────
function Entry({ speaker, text, fresh }) {
  const [active, setActive] = useState(fresh);

  useEffect(() => {
    if (fresh) {
      const timer = setTimeout(() => setActive(false), 3000);
      return () => clearTimeout(timer);
    }
  }, [fresh]);

  return (
    <motion.div
      initial={fresh ? { opacity: 0, y: 15, scale: 0.98 } : false}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ type: 'spring', damping: 25, stiffness: 200 }}
      style={{
        borderLeft: `2px solid ${active ? T.primary : T.border}`,
        paddingLeft: 12,
        transition: 'border-color 1.5s ease',
        background: active ? 'rgba(212,175,55,0.03)' : 'transparent',
        borderRadius: '0 4px 4px 0',
      }}
    >
      <div style={{
        fontSize: '0.58rem',
        letterSpacing: '0.16em',
        color: T.primary,
        marginBottom: 4,
        opacity: active ? 1 : 0.6,
        fontWeight: 700,
        textTransform: 'uppercase'
      }}>
        {speaker}
      </div>
      <div style={{ fontSize: '0.78rem', color: T.textDim, lineHeight: 1.6, fontWeight: 400 }}>{text}</div>
    </motion.div>
  );
}

// ─── Memoised canvas wrapper — insulates 3D scene from transcript re-renders ──
const CourtroomCanvas = memo(function CourtroomCanvas({ sessionStarted }) {
  return (
    <div style={{ flex: 1, position: 'relative', background: '#0D1A1E' }}>
      <Canvas
        shadows="soft"
        gl={{ antialias: true, powerPreference: 'high-performance' }}
        dpr={[1, 1.5]}
        style={{ width: '100%', height: '100%' }}
      >
        <Suspense fallback={null}>
          <CourtroomScene sessionStarted={sessionStarted} />
        </Suspense>
      </Canvas>

      <div style={{
        position: 'absolute', bottom: 14, left: 18,
        fontSize: '0.58rem', letterSpacing: '0.2em',
        color: 'rgba(212,175,55,0.28)', textTransform: 'uppercase',
        pointerEvents: 'none', userSelect: 'none',
      }}>
        Attorney.AI — Courtroom Simulation v1
      </div>

      <div style={{
        position: 'absolute', bottom: 14, right: 16,
        fontSize: '0.57rem', letterSpacing: '0.1em',
        color: 'rgba(212,175,55,0.35)',
        pointerEvents: 'none', userSelect: 'none',
      }}>
        Drag to orbit · Scroll to zoom
      </div>
    </div>
  );
});

// ─── Main component ──────────────────────────────────────────────────────────
export default function CourtroomSession() {
  const [sessionStarted, setSessionStarted] = useState(false);
  const [transcript, setTranscript] = useState(INITIAL_TRANSCRIPT);
  const transcriptRef = useRef(null);
  const lenisRef      = useRef(null);

  // Rolling window — keep last 50 entries to prevent unbounded DOM growth
  const push = (speaker, text) =>
    setTranscript((prev) => {
      const next = [...prev, { speaker, text, fresh: true }];
      return next.length > 50 ? next.slice(-50) : next;
    });

  useEffect(() => {
    const lenis = new Lenis({
      wrapper: transcriptRef.current,
      content: transcriptRef.current,
      duration: 1.2,
      easing: (t) => Math.min(1, 1.001 - Math.pow(2, -10 * t)),
    });
    lenisRef.current = lenis;

    let rafId;
    function raf(time) {
      lenis.raf(time);
      rafId = requestAnimationFrame(raf);
    }
    rafId = requestAnimationFrame(raf);

    return () => {
      cancelAnimationFrame(rafId);
      lenis.destroy();
      lenisRef.current = null;
    };
  }, []);

  // Use Lenis scrollTo so it doesn't fight its own RAF loop
  useEffect(() => {
    if (lenisRef.current && transcriptRef.current) {
      lenisRef.current.scrollTo(transcriptRef.current.scrollHeight);
    }
  }, [transcript]);

  const handleStart = () => {
    setSessionStarted(true);
    push('JUDGE', 'Court is now officially in session. Case proceedings shall commence.');
  };

  const handleEnd = () => {
    setSessionStarted(false);
    push('JUDGE', 'This court is adjourned. All rise.');
  };

  return (
    <div style={ROOT}>

      {/* ── LEFT: Control Panel ── */}
      <motion.div
        initial={{ x: -240, opacity: 0 }}
        animate={{ x: 0, opacity: 1 }}
        transition={{ type: 'spring', damping: 28, stiffness: 120, delay: 0.5 }}
        style={PANEL}
      >

        {/* Header */}
        <div style={{ padding: '16px 14px 12px', borderBottom: `1px solid ${T.border}`, background: 'rgba(255,255,255,0.02)' }}>
          <div style={{ fontSize: '0.52rem', letterSpacing: '0.32em', color: T.primary, marginBottom: 5, textTransform: 'uppercase', fontWeight: 700 }}>
            Attorney.AI
          </div>
          <div style={{ fontSize: '1.0rem', fontWeight: 800, letterSpacing: '0.01em', color: T.text, lineHeight: 1.2, fontFamily: 'serif' }}>
            Courtroom Session
          </div>
          <div style={{ fontSize: '0.58rem', color: T.textMuted, marginTop: 4, letterSpacing: '0.04em', textTransform: 'uppercase' }}>
            High Court of Pakistan · Civil Division
          </div>
        </div>

        {/* Status */}
        <div style={{ padding: '12px 16px', borderBottom: `1px solid ${T.border}` }}>
          <SectionLabel label="Session Status" />
          <div style={{ display: 'flex', alignItems: 'center', gap: 9 }}>
            <div style={{
              width: 8, height: 8, borderRadius: '50%', flexShrink: 0,
              background: sessionStarted ? T.success : T.textFaint,
              boxShadow: sessionStarted ? `0 0 8px ${T.success}88` : 'none',
              transition: 'all 0.4s ease',
            }} />
            <span style={{
              fontSize: '0.78rem', letterSpacing: '0.06em', fontWeight: 600,
              color: sessionStarted ? T.success : T.textMuted,
              transition: 'color 0.3s',
            }}>
              {sessionStarted ? 'IN SESSION' : 'NOT COMMENCED'}
            </span>
          </div>
          {sessionStarted && (
            <div style={{ marginTop: 6, fontSize: '0.62rem', color: T.textFaint, letterSpacing: '0.06em' }}>
              Case No. HCP-2026-00142 · Islamabad
            </div>
          )}
        </div>

        {/* Controls */}
        <div style={{ padding: '12px 16px', borderBottom: `1px solid ${T.border}` }}>
          <SectionLabel label="Session Controls" />
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            <Btn onClick={handleStart} disabled={sessionStarted}>
              ▶&nbsp; Commence Proceedings
            </Btn>
            <Btn disabled>
              ⚑&nbsp; Raise Objection
              <span style={{ fontSize: '0.58rem', marginLeft: 6, opacity: 0.45 }}>(Phase 2)</span>
            </Btn>
            <Btn disabled>
              ⊕&nbsp; Submit Evidence
              <span style={{ fontSize: '0.58rem', marginLeft: 6, opacity: 0.45 }}>(Phase 2)</span>
            </Btn>
            <Btn disabled>
              ◈&nbsp; Cross-Examine
              <span style={{ fontSize: '0.58rem', marginLeft: 6, opacity: 0.45 }}>(Phase 2)</span>
            </Btn>
            <Btn onClick={handleEnd} disabled={!sessionStarted} danger>
              ■&nbsp; Adjourn Session
            </Btn>
          </div>
        </div>

        {/* Transcript */}
        <div style={{ flex: 1, padding: '12px 16px 0', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
          <SectionLabel label="Session Transcript" />
          <div
            ref={transcriptRef}
            style={{
              flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column',
              gap: 10, paddingBottom: 14, paddingRight: 2,
              scrollBehavior: 'smooth'
            }}
          >
            {transcript.map((entry, i) => (
              <Entry key={i} speaker={entry.speaker} text={entry.text} fresh={entry.fresh} />
            ))}
          </div>
        </div>

        {/* Footer */}
        <div style={{
          padding: '12px 18px',
          borderTop: `1px solid ${T.border}`,
          fontSize: '0.54rem',
          color: T.textFaint,
          letterSpacing: '0.14em',
          textTransform: 'uppercase',
          flexShrink: 0,
          background: 'rgba(0,0,0,0.2)'
        }}>
          Institutional Protocol · v1.2
        </div>
      </motion.div>

      {/* ── RIGHT: 3D Courtroom Canvas — memoised, ignores transcript updates ── */}
      <CourtroomCanvas sessionStarted={sessionStarted} />

      <style jsx global>{`
        ::-webkit-scrollbar { width: 4px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb { background: rgba(212,175,55,0.2); border-radius: 10px; }
        ::-webkit-scrollbar-thumb:hover { background: rgba(212,175,55,0.4); }
      `}</style>

    </div>
  );
}
