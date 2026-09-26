/* The digest of an agreement body — the record of WHAT was signed.
 *
 * Deliberately NOT in lib/api.js. This is pure computation, not a request, and
 * a component importing it must get the real function: the test loader swaps
 * lib/api.js for a spy stub whenever component code imports it, which would
 * turn this into a coroutine returning `{data, error}` and make the one value
 * the signature record depends on impossible to see in a mounted test. Same
 * reasoning as lib/bookingIdempotency.js.
 *
 * Must agree, byte for byte, with the backend's `body_digest(normalise_body(x))`
 * in app/services/agreement_service.py. A mismatch does not degrade gracefully:
 * every send is refused as a phantom conflict, or — worse — a signature is
 * recorded against a digest describing text nobody read.
 */

/* SHA-256 of `body`, lowercase hex.
 *
 * HASH WHAT THE SERVER RETURNED, never the editor's current text. The server
 * hashes the body AS STORED, after normalising line endings to \n. A textarea
 * on Windows holds \r\n, so hashing local state mismatches the stored copy on
 * some machines and never on others — and, more seriously, would attest to
 * wording the server does not hold. Save first, then hash what comes back,
 * which is also the text displayed for review.
 *
 * There is no non-WebCrypto fallback on purpose. A wrong digest is not a
 * degraded signature, it is a false record of what was signed, so this throws
 * and the caller refuses to send. WebCrypto requires a secure context: https,
 * or localhost.
 */
export async function bodyDigestHex(body) {
  const subtle = (typeof crypto !== 'undefined' && crypto.subtle) || null;
  if (!subtle) {
    throw new Error(
      'This browser cannot compute the signature digest (a secure connection ' +
      'is required). Nothing has been sent.',
    );
  }
  const bytes = new TextEncoder().encode(body ?? '');
  const digest = await subtle.digest('SHA-256', bytes);
  return Array.from(new Uint8Array(digest))
    .map(b => b.toString(16).padStart(2, '0'))
    .join('');
}
