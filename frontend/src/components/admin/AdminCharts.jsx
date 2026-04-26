'use client';
import { useState, useRef, useEffect } from "react";

// ─── Ic — SVG Icon ────────────────────────────────────────────────────────────
export const Ic = ({ d, size = 18, color = "currentColor", sw = 1.8, fill = "none" }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill={fill} stroke={color} strokeWidth={sw} strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0 }}>
    {(Array.isArray(d) ? d : [d]).map((p, i) =>
      typeof p === "string" ? <path key={i} d={p} /> : <circle key={i} {...p} />
    )}
  </svg>
);

// ─── Avatar ───────────────────────────────────────────────────────────────────
export const Avatar = ({ name, size = 38, bg }) => {
  const initials = name.split(" ").map(w => w[0]).slice(0, 2).join("").toUpperCase();
  const palette = ["#2C606E", "#1A3A42", "#3A7A8A", "#4A6B5A", "#3D5A6D"];
  const c = bg || palette[name.charCodeAt(0) % palette.length];
  return (
    <div style={{ width: size, height: size, borderRadius: "50%", background: c, display: "flex", alignItems: "center", justifyContent: "center", color: "#fff", fontSize: size * 0.35, fontWeight: 700, flexShrink: 0 }}>
      {initials}
    </div>
  );
};

// ─── IconBox ──────────────────────────────────────────────────────────────────
export const IconBox = ({ icon, variant = "gray", size = 40, T }) => {
  const key = `icon${variant.charAt(0).toUpperCase() + variant.slice(1)}`;
  const v = T[key] || T.iconGray;
  return (
    <div style={{ width: size, height: size, borderRadius: 10, background: v.bg, display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
      <Ic d={icon} size={size * 0.46} color={v.color} />
    </div>
  );
};

// ─── Badge ────────────────────────────────────────────────────────────────────
export const Badge = ({ label, type = "gray", T }) => {
  const key = `badge${type.charAt(0).toUpperCase() + type.slice(1)}`;
  const s = T[key] || T.badgeGray;
  return (
    <span style={{ background: s.bg, color: s.color, border: `1px solid ${s.border}`, padding: "3px 10px", borderRadius: 20, fontSize: 11.5, fontWeight: 600, whiteSpace: "nowrap" }}>
      {label}
    </span>
  );
};

// ─── DocTag ───────────────────────────────────────────────────────────────────
export const DocTag = ({ label, T }) => (
  <span style={{ background: T.mode === "dark" ? "rgba(255,255,255,0.06)" : "rgba(26,46,53,0.05)", color: T.textMuted, border: `1px solid ${T.border}`, padding: "3px 10px", borderRadius: 6, fontSize: 11.5, fontWeight: 500, whiteSpace: "nowrap" }}>
    {label}
  </span>
);

// ─── Sparkline ────────────────────────────────────────────────────────────────
export const Sparkline = ({ data, color, h = 28, w = 72 }) => {
  if (!data || data.length < 2) return null;
  const max = Math.max(...data), min = Math.min(...data);
  const range = max - min || 1;
  const pts = data
    .map((v, i) => `${(i / (data.length - 1)) * w},${h - ((v - min) / range) * (h - 4) + 2}`)
    .join(" ");
  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} style={{ display: "block", flexShrink: 0 }}>
      <polyline points={pts} fill="none" stroke={color} strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" opacity="0.85" />
    </svg>
  );
};

// ─── StatCard ─────────────────────────────────────────────────────────────────
export const StatCard = ({ label, value, sub, subColor, iconEl, T, sparkData, sparkColor, onClick }) => {
  const [hov, setHov] = useState(false);
  return (
    <div
      onClick={onClick}
      onMouseEnter={() => setHov(true)}
      onMouseLeave={() => setHov(false)}
      title={onClick ? `Click to view ${label}` : undefined}
      style={{
        background: T.card,
        border: `1px solid ${hov && onClick ? T.primary : T.border}`,
        borderRadius: 14,
        padding: "18px 20px",
        boxShadow: hov && onClick ? T.shadowHover : T.shadowCard,
        display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 12,
        cursor: onClick ? "pointer" : "default",
        transition: "border-color 0.18s, box-shadow 0.18s",
      }}>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ color: T.textMuted, fontSize: 12.5, fontWeight: 500, marginBottom: 5 }}>{label}</div>
        <div style={{ color: T.text, fontSize: 26, fontWeight: 600, lineHeight: 1.1, marginBottom: 4 }}>{value}</div>
        {sub && <div style={{ color: subColor || T.success, fontSize: 12, fontWeight: 500 }}>{sub}</div>}
        {sparkData && (
          <div style={{ marginTop: 8 }}>
            <Sparkline data={sparkData} color={sparkColor || T.primary} />
          </div>
        )}
      </div>
      {iconEl && <div style={{ marginTop: 2 }}>{iconEl}</div>}
    </div>
  );
};

