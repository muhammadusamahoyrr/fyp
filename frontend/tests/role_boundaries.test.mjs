/* Client and lawyer screens never import each other.
 *
 * WHY. On 2026-10-07 a client Documents redesign was lost and restyled in
 * part because the two roles shared presentation code: the lawyer Review
 * Queue imported the whole client Vault screen, the lawyer Document Analyzer
 * read the client theme and the client Documents building blocks, and the
 * legacy client shell provided the LAWYER theme context. A client styling
 * edit could therefore change a lawyer screen, and the other way round.
 *
 * THE RULES (every static import, `export … from`, dynamic import() and
 * require(), through the "@/" alias or a relative path):
 *   client  (components/client, app/(client))         must not import lawyer
 *   lawyer  (components/lawyer, components/analyzer,
 *            app/lawyer)                                must not import client
 *   shared  (components/shared)                        must not import a role
 *   logic   (lib, features)                            must not import a role
 *   shared/ui holds small neutral primitives only: no default-exported
 *            component (a screen) and no API call or data hook.
 * components/analyzer is lawyer-owned: the analyzer is a lawyer tool.
 *
 * ALLOWLIST: exact "file -> import" pairs that may cross for now, each with
 * a reason. Target, and current state: empty. */
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync, statSync, existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const FRONTEND = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const SRC = path.join(FRONTEND, "src");

const ALLOWLIST = [];   // e.g. { from: "src/components/x.jsx", to: "src/components/y.jsx", why: "TODO …" }

