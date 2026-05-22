# SKILL: cinematic-environments

## Purpose

Manages **camera systems, environmental atmosphere, and cinematic storytelling** inside the courtroom 3D scene. This skill controls where the camera is, how it moves, what it focuses on, and what environmental elements (fog, sky, ambient particles, audio reverb zones) enhance the scene's emotional impact.

## Source Ecosystem
- `pmndrs/drei` — `CameraControls`, `PerspectiveCamera`, `OrthographicCamera`, `PositionalAudio`
- Three.js `FogExp2`, `Fog`
- `@react-three/postprocessing` — DoF, motion blur, lens effects
- GSAP or `@react-spring/three` for camera animation

## Triggers

Activate when:
- `camera_preset` changes in SceneConfig
- Case phase transitions (opening → evidence → verdict)
- User says "cinematic view", "cut to the judge", "establishing shot", "close up"
- A dramatic event occurs in the simulation (verdict announced, witness breaks down)
- Mood changes require atmospheric adjustment

## Camera Presets

### establishing
Wide shot showing the full courtroom — used at scene start.
```jsx
{ position: [0, 6, 18], fov: 55, target: [0, 1, -2] }
```

### closeup_judge
Hero shot of the judge — used during rulings and verdict.
```jsx
{ position: [0, 3, -4], fov: 35, target: [0, 2, -8] }
```

### counsel_pov
First-person-ish from the plaintiff's side.
```jsx
{ position: [-4, 1.7, -1], fov: 65, target: [0, 1.5, -6] }
```

### jury_pov
Jury perspective watching witness / counsel.
```jsx
{ position: [-7, 2, -4], fov: 60, target: [0, 1.5, -3] }
```

### overhead
God-view / aerial — used for layout overview.
```jsx
{ position: [0, 18, 0], fov: 70, target: [0, 0, 0] }
```

### witness_closeup
Tight on the witness stand.
```jsx
{ position: [4, 2, -3], fov: 38, target: [3, 2, -6] }
```

## Camera Controller Component

```jsx
import { CameraControls, PerspectiveCamera } from '@react-three/drei'
import { useRef, useEffect } from 'react'
import { useSpring, animated } from '@react-spring/three'

const CAMERA_PRESETS = {
  establishing:    { position: [0, 6, 18],   target: [0, 1, -2],  fov: 55 },
  closeup_judge:   { position: [0, 3, -4],   target: [0, 2, -8],  fov: 35 },
  counsel_pov:     { position: [-4, 1.7, -1], target: [0, 1.5, -6], fov: 65 },
  jury_pov:        { position: [-7, 2, -4],  target: [0, 1.5, -3], fov: 60 },
  overhead:        { position: [0, 18, 0],   target: [0, 0, 0],   fov: 70 },
  witness_closeup: { position: [4, 2, -3],   target: [3, 2, -6],  fov: 38 }
}

export function CourtCamera({ preset = 'establishing', enableOrbit = false }) {
  const controlsRef = useRef()
  const current = CAMERA_PRESETS[preset] || CAMERA_PRESETS.establishing

  useEffect(() => {
    if (!controlsRef.current) return
    controlsRef.current.setPosition(...current.position, true)  // true = animate
    controlsRef.current.setTarget(...current.target, true)
  }, [preset])

  return (
    <>
      <PerspectiveCamera makeDefault fov={current.fov} near={0.1} far={500} />
      <CameraControls
        ref={controlsRef}
        enabled={enableOrbit}
        minDistance={2}
        maxDistance={30}
        maxPolarAngle={Math.PI / 2.2}
      />
    </>
  )
}
```

## Cinematic Cut Sequencer

