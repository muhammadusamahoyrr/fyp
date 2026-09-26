/** @type {import('next').NextConfig} */

/* ONE ORIGIN FOR THE PAGE AND THE API.
 *
 * An invited signer opens their link on their own device. If the page comes
 * from a tunnel (ngrok) but its JavaScript still calls an absolute
 * `http://localhost:8000`, that resolves to THEIR machine, where nothing is
 * listening — the page loads and every request fails.
 *
 * So `NEXT_PUBLIC_API_URL` is relative (`/api/v1`) and this rewrite forwards it
 * to the backend server-side. The browser only ever talks to the origin it
 * loaded from, which also means no CORS and no second tunnel: whatever host
 * serves the page serves the API. Works identically on localhost.
 *
 * `API_PROXY_TARGET` exists so the backend can move (a different port, a
 * container) without editing this file.
 */
const API_TARGET = process.env.API_PROXY_TARGET || 'http://127.0.0.1:8000';

const nextConfig = {
  outputFileTracingRoot: __dirname,

  /* A PRODUCTION BUILD MUST NOT SHARE `.next` WITH A RUNNING DEV SERVER.
   *
   * Both write there. Running `next build` while `next dev` is up replaces the
   * chunk files the dev server's in-memory manifest still points at, and the
   * next request dies with `Cannot find module './5611.js'` from
   * .next/server/webpack-runtime.js -- an error that names a file nobody wrote
   * and gives no hint that a second process is the cause. Recovery is deleting
   * .next and restarting.
   *
   * So a build can be sent elsewhere:  NEXT_DIST_DIR=.next-build npm run build
   * Unset, behaviour is exactly as before.
   */
  distDir: process.env.NEXT_DIST_DIR || '.next',

  async rewrites() {
    return [
      { source: '/api/v1/:path*', destination: `${API_TARGET}/api/v1/:path*` },
    ];
  },

  // Next's dev server refuses cross-origin requests from hosts it does not
  // know, which is every tunnel URL. Dev-only; it has no effect on a build.
  // `.dev` as well as `.app`: ngrok hands out both, and a missing entry here
  // fails as a blocked cross-origin request rather than anything that names the
  // allowlist, so it is worth listing every form.
  allowedDevOrigins: [
    '*.ngrok-free.dev', '*.ngrok-free.app', '*.ngrok.app', '*.ngrok.io',
    '*.trycloudflare.com',
  ],
};

module.exports = nextConfig;
