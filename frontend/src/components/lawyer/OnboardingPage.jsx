import { useState, useRef } from "react";
import { DARK } from "./theme.js";

export const ONBOARDED_KEY = "lawyer_onboarded";

// ─── Theme ────────────────────────────────────────────────────────────────────
const T = {
  bg: DARK.bg,
  sidebar: DARK.surface,
  card: DARK.card,
  cardBorder: DARK.border,
  primary: DARK.primary,
  primaryLight: DARK.secondary,
  primaryGlow: DARK.primaryGlow,
  primaryGlow2: DARK.primaryGlow2,
  accent: DARK.primaryDim,
  text: DARK.text,
  textMuted: DARK.textMuted,
  textFaint: DARK.textFaint,
  border: DARK.border,
  inputBg: DARK.inputBg,
  inputBorder: DARK.border,
  success: DARK.success,
  warning: DARK.warn,
  danger: DARK.danger,
  r: { ...DARK.r, xl: 20 },
};

// ─── Icons ────────────────────────────────────────────────────────────────────
const Ic = {
  shield: (c=T.primary) => <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke={c} strokeWidth="2"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>,
  user: (c=T.primary) => <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke={c} strokeWidth="2"><circle cx="12" cy="8" r="4"/><path d="M4 20c0-4 3.6-7 8-7s8 3 8 7"/></svg>,
  cert: (c=T.primary) => <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke={c} strokeWidth="2"><rect x="3" y="4" width="18" height="14" rx="2"/><path d="M8 10h8M8 14h5"/></svg>,
  clock: (c=T.primary) => <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke={c} strokeWidth="2"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 3"/></svg>,
  camera: (c=T.primary) => <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke={c} strokeWidth="2"><path d="M23 19a2 2 0 01-2 2H3a2 2 0 01-2-2V8a2 2 0 012-2h4l2-3h6l2 3h4a2 2 0 012 2z"/><circle cx="12" cy="13" r="4"/></svg>,
  map: (c=T.primary) => <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke={c} strokeWidth="2"><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0118 0z"/><circle cx="12" cy="10" r="3"/></svg>,
  phone: (c=T.primary) => <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke={c} strokeWidth="2"><path d="M22 16.92v3a2 2 0 01-2.18 2 19.79 19.79 0 01-8.63-3.07A19.5 19.5 0 013.07 10.8a19.79 19.79 0 01-3.07-8.67A2 2 0 012 0h3a2 2 0 012 1.72c.127.96.361 1.903.7 2.81a2 2 0 01-.45 2.11L6.91 7.91a16 16 0 006.13 6.13l1.27-1.27a2 2 0 012.11-.45c.907.339 1.85.573 2.81.7A2 2 0 0122 16.92z"/></svg>,
  money: (c=T.primary) => <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke={c} strokeWidth="2"><rect x="1" y="4" width="22" height="16" rx="2"/><path d="M1 10h22"/></svg>,
  check: (c=T.success,s=16) => <svg width={s} height={s} viewBox="0 0 24 24" fill="none" stroke={c} strokeWidth="2.5"><path d="M20 6L9 17l-5-5" strokeLinecap="round" strokeLinejoin="round"/></svg>,
  upload: (c=T.primary) => <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke={c} strokeWidth="2"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4M17 8l-5-5-5 5M12 3v12"/></svg>,
  download: (c=T.primary) => <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke={c} strokeWidth="2"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4M7 10l5 5 5-5M12 15V3"/></svg>,
  arrow: (dir="right",c="#fff") => <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke={c} strokeWidth="2.5" strokeLinecap="round">{dir==="right"?<path d="M5 12h14M12 5l7 7-7 7"/>:<path d="M19 12H5M12 19l-7-7 7-7"/>}</svg>,
  home: (c=T.primary) => <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke={c} strokeWidth="2"><path d="M3 9l9-7 9 7v11a2 2 0 01-2 2H5a2 2 0 01-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/></svg>,
  star: (c=T.textMuted) => <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke={c} strokeWidth="2"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>,
  target: (c=T.primary) => <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke={c} strokeWidth="2"><circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/></svg>,
  doc: (c=T.primary) => <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke={c} strokeWidth="2"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>,
  rocket: (c=T.primary) => <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke={c} strokeWidth="2"><path d="M4.5 16.5c-1.5 1.26-2 5-2 5s3.74-.5 5-2c.71-.84.7-2.13-.09-2.91a2.18 2.18 0 00-2.91-.09zM12 15l-3-3a22 22 0 012-3.95A12.88 12.88 0 0122 2c0 2.72-.78 7.5-6 11a22.35 22.35 0 01-4 2z"/><path d="M9 12H4s.55-3.03 2-4c1.62-1.08 5 0 5 0M15 12v5s3.03-.55 4-2c1.08-1.62 0-5 0-5"/></svg>,
  lock: (c=T.primary) => <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke={c} strokeWidth="2"><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0110 0v4"/></svg>,
  briefcase: (c=T.textMuted) => <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke={c} strokeWidth="2"><rect x="2" y="7" width="20" height="14" rx="2"/><path d="M16 7V5a2 2 0 00-2-2h-4a2 2 0 00-2 2v2M12 12v4M8 12v4"/></svg>,
  hammer: (c=T.textMuted) => <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke={c} strokeWidth="2"><path d="M15 12l-8.5 8.5a2.12 2.12 0 01-3-3L12 9"/><path d="M17.64 15L22 10.64"/><path d="M20.91 11.7l-1.25-1.25c-.6-.6-.93-1.4-.93-2.25v-.86L16.01 4.6a5.56 5.56 0 00-3.94-1.64H9l.92.82A6.18 6.18 0 0112 8.4v1.56l2 2h2.47l2.26 1.91z"/></svg>,
};

// ─── Sidebar Steps ─────────────────────────────────────────────────────────────
const STEPS = [
  { label: "Professional Profile", sub: "Name, license & specialization", icon: Ic.hammer },
  { label: "Credentials & Photo", sub: "Documents & profile picture", icon: Ic.doc },
  { label: "Office & Availability", sub: "Location, fees & working hours", icon: Ic.map },
  { label: "Workspace Ready", sub: "Your profile is complete", icon: Ic.star },
];

const SPECS_CORE = ["Corporate", "Criminal", "Family", "Civil Litigation", "Real Estate", "Immigration"];
const SPECS_EXTRA = ["Environment Law", "Intellectual Property", "Arbitration"];
const DAYS = ["M","T","W","T","F","S","S"];
const DAY_FULL = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"];
const CONTENT_PAD = 18;

// ─── Shared UI Atoms ──────────────────────────────────────────────────────────
const Label = ({ children }) => (
  <p style={{ fontSize: 10, fontWeight: 700, color: T.textMuted, textTransform: "uppercase", letterSpacing: ".1em", marginBottom: 6 }}>
    {children}
  </p>
);

