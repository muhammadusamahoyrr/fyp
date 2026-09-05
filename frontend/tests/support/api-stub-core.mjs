/* Shared state for the generated API stub. See jsx-loader.mjs.
 *
 * The stub's surface is GENERATED from the real client's exports rather than
 * hand-written, so it cannot drift: a component importing a function nobody
 * anticipated gets a spy, not a SyntaxError about a missing export.
 */
const state = { calls: [], responses: {} };

export function spy(name, fallback) {
    return async (...args) => {
        state.calls.push({ name, args });
        const responder = state.responses[name];
        if (typeof responder === "function") return responder(...args);
        if (responder !== undefined) return responder;
        return fallback;
    };
}

export function __calls(name) {
    return name ? state.calls.filter(c => c.name === name) : state.calls;
}
export function __respond(name, value) { state.responses[name] = value; }
export function __reset() { state.calls = []; state.responses = {}; }
