# SKILL: threepipe-interaction

## Source
- Site: https://threepipe.org
- GitHub: https://github.com/repalash/threepipe
- Docs: https://threepipe.org/docs/
- Example: https://threepipe.org/examples/#picking-plugin
- Install: `npm install threepipe`
- R3F bridge: `@threepipe/plugin-r3f`
- License: Apache 2.0

## What Threepipe Is

Threepipe is a **next-generation TypeScript 3D toolkit** built on top of Three.js. It wraps Three.js with a modular **plugin architecture** (400+ classes, 200+ interfaces) that handles picking, rendering, materials, post-FX, asset import/export, and scene interaction — without replacing Three.js or React Three Fiber.

Key differentiator from bare R3F: Threepipe provides **production-grade interaction tools** (object picking, selection boxes, drag-and-drop material assignment, clipboard operations, undo/redo) that would take weeks to build from scratch in R3F alone.

For Attorney.AI this is the **interaction layer** — it handles what happens when a user clicks on evidence props, characters, or furniture inside the courtroom.

---

## Purpose (Attorney.AI Context)

Use threepipe's `PickingPlugin` and `TransformControlsPlugin` to add:
- **Click to select** evidence props, furniture, characters
- **Hover highlighting** on interactive courtroom objects
- **Multi-select** for batch evidence review
- **Object inspection panel** — clicking a prop opens its legal data card
- **Drag material replacement** — drop a new material skin onto a character
- **Scene editor mode** — allow layout customization by the operator

---

## Triggers

Activate this skill when:
- User clicks a 3D object in the courtroom and expects a reaction
- Evidence prop must be selectable and show a detail panel
- Judge, lawyer, or witness character must be clickable for agent dialogue
- Scene editor mode is needed (operator repositioning furniture)
- Hover highlight on interactive objects is needed
- "What did the user click?" needs to be answered inside a 3D scene

---

## ThreeViewer Setup (Attorney.AI)

```typescript
import { ThreeViewer, PickingPlugin, TransformControlsPlugin } from 'threepipe'

// Initialize viewer — attaches to an existing canvas
const viewer = new ThreeViewer({
  canvas: document.getElementById('court-canvas') as HTMLCanvasElement,
  msaa: true,
  renderScale: 'auto',   // Adaptive resolution (like AdaptiveDpr in R3F)
})

// Add interaction plugins
const picking = viewer.addPluginSync(new PickingPlugin())
const transform = viewer.addPluginSync(new TransformControlsPlugin())
```

### With React Three Fiber (via @threepipe/plugin-r3f)
```tsx
import { ThreepipeR3fPlugin } from '@threepipe/plugin-r3f'

// If staying in R3F, use the bridge plugin
// This lets PickingPlugin work inside an R3F Canvas
viewer.addPluginSync(new ThreepipeR3fPlugin())
```

---

## PickingPlugin — Full API

### Constructor
```typescript
new PickingPlugin(
  selection?: Class<SelectionWidget>,  // Default: BoxSelectionWidget
  pickUi?: boolean,                     // Default: true — show UI panel
  autoFocus?: boolean                   // Default: false — auto-zoom on select
)
```

### Static
```typescript
PickingPlugin.PluginType    // 'Picking'
PickingPlugin.OldPluginType // 'PickingPlugin'
```

### Key Properties

| Property | Type | Default | Purpose |
|---|---|---|---|
| `enabled` | `boolean` | `true` | Enable/disable all picking |
| `selectionMode` | `'object' \| 'material' \| 'geometry' \| 'texture'` | `'object'` | What entity gets selected |
| `autoFocus` | `boolean` | `false` | Camera zooms to selection |
| `autoFocusHover` | `boolean` | `false` | Camera follows hover |
| `multiSelectEnabled` | `boolean` | `true` | Ctrl+click multi-select |
| `widgetEnabled` | `boolean` | `true` | Show selection box widget |
| `autoApplyMaterialOnDrop` | `boolean` | `true` | Drag-drop material swap |
| `duplicateMode` | `'simple' \| 'compound'` | `'simple'` | Offset mode for duplication |
| `hoverEnabled` | `boolean` | — | Get/set hover detection |
| `dirty` | `boolean` | — | Mark scene needs re-render |
| `picker` | `ObjectPicker \| undefined` | — | Raw raycasting engine |
| `widget` | `SelectionWidget \| undefined` | — | Active selection widget |

### Selection Methods

```typescript
// Read selection
picking.getSelectedObject<T>(): T | undefined
picking.getSelectedObjects<T>(): T[]

// Modify selection
picking.setSelectedObject(object?, focusCamera?, trackUndo?): void
picking.toggleSelectedObject(object): void
picking.selectAll(): void
picking.clearSelection(): void
```

### Object Operations

