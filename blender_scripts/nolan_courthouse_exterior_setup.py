"""
╔══════════════════════════════════════════════════════════════════════════╗
║  ATTORNEY.AI — Nolan County Courthouse  ·  Exterior Scene Setup         ║
║  Imports nolan_county_courthouse_3d_mesh.glb and builds full exterior   ║
║  Compatible: Blender 3.3 LTS → 4.x                                     ║
╚══════════════════════════════════════════════════════════════════════════╝

HOW TO USE:
  1. Open Blender → Scripting workspace
  2. New → paste / open this file → ▶ Run Script
  3. F12 = render aerial view    (Cam_Aerial)
  4. Select Cam_Front → Ctrl+Numpad0  (front elevation)
  5. Select Cam_Plaza → Ctrl+Numpad0  (street level)

WHAT THIS DOES:
  • Imports the GLB mesh, auto-centers it on world origin
  • Scales it to real-world dimensions (auto-detected from bounds)
  • Builds ground plane, plaza paving, sidewalks, roads
  • Adds trees, lamp posts, parked cars, people silhouettes
  • Golden-hour sun lighting + physical Nishita sky
  • Three calibrated cameras (aerial, front, street level)
  • Cycles render: 2560×1440, adaptive sampling, OIDN denoising
"""

import bpy
import bmesh
import math
import random
from mathutils import Vector

random.seed(42)
PI  = math.pi

# ── Absolute path to the GLB mesh ──────────────────────────────────────
GLB_PATH = r"C:\Users\The Laptop Hut\Desktop\attorney-ai\blender_scripts\nolan_county_courthouse_3d_mesh.glb"

# ═══════════════════════════════════════════════════════════════════════
#  SCENE HELPERS
# ═══════════════════════════════════════════════════════════════════════

def clear_scene():
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    for blk in (bpy.data.meshes, bpy.data.cameras, bpy.data.lights,
                bpy.data.materials, bpy.data.collections, bpy.data.curves):
        for item in list(blk):
            try: blk.remove(item)
            except Exception: pass

def col(name, parent=None):
    if name in bpy.data.collections:
        return bpy.data.collections[name]
    c = bpy.data.collections.new(name)
    (parent or bpy.context.scene.collection).children.link(c)
    return c

def obj_link(obj, collection):
    for c in list(obj.users_collection):
        c.objects.unlink(obj)
    collection.objects.link(obj)

def apply_bevel(obj, width=0.03, segs=3):
    mod = obj.modifiers.new("Bevel", 'BEVEL')
    mod.width        = width
    mod.segments     = segs
    mod.limit_method = 'ANGLE'
    mod.angle_limit  = math.radians(60)

# ═══════════════════════════════════════════════════════════════════════
#  MATERIAL SYSTEM
# ═══════════════════════════════════════════════════════════════════════

M = {}

def safe_input(node, name, value):
    if name in node.inputs:
        node.inputs[name].default_value = value

def _lnk(nt, a_out, b_in):
    nt.links.new(a_out, b_in)

def base_bsdf(nt):
    out  = nt.nodes.new('ShaderNodeOutputMaterial'); out.location  = (800, 0)
    bsdf = nt.nodes.new('ShaderNodeBsdfPrincipled'); bsdf.location = (400, 0)
    _lnk(nt, bsdf.outputs['BSDF'], out.inputs['Surface'])
    return bsdf, out

def mat_simple(name, base, metal=0.0, rough=0.5, emission=None, emit_str=0.0):
    if name in M: return M[name]
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree; nt.nodes.clear()
    bsdf, out = base_bsdf(nt)
    safe_input(bsdf, 'Base Color', (*base, 1.0))
    safe_input(bsdf, 'Metallic',   metal)
    safe_input(bsdf, 'Roughness',  rough)
    if emission:
        safe_input(bsdf, 'Emission Color',    (*emission, 1.0))
        safe_input(bsdf, 'Emission',          (*emission, 1.0))
        safe_input(bsdf, 'Emission Strength', emit_str)
    M[name] = m; return m

def mat_glass_dark(name):
    if name in M: return M[name]
    m = bpy.data.materials.new(name); m.use_nodes = True
    nt = m.node_tree; nt.nodes.clear()
    out = nt.nodes.new('ShaderNodeOutputMaterial'); out.location = (400, 0)
    gls = nt.nodes.new('ShaderNodeBsdfGlass');      gls.location = (0, 0)
    gls.inputs['Color'].default_value     = (0.04, 0.06, 0.10, 1.0)
    gls.inputs['Roughness'].default_value = 0.04
    gls.inputs['IOR'].default_value       = 1.52
    _lnk(nt, gls.outputs['BSDF'], out.inputs['Surface'])
    try: m.blend_method = 'BLEND'
    except: pass
    M[name] = m; return m

