"""Chenab Bridge cutaway set: a Himalayan gorge cut open at the front (orange hatch), the two-rib steel truss arch
(467 m span), deck, lattice piers on the arch, concrete piers on the slopes, a generic train, and a flat Eiffel Tower
silhouette (330 m) for scale.

Usage (bpy module or blender -b -P):
    python3 scene.py --frames 1-1200 --res 720x1280 --samples 32 --out frames/
    python3 scene.py --frames 30,90 --engine WORKBENCH --res 360x640 --out wb/     (framing check)
    python3 scene.py --frames 30,90 --anchors anchors.json                        (projected label anchors)

Real dimensions (metres, published figures): deck 359 above the river bed, arch span 467 (abutment base plates),
total bridge length 1,315, tallest slope pier ~131-134, Eiffel Tower 330. Arch rise, rib depth and slope
profile are approximate (drawn from published elevations). Members are drawn thicker than real so they read
on a phone (house style).
"""
import argparse, json, math, os, sys
import bpy, bmesh
from mathutils import Vector, noise

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import materials  # noqa: E402

FPS = 24
SPAN = 467.0; A = SPAN / 2
DECK = 359.0                  # rail top above the river bed
GIRDER = 7.0                  # rail top → girder bottom
GB = DECK - GIRDER            # girder bottom
Z_SPRING = 198.0              # arch springing (bottom chord): low on the gorge walls (rise ≈ 0.30 × span, checked vs side photo)
RIB_D = 11.0                  # rib depth (chord to chord)
CROWN_B = GB - 1.5 - RIB_D    # bottom chord at the crown
BED = 75.0                    # half-width of the flat river bed at the bridge
Y_CUT = -320.0                # the gorge is cut open here (hatched face)
EIFFEL = 330.0
V_TRAIN = 18.0                # m/s (~65 km/h)
N_PANELS = 36
OBJ = {}; ANIM = {}; LIB = {}

# ---------------------------------------------------------------- provisional timeline (beat sheet estimate)
# Re-timed later from the final audio (timing.py → inject_cues.py).
EV = {"BHOOKAMP": 34.6}
SHOTS = [{"name": "H1", "t0": 0.0, "t1": 2.3}, {"name": "H2", "t0": 2.3, "t1": 4.2}, {"name": "N1", "t0": 4.2, "t1": 7.0},
         {"name": "N2", "t0": 7.0, "t1": 9.8}, {"name": "P1", "t0": 9.8, "t1": 11.9}, {"name": "P2", "t0": 11.9, "t1": 14.2},
         {"name": "P3", "t0": 14.2, "t1": 17.2}, {"name": "A1", "t0": 17.2, "t1": 19.5}, {"name": "A2", "t0": 19.5, "t1": 22.4},
         {"name": "A3", "t0": 22.4, "t1": 25.2}, {"name": "W1", "t0": 25.2, "t1": 27.6}, {"name": "W2", "t0": 27.6, "t1": 30.5},
         {"name": "W3", "t0": 30.5, "t1": 33.0}, {"name": "T1", "t0": 33.0, "t1": 35.8}, {"name": "T2", "t0": 35.8, "t1": 38.2},
         {"name": "T3", "t0": 38.2, "t1": 40.3}, {"name": "Y1", "t0": 40.3, "t1": 44.2}, {"name": "Z1", "t0": 44.2, "t1": 46.4},
         {"name": "Z2", "t0": 46.4, "t1": 50.0}]
END = 50.0
JUNCTION_HOLD = 0.3


# ---------------------------------------------------------------- geometry of the bridge and the gorge
def zb(x): return Z_SPRING + (CROWN_B - Z_SPRING) * (1 - (x / A) ** 2)
def zt(x): return zb(x) + RIB_D
def yr(x): return 6.0 + 9.0 * (x / A) ** 2          # ribs lean in: 15 m off-centre at the springing, 6 m at the crown


def smooth(a, b, v):
    u = min(1.0, max(0.0, (v - a) / (b - a))); return u * u * (3 - 2 * u)


def meander(y): return 70.0 * math.sin(y / 420.0) * smooth(150, 450, abs(y))


K1 = Z_SPRING / (A - BED)     # steep lower walls reach the springing level exactly at x = ±A


def profile(x):
    u = abs(x) - BED
    if u <= 0:
        return -2.0
    z = u * K1
    if z > 240.0:
        k2 = 1.1 if x < 0 else 0.33                    # south wall steep, north side a long ramp (the long viaduct)
        z = 240.0 + (u - 240.0 / K1) * k2
        if z > 368.0:
            z = 368.0 + (z - 368.0) * (0.22 / k2)
    return z + 330.0 * smooth(800, 1750, abs(x))       # mountains beyond


def ground(x, y):
    xm = x - meander(y)
    z = profile(xm)
    w = smooth(BED - 5, BED + 25, abs(xm))
    z += w * (7.0 * noise.noise(Vector((x / 70, y / 70, 0.3))) + 2.5 * noise.noise(Vector((x / 18, y / 18, 1.7))))
    return z


# ---------------------------------------------------------------- bmesh helpers
def bm_quad_box(bm, c8):
    vs = [bm.verts.new(c) for c in c8]
    for f in ((0, 1, 2, 3), (7, 6, 5, 4), (0, 4, 5, 1), (1, 5, 6, 2), (2, 6, 7, 3), (3, 7, 4, 0)):
        bm.faces.new([vs[i] for i in f])


