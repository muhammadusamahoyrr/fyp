# SKILL: legal-ui-dashboard

## Purpose

Designs and implements the **2D/3D hybrid legal interface** — the HUD overlay, case data panels, evidence viewer, case timeline, and participant cards that layer on top of the 3D courtroom. This skill bridges the immersive 3D scene with the functional legal data interface.

## Architecture: Hybrid 2D + 3D UI

```
┌─────────────────────────────────────────────────────────────────┐
│  [CASE HEADER]   Case #2024-CR-0471 · Phase: Evidence          │
├──────────┬──────────────────────────────────────┬──────────────┤
│ CASE     │                                      │ EVIDENCE     │
│ SIDEBAR  │        3D COURTROOM SCENE            │ PANEL        │
│          │                                      │              │
│ Parties  │   ┌──────────────────────────────┐  │ [Ex. A] Doc  │
│ Timeline │   │   COURTROOM (Canvas)          │  │ [Ex. B] Vid  │
│ Charges  │   │                              │  │ [Ex. C] Phys │
│          │   └──────────────────────────────┘  │              │
├──────────┴──────────────────────────────────────┴──────────────┤
│  [PHASE CONTROLS]  ◄ Previous   Current: Evidence ►  Next      │
└─────────────────────────────────────────────────────────────────┘
```

## 3D-Anchored UI (Drei Html)

```jsx
import { Html } from '@react-three/drei'

// Floating label above the judge bench
function JudgeNameplate({ judgeName, position }) {
  return (
    <Html
      position={position}
      center
      distanceFactor={12}
      occlude
      style={{ pointerEvents: 'none' }}
    >
      <div className="nameplate">
        <span className="nameplate__title">THE HONORABLE</span>
        <span className="nameplate__name">{judgeName}</span>
      </div>
    </Html>
  )
}

// Evidence prop label (appears when hovered)
function EvidenceLabel({ item, position }) {
  return (
    <Html position={position} center distanceFactor={8}>
      <div className="evidence-tag">
        <span className="evidence-tag__id">Exhibit {item.id}</span>
        <span className="evidence-tag__type">{item.type}</span>
        <span className="evidence-tag__label">{item.label}</span>
      </div>
    </Html>
  )
}
```

## HUD Component

```jsx
export function CourtHUD({ sceneConfig, phase, onPhaseChange }) {
  const { parties, evidence, case_id, case_type } = sceneConfig

  return (
    <div className="court-hud">
      <CaseHeader caseId={case_id} type={case_type} phase={phase} />
      <PhaseTimeline current={phase} onChange={onPhaseChange} />
      <EvidencePanel items={evidence} />
      <PartyCards parties={parties} />
    </div>
  )
}
```

## CaseHeader

```jsx
const PHASE_LABELS = {
  intake: 'Intake',
  opening: 'Opening Statements',
  evidence: 'Evidence Presentation',
  cross_examination: 'Cross-Examination',
  closing: 'Closing Arguments',
  verdict: 'Verdict'
}

function CaseHeader({ caseId, type, phase }) {
  return (
    <header className="case-header">
      <div className="case-header__id">Case #{caseId}</div>
      <div className="case-header__type">{type.toUpperCase()} PROCEEDING</div>
      <div className="case-header__phase">
        <span className="phase-dot" data-phase={phase} />
        {PHASE_LABELS[phase]}
      </div>
    </header>
  )
}
```

## Phase Timeline Controls

```jsx
const PHASE_ORDER = ['intake','opening','evidence','cross_examination','closing','verdict']

function PhaseTimeline({ current, onChange }) {
  const idx = PHASE_ORDER.indexOf(current)

  return (
    <nav className="phase-timeline">
      <button
        disabled={idx === 0}
        onClick={() => onChange(PHASE_ORDER[idx - 1])}
      >
        ← Previous
      </button>
      <div className="phase-track">
        {PHASE_ORDER.map((p, i) => (
          <div
            key={p}
            className={`phase-step ${i === idx ? 'active' : ''} ${i < idx ? 'done' : ''}`}
            onClick={() => onChange(p)}
          >
            {PHASE_LABELS[p]}
          </div>
        ))}
      </div>
      <button
        disabled={idx === PHASE_ORDER.length - 1}
        onClick={() => onChange(PHASE_ORDER[idx + 1])}
      >
        Next →
      </button>
    </nav>
  )
}
```

## Evidence Panel