def mat_plaza(name):
    """Cream stone paving with subtle tile grid."""
    if name in M: return M[name]
    m = bpy.data.materials.new(name); m.use_nodes = True
    nt = m.node_tree; nt.nodes.clear()
    bsdf, out = base_bsdf(nt)
    tc = nt.nodes.new('ShaderNodeTexCoord'); tc.location = (-700, 0)
    mp = nt.nodes.new('ShaderNodeMapping');  mp.location = (-500, 0)
    mp.inputs['Scale'].default_value = (5, 5, 5)
    _lnk(nt, tc.outputs['Object'], mp.inputs['Vector'])
    wx = nt.nodes.new('ShaderNodeTexWave'); wx.location = (-300, 100)
    wx.wave_type = 'BANDS'; wx.bands_direction = 'X'
    wx.inputs['Scale'].default_value = 6.0
    wy = nt.nodes.new('ShaderNodeTexWave'); wy.location = (-300,-100)
    wy.wave_type = 'BANDS'; wy.bands_direction = 'Y'
    wy.inputs['Scale'].default_value = 6.0
    _lnk(nt, mp.outputs['Vector'], wx.inputs['Vector'])
    _lnk(nt, mp.outputs['Vector'], wy.inputs['Vector'])
    mx = nt.nodes.new('ShaderNodeMath'); mx.operation='MULTIPLY'; mx.location=(-80,0)
    _lnk(nt, wx.outputs['Fac'], mx.inputs[0])
    _lnk(nt, wy.outputs['Fac'], mx.inputs[1])
    cr = nt.nodes.new('ShaderNodeValToRGB'); cr.location=(100,0)
    cr.color_ramp.elements[0].color = (0.74, 0.72, 0.66, 1.0)
    el2 = cr.color_ramp.elements.new(0.10); el2.color = (0.89, 0.87, 0.81, 1.0)
    cr.color_ramp.elements[1].color = (0.91, 0.89, 0.85, 1.0)
    _lnk(nt, mx.outputs['Value'], cr.inputs['Fac'])
    _lnk(nt, cr.outputs['Color'], bsdf.inputs['Base Color'])
    safe_input(bsdf, 'Roughness', 0.30)
    M[name] = m; return m

def build_all_materials():
    mat_simple('MAT_Stone',    (0.82, 0.78, 0.68), rough=0.55)   # warm sandstone
    mat_simple('MAT_StoneDk',  (0.62, 0.58, 0.50), rough=0.65)   # darker stone trim
    mat_simple('MAT_Brick',    (0.65, 0.38, 0.25), rough=0.80)   # red brick
    mat_simple('MAT_Roof',     (0.38, 0.32, 0.28), rough=0.75)   # dark roof
    mat_plaza('MAT_Plaza')
    mat_simple('MAT_Sidewalk', (0.72, 0.70, 0.65), rough=0.75)   # concrete sidewalk
    mat_simple('MAT_Road',     (0.12, 0.12, 0.12), rough=0.92)   # asphalt road
    mat_simple('MAT_Grass',    (0.08, 0.35, 0.06), rough=1.00)
    mat_simple('MAT_GrassDk',  (0.05, 0.22, 0.04), rough=1.00)
    mat_simple('MAT_Ground',   (0.30, 0.26, 0.18), rough=1.00)
    mat_simple('MAT_TreeLeaf', (0.07, 0.28, 0.05), rough=1.00)
    mat_simple('MAT_TreeLeafDk',(0.04,0.18, 0.03), rough=1.00)
    mat_simple('MAT_TreeTrunk',(0.28, 0.18, 0.08), rough=1.00)
    mat_simple('MAT_Hedge',    (0.04, 0.22, 0.04), rough=1.00)
    mat_glass_dark('MAT_WinDark')
    mat_simple('MAT_LampMetal',(0.25, 0.24, 0.22), metal=0.80, rough=0.25)
    mat_simple('MAT_LampGlow', (1.00, 0.94, 0.76),
               emission=(1.0, 0.94, 0.76), emit_str=14.0)
    mat_simple('MAT_FlagUSA',  (0.70, 0.10, 0.10), rough=0.85)
    mat_simple('MAT_FlagPole', (0.78, 0.78, 0.76), metal=0.85, rough=0.20)
    mat_simple('MAT_CarWhite', (0.90, 0.89, 0.87), rough=0.25, metal=0.05)
    mat_simple('MAT_CarBlack', (0.05, 0.05, 0.06), rough=0.22, metal=0.05)
    mat_simple('MAT_CarRed',   (0.55, 0.05, 0.05), rough=0.28, metal=0.05)
    mat_simple('MAT_CarSilver',(0.65, 0.65, 0.66), rough=0.20, metal=0.30)
    mat_simple('MAT_Person',   (0.15, 0.12, 0.10), rough=0.90)
    mat_simple('MAT_Bench',    (0.45, 0.32, 0.18), rough=0.80)
    mat_simple('MAT_Concrete', (0.55, 0.54, 0.52), rough=0.85)
    mat_simple('MAT_ParkLine', (0.82, 0.82, 0.82), rough=0.90)

def asgn(obj, mat_name):
    if mat_name not in M: return
    if obj.data.materials: obj.data.materials[0] = M[mat_name]
    else:                   obj.data.materials.append(M[mat_name])