def bm_beam(bm, a, b, w, h=None, up=(0, 0, 1)):
    """Rectangular beam (w across, h up) between points a and b."""
    h = w if h is None else h
    a, b = Vector(a), Vector(b); d = (b - a).normalized(); u = Vector(up)
    if abs(d.dot(u)) > 0.95:
        u = Vector((1, 0, 0))
    s = d.cross(u).normalized() * (w / 2); t = s.cross(d).normalized() * (h / 2)
    bm_quad_box(bm, [a - s - t, a + s - t, a + s + t, a - s + t, b - s - t, b + s - t, b + s + t, b - s + t])


def bm_box(bm, mn, mx):
    x0, y0, z0 = mn; x1, y1, z1 = mx
    bm_quad_box(bm, [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0), (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)])


def mesh_obj(name, bm, mat, smooth_=False):
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free()
    o = bpy.data.objects.new(name, me); bpy.context.collection.objects.link(o)
    for m in (mat if isinstance(mat, (list, tuple)) else [mat]):
        me.materials.append(m)
    if smooth_:
        for p in me.polygons:
            p.use_smooth = True
    return o


def empty(name, loc=(0, 0, 0)):
    o = bpy.data.objects.new(name, None); bpy.context.collection.objects.link(o); o.location = loc; return o


def anchor(name, loc, par=None):
    o = empty('A_' + name, loc)
    if par:
        o.parent = par
    return o


def cyl(name, loc, r, depth, mat, rot=(0, 0, 0), verts=24):
    bpy.ops.mesh.primitive_cylinder_add(vertices=verts, radius=r, depth=depth, location=loc, rotation=rot)
    o = bpy.context.object; o.name = name; o.data.materials.append(mat); return o


def cone(name, loc, r, depth, mat, verts=24):
    bpy.ops.mesh.primitive_cone_add(vertices=verts, radius1=r, radius2=0, depth=depth, location=loc)
    o = bpy.context.object; o.name = name; o.data.materials.append(mat); return o


def sphere(name, loc, r, mat, seg=24):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=seg, ring_count=seg // 2, radius=r, location=loc)
    o = bpy.context.object; o.name = name; o.data.materials.append(mat)
    for p in o.data.polygons:
        p.use_smooth = True
    return o


def point_along(o, d):
    o.rotation_mode = 'QUATERNION'; o.rotation_quaternion = Vector(d).to_track_quat('Z', 'Y')


def tube_curve(name, pts, r, mat):
    cu = bpy.data.curves.new(name, 'CURVE'); cu.dimensions = '3D'; cu.bevel_depth = r; cu.bevel_resolution = 2
    sp = cu.splines.new('POLY'); sp.points.add(len(pts) - 1)
    for p, q in zip(sp.points, pts):
        p.co = (*q, 1.0)
    o = bpy.data.objects.new(name, cu); bpy.context.collection.objects.link(o); cu.materials.append(mat); return o


# ---------------------------------------------------------------- world
def build_world(L):
    sc = bpy.context.scene
    w = bpy.data.worlds.new('Sky'); sc.world = w; w.use_nodes = True
    nt = w.node_tree; bg = nt.nodes['Background']; bg.inputs['Strength'].default_value = 0.7
    tcw = nt.nodes.new('ShaderNodeTexCoord'); sep = nt.nodes.new('ShaderNodeSeparateXYZ'); mr = nt.nodes.new('ShaderNodeMapRange')
    ramp = nt.nodes.new('ShaderNodeValToRGB'); ramp.name = 'SkyRamp'
    mr.inputs['From Min'].default_value = -0.02; mr.inputs['From Max'].default_value = 0.42
    nt.links.new(tcw.outputs['Generated'], sep.inputs[0]); nt.links.new(sep.outputs['Z'], mr.inputs['Value'])
    nt.links.new(mr.outputs['Result'], ramp.inputs['Fac'])
    ramp.color_ramp.elements[0].color = (0.86, 0.80, 0.70, 1); ramp.color_ramp.elements[1].color = (0.13, 0.36, 0.78, 1)
    nt.links.new(ramp.outputs['Color'], bg.inputs['Color'])
    bpy.ops.object.light_add(type='SUN', location=(0, 0, 900)); sun = bpy.context.object; sun.name = 'Sun'
    sun.data.energy = 5.5; sun.data.color = (1.0, 0.86, 0.68); sun.data.angle = math.radians(2)
    OBJ['sun'] = sun; set_sun(Vector((0.45, 0.75, -0.62)))
    bpy.ops.mesh.primitive_plane_add(size=30000, location=(0, 0, -150)); g = bpy.context.object; g.name = 'Ground'
    g.data.materials.append(L['sand'])


def set_sun(d):
    s = OBJ['sun']; s.rotation_mode = 'QUATERNION'; s.rotation_quaternion = (-d).to_track_quat('Z', 'Y')
    ANIM['sun_dir'] = d.normalized()


def build_terrain(L):
    xs = [-1800 + 9 * i for i in range(401)]
    ys = []; y = Y_CUT
    while y < 3600:
        ys.append(y); y += 12 if y < 450 else 32
    bm = bmesh.new(); grid = []
    for y in ys:
        grid.append([bm.verts.new((x, y, ground(x, y))) for x in xs])
    for j in range(len(ys) - 1):
        for i in range(len(xs) - 1):
            bm.faces.new((grid[j][i], grid[j][i + 1], grid[j + 1][i + 1], grid[j + 1][i]))
    low = [bm.verts.new((x, Y_CUT, -150.0)) for x in xs]          # the cutaway face, hatched
    for i in range(len(xs) - 1):
        f = bm.faces.new((low[i], low[i + 1], grid[0][i + 1], grid[0][i])); f.material_index = 1
    OBJ['terrain'] = mesh_obj('Terrain', bm, [L['rock'], L['hatchRock']], smooth_=True)
    # river: a strip that follows the meander, flow scrolled along Y
    bm = bmesh.new(); prev = None
    for y in [Y_CUT + 0.5] + ys[1:]:
        m = meander(y); row = [bm.verts.new((m + dx, y, 1.2)) for dx in (-64.0, 64.0)]
        if prev:
            bm.faces.new((prev[0], prev[1], row[1], row[0]))
        prev = row
    OBJ['river'] = mesh_obj('River', bm, L['river'])


