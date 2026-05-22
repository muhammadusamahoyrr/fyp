"""
╔══════════════════════════════════════════════════════════════════════════╗
║  ATTORNEY.AI — Supreme Court of Pakistan (Kenzō Tange, 1993)           ║
║  Blender Script  v6  ·  Full Complex Reconstruction                     ║
║  Compatible: Blender 3.3 LTS → 4.x                                     ║
╚══════════════════════════════════════════════════════════════════════════╝

CHANGES vs v5 (driven by 3-skill audit against court.png + arial.png):
  ✦ FIXED   tower base width  90m → 120m  (ratio to height now ~2.4×)
  ✦ FIXED   wings 2× bigger   46m → 96m wide, ±105m offset (not ±66m)
  ✦ ADDED   2 large compound blocks (L+R) visible in arial.png
  ✦ ADDED   colonnade corridors linking main block to compound blocks
  ✦ FIXED   spandrel bands thicker + projecting (bold, like reference)
  ✦ FIXED   forecourt plaza 150×100 (was 80×60), fountain grid rescaled
  ✦ ADDED   volumetric atmosphere scatter (aerial haze visible in arial)
  ✦ FIXED   MAT_White rough 0.22→0.18 (reference stone more polished)
  ✦ FIXED   MAT_Grass richer green (0.08,0.42,0.06)
  ✦ FIXED   MAT_TreeLeaf richer green (0.06,0.30,0.05)
  ✦ FIXED   Cam_Aerial pulled back to frame full 400m complex, lens=28
  ✦ FIXED   perimeter walls expanded to match new complex footprint
"""

import bpy
import bmesh
import math
import random
from mathutils import Vector

random.seed(7)
PI  = math.pi
TAU = PI * 2

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

def link(obj, collection):
    for c in list(obj.users_collection):
        c.objects.unlink(obj)
    collection.objects.link(obj)

def deselect():
    bpy.ops.object.select_all(action='DESELECT')

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

def _link(nt, a_out, b_in):
    nt.links.new(a_out, b_in)

def base_bsdf(nt):
    out  = nt.nodes.new('ShaderNodeOutputMaterial'); out.location  = (800, 0)
    bsdf = nt.nodes.new('ShaderNodeBsdfPrincipled'); bsdf.location = (400, 0)
    _link(nt, bsdf.outputs['BSDF'], out.inputs['Surface'])
    return bsdf, out

def mat_simple(name, base, metal=0.0, rough=0.5,
               emission=None, emit_str=0.0, alpha=1.0):
    if name in M: return M[name]
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree; nt.nodes.clear()
    bsdf, out = base_bsdf(nt)
    safe_input(bsdf, 'Base Color', (*base, 1.0))
    safe_input(bsdf, 'Metallic',   metal)
    safe_input(bsdf, 'Roughness',  rough)
    if alpha < 1.0:
        safe_input(bsdf, 'Alpha', alpha)
        try: m.blend_method = 'BLEND'
        except: pass
    if emission:
        safe_input(bsdf, 'Emission Color',    (*emission, 1.0))
        safe_input(bsdf, 'Emission',          (*emission, 1.0))
        safe_input(bsdf, 'Emission Strength', emit_str)
    M[name] = m; return m

def mat_glass_dark(name):
    if name in M: return M[name]
    m = bpy.data.materials.new(name); m.use_nodes = True
    nt = m.node_tree; nt.nodes.clear()
    out  = nt.nodes.new('ShaderNodeOutputMaterial'); out.location = (400, 0)
    gls  = nt.nodes.new('ShaderNodeBsdfGlass');      gls.location = (0, 0)
    gls.inputs['Color'].default_value     = (0.04, 0.06, 0.10, 1.0)
    gls.inputs['Roughness'].default_value = 0.03
    gls.inputs['IOR'].default_value       = 1.52
    _link(nt, gls.outputs['BSDF'], out.inputs['Surface'])
    try: m.blend_method = 'BLEND'
    except: pass
    M[name] = m; return m

def mat_plaza_clean(name):
    if name in M: return M[name]
    m = bpy.data.materials.new(name); m.use_nodes = True
    nt = m.node_tree; nt.nodes.clear()
    bsdf, out = base_bsdf(nt)
    tc = nt.nodes.new('ShaderNodeTexCoord'); tc.location = (-700, 0)
    mp = nt.nodes.new('ShaderNodeMapping');  mp.location = (-500, 0)
    mp.inputs['Scale'].default_value = (4, 4, 4)
    _link(nt, tc.outputs['Object'], mp.inputs['Vector'])
    wx = nt.nodes.new('ShaderNodeTexWave'); wx.location = (-300, 100)
    wx.wave_type = 'BANDS'; wx.bands_direction = 'X'
    wx.inputs['Scale'].default_value = 6.0
    wx.inputs['Distortion'].default_value = 0.05
    wy = nt.nodes.new('ShaderNodeTexWave'); wy.location = (-300, -100)
    wy.wave_type = 'BANDS'; wy.bands_direction = 'Y'
    wy.inputs['Scale'].default_value = 6.0
    wy.inputs['Distortion'].default_value = 0.05
    _link(nt, mp.outputs['Vector'], wx.inputs['Vector'])
    _link(nt, mp.outputs['Vector'], wy.inputs['Vector'])
    mx = nt.nodes.new('ShaderNodeMath'); mx.operation = 'MULTIPLY'; mx.location = (-80, 0)
    _link(nt, wx.outputs['Fac'], mx.inputs[0])
    _link(nt, wy.outputs['Fac'], mx.inputs[1])
    cr = nt.nodes.new('ShaderNodeValToRGB'); cr.location = (100, 0)
    cr.color_ramp.elements[0].color = (0.76, 0.74, 0.68, 1.0)
    el2 = cr.color_ramp.elements.new(0.12); el2.color = (0.90, 0.88, 0.82, 1.0)
    cr.color_ramp.elements[1].color = (0.92, 0.90, 0.86, 1.0)
    _link(nt, mx.outputs['Value'], cr.inputs['Fac'])
    _link(nt, cr.outputs['Color'], bsdf.inputs['Base Color'])
    safe_input(bsdf, 'Roughness', 0.26)
    safe_input(bsdf, 'Specular IOR Level', 0.55)
    safe_input(bsdf, 'Specular',           0.55)
    bmp = nt.nodes.new('ShaderNodeBump'); bmp.location = (300, -200)
    bmp.inputs['Strength'].default_value = 0.20
    _link(nt, mx.outputs['Value'], bmp.inputs['Height'])
    _link(nt, bmp.outputs['Normal'], bsdf.inputs['Normal'])
    M[name] = m; return m

def mat_water_proc(name):
    if name in M: return M[name]
    m = bpy.data.materials.new(name); m.use_nodes = True
    nt = m.node_tree; nt.nodes.clear()
    out = nt.nodes.new('ShaderNodeOutputMaterial'); out.location = (600, 0)
    gls = nt.nodes.new('ShaderNodeBsdfGlossy');     gls.location = (0, 100)
    trn = nt.nodes.new('ShaderNodeBsdfTransparent');trn.location = (0, -100)
    mix = nt.nodes.new('ShaderNodeMixShader');       mix.location = (300, 0)
    gls.inputs['Color'].default_value     = (0.20, 0.52, 0.80, 1.0)
    gls.inputs['Roughness'].default_value = 0.04
    mix.inputs['Fac'].default_value = 0.55
    _link(nt, gls.outputs['BSDF'], mix.inputs[1])
    _link(nt, trn.outputs['BSDF'], mix.inputs[2])
    _link(nt, mix.outputs['Shader'], out.inputs['Surface'])
    try: m.blend_method = 'BLEND'
    except: pass
    M[name] = m; return m

