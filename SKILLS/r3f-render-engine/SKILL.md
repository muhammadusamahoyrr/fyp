# SKILL: r3f-render-engine

## Purpose

Manages the **React Three Fiber (R3F) scene graph** — the real-time WebGL rendering layer of Attorney.AI. This skill owns Canvas setup, asset loading, scene composition, performance monitoring, and the component architecture that all visual elements live inside.

## Source Repositories
- `pmndrs/react-three-fiber` — Core renderer
- `pmndrs/drei` — Component helpers (Environment, OrbitControls, Html, Sparkles, etc.)
- `mrdoob/three.js` — Underlying WebGL abstraction

## Triggers

Activate when:
- Writing or modifying any `.jsx`/`.tsx` file that imports from `@react-three/fiber`
- Creating or updating a 3D scene component
- Adding new 3D assets (GLB, HDR, textures)
- Optimizing render performance (FPS drops, draw call spikes)
- Adding lighting, cameras, or post-processing effects

## Architecture Rules

### 1. Canvas is Sacred
```jsx
// CORRECT — single Canvas, no nested Canvas
<Canvas
  shadows
  dpr={[1, 2]}
  gl={{ antialias: true, powerPreference: "high-performance" }}
  camera={{ fov: 45, near: 0.1, far: 500, position: [0, 3, 15] }}
>
  <Suspense fallback={<Loader />}>
    <CourtScene />
  </Suspense>
</Canvas>
```
- **One Canvas per page** — never nest Canvas elements
- **Always set dpr={[1, 2]}** — prevents 4K blowout on retina
- **Always set powerPreference="high-performance"**
- **shadows prop is required** for courtroom realism

### 2. Asset Loading — Always Suspense + useGLTF
```jsx
// CORRECT
import { useGLTF } from '@react-three/drei'

function JudgeBench() {
  const { nodes, materials } = useGLTF('/assets/judge_bench.glb')
  return <primitive object={nodes.Bench} />
}

// CORRECT — preload outside component
useGLTF.preload('/assets/judge_bench.glb')
useGLTF.preload('/assets/courtroom_walls.glb')
```
- **Never use `new THREE.GLTFLoader()`** inside components — always `useGLTF`
- **Always `.preload()`** at module level for assets known at compile time
- **Always wrap in `<Suspense>`** — never conditionally render without fallback

### 3. Instanced Meshes for Repetition
```jsx
// CORRECT — gallery seats (60–120 chairs use single draw call)
function GallerySeats({ count = 80, positions }) {
  const { nodes } = useGLTF('/assets/gallery_chair.glb')
  const ref = useRef()
  const mat = new THREE.Matrix4()

  useEffect(() => {
    positions.forEach((pos, i) => {
      mat.setPosition(...pos)
      ref.current.setMatrixAt(i, mat)
    })
    ref.current.instanceMatrix.needsUpdate = true
  }, [positions])

  return (
    <instancedMesh ref={ref} args={[nodes.Chair.geometry, nodes.Chair.material, count]}>
    </instancedMesh>
  )
}
```

### 4. useFrame — Performance Contracts
```jsx
// CORRECT — subscribe only when needed
useFrame((state, delta) => {
  // Only mutate refs, never setState inside useFrame
  meshRef.current.rotation.y += delta * 0.1
})

// WRONG — causes re-render every frame
useFrame(() => setState(something))
```
- **Never call `setState` inside `useFrame`** — instant performance kill
- **Unsubscribe useFrame** when component unmounts (R3F handles this automatically with component lifecycle)
- **Use `delta` for time-based animation**, not `Date.now()`

### 5. R3F + React State Bridge
```jsx
// CORRECT — Zustand for 3D state (not useState)
import { create } from 'zustand'

const useCourtStore = create((set) => ({
  phase: 'opening',
  activeWitness: null,
  setPhase: (phase) => set({ phase }),
  setWitness: (w) => set({ activeWitness: w })
}))
```
- **Use Zustand** (not React Context) for scene state shared between 3D and UI layers
- **Never pass Three.js objects through React props** — use refs or stores

### 6. Scene Component Structure

```
src/
├── components/
│   └── courtroom/
│       ├── CourtScene.jsx          ← Root scene (loaded in Canvas)
│       ├── rooms/
│       │   ├── NeoclassicalRoom.jsx
│       │   ├── ModernRoom.jsx
│       │   └── ColonialRoom.jsx
│       ├── furniture/
│       │   ├── JudgeBench.jsx
│       │   ├── CounselTable.jsx
│       │   ├── WitnessStand.jsx
│       │   └── JuryBox.jsx
│       ├── characters/
│       │   ├── JudgeCharacter.jsx
│       │   ├── LawyerCharacter.jsx
│       │   └── WitnessCharacter.jsx
│       ├── lighting/
│       │   └── CourtLighting.jsx  ← Delegated to shader-lighting-system
│       └── ui/
│           └── CourtHUD.jsx       ← Delegated to legal-ui-dashboard
```