# ═══════════════════════════════════════════════════════════════════════
#  PRIMITIVE BUILDERS
# ═══════════════════════════════════════════════════════════════════════

def BOX(name, loc, sx, sy, sz, collection, mat='MAT_Stone',
        rx=0, ry=0, rz=0, bevel=False, bw=0.04):
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=2.0)
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free()
    obj = bpy.data.objects.new(name, me)
    obj_link(obj, collection)
    obj.location       = loc
    obj.scale          = (sx, sy, sz)
    obj.rotation_euler = (rx, ry, rz)
    asgn(obj, mat)
    if bevel: apply_bevel(obj, bw)
    return obj

def CYL(name, loc, r, h, collection, mat='MAT_TreeTrunk', verts=32):
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False,
                          segments=verts, radius1=r, radius2=r, depth=h)
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free()
    obj = bpy.data.objects.new(name, me)
    obj_link(obj, collection)
    obj.location = loc
    asgn(obj, mat)
    return obj

def CONE_OBJ(name, loc, r1, r2, h, collection, mat='MAT_StoneDk', verts=8):
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False,
                          segments=verts, radius1=r1, radius2=r2, depth=h)
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free()
    obj = bpy.data.objects.new(name, me)
    obj_link(obj, collection)
    obj.location = loc
    asgn(obj, mat)
    return obj

def SPHERE(name, loc, r, collection, mat='MAT_TreeLeaf'):
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=24, v_segments=12, radius=r)
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free()
    obj = bpy.data.objects.new(name, me)
    obj_link(obj, collection)
    obj.location = loc
    asgn(obj, mat)
    return obj

def PLANE(name, loc, sx, sy, collection, mat='MAT_Grass', rz=0):
    bm = bmesh.new()
    bmesh.ops.create_grid(bm, x_segments=2, y_segments=2, size=1.0)
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free()
    obj = bpy.data.objects.new(name, me)
    obj_link(obj, collection)
    obj.location       = loc
    obj.scale          = (sx, sy, 1)
    obj.rotation_euler = (0, 0, rz)
    asgn(obj, mat)
    return obj

# ═══════════════════════════════════════════════════════════════════════
#  GLB IMPORT + AUTO-FIT
# ═══════════════════════════════════════════════════════════════════════

def import_courthouse(C_BLD):
    """
    Import the GLB, move all its objects into the Buildings collection,
    center on world origin X/Y, set base at Z=0.
    Returns the bounding-box dimensions (width, depth, height) in metres.
    """
    print("  [GLB] Importing nolan_county_courthouse_3d_mesh.glb ...")
    before = set(bpy.data.objects.keys())
    bpy.ops.import_scene.gltf(filepath=GLB_PATH)
    after  = set(bpy.data.objects.keys())
    new_objs = [bpy.data.objects[n] for n in (after - before)]

    if not new_objs:
        print("  [GLB] WARNING — no objects imported. Check GLB_PATH.")
        return 30.0, 30.0, 15.0   # fallback dimensions

    # Move all imported objects into Buildings collection
    for obj in new_objs:
        obj_link(obj, C_BLD)

    # ── Compute world bounding box ──────────────────────────────────
    min_co = Vector((1e9, 1e9, 1e9))
    max_co = Vector((-1e9,-1e9,-1e9))
    for obj in new_objs:
        if obj.type != 'MESH': continue
        for corner in obj.bound_box:
            wco = obj.matrix_world @ Vector(corner)
            min_co.x = min(min_co.x, wco.x)
            min_co.y = min(min_co.y, wco.y)
            min_co.z = min(min_co.z, wco.z)
            max_co.x = max(max_co.x, wco.x)
            max_co.y = max(max_co.y, wco.y)
            max_co.z = max(max_co.z, wco.z)

    ctr_x = (min_co.x + max_co.x) / 2
    ctr_y = (min_co.y + max_co.y) / 2
    w = max_co.x - min_co.x
    d = max_co.y - min_co.y
    h = max_co.z - min_co.z

    print(f"  [GLB] Raw bounds: {w:.2f} × {d:.2f} × {h:.2f} m")

    # ── Auto-scale to sensible courthouse size ──────────────────────
    # Nolan County Courthouse is roughly 30m × 30m footprint, ~18m tall
    TARGET_H = 18.0
    if h > 0.01:
        scale_factor = TARGET_H / h
        print(f"  [GLB] Scaling by {scale_factor:.4f} to match {TARGET_H}m target height")
        for obj in new_objs:
            obj.scale *= scale_factor
        # Recompute after scale
        bpy.context.view_layer.update()
        min_co = Vector((1e9, 1e9, 1e9))
        max_co = Vector((-1e9,-1e9,-1e9))
        for obj in new_objs:
            if obj.type != 'MESH': continue
            for corner in obj.bound_box:
                wco = obj.matrix_world @ Vector(corner)
                min_co.x = min(min_co.x, wco.x)
                min_co.y = min(min_co.y, wco.y)
                min_co.z = min(min_co.z, wco.z)
                max_co.x = max(max_co.x, wco.x)
                max_co.y = max(max_co.y, wco.y)
                max_co.z = max(max_co.z, wco.z)
        ctr_x = (min_co.x + max_co.x) / 2
        ctr_y = (min_co.y + max_co.y) / 2
        w = max_co.x - min_co.x
        d = max_co.y - min_co.y
        h = max_co.z - min_co.z

    # ── Center X/Y, bottom at Z=0 ───────────────────────────────────
    offset = Vector((-ctr_x, -ctr_y, -min_co.z))
    for obj in new_objs:
        obj.location += offset
    bpy.context.view_layer.update()

    print(f"  [GLB] Final size: {w:.1f} × {d:.1f} × {h:.1f} m  (centered, base=0)")
    return w, d, h

