# SKILL: courtroom-architecture

## Purpose

Generates the **procedural spatial layout** of the courtroom environment. This skill converts the `SceneConfig` from `legal-core` into a concrete room definition: dimensions, zones, furniture placement, acoustic zones, gallery seating, and witness stand positioning. It acts as the bridge between legal data and 3D geometry.

## Triggers

Activate when:
- `SceneConfig.courthouse_style` is set and a room must be built
- User says "build the courtroom", "set up the scene", "create the court environment"
- Blender or CAD modeling is about to begin (this skill runs first to define space)
- Scene reset or jurisdiction change occurs

## Spatial Model

```
╔══════════════════════════════════════════════════════════════════╗
║                     COURTROOM FLOOR PLAN                         ║
║                                                                  ║
║   [JURY BOX]          [JUDGE BENCH]         [WITNESS STAND]     ║
║      ████               ██████████              ████             ║
║                                                                  ║
║   [PLAINTIFF TABLE]              [DEFENSE TABLE]                 ║
║       ████████                     ████████                      ║
║                                                                  ║
║              [SPECTATOR GALLERY / BAR]                           ║
║   ███████████████████████████████████████████████████           ║
║   ███████████████████████████████████████████████████           ║
║                                                                  ║
║   [ENTRY DOOR]                           [SIDE DOOR]            ║
╚══════════════════════════════════════════════════════════════════╝
```

## Room Presets by Style

### neoclassical (Federal US)
- Dimensions: 20m × 14m × 6m
- Ceiling: coffered, 6m height
- Materials: marble floors, mahogany wood paneling, plaster columns
- Judge bench: raised 0.9m, solid mahogany
- Jury box: 12 seats, stage-left, enclosed railing
- Gallery: 80 seats, divided by bar rail
- Windows: tall arched, clear glass

### modern (State US)
- Dimensions: 16m × 12m × 3.5m
- Ceiling: flat acoustic tile, 3.5m
- Materials: carpet, laminate, glass partitions
- Judge bench: raised 0.6m, laminate
- Jury box: 12 seats, open
- Gallery: 60 seats, folding chairs
- Windows: horizontal strip, frosted

### colonial (UK Crown)
- Dimensions: 18m × 12m × 5m
- Ceiling: ornate plaster, 5m
- Materials: dark oak, leather, velvet
- Judge bench: raised 1.2m, enclosed
- Dock: enclosed glass/wood prisoner dock (rear)
- Jury box: 12 seats, side paneled
- Gallery: 40 seats, upper gallery level
- Windows: gothic arched

### brutalist (International ICC)
- Dimensions: 24m × 18m × 8m
- Ceiling: raw concrete, 8m
- Materials: concrete, glass, steel, neutral carpet
- Judge bench: flat, long (5 judges), raised 0.5m
- No jury (international tribunal)
- Gallery: 120 seats, terraced
- Windows: full-height, courtyard-facing

## Zone Definitions

```python
ZONES = {
    "bench":      { "position": [0, 0, -8],  "rotation": [0, 0, 0], "tag": "judge" },
    "plaintiff":  { "position": [-3, 0, -3], "rotation": [0, 0.3, 0], "tag": "counsel" },
    "defense":    { "position": [3, 0, -3],  "rotation": [0, -0.3, 0], "tag": "counsel" },
    "witness":    { "position": [3, 0, -6],  "rotation": [0, -0.5, 0], "tag": "witness" },
    "jury_box":   { "position": [-7, 0, -5], "rotation": [0, 0.8, 0], "tag": "jury" },
    "podium":     { "position": [0, 0, -4],  "rotation": [0, 0, 0], "tag": "podium" },
    "gallery":    { "position": [0, 0, 4],   "rotation": [0, 3.14, 0], "tag": "gallery" },
    "entry":      { "position": [0, 0, 8],   "rotation": [0, 0, 0], "tag": "door" }
}
```

## Rules (MUST follow)

