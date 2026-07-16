'use client';
import { useMemo, useState, useEffect } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
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

  useEffect(() => {
    const id = 'admin-gs'; if (document.getElementById(id)) return;
    const s = document.createElement('style'); s.id = id;
    s.textContent = `
      .admin-page-enter{animation:adminFadeUp .45s cubic-bezier(.22,.68,0,1.2) both}
      .admin-card-lift{transition:transform .22s cubic-bezier(.4,0,.2,1),box-shadow .22s cubic-bezier(.4,0,.2,1)}
      .admin-card-lift:hover{transform:translateY(-3px);box-shadow:0 14px 38px rgba(0,0,0,.5),0 0 0 1px rgba(64,240,220,0.12)}
      @keyframes adminFadeUp{from{opacity:0;transform:translateY(16px)}to{opacity:1;transform:none}}
    `;
    document.head.appendChild(s);
  }, []);

  return (
    <div style={{ display: 'flex', minHeight: '100vh', background: T.bg, fontFamily: "'DM Sans',sans-serif", position: 'relative' }}>
      {/* Gradient mesh background */}
      <div aria-hidden style={{ position: 'absolute', inset: 0, pointerEvents: 'none', zIndex: 0,
        backgroundImage: "radial-gradient(ellipse at 18% 14%, rgba(64,240,220,0.08) 0%, transparent 50%), radial-gradient(ellipse at 80% 80%, rgba(64,200,220,0.06) 0%, transparent 48%), radial-gradient(ellipse at 50% 95%, rgba(91,179,255,0.05) 0%, transparent 42%)" }} />
      {/* Noise texture overlay */}
      <div aria-hidden style={{ position: 'absolute', inset: 0, pointerEvents: 'none', zIndex: 0, opacity: 0.035,
        backgroundImage: "url(\"data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.65' numOctaves='3' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E\")" }} />
      {/* Sidebar */}
      <aside style={{ width: 220, background: T.surface, borderRight: `1px solid ${T.border}`, display: 'flex', flexDirection: 'column', padding: '24px 0', flexShrink: 0, position: 'relative', zIndex: 1 }}>
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
      <main style={{ flex: 1, overflow: 'auto', padding: 28, position: 'relative', zIndex: 1 }}>
        <AnimatePresence mode="wait">
          <motion.div
            key={nav}
            initial={{ opacity: 0, y: 18 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -10 }}
            transition={{ duration: 0.35, ease: [0.22, 1, 0.36, 1] }}
          >
            <Page T={T} nav={setNav} />
          </motion.div>
        </AnimatePresence>
      </main>
    </div>
  );
}

