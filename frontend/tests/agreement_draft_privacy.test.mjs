/* A draft is private to the lawyer writing it — the client-side half.
 *
 * The server is what actually enforces this: `find_for_user` returns a draft
 * only to its `created_by`, and `get_agreement` answers 404 to anyone else.
 * This file guards the front end from quietly undoing that, in the two ways it
 * could.
 *
 * FIRST, by promising something the server will never deliver. The client's
 * agreement screen used to render a "Draft" filter tab. Only a verified lawyer
 * can create a draft, and every agreement a client can reach starts at
 * `pending`, so that tab could only ever be empty — and before the server
 * filtered drafts out of the list, it would have shown the client the lawyer's
 * unsent wording under a tab inviting them to look.
 *
 * SECOND, by taking over the filtering itself. Both screens read the SAME
 * endpoint, `GET /agreements`, and that is deliberate: the separation is the
 * server scoping the response to the caller, not the browser choosing what to
 * show. The danger is a future draft list that passes a user id and asks the
 * server for someone's drafts by name. `listAgreements()` takes no argument,
 * and this pins that.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const read = (rel) => readFileSync(new URL(rel, import.meta.url), "utf8");

const CLIENT_VIEW = read("../src/components/client/ModAgreements.jsx");
const LAWYER_VIEW = read("../src/components/lawyer/AgreementsPage.jsx");
const API = read("../src/lib/api.js");

test("the client's agreement screen offers no Draft filter", () => {
    const line = CLIENT_VIEW.split("\n").find(l => l.includes("const filters ="));
    assert.ok(line, "the filter list moved; this test needs updating");
    assert.ok(!/["']Draft["']/.test(line),
        'the client cannot own or see a draft, so a "Draft" tab can only ever ' +
        "be empty — and was a door to the lawyer's unsent wording");
    for (const expected of ["All", "Signed", "Pending", "Rejected"]) {
        assert.ok(line.includes(`"${expected}"`), `lost the ${expected} filter`);
    }
});

test("the list endpoint is scoped by the server, not by a user id from the browser", () => {
    const decl = API.match(/export async function listAgreements\s*\(([^)]*)\)/);
    assert.ok(decl, "listAgreements moved; this test needs updating");
    assert.equal(decl[1].trim(), "",
        "listAgreements must take no argument: a user id in the query string " +
        "is a request for someone else's drafts waiting to be written");
    assert.ok(/listAgreements\(\)\s*\{\s*\n?\s*return apiFetch\('\/agreements'\)/.test(API),
        "listAgreements must call the plain user-scoped /agreements route");
});

test("neither screen asks for another user's agreements", () => {
    for (const [name, src] of [["client", CLIENT_VIEW], ["lawyer", LAWYER_VIEW]]) {
        const calls = src.match(/listAgreements\([^)]*\)/g) || [];
        assert.ok(calls.length > 0, `${name} view no longer lists agreements`);
        for (const call of calls) {
            assert.equal(call, "listAgreements()",
                `${name} view passes an argument to listAgreements: ${call}`);
        }
    }
});

test("a user id in these screens is only used to tell the parties apart", () => {
    // `mapAgreement(a, myId)` uses the id to work out which party is "me" for
    // display. That is presentation, and harmless. What must not happen is the
    // id deciding whether a row is shown at all — that decision is the
    // server's, and a client-side one would be bypassable from the console.
    const map = CLIENT_VIEW.match(/const mapAgreement = \(a, myId\) => \{[\s\S]*?\n\};/);
    assert.ok(map, "mapAgreement moved; this test needs updating");
    assert.ok(!/\bfilter\b[\s\S]*?status === ["']draft["']/.test(map[0]),
        "drafts must be excluded by the server, not by the mapper");
});
