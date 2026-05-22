# Procedural Geometry Patterns — Attorney.AI

## Pattern 1: Parametric Box with Chamfer (bmesh)
```python
import bmesh, math

def chamfered_box(w, h, d, chamfer=0.05):
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1)
    bmesh.ops.scale(bm, vec=(w, d, h), verts=bm.verts)
    bmesh.ops.bevel(bm, geom=bm.edges, offset=chamfer,
                    offset_type='OFFSET', segments=2, profile=0.5)
    return bm
```

## Pattern 2: Procedural Column Array
```python
def column_array(room_w, room_d, count, radius, height):
    objs = []
    xs = [-room_w/2 + i * (room_w / (count-1)) for i in range(count)]
    for x in xs:
        for z_side in [-room_d/2 + 0.3, room_d/2 - 0.3]:
            objs.append(generate_column(radius, height, pos=(x, z_side, 0)))
    return objs
```

## Pattern 3: build123d Sweep Profile
For crown molding and chair rails.
```python
from build123d import *

def crown_molding(room_w, room_d, height, profile_h=80, profile_d=60):
    with BuildPart() as molding:
        with BuildSketch(Plane.XZ) as profile:
            with BuildLine():
                Line((0,0), (profile_d, 0))
                Line((profile_d, 0), (profile_d, profile_h))
                Line((profile_d, profile_h), (0, profile_h))
        extrude(amount=room_w)  # simplified — real impl uses sweep along perimeter
    return molding.part
```

## Pattern 4: UV-Safe Mesh Assembly
Always merge by distance after bmesh boolean operations to prevent UV seams.
```python
def merge_and_clean(bm):
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=0.001)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return bm
```

## Pattern 5: InstancedMesh Position Grid (R3F)
Gallery seating layout.
```js
export function galleryPositions(rows=4, cols=20, rowDepth=1.0, seatWidth=0.55) {
  return Array.from({ length: rows * cols }, (_, i) => {
    const row = Math.floor(i / cols)
    const col = i % cols
    return [
      (col - cols/2) * seatWidth + seatWidth/2,
      0,
      row * rowDepth + 2.0
    ]
  })
}
```