# ---------------------------------------------------------------- the bridge
def build_arch(L):
    """One object per panel (both ribs + bracing), so the arch can grow from both banks."""
    xs = [-A + SPAN * i / N_PANELS for i in range(N_PANELS + 1)]
    OBJ['panels'] = []
    for i in range(N_PANELS):
        x0, x1 = xs[i], xs[i + 1]; bm = bmesh.new()
        for s in (-1, 1):
            P = lambda x, z: (x, s * yr(x), z)
            bm_beam(bm, P(x0, zt(x0)), P(x1, zt(x1)), 3.6, 3.6)              # chords (box sections)
            bm_beam(bm, P(x0, zb(x0)), P(x1, zb(x1)), 3.6, 3.6)
            bm_beam(bm, P(x0, zb(x0)), P(x0, zt(x0)), 1.8, 1.8, up=(1, 0, 0))   # verticals
            if i == N_PANELS - 1:
                bm_beam(bm, P(x1, zb(x1)), P(x1, zt(x1)), 1.8, 1.8, up=(1, 0, 0))
            a, b = (P(x0, zb(x0)), P(x1, zt(x1))) if (i < N_PANELS / 2) else (P(x0, zt(x0)), P(x1, zb(x1)))
            bm_beam(bm, a, b, 1.5, 1.5)                                      # diagonals point to the crown
        for z_of in (zt, zb):                                                # lateral bracing between the ribs
            bm_beam(bm, (x0, -yr(x0), z_of(x0)), (x0, yr(x0), z_of(x0)), 1.2, 1.2, up=(1, 0, 0))
        bm_beam(bm, (x0, -yr(x0), zt(x0)), (x1, yr(x1), zt(x1)), 0.9, 0.9)
        bm_beam(bm, (x0, yr(x0), zt(x0)), (x1, -yr(x1), zt(x1)), 0.9, 0.9)
        o = mesh_obj(f'ArchPanel{i:02d}', bm, L['archSteel']); o['xc'] = (x0 + x1) / 2
        OBJ['panels'].append(o)
    for s in (-1, 1):                                                         # abutments: concrete blocks on rock
        bm = bmesh.new(); xa = s * A
        bm_box(bm, (min(xa - s * 10, xa + s * 48), -28, Z_SPRING - 40), (max(xa - s * 10, xa + s * 48), 28, Z_SPRING + 22))
        mesh_obj(f'Abutment{s:+d}', bm, L['concrete'])


def build_deck(L):
    """Deck in three parts (south approach, arch span, north approach) so the span can wait for the arch."""
    parts = {'S': (-430.0, -A), 'M': (-A, A), 'N': (A, 720.0)}
    OBJ['deck'] = {}
    for k, (x0, x1) in parts.items():
        bm = bmesh.new()
        bm_box(bm, (x0, -6.5, GB), (x1, 6.5, DECK - 1.2))                     # girder
        bm_box(bm, (x0, -6.9, DECK - 1.2), (x1, 6.9, DECK - 0.6))             # slab overhang
        o = mesh_obj(f'Deck{k}', bm, L['deck'])
        bm = bmesh.new()
        for yc in (-0.875, 0.875):                                            # rails
            bm_box(bm, (x0, yc - 0.04, DECK - 0.6), (x1, yc + 0.04, DECK))
        bm_box(bm, (x0, -1.6, DECK - 0.62), (x1, 1.6, DECK - 0.45))           # track slab
        for s in (-1, 1):                                                     # railings: top rail + posts every 4 m
            y = s * 6.6
            bm_box(bm, (x0, y - 0.08, DECK + 0.5), (x1, y + 0.08, DECK + 0.62))
            x = x0
            while x < x1:
                bm_box(bm, (x - 0.07, y - 0.07, DECK - 0.6), (x + 0.07, y + 0.07, DECK + 0.6)); x += 4.0
        t = mesh_obj(f'Track{k}', bm, L['steel']); t.parent = o
        OBJ['deck'][k] = o
    # slope piers (concrete, hollow-looking slabs) — on both abutments and along the slopes
    OBJ['slopePiers'] = []
    for x in (-340.0, 350.0, 400.0, 450.0, 500.0, 550.0, 600.0):
        base = ground(x, 0) - 6
        if GB - base < 4:
            continue
        bm = bmesh.new(); h = GB - base; wb_, wt_ = 4.2 + h * 0.012, 3.4
        db_, dt_ = 6.5 + h * 0.02, 5.5
        bm_quad_box(bm, [(x - wb_, -db_, base), (x + wb_, -db_, base), (x + wb_, db_, base), (x - wb_, db_, base),
                         (x - wt_, -dt_, GB), (x + wt_, -dt_, GB), (x + wt_, dt_, GB), (x - wt_, dt_, GB)])
        o = mesh_obj(f'SlopePier{x:+.0f}', bm, L['concrete']); o['x'] = x; o['h'] = h
        OBJ['slopePiers'].append(o)
    # steel lattice piers standing on the arch (~48 m apart) + bearings at the crown
    OBJ['archPiers'] = []
    for x in (-192.0, -144.0, -96.0, -48.0, 48.0, 96.0, 144.0, 192.0):
        OBJ['archPiers'].append(lattice_pier(f'ArchPier{x:+.0f}', x, zt(x) + 1.8, yr(x), 3.0, L))
    for s in (-1, 1):                                     # tall lattice towers on the arch foundations (photos #1, #2)
        x = s * (A + 20)
        OBJ['footPiers'] = OBJ.get('footPiers', []) + [lattice_pier(f'FootPier{s:+d}', x, Z_SPRING + 22, 9.0, 4.0, L)]
        x2 = s * 300.0                                    # first approach pier: also a steel lattice tower (photo #1)
        OBJ['footPiers'].append(lattice_pier(f'SlopeTower{s:+d}', x2, ground(x2, 0) - 4, 7.0, 3.5, L))
    bm = bmesh.new()
    for x in (-24.0, 0.0, 24.0):
        for s in (-1, 1):
            bm_box(bm, (x - 2, s * yr(x) - 1.5, zt(x) + 1.8), (x + 2, s * yr(x) + 1.5, GB))
    OBJ['archPiers'].append(mesh_obj('CrownBearings', bm, L['pierSteel']))