```jsx
import { useEffect, useRef } from 'react'
import { useCourtStore } from '../store/courtStore'

const PHASE_CAMERA_SEQUENCE = {
  intake:            ['establishing'],
  opening:           ['establishing', 'counsel_pov'],
  evidence:          ['closeup_judge', 'witness_closeup', 'jury_pov'],
  cross_examination: ['witness_closeup', 'counsel_pov'],
  closing:           ['counsel_pov', 'closeup_judge'],
  verdict:           ['closeup_judge', 'establishing']
}

export function CinematicSequencer({ phase }) {
  const setCamera = useCourtStore(s => s.setCamera)
  const timerRef = useRef()
  const shots = PHASE_CAMERA_SEQUENCE[phase] || ['establishing']
  let shotIdx = 0

  useEffect(() => {
    setCamera(shots[0])
    // Auto-advance shots during simulation
    timerRef.current = setInterval(() => {
      shotIdx = (shotIdx + 1) % shots.length
      setCamera(shots[shotIdx])
    }, 12000)  // 12s per shot
    return () => clearInterval(timerRef.current)
  }, [phase])

  return null
}
```

## Atmospheric Effects

### Fog
```jsx
// Tense/solemn moods — light fog increases weight
function CourtFog({ mood }) {
  const color = mood === 'dramatic' ? '#0a0805' : '#e8e4e0'
  const near  = mood === 'neutral'  ? 40 : 20
  const far   = mood === 'neutral'  ? 100 : 50

  return <fog attach="fog" args={[color, near, far]} />
}
```

### Dust Particles (Cinematic)
```jsx
import { Sparkles } from '@react-three/drei'

function CourtDust({ mood }) {
  if (mood === 'neutral') return null
  return (
    <Sparkles
      count={200}
      size={0.3}
      speed={0.1}
      opacity={0.15}
      color="#e8d4a0"
      position={[0, 3, 0]}
      scale={[18, 5, 12]}
    />
  )
}
```

### God Rays (Dramatic Lighting Shafts)
```jsx
// Through courthouse windows — shafts of light
// Implemented via volumetric mesh + alpha blending
function GodRay({ position, angle, color = '#ffe8b0', opacity = 0.06 }) {
  return (
    <mesh position={position} rotation={[0, 0, angle]}>
      <coneGeometry args={[0.5, 8, 8, 1, true]} />
      <meshBasicMaterial
        color={color}
        transparent
        opacity={opacity}
        side={THREE.DoubleSide}
        depthWrite={false}
      />
    </mesh>
  )
}
```

## Phase Transition System

```jsx
import { useTransition } from '@react-spring/three'

// Smooth camera + atmosphere transition between phases
function PhaseTransition({ phase, mood }) {
  const prevPhase = useRef(phase)
  const isTransitioning = prevPhase.current !== phase

  useEffect(() => {
    if (isTransitioning) {
      prevPhase.current = phase
    }
  }, [phase])

  return (
    <group>
      <CourtCamera preset={PHASE_CAMERA_SEQUENCE[phase]?.[0]} />
      <CourtFog mood={mood} />
      <CourtDust mood={mood} />
    </group>
  )
}
```

## Mood → Atmosphere Mapping

| Mood | Fog | Dust | God Rays | Camera motion |
|---|---|---|---|---|
| neutral | None | None | None | Slow pan |
| tense | Light grey | None | None | Static |
| dramatic | Warm dark | Yes | Yes | Slow push-in |
| solemn | Dark warm | Yes | Dim | Hold still |

## Performance Rules

| Rule | Value |
|---|---|
| Fog far distance | Scale with room size |
| Sparkle count | Max 300 |
| God ray meshes | Max 4 per scene |
| Camera animation duration | 1.5–2.5s |
| Post DoF | Only on dramatic/solemn |
| Auto-cut interval | Min 8s |

## Anti-Patterns

- **Do not** use `OrbitControls` in production — use `CameraControls` with constrained angles
- **Do not** cut cameras faster than 8s — disorienting for users
- **Do not** animate camera position with `useFrame` and lerp without damping — creates jitter
- **Do not** use fog colors that conflict with room materials
- **Do not** render god rays with depth write on — causes Z-fighting with floor
- **Do not** trigger camera preset change on every render — only on phase/event change