# ═══════════════════════════════════════════════════════════════════════
#  GROUND, PLAZA, ROADS  (sized around the building)
# ═══════════════════════════════════════════════════════════════════════

def build_ground(C_GND, bw, bd):
    hw = bw / 2; hd = bd / 2
    PLANE('Gnd_Base',    (0, 0, -0.12), 300, 300, C_GND, 'MAT_Ground')

    # Courthouse lawn (surrounds building on all sides)
    PLANE('Lawn_Front',  (0, -(hd+22), 0.02), bw+40, 28, C_GND, 'MAT_Grass')
    PLANE('Lawn_Rear',   (0,  (hd+22), 0.02), bw+40, 28, C_GND, 'MAT_Grass')
    PLANE('Lawn_L',      (-(hw+22), 0, 0.02), 28, bd+60, C_GND, 'MAT_Grass')
    PLANE('Lawn_R',      ( (hw+22), 0, 0.02), 28, bd+60, C_GND, 'MAT_Grass')

    # Sidewalks (concrete, 4m wide)
    PLANE('SW_Front', (0, -(hd+8),  0.02), bw+32, 4, C_GND, 'MAT_Sidewalk')
    PLANE('SW_Rear',  (0,  (hd+8),  0.02), bw+32, 4, C_GND, 'MAT_Sidewalk')
    PLANE('SW_L',     (-(hw+8), 0, 0.02),  4, bd+16, C_GND, 'MAT_Sidewalk')
    PLANE('SW_R',     ( (hw+8), 0, 0.02),  4, bd+16, C_GND, 'MAT_Sidewalk')

    # Front plaza approach (stone paving leading to entrance steps)
    PLANE('Plaza_Front', (0, -(hd+4), 0.025), bw*0.7, 10, C_GND, 'MAT_Plaza')

    # Roads
    PLANE('Rd_Front', (0, -(hd+40), 0.02), bw+80, 14, C_GND, 'MAT_Road')
    PLANE('Rd_Rear',  (0,  (hd+40), 0.02), bw+80, 14, C_GND, 'MAT_Road')
    PLANE('Rd_L',     (-(hw+40), 0, 0.02), 14, bd+80, C_GND, 'MAT_Road')
    PLANE('Rd_R',     ( (hw+40), 0, 0.02), 14, bd+80, C_GND, 'MAT_Road')

    # Parking lots (both sides)
    PLANE('Lot_L', (-(hw+60), 0, 0.01), 30, bd+20, C_GND, 'MAT_Road')
    PLANE('Lot_R', ( (hw+60), 0, 0.01), 30, bd+20, C_GND, 'MAT_Road')

def build_parking_lines(C_INF, bw, bd):
    hw = bw / 2
    for row in range(8):
        for slot in range(7):
            for s, tag in [(-1,'L'),(1,'R')]:
                lx = s * (hw + 50 + slot * 3.8)
                ly = -(bd/2) + 5 + row * 6.5
                BOX(f'PkLn_{tag}_{row}_{slot}',
                    (lx, ly, 0.015), 1.1, 0.06, 0.01, C_INF, 'MAT_ParkLine')

# ═══════════════════════════════════════════════════════════════════════
#  STEPS + PILLARS (courthouse entry — in front of building)
# ═══════════════════════════════════════════════════════════════════════