### 7. Performance Budget

| Metric              | Target     | Hard Limit |
|---------------------|------------|------------|
| Draw calls          | < 80       | < 150      |
| Triangle count      | < 500k     | < 1M       |
| Texture memory      | < 256MB    | < 512MB    |
| Target FPS          | 60         | 30 (min)   |
| JS frame time       | < 4ms      | < 8ms      |
| Shadow map res.     | 1024px     | 2048px     |

### 8. Drei Components for Attorney.AI

```jsx
import {
  Environment,         // HDRI env lighting
  ContactShadows,      // Soft floor shadows
  OrbitControls,       // Debug camera
  Html,                // 3D-anchored UI panels
  Text3D,              // 3D typography for signage
  Bvh,                 // BVH acceleration for raycasting
  useProgress,         // Loading progress
  Preload,             // Preload all useGLTF assets
  AdaptiveDpr,         // Dynamic resolution scaling
  PerformanceMonitor,  // FPS-reactive degradation
  SoftShadows,         // PCF soft shadows
  Sky,                 // Atmospheric sky
  Lightformer          // Area lights for cinematic rigs
} from '@react-three/drei'
```

### 9. Level of Detail (LOD)

```jsx
import { Detailed } from '@react-three/drei'

function JudgeBenchLOD() {
  return (
    <Detailed distances={[0, 10, 30]}>
      <JudgeBenchHigh />   {/* < 10m — full detail */}
      <JudgeBenchMed />    {/* 10–30m — medium */}
      <JudgeBenchLow />    {/* > 30m — billboard/box */}
    </Detailed>
  )
}
```

### 10. PerformanceMonitor Integration

```jsx
<PerformanceMonitor
  onDecline={() => setQuality('low')}
  onIncline={() => setQuality('high')}
  bounds={(refreshrate) => [0.9, 1]}
  flipflops={3}
>
  <AdaptiveDpr pixelated />
  <CourtScene quality={quality} />
</PerformanceMonitor>
```

## Anti-Patterns

| Anti-Pattern | Why It's Wrong | Fix |
|---|---|---|
| `new THREE.Mesh()` inside render | Creates new object every frame | Use `useMemo` or declare outside |
| Nested `<Canvas>` | R3F only supports one root | Single Canvas at page root |
| `setState` in `useFrame` | Triggers full React re-render | Use refs or Zustand |
| Importing `three` directly in components | Breaks tree-shaking | Use R3F/drei abstractions |
| 4096px shadow maps | GPU memory blowout | Max 2048px, usually 1024px |
| Loading GLBs without `useGLTF` | No caching, no Suspense | Always `useGLTF` + `Suspense` |
| Raw `requestAnimationFrame` | Competes with R3F loop | Always `useFrame` |
| `useEffect` for 3D mutations | Runs after paint, causes flash | Use `useLayoutEffect` or refs |

## scripts/Scene.jsx

```jsx
import { Canvas } from '@react-three/fiber'
import { Suspense } from 'react'
import { AdaptiveDpr, PerformanceMonitor, Preload } from '@react-three/drei'
import CourtScene from './courtroom/CourtScene'
import Loader from './ui/Loader'

export default function AttorneyAICanvas({ sceneConfig }) {
  return (
    <Canvas
      shadows
      dpr={[1, 2]}
      gl={{ antialias: true, powerPreference: 'high-performance', alpha: false }}
      camera={{ fov: 45, near: 0.1, far: 500, position: [0, 3, 15] }}
    >
      <PerformanceMonitor>
        <AdaptiveDpr pixelated />
        <Suspense fallback={null}>
          <CourtScene config={sceneConfig} />
          <Preload all />
        </Suspense>
      </PerformanceMonitor>
    </Canvas>
  )
}
```

## scripts/useAssetLoader.js

```js
import { useGLTF, useTexture } from '@react-three/drei'
import { useMemo } from 'react'

const ASSET_MAP = {
  neoclassical: {
    room: '/assets/rooms/neoclassical.glb',
    bench: '/assets/furniture/bench_neo.glb',
    jurybox: '/assets/furniture/jurybox_neo.glb'
  },
  modern: {
    room: '/assets/rooms/modern.glb',
    bench: '/assets/furniture/bench_mod.glb',
    jurybox: '/assets/furniture/jurybox_mod.glb'
  }
}

export function useCourtAssets(style) {
  const paths = ASSET_MAP[style] || ASSET_MAP.modern
  const room = useGLTF(paths.room)
  const bench = useGLTF(paths.bench)
  return useMemo(() => ({ room, bench }), [room, bench])
}

// Preload all known assets
Object.values(ASSET_MAP).forEach(set => Object.values(set).forEach(useGLTF.preload))
```
