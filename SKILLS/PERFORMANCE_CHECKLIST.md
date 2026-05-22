# Global Performance Checklist — Attorney.AI 3D System

## Target Hardware Profile
- Primary: Mid-range laptop (Intel i5/Ryzen 5, GTX 1060 / RX 580, 8GB VRAM)
- Minimum: 30 FPS at 1080p, full courtroom scene
- Target: 60 FPS at 1080p, full courtroom scene

---

## R3F Scene Performance

### GPU Budget
- [ ] Draw calls < 80 (use InstancedMesh for chairs, gallery, columns)
- [ ] Triangle count < 500k (target), < 1M (hard limit)
- [ ] Texture memory < 256MB loaded
- [ ] Shadow casting lights ≤ 3
- [ ] Shadow map resolution ≤ 1024px per light (one at 2048px for key)
- [ ] `dpr` capped at `[1, 2]` — never `window.devicePixelRatio` unclamped

### CPU / JS Budget
- [ ] No `setState` inside `useFrame`
- [ ] No `new THREE.*()` inside render functions — use `useMemo`
- [ ] `useFrame` handlers < 1ms each (profile with Chrome DevTools)
- [ ] No raw `requestAnimationFrame` competing with R3F loop
- [ ] Zustand subscriptions scoped — no full-store re-renders

### Asset Loading
- [ ] All GLBs use Draco compression (level 6)
- [ ] All GLBs preloaded with `useGLTF.preload()` at module level
- [ ] Textures: PNG for transparency, JPEG for opaque surfaces
- [ ] Texture sizes: 1024² for props, 2048² for room surfaces
- [ ] Use KTX2/Basis compressed textures for production (via `@react-three/drei`'s `useTexture`)

### Level of Detail
- [ ] Furniture > 10m from camera uses LOD (Detailed component)
- [ ] Gallery chairs use InstancedMesh (never individual meshes per chair)
- [ ] Background columns: LOD low at > 15m
- [ ] Characters: LOD med at > 8m, LOD low at > 20m

### Post-Processing
- [ ] Max 3 post-processing passes active simultaneously
- [ ] SSAO disabled on mobile/low-end (PerformanceMonitor detects)
- [ ] Bloom threshold ≥ 0.85 (not full-scene bloom)
- [ ] Use AdaptiveDpr for automatic resolution scaling

---

## Blender Export Performance

- [ ] All meshes triangulated before export (no n-gons)
- [ ] Apply all modifiers before GLB export
- [ ] Draco mesh compression enabled in GLB export
- [ ] Lights and cameras excluded from GLB export
- [ ] Max 50k triangles per furniture asset
- [ ] Max 200k triangles for full room shell
- [ ] UVs present on all exported meshes

---

## Physics Performance

- [ ] Max 20 dynamic RigidBody objects in scene
- [ ] All static geometry uses `type="fixed"` (no simulation cost)
- [ ] Sensor colliders preferred over dynamic for zones (no solve cost)
- [ ] Physics disabled (`paused={true}`) in non-interactive camera views
- [ ] Character capsule radius matches visual mesh (no floating)
- [ ] Collider debug OFF in production builds

---

## AI Agent Performance

- [ ] Max 500 tokens per agent response
- [ ] Agent calls are sequential (turn-based), never parallel (avoids rate limits)
- [ ] Agent history pruned to last 10 turns (prevent prompt bloat)
- [ ] Verdict generation is gated — only after `closing` phase
- [ ] WebSocket paces agent output at 2s intervals (UX pacing)

---

## Network / Loading

- [ ] GLBs served from `/public/assets/` (static, CDN-cacheable)
- [ ] HDRI files: max 8MB each (use .hdr not .exr for web)
- [ ] Scene loads with `<Suspense>` fallback — never blank screen
- [ ] `<Preload all />` after all assets declared

---

## Monitoring in Production

```jsx
import { PerformanceMonitor } from '@react-three/drei'

<PerformanceMonitor
  onDecline={() => {
    setQuality('low')  // Disable SSAO, reduce draw distance
    console.warn('[Attorney.AI] Performance degraded — switching to low quality')
  }}
  onIncline={() => setQuality('high')}
  flipflops={3}
  bounds={refresh => [0.85, 1]}
>
```

## Quality Tiers

| Setting | High | Medium | Low |
|---|---|---|---|
| Shadows | Yes (2048px key) | Yes (1024px) | No |
| SSAO | Yes | No | No |
| Bloom | Yes | Yes | No |
| DoF | Yes | No | No |
| Instance count (gallery) | 80 | 40 | 20 |
| Fog | Yes | Yes | No |
| Dust particles | 200 | 50 | 0 |
| Character LOD distance | 20m | 10m | 5m |