const Input = ({ placeholder, icon, type = "text", value, onChange }) => (
  <div style={{ position: "relative", marginBottom: 2 }}>
    {icon && <span style={{ position: "absolute", left: 12, top: "50%", transform: "translateY(-50%)", opacity: .7 }}>{icon}</span>}
    <input
      type={type}
      placeholder={placeholder}
      value={value || ""}
      onChange={e => onChange && onChange(e.target.value)}
      style={{
        width: "100%", boxSizing: "border-box",
        background: T.inputBg, border: `1.5px solid ${T.inputBorder}`, borderRadius: T.r.md,
        color: T.text, fontSize: 13.5, padding: icon ? "10px 12px 10px 38px" : "10px 14px",
        outline: "none", fontFamily: "inherit",
        transition: "border-color .2s",
      }}
      onFocus={e => (e.target.style.borderColor = T.primary)}
      onBlur={e => (e.target.style.borderColor = T.inputBorder)}
    />
  </div>
);

const Textarea = ({ placeholder, rows = 4, value, onChange }) => (
  <textarea
    rows={rows}
    placeholder={placeholder}
    value={value || ""}
    onChange={e => onChange && onChange(e.target.value)}
    style={{
      width: "100%", boxSizing: "border-box", resize: "vertical",
      background: T.inputBg, border: `1.5px solid ${T.inputBorder}`, borderRadius: T.r.md,
      color: T.text, fontSize: 13, padding: "10px 14px",
      outline: "none", fontFamily: "inherit",
    }}
    onFocus={e => (e.target.style.borderColor = T.primary)}
    onBlur={e => (e.target.style.borderColor = T.inputBorder)}
  />
);

const CardPanel = ({ title, icon, children, style = {} }) => (
  <div style={{
    background: T.card, border: `1.5px solid ${T.cardBorder}`, borderRadius: T.r.lg,
    padding: "18px 20px", flex: 1, display: "flex", flexDirection: "column", gap: 14, ...style
  }}>
    {title && (
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 2 }}>
        {icon && <span>{icon}</span>}
        <span style={{ fontSize: 15, fontWeight: 700, color: T.text }}>{title}</span>
      </div>
    )}
    {children}
  </div>
);

const Chip = ({ label, selected, onClick }) => (
  <span onClick={onClick} style={{
    display: "inline-flex", alignItems: "center", gap: 5, cursor: "pointer",
    fontSize: 12, fontWeight: 500, padding: "7px 14px", borderRadius: 99,
    border: `1.5px solid ${selected ? T.primary : T.cardBorder}`,
    background: selected ? T.primaryGlow : "transparent",
    color: selected ? T.primaryLight : T.textMuted,
    transition: "all .18s",
  }}>
    {selected && Ic.check(T.primary, 10)}
    {label}
  </span>
);

const GlowBtn = ({ children, onClick, disabled, style = {} }) => (
  <button onClick={onClick} disabled={disabled} style={{
    background: `linear-gradient(135deg, ${T.primary}, ${T.primaryLight})`,
    border: "none", borderRadius: T.r.md, color: "#fff",
    fontSize: 14, fontWeight: 700, padding: "11px 28px",
    cursor: disabled ? "not-allowed" : "pointer", opacity: disabled ? .5 : 1,
    display: "inline-flex", alignItems: "center", gap: 8,
    boxShadow: `0 0 20px rgba(13,148,136,0.35)`,
    transition: "all .2s", ...style,
  }}>
    {children}
  </button>
);

const OutlineBtn = ({ children, onClick }) => (
  <button onClick={onClick} style={{
    background: "transparent", border: `1.5px solid ${T.cardBorder}`,
    borderRadius: T.r.md, color: T.textMuted, fontSize: 14, fontWeight: 600,
    padding: "11px 22px", cursor: "pointer", display: "inline-flex", alignItems: "center", gap: 8,
  }}>
    {children}
  </button>
);