```jsx
const EVIDENCE_ICONS = {
  document: '📄',
  physical: '🔬',
  digital: '💻',
  testimony: '🎤'
}

function EvidencePanel({ items, onSelect }) {
  const [active, setActive] = useState(null)

  return (
    <aside className="evidence-panel">
      <h3 className="evidence-panel__title">Evidence</h3>
      <ul className="evidence-list">
        {items.map(item => (
          <li
            key={item.id}
            className={`evidence-item ${active === item.id ? 'active' : ''}`}
            onClick={() => { setActive(item.id); onSelect?.(item) }}
          >
            <span className="evidence-item__icon">{EVIDENCE_ICONS[item.type]}</span>
            <span className="evidence-item__label">{item.label}</span>
            <span className="evidence-item__id">Exhibit {item.id}</span>
          </li>
        ))}
      </ul>
    </aside>
  )
}
```

## Document Viewer (3D Floating Panel)

```jsx
import { Html, useTexture } from '@react-three/drei'

function DocumentViewer3D({ document, position, onClose }) {
  return (
    <Html
      position={position}
      transform
      distanceFactor={1}
      style={{ width: '400px', background: 'rgba(0,0,0,0.85)', borderRadius: 8, padding: 16 }}
    >
      <div className="doc-viewer">
        <div className="doc-viewer__header">
          <span>{document.label}</span>
          <button onClick={onClose}>✕</button>
        </div>
        <div className="doc-viewer__content">
          {document.type === 'document' && (
            <iframe src={document.url} title={document.label} style={{ width: '100%', height: 300 }} />
          )}
          {document.type === 'testimony' && (
            <blockquote className="testimony">{document.content}</blockquote>
          )}
        </div>
      </div>
    </Html>
  )
}
```

## CSS Design System

> **Source of truth:** `frontend/src/components/admin/themes.js` — DARK is the default theme.
> Always import from `useTheme()` (lawyer dashboard hook) rather than hard-coding colors.

