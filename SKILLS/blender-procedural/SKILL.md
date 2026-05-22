# SKILL: blender-procedural

## Purpose

Drives **Blender Python (bpy/bmesh) automation** for procedural courtroom asset generation. This skill creates, modifies, and exports 3D meshes — room geometry, furniture, architectural details — that are consumed by the r3f-render-engine as GLB files. Operates via Blender MCP or direct `.py` script execution.

## Source Ecosystem
- Blender `bpy` Python API
- `bmesh` module for mesh editing
- Geometry Nodes (GN) for procedural structures
- Blender MCP server (when available) for Claude Code → Blender bridge

## Triggers

Activate when:
- New courthouse style is requested and GLB assets don't exist
- Furniture dimensions change (parametric update needed)
- Evidence 3D props must be created (documents, scales, gavels)
- Architectural details need procedural generation (columns, cornices, railings)
- User says "generate the 3D model", "create the mesh", "build in Blender"

## Blender MCP Integration

When Blender MCP server is running (`blender-mcp` or `io.github.ahujasid.blender-mcp`):
```
Claude Code → MCP Tool: execute_python → Blender bpy context
```

Without MCP: write `.py` scripts and instruct user to run them via:
```
blender --background --python courtroom_gen.py
```

## Architecture Patterns

### 1. Always Use bmesh for Mesh Editing
```python
import bpy
import bmesh

def create_judge_bench(width=3.0, height=1.2, depth=0.9):
    bm = bmesh.new()
    # Build geometry in bmesh (fast, no scene overhead)
    verts = bmesh.ops.create_cube(bm, size=1)
    bmesh.ops.scale(bm, vec=(width, depth, height), verts=bm.verts)
    # Transfer to mesh object
    mesh = bpy.data.meshes.new("JudgeBench")
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new("JudgeBench", mesh)
    bpy.context.collection.objects.link(obj)
    return obj
```

### 2. Material Assignment Pattern
```python
def assign_material(obj, material_name, base_color, roughness=0.6, metallic=0.0):
    mat = bpy.data.materials.get(material_name)
    if mat is None:
        mat = bpy.data.materials.new(name=material_name)
        mat.use_nodes = True
        bsdf = mat.node_tree.nodes["Principled BSDF"]
        bsdf.inputs["Base Color"].default_value = (*base_color, 1.0)
        bsdf.inputs["Roughness"].default_value = roughness
        bsdf.inputs["Metallic"].default_value = metallic
    obj.data.materials.append(mat)
```

### 3. Parametric Furniture Generator
```python
FURNITURE_PARAMS = {
    "neoclassical": {
        "bench_w": 3.0, "bench_h": 1.2, "bench_d": 0.9,
        "bench_color": (0.25, 0.15, 0.08),  # mahogany
        "table_w": 2.2, "table_h": 0.76, "table_d": 0.9,
        "table_color": (0.20, 0.12, 0.07)
    },
    "modern": {
        "bench_w": 2.8, "bench_h": 0.9, "bench_d": 0.8,
        "bench_color": (0.15, 0.15, 0.18),  # dark laminate
        "table_w": 2.0, "table_h": 0.74, "table_d": 0.8,
        "table_color": (0.8, 0.8, 0.82)
    }
}

def generate_furniture_set(style: str):
    params = FURNITURE_PARAMS.get(style, FURNITURE_PARAMS["modern"])
    objs = []
    objs.append(create_judge_bench(params["bench_w"], params["bench_h"], params["bench_d"]))
    assign_material(objs[0], f"Bench_{style}", params["bench_color"], roughness=0.4)
    return objs
```

### 4. Room Shell Generation
```python
def generate_room_shell(w: float, d: float, h: float):
    """Creates floor, 4 walls, ceiling as separate mesh objects."""
    bm = bmesh.new()
    # Floor
    verts = [bm.verts.new(v) for v in [
        (-w/2, -d/2, 0), (w/2, -d/2, 0),
        (w/2,  d/2, 0), (-w/2,  d/2, 0)
    ]]
    bm.faces.new(verts)
    mesh = bpy.data.meshes.new("Floor")
    bm.to_mesh(mesh)
    bm.free()
    return bpy.data.objects.new("Floor", mesh)
```

