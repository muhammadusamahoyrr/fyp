'use client';
import { StatCard, IconBox, Ic } from "./components.jsx";
import { BarChart, DonutChart } from "./charts.jsx";
import { IC } from "./icons.js";

export const Dashboard = ({ T, nav }) => {
  const dk = T.mode === "dark";
  const sparkUsers   = [62, 65, 68, 66, 72, 74, 78, 82];
  const sparkCases   = [45, 52, 48, 60, 57, 65, 70, 68];
  const sparkDocs    = [340, 380, 360, 420, 400, 450, 480, 490];
  const sparkLawyers = [82, 84, 85, 86, 87, 88, 89, 89];

  const stats = [
    { label: "Active Users", value: "1,284", sub: "+12% from last month", sparkData: sparkUsers, sparkColor: dk ? "#40F0DC" : T.primary, icon: <IconBox icon={IC.users} variant="Primary" T={T} size={42} />, onClick: () => nav("users") },
    { label: "Total Cases", value: "164", sub: "+8 this week", sparkData: sparkCases, sparkColor: T.warn, icon: <IconBox icon={IC.briefcase} variant="Warn" T={T} size={42} />, onClick: () => nav("cases") },
    { label: "Documents", value: "3,847", sub: "+23 today", sparkData: sparkDocs, sparkColor: T.info, icon: <IconBox icon={IC.file} variant="Info" T={T} size={42} />, onClick: () => nav("analytics") },
    { label: "Active Lawyers", value: "89", sub: "3 pending verification", subColor: T.warn, sparkData: sparkLawyers, sparkColor: T.success, icon: <IconBox icon={IC.balance} variant="Success" T={T} size={42} />, onClick: () => nav("kyc") },
  ];
  const barCols  = dk ? ["#40F0DC","#5AB3FF"] : ["#2C8C99","#6B8FD4"];
  const barData  = [[45,28],[52,40],[40,32],[60,47],[57,50],[65,52],[72,60],[68,53],[75,62],[60,58]];
  const barLabels = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct"];
  const donut = [
    { label: "Filed",         value: 45, color: dk ? "#5AB3FF" : "#6B8FD4" },
    { label: "Under Hearing", value: 38, color: dk ? "#FFC857" : "#E8A838" },
    { label: "Adjourned",     value: 12, color: dk ? "#FF6B7A" : "#E05C70" },
    { label: "Closed",        value: 69, color: dk ? "#4DD4A3" : "#2C9E7A" },
  ];
  const recent = [
    { text: "Emily Rodriguez submitted KYC verification", time: "2m ago",  dot: T.warn,      action: () => nav("kyc") },
    { text: "New case CASE-2024-089 filed (Labor)",       time: "18m ago", dot: T.info },
    { text: "Michael Chen account activated",             time: "1h ago",  dot: T.success },
    { text: "Template 'Demand Letter' updated",           time: "2h ago",  dot: T.primary },
    { text: "Q1 performance report generated",           time: "3h ago",  dot: T.textFaint },
  ];

  return (
    <div>
      {/* Attention band */}
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 20, flexWrap: "wrap" }}>
        <span style={{ fontSize: 12, fontWeight: 700, color: T.textMuted, display: "flex", alignItems: "center", gap: 5 }}>
          <Ic d={IC.bell} size={13} color={T.warn} /> Needs attention:
        </span>
        {[
          { label: "2 KYC pending",   color: T.warn,      m: "kyc"   },
          { label: "1 overdue case",  color: T.danger,    m: "cases" },
          { label: "1 inactive user", color: T.textMuted, m: "users" },
        ].map(a => (
          <button key={a.label} onClick={() => nav(a.m)}
            style={{ display: "flex", alignItems: "center", gap: 6, padding: "5px 14px", borderRadius: 20, background: `${a.color}14`, border: `1px solid ${a.color}35`, color: a.color, fontSize: 12.5, fontWeight: 600, cursor: "pointer", transition: "all 0.15s" }}
            onMouseEnter={e => e.currentTarget.style.background = `${a.color}24`}
            onMouseLeave={e => e.currentTarget.style.background = `${a.color}14`}>
            {a.label}
          </button>
        ))}
      </div>

      <div style={{ marginBottom: 22 }}>
        <h1 style={{ margin: 0, fontSize: 28, fontWeight: 700, color: T.text, letterSpacing: -0.5 }}>Dashboard</h1>
        <p style={{ margin: "4px 0 0", color: T.textMuted, fontSize: 14 }}>System overview · click any card to explore</p>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 14, marginBottom: 20 }}>
        {stats.map(s => (
          <StatCard key={s.label} label={s.label} value={s.value} sub={s.sub} subColor={s.subColor}
            iconEl={s.icon} sparkData={s.sparkData} sparkColor={s.sparkColor} onClick={s.onClick} T={T} />
        ))}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 320px", gap: 14, marginBottom: 16 }}>
        <div style={{ background: T.card, border: `1px solid ${T.border}`, borderRadius: 14, padding: "20px 22px", boxShadow: T.shadowCard }}>
          <div style={{ fontWeight: 600, fontSize: 14, color: T.text, marginBottom: 10 }}>Case Trends</div>
          <div style={{ display: "flex", gap: 16, marginBottom: 14 }}>
            {[["Total Cases", barCols[0]], ["New Cases", barCols[1]]].map(([l, c]) => (
              <div key={l} style={{ display: "flex", gap: 6, alignItems: "center" }}>
                <div style={{ width: 10, height: 10, borderRadius: 2, background: c }} />
                <span style={{ color: T.textMuted, fontSize: 12 }}>{l}</span>
              </div>
            ))}
          </div>
          <BarChart data={barData} labels={barLabels} colors={barCols} T={T} />
        </div>
        <div style={{ background: T.card, border: `1px solid ${T.border}`, borderRadius: 14, padding: "20px 22px", boxShadow: T.shadowCard }}>
          <div style={{ fontWeight: 600, fontSize: 14, color: T.text, marginBottom: 16 }}>Case Status</div>
          <DonutChart segments={donut} T={T} onSegmentClick={() => nav("cases")} />
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
        <div style={{ background: T.card, border: `1px solid ${T.border}`, borderRadius: 14, padding: "20px 22px", boxShadow: T.shadowCard }}>
          <div style={{ fontWeight: 600, fontSize: 14, color: T.text, marginBottom: 14 }}>Recent Activity</div>
          {recent.map((a, i) => (
            <div key={i} onClick={a.action} style={{ display: "flex", gap: 10, padding: "8px 0", borderBottom: i < recent.length - 1 ? `1px solid ${T.border}40` : "none", cursor: a.action ? "pointer" : "default" }}>
              <div style={{ width: 7, height: 7, borderRadius: "50%", background: a.dot, marginTop: 5, flexShrink: 0 }} />
              <span style={{ color: T.textDim, fontSize: 12.5, flex: 1 }}>{a.text}</span>
              <span style={{ color: T.textFaint, fontSize: 11, flexShrink: 0 }}>{a.time}</span>
            </div>
          ))}
        </div>
        <div style={{ background: T.card, border: `1px solid ${T.border}`, borderRadius: 14, padding: "20px 22px", boxShadow: T.shadowCard }}>
          <div style={{ fontWeight: 600, fontSize: 14, color: T.text, marginBottom: 14 }}>Quick Actions</div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
            {[
              { l: "User Management", ic: IC.users,     m: "users" },
              { l: "KYC Verification", ic: IC.verify,   m: "kyc" },
              { l: "Case Tracking",   ic: IC.briefcase, m: "cases" },
              { l: "System Config",   ic: IC.settings,  m: "config" },
            ].map(q => (
              <button key={q.l} onClick={() => nav(q.m)}
                style={{ background: T.mode === "dark" ? T.surface : T.bg, border: `1px solid ${T.border}`, borderRadius: 12, padding: "16px 12px", cursor: "pointer", textAlign: "center", transition: "all 0.18s" }}
                onMouseEnter={e => { e.currentTarget.style.borderColor = T.primary; e.currentTarget.style.background = T.primaryGlow2; }}
                onMouseLeave={e => { e.currentTarget.style.borderColor = T.border; e.currentTarget.style.background = T.mode === "dark" ? T.surface : T.bg; }}>
                <Ic d={q.ic} size={20} color={T.textMuted} />
                <div style={{ color: T.textMuted, fontSize: 12, fontWeight: 600, marginTop: 7 }}>{q.l}</div>
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
};
