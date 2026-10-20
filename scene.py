"""Technical-cutaway scene kit: a broad-gauge wheelset, bogie and coach on curved / canted track, a turnout,
and the effects used to explain how a train follows the rails.

Usage (bpy module or blender -b -P):
    python3 scene.py --style hook --res 540x960 --samples 48 --out style/
    python3 scene.py --frames 1-2790 --res 720x1280 --samples 32 --out frames/   (once the shot list exists)

Everything is built from primitives, revolved profiles and swept profiles. Real dimensions (metres):
gauge 1.676, rail centres 1.750, wheel radius 0.4575, tread taper 1 in 20 (exaggerated in cutaways),
rail inclination 1 in 20, sleeper spacing 0.60, cant up to 0.165.
"""
import argparse, json, math, os, random, sys
import bpy, bmesh
from mathutils import Vector, Matrix

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import materials  # noqa: E402

FPS = 24
G = 9.81
GAUGE = 1.676
RAIL_C = 0.875            # half the distance between rail centres
RAIL_H = 0.172            # rail height (base on sleeper top at z = 0)
R0 = 0.4575               # nominal wheel rolling radius (915 mm new wheel)
XB = 0.800                # wheel back face (half back-to-back distance)
TAPER_REAL = 1 / 20
OBJ = {}


# ---------------------------------------------------------------- helpers
def apply_scale(o):
    bpy.ops.object.select_all(action='DESELECT'); o.select_set(True); bpy.context.view_layer.objects.active = o
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)


def box(name, mn, mx, mat, bevel=0.03, segs=2):
    c = [(a + b) / 2 for a, b in zip(mn, mx)]; s = [(b - a) / 2 for a, b in zip(mn, mx)]
    bpy.ops.mesh.primitive_cube_add(location=c); o = bpy.context.object; o.name = name; o.scale = s
    apply_scale(o); o.data.materials.append(mat)
    if bevel:
        m = o.modifiers.new('Bevel', 'BEVEL'); m.width = bevel; m.segments = segs; m.limit_method = 'ANGLE'
    return o


def cyl(name, loc, r, depth, mat, rot=(0, 0, 0), verts=32, bevel=0.02, sub=0):
    bpy.ops.mesh.primitive_cylinder_add(vertices=verts, radius=r, depth=depth, location=loc, rotation=rot)
    o = bpy.context.object; o.name = name; o.data.materials.append(mat)
    if bevel:
        m = o.modifiers.new('Bevel', 'BEVEL'); m.width = bevel; m.segments = 3; m.limit_method = 'ANGLE'
    if sub:
        s = o.modifiers.new('Sub', 'SUBSURF'); s.levels = sub; s.render_levels = sub
    for poly in o.data.polygons:
        poly.use_smooth = True
    return o


def pipe(name, a, b, r, mat, verts=20):
    """Straight closed cylinder between two points."""
    a, b = Vector(a), Vector(b); d = b - a
    o = cyl(name, (a + b) / 2, r, d.length, mat, verts=verts, bevel=0)
    o.rotation_mode = 'QUATERNION'; o.rotation_quaternion = d.to_track_quat('Z', 'Y')
    return o


def sphere(name, loc, r, mat, seg=12):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=seg, ring_count=seg // 2, radius=r, location=loc)
    o = bpy.context.object; o.name = name; o.data.materials.append(mat)
    for poly in o.data.polygons:
        poly.use_smooth = True
    return o


def hide_helper(o):
    o.hide_render = True; o.display_type = 'WIRE'; o.hide_viewport = True


def cutter(name, mn, mx, hatch):
    o = box(name, mn, mx, hatch, bevel=0); hide_helper(o); return o


def cut(obj, cut_obj, keep_material=False):
    m = obj.modifiers.new('Cut', 'BOOLEAN'); m.operation = 'DIFFERENCE'; m.solver = 'EXACT'
    m.object = cut_obj; m.material_mode = 'INDEX' if keep_material else 'TRANSFER'
    return m


def hollow(obj, inner):
    m = obj.modifiers.new('Hollow', 'BOOLEAN'); m.operation = 'DIFFERENCE'; m.solver = 'EXACT'; m.object = inner
    hide_helper(inner)


def fcurves_of(idblock):
    ad = idblock.animation_data
    if not ad or not ad.action:
        return []
    act = ad.action
    out = []
    try:
        out = list(act.fcurves)
    except Exception:
        out = []
    if out:
        return out
    for layer in getattr(act, 'layers', []):
        for strip in layer.strips:
            for cb in strip.channelbags:
                out.extend(cb.fcurves)
    return out


def ease_all(idb, interp='BEZIER'):
    for fc in fcurves_of(idb):
        for kp in fc.keyframe_points:
            kp.interpolation = interp
            kp.handle_left_type = kp.handle_right_type = 'AUTO_CLAMPED'


def key_visible(obj, frame, on):
    obj.hide_render = not on; obj.hide_viewport = not on
    obj.keyframe_insert('hide_render', frame=frame); obj.keyframe_insert('hide_viewport', frame=frame)
    for fc in fcurves_of(obj):
        if fc.data_path in ('hide_render', 'hide_viewport'):
            for kp in fc.keyframe_points:
                kp.interpolation = 'CONSTANT'


def key_mod(md, frame, on):
    md.show_render = on; md.show_viewport = on
    ob = md.id_data
    ob.keyframe_insert(data_path=f'modifiers["{md.name}"].show_render', frame=frame)
    ob.keyframe_insert(data_path=f'modifiers["{md.name}"].show_viewport', frame=frame)
    for fc in fcurves_of(ob):
        if 'modifiers' in fc.data_path:
            for kp in fc.keyframe_points:
                kp.interpolation = 'CONSTANT'


def anchor(name, loc):
    o = bpy.data.objects.new('A_' + name, None); bpy.context.collection.objects.link(o); o.location = loc
    return o


def mesh_obj(name, bm, mat, smooth=False):
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free()
    o = bpy.data.objects.new(name, me); bpy.context.collection.objects.link(o)
    if isinstance(mat, (list, tuple)):
        for m in mat:
            me.materials.append(m)
    else:
        me.materials.append(mat)
    if smooth:
        for p in me.polygons:
            p.use_smooth = True
    return o


def empty(name, loc=(0, 0, 0)):
    o = bpy.data.objects.new(name, None); bpy.context.collection.objects.link(o); o.location = loc
    return o


def parent(child, par):
    child.parent = par; child.matrix_parent_inverse = par.matrix_world.inverted()


# ---------------------------------------------------------------- track path (centreline) with curvature and cant
class Path:
    """Centreline sampled every ds metres from segments: ('straight', L) or ('arc', R, degrees, +1 left / -1 right).
    at(s) → (point, tangent, right, up) with the cross-section rolled by the cant at s (outer rail raised)."""

    def __init__(self, segments, origin=(0, 0, 0), heading_deg=90.0, ds=0.25, cant=0.0):
        self.ds = ds; self.pts = []; self.turn = []
        p = Vector(origin); h = math.radians(heading_deg)
        self.pts.append((p.copy(), h)); self.turn.append(0)
        for seg in segments:
            if seg[0] == 'straight':
                n = max(1, int(round(seg[1] / ds)))
                for _ in range(n):
                    p = p + Vector((math.cos(h), math.sin(h), 0)) * ds; self.pts.append((p.copy(), h)); self.turn.append(0)
            else:
                _, R, deg, d = seg
                n = max(1, int(round(R * math.radians(deg) / ds)))
                for _ in range(n):
                    h2 = h + d * ds / R
                    hm = (h + h2) / 2
                    p = p + Vector((math.cos(hm), math.sin(hm), 0)) * ds; h = h2
                    self.pts.append((p.copy(), h)); self.turn.append(d)
        self.length = (len(self.pts) - 1) * ds
        self.cant = cant           # metres of cant on curved parts (with a short linear ramp)

    def cant_at(self, i):
        if not self.cant:
            return 0.0
        k = int(6 / self.ds)       # 6 m ramp
        lo, hi = max(0, i - k), min(len(self.turn) - 1, i + k)
        turns = self.turn[lo:hi + 1]
        d = sum(turns) / max(1, len(turns))
        return self.cant * d       # signed: +left turn → right (outer) rail up

    def at(self, s):
        s = max(0.0, min(self.length, s)); f = s / self.ds; i = int(f); u = f - i
        j = min(i + 1, len(self.pts) - 1)
        p = self.pts[i][0].lerp(self.pts[j][0], u); h = self.pts[i][1] * (1 - u) + self.pts[j][1] * u
        t = Vector((math.cos(h), math.sin(h), 0)); right = Vector((math.sin(h), -math.cos(h), 0)); up = Vector((0, 0, 1))
        c = self.cant_at(i) * (1 - u) + self.cant_at(j) * u
        a = math.atan2(c, 2 * RAIL_C)
        right_r = right * math.cos(a) + up * math.sin(a); up_r = up * math.cos(a) - right * math.sin(a)
        return p, t, right_r, up_r


def sweep(name, frames, profile, mat, cap=True, smooth=False):
    """Sweep a closed 2D profile [(u, v)] along frames [(origin, right, up)]."""
    bm = bmesh.new(); rings = []
    for o, r, up in frames:
        rings.append([bm.verts.new(o + r * u + up * v) for u, v in profile])
    n = len(profile)
    for a, b in zip(rings, rings[1:]):
        for k in range(n):
            bm.faces.new((a[k], a[(k + 1) % n], b[(k + 1) % n], b[k]))
    if cap:
        bm.faces.new(list(reversed(rings[0]))); bm.faces.new(rings[-1])
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return mesh_obj(name, bm, mat, smooth)


def incline(profile, side):
    """Rails lean inward 1 in 20: rotate about the rail-base centre toward the track centre, then shift the rail
    outward by RAIL_H/20 so the head (where gauge is measured) stays centred on RAIL_C."""
    a = -side * math.atan(1 / 20); sh = side * RAIL_H / 20
    return [(u * math.cos(a) - v * math.sin(a) + sh, u * math.sin(a) + v * math.cos(a)) for u, v in profile]


RAIL_FOOT = [(-0.075, 0.0), (0.075, 0.0), (0.075, 0.011), (0.013, 0.034), (0.0085, 0.128), (-0.0085, 0.128), (-0.013, 0.034), (-0.075, 0.011)]
RAIL_HEAD = [(-0.0095, 0.1282), (0.0095, 0.1282), (0.036, 0.132), (0.0365, 0.160), (0.031, 0.1695), (0.016, 0.172), (-0.016, 0.172), (-0.031, 0.1695), (-0.0365, 0.160), (-0.036, 0.132)]


def rail_frames(path, s0, s1, offset, step=0.25):
    fr = []; s = s0
    while s <= s1 + 1e-6:
        p, t, r, up = path.at(s); fr.append((p + r * offset, r, up)); s += step
    return fr


RAIL_FULL = [(-0.075, 0.0), (0.075, 0.0), (0.075, 0.011), (0.013, 0.034), (0.0085, 0.124), (0.036, 0.132), (0.0365, 0.160),
             (0.031, 0.1695), (0.016, 0.172), (-0.016, 0.172), (-0.031, 0.1695), (-0.0365, 0.160), (-0.036, 0.132), (-0.0085, 0.124),
             (-0.013, 0.034), (-0.075, 0.011)]


def build_rail(name, frames, side, L, head_mat=None):
    """Rail body (web/foot material) + a thin running-surface skin on the head, so a section shows one solid shape."""
    a = sweep(name + 'Foot', frames, incline(RAIL_FULL, side), L['rail'])
    skin = [(-0.033, 0.158), (-0.0305, 0.1688), (-0.016, 0.1714), (0.016, 0.1714), (0.0305, 0.1688), (0.033, 0.158),
            (0.0368, 0.1600), (0.0313, 0.1700), (0.016, 0.1726), (-0.016, 0.1726), (-0.0313, 0.1700), (-0.0368, 0.1600)]
    b = sweep(name + 'Head', frames, incline(skin, side), head_mat or L['railHead'], smooth=False)
    return a, b


