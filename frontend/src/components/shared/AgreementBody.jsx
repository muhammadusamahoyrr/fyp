'use client';
/* An agreement's text, as its parties read it (2026-10-11).
 *
 * Two formats: "html" (the builder's rich editor) is shown as formatted text,
 * cleaned again in the browser with the server's allowlist; anything else is
 * the plain text every agreement had until now, shown exactly as typed. Used by
 * every screen that shows an agreement to someone about to sign it, so they
 * all show the same thing. */
import React from "react";
import { cleanAgreementHtml } from "@/lib/agreementHtml.js";

const RICH_CSS = `[data-agreement-body="html"] p,[data-agreement-body="html"] div{margin:0 0 10px}
[data-agreement-body="html"] h1{font-size:1.45em;margin:4px 0 12px}
[data-agreement-body="html"] h2{font-size:1.2em;margin:14px 0 8px}
[data-agreement-body="html"] h3{font-size:1.05em;margin:12px 0 6px}
[data-agreement-body="html"] ul,[data-agreement-body="html"] ol{margin:0 0 10px;padding-left:1.6em}
[data-agreement-body="html"] blockquote{margin:0 0 10px;padding:4px 0 4px 14px;border-left:3px solid currentColor;opacity:.85}
[data-agreement-body="html"] hr{border:0;border-top:1px solid currentColor;opacity:.3;margin:14px 0}
[data-agreement-body="html"] a{color:#3fa7d6;text-decoration:underline}`;

export default function AgreementBody({ body, format, empty = "No content.", style }) {
    if (!body) return <div style={style}>{empty}</div>;
    if (format === "html") {
        return (
            <>
                <style>{RICH_CSS}</style>
                <div data-agreement-body="html" style={style}
                    dangerouslySetInnerHTML={{ __html: cleanAgreementHtml(body) }} />
            </>
        );
    }
    return <div data-agreement-body="text" style={{ whiteSpace: "pre-wrap", ...style }}>{body}</div>;
}