// ─── Sidebar ──────────────────────────────────────────────────────────────────
function Sidebar({ step, submitted }) {
  return (
    <div style={{
      width: 236, minWidth: 220, background: T.sidebar,
      borderRight: `1px solid ${T.border}`, display: "flex", flexDirection: "column", flexShrink: 0,
    }}>
      {/* Header */}
      <div style={{ padding: "20px 18px 16px", borderBottom: `1px solid ${T.border}` }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 12 }}>
          <img src="/logo.png" alt="AttorneyAI"
            style={{ width: 42, height: 42, objectFit: "contain", filter: `drop-shadow(0 1px 8px ${T.primaryGlow})`, flexShrink: 0 }} />
          <span style={{ fontSize: 16, fontWeight: 800, color: T.text, letterSpacing: "-.02em", fontFamily: "Georgia, serif" }}>
            Attorney<span style={{ color: T.primary }}>AI</span>
          </span>
        </div>
        <p style={{ fontSize: 13, fontWeight: 700, color: T.text }}>Profile Setup</p>
        <p style={{ fontSize: 11, color: T.textMuted, marginTop: 2 }}>Complete your profile to go live</p>
      </div>

      {/* Steps */}
      <div style={{ padding: "22px 18px 0", flex: 1 }}>
        {STEPS.map((s, i) => {
          const done = submitted ? true : i < step;
          const active = !submitted && i === step;
          const isLast = i === STEPS.length - 1;
          const iconColor = done ? "#fff" : active ? T.primary : T.textMuted;

          return (
            <div key={i} style={{ display: "flex", gap: 14 }}>
              {/* Left column: indicator + connector */}
              <div style={{ display: "flex", flexDirection: "column", alignItems: "center", flexShrink: 0, width: 36 }}>
                <div style={{
                  width: 36, height: 36, borderRadius: 10, flexShrink: 0,
                  display: "flex", alignItems: "center", justifyContent: "center",
                  background: done
                    ? `linear-gradient(135deg, ${T.primary}, ${T.primaryLight})`
                    : active ? T.primaryGlow2 : T.inputBg,
                  border: done ? "none" : `1.5px solid ${active ? T.primary : T.border}`,
                  boxShadow: done ? `0 2px 12px ${T.primary}50` : active ? `0 0 14px ${T.primary}30` : "none",
                  transition: "all .25s",
                }}>
                  {done ? Ic.check("#fff", 14) : s.icon(iconColor)}
                </div>
                {!isLast && (
                  <div style={{
                    width: 2, height: 24, borderRadius: 1,
                    background: done ? T.primary : T.border,
                    opacity: done ? 0.45 : 0.3,
                    margin: "5px 0",
                    transition: "background .25s",
                  }} />
                )}
              </div>

              {/* Right column: text */}
              <div style={{ paddingBottom: isLast ? 0 : 16, paddingTop: 5, minWidth: 0 }}>
                <p style={{
                  fontSize: 13, fontWeight: 700,
                  color: done || active ? T.text : T.textMuted,
                  letterSpacing: "-.01em", lineHeight: 1.15,
                }}>
                  {s.label}
                </p>
                <p style={{
                  marginTop: 4, fontSize: 11,
                  color: active ? T.textMuted : T.textFaint,
                  lineHeight: 1.3,
                }}>
                  {s.sub}
                </p>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ─── Spec icon SVGs ───────────────────────────────────────────────────────────
const SpecIcons = {
  Corporate: (c) => <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke={c} strokeWidth="1.8"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg>,
  Criminal:  (c) => <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke={c} strokeWidth="1.8"><path d="M14.7 6.3a1 1 0 000 1.4l1.6 1.6a1 1 0 001.4 0l3.77-3.77a6 6 0 01-7.94 7.94l-6.91 6.91a2.12 2.12 0 01-3-3l6.91-6.91a6 6 0 017.94-7.94l-3.76 3.76z"/></svg>,
  Family:    (c) => <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke={c} strokeWidth="1.8"><path d="M3 9l9-7 9 7v11a2 2 0 01-2 2H5a2 2 0 01-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/></svg>,
  "Civil Litigation": (c) => <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke={c} strokeWidth="1.8"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18M9 21V9"/></svg>,
  "Real Estate": (c) => <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke={c} strokeWidth="1.8"><rect x="2" y="7" width="20" height="14" rx="1"/><path d="M16 7V5a2 2 0 00-2-2h-4a2 2 0 00-2 2v2"/><line x1="12" y1="12" x2="12" y2="16"/><line x1="10" y1="14" x2="14" y2="14"/></svg>,
  Immigration: (c) => <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke={c} strokeWidth="1.8"><path d="M3 12h18M3 12l4-4M3 12l4 4M21 12l-4-4M21 12l-4 4"/></svg>,
  "Environment Law": (c) => <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke={c} strokeWidth="1.8"><path d="M17 8C8 10 5.9 16.17 3.82 19.15A2 2 0 005.49 22h13a2 2 0 001.92-2.56C19 16 19 8 17 8z"/><path d="M17 8C17 8 17 2 12 2c0 0 0 6-5 8"/></svg>,
  "Intellectual Property": (c) => <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke={c} strokeWidth="1.8"><circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 015.83 1c0 2-3 3-3 3M12 17h.01"/></svg>,
  Arbitration: (c) => <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke={c} strokeWidth="1.8"><path d="M15 12l-8.5 8.5a2.12 2.12 0 01-3-3L12 9M18 9l3-3M17 3l4 4M3 14l4 4"/></svg>,
};

// ─── Step 1: Professional Profile ─────────────────────────────────────────────
function StepProfessional({ onNext }) {
  const [name, setName] = useState("Adv. Ahmad Khan");
  const [exp, setExp] = useState("");
  const [license, setLicense] = useState("BKP/PNJ/2019");
  const [council, setCouncil] = useState("Punjab Bar Council");
  const [coreSpecs, setCoreSpecs] = useState(["Corporate"]);
  const [extraSpecs, setExtraSpecs] = useState(["Intellectual Property"]);

  const togCore = (s) => setCoreSpecs(p => p.includes(s) ? p.filter(x => x !== s) : p.length < 3 ? [...p, s] : p);
  const togExtra = (s) => setExtraSpecs(p => p.includes(s) ? p.filter(x => x !== s) : [...p, s]);

  // Icon grid card for specializations
  const SpecCard = ({ label, selected, onClick, size = "core" }) => {
    const IconFn = SpecIcons[label];
    const iconColor = selected ? T.primaryLight : T.textMuted;
    return (
      <div onClick={onClick} style={{
        background: selected ? T.primaryGlow : T.inputBg,
        border: `1.5px solid ${selected ? T.primary : T.cardBorder}`,
        borderRadius: T.r.md, cursor: "pointer",
        display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center",
        gap: 6, padding: "10px 6px", position: "relative",
        transition: "all .18s",
        minHeight: size === "core" ? 72 : 68,
      }}>
        {selected && (
          <div style={{
            position: "absolute", top: 4, right: 4, width: 16, height: 16,
            borderRadius: "50%", background: T.primary,
            display: "flex", alignItems: "center", justifyContent: "center",
          }}>
            {Ic.check("#fff", 10)}
          </div>
        )}
        {IconFn && IconFn(iconColor)}
        <span style={{ fontSize: 11, fontWeight: 600, color: selected ? T.primaryLight : T.textMuted, textAlign: "center", lineHeight: 1.3 }}>{label}</span>
      </div>
    );
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", flex: 1, overflow: "hidden" }}>
      <div style={{ padding: `${CONTENT_PAD}px ${CONTENT_PAD}px 0`, flex: 1, minHeight: 0, overflow: "auto", display: "flex", flexDirection: "column" }}>

        {/* ── Step header ── */}
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 14 }}>
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 4 }}>
              <div style={{
                width: 28, height: 28, borderRadius: 8, flexShrink: 0,
                background: `linear-gradient(135deg, ${T.primary}, ${T.primaryLight})`,
                display: "flex", alignItems: "center", justifyContent: "center",
                boxShadow: `0 0 14px ${T.primaryGlow}`,
              }}>
                {Ic.user(T.bg)}
              </div>
              <h2 style={{ fontSize: 22, fontWeight: 800, color: T.text, margin: 0, letterSpacing: "-.02em" }}>
                Professional Profile
              </h2>
              <div style={{
                display: "flex", alignItems: "center", gap: 5,
                background: T.primaryGlow2, border: `1px solid ${T.primary}40`,
                borderRadius: 99, padding: "4px 12px",
              }}>
                <span style={{ width: 6, height: 6, borderRadius: "50%", background: T.primary, display: "inline-block" }} />
                <span style={{ fontSize: 11, fontWeight: 600, color: T.primaryLight }}>Step 1 of 4</span>
              </div>
            </div>
            <p style={{ fontSize: 12.5, color: T.textMuted, margin: 0, lineHeight: 1.5 }}>
              Tell clients who you are — your name, bar license, and areas of practice.
            </p>
          </div>
          <div style={{
            display: "flex", alignItems: "center", gap: 8,
            background: T.card, border: `1.5px solid ${T.cardBorder}`,
            borderRadius: T.r.lg, padding: "8px 14px",
          }}>
            <svg width="32" height="32" viewBox="0 0 36 36">
              <circle cx="18" cy="18" r="14" fill="none" stroke={T.border} strokeWidth="3"/>
              <circle cx="18" cy="18" r="14" fill="none" stroke={T.primary} strokeWidth="3"
                strokeDasharray={`${(1/4)*88} 88`} strokeLinecap="round" transform="rotate(-90 18 18)"/>
              <text x="18" y="22" textAnchor="middle" fill={T.text} fontSize="9" fontWeight="700">1/4</text>
            </svg>
            <div>
              <p style={{ fontSize: 11, fontWeight: 700, color: T.text, margin: 0 }}>25% Done</p>
              <p style={{ fontSize: 10, color: T.textFaint, margin: 0 }}>3 steps remaining</p>
            </div>
          </div>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gridTemplateRows: "1fr", gap: 14, flex: 1 }}>

          {/* ── Identity Details ── */}
          <div style={{
            background: T.card, border: `1.5px solid ${T.cardBorder}`, borderRadius: T.r.lg,
            padding: "20px 20px", display: "flex", flexDirection: "column", gap: 16,
          }}>
            {/* Card header */}
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <div style={{ width: 32, height: 32, borderRadius: 8, background: T.primaryGlow, display: "flex", alignItems: "center", justifyContent: "center" }}>
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke={T.primary} strokeWidth="2"><path d="M20 21v-2a4 4 0 00-4-4H8a4 4 0 00-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>
              </div>
              <span style={{ fontSize: 17, fontWeight: 800, color: T.text }}>Identity Details</span>
            </div>
            <div>
              <Label>Full Name</Label>
              <Input placeholder="Adv. Ahmad Khan" icon={Ic.user(T.textFaint)} value={name} onChange={setName} />
            </div>
            <div>
              <Label>Years of Experience</Label>
              <Input type="number" placeholder="e.g. 8" icon={Ic.clock(T.textFaint)} value={exp} onChange={setExp} />
              <p style={{ fontSize: 11, color: T.textFaint, marginTop: 6 }}>This information is used for matching.</p>
            </div>
          </div>

          {/* ── License Information ── */}
          <div style={{
            background: T.card, border: `1.5px solid ${T.cardBorder}`, borderRadius: T.r.lg,
            padding: "20px 20px", display: "flex", flexDirection: "column", gap: 14,
          }}>
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <div style={{ width: 32, height: 32, borderRadius: 8, background: T.primaryGlow, display: "flex", alignItems: "center", justifyContent: "center" }}>
                {Ic.shield(T.primary)}
              </div>
              <span style={{ fontSize: 17, fontWeight: 800, color: T.text }}>License Information</span>
            </div>
            <div>
              <Label>Bar Council</Label>
              <div style={{ position: "relative" }}>
                <span style={{ position: "absolute", left: 12, top: "50%", transform: "translateY(-50%)" }}>
                  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke={T.textFaint} strokeWidth="2"><path d="M15 12l-8.5 8.5a2.12 2.12 0 01-3-3L12 9M18 9l3-3M17 3l4 4"/></svg>
                </span>
                <input value={council} onChange={e => setCouncil(e.target.value)} style={{
                  width:"100%", boxSizing:"border-box", background: T.inputBg,
                  border: `1.5px solid ${T.inputBorder}`, borderRadius: T.r.md,
                  color: T.text, fontSize: 13.5, padding: "10px 12px 10px 36px",
                  outline: "none", fontFamily: "inherit",
                }} />
              </div>
            </div>
            <div>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
                <Label>Bar License No.</Label>
                <span style={{ fontSize: 11, color: T.success, display: "flex", alignItems: "center", gap: 4, fontWeight: 600 }}>
                  <svg width="14" height="14" viewBox="0 0 24 24" fill={T.success} stroke="none"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 14.5l-4-4 1.41-1.41L10 13.67l6.59-6.59L18 8.5l-8 8z"/></svg>
                  Verified
                </span>
              </div>
              <div style={{ position: "relative" }}>
                <span style={{ position: "absolute", left: 12, top: "50%", transform: "translateY(-50%)" }}>
                  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke={T.textFaint} strokeWidth="2"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
                </span>
                <input value={`VERIFIED (${license})`} readOnly style={{
                  width:"100%", boxSizing:"border-box", background: T.inputBg,
                  border: `1.5px solid ${T.inputBorder}`, borderRadius: T.r.md,
                  color: T.text, fontSize: 13, padding: "10px 12px 10px 36px",
                  outline: "none", fontFamily: "inherit",
                }} />
              </div>
            </div>
            <div style={{
              display: "flex", alignItems: "center", gap: 8,
              background: "rgba(13,148,136,0.06)", border: `1px solid rgba(13,148,136,0.2)`,
              borderRadius: T.r.sm, padding: "9px 12px",
            }}>
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke={T.primary} strokeWidth="2"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
              <span style={{ fontSize: 11.5, color: T.primaryLight, fontWeight: 600 }}>DOCUMENT VERIFIED - PENDING BAR APPROVAL</span>
            </div>
            <button style={{
              background: T.card, border: `1.5px solid ${T.border}`, borderRadius: T.r.md,
              color: T.textMuted, fontSize: 13, fontWeight: 700, padding: "11px",
              cursor: "pointer", letterSpacing: ".12em", textTransform: "uppercase",
            }}>VERIFY</button>
          </div>

          {/* ── Primary Specializations ── */}
          <div style={{
            background: T.card, border: `1.5px solid ${T.cardBorder}`, borderRadius: T.r.lg,
            padding: "20px 20px", display: "flex", flexDirection: "column", gap: 14,
          }}>
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <div style={{ width: 32, height: 32, borderRadius: 8, background: T.primaryGlow, display: "flex", alignItems: "center", justifyContent: "center" }}>
                {Ic.target(T.primary)}
              </div>
              <span style={{ fontSize: 17, fontWeight: 800, color: T.text }}>Primary Specializations</span>
            </div>

            {/* Core — 2×3 grid */}
            <div>
              <Label>Core Specializations (Select up to 3)</Label>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 7, marginTop: 8 }}>
                {SPECS_CORE.map(s => (
                  <SpecCard key={s} label={s} selected={coreSpecs.includes(s)} onClick={() => togCore(s)} size="core" />
                ))}
              </div>
            </div>

            {/* Additional — 1×3 */}
            <div>
              <Label>Additional Areas</Label>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 7, marginTop: 8 }}>
                {SPECS_EXTRA.map(s => (
                  <SpecCard key={s} label={s} selected={extraSpecs.includes(s)} onClick={() => togExtra(s)} size="extra" />
                ))}
              </div>
            </div>
          </div>

        </div>
      </div>

      {/* Inline nav — compact, no wasted space */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: `6px ${CONTENT_PAD}px 10px` }}>
        <span style={{ fontSize: 11, color: T.textFaint, fontWeight: 700 }}>1/4</span>
        <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
          <button onClick={() => {}} style={{
            background: "transparent", border: `1px solid ${T.border}`, borderRadius: T.r.sm,
            color: T.textMuted, fontSize: 11, padding: "5px 10px", cursor: "pointer",
            display: "flex", alignItems: "center", gap: 4,
          }}>{Ic.arrow("left", T.textFaint)} Back</button>
          <button style={{ background: "transparent", border: "none", color: T.textMuted, fontSize: 11, cursor: "pointer" }}>Skip</button>
          <GlowBtn onClick={onNext} style={{ padding: "7px 16px", fontSize: 12 }}>Continue {Ic.arrow("right")}</GlowBtn>
        </div>
      </div>
    </div>
  );
}

