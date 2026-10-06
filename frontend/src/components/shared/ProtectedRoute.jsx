'use client';
import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth } from '@/context/AuthContext';

const ROLE_HOME = { client: '/dashboard', lawyer: '/lawyer', admin: '/admin' };

export default function ProtectedRoute({ allowedRoles, children }) {
  const { isAuthenticated, role, loading, authUnavailable, retryAuth } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (loading) return;
    if (authUnavailable) return;
    if (!isAuthenticated) { router.replace('/login'); return; }
    if (allowedRoles && !allowedRoles.includes(role)) {
      router.replace(ROLE_HOME[role] || '/login');
    }
  }, [loading, authUnavailable, isAuthenticated, role, allowedRoles, router]);

  if (loading) return <AuthSpinner />;
  if (authUnavailable) return <AuthUnavailable onRetry={retryAuth} />;
  if (!isAuthenticated) return null;
  if (allowedRoles && !allowedRoles.includes(role)) return null;
  return <>{children}</>;
}

function AuthUnavailable({ onRetry }) {
  return (
    <div style={{
      minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center',
      padding: 24, background: '#0d1f26', color: '#e7f5f3', textAlign: 'center',
    }}>
      <div style={{ maxWidth: 440 }}>
        <h2 style={{ marginBottom: 10 }}>Server temporarily unavailable</h2>
        <p style={{ color: '#a9c8c5', lineHeight: 1.6 }}>
          The backend may be restarting. Your session has not been cleared.
        </p>
        <button type="button" onClick={onRetry} style={{
          marginTop: 16, border: 0, borderRadius: 10, padding: '11px 22px',
          background: '#40d4c8', color: '#092126', fontWeight: 700, cursor: 'pointer',
        }}>
          Retry connection
        </button>
      </div>
    </div>
  );
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