def build_track(name, path, s0, s1, L, sleepers=True, ballast=True):
    objs = []
    for side in (-1, 1):
        objs += build_rail(f'{name}Rail{"L" if side < 0 else "R"}', rail_frames(path, s0, s1, side * RAIL_C), side, L)
    if sleepers:
        bm = bmesh.new(); s = s0 + 0.3
        while s < s1:
            p, t, r, up = path.at(s)
            corners = []
            for u in (-1.375, 1.375):
                for w in (-0.125, 0.125):
                    for v in (-0.21, 0.0):
                        corners.append(p + r * u + t * w + up * v)
            vs = [bm.verts.new(c) for c in corners]
            # corners index: u(-/+) w(-/+) v(-/+) → 8 verts
            idx = lambda iu, iw, iv: vs[iu * 4 + iw * 2 + iv]
            for f in ([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)], [(0, 0, 1), (0, 1, 1), (1, 1, 1), (1, 0, 1)],
                      [(0, 0, 0), (0, 0, 1), (1, 0, 1), (1, 0, 0)], [(0, 1, 0), (1, 1, 0), (1, 1, 1), (0, 1, 1)],
                      [(0, 0, 0), (0, 1, 0), (0, 1, 1), (0, 0, 1)], [(1, 0, 0), (1, 0, 1), (1, 1, 1), (1, 1, 0)]):
                bm.faces.new([idx(*c) for c in f])
            s += 0.6
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        o = mesh_obj(name + 'Sleepers', bm, L['sleeper']); bv = o.modifiers.new('Bevel', 'BEVEL'); bv.width = 0.015; bv.segments = 2
        objs.append(o)
    if ballast:
        prof = [(-3.3, -0.62), (3.3, -0.62), (1.95, -0.05), (-1.95, -0.05)]
        objs.append(sweep(name + 'Ballast', rail_frames(path, s0, s1, 0.0, step=0.5), prof, L['ballast']))
    return objs


# ---------------------------------------------------------------- wheelset (revolved conical tread + flange)
def tread_r(x, taper):
    """Rolling radius at distance |x| from the wheelset centre (tape circle at the rail centre)."""
    return R0 - (abs(x) - RAIL_C) * taper


def wheel_profile(taper, side=1, full=True, xb=XB):
    """(x, r) closed profile of one wheel in wheelset coordinates (x along the axle, + = right).
    full=True: one piece — hub, web and rim — so a section cut is a single clean face."""
    rr = lambda x: tread_r(x, taper)
    XB = xb                                             # demo wheels may move the flange inward for more play
    ft, fh = 0.032, 0.028
    root = rr(XB + ft + 0.010)
    rim_in = R0 - 0.075
    tread = []
    x = XB + ft + 0.022
    while x < 0.930:
        tread.append((x, rr(x))); x += 0.012
    flange = [(XB + ft + 0.010, root), (XB + ft, root + fh * 0.55), (XB + ft - 0.009, root + fh), (XB + 0.006, root + fh), (XB, root + fh - 0.006)]
    if full:
        pts = [(0.760, 0.086), (0.900, 0.086), (0.900, 0.130), (0.875, 0.145), (0.875, rim_in), (0.935, rim_in),
               (0.935, rr(0.935) - 0.004)] + list(reversed(tread)) + flange + [(XB, rim_in), (min(0.835, XB + 0.035), rim_in),
               (min(0.835, XB + 0.035), 0.145), (0.760, 0.130)]
    else:
        pts = [(XB, rim_in)] + list(reversed(flange)) + tread + [(0.935, rr(0.935) - 0.004), (0.935, rim_in)]
    return [(side * x, r) for x, r in pts] if side > 0 else [(side * x, r) for x, r in reversed(pts)]


def revolve(name, prof, mat, seg=96, morph=None):
    """Revolve a closed (x, r) profile about X. morph = second profile with the same point count → shape key 'Morph'."""
    bm = bmesh.new(); rings = []
    for k in range(seg):
        a = 2 * math.pi * (k + 0.37) / seg; c, s = math.cos(a), math.sin(a)   # no vertex on the section plane
        rings.append([bm.verts.new((x, r * c, r * s)) for x, r in prof])
    n = len(prof)
    for k in range(seg):
        A, B = rings[k], rings[(k + 1) % seg]
        for i in range(n):
            bm.faces.new((A[i], A[(i + 1) % n], B[(i + 1) % n], B[i]))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    if bm.calc_volume(signed=True) < 0:            # make sure the solid points outward (clean boolean sections)
        bmesh.ops.reverse_faces(bm, faces=bm.faces)
    o = mesh_obj(name, bm, mat, smooth=True)
    if morph is not None:
        o.shape_key_add(name='Basis'); sk = o.shape_key_add(name='Morph'); n = len(prof)
        for k in range(seg):
            a = 2 * math.pi * (k + 0.37) / seg; c, s_ = math.cos(a), math.sin(a)
            for i, (x, r) in enumerate(morph):
                sk.data[k * n + i].co = (x, r * c, r * s_)
    return o


def xcyl(name, x0, x1, r, mat, verts=48):
    """Cylinder along the local X axis (the axle direction)."""
    return cyl(name, ((x0 + x1) / 2, 0, 0), r, abs(x1 - x0), mat, rot=(0, math.radians(90), 0), verts=verts, bevel=0.004)


def build_wheelset(name, L, taper=TAPER_REAL, discs=True, ticks=False, morph_taper=None, xb=XB):
    """Root empty at the axle centre (wheel-centre height). Child 'spin' rotates about X as the wheels roll.
    morph_taper: adds a 'Morph' shape key to each wheel (e.g. cylinder → cone, steep → shallow cone)."""
    root = empty(name); spin = empty(name + 'Spin'); spin.parent = root
    parts = []
    for side in (-1, 1):
        mp = wheel_profile(morph_taper, side, xb=xb) if morph_taper is not None else None
        rim = revolve(f'{name}Rim{side:+d}', wheel_profile(taper, side, xb=xb), L['tread'], morph=mp)
        parts += [rim]
        if ticks:
            parts.append(box(f'{name}Tick{side:+d}', (side * 0.93 - 0.006, -0.02, R0 - 0.20), (side * 0.93 + 0.006, 0.02, R0 - 0.08), L['glowO'], bevel=0.003))
    parts.append(xcyl(name + 'Axle', -1.08, 1.08, 0.085, L['axle']))
    if discs:
        for side in (-1, 1):
            parts.append(xcyl(f'{name}Disc{side:+d}', side * 0.30, side * 0.37, 0.32, L['axle']))
    for p in parts:
        p.parent = spin
    OBJ.setdefault('wheelsets', []).append(root)
    root['taper'] = taper
    return root


def place_on_track(obj, path, s, drift=0.0, yaw=0.0, lift=0.0):
    """Put a wheelset/bogie root on the track at arc length s: drift = sideways shift (m, + right), yaw (rad)."""
    p, t, r, up = path.at(s)
    ca, sa = math.cos(yaw), math.sin(yaw)
    r2 = r * ca + t * sa; t2 = t * ca - r * sa
    m = Matrix((r2, t2, up)).transposed()
    obj.matrix_world = Matrix.Translation(p + r * drift + up * (RAIL_H + R0 + lift)) @ m.to_4x4()


def spin_of(ws):
    return bpy.data.objects[ws.name + 'Spin']


def roll(ws, distance):
    spin_of(ws).rotation_euler = (-distance / R0, 0, 0)


# ---------------------------------------------------------------- bogie (LHB-style, simplified) + coach
def build_bogie(name, L, taper=TAPER_REAL, damper=True):
    root = empty(name)
    wsets = []
    for k, y in enumerate((1.28, -1.28)):
        ws = build_wheelset(f'{name}WS{k}', L, taper); ws.location = (0, y, 0); ws.parent = root; wsets.append(ws)
    fr = []
    for side in (-1, 1):
        x = side * 1.02
        fr.append(box(f'{name}Side{side:+d}', (x - 0.09, -2.0, 0.08), (x + 0.09, 2.0, 0.34), L['bogie'], bevel=0.03))
        for y in (1.28, -1.28):
            fr.append(box(f'{name}AxBox{side:+d}{y:+.0f}', (x - 0.12, y - 0.17, -0.12), (x + 0.12, y + 0.17, 0.12), L['bogie'], bevel=0.02))
            fr.append(spring(f'{name}Spr{side:+d}{y:+.0f}', (x, y - 0.0, 0.12), 0.09, 0.2, L['spring']))
        fr.append(spring(f'{name}Sec{side:+d}', (x, 0.0, 0.34), 0.16, 0.42, L['spring'], turns=5))
        if damper:
            d1 = cyl(f'{name}Damper{side:+d}', (side * 1.38, 0.55, 0.62), 0.055, 0.75, L['damper'], rot=(math.radians(90), 0, 0), bevel=0.01)
            d2 = cyl(f'{name}DamperRod{side:+d}', (side * 1.38, 1.05, 0.62), 0.022, 0.35, L['axle'], rot=(math.radians(90), 0, 0), bevel=0)
            fr += [d1, d2]; OBJ.setdefault('dampers', []).extend([d1, d2])
    fr.append(box(name + 'Transom', (-1.0, -0.22, 0.12), (1.0, 0.22, 0.30), L['bogie'], bevel=0.03))
    for o in fr:
        o.parent = root
    root['wheelsets'] = [w.name for w in wsets]
    return root, wsets


def spring(name, base, r, h, mat, turns=4):
    """Coil spring: a helix curve with a round bevel."""
    cu = bpy.data.curves.new(name, 'CURVE'); cu.dimensions = '3D'; cu.bevel_depth = r * 0.16; cu.bevel_resolution = 3
    sp = cu.splines.new('POLY'); n = turns * 16; sp.points.add(n)
    for i in range(n + 1):
        a = 2 * math.pi * i / 16
        sp.points[i].co = (base[0] + r * math.cos(a), base[1] + r * math.sin(a), base[2] + h * i / n, 1)
    o = bpy.data.objects.new(name, cu); bpy.context.collection.objects.link(o); cu.materials.append(mat)
    return o


COACH_L, COACH_W, BOGIE_C = 23.54, 3.24, 7.45


def build_coach_body(name, L, livery='coach'):
    """Body only, origin at track centre / wheel-centre height under the coach centre.
    coach: LHB stainless shell, red window band + cream stripe, wide tinted windows, end doors, AC roof units,
    black gangway bellows.  loco: WAP-7-style electric loco — red/cream body, flat cab fronts with two windscreens,
    headlight, two pantographs on the roof."""
    root = empty(name); parts = []
    z0, z1 = 0.80, 3.55
    if livery == 'loco':
        Lb = 20.4
        parts.append(box(name + 'Body', (-COACH_W / 2 + 0.05, -Lb / 2, z0), (COACH_W / 2 - 0.05, Lb / 2, z1 - 0.15), L['loco'], bevel=0.14, segs=3))
        for side in (-1, 1):
            x = side * (COACH_W / 2 - 0.04)
            parts.append(box(f'{name}Cream{side:+d}', (x - 0.012, -Lb / 2 + 0.2, 1.05), (x + 0.012, Lb / 2 - 0.2, 1.45), L['cream'], bevel=0))
            for k, y in enumerate((-6.5, -2.0, 2.0, 6.5)):
                parts.append(box(f'{name}Louvre{side:+d}{k}', (x - 0.014, y - 1.2, 2.05), (x + 0.014, y + 1.2, 2.65), L['bogie'], bevel=0.01))
        for end in (-1, 1):
            y = end * (Lb / 2 + 0.01)
            parts.append(box(f'{name}Face{end:+d}', (-COACH_W / 2 + 0.15, y - 0.03, 1.05), (COACH_W / 2 - 0.15, y + 0.03, 1.55), L['cream'], bevel=0.01))
            for xw in (-0.72, 0.72):
                parts.append(box(f'{name}Wind{end:+d}{xw:+.1f}', (xw - 0.6, y - 0.035, 2.15), (xw + 0.6, y + 0.035, 2.95), L['window'], bevel=0.03))
            parts.append(cyl(f'{name}Lamp{end:+d}', (0, y, 3.15), 0.13, 0.08, L['glowB'], rot=(math.radians(90), 0, 0), bevel=0))
            parts.append(box(f'{name}Buffer{end:+d}', (-0.3, y - 0.25 * end, 0.45), (0.3, y + 0.25 * end, 0.75), L['buffer'], bevel=0.03))
            # pantograph: base + two diamond arms + collector bar
            yp = end * 5.5
            parts.append(box(f'{name}PBase{end:+d}', (-0.6, yp - 0.6, z1 - 0.15), (0.6, yp + 0.6, z1 - 0.05), L['pantograph'], bevel=0.02))
            for dy in (-0.45, 0.45):
                parts.append(pipe(f'{name}PArm{end:+d}{dy:+.2f}', (0, yp + dy, z1 - 0.05), (0, yp, z1 + 0.75), 0.025, L['pantograph']))
            parts.append(box(f'{name}PBar{end:+d}', (-0.9, yp - 0.05, z1 + 0.73), (0.9, yp + 0.05, z1 + 0.8), L['pantograph'], bevel=0.01))
    else:
        parts.append(box(name + 'Body', (-COACH_W / 2, -COACH_L / 2, z0), (COACH_W / 2, COACH_L / 2, z1), L['shell'], bevel=0.12, segs=3))
        roof = cyl(name + 'Roof', (0, 0, z1 - 0.05), COACH_W / 2 - 0.02, COACH_L - 0.3, L['roof'], rot=(math.radians(90), 0, 0), verts=40, bevel=0)
        roof.scale = (1, 0.22, 1); parts.append(roof)
        for y in (-COACH_L / 2 + 2.2, COACH_L / 2 - 2.2):
            parts.append(box(f'{name}AC{y:+.0f}', (-0.9, y - 1.1, z1 + 0.15), (0.9, y + 1.1, z1 + 0.5), L['acunit'], bevel=0.06))
        for side in (-1, 1):
            x = side * (COACH_W / 2 + 0.005)
            parts.append(box(f'{name}Band{side:+d}', (x - 0.012, -COACH_L / 2 + 1.2, 1.9), (x + 0.012, COACH_L / 2 - 1.2, 2.85), L['loco'], bevel=0))
            parts.append(box(f'{name}Stripe2{side:+d}', (x - 0.013, -COACH_L / 2 + 1.2, 1.72), (x + 0.013, COACH_L / 2 - 1.2, 1.82), L['cream'], bevel=0))
            for k in range(8):
                y = -COACH_L / 2 + 3.4 + k * 2.4
                parts.append(box(f'{name}Win{side:+d}{k}', (x - 0.016, y - 0.85, 2.02), (x + 0.016, y + 0.85, 2.72), L['window'], bevel=0.03))
            for y in (-COACH_L / 2 + 1.0, COACH_L / 2 - 1.0):
                parts.append(box(f'{name}Door{side:+d}{y:+.0f}', (x - 0.016, y - 0.4, 1.0), (x + 0.016, y + 0.4, 3.0), L['stripe'], bevel=0.02))
        for end in (-1, 1):
            y = end * (COACH_L / 2 + 0.25)
            parts.append(box(f'{name}Bellows{end:+d}', (-0.75, y - 0.25, 1.0), (0.75, y + 0.25, 3.1), L['buffer'], bevel=0.05))
    for p in parts:
        p.parent = root
    return root


