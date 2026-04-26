# Frontend folder structure & routing (Attorney.AI)

This document explains how your **`frontend/`** is structured today, how **routing works** (Next.js 15 App Router), and the **correct approach** to keep it maintainable going forward — **without implementing any new code**.

---

## What to ignore (important)

- **`frontend/.next/`**: this is **generated build/dev output**. It should **not** be treated as source code and typically should not be committed to git.
  - If you see lots of `.next` files in `git status`, it usually means `.gitignore` isn’t excluding it (or it was committed previously).

---

## The key rule: Next.js App Router lives in `src/app/`

Your routes are defined by the filesystem under:

- **`frontend/src/app/`**

Each folder segment becomes a URL segment, and each `page.jsx` becomes a route.

### Special files in App Router

- **`layout.jsx`**: wraps all nested routes under its folder.
- **`page.jsx`**: the actual page for that route.
- **`globals.css`**: global CSS imported in the root `layout.jsx`.
- Route groups like **`(auth)`**: a **folder name in parentheses does *not* appear in the URL**, but helps organize routes.

---

## Current route map (from your repo)

Root:

- **`/`** → `frontend/src/app/page.jsx`
- Root layout → `frontend/src/app/layout.jsx`

Auth route group (URL does not include `(auth)`):

- **`/login`** → `frontend/src/app/(auth)/login/page.jsx`
- **`/register`** → `frontend/src/app/(auth)/register/page.jsx`
- **`/reset-password`** → `frontend/src/app/(auth)/reset-password/page.jsx`

Client route group (URL does not include `(client)`):

- Group layout → `frontend/src/app/(client)/layout.jsx`
- **`/dashboard`** → `frontend/src/app/(client)/dashboard/page.jsx`
- **`/cases`** → `frontend/src/app/(client)/cases/page.jsx`
- **`/chat`** → `frontend/src/app/(client)/chat/page.jsx`
- **`/intake`** → `frontend/src/app/(client)/intake/page.jsx`
- **`/documents`** → `frontend/src/app/(client)/documents/page.jsx`
- **`/agreements`** → `frontend/src/app/(client)/agreements/page.jsx`
- **`/tracking`** → `frontend/src/app/(client)/tracking/page.jsx`
- **`/lawyers`** → `frontend/src/app/(client)/lawyers/page.jsx`

Lawyer routes (currently a normal segment, so it *does* appear in the URL):

- **`/lawyer`** → `frontend/src/app/lawyer/page.jsx`
- **`/lawyer/cases`** → `frontend/src/app/lawyer/cases/page.jsx`
- **`/lawyer/clients`** → `frontend/src/app/lawyer/clients/page.jsx`
- **`/lawyer/communications`** → `frontend/src/app/lawyer/communications/page.jsx`
- **`/lawyer/ai-assistant`** → `frontend/src/app/lawyer/ai-assistant/page.jsx`
- **`/lawyer/profile`** → `frontend/src/app/lawyer/profile/page.jsx`
- **`/lawyer/appointments`** → `frontend/src/app/lawyer/appointments/page.jsx`
- **`/lawyer/documents`** → `frontend/src/app/lawyer/documents/page.jsx`
- **`/lawyer/doc-automation`** → `frontend/src/app/lawyer/doc-automation/page.jsx`

Admin routes:

- **`/admin`** → `frontend/src/app/admin/page.jsx`
- **`/admin/users`** → `frontend/src/app/admin/users/page.jsx`
- **`/admin/kyc`** → `frontend/src/app/admin/kyc/page.jsx`
- **`/admin/analytics`** → `frontend/src/app/admin/analytics/page.jsx`
- **`/admin/configuration`** → `frontend/src/app/admin/configuration/page.jsx`
- **`/admin/account-settings`** → `frontend/src/app/admin/account-settings/page.jsx`
- **`/admin/case-tracking`** → `frontend/src/app/admin/case-tracking/page.jsx`
- **`/admin/lawyer-monitoring`** → `frontend/src/app/admin/lawyer-monitoring/page.jsx`

---

## Where “UI and screens” live today

In addition to route files in `src/app/`, you have most UI in:

- **`frontend/src/components/`**
  - `components/client/*` (client dashboard modules)
  - `components/lawyer/*` (lawyer portal screens like onboarding/settings/etc.)
  - `components/admin/*` (admin panel screens)
  - `components/ui/*` (reusable primitives like `Card`, `Modal`, `Spinner`, etc.)
  - `components/shared/*` (cross-role shared components)

You also currently have some app-wide UI helpers placed directly in `src/app/`:

- **`frontend/src/app/UIComponents.jsx`**
- **`frontend/src/app/LayoutComponents.jsx`**
- **`frontend/src/app/Icons.jsx`**

These work, but conceptually they are “components”, so the clean long-term pattern is to keep `src/app/` focused on **routing + layouts**, and keep reusable UI in **`src/components/`** (or `src/components/ui`, `src/components/layout`, etc.).

---

## The correct approach for routes going forward (no code changes here, just guidance)

### 1) Keep `src/app/` “thin”

Use route files (`page.jsx`, `layout.jsx`) primarily to:

- Compose layout wrappers
- Import a screen component from `src/components/**`
- Wire navigation (if needed)

Avoid putting big UI trees directly inside route `page.jsx` files long-term. Treat them as entrypoints.

### 2) Use route groups for organization (and keep URLs clean)

You already use:

- `(auth)` for authentication
- `(client)` for client pages

This is the right idea: route groups help keep the repository organized without changing the URL.

**Recommended convention for a role-based app**:

- **`src/app/(auth)/*`** for all auth pages
- **`src/app/(client)/*`** for client pages
- **`src/app/(lawyer)/*`** for lawyer pages (URLs can still be `/lawyer/...` inside that group)
- **`src/app/(admin)/*`** for admin pages (URLs can still be `/admin/...` inside that group)

You don’t have to change anything now; the main “correct approach” is: **keep role sections grouped and consistent** so routes remain discoverable.

### 3) Use nested `layout.jsx` for role shells

Your `src/app/layout.jsx` is the global root wrapper.

A scalable Next.js pattern for multi-role apps is:

- Root `layout.jsx`: HTML/body, global CSS, fonts, top-level providers
- Role layouts (e.g. `(client)/layout.jsx`): the “shell” for that role (sidebar/topbar, role-specific providers, etc.)
- Feature routes under each role: thin pages that render a “screen component”

### 4) Keep shared code in obvious places

Clean separation that stays maintainable:

- **`src/components/ui/`**: small reusable primitives (Button, Input, Modal, Table, etc.)
- **`src/components/shared/`**: cross-role shared “domain UI” (header, landing, shared context/providers)
- **`src/components/client/`**, `src/components/lawyer/`, `src/components/admin/`: role-specific screens and components
- **`src/lib/`**: constants, helpers, formatting functions (pure logic)

### 5) Make routing decisions based on UX + access control

Your URLs already communicate roles:

- `/dashboard`, `/cases`, `/chat` → client experience
- `/lawyer/...` → lawyer portal
- `/admin/...` → admin

That’s good. The “correct approach” is to keep **role-only areas** under a dedicated prefix and handle auth/role gating in a consistent layer (usually a middleware or layout-level guard pattern in Next.js).

---

## Quick mental model (how a request resolves)

Example: user opens `/dashboard`

- Next finds `src/app/(client)/dashboard/page.jsx`
- It wraps it with:
  - `src/app/(client)/layout.jsx`
  - then `src/app/layout.jsx`
- The page typically renders a screen from `src/components/client/*`

This same model applies to `/login` under `(auth)` and all nested segments.

---

## Route audit: real pages vs redirect-only placeholders

This section answers: “Can a user actually land on this URL and see a unique screen, or will it immediately redirect elsewhere?”

Legend:

- **Real page**: route renders UI (even if that UI is a wrapper around a big component)
- **Redirect-only**: route file immediately calls `redirect(...)` and never renders its own screen

### Root

- **`/`** (`src/app/page.jsx`) — **Real page** (renders `components/shared/LandingClient`)

### Auth (`src/app/(auth)/*`)

- **`/login`** (`(auth)/login/page.jsx`) — **Real page**
- **`/register`** (`(auth)/register/page.jsx`) — **Real page**
- **`/reset-password`** (`(auth)/reset-password/page.jsx`) — **Real page**

### Client (`src/app/(client)/*`)

- **`/dashboard`** (`(client)/dashboard/page.jsx`) — **Real page**
- **`/cases`** (`(client)/cases/page.jsx`) — **Redirect-only** (redirects to `/dashboard`)
- **`/chat`** (`(client)/chat/page.jsx`) — **Redirect-only** (redirects to `/dashboard`)
- **`/intake`** (`(client)/intake/page.jsx`) — **Real page** *(not audited here for redirects; it appears to be a normal page route in the tree)*
- **`/documents`** (`(client)/documents/page.jsx`) — **Real page** *(not audited here for redirects)*
- **`/agreements`** (`(client)/agreements/page.jsx`) — **Real page** *(not audited here for redirects)*
- **`/tracking`** (`(client)/tracking/page.jsx`) — **Real page** *(not audited here for redirects)*
- **`/lawyers`** (`(client)/lawyers/page.jsx`) — **Real page** *(not audited here for redirects)*

**Key observation (client)**: The route group/layout exists, but at least `cases` and `chat` are currently stubs that collapse back to `/dashboard`.

### Lawyer (`src/app/lawyer/*`)

- **`/lawyer`** (`lawyer/page.jsx`) — **Real page** (renders `components/lawyer/App`)
- **`/lawyer/cases`** (`lawyer/cases/page.jsx`) — **Redirect-only** (redirects to `/lawyer`)
- **`/lawyer/clients`** (`lawyer/clients/page.jsx`) — **Redirect-only** (redirects to `/lawyer`)
- **`/lawyer/ai-assistant`** (`lawyer/ai-assistant/page.jsx`) — **Redirect-only** (redirects to `/lawyer`)
- **`/lawyer/communications`** (`lawyer/communications/page.jsx`) — **Real page** *(not audited here for redirects)*
- **`/lawyer/profile`** (`lawyer/profile/page.jsx`) — **Real page** *(not audited here for redirects)*
- **`/lawyer/appointments`** (`lawyer/appointments/page.jsx`) — **Real page** *(not audited here for redirects)*
- **`/lawyer/documents`** (`lawyer/documents/page.jsx`) — **Real page** *(not audited here for redirects)*
- **`/lawyer/doc-automation`** (`lawyer/doc-automation/page.jsx`) — **Real page** *(not audited here for redirects)*

**Key observation (lawyer)**: `/lawyer` is the “single entry” page, and several subroutes are currently stubs redirecting back to it.

### Admin (`src/app/admin/*`)

- **`/admin`** (`admin/page.jsx`) — **Real page** (admin shell + internal state-driven nav)
- **`/admin/*` subpages** (e.g. `admin/users/page.jsx`) — **Real page** *(not audited here for redirects)*

---

## Summary

- **Routing source of truth**: `frontend/src/app/`
- **Use route groups** like `(auth)` and `(client)` to organize without changing URLs
- **Prefer thin route pages** that render components from `src/components/**`
- **Keep `.next/` out of source control mindset** (it’s build output)