const IMPORT_PATTERNS = [
    /\bimport\s+(?:[^'"`;]*?\s+from\s+)?["']([^"']+)["']/g,      // import x from "…" / import "…"
    /\bexport\s+(?:\*|\{[^}]*\}|\*\s+as\s+\w+)\s+from\s+["']([^"']+)["']/g,  // export … from "…"
    /\bimport\s*\(\s*["']([^"']+)["']\s*\)/g,                    // import("…")
    /\brequire\s*\(\s*["']([^"']+)["']\s*\)/g,                   // require("…")
];

/** Every module specifier a source file names. */
export function specifiers(source) {
    const found = [];
    for (const pattern of IMPORT_PATTERNS) {
        for (const m of source.matchAll(pattern)) found.push(m[1]);
    }
    return found;
}

/** The src-relative path a specifier points at, or null for a package. */
export function target(fromRel, spec) {
    if (spec.startsWith("@/")) return path.posix.normalize(`src/${spec.slice(2)}`);
    if (spec.startsWith(".")) return path.posix.normalize(path.posix.join(path.posix.dirname(fromRel), spec));
    return null;
}

/** Which side of the boundary a src-relative path is on. */
export function roleOf(rel) {
    const p = rel.replace(/\\/g, "/");
    if (p.startsWith("src/components/client/") || p.startsWith("src/app/(client)/")) return "client";
    if (p.startsWith("src/components/lawyer/") || p.startsWith("src/components/analyzer/")
        || p.startsWith("src/app/lawyer/")) return "lawyer";
    if (p.startsWith("src/components/shared/")) return "shared";
    if (p.startsWith("src/lib/") || p.startsWith("src/features/")) return "logic";
    return "other";
}

const FORBIDDEN = {
    client: ["lawyer"],
    lawyer: ["client"],
    shared: ["client", "lawyer"],
    logic: ["client", "lawyer"],
};

/** Boundary violations of one file, as { from, to, spec } (paths src-relative). */
export function violationsOf(fromRel, source) {
    const role = roleOf(fromRel);
    const banned = FORBIDDEN[role] || [];
    const out = [];
    for (const spec of specifiers(source)) {
        const to = target(fromRel, spec);
        if (to && banned.includes(roleOf(to))) out.push({ from: fromRel, to, spec });
    }
    return out;
}

/** shared/ui must stay primitives: no screen (default export) and no data access. */
export function sharedUiProblems(fromRel, source) {
    if (!fromRel.replace(/\\/g, "/").startsWith("src/components/shared/ui/")) return [];
    const problems = [];
    if (/\bexport\s+default\b/.test(source)) problems.push(`${fromRel}: default export (a screen?) in shared/ui`);
    for (const spec of specifiers(source)) {
        if (/^@\/lib\/(api|use[A-Z])/.test(spec) || /\/lib\/api(\.js)?$/.test(spec)) {
            problems.push(`${fromRel}: data access (${spec}) in shared/ui`);
        }
    }
    return problems;
}

function* sourceFiles(dir) {
    for (const name of readdirSync(dir)) {
        const full = path.join(dir, name);
        if (statSync(full).isDirectory()) yield* sourceFiles(full);
        else if (/\.(m?js|jsx)$/.test(name)) yield full;
    }
}

function scan() {
    const violations = [], uiProblems = [];
    for (const file of sourceFiles(SRC)) {
        const rel = path.relative(FRONTEND, file).replace(/\\/g, "/");
        const source = readFileSync(file, "utf8");
        violations.push(...violationsOf(rel, source));
        uiProblems.push(...sharedUiProblems(rel, source));
    }
    const allowed = v => ALLOWLIST.some(a => a.from === v.from && v.to.startsWith(a.to.replace(/\.(m?js|jsx)$/, "")));
    return { violations: violations.filter(v => !allowed(v)), uiProblems };
}

// ── the real tree ────────────────────────────────────────────────────────────

test("no client file imports a lawyer file, and no lawyer file imports a client file", () => {
    const { violations } = scan();
    assert.deepEqual(violations.map(v => `${v.from} -> ${v.spec}`), []);
});

test("shared/ui holds primitives only: no screens and no data access", () => {
    assert.deepEqual(scan().uiProblems, []);
});

test("the allowlist is empty, and any entry carries a reason", () => {
    for (const entry of ALLOWLIST) assert.ok(entry.why && /TODO/.test(entry.why), JSON.stringify(entry));
    assert.equal(ALLOWLIST.length, 0, "a cross-role import was allowlisted; remove it");
});

test("the role themes stay on their side, and the shared context is the client's", async () => {
    const shared = readFileSync(path.join(SRC, "components/shared/ui/theme.js"), "utf8");
    const client = readFileSync(path.join(SRC, "components/client/theme.js"), "utf8");
    assert.match(client, /from "@\/components\/shared\/ui\/theme\.js"/, "client/theme.js no longer re-exports the shared context");
    assert.doesNotMatch(shared, /components\/(client|lawyer)\//);
    assert.ok(existsSync(path.join(SRC, "components/lawyer/theme.js")));
});

// ── the checker itself: each kind of violation is caught ─────────────────────

test("a static, aliased import from lawyer into client is caught", () => {
    const v = violationsOf("src/components/client/X.jsx", 'import { useTheme } from "@/components/lawyer/theme.js";');
    assert.equal(v.length, 1);
    assert.equal(v[0].to, "src/components/lawyer/theme.js");
});

test("a relative import that climbs into the other role is caught", () => {
    const v = violationsOf("src/components/lawyer/ReviewQueuePage.jsx",
        'import { formatWhen } from "../client/documents/DocsVault.jsx";');
    assert.equal(v[0].to, "src/components/client/documents/DocsVault.jsx");
});

test("dynamic import(), require() and export-from are caught", () => {
    const src = [
        'const Page = await import("@/components/client/ModDocuments.jsx");',
        'const t = require("../client/theme.js");',
        'export { Btn } from "@/components/client/documents/ui.jsx";',
        'export * from "../client/documents/ui.jsx";',
    ].join("\n");
    assert.equal(violationsOf("src/components/lawyer/Some.jsx", src).length, 4);
});

test("a multi-line import is caught", () => {
    const src = 'import {\n    Btn, Card,\n    Pill,\n} from "@/components/client/documents/ui.jsx";';
    assert.equal(violationsOf("src/components/analyzer/A.jsx", src).length, 1, "analyzer is lawyer-owned");
});

test("shared and logic modules may not import a role either", () => {
    assert.equal(violationsOf("src/components/shared/S.jsx", 'import { useT } from "@/components/client/theme.js";').length, 1);
    assert.equal(violationsOf("src/lib/x.js", 'import P from "@/components/lawyer/App.jsx";').length, 1);
    assert.equal(violationsOf("src/features/documents/y.js", 'import V from "../../components/client/documents/DocsVault.jsx";').length, 1);
});

test("allowed directions pass: role -> shared, role -> logic, packages", () => {
    const src = [
        'import React from "react";',
        'import { Btn } from "@/components/shared/ui/primitives.jsx";',
        'import { formatWhen } from "@/features/documents/formatWhen.js";',
        'import { listTemplates } from "@/lib/api.js";',
        'import { ThemeCtx } from "./theme.js";',
    ].join("\n");
    assert.deepEqual(violationsOf("src/components/lawyer/ReviewQueuePage.jsx", src), []);
    assert.deepEqual(violationsOf("src/components/client/documents/DocsVault.jsx", src.replace('"./theme.js"', '"../theme.js"')), []);
});

test("a screen or a data call in shared/ui is caught", () => {
    assert.equal(sharedUiProblems("src/components/shared/ui/Big.jsx", "export default function Vault() {}").length, 1);
    assert.equal(sharedUiProblems("src/components/shared/ui/P.jsx", 'import { myDocumentsV2 } from "@/lib/api.js";').length, 1);
    assert.deepEqual(sharedUiProblems("src/components/shared/ui/P.jsx", "export function Btn() {}"), []);
});