def build_entry_steps(C_BLD, bw, bd):
    """
    Broad entry steps + classical columns appropriate for a Texas county courthouse.
    Placed at front face (y = -bd/2).
    """
    hd = bd / 2
    step_w = min(bw * 0.55, 24.0)   # steps span 55% of facade width
    for s in range(4):
        sw = step_w / 2 - s * 0.8
        sy = 1.5 - s * 0.6
        sz = 0.5
        y  = -(hd + 0.5 + (4 - s) * 1.2)
        z  = 0.25 + s * 1.0
        BOX(f'Step_{s}', (0, y, z), sw, sy, sz, C_BLD, 'MAT_Stone', bevel=True, bw=0.05)

    # Classical columns (6 across front portico)
    n_col = 6
    portico_w = step_w * 0.85
    for i in range(n_col):
        px = -portico_w / 2 + i * (portico_w / (n_col - 1))
        CYL(f'Col_{i}', (px, -(hd + 0.5), 7.0), 0.55, 14.0, C_BLD, 'MAT_Stone', verts=24)
        # Capital
        BOX(f'ColCap_{i}', (px, -(hd + 0.5), 14.3), 0.80, 0.80, 0.40, C_BLD, 'MAT_Stone')

    # Entablature spanning columns
    BOX('Entablature', (0, -(hd + 0.5), 14.8), portico_w / 2 + 0.6, 0.8, 0.55,
        C_BLD, 'MAT_Stone', bevel=True, bw=0.04)
    # Pediment (triangular gable)
    BOX('Pediment',    (0, -(hd + 0.5), 16.4), portico_w / 2 + 0.3, 0.65, 1.0,
        C_BLD, 'MAT_Stone', bevel=True, bw=0.06)

    # Flag poles (standard in front of US county courthouses)
    for s, tag in [(-1,'L'),(1,'R')]:
        px = s * (step_w / 2 + 4)
        py = -(hd + 12)
        CYL(f'FPole_{tag}',   (px, py, 12.0), 0.10, 24.0, C_BLD, 'MAT_FlagPole', verts=16)
        SPHERE(f'FBall_{tag}',(px, py, 24.1), 0.22,        C_BLD, 'MAT_FlagPole')
        BOX(f'Flag_{tag}',    (px + s*1.8, py, 21.0), 1.8, 0.03, 0.90,
            C_BLD, 'MAT_FlagUSA')

# ═══════════════════════════════════════════════════════════════════════
#  TREES
# ═══════════════════════════════════════════════════════════════════════

def TREE(prefix, x, y, collection, h=6.0, cr=2.2, mat='MAT_TreeLeaf'):
    CYL(f'{prefix}_T',   (x, y, h*0.36), 0.22, h*0.72, collection, 'MAT_TreeTrunk')
    SPHERE(f'{prefix}_C0',(x,        y,        h*0.88), cr,        collection, mat)
    SPHERE(f'{prefix}_C1',(x+cr*0.5, y+cr*0.2, h*0.80), cr*0.72,  collection, mat)
    SPHERE(f'{prefix}_C2',(x-cr*0.4, y-cr*0.3, h*0.78), cr*0.65,  collection, mat)

def build_trees(C_NAT, bw, bd):
    hw = bw / 2; hd = bd / 2

    # Lawn trees flanking front approach
    for i in range(5):
        x_off = -hw - 4 + i * (hw * 2 + 8) / 4
        TREE(f'Fr_L{i}', x_off, -(hd + 18), C_NAT, h=7, cr=2.8)
    for i in range(5):
        x_off = -hw - 4 + i * (hw * 2 + 8) / 4
        TREE(f'Fr_R{i}', x_off, -(hd + 30), C_NAT, h=8, cr=3.0)

    # Side lawn trees
    for s, tag in [(-1,'L'),(1,'R')]:
        for i in range(7):
            y = -hd + i * (bd + 8) / 6
            TREE(f'Side_{tag}_{i}', s*(hw + 15), y, C_NAT,
                 h=7 + random.uniform(0,2), cr=2.5 + random.uniform(0,0.8))

    # Rear trees
    for i in range(6):
        x_off = -hw + i * bw / 5
        TREE(f'Rear_{i}', x_off, hd + 18, C_NAT, h=8, cr=3.2)

    # Perimeter street trees along roads
    for i in range(12):
        x = -hw - 40 + i * (bw + 80) / 11
        TREE(f'St_F{i}', x, -(hd + 45), C_NAT, h=9, cr=3.5, mat='MAT_TreeLeafDk')
        TREE(f'St_R{i}', x,  (hd + 45), C_NAT, h=9, cr=3.5, mat='MAT_TreeLeafDk')

    # Dense corner clumps
    for corner_x, corner_y in [(-hw-18,-hd-18),(hw+18,-hd-18),
                                 (-hw-18, hd+18),(hw+18, hd+18)]:
        for k in range(4):
            ox = corner_x + random.uniform(-4,4)
            oy = corner_y + random.uniform(-4,4)
            TREE(f'Cnr_{corner_x:.0f}_{corner_y:.0f}_{k}', ox, oy, C_NAT,
                 h=random.uniform(7,11), cr=random.uniform(2.5,4),
                 mat='MAT_TreeLeaf')

# ═══════════════════════════════════════════════════════════════════════
#  LAMP POSTS  (ornate street style for historic courthouse)
# ═══════════════════════════════════════════════════════════════════════

def LAMP(prefix, x, y, collection):
    BOX(f'{prefix}_B',   (x,y,0.25), 0.45,0.45,0.25, collection,'MAT_LampMetal')
    CONE_OBJ(f'{prefix}_Sh',(x,y,5.5), 0.12,0.08,10.5,collection,'MAT_LampMetal',verts=16)
    BOX(f'{prefix}_Arm', (x+0.8,y,10.8), 0.8,0.06,0.06,collection,'MAT_LampMetal')
    CYL(f'{prefix}_Hous',(x+1.6,y,10.4), 0.28,0.45,collection,'MAT_LampMetal',verts=8)
    SPHERE(f'{prefix}_Gl',(x+1.6,y,10.4),0.24,collection,'MAT_LampGlow')