# ---------------------------------------------------------------- effects
SPARKS = []


class Sparks:
    """Hot sparks thrown from a contact point (callable returning (point, forward, up))."""

    def __init__(self, name, where, L, n=40, rate=1.0, t_on=-1e9, t_off=1e9, speed=2.5, size=0.006):
        self.name = name
        self.where, self.t_on, self.t_off, self.speed, self.size, self.rate = where, t_on, t_off, speed, size, rate
        rnd = random.Random(hash(name) & 0xffff)
        self.p = []
        for i in range(n):
            d = sphere(f'{name}_{i}', (0, 0, 0), 1.0, L['spark'], seg=6)
            d.visible_shadow = False
            self.p.append((d, rnd.random(), rnd.uniform(-1, 1), rnd.uniform(0.3, 1.0), rnd.uniform(0.6, 1.2)))
        SPARKS.append(self)

    def update(self, t):
        on = self.t_on <= t < self.t_off
        if t > END / 2:                                   # phase measured from the loop point → frame N joins frame 1
            t = t - END
        o, fwd, up = self.where(t)
        side = fwd.cross(up)
        for d, ph, sx, sz, sv in self.p:
            life = 0.35 * sv
            a = ((t * self.rate / life) + ph) % 1.0; tau = a * life
            v = (-fwd * 0.9 + side * sx * 0.5 + up * sz) * self.speed * sv
            pos = o + v * tau + Vector((0, 0, -0.5 * G * tau * tau))
            d.location = pos
            vel = v + Vector((0, 0, -G * tau))
            d.rotation_mode = 'QUATERNION'; d.rotation_quaternion = vel.to_track_quat('Z', 'Y')
            s = self.size * (1 - a) if on else 0.0
            d.scale = (s, s, s * 6)


def ring(name, mat, r=1.0, minor=0.012):
    bpy.ops.mesh.primitive_torus_add(major_radius=r, minor_radius=minor, major_segments=96, minor_segments=8)
    o = bpy.context.object; o.name = name; o.data.materials.append(mat); return o


def tube_curve(name, pts, r, mat):
    cu = bpy.data.curves.new(name, 'CURVE'); cu.dimensions = '3D'; cu.bevel_depth = r; cu.bevel_resolution = 3
    sp = cu.splines.new('POLY'); sp.points.add(len(pts) - 1)
    for i, p in enumerate(pts):
        sp.points[i].co = (p[0], p[1], p[2], 1)
    o = bpy.data.objects.new(name, cu); bpy.context.collection.objects.link(o); cu.materials.append(mat)
    return o


def on_frame(scene, depsgraph=None):
    t = (scene.frame_current + scene.frame_subframe - 1) / FPS
    for s in SPARKS:
        s.update(t)


# ---------------------------------------------------------------- world
def build_world(L):
    sc = bpy.context.scene
    w = bpy.data.worlds.new('Sky'); sc.world = w; w.use_nodes = True
    nt = w.node_tree; bg = nt.nodes['Background']; bg.inputs['Strength'].default_value = 0.6
    tcw = nt.nodes.new('ShaderNodeTexCoord'); sep = nt.nodes.new('ShaderNodeSeparateXYZ'); mr = nt.nodes.new('ShaderNodeMapRange')
    ramp = nt.nodes.new('ShaderNodeValToRGB')
    mr.inputs['From Min'].default_value = -0.02; mr.inputs['From Max'].default_value = 0.42
    nt.links.new(tcw.outputs['Generated'], sep.inputs[0]); nt.links.new(sep.outputs['Z'], mr.inputs['Value'])
    nt.links.new(mr.outputs['Result'], ramp.inputs['Fac'])
    ramp.color_ramp.elements[0].color = (0.86, 0.78, 0.64, 1); ramp.color_ramp.elements[1].color = (0.24, 0.47, 0.78, 1)
    nt.links.new(ramp.outputs['Color'], bg.inputs['Color'])
    bpy.ops.object.light_add(type='SUN', location=(0, 0, 30)); sun = bpy.context.object; sun.name = 'Sun'
    sun.data.energy = 5.5; sun.data.color = (1.0, 0.82, 0.62); sun.data.angle = math.radians(3)
    sun.rotation_euler = (math.radians(58), 0, math.radians(-35))
    bpy.ops.mesh.primitive_plane_add(size=20000, location=(0, 0, -0.62)); g = bpy.context.object; g.name = 'Ground'   # covers every set (up to 6 km out)
    g.data.materials.append(L['sand'])


# ---------------------------------------------------------------- sets (each lives in its own patch of the world)
SET = {}


CURVE_START, CURVE_R, CURVE_DEG = 620.0, 420.0, 45.0      # entry of the first (left-hand) curve of the S


def set_curve(L, coaches=24, hero_s=None):
    """Set A: 620 m straight → 300 m-radius left curve over 120° (cant 0.12 m) → straight.
    A loco + `coaches` coaches; hero_s = arc length of the first coach (behind the loco)."""
    path = Path([('straight', CURVE_START), ('arc', CURVE_R, CURVE_DEG, +1), ('straight', 60), ('arc', CURVE_R, 55, -1),
                 ('straight', 260)], origin=(0, -CURVE_START, 0), heading_deg=90, cant=0.12)
    build_track('A', path, 0, path.length, L)
    SET['A'] = dict(path=path)
    # hero coach (index 0, behind the loco) gets real bogies; the rest are instanced
    hero_s = CURVE_START + 6.0 if hero_s is None else hero_s
    bog = []
    for k, off in enumerate((BOGIE_C, -BOGIE_C)):
        b, ws = build_bogie(f'HeroBogie{k}', L); place_on_track(b, path, hero_s + off); bog.append((b, ws))
    body = build_coach_body('HeroBody', L)
    place_body(body, path, hero_s)
    SET['A'].update(hero_s=hero_s, bogies=bog, body=body)
    # loco ahead of the hero coach
    loco = build_coach_body('Loco', L, livery='loco'); place_body(loco, path, hero_s + 22.5)
    for k, off in enumerate((BOGIE_C - 1.5, -BOGIE_C + 1.5)):
        b, _ = build_bogie(f'LocoBogie{k}', L, damper=False); place_on_track(b, path, hero_s + 22.5 + off)
    SET['A']['loco'] = loco
    # instanced coaches behind (static geometry is plenty at that distance)
    col = bpy.data.collections.new('CoachInst'); bpy.context.scene.collection.children.link(col)
    prev = bpy.context.view_layer.active_layer_collection
    bpy.context.view_layer.active_layer_collection = bpy.context.view_layer.layer_collection.children['CoachInst']
    cb = build_coach_body('InstBody', L)
    for k, off in enumerate((BOGIE_C, -BOGIE_C)):
        b, _ = build_bogie(f'InstBogie{k}', L, damper=True); b.location = (0, off, 0)
        b.parent = cb
    bpy.context.view_layer.active_layer_collection = prev
    col.hide_render = False
    excl = bpy.context.view_layer.layer_collection.children['CoachInst']; excl.exclude = True
    insts = []
    for i in range(1, coaches):
        s = hero_s - 24.0 * i
        if s - BOGIE_C < 1:
            break
        o = bpy.data.objects.new(f'Coach{i}', None); o.instance_type = 'COLLECTION'; o.instance_collection = col
        bpy.context.collection.objects.link(o); place_body(o, path, s); insts.append(o)
    SET['A']['insts'] = insts
    return path


def place_body(obj, path, s):
    """Coach body follows the chord between its two bogie centres."""
    pa, _, _, ua = path.at(s + BOGIE_C); pb, _, _, ub = path.at(s - BOGIE_C)
    fwd = (pa - pb).normalized(); up = (ua + ub).normalized(); right = fwd.cross(up).normalized(); up = right.cross(fwd)
    m = Matrix((right, fwd, up)).transposed().to_4x4()
    obj.matrix_world = Matrix.Translation((pa + pb) / 2 + up * (RAIL_H + R0)) @ m


def set_demo(L, origin=(0, 3000, 0), taper=1 / 5, drift=0.0, section=True, rings=True, xb=XB, key='B', morph_taper=None,
             ticks=True, length=16.0, ws_s=1.4):
    """A lone wheelset on a short straight track (front view), optional half-section cut and rolling rings.
    key prefixes every object so several demo rigs can coexist; SET[key] holds the handles."""
    path = Path([('straight', length)], origin=origin, heading_deg=90)
    build_track(key, path, 0.0, length, L, ballast=False)
    for o in list(bpy.data.objects):                      # demo rails: one solid steel body (no head skin → clean section)
        if o.name.startswith(key + 'Rail') and o.name.endswith('Head'):
            bpy.data.objects.remove(o, do_unlink=True)
        elif o.name.startswith(key + 'Rail') and o.name.endswith('Foot'):
            o.data.materials[0] = L['railHead']
    ws = build_wheelset(key + 'WS', L, taper=taper, discs=False, ticks=ticks, xb=xb, morph_taper=morph_taper)
    place_on_track(ws, path, ws_s, drift=drift, lift=-0.0012)          # seated on the railhead: no visible gap
    SET[key] = dict(path=path, ws=ws, taper=taper, drift=drift, s=ws_s, morph=morph_taper, rings={})
    if section:
        c = cutter(key + 'Cut', (-1.3, -1.5, -0.7), (1.3, 0.0, 0.7), L['hatch'])
        bpy.context.view_layer.update()
        c.matrix_world = ws.matrix_world @ Matrix.Translation((0, -0.75, 0)); parent(c, ws)
        for o in spin_of(ws).children:
            if 'Rim' in o.name:
                cut(o, c)
        p0, t0, r0, u0 = path.at(ws_s)
        tc = cutter(key + 'TrackCut', (p0.x - 4, p0.y - 6, -1.0), (p0.x + 4, p0.y, 1.0), L['hatchRail'])
        for o in list(bpy.data.objects):
            if o.name.startswith(key + 'Rail'):
                cut(o, tc)
            elif o.name.startswith(key + 'Sleepers'):
                cut(o, tc, keep_material=True)
    if rings:
        for side in (-1, 1):
            rg = ring(f'{key}Ring{side:+d}', L['glowO'], r=1.0, minor=0.006)
            rg.rotation_euler = (0, math.radians(90), 0); rg.parent = ws
            SET[key]['rings'][side] = rg
        demo_pose(key, drift, taper)
    return path


