# Repository-to-Skill Mapping Table

| Repository | GitHub | Primary Skill | Secondary Skills | Key Patterns Used |
|---|---|---|---|---|
| threepipe | repalash/threepipe | threepipe-interaction | r3f-render-engine, legal-ui-dashboard | PickingPlugin, TransformControlsPlugin, DropzonePlugin, ObjectPickerEventMap, ThreeViewer |
| react-three-fiber | pmndrs/react-three-fiber | r3f-render-engine | cinematic-environments, physics-interaction | Canvas, useFrame, useThree, hooks-as-components |
| drei | pmndrs/drei | r3f-render-engine | shader-lighting-system, legal-ui-dashboard, cinematic-environments | Environment, Html, OrbitControls, Detailed, useGLTF, Sparkles, Text3D |
| react-three-rapier | pmndrs/react-three-rapier | physics-interaction | courtroom-architecture | RigidBody, CuboidCollider, CapsuleCollider, Sensor, useRapier |
| three.js | mrdoob/three.js | r3f-render-engine | shader-lighting-system | MeshStandardMaterial, MeshPhysicalMaterial, FogExp2, ShaderMaterial, InstancedMesh |
| Blender bpy/bmesh | (docs.blender.org) | blender-procedural | courtroom-architecture, cad-parametric-modeling | bmesh.ops, bpy.data, geometry nodes, export_scene.gltf |
| build123d | gumyr/build123d | cad-parametric-modeling | courtroom-architecture | BuildPart, BuildSketch, extrude, revolve, export_step, export_stl |
| GSAP / @react-spring/three | greensock/gsap, pmndrs/react-spring | cinematic-environments | legal-ui-dashboard | useSpring, animated, camera tweening |
| postprocessing / r3f-postprocessing | pmndrs/react-postprocessing | shader-lighting-system | cinematic-environments | EffectComposer, Bloom, Vignette, DepthOfField, SSAO |
| Zustand | pmndrs/zustand | ai-legal-agent-workflows | legal-ui-dashboard, r3f-render-engine | create(), subscribeWithSelector, scene state bridge |
| Anthropic SDK | anthropic/anthropic-sdk-python | ai-legal-agent-workflows | legal-core | client.messages.create(), system prompts, multi-agent turns |

## Threepipe Plugin Shortlist for Attorney.AI

| Plugin | From | Attorney.AI Use |
|---|---|---|
| `PickingPlugin` | `threepipe` core | Click-to-select evidence props & characters |
| `TransformControlsPlugin` | `threepipe` core | Move furniture in scene editor mode |
| `DropzonePlugin` | `threepipe` core | Drag-drop material onto objects |
| `CanvasSnapshotPlugin` | `threepipe` core | Screenshot courtroom for legal record |
| `SSAOPlugin` | `threepipe` core | Ambient occlusion on marble floors |
| `ProgressivePlugin` | `threepipe` core | Refine render quality when scene is idle |
| `HDRiGroundPlugin` | `threepipe` core | Environment + contact shadows |
| `SSR + HDR Bloom` | `@threepipe/webgi-plugins` | Cinematic quality reflections & bloom |
| `@threepipe/plugin-r3f` | threepipe ecosystem | Bridge threepipe plugins into R3F Canvas |

## Skill Dependency Graph

```
legal-core
    └── SceneConfig ──► courtroom-architecture
                               │
                    ┌──────────┼───────────────────┐
                    ▼          ▼                   ▼
           blender-procedural  cad-parametric    ai-legal-agent-workflows
                    │          modeling
                    └──────────┤
                               ▼
                    r3f-render-engine
                               │
              ┌────────────────┼──────────────────┐
              ▼                ▼                  ▼
    shader-lighting-system  cinematic-env   physics-interaction
                                                   │
                                    ┌──────────────┘
                                    ▼
                          legal-ui-dashboard
```

## When to Use Each Repo Pattern

| Task | Use This | Not This |
|---|---|---|
| Load 3D model | `useGLTF` (drei) | `new GLTFLoader()` |
| Camera transition | `CameraControls` (drei) | `OrbitControls` + manual lerp |
| Repeating geometry | `InstancedMesh` (three.js) | Individual mesh per instance |
| Physics body | `RigidBody` (rapier) | Manual position clamping |
| Scene state | `zustand` | React Context |
| 3D text/labels | `Html` (drei) | CSS absolute positioned divs |
| Build geometry | `bmesh` | Blender edit mode ops in loops |
| Parametric arch. | `build123d` | Blender for precision shapes |
| Agent dialogue | `anthropic.messages.create` | Template strings |
| Post FX | `EffectComposer` | Manual render target hacks |
