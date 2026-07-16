'use client';
// Lightweight EN/UR language layer for the client-facing app.
// Usage: const { T, lang, isUrdu, toggleLang } = useLang();
//        <h1>{T("Legal Intake", "قانونی درخواست")}</h1>
// Strings stay colocated with the markup — no key bookkeeping. Layout stays
// LTR (standard for Pakistani bilingual UIs); only the text swaps.
import { createContext, useCallback, useContext, useEffect, useState } from 'react';

const LangCtx = createContext(null);

export function LangProvider({ children }) {
  const [lang, setLang] = useState('en');

  useEffect(() => {
    try {
      const saved = localStorage.getItem('aai-lang');
      if (saved === 'ur' || saved === 'en') setLang(saved);
    } catch {}
  }, []);

  const toggleLang = useCallback(() => {
    setLang(prev => {
      const next = prev === 'en' ? 'ur' : 'en';
      try { localStorage.setItem('aai-lang', next); } catch {}
      return next;
    });
  }, []);

  const T = useCallback(
    (en, ur) => (lang === 'ur' && ur ? ur : en),
    [lang],
  );

  return (
    <LangCtx.Provider value={{ lang, isUrdu: lang === 'ur', toggleLang, T }}>
      {children}
    </LangCtx.Provider>
  );
}

// Safe outside the provider (defaults to English) so shared components
// don't crash when rendered in the lawyer/admin apps.
export function useLang() {
  const ctx = useContext(LangCtx);
  if (ctx) return ctx;
  return { lang: 'en', isUrdu: false, toggleLang: () => {}, T: (en) => en };
}

// ─── Responsive helper ────────────────────────────────────────────────────────
export function useIsMobile(breakpoint = 768) {
  const [isMobile, setIsMobile] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia(`(max-width: ${breakpoint}px)`);
    const onChange = () => setIsMobile(mq.matches);
    onChange();
    mq.addEventListener('change', onChange);
    return () => mq.removeEventListener('change', onChange);
  }, [breakpoint]);
  return isMobile;
}
