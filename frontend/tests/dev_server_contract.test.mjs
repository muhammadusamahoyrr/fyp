import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";


test("local development uses one explicit frontend port", () => {
    const pkg = JSON.parse(readFileSync(
        new URL("../package.json", import.meta.url), "utf8"));
    assert.match(pkg.scripts.dev, /next dev -p 3001$/);
});


test("the browser API fallback stays on the frontend origin", () => {
    const api = readFileSync(
        new URL("../src/lib/api.js", import.meta.url), "utf8");
    assert.match(api, /NEXT_PUBLIC_API_URL \|\| '\/api\/v1'/);
    assert.doesNotMatch(api, /NEXT_PUBLIC_API_URL \|\| 'http:\/\/localhost:8000/);
});