def lattice_pier(name, x, z0, yb, hx, L):
    """Four-legged steel lattice column from z0 to the girder: legs splay from ±yb at the foot to ±5 at the top,
    X-bracing on all four faces every ~12 m."""
    bm = bmesh.new(); z1 = GB
    legs = [((x + dx, s * yb, z0), (x + dx * 0.8, s * 5.0, z1)) for dx in (-hx, hx) for s in (-1, 1)]
    for a_, b_ in legs:
        bm_beam(bm, a_, b_, 1.8, 1.8)
    n = max(1, int((z1 - z0) / 12))
    lerp3 = lambda p, q, u: tuple(pi + (qi - pi) * u for pi, qi in zip(p, q))
    for k in range(n):
        u0, u1 = k / n, (k + 1) / n
        for (p, q), (r, s_) in ((legs[0], legs[2]), (legs[1], legs[3]), (legs[0], legs[1]), (legs[2], legs[3])):
            bm_beam(bm, lerp3(p, q, u0), lerp3(r, s_, u1), 0.7, 0.7)
            bm_beam(bm, lerp3(r, s_, u0), lerp3(p, q, u1), 0.7, 0.7)
            bm_beam(bm, lerp3(p, q, u1), lerp3(r, s_, u1), 0.8, 0.8)
    return mesh_obj(name, bm, L['pierSteel'])


COACH_W, COACH_L, LOCO_L = 3.24, 23.54, 20.4


def build_train(L):
    """Generic electric loco + 8 coaches (no real livery), root at the front of the train, rail-top height."""
    root = empty('Train'); y = 0.0
    for k in range(9):
        loco = k == 0; Lc = LOCO_L if loco else COACH_L; cy = -(y + Lc / 2)
        bm = bmesh.new()
        bm_box(bm, (cy - Lc / 2, -COACH_W / 2, 1.25), (cy + Lc / 2, COACH_W / 2, 4.0))
        body = mesh_obj(f'Car{k}', bm, L['loco'] if loco else L['shell']); body.parent = root
        bm = bmesh.new()
        bm_box(bm, (cy - Lc / 2 + 0.6, -COACH_W / 2 - 0.02, 2.45), (cy + Lc / 2 - 0.6, COACH_W / 2 + 0.02, 3.05))
        band = mesh_obj(f'Band{k}', bm, L['cream'] if loco else L['loco']); band.parent = root
        bm = bmesh.new()
        bm_box(bm, (cy - Lc / 2 + 0.3, -COACH_W / 2 + 0.25, 4.0), (cy + Lc / 2 - 0.3, COACH_W / 2 - 0.25, 4.35))
        for yb in (cy - Lc / 2 + 3.2, cy + Lc / 2 - 3.2):                     # bogies
            bm_box(bm, (yb - 1.6, -1.25, 0.25), (yb + 1.6, 1.25, 1.2))
        under = mesh_obj(f'Under{k}', bm, L['roof'] if not loco else L['bogie']); under.parent = root
        if loco:
            bm = bmesh.new(); bm_box(bm, (-0.05, -1.3, 2.6), (0.08, 1.3, 3.4))
            mesh_obj('LocoWind', bm, L['window']).parent = root
        y += Lc + 0.6
    ANIM['train_len'] = y
    root.location = (0, 0, DECK)
    OBJ['train'] = root
    anchor('train', (-y / 2, 0, 6.0), root)            # local to the train root
    return root


def build_eiffel(L):
    """Generic flat silhouette, 330 m, in the bridge plane (y = 0) under the arch. Flat colour, no modelled light."""
    w = lambda z: 62.5 * (1 - z / 300.0) ** 2.1 + 2.0
    g = lambda z: 44.0 * math.sqrt(max(0.0, 1 - (z / 48.0) ** 2))            # arch between the legs
    bm = bmesh.new(); th = 2.0
    def quad(x0a, x1a, za, x0b, x1b, zb_):
        vs = [bm.verts.new(p) for p in ((x0a, -th, za), (x1a, -th, za), (x1b, -th, zb_), (x0b, -th, zb_),
                                        (x0a, th, za), (x1a, th, za), (x1b, th, zb_), (x0b, th, zb_))]
        for f in ((0, 1, 2, 3), (7, 6, 5, 4), (0, 4, 5, 1), (1, 5, 6, 2), (2, 6, 7, 3), (3, 7, 4, 0)):
            bm.faces.new([vs[i] for i in f])
    zs = [0, 6, 12, 18, 24, 30, 36, 42, 46, 48]
    for za, zb_ in zip(zs, zs[1:]):
        for s in (-1, 1):
            quad(s * w(za), s * g(za), za, s * w(zb_), s * g(zb_), zb_)
    zs = [48, 60, 80, 100, 125, 150, 180, 210, 240, 270, 290, 300]
    for za, zb_ in zip(zs, zs[1:]):
        quad(-w(za), w(za), za, -w(zb_), w(zb_), zb_)
    for z, hh, ww in ((57, 7, 4), (115, 6, 3), (276, 5, 2)):                  # platforms
        quad(-w(z) - ww, w(z) + ww, z, -w(z + hh) - ww, w(z + hh) + ww, z + hh)
    quad(-1.2, 1.2, 300, -0.6, 0.6, EIFFEL)                                   # spire to 330 m
    o = mesh_obj('Eiffel', bm, L['eiffel']); OBJ['eiffel'] = o