def build_all_materials():
    # v6: rough 0.22→0.18 on MAT_White — reference looks more polished
    mat_simple('MAT_White',    (0.95, 0.94, 0.90), rough=0.18)
    mat_simple('MAT_WhiteDk',  (0.88, 0.87, 0.84), rough=0.28)
    mat_simple('MAT_WhiteGy',  (0.80, 0.79, 0.77), rough=0.40)
    mat_plaza_clean('MAT_Plaza')
    mat_simple('MAT_Garden',   (0.72, 0.68, 0.58), rough=0.65)
    mat_simple('MAT_Road',     (0.12, 0.12, 0.12), rough=0.92)
    mat_simple('MAT_Parking',  (0.10, 0.10, 0.10), rough=0.95)
    mat_simple('MAT_ParkLine', (0.88, 0.88, 0.88), rough=0.90)
    mat_simple('MAT_Kerb',     (0.62, 0.61, 0.59), rough=0.55)
    mat_simple('MAT_Ground',   (0.28, 0.32, 0.18), rough=1.00)
    # v6: brighter grass + richer tree leaves to match reference
    mat_simple('MAT_Grass',    (0.08, 0.42, 0.06), rough=1.00)
    mat_simple('MAT_GrassDk',  (0.05, 0.24, 0.04), rough=1.00)
    mat_simple('MAT_TreeLeaf', (0.06, 0.30, 0.05), rough=1.00)
    mat_simple('MAT_TreeLeafDk',(0.04,0.20, 0.03), rough=1.00)
    mat_simple('MAT_TreeTrunk',(0.25, 0.14, 0.06), rough=1.00)
    mat_simple('MAT_Hedge',    (0.04, 0.24, 0.04), rough=1.00)
    mat_glass_dark('MAT_WinDark')
    mat_water_proc('MAT_Water')
    # v6: fountain spray — bright white emissive overlay
    mat_simple('MAT_FountainSpray',(0.95,0.97,1.00),
               emission=(0.95,0.97,1.0), emit_str=3.5)
    mat_simple('MAT_LampMetal',(0.22, 0.22, 0.24), metal=0.75, rough=0.28)
    mat_simple('MAT_LampGlow', (1.00, 0.96, 0.82),
               emission=(1.0, 0.96, 0.82), emit_str=12.0)
    mat_simple('MAT_FlagGreen',(0.00, 0.36, 0.10), rough=0.85)
    mat_simple('MAT_FlagWhite',(0.96, 0.96, 0.95), rough=0.85)
    mat_simple('MAT_CarWhite', (0.92, 0.91, 0.89), rough=0.25, metal=0.05)
    mat_simple('MAT_CarBlue',  (0.05, 0.10, 0.50), rough=0.28, metal=0.05)
    mat_simple('MAT_CarRed',   (0.60, 0.04, 0.04), rough=0.28, metal=0.05)
    mat_simple('MAT_CarSilver',(0.65, 0.65, 0.67), rough=0.20, metal=0.30)
    mat_simple('MAT_Person',   (0.10, 0.10, 0.14), rough=0.90)

def asgn(obj, mat_name):
    if mat_name not in M: return
    if obj.data.materials: obj.data.materials[0] = M[mat_name]
    else:                   obj.data.materials.append(M[mat_name])

# ═══════════════════════════════════════════════════════════════════════
#  PRIMITIVE BUILDERS
# ═══════════════════════════════════════════════════════════════════════

def BOX(name, loc, sx, sy, sz, collection, mat='MAT_White',
        rx=0, ry=0, rz=0, bevel=False, bw=0.04):
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=2.0)
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free()
    obj = bpy.data.objects.new(name, me)
    link(obj, collection)
    obj.location       = loc
    obj.scale          = (sx, sy, sz)
    obj.rotation_euler = (rx, ry, rz)
    asgn(obj, mat)
    if bevel: apply_bevel(obj, bw)
    return obj

def CYL(name, loc, r, h, collection, mat='MAT_White', verts=48, bevel=False):
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False,
                          segments=verts, radius1=r, radius2=r, depth=h)
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free()
    obj = bpy.data.objects.new(name, me)
    link(obj, collection)
    obj.location = loc
    asgn(obj, mat)
    if bevel: apply_bevel(obj, 0.02)
    return obj

def CONE_OBJ(name, loc, r1, r2, h, collection, mat='MAT_WhiteDk', verts=8):
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False,
                          segments=verts, radius1=r1, radius2=r2, depth=h)
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free()
    obj = bpy.data.objects.new(name, me)
    link(obj, collection)
    obj.location = loc
    asgn(obj, mat)
    return obj

def SPHERE(name, loc, r, collection, mat='MAT_Water'):
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=32, v_segments=16, radius=r)
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free()
    obj = bpy.data.objects.new(name, me)
    link(obj, collection)
    obj.location = loc
    asgn(obj, mat)
    return obj

def PLANE(name, loc, sx, sy, collection, mat='MAT_Grass', rz=0):
    bm = bmesh.new()
    bmesh.ops.create_grid(bm, x_segments=2, y_segments=2, size=1.0)
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free()
    obj = bpy.data.objects.new(name, me)
    link(obj, collection)
    obj.location       = loc
    obj.scale          = (sx, sy, 1)
    obj.rotation_euler = (0, 0, rz)
    asgn(obj, mat)
    return obj

# ═══════════════════════════════════════════════════════════════════════
#  ISLAMIC POINTED ARCH
# ═══════════════════════════════════════════════════════════════════════

def build_arch_clean(name, loc, width, height, thickness, depth,
                     collection, mat='MAT_WhiteDk', segs=40):
    bm = bmesh.new()
    hw = width / 2.0

    def arch_profile(w, h, n):
        r   = w * 0.65
        cx  = -w * 0.25
        pts = []
        for i in range(n + 1):
            t   = PI * i / (2 * n)
            ang = PI + t
            x   = cx + r * math.cos(ang)
            z   = r * math.sin(ang) + r * 0.3
            if z > h: z = h
            pts.append((x, z))
        return pts

    n  = segs // 2
    outer_w = hw * 2
    inner_w = hw * 1.55

    pts_outer = arch_profile(outer_w, height, n)
    pts_inner = arch_profile(inner_w, height * 0.92, n)

    full_outer = pts_outer + [(-x, z) for x, z in reversed(pts_outer[:-1])]
    full_inner = pts_inner + [(-x, z) for x, z in reversed(pts_inner[:-1])]

    ho = outer_w / 2; hi = inner_w / 2
    full_outer = [(-ho, 0)] + full_outer + [(ho, 0)]
    full_inner = [(-hi, 0.1)] + full_inner + [(hi, 0.1)]

    y_f = 0.0; y_b = depth
    fo = [bm.verts.new((x, y_f, z)) for x, z in full_outer]
    fi = [bm.verts.new((x, y_f, z)) for x, z in full_inner]
    bo = [bm.verts.new((x, y_b, z)) for x, z in full_outer]
    bi = [bm.verts.new((x, y_b, z)) for x, z in full_inner]
    bm.verts.ensure_lookup_table()

    N = len(full_outer)
    def face4(a, b, c, d):
        try: bm.faces.new([a, b, c, d])
        except: pass

    for i in range(N - 1):
        face4(fo[i], fo[i+1], fi[i+1], fi[i])
        face4(fo[i], bo[i], bo[i+1], fo[i+1])
        face4(bi[i], fi[i], fi[i+1], bi[i+1])
        face4(bo[i], bo[i+1], bi[i+1], bi[i])

    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=0.005)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free()
    obj = bpy.data.objects.new(name, me)
    link(obj, collection)
    obj.location = loc
    asgn(obj, mat)
    return obj

