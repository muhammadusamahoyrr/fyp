/* Decision D1 (2026-10-03): a client sends a document only to a lawyer they
 * have an ACCEPTED engagement with -- the server refuses anyone else. The
 * review step must therefore offer the client's engaged lawyers, never the
 * whole lawyer directory, and say plainly when there is none. */
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const src = readFileSync(new URL("../src/components/client/ModDocuments.jsx", import.meta.url), "utf8");

test("the review step offers only lawyers of accepted engagements", () => {
    assert.match(src, /listEngagements\(\{ status: "accepted" \}\)/);
    assert.doesNotMatch(src, /searchLawyers\(/, "the whole lawyer directory is still offered");
});

test("with no engaged lawyer the client is told to hire one, not shown a spinner forever", () => {
    assert.match(src, /data-no-engaged-lawyer/);
    assert.match(src, /hire a lawyer first/);
    assert.doesNotMatch(src, /Loading verified lawyers/);
});