def build_fx(L):
    # ghost pillar in the river (the one they did NOT build)
    bm = bmesh.new(); bm_box(bm, (-14, -14, 0), (14, 14, GB)); OBJ['ghost'] = mesh_obj('GhostPillar', bm, L['ghost'])
    # weight arrow under the train + dashed version
    OBJ['wArrow'] = []
    for side in (-1, 1):                                  # load leaves the train diagonally, toward each foundation
        root = empty(f'WArrow{side:+d}')
        sh = cyl(f'WArrow{side:+d}Shaft', (0, 0, 24), 2.8, 48, L['arrow']); sh.parent = root
        hd = cone(f'WArrow{side:+d}Head', (0, 0, 54), 7.5, 12, L['arrow']); hd.parent = root
        root['side'] = side; OBJ['wArrow'].append(root)
    # chevrons flowing along the near and far ribs, crown → springing, both halves
    OBJ['chev'] = []
    for side in (-1, 1):
        for rib in (-1, 1):
            for k in range(9):
                c = cone(f'Chev{side:+d}{rib:+d}{k}', (0, 0, 0), 6.0, 12.0, L['arrow'], verts=16)
                c['side'] = side; c['rib'] = rib; c['k'] = k; OBJ['chev'].append(c)
    OBJ['thrust'] = []
    for side in (-1, 1):                                    # thrust into the rock along the arch tangent
        root = empty(f'Thrust{side:+d}'); d = Vector((side, 0, -2 * (CROWN_B - Z_SPRING) / A)).normalized()
        tip = Vector((side * (A - 4), -(yr(A) + 6), Z_SPRING + RIB_D / 2))   # head ends at the foundation, in front of the near rib
        p0 = tip - d * 72
        sh = cyl(f'Thrust{side:+d}Shaft', (0, 0, 22), 4.5, 44, L['arrow']); sh.parent = root
        hd = cone(f'Thrust{side:+d}Head', (0, 0, 52), 11.0, 18, L['arrow']); hd.parent = root
        root.location = p0; point_along(root, d); OBJ['thrust'].append(root)
    # wind streaks across the arch (blowing up the gorge, along +y)
    OBJ['wind'] = []
    for k in range(22):
        x = -210 + (k * 53.3) % 420; z = 245 + (k * 37.1) % 130
        pts = [(x + 6 * math.sin(yy / 90 + k), yy, z + 5 * math.sin(yy / 70 + k * 0.7)) for yy in range(-320, 330, 25)]
        OBJ['wind'].append(tube_curve(f'Wind{k}', pts, 0.4, L['wind']))
    # shockwave (stylised: an expanding bright shell, no fire, no debris)
    bpy.ops.mesh.primitive_torus_add(major_radius=1.0, minor_radius=0.022, major_segments=128, minor_segments=12)
    OBJ['ring'] = bpy.context.object; OBJ['ring'].name = 'ShockRing'; OBJ['ring'].data.materials.append(L['shockRing'])
    bpy.ops.mesh.primitive_torus_add(major_radius=1.0, minor_radius=0.13, major_segments=96, minor_segments=16)
    OBJ['dust'] = bpy.context.object; OBJ['dust'].name = 'DustRing'; OBJ['dust'].data.materials.append(L['dust'])
    for o in (OBJ['ring'], OBJ['dust']):
        for p_ in o.data.polygons:
            p_.use_smooth = True
    # clouds: stylised puffs below the deck
    OBJ['clouds'] = []
    for k, (x, y, z, r) in enumerate(((-150, -90, 300, 22), (-60, 140, 292, 26), (40, -150, 310, 20), (120, 80, 296, 24),
                                       (190, -60, 286, 18), (-210, 60, 306, 20), (0, 260, 300, 30), (-120, -230, 284, 24))):
        for j in range(5):
            dx, dy, dz = (j - 2) * r * 0.8, (j % 2) * r * 0.5, -abs(j - 2) * r * 0.25
            s = sphere(f'Cloud{k}{j}', (x + dx, y + dy, z + dz), r * (1.0 - abs(j - 2) * 0.18), L['cloud'], seg=16)
            s.scale = (1.0, 1.0, 0.55); OBJ['clouds'].append(s)
    OBJ['sunDisc'] = sphere('SunDisc', (0, 0, 0), 60.0, L['sunDisc'])


def build_all(L):
    build_terrain(L); build_arch(L); build_deck(L); build_train(L); build_eiffel(L); build_fx(L)
    for name, p in (('bed', (0, 0, 0)), ('deck', (0, 0, DECK)), ('crown', (0, 0, zt(0))), ('eiffelTip', (0, 0, EIFFEL)),
                    ('springL', (-A, 0, Z_SPRING)), ('springR', (A, 0, Z_SPRING)), ('ghost', (0, 0, 175)),
                    ('abutR', (A + 20, 0, Z_SPRING)), ('truss', (60, -yr(60), zt(60) + 4)), ('pier', (350, -6, 305)),
                    ('archMid', (0, 0, 300))):
        anchor(name, p)