```typescript
picking.duplicateSelected(mode?: 'simple' | 'compound'): void
picking.deleteSelected(): Promise<void>       // Shows confirmation dialog
picking.focusSelected(): void                 // Camera zooms to fit
picking.focusObject(selected?): Promise<void>
picking.resetTransform('position' | 'rotation' | 'scale'): void
picking.toggleVisibilitySelected(): void
picking.unhideAll(): void
```

### Clipboard

```typescript
picking.copySelected(): void
picking.cutSelected(): void
picking.pasteFromClipboard(): void
```

---

## Event Map — Complete

All events come from `PickingPluginEventMap` which extends `ObjectPickerEventMap`:

### `hitObject`
```typescript
// Fires on every raycast hit (mouse move + click)
viewer.addEventListener('hitObject', (e: { intersects: HitIntersects; time: number }) => {
  const hit = e.intersects[0]
  if (hit) {
    console.log('Hit:', hit.object.name, 'at', hit.point)
  }
})
```

### `selectedObjectChanged`
```typescript
// Fires when the active selection changes
viewer.addEventListener('selectedObjectChanged', (e) => {
  const selected = picking.getSelectedObject()
  if (selected) {
    // Dispatch to legal UI: open evidence card
    openEvidenceCard(selected.userData.evidenceId)
  }
})
```

### `hoverObjectChanged`
```typescript
// Fires when mouse moves over a different object
viewer.addEventListener('hoverObjectChanged', (e) => {
  const hovered = e.detail?.value
  setCursorToPointer(!!hovered)
  if (hovered) highlightObject(hovered)
  else clearHighlight()
})
```

### `selectionModeChanged`
```typescript
// Fires when selectionMode property changes
viewer.addEventListener('selectionModeChanged', (e) => {
  console.log('Mode:', e.detail.value)  // 'object' | 'material' | etc.
})
```

### `multiSelectChanged`
```typescript
viewer.addEventListener('multiSelectChanged', (e) => {
  console.log('Multi-select:', e.detail.value)  // boolean
})
```

### `pickingModeChanged`
```typescript
viewer.addEventListener('pickingModeChanged', (e) => {
  console.log('Picking mode:', e.detail.value)
})
```

---

## Attorney.AI Integration Patterns

### Pattern 1: Evidence Prop Click → Legal Card

```typescript
// Tag evidence props in userData when building the scene
function tagEvidenceProp(mesh: THREE.Mesh, evidenceItem: EvidenceItem) {
  mesh.userData.type = 'evidence'
  mesh.userData.evidenceId = evidenceItem.id
  mesh.userData.evidenceLabel = evidenceItem.label
  mesh.userData.evidenceType = evidenceItem.type  // document | physical | digital
}

// Listen for selection
picking.addEventListener('selectedObjectChanged', () => {
  const obj = picking.getSelectedObject<THREE.Object3D>()
  if (!obj) return

  if (obj.userData.type === 'evidence') {
    // Show legal UI card
    dispatch({ type: 'OPEN_EVIDENCE_CARD', payload: obj.userData })
  } else if (obj.userData.type === 'character') {
    // Trigger agent dialogue
    dispatch({ type: 'ACTIVATE_AGENT', payload: { role: obj.userData.role } })
  }
})
```

### Pattern 2: Hover Highlight for Interactive Objects

```typescript
import { MeshBasicMaterial } from 'three'

const highlightMat = new MeshBasicMaterial({
  color: 0x40F0DC,  // --primary from themes.js DARK
  transparent: true,
  opacity: 0.22,
  depthTest: false
})

picking.addEventListener('hoverObjectChanged', (e) => {
  const prev = e.detail?.oldValue as THREE.Object3D | undefined
  const next = e.detail?.value  as THREE.Object3D | undefined

  // Remove highlight from previous
  if (prev?.userData.originalMaterial) {
    prev.traverse(child => {
      if ((child as THREE.Mesh).isMesh) {
        (child as THREE.Mesh).material = child.userData.originalMaterial
      }
    })
  }

  // Apply highlight to new hover target
  if (next && next.userData.interactive) {
    next.traverse(child => {
      if ((child as THREE.Mesh).isMesh) {
        child.userData.originalMaterial = (child as THREE.Mesh).material
        ;(child as THREE.Mesh).material = highlightMat
      }
    })
  }
})
```

### Pattern 3: Multi-Select Evidence for Comparison

```typescript
// Enable multi-select (Ctrl+Click)
picking.multiSelectEnabled = true
picking.selectionMode = 'object'

// Get all selected evidence
function getSelectedEvidence(): EvidenceItem[] {
  return picking.getSelectedObjects<THREE.Object3D>()
    .filter(obj => obj.userData.type === 'evidence')
    .map(obj => ({
      id: obj.userData.evidenceId,
      label: obj.userData.evidenceLabel,
      type: obj.userData.evidenceType
    }))
}

// On selection change, update comparison panel
picking.addEventListener('selectedObjectChanged', () => {
  const items = getSelectedEvidence()
  if (items.length > 1) openComparisonPanel(items)
})
```