def demo_pose(key, drift, taper, lift=-0.0012, roll_dist=None):
    """Re-seat a demo wheelset: sideways drift and current taper (rings follow the contact circles)."""
    D = SET[key]; ws = D['ws']
    place_on_track(ws, D['path'], D['s'], drift=drift, lift=lift)
    for side, rg in D['rings'].items():
        x = side * RAIL_C - drift
        r = tread_r(x, taper)
        rg.location = (x, 0, 0); s_ = r / 1.0; rg.scale = (s_, s_, s_)
        rg.hide_render = taper <= 0.0
    if roll_dist is not None:
        roll(ws, roll_dist)


def set_turnout(L, origin=(3000, 0, 0), u=1.0, R=120.0, throw=0.11):
    """Set C: right-hand turnout. u = 0 straight route set, 1 diverging route set (switch rails slide together)."""
    ox, oy, oz = origin
    xc = lambda y: (R - math.sqrt(max(0.0, R * R - y * y))) if y > 0 else 0.0
    hd = lambda y: math.atan2(y, math.sqrt(max(1e-6, R * R - y * y))) if y > 0 else 0.0

    def frames(fx, y0, y1, step=0.25, dx=lambda y: 0.0, curved=False):
        out = []; y = y0
        while y <= y1 + 1e-6:
            x = fx(y) + dx(y); a = hd(y) if curved else 0.0
            right = Vector((math.cos(a), -math.sin(a), 0)); out.append((Vector((ox + x, oy + y, oz)), right, Vector((0, 0, 1)))); y += step
        return out

    toe, heel = 0.0, 10.0
    rails = []
    rails += build_rail('TStockL', frames(lambda y: -RAIL_C, -16, 34), -1, L)
    rails += build_rail('TStockR', frames(lambda y: xc(y) + RAIL_C, -16, 34, curved=True), 1, L)
    open_l = lambda y: throw * (1 - u) * max(0.0, 1 - y / heel)
    open_r = lambda y: -throw * u * max(0.0, 1 - y / heel)
    bl = build_rail('TBladeL', frames(lambda y: xc(y) - RAIL_C, toe, heel, dx=open_l, curved=True), 1, L, head_mat=L['glowO'])
    br = build_rail('TBladeR', frames(lambda y: RAIL_C, toe, heel, dx=open_r), -1, L, head_mat=L['glowO'])   # moving parts glow
    rails += list(bl) + list(br)
    rails += build_rail('TClosureR', frames(lambda y: RAIL_C, heel, 19.6), -1, L)
    rails += build_rail('TClosureL', frames(lambda y: xc(y) - RAIL_C, heel, 19.6, curved=True), 1, L)
    rails += build_rail('TExitR', frames(lambda y: RAIL_C, 21.4, 34), -1, L)
    rails += build_rail('TExitL', frames(lambda y: xc(y) - RAIL_C, 21.4, 34, curved=True), 1, L)
    # timbers
    bm = bmesh.new(); y = -15.7
    while y < 34:
        x0, x1 = -1.45, xc(y) + 1.45 if y > 0 else 1.45
        x1 = max(1.45, xc(y) + 1.45)
        vs = [bm.verts.new((ox + x, oy + yy, z)) for x in (x0, x1) for yy in (y - 0.125, y + 0.125) for z in (-0.21, 0.0)]
        idx = lambda a, b, c: vs[a * 4 + b * 2 + c]
        for f in ([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)], [(0, 0, 1), (0, 1, 1), (1, 1, 1), (1, 0, 1)],
                  [(0, 0, 0), (0, 0, 1), (1, 0, 1), (1, 0, 0)], [(0, 1, 0), (1, 1, 0), (1, 1, 1), (0, 1, 1)],
                  [(0, 0, 0), (0, 1, 0), (0, 1, 1), (0, 0, 1)], [(1, 0, 0), (1, 0, 1), (1, 1, 1), (1, 1, 0)]):
            bm.faces.new([idx(*c) for c in f])
        y += 0.6
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces); tim = mesh_obj('TTimbers', bm, L['sleeper'])
    box('TBallast', (ox - 3.4, oy - 17, oz - 0.62), (ox + 7.5, oy + 35, oz - 0.05), L['ballast'], bevel=0.3)
    # stretcher bars + point machine (move with the switch rails)
    for k, y in enumerate((0.35, 1.6)):
        dx = (open_l(y) + open_r(y)) / 2
        box(f'TStretch{k}', (ox - RAIL_C - 0.02 + dx, oy + y - 0.03, oz + 0.02), (ox + RAIL_C + 0.02 + dx, oy + y + 0.03, oz + 0.06), L['axle'], bevel=0.005)
    box('TMachine', (ox - 2.45, oy - 0.1, oz - 0.05), (ox - 1.55, oy + 0.8, oz + 0.35), L['machine'], bevel=0.05)
    pipe('TMachineRod', (ox - 1.55, oy + 0.35, oz + 0.04), (ox - RAIL_C + (open_l(0.35) + open_r(0.35)) / 2, oy + 0.35, oz + 0.04), 0.015, L['axle'])
    SET['C'] = dict(origin=Vector(origin), xc=xc, hd=hd, R=R)
    return SET['C']


def place_on_turnout(obj, ystation, diverging=True):
    C = SET['C']; o = C['origin']
    x = C['xc'](ystation) if diverging else 0.0; a = C['hd'](ystation) if diverging else 0.0
    right = Vector((math.cos(a), -math.sin(a), 0)); fwd = Vector((math.sin(a), math.cos(a), 0)); up = Vector((0, 0, 1))
    obj.matrix_world = Matrix.Translation(o + Vector((x, ystation, RAIL_H + R0))) @ Matrix((right, fwd, up)).transposed().to_4x4()


HUNT_L = 17.4                                      # kinematic wavelength 2π√(r0·b/λ) for λ = 1/20


def hunt_offset(s, s0=0.0, a0=0.003, grow=0.06, amax=0.0385):
    a = min(amax, a0 * math.exp(grow * max(0.0, s - s0)))
    return a * math.sin(2 * math.pi * (s - s0) / HUNT_L), a


def set_hunting(L, origin=(-3000, 0, 0), s_now=70.0, trail_gain=16.0):
    """Set D: straight track; a bogie whose sideways swing grows (hunting); glowing zig-zag trail behind it."""
    path = Path([('straight', 120)], origin=origin, heading_deg=90)
    build_track('D', path, 0, 120, L)
    b, ws = build_bogie('HuntBogie', L)
    d, a = hunt_offset(s_now)
    yaw = (hunt_offset(s_now + 0.05)[0] - hunt_offset(s_now - 0.05)[0]) / 0.1
    place_on_track(b, path, s_now, drift=d, yaw=-math.atan(yaw))
    pts = []; s = 2.0
    while s <= s_now - 1.28:
        p, t, r, up = path.at(s); dd, _ = hunt_offset(s)
        pts.append(tuple(p + r * dd * trail_gain + up * (RAIL_H + 0.03))); s += 0.2
    tr = tube_curve('HuntTrail', pts, 0.05, L['glowO'])
    SET['D'] = dict(path=path, bogie=b, ws=ws, s=s_now, drift=d, amp=a, trail=tr)
    return path


# ---------------------------------------------------------------- camera + render
def taper_marker(ws, taper, L, y=-0.004):
    """On the section plane: dashed horizontal reference line, a slope line along the tread, and an angle arc."""
    m = ws.matrix_world
    x0, x1 = 0.858, 1.02
    z = lambda x: -tread_r(x, taper) - 0.004                # just under the tread line (wheel bottom = contact side)
    p0 = Vector((x0, y, z(x0)))
    k = 0; x = x0
    while x < x1:                                          # dashed reference (horizontal)
        xa, xb = x, min(x + 0.012, x1)
        tube_curve(f'RefDash{k}', [tuple(m @ Vector((xa, y, z(x0)))), tuple(m @ Vector((xb, y, z(x0))))], 0.0016, L['dash'])
        x += 0.020; k += 1
    tube_curve('TaperLine', [tuple(m @ p0), tuple(m @ Vector((x1, y, z(x1))))], 0.0022, L['glowO'])
    ang = math.atan(taper); arc = []
    for i in range(13):
        a = ang * i / 12; rad = 0.07
        arc.append(tuple(m @ Vector((x0 + rad * math.cos(a), y, z(x0) + rad * math.sin(a)))))
    tube_curve('TaperArc', arc, 0.0016, L['glowO'])
    SET['taper_label'] = m @ Vector((x1, y, z(x1)))


def fill_light(at, target, power=60.0, size=1.5):
    """Soft area fill from the camera side: lifts the shadowed wedge between flange, tread and railhead."""
    bpy.ops.object.light_add(type='AREA', location=at); l = bpy.context.object; l.name = 'Fill'
    l.data.energy = power; l.data.size = size; l.data.color = (1.0, 0.95, 0.9)
    l.rotation_mode = 'QUATERNION'; l.rotation_quaternion = (Vector(target) - Vector(at)).to_track_quat('-Z', 'Y')
    l.visible_camera = False
    return l


def make_camera(loc, target, lens=35, fstop=5.6, focus=None):
    sc = bpy.context.scene
    tgt = empty('CamTarget', target)
    bpy.ops.object.camera_add(location=loc); cam = bpy.context.object; cam.name = 'Cam'; sc.camera = cam
    con = cam.constraints.new('TRACK_TO'); con.target = tgt; con.track_axis = 'TRACK_NEGATIVE_Z'; con.up_axis = 'UP_Y'
    cam.data.lens = lens; cam.data.sensor_width = 36; cam.data.clip_start = 0.02; cam.data.clip_end = 3000
    cam.data.dof.use_dof = True; cam.data.dof.aperture_fstop = fstop
    fo = empty('CamFocus', focus if focus is not None else target); cam.data.dof.focus_object = fo
    return cam


def setup_render(a):
    sc = bpy.context.scene
    sc.render.fps = FPS
    sc.render.resolution_x, sc.render.resolution_y, sc.render.resolution_percentage = a.w, a.h, 100
    sc.render.image_settings.file_format = 'PNG'
    sc.view_settings.view_transform = 'AgX'
    looks = [i.identifier for i in sc.view_settings.bl_rna.properties['look'].enum_items]
    for want in ('AgX - Medium High Contrast', 'AgX - Base Contrast'):
        if want in looks:
            sc.view_settings.look = want; break
    if a.engine == 'WORKBENCH':
        sc.render.engine = 'BLENDER_WORKBENCH'
        sh = sc.display.shading; sh.light = 'STUDIO'; sh.color_type = 'MATERIAL'; sh.show_shadows = False; sh.show_cavity = False   # CPU GL: shadows+cavity cost ~30 s/frame
        sc.render.use_motion_blur = False
    else:
        sc.render.engine = 'CYCLES'
        sc.cycles.device = 'CPU'; sc.cycles.samples = a.samples; sc.cycles.use_adaptive_sampling = True
        sc.cycles.use_denoising = True; sc.cycles.denoiser = 'OPENIMAGEDENOISE'
        sc.cycles.max_bounces = 8; sc.cycles.glossy_bounces = 3; sc.cycles.transmission_bounces = 6
        sc.cycles.caustics_reflective = False; sc.cycles.caustics_refractive = False
        sc.render.use_motion_blur = not a.no_blur; sc.render.motion_blur_shutter = 0.5
        sc.render.motion_blur_position = 'START'


# ---------------------------------------------------------------- style frames
def contact_point(ws, side):
    """World-space contact point of a wheelset's wheel (side -1 left, +1 right) on its rail."""
    m = ws.matrix_world
    return m @ Vector((side * RAIL_C, 0, -R0)), (m.to_3x3() @ Vector((0, 1, 0))).normalized(), (m.to_3x3() @ Vector((0, 0, 1))).normalized()


def xray_wheels(ws_list, L):
    """Swap wheel materials to the X-ray look and add a glowing cone-profile outline through each wheel."""
    for ws in ws_list:
        for o in spin_of(ws).children:
            if o.type == 'MESH' and 'Rim' in o.name:
                o.hide_render = True
            elif o.type == 'MESH' and any(k in o.name for k in ('Web', 'Hub', 'Axle', 'Disc')):
                o.data.materials.clear(); o.data.materials.append(L['xray'])
        for side in (-1, 1):                              # X-ray reveals the cone: an exaggerated glowing rim
            gr = revolve(f'{ws.name}XCone{side:+d}', wheel_profile(1 / 2.5, side), L['glowO'])
            gr.matrix_world = ws.matrix_world.copy()
        for side in ():
            prof = wheel_profile(ws.get('taper', TAPER_REAL), side)
            for sgn in (1, -1):
                pts = [(x, 0.0, sgn * r) for x, r in prof] + [(prof[0][0], 0.0, sgn * prof[0][1])]
                pts_w = [tuple(ws.matrix_world @ Vector(p)) for p in pts]
                tube_curve(f'{ws.name}Prof{side:+d}{sgn:+d}', pts_w, 0.012, L['glowO'])


