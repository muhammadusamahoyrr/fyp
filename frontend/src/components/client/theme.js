'use client';
import { createContext, useContext } from "react";
export { DARK, LIGHT } from "@/components/admin/themes.js";
export const ThemeCtx = createContext(null);
export const HeaderActionsCtx = createContext(null);

export function useT() {
  return useContext(ThemeCtx) || DARK;
}

export function useHeaderActions() {
  return useContext(HeaderActionsCtx) || {};
}
