# Attorney.AI — 3D Skills System Architecture

```
╔══════════════════════════════════════════════════════════════════════════════════╗
║              ATTORNEY.AI — AI-DRIVEN 3D LEGAL SIMULATION ENGINE                 ║
║         "A procedural, cinematic, AI-powered legal universe"                     ║
╚══════════════════════════════════════════════════════════════════════════════════╝

┌─────────────────────────────────────────────────────────────────────────────────┐
│                          SYSTEM LAYER OVERVIEW                                  │
└─────────────────────────────────────────────────────────────────────────────────┘

  LAYER 0 — AI ORCHESTRATION
  ┌───────────────────────────────────────────────────────────────────────────┐
  │  Claude Code Agent  →  Skill Router  →  Tool Dispatcher  →  MCP Servers  │
  │  (intent parse)         (SKILL.md)      (scripts/tools)     (Blender/CAD) │
  └───────────────────────────────────────────────────────────────────────────┘
                                    │
  LAYER 1 — LEGAL CORE              │
  ┌─────────────────────────────────▼─────────────────────────────────────────┐
  │  legal-core/          Case data → scene config → render request pipeline  │
  │  ai-legal-agent-workflows/       Judge / Lawyer / Jury agent coordination  │
  └───────────────────────────────────────────────────────────────────────────┘
                                    │
  LAYER 2 — ENVIRONMENT GENERATION  │
  ┌─────────────────────────────────▼─────────────────────────────────────────┐
  │  courtroom-architecture/         Procedural space layout & generation      │
  │  cad-parametric-modeling/        Parametric furniture, bench, podium CAD   │
  │  blender-procedural/             Mesh gen, UV mapping, asset export        │
  └───────────────────────────────────────────────────────────────────────────┘
                                    │
  LAYER 3 — REAL-TIME RENDERING     │
  ┌─────────────────────────────────▼─────────────────────────────────────────┐
  │  r3f-render-engine/              React Three Fiber scene graph & canvas    │
  │  shader-lighting-system/         Cinematic lighting, materials, shaders    │
  │  cinematic-environments/         Camera rigs, fog, DoF, mood staging       │
  │  physics-interaction/            Rapier physics, collisions, character nav │
  │  threepipe-interaction/          PickingPlugin: click/hover/select/inspect │
  └───────────────────────────────────────────────────────────────────────────┘
                                    │
  LAYER 4 — UI & VISUALIZATION      │
  ┌─────────────────────────────────▼─────────────────────────────────────────┐
  │  legal-ui-dashboard/             Legal data panels, HUD, document viewer  │
  └───────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────────┐
│                        SKILL SYSTEM FOLDER STRUCTURE                            │
└─────────────────────────────────────────────────────────────────────────────────┘

SKILLS/
├── ARCHITECTURE.md                   ← This file
├── REPO_MAPPING.md                   ← Repo-to-skill mapping table
├── PERFORMANCE_CHECKLIST.md          ← Global performance rules
├── MCP_INTEGRATIONS.md               ← Blender MCP, CAD, Firecrawl setup
├── HOW_CLAUDE_USES_THIS.md           ← Agent usage guide
│
├── _shared/
│   ├── patterns/
│   │   ├── component-patterns.md     ← Reusable R3F component patterns
│   │   ├── agent-patterns.md         ← AI agent orchestration patterns
│   │   └── geometry-patterns.md      ← Procedural geometry reuse patterns
│   ├── performance/
│   │   ├── fps-budget.md             ← Frame time budgets
│   │   └── gpu-memory.md             ← Texture/mesh memory limits
│   └── references/
│       ├── r3f-api.md
│       ├── blender-bpy.md
│       └── rapier-api.md
│
├── legal-core/
│   ├── SKILL.md
│   └── scripts/
│       ├── case_to_scene.py          ← Maps case data to scene config
│       └── legal_entity_schema.json  ← Standard entity definitions
│
├── courtroom-architecture/
│   ├── SKILL.md
│   └── scripts/
│       ├── layout_generator.py       ← Procedural room layout
│       └── courthouse_config.json    ← Parametric room presets
│
├── cinematic-environments/
│   ├── SKILL.md
│   └── scripts/
│       ├── camera_rig.jsx            ← R3F cinematic camera
│       └── mood_presets.json         ← Lighting/fog scene presets
│
├── r3f-render-engine/
│   ├── SKILL.md
│   └── scripts/
│       ├── Scene.jsx                 ← Root scene template
│       ├── useAssetLoader.js         ← Suspense-based asset hook
│       └── performance_monitor.jsx   ← FPS/draw call monitor
│
├── blender-procedural/
│   ├── SKILL.md
│   └── scripts/
│       ├── courtroom_gen.py          ← Blender procedural courtroom
│       ├── furniture_gen.py          ← Parametric furniture (bmesh)
│       └── export_glb.py             ← GLB export pipeline
│
├── cad-parametric-modeling/
│   ├── SKILL.md
│   └── scripts/
│       ├── courthouse_cad.py         ← build123d courthouse geometry
│       ├── bench_cad.py              ← Parametric judge bench
│       └── export_step_stl.py        ← Multi-format export
│
├── shader-lighting-system/
│   ├── SKILL.md
│   └── scripts/
│       ├── CourtShader.glsl          ← Custom courtroom shader
│       ├── LightRig.jsx              ← Three-point legal light rig
│       └── EnvMapLoader.jsx          ← HDRI environment loader
│
├── threepipe-interaction/
│   └── SKILL.md                      ← PickingPlugin, TransformControls, events
│
├── physics-interaction/
│   ├── SKILL.md
│   └── scripts/
│       ├── CharacterController.jsx   ← Rapier character with nav
│       ├── CourtColliders.jsx        ← Static room colliders
│       └── InteractionZones.jsx      ← Click/proximity triggers
│
├── legal-ui-dashboard/
│   ├── SKILL.md
│   └── scripts/
│       ├── HUD.jsx                   ← 3D HUD overlay component
│       ├── DocumentViewer.jsx        ← 3D floating doc panel
│       └── CaseSidebar.jsx           ← R3D HTML case data sidebar
│
└── ai-legal-agent-workflows/
    ├── SKILL.md
    └── scripts/
        ├── agent_router.py           ← Skill-level agent orchestration
        ├── judge_agent.py            ← LLM judge persona
        └── lawyer_agent.py           ← LLM lawyer persona
```

## Data Flow — Full Pipeline

```
  [Case Data / User Request]
         │
         ▼
  legal-core  ──────────────────────────────► legal-entity-schema
  (parse intent, extract entities)
         │
         ├──────────────────────► courtroom-architecture
         │                        (generate room layout config)
         │                                │
         │                                ├──► blender-procedural
         │                                │    (generate meshes → .glb)
         │                                │
         │                                └──► cad-parametric-modeling
         │                                     (generate furniture → .step/.stl)
         │
         ├──────────────────────► r3f-render-engine
         │                        (load .glb assets, build scene graph)
         │                                │
         │                                ├──► shader-lighting-system
         │                                │    (apply materials, lighting)
         │                                │
         │                                ├──► cinematic-environments
         │                                │    (camera, mood, DoF)
         │                                │
         │                                └──► physics-interaction
         │                                     (colliders, character nav)
         │
         ├──────────────────────► legal-ui-dashboard
         │                        (HUD, document panels, case sidebar)
         │
         └──────────────────────► ai-legal-agent-workflows
                                  (judge/lawyer agents, sim loop)
```