# ---------------------------------------------------------------- animation
def eo(u): u = min(1.0, max(0.0, u)); return 1 - (1 - u) ** 3
def eio(u): u = min(1.0, max(0.0, u)); return u * u * (3 - 2 * u)
def lerp(a, b, u): return a + (b - a) * u
def lerpv(a, b, u): return Vector(a).lerp(Vector(b), u)
def ease_move(u): return 0.3 * u + 0.7 * eio(u)


def shot_at_frame(f):
    t = (f - 1) / FPS
    for s in SHOTS:
        if s['t0'] <= t < s['t1']:
            return s
    return SHOTS[-1]


TRAIN_S0 = dict(H1=110, H2=40, N1=40, N2=80, P1=-900, P2=-900, P3=-900, A1=87, A2=81, A3=190, W1=-60, W2=40, W3=80, T1=420, T2=-900,
                T3=-900, Y1=20, Z1=140)


def train_front(name, t, t0):
    if name in ('H1', 'Z2'):                                 # loop: Z2 continues H1 backwards in time
        return TRAIN_S0['H1'] + V_TRAIN * (t - (END if name == 'Z2' else 0.0))
    return TRAIN_S0[name] + V_TRAIN * (t - t0)


def show(o, on):
    o.hide_render = not on; o.hide_viewport = not on
    for c in o.children:
        show(c, on)


def set_value(mat, node, v):
    mat.node_tree.nodes[node].outputs[0].default_value = v


def update(t, sh):
    n = sh['name']; u = (t - sh['t0']) / max(1e-6, sh['t1'] - sh['t0']); L = LIB['L']
    building = n in ('P1', 'P2', 'P3')
    grow = 0.0 if n in ('P1', 'P2') else (eio(min(1.0, u / 0.85)) if n == 'P3' else 1.0)
    for p in OBJ['panels']:                                  # panels appear from the banks inwards
        show(p, A - abs(p['xc']) <= grow * A + 1e-3)
    show(OBJ['deck']['M'], not building)
    for o in OBJ['archPiers']:
        show(o, not building)
    tr = OBJ['train']; show(tr, not building and n not in ('T2', 'T3'))
    s = train_front(n, t, sh['t0']); tr.location = (s, 0, DECK); ANIM['train_c'] = s - ANIM['train_len'] / 2
    # Eiffel silhouette: hook + fades back in during the return to the hook pose
    fe = 1.0 if n == 'H1' else (eio((u - 0.35) / 0.4) if n == 'Z2' else 0.0)
    show(OBJ['eiffel'], fe > 0.001); set_value(L['eiffel'], 'Fade', fe)
    # ghost pillar in the river
    show(OBJ['ghost'], n == 'P2')
    if n == 'P2':
        OBJ['ghost'].scale = (1, 1, eo(u / 0.45)); set_value(L['ghost'], 'Fade', 1.0 - eio((u - 0.75) / 0.25) * 0.85)
    # weight arrow + chevrons + thrust + glow
    for a_ in OBJ['wArrow']:
        show(a_, n == 'A1')
        if n == 'A1':
            sd = a_['side']; p0 = Vector((ANIM['train_c'] + sd * 4, 0, GB - 2))
            a_.location = p0; point_along(a_, Vector((sd * A, 0, Z_SPRING)) - Vector((0, 0, GB)))   # crown → foundation
            k = eo(u / 0.35); a_.scale = (1, 1, k)
    flow = n in ('A2', 'A3')
    for c in OBJ['chev']:
        show(c, flow)
        if flow:
            q = ((c['k'] + 0.0) / 9 + 0.35 * t) % 1.0      # 0 at the crown → 1 at the springing
            x = c['side'] * q * A * 0.97; zc = (zb(x) + zt(x)) / 2
            dzdx = -2 * (CROWN_B - Z_SPRING) * x / A ** 2
            c.location = (x, c['rib'] * (yr(x) + 3.0), zc); point_along(c, Vector((c['side'], 0, dzdx * c['side'])))
            sc_ = min(1.0, 4 * q, 4 * (1 - q)) * (eo(u / 0.3) if n == 'A2' else 1.0); c.scale = (sc_, sc_, sc_)
    for th in OBJ['thrust']:
        show(th, n in ('A2', 'A3'))                         # into the rock at BOTH foundations
        if n in ('A2', 'A3'):
            k = eo(u / 0.4) if n == 'A2' else 1.0; th.scale = (k, k, k)
    set_value(L['rock'], 'Glow', eio((u - 0.15) / 0.5) if n == 'A3' else 0.0)
    # wind
    wind = n in ('W1', 'W2', 'W3')
    for w in OBJ['wind']:
        show(w, wind)
    L['wind'].node_tree.nodes['FlowMap'].inputs['Location'].default_value[1] = -t * 2.2
    set_value(L['wind'], 'Fade', eio(u / 0.3) if n == 'W1' else 1.0)
    # shockwave on the north slope pier at x = 300
    on = n in ('T2', 'T3'); show(OBJ['ring'], on); show(OBJ['dust'], on)
    if on:                                                 # source on the slope in front of the pier base; rings lie on the slope
        c = Vector((350, -34, ground(350, -34) + 2.5)); tilt = -math.atan(0.33)
        r = lerp(3, 52, eo(u)) if n == 'T2' else lerp(52, 95, eo(u))
        rd = lerp(2, 34, eo(u)) if n == 'T2' else lerp(34, 42, eo(u))
        for o, rr, sz in ((OBJ['ring'], r, 1.0), (OBJ['dust'], rd, 0.45)):
            o.location = c; o.rotation_euler = (0, tilt, 0); o.scale = (rr, rr, rr * sz)
        set_value(L['shockRing'], 'Fade', 1.0 if n == 'T2' else 1.0 - eio(u / 0.7))
        set_value(L['dust'], 'Fade', 0.75 * (eio(u / 0.25) if n == 'T2' else 1.0 - eio(u / 0.5)))
    # clouds, sun
    for c in OBJ['clouds']:
        show(c, n in ('N2', 'Z1'))
    if n == 'Y1':
        a = math.radians(lerp(20, 20 + 360 * 3, u))      # 3 quick, smooth day cycles (no flashing)
        pos = Vector((-math.cos(a) * 3200, 5200, 280 + math.sin(a) * 2400))
        d = (Vector((0, 0, 280)) - pos).normalized(); el = max(0.0, math.sin(a))
        set_sun(d); OBJ['sun'].data.energy = 1.2 + 3.6 * el
        show(OBJ['sunDisc'], el > 0.02); OBJ['sunDisc'].location = tuple(pos)
        bpy.context.scene.world.node_tree.nodes['Background'].inputs['Strength'].default_value = 0.25 + 0.45 * el
    else:
        set_sun(Vector((0.45, 0.75, -0.62))); OBJ['sun'].data.energy = 5.5; show(OBJ['sunDisc'], False)
        bpy.context.scene.world.node_tree.nodes['Background'].inputs['Strength'].default_value = 0.7
    L['river'].node_tree.nodes['FlowMap'].inputs['Location'].default_value[1] = -t * 0.35


