'use client';
import { createContext, useContext } from "react";
// IMPORTED, then re-exported. `export { DARK } from "…"` is a re-export: it
// forwards the name to this module's consumers WITHOUT binding it locally, so
// the `|| DARK` fallback below referenced a name that does not exist here and
// threw a ReferenceError instead of returning a theme.
//
// It never fired in the app because every rendered tree has a ThemeCtx
// provider, so the left side always short-circuited — the fallback was dead
// code that would crash the moment it was actually needed, which is precisely
// when something has already gone wrong.
import { DARK, LIGHT } from "@/components/admin/themes.js";
export { DARK, LIGHT };

export const ThemeCtx = createContext(null);
export const HeaderActionsCtx = createContext(null);

export function useT() {
  return useContext(ThemeCtx) || DARK;
}

export function useHeaderActions() {
  return useContext(HeaderActionsCtx) || {};
}
