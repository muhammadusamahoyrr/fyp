# MCP Integrations — Attorney.AI 3D System

## Overview

Three MCP servers extend Claude Code's capabilities for the Attorney.AI 3D pipeline:

| Server | Purpose | When to Use |
|---|---|---|
| Blender MCP | Execute Python scripts inside a live Blender session | Generating/modifying 3D assets without leaving Claude Code |
| Firecrawl MCP | Scrape legal databases, case records, court documents | Populating the intake pipeline with real case data |
| CAD/FreeCAD MCP | Run build123d / FreeCAD operations | Parametric architecture generation |

---

## 1. Blender MCP

### Setup
```json
// .claude/settings.json
{
  "mcpServers": {
    "blender": {
      "command": "uvx",
      "args": ["blender-mcp"],
      "env": {
        "BLENDER_PATH": "C:/Program Files/Blender Foundation/Blender 4.2/blender.exe"
      }
    }
  }
}
```

### Available MCP Tools (via blender-mcp)
- `execute_python` — run bpy/bmesh code inside active Blender session
- `get_scene_info` — list all objects, collections, and materials
- `create_object` — add primitive with parameters
- `export_selected` — export selection to GLB

### Workflow: Generate Courtroom Asset via MCP
```
User: "Generate a neoclassical judge bench"
Claude:
  1. Reads courtroom-architecture/SKILL.md → gets bench params
  2. Reads blender-procedural/SKILL.md → gets bmesh patterns
  3. Calls MCP execute_python with furniture_gen.py code
  4. Calls MCP export_selected → bench_neo.glb
  5. Places file in public/assets/furniture/
  6. Updates r3f-render-engine asset map
```

### Example MCP Call Pattern
```python
# Claude Code executes this via Blender MCP tool
import bpy
import bmesh

def create_neoclassical_bench():
    bm = bmesh.new()
    # ... bmesh operations ...
    mesh = bpy.data.meshes.new("JudgeBench_Neo")
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new("JudgeBench_Neo", mesh)
    bpy.context.collection.objects.link(obj)
    obj.select_set(True)
    bpy.ops.export_scene.gltf(
        filepath="//assets/furniture/bench_neo.glb",
        use_selection=True,
        export_draco_mesh_compression_enable=True
    )

create_neoclassical_bench()
```

---

## 2. Firecrawl MCP

### Setup
```json
{
  "mcpServers": {
    "firecrawl": {
      "command": "npx",
      "args": ["-y", "firecrawl-mcp"],
      "env": {
        "FIRECRAWL_API_KEY": "${FIRECRAWL_API_KEY}"
      }
    }
  }
}
```

### Use Cases for Attorney.AI
- Scrape PACER (US federal court records) for real case structures
- Extract courtroom layout descriptions from legal architecture resources
- Pull case law from Justia, CourtListener for agent briefing documents
- Fetch courthouse floor plans from public architecture databases

### Workflow: Real Case → Simulation
```
User: "Simulate the OJ Simpson criminal trial"
Claude:
  1. Calls Firecrawl: scrape Wikipedia/CourtListener for case facts
  2. Extracts: parties, charges, evidence items, key witnesses
  3. Passes to legal-core → build_scene_config()
  4. SceneConfig generated with real parties and evidence
  5. Simulation begins with grounded historical data
```

### Firecrawl Anti-Patterns
- **Do not** scrape copyrighted legal documents for reproduction
- **Do not** scrape live case records for ongoing proceedings
- **Always** cite sources when using scraped case data in simulation

---

## 3. FreeCAD / build123d MCP

### Option A: Direct Python Script Execution
Since build123d is a Python library, no MCP server is strictly needed:
```bash
# Claude writes the script, user runs it
python courthouse_cad.py
# Outputs: judge_bench.step, judge_bench.stl
```

### Option B: FreeCAD MCP Server
```json
{
  "mcpServers": {
    "freecad": {
      "command": "python",
      "args": ["-m", "freecad_mcp"],
      "env": {
        "FREECAD_PATH": "C:/Program Files/FreeCAD 0.21/bin/FreeCAD.exe"
      }
    }
  }
}
```

### CAD → Blender → R3F Pipeline
```
build123d (Python)
    → export .STEP
        → Blender: File > Import > STEP (via FreeCAD importer)
            → Apply smooth shading + subdivision
            → UV unwrap (Smart UV Project)
            → Assign PBR materials
            → Export GLB (Draco compressed)
                → public/assets/furniture/
                    → R3F useGLTF → scene
```

---

## 4. Recommended Claude Code Settings

```json
// .claude/settings.json
{
  "mcpServers": {
    "blender": { "command": "uvx", "args": ["blender-mcp"] },
    "firecrawl": { "command": "npx", "args": ["-y", "firecrawl-mcp"], "env": { "FIRECRAWL_API_KEY": "" } }
  },
  "permissions": {
    "allow": [
      "Bash(python:*)",
      "Bash(blender --background*)",
      "Write(SKILLS/**)",
      "Write(public/assets/**)",
      "Write(backend/app/ai/**)"
    ]
  }
}
```

---

## 5. MCP-Driven Development Loop

```
┌─────────────────────────────────────────────────────┐
│  Claude Code (you are here)                         │
│                                                     │
│  1. Read SKILL.md → understand constraints          │
│  2. Firecrawl MCP → gather real case/design data    │
│  3. Write build123d script → CAD geometry           │
│  4. Blender MCP → convert CAD to renderable mesh    │
│  5. Write R3F component → integrate into scene      │
│  6. Write agent script → animate the simulation     │
│  7. Run frontend → validate at 60fps                │
└─────────────────────────────────────────────────────┘
```