def style(name, L):
    sc = bpy.context.scene
    if name in ('hook', 'teaser'):
        path = set_curve(L, coaches=24)
        b, ws = SET['A']['bogies'][0]
        lead = bpy.data.objects[b['wheelsets'][0]]
        for w in ws:
            roll(w, 3.1)
        cp, fwd, up = contact_point(lead, -1)                      # left = inner rail on this left-hand curve
        Sparks('HookSparks', lambda t: (cp, fwd, up), L, n=90, speed=2.6, size=0.016)
        p, t, r, u = path.at(SET['A']['hero_s'] + BOGIE_C + 1.28)
        if name == 'hook':
            cam = p + t * 1.75 - r * 1.45 + u * 0.42
            make_camera(cam, cp + up * 0.30 + r * 0.10, lens=24, fstop=4.0, focus=cp + up * 0.3)
        else:
            xray_wheels(ws, L)
            cam = p + t * 2.6 - r * 2.6 + u * 1.05
            make_camera(cam, p + u * 0.62 - r * 0.2, lens=24, fstop=8.0)
    elif name == 'wide24':
        s_front = CURVE_START + CURVE_R * math.radians(CURVE_DEG) + 60 + CURVE_R * math.radians(30)   # loco in the 2nd curve
        path = set_curve(L, coaches=24, hero_s=s_front - 22.5)
        p, t, r, u = path.at(s_front + 10)
        make_camera(p - r * 11 + u * 8.5, path.at(s_front - 190)[0] + u * 1.5, lens=30, fstop=16)
    elif name == 'cone_close':
        set_demo(L, taper=1 / 2.5, drift=0.0, section=True, rings=False, xb=0.762)
        ws = SET['B']['ws']; m = ws.matrix_world
        taper_marker(ws, 1 / 2.5, L)
        make_camera(m @ Vector((0.66, -0.95, -0.24)), m @ Vector((0.86, 0, -0.40)), lens=60, fstop=11)
        fill_light(m @ Vector((0.5, -0.8, -0.35)), m @ Vector((0.86, 0, -0.44)), power=25)
    elif name == 'cone':
        set_demo(L, taper=1 / 2.5, drift=0.035, section=True, rings=True, xb=0.762)    # play exaggerated with the taper
        ws = SET['B']['ws']; m = ws.matrix_world
        make_camera(m @ Vector((0.0, -3.2, 0.55)), m @ Vector((0.0, 0, -0.12)), lens=28, fstop=11)
    elif name == 'flange':
        set_demo(L, taper=TAPER_REAL, drift=0.0068, section=True, rings=False)   # real play ≈ 7 mm: flange face meets the gauge face
        ws = SET['B']['ws']
        cp, fwd, up = contact_point(ws, 1)
        flange_pt = ws.matrix_world @ Vector((XB + 0.030, 0.0, -R0 + 0.006))
        Sparks('FlangeSparks', lambda t: (flange_pt, -fwd, up), L, n=140, speed=1.3, size=0.0035)
        m = ws.matrix_world
        make_camera(m @ Vector((0.62, -1.15, -0.22)), m @ Vector((0.84, 0.0, -0.42)), lens=70, fstop=8)
        fill_light(m @ Vector((0.5, -0.8, -0.35)), m @ Vector((0.84, 0, -0.44)), power=25)
        bpy.ops.object.light_add(type='POINT', location=m @ Vector((0.825, -0.06, -0.452)))   # lights the flange throat
        gl = bpy.context.object; gl.data.energy = 1.5; gl.data.shadow_soft_size = 0.01; gl.visible_camera = False
    elif name == 'switch':
        set_turnout(L, u=1.0)
        ws = build_wheelset('TurnWS', L, discs=True)
        place_on_turnout(ws, 6.0, diverging=True)
        o = SET['C']['origin']
        make_camera(o + Vector((-2.6, -3.2, 1.55)), o + Vector((0.25, 3.0, 0.05)), lens=26, fstop=8)
    elif name == 'hunting':
        set_hunting(L, s_now=72.0)
        D = SET['D']; p, t, r, u = D['path'].at(D['s'])
        lead = bpy.data.objects[D['bogie']['wheelsets'][0]]
        cp, fwd, up = contact_point(lead, 1 if D['drift'] > 0 else -1)
        Sparks('HuntSparks', lambda tt: (cp, fwd, up), L, n=60, speed=2.6)
        make_camera(p + t * 9.0 + r * 2.0 + u * 5.2, p - t * 3.5 + u * 0.2, lens=24, fstop=11)
    bpy.app.handlers.frame_change_pre.clear(); bpy.app.handlers.frame_change_pre.append(on_frame)


# ================================================================ ANIMATION (shot timeline driven by numeric cues)
# >>> CUES (generated — numbers only)
EV = {"XRAY": [7.401, 8.001], "TWENTY": 19.401, "MORPH": 18.485, "HUNT_LABEL": 36.275, "SLAM": 38.367, "DAMPER": 42.216, "NUDGE": 9999.0, "THROW": 9999.0, "CANT": 9999.0, "GRIND": 9999.0}
SHOTS = [{"name": "H1", "t0": 0.0, "t1": 2.75}, {"name": "H2", "t0": 2.75, "t1": 4.151}, {"name": "H3", "t0": 4.151, "t1": 7.049}, {"name": "H4", "t0": 7.049, "t1": 8.001}, {"name": "P1", "t0": 8.001, "t1": 10.025}, {"name": "P2a", "t0": 10.025, "t1": 11.453}, {"name": "P2b", "t0": 11.453, "t1": 13.902}, {"name": "P3a", "t0": 13.902, "t1": 15.448}, {"name": "P3b", "t0": 15.448, "t1": 16.98}, {"name": "C1", "t0": 16.98, "t1": 19.401}, {"name": "C2", "t0": 19.401, "t1": 21.057}, {"name": "C3", "t0": 21.057, "t1": 22.465}, {"name": "C4a", "t0": 22.465, "t1": 24.75}, {"name": "C4b", "t0": 24.75, "t1": 26.344}, {"name": "C5a", "t0": 26.344, "t1": 28.502}, {"name": "C5b", "t0": 28.502, "t1": 30.149}, {"name": "T1", "t0": 30.149, "t1": 32.077}, {"name": "T2", "t0": 32.077, "t1": 33.968}, {"name": "T3a", "t0": 33.968, "t1": 35.062}, {"name": "T3b", "t0": 35.062, "t1": 36.275}, {"name": "T4", "t0": 36.275, "t1": 37.867}, {"name": "T5a", "t0": 37.867, "t1": 39.578}, {"name": "X3", "t0": 39.578, "t1": 42.1}, {"name": "X1", "t0": 42.1, "t1": 43.02}, {"name": "X2", "t0": 43.02, "t1": 44.167}, {"name": "Z1", "t0": 44.167, "t1": 45.674}, {"name": "M1", "t0": 45.674, "t1": 46.424}, {"name": "M2", "t0": 46.424, "t1": 47.174}, {"name": "M3", "t0": 47.174, "t1": 48.024}, {"name": "Z2", "t0": 48.024, "t1": 49.917}]
END = 49.916666666666664
# <<< CUES
ORG = dict(B=(0, 6000, 0), R=(0, 6100, 0), L=(0, 6200, 0), F=(6000, 6000, 0), C=(6000, 0, 0), D=(-6000, 0, 0),
           E=(0, -6000, 0), H=(-6000, 6000, 0))
CUT50 = 'MORPH' in EV          # 50 s cut (word-timed C1 morph, X3 shallow-cone morph, montage); else the 116 s cut
ALIAS = {'M1': ('C2', 0.45, 1.0), 'M2': ('C5b', 0.2, 1.0), 'M3': ('X2', 0.0, 0.9)}   # montage → (rig shot, from, to)
V_A = 8.0                      # set-A train speed (m/s)
V_D = 25.0                     # hunting-set speed (m/s)
S0_H1 = CURVE_START + 30.0     # hero-coach arc length at frame 1 (lead wheelset well into the canted curve)
ANIM = {}


def shot_at_frame(f):
    for sh in SHOTS:
        if int(round(sh['t0'] * FPS)) + 1 <= f < int(round(sh['t1'] * FPS)) + 1:
            return sh
    return SHOTS[-1]


def eo(u):
    u = max(0.0, min(1.0, u)); return 1 - (1 - u) ** 3


def eio(u):
    u = max(0.0, min(1.0, u)); return u * u * (3 - 2 * u)


def lerp(a, b, u):
    return a + (b - a) * u


# ---------------------------------------------------------------- extra rigs
def build_cab(L):
    """Driver desk with two levers + windscreen frame; moved to the loco front each frame."""
    root = empty('Cab')
    parts = [box('CabFloor', (-1.62, -2.4, 0.9), (1.62, 0.45, 1.0), L['bogie'], bevel=0.02),
             box('CabDesk', (-1.45, -0.55, 1.0), (1.45, 0.25, 1.95), L['shell'], bevel=0.06),
             box('CabDeskTop', (-1.4, -0.52, 1.93), (1.4, 0.22, 1.97), L['bogie'], bevel=0.02),
             box('CabPanel', (-1.3, 0.05, 1.95), (1.3, 0.35, 2.25), L['stripe'], bevel=0.03),
             box('CabThrottleSlot', (-0.58, -0.42, 1.96), (-0.32, 0.02, 2.0), L['buffer'], bevel=0.008),
             pipe('CabThrottle', (-0.45, -0.22, 1.98), (-0.45, -0.12, 2.32), 0.026, L['axle']),
             sphere('CabThrottleKnob', (-0.45, -0.12, 2.35), 0.07, L['spring']),
             box('CabBrakeBase', (0.30, -0.32, 1.96), (0.60, -0.02, 2.02), L['buffer'], bevel=0.01),
             pipe('CabBrake', (0.45, -0.17, 2.0), (0.54, -0.02, 2.30), 0.026, L['axle']),
             sphere('CabBrakeKnob', (0.55, -0.01, 2.33), 0.07, L['damper'])]
    for k, x in enumerate((-0.95, 0.95)):
        g = cyl(f'CabGauge{k}', (x, 0.12, 2.1), 0.11, 0.03, L['dial'] if 'dial' in L else L['shell'], rot=(math.radians(70), 0, 0), bevel=0.005)
        parts.append(g)
    for x in (-1.55, 1.55):
        parts.append(box(f'CabPillar{x:+.1f}', (x - 0.07, 0.35, 1.0), (x + 0.07, 0.45, 3.2), L['loco'], bevel=0.02))
    parts.append(box('CabTop', (-1.62, 0.3, 3.15), (1.62, 0.5, 3.35), L['loco'], bevel=0.02))
    for p in parts:
        p.parent = root
    for nm, loc in (('CabThrottle', (-0.45, -0.12, 2.35)), ('CabBrake', (0.55, -0.01, 2.33))):
        anchor(nm, loc).parent = root
    ANIM['cab'] = root


def set_lift(L):
    """Lift rig: a bogie on straight track; its frame rises off the leading wheelset (exploded view); flange glow rings."""
    key = 'L'; path = Path([('straight', 40)], origin=ORG['L'], heading_deg=90)
    build_track(key, path, 0, 40, L)
    b, ws = build_bogie('LiftBogie', L)
    place_on_track(b, path, 12.0)
    lead = bpy.data.objects[b['wheelsets'][0]]
    # ticks on both wheels (same angle) to show they turn together
    for side in (-1, 1):
        t = box(f'LiftTick{side:+d}', (side * 0.94 - 0.008, -0.025, R0 - 0.21), (side * 0.94 + 0.008, 0.025, R0 - 0.02), L['glowO'], bevel=0.004)
        t.parent = spin_of(lead); t.matrix_parent_inverse = Matrix.Identity(4)
        fl = [(x, r) for x, r in wheel_profile(TAPER_REAL, side, full=False)[:7]] if side > 0 else None
    # flange glow: thin ring at the flange tip on each wheel
    for side in (-1, 1):
        g = ring(f'LiftFlange{side:+d}', L['glowO'], r=R0 + 0.026, minor=0.012)
        g.rotation_euler = (0, math.radians(90), 0); g.location = (side * (XB + 0.016), 0, 0); g.parent = spin_of(lead)
        ANIM.setdefault('flange_glow', []).append(g)
    frame = [o for o in b.children if o.type != 'EMPTY']
    ANIM['lift'] = dict(path=path, bogie=b, lead=lead, frame=frame, base={o.name: o.location.copy() for o in frame})


