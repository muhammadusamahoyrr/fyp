# How Claude Code Uses the Attorney.AI Skills System

## The Mental Model

This skills system transforms Claude Code from a code editor into a **full AI director** for the Attorney.AI 3D legal simulation engine. Each SKILL.md is a set of binding rules, patterns, and contracts that Claude follows automatically — you don't have to re-explain constraints every time.

---

## Step-by-Step: From Request to 3D Simulation

### Example prompt:
> "Generate a federal murder trial courtroom with dramatic evening lighting and run a 3-agent simulation"

### What Claude does:

**Step 1 — Legal Core**
```
Reads: SKILLS/legal-core/SKILL.md
Action: Build SceneConfig from prompt
Output:
  { case_type: "criminal", jurisdiction: "federal_us",
    courthouse_style: "neoclassical", phase: "opening",
    mood: "neutral", lighting_preset: "day_neutral",
    enable_jury: true, enable_physics: true }
```

**Step 2 — Courtroom Architecture**
```
Reads: SKILLS/courtroom-architecture/SKILL.md
Input: SceneConfig.courthouse_style = "neoclassical"
Action: generate_room_config(scene_config)
Output: RoomConfig (20m × 14m, marble, mahogany, 12-seat jury box)
```

**Step 3 — Blender Procedural** *(if assets don't exist)*
```
Reads: SKILLS/blender-procedural/SKILL.md
Action: Write furniture_gen.py + courtroom_gen.py
        Export via Blender MCP or script
Output: public/assets/rooms/neoclassical.glb
        public/assets/furniture/bench_neo.glb, etc.
```

**Step 4 — R3F Render Engine**
```
Reads: SKILLS/r3f-render-engine/SKILL.md
Action: Write CourtScene.jsx, CourtRoom.jsx components
        useGLTF for all assets, InstancedMesh for gallery
        Single Canvas with dpr=[1,2], shadows, PerformanceMonitor
```

**Step 5 — Shader Lighting**
```
Reads: SKILLS/shader-lighting-system/SKILL.md
Input: lighting_preset = "evening_dramatic"
Action: Write CourtLighting.jsx with EveningDramaticLighting rig
        Three-point character rig for judge
        Bloom + Vignette + DoF post-processing
```

**Step 6 — Cinematic Environments**
```
Reads: SKILLS/cinematic-environments/SKILL.md
Action: CourtCamera with "establishing" preset
        CinematicSequencer wired to phase changes
        Fog + dust particles for dramatic mood
```

**Step 7 — Physics**
```
Reads: SKILLS/physics-interaction/SKILL.md
Action: CourtColliders for room walls + furniture
        CharacterController for judge → bench zone
        CharacterController for plaintiff → plaintiff zone
        InteractionZones on witness stand + podium
```

**Step 8 — Legal UI Dashboard**
```
Reads: SKILLS/legal-ui-dashboard/SKILL.md
Action: CourtHUD with CaseHeader, PhaseTimeline, EvidencePanel
        Html nameplates anchored to judge bench zone
        Dark legal design theme (navy/gold)
```

**Step 9 — AI Legal Agents**
```
Reads: SKILLS/ai-legal-agent-workflows/SKILL.md
Action: Initialize AgentRouter with SceneConfig
        System prompts for judge, plaintiff, defense
        run_phase('opening') → 3 agent turns
        WebSocket streams dialogue to frontend
        Characters animate to appropriate zones
```

---

## Skill Activation Rules

Claude activates skills based on these signals:

| Signal | Skill Activated |
|---|---|
| "generate a courtroom", "build the scene" | legal-core → courtroom-architecture |
| "dramatic lighting", "change the mood", "evening scene" | shader-lighting-system |
| "3D model", "generate the mesh", "build in Blender" | blender-procedural |
| "parametric", "exact dimensions", "CAD model" | cad-parametric-modeling |
| "cinematic", "camera cut", "establishing shot" | cinematic-environments |
| "walk to", "character moves", "interactive" | physics-interaction |
| "UI panel", "case sidebar", "evidence viewer" | legal-ui-dashboard |
| "simulate", "let the judge speak", "run the trial" | ai-legal-agent-workflows |
| Imports `@react-three/fiber` | r3f-render-engine |
| Imports `build123d` | cad-parametric-modeling |
| Imports `bpy` | blender-procedural |

---

## Development Loop: Research → Design → Generate → Optimize → Render → Iterate

```
┌─────────────────────────────────────────────────────────────────┐
│ RESEARCH     Read SKILL.md + REPO_MAPPING.md                    │
│              Verify what assets exist in public/assets/         │
├─────────────────────────────────────────────────────────────────┤
│ DESIGN       Run legal-core: build SceneConfig                  │
│              Run courtroom-architecture: build RoomConfig        │
├─────────────────────────────────────────────────────────────────┤
│ GENERATE     Write blender-procedural scripts → GLB assets      │
│              Write cad-parametric scripts → STEP/STL            │
│              Convert CAD → Blender → GLB pipeline               │
├─────────────────────────────────────────────────────────────────┤
│ OPTIMIZE     Check PERFORMANCE_CHECKLIST.md                     │
│              Verify draw calls < 80, triangles < 500k           │
│              Apply InstancedMesh, LOD, Draco compression        │
├─────────────────────────────────────────────────────────────────┤
│ RENDER       Write R3F components (Scene.jsx, CourtScene.jsx)   │
│              Add lighting rig from shader-lighting-system        │
│              Add camera from cinematic-environments              │
│              Add physics from physics-interaction                │
├─────────────────────────────────────────────────────────────────┤
│ ITERATE      Run dev server → validate at 60fps                 │
│              Test phase transitions (opening → verdict)          │
│              Run AI agent simulation → verify dialogue quality   │
│              Check PerformanceMonitor — no decline events        │
└─────────────────────────────────────────────────────────────────┘
```

---

## Cross-Skill Communication Contracts

| From Skill | To Skill | Data Passed |
|---|---|---|
| legal-core | All | SceneConfig JSON |
| courtroom-architecture | blender-procedural | RoomConfig (dimensions, materials, furniture list) |
| courtroom-architecture | cad-parametric | Spec (jurisdiction, exact dims) |
| courtroom-architecture | physics-interaction | Zone positions, ceiling height |
| courtroom-architecture | shader-lighting-system | ceiling_height |
| blender-procedural | r3f-render-engine | GLB file paths |
| cad-parametric | blender-procedural | .STEP/.STL file paths |
| shader-lighting-system | cinematic-environments | Active mood/lighting preset |
| legal-core | ai-legal-agent-workflows | SceneConfig (parties, case_type, phase) |
| ai-legal-agent-workflows | legal-ui-dashboard | Agent turns (speaker, content, action) |
| physics-interaction | ai-legal-agent-workflows | Zone entry events |

---

## What Claude Must Never Do

- Bypass `legal-core` to go directly to 3D rendering (no SceneConfig = broken scene)
- Generate 3D components without reading `r3f-render-engine/SKILL.md` anti-patterns
- Use `setState` inside `useFrame` (this is the most common R3F performance bug)
- Create raw `THREE.*` objects inside component render without `useMemo`
- Skip Draco compression on GLB exports (file sizes blow up)
- Give agents access to real PII or attorney-client privileged information
- Hardcode courtroom dimensions without referencing `courtroom-architecture` presets
- Render post-processing stacks with > 3 passes without checking FPS budget
- Run all AI agents in parallel (legal procedure is strictly sequential)

---

## Quick Reference: File Locations

| Need | Read |
|---|---|
| Courtroom style presets | `courtroom-architecture/SKILL.md` → `STYLE_PRESETS` |
| Camera positions | `cinematic-environments/SKILL.md` → `CAMERA_PRESETS` |
| Material definitions | `shader-lighting-system/SKILL.md` → `COURT_MATERIALS` |
| Evidence type icons | `legal-ui-dashboard/SKILL.md` → `EVIDENCE_ICONS` |
| Phase-to-mood mapping | `legal-core/SKILL.md` → `MOOD_MAP` |
| Physics zone positions | `physics-interaction/SKILL.md` → `ZONE_POSITIONS` |
| Blender export command | `blender-procedural/SKILL.md` → `export_collection_glb` |
| Agent system prompts | `ai-legal-agent-workflows/SKILL.md` → `*_SYSTEM_PROMPT` |
| GPU budget limits | `PERFORMANCE_CHECKLIST.md` → GPU Budget section |
| MCP server setup | `MCP_INTEGRATIONS.md` → Setup sections |
