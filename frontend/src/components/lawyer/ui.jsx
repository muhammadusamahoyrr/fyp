'use client';
/* The lawyer screens' building blocks.
 *
 * The primitives are the lawyer's OWN copy, lawyer/primitives.jsx (the
 * client keeps the shared original, through client/documents/ui.jsx)
 * and are re-exported here, so lawyer and analyzer code imports from THIS
 * file. Restyle the lawyer screens here -- never in the shared primitives --
 * so a lawyer design change cannot reach a client screen.
 * (The mirror of client/documents/ui.jsx; tests/docs_isolation.test.mjs.) */
export * from "./primitives.jsx";