// ─── Step 2: Credentials & Photo ──────────────────────────────────────────────
function StepCredentials({ onNext, onBack }) {
  const fileRef = useRef();
  const [photo, setPhoto] = useState(null);
  const [eduReady] = useState(true);
  const [profReady] = useState(true);

  const handlePhoto = (e) => {
    const f = e.target.files?.[0];
    if (f) setPhoto(URL.createObjectURL(f));
  };

  const CredCard = ({ svgIcon, title, sub1, sub2, uploaded, fileName }) => (
    <div style={{
      flex: 1, background: T.card, border: `1.5px solid ${T.cardBorder}`,
      borderRadius: T.r.lg, padding: "18px 16px 16px",
      display: "flex", flexDirection: "column",
    }}>
      {/* Icon — fixed height zone */}
      <div style={{ height: 60, display: "flex", alignItems: "center", justifyContent: "center", marginBottom: 10 }}>
        {svgIcon}
      </div>
      {/* Title — fixed height zone */}
      <div style={{ height: 44, display: "flex", alignItems: "center", justifyContent: "center", marginBottom: 6 }}>
        <p style={{ fontSize: 14, fontWeight: 700, color: T.text, textAlign: "center", lineHeight: 1.3 }}>{title}</p>
      </div>
      {/* Sub — fixed height zone */}
      <div style={{ height: 48, display: "flex", alignItems: "flex-start", justifyContent: "center", marginBottom: 12 }}>
        <p style={{ fontSize: 11, color: T.textFaint, textAlign: "center", lineHeight: 1.55 }}>{sub1} ·<br/>{sub2}</p>
      </div>
      {/* Upload button — same height for all */}
      <GlowBtn style={{ width: "100%", justifyContent: "center", fontSize: 13, padding: "8px" }}>
        Upload
      </GlowBtn>
      {/* Status row — pinned below button */}
      <div style={{ marginTop: 8 }}>
        {fileName ? (
          <div style={{
            background: T.inputBg, border: `1px solid ${T.border}`, borderRadius: T.r.sm,
            padding: "8px 10px", display: "flex", alignItems: "center", gap: 8,
          }}>
            <div style={{ width: 26, height: 26, background: T.accent, borderRadius: 4, display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
              {Ic.doc(T.textMuted)}
            </div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <p style={{ fontSize: 11.5, color: T.text, fontWeight: 600 }}>{fileName}</p>
              <p style={{ fontSize: 10, color: T.textFaint, display: "flex", alignItems: "center", gap: 3 }}>{Ic.doc(T.textFaint)} {fileName}</p>
            </div>
            {Ic.download(T.textMuted)}
          </div>
        ) : uploaded ? (
          <div style={{
            display: "flex", alignItems: "center", justifyContent: "space-between",
            padding: "8px 12px", background: "rgba(13,148,136,0.08)",
            border: `1px solid rgba(13,148,136,0.25)`, borderRadius: T.r.sm,
          }}>
            <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
              {Ic.check(T.primary, 14)}
              <span style={{ fontSize: 12, fontWeight: 600, color: T.primaryLight }}>Ready to Upload</span>
            </div>
            {Ic.download(T.primary)}
          </div>
        ) : null}
      </div>
    </div>
  );

  // Decorative SVG icons matching screenshot style
  const CertIcon = () => (
    <svg width="52" height="52" viewBox="0 0 64 64" fill="none">
      <rect x="6" y="10" width="44" height="36" rx="3" fill="#c8972a" opacity=".9"/>
      <rect x="10" y="14" width="36" height="28" rx="2" fill="#e8b84b"/>
      <rect x="14" y="20" width="24" height="3" rx="1" fill="#c8972a"/>
      <rect x="14" y="26" width="18" height="2" rx="1" fill="#c8972a" opacity=".6"/>
      <circle cx="32" cy="48" r="8" fill="#d4a835" stroke="#f0c040" strokeWidth="2"/>
      <path d="M28 48l3 3 6-6" stroke="#fff" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
    </svg>
  );
  const EduIcon = () => (
    <svg width="52" height="52" viewBox="0 0 64 64" fill="none">
      <path d="M8 28l24-14 24 14-24 14-24-14z" fill="#1a9aaa" opacity=".9"/>
      <path d="M20 35v12l12 6 12-6V35" fill="#0e7a88"/>
      <path d="M52 28v10" stroke="#1a9aaa" strokeWidth="3" strokeLinecap="round"/>
      <circle cx="52" cy="41" r="3" fill="#1a9aaa"/>
    </svg>
  );
  const AwardIcon = () => (
    <svg width="52" height="52" viewBox="0 0 64 64" fill="none">
      <circle cx="32" cy="26" r="18" fill="none" stroke="#9b6dd4" strokeWidth="3"/>
      <circle cx="32" cy="26" r="12" fill="none" stroke="#7c4daa" strokeWidth="2"/>
      <path d="M32 14l2.47 7.6H42l-6.18 4.49 2.36 7.25L32 29l-6.18 4.34 2.36-7.25L22 21.6h7.53z" fill="#9b6dd4"/>
      <path d="M24 44l-4 8M40 44l4 8" stroke="#9b6dd4" strokeWidth="2.5" strokeLinecap="round"/>
    </svg>
  );

  return (
    <div style={{ display: "flex", flexDirection: "column", flex: 1, overflow: "hidden" }}>
      {/* Scrollable content */}
      <div style={{ padding: `${CONTENT_PAD}px ${CONTENT_PAD}px 0`, flex: 1, minHeight: 0, overflow: "auto", display: "flex", flexDirection: "column" }}>
        {/* ── Step header ── */}
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 14 }}>
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 4 }}>
              <div style={{
                width: 28, height: 28, borderRadius: 8, flexShrink: 0,
                background: `linear-gradient(135deg, ${T.primary}, ${T.primaryLight})`,
                display: "flex", alignItems: "center", justifyContent: "center",
                boxShadow: `0 0 14px ${T.primaryGlow}`,
              }}>
                {Ic.camera(T.bg)}
              </div>
              <h2 style={{ fontSize: 22, fontWeight: 800, color: T.text, margin: 0, letterSpacing: "-.02em" }}>
                Credentials & Photo
              </h2>
              <div style={{
                display: "flex", alignItems: "center", gap: 5,
                background: T.primaryGlow2, border: `1px solid ${T.primary}40`,
                borderRadius: 99, padding: "4px 12px",
              }}>
                <span style={{ width: 6, height: 6, borderRadius: "50%", background: T.primary, display: "inline-block" }} />
                <span style={{ fontSize: 11, fontWeight: 600, color: T.primaryLight }}>Step 2 of 4</span>
              </div>
            </div>
            <p style={{ fontSize: 12.5, color: T.textMuted, margin: 0, lineHeight: 1.5 }}>
              Upload a professional photo and your credentials — clients see these before booking.
            </p>
          </div>
          <div style={{
            display: "flex", alignItems: "center", gap: 8,
            background: T.card, border: `1.5px solid ${T.cardBorder}`,
            borderRadius: T.r.lg, padding: "8px 14px",
          }}>
            <svg width="32" height="32" viewBox="0 0 36 36">
              <circle cx="18" cy="18" r="14" fill="none" stroke={T.border} strokeWidth="3"/>
              <circle cx="18" cy="18" r="14" fill="none" stroke={T.primary} strokeWidth="3"
                strokeDasharray={`${(2/4)*88} 88`} strokeLinecap="round" transform="rotate(-90 18 18)"/>
              <text x="18" y="22" textAnchor="middle" fill={T.text} fontSize="9" fontWeight="700">2/4</text>
            </svg>
            <div>
              <p style={{ fontSize: 11, fontWeight: 700, color: T.text, margin: 0 }}>50% Done</p>
              <p style={{ fontSize: 10, color: T.textFaint, margin: 0 }}>2 steps remaining</p>
            </div>
          </div>
        </div>

        {/* Warning banner + cards row */}
        <div style={{ display: "flex", gap: 14, marginTop: 18, flex: 1, minHeight: 0 }}>
          {/* Photo card */}
          <div style={{
            width: 240, flexShrink: 0, background: T.card, border: `1.5px solid ${T.cardBorder}`,
            borderRadius: T.r.lg, padding: "22px 18px",
            display: "flex", flexDirection: "column", alignItems: "center", gap: 12,
          }}>
            {/* Avatar */}
            <div style={{
              width: 88, height: 88, borderRadius: "50%",
              background: photo ? "transparent" : `linear-gradient(135deg, ${T.primary}60, ${T.accent})`,
              display: "flex", alignItems: "center", justifyContent: "center",
              overflow: "hidden", border: `3px solid ${T.primary}60`,
            }}>
              {photo
                ? <img src={photo} alt="profile" style={{ width: "100%", height: "100%", objectFit: "cover" }} />
                : <span style={{ fontSize: 28, fontWeight: 800, color: T.primaryLight }}>AK</span>
              }
            </div>
            <div style={{ textAlign: "center" }}>
              <p style={{ fontSize: 14, fontWeight: 700, color: T.text }}>Profile Photo</p>
              <p style={{ fontSize: 11, color: T.textFaint, marginTop: 2 }}>JPG or PNG · min 200×200px</p>
            </div>
            <input type="file" ref={fileRef} onChange={handlePhoto} accept="image/*" style={{ display: "none" }} />
            <GlowBtn onClick={() => fileRef.current?.click()} style={{ width: "100%", justifyContent: "center", fontSize: 13, padding: "10px" }}>
              {Ic.camera("#fff")} Upload Photo
            </GlowBtn>
            <button style={{
              width: "100%", background: "transparent", border: `1.5px solid ${T.border}`,
              borderRadius: T.r.md, color: T.textMuted, fontSize: 13, padding: "9px",
              cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center", gap: 6,
            }}>
              {Ic.camera(T.textMuted)} Take Photo
            </button>
            <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <div style={{ width: 8, height: 8, borderRadius: "50%", border: `1.5px solid ${T.textFaint}` }} />
              <span style={{ fontSize: 11, color: T.textFaint }}>No image uploaded yet</span>
            </div>
          </div>

          {/* Right: verification banner + 3 cred cards */}
          <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 12 }}>
            {/* Verification banner */}
            <div style={{
              background: "rgba(255,200,87,0.07)", border: `1px solid rgba(255,200,87,0.25)`,
              borderRadius: T.r.md, padding: "9px 14px",
              display: "flex", gap: 10, alignItems: "center", alignSelf: "stretch",
            }}>
              <div style={{ width: 28, height: 28, borderRadius: 8, background: "rgba(255,200,87,0.15)", display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke={T.warning} strokeWidth="2.2"><path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
              </div>
              <div>
                <p style={{ fontSize: 12, fontWeight: 700, color: T.warning, margin: 0 }}>2 items pending verification</p>
                <p style={{ fontSize: 10.5, color: T.textFaint, margin: "2px 0 0" }}>Credentials will be reviewed by admin within 24–48 hours</p>
              </div>
            </div>
            {/* 3 cards */}
            <div style={{ display: "flex", gap: 12, flex: 1 }}>
              <CredCard svgIcon={<CertIcon />} title="Bar Council Certificate" sub1="Official bar membership certificate" sub2="PDF, JPG or PNG · Max 5MB" fileName="certificate.pdf" />
              <CredCard svgIcon={<EduIcon />} title="Educational Credentials" sub1="LLB or equivalent law degree" sub2="PDF, JPG or PNG · Max 5MB" uploaded={eduReady} />
              <CredCard svgIcon={<AwardIcon />} title="Professional Certificates" sub1="Additional certifications or awards" sub2="PDF, JPG or PNG · Max 5MB" uploaded={profReady} />
            </div>
          </div>
        </div>
      </div>

      {/* Inline nav */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: `8px ${CONTENT_PAD}px 14px` }}>
        <button onClick={onBack} style={{
          background: "transparent", border: `1px solid ${T.border}`, borderRadius: T.r.sm,
          color: T.textMuted, fontSize: 11, padding: "5px 10px", cursor: "pointer",
          display: "flex", alignItems: "center", gap: 4,
        }}>{Ic.arrow("left", T.textFaint)} Back</button>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <svg width="34" height="34" viewBox="0 0 44 44" style={{ flexShrink: 0 }}>
            <circle cx="22" cy="22" r="18" fill="none" stroke={T.border} strokeWidth="3.5"/>
            <circle cx="22" cy="22" r="18" fill="none" stroke={T.primary} strokeWidth="3.5"
              strokeDasharray={`${(2/4)*113} 113`} strokeLinecap="round" transform="rotate(-90 22 22)"/>
            <text x="22" y="27" textAnchor="middle" fill={T.text} fontSize="10" fontWeight="700">2/4</text>
          </svg>
          <button style={{ background: "transparent", border: "none", color: T.textMuted, fontSize: 12, cursor: "pointer" }}>Skip</button>
          <GlowBtn onClick={onNext} style={{ padding: "8px 22px", fontSize: 13 }}>Continue {Ic.arrow("right")}</GlowBtn>
        </div>
      </div>
    </div>
  );
}

