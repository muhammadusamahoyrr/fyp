/* A lawyer screen's UI change must not reach the client's Documents module
 * (2026-10-08). role_boundaries.test.mjs already forbids either role importing
 * the other; these pin the routes that remain -- the SHARED files both use --
 * so that each role restyles on its own side:
 *
 *   1. primitives reach each role through that role's own layer
 *      (client/documents/ui.jsx, lawyer/ui.jsx), never directly -- and since
 *      2026-10-08 the lawyer has its OWN copies of every UI component the two
 *      roles shared (primitives, RevisionHistory, SessionsPanel, SignaturePad):
 *      the shared originals are the finalized client screens' alone;
 *   2. every client use of the shared RevisionHistory draws its own rows, so
 *      the component's default look is the lawyer's alone;
 *   3. the lawyer app removes its global (unscoped) styles when it unmounts;
 *   4. CSS the client's Documents screens inject is scoped by a data attribute,
 *      so it can never style a lawyer screen either. */
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync, statSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const SRC = path.join(path.dirname(fileURLToPath(import.meta.url)), "..", "src");
const rel = full => path.relative(SRC, full).split(path.sep).join("/");
function* files(dir) {
    for (const name of readdirSync(dir)) {
        const full = path.join(dir, name);
        if (statSync(full).isDirectory()) yield* files(full);
        else if (/\.(m?js|jsx)$/.test(name)) yield full;
    }
}
const ROLE_DIRS = ["components/client", "components/lawyer", "components/analyzer", "app/lawyer", "app/(client)"];
const roleFiles = () => ROLE_DIRS.flatMap(d => [...files(path.join(SRC, d))]);
const read = r => readFileSync(path.join(SRC, r), "utf8");

test("each role reaches the shared primitives only through its own ui layer", () => {
    const LAYERS = ["components/client/documents/ui.jsx", "components/lawyer/ui.jsx"];
    const direct = roleFiles().map(rel)
        .filter(r => !LAYERS.includes(r))
        .filter(r => /["']@\/components\/shared\/ui\/primitives/.test(read(r)));
    assert.deepEqual(direct, [], "import from client/documents/ui.jsx or lawyer/ui.jsx instead");
    assert.match(read("components/client/documents/ui.jsx"), /export \* from "@\/components\/shared\/ui\/primitives\.jsx"/);
    assert.match(read("components/lawyer/ui.jsx"), /export \* from "\.\/primitives\.jsx"/, "the lawyer layer must use the lawyer's own copy");
});

/* A lawyer screen can be redesigned without reaching a finalized client screen:
 * no lawyer or analyzer file uses a shared UI component -- only its own copy. */
// [the client's original, the lawyer's own copy]
const FORKED = [
    ["components/shared/ui/primitives", "components/lawyer/primitives.jsx"],
    ["components/shared/RevisionHistory", "components/lawyer/RevisionHistory.jsx"],
    ["components/shared/SessionsPanel", "components/lawyer/SessionsPanel.jsx"],
    ["components/shared/SignaturePad", "components/lawyer/SignaturePad.jsx"],
    ["components/shared/Toast", "components/lawyer/Toast.jsx"],
    ["components/shared/Ic", "components/lawyer/Ic.jsx"],
    ["components/admin/themes", "components/lawyer/palette.js"],
];
// Any import of `original`, by alias or by relative path, with or without extension.
const importsOf = (r, original) => {
    const name = original.split("/").pop();
    return [...read(r).matchAll(/(?:from|import)\s*\(?\s*["']([^"']+)["']/g)].map(m => m[1])
        .filter(spec => spec.startsWith("@/") || spec.startsWith("."))
        .some(spec => {
            const full = spec.startsWith("@/") ? spec.slice(2)
                : path.posix.normalize(path.posix.join(path.posix.dirname(r), spec));
            return full.replace(/\.(jsx|js)$/, "") === original && name;
        });
};
test("lawyer and analyzer screens use their own copies of the once-shared UI and palette", () => {
    const lawyerSide = ["components/lawyer", "components/analyzer", "app/lawyer"]
        .flatMap(d => { try { return [...files(path.join(SRC, d))]; } catch { return []; } }).map(rel);
    const hits = lawyerSide.flatMap(r => FORKED.filter(([original]) => importsOf(r, original)).map(([original]) => `${r} -> ${original}`));
    assert.deepEqual(hits, [], "import the lawyer's own copy (components/lawyer/...) instead");
    for (const [, copy] of FORKED) assert.match(read(copy), /LAWYER-OWNED COPY/, `${copy} is missing`);
    assert.match(read("components/lawyer/theme.js"), /from "\.\/palette\.js"/, "the lawyer theme must use the lawyer's palette");
    assert.match(read("components/lawyer/Toast.jsx"), /import Ic from "\.\/Ic\.jsx"/, "the lawyer toast must use the lawyer's icons");
});

test("every client RevisionHistory draws its own rows", () => {
    const uses = [...files(path.join(SRC, "components/client"))].map(rel)
        .flatMap(r => [...read(r).matchAll(/<RevisionHistory\b[\s\S]*?\/>/g)].map(m => [r, m[0]]));
    assert.ok(uses.length >= 2, "expected the drafting workspace and the guided flow");
    for (const [r, jsx] of uses) assert.match(jsx, /renderRow=/, `${r} relies on RevisionHistory's default (lawyer) look`);
});

test("the lawyer app takes its global styles away when it unmounts", () => {
    const app = read("components/lawyer/App.jsx");
    assert.match(app, /injectGS\(t\)/);
    assert.match(app, /useEffect\(\(\) => \(\) => \{\s*for \(const id of \["ag-gs", "ag-extra"\]\) document\.getElementById\(id\)\?\.remove\(\);/);
});

test("CSS injected by the client's Documents screens is scoped by a data attribute", () => {
    const docs = ["components/client/ModDocuments.jsx", "components/client/DocumentsHome.jsx",
        ...[...files(path.join(SRC, "components/client/documents"))].map(rel)];
    let checked = 0;
    for (const r of docs) {
        for (const m of read(r).matchAll(/const ([A-Z_]+_CSS) = `([\s\S]*?)`;/g)) {
            const [, name, css] = m;
            // Top-level selectors only: drop @keyframes blocks and unwrap @media.
            const body = css.replace(/\$\{[^}]*\}/g, "x")      // template values, e.g. ${DOCS_FONT}
                .replace(/@keyframes[^{]+\{(?:[^{}]*\{[^{}]*\})*[^{}]*\}/g, "")
                // A container query's opener; its rules inside are still checked.
                .replace(/@container[^{]+\{/g, "")
                .replace(/@media[^{]+\{([\s\S]*)\}\s*$/m, "$1");
            for (const sel of body.split("}").map(b => b.split("{")[0].trim()).filter(Boolean)) {
                for (const part of sel.split(",")) {
                    assert.match(part.trim(), /^\[data-[a-z-]+\]/, `${r} ${name}: "${part.trim()}" is not scoped`);
                }
                checked += 1;
            }
        }
    }
    assert.ok(checked >= 5, "expected the Documents style rules to be found");
});