# ═══════════════════════════════════════════════════════════════════════
#  STEPPED PODIUM STAIRCASE
# ═══════════════════════════════════════════════════════════════════════

def build_podium(C_BLD, cx=0, cy_front=-35.0, total_w=120, steps=5,
                 riser=1.20, tread=3.50):
    for s in range(steps):
        sw = total_w / 2 - s * 2.5
        sy_half = (steps - s) * tread / 2
        sz = riser / 2
        z_ctr = (s + 0.5) * riser
        y_ctr = cy_front + (steps - s) * tread
        BOX(f'Pod_Step{s}',
            (cx, y_ctr, z_ctr),
            sw, sy_half, sz,
            C_BLD, 'MAT_White', bevel=True, bw=0.06)
        BOX(f'Pod_Cop{s}',
            (cx, y_ctr - sy_half + 0.15, z_ctr + sz + 0.12),
            sw, 0.15, 0.12,
            C_BLD, 'MAT_WhiteDk')

# ═══════════════════════════════════════════════════════════════════════
#  MAIN CENTRAL BLOCK — v6: wider tiers calibrated to 120m base / 51m h
# ═══════════════════════════════════════════════════════════════════════

def build_main_tower(C_BLD):
    cx, cy = 0.0, 10.0

    # v6 tier dimensions — Tier1 now 120×70m (was 90×55m)
    tiers = [
        # (sx,  sy,   sz,   z_ctr,  label)
        (60.0, 35.0, 7.0,  13.0, 'T1'),   # 120 × 70 × 14 m
        (43.0, 27.0, 6.5,  26.5, 'T2'),   #  86 × 54 × 13 m
        (28.0, 18.0, 5.5,  38.0, 'T3'),   #  56 × 36 × 11 m
        (18.0, 12.0, 4.5,  47.5, 'T4'),   #  36 × 24 ×  9 m
    ]
    for sx, sy, sz, zc, tag in tiers:
        BOX(f'Blk_{tag}', (cx, cy, zc), sx, sy, sz,
            C_BLD, 'MAT_White', bevel=True, bw=0.08)
        BOX(f'Cop_{tag}', (cx, cy, zc + sz + 0.22),
            sx + 0.5, sy + 0.5, 0.28,
            C_BLD, 'MAT_WhiteDk')
        # v6: thicker, projecting spandrel bands — reads boldly in reference
        BOX(f'Spnd_{tag}', (cx, cy, zc - sz + 0.80),
            sx + 0.8, sy + 0.8, 0.45,
            C_BLD, 'MAT_WhiteDk', bevel=True, bw=0.06)
        BOX(f'SpndSub_{tag}', (cx, cy, zc - sz + 0.28),
            sx + 0.4, sy + 0.4, 0.22,
            C_BLD, 'MAT_WhiteDk')

    # Portal on front face of Tier 1 — y_face = cy - sy_T1 = 10-35 = -25
    portal_y = cy - 35.0   # = -25
    portal_z = 6.0
    arch_w   = 16.0
    arch_h   = 22.0

    build_arch_clean('Portal_Arch',
                     (cx - arch_w / 2, portal_y, portal_z),
                     arch_w, arch_h, 1.0, 3.0,
                     C_BLD, 'MAT_WhiteDk', segs=48)

    BOX('Portal_Glass',
        (cx, portal_y - 1.4, portal_z + arch_h * 0.45),
        arch_w / 2 - 0.8, 0.25, arch_h * 0.44,
        C_BLD, 'MAT_WinDark')

    for sx_pil in [-1, 1]:
        px = cx + sx_pil * (arch_w / 2 + 3.2)
        BOX(f'Portal_Pil{sx_pil}',
            (px, portal_y - 0.6, portal_z + arch_h * 0.5),
            2.2, 0.9, arch_h * 0.5,
            C_BLD, 'MAT_White', bevel=True, bw=0.05)

    # Window grids on Tier 1 front face (flanking arch)
    win_z_base = portal_z + 1.5
    for side in [-1, 1]:
        x_start = side * (arch_w / 2 + 6.0)
        for col_i in range(4):
            for row_i in range(2):
                wx = x_start + side * col_i * 5.2
                wz = win_z_base + row_i * 5.5
                BOX(f'Win_T1F_{side}_{col_i}_{row_i}',
                    (wx, portal_y - 0.18, wz),
                    1.4, 0.22, 2.2,
                    C_BLD, 'MAT_WinDark')
                BOX(f'WFr_T1F_{side}_{col_i}_{row_i}',
                    (wx, portal_y - 0.08, wz),
                    1.6, 0.15, 2.4,
                    C_BLD, 'MAT_WhiteDk')

    # Windows on Tier 2, 3, 4 front faces
    for t_i, (sx, sy, sz, zc, tag) in enumerate(tiers[1:], 1):
        fy = cy - sy - 0.05
        win_rows = max(1, int(sz * 2 / 4.5))
        win_cols = max(2, int(sx * 2 / 5.5))
        for ri in range(win_rows):
            for ci in range(win_cols):
                wx = cx - sx + 3.0 + ci * (sx * 2 - 6.0) / max(win_cols - 1, 1)
                wz = zc - sz + 2.0 + ri * 4.0
                BOX(f'Win_{tag}_{ri}_{ci}',
                    (wx, fy - 0.18, wz),
                    1.2, 0.20, 1.9,
                    C_BLD, 'MAT_WinDark')

    # Flagpole
    flag_z = 47.5 + 4.5
    CYL('Flag_Pole',   (cx, cy, flag_z + 9.0), 0.18, 18.0, C_BLD, 'MAT_LampMetal')
    SPHERE('Flag_Ball',(cx, cy, flag_z + 18.2), 0.40, C_BLD, 'MAT_LampMetal')
    BOX('Flag_Green',  (cx + 3.6, cy, flag_z + 15.5), 3.6, 0.04, 1.5, C_BLD, 'MAT_FlagGreen')
    BOX('Flag_White',  (cx + 3.6, cy, flag_z + 17.1), 3.6, 0.04, 0.42, C_BLD, 'MAT_FlagWhite')

    # Podium staircase — v6: wider (120m) and moved forward to portal_y
    build_podium(C_BLD, cx=cx, cy_front=portal_y,
                 total_w=120, steps=5, riser=1.20, tread=3.50)

# ═══════════════════════════════════════════════════════════════════════
#  WINGS — v6: 2× bigger, further out, to match aerial image
# ═══════════════════════════════════════════════════════════════════════

