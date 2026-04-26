'use client';
import React from 'react';

export function AuthLayout({ t, fullCard, children }) {
  return (
    <div style={{
      minHeight: '100vh',
      background: t.bg,
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      padding: '32px 20px',
      position: 'relative',
      overflow: 'hidden',
    }}>
      {/* Decorative background glows */}
      <div style={{
        position: 'absolute', width: 500, height: 500, borderRadius: '50%',
        background: t.primaryGlow2, filter: 'blur(100px)',
        top: -120, right: -100, pointerEvents: 'none',
      }} />
      <div style={{
        position: 'absolute', width: 350, height: 350, borderRadius: '50%',
        background: t.primaryGlow2, filter: 'blur(80px)',
        bottom: -80, left: -80, pointerEvents: 'none',
      }} />

      {fullCard ? (
        <div style={{
          width: '100%', maxWidth: 440,
          background: t.mode === 'dark' ? 'rgba(32,55,63,0.98)' : (t.surface ?? '#fff'),
          borderRadius: t.r?.xl ?? 18,
          border: `1px solid ${t.border}`,
          padding: '28px 26px 24px',
          boxShadow: t.shadowCard,
          position: 'relative', zIndex: 1,
          backdropFilter: 'blur(20px)',
        }}>
          {children}
        </div>
      ) : (
        <div style={{ width: '100%', maxWidth: 440, position: 'relative', zIndex: 1 }}>
          {children}
        </div>
      )}
    </div>
  );
}