```css
/* ─── Attorney.AI Design Tokens — from themes.js DARK ─────────────────────── */
:root {
  /* Backgrounds */
  --bg:           #1A2E35;   /* Page / scene backdrop */
  --surface:      #223A42;   /* Nav, sidebars */
  --card:         #2A4750;   /* Cards, panels */
  --card-hi:      #325A65;   /* Hovered card */

  /* Borders */
  --border:       #2C606E;
  --border-hi:    #3A7A8A;

  /* Brand — Cyan/Teal */
  --primary:      #40F0DC;   /* Main accent — buttons, links, active states */
  --primary-dim:  #2CD4C0;   /* Pressed / subdued accent */
  --primary-glow: rgba(64, 240, 220, 0.25);
  --primary-glow2:rgba(64, 240, 220, 0.12);  /* Subtle background tint */
  --secondary:    #ACDFD7;   /* Secondary accent */

  /* Text */
  --text:         #F2F2EC;   /* Primary text */
  --text-dim:     #D4D4CE;   /* Body text */
  --text-muted:   #9A9A94;   /* Labels, captions */
  --text-faint:   #6A6A64;   /* Disabled, timestamps */

  /* Semantic */
  --success:      #4DD4A3;   /* Sustained / accepted */
  --danger:       #FF6B7A;   /* Objection / rejected */
  --warn:         #FFC857;   /* Pending / attention */
  --info:         #5AB3FF;   /* Informational */

  /* Stat Accent Colors (Dashboard cards) */
  --stat-cases:   #3EECD6;   /* Active cases */
  --stat-docs:    #FFBE45;   /* Pending documents */
  --stat-clients: #42D4A0;   /* Total clients */
  --stat-hearings:#4AAFFF;   /* Today's hearings */

  /* Shadows */
  --shadow-card:  0 2px 12px rgba(0,0,0,0.35), 0 0 0 1px rgba(64,240,220,0.08);
  --shadow-hover: 0 8px 32px rgba(64,240,220,0.2);

  /* Gradient */
  --grad1:        linear-gradient(135deg, #40F0DC 0%, #ACDFD7 100%);

  /* Inputs */
  --input-bg:     rgba(44, 96, 110, 0.2);
  --input-focus:  rgba(64, 240, 220, 0.15);

  /* Border radius (from t.r) */
  --r-sm: 6px;
  --r-md: 10px;
  --r-lg: 14px;
  --r-xl: 18px;

  /* Typography */
  --font-serif:   'Cormorant Garamond', Georgia, serif;  /* .serif headings */
  --font-ui:      'Inter', 'Segoe UI', system-ui, sans-serif;
  --font-mono:    'JetBrains Mono', 'Fira Code', monospace; /* .mono case IDs */
}

/* ─── Case Header ───────────────────────────────────────────────────────────── */
.case-header {
  background: var(--surface);
  color: var(--text);
  font-family: var(--font-ui);
  border-bottom: 1px solid var(--border);
  padding: 12px 24px;
  display: flex;
  gap: 24px;
  align-items: center;
}

.case-header__id {
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--primary);
  font-weight: 600;
}

.case-header__type {
  font-size: 11px;
  color: var(--text-faint);
  text-transform: uppercase;
  letter-spacing: 0.07em;
  font-weight: 700;
}

.case-header__phase {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: var(--text-dim);
}

/* ─── Phase Dot (matches stat accent colors) ────────────────────────────────── */
.phase-dot { width: 8px; height: 8px; border-radius: 50%; }
.phase-dot[data-phase="intake"]            { background: var(--text-faint); }
.phase-dot[data-phase="opening"]           { background: var(--info); }
.phase-dot[data-phase="evidence"]          { background: var(--warn); }
.phase-dot[data-phase="cross_examination"] { background: var(--stat-docs); }
.phase-dot[data-phase="closing"]           { background: var(--primary); }
.phase-dot[data-phase="verdict"]           { background: var(--success); }

/* ─── Cards (matches t.card + t.shadowCard) ─────────────────────────────────── */
.court-card {
  background: var(--card);
  border-radius: var(--r-lg);
  box-shadow: var(--shadow-card);
  border: 1px solid var(--border);
  transition: box-shadow 0.2s, background 0.2s;
}
.court-card:hover {
  background: var(--card-hi);
  box-shadow: var(--shadow-hover);
}

/* ─── 3D Nameplate (floats above judge bench in scene) ──────────────────────── */
.nameplate {
  background: rgba(26, 46, 53, 0.92);   /* --bg at 92% opacity */
  border: 1px solid var(--primary);
  border-radius: var(--r-sm);
  padding: 4px 12px;
  text-align: center;
  font-family: var(--font-serif);
  color: var(--primary);
  font-size: 13px;
  white-space: nowrap;
  backdrop-filter: blur(8px);
  box-shadow: 0 0 12px var(--primary-glow);
}

.nameplate__title {
  display: block;
  font-size: 9px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--text-muted);
  margin-bottom: 2px;
}

.nameplate__name {
  display: block;
  font-size: 14px;
  font-weight: 600;
  color: var(--text);
}

/* ─── Evidence Panel ─────────────────────────────────────────────────────────── */
.evidence-panel {
  background: var(--card);
  border-left: 1px solid var(--border);
  padding: 16px;
}

.evidence-panel__title {
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 0.07em;
  color: var(--text-muted);
  font-weight: 700;
  margin-bottom: 12px;
}

.evidence-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 10px;
  border-radius: var(--r-md);
  cursor: pointer;
  transition: background 0.15s;
  border-left: 3px solid transparent;
}

.evidence-item:hover {
  background: var(--primary-glow2);
}

.evidence-item.active {
  border-left: 3px solid var(--primary);
  background: var(--primary-glow2);
}

.evidence-item__label {
  font-size: 13px;
  color: var(--text-dim);
  flex: 1;
}

.evidence-item__id {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--primary);
  font-weight: 600;
}

/* ─── Evidence Tag (3D Html overlay) ────────────────────────────────────────── */
.evidence-tag {
  background: rgba(26, 46, 53, 0.9);
  border: 1px solid var(--border-hi);
  border-radius: var(--r-sm);
  padding: 5px 10px;
  backdrop-filter: blur(8px);
  pointer-events: none;
}

.evidence-tag__id   { font-family: var(--font-mono); font-size: 10px; color: var(--primary); font-weight: 700; display: block; }
.evidence-tag__type { font-size: 9px;  color: var(--text-faint); text-transform: uppercase; letter-spacing: 0.08em; display: block; }
.evidence-tag__label{ font-size: 12px; color: var(--text-dim); display: block; margin-top: 2px; }

/* ─── Badge System (matches DashboardPage Badge component) ──────────────────── */
.badge {
  display: inline-flex;
  align-items: center;
  padding: 3px 9px;
  border-radius: 99px;
  font-size: 11px;
  font-weight: 700;
  border: 1px solid;
}

.badge--primary { background: rgba(64,240,220,0.15);  color: #40F0DC; border-color: rgba(64,240,220,0.3); }
.badge--success { background: rgba(77,212,163,0.15);  color: #4DD4A3; border-color: rgba(77,212,163,0.3); }
.badge--danger  { background: rgba(255,107,122,0.15); color: #FF6B7A; border-color: rgba(255,107,122,0.3); }
.badge--warn    { background: rgba(255,200,87,0.18);  color: #FFC857; border-color: rgba(255,200,87,0.3); }
.badge--info    { background: rgba(90,179,255,0.15);  color: #5AB3FF; border-color: rgba(90,179,255,0.3); }
.badge--gray    { background: rgba(154,154,148,0.18); color: #ACACAA; border-color: rgba(154,154,148,0.3); }

/* ─── Phase Timeline ─────────────────────────────────────────────────────────── */
.phase-timeline {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 16px;
  background: var(--surface);
  border-top: 1px solid var(--border);
}

.phase-step {
  flex: 1;
  text-align: center;
  font-size: 11px;
  color: var(--text-faint);
  padding: 6px 4px;
  border-radius: var(--r-sm);
  cursor: pointer;
  transition: all 0.15s;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  font-weight: 700;
}

.phase-step.done   { color: var(--text-muted); }
.phase-step.active {
  color: var(--primary);
  background: var(--primary-glow2);
  border: 1px solid var(--border-hi);
}

.phase-timeline button {
  background: var(--card);
  border: 1px solid var(--border);
  color: var(--text-muted);
  padding: 6px 14px;
  border-radius: var(--r-sm);
  font-size: 12px;
  cursor: pointer;
  transition: all 0.15s;
}

.phase-timeline button:hover:not(:disabled) {
  border-color: var(--primary);
  color: var(--primary);
}

.phase-timeline button:disabled { opacity: 0.3; cursor: not-allowed; }

/* ─── Party Cards ────────────────────────────────────────────────────────────── */
.party-cards { display: flex; gap: 8px; padding: 12px 16px; background: var(--surface); }

.party-card {
  flex: 1;
  padding: 10px 12px;
  background: var(--primary-glow2);
  border: 1px solid var(--border);
  border-radius: var(--r-md);
  text-align: center;
}

.party-card__role { font-size: 10px; color: var(--text-faint); text-transform: uppercase; letter-spacing: 0.07em; font-weight: 700; }
.party-card__name { font-size: 13px; color: var(--text-dim); margin-top: 4px; font-weight: 500; }

/* ─── Document Viewer (3D floating panel) ────────────────────────────────────── */
.doc-viewer {
  background: var(--card);
  border: 1px solid var(--border-hi);
  border-radius: var(--r-lg);
  box-shadow: var(--shadow-hover);
  overflow: hidden;
}

.doc-viewer__header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 14px;
  border-bottom: 1px solid var(--border);
  font-size: 13px;
  color: var(--text);
  font-weight: 600;
}

.doc-viewer__header button {
  background: none;
  border: none;
  color: var(--text-faint);
  cursor: pointer;
  font-size: 16px;
  transition: color 0.15s;
}
.doc-viewer__header button:hover { color: var(--danger); }

/* ─── Stat Bar (matches DashboardPage progress bar pattern) ─────────────────── */
.stat-bar { height: 2px; border-radius: 2px; background: var(--border); }
.stat-bar__fill { height: 100%; border-radius: 2px; transition: width 0.6s ease; }
```

