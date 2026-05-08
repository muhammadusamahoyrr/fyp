'use client';
import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth } from '@/context/AuthContext';

const ROLE_HOME = { client: '/dashboard', lawyer: '/lawyer', admin: '/admin' };

export default function ProtectedRoute({ allowedRoles, children }) {
  const { isAuthenticated, role, loading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (loading) return;
    if (!isAuthenticated) { router.replace('/login'); return; }
    if (allowedRoles && !allowedRoles.includes(role)) {
      router.replace(ROLE_HOME[role] || '/login');
    }
  }, [loading, isAuthenticated, role, allowedRoles, router]);

  if (loading) return <AuthSpinner />;
  if (!isAuthenticated) return null;
  if (allowedRoles && !allowedRoles.includes(role)) return null;
  return <>{children}</>;
}

function AuthSpinner() {
  return (
    <div style={{
      height: '100vh', width: '100vw',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      background: '#0d1f26',
    }}>
      <style>{`@keyframes _spin { to { transform: rotate(360deg); } }`}</style>
      <div style={{
        width: 36, height: 36, borderRadius: '50%',
        border: '3px solid rgba(64,240,220,0.15)',
        borderTopColor: '#40F0DC',
        animation: '_spin 0.75s linear infinite',
      }} />
    </div>
  );
}
