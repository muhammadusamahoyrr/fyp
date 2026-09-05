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

    const fromComponent = (context.parentURL || "").startsWith(COMPONENTS);
    if (fromComponent && /\/lib\/api(\.js)?$/.test(specifier)) {
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
