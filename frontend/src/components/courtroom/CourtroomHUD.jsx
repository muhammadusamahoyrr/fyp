'use client';

import { useState, useEffect } from 'react';
import { motion } from 'framer-motion';

// ─── Clock formatter — created once at module level, not inside the interval ──
const CLOCK_FMT = new Intl.DateTimeFormat('en-PK', {
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hour12: false,
  timeZone: 'Asia/Karachi',
});

// ─── Theme palette ────────────────────────────────────────────────────────────
const T = {
  bg:         '#0F1115',
  surface:    '#16191E',
  border:     '#2D333B',
  primary:    '#D4AF37', // Polished Gold
  text:       '#F2F2EC',
  textMuted:  '#8B8B85',
  success:    '#4DD4A3',
  danger:     '#FF6B7A',
};

// ─── Components ───────────────────────────────────────────────────────────────

function TopBar() {
  const [time, setTime] = useState('');
  useEffect(() => {
    const timer = setInterval(() => {
      setTime(CLOCK_FMT.format(new Date()));
    }, 1000);
    return () => clearInterval(timer);
  }, []);

  return (
    <motion.div
      initial={{ y: -50, opacity: 0 }}
      animate={{ y: 0, opacity: 1 }}
      transition={{ duration: 0.8, delay: 0.2, type: 'spring' }}
      style={{
        position: 'absolute', top: 0, left: 0, right: 0,
        height: 56, background: 'rgba(15,17,21,0.85)', backdropFilter: 'blur(12px)',
        borderBottom: `1px solid ${T.border}`,
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '0 24px', zIndex: 10,
        fontFamily: '"Inter", sans-serif',
      }}
    >
      <div style={{ fontSize: '0.8rem', letterSpacing: '0.3em', color: T.primary, fontWeight: 700, textTransform: 'uppercase' }}>
        Attorney.AI
      </div>
      <div style={{ fontSize: '0.75rem', letterSpacing: '0.15em', color: T.textMuted, textTransform: 'uppercase' }}>
        Supreme Court of Pakistan — Virtual Session
      </div>
      <div style={{ fontSize: '0.75rem', color: T.text, display: 'flex', gap: '16px', fontWeight: 500, letterSpacing: '0.05em' }}>
        <span style={{ color: T.primary }}>2024-CR-0471</span>
        <span>{time}</span>
      </div>
    </motion.div>
  );
}

function BottomHUD() {
  return (
    <motion.div
      initial={{ y: 100, opacity: 0 }}
      animate={{ y: 0, opacity: 1 }}
      transition={{ duration: 0.8, delay: 0.4, type: 'spring' }}
      style={{
        position: 'absolute', bottom: 24, left: '50%', transform: 'translateX(-50%)',
        display: 'flex', alignItems: 'center', gap: 24,
        padding: '12px 24px', background: 'rgba(15,17,21,0.85)', backdropFilter: 'blur(12px)',
        borderRadius: 30, border: `1px solid ${T.border}`, zIndex: 10,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <motion.div
          animate={{ opacity: [1, 0.4, 1] }}
          transition={{ duration: 2, repeat: Infinity }}
          style={{ width: 8, height: 8, borderRadius: '50%', background: T.success, boxShadow: `0 0 8px ${T.success}88` }}
        />
        <span style={{ fontSize: '0.7rem', color: T.success, fontWeight: 600, letterSpacing: '0.05em', textTransform: 'uppercase' }}>Session Active</span>
      </div>
      
      <div style={{ width: 1, height: 24, background: T.border }} />
      
      <div style={{ fontSize: '0.8rem', color: T.text, fontWeight: 500 }}>
        Opening Hearing / Bail Application
      </div>

      <div style={{ width: 1, height: 24, background: T.border }} />

      <div style={{ display: 'flex', gap: 12 }}>
        {['Objection', 'Submit Evidence', 'Adjourn'].map((label, i) => (
          <button key={i} style={{
            background: 'transparent', border: `1px solid ${label === 'Adjourn' ? T.danger : T.primary}40`,
            color: label === 'Adjourn' ? T.danger : T.primary,
            padding: '6px 16px', borderRadius: 20, fontSize: '0.7rem', cursor: 'pointer',
            textTransform: 'uppercase', letterSpacing: '0.05em', fontWeight: 600,
          }}>
            {label}
          </button>
        ))}
      </div>
    </motion.div>
  );
}



export default function CourtroomHUD() {
  return (
    <>
      <TopBar />
      <BottomHUD />
    </>
  );
}
