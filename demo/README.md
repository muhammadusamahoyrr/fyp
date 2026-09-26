# Running the Attorney.AI demo on this laptop

Brings up the agreement-signing demo so an invited signer can open their link on
a **phone** — no account, no deployment.

```powershell
# Administrator PowerShell, from the repo root
.\demo\start-demo.ps1
```

It prints a `https://….ngrok-free.dev` URL. That is the demo.

To shut everything down:

```powershell
.\demo\stop-demo.ps1
```

---

## What it does, and why in that order

```
  free :3000  →  frontend :3000  →  ngrok  →  read URL  →  write .env  →  backend :8000
```

The order is the whole reason this is a script rather than four commands.

**The backend reads `FRONTEND_URL` once, at import** (`app/core/config.py`,
`settings = Settings()`), and that value is written into every invitation email
at the moment it is sent. ngrok's free tier issues a **new URL on every start**.
So the tunnel must exist, and its URL must be in `.env`, *before* the backend
starts. Get this backwards and every emailed link points at the previous tunnel
or at `localhost` — and it fails silently, in somebody else's inbox, with
nothing in your logs.

`--reload` does **not** save you here: `watchfiles` ignores dotfiles, so editing
`.env` never triggers a reload. The backend has to be started after the write.

**One tunnel, not two.** `next.config.js` rewrites `/api/v1/*` to
`http://127.0.0.1:8000` server-side, so the page and the API share an origin.
The phone talks only to the ngrok host; the API hop happens on your laptop. That
also means no CORS and no second URL to keep in sync.

---

## Port 3000 and the VPN

`EonVPNRoutingService` binds `127.0.0.1:3000` and is `StartType=Automatic`, so
**it reclaims the port on every boot**. When it wins, ngrok forwards to *it*, and
the symptom is a `307` redirect loop that looks nothing like a port conflict —
the page never loads and no error mentions the VPN.

`start-demo.ps1` stops both EonVPN services when run as Administrator. To stop
them reclaiming the port permanently:

```powershell
Set-Service EonVPNRoutingService -StartupType Manual
```

Reversible with `-StartupType Automatic`.

---

## Demo script

1. Open the printed URL → **Agreements** → **Create**
2. **Replace the `[UNREVIEWED SAMPLE — NOT LEGAL CONTENT]` text.** The server
   refuses any body still containing that marker, at create *and* at sign. All
   six built-in templates carry it pending review by a Pakistani lawyer.
3. **Add Signers** → *Invite by email* → real addresses (2 others max; the cap
   is 3 parties including you)
4. **Your Signature** → draw, type or upload
5. **Review & Send**
6. The panel then shows, per recipient, whether the email actually went out —
   and every one-time link, **once**. Only hashes are stored, so a link you
   don't copy cannot be recovered; that invitation would have to be reissued.
7. The signer opens the link on their phone, reads the agreement, signs. No
   account.

---

## Things that will end a demo

| | |
|---|---|
| **Restarting ngrok** | new URL; every link already emailed is dead |
| **Rebooting** | EonVPN takes :3000 again unless set to Manual |
| **7 days** | invitation links expire (`invitation_token.DEFAULT_TTL_DAYS`) |
| **90 days** | the agreement itself expires and can no longer be signed |
| **ngrok interstitial** | free tier shows a "You are about to visit…" page with a **Visit Site** button on first load — harmless, but warn your audience |

---

## Configuration this relies on

In `backend/.env` (all gitignored, none of it committed):

| Key | Purpose |
|---|---|
| `SMTP_USER` / `SMTP_PASSWORD` | the Gmail App Password (16 chars, needs 2FA on the account) |
| `EMAIL_FROM` | must equal `SMTP_USER`, or Gmail rewrites or rejects the header |
| `FRONTEND_URL` | written by the script on each run |
| `AGREEMENTS_DIY_BUILDER_ENABLED=true` | without it the builder is parked and the server returns 403 |
| `SIGNATURE_ENCRYPTION_KEY` | required — signing refuses rather than storing a signature in clear |

In `frontend/.env.local`:

| Key | Purpose |
|---|---|
| `NEXT_PUBLIC_API_URL=/api/v1` | **relative on purpose** — an absolute `localhost:8000` would resolve to the *signer's* machine |
| `NEXT_PUBLIC_AGREEMENTS_DIY_ENABLED=true` | shows Templates/Create in the sidebar |

If SMTP is unset the demo still runs: nothing is emailed, and the panel says so
rather than claiming a delivery that did not happen.

---

## When something is wrong

| Symptom | Cause |
|---|---|
| `307` loop, page never loads | EonVPN holds :3000 — run the script as Administrator |
| Links in emails say `localhost:3000` | backend started before `.env` was written — restart it |
| "no mail server is configured" in the panel | `SMTP_USER`/`SMTP_PASSWORD` empty |
| Signer gets "Invitation not found" | the link came from a different database (a test run) or the tunnel changed |
| `Sign & Send` refused | the `[UNREVIEWED SAMPLE]` marker is still in the body |

Check what actually owns a port before believing any other explanation:

```powershell
Get-NetTCPConnection -LocalPort 3000 -State Listen |
  ForEach-Object { Get-Process -Id $_.OwningProcess }
```