### Pattern 4: Scene Editor Mode (Operator)

```typescript
// Toggle between "simulation mode" (no editing) and "editor mode"
function enableEditorMode() {
  picking.enabled = true
  picking.widgetEnabled = true  // Show selection box
  transform.enabled = true      // Allow drag repositioning
  picking.autoFocus = true
}

function enableSimulationMode() {
  // During trial simulation: disable editor controls
  picking.widgetEnabled = false
  transform.enabled = false
  picking.autoFocus = false
  picking.enabled = true         // Still allow click-to-inspect evidence
  picking.selectionMode = 'object'
}
```

### Pattern 5: Programmatic Selection for Agent Events

```typescript
// When judge agent fires "RULING" event, select the judge mesh
function selectJudgeForRuling(judgeObject: THREE.Object3D) {
  picking.setSelectedObject(
    judgeObject,
    true,   // focusCamera → zoom to judge
    false   // trackUndo → don't add to undo stack
  )
}

// When witness takes the stand
function selectWitness(witnessObject: THREE.Object3D) {
  picking.setSelectedObject(witnessObject, true, false)
}
```

---

## Plugin Ecosystem Relevant to Attorney.AI

| Plugin | Package | Use Case |
|---|---|---|
| `PickingPlugin` | `threepipe` (core) | Object selection, hover, events |
| `TransformControlsPlugin` | `threepipe` (core) | Move/rotate furniture in editor mode |
| `DropzonePlugin` | `threepipe` (core) | Drag material/asset onto objects |
| `SSAOPlugin` | `threepipe` (core) | Ambient occlusion (courtroom depth) |
| `SSAAPlugin` | `threepipe` (core) | Anti-aliasing quality |
| `ProgressivePlugin` | `threepipe` (core) | Progressive rendering (quality refinement) |
| `CanvasSnapshotPlugin` | `threepipe` (core) | Screenshot for legal record export |
| `HDRiGroundPlugin` | `threepipe` (core) | HDRI environment + ground shadows |
| `SSR (WebGI)` | `@threepipe/webgi-plugins` | Screen space reflections (marble floors) |
| `HDR Bloom (WebGI)` | `@threepipe/webgi-plugins` | Cinematic bloom quality |
| `Path Tracing` | `@threepipe/plugin-path-tracing` | Photorealistic preview renders |
| `GLTF Transform` | `@threepipe/plugin-gltf-transform` | Optimize GLB assets at load time |
| `Gaussian Splatting` | `@threepipe/plugin-gaussian-splatting` | NeRF-style real courtroom scans |

---

## Threepipe vs. Bare R3F — When to Use Which

| Need | Use |
|---|---|
| Core scene graph, components | `r3f-render-engine` skill (React Three Fiber) |
| Object click/select/hover with full UX | **threepipe `PickingPlugin`** |
| Drag-drop material swapping | **threepipe `DropzonePlugin`** |
| Scene editor (move furniture) | **threepipe `TransformControlsPlugin`** |
| Undo/redo for operator edits | **threepipe** (built-in `JSUndoManager`) |
| Physics (character nav, collisions) | `physics-interaction` skill (Rapier) |
| Cinematic camera automation | `cinematic-environments` skill |
| UI panels (HUD, evidence cards) | `legal-ui-dashboard` skill |

> Threepipe's `PickingPlugin` **replaces** building raycasting + hover + selection UX from scratch in Three.js. Do not re-implement raycasting manually when this plugin exists.

---

## Performance Rules

| Rule | Value |
|---|---|
| `pickUi` | Set `false` in production if no Tweakpane editor needed |
| `autoFocusHover` | Always `false` — causes disorienting camera motion |
| `widgetEnabled` | `false` during simulation mode |
| Hover event frequency | Throttle handler to 60fps — already handled internally |
| Multi-select limit | Warn if > 20 objects selected (UI cost) |
| `hitObject` listener | Avoid heavy computation — fires on every mousemove |

---

## Anti-Patterns

- **Do not** implement custom raycasting (`THREE.Raycaster`) when `PickingPlugin` covers it — duplicates logic and misses edge cases
- **Do not** listen to `hitObject` for selection logic — use `selectedObjectChanged` instead (hitObject fires continuously)
- **Do not** enable `autoFocusHover` in the courtroom — camera will constantly jitter as user mouses over furniture
- **Do not** leave `widgetEnabled: true` during simulation mode — selection box overlaps the scene
- **Do not** forget to call `picking.dispose()` on scene teardown — memory leak from unremoved event listeners
- **Do not** mix threepipe `TransformControls` with the Drei `TransformControls` — they will conflict over the same canvas events
- **Do not** use `deleteSelected()` without confirmation — it shows a dialog, which blocks the simulation loop