def build_lamps(C_INF, bw, bd):
    hw = bw / 2; hd = bd / 2
    # Front approach lamps
    for i in range(6):
        x = -hw * 0.7 + i * hw * 1.4 / 5
        LAMP(f'Lp_Ft{i}', x, -(hd + 10), C_INF)
    # Street lamps along front road
    for i in range(8):
        x = -hw - 36 + i * (bw + 72) / 7
        LAMP(f'Lp_St{i}', x, -(hd + 38), C_INF)
    # Side lamps
    for s, tag in [(-1,'L'),(1,'R')]:
        for i in range(5):
            LAMP(f'Lp_{tag}_{i}', s*(hw+10), -hd+8+i*(bd+4)/4, C_INF)

# ═══════════════════════════════════════════════════════════════════════
#  CARS  (parked in lots)
# ═══════════════════════════════════════════════════════════════════════

CAR_MATS = ['MAT_CarWhite','MAT_CarBlack','MAT_CarRed','MAT_CarSilver']

def DETAILED_CAR(prefix, x, y, collection):
    mat = random.choice(CAR_MATS)
    BOX(f'{prefix}_Bd',(x,y,0.52), 1.05,2.25,0.52, collection, mat)
    BOX(f'{prefix}_Cb',(x,y+0.15,1.14),0.90,1.35,0.38,collection, mat)
    BOX(f'{prefix}_WS',(x,y-0.72,1.05),0.88,0.06,0.36,collection,'MAT_WinDark')
    for wx2,wy2 in [(-0.6,-0.84),(0.6,-0.84),(-0.6,0.84),(0.6,0.84)]:
        CYL(f'{prefix}_W{wx2}{wy2}',(x+wx2,y+wy2,0.27),0.28,0.22,collection,'MAT_LampMetal',verts=12)

def build_cars(C_INF, bw, bd):
    hw = bw / 2
    for row in range(8):
        for slot in range(7):
            for s, tag in [(-1,'L'),(1,'R')]:
                lx = s * (hw + 50 + slot * 3.8)
                ly = -(bd / 2) + 5 + row * 6.5
                DETAILED_CAR(f'Car_{tag}_{row}_{slot}', lx, ly, C_INF)

# ═══════════════════════════════════════════════════════════════════════
#  PEOPLE SILHOUETTES  (plaza + sidewalk)
# ═══════════════════════════════════════════════════════════════════════

def PERSON(name, x, y, collection):
    BOX(f'{name}_B',  (x,y,0.90), 0.22,0.12,0.90, collection,'MAT_Person')
    SPHERE(f'{name}_H',(x,y,2.05),0.22,            collection,'MAT_Person')

def build_people(C_DET, bw, bd):
    hd = bd / 2
    base_y = -(hd + 8)
    pts = []
    for _ in range(30):
        px = random.uniform(-bw*0.4, bw*0.4)
        py = base_y + random.uniform(-6, 2)
        pts.append((px, py))
    for i, (px, py) in enumerate(pts):
        PERSON(f'P{i}', px, py, C_DET)

# ═══════════════════════════════════════════════════════════════════════
#  BENCHES + MONUMENT PLACEHOLDER
# ═══════════════════════════════════════════════════════════════════════

def build_street_furniture(C_DET, bw, bd):
    hw = bw / 2; hd = bd / 2
    # Benches in front lawn
    for s, tag in [(-1,'L'),(1,'R')]:
        bx = s * hw * 0.4
        by = -(hd + 22)
        BOX(f'Bench_{tag}',  (bx, by, 0.45), 1.5, 0.22, 0.06, C_DET, 'MAT_Bench')
        BOX(f'BenchLg_{tag}',(bx, by, 0.28), 1.5, 0.10, 0.28, C_DET, 'MAT_Concrete')
        for sb in [-1,1]:
            BOX(f'BLeg_{tag}_{sb}',(bx+sb*1.35, by, 0.16),0.08,0.12,0.16,C_DET,'MAT_Concrete')

    # Central monument / statue plinth in front lawn
    BOX('Mnmt_Base',  (0, -(hd+26), 0.6), 2.5, 2.5, 0.6, C_DET, 'MAT_Stone', bevel=True, bw=0.06)
    BOX('Mnmt_Shaft', (0, -(hd+26), 2.5), 0.6, 0.6, 2.5, C_DET, 'MAT_Stone', bevel=True, bw=0.04)
    SPHERE('Mnmt_Top',(0, -(hd+26), 5.3), 0.55, C_DET, 'MAT_Stone')

# ═══════════════════════════════════════════════════════════════════════
#  LIGHTING  (warm afternoon sun — classic Texas courthouse look)
# ═══════════════════════════════════════════════════════════════════════