def build_wing(C_BLD, side=1):
    s   = side
    tag = 'L' if s == -1 else 'R'
    cx  = s * 105.0   # v6: ±105m (was ±66m)
    cy  = 10.0
    wx  = 48.0        # v6: 96m wide (was 46m)
    wy  = 27.5        # v6: 55m deep (was 30m)
    wz  = 12.0        # v6: 24m tall (was 22m)
    z_c = wz

    BOX(f'Wing_{tag}',  (cx, cy, z_c),        wx, wy, wz,   C_BLD, 'MAT_White', bevel=True, bw=0.08)
    BOX(f'WCop_{tag}',  (cx, cy, z_c+wz+0.28),wx+0.5,wy+0.5,0.28, C_BLD, 'MAT_WhiteDk')
    BOX(f'WSpnd_{tag}', (cx, cy, 1.0),         wx+0.3,wy+0.3,0.45, C_BLD, 'MAT_WhiteDk')

    # Connector link to main tower
    BOX(f'WLink_{tag}',
        (s * 62.0, cy, 9.0),
        3.0, wy, 9.0,
        C_BLD, 'MAT_White', bevel=True, bw=0.06)

    # Flat rectangular pilasters on front face
    front_y = cy - wy
    n_pil   = 9        # v6: wider wing needs more pilasters
    pil_w   = 1.3
    pil_proj= 0.60

    for i in range(n_pil):
        px = cx - wx + 4.0 + i * (wx * 2 - 8.0) / (n_pil - 1)
        BOX(f'WPil_{tag}_{i}',
            (px, front_y - pil_proj, z_c),
            pil_w, pil_proj, wz,
            C_BLD, 'MAT_White', bevel=True, bw=0.04)
        BOX(f'WCap_{tag}_{i}',
            (px, front_y - pil_proj - 0.08, z_c + wz - 0.9),
            pil_w + 0.2, pil_proj + 0.08, 0.60,
            C_BLD, 'MAT_WhiteDk')

    BOX(f'WEnta_{tag}',
        (cx, front_y - 0.38, z_c + wz - 0.28),
        wx + 0.3, 0.65, 0.28,
        C_BLD, 'MAT_WhiteDk')

    # Window bays
    for i in range(n_pil - 1):
        px = cx - wx + 4.0 + (i + 0.5) * (wx * 2 - 8.0) / (n_pil - 1)
        for row in range(3):
            wz_pos = 2.5 + row * 6.0
            BOX(f'WWin_{tag}_{i}_{row}',
                (px, front_y - 0.2, wz_pos),
                1.9, 0.22, 2.4,
                C_BLD, 'MAT_WinDark')
            BOX(f'WWFr_{tag}_{i}_{row}',
                (px, front_y - 0.10, wz_pos),
                2.1, 0.15, 2.6,
                C_BLD, 'MAT_WhiteDk')

    # Side arch entrance on outer face
    outer_x = s * (cx + wx)
    build_arch_clean(f'WArc_{tag}',
                     (outer_x - s * 6, cy - 8, 0),
                     12, 15, 0.7, 2.2,
                     C_BLD, 'MAT_WhiteDk', segs=36)

# ═══════════════════════════════════════════════════════════════════════
#  COMPOUND BLOCKS — v6 NEW: large rectangular court buildings L+R
#  visible in arial.png as huge massing equal to the main tower
# ═══════════════════════════════════════════════════════════════════════

def build_compound_blocks(C_BLD):
    for s, tag in [(-1, 'L'), (1, 'R')]:
        cx = s * 168.0    # far out — beyond wings
        cy = 25.0

        # Main large block: ~100m × 80m × 16m
        BOX(f'Cmp_{tag}',      (cx, cy, 8.0),  50, 40, 8.0,   C_BLD, 'MAT_White', bevel=True, bw=0.08)
        BOX(f'CmpCop_{tag}',   (cx, cy, 16.4), 50.5, 40.5, 0.28, C_BLD, 'MAT_WhiteDk')
        # v6: spandrel band at mid-floor
        BOX(f'CmpSpnd_{tag}',  (cx, cy,  8.3), 50.4, 40.4, 0.40, C_BLD, 'MAT_WhiteDk')

        # Inner sub-block (secondary mass, rear)
        BOX(f'CmpSub_{tag}',   (cx, cy+32, 5.5), 38, 16, 5.5, C_BLD, 'MAT_White', bevel=True, bw=0.06)
        BOX(f'CmpSubCop_{tag}',(cx, cy+32,11.2), 38.4,16.4,0.22,C_BLD,'MAT_WhiteDk')

        # Front colonnade — 10 pilasters across front face
        front_y = cy - 40
        for i in range(10):
            px = cx - 45 + i * 10
            BOX(f'CmpPil_{tag}_{i}',
                (px, front_y - 0.7, 7.5),
                1.4, 0.7, 7.5,
                C_BLD, 'MAT_White', bevel=True, bw=0.04)
        # Entablature across colonnade
        BOX(f'CmpEnta_{tag}', (cx, front_y - 0.45, 15.4), 50, 0.7, 0.55, C_BLD, 'MAT_WhiteDk')

        # Windows on compound block front
        for i in range(8):
            px = cx - 42 + i * 12
            for row in range(2):
                BOX(f'CmpWin_{tag}_{i}_{row}',
                    (px, front_y - 0.2, 2.2 + row * 6.0),
                    2.0, 0.22, 2.8,
                    C_BLD, 'MAT_WinDark')

        # Side entry arch on inner face (faces toward main building)
        inner_x = s * (cx - s * 50)
        build_arch_clean(f'CmpArc_{tag}',
                         (inner_x - s * 7, cy - 8, 0),
                         14, 14, 0.8, 2.5,
                         C_BLD, 'MAT_WhiteDk', segs=36)

# ═══════════════════════════════════════════════════════════════════════
#  COLONNADE CORRIDORS — v6 NEW: link main block to compound blocks
#  visible as long white linear elements in arial.png
# ═══════════════════════════════════════════════════════════════════════

def build_corridors(C_BLD):
    for s, tag in [(-1, 'L'), (1, 'R')]:
        # Corridor centerline: x from ±60 (wing edge) to ±118 (compound inner face)
        # Y: same as building cy=10, depth ~30m
        cx_corr = s * 88.0   # midpoint between wing and compound
        cy_corr = 10.0

        # Roof slab
        BOX(f'Corr_{tag}',    (cx_corr, cy_corr, 8.8),  14, 32, 0.7,  C_BLD, 'MAT_WhiteDk')
        # Floor slab
        BOX(f'CorrFlr_{tag}', (cx_corr, cy_corr, 0.2),  14, 32, 0.2,  C_BLD, 'MAT_WhiteDk')
        # Back wall
        BOX(f'CorrWall_{tag}',(cx_corr, cy_corr + 32, 4.5), 14, 0.6, 4.5, C_BLD, 'MAT_White')

        # Colonnade columns along open front face
        n_cols = 8
        for i in range(n_cols):
            py = cy_corr - 14 + i * 4.0
            BOX(f'CorrPil_{tag}_{i}',
                (cx_corr, py, 4.2),
                0.9, 0.9, 4.2,
                C_BLD, 'MAT_White', bevel=True, bw=0.04)

        # Entablature along corridor front
        BOX(f'CorrEnta_{tag}', (cx_corr, cy_corr - 14, 8.65),
            14, 0.6, 0.55,
            C_BLD, 'MAT_WhiteDk')

