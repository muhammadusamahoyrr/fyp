'use client';
// Paste your App.jsx code here
import React, { useState, useEffect } from "react";
import { DARK, LIGHT } from "@/components/admin/themes.js";
import { ThemeCtx } from "@/components/lawyer/theme.js";
import { FONTS, makeGlobal } from "@/lib/styles.js";
import ErrorBoundary from "@/components/shared/ErrorBoundary.jsx";
import { ToastContainer } from "@/components/shared/Toast.jsx";
import Dashboard from "./Dashboard.jsx";
import Landing from "@/components/shared/Landing.jsx";

// AuthPage not yet implemented
const AuthPage = () => null;

export default function App() {
    const [page, setPage] = useState("landing");
    const [isDark, setIsDark] = useState(true);
    const toggleTheme = () => setIsDark(d => !d);
    const t = isDark ? DARK : LIGHT;

    useEffect(() => {
        const s = document.createElement("style");
        s.textContent = FONTS + makeGlobal();
        document.head.appendChild(s);
        return () => document.head.removeChild(s);
    }, []);

    useEffect(() => {
        document.body.style.background = isDark ? DARK.bg : LIGHT.bg;
    }, [isDark]);

    return (
        <ErrorBoundary>
            <ToastContainer theme={t}>
                {page === "dashboard" && <Dashboard go={setPage} isDark={isDark} toggleTheme={toggleTheme} />}
                {["login", "register", "forgot"].includes(page) && <AuthPage mode={page} go={setPage} isDark={isDark} toggleTheme={toggleTheme} />}
                {page === "landing" && <Landing go={setPage} isDark={isDark} toggleTheme={toggleTheme} />}
            </ToastContainer>
        </ErrorBoundary>
    );
}