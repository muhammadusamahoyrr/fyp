'use client';
import { createContext, useContext, useEffect, useState, useCallback } from 'react';
import { setToken, clearToken, authLogout, bootstrapAuth, broadcastLogout, getMe } from '@/lib/api';
import { clearActiveSessions } from '@/lib/conversations.js';

const AuthCtx = createContext(null);

export function useAuth() {
  const ctx = useContext(AuthCtx);
  if (!ctx) throw new Error('useAuth must be used inside <AuthProvider>');
  return ctx;
}

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  // Hydrate auth state on mount (audit #5): the access token is in-memory only,
  // so on a cold load we adopt a sibling tab's token or silently re-mint one from
  // the HttpOnly refresh cookie (bootstrapAuth), then load the profile.
  useEffect(() => {
    (async () => {
      try {
        const ok = await bootstrapAuth();
        if (!ok) { setLoading(false); return; }
        // getMe goes through apiFetch — one endpoint definition, and a stale
        // access token is refreshed and retried instead of dropping the session.
        const { data, status } = await getMe();
        if (data) setUser(data);
        else if (status === 401) clearToken();
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
    try { localStorage.setItem('aai-role', tokenData.role); } catch { }
    // Set immediately with minimal data so ProtectedRoute unblocks right away
    setUser({ _id: tokenData.user_id, role: tokenData.role });
    // Enrich with full profile in background. setToken above already published
    // the token, so getMe picks it up — and refreshes it if it 401s.
    getMe()
      .then(({ data }) => { if (data) setUser(data); })
      .catch(() => { });
  }, []);

  const logout = useCallback(async () => {
    try { await authLogout(); } catch { }
    clearToken();
    broadcastLogout();   // sibling tabs clear their in-memory token + redirect
    try { localStorage.removeItem('aai-role'); } catch { }
    // Which conversation each surface was looking at. Scoping those keys by
    // user id already stops the next account from reading them, but leaving
    // the value behind records what someone was reading on a shared machine.
    clearActiveSessions();
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
