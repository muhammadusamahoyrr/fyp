# UI Audit Report — Full Codebase

Comprehensive audit of every frontend file for broken layouts, misalignment, overflow, inconsistent styles, responsiveness problems, console errors, broken links/buttons, logic bugs, and missing states.

---

## Severity: Critical (Logic Bugs)

### 1. `!viewMode === v` — always `false`
* **File**: [AppointmentsPage.jsx](file:///c:/Users/The%20Laptop%20Hut/Desktop/attorney-ai/frontend/src/components/lawyer/AppointmentsPage.jsx#L535-L544)
* **What's Wrong**: The hover handlers for the List/Calendar toggle use `!viewMode === v`. JavaScript evaluates `!viewMode` first (producing a boolean), then compares it to the string `v`. The condition is **always false**, so the non-active button never receives hover styles.
* **Fix**: Change `!viewMode === v` → `viewMode !== v` on lines 535 and 541.

### 2. `isComm` ReferenceError crashes app when topbar visible
* **File**: [layout.jsx](file:///c:/Users/The%20Laptop%20Hut/Desktop/attorney-ai/frontend/src/components/lawyer/layout.jsx#L514)
* **What's Wrong**: Line 514 references `{isComm && (`. However, the variable `isComm` is never defined inside the `Topbar` component or its file scope. If the topbar is ever shown (i.e. `hideTopbar` set to `false` in `App.jsx`), this immediately crashes the application with a `ReferenceError: isComm is not defined`.
* **Fix**: Define `const isComm = page === "communication";` inside the `Topbar` component to prevent the crash and correctly toggle the communication search bar.

### 3. Direct fetch bypasses JWT auto-refresh in API Client
* **File**: [api.js](file:///c:/Users/The%20Laptop%20Hut/Desktop/attorney-ai/frontend/src/lib/api.js#L461)
* **What's Wrong**: Functions like `downloadDocument`, `downloadReceipt`, `aiQueryStream`, `aiDraftStream`, and `aiPleadingUrduStream` use browser-native `fetch()` directly instead of the `apiFetch` wrapper. They completely bypass the automatic access token refresh handling on 401. If the access token has expired (which happens every 15-30 minutes), these streaming or download features will fail silently with a `401 Unauthorized` response.
* **Fix**: Add a `returnResponse` option to `apiFetch` that resolves with the raw `Response` on success (instead of parsing JSON) so that callers can call `.blob()` or `.body.getReader()`, then refactor the direct fetch helpers to use `apiFetch` with this option.

### 4. WebSocket Ticket fetch bypasses JWT auto-refresh
* **File**: [ModChatbot.jsx](file:///c:/Users/The%20Laptop%20Hut/Desktop/attorney-ai/frontend/src/components/client/ModChatbot.jsx#L68)
* **What's Wrong**: Line 68 has a direct `fetch` call to exchange the JWT token for a one-time WebSocket ticket: `fetch(`${apiBase}/api/v1/auth/ws-ticket`, ...)`. This raw fetch does not trigger token auto-refresh, so if the JWT token has expired (e.g. after 15–30 minutes of session activity), the AI chatbot connection will fail to connect with a 401 error.
* **Fix**: Use `apiFetch` instead of raw `fetch` for this request to benefit from token auto-retries.

---

## Severity: High (Breaking Layouts & Responsiveness)

### 2. Login Page — Absolute Positioning Overlap
* **File**: [login/page.jsx](file:///c:/Users/The%20Laptop%20Hut/Desktop/attorney-ai/frontend/src/app/(auth)/login/page.jsx#L113-L365)
* **What's Wrong**: Left hero column (`left: 64`) and right login card (`right: 72`) both use `position: absolute` with no media queries. On viewports under ~1000 px they overlap completely, rendering all content unusable.
* **Fix**: Replace with a flex row that stacks to a column on small screens.

### 3. Register Page — Same Absolute Overlap
* **File**: [register/page.jsx](file:///c:/Users/The%20Laptop%20Hut/Desktop/attorney-ai/frontend/src/app/(auth)/register/page.jsx#L179-L234)
* **What's Wrong**: Identical pattern — hero at `left: 64`, card at `right: 72`, both `position: absolute`. Tablet and mobile users see an unreadable overlap.
* **Fix**: Same as #2 — responsive flex layout.

### 4. Admin Dashboard — Hardcoded 4-Column Grid
* **File**: [AdminDashboard.jsx](file:///c:/Users/The%20Laptop%20Hut/Desktop/attorney-ai/frontend/src/components/admin/AdminDashboard.jsx#L76)
* **What's Wrong**: `gridTemplateColumns: "repeat(4,1fr)"` is used for stat cards. On any screen under ~900 px this causes severe squishing and text clipping. The `"1fr 320px"` chart grid (line 83) also overflows on mobile.
* **Fix**: Use `repeat(auto-fit, minmax(200px, 1fr))` for stats. For charts, use `repeat(auto-fit, minmax(280px, 1fr))`.

### 5. Admin Sidebar — No Mobile Breakpoint
* **File**: [AdminApp.jsx](file:///c:/Users/The%20Laptop%20Hut/Desktop/attorney-ai/frontend/src/components/admin/AdminApp.jsx#L56)
* **What's Wrong**: The admin sidebar is a fixed 220 px `<aside>` with no mobile drawer/hamburger. On phones, it consumes most of the viewport width.
* **Fix**: Add a mobile hamburger drawer like the client dashboard already has.

### 6. Admin KYC — 3-Column Grid Overflow
* **File**: [AdminKYCVerification.jsx](file:///c:/Users/The%20Laptop%20Hut/Desktop/attorney-ai/frontend/src/components/admin/AdminKYCVerification.jsx#L88)
* **What's Wrong**: `gridTemplateColumns: "repeat(3,1fr)"` — the stat cards clip on mobile/tablet.
* **Fix**: `repeat(auto-fit, minmax(200px, 1fr))`.

### 7. Lawyer Dashboard — Hardcoded 4-Column Grid
* **File**: [DashboardPage.jsx](file:///c:/Users/The%20Laptop%20Hut/Desktop/attorney-ai/frontend/src/components/lawyer/DashboardPage.jsx#L67-L79)
* **What's Wrong**: `gridTemplateColumns: "repeat(4,1fr)"` for practice stats — severe squishing on mobile.
* **Fix**: `repeat(auto-fit, minmax(200px, 1fr))`.

### 8. Lawyer Cases & Appointments — Non-Responsive Grids
* **File**: [CasesPage.jsx](file:///c:/Users/The%20Laptop%20Hut/Desktop/attorney-ai/frontend/src/components/lawyer/CasesPage.jsx) & [AppointmentsPage.jsx](file:///c:/Users/The%20Laptop%20Hut/Desktop/attorney-ai/frontend/src/components/lawyer/AppointmentsPage.jsx#L556-L560)
* **What's Wrong**: Multiple hardcoded grids: `repeat(4,1fr)`, `1fr 1fr`, `1fr 260px`. All overflow on screens under 800 px.
* **Fix**: `repeat(auto-fit, minmax(220px, 1fr))` for card grids; stack the side column below on mobile.

### 9. Lawyer Clients — 3-Column Grid Overflow
* **File**: [ClientsPage.jsx](file:///c:/Users/The%20Laptop%20Hut/Desktop/attorney-ai/frontend/src/components/lawyer/ClientsPage.jsx#L78)
* **What's Wrong**: `gridTemplateColumns: "repeat(3,1fr)"` for client cards — clips on mobile.
* **Fix**: `repeat(auto-fit, minmax(260px, 1fr))`.

### 10. Onboarding Final Screen — Grid & Flex Overflow
* **File**: [OnboardingPage.jsx](file:///c:/Users/The%20Laptop%20Hut/Desktop/attorney-ai/frontend/src/components/lawyer/OnboardingPage.jsx#L1012-L1042)
* **What's Wrong**: Status cards use `"1fr 1fr 1fr"` without wrapping; the progress flex row has a child with `width: 240` that clips.
* **Fix**: `repeat(auto-fit, minmax(250px, 1fr))` for the grid; add `flexWrap: "wrap"` on the progress bar row.

### 11. Client ModTools Inheritance — Fixed 2-Column Grid
* **File**: [ModTools.jsx](file:///c:/Users/The%20Laptop%20Hut/Desktop/attorney-ai/frontend/src/components/client/ModTools.jsx#L107)
* **What's Wrong**: `gridTemplateColumns: "minmax(300px, 380px) 1fr"` — on screens under 700 px the two columns overlap and the results panel clips.
* **Fix**: Stack to a single column on small viewports: `repeat(auto-fit, minmax(300px, 1fr))`.

### 12. ModAgreements, ModOverview & ModDocuments — Non-Responsive Grids
* **Files**: [ModAgreements.jsx](file:///c:/Users/The%20Laptop%20Hut/Desktop/attorney-ai/frontend/src/components/client/ModAgreements.jsx#L229), [ModOverview.jsx](file:///c:/Users/The%20Laptop%20Hut/Desktop/attorney-ai/frontend/src/components/client/ModOverview.jsx#L54), [ModDocuments.jsx](file:///c:/Users/The%20Laptop%20Hut/Desktop/attorney-ai/frontend/src/components/client/ModDocuments.jsx#L334)
* **What's Wrong**: Hardcoded columns like `repeat(4, 1fr)` for dashboard/template grid metrics squeeze layouts on small viewports, causing text overflows and misalignments.
* **Fix**: Replace with responsive auto-fit layouts or stack elements in column flex direction below 768px.

### 13. Lawyer ProfilePage — Fixed Grid Columns
* **File**: [ProfilePage.jsx](file:///c:/Users/The%20Laptop%20Hut/Desktop/attorney-ai/frontend/src/components/lawyer/ProfilePage.jsx#L81)
* **What's Wrong**: `gridTemplateColumns: "250px 1fr"` and `gridTemplateColumns: "1fr 1fr"` for profile details squish card layouts and input fields on tablets and mobile screens, clipping text labels.
* **Fix**: Use media queries or flexible grid properties to stack components vertically on mobile viewports.

### 14. client/ModProfile — Non-Responsive Grids
* **File**: [ModProfile.jsx](file:///c:/Users/The%20Laptop%20Hut/Desktop/attorney-ai/frontend/src/components/client/ModProfile.jsx#L519)
* **What's Wrong**: Uses hardcoded column structures like `gridTemplateColumns: "1fr 1fr 1fr 1fr"` for personal details, and `1fr 1fr` in edit mode. On screen widths below 768px, text labels overlap and metrics become squished and unreadable.
* **Fix**: Stack fields into a single column using CSS media queries or responsive wrapping properties on mobile.

### 15. OnboardingPage — Step 1 & Step 2 Rigid Columns
* **File**: [OnboardingPage.jsx](file:///c:/Users/The%20Laptop%20Hut/Desktop/attorney-ai/frontend/src/components/lawyer/OnboardingPage.jsx#L378)
* **What's Wrong**: Both Step 1 (line 378) and Step 2 (line 808) use `gridTemplateColumns: "1fr 1fr 1fr"` to divide main forms and fields into side-by-side columns. On narrow tablets and mobile screens, this causes severe squishing, overlapping text fields, and clips content.
* **Fix**: Stack form cards vertically on mobile or convert columns to `repeat(auto-fit, minmax(280px, 1fr))`.

### 16. AgreementsPage — Non-Responsive Stats Cards Grid
* **File**: [AgreementsPage.jsx](file:///c:/Users/The%20Laptop%20Hut/Desktop/attorney-ai/frontend/src/components/lawyer/AgreementsPage.jsx#L73)
* **What's Wrong**: Hardcoded 3-column stats card wrapper `gridTemplateColumns: "repeat(3,1fr)"` squishes label texts and value counters on viewports under 600px, causing text clipping.
* **Fix**: Use flex-wrap or auto-fit grids (`repeat(auto-fit, minmax(180px, 1fr))`) to stack stats cards vertically on mobile.

### 17. SettingsPage — Rigid Password Fields Grid
* **File**: [SettingsPage.jsx](file:///c:/Users/The%20Laptop%20Hut/Desktop/attorney-ai/frontend/src/components/lawyer/SettingsPage.jsx#L117)
* **What's Wrong**: Line 117 places the New Password and Confirm fields in a rigid `1fr 1fr` grid columns. On screens under 600px wide, the text inputs are squished side-by-side.
* **Fix**: Stack password input fields vertically on smaller screen widths.

### 18. ModDocuments — Non-Responsive Workspace Grids
* **File**: [ModDocuments.jsx](file:///c:/Users/The%20Laptop%20Hut/Desktop/attorney-ai/frontend/src/components/client/ModDocuments.jsx#L334)
* **What's Wrong**: Uses rigid column structures like `gridTemplateColumns: "1fr 280px"`, `"1fr 300px"`, `"2fr 1fr"`, and `"repeat(3, minmax(0,1fr))"` across document search lists, review states, and editing workspaces. These layouts squash sidebar lists, previews, and edit canvases under 800px.
* **Fix**: Leverage `useIsMobile()` to transition to a single-column layout on mobile viewports.

### 19. ModOverseas — Rigid POA Form Grids
* **File**: [ModOverseas.jsx](file:///c:/Users/The%20Laptop%20Hut/Desktop/attorney-ai/frontend/src/components/client/ModOverseas.jsx#L219)
* **What's Wrong**: The Power of Attorney form fields are split into hardcoded side-by-side columns: `gridTemplateColumns: "1fr 1fr"`. On mobile sizes, these CNIC/Relation inputs are squished to a tiny layout.
* **Fix**: Stack inputs vertically on mobile.

### 20. ModLawyers — Rigid Profile Split Grid
* **File**: [ModLawyers.jsx](file:///c:/Users/The%20Laptop%20Hut/Desktop/attorney-ai/frontend/src/components/client/ModLawyers.jsx#L764)
* **What's Wrong**: The lawyer details view uses `gridTemplateColumns: "1fr 1fr"` to show bio details next to reviews, and case inputs side-by-side. This results in cramped texts and misalignments on mobile screen widths.
* **Fix**: Stack elements vertically under 768px.

### 21. Architectural Omission: `useIsMobile` Hook Underutilization
* **Files**: [ModDocuments.jsx](file:///c:/Users/The%20Laptop%20Hut/Desktop/attorney-ai/frontend/src/components/client/ModDocuments.jsx), [ModOverseas.jsx](file:///c:/Users/The%20Laptop%20Hut/Desktop/attorney-ai/frontend/src/components/client/ModOverseas.jsx), [ModLawyers.jsx](file:///c:/Users/The%20Laptop%20Hut/Desktop/attorney-ai/frontend/src/components/client/ModLawyers.jsx)
* **What's Wrong**: While [ModIntake.jsx](file:///c:/Users/The%20Laptop%20Hut/Desktop/attorney-ai/frontend/src/components/client/ModIntake.jsx#L101) correctly imports and uses the responsive custom hook `useIsMobile()` to dynamically adapt its grid layouts, the rest of the client modules completely omit it and rely on rigid layout styles, leading to inconsistencies.
* **Fix**: Import and utilize `useIsMobile()` in these modules to dynamically adjust grid column CSS definitions.

---

## Severity: Medium (Sidebar Gaps, Code Quality & Console)

### 12. Lawyer Sidebar — Rigid Width, No Mobile Drawer
* **File**: [layout.jsx](file:///c:/Users/The%20Laptop%20Hut/Desktop/attorney-ai/frontend/src/components/lawyer/layout.jsx#L266-L275)
* **What's Wrong**: Sidebar is `width: collapsed ? 56 : 240` on all viewports, leaving no room on mobile. Unlike the client dashboard (which has `isMobile` checks and a slide-in drawer), the lawyer sidebar has no mobile breakpoint.
* **Fix**: Implement a slide-in overlay drawer with a hamburger trigger on mobile, matching the client dashboard pattern.

### 13. DocAutomationPage — Hardcoded Fixed Position Offset
* **File**: [DocAutomationPage.jsx](file:///c:/Users/The%20Laptop%20Hut/Desktop/attorney-ai/frontend/src/components/lawyer/DocAutomationPage.jsx#L955)
* **What's Wrong**: Uses `position: "fixed"` with `left: sidebarCollapsed ? 56 : 240`. On mobile (where the sidebar should be hidden), this still reserves 56–240 px of dead space.
* **Fix**: When sidebar is hidden on mobile, set `left: 0`.

### 14. Hydration Mismatch Console Warning
* **File**: [layout.jsx](file:///c:/Users/The%20Laptop%20Hut/Desktop/attorney-ai/frontend/src/app/layout.jsx#L12-L13)
* **What's Wrong**: `<html>` and `<body>` tags lack `suppressHydrationWarning`, causing a console warning when browser extensions or client-side theme scripts inject attributes before hydration completes.
* **Fix**:
  ```jsx
  <html lang="en-PK" suppressHydrationWarning>
    <body suppressHydrationWarning>
  ```

### 15. Dead Code Components in CasesPage
* **File**: [CasesPage.jsx](file:///c:/Users/The%20Laptop%20Hut/Desktop/attorney-ai/frontend/src/components/lawyer/CasesPage.jsx#L13-L240)
* **What's Wrong**: Three large components (`WorkspaceOverview`, `WorkspaceDocuments`, `WorkspaceHearings`) are declared but never used — ~230 lines of dead code inflating the bundle.
* **Fix**: Delete these three unused components.

### 16. Empty UI Stub Components
* **Files**: [Button.jsx](file:///c:/Users/The%20Laptop%20Hut/Desktop/attorney-ai/frontend/src/components/ui/Button.jsx), [Card.jsx](file:///c:/Users/The%20Laptop%20Hut/Desktop/attorney-ai/frontend/src/components/ui/Card.jsx), [Input.jsx](file:///c:/Users/The%20Laptop%20Hut/Desktop/attorney-ai/frontend/src/components/ui/Input.jsx), [Modal.jsx](file:///c:/Users/The%20Laptop%20Hut/Desktop/attorney-ai/frontend/src/components/ui/Modal.jsx), [Table.jsx](file:///c:/Users/The%20Laptop%20Hut/Desktop/attorney-ai/frontend/src/components/ui/Table.jsx), [Spinner.jsx](file:///c:/Users/The%20Laptop%20Hut/Desktop/attorney-ai/frontend/src/components/ui/Spinner.jsx)
* **What's Wrong**: All 6 files in `/components/ui/` are empty stubs (comment-only or trivially empty). They export nothing, so any import would fail at runtime.
* **Fix**: Either implement them with real primitives, or delete them and remove any imports.

### 17. Notification Drawer Hardcoded Width
* **File**: [Dashboard.jsx](file:///c:/Users/The%20Laptop%20Hut/Desktop/attorney-ai/frontend/src/components/client/Dashboard.jsx#L88) (client)
* **What's Wrong**: The `NotifDrawer` is `width: 380`. On phones (< 400 px wide), it overflows the viewport since it's `position: absolute; right: 0`.
* **Fix**: Cap to `width: min(380px, 100vw)` or use percentage-based width on mobile.

### 18. ModAgreements & ModTracking — Cluttered Nested Layouts
* **Files**: [ModAgreements.jsx](file:///c:/Users/The%20Laptop%20Hut/Desktop/attorney-ai/frontend/src/components/client/ModAgreements.jsx) and [ModTracking.jsx](file:///c:/Users/The%20Laptop%20Hut/Desktop/attorney-ai/frontend/src/components/client/ModTracking.jsx)
* **What's Wrong**: These modules render a nested Sidebar and Topbar *inside* the parent client Dashboard viewport. This double sidebar/topbar structure is visually cluttered and eats up significant horizontal space, especially on small/tablet viewports.
* **Fix**: Hide or collapse the nested sidebar/header on screen widths below 1024px, or implement a responsive navigation switcher (e.g. mobile tab strip or dropdown).

### 19. Duplicated & Fragile Auth State Hydration in AuthContext
* **File**: [AuthContext.jsx](file:///c:/Users/The%20Laptop%20Hut/Desktop/attorney-ai/frontend/src/context/AuthContext.jsx#L27)
* **What's Wrong**: On lines 27 and 48, raw `fetch` calls are made to `${BASE}/users/me` directly, bypassing the unified `getMe` helper function defined in `api.js`. This duplicates endpoints and makes profile state bootstrapping fragile under token expiration, lacking formatResponseError.
* **Fix**: Import and utilize `getMe` from `@/lib/api` in place of the raw fetch calls.

---

## Severity: Low (Minor UI & Form Usability Gaps)

### 18. Login Loading UX Shift
* **File**: [login/page.jsx](file:///c:/Users/The%20Laptop%20Hut/Desktop/attorney-ai/frontend/src/app/(auth)/login/page.jsx#L341-L352)
* **What's Wrong**: The "Sign In" button is replaced by plain text `"Checking session…"` during auth bootstrap, causing a brief layout shift and unstyled appearance.
* **Fix**: Render a loading spinner inside the same button dimensions instead.

### 19. Appointments Date Input — Manual Text Entry
* **File**: [AppointmentsPage.jsx](file:///c:/Users/The%20Laptop%20Hut/Desktop/attorney-ai/frontend/src/components/lawyer/AppointmentsPage.jsx#L227-L232)
* **What's Wrong**: Appointment date uses `<input type="text">` with a placeholder like `"YYYY-MM-DD"` instead of a native date picker, making mobile input very error-prone.
* **Fix**: Use `<input type="date">`.

### 20. Public Landing Page — Missing `/hero.png` Fallback
* **File**: [Landing.jsx](file:///c:/Users/The%20Laptop%20Hut/Desktop/attorney-ai/frontend/src/components/shared/Landing.jsx#L32)
* **What's Wrong**: `<img src="/hero.png" />` and `<img src="/illustrate.png" />` have no `onError` fallback. If these images are missing from the `/public` directory, the hero section renders a broken image icon.
* **Fix**: Add an `onError` handler that hides the image or shows a CSS gradient placeholder.

### 21. client/ModOverview — Literal `&amp;` instead of `&`
* **File**: [ModOverview.jsx](file:///c:/Users/The%20Laptop%20Hut/Desktop/attorney-ai/frontend/src/components/client/ModOverview.jsx#L160)
* **What's Wrong**: Renders the literal text `based on evidence &amp; precedents.`. In React/JSX text content, literal `&amp;` renders literally as `&amp;` instead of a single ampersand.
* **Fix**: Replace `&amp;` with `&`.

### 22. CauselistPage — Input Field Box-Sizing Misalignment
* **File**: [CauselistPage.jsx](file:///c:/Users/The%20Laptop%20Hut/Desktop/attorney-ai/frontend/src/components/lawyer/CauselistPage.jsx#L124)
* **What's Wrong**: The add-watch input fields on lines 124–130 do not have `boxSizing: "border-box"`. When browser borders and padding are added to their custom heights/widths, they align unevenly with the adjacent `+ Watch` button.
* **Fix**: Add `boxSizing: "border-box"` to `inputStyle` on line 95.

---

## Summary Table

| # | Severity | Component | Issue |
|---|----------|-----------|-------|
| 1 | **Critical** | AppointmentsPage | `!viewMode === v` always false — broken hover |
| 2 | **Critical** | Topbar (lawyer) | `isComm` ReferenceError crashes app when topbar visible |
| 3 | **Critical** | API Client (api.js) | Streaming and downloads direct fetch bypasses token refresh |
| 4 | **Critical** | ModChatbot (client) | WS ticket fetch bypasses JWT token auto-refresh |
| 5 | **High** | Login page | Absolute position overlap on mobile |
| 6 | **High** | Register page | Same absolute position overlap |
| 7 | **High** | Admin Dashboard | `repeat(4,1fr)` + `1fr 320px` grids |
| 8 | **High** | Admin sidebar | No mobile drawer |
| 9 | **High** | Admin KYC | `repeat(3,1fr)` grid overflow |
| 10 | **High** | Lawyer Dashboard | `repeat(4,1fr)` grid overflow |
| 11 | **High** | Cases & Appointments | Multiple hardcoded grids |
| 12 | **High** | Lawyer Clients | `repeat(3,1fr)` grid overflow |
| 13 | **High** | Onboarding | 3-col grid + fixed-width flex |
| 14 | **High** | ModTools | 2-col grid clips on mobile |
| 15 | **High** | ModAgreements | Hardcoded grids overflow on small screens |
| 16 | **High** | ModOverview (client) | Hardcoded grids overflow on small screens |
| 17 | **High** | ModDocuments (client) | Hardcoded grids overflow on small screens |
| 18 | **High** | ProfilePage (lawyer) | Fixed column grid `250px 1fr` overflows |
| 19 | **High** | ModProfile (client) | Non-responsive grid `1fr 1fr 1fr 1fr` squishes text |
| 20 | **High** | OnboardingPage (lawyer) | Step 1 & 2 side-by-side forms squishing on mobile |
| 21 | **High** | AgreementsPage (lawyer) | Stats cards grid `repeat(3,1fr)` wraps and clips |
| 22 | **High** | SettingsPage (lawyer) | Side-by-side password inputs cramped on mobile |
| 23 | **High** | ModDocuments (client) | Non-responsive document workspaces and list sidebars |
| 24 | **High** | ModOverseas (client) | POA form fields rigid side-by-side grids `1fr 1fr` |
| 25 | **High** | ModLawyers (client) | Profile view grid split `1fr 1fr` overflows on mobile |
| 26 | **High** | Client Portal | Custom hook `useIsMobile()` underutilized in layouts |
| 27 | **Medium** | Lawyer sidebar | No mobile breakpoint |
| 28 | **Medium** | DocAutomation | Fixed `left` offset ignores mobile |
| 29 | **Medium** | Root layout | Hydration warning |
| 30 | **Medium** | CasesPage | 230 lines dead code |
| 31 | **Medium** | `/ui/` stubs | 6 empty files — broken imports |
| 32 | **Medium** | Client NotifDrawer | Overflows viewport on phones |
| 33 | **Medium** | ModAgreements/ModTracking | Nested Sidebar/Topbar UI clutter and screen squeeze |
| 34 | **Medium** | AuthContext | Duplicated raw fetch bypasses API client retry/refresh |
| 35 | **Low** | Login page | "Checking session" layout shift |
| 36 | **Low** | AppointmentsPage | Manual text date input |
| 37 | **Low** | Landing page | No broken image fallback |
| 38 | **Low** | ModOverview (client) | Literal `&amp;` rendered instead of `&` |
| 39 | **Low** | CauselistPage | Box-sizing omission causes uneven alignment |