# ═══════════════════════════════════════════════════════════════════════
#  REAR BLOCKS
# ═══════════════════════════════════════════════════════════════════════

def build_rear(C_BLD):
    cx, cy_tower = 0.0, 10.0

    BOX('JudgeCh_Main', ( 80, cy_tower, 9.0),  22, 24, 9.0,  C_BLD, 'MAT_White', bevel=True, bw=0.07)
    BOX('JudgeCh_Cop',  ( 80, cy_tower, 18.4), 22.4,24.4,0.22,C_BLD,'MAT_WhiteDk')
    BOX('JudgeCh_Sub',  ( 80, cy_tower+24,6.5),18,  8, 6.5,  C_BLD, 'MAT_White', bevel=True)

    for s, tag in [(-1, 'L'), (1, 'R')]:
        px = s * 40
        BOX(f'Admin_{tag}',    (px, 65, 8.0),  20, 22, 8.0,  C_BLD, 'MAT_White', bevel=True, bw=0.06)
        BOX(f'AdminCop_{tag}', (px, 65, 16.4), 20.4,22.4,0.22,C_BLD,'MAT_WhiteDk')
        BOX(f'AdminSub_{tag}', (px, 80, 6.0),  15, 10, 6.0,  C_BLD, 'MAT_White', bevel=True)

    BOX('Admin_Ctr',    (0, 50, 5.5),  22, 9, 5.5, C_BLD, 'MAT_White', bevel=True)
    BOX('Admin_CtrCop', (0, 50, 11.2), 22.4,9.4,0.22,C_BLD,'MAT_WhiteDk')

# ═══════════════════════════════════════════════════════════════════════
#  ENTRY GATE + BOUNDARY WALL — v6: expanded to ±195m to frame complex
# ═══════════════════════════════════════════════════════════════════════

def build_gate(C_BLD):
    for s in [-1, 1]:
        BOX(f'GT_{s}',    (s*14, -165, 8.0), 5.0,5.0,8.0, C_BLD,'MAT_White',bevel=True)
        BOX(f'GT_Cop{s}', (s*14, -165,16.4), 5.4,5.4,0.22,C_BLD,'MAT_WhiteDk')
        CONE_OBJ(f'GT_Top{s}',(s*14,-165,18.0),4.5,0.5,3.5,C_BLD,'MAT_WhiteDk',verts=4)

    build_arch_clean('Gate_Arch', (-8, -165, 0), 16, 14, 0.8, 5.0, C_BLD, 'MAT_WhiteDk', segs=32)
    BOX('Gate_Span', (0, -165, 13.5), 8, 5.0, 0.9, C_BLD, 'MAT_WhiteDk')

    for i in range(9):
        BOX(f'GBar_L{i}', (-10+i*1.1, -165, 3.8), 0.09,0.09,3.8, C_BLD,'MAT_LampMetal')
    BOX('GRail', (0,-165,7.4), 9,0.12,0.12, C_BLD,'MAT_LampMetal')

    BOX('GPost',    (-28,-165,2.4), 3.0,3.0,2.4, C_BLD,'MAT_White',bevel=True)
    BOX('GPost_Rf', (-28,-165,5.0), 3.4,3.4,0.4, C_BLD,'MAT_WhiteDk')

    BOX('GWall_L', (-72,-165,2.2), 36,0.6,2.2, C_BLD,'MAT_White')
    BOX('GWall_R', ( 72,-165,2.2), 36,0.6,2.2, C_BLD,'MAT_White')
    for i in range(7):
        for s2 in [-1,1]:
            BOX(f'GWPil_{s2}_{i}',(s2*(-28+i*8),-165,2.6),1.0,1.0,2.6,C_BLD,'MAT_WhiteDk')

    # v6: perimeter walls at ±195m to enclose full complex including compound blocks
    BOX('BW_L',  (-195, 30, 2.2), 0.6, 195, 2.2, C_BLD,'MAT_White')
    BOX('BW_R',  ( 195, 30, 2.2), 0.6, 195, 2.2, C_BLD,'MAT_White')
    BOX('BW_Rr', (   0, 120, 2.2), 195, 0.6, 2.2, C_BLD,'MAT_White')
    for i in range(18):
        y = -80 + i * 12
        for s3 in [-1,1]:
            BOX(f'BWPil_{s3}_{i}',(s3*195,y,2.8),1.4,1.4,2.8,C_BLD,'MAT_WhiteDk')

# ═══════════════════════════════════════════════════════════════════════
#  GROUND — v6: larger plaza (150×100), extended roads
# ═══════════════════════════════════════════════════════════════════════

def build_ground(C_GND):
    PLANE('Gnd_Base',  (0,   0,-0.12), 420, 420, C_GND,'MAT_Ground')
    # v6: forecourt plaza 150×100 (was 80×60)
    PLANE('Plaza_Main',(0, -60, 0.02), 150, 100, C_GND,'MAT_Plaza')
    PLANE('Plaza_Fore',(0,-135, 0.02), 140,  50, C_GND,'MAT_Plaza')
    PLANE('Path_Axis', (0, -95, 0.02),  10,  25, C_GND,'MAT_Plaza')
    PLANE('Plaza_Circ',(0, -90, 0.025), 30,  30, C_GND,'MAT_Plaza')
    # Side plaza paving at compound blocks
    for s, tag in [(-1,'L'),(1,'R')]:
        PLANE(f'CmpPlaza_{tag}', (s*168, -10, 0.02), 55, 70, C_GND,'MAT_Plaza')
        PLANE(f'CorrPlaza_{tag}',(s* 88,  10, 0.02), 16, 34, C_GND,'MAT_Plaza')
    # Roads
    PLANE('Rd_Front', (0, -190, 0.02), 200, 24, C_GND,'MAT_Road')
    PLANE('Rd_L',     (-210, 0, 0.02),  18, 200, C_GND,'MAT_Road')
    PLANE('Rd_R',     ( 210, 0, 0.02),  18, 200, C_GND,'MAT_Road')
    PLANE('Rd_Rear',  (0,  130, 0.02), 200, 18, C_GND,'MAT_Road')
    BOX('Kerb_FL', (-60,-120,0.14), 30,0.28,0.14, C_GND,'MAT_Kerb')
    BOX('Kerb_FR', ( 60,-120,0.14), 30,0.28,0.14, C_GND,'MAT_Kerb')

def build_grass(C_GND):
    PLANE('Gr_L',   (-100, 20, 0.01),  38, 140, C_GND,'MAT_Grass')
    PLANE('Gr_R',   ( 100, 20, 0.01),  38, 140, C_GND,'MAT_Grass')
    PLANE('Gr_PL',  (-62, -10, 0.01),  10,  80, C_GND,'MAT_Grass')
    PLANE('Gr_PR',  ( 62, -10, 0.01),  10,  80, C_GND,'MAT_Grass')
    PLANE('Gr_Rear',(  0,  90, 0.01), 140,  60, C_GND,'MAT_Grass')
    PLANE('Gr_FL',  (-55, -80, 0.01),  22,  28, C_GND,'MAT_Grass')
    PLANE('Gr_FR',  ( 55, -80, 0.01),  22,  28, C_GND,'MAT_Grass')
    # Hedge rows flanking plaza approach
    for i in range(14):
        y = -110 + i * 10
        BOX(f'Hdg_L{i}', (-50, y, 0.9), 0.9, 4.0, 0.9, C_GND,'MAT_Hedge')
        BOX(f'Hdg_R{i}', ( 50, y, 0.9), 0.9, 4.0, 0.9, C_GND,'MAT_Hedge')