def set_topcurve(L):
    """Set F: tight curve seen from above — measuring lines along both rails, equal-length arcs, an exaggerated
    wheelset rolling round it."""
    R = 18.0
    path = Path([('straight', 6), ('arc', R, 110, +1), ('straight', 6)], origin=ORG['F'], heading_deg=90)
    build_track('F', path, 0, path.length, L)
    s_a, s_b = 6 + R * math.radians(15), 6 + R * math.radians(75)

    def line(name, off, s0, s1, mat, r=0.025, lift=RAIL_H + 0.05):
        pts = []; s = s0
        while s <= s1 + 1e-6:
            p, t, rr, up = path.at(s); pts.append(tuple(p + rr * off + up * lift)); s += 0.25
        o = tube_curve(name, pts, r, mat); return o
    outer = line('FMeasOut', RAIL_C, s_a, s_b, L['glowO'])       # left-hand curve → right rail is the outer rail
    inner = line('FMeasIn', -RAIL_C, s_a, s_b, L['glowB'])
    turn = 2 * math.pi * R0                                         # one wheel turn of rolling
    # equal arc lengths from the same radial line: angle on each rail = turn / radius
    ang_out, ang_in = turn / (R + RAIL_C), turn / (R - RAIL_C)
    s_start = 6 + R * math.radians(30)
    arc_out = line('FTurnOut', RAIL_C, s_start, s_start + ang_out * R, L['glowO'], r=0.04, lift=RAIL_H + 0.09)
    arc_in = line('FTurnIn', -RAIL_C, s_start, s_start + ang_in * R, L['glowB'], r=0.04, lift=RAIL_H + 0.09)
    gap = line('FGap', RAIL_C, s_start + ang_out * R, s_start + ang_in * R, L['spark'], r=0.05, lift=RAIL_H + 0.09)
    for o in (outer, inner, arc_out, arc_in, gap):
        o.data.bevel_factor_mapping_end = 'SPLINE'
    ws = build_wheelset('FWS', L, taper=1 / 2.5, discs=False, xb=0.762)
    rings = {}
    for side in (-1, 1):
        rg = ring(f'FRing{side:+d}', L['glowO'] if side > 0 else L['glowB'], r=1.0, minor=0.02)
        rg.rotation_euler = (0, math.radians(90), 0); rg.parent = ws; rings[side] = rg
    ANIM['F'] = dict(path=path, R=R, outer=outer, inner=inner, arc_out=arc_out, arc_in=arc_in, gap=gap, ws=ws, rings=rings,
                     s_a=s_a, s_b=s_b, s_start=s_start, ang_in=ang_in)
    for k, (side, s) in enumerate(((1, (s_a + s_b) / 2), (-1, (s_a + s_b) / 2))):
        p, t, rr, up = path.at(s); anchor('F' + ('outer' if side > 0 else 'inner'), p + rr * side * (RAIL_C + 0.9) + up * 0.3)
    p, t, rr, up = path.at(s_start + ang_out * R); anchor('Fgap', p + rr * (RAIL_C + 0.8) + up * 0.3)


def set_turnout_anim(L):
    """Turnout with switch rails that slide (rotate about their heels); u(t) = 0 straight, 1 diverging."""
    C = set_turnout(L, origin=ORG['C'], u=0.5, throw=0.0)            # blades built in their closed shape
    o = C['origin']
    piv = {}
    for nm, side in (('TBladeL', -1), ('TBladeR', 1)):
        heel_x = (C['xc'](10.0) - RAIL_C) if side < 0 else RAIL_C
        pv = empty(nm + 'Pivot', (o.x + heel_x, o.y + 10.0, o.z))
        for suf in ('Foot', 'Head'):
            ob = bpy.data.objects[nm + suf]; ob.parent = pv; ob.matrix_parent_inverse = pv.matrix_world.inverted()
        piv[side] = pv
    bars = [bpy.data.objects[f'TStretch{k}'] for k in range(2)]
    ANIM['C'] = dict(piv=piv, bars=bars, base=[b.location.copy() for b in bars], throw=0.11, origin=o, xc=C['xc'], hd=C['hd'])
    ANIM['C']['ws'] = [build_wheelset(f'TWS{k}', L) for k in range(2)]


def turnout_state(u):
    A = ANIM['C']; th = A['throw']
    A['piv'][-1].rotation_euler = (0, 0, th * (1 - u) / 10.0)        # left blade opens toward +x
    A['piv'][1].rotation_euler = (0, 0, -th * u / 10.0)              # right blade opens toward −x
    for b, base, y in zip(A['bars'], A['base'], (0.35, 1.6)):
        dx = (th * (1 - u) - th * u) * (1 - y / 10.0) / 2
        b.location = base + Vector((dx, 0, 0))


def set_hunting_anim(L):
    path = Path([('straight', 760)], origin=ORG['D'], heading_deg=90)
    build_track('D', path, 0, 760, L)
    b, ws = build_bogie('HuntBogie', L)
    n = 320
    tr = tube_curve('HuntTrail', [(0, 0, 0)] * n, 0.05, L['glowO'])
    ANIM['D'] = dict(path=path, bogie=b, ws=[bpy.data.objects[w] for w in b['wheelsets']], trail=tr, n=n)
    anchor('Dsubject', (0, 0, 0)).parent = b
    dm = [o for o in bpy.data.objects if o.name.startswith('HuntBogieDamper') and 'Rod' not in o.name]
    if dm:
        anchor('Ddamper', (0, 0, 0)).parent = dm[0]


def hunt_amp(t):
    """Swing amplitude (m) over time: grows from T2, saturates at flange contact, decays once the dampers act (X1)."""
    t_grow = sh_t0('T2'); t_damp = sh_t0('X1')
    if t < t_grow:
        a = 0.002
    else:
        rate = math.log(0.0385 / 0.002) / max(1.0, EV['SLAM'] - t_grow) if CUT50 else 0.42
        a = min(0.0385, 0.002 * math.exp(rate * (t - t_grow)))
    if t > t_damp:
        a = max(0.002, a * math.exp(-1.6 * (t - t_damp)))
    return a


def hunt_s(t):
    return 30.0 + V_D * (t - sh_t0('T1'))


def hunt_drift(t):
    s = hunt_s(t)
    return hunt_amp(t) * math.sin(2 * math.pi * s / HUNT_L)


def set_bank(L):
    """Cross-section rig: a short piece of track sectioned at the front; it rolls about the inner rail to show cant."""
    o = Vector(ORG['E'])
    path = Path([('straight', 30.0)], origin=tuple(o), heading_deg=90)
    root = empty('BankRoot', o + Vector((-RAIL_C, 0, 0)))
    before = set(bpy.data.objects.keys())
    build_track('E', path, 0, 30.0, L, ballast=True)
    tc = cutter('EFrontCut', (o.x - 5, o.y - 3, -2), (o.x + 5, o.y + 0.4, 2), L['hatchRail'])
    for nm in set(bpy.data.objects.keys()) - before:
        ob = bpy.data.objects[nm]
        if nm.startswith('ERail'):
            cut(ob, tc)
        elif nm.startswith('ESleepers') or nm.startswith('EBallast'):
            cut(ob, tc, keep_material=True)
        if ob.parent is None and nm != 'BankRoot':
            ob.parent = root; ob.matrix_parent_inverse = root.matrix_world.inverted()
    coach = build_coach_body('BankCoach', L)
    coach.location = o + Vector((0, COACH_L / 2 + 1.2, RAIL_H + R0))   # front end just behind the section plane
    coach.parent = root; coach.matrix_parent_inverse = root.matrix_world.inverted()
    for k, off in enumerate((BOGIE_C, -BOGIE_C)):                     # sits on its bogies, not floating
        b, _ = build_bogie(f'BankBogie{k}', L, damper=False); b.location = (0, off, 0); b.parent = coach
    # dimension bar on the outer rail: from inner-rail height to outer-rail height
    bar = box('ECantBar', (-0.025, -0.01, 0), (0.025, 0.01, 1.0), L['glowO'], bevel=0)
    zl = o.z + RAIL_H + 0.004; x = o.x - RAIL_C - 0.25; k = 0               # level reference: dashed line at inner-rail height
    while x < o.x + RAIL_C + 0.3:
        tube_curve(f'ELevelDash{k}', [(x, o.y - 0.06, zl), (min(x + 0.07, o.x + RAIL_C + 0.3), o.y - 0.06, zl)], 0.007, L['dash'])
        x += 0.12; k += 1
    ANIM['E'] = dict(root=root, coach=coach, bar=bar, o=o)
    ac = anchor('Ecant', o + Vector((RAIL_C, 0, RAIL_H + 0.08)))       # outer rail head; rolls with the rig
    ac.parent = root; ac.matrix_parent_inverse = root.matrix_world.inverted()


def bank_state(cant, show_bar):
    E = ANIM['E']; a = math.atan2(cant, 2 * RAIL_C)
    E['root'].rotation_euler = (0, -a, 0)                             # roll about the inner (left) rail, outer rail up
    o = E['o']; xr = o.x + RAIL_C + 0.16
    E['bar'].location = (xr, o.y - 0.05, o.z + RAIL_H); E['bar'].scale = (1, 1, max(0.001, cant))
    E['bar'].hide_render = not show_bar


def set_split(L):
    """Split rig: top = steep cone on a tight curve, bottom = shallow cone on a straight (seen from above)."""
    o = Vector(ORG['H'])
    pc = Path([('arc', 9.0, 60, +1)], origin=tuple(o + Vector((-4.0, 1.4, 0))), heading_deg=-20)
    build_track('HC', pc, 0, pc.length, L, ballast=False)
    ps = Path([('straight', 14)], origin=tuple(o + Vector((-7.0, -1.6, 0))), heading_deg=0)
    build_track('HS', ps, 0, 14, L, ballast=False)
    w1 = build_wheelset('HWsteep', L, taper=1 / 2.5, discs=False, xb=0.762)
    w2 = build_wheelset('HWshallow', L, taper=1 / 12, discs=False, xb=0.762)
    rings = []
    for ws, tp in ((w1, 1 / 2.5), (w2, 1 / 12)):
        for side in (-1, 1):
            rg = ring(f'{ws.name}Ring{side:+d}', L['glowO'], r=1.0, minor=0.02)
            rg.rotation_euler = (0, math.radians(90), 0); rg.parent = ws; rings.append((ws, rg, side, tp))
    trail = tube_curve('HSTrail', [tuple(ps.at(s)[0] + Vector((0, 0, RAIL_H + 0.05))) for s in (1.0, 13.0)], 0.035, L['glowO'])
    ANIM['H'] = dict(pc=pc, ps=ps, w1=w1, w2=w2, rings=rings, o=o)
    anchor('Htop', o + Vector((0, 3.6, 0.5))); anchor('Hbottom', o + Vector((0, -3.0, 0.5)))


# ---------------------------------------------------------------- per-frame state
def sh_t0(name):
    for sh in SHOTS:
        if sh['name'] == name or sh['name'].rstrip('ab') == name:
            return sh['t0']
    return 0.0


def train_s(name, t):
    """Arc length of the hero coach on set A for a shot. H shots and the close share one timeline that loops."""
    if name in ('H3',):
        return CURVE_START + CURVE_R * math.radians(CURVE_DEG) + 60 + CURVE_R * math.radians(30) - 22.5 + V_A * (t - sh_t0('H3'))
    if name.startswith('Z'):
        return S0_H1 + V_A * (t - END)
    if name.startswith('P5') or name.startswith('F4'):
        return S0_H1 + 40 + V_A * (t - sh_t0(name.rstrip('ab')))
    return S0_H1 + V_A * t


def place_train(s):
    A = SET['A']; path = A['path']
    for k, (b, ws) in enumerate(A['bogies']):
        off = BOGIE_C if k == 0 else -BOGIE_C
        place_on_track(b, path, s + off)
        for w in ws:
            roll(w, s + off)
    place_body(A['body'], path, s)
    place_body(A['loco'], path, s + 22.5)
    for k, nm in enumerate(('LocoBogie0', 'LocoBogie1')):
        place_on_track(bpy.data.objects[nm], path, s + 22.5 + (BOGIE_C - 1.5 if k == 0 else -BOGIE_C + 1.5))
    for i, o in enumerate(A['insts'], start=1):
        place_body(o, path, s - 24.0 * i)
    # cab rig at the loco front
    p, t, r, u = path.at(s + 22.5 + 13.2)               # ahead of the loco nose (the cab camera stays outside the body)
    ANIM['cab'].matrix_world = Matrix.Translation(p) @ Matrix((r, t, u)).transposed().to_4x4()


def lead_ws():
    return bpy.data.objects[SET['A']['bogies'][0][0]['wheelsets'][0]]


XRAY_OBJS = []