def build_lighting():
    bpy.ops.object.light_add(type='SUN', location=(80,-120,80))
    sun = bpy.context.active_object; sun.name='Sun_Key'
    sun.data.energy = 6.0
    sun.data.color  = (1.0, 0.92, 0.78)
    sun.data.angle  = math.radians(1.0)
    sun.rotation_euler = (math.radians(40), math.radians(8), math.radians(-38))

    bpy.ops.object.light_add(type='AREA', location=(0, 0, 120))
    fill = bpy.context.active_object; fill.name='Sky_Fill'
    fill.data.energy = 480; fill.data.size = 280
    fill.data.color  = (0.60, 0.76, 1.0)

    bpy.ops.object.light_add(type='AREA', location=(-80, 80, 55))
    rim = bpy.context.active_object; rim.name='Rim_Light'
    rim.data.energy = 220; rim.data.size = 100
    rim.data.color  = (0.78, 0.88, 1.0)
    rim.rotation_euler = (math.radians(46), 0, math.radians(135))

    bpy.ops.object.light_add(type='AREA', location=(0, -10, 1))
    bnc = bpy.context.active_object; bnc.name='Ground_Bounce'
    bnc.data.energy = 140; bnc.data.size = 160
    bnc.data.color  = (1.0, 0.95, 0.82)
    bnc.rotation_euler = (math.radians(180), 0, 0)

# ═══════════════════════════════════════════════════════════════════════
#  WORLD — Nishita sky (clear Texas afternoon)
# ═══════════════════════════════════════════════════════════════════════

def build_world():
    scene = bpy.context.scene
    world = bpy.data.worlds.new("CourthouseWorld")
    scene.world = world; world.use_nodes = True
    nt = world.node_tree; nt.nodes.clear()
    out = nt.nodes.new('ShaderNodeOutputWorld'); out.location = (400, 0)
    bg  = nt.nodes.new('ShaderNodeBackground');  bg.location  = (200, 0)
    sky = nt.nodes.new('ShaderNodeTexSky');       sky.location = (-100, 0)
    sky.sky_type      = 'NISHITA'
    sky.sun_elevation = math.radians(40)
    sky.sun_rotation  = math.radians(215)
    sky.air_density   = 1.0
    sky.dust_density  = 0.25
    sky.ozone_density = 1.0
    bg.inputs['Strength'].default_value = 1.4
    nt.links.new(sky.outputs['Color'], bg.inputs['Color'])
    nt.links.new(bg.outputs['Background'], out.inputs['Surface'])

# ═══════════════════════════════════════════════════════════════════════
#  CAMERAS  (calibrated around building size)
# ═══════════════════════════════════════════════════════════════════════

def build_cameras(bw, bd, bh):
    scene = bpy.context.scene
    hw = bw / 2; hd = bd / 2

    # Aerial — 45° diagonal, wide enough to show full block
    dist_a = max(bw, bd) * 3.2
    h_a    = dist_a * 0.75
    bpy.ops.object.camera_add(location=(dist_a*0.55, -dist_a, h_a))
    ca = bpy.context.active_object; ca.name='Cam_Aerial'
    ca.rotation_euler = (math.radians(48), 0, math.radians(32))
    ca.data.lens = 32
    scene.camera = ca

    # Front 3/4 — classic courthouse elevation angle
    dist_f = max(bw, bd) * 2.0
    bpy.ops.object.camera_add(location=(bw*0.25, -(hd + dist_f), bh * 0.55))
    cf = bpy.context.active_object; cf.name='Cam_Front'
    cf.rotation_euler = (math.radians(76), 0, math.radians(8))
    cf.data.lens = 50
    cf.data.dof.use_dof = True
    cf.data.dof.focus_distance = dist_f + hd
    cf.data.dof.aperture_fstop = 8.0

    # Street level — low dramatic view from front steps approach
    bpy.ops.object.camera_add(location=(0, -(hd + dist_f * 0.65), 1.65))
    cp = bpy.context.active_object; cp.name='Cam_Street'
    cp.rotation_euler = (math.radians(86), 0, 0)
    cp.data.lens = 24
    cp.data.dof.use_dof = True
    cp.data.dof.focus_distance = dist_f * 0.6 + hd
    cp.data.dof.aperture_fstop = 5.6

# ═══════════════════════════════════════════════════════════════════════
#  RENDER SETTINGS
# ═══════════════════════════════════════════════════════════════════════