// ─── Step 3: Office & Availability ────────────────────────────────────────────
function StepOffice({ onNext, onBack }) {
  const [address, setAddress] = useState("");
  const [city, setCity] = useState("Lahore, 54000");
  const [phone, setPhone] = useState("");
  const [minFee, setMinFee] = useState(5000);
  const [maxFee, setMaxFee] = useState(25000);
  const [feeNote, setFeeNote] = useState("");
  const [activeDays, setActiveDays] = useState([0, 1, 2, 3, 4]);
  const [schedule, setSchedule] = useState("Standard 9 AM - 5 PM");
  const [feeTier, setFeeTier] = useState("10k-25k");

  const togDay = (i) => setActiveDays(p => p.includes(i) ? p.filter(d => d !== i) : [...p, i].sort((a, b) => a - b));

  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
      <div style={{ flex: 1, minHeight: 0, overflow: "auto", padding: `${CONTENT_PAD}px ${CONTENT_PAD}px 0`, display: "flex", flexDirection: "column" }}>
        {/* ── Step header ── */}
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 14 }}>
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 4 }}>
              <div style={{
                width: 28, height: 28, borderRadius: 8, flexShrink: 0,
                background: `linear-gradient(135deg, ${T.primary}, ${T.primaryLight})`,
                display: "flex", alignItems: "center", justifyContent: "center",
                boxShadow: `0 0 14px ${T.primaryGlow}`,
              }}>
                {Ic.map(T.bg)}
              </div>
              <h2 style={{ fontSize: 22, fontWeight: 800, color: T.text, margin: 0, letterSpacing: "-.02em" }}>
                Office & Availability
              </h2>
              <div style={{
                display: "flex", alignItems: "center", gap: 5,
                background: T.primaryGlow2, border: `1px solid ${T.primary}40`,
                borderRadius: 99, padding: "4px 12px",
              }}>
                <span style={{ width: 6, height: 6, borderRadius: "50%", background: T.primary, display: "inline-block" }} />
                <span style={{ fontSize: 11, fontWeight: 600, color: T.primaryLight }}>Step 3 of 4</span>
              </div>
            </div>
            <p style={{ fontSize: 12.5, color: T.textMuted, margin: 0, lineHeight: 1.5 }}>
              Help clients find your office and know when they can book a consultation.
            </p>
          </div>
          <div style={{
            display: "flex", alignItems: "center", gap: 8,
            background: T.card, border: `1.5px solid ${T.cardBorder}`,
            borderRadius: T.r.lg, padding: "8px 14px",
          }}>
            <svg width="32" height="32" viewBox="0 0 36 36">
              <circle cx="18" cy="18" r="14" fill="none" stroke={T.border} strokeWidth="3"/>
              <circle cx="18" cy="18" r="14" fill="none" stroke={T.primary} strokeWidth="3"
                strokeDasharray={`${(3/4)*88} 88`} strokeLinecap="round" transform="rotate(-90 18 18)"/>
              <text x="18" y="22" textAnchor="middle" fill={T.text} fontSize="9" fontWeight="700">3/4</text>
            </svg>
            <div>
              <p style={{ fontSize: 11, fontWeight: 700, color: T.text, margin: 0 }}>75% Done</p>
              <p style={{ fontSize: 10, color: T.textFaint, margin: 0 }}>1 step remaining</p>
            </div>
          </div>
        </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gridTemplateRows: "1fr", gap: 12, flex: 1 }}>
          {/* Location & Contact */}
          <CardPanel>
            <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
              <div style={{ width: 30, height: 30, borderRadius: 8, background: T.primaryGlow, display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
                {Ic.map(T.primary)}
              </div>
              <span style={{ fontSize: 15, fontWeight: 700, color: T.text }}>Location & Contact</span>
            </div>
            <div>
              <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 6 }}>
                <Label>Office address</Label>
                <span style={{ fontSize: 11, color: T.primary, cursor: "pointer" }}>Map Preview</span>
              </div>
              <div style={{ display: "flex", gap: 8, alignItems: "flex-start" }}>
                <div style={{ flex: 1 }}>
                  <Input placeholder="Street Address (e.g., 14..." icon={Ic.map(T.textFaint)} value={address} onChange={setAddress} />
                </div>
                {/* Mini map thumb */}
                <div style={{
                  width: 60, height: 42, borderRadius: 8, overflow: "hidden",
                  border: `1px solid ${T.border}`, flexShrink: 0,
                  background: "linear-gradient(135deg, #1a3a2e, #0d2a22)",
                  display: "flex", alignItems: "center", justifyContent: "center",
                }}>
                  <span style={{ fontSize: 18 }}>📍</span>
                </div>
              </div>
            </div>
            <div>
              <Label>City & Postal Code</Label>
              <Input placeholder="Lahore, 54000" value={city} onChange={setCity} />
            </div>
            <div>
              <Label>Office phone</Label>
              <div style={{ display: "flex", gap: 8 }}>
                <div style={{ flex: 1 }}>
                  <Input placeholder="+92" icon={Ic.phone(T.textFaint)} value={phone} onChange={setPhone} />
                </div>
                <select style={{
                  background: T.inputBg, border: `1.5px solid ${T.inputBorder}`,
                  borderRadius: T.r.md, color: T.textMuted, fontSize: 12,
                  padding: "10px 10px", outline: "none",
                }}>
                  <option>Primary/</option>
                  <option>Secondary/</option>
                </select>
              </div>
            </div>
            <div style={{ padding: "10px 12px", background: T.inputBg, border: `1px solid ${T.border}`, borderRadius: T.r.sm, fontSize: 12, color: T.textFaint }}>
              Map Preview
            </div>
          </CardPanel>

          {/* Consultation Fee */}
          <CardPanel>
            <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
              <div style={{ width: 30, height: 30, borderRadius: 8, background: T.primaryGlow, display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
                {Ic.money(T.primary)}
              </div>
              <span style={{ fontSize: 15, fontWeight: 700, color: T.text }}>Consultation Fee (PKR)</span>
            </div>
            <div>
              <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 6 }}>
                <Label>Min: PKR {minFee.toLocaleString()}</Label>
                <Label>Max: PKR 50,000</Label>
              </div>
              <input type="range" min="0" max="50000" step="1000" value={minFee}
                onChange={e => setMinFee(+e.target.value)}
                style={{ width: "100%", accentColor: T.primary }} />
            </div>
            <div>
              <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 6 }}>
                <Label>Maximum Fee</Label>
                <Label>Max: PKR 50,000</Label>
              </div>
              <input type="range" min="0" max="50000" step="1000" value={maxFee}
                onChange={e => setMaxFee(+e.target.value)}
                style={{ width: "100%", accentColor: T.primary }} />
            </div>
            <div style={{ display: "flex", gap: 8 }}>
              {["<10k", "10k-25k", ">25k"].map(t => (
                <button key={t} onClick={() => setFeeTier(t)} style={{
                  flex: 1, padding: "8px 6px", borderRadius: T.r.sm, fontSize: 12, fontWeight: 600, cursor: "pointer",
                  background: feeTier === t ? T.primaryGlow : T.inputBg,
                  border: `1.5px solid ${feeTier === t ? T.primary : T.border}`,
                  color: feeTier === t ? T.primaryLight : T.textMuted,
                }}>{t}</button>
              ))}
            </div>
            <div>
              <Label>Explain your fees <span style={{ color: T.textFaint }}>(optional)</span></Label>
              <Textarea placeholder="" rows={3} value={feeNote} onChange={setFeeNote} />
            </div>
          </CardPanel>

          {/* Working Schedule */}
          <CardPanel>
            <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
              <div style={{ width: 30, height: 30, borderRadius: 8, background: T.primaryGlow, display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
                {Ic.clock(T.primary)}
              </div>
              <span style={{ fontSize: 15, fontWeight: 700, color: T.text }}>Working Schedule</span>
            </div>
            <div>
              <Label>Working Days</Label>
              <div style={{ display: "flex", gap: 5, marginTop: 6 }}>
                {DAYS.map((d, i) => (
                  <button key={i} onClick={() => togDay(i)} style={{
                    width: 30, height: 30, borderRadius: "50%", border: `1.5px solid ${activeDays.includes(i) ? T.primary : T.border}`,
                    background: activeDays.includes(i) ? T.primaryGlow : T.inputBg,
                    color: activeDays.includes(i) ? T.primaryLight : T.textFaint,
                    fontSize: 11, fontWeight: 700, cursor: "pointer",
                  }}>{d}</button>
                ))}
              </div>
              <p style={{ fontSize: 11, color: T.textFaint, marginTop: 6 }}>
                Selected: {activeDays.length} Days ({activeDays.map(i => DAY_FULL[i]).join("-")})
              </p>
            </div>
            <div>
              <div style={{ display: "flex", justifyContent: "space-between" }}>
                <Label>Office Hours</Label>
                <span style={{ fontSize: 10, color: T.textFaint }}>ⓘ</span>
              </div>
              <div style={{ display: "flex", gap: 6, marginTop: 6 }}>
                {["AM","Min","AM","Min"].map((p, i) => (
                  <select key={i} style={{ flex: 1, background: T.inputBg, border: `1px solid ${T.border}`, borderRadius: T.r.sm, color: T.textMuted, fontSize: 12, padding: "8px 6px", outline: "none" }}>
                    <option>{p}</option>
                  </select>
                ))}
              </div>
            </div>
            <div style={{ padding: "10px 14px", background: T.primaryGlow2, border: `1px solid ${T.primary}30`, borderRadius: T.r.sm }}>
              <p style={{ fontSize: 12, fontWeight: 600, color: T.primaryLight }}>Standard 9 AM - 5 PM</p>
              <p style={{ fontSize: 11, color: T.textFaint, marginTop: 2 }}>Selected: 9 AM - 5 PM (Mon-Fri)</p>
            </div>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", cursor: "pointer" }}>
              <span style={{ fontSize: 13, fontWeight: 600, color: T.text }}>Exception/Holiday Schedule</span>
              <span style={{ color: T.textMuted }}>▾</span>
            </div>
          </CardPanel>
      </div>
      </div>

      {/* Inline nav */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: `12px ${CONTENT_PAD}px 16px` }}>
        <OutlineBtn onClick={onBack}>{Ic.arrow("left", T.textMuted)} Back</OutlineBtn>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <svg width="32" height="32" viewBox="0 0 36 36">
            <circle cx="18" cy="18" r="14" fill="none" stroke={T.border} strokeWidth="3"/>
            <circle cx="18" cy="18" r="14" fill="none" stroke={T.primary} strokeWidth="3"
              strokeDasharray={`${(3/4)*88} 88`} strokeLinecap="round" transform="rotate(-90 18 18)"/>
            <text x="18" y="22" textAnchor="middle" fill={T.text} fontSize="9" fontWeight="700">3/4</text>
          </svg>
          <button style={{ background: "transparent", border: "none", color: T.textMuted, fontSize: 12, cursor: "pointer" }}>Skip this step</button>
          <GlowBtn onClick={onNext} style={{ padding: "9px 20px", fontSize: 13 }}>Continue {Ic.arrow("right")}</GlowBtn>
        </div>
      </div>
    </div>
  );
}

