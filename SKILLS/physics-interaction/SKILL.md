# SKILL: physics-interaction

## Purpose

Implements **Rapier physics** for the Attorney.AI courtroom — character navigation, collisions, interactive props, proximity triggers, and zone-based event detection. This skill makes the 3D scene feel inhabited and interactive rather than a static diorama.

## Source Repository
- `pmndrs/react-three-rapier` — R3F Rapier bindings
- `@dimforge/rapier3d-compat` — WASM physics engine

## Triggers

Activate when:
- Characters (judge, lawyers, witnesses) need to navigate the courtroom
- Interactive props must respond to clicks or proximity
- Zone-based triggers are needed (entering witness stand = event fires)
- `enable_physics: true` in SceneConfig
- User says "make it interactive", "character walks to", "trigger on approach"

## Setup

```jsx
import { Physics } from '@react-three/rapier'

function CourtScene({ config }) {
  return (
    <Physics
      gravity={[0, -9.81, 0]}
      debug={process.env.NODE_ENV === 'development'}
      paused={!config.enable_physics}
    >
      <CourtColliders roomConfig={roomConfig} />
      <CharacterController zone="bench" character="judge" />
      <CharacterController zone="plaintiff" character="lawyer_plaintiff" />
      <CharacterController zone="defense" character="lawyer_defense" />
      <InteractionZones />
    </Physics>
  )
}
```

## Static Room Colliders

```jsx
import { RigidBody, CuboidCollider } from '@react-three/rapier'

export function CourtColliders({ roomConfig }) {
  const { w, d, h } = roomConfig.dimensions
  const t = 0.3  // wall thickness

  return (
    <>
      {/* Floor */}
      <RigidBody type="fixed">
        <CuboidCollider args={[w/2, 0.1, d/2]} position={[0, -0.1, 0]} />
      </RigidBody>

      {/* Walls */}
      <RigidBody type="fixed">
        <CuboidCollider args={[w/2, h/2, t]} position={[0, h/2, -d/2]} />  {/* Back */}
        <CuboidCollider args={[w/2, h/2, t]} position={[0, h/2,  d/2]} />  {/* Front */}
        <CuboidCollider args={[t, h/2, d/2]} position={[-w/2, h/2, 0]} />  {/* Left */}
        <CuboidCollider args={[t, h/2, d/2]} position={[ w/2, h/2, 0]} />  {/* Right */}
      </RigidBody>

      {/* Judge bench collider */}
      <RigidBody type="fixed">
        <CuboidCollider args={[1.5, 0.6, 0.45]} position={[0, 0.6, -8]} />
      </RigidBody>

      {/* Counsel tables */}
      <RigidBody type="fixed">
        <CuboidCollider args={[1.1, 0.38, 0.45]} position={[-3, 0.38, -3]} />
        <CuboidCollider args={[1.1, 0.38, 0.45]} position={[3, 0.38, -3]} />
      </RigidBody>
    </>
  )
}
```

## Character Controller

```jsx
import { RigidBody, CapsuleCollider, useRapier } from '@react-three/rapier'
import { useRef, useEffect } from 'react'
import { useFrame } from '@react-three/fiber'
import * as THREE from 'three'

const ZONE_POSITIONS = {
  bench:     [0, 0, -8],
  plaintiff: [-3, 0, -3],
  defense:   [3, 0, -3],
  witness:   [3, 0, -6],
  podium:    [0, 0, -4]
}

export function CharacterController({ zone, character, onArrived }) {
  const bodyRef = useRef()
  const targetPos = new THREE.Vector3(...(ZONE_POSITIONS[zone] || [0, 0, 0]))
  const arrived = useRef(false)

  useFrame(() => {
    if (!bodyRef.current || arrived.current) return
    const pos = bodyRef.current.translation()
    const current = new THREE.Vector3(pos.x, pos.y, pos.z)
    const dist = current.distanceTo(targetPos)

    if (dist > 0.3) {
      // Move toward target
      const dir = targetPos.clone().sub(current).normalize()
      bodyRef.current.setLinvel({ x: dir.x * 2, y: 0, z: dir.z * 2 }, true)
    } else {
      bodyRef.current.setLinvel({ x: 0, y: 0, z: 0 }, true)
      arrived.current = true
      onArrived?.()
    }
  })

  return (
    <RigidBody
      ref={bodyRef}
      type="dynamic"
      colliders={false}
      lockRotations
      position={[0, 1, 10]}  // Spawn at entry
    >
      <CapsuleCollider args={[0.4, 0.5]} />
      <CharacterMesh character={character} />
    </RigidBody>
  )
}
```