H1_POSE = ((-4.0, -205.0, 6.0), (0.0, 0.0, 215.0), 15.0)


def h1_pose(t):
    """The hook pose moving in time (t may be negative: the end shot follows it backwards into the loop)."""
    (lx, ly, lz), (tx, ty, tz), lens = H1_POSE
    return Vector((lx + 0.6 * t, ly, lz)), Vector((tx, ty, tz + 9.0 * t)), lens


CAMS = {   # name: (loc0, tgt0, lens0, loc1, tgt1, lens1)
    'H2': ((-95, -42, 364), (10, 0, 352), 30, (-80, -38, 363), (25, 0, 352), 30),
    'N1': ((0, -600, 300), (0, 0, 280), 24, (0, -740, 315), (0, 0, 282), 24),
    'N2': ((-150, -170, 262), (0, 0, 348), 22, (-110, -195, 290), (10, 0, 352), 22),
    'P1': ((0, -900, 430), (0, 0, 200), 24, (0, -620, 170), (0, 0, 80), 24),
    'P2': ((-30, -540, 120), (0, 0, 150), 22, (-30, -470, 115), (0, 0, 150), 22),
    'P3': ((0, -560, 290), (0, 0, 275), 24, (0, -720, 310), (0, 0, 278), 24),
    'A1': ((0, -250, 352), (0, 0, 345), 28, (0, -225, 352), (0, 0, 345), 28),
    'A2': ((0, -660, 290), (0, 0, 285), 24, (0, -630, 290), (0, 0, 285), 24),
    'A3': ((165, -270, 280), (245, 0, 205), 26, (180, -240, 270), (245, 0, 203), 26),
    'W1': ((-150, -265, 255), (0, 0, 300), 22, (-130, -255, 262), (20, 0, 305), 22),
    'W2': ((105, -80, 318), (55, 0, 312), 24, (80, -82, 322), (45, 0, 314), 24),
    'W3': ((80, -82, 322), (45, 0, 314), 24, (72, -82, 323), (42, 0, 314), 24),
    'T1': ((0, -700, 300), (0, 0, 280), 24, (0, -700, 300), (0, 0, 280), 24),
    'T2': ((396, -140, 300), (350, 0, 262), 22, (388, -128, 300), (350, 0, 264), 22),
    'T3': ((388, -128, 300), (350, 0, 264), 22, (384, -122, 301), (350, 0, 265), 22),
    'Y1': ((0, -700, 300), (0, 0, 310), 24, (0, -660, 300), (0, 0, 310), 24),
    'Z1': ((-10, -170, 300), (0, 120, 345), 20, (-5, 30, 302), (0, 220, 345), 20),
}


def camera_for(name, u, t):
    if name == 'H1':
        return h1_pose(t)
    if name == 'Z2':                                       # descend from under the arch and land on the H1 pose early
        dur = SHOTS[-1]['t1'] - SHOTS[-1]['t0']; land = (dur - JUNCTION_HOLD) / dur
        pl, pt, plens = h1_pose(t - END)
        if u >= land:
            return pl, pt, plens
        k = ease_move(u / land)
        a0, b0 = Vector((-5, -60, 250)), Vector((0, 150, 340))
        return a0.lerp(pl, k), b0.lerp(pt, k), lerp(20, plens, k)
    l0, t0_, f0, l1, t1_, f1 = CAMS[name]; k = ease_move(u)
    return lerpv(l0, l1, k), lerpv(t0_, t1_, k), lerp(f0, f1, k)


def frame_handler(scene, depsgraph=None):
    t = (scene.frame_current + scene.frame_subframe - 1) / FPS
    sh = shot_at_frame(scene.frame_current); ANIM['shot'] = sh['name']
    update(t, sh)
    bpy.context.view_layer.update()
    loc, tgt, lens = camera_for(sh['name'], (t - sh['t0']) / max(1e-6, sh['t1'] - sh['t0']), t)
    if sh['name'] == 'T1':                                  # one decaying jolt on "bhookamp" (never noise shake)
        dt = t - EV['BHOOKAMP']
        if 0 <= dt < 1.2:
            j = 2.2 * math.exp(-dt * 4.0) * math.sin(dt * 2 * math.pi * 3.0)
            loc = loc + Vector((0, 0, j)); tgt = tgt + Vector((0, 0, j))
    cam = scene.camera; cam.location = loc
    bpy.data.objects['CamTarget'].location = tgt; bpy.data.objects['CamFocus'].location = tgt; cam.data.lens = lens