// ─── Step 4: Submitted ────────────────────────────────────────────────────────
function StepSubmitted({ onBack, onComplete }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", flex: 1 }}>
      <div style={{ flex: 1, minHeight: 0, overflow: "auto", padding: `${CONTENT_PAD}px ${CONTENT_PAD}px 0` }}>
        {/* Hero */}
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 16, paddingBottom: 20, borderBottom: `1px solid ${T.border}` }}>
          <div style={{
            width: "100%", height: 170, background: `linear-gradient(135deg, ${T.accent} 0%, #0a1a17 100%)`,
            borderRadius: T.r.xl, display: "flex", alignItems: "center", justifyContent: "center",
            position: "relative", overflow: "hidden", boxShadow: `0 0 60px rgba(13,148,136,0.2)`,
          }}>
            <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "flex-start", paddingLeft: 28 }}>
              {[T.primary,T.primaryLight,T.accent].map((c, i) => (
                <div key={i} style={{ width: 14, height: 60 + i * 12, background: c, borderRadius: 3, marginRight: 4, opacity: .7 + i * .1 }} />
              ))}
              <div style={{ width: 36, height: 85, background: T.card, borderRadius: 4, marginRight: 4, border: `1px solid ${T.primary}`, display: "flex", alignItems: "center", justifyContent: "center" }}>
                <span style={{ fontSize: 18 }}>⚖️</span>
              </div>
            </div>
            <div style={{
              position: "absolute", right: 72, width: 100, height: 100, borderRadius: "50%",
              border: `2px solid ${T.primary}`, boxShadow: `0 0 40px ${T.primary}40, inset 0 0 30px ${T.primary}20`,
              display: "flex", alignItems: "center", justifyContent: "center",
            }}>
              <span style={{ fontSize: 30 }}>⚖️</span>
            </div>
          </div>
          <div style={{ textAlign: "center" }}>
            <h1 style={{ fontSize: 24, fontWeight: 800, color: T.text, fontStyle: "italic", marginBottom: 10 }}>
              Your Profile is Complete & Submitted
            </h1>
            <p style={{ fontSize: 12.5, color: T.textMuted, maxWidth: 560, lineHeight: 1.7, margin: "0 auto" }}>
              Your complete profile has been securely submitted for verification. Admin review is underway, ensuring the highest level of professional standard. This check typically takes 24–48 hours.
            </p>
          </div>
        </div>

        {/* Status cards */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 12, margin: "16px 0" }}>
          {[
            { icon: "📤", title: "Profile Submitted", sub: "Verification pending", iconRight: Ic.check(T.success, 18) },
            { icon: "🔒", title: "Security Active", sub: "AES-256 protected.", iconRight: null },
            { icon: "🚀", title: "Waiting to Launch", sub: "Awaiting Approval", iconRight: null },
          ].map((card, i) => (
            <div key={i} style={{ background: T.card, border: `1.5px solid ${T.cardBorder}`, borderRadius: T.r.lg, padding: "14px 16px", display: "flex", alignItems: "center", gap: 12 }}>
              <span style={{ fontSize: 22 }}>{card.icon}</span>
              <div style={{ flex: 1 }}>
                <p style={{ fontSize: 13, fontWeight: 700, color: T.text }}>{card.title}</p>
                <p style={{ fontSize: 11, color: T.textFaint }}>{card.sub}</p>
              </div>
              {card.iconRight && card.iconRight}
            </div>
          ))}
        </div>

        {/* Approval progress */}
        <div style={{ display: "flex", gap: 12, marginBottom: 0 }}>
          <div style={{ flex: 1, background: T.card, border: `1.5px solid ${T.cardBorder}`, borderRadius: T.r.lg, padding: "14px 16px" }}>
            <p style={{ fontSize: 13, fontWeight: 700, color: T.text, marginBottom: 10 }}>Approval Status: Reviewing Your Details.</p>
            <div style={{ background: T.inputBg, borderRadius: 99, height: 7, overflow: "hidden", marginBottom: 7 }}>
              <div style={{ width: "15%", height: "100%", background: `linear-gradient(90deg, ${T.primary}, ${T.primaryLight})`, borderRadius: 99 }} />
            </div>
            <p style={{ fontSize: 11, color: T.textFaint }}>15% Admin verification (Step 1/2) in progress.</p>
          </div>
          <div style={{ width: 240, background: T.card, border: `1.5px solid ${T.cardBorder}`, borderRadius: T.r.lg, padding: "14px 16px", display: "flex", alignItems: "center", gap: 10 }}>
            <span style={{ fontSize: 20 }}>✉️</span>
            <p style={{ fontSize: 12, color: T.textMuted }}>Questions? Contact <span style={{ color: T.primaryLight, cursor: "pointer" }}>Admin Support</span>.</p>
          </div>
        </div>

      </div>

      {/* Inline nav */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: `14px ${CONTENT_PAD}px 16px` }}>
        <OutlineBtn onClick={onBack}>{Ic.arrow("left", T.textMuted)} Back</OutlineBtn>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <div style={{ textAlign: "right" }}>
            <p style={{ fontSize: 12, fontWeight: 700, color: T.text }}>4/4 Step Complete</p>
            <p style={{ fontSize: 10, color: T.warning }}>Pending Approval</p>
          </div>
          <GlowBtn onClick={onComplete} style={{ padding: "9px 20px", fontSize: 13 }}>Monitor Progress {Ic.arrow("right")}</GlowBtn>
        </div>
      </div>
    </div>
  );
}

// ─── Root ─────────────────────────────────────────────────────────────────────
export function OnboardingPage({ onComplete }) {
  const [step, setStep] = useState(0);
  const [submitted, setSubmitted] = useState(false);

  const next = () => {
    if (step === 2) { setSubmitted(true); setStep(3); }
    else setStep(s => Math.min(s + 1, 3));
  };
  const back = () => {
    if (step === 3) { setSubmitted(false); setStep(2); }
    else setStep(s => Math.max(s - 1, 0));
  };

  return (
    <div style={{ display: "flex", height: "100vh", background: T.bg, fontFamily: "'Segoe UI', system-ui, sans-serif", color: T.text, overflow: "hidden" }}>
      <Sidebar step={step} submitted={submitted} />

      {/* Main content */}
      <div style={{ flex: 1, overflow: "hidden", minWidth: 0, display: "flex", flexDirection: "column" }}>
        {step === 0 && <StepProfessional onNext={next} />}
        {step === 1 && <StepCredentials onNext={next} onBack={back} />}
        {step === 2 && <StepOffice onNext={next} onBack={back} />}
        {step === 3 && <StepSubmitted onBack={back} onComplete={onComplete} />}
      </div>
    </div>
  );
}

export default OnboardingPage;