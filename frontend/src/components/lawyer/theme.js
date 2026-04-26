import React, { createContext, useContext } from "react";
import { DARK, LIGHT } from "../admin/themes.js";

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

