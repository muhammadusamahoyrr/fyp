import React, { createContext, useContext } from "react";
// The lawyer's OWN palette (a copy): restyling it never recolours a client screen.
import { DARK, LIGHT } from "./palette.js";

export { DARK, LIGHT };

export const ThemeCtx = createContext(null);
export const ToggleCtx = createContext(null);
export const CaseCtx = createContext(null);
export const NotifCtx = createContext(null);

export function useTheme() {
  const t = useContext(ThemeCtx) || DARK;
  const toggle = useContext(ToggleCtx) || (() => {});
  return { t, toggle };
}

export function useCase() {
  return useContext(CaseCtx) || {};
}

export function useNotif() {
  return useContext(NotifCtx) || {};
}

