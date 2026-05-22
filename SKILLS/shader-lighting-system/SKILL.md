# SKILL: shader-lighting-system

## Purpose

Controls **all lighting, materials, shaders, and visual atmosphere** inside the Attorney.AI courtroom. This skill translates the `lighting_preset` and `mood` from `SceneConfig` into cinematic Three.js/R3F lighting rigs, custom GLSL shaders, HDR environments, and PBR material definitions.

## Source Ecosystem
- Three.js `MeshStandardMaterial`, `MeshPhysicalMaterial`
- R3F / Drei: `Environment`, `Lightformer`, `SpotLight`, `DirectionalLight`
- Custom GLSL via `shaderMaterial` (drei) or `RawShaderMaterial` (three.js)
- HDRI: Poly Haven courthouse/interior HDR maps

## Triggers

Activate when:
- `lighting_preset` is set in SceneConfig
- Courtroom mood changes (phase transition)
- User says "change the lighting", "make it more dramatic", "add cinematic lighting"
- New shader material is needed for a surface type
- Post-processing effects are added

## Lighting Presets

### day_neutral
```jsx
// Opening statements, intake — calm, authoritative
function DayNeutralLighting() {
  return (
    <>
      <ambientLight intensity={0.4} color="#fff5e6" />
      <directionalLight
        position={[5, 12, 3]}
        intensity={2.0}
        color="#fff8f0"
        castShadow
        shadow-mapSize={[1024, 1024]}
        shadow-camera-far={50}
        shadow-camera-near={0.1}
      />
      {/* Window fill lights */}
      <rectAreaLight position={[-8, 4, 0]} width={2} height={4} intensity={1.5} color="#d4e8ff" />
      <rectAreaLight position={[8, 4, 0]}  width={2} height={4} intensity={1.5} color="#d4e8ff" />
    </>
  )
}
```

### overcast_tense
```jsx
// Evidence phase — flattened, cold, uncomfortable
function OvercastTenseLighting() {
  return (
    <>
      <ambientLight intensity={0.6} color="#c8ccd0" />
      <directionalLight position={[0, 10, 0]} intensity={1.2} color="#b0b8c4" castShadow />
      {/* Harsh ceiling fill — no warmth */}
      <hemisphereLight skyColor="#9aa0aa" groundColor="#3a3f45" intensity={0.5} />
    </>
  )
}
```

### evening_dramatic
```jsx
// Closing arguments, verdict — high contrast, warm/cool split
function EveningDramaticLighting() {
  return (
    <>
      <ambientLight intensity={0.15} color="#1a0a00" />
      {/* Key light — warm, angled */}
      <spotLight
        position={[3, 8, 3]}
        angle={0.35}
        penumbra={0.5}
        intensity={4.0}
        color="#ff9040"
        castShadow
        shadow-mapSize={[2048, 2048]}
      />
      {/* Rim light — cool blue */}
      <spotLight position={[-5, 6, -4]} angle={0.5} penumbra={0.8} intensity={1.5} color="#4080ff" />
      {/* Judge halo — primary cyan tint matches dashboard brand */}
      <pointLight position={[0, 5, -8]} intensity={1.6} color="#40F0DC" distance={10} />
    </>
  )
}
```

## Three-Point Rig for Characters

```jsx
function CharacterLightRig({ position = [0, 0, 0], character = 'judge' }) {
  const [x, y, z] = position
  const intensity = character === 'judge' ? 1.8 : 1.2

  return (
    <group position={position}>
      {/* Key */}
      <spotLight position={[x+1.5, y+3, z+2]} angle={0.4} intensity={intensity} color="#ffe8d0" />
      {/* Fill */}
      <spotLight position={[x-2, y+2, z+1]} angle={0.6} intensity={intensity*0.4} color="#d0e8ff" />
      {/* Back/rim */}
      <spotLight position={[x, y+2, z-2]} angle={0.5} intensity={intensity*0.6} color="#ffffff" />
    </group>
  )
}
```

## PBR Material Library

```jsx
import { MeshStandardMaterial, MeshPhysicalMaterial } from 'three'
import { useMemo } from 'react'

export const COURT_MATERIALS = {
  marble_white: {
    color: '#f0ede8',
    roughness: 0.05,
    metalness: 0.0,
    envMapIntensity: 1.5
  },
  mahogany: {
    color: '#3d1c08',
    roughness: 0.4,
    metalness: 0.05,
    envMapIntensity: 0.8
  },
  plaster_cream: {
    color: '#f5f0e8',
    roughness: 0.9,
    metalness: 0.0,
    envMapIntensity: 0.2
  },
  dark_oak: {
    color: '#1a0d04',
    roughness: 0.5,
    metalness: 0.02,
    envMapIntensity: 0.6
  },
  concrete_raw: {
    color: '#808080',
    roughness: 0.95,
    metalness: 0.0,
    envMapIntensity: 0.1
  },
  glass_clear: {
    color: '#a0b8d0',
    roughness: 0.05,
    metalness: 0.1,
    transparent: true,
    opacity: 0.25,
    envMapIntensity: 2.0
  }
}

export function useCourtroomMaterial(name) {
  return useMemo(() => {
    const def = COURT_MATERIALS[name] || COURT_MATERIALS.plaster_cream
    return new MeshStandardMaterial(def)
  }, [name])
}
```

