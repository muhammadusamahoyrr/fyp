'use client';
/* The client dashboard's theme access. The context itself is role-neutral and
 * lives in components/shared/ui/theme.js (one context object, so screens and
 * shared primitives read the same values); re-exported here so client code
 * keeps importing from its own folder. */
export { ThemeCtx, HeaderActionsCtx, useT, useHeaderActions, DARK, LIGHT } from "@/components/shared/ui/theme.js";
