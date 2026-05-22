# Reusable R3F Component Patterns — Attorney.AI

## Pattern 1: Zone-Anchored Component
Any 3D object that lives at a named courtroom zone.

```jsx
import { ZONE_POSITIONS } from '../constants/zones'

function ZoneObject({ zone, children, offset = [0, 0, 0] }) {
  const base = ZONE_POSITIONS[zone] || [0, 0, 0]
  return (
    <group position={[base[0]+offset[0], base[1]+offset[1], base[2]+offset[2]]}>
      {children}
    </group>
  )
}
```

## Pattern 2: Mood-Reactive Component
Subscribes to mood state and adjusts visual parameters.

```jsx
import { useCourtStore } from '../../store/courtStore'

function MoodReactive({ neutral, tense, dramatic, solemn }) {
  const mood = useCourtStore(s => s.mood)
  const map = { neutral, tense, dramatic, solemn }
  return <>{map[mood] || neutral}</>
}
```

## Pattern 3: Phase-Gated Visibility
Show/hide based on current trial phase.

```jsx
function PhaseVisible({ phases, children }) {
  const phase = useCourtStore(s => s.phase)
  if (!phases.includes(phase)) return null
  return <>{children}</>
}

// Usage:
<PhaseVisible phases={['evidence', 'cross_examination']}>
  <EvidenceDocumentProp />
</PhaseVisible>
```

## Pattern 4: Suspenseful Asset
Standard pattern for any GLB asset.

```jsx
import { useGLTF } from '@react-three/drei'
import { Suspense } from 'react'

function CourtAsset({ path, position, rotation, scale }) {
  const { scene } = useGLTF(path)
  return <primitive object={scene.clone()} position={position} rotation={rotation} scale={scale} />
}
CourtAsset.preload = (path) => useGLTF.preload(path)

// Always wrap with Suspense at usage site
<Suspense fallback={null}>
  <CourtAsset path="/assets/furniture/bench_neo.glb" position={[0, 0, -8]} />
</Suspense>
```

## Pattern 5: Instanced Court Furniture
For any furniture that appears multiple times (chairs, columns, lights).

```jsx
import { useRef, useEffect } from 'react'
import { useGLTF } from '@react-three/drei'
import * as THREE from 'three'

function InstancedFurniture({ glbPath, positions, rotations = [] }) {
  const { nodes, materials } = useGLTF(glbPath)
  const ref = useRef()
  const dummy = useMemo(() => new THREE.Object3D(), [])

  useEffect(() => {
    positions.forEach((pos, i) => {
      dummy.position.set(...pos)
      dummy.rotation.set(...(rotations[i] || [0, 0, 0]))
      dummy.updateMatrix()
      ref.current.setMatrixAt(i, dummy.matrix)
    })
    ref.current.instanceMatrix.needsUpdate = true
  }, [positions])

  const geom = nodes[Object.keys(nodes)[0]].geometry
  const mat = Object.values(materials)[0]

  return (
    <instancedMesh ref={ref} args={[geom, mat, positions.length]} castShadow receiveShadow />
  )
}
```

## Pattern 6: Event-Driven Animation
Animate a 3D object when a legal event fires.

```jsx
import { useSpring, animated } from '@react-spring/three'

function AnimatedGavel({ struck }) {
  const { rotation } = useSpring({
    rotation: struck ? [Math.PI / 3, 0, 0] : [0, 0, 0],
    config: { tension: 400, friction: 20 }
  })
  return (
    <animated.group rotation={rotation}>
      <GavelMesh />
    </animated.group>
  )
}
```
