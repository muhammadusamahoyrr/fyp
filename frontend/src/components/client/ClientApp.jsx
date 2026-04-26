'use client';
import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import Dashboard from './Dashboard';

export default function ClientApp({ initialTab = 'overview' }) {
  const router = useRouter();
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

  return (
    <Dashboard
      initialTab={initialTab}
      isDark={isDark}
      toggleTheme={toggleTheme}
      go={(target) => {
        if (target === 'landing') router.push('/');
        else if (target === 'login') router.push('/login');
      }}
    />
  );
}
