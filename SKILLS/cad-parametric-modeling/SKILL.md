# SKILL: cad-parametric-modeling

## Purpose

Uses **build123d** (Python CAD) to generate **precision parametric geometry** for architectural elements that require engineering accuracy — courtroom footprints, raised platforms, dock structures, column bases, stair profiles. Outputs `.step`, `.stl`, or `.brep` files that can be imported into Blender for rendering or directly into simulation environments.

## Source Repository
- `gumyr/build123d` — Pythonic CAD modeling (successor to CadQuery)
- Exports: STEP, STL, SVG, DXF, BREP

## Triggers

Activate when:
- Architectural precision matters (stairs, platform heights, column diameters)
- User says "CAD model", "parametric design", "exact dimensions"
- Structural components need to match real courthouse specifications
- Furniture must match ergonomic or ADA standards
- Generating courtroom floor plans for layout validation

## Why CAD Over Blender for Architecture?

| Concern | Blender bmesh | build123d CAD |
|---|---|---|
| Exact dimensions | Approximate | Exact to mm |
| Parametric constraints | Manual | Fully parametric |
| Curved profiles | Manual loops | Sweep/loft operations |
| ADA compliance | Manual | Enforced by constraints |
| Export to BIM | Not standard | STEP → Revit/ArchiCAD |
| Snap-to-grid errors | Common | Impossible |

## Core build123d Patterns

### 1. Basic Parametric Room Profile
```python
from build123d import *

def courthouse_floor_plan(
    width: float = 20_000,   # mm
    depth: float = 14_000,
    wall_thickness: float = 300
) -> Part:
    with BuildPart() as room:
        with BuildSketch() as outer:
            Rectangle(width, depth)
        with BuildSketch() as inner:
            Rectangle(width - 2*wall_thickness, depth - 2*wall_thickness)
        extrude(amount=3000)  # 3m wall height
    return room.part
```

### 2. Parametric Judge Bench
```python
def judge_bench(
    width: float = 3000,      # 3m wide
    height: float = 1200,     # 1.2m tall (raised platform)
    depth: float = 900,
    platform_h: float = 300   # 30cm platform raise
) -> Part:
    with BuildPart() as bench:
        # Main body
        Box(width, depth, height - platform_h)
        # Platform base
        with Locations((0, 0, -(height - platform_h)/2)):
            Box(width + 100, depth + 100, platform_h, mode=Mode.ADD)
        # Fascia panel (front face detail)
        with Locations((0, depth/2, 0)):
            Box(width, 20, height - platform_h, mode=Mode.SUBTRACT)
    return bench.part

def export_bench_stl(output_path: str = "judge_bench.stl"):
    part = judge_bench()
    export_stl(part, output_path)
    print(f"Exported: {output_path}")
```

### 3. Neoclassical Column (Doric Order)
```python
from build123d import *
import math

def doric_column(
    base_radius: float = 200,   # 20cm radius
    height: float = 5000,       # 5m height
    entasis: float = 0.03       # 3% taper (Doric standard)
) -> Part:
    # Shaft with entasis (classical taper)
    top_radius = base_radius * (1 - entasis)
    with BuildPart() as col:
        with BuildSketch(Plane.XZ) as profile:
            with BuildLine() as shaft_line:
                Line((base_radius, 0), (top_radius, height))
                Line((top_radius, height), (0, height))
                Line((0, 0), (base_radius, 0))
        revolve(axis=Axis.Z)

        # Capital (Doric abacus)
        with Locations((0, 0, height)):
            Box(base_radius*2.2, base_radius*2.2, base_radius*0.4)

        # Base (stylobate)
        with Locations((0, 0, -base_radius*0.3)):
            Cylinder(base_radius*1.3, base_radius*0.3)
    return col.part
```

### 4. Raised Jury Box Platform
```python
def jury_box(
    seats: int = 12,
    seat_width: float = 550,
    rows: int = 2,
    platform_h: float = 150,
    railing_h: float = 900
) -> Part:
    total_width = (seats // rows) * seat_width
    total_depth = rows * 800  # 80cm row depth

    with BuildPart() as box:
        # Platform
        Box(total_width, total_depth, platform_h)

        # Front railing
        with Locations((0, -total_depth/2, platform_h)):
            Box(total_width, 50, railing_h, mode=Mode.ADD)

        # Side railings
        for x in [-total_width/2, total_width/2]:
            with Locations((x, 0, platform_h)):
                Box(50, total_depth, railing_h, mode=Mode.ADD)
    return box.part
```