def build_garden(C_GND):
    PLANE('GPth_Axis', (0,  60, 0.02),  5, 40, C_GND,'MAT_Plaza')
    PLANE('GPth_X1',   (0,  72, 0.02), 70,  5, C_GND,'MAT_Plaza')
    PLANE('GPth_X2',   (0,  95, 0.02), 60,  4, C_GND,'MAT_Plaza')
    PLANE('GPth_SL',  (-32, 75, 0.02),  4, 38, C_GND,'MAT_Plaza')
    PLANE('GPth_SR',  ( 32, 75, 0.02),  4, 38, C_GND,'MAT_Plaza')
    for i in range(4):
        for j in range(4):
            bx = -18 + i * 12; by = 60 + j * 14
            PLANE(f'Bed_{i}_{j}', (bx, by, 0.02), 4.0, 5.0, C_GND,'MAT_GrassDk')
    PLANE('Pond_L', (-26,100,0.02), 12,  8, C_GND,'MAT_Water')
    PLANE('Pond_R', ( 26,100,0.02), 12,  8, C_GND,'MAT_Water')
    CYL('Pond_FntL',(-26,100,0.9), 0.22,2.2, C_GND,'MAT_White')
    CYL('Pond_FntR',( 26,100,0.9), 0.22,2.2, C_GND,'MAT_White')

# ═══════════════════════════════════════════════════════════════════════
#  FOUNTAIN SYSTEM — v6: brighter spray, larger grid matching arial.png
# ═══════════════════════════════════════════════════════════════════════

def fountain(prefix, cx, cy, collection, scale=1.0):
    z = 0.04; s = scale
    CYL(f'{prefix}_OBase', (cx,cy,z+0.08*s), 5.2*s,0.16*s, collection,'MAT_White', verts=8)
    CYL(f'{prefix}_OWall', (cx,cy,z+0.50*s), 5.0*s,0.80*s, collection,'MAT_White', verts=8)
    # v6: bright white emissive water surface
    CYL(f'{prefix}_OWater',(cx,cy,z+0.88*s), 4.8*s,0.06,   collection,'MAT_FountainSpray', verts=8)
    CYL(f'{prefix}_Shaft', (cx,cy,z+2.8*s),  0.24*s,3.8*s, collection,'MAT_White')
    SPHERE(f'{prefix}_Sp', (cx,cy,z+4.8*s),  0.50*s,       collection,'MAT_FountainSpray')
    for ang in range(0,360,60):
        rad=math.radians(ang)
        jx=cx+math.cos(rad)*3.2*s; jy=cy+math.sin(rad)*3.2*s
        SPHERE(f'{prefix}_J{ang}',(jx,jy,z+1.6*s),0.18*s,collection,'MAT_FountainSpray')

def build_fountains(C_DET):
    # v6: 7-fountain grid matching arial.png symmetrical layout
    fountain('F_Main',   0,  -90,  C_DET, scale=2.2)   # large central
    fountain('F_L1',   -42,  -75,  C_DET, scale=1.2)
    fountain('F_R1',    42,  -75,  C_DET, scale=1.2)
    fountain('F_L2',   -42, -105,  C_DET, scale=1.2)
    fountain('F_R2',    42, -105,  C_DET, scale=1.2)
    fountain('F_L3',   -80,  -90,  C_DET, scale=0.80)
    fountain('F_R3',    80,  -90,  C_DET, scale=0.80)

# ═══════════════════════════════════════════════════════════════════════
#  TREES
# ═══════════════════════════════════════════════════════════════════════

def TREE(prefix, x, y, collection, h=5.0, cr=1.8, mat='MAT_TreeLeaf'):
    CYL(f'{prefix}_T',   (x, y, h*0.35), 0.20, h*0.72, collection,'MAT_TreeTrunk')
    SPHERE(f'{prefix}_C0',(x,        y,        h*0.88), cr,        collection, mat)
    SPHERE(f'{prefix}_C1',(x+cr*0.5, y+cr*0.2, h*0.80), cr*0.72,  collection, mat)
    SPHERE(f'{prefix}_C2',(x-cr*0.4, y-cr*0.3, h*0.78), cr*0.65,  collection, mat)

def build_trees(C_NAT):
    # Central avenue (wider, matching larger plaza)
    for i in range(18):
        y = -180 + i * 8
        TREE(f'Av_L{i}', -12, y, C_NAT, h=6.5, cr=2.2)
        TREE(f'Av_R{i}',  12, y, C_NAT, h=6.5, cr=2.2)
    # Plaza perimeter trees
    for i in range(12):
        TREE(f'Plz_L{i}', -60, -130+i*12, C_NAT, h=5.5, cr=2.0)
        TREE(f'Plz_R{i}',  60, -130+i*12, C_NAT, h=5.5, cr=2.0)
    # Compound block surrounds
    for s, tag in [(-1,'L'),(1,'R')]:
        for i in range(8):
            TREE(f'CmpT_{tag}_{i}', s*168, -55+i*14, C_NAT, h=6.0, cr=2.2)
        for i in range(5):
            TREE(f'CmpTB_{tag}_{i}', s*(145+i*8), 55, C_NAT, h=6.5, cr=2.4)
    # Side garden rows
    for row in range(4):
        for i in range(14):
            TREE(f'SL_{row}_{i}', -90-row*14, -40+i*14, C_NAT,
                 h=7+row, cr=2.8+row*0.3, mat='MAT_TreeLeaf')
            TREE(f'SR_{row}_{i}',  90+row*14, -40+i*14, C_NAT,
                 h=7+row, cr=2.8+row*0.3, mat='MAT_TreeLeaf')
    # Rear formal garden trees
    for r in range(6):
        for c in range(9):
            TREE(f'RG_{r}_{c}', -40+c*10, 55+r*12, C_NAT,
                 h=6+random.uniform(0,2), cr=2.2+random.uniform(0,0.8))
    # Dense perimeter forest
    for i in range(42):
        TREE(f'Frst_{i}', random.uniform(-190,190), random.uniform(120,165),
             C_NAT, h=random.uniform(8,15), cr=random.uniform(3,6),
             mat='MAT_TreeLeafDk')

# ═══════════════════════════════════════════════════════════════════════
#  LAMP POSTS
# ═══════════════════════════════════════════════════════════════════════

def LAMP(prefix, x, y, collection):
    BOX(f'{prefix}_B',   (x,y,0.20),    0.5,0.5,0.20, collection,'MAT_LampMetal')
    CONE_OBJ(f'{prefix}_Sh',(x,y,6.2), 0.14,0.09,11.5,collection,'MAT_LampMetal',verts=16)
    BOX(f'{prefix}_Arm',  (x+0.9,y,11.8),0.9,0.07,0.07,collection,'MAT_LampMetal')
    BOX(f'{prefix}_ArmV', (x+1.8,y,11.4),0.07,0.07,0.38,collection,'MAT_LampMetal')
    CYL(f'{prefix}_Hous', (x+1.8,y,10.9),0.30,0.50,collection,'MAT_LampMetal',verts=8)
    SPHERE(f'{prefix}_Glo',(x+1.8,y,10.9),0.26,collection,'MAT_LampGlow')

