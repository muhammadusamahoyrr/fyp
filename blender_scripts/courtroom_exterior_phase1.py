"""
╔══════════════════════════════════════════════════════════════════════════╗
║  ATTORNEY.AI — Supreme Court of Pakistan (Kenzō Tange, 1993)           ║
║  Blender Script  v5  ·  Reference-Accurate Reconstruction               ║
║  Compatible: Blender 3.3 LTS → 4.x                                     ║
╚══════════════════════════════════════════════════════════════════════════╝

REFERENCE IMAGES: court.png (front elevation) + arial.png (aerial view)
ARCHITECT : Kenzō Tange Associates + PEPAC (Pakistan) — Completed 1993
LOCATION  : Constitution Avenue, Islamabad — Red Zone
HEIGHT    : 167 ft (≈ 51 m) — Main Central Block
STYLE     : Modernist Islamic — white marble, stepped tiers inspired by
            Mohenjo-Daro, "plain and pure lines creating volume & mobility"

ACCURACY vs v4 (corrections driven by visual reference + web research):
  ✦ REMOVED dome           — reference shows flat-topped stepped crown
  ✦ REMOVED verdigris/aged materials — facade is clean white marble
  ✦ REMOVED balustrades    — reference shows plain flat parapet coping
  ✦ REMOVED classical pediment — Tange style is modernist, not classical
  ✦ REMOVED rusticated base — smooth white stone plinth only
  ✦ FIXED   wing pilasters — flat rectangular (NOT round cylinders)
  ✦ FIXED   proportions    — calibrated to real 51 m height
  ✦ FIXED   materials      — (0.95,0.94,0.90) white marble, roughness 0.22
  ✦ FIXED   arch style     — clean 1-ring modernist Islamic portal
  ✦ KEPT    Islamic arch   — confirmed by research + visible in reference
  ✦ KEPT    wide podium staircase — "wide staircase leads to entrance"
  ✦ KEPT    forecourt fountains, trees, parking — confirmed from aerial

HOW TO USE:
  1. Open Blender → Scripting workspace
  2. New → paste / open this file → ▶ Run Script
  3. F12 = render aerial view   (Cam_Aerial — matches arial.png)
  4. Select Cam_Front  → Ctrl+Numpad0  (matches court.png angle)
  5. Select Cam_Plaza  → Ctrl+Numpad0  (eye-level courtyard shot)
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
#  MATERIAL SYSTEM — reference-accurate clean white stone palette
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
    """Dark reflective glass for arch interior + window recesses."""
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
    """Light cream stone plaza tiles with subtle grout grid."""
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
    cr.color_ramp.elements[0].color = (0.76, 0.74, 0.68, 1.0)  # grout
    el2 = cr.color_ramp.elements.new(0.12); el2.color = (0.90, 0.88, 0.82, 1.0)
    cr.color_ramp.elements[1].color = (0.92, 0.90, 0.86, 1.0)  # tile face
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
    # ── Primary building stone — reference: clean white marble facade
    mat_simple('MAT_White',    (0.95, 0.94, 0.90), rough=0.22)
    mat_simple('MAT_WhiteDk',  (0.88, 0.87, 0.84), rough=0.30)  # coping / spandrels
    mat_simple('MAT_WhiteGy',  (0.80, 0.79, 0.77), rough=0.40)  # roof decks (aerial view)
    # ── Ground surfaces
    mat_plaza_clean('MAT_Plaza')
    mat_simple('MAT_Garden',   (0.72, 0.68, 0.58), rough=0.65)  # sandy garden paths
    mat_simple('MAT_Road',     (0.12, 0.12, 0.12), rough=0.92)
    mat_simple('MAT_Parking',  (0.10, 0.10, 0.10), rough=0.95)
    mat_simple('MAT_ParkLine', (0.88, 0.88, 0.88), rough=0.90)
    mat_simple('MAT_Kerb',     (0.62, 0.61, 0.59), rough=0.55)
    mat_simple('MAT_Ground',   (0.28, 0.32, 0.18), rough=1.00)
    # ── Vegetation
    mat_simple('MAT_Grass',    (0.10, 0.38, 0.08), rough=1.00)
    mat_simple('MAT_GrassDk',  (0.06, 0.22, 0.04), rough=1.00)
    mat_simple('MAT_TreeLeaf', (0.07, 0.28, 0.05), rough=1.00)
    mat_simple('MAT_TreeLeafDk',(0.04,0.18, 0.03), rough=1.00)
    mat_simple('MAT_TreeTrunk',(0.25, 0.14, 0.06), rough=1.00)
    mat_simple('MAT_Hedge',    (0.04, 0.22, 0.04), rough=1.00)
    # ── Glass / metal
    mat_glass_dark('MAT_WinDark')
    mat_water_proc('MAT_Water')
    mat_simple('MAT_LampMetal',(0.22, 0.22, 0.24), metal=0.75, rough=0.28)
    mat_simple('MAT_LampGlow', (1.00, 0.96, 0.82),
               emission=(1.0, 0.96, 0.82), emit_str=12.0)
    # ── Flag (Pakistan: dark green + white)
    mat_simple('MAT_FlagGreen',(0.00, 0.36, 0.10), rough=0.85)
    mat_simple('MAT_FlagWhite',(0.96, 0.96, 0.95), rough=0.85)
    # ── Cars + people
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
#  ISLAMIC POINTED ARCH  (modernist clean — Kenzo Tange style)
# ═══════════════════════════════════════════════════════════════════════

def build_arch_clean(name, loc, width, height, thickness, depth,
                     collection, mat='MAT_WhiteDk', segs=40):
    """
    Single-ring clean pointed arch — Tange's modernist Islamic language.
    Two circular arcs meeting at a point, minimal frame thickness.
    """
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
        face4(fo[i], fo[i+1], fi[i+1], fi[i])   # front ring
        face4(fo[i], bo[i], bo[i+1], fo[i+1])   # outer side
        face4(bi[i], fi[i], fi[i+1], bi[i+1])   # inner side
        face4(bo[i], bo[i+1], bi[i+1], bi[i])   # back ring

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

def build_podium(C_BLD, cx=0, cy_front=-17.5, total_w=110, steps=5,
                 riser=1.20, tread=3.50):
    """
    Broad monumental staircase — reference: "wide staircase leads to entrance".
    5 steps × 1.2 m rise, 3.5 m tread = 6 m total rise, 17.5 m projection.
    """
    for s in range(steps):
        sw = total_w / 2 - s * 2.5   # steps narrow slightly toward top
        sy_half = (steps - s) * tread / 2
        sz = riser / 2
        z_ctr = (s + 0.5) * riser
        y_ctr = cy_front + (steps - s) * tread
        BOX(f'Pod_Step{s}',
            (cx, y_ctr, z_ctr),
            sw, sy_half, sz,
            C_BLD, 'MAT_White', bevel=True, bw=0.06)
        # Coping strip on each step edge
        BOX(f'Pod_Cop{s}',
            (cx, y_ctr - sy_half + 0.15, z_ctr + sz + 0.12),
            sw, 0.15, 0.12,
            C_BLD, 'MAT_WhiteDk')

# ═══════════════════════════════════════════════════════════════════════
#  MAIN CENTRAL BLOCK — 4 stepped tiers, flat-topped, 167 ft / 51 m
# ═══════════════════════════════════════════════════════════════════════

def build_main_tower(C_BLD):
    """
    Stepped ziggurat inspired by Mohenjo-Daro (Kenzo Tange design intent).
    4 rectangular tiers, each stepping inward. All flat-topped.
    Total height ≈ 51 m calibrated to 167 ft real-world measurement.
    """
    cx, cy = 0.0, 10.0   # tower block center (Y slightly behind plaza)

    # ── Tier dimensions (half-extents for BOX): sx, sy, sz, z_center ──
    tiers = [
        # (sx,  sy,   sz,   z_ctr,  label)
        (45.0, 27.5, 7.0,  13.0, 'T1'),   # 90 × 55 × 14 m
        (32.5, 21.0, 6.5,  26.5, 'T2'),   # 65 × 42 × 13 m
        (23.0, 15.0, 5.5,  38.0, 'T3'),   # 46 × 30 × 11 m
        (16.0, 11.0, 4.5,  47.5, 'T4'),   # 32 × 22 ×  9 m
    ]
    for sx, sy, sz, zc, tag in tiers:
        # Main block
        BOX(f'Blk_{tag}', (cx, cy, zc), sx, sy, sz,
            C_BLD, 'MAT_White', bevel=True, bw=0.08)
        # Flat parapet coping strip at top of each tier
        BOX(f'Cop_{tag}', (cx, cy, zc + sz + 0.22),
            sx + 0.4, sy + 0.4, 0.22,
            C_BLD, 'MAT_WhiteDk')
        # Horizontal spandrel band at base of each tier (reads as shadow line)
        BOX(f'Spnd_{tag}', (cx, cy, zc - sz + 0.55),
            sx + 0.2, sy + 0.2, 0.28,
            C_BLD, 'MAT_WhiteDk')

    # ── Islamic arch portal (front face of Tier 1, y_face = cy - sy_T1) ──
    portal_y = cy - 27.5   # = -17.5
    portal_z = 6.0         # sits on top of podium
    arch_w   = 14.0        # arch span
    arch_h   = 20.0        # arch height

    # Arch frame
    build_arch_clean('Portal_Arch',
                     (cx - arch_w / 2, portal_y, portal_z),
                     arch_w, arch_h, 0.9, 2.5,
                     C_BLD, 'MAT_WhiteDk', segs=48)

    # Dark glass recessed inside arch
    BOX('Portal_Glass',
        (cx, portal_y - 1.2, portal_z + arch_h * 0.45),
        arch_w / 2 - 0.8, 0.25, arch_h * 0.44,
        C_BLD, 'MAT_WinDark')

    # Large pilasters flanking the portal
    for sx_pil in [-1, 1]:
        px = cx + sx_pil * (arch_w / 2 + 2.8)
        BOX(f'Portal_Pil{sx_pil}',
            (px, portal_y - 0.5, portal_z + arch_h * 0.5),
            2.0, 0.8, arch_h * 0.5,
            C_BLD, 'MAT_White', bevel=True, bw=0.05)

    # ── Window grids on Tier 1 front face (flanking the arch) ──
    win_z_base = portal_z + 1.5
    for side in [-1, 1]:
        x_start = side * (arch_w / 2 + 5.5)
        for col_i in range(3):
            for row_i in range(2):
                wx = x_start + side * col_i * 4.8
                wz = win_z_base + row_i * 5.5
                BOX(f'Win_T1F_{side}_{col_i}_{row_i}',
                    (wx, portal_y - 0.18, wz),
                    1.4, 0.22, 2.2,
                    C_BLD, 'MAT_WinDark')
                # Frame surround
                BOX(f'WFr_T1F_{side}_{col_i}_{row_i}',
                    (wx, portal_y - 0.08, wz),
                    1.6, 0.15, 2.4,
                    C_BLD, 'MAT_WhiteDk')

    # ── Windows on Tier 2, 3, 4 front faces ──
    for t_i, (sx, sy, sz, zc, tag) in enumerate(tiers[1:], 1):
        fy = cy - sy - 0.05   # front face Y
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

    # ── Flagpole at top center ──
    flag_z = 47.5 + 4.5   # top of Tier 4
    CYL('Flag_Pole',   (cx, cy, flag_z + 9.0), 0.18, 18.0, C_BLD, 'MAT_LampMetal')
    SPHERE('Flag_Ball',(cx, cy, flag_z + 18.2), 0.40, C_BLD, 'MAT_LampMetal')
    BOX('Flag_Green',  (cx + 3.6, cy, flag_z + 15.5), 3.6, 0.04, 1.5, C_BLD, 'MAT_FlagGreen')
    BOX('Flag_White',  (cx + 3.6, cy, flag_z + 17.1), 3.6, 0.04, 0.42, C_BLD, 'MAT_FlagWhite')

    # ── Podium staircase ──
    build_podium(C_BLD, cx=cx, cy_front=portal_y,
                 total_w=100, steps=5, riser=1.20, tread=3.50)

# ═══════════════════════════════════════════════════════════════════════
#  WINGS  (flat-pilastered, flat-roofed — reference-accurate)
# ═══════════════════════════════════════════════════════════════════════

def build_wing(C_BLD, side=1):
    """
    Court wings: rectangular block + flat rectangular pilasters on front face.
    Kenzo Tange style — NOT round columns, flat pilasters with thin projection.
    """
    s   = side
    tag = 'L' if s == -1 else 'R'
    cx  = s * 66.0    # wing center X (offset from tower)
    cy  = 10.0        # same Y as tower
    wx  = 23.0        # half-width  → 46 m wide
    wy  = 15.0        # half-depth  → 30 m deep
    wz  = 11.0        # half-height → 22 m tall
    z_c = wz          # center Z

    # Main wing slab
    BOX(f'Wing_{tag}',     (cx, cy, z_c),      wx, wy, wz,   C_BLD, 'MAT_White', bevel=True, bw=0.08)
    # Flat roof coping
    BOX(f'WCop_{tag}',     (cx, cy, z_c+wz+0.22), wx+0.4, wy+0.4, 0.22, C_BLD, 'MAT_WhiteDk')
    # Base spandrel
    BOX(f'WSpnd_{tag}',    (cx, cy, 1.0),      wx+0.2, wy+0.2, 0.45, C_BLD, 'MAT_WhiteDk')

    # Connector link to main tower (fills gap between wing and tower)
    link_cx = s * (66.0 - wx - (45.0 - wx) / 2)   # midpoint between wing edge and tower edge
    BOX(f'WLink_{tag}',
        (s * 46.5, cy, 9.0),
        2.5, wy, 9.0,
        C_BLD, 'MAT_White', bevel=True, bw=0.06)

    # ── Flat rectangular pilasters on front face ──
    front_y = cy - wy   # front face of wing
    n_pil   = 7
    pil_w   = 1.2   # half-width of pilaster
    pil_proj= 0.55  # how far they project from facade

    for i in range(n_pil):
        px = cx - wx + 3.0 + i * (wx * 2 - 6.0) / (n_pil - 1)
        # Full-height pilaster
        BOX(f'WPil_{tag}_{i}',
            (px, front_y - pil_proj, z_c),
            pil_w, pil_proj, wz,
            C_BLD, 'MAT_White', bevel=True, bw=0.04)
        # Pilaster capital (slight projection at top)
        BOX(f'WCap_{tag}_{i}',
            (px, front_y - pil_proj - 0.08, z_c + wz - 0.8),
            pil_w + 0.2, pil_proj + 0.08, 0.55,
            C_BLD, 'MAT_WhiteDk')

    # ── Entablature band across pilaster tops ──
    BOX(f'WEnta_{tag}',
        (cx, front_y - 0.35, z_c + wz - 0.22),
        wx + 0.2, 0.60, 0.22,
        C_BLD, 'MAT_WhiteDk')

    # ── Window bays between pilasters ──
    for i in range(n_pil - 1):
        px = cx - wx + 3.0 + (i + 0.5) * (wx * 2 - 6.0) / (n_pil - 1)
        for row in range(3):
            wz_pos = 2.5 + row * 5.8
            BOX(f'WWin_{tag}_{i}_{row}',
                (px, front_y - 0.2, wz_pos),
                1.8, 0.22, 2.2,
                C_BLD, 'MAT_WinDark')
            BOX(f'WWFr_{tag}_{i}_{row}',
                (px, front_y - 0.10, wz_pos),
                2.0, 0.15, 2.4,
                C_BLD, 'MAT_WhiteDk')

    # ── Side arch entrance on outer face ──
    outer_y = cy   # side face is at cx ± wx
    outer_x = s * (cx + wx)
    build_arch_clean(f'WArc_{tag}',
                     (outer_x - s * 6, outer_y - 8, 0),
                     12, 14, 0.7, 2.0,
                     C_BLD, 'MAT_WhiteDk', segs=36)

# ═══════════════════════════════════════════════════════════════════════
#  REAR BLOCKS — Judges' Chambers (E) + Administrative (N/S)
# ═══════════════════════════════════════════════════════════════════════

def build_rear(C_BLD):
    cx, cy_tower = 0.0, 10.0

    # Judges' Chambers — east side (research: "east of main block")
    BOX('JudgeCh_Main', ( 72, cy_tower, 9.0), 20, 22, 9.0,  C_BLD, 'MAT_White', bevel=True, bw=0.07)
    BOX('JudgeCh_Cop',  ( 72, cy_tower, 18.4),20.4,22.4,0.22, C_BLD,'MAT_WhiteDk')
    BOX('JudgeCh_Sub',  ( 72, cy_tower+22, 6.5), 16, 8, 6.5, C_BLD,'MAT_White', bevel=True)

    # Administrative — north (behind tower)
    for s, tag in [(-1, 'L'), (1, 'R')]:
        px = s * 36
        BOX(f'Admin_{tag}',    (px, 58, 8.0),  18, 20, 8.0,  C_BLD, 'MAT_White', bevel=True, bw=0.06)
        BOX(f'AdminCop_{tag}', (px, 58, 16.4), 18.4,20.4,0.22,C_BLD,'MAT_WhiteDk')
        BOX(f'AdminSub_{tag}', (px, 72, 6.0),  14, 10, 6.0,  C_BLD, 'MAT_White', bevel=True)

    # Central link behind tower
    BOX('Admin_Ctr', (0, 44, 5.5), 20, 8, 5.5, C_BLD, 'MAT_White', bevel=True)
    BOX('Admin_CtrCop',(0,44,11.2),20.4,8.4,0.22,C_BLD,'MAT_WhiteDk')

# ═══════════════════════════════════════════════════════════════════════
#  ENTRY GATE + BOUNDARY WALL
# ═══════════════════════════════════════════════════════════════════════

def build_gate(C_BLD):
    # Gate towers
    for s in [-1, 1]:
        BOX(f'GT_{s}',    (s*14, -130, 8.0), 5.0,5.0,8.0, C_BLD,'MAT_White',bevel=True)
        BOX(f'GT_Cop{s}', (s*14, -130,16.4), 5.4,5.4,0.22,C_BLD,'MAT_WhiteDk')
        CONE_OBJ(f'GT_Top{s}',(s*14,-130,18.0),4.5,0.5,3.5,C_BLD,'MAT_WhiteDk',verts=4)

    # Gate arch (clean pointed)
    build_arch_clean('Gate_Arch', (-8, -130, 0), 16, 14, 0.8, 5.0, C_BLD, 'MAT_WhiteDk', segs=32)
    BOX('Gate_Span', (0, -130, 13.5), 8, 5.0, 0.9, C_BLD, 'MAT_WhiteDk')

    # Gate bars
    for i in range(9):
        BOX(f'GBar_L{i}', (-10+i*1.1, -130, 3.8), 0.09,0.09,3.8, C_BLD,'MAT_LampMetal')
    BOX('GRail', (0,-130,7.4), 9,0.12,0.12, C_BLD,'MAT_LampMetal')

    # Guard post
    BOX('GPost', (-22,-130,2.4), 3.0,3.0,2.4, C_BLD,'MAT_White',bevel=True)
    BOX('GPost_Rf',(-22,-130,5.0),3.4,3.4,0.4,C_BLD,'MAT_WhiteDk')

    # Wing walls
    BOX('GWall_L', (-52,-130,2.2), 22,0.6,2.2, C_BLD,'MAT_White')
    BOX('GWall_R', ( 52,-130,2.2), 22,0.6,2.2, C_BLD,'MAT_White')
    # Wall pilasters
    for i in range(5):
        for s in [-1,1]:
            BOX(f'GWPil_{s}_{i}',(s*(-28+i*7),-130,2.6),1.0,1.0,2.6,C_BLD,'MAT_WhiteDk')

    # Perimeter boundary walls
    BOX('BW_L',  (-112, 12, 2.2), 0.6,118, 2.2, C_BLD,'MAT_White')
    BOX('BW_R',  ( 112, 12, 2.2), 0.6,118, 2.2, C_BLD,'MAT_White')
    BOX('BW_Rr', (   0,105, 2.2), 112,0.6, 2.2, C_BLD,'MAT_White')
    for i in range(12):
        y = -65+i*15
        for s in [-1,1]:
            BOX(f'BWPil_{s}_{i}',(s*112,y,2.8),1.4,1.4,2.8,C_BLD,'MAT_WhiteDk')

# ═══════════════════════════════════════════════════════════════════════
#  GROUND — PLAZA, ROADS, PARKING MARKERS
# ═══════════════════════════════════════════════════════════════════════

def build_ground(C_GND):
    PLANE('Gnd_Base',  (0,  0,-0.12), 240, 240, C_GND,'MAT_Ground')
    # Main forecourt plaza (cream stone tiles)
    PLANE('Plaza_Main',(0,-40, 0.02),  80,  60, C_GND,'MAT_Plaza')
    PLANE('Plaza_Fore',(0,-90, 0.02),  80,  30, C_GND,'MAT_Plaza')
    PLANE('Path_Axis', (0,-65, 0.02),   8,  20, C_GND,'MAT_Plaza')
    PLANE('Plaza_Circ',(0,-60, 0.025), 24,  24, C_GND,'MAT_Plaza')
    # Roads
    PLANE('Rd_Front',  (0,-155,0.02), 120,  20, C_GND,'MAT_Road')
    PLANE('Rd_L',      (-120,0, 0.02), 18, 140, C_GND,'MAT_Road')
    PLANE('Rd_R',      ( 120,0, 0.02), 18, 140, C_GND,'MAT_Road')
    PLANE('Rd_Rear',   (0, 115,0.02), 120,  18, C_GND,'MAT_Road')
    # Kerbs
    BOX('Kerb_FL', (-48,-78,0.14), 24,0.28,0.14, C_GND,'MAT_Kerb')
    BOX('Kerb_FR', ( 48,-78,0.14), 24,0.28,0.14, C_GND,'MAT_Kerb')

def build_grass(C_GND):
    PLANE('Gr_L',   (-82, 15, 0.01),  28, 120, C_GND,'MAT_Grass')
    PLANE('Gr_R',   ( 82, 15, 0.01),  28, 120, C_GND,'MAT_Grass')
    PLANE('Gr_PL',  (-50,-10, 0.01),   8,  70, C_GND,'MAT_Grass')
    PLANE('Gr_PR',  ( 50,-10, 0.01),   8,  70, C_GND,'MAT_Grass')
    PLANE('Gr_Rear',(  0, 78, 0.01), 100,  55, C_GND,'MAT_Grass')
    PLANE('Gr_FL',  (-44,-60, 0.01),  18,  24, C_GND,'MAT_Grass')
    PLANE('Gr_FR',  ( 44,-60, 0.01),  18,  24, C_GND,'MAT_Grass')
    # Hedge rows flanking plaza approach
    for i in range(10):
        y = -75 + i * 9
        BOX(f'Hdg_L{i}', (-38, y, 0.9), 0.9, 3.8, 0.9, C_GND,'MAT_Hedge')
        BOX(f'Hdg_R{i}', ( 38, y, 0.9), 0.9, 3.8, 0.9, C_GND,'MAT_Hedge')

def build_garden(C_GND):
    """Formal rear gardens visible in arial.png — grid paths + beds."""
    PLANE('GPth_Axis', (0, 50, 0.02), 5, 32, C_GND,'MAT_Plaza')
    PLANE('GPth_X1',   (0, 62, 0.02),60,  4, C_GND,'MAT_Plaza')
    PLANE('GPth_X2',   (0, 82, 0.02),52,  3, C_GND,'MAT_Plaza')
    PLANE('GPth_SL',  (-28,65, 0.02), 3, 30, C_GND,'MAT_Plaza')
    PLANE('GPth_SR',  ( 28,65, 0.02), 3, 30, C_GND,'MAT_Plaza')
    for i in range(4):
        for j in range(3):
            bx = -15 + i * 10; by = 55 + j * 12
            PLANE(f'Bed_{i}_{j}', (bx, by, 0.02), 3.5, 4.5, C_GND,'MAT_GrassDk')
    # Rear reflecting pond
    PLANE('Pond_L', (-22,88,0.02), 10, 7, C_GND,'MAT_Water')
    PLANE('Pond_R', ( 22,88,0.02), 10, 7, C_GND,'MAT_Water')
    CYL('Pond_FntL',(-22,88,0.9),0.20,2.0,C_GND,'MAT_White')
    CYL('Pond_FntR',( 22,88,0.9),0.20,2.0,C_GND,'MAT_White')

# ═══════════════════════════════════════════════════════════════════════
#  FOUNTAIN SYSTEM
# ═══════════════════════════════════════════════════════════════════════

def fountain(prefix, cx, cy, collection, scale=1.0):
    z = 0.04; s = scale
    CYL(f'{prefix}_OBase', (cx,cy,z+0.08*s), 5.2*s,0.16*s, collection,'MAT_White', verts=8)
    CYL(f'{prefix}_OWall', (cx,cy,z+0.50*s), 5.0*s,0.80*s, collection,'MAT_White', verts=8)
    CYL(f'{prefix}_OWater',(cx,cy,z+0.88*s), 4.8*s,0.06,   collection,'MAT_Water', verts=8)
    CYL(f'{prefix}_Shaft', (cx,cy,z+2.8*s),  0.24*s,3.8*s, collection,'MAT_White')
    SPHERE(f'{prefix}_Sp', (cx,cy,z+4.8*s),  0.50*s,       collection,'MAT_Water')
    for ang in range(0,360,60):
        rad=math.radians(ang)
        jx=cx+math.cos(rad)*3.2*s; jy=cy+math.sin(rad)*3.2*s
        SPHERE(f'{prefix}_J{ang}',(jx,jy,z+1.6*s),0.18*s,collection,'MAT_Water')

def build_fountains(C_DET):
    fountain('F_Main',  0, -60,  C_DET, scale=1.8)
    fountain('F_L',   -22, -48,  C_DET, scale=1.0)
    fountain('F_R',    22, -48,  C_DET, scale=1.0)
    fountain('F_L2',  -10, -36,  C_DET, scale=0.70)
    fountain('F_R2',   10, -36,  C_DET, scale=0.70)

# ═══════════════════════════════════════════════════════════════════════
#  TREES  (3-sphere canopy cluster — matches aerial dense tree look)
# ═══════════════════════════════════════════════════════════════════════

def TREE(prefix, x, y, collection, h=5.0, cr=1.8, mat='MAT_TreeLeaf'):
    CYL(f'{prefix}_T',  (x,y,h*0.35), 0.20,h*0.72, collection,'MAT_TreeTrunk')
    SPHERE(f'{prefix}_C0',(x,       y,       h*0.88), cr,      collection,mat)
    SPHERE(f'{prefix}_C1',(x+cr*0.5,y+cr*0.2,h*0.80), cr*0.72, collection,mat)
    SPHERE(f'{prefix}_C2',(x-cr*0.4,y-cr*0.3,h*0.78), cr*0.65, collection,mat)

def build_trees(C_NAT):
    # Central avenue (both sides of approach axis)
    for i in range(14):
        y = -140 + i * 7
        TREE(f'Av_L{i}',  -10, y, C_NAT, h=6.5, cr=2.2)
        TREE(f'Av_R{i}',   10, y, C_NAT, h=6.5, cr=2.2)
    # Plaza perimeter trees
    for i in range(8):
        TREE(f'Plz_L{i}', -46, -90+i*10, C_NAT, h=5.0, cr=1.8)
        TREE(f'Plz_R{i}',  46, -90+i*10, C_NAT, h=5.0, cr=1.8)
    # Side garden rows
    for row in range(3):
        for i in range(11):
            TREE(f'SL_{row}_{i}', -74-row*12, -30+i*12, C_NAT,
                 h=7+row, cr=2.8+row*0.3, mat='MAT_TreeLeaf')
            TREE(f'SR_{row}_{i}',  74+row*12, -30+i*12, C_NAT,
                 h=7+row, cr=2.8+row*0.3, mat='MAT_TreeLeaf')
    # Rear formal garden trees
    for r in range(5):
        for c in range(7):
            TREE(f'RG_{r}_{c}', -32+c*10, 50+r*10, C_NAT,
                 h=6+random.uniform(0,2), cr=2.2+random.uniform(0,0.8))
    # Dense perimeter forest
    for i in range(28):
        TREE(f'Frst_{i}', random.uniform(-110,110), random.uniform(100,130),
             C_NAT, h=random.uniform(7,13), cr=random.uniform(3,5),
             mat='MAT_TreeLeafDk')

# ═══════════════════════════════════════════════════════════════════════
#  LAMP POSTS
# ═══════════════════════════════════════════════════════════════════════

def LAMP(prefix, x, y, collection):
    BOX(f'{prefix}_B', (x,y,0.20), 0.5,0.5,0.20, collection,'MAT_LampMetal')
    CONE_OBJ(f'{prefix}_Sh',(x,y,6.2),0.14,0.09,11.5,collection,'MAT_LampMetal',verts=16)
    BOX(f'{prefix}_Arm',(x+0.9,y,11.8),0.9,0.07,0.07,collection,'MAT_LampMetal')
    BOX(f'{prefix}_ArmV',(x+1.8,y,11.4),0.07,0.07,0.38,collection,'MAT_LampMetal')
    CYL(f'{prefix}_Hous',(x+1.8,y,10.9),0.30,0.50,collection,'MAT_LampMetal',verts=8)
    SPHERE(f'{prefix}_Glo',(x+1.8,y,10.9),0.26,collection,'MAT_LampGlow')

def build_lamps(C_INF):
    for i in range(14):
        y = -140 + i * 8
        LAMP(f'Lp_L{i}', -14, y, C_INF)
        LAMP(f'Lp_R{i}',  14, y, C_INF)
    for i in range(6):
        LAMP(f'Lp_PL{i}', -34, -90+i*12, C_INF)
        LAMP(f'Lp_PR{i}',  34, -90+i*12, C_INF)

# ═══════════════════════════════════════════════════════════════════════
#  PARKING  (both sides — confirmed from arial.png)
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
    PLANE('Lot_L',(-95,-25,0.01),32,55,C_INF,'MAT_Parking')
    PLANE('Lot_R',( 95,-25,0.01),32,55,C_INF,'MAT_Parking')
    for row in range(9):
        for slot in range(8):
            lx = -107+slot*3.5; ly = -48+row*5.5
            BOX(f'PkLn_L{row}_{slot}',(lx,ly,0.015),1.1,0.05,0.01,C_INF,'MAT_ParkLine')
            DETAILED_CAR(f'Car_L{row}_{slot}',lx,ly,C_INF)
            rx =  72+slot*3.5
            BOX(f'PkLn_R{row}_{slot}',(rx,ly,0.015),1.1,0.05,0.01,C_INF,'MAT_ParkLine')
            DETAILED_CAR(f'Car_R{row}_{slot}',rx,ly,C_INF)

# ═══════════════════════════════════════════════════════════════════════
#  PEOPLE SILHOUETTES  (visible in court.png foreground)
# ═══════════════════════════════════════════════════════════════════════

def PERSON(name, x, y, collection):
    BOX(f'{name}_B', (x,y,0.90), 0.22,0.12,0.90, collection,'MAT_Person')
    SPHERE(f'{name}_H',(x,y,2.05),0.22,             collection,'MAT_Person')

def build_people(C_DET):
    positions = [
        (-10,-32),(-5,-30),(2,-35),(7,-32),(12,-28),
        (-14,-26),(0,-40),(15,-22),(-7,-40),(4,-28),
        (-20,-35),(18,-30),(-2,-50),(9,-52),(16,-45),
        (0,-58),(-11,-55),(22,-38),(-22,-28),(6,-62),
        (14,-68),(-6,-70),(24,-62),(-18,-58),(0,-72),
    ]
    for i, (px, py) in enumerate(positions):
        jx = px + random.uniform(-1.2, 1.2)
        jy = py + random.uniform(-1.2, 1.2)
        PERSON(f'P{i}', jx, jy, C_DET)

# ═══════════════════════════════════════════════════════════════════════
#  LIGHTING  (golden-hour matching arial.png)
# ═══════════════════════════════════════════════════════════════════════

def build_lighting():
    # Key: warm golden-hour sun from upper-left (matches aerial shadow direction)
    bpy.ops.object.light_add(type='SUN', location=(100,-150,90))
    sun = bpy.context.active_object; sun.name='Sun_Key'
    sun.data.energy = 7.5
    sun.data.color  = (1.0, 0.94, 0.80)
    sun.data.angle  = math.radians(0.8)
    sun.rotation_euler = (math.radians(38), math.radians(5), math.radians(-42))

    # Sky fill: cool blue
    bpy.ops.object.light_add(type='AREA', location=(0,0,140))
    fill = bpy.context.active_object; fill.name='Sky_Fill'
    fill.data.energy = 550; fill.data.size = 280
    fill.data.color  = (0.62, 0.78, 1.0)

    # Rim: back depth
    bpy.ops.object.light_add(type='AREA', location=(-90,90,65))
    rim = bpy.context.active_object; rim.name='Rim_Light'
    rim.data.energy = 260; rim.data.size = 110
    rim.data.color  = (0.80, 0.90, 1.0)
    rim.rotation_euler = (math.radians(48),0,math.radians(132))

    # Ground bounce (warm, subtle)
    bpy.ops.object.light_add(type='AREA', location=(0,-20,1))
    bnc = bpy.context.active_object; bnc.name='Ground_Bounce'
    bnc.data.energy = 180; bnc.data.size = 120
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
#  CAMERAS — calibrated to match both reference images
# ═══════════════════════════════════════════════════════════════════════

def build_cameras():
    scene = bpy.context.scene

    # Aerial — matches arial.png: steep diagonal, wide lens, full complex visible
    bpy.ops.object.camera_add(location=(140,-260,180))
    ca = bpy.context.active_object; ca.name='Cam_Aerial'
    ca.rotation_euler = (math.radians(48),0,math.radians(38))
    ca.data.lens = 35; scene.camera = ca

    # Front 3/4 — matches court.png: slight left-of-center, 50 mm, eye-level+
    bpy.ops.object.camera_add(location=(30,-170,40))
    cf = bpy.context.active_object; cf.name='Cam_Front'
    cf.rotation_euler = (math.radians(78),0,math.radians(10))
    cf.data.lens = 50
    cf.data.dof.use_dof = True
    cf.data.dof.focus_distance = 168
    cf.data.dof.aperture_fstop = 6.3

    # Plaza level — dramatic entrance low-angle, 28 mm wide
    bpy.ops.object.camera_add(location=(0,-90,4.0))
    cp = bpy.context.active_object; cp.name='Cam_Plaza'
    cp.rotation_euler = (math.radians(84),0,0)
    cp.data.lens = 28
    cp.data.dof.use_dof = True
    cp.data.dof.focus_distance = 90
    cp.data.dof.aperture_fstop = 8.0

# ═══════════════════════════════════════════════════════════════════════
#  RENDER SETTINGS + COMPOSITOR
# ═══════════════════════════════════════════════════════════════════════

def setup_render():
    scene = bpy.context.scene
    scene.render.engine = 'CYCLES'

    # Adaptive sampling — fast convergence on large flat white surfaces
    scene.cycles.use_adaptive_sampling = True
    scene.cycles.adaptive_threshold    = 0.01
    scene.cycles.adaptive_min_samples  = 32
    scene.cycles.samples               = 512
    scene.cycles.use_denoising         = True
    try: scene.cycles.denoiser         = 'OPENIMAGEDENOISE'
    except: pass

    # Bounces — critical for white marble multi-bounce + glass IOR
    scene.cycles.max_bounces           = 16
    scene.cycles.diffuse_bounces       = 5
    scene.cycles.glossy_bounces        = 6
    scene.cycles.transmission_bounces  = 12
    scene.cycles.volume_bounces        = 2

    scene.render.resolution_x = 2560
    scene.render.resolution_y = 1440
    scene.render.film_transparent = False

    # Colour management — Filmic, slight warmth lift
    scene.view_settings.view_transform = 'Filmic'
    scene.view_settings.look           = 'High Contrast'
    scene.view_settings.exposure       = 0.18
    scene.view_settings.gamma          = 1.04

    # Compositor: Glare → Lens Distort → Vignette → Output
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
    print("\n╔══════════════════════════════════════════════════════╗")
    print("║  Supreme Court of Pakistan — v5 Reference Accurate  ║")
    print("║  Kenzō Tange 1993 · 167 ft · White Marble · Islamabad║")
    print("╚══════════════════════════════════════════════════════╝\n")

    clear_scene()
    print("  [MAT] Building reference-accurate material palette...")
    build_all_materials()

    C_GND = col("Ground_Plaza")
    C_BLD = col("Buildings")
    C_DET = col("Details_Fountains")
    C_NAT = col("Nature")
    C_INF = col("Infrastructure")

    print("  [1/9]  Ground, plaza, roads & grass...")
    build_ground(C_GND)
    build_grass(C_GND)
    build_garden(C_GND)

    print("  [2/9]  Main central tower (stepped tiers, 51 m / 167 ft)...")
    build_main_tower(C_BLD)

    print("  [3/9]  Left & right wings (flat pilasters)...")
    build_wing(C_BLD, -1)
    build_wing(C_BLD,  1)

    print("  [4/9]  Rear blocks: Judges Chambers + Administrative...")
    build_rear(C_BLD)

    print("  [5/9]  Entry gate & perimeter boundary wall...")
    build_gate(C_BLD)

    print("  [6/9]  Fountains...")
    build_fountains(C_DET)

    print("  [7/9]  People on forecourt plaza...")
    build_people(C_DET)

    print("  [8/9]  Trees, lamp posts, parking & cars...")
    build_trees(C_NAT)
    build_lamps(C_INF)
    build_parking(C_INF)

    print("  [9/9]  Lighting, sky, cameras, render...")
    build_lighting()
    build_world()
    build_cameras()
    setup_render()

    n_obj = len(list(bpy.data.objects))
    n_mat = len(list(bpy.data.materials))
    print(f"\n  ✓  Objects   : {n_obj}")
    print(f"  ✓  Materials : {n_mat}")
    print("""
  CAMERAS:
    Cam_Aerial  → F12           (aerial — matches arial.png)
    Cam_Front   → Ctrl+Numpad0  (front 3/4 — matches court.png)
    Cam_Plaza   → Ctrl+Numpad0  (plaza level — dramatic low-angle)

  TIPS:
    • GPU: Edit > Preferences > System > CUDA / OptiX
    • Adaptive sampling stops automatically — no manual tuning needed
    • White stone looks best with Filmic + High Contrast colour management
    • Reduce sun elevation to 22° for late-afternoon golden glow
    • All white-stone objects share MAT_White — edit once, affects whole building
""")

main()
