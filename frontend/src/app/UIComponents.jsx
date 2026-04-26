'use client';
import React from 'react';

export function Logo({ t, sm }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
      <div style={{
        width: sm ? 28 : 34, height: sm ? 28 : 34,
        borderRadius: 8,
        background: t.grad1,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        flexShrink: 0,
      }}>
        <svg width={sm ? 14 : 18} height={sm ? 14 : 18} viewBox="0 0 24 24" fill="none"
          stroke={t.mode === 'dark' ? '#182B32' : '#fff'} strokeWidth="2.2">
          <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
        </svg>
      </div>
      <span style={{
        fontFamily: "'Cormorant Garamond', serif",
        fontSize: sm ? 16 : 20,
        fontWeight: 700,
        color: t.text,
        letterSpacing: '-0.01em',
      }}>
        AttorneyAI
      </span>
    </div>
  );
}

export function InputField({ label, type = 'text', placeholder, t, d = 0, icon, right }) {
  return (
    <div style={{ animation: `fadeUp 0.4s ease ${d}s both` }}>
      {label && (
        <label style={{
          display: 'block', fontSize: 12.5, fontWeight: 600,
          color: t.textDim, marginBottom: 5, letterSpacing: '0.01em',
        }}>
          {label}
        </label>
      )}
      <div
        style={{
          display: 'flex', alignItems: 'center', gap: 8,
          background: t.inputBg,
          border: `1px solid ${t.border}`,
          borderRadius: t.r?.md ?? 10,
          padding: '10px 12px',
          transition: 'border-color 0.2s, box-shadow 0.2s',
        }}
        onFocusCapture={e => {
          e.currentTarget.style.borderColor = t.primary;
          e.currentTarget.style.boxShadow = `0 0 0 3px ${t.inputFocus}`;
        }}
        onBlurCapture={e => {
          e.currentTarget.style.borderColor = t.border;
          e.currentTarget.style.boxShadow = 'none';
        }}
      >
        {icon && <span style={{ display: 'flex', flexShrink: 0 }}>{icon}</span>}
        <input
          type={type}
          placeholder={placeholder}
          style={{
            flex: 1, background: 'none', border: 'none', outline: 'none',
            fontSize: 13.5, color: t.text,
          }}
        />
        {right && <span style={{ display: 'flex', flexShrink: 0 }}>{right}</span>}
      </div>
    </div>
  );
}

export function PrimaryBtn({ onClick, t, d = 0, children }) {
  return (
    <button
      className="aBtn"
      onClick={onClick}
      style={{
        width: '100%', padding: '13px 0',
        borderRadius: t.r?.md ?? 10,
        background: t.grad1, border: 'none',
        color: t.mode === 'dark' ? '#182B32' : '#fff',
        fontSize: 14, fontWeight: 700,
        display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 7,
        cursor: 'pointer',
        boxShadow: `0 6px 20px ${t.primaryGlow}`,
        animation: `fadeUp 0.4s ease ${d}s both`,
      }}
    >
      {children}
    </button>
  );
}

export function Checkbox({ on, onChange, t }) {
  return (
    <div
      onClick={onChange}
      style={{
        width: 17, height: 17, borderRadius: 4, flexShrink: 0,
        border: `2px solid ${on ? t.primary : t.border}`,
        background: on ? t.primary : 'transparent',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        cursor: 'pointer', transition: 'all 0.2s',
      }}
    >
      {on && (
        <svg width="10" height="10" viewBox="0 0 24 24" fill="none"
          stroke={t.mode === 'dark' ? '#182B32' : '#fff'} strokeWidth="3.5">
          <polyline points="20,6 9,17 4,12" />
        </svg>
      )}
    </div>
  );
}

export function Divider({ t }) {
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 12,
      margin: '18px 0', animation: 'fadeUp 0.4s ease 0.32s both',
    }}>
      <div style={{ flex: 1, height: 1, background: t.border }} />
      <span style={{ fontSize: 12, color: t.textFaint, fontWeight: 500 }}>or continue with</span>
      <div style={{ flex: 1, height: 1, background: t.border }} />
    </div>
  );
}

export function GoogleBtn({ t }) {
  return (
    <button
      className="aBtn"
      style={{
        width: '100%', padding: '11px 0',
        borderRadius: t.r?.md ?? 10,
        background: 'transparent',
        border: `1.5px solid ${t.border}`,
        color: t.textDim, fontSize: 13.5, fontWeight: 600,
        display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 10,
        cursor: 'pointer',
        animation: 'fadeUp 0.4s ease 0.35s both',
      }}
    >
      <svg width="18" height="18" viewBox="0 0 24 24">
        <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" />
        <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" />
        <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" />
        <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" />
      </svg>
      Continue with Google
    </button>
  );
}

export function PillInput({ t, placeholder, type = 'text', icon, value, onChange, right }) {
  return (
    <div
      style={{
        display: 'flex', alignItems: 'center', gap: 8,
        background: t.inputBg,
        border: `1px solid ${t.border}`,
        borderRadius: t.r?.md ?? 10,
        padding: '9px 11px',
        transition: 'border-color 0.2s, box-shadow 0.2s',
      }}
      onFocusCapture={e => {
        e.currentTarget.style.borderColor = t.primary;
        e.currentTarget.style.boxShadow = `0 0 0 3px ${t.inputFocus}`;
      }}
      onBlurCapture={e => {
        e.currentTarget.style.borderColor = t.border;
        e.currentTarget.style.boxShadow = 'none';
      }}
    >
      {icon && <span style={{ display: 'flex', flexShrink: 0 }}>{icon}</span>}
      <input
        type={type}
        placeholder={placeholder}
        value={value}
        onChange={onChange}
        style={{
          flex: 1, background: 'none', border: 'none', outline: 'none',
          fontSize: 13, color: t.text,
        }}
      />
      {right && <span style={{ display: 'flex', flexShrink: 0 }}>{right}</span>}
    </div>
  );
}

export function FieldLabel({ t, children }) {
  return (
    <label style={{
      display: 'block', fontSize: 12, fontWeight: 600,
      color: t.textDim, marginBottom: 4, letterSpacing: '0.01em',
    }}>
      {children}
    </label>
  );
}
