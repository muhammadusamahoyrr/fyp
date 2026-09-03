/* Socket ownership: no two sockets for one conversation, ever.
 *
 * The bug these cover is not "a stray socket": it is that a stray socket
 * receives every frame, appends every answer twice, and schedules its own
 * reconnect when it closes — so one dropped connection compounded instead of
 * settling. Every test here is a sequence that used to produce two. */
import { test } from "node:test";
import assert from "node:assert/strict";
import { createSocketOwner } from "../src/lib/socket.js";

class FakeWS {
    constructor() { this.readyState = FakeWS.CONNECTING; this.closed = false; }
    open() { this.readyState = FakeWS.OPEN; }
    close() { this.closed = true; this.readyState = FakeWS.CLOSED; }
}
FakeWS.CONNECTING = 0;
FakeWS.OPEN = 1;
FakeWS.CLOSED = 3;

test("a second connect during the ticket fetch is refused", () => {
    const owner = createSocketOwner(FakeWS);
    // The reconnect timer claims and starts awaiting its ticket.
    const first = owner.claim();
    assert.notEqual(first, null);
    // A conversation switch fires while that await is still outstanding. This
    // is the exact window the old readyState guard was blind to.
    assert.equal(owner.claim(), null);
});

test("a claim that produced no socket does not block the next one", () => {
    const owner = createSocketOwner(FakeWS);
    const token = owner.claim();
    owner.abandon(token);                 // no ticket came back
    assert.notEqual(owner.claim(), null, "the surface would never reconnect");
});

test("a superseded connect closes its socket instead of installing it", () => {
    const owner = createSocketOwner(FakeWS);
    const stale = owner.claim();
    // The user switches conversation while that connect is in flight.
    owner.close();
    const fresh = owner.claim();
    const live = new FakeWS();
    assert.equal(owner.adopt(fresh, live), true);

    const orphan = new FakeWS();
    assert.equal(owner.adopt(stale, orphan), false, "two sockets would be live");
    assert.equal(orphan.closed, true, "the loser must not linger");
    assert.equal(owner.current(), live);
});

test("a replaced socket is no longer current, so its close is silent", () => {
    const owner = createSocketOwner(FakeWS);
    const old = new FakeWS();
    owner.adopt(owner.claim(), old);
    owner.close();

    const fresh = new FakeWS();
    owner.adopt(owner.claim(), fresh);

    // The old socket's onclose fires now. Acting on it would schedule a
    // reconnect for a connection that was replaced on purpose.
    assert.equal(owner.isCurrent(old), false);
    assert.equal(owner.isCurrent(fresh), true);
});

test("an open socket refuses a new claim", () => {
    const owner = createSocketOwner(FakeWS);
    const ws = new FakeWS();
    owner.adopt(owner.claim(), ws);
    ws.open();
    assert.equal(owner.claim(), null);
    assert.equal(owner.isOpen(), true);
});

test("a closed socket allows a reconnect", () => {
    const owner = createSocketOwner(FakeWS);
    const ws = new FakeWS();
    owner.adopt(owner.claim(), ws);
    ws.open();
    ws.readyState = FakeWS.CLOSED;        // the network dropped
    assert.notEqual(owner.claim(), null);
    assert.equal(owner.isOpen(), false);
});

test("close disowns even a socket that throws on close", () => {
    const owner = createSocketOwner(FakeWS);
    const ws = new FakeWS();
    ws.close = () => { throw new Error("already dead"); };
    owner.adopt(owner.claim(), ws);
    owner.close();                        // must not propagate
    assert.equal(owner.current(), null);
    assert.notEqual(owner.claim(), null);
});