## Interaction Zones (Proximity Triggers)

```jsx
import { Sensor, CuboidCollider } from '@react-three/rapier'

export function InteractionZones({ onEnterWitness, onEnterPodium }) {
  return (
    <>
      {/* Witness stand approach zone */}
      <RigidBody type="fixed" sensor>
        <CuboidCollider
          args={[1, 1.5, 1]}
          position={[3, 1, -6]}
          onIntersectionEnter={() => onEnterWitness?.()}
          onIntersectionExit={() => console.log('left witness zone')}
        />
      </RigidBody>

      {/* Podium zone */}
      <RigidBody type="fixed" sensor>
        <CuboidCollider
          args={[1, 1.5, 1]}
          position={[0, 1, -4]}
          onIntersectionEnter={() => onEnterPodium?.()}
        />
      </RigidBody>
    </>
  )
}
```

## Click-to-Interact Props

```jsx
import { useRef, useState } from 'react'
import { RigidBody } from '@react-three/rapier'
import { useCursor } from '@react-three/drei'

export function InteractiveProp({ model, position, onActivate, label }) {
  const [hovered, setHovered] = useState(false)
  useCursor(hovered)

  return (
    <RigidBody type="fixed" position={position}>
      <mesh
        onPointerEnter={() => setHovered(true)}
        onPointerLeave={() => setHovered(false)}
        onClick={onActivate}
      >
        <primitive object={model} />
        {hovered && (
          <Html center distanceFactor={8}>
            <div className="prop-label">{label}</div>
          </Html>
        )}
      </mesh>
    </RigidBody>
  )
}
```

## Physics Event → Legal Event Bridge

```jsx
// Maps physics zone events to legal simulation events
const ZONE_EVENTS = {
  witness: { event: 'WITNESS_TAKING_STAND', nextPhase: 'cross_examination' },
  podium:  { event: 'ATTORNEY_AT_PODIUM', nextPhase: null },
  bench:   { event: 'JUDGE_SEATED', nextPhase: null }
}

export function PhysicsLegalBridge({ onLegalEvent }) {
  return (
    <InteractionZones
      onEnterWitness={() => onLegalEvent(ZONE_EVENTS.witness)}
      onEnterPodium={() => onLegalEvent(ZONE_EVENTS.podium)}
    />
  )
}
```

## Performance Rules

| Rule | Value |
|---|---|
| Max dynamic rigid bodies | 20 |
| Capsule colliders per character | 1 |
| Sensor colliders | Unlimited (no solve cost) |
| Physics timestep | Fixed 1/60 |
| Disable physics in non-interactive views | `paused={true}` |
| Character move speed | 2.0 m/s (realistic walk) |
| Collider debug | Dev only — never production |

## Anti-Patterns

- **Do not** apply physics to every mesh — only dynamic objects need `RigidBody`
- **Do not** use `type="dynamic"` for static room geometry — always `type="fixed"`
- **Do not** call `rapier.world.step()` manually — R3F Rapier owns the loop
- **Do not** read rigid body position inside React render — use `useFrame` refs
- **Do not** create physics bodies outside `<Physics>` wrapper
- **Do not** use trimesh colliders for characters — capsule is always correct
- **Do not** leave `debug={true}` in production — wireframe overlay is jarring for users
