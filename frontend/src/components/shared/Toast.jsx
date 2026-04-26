'use client';
import React, { createContext, useContext, useState } from "react";
import Ic from "./Ic.jsx";

export const ToastCtx = createContext(null);
export const useToast = () => {
    const ctx = useContext(ToastCtx);
    return ctx || { show: () => { } };
};

export const ToastContainer = ({ theme, children }) => {
    const [toasts, setToasts] = useState([]);
    const show = (msg, type = "info", duration = 3000) => {
        const id = Date.now();
        setToasts(t => [...t, { id, msg, type }]);
        if (duration > 0) setTimeout(() => setToasts(t => t.filter(x => x.id !== id)), duration);
    };

    const colors = {
        success: { bg: theme.badgeSuccess.bg, border: theme.badgeSuccess.border, color: theme.badgeSuccess.color, icon: "check" },
        danger: { bg: theme.badgeDanger.bg, border: theme.badgeDanger.border, color: theme.badgeDanger.color, icon: "check" },
        warn: { bg: theme.badgeWarn.bg, border: theme.badgeWarn.border, color: theme.badgeWarn.color, icon: "check" },
        info: { bg: theme.badgeInfo.bg, border: theme.badgeInfo.border, color: theme.badgeInfo.color, icon: "msg" },
    };

    return (
        <ToastCtx.Provider value={{ show }}>
            {children}
            <div style={{ position: "fixed", bottom: 24, right: 24, zIndex: 9999, pointerEvents: "none" }}>
                {toasts.map(t => {
                    const c = colors[t.type] || colors.info;
                    return (
                        <div key={t.id} className="aSlideR" style={{
                            background: c.bg, border: `1.5px solid ${c.border}`, borderRadius: 14,
                            padding: "14px 18px", marginBottom: 12, pointerEvents: "auto",
                            display: "flex", gap: 12, alignItems: "center", minWidth: 280,
                            boxShadow: `0 8px 24px rgba(0,0,0,0.15)`, animation: "slideR 0.4s ease"
                        }}>
                            <Ic n={c.icon} s={18} c={c.color} />
                            <span style={{ fontSize: 14, color: c.color, fontWeight: 600 }}>{t.msg}</span>
                        </div>
                    );
                })}
            </div>
        </ToastCtx.Provider>
    );
};
