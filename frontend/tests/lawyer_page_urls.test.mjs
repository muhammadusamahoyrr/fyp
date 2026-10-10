/* The lawyer's address follows the page (2026-10-09).
 *
 * Navigation is React state, so a sidebar click left the URL on the entry
 * route and a refresh went back there. App.jsx now writes PAGE_PATH[page] into
 * the address; every path it writes must be a real route, or a refresh 404s. */
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync, existsSync } from "node:fs";

const src = readFileSync(new URL("../src/components/lawyer/App.jsx", import.meta.url), "utf8");
const block = src.slice(src.indexOf("export const PAGE_PATH = {"), src.indexOf("};", src.indexOf("export const PAGE_PATH = {")));
const pairs = [...block.matchAll(/"?([\w-]+)"?:\s*"(\/lawyer[^"]*)"/g)].map(m => [m[1], m[2]]);

test("every address the lawyer app writes is a real route that opens the same page", () => {
    assert.ok(pairs.length >= 15, `PAGE_PATH not found or too small: ${pairs.length}`);
    for (const [page, path] of pairs) {
        const file = new URL(`../src/app${path}/page.jsx`, import.meta.url);
        assert.ok(existsSync(file), `${path} has no route file`);
        const route = readFileSync(file, "utf8");
        if (page === "dashboard") continue;   // /lawyer renders <App /> with the default page
        assert.match(route, new RegExp(`initialPage="${page}"`), `${path} does not open ${page}`);
    }
});

test("the page writes its address and Back/Forward follow it", () => {
    assert.match(src, /window\.history\.pushState\(\{ lawyerPage: page \}, "", path\)/);
    assert.match(src, /addEventListener\("popstate"/);
});

test("the old Draft Generator address opens Legal drafting instead of a 404", () => {
    const file = new URL("../src/app/lawyer/drafts/page.jsx", import.meta.url);
    assert.ok(existsSync(file));
    assert.match(readFileSync(file, "utf8"), /initialPage="doc-automation"/);
});