### 5. Column Generation (Neoclassical)
```python
import math

def generate_column(radius=0.2, height=5.0, segments=16, pos=(0, 0, 0)):
    bm = bmesh.new()
    # Cylinder for column shaft
    bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False,
                          segments=segments, radius1=radius,
                          radius2=radius * 0.92, depth=height)
    mesh = bpy.data.meshes.new("Column")
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new("Column", mesh)
    obj.location = pos
    bpy.context.collection.objects.link(obj)
    return obj

def place_columns(count=6, room_w=20.0, room_d=14.0):
    spacing = room_w / (count - 1)
    for i in range(count):
        x = -room_w/2 + i * spacing
        generate_column(pos=(x, -room_d/2 + 0.3, 0))
        generate_column(pos=(x,  room_d/2 - 0.3, 0))
```

### 6. GLB Export Pipeline
```python
def export_collection_glb(collection_name: str, output_path: str):
    """Export a named collection to GLB for R3F consumption."""
    bpy.ops.object.select_all(action='DESELECT')
    coll = bpy.data.collections[collection_name]
    for obj in coll.all_objects:
        obj.select_set(True)
    bpy.ops.export_scene.gltf(
        filepath=output_path,
        export_format='GLB',
        use_selection=True,
        export_apply=True,           # Apply modifiers
        export_materials='EXPORT',
        export_lights=False,         # Lights handled in R3F
        export_cameras=False,
        export_draco_mesh_compression_enable=True,  # Smaller files
        export_draco_mesh_compression_level=6
    )
    print(f"Exported: {output_path}")
```

## Geometry Nodes Patterns

For complex procedural structures (railings, moldings, gallery seating arrays):

```
Modifier Stack:
  [Mesh Line] → [Resample Curve] → [Instance on Points] → [Realize Instances]
                                        ↑
                                   [Chair Geometry]
```

Use Geometry Nodes when:
- Repeating elements > 10 instances
- Parametric shape needs real-time Blender sliders
- Railing, balustrade, or array patterns

Use bmesh when:
- Custom topology is needed
- UV mapping must be precise
- Performance of GN would be overkill

## UV Mapping Rules

```python
def unwrap_smart(obj):
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.uv.smart_project(angle_limit=66, island_margin=0.02)
    bpy.ops.object.mode_set(mode='OBJECT')
```

- **Always UV unwrap** before export — R3F textures need UVs
- **Smart UV Project** for furniture (fast, acceptable quality)
- **Manual unwrap** for hero assets (judge bench, witness stand)
- **Lightmap UV** in UV channel 1 for baked lighting

## Performance Rules

| Rule | Value |
|---|---|
| Max poly count per furniture piece | 50,000 tris |
| Max poly count for full room shell | 200,000 tris |
| Texture resolution (furniture) | 1024×1024 |
| Texture resolution (room) | 2048×2048 |
| Use Draco compression for GLB | Yes, level 6 |
| Merge static geometry | Yes, per zone |
| Apply all modifiers before export | Always |

## Anti-Patterns

- **Do not** use Blender's Edit Mode operations in loops — extremely slow; use bmesh API
- **Do not** create materials with image textures without UVs
- **Do not** export the entire scene — always export by collection
- **Do not** use `bpy.ops` in tight loops (slow due to context overhead) — prefer `bmesh` and direct API
- **Do not** leave n-gon faces in exported meshes — triangulate before export
- **Do not** export lights or cameras from Blender — managed entirely in R3F

## Triangulate Before Export

```python
def triangulate_all(collection_name: str):
    for obj in bpy.data.collections[collection_name].all_objects:
        if obj.type == 'MESH':
            mod = obj.modifiers.new("Triangulate", 'TRIANGULATE')
            bpy.ops.object.modifier_apply(modifier=mod.name)
```

## Asset Output Structure

```
public/assets/
├── rooms/
│   ├── neoclassical.glb
│   ├── modern.glb
│   ├── colonial.glb
│   └── brutalist.glb
├── furniture/
│   ├── bench_neo.glb
│   ├── bench_mod.glb
│   ├── table_counsel.glb
│   ├── witness_stand.glb
│   ├── jury_box.glb
│   └── podium.glb
├── props/
│   ├── gavel.glb
│   ├── document_stack.glb
│   ├── scales_justice.glb
│   └── microphone.glb
└── characters/
    ├── judge_base.glb
    ├── lawyer_m_base.glb
    └── lawyer_f_base.glb
```