def build_xray(L):
    """X-ray flash: glowing exaggerated cones parented to every hero wheel spin (hidden except during the flash)."""
    for b, ws in SET['A']['bogies']:
        for w in ws:
            for side in (-1, 1):
                g = revolve(f'{w.name}XCone{side:+d}', wheel_profile(1 / 2.5, side), L['glowO'])
                g.parent = spin_of(w); XRAY_OBJS.append(g)


def set_xray(on, L):
    for o in XRAY_OBJS:
        o.hide_render = not on; o.hide_viewport = not on
    for b, ws in SET['A']['bogies']:
        for w in ws:
            for o in spin_of(w).children:
                if 'Rim' in o.name:
                    o.hide_render = on
                elif o.type == 'MESH' and ('Axle' in o.name or 'Disc' in o.name):
                    o.material_slots[0].material = L['xray'] if on else L['axle']


_LAST = {}


def changed(key, *vals):
    """True if a rig's state differs from the last frame (avoids re-evaluating EXACT booleans every frame)."""
    v = tuple(round(x, 6) if isinstance(x, float) else x for x in vals)
    if _LAST.get(key) == v:
        return False
    _LAST[key] = v; return True


def update(t, sh, L):
    name = sh['name']; base = name.rstrip('ab'); u = (t - sh['t0']) / max(1e-6, sh['t1'] - sh['t0'])
    # ---- set A train
    place_train(train_s(base, t))
    x0, x1 = EV['XRAY']
    if changed('X', x0 <= t < x1):
        set_xray(x0 <= t < x1, L)
    # ---- lift rig (P1, P2, F1)
    Lr = ANIM['lift']
    rise = 1.3 * eio((t - sh_t0('P1') - 0.4) / 1.6) if t >= sh_t0('P1') else 0.0
    if t >= sh_t0('F1') - 0.01 and base.startswith('F1'):
        rise = 1.3
    for o in Lr['frame']:
        o.location = Lr['base'][o.name] + Vector((0, 0, rise))
    roll(Lr['lead'], 4.0 * max(0.0, t - sh_t0('P2a')) if base.startswith('P2') else 0.0)
    for g in ANIM['flange_glow']:
        g.hide_render = not base.startswith('F1')
    # ---- demo B: cone morph, drift, rings, centring, shallow cone
    B = SET['B']; morph = 1.0; drift = 0.0; roll_d = 0.0; marker = False
    if base == 'C1':
        morph = eio((t - EV['MORPH']) / 0.9) if CUT50 else eio(u * 1.25)
    elif base == 'C2':
        marker = t >= EV['TWENTY'] - 0.3
    elif base == 'C3':
        drift = 0.035 * eio(u * 1.3)
    elif base == 'C4':
        drift = 0.035
    elif base in ('S1', 'S2'):
        tn = t - EV['NUDGE']
        drift = 0.0 if tn < 0 else -0.035 * math.exp(-1.1 * tn) * math.cos(1.7 * tn) * min(1.0, tn / 0.25)
        roll_d = 1.2 * (t - sh_t0('S1'))
    elif base == 'X3' and CUT50:                     # steep cone flattens to a shallow one
        morph = lerp(1.0, 0.25, eio((u - 0.15) * 1.5)); drift = 0.0
    elif base == 'X3':
        morph = 0.25; drift = 0.0445 * eio(u * 1.4)
    tp = morph / 2.5
    if changed('B', morph, drift, roll_d):
        for o in spin_of(B['ws']).children:
            if o.data and getattr(o.data, 'shape_keys', None):
                o.data.shape_keys.key_blocks['Morph'].value = morph
        demo_pose('B', drift, tp, roll_dist=roll_d)
    for o in ANIM.get('marker', []):
        o.hide_render = not marker
    # ---- real demo R: flange contact / sideways slide
    rd = 0.0068
    if base == 'F3':
        rd = 0.0068 - 0.004 - 0.004 * math.sin(2 * math.pi * 5.0 * t)        # stick-slip shimmy across the railhead
    if changed('R', rd):
        demo_pose('R', rd, TAPER_REAL)
    # ---- top curve F
    F = ANIM['F']
    for k, o in (('outer', F['outer']), ('inner', F['inner'])):
        o.data.bevel_factor_end = eo((t - sh_t0('P3a')) / 1.6) if base.startswith('P3') else (1.0 if base.startswith('P4') else 0.0)
        o.hide_render = not (base.startswith('P3') or base.startswith('P4'))
    for o, delay in ((F['arc_out'], 0.0), (F['arc_in'], 0.0)):
        o.data.bevel_factor_end = eo((t - sh_t0('P4a') - delay) / 2.0) if base.startswith('P4') else 0.0
        o.hide_render = not base.startswith('P4')
    F['gap'].hide_render = not (base.startswith('P4') and t > sh_t0('P4a') + 2.2)
    sF = 6 + F['R'] * math.radians(20) + (1.6 * (t - sh_t0('C5a')) if base.startswith('C5') else 9.0)
    dF = 0.035
    place_on_track(F['ws'], F['path'], sF, drift=dF)
    roll(F['ws'], sF)
    for side, rg in F['rings'].items():
        x = side * RAIL_C - dF; r = tread_r(x, 1 / 2.5); rg.location = (x, 0, 0); rg.scale = (r, r, r)
        rg.hide_render = not base.startswith('C5')
    F['ws'].hide_render = False
    # ---- turnout C
    uu = 0.0 if t < EV['THROW'] else eio((t - EV['THROW']) / 1.4)
    if changed('C', uu):
        turnout_state(uu)
    yst = (-1.0 + 3.0 * (t - sh_t0('W3'))) if base in ('W3', 'W4') else -6.0
    for k, w in enumerate(ANIM['C']['ws']):
        y = yst - 2.56 * k
        place_on_turnout(w, max(-14.0, y), diverging=True)
        roll(w, y)
    # ---- hunting D
    D = ANIM['D']; sD = hunt_s(t) if t >= sh_t0('T1') else 30.0
    dD = hunt_drift(t) if t >= sh_t0('T1') else 0.0
    yaw = (hunt_drift(t + 0.01) - hunt_drift(t - 0.01)) / (0.02 * V_D) if t >= sh_t0('T1') else 0.0
    place_on_track(D['bogie'], D['path'], sD, drift=dD, yaw=-math.atan(yaw))
    for w in D['ws']:
        roll(w, sD)
    cu = D['trail'].data; sp = cu.splines[0]; n = D['n']
    for i in range(n):
        s = sD - 1.5 - 60.0 * (1 - i / (n - 1))
        tt = t - (sD - s) / V_D
        dd = hunt_amp(tt) * math.sin(2 * math.pi * s / HUNT_L) if tt >= sh_t0('T2') else 0.0
        p, tg, r, up = D['path'].at(max(0.0, s))
        q = p + r * dd * 16.0 + up * (RAIL_H + 0.03)
        sp.points[i].co = (q.x, q.y, q.z, 1.0)
    D['trail'].hide_render = not (base.startswith('T') or base in ('X1', 'X2'))
    glow = 0.0
    if base in ('X1', 'X2') and t >= EV['DAMPER']:
        glow = 3.0 + 2.0 * math.sin(2 * math.pi * 2.0 * (t - EV['DAMPER']))
    L['damper'].node_tree.nodes['Principled BSDF'].inputs['Emission Strength'].default_value = glow
    L['damper'].node_tree.nodes['Principled BSDF'].inputs['Emission Color'].default_value = (1.0, 0.55, 0.1, 1)
    # ---- bank E
    cant = 0.0
    if base == 'K1':
        cant = 0.165 * eio((u - 0.15) / 0.75)
    elif base in ('K2', 'K3'):
        cant = 0.165
    if changed('E', cant, base == 'K2'):
        bank_state(cant, base == 'K2')
    for o in [ANIM['E']['coach']] + list(ANIM['E']['coach'].children_recursive):
        o.hide_render = base != 'K3'
    # ---- split H
    H = ANIM['H']
    place_on_track(H['w1'], H['pc'], 2.0 + 1.2 * (t % 6.0), drift=0.035)
    place_on_track(H['w2'], H['ps'], 3.0 + (2.5 * t) % 8.0, drift=0.0)
    for ws, rg, side, tp in H['rings']:
        dr = 0.035 if ws is H['w1'] else 0.0
        x = side * RAIL_C - dr; r = tread_r(x, tp); rg.location = (x, 0, 0); rg.scale = (r, r, r)
    for s_ in SPARKS:
        s_.update(t)


# ---------------------------------------------------------------- cameras per shot
def frame_of(path, s):
    return path.at(s)