## Custom GLSL Shader — Wood Grain

```glsl
// CourtShader.glsl (fragment)
varying vec2 vUv;
varying vec3 vNormal;
uniform vec3 uBaseColor;
uniform float uGrainScale;
uniform float uTime;

float grain(vec2 uv, float scale) {
  return fract(sin(dot(uv * scale, vec2(12.9898, 78.233))) * 43758.5453);
}

void main() {
  // Anisotropic wood grain approximation
  float g = grain(vUv, uGrainScale);
  float ring = sin(vUv.y * uGrainScale * 3.14159 * 2.0) * 0.5 + 0.5;
  vec3 woodColor = mix(uBaseColor, uBaseColor * 1.3, ring * 0.3 + g * 0.1);
  vec3 lighting = vNormal * 0.5 + 0.5;
  gl_FragColor = vec4(woodColor * lighting, 1.0);
}
```

```jsx
// Usage with shaderMaterial
import { shaderMaterial } from '@react-three/drei'
import { extend } from '@react-three/fiber'
import * as THREE from 'three'

const WoodMaterial = shaderMaterial(
  { uBaseColor: new THREE.Color('#3d1c08'), uGrainScale: 80.0, uTime: 0 },
  vertGLSL,
  fragGLSL
)
extend({ WoodMaterial })
```

## Post-Processing Stack

```jsx
import { EffectComposer, Bloom, Vignette, SSAO, DepthOfField, ToneMapping } from '@react-three/postprocessing'
import { ToneMappingMode } from 'postprocessing'

function PostFX({ mood }) {
  const isDramatic = mood === 'dramatic' || mood === 'solemn'

  return (
    <EffectComposer>
      <ToneMapping mode={ToneMappingMode.ACES_FILMIC} />
      <Bloom luminanceThreshold={0.85} luminanceSmoothing={0.9} intensity={isDramatic ? 0.4 : 0.1} />
      <Vignette offset={0.35} darkness={isDramatic ? 0.7 : 0.3} />
      {isDramatic && (
        <DepthOfField focusDistance={0.01} focalLength={0.02} bokehScale={2} />
      )}
    </EffectComposer>
  )
}
```

## HDRI Environment Loading

```jsx
import { Environment } from '@react-three/drei'

// Maps lighting_preset → HDRI file
const HDRI_MAP = {
  day_neutral:      '/hdri/courthouse_day.hdr',
  overcast_tense:   '/hdri/overcast_interior.hdr',
  evening_dramatic: '/hdri/golden_hour_interior.hdr'
}

function CourtEnvironment({ preset }) {
  return (
    <Environment
      files={HDRI_MAP[preset] || HDRI_MAP.day_neutral}
      background={false}   // Don't show HDRI as background — use room geometry
      blur={0.5}
    />
  )
}
```

## Mood → Effect Mapping

| Mood | Ambient | Key Color | Post Effects | Shadows |
|---|---|---|---|---|
| neutral | 0.4 | #fff8f0 | None | Soft |
| tense | 0.6 | #b0b8c4 | Vignette low | Hard |
| dramatic | 0.15 | #ff9040 | Bloom + Vignette + DoF | High contrast |
| solemn | 0.1 | #ff6020 | Bloom dark + Vignette heavy | Hard + rim |

## Performance Rules

| Rule | Value |
|---|---|
| Max shadow-casting lights | 3 |
| Shadow map resolution | 1024px (2048px for key only) |
| SSAO | Disable on mobile/low GPU |
| Bloom passes | Max 1 |
| Reflection probes | 1 per room (baked preferred) |
| `envMapIntensity` on materials | Max 2.0 |

## Anti-Patterns

- **Do not** cast shadows from every light — only key light casts shadows
- **Do not** use `envMapIntensity > 2.0` — overly reflective, unrealistic
- **Do not** enable SSAO on low-end GPUs without performance check
- **Do not** use `<ambientLight intensity={1.0}>` — washes out all depth
- **Do not** animate HDRI environment per frame — bake or swap at mood change only
- **Do not** use raw `THREE.ShaderMaterial` without `glslify` or `shaderMaterial` — hard to debug
- **Do not** stack more than 3 post-processing passes without measuring FPS
