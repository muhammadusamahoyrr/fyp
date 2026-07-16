'use client';
import { createContext, useContext, useEffect, useState, useCallback } from 'react';
import { getToken, setToken, clearToken, authLogout, bootstrapAuth, broadcastLogout } from '@/lib/api';

const BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1';

const AuthCtx = createContext(null);

export function useAuth() {
  const ctx = useContext(AuthCtx);
  if (!ctx) throw new Error('useAuth must be used inside <AuthProvider>');
  return ctx;
}

export function AuthProvider({ children }) {
  const [user, setUser]       = useState(null);
  const [loading, setLoading] = useState(true);

  // Hydrate auth state on mount (audit #5): the access token is in-memory only,
  // so on a cold load we adopt a sibling tab's token or silently re-mint one from
  // the HttpOnly refresh cookie (bootstrapAuth), then load the profile.
  useEffect(() => {
    (async () => {
      try {
        const ok = await bootstrapAuth();
        if (!ok) { setLoading(false); return; }
        const res = await fetch(`${BASE}/users/me`, {
          headers: { Authorization: `Bearer ${getToken()}` },
          credentials: 'include',
        });
        if (res.ok) setUser(await res.json());
        else clearToken();
      } catch {
        // Network error — stay unauthenticated (isAuthenticated false) until a
        // real /users/me succeeds; the in-memory token is left for retry.
      }
      setLoading(false);
    })();
  }, []);

  // Call after successful login — tokenData = { access_token, role, user_id }
  const login = useCallback((tokenData) => {
    setToken(tokenData.access_token);
    try { localStorage.setItem('aai-role', tokenData.role); } catch {}
    // Set immediately with minimal data so ProtectedRoute unblocks right away
    setUser({ _id: tokenData.user_id, role: tokenData.role });
    // Enrich with full profile in background
    fetch(`${BASE}/users/me`, {
      headers: { Authorization: `Bearer ${tokenData.access_token}` },
      credentials: 'include',
    })
      .then(r => r.ok ? r.json() : null)
      .then(profile => { if (profile) setUser(profile); })
      .catch(() => {});
  }, []);

  const logout = useCallback(async () => {
    try { await authLogout(); } catch {}
    clearToken();
    broadcastLogout();   // sibling tabs clear their in-memory token + redirect
    try { localStorage.removeItem('aai-role'); } catch {}
    setUser(null);
  }, []);

  // Merge partial updates into user object (e.g. after profile edit)
  const updateUser = useCallback((patch) => {
    setUser(prev => prev ? { ...prev, ...patch } : null);
  }, []);

  return (
    <AuthCtx.Provider value={{
      user,
      role: user?.role ?? null,
      isAuthenticated: !!user,
      loading,
      login,
      logout,
      updateUser,
    }}>
      {children}
    </AuthCtx.Provider>
  );
}