// ─── Btn ──────────────────────────────────────────────────────────────────────
export const Btn = ({ children, onClick, variant = "primary", size = "md", T, icon, style: ex }) => {
  const [h, setH] = useState(false);
  const pad = size === "sm" ? "6px 13px" : "8px 18px";
  const fs = size === "sm" ? 12 : 13;
  const vars = {
    primary: { bg: h ? T.primaryDim : T.primary, color: T.mode === "dark" ? T.bg : "#fff", border: "none" },
    success: { bg: h ? "#35b882" : T.success, color: T.mode === "dark" ? T.bg : "#fff", border: "none" },
    danger: { bg: h ? "#c44" : T.danger, color: "#fff", border: "none" },
    outline: { bg: h ? T.primaryGlow2 : "transparent", color: T.primary, border: `1px solid ${T.primary}` },
    ghost: { bg: h ? (T.mode === "dark" ? "rgba(255,255,255,0.06)" : "rgba(26,46,53,0.05)") : "transparent", color: T.textMuted, border: `1px solid ${T.border}` },
  };
  const v = vars[variant] || vars.ghost;
  return (
    <button onClick={onClick} onMouseEnter={() => setH(true)} onMouseLeave={() => setH(false)}
      style={{ padding: pad, background: v.bg, color: v.color, border: v.border || "none", borderRadius: 9, cursor: "pointer", fontWeight: 600, fontSize: fs, display: "inline-flex", alignItems: "center", gap: 6, transition: "all 0.15s", whiteSpace: "nowrap", ...ex }}>
      {icon && <Ic d={icon} size={13} color={v.color} />}
      {children}
    </button>
  );
};

// ─── Modal ────────────────────────────────────────────────────────────────────
export const Modal = ({ open, onClose, title, children, T }) => {
  if (!open) return null;
  return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.45)", zIndex: 999, display: "flex", alignItems: "center", justifyContent: "center", padding: 20 }} onClick={onClose}>
      <div style={{ background: T.card, border: `1px solid ${T.border}`, borderRadius: 16, padding: 28, width: "100%", maxWidth: 480, boxShadow: "0 20px 60px rgba(0,0,0,0.25)", maxHeight: "90vh", overflowY: "auto" }} onClick={e => e.stopPropagation()}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 20 }}>
          <h3 style={{ margin: 0, color: T.text, fontSize: 15, fontWeight: 600 }}>{title}</h3>
          <button onClick={onClose} style={{ background: "none", border: "none", cursor: "pointer", padding: 4 }}>
            <Ic d="M18 6L6 18M6 6l12 12" size={18} color={T.textMuted} />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
};

// ─── Input ────────────────────────────────────────────────────────────────────
export const Input = ({ label, value, onChange, type = "text", placeholder, T }) => {
  const [f, setF] = useState(false);
  return (
    <div style={{ marginBottom: 14 }}>
      {label && <label style={{ display: "block", color: T.textMuted, fontSize: 11.5, fontWeight: 700, marginBottom: 5, textTransform: "uppercase", letterSpacing: 0.6 }}>{label}</label>}
      <input type={type} value={value} onChange={onChange} placeholder={placeholder}
        onFocus={() => setF(true)} onBlur={() => setF(false)}
        style={{ width: "100%", background: f ? T.inputFocus : T.inputBg, border: `1px solid ${f ? T.primary : T.border}`, borderRadius: 9, padding: "9px 13px", color: T.text, fontSize: 13.5, outline: "none", transition: "all 0.18s", boxSizing: "border-box" }} />
    </div>
  );
};