def camera_for(name, u, t):
    base = name.rstrip('ab'); var = name[-1] if name[-1] in 'ab' and base != name else ''
    A = SET['A']; pa = A['path']
    if base in ('H1', 'H2', 'H4', 'P5', 'F4', 'Z1', 'Z2'):
        lw = lead_ws(); cp, fwd, up = contact_point(lw, -1)
        s_lead = train_s(base, t) + BOGIE_C + 1.28
        p, tg, r, uu = pa.at(s_lead)
    if base == 'H1':
        return p + tg * (1.75 - 0.25 * u) - r * 1.45 + uu * 0.42, cp + up * 0.30 + r * 0.10, 24, 4.0
    if base == 'H2':
        c = ANIM['cab'].matrix_world
        return c @ Vector((0.0, -2.25 + 0.2 * u, 3.05)), c @ Vector((0.0, 0.4, 2.05)), 18, 8.0
    if base == 'H3':
        sf = train_s('H3', t) + 22.5
        p3, t3, r3, u3 = pa.at(sf + 10)
        return p3 - r3 * (11 + 2 * u) + u3 * (8.5 + 3 * u), pa.at(sf - 190)[0] + u3 * 1.5, 30, 16
    if base == 'H4':
        bp = A['bogies'][0][0].matrix_world.translation
        return lerp(p + tg * 5.5 - r * 4.0 + uu * 3.2, p + tg * 2.8 - r * 2.4 + uu * 1.1, eio(u)), lerp(bp, cp + uu * 0.45, eio(u)), 24, 8.0
    if base == 'P1':
        Lr = ANIM['lift']; c = Lr['lead'].matrix_world.translation; a = math.radians(-50 + 40 * u)
        return c + Vector((math.cos(a) * 4.2, math.sin(a) * 4.2 - 1.0, 2.4)), c + Vector((0, 0, 0.6)), 30, 8.0
    if base == 'P2':
        c = ANIM['lift']['lead'].matrix_world.translation
        if var == 'a':
            return c + Vector((2.6 - 0.3 * u, -2.8, 1.4)), c, 30, 8.0
        return c + Vector((0.0, -0.15, 3.6 - 0.4 * u)), c, 30, 11.0
    if base == 'P3':
        F = ANIM['F']; pc = F['path'].at((F['s_a'] + F['s_b']) / 2)[0]
        return pc + Vector((0, 0, 22 - 3 * u)) + (Vector((0, -0.5, 0)) if var == 'a' else Vector((4, -6, -6))), pc, 35, 16
    if base == 'P4':
        F = ANIM['F']; pc = F['path'].at(F['s_start'] + 1.5)[0]
        z = 9.0 - 1.5 * u
        return pc + Vector((0, -0.1, z)) + (Vector() if var == 'a' else Vector((1.5, -2.5, -2.0))), pc, 35, 16
    if base == 'P5':
        if var == 'a':
            return p - tg * 1.2 - r * 1.25 + uu * 0.35, cp + up * 0.18, 30, 3.5
        return cp + fwd * 0.9 + r * 0.55 + up * 0.22, cp + up * 0.03, 50, 4.0
    if base in ('C1', 'C2', 'C3', 'C4', 'S1', 'S2', 'X3'):
        m = SET['B']['ws'].matrix_world
        if base == 'C1':
            return m @ Vector((-0.6 + 0.9 * u, -2.6, 0.6)), m @ Vector((0.4, 0, -0.1)), 35, 11
        if base == 'C2':
            return m @ Vector((0.66, -0.95 + 0.08 * u, -0.24)), m @ Vector((0.86, 0, -0.40)), 60, 11
        if base in ('C3', 'S1', 'X3'):                     # wheelset kept in the upper frame
            return m @ Vector((0.0, -3.2 + 0.2 * u, 0.80)), m @ Vector((0.0, 0, -0.50)), 28, 11
        if base == 'C4':
            if var == 'a':
                return m @ Vector((-0.4 + 0.3 * u, -3.0, 0.95)), m @ Vector((0.0, 0, -0.48)), 28, 11
            sd = -1 if CUT50 else 1                       # 50 s cut: the inner wheel
            return m @ Vector((sd * 1.35, -1.6 + 0.2 * u, 0.15)), m @ Vector((sd * 0.85, 0, -0.25)), 40, 11
        if base == 'S2':
            if var == 'a':
                return m @ Vector((0.0, -3.0, 0.80)), m @ Vector((0.0, 0, -0.50)), 28, 11
            return m @ Vector((0.0, -0.6, 2.4)), m @ Vector((0.0, 0.25, -0.1)), 28, 11
    if base == 'C5':
        F = ANIM['F']; c = F['ws'].matrix_world.translation
        if var == 'a':
            return c + Vector((-1.4, -2.6, 3.0)), c, 30, 11
        return c + Vector((0.0, -0.3, 3.6)), c, 30, 11
    if base == 'F1':
        c = ANIM['lift']['lead'].matrix_world.translation; a = math.radians((-70 if var == 'a' else 20) + 30 * u)
        return c + Vector((math.cos(a) * 3.0, math.sin(a) * 3.0, 1.2)), c, 35, 8.0
    if base in ('F2', 'F3'):
        m = SET['R']['ws'].matrix_world
        if base == 'F2' and var == 'b':
            return m @ Vector((0.45, -0.6, -0.30)), m @ Vector((0.84, 0.0, -0.44)), 80, 8
        if base == 'F3':
            return m @ Vector((0.66, -0.95, -0.24)), m @ Vector((0.86, 0, -0.42)), 60, 11
        return m @ Vector((0.62, -1.15, -0.22)), m @ Vector((0.84, 0.0, -0.42)), 70, 8
    if base == 'F4':
        return lerp(p - tg * 1.5 - r * 1.6 + uu * 0.6, p - tg * 6.0 - r * 5.5 + uu * 2.6, eio(u)), cp + uu * 0.5, 26, 8
    if base in ('K1', 'K2', 'K3'):
        o = ANIM['E']['o']
        if base == 'K3':
            return o + Vector((5.6 - 0.5 * u, -3.2 + 0.6 * u, 0.9)), o + Vector((-0.4, 9.0, 1.2)), 26, 16
        return o + Vector((0.15, -3.9 + 0.3 * u, 0.42)), o + Vector((0.15, 0, -0.32)), 26, 16
    if base in ('W1', 'W2', 'W3', 'W4'):
        o = ANIM['C']['origin']
        if base in ('W1', 'W2'):
            return o + Vector((0.2, 1.0 - 0.6 * u, 9.0 - 1.0 * u)), o + Vector((0.2, 2.0, 0)), 35, 16
        w = ANIM['C']['ws'][0].matrix_world.translation
        if base == 'W3':
            return o + Vector((-2.6, -3.2, 1.55)), w + Vector((0.3, 2.0, -0.95)), 26, 8
        return w + Vector((-3.0, -4.5, 2.6)), w + Vector((0.5, 2.0, -1.1)), 28, 8
    if base in ('T1', 'T2', 'T3', 'T4', 'T5', 'X1', 'X2'):
        D = ANIM['D']; sD = hunt_s(t); p, tg, r, uu = D['path'].at(sD); bpos = D['bogie'].matrix_world.translation
        if base == 'T1':
            return p + tg * 3.5 - r * 2.2 + uu * 0.5, bpos + uu * 0.1, 24, 6
        if base in ('T2', 'T3', 'T4'):
            if var == 'b' or base in ('T4', 'T2'):
                return p + tg * 9.0 + r * 2.0 + uu * 5.2, p + tg * 2.0 - uu * 0.8, 24, 11
            return p - tg * 1.0 + r * 0.8 + uu * 8.5, p - tg * 7.0, 24, 16
        if base == 'T5':
            sh = Vector((math.sin(t * 61) * 0.05, math.sin(t * 47) * 0.04, math.sin(t * 53) * 0.03)) * min(1.0, hunt_amp(t) / 0.03)
            if var == 'a':
                return p - tg * 2.0 - r * 1.6 + uu * 0.45 + sh, bpos - uu * 0.3, 24, 5
            return p + tg * 6.0 + r * 1.6 + uu * 3.5 + sh, bpos - uu * 0.9, 24, 8
        if base == 'X1':
            return p + tg * 2.2 + r * 2.6 + uu * 1.4, bpos + r * 1.3 + uu * 0.2, 30, 5
        if base == 'X2':
            return p + tg * 9.0 + r * 2.0 + uu * 5.2, p + tg * 2.0 - uu * 0.8, 24, 11
    if base == 'X4':
        o = ANIM['H']['o']
        if var == 'a':
            return o + Vector((0.0, -1.8, 10.5)), o + Vector((0.0, -1.2, 0)), 30, 16
        return o + Vector((0.0, -7.5, 6.5)), o + Vector((0.0, -0.6, 0)), 30, 16
    if base == 'Z1':
        return p + tg * 14 - r * 22 + uu * 9.0, A['body'].matrix_world.translation + uu * 1.0, 30, 16
    if base == 'Z2':
        e = eio(u)
        c0 = p + tg * 6.0 - r * 7.0 + uu * 4.0; c1 = p + tg * 1.75 - r * 1.45 + uu * 0.42
        g0 = A['body'].matrix_world.translation; g1 = cp + up * 0.30 + r * 0.10
        return lerp(c0, c1, e), lerp(g0, g1, e), lerp(30, 24, e), 4.0
    return Vector((0, -10, 5)), Vector((0, 0, 0)), 35, 8


def build_all(L):
    set_curve(L, coaches=24, hero_s=S0_H1)
    build_cab(L)
    build_xray(L)
    set_demo(L, origin=ORG['B'], taper=0.0, morph_taper=1 / 2.5, xb=0.762, key='B', section=True, rings=True)
    taper_marker(SET['B']['ws'], 1 / 2.5, L)
    ANIM['marker'] = [o for o in bpy.data.objects if o.name.startswith(('RefDash', 'TaperLine', 'TaperArc'))]
    anchor('Btaper', SET['taper_label'])
    for side in (-1, 1):
        a_ = anchor(f'Bring{side:+d}', (side * RAIL_C, 0, R0 + 0.07)); a_.parent = SET['B']['ws']
    set_demo(L, origin=ORG['R'], taper=TAPER_REAL, drift=0.0068, xb=XB, key='R', section=True, rings=False, ticks=False)
    set_lift(L)
    set_topcurve(L)
    set_turnout_anim(L)
    set_hunting_anim(L)
    set_bank(L)
    set_split(L)
    # sparks
    lw = lead_ws()
    Sparks('HookSparks', lambda t: contact_point(lead_ws(), -1), L, n=130, speed=2.6, size=0.010)
    Rws = SET['R']['ws']
    Sparks('FlangeSparks', lambda t: (Rws.matrix_world @ Vector((XB + 0.030, 0.0, -R0 + 0.006)),
                                      -(Rws.matrix_world.to_3x3() @ Vector((0, 1, 0))), Vector((0, 0, 1))), L, n=140, speed=1.3, size=0.0035)
    Sparks('HuntSparks', lambda t: contact_point(ANIM['D']['ws'][0], 1 if hunt_drift(t) > 0 else -1), L, n=70, speed=2.8, size=0.014)
    SPARK_ON.update(HookSparks=('H1', 'H4', 'P5', 'F4', 'Z2'), FlangeSparks=('F2', 'F3'), HuntSparks=('T5',))
    bpy.app.handlers.frame_change_pre.clear(); bpy.app.handlers.frame_change_pre.append(frame_handler)


SPARK_ON = {}
LIB = {}


def frame_handler(scene, depsgraph=None):
    t = (scene.frame_current + scene.frame_subframe - 1) / FPS
    f = scene.frame_current
    sh = shot_at_frame(f); ANIM['shot'] = sh['name']
    if sh['name'] in ALIAS:                               # montage: show another shot's rig at a mapped time
        rig, a0, a1 = ALIAS[sh['name']]; u = (t - sh['t0']) / max(1e-6, sh['t1'] - sh['t0'])
        sh = next(x for x in SHOTS if x['name'] == rig)
        t = sh['t0'] + (sh['t1'] - sh['t0']) * (a0 + (a1 - a0) * u)
    base = sh['name'].rstrip('ab')
    for sp in SPARKS:
        allowed = SPARK_ON.get(sp.name, ())
        sp.t_on, sp.t_off = (-1e9, 1e9) if base in allowed else (1e9, 1e9)
        if sp.name == 'HuntSparks':
            sp.t_on, sp.t_off = ((-1e9, 1e9) if base in allowed and hunt_amp(t) > 0.03 else (1e9, 1e9))
    update(t, sh, LIB['L'])
    loc, tgt, lens, fs = camera_for(sh['name'], (t - sh['t0']) / max(1e-6, sh['t1'] - sh['t0']), t)
    cam = scene.camera; ct = bpy.data.objects['CamTarget']; cf = bpy.data.objects['CamFocus']
    cam.location = loc; ct.location = tgt; cf.location = tgt; cam.data.lens = lens; cam.data.dof.aperture_fstop = fs


def export_anchors(path):
    from bpy_extras.object_utils import world_to_camera_view
    sc = bpy.context.scene; out = {'fps': FPS, 'frames': {}}
    names = [o for o in bpy.data.objects if o.name.startswith('A_')]
    for f in range(1, int(round(END * FPS)) + 1):
        sc.frame_set(f); row = {'shot': ANIM['shot']}
        for o in names:
            v = world_to_camera_view(sc, sc.camera, o.matrix_world.translation)
            row[o.name[2:]] = [round(v.x, 4), round(1 - v.y, 4), round(v.z, 3)]
        out['frames'][f] = row
    json.dump(out, open(path, 'w'))


# ---------------------------------------------------------------- main
def parse_args():
    argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else sys.argv[1:]
    p = argparse.ArgumentParser()
    p.add_argument('--style', default=None)
    p.add_argument('--frames', default='1')
    p.add_argument('--res', default='540x960')
    p.add_argument('--samples', type=int, default=48)
    p.add_argument('--engine', default='CYCLES', choices=['CYCLES', 'WORKBENCH'])
    p.add_argument('--out', default='frames')
    p.add_argument('--no-blur', action='store_true')
    p.add_argument('--before', action='store_true')
    p.add_argument('--anchors', default=None)
    a = p.parse_args(argv)
    a.w, a.h = (int(x) for x in a.res.lower().split('x'))
    return a


def main():
    a = parse_args()
    bpy.ops.wm.read_factory_settings(use_empty=True)
    SPARKS.clear(); OBJ.clear(); SET.clear()
    L = materials.train_library(materials.library())
    build_world(L)
    setup_render(a)
    sc = bpy.context.scene
    os.makedirs(a.out, exist_ok=True)
    LIB['L'] = L
    if not a.style:
        build_all(L)
        make_camera((0, -10, 5), (0, 0, 0))
        sc.frame_start, sc.frame_end = 1, int(round(END * FPS))
        if a.anchors:
            export_anchors(a.anchors); return
        sc.render.filepath = os.path.join(os.path.abspath(a.out), 'before_' if a.before else 'frame_')
        if '-' in a.frames and ',' not in a.frames:
            s0, s1 = (int(x) for x in a.frames.split('-')); sc.frame_start, sc.frame_end = s0, s1
            bpy.ops.render.render(animation=True)
        else:
            for f in (int(x) for x in a.frames.split(',')):
                sc.frame_start = sc.frame_end = f; bpy.ops.render.render(animation=True)
        return
    if a.style:
        style(a.style, L)
        sc.render.use_motion_blur = False
        sc.frame_set(12)
        on_frame(sc)
        sc.render.filepath = os.path.join(os.path.abspath(a.out), f'style_{a.style}.png')
        bpy.ops.render.render(write_still=True)
        # projected anchor points for the post labels
        from bpy_extras.object_utils import world_to_camera_view
        anchors = {}
        if a.style in ('cone', 'cone_close'):
            ws = SET['B']['ws']; m = ws.matrix_world; tp = SET['B']['taper']
            anchors['taper'] = SET.get('taper_label', m @ Vector((0.93, 0, -(R0 - (0.93 - RAIL_C) * tp) + 0.05)))
            anchors['subject'] = m @ Vector((0.0, 0, -R0))
            for side in (-1, 1):
                anchors[f'ring{side:+d}'] = m @ Vector((side * RAIL_C, 0, R0 + 0.06))
        if a.style == 'hunting':
            anchors['subject'] = SET['D']['bogie'].matrix_world.translation
        if a.style == 'switch':
            anchors['subject'] = SET['C']['origin'] + Vector((0, 2.0, 0))
        for k, v in anchors.items():
            c = world_to_camera_view(sc, sc.camera, v); anchors[k] = [round(c.x, 4), round(1 - c.y, 4)]
        json.dump(anchors, open(os.path.join(a.out, f'style_{a.style}.json'), 'w'))


if __name__ == '__main__':
    main()