### Theme JS Reference (import in React components)

```js
// Always use the shared theme — never hard-code hex values in components
import { DARK, LIGHT } from '@/components/admin/themes'

// In R3F / courtroom components (outside React tree):
const T = DARK  // use directly when useTheme() hook isn't available

// In React components:
import { useTheme } from '@/components/lawyer/theme'
const { t } = useTheme()   // t.primary, t.card, t.border, etc.
```

### 3D Scene Color Usage

```jsx
// Nameplate glow — primary color as point light tint
<pointLight color={0x40F0DC} intensity={0.6} distance={2} />

// Evidence highlight — primary glow on hover
const HOVER_COLOR = new THREE.Color('#40F0DC')

// Phase accent lights — match stat colors
const PHASE_LIGHT_COLORS = {
  opening:           '#5AB3FF',   // info
  evidence:          '#FFC857',   // warn
  cross_examination: '#FFBE45',   // stat-docs
  closing:           '#40F0DC',   // primary
  verdict:           '#4DD4A3',   // success
}
```

## Party Cards

```jsx
function PartyCards({ parties }) {
  const { judge, plaintiff_attorney, defense_attorney } = parties
  return (
    <div className="party-cards">
      <PartyCard role="Judge" name={judge?.name} />
      <PartyCard role="Plaintiff" name={plaintiff_attorney?.name} />
      <PartyCard role="Defense" name={defense_attorney?.name} />
    </div>
  )
}

function PartyCard({ role, name }) {
  return (
    <div className="party-card">
      <div className="party-card__role">{role}</div>
      <div className="party-card__name">{name || '—'}</div>
    </div>
  )
}
```

## Anti-Patterns

- **Do not** render all UI components inside the Canvas — only `Html` elements belong in Canvas
- **Do not** use `position: fixed` for HUD elements — breaks when iframe embeds Canvas
- **Do not** use pixel fonts or Comic Sans — legal UI demands serif or clean sans-serif
- **Do not** show all evidence at once — paginate if > 8 items
- **Do not** use bright colors for UI elements — competes with 3D scene; use dark theme
- **Do not** use `Html` with `distanceFactor` < 4 — too large, occlude scene objects
- **Do not** skip the `occlude` prop on Html elements — they render through walls