// ─── SortTh ───────────────────────────────────────────────────────────────────
export const SortTh = ({ label, field, sort, onSort, T }) => {
  const active = sort.field === field;
  return (
    <th onClick={() => onSort(field)}
      style={{ padding: "12px 18px", textAlign: "left", color: active ? T.primary : T.textMuted, fontSize: 12, fontWeight: 600, cursor: "pointer", userSelect: "none", whiteSpace: "nowrap" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
        {label}
        <div style={{ display: "flex", flexDirection: "column", gap: 1, opacity: active ? 1 : 0.35 }}>
          <svg width={8} height={5} viewBox="0 0 8 5"><path d="M4 0L8 5H0Z" fill={active && sort.dir === "asc" ? T.primary : T.textFaint} /></svg>
          <svg width={8} height={5} viewBox="0 0 8 5"><path d="M4 5L0 0H8Z" fill={active && sort.dir === "desc" ? T.primary : T.textFaint} /></svg>
        </div>
      </div>
    </th>
  );
};

// ─── ActionMenu ───────────────────────────────────────────────────────────────
export const ActionMenu = ({ actions, T }) => {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  useEffect(() => {
    if (!open) return;
    const handler = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);
  return (
    <div ref={ref} style={{ position: "relative", display: "inline-block" }}>
      <button aria-label="More actions" onClick={() => setOpen(p => !p)}
        style={{ background: open ? T.inputBg : "transparent", border: `1px solid ${open ? T.border : "transparent"}`, borderRadius: 8, padding: "5px 8px", cursor: "pointer", display: "flex", alignItems: "center", transition: "all 0.14s" }}
        onMouseEnter={e => { e.currentTarget.style.background = T.inputBg; e.currentTarget.style.borderColor = T.border; }}
        onMouseLeave={e => { if (!open) { e.currentTarget.style.background = "transparent"; e.currentTarget.style.borderColor = "transparent"; } }}>
        <svg width={16} height={16} viewBox="0 0 24 24" fill={T.textMuted}>
          <circle cx={5} cy={12} r={2.2} /><circle cx={12} cy={12} r={2.2} /><circle cx={19} cy={12} r={2.2} />
        </svg>
      </button>
      {open && (
        <div style={{ position: "absolute", right: 0, top: "calc(100% + 4px)", background: T.card, border: `1px solid ${T.border}`, borderRadius: 10, boxShadow: "0 8px 28px rgba(0,0,0,0.18)", zIndex: 500, minWidth: 175, overflow: "hidden" }}>
          {actions.map((a, i) => (
            <button key={i} onClick={() => { a.fn(); setOpen(false); }}
              style={{ width: "100%", display: "flex", alignItems: "center", gap: 9, padding: "10px 14px", background: "none", border: "none", borderBottom: i < actions.length - 1 ? `1px solid ${T.border}40` : "none", cursor: "pointer", textAlign: "left", color: a.danger ? T.danger : T.textDim, fontSize: 13, fontWeight: 500, transition: "background 0.12s" }}
              onMouseEnter={e => e.currentTarget.style.background = T.mode === "dark" ? "rgba(255,255,255,0.05)" : "rgba(26,46,53,0.04)"}
              onMouseLeave={e => e.currentTarget.style.background = "none"}>
              {a.icon && <Ic d={a.icon} size={14} color={a.danger ? T.danger : T.textMuted} />}
              {a.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
};

// ─── EmptyState ───────────────────────────────────────────────────────────────
export const EmptyState = ({ T, icon, title, sub, actionLabel, onAction }) => (
  <div style={{ textAlign: "center", padding: "48px 24px", display: "flex", flexDirection: "column", alignItems: "center", gap: 10 }}>
    <div style={{ width: 52, height: 52, borderRadius: 14, background: T.inputBg, display: "flex", alignItems: "center", justifyContent: "center", marginBottom: 4 }}>
      <Ic d={icon || "M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16z"} size={24} color={T.textFaint} />
    </div>
    <div style={{ fontSize: 14, fontWeight: 600, color: T.text }}>{title || "No results"}</div>
    <div style={{ fontSize: 13, color: T.textMuted, maxWidth: 280 }}>{sub}</div>
    {onAction && (
      <button onClick={onAction} style={{ marginTop: 6, padding: "7px 18px", borderRadius: 9, border: `1px solid ${T.border}`, background: "transparent", color: T.textMuted, fontSize: 12.5, fontWeight: 600, cursor: "pointer" }}>
        {actionLabel || "Clear filters"}
      </button>
    )}
  </div>
);

// ─── Paginator ────────────────────────────────────────────────────────────────
export const Paginator = ({ total, page, perPage, onPage, onPerPage, T }) => {
  const pages = Math.ceil(total / perPage);
  const start = (page - 1) * perPage + 1;
  const end   = Math.min(page * perPage, total);
  if (total === 0) return null;
  return (
    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "12px 18px", borderTop: `1px solid ${T.border}`, flexWrap: "wrap", gap: 10 }}>
      <div style={{ fontSize: 12.5, color: T.textMuted }}>
        Showing <strong style={{ color: T.text }}>{start}–{end}</strong> of <strong style={{ color: T.text }}>{total}</strong>
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
        <select value={perPage} onChange={e => { onPerPage(Number(e.target.value)); onPage(1); }}
          style={{ background: T.inputBg, border: `1px solid ${T.border}`, borderRadius: 8, padding: "5px 9px", fontSize: 12, color: T.textMuted, outline: "none", cursor: "pointer" }}>
          {[5, 10, 25].map(n => <option key={n} value={n}>{n} / page</option>)}
        </select>
        {[...Array(pages)].map((_, i) => (
          <button key={i} onClick={() => onPage(i + 1)} aria-label={`Page ${i + 1}`}
            style={{ width: 30, height: 30, borderRadius: 8, border: `1px solid ${page === i + 1 ? T.primary : T.border}`, background: page === i + 1 ? T.primaryGlow2 : "transparent", color: page === i + 1 ? T.primary : T.textMuted, fontSize: 12.5, fontWeight: 600, cursor: "pointer", transition: "all 0.14s" }}>
            {i + 1}
          </button>
        ))}
      </div>
    </div>
  );
};
