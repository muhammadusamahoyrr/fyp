'use client';
import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth } from '@/context/AuthContext.jsx';
import Dashboard from './Dashboard.jsx';
import { DARK, LIGHT } from '@/components/admin/themes.js';
import { ToastContainer } from '@/components/shared/Toast.jsx';

export default function ClientApp({ initialTab = 'overview' }) {
  const router = useRouter();
  const { logout } = useAuth();
  const [isDark, setIsDark] = useState(true);

  useEffect(() => {
    try {
      const saved = localStorage.getItem('aai-theme');
      if (saved) setIsDark(saved === 'dark');
    } catch {}
  }, []);

  useEffect(() => {
    try { localStorage.setItem('aai-theme', isDark ? 'dark' : 'light'); } catch {}
  }, [isDark]);

  const toggleTheme = () => setIsDark(d => !d);

  // The ONE toast provider for every live client screen. Without it useToast()
  // fell back to a no-op and every client toast — successes and refusals alike —
  // was silently dropped; the only container lived in the unused legacy App.jsx.
  return (
    <ToastContainer theme={isDark ? DARK : LIGHT}>
      <Dashboard
        initialTab={initialTab}
        isDark={isDark}
        toggleTheme={toggleTheme}
        go={async (target) => {
          if (target === 'signout') { await logout(); router.push('/'); }
          else if (target === 'landing') router.push('/');
          else if (target === 'login') router.push('/login');
        }}
      />
    </ToastContainer>
  );
}