def build_lamps(C_INF):
    for i in range(18):
        y = -180 + i * 10
        LAMP(f'Lp_L{i}', -16, y, C_INF)
        LAMP(f'Lp_R{i}',  16, y, C_INF)
    for i in range(8):
        LAMP(f'Lp_PL{i}', -42, -130+i*14, C_INF)
        LAMP(f'Lp_PR{i}',  42, -130+i*14, C_INF)

# ═══════════════════════════════════════════════════════════════════════
#  PARKING
# ═══════════════════════════════════════════════════════════════════════

CAR_MATS = ['MAT_CarWhite','MAT_CarBlue','MAT_CarRed','MAT_CarSilver']

def DETAILED_CAR(prefix, x, y, C):
    mat = random.choice(CAR_MATS)
    BOX(f'{prefix}_Bod',(x,y,0.52),1.05,2.25,0.52,C,mat)
    BOX(f'{prefix}_Cab',(x,y+0.15,1.14),0.90,1.35,0.38,C,mat)
    BOX(f'{prefix}_WS', (x,y-0.72,1.05),0.88,0.06,0.36,C,'MAT_WinDark')
    for wx2,wy2 in [(-0.6,-0.84),(0.6,-0.84),(-0.6,0.84),(0.6,0.84)]:
        CYL(f'{prefix}_Wh{wx2}{wy2}',(x+wx2,y+wy2,0.27),0.28,0.22,C,'MAT_LampMetal',verts=12)

def build_parking(C_INF):
    PLANE('Lot_L',(-130,-30,0.01),38,60,C_INF,'MAT_Parking')
    PLANE('Lot_R',( 130,-30,0.01),38,60,C_INF,'MAT_Parking')
    for row in range(10):
        for slot in range(9):
            lx = -145+slot*3.5; ly = -55+row*5.5
            BOX(f'PkLn_L{row}_{slot}',(lx,ly,0.015),1.1,0.05,0.01,C_INF,'MAT_ParkLine')
            DETAILED_CAR(f'Car_L{row}_{slot}',lx,ly,C_INF)
            rx =  100+slot*3.5
            BOX(f'PkLn_R{row}_{slot}',(rx,ly,0.015),1.1,0.05,0.01,C_INF,'MAT_ParkLine')
            DETAILED_CAR(f'Car_R{row}_{slot}',rx,ly,C_INF)

# ═══════════════════════════════════════════════════════════════════════
#  PEOPLE SILHOUETTES
# ═══════════════════════════════════════════════════════════════════════

def PERSON(name, x, y, collection):
    BOX(f'{name}_B', (x,y,0.90), 0.22,0.12,0.90, collection,'MAT_Person')
    SPHERE(f'{name}_H',(x,y,2.05),0.22,             collection,'MAT_Person')

def build_people(C_DET):
    positions = [
        (-10,-52),(-5,-50),(2,-55),(7,-52),(12,-48),
        (-14,-46),(0,-60),(15,-42),(-7,-60),(4,-48),
        (-20,-55),(18,-50),(-2,-70),(9,-72),(16,-65),
        (0,-78),(-11,-75),(22,-58),(-22,-48),(6,-82),
        (14,-88),(-6,-90),(24,-82),(-18,-78),(0,-92),
    ]
    for i, (px, py) in enumerate(positions):
        jx = px + random.uniform(-1.2, 1.2)
        jy = py + random.uniform(-1.2, 1.2)
        PERSON(f'P{i}', jx, jy, C_DET)

# ═══════════════════════════════════════════════════════════════════════
#  LIGHTING  (golden-hour matching arial.png)
# ═══════════════════════════════════════════════════════════════════════

def build_lighting():
    bpy.ops.object.light_add(type='SUN', location=(100,-150,90))
    sun = bpy.context.active_object; sun.name='Sun_Key'
    sun.data.energy = 7.5
    sun.data.color  = (1.0, 0.94, 0.80)
    sun.data.angle  = math.radians(0.8)
    sun.rotation_euler = (math.radians(38), math.radians(5), math.radians(-42))

    bpy.ops.object.light_add(type='AREA', location=(0,0,200))
    fill = bpy.context.active_object; fill.name='Sky_Fill'
    fill.data.energy = 550; fill.data.size = 420
    fill.data.color  = (0.62, 0.78, 1.0)

    bpy.ops.object.light_add(type='AREA', location=(-120,120,80))
    rim = bpy.context.active_object; rim.name='Rim_Light'
    rim.data.energy = 260; rim.data.size = 140
    rim.data.color  = (0.80, 0.90, 1.0)
    rim.rotation_euler = (math.radians(48),0,math.radians(132))

    bpy.ops.object.light_add(type='AREA', location=(0,-20,1))
    bnc = bpy.context.active_object; bnc.name='Ground_Bounce'
    bnc.data.energy = 180; bnc.data.size = 180
    bnc.data.color  = (1.0, 0.95, 0.82)
    bnc.rotation_euler = (math.radians(180),0,0)

# ═══════════════════════════════════════════════════════════════════════
#  WORLD — Nishita physical sky
# ═══════════════════════════════════════════════════════════════════════

def build_world():
    scene = bpy.context.scene
    world = bpy.data.worlds.new("JudicialWorld")
    scene.world = world; world.use_nodes = True
    nt = world.node_tree; nt.nodes.clear()
    out = nt.nodes.new('ShaderNodeOutputWorld'); out.location = (400,0)
    bg  = nt.nodes.new('ShaderNodeBackground');  bg.location  = (200,0)
    sky = nt.nodes.new('ShaderNodeTexSky');       sky.location = (-100,0)
    sky.sky_type      = 'NISHITA'
    sky.sun_elevation = math.radians(34)
    sky.sun_rotation  = math.radians(210)
    sky.air_density   = 1.0
    sky.dust_density  = 0.3
    sky.ozone_density = 1.0
    bg.inputs['Strength'].default_value = 1.5
    _link(nt, sky.outputs['Color'], bg.inputs['Color'])
    _link(nt, bg.outputs['Background'], out.inputs['Surface'])

# ═══════════════════════════════════════════════════════════════════════
#  VOLUMETRIC ATMOSPHERE — v6 NEW: aerial haze visible in arial.png
# ═══════════════════════════════════════════════════════════════════════

def build_atmosphere(C_BLD):
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=2.0)
    me = bpy.data.meshes.new('Atm_Vol'); bm.to_mesh(me); bm.free()
    obj = bpy.data.objects.new('Atm_Vol', me)
    link(obj, C_BLD)
    obj.scale    = (450, 450, 90)
    obj.location = (0, 0, 45)

    m = bpy.data.materials.new('MAT_Atm')
    m.use_nodes = True
    nt = m.node_tree; nt.nodes.clear()
    out = nt.nodes.new('ShaderNodeOutputMaterial'); out.location = (400, 0)
    vol = nt.nodes.new('ShaderNodeVolumeScatter');  vol.location = (0, 0)
    vol.inputs['Color'].default_value     = (0.84, 0.90, 0.98, 1.0)
    vol.inputs['Density'].default_value   = 0.0012
    vol.inputs['Anisotropy'].default_value= 0.3
    nt.links.new(vol.outputs['Volume'], out.inputs['Volume'])
    obj.data.materials.append(m)

