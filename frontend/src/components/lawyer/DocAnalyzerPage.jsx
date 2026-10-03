'use client';
/* The lawyer dashboard's Document Analyzer: the same workspace, flow and
 * design the analyzer always had, mounted here because the analyzer is a
 * lawyer's tool (2026-10-03). The client dashboard has none, and the server
 * refuses every analyzer endpoint to a client account.
 *
 * The workspace reads the app theme through the client ThemeCtx (`useT`).
 * Both dashboards build their themes from the same DARK/LIGHT objects, so this
 * page hands it the lawyer dashboard's current theme and the analyzer follows
 * the lawyer's light/dark toggle. */
import React from "react";
import { ThemeCtx as WorkspaceThemeCtx } from "@/components/client/theme.js";
import AnalyzerWorkspace from "@/components/analyzer/AnalyzerWorkspace.jsx";
import { useCase, useTheme } from "./theme.js";

export function DocAnalyzerPage() {
    const { t } = useTheme();
    const { setPage } = useCase();
    return (
        <WorkspaceThemeCtx.Provider value={t}>
            <div data-lawyer-analyzer style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column" }}>
                <AnalyzerWorkspace onBack={() => setPage?.("documents")} />
            </div>
        </WorkspaceThemeCtx.Provider>
    );
}

export default DocAnalyzerPage;
