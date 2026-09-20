/* A Node module loader that makes the app's real components importable.
 *
 * Two things stopped `node --test` from mounting an actual component, and so
 * confined every UI test to either a hook or a regex over source text:
 *
 *   1. JSX. Node does not parse it.
 *   2. The `@/` alias. It is a bundler convention with no meaning to Node.
 *
 * Both are build concerns, not design ones, and neither is a good reason to
 * stop testing the thing that actually ships. `sucrase` is already in the tree
 * (transitively) and does the JSX transform; the alias is three lines of
 * resolution.
 *
 * `@/lib/api.js` is redirected to a stub, because a mounted component must not
 * be able to reach the network — a test that quietly hits localhost:8000 either
 * fails for the wrong reason or, worse, passes for one.
 */
import { readFile, stat } from "node:fs/promises";
import { fileURLToPath, pathToFileURL } from "node:url";
import path from "node:path";

import { transform } from "sucrase";

const ROOT = path.resolve(fileURLToPath(import.meta.url), "../../..");
const SRC = path.join(ROOT, "src");
const API_STUB = pathToFileURL(
    path.join(ROOT, "tests", "support", "api-stub.mjs")).href;

const COMPONENTS = pathToFileURL(path.join(SRC, "components")).href;
// Context providers are application code too — see the note in resolve().
const CONTEXT = pathToFileURL(path.join(SRC, "context")).href;

/* Minimal stand-ins for the Next.js runtime modules a page-level component
 * imports. Deliberately tiny and inert: a test that wants to assert on routing
 * reads `__nav` off globalThis rather than these growing behaviour.
 *
 * `next/dynamic` returns the loader's component synchronously-ish rather than
 * the real lazy wrapper, so a dynamically imported child (the Leaflet map)
 * renders as its fallback instead of exploding on `window` during import. */
const NEXT_STUB_PREFIX = "attorney-ai-next-stub:";
const NEXT_STUBS = {
    "next/navigation": `
        const nav = (globalThis.__nav ||= { pushed: [], replaced: [], params: new Map() });
        export function useRouter() {
            return {
                push: (u) => nav.pushed.push(u),
                replace: (u) => nav.replaced.push(u),
                back: () => nav.pushed.push("(back)"),
                prefetch: () => {},
            };
        }
        export function useSearchParams() {
            return { get: (k) => (nav.params.get(k) ?? null),
                     toString: () => "" };
        }
        export function usePathname() { return nav.pathname || "/"; }
    `,
    "next/dynamic": `
        export default function dynamic(_loader, options = {}) {
            const Loading = options.loading;
            const Stub = (props) => (Loading ? Loading(props) : null);
            Stub.displayName = "DynamicStub";
            return Stub;
        }
    `,
};

export async function resolve(specifier, context, nextResolve) {
    // The stub applies to COMPONENTS ONLY, decided by who is importing.
    //
    // Redirecting every `/lib/api.js` specifier was too blunt: tests that
    // import the real client to check `errorCode`, `idempotencyKey` and
    // `isRetryable` silently got the stub and failed. A component must not be
    // able to reach the network; a test asking about the client itself must get
    // the client itself.
    // The stub has no file on disk — its source is synthesised below — so a
    // test importing it by name must be short-circuited here too, or the
    // default resolver looks for a file that was never written.
    if (specifier.endsWith("api-stub.mjs")) {
        return { url: API_STUB, shortCircuit: true };
    }

    // `next/navigation` and `next/dynamic` are framework runtime, not component
    // code. The real modules resolve fine from node_modules and then throw
    // outside a Next render — `useSearchParams` in particular expects an app
    // router context a bare jsdom mount cannot provide. Stubbing them is what
    // lets a page-level component be mounted at all; the component under test
    // is still the unmodified real one.
    if (NEXT_STUBS[specifier]) {
        return { url: `${NEXT_STUB_PREFIX}${specifier}`, shortCircuit: true };
    }

    // `src/context/` counts as component code for this purpose.
    //
    // The guard's intent is "application code must not reach the network in a
    // mounted test". It matched `src/components/` only, so `AuthContext.jsx` —
    // which lives in src/context and calls bootstrapAuth/getMe on mount — got
    // the REAL client, failed against no server, and left `user` null. Any
    // component whose behaviour depends on the signed-in user then behaved as
    // though nobody were logged in, silently.
    //
    // Tests that deliberately import the real client are imported FROM tests/,
    // so their parentURL matches neither prefix and they are unaffected.
    const parent = context.parentURL || "";
    const fromAppCode = parent.startsWith(COMPONENTS) || parent.startsWith(CONTEXT);
    if (fromAppCode && /\/lib\/api(\.js)?$/.test(specifier)) {
        return { url: API_STUB, shortCircuit: true };
    }
    if (specifier.startsWith("@/")) {
        return {
            url: await resolveFile(path.join(SRC, specifier.slice(2))),
            shortCircuit: true,
        };
    }
    return nextResolve(specifier, context);
}

/* The bundler resolves extensionless imports; Node does not. Components are
 * written for the bundler ("@/lib/api"), so the same candidates are tried
 * here — otherwise every such import fails with ENOENT on a path that is
 * perfectly valid in the app. */
const CANDIDATES = ["", ".js", ".jsx", ".mjs",
                    "/index.js", "/index.jsx"];

async function resolveFile(base) {
    for (const suffix of CANDIDATES) {
        const candidate = base + suffix;
        try {
            const info = await stat(candidate);
            if (info.isFile()) return pathToFileURL(candidate).href;
        } catch {
            /* try the next candidate */
        }
    }
    // Let Node produce its own error, naming the specifier the author wrote.
    return pathToFileURL(base).href;
}

/* The stub's exports are GENERATED from the real client's, so the two cannot
 * drift. Hand-listing them meant a component importing any function nobody had
 * anticipated died with "does not provide an export named …" — which is a
 * failure of the test harness masquerading as a failure of the component. */
async function synthesiseApiStub() {
    const real = await readFile(path.join(SRC, "lib", "api.js"), "utf8");
    const names = new Set();
    const patterns = [
        /^export\s+(?:async\s+)?function\s+([A-Za-z0-9_$]+)/gm,
        /^export\s+(?:const|let|var)\s+([A-Za-z0-9_$]+)/gm,
    ];
    for (const re of patterns) {
        for (const m of real.matchAll(re)) names.add(m[1]);
    }
    const lines = [
        'import { spy, __calls, __respond, __reset } from "./api-stub-core.mjs";',
        "export { __calls, __respond, __reset };",
    ];
    for (const name of names) {
        lines.push(`export const ${name} = spy(${JSON.stringify(name)}, ` +
                   `{ data: null, error: null });`);
    }
    return lines.join(String.fromCharCode(10));
}

export async function load(url, context, nextLoad) {
    if (url === API_STUB) {
        return { format: "module", source: await synthesiseApiStub(),
                 shortCircuit: true };
    }
    if (url.startsWith(NEXT_STUB_PREFIX)) {
        return { format: "module",
                 source: NEXT_STUBS[url.slice(NEXT_STUB_PREFIX.length)],
                 shortCircuit: true };
    }
    if (url.endsWith(".jsx")) {
        const source = await readFile(fileURLToPath(url), "utf8");
        const { code } = transform(source, {
            transforms: ["jsx"],
            jsxRuntime: "automatic",
            filePath: fileURLToPath(url),
        });
        return { format: "module", source: code, shortCircuit: true };
    }
    return nextLoad(url, context);
}