def setup_render():
    scene = bpy.context.scene
    scene.render.engine = 'CYCLES'

    scene.cycles.use_adaptive_sampling = True
    scene.cycles.adaptive_threshold    = 0.01
    scene.cycles.adaptive_min_samples  = 32
    scene.cycles.samples               = 512
    scene.cycles.use_denoising         = True
    try: scene.cycles.denoiser         = 'OPENIMAGEDENOISE'
    except: pass

    scene.cycles.max_bounces           = 16
    scene.cycles.diffuse_bounces       = 5
    scene.cycles.glossy_bounces        = 6
    scene.cycles.transmission_bounces  = 12
    scene.cycles.volume_bounces        = 2

    scene.render.resolution_x = 2560
    scene.render.resolution_y = 1440
    scene.render.film_transparent = False

    scene.view_settings.view_transform = 'Filmic'
    scene.view_settings.look           = 'Medium High Contrast'
    scene.view_settings.exposure       = 0.12
    scene.view_settings.gamma          = 1.02

    # Compositor
    scene.use_nodes = True
    tree = scene.node_tree; tree.nodes.clear()

    rl   = tree.nodes.new('CompositorNodeRLayers');  rl.location   = (-600, 0)
    glr  = tree.nodes.new('CompositorNodeGlare');    glr.location  = (-320, 0)
    glr.glare_type = 'FOG_GLOW'; glr.quality = 'HIGH'
    glr.threshold  = 0.95;       glr.size    = 6

    lens = tree.nodes.new('CompositorNodeLensdist'); lens.location = (-40, 0)
    lens.inputs['Distort'].default_value    = -0.010
    lens.inputs['Dispersion'].default_value =  0.004

    ell  = tree.nodes.new('CompositorNodeEllipseMask'); ell.location  = (-40,-220)
    ell.width = 0.86; ell.height = 0.82
    blr  = tree.nodes.new('CompositorNodeBlur');        blr.location  = (180,-220)
    blr.size_x = 90; blr.size_y = 90; blr.use_relative = False
    vig  = tree.nodes.new('CompositorNodeMixRGB');      vig.location  = (380,-100)
    vig.blend_type = 'MULTIPLY'; vig.inputs['Fac'].default_value = 0.55

    comp = tree.nodes.new('CompositorNodeComposite');   comp.location = (620, 0)

    nt = tree
    nt.links.new(rl.outputs['Image'],   glr.inputs['Image'])
    nt.links.new(glr.outputs['Image'],  lens.inputs['Image'])
    nt.links.new(lens.outputs['Image'], vig.inputs['Color1'])
    nt.links.new(ell.outputs['Mask'],   blr.inputs['Image'])
    nt.links.new(blr.outputs['Image'],  vig.inputs['Color2'])
    nt.links.new(vig.outputs['Color'],  comp.inputs['Image'])

# ═══════════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════════

def main():
    print("\n╔══════════════════════════════════════════════════════════╗")
    print("║  Nolan County Courthouse — Exterior Scene Setup         ║")
    print("║  Auto-imports GLB + builds full exterior environment    ║")
    print("╚══════════════════════════════════════════════════════════╝\n")

    clear_scene()

    print("  [MAT] Building material palette...")
    build_all_materials()

    C_GND = col("Ground_Roads")
    C_BLD = col("Courthouse")
    C_DET = col("Details")
    C_NAT = col("Nature")
    C_INF = col("Infrastructure")

    # ── Import the real courthouse mesh ────────────────────────────
    print("  [1/9]  Importing GLB mesh...")
    bw, bd, bh = import_courthouse(C_BLD)

    # ── Add entry portico + steps on top of imported mesh ──────────
    print("  [2/9]  Entry steps + columns + flag poles...")
    build_entry_steps(C_BLD, bw, bd)

    # ── Ground, plaza, roads ───────────────────────────────────────
    print("  [3/9]  Ground, lawn, plaza, sidewalks, roads...")
    build_ground(C_GND, bw, bd)
    build_parking_lines(C_INF, bw, bd)

    # ── Trees ──────────────────────────────────────────────────────
    print("  [4/9]  Trees (lawn, street, perimeter)...")
    build_trees(C_NAT, bw, bd)

    # ── Lamp posts ─────────────────────────────────────────────────
    print("  [5/9]  Lamp posts...")
    build_lamps(C_INF, bw, bd)

    # ── Cars ───────────────────────────────────────────────────────
    print("  [6/9]  Parking lot cars...")
    build_cars(C_INF, bw, bd)

    # ── People + street furniture ──────────────────────────────────
    print("  [7/9]  People, benches, monument...")
    build_people(C_DET, bw, bd)
    build_street_furniture(C_DET, bw, bd)

    # ── Lighting + sky ─────────────────────────────────────────────
    print("  [8/9]  Lighting + Nishita sky...")
    build_lighting()
    build_world()

    # ── Cameras + render ───────────────────────────────────────────
    print("  [9/9]  Cameras + render settings...")
    build_cameras(bw, bd, bh)
    setup_render()

    n_obj = len(list(bpy.data.objects))
    n_mat = len(list(bpy.data.materials))
    print(f"\n  ✓  Objects   : {n_obj}")
    print(f"  ✓  Materials : {n_mat}")
    print(f"  ✓  Building  : {bw:.1f}m × {bd:.1f}m × {bh:.1f}m")
    print("""
  CAMERAS:
    Cam_Aerial  → F12            (45° aerial — full city block)
    Cam_Front   → Ctrl+Numpad0   (front 3/4 elevation)
    Cam_Street  → Ctrl+Numpad0   (street-level dramatic)

  TIPS:
    • GPU: Edit > Preferences > System > CUDA / OptiX
    • If mesh imports at wrong scale, adjust TARGET_H in import_courthouse()
    • Entry columns are procedural — disable build_entry_steps() if GLB
      already includes them
    • All exterior mats use MAT_Stone / MAT_Grass — tweak colours freely
""")

main()