# ═══════════════════════════════════════════════════════════════════════
#  CAMERAS — v6: Cam_Aerial pulled back to frame full ~400m complex
# ═══════════════════════════════════════════════════════════════════════

def build_cameras():
    scene = bpy.context.scene

    # v6 Aerial — pulled back to frame compound blocks, wider lens
    bpy.ops.object.camera_add(location=(200,-380,240))
    ca = bpy.context.active_object; ca.name='Cam_Aerial'
    ca.rotation_euler = (math.radians(50),0,math.radians(35))
    ca.data.lens = 28   # wider: 28mm to show full complex
    scene.camera = ca

    # Front 3/4 — matches court.png, adjusted for wider building
    bpy.ops.object.camera_add(location=(40,-210,45))
    cf = bpy.context.active_object; cf.name='Cam_Front'
    cf.rotation_euler = (math.radians(78),0,math.radians(10))
    cf.data.lens = 50
    cf.data.dof.use_dof = True
    cf.data.dof.focus_distance = 210
    cf.data.dof.aperture_fstop = 6.3

    # Plaza level — dramatic entrance low-angle
    bpy.ops.object.camera_add(location=(0,-120,4.5))
    cp = bpy.context.active_object; cp.name='Cam_Plaza'
    cp.rotation_euler = (math.radians(84),0,0)
    cp.data.lens = 28
    cp.data.dof.use_dof = True
    cp.data.dof.focus_distance = 115
    cp.data.dof.aperture_fstop = 8.0

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

    # Extra volume bounces for atmosphere scatter
    scene.cycles.max_bounces           = 16
    scene.cycles.diffuse_bounces       = 5
    scene.cycles.glossy_bounces        = 6
    scene.cycles.transmission_bounces  = 12
    scene.cycles.volume_bounces        = 4   # v6: +2 for atmosphere

    scene.render.resolution_x = 2560
    scene.render.resolution_y = 1440
    scene.render.film_transparent = False

    scene.view_settings.view_transform = 'Filmic'
    scene.view_settings.look           = 'High Contrast'
    scene.view_settings.exposure       = 0.18
    scene.view_settings.gamma          = 1.04

    scene.use_nodes = True
    tree = scene.node_tree; tree.nodes.clear()

    rl   = tree.nodes.new('CompositorNodeRLayers');  rl.location   = (-600,0)
    glr  = tree.nodes.new('CompositorNodeGlare');    glr.location  = (-320,0)
    glr.glare_type = 'FOG_GLOW'; glr.quality = 'HIGH'
    glr.threshold  = 0.92;       glr.size    = 7

    lens = tree.nodes.new('CompositorNodeLensdist'); lens.location = (-40,0)
    lens.inputs['Distort'].default_value    = -0.014
    lens.inputs['Dispersion'].default_value =  0.005

    ell  = tree.nodes.new('CompositorNodeEllipseMask'); ell.location  = (-40,-220)
    ell.width = 0.84; ell.height = 0.80
    blr  = tree.nodes.new('CompositorNodeBlur');        blr.location  = (180,-220)
    blr.size_x = 110; blr.size_y = 110; blr.use_relative = False
    vig  = tree.nodes.new('CompositorNodeMixRGB');      vig.location  = (380,-100)
    vig.blend_type = 'MULTIPLY'; vig.inputs['Fac'].default_value = 0.65

    comp = tree.nodes.new('CompositorNodeComposite');   comp.location = (620,0)

    _link(tree, rl.outputs['Image'],   glr.inputs['Image'])
    _link(tree, glr.outputs['Image'],  lens.inputs['Image'])
    _link(tree, lens.outputs['Image'], vig.inputs['Color1'])
    _link(tree, ell.outputs['Mask'],   blr.inputs['Image'])
    _link(tree, blr.outputs['Image'],  vig.inputs['Color2'])
    _link(tree, vig.outputs['Color'],  comp.inputs['Image'])

# ═══════════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════════

def main():
    print("\n╔══════════════════════════════════════════════════════════╗")
    print("║  Supreme Court of Pakistan — v6 Full Complex            ║")
    print("║  Kenzō Tange 1993 · 167 ft · White Marble · Islamabad  ║")
    print("║  Compound blocks + corridors + atmosphere + prop fixes  ║")
    print("╚══════════════════════════════════════════════════════════╝\n")

    clear_scene()
    print("  [MAT] Building material palette...")
    build_all_materials()

    C_GND = col("Ground_Plaza")
    C_BLD = col("Buildings")
    C_DET = col("Details_Fountains")
    C_NAT = col("Nature")
    C_INF = col("Infrastructure")

    print("  [1/11]  Ground, plaza, roads & grass...")
    build_ground(C_GND)
    build_grass(C_GND)
    build_garden(C_GND)

    print("  [2/11]  Main central tower (4 tiers, 51 m / 167 ft)...")
    build_main_tower(C_BLD)

    print("  [3/11]  Left & right wings (v6: 96m wide, ±105m offset)...")
    build_wing(C_BLD, -1)
    build_wing(C_BLD,  1)

    print("  [4/11]  Large compound blocks L+R (NEW)...")
    build_compound_blocks(C_BLD)

    print("  [5/11]  Colonnade corridors (NEW)...")
    build_corridors(C_BLD)

    print("  [6/11]  Rear blocks: Judges Chambers + Administrative...")
    build_rear(C_BLD)

    print("  [7/11]  Entry gate & expanded perimeter boundary wall...")
    build_gate(C_BLD)

    print("  [8/11]  Fountains (v6: 7-fountain grid)...")
    build_fountains(C_DET)

    print("  [9/11]  People on forecourt plaza...")
    build_people(C_DET)

    print("  [10/11]  Trees, lamp posts, parking...")
    build_trees(C_NAT)
    build_lamps(C_INF)
    build_parking(C_INF)

    print("  [11/11]  Lighting, atmosphere, sky, cameras, render...")
    build_lighting()
    build_atmosphere(C_BLD)
    build_world()
    build_cameras()
    setup_render()

    n_obj = len(list(bpy.data.objects))
    n_mat = len(list(bpy.data.materials))
    print(f"\n  ✓  Objects   : {n_obj}")
    print(f"  ✓  Materials : {n_mat}")
    print("""
  CAMERAS:
    Cam_Aerial  → F12            (aerial — pulled back for full complex)
    Cam_Front   → Ctrl+Numpad0   (front 3/4 — matches court.png)
    Cam_Plaza   → Ctrl+Numpad0   (plaza level — dramatic low-angle)

  v6 KEY ADDITIONS:
    • 2 large compound blocks (±168m) visible in arial.png
    • Colonnade corridors connecting compound blocks to wings
    • Volumetric atmosphere scatter (aerial haze)
    • 120m-wide tower base (was 90m)
    • 96m wings at ±105m (was 46m at ±66m)
    • 150×100m forecourt plaza (was 80×60m)
    • 7-fountain grid (was 5 fountains)
    • Polished stone: MAT_White rough 0.18 (was 0.22)

  TIPS:
    • GPU: Edit > Preferences > System > CUDA / OptiX
    • volume_bounces=4 — needed for atmosphere; adds ~15% render time
    • All white-stone objects share MAT_White — edit once, affects all
""")

main()