def make_camera():
    sc = bpy.context.scene; tgt = empty('CamTarget', (0, 0, 0))
    bpy.ops.object.camera_add(location=(0, -10, 0)); cam = bpy.context.object; cam.name = 'Cam'; sc.camera = cam
    con = cam.constraints.new('TRACK_TO'); con.target = tgt; con.track_axis = 'TRACK_NEGATIVE_Z'; con.up_axis = 'UP_Y'
    cam.data.sensor_width = 36; cam.data.clip_start = 0.5; cam.data.clip_end = 20000
    cam.data.dof.use_dof = False; empty('CamFocus', (0, 0, 0))
    return cam


def setup_render(a):
    sc = bpy.context.scene; sc.render.fps = FPS
    sc.render.resolution_x, sc.render.resolution_y, sc.render.resolution_percentage = a.w, a.h, 100
    sc.render.image_settings.file_format = 'PNG'
    sc.view_settings.view_transform = 'AgX'
    looks = [i.identifier for i in sc.view_settings.bl_rna.properties['look'].enum_items]
    for want in ('AgX - Medium High Contrast', 'AgX - Base Contrast'):
        if want in looks:
            sc.view_settings.look = want; break
    if a.engine == 'WORKBENCH':
        sc.render.engine = 'BLENDER_WORKBENCH'
        shd = sc.display.shading; shd.light = 'STUDIO'; shd.color_type = 'MATERIAL'; shd.show_shadows = False
        sc.render.use_motion_blur = False
    else:
        sc.render.engine = 'CYCLES'
        sc.cycles.device = 'CPU'; sc.cycles.samples = a.samples; sc.cycles.use_adaptive_sampling = True
        sc.cycles.use_denoising = True; sc.cycles.denoiser = 'OPENIMAGEDENOISE'
        sc.cycles.max_bounces = 6; sc.cycles.transmission_bounces = 4; sc.cycles.transparent_max_bounces = 16
        sc.cycles.caustics_reflective = False; sc.cycles.caustics_refractive = False
        sc.render.use_motion_blur = not a.no_blur; sc.render.motion_blur_shutter = 0.5
        sc.render.motion_blur_position = 'START'


def export_anchors(path, frames):
    from bpy_extras.object_utils import world_to_camera_view
    sc = bpy.context.scene; out = {'fps': FPS, 'frames': {}}
    names = [o for o in bpy.data.objects if o.name.startswith('A_')]
    for f in frames:
        sc.frame_set(f); row = {'shot': ANIM['shot']}
        for o in names:
            v = world_to_camera_view(sc, sc.camera, o.matrix_world.translation)
            row[o.name[2:]] = [round(v.x, 4), round(1 - v.y, 4), round(v.z, 3)]
        out['frames'][f] = row
    json.dump(out, open(path, 'w'), indent=0)


def parse_args():
    argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else sys.argv[1:]
    p = argparse.ArgumentParser()
    p.add_argument('--frames', default='1')
    p.add_argument('--res', default='540x960')
    p.add_argument('--samples', type=int, default=32)
    p.add_argument('--engine', default='CYCLES', choices=['CYCLES', 'WORKBENCH'])
    p.add_argument('--out', default='frames')
    p.add_argument('--no-blur', action='store_true')
    p.add_argument('--before', action='store_true')        # unused here; accepted for the farm workflow
    p.add_argument('--anchors', default=None)
    p.add_argument('--refcam', action='store_true')   # side view for checking the silhouette against reference photos
    a = p.parse_args(argv)
    a.w, a.h = (int(x) for x in a.res.lower().split('x'))
    return a


def frame_list(spec):
    out = []
    for part in spec.split(','):
        if '-' in part:
            s0, s1 = (int(x) for x in part.split('-')); out += list(range(s0, s1 + 1))
        else:
            out.append(int(part))
    return out


def main():
    a = parse_args()
    bpy.ops.wm.read_factory_settings(use_empty=True)
    OBJ.clear(); ANIM.clear()
    L = materials.chenab_library(materials.train_library(materials.library()), glow=(A + 30, Z_SPRING)); LIB['L'] = L
    build_world(L); setup_render(a); build_all(L); make_camera()
    sc = bpy.context.scene; sc.frame_start, sc.frame_end = 1, int(round(END * FPS))
    bpy.app.handlers.frame_change_pre.clear(); bpy.app.handlers.frame_change_pre.append(frame_handler)
    frames = frame_list(a.frames)
    if a.anchors:
        export_anchors(a.anchors, frames); return
    if a.refcam:                                          # fixed side-on camera, level with the deck, from downstream
        bpy.app.handlers.frame_change_pre.clear(); sc.frame_set(500); frame_handler(sc)
        bpy.app.handlers.frame_change_pre.clear()
        for o in OBJ['chev'] + OBJ['thrust']:
            show(o, False)
        sc.render.resolution_x, sc.render.resolution_y = 1000, 610
        cam = sc.camera; cam.location = (40, -1500, 330); bpy.data.objects['CamTarget'].location = (40, 0, 250)
        cam.data.lens = 61
        for k in ('terrain', 'river', 'train'):
            show(OBJ[k], False)
        bpy.data.objects['Ground'].hide_render = True
    os.makedirs(a.out, exist_ok=True)
    sc.render.filepath = os.path.join(os.path.abspath(a.out), 'frame_')
    if '-' in a.frames and ',' not in a.frames:
        sc.frame_start, sc.frame_end = frames[0], frames[-1]; bpy.ops.render.render(animation=True)
    else:
        for f in frames:
            sc.frame_start = sc.frame_end = f; bpy.ops.render.render(animation=True)


if __name__ == '__main__':
    main()