1. **Judge bench always faces gallery** — Z-axis pointing toward spectators
2. **Jury box always stage-left** (negative X) — unless `enable_jury: false`
3. **Witness stand always flanks the bench** — never behind it
4. **Room dimensions scale with party count** — more parties = wider room
5. **Ceiling height drives lighting rigs** — hand this value to shader-lighting-system
6. **All zones must have collision volumes** — hand zone list to physics-interaction
7. **Dock zone only generated** for `uk_crown` style
8. **International style never generates jury box**

## Anti-Patterns

- **Do not** place defendant and plaintiff tables on the same side
- **Do not** generate a room without a defined `courthouse_style`
- **Do not** overlap furniture zones — minimum 1.5m clearance between tables
- **Do not** hard-code room size — always derive from style preset + party count
- **Do not** forget the `entry` zone — physics-interaction needs it for character spawn

## Output: RoomConfig JSON

```json
{
  "style": "neoclassical",
  "dimensions": { "w": 20, "d": 14, "h": 6 },
  "ceiling_height": 6,
  "materials": {
    "floor": "marble_white",
    "walls": "plaster_cream",
    "ceiling": "plaster_coffered",
    "trim": "mahogany"
  },
  "zones": { "...see above..." },
  "furniture": [
    { "type": "judge_bench", "zone": "bench", "style": "neoclassical" },
    { "type": "counsel_table", "zone": "plaintiff", "seats": 2 },
    { "type": "counsel_table", "zone": "defense", "seats": 2 },
    { "type": "witness_stand", "zone": "witness" },
    { "type": "jury_box", "zone": "jury_box", "seats": 12 },
    { "type": "podium", "zone": "podium" }
  ],
  "lighting_ceiling_h": 6
}
```

## scripts/layout_generator.py

```python
STYLE_PRESETS = {
    "neoclassical": {
        "dimensions": {"w": 20, "d": 14, "h": 6},
        "materials": {"floor": "marble_white", "walls": "plaster_cream",
                      "ceiling": "plaster_coffered", "trim": "mahogany"},
        "has_dock": False, "has_jury": True, "gallery_seats": 80
    },
    "modern": {
        "dimensions": {"w": 16, "d": 12, "h": 3.5},
        "materials": {"floor": "carpet_grey", "walls": "drywall_white",
                      "ceiling": "acoustic_tile", "trim": "laminate"},
        "has_dock": False, "has_jury": True, "gallery_seats": 60
    },
    "colonial": {
        "dimensions": {"w": 18, "d": 12, "h": 5},
        "materials": {"floor": "oak_dark", "walls": "oak_paneling",
                      "ceiling": "plaster_ornate", "trim": "dark_oak"},
        "has_dock": True, "has_jury": True, "gallery_seats": 40
    },
    "brutalist": {
        "dimensions": {"w": 24, "d": 18, "h": 8},
        "materials": {"floor": "carpet_neutral", "walls": "concrete_raw",
                      "ceiling": "concrete_raw", "trim": "steel"},
        "has_dock": False, "has_jury": False, "gallery_seats": 120
    }
}

def generate_room_config(scene_config: dict) -> dict:
    style = scene_config.get("courthouse_style", "modern")
    preset = STYLE_PRESETS[style]
    dims = preset["dimensions"]
    enable_jury = scene_config.get("enable_jury", True) and preset["has_jury"]

    furniture = [
        {"type": "judge_bench", "zone": "bench", "style": style},
        {"type": "counsel_table", "zone": "plaintiff", "seats": 2},
        {"type": "counsel_table", "zone": "defense", "seats": 2},
        {"type": "witness_stand", "zone": "witness"},
        {"type": "podium", "zone": "podium"}
    ]
    if enable_jury:
        furniture.append({"type": "jury_box", "zone": "jury_box", "seats": 12})
    if preset["has_dock"]:
        furniture.append({"type": "prisoner_dock", "zone": "dock"})

    return {
        "style": style,
        "dimensions": dims,
        "ceiling_height": dims["h"],
        "materials": preset["materials"],
        "furniture": furniture,
        "lighting_ceiling_h": dims["h"]
    }
```
