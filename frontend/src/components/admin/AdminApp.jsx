'use client';
import { useMemo, useState } from 'react';
import { DARK } from '@/components/admin/themes.js';
import { Dashboard } from '@/components/admin/AdminDashboard.jsx';
import { UserManagement } from '@/components/admin/AdminUserManagement.jsx';
import { KYCVerification } from '@/components/admin/AdminKYCVerification.jsx';
import { CaseTracking } from '@/components/admin/AdminCaseTracking.jsx';
import { LawyerMonitoring } from '@/components/admin/AdminLawyerMonitoring.jsx';
import { IC } from '@/components/admin/icons.js';
import { Ic } from '@/components/admin/AdminComponent.jsx';

const NAV = [
  { id: 'dashboard', label: 'Dashboard',        icon: IC.dashboard ?? IC.home ?? "M3 9l9-7 9 7v11a2 2 0 01-2 2H5a2 2 0 01-2-2z" },
  { id: 'users',     label: 'Users',             icon: IC.users },
  { id: 'kyc',       label: 'KYC Verification',  icon: IC.verify ?? IC.shield ?? "M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" },
  { id: 'cases',     label: 'Case Tracking',     icon: IC.briefcase },
  { id: 'lawyers',   label: 'Lawyer Monitoring', icon: IC.balance ?? IC.scale ?? "M12 3v18M6 6l-3 6h6L6 6zM18 6l-3 6h6L18 6z" },
];

const PAGE_MAP = {
  dashboard: Dashboard,
  users:     UserManagement,
  kyc:       KYCVerification,
  cases:     CaseTracking,
  lawyers:   LawyerMonitoring,
};

export default function AdminApp({ initialSection = 'dashboard' }) {
  const T = DARK;
  const normalizedInitial = PAGE_MAP[initialSection] ? initialSection : 'dashboard';
  const [nav, setNav] = useState(normalizedInitial);
  const Page = useMemo(() => PAGE_MAP[nav] ?? Dashboard, [nav]);

  return (
    <div style={{ display: 'flex', minHeight: '100vh', background: T.bg, fontFamily: "'Inter',sans-serif" }}>
      {/* Sidebar */}
      <aside style={{ width: 220, background: T.surface, borderRight: `1px solid ${T.border}`, display: 'flex', flexDirection: 'column', padding: '24px 0', flexShrink: 0 }}>
        <div style={{ padding: '0 20px 24px', borderBottom: `1px solid ${T.border}40` }}>
          <span style={{ fontFamily: "'Cormorant Garamond',serif", fontSize: 20, fontWeight: 700, color: T.primary }}>AttorneyAI</span>
          <div style={{ fontSize: 10, color: T.textFaint, fontWeight: 600, letterSpacing: '.06em', marginTop: 2 }}>ADMIN PANEL</div>
        </div>
        <nav style={{ flex: 1, padding: '16px 10px', display: 'flex', flexDirection: 'column', gap: 4 }}>
          {NAV.map(item => {
            const active = nav === item.id;
            return (
              <button key={item.id} onClick={() => setNav(item.id)} style={{
                display: 'flex', alignItems: 'center', gap: 10, padding: '9px 12px',
                borderRadius: 10, border: 'none', cursor: 'pointer', textAlign: 'left', width: '100%',
                background: active ? T.primaryGlow2 : 'transparent',
                color: active ? T.primary : T.textMuted,
                fontWeight: active ? 600 : 400, fontSize: 13,
                borderLeft: active ? `3px solid ${T.primary}` : '3px solid transparent',
                transition: 'all 0.15s',
              }}>
                <Ic d={item.icon} size={16} color={active ? T.primary : T.textMuted} />
                {item.label}
              </button>
            );
          })}
        </nav>
      </aside>

      {/* Main content */}
      <main style={{ flex: 1, overflow: 'auto', padding: 28 }}>
        <Page T={T} nav={setNav} />
      </main>
    </div>
  );
}

