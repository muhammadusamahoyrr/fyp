'use client';
import React, { useState, useEffect, useRef } from 'react';
import { DARK } from '../admin/themes.js';

export const ONBOARDED_KEY = "attorney_ai_lawyer_onboarded";

// ─── Sidebar step config ──────────────────────────────────────────────────────
const LSTEPS = [
  { l: "Professional Profile", s: "Name, license & specialization" },
  { l: "Credentials & Photo", s: "Documents & profile picture" },
  { l: "Office & Availability", s: "Location, fees & working hours" },
  { l: "Admin Review", s: "Verification pending." },
];

// Specializations split into core / additional
const CORE_SPECS = [
  { label: "Corporate", icon: <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"><rect x="2" y="7" width="20" height="14" rx="2" /><path d="M16 7V5a2 2 0 00-2-2h-4a2 2 0 00-2 2v2" /><path d="M12 12v4M10 14h4" /></svg> },
  { label: "Criminal", icon: <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"><path d="M14.5 10c-.83 0-1.5-.67-1.5-1.5v-5c0-.83.67-1.5 1.5-1.5s1.5.67 1.5 1.5v5c0 .83-.67 1.5-1.5 1.5z" /><path d="M20.5 10H19V8.5c0-.83.67-1.5 1.5-1.5s1.5.67 1.5 1.5-.67 1.5-1.5 1.5z" /><path d="M9.5 14.5c.83 0 1.5.67 1.5 1.5v5c0 .83-.67 1.5-1.5 1.5S8 21.83 8 21v-5c0-.83.67-1.5 1.5-1.5z" /><path d="M3.5 14H5v1.5c0 .83-.67 1.5-1.5 1.5S2 16.33 2 15.5 2.67 14 3.5 14z" /><path d="M14 14.5c0-.83.67-1.5 1.5-1.5h5c.83 0 1.5.67 1.5 1.5s-.67 1.5-1.5 1.5h-5c-.83 0-1.5-.67-1.5-1.5z" /><path d="M15.5 19H14v1.5c0 .83.67 1.5 1.5 1.5s1.5-.67 1.5-1.5-.67-1.5-1.5-1.5z" /><path d="M10 9.5C10 8.67 9.33 8 8.5 8h-5C2.67 8 2 8.67 2 9.5S2.67 11 3.5 11h5c.83 0 1.5-.67 1.5-1.5z" /><path d="M8.5 5H10V3.5C10 2.67 9.33 2 8.5 2S7 2.67 7 3.5 7.67 5 8.5 5z" /></svg> },
  { label: "Family", icon: <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"><path d="M3 9l9-7 9 7v11a2 2 0 01-2 2H5a2 2 0 01-2-2z" /><polyline points="9 22 9 12 15 12 15 22" /></svg> },
  { label: "Civil Litigation", icon: <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="3" width="7" height="7" /><rect x="14" y="3" width="7" height="7" /><rect x="3" y="14" width="7" height="7" /><rect x="14" y="14" width="7" height="7" /></svg> },
  { label: "Real Estate", icon: <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"><path d="M3 21h18" /><path d="M5 21V7l8-4v18" /><path d="M19 21V11l-6-4" /><path d="M9 9v.01M9 12v.01M9 15v.01M9 18v.01" /><path d="M14 14.5c0-.83.67-1.5 1.5-1.5h5c.83 0 1.5.67 1.5 1.5s-.67 1.5-1.5 1.5h-5c-.83 0-1.5-.67-1.5-1.5z" /></svg> },
  { label: "Immigration", icon: <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10" /><path d="M12 2a15.3 15.3 0 014 10 15.3 15.3 0 01-4 10 15.3 15.3 0 01-4-10 15.3 15.3 0 014-10z" /><path d="M2 12h20" /></svg> },
];
const ADD_SPECS = [
  { label: "Environment Law", icon: <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"><path d="M12 22V12" /><path d="M5 12H2a10 10 0 007 9.4" /><path d="M19 12h3a10 10 0 01-7 9.4" /><path d="M12 12C12 7 7 3 2 2c0 5 3 9 10 10z" /><path d="M12 12c0-5 5-9 10-10 0 5-3 9-10 10z" /></svg> },
  { label: "Intellectual Property", icon: <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10" /><circle cx="12" cy="12" r="4" /><circle cx="12" cy="12" r="1" fill="currentColor" /></svg> },
  { label: "Arbitration", icon: <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"><path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z" /></svg> },
];

// ─── Icons ────────────────────────────────────────────────────────────────────
const IcoHome = ({ c = "currentColor" }) => <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke={c} strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M3 9l9-7 9 7v11a2 2 0 01-2 2H5a2 2 0 01-2-2z" /><polyline points="9 22 9 12 15 12 15 22" /></svg>;
const IcoUser = ({ c = "currentColor" }) => <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke={c} strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M20 21v-2a4 4 0 00-4-4H8a4 4 0 00-4 4v2" /><circle cx="12" cy="7" r="4" /></svg>;
const IcoDoc = ({ c = "currentColor" }) => <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke={c} strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" /><polyline points="14 2 14 8 20 8" /><line x1="9" y1="13" x2="15" y2="13" /><line x1="9" y1="17" x2="13" y2="17" /></svg>;
const IcoBrief = ({ c = "currentColor" }) => <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke={c} strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><rect x="2" y="7" width="20" height="14" rx="2" /><path d="M16 7V5a2 2 0 00-2-2h-4a2 2 0 00-2 2v2" /></svg>;
const IcoHelp = ({ c = "currentColor" }) => <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke={c} strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10" /><path d="M9.09 9a3 3 0 015.83 1c0 2-3 3-3 3" /><line x1="12" y1="17" x2="12.01" y2="17" /></svg>;
const IcoSettings = ({ c = "currentColor" }) => <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke={c} strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 010 2.83 2 2 0 01-2.83 0l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-4 0v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83-2.83l.06-.06A1.65 1.65 0 004.68 15a1.65 1.65 0 00-1.51-1H3a2 2 0 010-4h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 012.83-2.83l.06.06A1.65 1.65 0 009 4.68a1.65 1.65 0 001-1.51V3a2 2 0 014 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 2.83l-.06.06A1.65 1.65 0 0019.4 9a1.65 1.65 0 001.51 1H21a2 2 0 010 4h-.09a1.65 1.65 0 00-1.51 1z" /></svg>;
const IcoCheck = ({ c = "#182B32", sz = 14 }) => <svg width={sz} height={sz} viewBox="0 0 16 16" fill="none"><path d="M3 8l3 3 7-7" stroke={c} strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" /></svg>;
const IcoArrowR = ({ c = "currentColor" }) => <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke={c} strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="M5 12h14M12 5l7 7-7 7" /></svg>;
const IcoArrowL = ({ c = "currentColor" }) => <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke={c} strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="M19 12H5M12 19l-7-7 7-7" /></svg>;
const IcoCamera = ({ c = "currentColor" }) => <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke={c} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M23 19a2 2 0 01-2 2H3a2 2 0 01-2-2V8a2 2 0 012-2h4l2-3h6l2 3h4a2 2 0 012 2z" /><circle cx="12" cy="13" r="4" /></svg>;
const IcoPin = ({ c = "currentColor" }) => <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke={c} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0118 0z" /><circle cx="12" cy="10" r="3" /></svg>;
const IcoClock = ({ c = "currentColor" }) => <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke={c} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10" /><polyline points="12 6 12 12 16 14" /></svg>;
const IcoShield = ({ c = "currentColor" }) => <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke={c} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" /></svg>;
const IcoPhone = ({ c = "currentColor" }) => <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke={c} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M22 16.92v3a2 2 0 01-2.18 2 19.79 19.79 0 01-8.63-3.07 19.5 19.5 0 01-6-6 19.79 19.79 0 01-3.07-8.67A2 2 0 014.11 2h3a2 2 0 012 1.72c.127.96.361 1.903.7 2.81a2 2 0 01-.45 2.11L8.09 9.91a16 16 0 006 6l1.27-1.27a2 2 0 012.11-.45c.907.339 1.85.573 2.81.7A2 2 0 0122 16.92z" /></svg>;
const IcoDownload = ({ c = "currentColor" }) => <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke={c} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" /><polyline points="7 10 12 15 17 10" /><line x1="12" y1="15" x2="12" y2="3" /></svg>;
const IcoMail = ({ c = "currentColor" }) => <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke={c} strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z" /><polyline points="22,6 12,13 2,6" /></svg>;

// ─── Use App Theme ────────────────────────────────────────────────────────────
// Defaults to DARK, but onboarding should inherit the currently selected app theme.
let T = DARK;

// Nav items for icon sidebar
const NAV_ITEMS = [
  { icon: <IcoHome />, idx: 0 },
  { icon: <IcoUser />, idx: 1 },
  { icon: <IcoDoc />, idx: 2 },
  { icon: <IcoBrief />, idx: 3 },
];

// ─── Left Icon Sidebar ────────────────────────────────────────────────────────
function IconSidebar({ step }) {
  const bg = "linear-gradient(180deg,#0D1E22 0%,#132028 100%)";
  return (
    <div style={{
      width: 64, flexShrink: 0, height: "100vh", borderRight: `1px solid ${T.border}`,
      background: bg, display: "flex", flexDirection: "column", alignItems: "center",
      paddingTop: 16, paddingBottom: 16,
    }}>
      {/* Logo */}
      <div style={{
        width: 38, height: 38, borderRadius: T.r?.md ?? 10, background: T.primaryGlow2,
        border: `1.5px solid ${T.primary}50`, display: "flex", alignItems: "center",
        justifyContent: "center", marginBottom: 28, flexShrink: 0,
      }}>
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke={T.primary} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
        </svg>
      </div>

      {/* Nav icons */}
      <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 6, alignItems: "center" }}>
        {NAV_ITEMS.map(({ icon, idx }) => {
          const active = idx === step;
          const done = idx < step;
          return (
            <div key={idx} style={{
              width: 40, height: 40, borderRadius: T.r?.md ?? 10, display: "flex",
              alignItems: "center", justifyContent: "center", position: "relative",
              background: active ? T.primaryGlow2 : "transparent",
              border: active ? `1.5px solid ${T.primary}60` : "1.5px solid transparent",
              color: active ? T.primary : done ? T.textDim : T.textFaint,
              transition: "all .2s", cursor: "pointer",
            }}>
              {React.cloneElement(icon, { c: active ? T.primary : done ? T.primary + "99" : T.textFaint })}
              {done && (
                <div style={{
                  position: "absolute", top: -3, right: -3, width: 14, height: 14,
                  borderRadius: "50%", background: T.primary, border: `2px solid ${T.bg}`,
                  display: "flex", alignItems: "center", justifyContent: "center",
                }}>
                  <IcoCheck c={T.bg} sz={8} />
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Bottom icons */}
      <div style={{ display: "flex", flexDirection: "column", gap: 6, alignItems: "center" }}>
        {[<IcoHelp />, <IcoSettings />].map((ico, i) => (
          <div key={i} style={{
            width: 40, height: 40, borderRadius: T.r?.md ?? 10, display: "flex",
            alignItems: "center", justifyContent: "center", color: T.textFaint, cursor: "pointer",
          }}>
            {React.cloneElement(ico, { c: T.textFaint })}
          </div>
        ))}
        {/* Avatar */}
        <div style={{
          width: 36, height: 36, borderRadius: "50%", background: T.primaryGlow2,
          border: `2px solid ${T.primary}50`, display: "flex", alignItems: "center",
          justifyContent: "center", marginTop: 8, cursor: "pointer",
        }}>
          <span style={{ fontFamily: "'Cormorant Garamond', serif", fontSize: 15, fontWeight: 700, color: T.primary }}>N</span>
        </div>
      </div>
    </div>
  );
}

// ─── Wide Step Sidebar ────────────────────────────────────────────────────────
function StepSidebar({ step }) {
  return (
    <div style={{
      width: 268, flexShrink: 0, height: "100vh", borderRight: `1px solid ${T.border}`,
      background: "linear-gradient(180deg,#0D1E22 0%,#132028 100%)",
      padding: "20px 20px 20px 16px", display: "flex", flexDirection: "column", overflow: "hidden",
    }}>
      {/* Logo row */}
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 24, flexShrink: 0 }}>
        <div style={{
          width: 34, height: 34, borderRadius: T.r.md, background: T.primaryGlow,
          border: `1.5px solid ${T.primary}50`, display: "flex", alignItems: "center", justifyContent: "center",
        }}>
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke={T.primary} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
          </svg>
        </div>
        <span style={{ fontFamily: "'Cormorant Garamond', serif", fontSize: 19, fontWeight: 700, color: T.text, letterSpacing: "-.02em" }}>AttorneyAI</span>
      </div>

      <div style={{ height: 1, background: T.border, marginBottom: 18, flexShrink: 0 }} />

      <p style={{ fontSize: 15, fontWeight: 700, color: T.text, marginBottom: 4, letterSpacing: "-.01em" }}>Profile Setup</p>
      <p style={{ fontSize: 12, color: T.textMuted, lineHeight: 1.5, marginBottom: 24 }}>Complete your profile to go live</p>

      {/* Steps — numbered circle style matching design */}
      <div style={{ flex: 1, display: "flex", flexDirection: "column" }}>
        {LSTEPS.map((s, i) => {
          const done = i < step, active = i === step;
          return (
            <div key={i} style={{
              display: "flex", gap: 14,
              flex: i < LSTEPS.length - 1 ? 1 : "none",
              minHeight: 56,
              opacity: done || active ? 1 : 0.3,
              transition: "opacity .3s",
            }}>
              {/* Circle + connector line */}
              <div style={{ display: "flex", flexDirection: "column", alignItems: "center", flexShrink: 0 }}>
                <div style={{
                  width: 36, height: 36, borderRadius: "50%", flexShrink: 0,
                  display: "flex", alignItems: "center", justifyContent: "center",
                  background: done ? T.primary : active ? T.primaryGlow : "transparent",
                  border: `2px solid ${done ? T.primary : active ? T.primary : T.border}`,
                  color: done ? T.bg : active ? T.primary : T.textMuted,
                  fontSize: 13, fontWeight: 700,
                  transition: "all .3s",
                  boxShadow: active ? `0 0 0 5px ${T.primaryGlow2}` : "none",
                  position: "relative",
                }}>
                  {done
                    ? <IcoCheck c={T.bg} sz={15} />
                    : <span style={{ fontSize: 13, fontWeight: 700, fontFamily: "'Inter', sans-serif" }}>{i + 1}</span>
                  }
                </div>
                {i < LSTEPS.length - 1 && (
                  <div style={{
                    width: 2, flex: 1, minHeight: 16,
                    background: done
                      ? T.primary
                      : `linear-gradient(to bottom, ${active ? T.primary + "60" : T.border}, ${T.border})`,
                    margin: "4px 0", borderRadius: 2, transition: "background .4s",
                  }} />
                )}
              </div>

              {/* Text */}
              <div style={{ paddingTop: 7 }}>
                <p style={{
                  fontSize: 13.5, fontWeight: active ? 700 : done ? 600 : 500,
                  color: active ? T.text : done ? T.textDim : T.textMuted,
                  lineHeight: 1.2, marginBottom: 4, transition: "all .3s",
                }}>{s.l}</p>
                <p style={{ fontSize: 11.5, color: T.textFaint, lineHeight: 1.4 }}>{s.s}</p>
                {active && (
                  <span style={{
                    display: "inline-flex", alignItems: "center", marginTop: 6, fontSize: 10, fontWeight: 700,
                    color: T.primary, background: T.primaryGlow2, padding: "2px 10px",
                    borderRadius: 99, border: `1px solid ${T.primary}30`, letterSpacing: ".08em",
                  }}>ACTIVE</span>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {/* Bottom avatar */}
      <div style={{ display: "flex", alignItems: "center", gap: 10, paddingTop: 16, borderTop: `1px solid ${T.border}`, flexShrink: 0 }}>
        <div style={{
          width: 34, height: 34, borderRadius: "50%", background: T.primaryGlow,
          border: `2px solid ${T.primary}50`, display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0,
        }}>
          <span style={{ fontFamily: "'Cormorant Garamond', serif", fontSize: 15, fontWeight: 700, color: T.primary }}>N</span>
        </div>
        <div style={{ minWidth: 0 }}>
          <p style={{ fontSize: 13, fontWeight: 600, color: T.text, marginBottom: 2, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>Ahmad Khan</p>
          <p style={{ fontSize: 11, color: T.textFaint }}>Draft profile</p>
        </div>
      </div>
    </div>
  );
}

// ─── Input ────────────────────────────────────────────────────────────────────
function TextInput({ placeholder, type = "text", icon, right, prefix, style: extStyle }) {
  const [f, setF] = useState(false);
  return (
    <div style={{
      display: "flex", alignItems: "center", gap: 10,
      background: f ? T.primaryGlow2 : "rgba(22,40,48,0.9)",
      border: `1.5px solid ${f ? T.primary : T.border}`,
      borderRadius: T.r.md, padding: "0 14px",
      transition: "all .2s", boxShadow: f ? `0 0 0 3px ${T.primaryGlow}` : "none",
      ...extStyle,
    }}>
      {icon && <span style={{ color: f ? T.primary : T.textFaint, flexShrink: 0, display: "flex", transition: "color .2s" }}>{icon}</span>}
      {prefix && <span style={{ color: T.textMuted, fontSize: 13, fontWeight: 600, whiteSpace: "nowrap" }}>{prefix}</span>}
      <input
        type={type}
        placeholder={placeholder}
        onFocus={() => setF(true)}
        onBlur={() => setF(false)}
        style={{
          flex: 1, minWidth: 0, padding: "11px 0", background: "transparent",
          border: "none", color: T.text, fontSize: 13.5, outline: "none",
          fontFamily: "'Inter', sans-serif",
        }}
      />
      {right}
    </div>
  );
}

function Label({ children, mt = 0 }) {
  return (
    <p style={{
      fontSize: 10, fontWeight: 700, color: T.textMuted, textTransform: "uppercase",
      letterSpacing: ".14em", marginBottom: 8, marginTop: mt,
    }}>{children}</p>
  );
}

// ─── Step 0: Professional Profile ────────────────────────────────────────────
function Step0({ specs, setSpecs }) {
  const togSpec = (s) => setSpecs(p => p.includes(s) ? p.filter(x => x !== s) : [...p, s]);
  const SpecBtn = ({ item }) => {
    const active = specs.includes(item.label);
    return (
      <button
        type="button"
        onClick={() => togSpec(item.label)}
        style={{
          display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center",
          gap: 8, padding: "12px 8px", borderRadius: T.r.md, cursor: "pointer",
          border: `1.5px solid ${active ? T.primary : T.border}`,
          background: active ? T.primaryGlow : "rgba(22,40,48,0.8)",
          color: active ? T.primary : T.textDim,
          boxShadow: active ? `0 0 0 1px ${T.primary}40, 0 4px 16px ${T.primaryGlow}` : "none",
          transition: "all .2s", minHeight: 80, textAlign: "center",
        }}
      >
        <span style={{ opacity: active ? 1 : 0.6 }}>{item.icon}</span>
        <span style={{ fontSize: 11.5, fontWeight: active ? 700 : 500, lineHeight: 1.2 }}>{item.label}</span>
        {active && (
          <div style={{
            position: "absolute", top: 6, right: 6, width: 16, height: 16, borderRadius: "50%",
            background: T.primary, display: "flex", alignItems: "center", justifyContent: "center",
          }}>
            <IcoCheck c={T.bg} sz={10} />
          </div>
        )}
      </button>
    );
  };

  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 16, height: "100%", alignItems: "start" }}>
      {/* Card 1: Identity Details */}
      <div style={{ background: T.card, border: `1px solid ${T.border}`, borderRadius: T.r.lg, padding: "20px 18px" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 18 }}>
          <div style={{ width: 32, height: 32, borderRadius: T.r.sm, background: T.primaryGlow, display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
            <IcoUser c={T.primary} />
          </div>
          <p style={{ fontFamily: "'Cormorant Garamond', serif", fontSize: 20, fontWeight: 700, color: T.text }}>Identity Details</p>
        </div>
        <Label>Full Name</Label>
        <TextInput placeholder="Adv. Ahmad Khan" icon={<IcoUser c={T.textFaint} />} />
        <div style={{ height: 14 }} />
        <Label>Years of Experience</Label>
        <TextInput placeholder="e.g. 8" type="number" icon={<IcoClock c={T.textFaint} />} />
        <p style={{ fontSize: 11.5, color: T.textFaint, marginTop: 10, lineHeight: 1.5 }}>This information is used for matching.</p>
      </div>

      {/* Card 2: License Information */}
      <div style={{ background: T.card, border: `1px solid ${T.border}`, borderRadius: T.r.lg, padding: "20px 18px" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 18 }}>
          <div style={{ width: 32, height: 32, borderRadius: T.r.sm, background: T.primaryGlow, display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
            <IcoShield c={T.primary} />
          </div>
          <p style={{ fontFamily: "'Cormorant Garamond', serif", fontSize: 20, fontWeight: 700, color: T.text }}>License Information</p>
        </div>
        <Label>Bar Council</Label>
        <TextInput placeholder="Punjab Bar Council" icon={<IcoShield c={T.textFaint} />} />
        <div style={{ height: 14 }} />
        <Label>Bar License No.</Label>
        <TextInput
          placeholder="BCI/PNJ/2019/12345"
          right={
            <span style={{ display: "flex", alignItems: "center", gap: 4, color: T.primary, fontSize: 11.5, fontWeight: 700, flexShrink: 0 }}>
              <IcoCheck c={T.primary} sz={12} /> Verified
            </span>
          }
        />
        <div style={{ marginTop: 12, padding: "10px 14px", borderRadius: T.r.md, background: "rgba(45,212,191,0.06)", border: `1px solid ${T.primary}30`, display: "flex", alignItems: "center", gap: 10 }}>
          <IcoCheck c={T.primary} sz={14} />
          <span style={{ fontSize: 12, color: T.textDim }}>VERIFIED (BKP/PNJ/2019)</span>
        </div>
        <div style={{ marginTop: 8, padding: "10px 14px", borderRadius: T.r.md, background: "rgba(45,212,191,0.04)", border: `1px solid ${T.border}`, display: "flex", alignItems: "center", gap: 10 }}>
          <IcoCheck c={T.primary} sz={14} />
          <span style={{ fontSize: 11.5, color: T.textMuted }}>Document Verified · Pending Bar Approval</span>
        </div>
        <button style={{
          width: "100%", marginTop: 12, padding: "11px", borderRadius: T.r.md,
          background: "rgba(45,212,191,0.07)", border: `1px solid ${T.border}`,
          color: T.textDim, fontSize: 13, fontWeight: 700, cursor: "pointer",
          letterSpacing: ".1em", textTransform: "uppercase",
        }}>Verify</button>
      </div>

      {/* Card 3: Primary Specializations */}
      <div style={{ background: T.card, border: `1px solid ${T.border}`, borderRadius: T.r.lg, padding: "20px 18px" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 6 }}>
          <div style={{ width: 32, height: 32, borderRadius: T.r.sm, background: T.primaryGlow, display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke={T.primary} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10" /><circle cx="12" cy="12" r="6" /><circle cx="12" cy="12" r="2" /></svg>
          </div>
          <p style={{ fontFamily: "'Cormorant Garamond', serif", fontSize: 20, fontWeight: 700, color: T.text }}>Primary Specializations</p>
        </div>

        <Label mt={10}>Core Specializations (Select up to 3)</Label>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 8, marginBottom: 14 }}>
          {CORE_SPECS.map(s => (
            <div key={s.label} style={{ position: "relative" }}>
              <SpecBtn item={s} />
            </div>
          ))}
        </div>

        <Label>Additional Areas</Label>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 8 }}>
          {ADD_SPECS.map(s => (
            <div key={s.label} style={{ position: "relative" }}>
              <SpecBtn item={s} />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ─── Step 1: Credentials & Photo ──────────────────────────────────────────────
function Step1() {
  const [uploaded, setUploaded] = useState([false, false, false]);
  const toggle = (i) => setUploaded(p => p.map((v, j) => j === i ? !v : v));

  const creds = [
    { label: "Bar Council Certificate", hint: "Official bar membership certificate", icon: "📋", emoji: "📜", color: "#F0A500" },
    { label: "Educational Credentials", hint: "LLB or equivalent law degree", icon: "🎓", emoji: "🎓", color: "#2DD4BF" },
    { label: "Professional Certificates", hint: "Additional certifications or awards", icon: "🏆", emoji: "🏅", color: "#A855F7" },
  ];

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      <div style={{ marginBottom: 18 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 14, marginBottom: 8 }}>
          <h2 style={{ fontFamily: "'Cormorant Garamond', serif", fontSize: 32, fontWeight: 700, color: T.text, lineHeight: 1.1, letterSpacing: "-.02em" }}>Credentials &amp; Photo</h2>
          <span style={{ padding: "4px 12px", borderRadius: 99, background: "rgba(240,165,0,0.12)", border: "1px solid rgba(240,165,0,0.3)", fontSize: 11.5, color: "#F0A500", fontWeight: 600, display: "flex", alignItems: "center", gap: 6 }}>
            ℹ Why this matters
          </span>
        </div>
        <p style={{ color: T.textMuted, fontSize: 13.5, lineHeight: 1.6 }}>Upload a professional photo and your credentials — clients see these before booking.</p>
      </div>

      {/* Verification banner */}
      <div style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        padding: "10px 18px", borderRadius: T.r.md, marginBottom: 16,
        background: "rgba(180,140,0,0.1)", border: "1px solid rgba(180,140,0,0.35)",
      }}>
        <span style={{ fontSize: 13, color: "#D4AA30", fontWeight: 600 }}>⚠ Verification needed for 2 items</span>
        <span style={{ fontSize: 11.5, color: T.textFaint }}>Items pending verification</span>
      </div>

      {/* Content row */}
      <div style={{ display: "grid", gridTemplateColumns: "200px 1fr", gap: 16, flex: 1 }}>
        {/* Profile Photo */}
        <div style={{
          display: "flex", flexDirection: "column", gap: 14, padding: "20px 16px",
          borderRadius: T.r.lg, background: T.card, border: `1px solid ${T.border}`,
          alignItems: "center", textAlign: "center",
        }}>
          <div style={{
            width: 90, height: 90, borderRadius: "50%",
            background: `linear-gradient(135deg,${T.primary}20,${T.primary}50)`,
            border: `2px solid ${T.primary}50`,
            display: "flex", alignItems: "center", justifyContent: "center",
          }}>
            <span style={{ fontFamily: "'Cormorant Garamond', serif", fontSize: 28, fontWeight: 700, color: T.primary }}>AK</span>
          </div>
          <div>
            <p style={{ fontSize: 14, fontWeight: 700, color: T.text, marginBottom: 4 }}>Profile Photo</p>
            <p style={{ fontSize: 11.5, color: T.textMuted, lineHeight: 1.5, marginBottom: 14 }}>JPG or PNG · min 200×200px</p>
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              <button style={{
                padding: "9px 16px", borderRadius: 99, background: T.grad1,
                border: "none", color: T.bg, fontSize: 12.5, fontWeight: 700, cursor: "pointer",
                display: "flex", alignItems: "center", gap: 7, justifyContent: "center",
                boxShadow: `0 4px 14px ${T.primaryGlow}`,
              }}>
                <IcoCamera c={T.bg} /> Upload Photo
              </button>
              <button style={{
                padding: "9px 16px", borderRadius: 99, background: "transparent",
                border: `1.5px solid ${T.border}`, color: T.textDim, fontSize: 12.5, fontWeight: 500, cursor: "pointer",
                display: "flex", alignItems: "center", gap: 7, justifyContent: "center",
              }}>
                <IcoCamera c={T.textDim} /> Take Photo
              </button>
            </div>
            <p style={{ fontSize: 11, color: T.textFaint, marginTop: 12 }}>No image uploaded yet</p>
          </div>
        </div>

        {/* Credentials */}
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          {creds.map((doc, i) => (
            <div key={i} style={{
              padding: "16px 18px", borderRadius: T.r.lg, background: T.card,
              border: `1px solid ${T.border}`, display: "flex", flexDirection: "column", gap: 10,
            }}>
              <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
                <div style={{
                  width: 50, height: 50, borderRadius: T.r.md, flexShrink: 0,
                  background: `${doc.color}15`, border: `1px solid ${doc.color}30`,
                  display: "flex", alignItems: "center", justifyContent: "center", fontSize: 24,
                }}>{doc.emoji}</div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <p style={{ fontSize: 15, fontWeight: 700, color: T.text, marginBottom: 3 }}>{doc.label}</p>
                  <p style={{ fontSize: 11.5, color: T.textFaint, lineHeight: 1.4 }}>{doc.hint} · PDF, JPG or PNG · Max 5MB</p>
                </div>
                <button
                  onClick={() => toggle(i)}
                  style={{
                    padding: "10px 22px", borderRadius: T.r.md, flexShrink: 0,
                    background: uploaded[i] ? T.primaryGlow : T.grad1,
                    border: uploaded[i] ? `1.5px solid ${T.primary}50` : "none",
                    color: uploaded[i] ? T.primary : T.bg,
                    fontSize: 13, fontWeight: 700, cursor: "pointer",
                    boxShadow: uploaded[i] ? "none" : `0 4px 12px ${T.primaryGlow}`,
                  }}>
                  {uploaded[i] ? "✓ Uploaded" : "Upload"}
                </button>
              </div>

              {i === 0 && (
                <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                  <span style={{ fontSize: 10, fontWeight: 700, color: T.primary, background: T.primaryGlow2, padding: "2px 8px", borderRadius: 99, border: `1px solid ${T.primary}30` }}>Recommended</span>
                  <div style={{
                    flex: 1, display: "flex", alignItems: "center", gap: 10,
                    padding: "8px 12px", borderRadius: T.r.sm,
                    background: "rgba(22,40,48,0.8)", border: `1px solid ${T.border}`,
                  }}>
                    <span style={{ fontSize: 18 }}>📄</span>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <p style={{ fontSize: 12.5, color: T.text, fontWeight: 500 }}>certificate.pdf</p>
                      <p style={{ fontSize: 11, color: T.textFaint }}>📎 certificate.pdf</p>
                    </div>
                    <IcoDownload c={T.textMuted} />
                  </div>
                </div>
              )}
              {i > 0 && (
                <div style={{
                  display: "flex", alignItems: "center", gap: 8,
                  padding: "8px 12px", borderRadius: T.r.sm,
                  background: "rgba(45,212,191,0.05)", border: `1px solid ${T.primary}25`,
                }}>
                  <IcoCheck c={T.primary} sz={14} />
                  <span style={{ fontSize: 12.5, color: T.textDim }}>Ready to Upload</span>
                  <div style={{ flex: 1 }} />
                  <IcoDownload c={T.textMuted} />
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ─── Step 2: Office & Availability ───────────────────────────────────────────
const DAYS = ["M", "T", "W", "T", "F", "S", "S"];

function Step2() {
  const [activeDays, setActiveDays] = useState([0, 1, 2, 3, 4]);
  const [minFee, setMinFee] = useState(5000);
  const [maxFee, setMaxFee] = useState(25000);
  const MAX_FEE = 50000;

  const toggleDay = (i) => setActiveDays(p => p.includes(i) ? p.filter(d => d !== i) : [...p, i].sort((a, b) => a - b));

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      <div style={{ marginBottom: 18 }}>
        <h2 style={{ fontFamily: "'Cormorant Garamond', serif", fontSize: 32, fontWeight: 700, color: T.text, lineHeight: 1.1, letterSpacing: "-.02em", marginBottom: 8 }}>Office &amp; Availability</h2>
        <p style={{ color: T.textMuted, fontSize: 14, lineHeight: 1.6 }}>Help clients find your office and know when they can book a consultation.</p>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 14, flex: 1 }}>
        {/* Col 1: Location */}
        <div style={{ background: T.card, border: `1px solid ${T.border}`, borderRadius: T.r.lg, padding: "18px 16px" }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 16 }}>
            <Label>Location &amp; Contact</Label>
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke={T.textMuted} strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M14.7 6.3a1 1 0 000 1.4l1.6 1.6a1 1 0 001.4 0l3.77-3.77a6 6 0 01-7.94 7.94l-6.91 6.91a2.12 2.12 0 01-3-3l6.91-6.91a6 6 0 017.94-7.94l-3.76 3.76z" /></svg>
          </div>
          <p style={{ fontSize: 12.5, color: T.textDim, marginBottom: 8, fontWeight: 500 }}>Office address</p>
          <div style={{ display: "grid", gridTemplateColumns: "1fr auto", gap: 8, marginBottom: 12 }}>
            <TextInput placeholder="Street Address (e.g., 14" icon={<IcoPin c={T.textFaint} />} />
            <div style={{
              width: 72, height: "100%", borderRadius: T.r.sm, overflow: "hidden",
              background: "#1E3A44", border: `1px solid ${T.border}`,
              display: "flex", alignItems: "center", justifyContent: "center",
              position: "relative",
            }}>
              <div style={{ fontSize: 20, opacity: 0.8 }}>🗺️</div>
              <div style={{ position: "absolute", top: "50%", left: "50%", transform: "translate(-50%,-50%)" }}>
                <svg width="16" height="20" viewBox="0 0 24 32" fill="#EF4444"><path d="M12 0C5.4 0 0 5.4 0 12c0 9 12 20 12 20s12-11 12-20C24 5.4 18.6 0 12 0zm0 16a4 4 0 110-8 4 4 0 010 8z" /></svg>
              </div>
            </div>
          </div>
          <p style={{ fontSize: 12.5, color: T.textDim, marginBottom: 8, fontWeight: 500 }}>City &amp; Postal Code</p>
          <TextInput placeholder="Lahore, 54000" style={{ marginBottom: 12 }} />
          <p style={{ fontSize: 12.5, color: T.textDim, marginBottom: 8, fontWeight: 500 }}>Office phone</p>
          <div style={{ display: "grid", gridTemplateColumns: "1fr auto", gap: 8 }}>
            <TextInput placeholder="+92" icon={<IcoPhone c={T.textFaint} />} prefix="+92" />
            <div style={{
              display: "flex", alignItems: "center", gap: 6, padding: "0 12px",
              background: T.card, border: `1px solid ${T.border}`, borderRadius: T.r.md,
              cursor: "pointer", color: T.textDim, fontSize: 12.5, fontWeight: 500, flexShrink: 0,
            }}>
              Primary ▾
            </div>
          </div>
          <p style={{ fontSize: 12.5, color: T.textDim, marginTop: 14, marginBottom: 8, fontWeight: 500 }}>Map Preview</p>
          <div style={{
            height: 80, borderRadius: T.r.md, background: "linear-gradient(135deg,#1A3040,#162830)",
            border: `1px solid ${T.border}`, display: "flex", alignItems: "center", justifyContent: "center",
            color: T.textFaint, fontSize: 12, gap: 8,
          }}>
            <IcoPin c={T.textFaint} /> Enter address to preview map
          </div>
        </div>

        {/* Col 2: Fee Range */}
        <div style={{ background: T.card, border: `1px solid ${T.border}`, borderRadius: T.r.lg, padding: "18px 16px" }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 16 }}>
            <Label>Consultation Fee Range (PKR)</Label>
            <span style={{ fontSize: 18 }}>💰</span>
          </div>

          {/* Min fee slider */}
          <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 6 }}>
            <span style={{ fontSize: 12, color: T.textDim }}>Min: <b style={{ color: T.primary }}>PKR {minFee.toLocaleString()}</b></span>
            <span style={{ fontSize: 12, color: T.textFaint }}>Max: PKR 50,000</span>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 14 }}>
            <span style={{ fontSize: 12, color: T.textFaint }}>PKR</span>
            <input type="range" min={1000} max={MAX_FEE} step={500} value={minFee}
              onChange={e => setMinFee(+e.target.value)}
              style={{ flex: 1, accentColor: T.primary }}
            />
            <span style={{ fontSize: 12, color: T.textFaint }}>PKR</span>
          </div>

          {/* Max fee slider */}
          <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 6 }}>
            <span style={{ fontSize: 12, color: T.textDim }}>Maximum Fee</span>
            <span style={{ fontSize: 12, color: T.textFaint }}>Max: PKR 50,000</span>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 14 }}>
            <input type="range" min={1000} max={MAX_FEE} step={500} value={maxFee}
              onChange={e => setMaxFee(+e.target.value)}
              style={{ flex: 1, accentColor: T.primary }}
            />
          </div>

          {/* Quick select */}
          <div style={{ display: "flex", gap: 8, marginBottom: 18 }}>
            {[["<10k", "<10k", 9000], ["10k-25k", "10k-25k", 25000], [">25k", ">25k", 50000]].map(([k, label, val]) => (
              <button key={k} onClick={() => setMaxFee(val)} style={{
                flex: 1, padding: "8px 4px", borderRadius: T.r.sm, fontSize: 12, fontWeight: 600, cursor: "pointer",
                background: maxFee <= val ? T.primaryGlow : "rgba(22,40,48,0.8)",
                border: `1.5px solid ${maxFee <= val ? T.primary : T.border}`,
                color: maxFee <= val ? T.primary : T.textMuted,
              }}>{label}</button>
            ))}
          </div>

          <p style={{ fontSize: 12.5, color: T.textDim, marginBottom: 8, fontWeight: 500 }}>Explain your fees <span style={{ color: T.textFaint }}>(optional)</span></p>
          <textarea placeholder="e.g. Flat fee for consultations, hourly for litigation..." style={{
            width: "100%", height: 80, background: "rgba(22,40,48,0.8)", border: `1.5px solid ${T.border}`,
            borderRadius: T.r.md, padding: "10px 12px", color: T.text, fontSize: 13, outline: "none",
            fontFamily: "'Inter', sans-serif", resize: "none", boxSizing: "border-box",
          }} />
        </div>

        {/* Col 3: Working Schedule */}
        <div style={{ background: T.card, border: `1px solid ${T.border}`, borderRadius: T.r.lg, padding: "18px 16px" }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 16 }}>
            <Label>Working Schedule</Label>
            <IcoClock c={T.textMuted} />
          </div>

          <p style={{ fontSize: 12.5, color: T.textDim, marginBottom: 10, fontWeight: 600 }}>Working Days</p>
          <div style={{ display: "flex", gap: 6, marginBottom: 8 }}>
            {DAYS.map((d, i) => {
              const on = activeDays.includes(i);
              return (
                <button key={i} onClick={() => toggleDay(i)} style={{
                  width: 32, height: 32, borderRadius: T.r.sm, fontSize: 12, fontWeight: 700, cursor: "pointer",
                  background: on ? T.primary : "rgba(22,40,48,0.8)",
                  border: `1.5px solid ${on ? T.primary : T.border}`,
                  color: on ? T.bg : T.textMuted, transition: "all .15s",
                }}>{d}</button>
              );
            })}
          </div>
          <p style={{ fontSize: 11, color: T.textFaint, marginBottom: 18 }}>
            Selected: {activeDays.length} Days {activeDays.length === 5 && activeDays[0] === 0 ? "(M-F)" : ""}
          </p>

          <p style={{ fontSize: 12.5, color: T.textDim, marginBottom: 10, fontWeight: 600, display: "flex", alignItems: "center", gap: 6 }}>
            Office Hours <IcoClock c={T.textFaint} />
          </p>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginBottom: 8 }}>
            {["Open", "Close"].map(lb => (
              <div key={lb}>
                <p style={{ fontSize: 11, color: T.textFaint, marginBottom: 4 }}>{lb}</p>
                <div style={{ display: "flex", gap: 4 }}>
                  {["AM", "Min"].map(unit => (
                    <select key={unit} style={{
                      flex: 1, padding: "8px 6px", background: "rgba(22,40,48,0.9)",
                      border: `1px solid ${T.border}`, borderRadius: T.r.sm,
                      color: T.text, fontSize: 12, outline: "none",
                    }}>
                      <option>{unit}</option>
                    </select>
                  ))}
                </div>
              </div>
            ))}
          </div>

          <div style={{
            padding: "10px 14px", borderRadius: T.r.md, marginBottom: 8,
            background: T.primaryGlow2, border: `1px solid ${T.primary}30`,
            display: "flex", alignItems: "center", gap: 8,
          }}>
            <IcoClock c={T.primary} />
            <span style={{ fontSize: 12.5, color: T.textDim, fontWeight: 600 }}>Standard 9 AM – 5 PM</span>
          </div>
          <p style={{ fontSize: 11, color: T.textFaint, marginBottom: 16 }}>Selected: 9 AM – 5 PM (Mon-Fri)</p>

          <button style={{
            width: "100%", padding: "10px", borderRadius: T.r.md, cursor: "pointer",
            background: "rgba(22,40,48,0.5)", border: `1px solid ${T.border}`,
            color: T.textDim, fontSize: 12.5, fontWeight: 700, display: "flex",
            alignItems: "center", justifyContent: "space-between",
          }}>
            <span>Exception/Holiday Schedule</span> <span>▾</span>
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── Step 3: Workspace Ready (Submission) ────────────────────────────────────
function Step3({ onComplete }) {
  const [progress] = useState(15);

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      {/* Hero illustration area */}
      <div style={{
        borderRadius: T.r.xl, overflow: "hidden", marginBottom: 20,
        background: "linear-gradient(135deg,#0D2A30 0%,#142830 50%,#0D1E22 100%)",
        border: `1px solid ${T.border}`, padding: "28px 28px 20px", position: "relative",
        display: "flex", flexDirection: "column", alignItems: "center",
      }}>
        {/* Decorative circuit-like lines */}
        <div style={{ position: "absolute", inset: 0, opacity: 0.06, backgroundImage: "repeating-linear-gradient(0deg,transparent,transparent 40px,#2DD4BF 40px,#2DD4BF 41px),repeating-linear-gradient(90deg,transparent,transparent 40px,#2DD4BF 40px,#2DD4BF 41px)" }} />

        {/* Gavel icon in glow circle */}
        <div style={{ position: "relative", marginBottom: 16 }}>
          <div style={{ position: "absolute", inset: -24, borderRadius: "50%", background: T.primaryGlow2, filter: "blur(16px)" }} />
          <div style={{
            width: 80, height: 80, borderRadius: "50%", position: "relative",
            background: "linear-gradient(135deg,rgba(45,212,191,0.15),rgba(45,212,191,0.3))",
            border: `2px solid ${T.primary}60`, display: "flex", alignItems: "center", justifyContent: "center",
            boxShadow: `0 0 48px ${T.primaryGlow}`,
          }}>
            <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke={T.primary} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
              <circle cx="12" cy="11" r="3" />
            </svg>
          </div>
        </div>

        <h2 style={{
          fontFamily: "'Cormorant Garamond', serif",
          fontSize: 34, fontWeight: 700, color: T.text,
          letterSpacing: "-.03em", fontStyle: "italic", textAlign: "center", marginBottom: 12,
        }}>Your Profile is Complete &amp; Submitted</h2>

        <p style={{
          color: T.textMuted, fontSize: 13.5, lineHeight: 1.8,
          maxWidth: 680, textAlign: "center", marginBottom: 20,
        }}>
          Your complete profile has been securely submitted for verification. Admin review is underway, ensuring the highest level of professional standard. This check typically takes 24-48 hours. Research with AI, case management, and client collaboration features will activate immediately upon approval.
        </p>

        {/* 3 status cards */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 12, width: "100%", maxWidth: 740 }}>
          {[
            { icon: "📤", label: "Profile Submitted", sub: "Verification pending", badge: <IcoCheck c={T.primary} sz={16} />, color: T.primary },
            { icon: "🔒", label: "Security Active", sub: "AES-256 protected.", badge: <IcoCheck c={T.primary} sz={16} />, color: T.primary },
            { icon: "🚀", label: "Waiting to Launch", sub: "Awaiting Approval", badge: <span style={{ fontSize: 16 }}>🔍</span>, color: T.textMuted },
          ].map(({ icon, label, sub, badge, color }) => (
            <div key={label} style={{
              padding: "14px 16px", borderRadius: T.r.lg, background: "rgba(13,30,34,0.8)",
              border: `1px solid ${T.border}`, display: "flex", alignItems: "center", gap: 12,
            }}>
              <div style={{
                width: 42, height: 42, borderRadius: T.r.md,
                background: "rgba(45,212,191,0.08)", border: `1px solid ${T.border}`,
                display: "flex", alignItems: "center", justifyContent: "center", fontSize: 20, flexShrink: 0,
              }}>{icon}</div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <p style={{ fontSize: 13.5, fontWeight: 700, color: T.text, marginBottom: 2 }}>{label}</p>
                <p style={{ fontSize: 11.5, color: T.textFaint }}>{sub}</p>
              </div>
              <div style={{ flexShrink: 0 }}>{badge}</div>
            </div>
          ))}
        </div>
      </div>

      {/* Bottom row */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr auto", gap: 12 }}>
        {/* Approval progress card */}
        <div style={{
          padding: "16px 20px", borderRadius: T.r.lg,
          background: T.card, border: `1px solid ${T.border}`,
        }}>
          <p style={{ fontSize: 14, fontWeight: 700, color: T.text, marginBottom: 10 }}>
            Approval Status: <span style={{ color: T.textDim }}>Reviewing Your Details.</span>
          </p>
          <div style={{ height: 6, borderRadius: 99, background: T.borderLight, overflow: "hidden", marginBottom: 8 }}>
            <div style={{ width: `${progress}%`, height: "100%", borderRadius: 99, background: T.grad1, transition: "width 1s ease" }} />
          </div>
          <p style={{ fontSize: 12, color: T.textFaint }}>{progress}% Admin verification (Step 1/2) in progress.</p>
        </div>

        {/* Contact support card */}
        <div style={{
          padding: "16px 20px", borderRadius: T.r.lg,
          background: T.card, border: `1px solid ${T.border}`,
          display: "flex", alignItems: "center", gap: 14, minWidth: 280,
        }}>
          <div style={{ width: 36, height: 36, borderRadius: T.r.sm, background: T.primaryGlow2, display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
            <IcoMail c={T.primary} />
          </div>
          <p style={{ fontSize: 12.5, color: T.textMuted, lineHeight: 1.5 }}>
            Questions? Need help with your application?{" "}
            <span style={{ color: T.primary, fontWeight: 600, cursor: "pointer" }}>Contact Admin Support.</span>
          </p>
        </div>
      </div>

      <p style={{ fontSize: 11, color: T.textFaint, textAlign: "center", marginTop: 10 }}>
        *This typically takes 24-48 hours.
      </p>
    </div>
  );
}

// ─── Progress ring ────────────────────────────────────────────────────────────
function ProgressRing({ step, total }) {
  const pct = step / total;
  const r = 18, circ = 2 * Math.PI * r;
  return (
    <svg width="44" height="44" style={{ transform: "rotate(-90deg)" }}>
      <circle cx="22" cy="22" r={r} fill="none" stroke={T.border} strokeWidth="3" />
      <circle cx="22" cy="22" r={r} fill="none" stroke={T.primary} strokeWidth="3"
        strokeDasharray={circ} strokeDashoffset={circ * (1 - pct)}
        strokeLinecap="round" style={{ transition: "stroke-dashoffset .5s ease" }} />
    </svg>
  );
}

// ─── Nav Bar ──────────────────────────────────────────────────────────────────
function NavBar({ step, total, isLast, onBack, onSkip, onNext, onComplete }) {
  return (
    <div style={{
      display: "flex", justifyContent: "space-between", alignItems: "center",
      padding: "12px 20px", marginTop: 14, borderRadius: T.r.xl,
      border: `1px solid ${T.border}`,
      background: "rgba(13,30,34,0.92)", backdropFilter: "blur(16px)",
      boxShadow: T.shadowSm,
    }}>
      {/* Back button */}
      <button
        onClick={onBack} disabled={step === 0}
        style={{
          display: "flex", alignItems: "center", gap: 8, padding: "10px 22px",
          borderRadius: 99, background: "transparent",
          border: `1.5px solid ${step === 0 ? T.border + "40" : T.border}`,
          color: step === 0 ? T.textFaint : T.textDim, fontSize: 13, fontWeight: 600,
          cursor: step === 0 ? "default" : "pointer",
          opacity: step === 0 ? 0.35 : 1, transition: "opacity .2s",
        }}>
        <IcoArrowL c={step === 0 ? T.textFaint : T.textDim} /> Back
      </button>

      {/* Center: progress ring + page label + skip + action */}
      <div style={{ display: "flex", alignItems: "center", gap: 14 }}>

        {/* Progress ring with step fraction inside */}
        <div style={{ position: "relative", display: "flex", alignItems: "center", justifyContent: "center" }}>
          <ProgressRing step={step + 1} total={total} />
          <span style={{ position: "absolute", fontSize: 10, fontWeight: 700, color: T.primary }}>
            {step + 1}/{total}
          </span>
        </div>

        {/* "Page X / Y" text label */}
        {isLast ? (
          /* Last step: show completion badge */
          <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 2 }}>
            <span style={{ fontSize: 13, fontWeight: 700, color: T.text }}>
              {total}/{total} Step Complete
            </span>
            <span style={{
              fontSize: 10, fontWeight: 700, color: "#F0A500",
              background: "rgba(240,165,0,0.12)", padding: "2px 10px",
              borderRadius: 99, border: "1px solid rgba(240,165,0,0.3)",
              letterSpacing: ".06em",
            }}>Pending Approval</span>
          </div>
        ) : (
          <span style={{ fontSize: 13, fontWeight: 600, color: T.textMuted }}>
            Page {step + 1} / {total}
          </span>
        )}

        {/* Skip button — hidden on last step */}
        {!isLast && (
          <button onClick={onSkip} style={{
            padding: "10px 18px", borderRadius: 99, background: "transparent",
            border: `1.5px solid ${T.border}`, color: T.textMuted,
            fontSize: 13, fontWeight: 500, cursor: "pointer",
          }}>Skip this step</button>
        )}

        {/* Primary action */}
        {isLast ? (
          <button onClick={onComplete} style={{
            padding: "10px 28px", borderRadius: 99, background: T.grad1,
            border: "none", color: T.bg, fontSize: 13.5, fontWeight: 700,
            display: "flex", alignItems: "center", gap: 8, cursor: "pointer",
            boxShadow: `0 6px 24px ${T.primaryGlow}`,
          }}>
            Monitor Progress <IcoArrowR c={T.bg} />
          </button>
        ) : (
          <button onClick={onNext} style={{
            padding: "10px 28px", borderRadius: 99, background: T.grad1,
            border: "none", color: T.bg, fontSize: 13.5, fontWeight: 700,
            display: "flex", alignItems: "center", gap: 8, cursor: "pointer",
            boxShadow: `0 6px 24px ${T.primaryGlow}`,
          }}>
            Continue <IcoArrowR c={T.bg} />
            <span style={{ fontSize: 16, marginLeft: -4 }}>✨</span>
          </button>
        )}
      </div>
    </div>
  );
}

// ─── Main Onboarding Component ────────────────────────────────────────────────
export function Onboarding({ t, role, onComplete }) {
  const [step, setStep] = useState(0);
  const [specs, setSpecs] = useState([]);
  const total = LSTEPS.length;
  const isLast = step === total - 1;

  // Keep lawyer onboarding aligned with the active app theme.
  T = t || DARK;

  useEffect(() => {
    if (role !== "lawyer") onComplete();
  }, [role, onComplete]);
  if (role !== "lawyer") return null;

  const styles = `
    @import url('https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,600;0,700;1,600;1,700&family=Inter:wght@400;500;600;700&display=swap');
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { background: ${T.bg}; }
    button { font-family: 'Inter', sans-serif; }
    input, select, textarea { font-family: 'Inter', sans-serif; }
    input[type=range] { height: 4px; cursor: pointer; }
    ::-webkit-scrollbar { width: 4px; }
    ::-webkit-scrollbar-track { background: ${T.bg}; }
    ::-webkit-scrollbar-thumb { background: ${T.border}; border-radius: 2px; }
  `;

  return (
    <div style={{ display: "flex", height: "100vh", overflow: "hidden", background: T.bg, fontFamily: "'Inter', sans-serif" }}>
      <style>{styles}</style>

      {/* Icon sidebar (always visible) */}
      <IconSidebar step={step} />

      {/* Step sidebar (wider, textual) */}
      <StepSidebar step={step} />

      {/* Main content */}
      <div style={{
        flex: 1, display: "flex", flexDirection: "column", height: "100vh",
        overflow: "hidden", padding: "24px 20px 18px",
        background: T.bg,
      }}>
        <div style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column", width: "100%" }}>
          <div style={{ flex: 1, minHeight: 0, overflowY: "auto", overflowX: "hidden" }}>
            {step === 0 && <Step0 specs={specs} setSpecs={setSpecs} />}
            {step === 1 && <Step1 />}
            {step === 2 && <Step2 />}
            {step === 3 && <Step3 onComplete={onComplete} />}
          </div>
          <NavBar
            step={step} total={total} isLast={isLast}
            onBack={() => setStep(s => Math.max(0, s - 1))}
            onSkip={() => setStep(s => Math.min(total - 1, s + 1))}
            onNext={() => setStep(s => Math.min(total - 1, s + 1))}
            onComplete={onComplete}
          />
        </div>
      </div>
    </div>
  );
}

export const OnboardingPage = Onboarding;