### 5. Stair Profile (ADA Compliant)
```python
def ada_stair(
    steps: int = 3,
    tread: float = 300,     # 30cm tread depth (ADA min)
    riser: float = 180,     # 18cm riser (ADA max)
    width: float = 1200
) -> Part:
    with BuildPart() as stair:
        for i in range(steps):
            with Locations((0, i * tread, i * riser)):
                Box(width, tread, riser * (steps - i))
    return stair.part
```

## Export Functions

```python
from build123d import export_stl, export_step, export_svg

def export_all(part: Part, name: str, output_dir: str = "./exports"):
    export_step(part, f"{output_dir}/{name}.step")
    export_stl(part, f"{output_dir}/{name}.stl", tolerance=0.1, angular_tolerance=1.0)
    print(f"Exported {name}: STEP + STL")
```

## Courthouse Parametric Spec Library

```python
COURTHOUSE_SPECS = {
    "federal_us": {
        "room": {"w": 20000, "d": 14000, "h": 6000, "wall_t": 400},
        "bench": {"w": 3000, "h": 1200, "d": 900, "platform_h": 300},
        "jury": {"seats": 12, "rows": 2, "platform_h": 200},
        "column": {"radius": 250, "height": 5500},
        "gallery_step_h": 200,
        "ada_ramp_grade": 0.0833   # 1:12 ADA max slope
    },
    "state_us": {
        "room": {"w": 16000, "d": 12000, "h": 3500, "wall_t": 250},
        "bench": {"w": 2800, "h": 900, "d": 800, "platform_h": 150},
        "jury": {"seats": 12, "rows": 2, "platform_h": 100},
        "column": None,
        "gallery_step_h": 0,
        "ada_ramp_grade": 0.0833
    },
    "uk_crown": {
        "room": {"w": 18000, "d": 12000, "h": 5000, "wall_t": 500},
        "bench": {"w": 2500, "h": 1500, "d": 1000, "platform_h": 400},
        "dock": {"w": 1800, "d": 1500, "h": 2000, "glass_h": 1200},
        "jury": {"seats": 12, "rows": 3, "platform_h": 300},
        "column": None
    }
}

def build_from_spec(jurisdiction: str) -> dict:
    spec = COURTHOUSE_SPECS.get(jurisdiction, COURTHOUSE_SPECS["state_us"])
    parts = {}
    if spec.get("bench"):
        parts["bench"] = judge_bench(**spec["bench"])
    if spec.get("jury"):
        parts["jury"] = jury_box(**spec["jury"])
    if spec.get("column"):
        parts["column"] = doric_column(**spec["column"])
    return parts
```

## Integration with Blender

CAD output → Blender import pipeline:
1. Export STEP from build123d
2. Import STEP into Blender via `io_scene_step` or FreeCAD intermediate
3. Apply subdivision surface modifier for smoothing (columns)
4. UV unwrap and assign materials
5. Export GLB for R3F

For STL direct import:
```python
# In Blender Python after STL import:
bpy.ops.import_mesh.stl(filepath="judge_bench.stl")
# Set origin to geometry
bpy.ops.object.origin_set(type='ORIGIN_GEOMETRY')
```

## ADA Compliance Checklist

| Element | ADA Requirement | CAD Parameter |
|---|---|---|
| Ramp slope | Max 1:12 (8.33%) | `ada_ramp_grade ≤ 0.0833` |
| Door width | Min 914mm | `door_w ≥ 914` |
| Stair riser | Max 180mm | `riser ≤ 180` |
| Stair tread | Min 280mm | `tread ≥ 280` |
| Hearing loop | Must be indicated in CAD | Zone marking in floor plan |
| Jury box access | Accessible route required | Ramp or lift zone |

## Anti-Patterns

- **Do not** model curved architectural profiles with Box approximations — use `Sweep` or `Loft`
- **Do not** export STL at default tolerance — always set `tolerance=0.1` for smooth curves
- **Do not** mix mm and m in the same model — build123d uses consistent units
- **Do not** use CAD for organic shapes (characters, props) — use Blender for those
- **Do not** skip ADA compliance parameters for public courthouse models
