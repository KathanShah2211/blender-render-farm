"""Technical-cutaway scene: water pressure from a bottle to a building.

Usage (bpy module or blender -b -P):
    python3 scene.py --frames 1-948 --res 720x1280 --samples 32 --out frames/
    python3 scene.py --frames 133,397,505 --res 540x960 --samples 64 --out style/
    python3 scene.py --frames 1-948 --res 270x480 --engine WORKBENCH --out animatic/
    python3 scene.py --anchors anchors.json          # screen positions for post labels (no render)

Everything is built from primitives + modifiers. Shell cut faces get the orange hatch via boolean
material transfer; water cross-sections keep their own material. Camera, pump, needles and
stream growth use keyframes with eased Bezier F-curves. Free water (droplets, splashes,
dribble wobble) is procedural in a frame-change handler, so it also evaluates at motion-blur
sub-frames.

Physics (see beat sheet): Torricelli jets v = sqrt(2 g d); tank sits on the roof slab, water
surface at Z_SURF; gauge pressure ≈ depth below Z_SURF / 10.2 m per bar.
"""
import argparse, json, math, os, sys
import bpy
from mathutils import Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import materials  # noqa: E402

FPS = 24
# >>> CUES (generated — numbers only)
EV = {"HOLE_LOW_OPEN": 4.732, "HOLE_HIGH_OPEN": 7.636, "BOTTLE_CUT": 8.96, "NEEDLES": [16.627, 16.977, 17.327, 17.677], "PUMP_DROP": 26.3, "PUMP_SPIN": 27.785, "PUMP_LAND": 26.9, "BOOST_T": 29.205, "SHOWER_FULL": 29.805}
SHOTS = [{"name": "C0", "t0": 0.0, "t1": 2.43}, {"name": "B1", "t0": 2.43, "t1": 4.06}, {"name": "B2", "t0": 4.06, "t1": 6.77}, {"name": "B3", "t0": 6.77, "t1": 8.96}, {"name": "B4", "t0": 8.96, "t1": 10.942}, {"name": "B5", "t0": 10.942, "t1": 12.57}, {"name": "M1", "t0": 12.57, "t1": 14.096}, {"name": "M2", "t0": 14.096, "t1": 15.24}, {"name": "G1", "t0": 15.24, "t1": 16.327}, {"name": "G2", "t0": 16.327, "t1": 18.62}, {"name": "G3", "t0": 18.62, "t1": 20.64}, {"name": "T1", "t0": 20.64, "t1": 23.017}, {"name": "T2", "t0": 23.017, "t1": 24.7}, {"name": "T3", "t0": 24.7, "t1": 26.15}, {"name": "P1", "t0": 26.15, "t1": 27.635}, {"name": "P2", "t0": 27.635, "t1": 28.955}, {"name": "P3", "t0": 28.955, "t1": 29.655}, {"name": "P4", "t0": 29.655, "t1": 31.88}]
END = 31.88
# <<< CUES
T = dict(END=END)
HOLE_LOW_OPEN, HOLE_HIGH_OPEN, BOTTLE_CUT = EV['HOLE_LOW_OPEN'], EV['HOLE_HIGH_OPEN'], EV['BOTTLE_CUT']
NEEDLE_CUE = dict(zip(('G3', 'G2', 'G1', 'G0'), EV['NEEDLES']))      # top floor → ground floor
PUMP_DROP, PUMP_LAND, PUMP_SPIN = EV['PUMP_DROP'], EV['PUMP_LAND'], EV['PUMP_SPIN']
BOOST_T, SHOWER_FULL = EV['BOOST_T'], EV['SHOWER_FULL']
if '--before' in sys.argv:              # BEFORE half of the end split: same shots, but the pump never boosts
    BOOST_T = SHOWER_FULL = 1e6
G = 9.81

ROOF_Z = 12.125
STAND_H, TANK_R, TANK_H = 0.4, 0.95, 1.5      # low steel stand, black poly tank
Z_SURF = ROOF_Z + STAND_H + 1.35              # tank water surface ≈ 13.875
OUTLET_Z = ROOF_Z + STAND_H + 0.14            # outlet near the tank base
FLOOR_TOPS = [0.125, 3.125, 6.125, 9.125]


def fr(sec):
    return int(round(sec * FPS)) + 1


def tsec(scene):
    return (scene.frame_current + scene.frame_subframe - 1) / FPS


def bar_at(z):
    return max(0.0, (Z_SURF - z) / 10.2)


# ---------------------------------------------------------------- args
def parse_args():
    argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else sys.argv[1:]
    p = argparse.ArgumentParser()
    p.add_argument('--frames', default='1-%d' % fr(T['END']))
    p.add_argument('--res', default='720x1280')
    p.add_argument('--samples', type=int, default=32)
    p.add_argument('--engine', default='CYCLES', choices=['CYCLES', 'WORKBENCH'])
    p.add_argument('--out', default='frames')
    p.add_argument('--no-blur', action='store_true')
    p.add_argument('--anchors', default=None)
    p.add_argument('--before', action='store_true')
    a = p.parse_args(argv)
    if '-' in a.frames and ',' not in a.frames:
        s, e = a.frames.split('-'); a.frame_list = list(range(int(s), int(e) + 1)); a.range = (int(s), int(e))
    else:
        a.frame_list = [int(x) for x in a.frames.split(',')]; a.range = None
    a.w, a.h = (int(x) for x in a.res.lower().split('x'))
    return a


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


# ---------------------------------------------------------------- free water: tapered streams, droplets, splashes
STREAMS = []


class Stream:
    """A ballistic water stream: tapered translucent curve near the source that breaks into droplets,
    plus an optional splash where it lands. Shape is recomputed per frame (wobble, growth)."""

    def __init__(self, name, origin, vel, land_z, r0, mat, t_on, t_off=None, brk=0.6, n_drops=10,
                 wobble=0.0, splash=True, cling=None, grow=0.35, splash_v=0.35, splash_n=6, splash_r=0.6, wet_r=0.0, wet_mat=None,
                 layer=0):
        self.splash_v, self.splash_r, self.wet_r, self.layer = splash_v, splash_r, wet_r, layer
        self.name, self.o, self.v, self.land_z = name, Vector(origin), Vector(vel), land_z
        self.r0, self.t_on, self.t_off, self.brk, self.wobble, self.cling, self.grow = r0, t_on, t_off, brk, wobble, cling, grow
        # flight time to land_z (solve z0 + vz t - g t^2/2 = land_z)
        a, b, c = -0.5 * G, self.v.z, self.o.z - land_z
        self.t_end = (-b - math.sqrt(max(0.0, b * b - 4 * a * c))) / (2 * a) if cling is None else 0.6
        cu = bpy.data.curves.new(name, 'CURVE'); cu.dimensions = '3D'; cu.bevel_depth = r0; cu.bevel_resolution = 4
        cu.use_fill_caps = True
        self.N = 24
        sp = cu.splines.new('POLY'); sp.points.add(self.N - 1)
        self.obj = bpy.data.objects.new(name, cu); bpy.context.collection.objects.link(self.obj); cu.materials.append(mat)
        self.drops = []
        for i in range(n_drops):
            d = sphere(f'{name}_d{i}', origin, 1.0, mat, seg=12); self.drops.append(d)
        self.spl = []
        if splash:
            for i in range(splash_n):
                self.spl.append(sphere(f'{name}_s{i}', origin, 1.0, mat, seg=8))
        self.ring = None
        if splash and wet_r > 0:   # soft shiny wet patch that spreads (radial alpha falloff, no outline)
            bpy.ops.mesh.primitive_circle_add(vertices=40, radius=1.0, fill_type='NGON', location=origin)
            self.ring = bpy.context.object; self.ring.name = f'{name}_wet'; self.ring.data.materials.append(wet_mat)
        self.splash = splash
        STREAMS.append(self)

    def pos(self, tau, t, wob=True):
        if self.cling is not None:          # weak dribble clinging to a surface: slides straight down it
            x0, y0, zbot = self.cling
            z = self.o.z - (self.o.z - zbot) * min(1.0, tau / self.t_end)
            w = self.wobble * math.sin(9 * tau + 3.1 * t) * min(1.0, tau / self.t_end) if wob else 0
            return Vector((x0 + w * 0.3, y0 + w, z))
        p = self.o + self.v * tau + Vector((0, 0, -0.5 * G * tau * tau))
        if wob and self.wobble:
            k = tau / self.t_end
            p += Vector((math.sin(11 * tau + 4 * t) * self.wobble * k, math.cos(7 * tau + 3 * t) * self.wobble * k, 0))
        return p

    def update(self, t):
        on = t >= self.t_on and (self.t_off is None or t < self.t_off)
        g = min(1.0, max(0.0, (t - self.t_on) / self.grow)) if on else 0.0
        g = 1 - (1 - g) ** 3                                       # ease-out growth
        cu = self.obj.data; sp = cu.splines[0]
        tb = self.t_end * self.brk * g
        for i, p in enumerate(sp.points):
            u = i / (self.N - 1); tau = tb * u
            q = self.pos(tau, t)
            p.co = (q.x, q.y, q.z, 1.0)
            ripple = 1.0 + 0.18 * math.sin(38 * u - 14 * t) * u              # surface ripples grow toward the break
            p.radius = max(0.05, (1.0 - 0.7 * u) * ripple) * (1.0 if on else 0.0)  # taper: thick at source, thin at the break
        self.obj.hide_render = not on or g < 0.02
        # droplets beyond the break point, flowing along the arc
        n = len(self.drops)
        for i, d in enumerate(self.drops):
            ph = ((t - self.t_on) * 1.3 + i / n) % 1.0
            tau = self.t_end * (self.brk + (1 - self.brk) * ph)
            q = self.pos(tau, t)
            d.location = q
            vis = on and g >= 1.0 and t - self.t_on > 0.15
            r = self.r0 * (0.75 - 0.35 * ph) * (0.6 + 0.8 * ((i * 37) % 10) / 10)
            vel = (self.pos(tau + 0.01, t, False) - self.pos(tau, t, False))
            d.rotation_mode = 'QUATERNION'; d.rotation_quaternion = vel.to_track_quat('Z', 'Y') if vel.length > 1e-6 else (1, 0, 0, 0)
            s = r if vis else 0.0
            d.scale = (s, s, s * 1.8)                              # slightly elongated along motion
        # splash at the landing point
        if self.splash:
            land = self.pos(self.t_end, t, False)
            lv = on and g >= 1.0
            n = len(self.spl)
            for i, s in enumerate(self.spl):              # crown: droplets thrown up and out in a ring on impact
                ph = ((t - self.t_on) * 2.6 + i * 0.618) % 1.0
                a = i / max(1, n) * 2 * math.pi + 0.37 * math.sin(i * 1.7)
                sp_v = self.splash_v * (0.75 + 0.5 * ((i * 53) % 10) / 10)
                tt = ph * 0.26
                h = sp_v * 1.6 * tt - 0.5 * G * tt * tt
                rr0 = self.r0 * 1.2
                s.location = (land.x + math.cos(a) * (rr0 + sp_v * 0.7 * tt), land.y + math.sin(a) * (rr0 + sp_v * 0.7 * tt),
                              self.land_z + max(0.0, h) + 0.002)
                rr = self.r0 * self.splash_r * (1 - 0.55 * ph) if lv and h > -0.01 else 0.0
                s.scale = (rr, rr, rr * 1.4)
            if self.ring is not None:
                grow = min(1.0, max(0.0, (t - self.t_on - 0.1) / 1.6))
                rs = self.wet_r * (0.25 + 0.75 * (1 - (1 - grow) ** 2)) if lv else 0.0
                self.ring.location = (land.x, land.y, self.land_z + 0.0012 + 0.0004 * self.layer)
                self.ring.scale = (rs, rs * 0.92, 1.0)
                self.ring.hide_render = not lv


# ---------------------------------------------------------------- world, lights, ground
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
    sun.data.energy = 6.5; sun.data.color = (1.0, 0.80, 0.60); sun.data.angle = math.radians(3)
    sun.rotation_euler = (math.radians(70), 0, math.radians(-42))
    bpy.ops.mesh.primitive_plane_add(size=400, location=(0, 0, -0.125)); g = bpy.context.object; g.name = 'Ground'
    m = L['sand'].copy(); m.name = 'SandHaze'; g.data.materials.append(m)
    nt = m.node_tree; bsdf = nt.nodes.get('Principled BSDF')
    cam = nt.nodes.new('ShaderNodeCameraData'); mr = nt.nodes.new('ShaderNodeMapRange')
    mr.inputs['From Min'].default_value = 25; mr.inputs['From Max'].default_value = 140
    mix = nt.nodes.new('ShaderNodeMix'); mix.data_type = 'RGBA'
    src = bsdf.inputs['Base Color'].links[0].from_socket
    nt.links.new(cam.outputs['View Distance'], mr.inputs['Value']); nt.links.new(mr.outputs['Result'], mix.inputs['Factor'])
    nt.links.new(src, mix.inputs['A']); mix.inputs['B'].default_value = (0.86, 0.78, 0.64, 1)
    nt.links.new(mix.outputs['Result'], bsdf.inputs['Base Color'])


# ---------------------------------------------------------------- building, tank, pipes
TANK_X = 1.8
OBJ = {}


def build_building(L):
    bc = cutter('BuildingCut', (-0.7, -6, 0.2), (7, 0.0, 17), L['hatch'])   # removes front-right (y<0, x>-0.7)
    box('Partition', (-0.8, -2.75, -0.125), (-0.6, 2.75, 12.9), L['wall'], bevel=0.02)   # hides the cut boundary
    OBJ['bc'] = bc
    parts = []
    for i, z in enumerate([0, 3, 6, 9, 12]):
        parts.append(box(f'Slab{i}', (-3.75, -2.75, z - 0.125), (3.75, 2.75, z + 0.125), L['slab'], bevel=0.03))
    parts.append(box('WallBack', (-4, 2.75, -0.125), (4, 3.0, 12.9), L['wall'], bevel=0.04))
    parts.append(box('WallLeft', (-4, -2.75, -0.125), (-3.75, 2.75, 12.9), L['wall'], bevel=0.04))
    parts.append(box('WallRight', (3.75, -2.75, -0.125), (4, 2.75, 12.9), L['wall'], bevel=0.04))
    parts.append(box('WallFront', (-4, -3, -0.125), (4, -2.75, 12.9), L['wall'], bevel=0.04))
    for p in parts:
        cut(p, bc)
    for z in [1.4, 4.4, 7.4, 10.4]:
        box(f'Win{z}', (-3.2, -3.06, z), (-1.6, -2.95, z + 1.2), L['navy'], bevel=0.03)
        box(f'WinG{z}', (-3.05, -3.08, z + 0.15), (-1.75, -3.0, z + 1.05), L['glass'], bevel=0.01)
        box(f'Sill{z}', (-3.3, -3.18, z - 0.08), (-1.5, -2.95, z + 0.0), L['sill'], bevel=0.015)
    for i, ft in enumerate(FLOOR_TOPS):
        box(f'Tile{i}', (1.2, 2.68, ft), (3.75, 2.75, ft + 2.7), L['tile'], bevel=0.0)

    # pipes/cores get their own cut plane 4 mm behind the building's, so where they pass through a slab the
    # slab's cut face hides them (no coplanar z-fighting)
    pc = cutter('PipeCut', (-0.6, -6, 0.2), (7, 0.004, 17), L['hatch'])

    # classic black polyethylene roof tank: ribbed cylinder, domed top, screw lid, outlet near the base,
    # on a low steel stand on the roof slab; cut open with the water level visible
    sb = ROOF_Z + STAND_H
    tq = cutter('TankQuarter', (TANK_X, -2.0, ROOF_Z + 0.2), (TANK_X + 2.0, 0.0, 15.5), L['hatch'])   # front-right wedge
    for dx in (-0.62, 0.62):
        for dy in (-0.62, 0.62):
            box(f'StandLeg{dx}{dy}', (TANK_X + dx - 0.05, dy - 0.05, ROOF_Z), (TANK_X + dx + 0.05, dy + 0.05, sb - 0.05), L['pipe'], bevel=0.012)
    box('StandTopX', (TANK_X - 0.72, -0.72, sb - 0.06), (TANK_X + 0.72, 0.72, sb), L['pipe'], bevel=0.015)
    for i, (dx, dy, dz) in enumerate([(x, y, z) for x in (-TANK_R, TANK_R) for y in (-TANK_R, TANK_R) for z in (sb, sb + TANK_H + 0.25)]):
        anchor(f'kTank{i}', (TANK_X + dx, dy, dz))
    tank = cyl('Tank', (TANK_X, 0, sb + TANK_H / 2), TANK_R, TANK_H, L['poly'], bevel=0.05, verts=56)
    hollow(tank, cyl('TankHollow', (TANK_X, 0, sb + TANK_H / 2 + 0.04), TANK_R - 0.06, TANK_H, L['poly'], bevel=0, verts=56))
    cut(tank, tq)
    for k in range(5):                                  # horizontal ribs
        z = sb + 0.18 + k * (TANK_H - 0.36) / 4
        bpy.ops.mesh.primitive_torus_add(major_radius=TANK_R, minor_radius=0.035, major_segments=56, minor_segments=8, location=(TANK_X, 0, z))
        r = bpy.context.object; r.name = f'Rib{k}'; r.data.materials.append(L['poly']); cut(r, tq)
    bpy.ops.mesh.primitive_uv_sphere_add(segments=56, ring_count=16, radius=TANK_R, location=(TANK_X, 0, sb + TANK_H))
    dome = bpy.context.object; dome.name = 'TankDome'; dome.scale = (1, 1, 0.24); apply_scale(dome)
    dome.data.materials.append(L['poly'])
    for poly in dome.data.polygons:
        poly.use_smooth = True
    domecut = cutter('DomeLower', (TANK_X - 1.2, -1.2, sb + TANK_H - 0.4), (TANK_X + 1.2, 1.2, sb + TANK_H - 0.01), L['hatch'])
    m = dome.modifiers.new('Half', 'BOOLEAN'); m.operation = 'DIFFERENCE'; m.solver = 'EXACT'; m.object = domecut
    cut(dome, tq)
    lid_z = sb + TANK_H + TANK_R * 0.24 - 0.01            # screw lid sits ON the dome
    lid = cyl('TankLid', (TANK_X, 0, lid_z + 0.04), 0.27, 0.09, L['poly'], bevel=0.02, verts=40)
    for k in range(16):                                  # knurled grip
        ang = k / 16 * 2 * math.pi
        bx = box(f'LidGrip{k}', (-0.012, -0.03, -0.035), (0.012, 0.03, 0.035), L['poly'], bevel=0.005)
        bx.location = (TANK_X + 0.275 * math.cos(ang), 0.275 * math.sin(ang), lid_z + 0.04); bx.rotation_euler = (0, 0, ang)
    cut(lid, tq)
    wh = Z_SURF - (sb + 0.07)
    cut(cyl('TankWater', (TANK_X, 0, sb + 0.07 + wh / 2), TANK_R - 0.065, wh, L['water'], bevel=0, verts=56), tq, keep_material=True)
    anchor('surface', (TANK_X - TANK_R, -0.02, Z_SURF)); anchor('tank', (TANK_X, -0.02, sb + TANK_H + 0.4))

    # riser: tank bottom → ground floor, light grey pipe with a translucent flowing water core
    rz0, rz1 = 0.4, sb + 0.02
    riser = cyl('Riser', (TANK_X, 0, (rz0 + rz1) / 2), 0.11, rz1 - rz0, L['pipe'], bevel=0, verts=24)
    hollow(riser, cyl('RiserBore', (TANK_X, 0, (rz0 + rz1) / 2), 0.085, rz1 - rz0 + 0.4, L['pipe'], bevel=0, verts=24))
    cut(riser, pc)
    cut(cyl('RiserCore', (TANK_X, 0, (rz0 + rz1) / 2), 0.084, rz1 - rz0 - 0.02, L['pipeWater'], bevel=0, verts=24), pc, keep_material=True)

    # floor taps with pressure gauges (ground, 1st, 2nd); ground tap gushes into a bucket
    for i, ft in enumerate(FLOOR_TOPS[:3]):
        z = ft + 1.15
        pipe(f'Branch{i}', (TANK_X, 0.0, z), (TANK_X, 0.45, z), 0.05, L['pipe'])
        pipe(f'BranchX{i}', (TANK_X - 0.02, 0.45, z), (2.55, 0.45, z), 0.05, L['pipe'])
        pipe(f'Spout{i}', (2.5, 0.45, z), (2.72, 0.45, z - 0.04), 0.05, L['pipe'])
        box(f'Handle{i}', (2.42, 0.38, z + 0.07), (2.55, 0.52, z + 0.12), L['navy'], bevel=0.01)
        gauge(f'G{i}', (2.3, 0.45, z + 0.78), L, bar_at(z), stem=((2.3, 0.45, z), (2.3, 0.45, z + 0.4)))
    bucket = cyl('Bucket', (3.3, 0.45, 0.33), 0.26, 0.42, L['navy'], bevel=0.02, verts=32)
    hollow(bucket, cyl('BucketIn', (3.3, 0.45, 0.38), 0.23, 0.42, L['navy'], bevel=0, verts=32))
    cyl('BucketWater', (3.3, 0.45, 0.42), 0.225, 0.2, L['water'], bevel=0, verts=32)

    # top-floor supply: tank outlet (near the base) → (booster pump goes here, on the roof) → down-line → shower
    oz = OUTLET_Z
    pipe('Outlet', (TANK_X + TANK_R - 0.02, 0, oz), (3.0, 0, oz), 0.05, L['pipe'])
    cyl('OutletCollar', (TANK_X + TANK_R + 0.02, 0, oz), 0.08, 0.06, L['poly'], rot=(0, math.radians(90), 0), bevel=0.01, verts=24)
    OBJ['inline'] = pipe('Inline', (3.0, 0, oz), (3.42, 0, oz), 0.05, L['pipe'])          # replaced by the pump
    pipe('Elbow', (3.42, 0, oz), (3.55, 0, oz), 0.05, L['pipe'])
    dz1 = 11.55
    down = cyl('DownLine', (3.5, 0, (oz + dz1) / 2), 0.065, oz - dz1, L['pipe'], bevel=0, verts=20)
    hollow(down, cyl('DownBore', (3.5, 0, (oz + dz1) / 2), 0.048, oz - dz1 + 0.3, L['pipe'], bevel=0, verts=20))
    cut(down, pc)
    cut(cyl('DownCore', (3.5, 0, (oz + dz1) / 2), 0.047, oz - dz1 - 0.02, L['pipeWater'], bevel=0, verts=20), pc, keep_material=True)
    pipe('ShowerFeed', (3.5, 0, dz1), (3.5, 0.45, dz1), 0.05, L['pipe'])
    pipe('ShowerArm', (3.5, 0.45, dz1), (3.5, 0.45, 11.32), 0.04, L['pipe'])
    cyl('ShowerHead', (3.5, 0.45, 11.3), 0.17, 0.06, L['pipe'], bevel=0.02, verts=32)
    gauge('G3', (2.95, 0.45, 11.35), L, bar_at(11.3), boosted=2.0, stem=((3.5, 0.45, 11.45), (3.3, 0.45, 11.45)), label_side=-1)
    anchor('shower', (3.5, 0.45, 10.6)); anchor('showerEdge', (3.95, 0.45, 9.3))


# ---------------------------------------------------------------- pressure gauges (dial + animated needle)
GAUGES = []


def gauge(name, loc, L, value, boosted=None, stem=None, label_side=1):
    """Large dial facing the camera (−y). 0–2.5 bar over −120°..+120°. Needle springs to `value` at its cue."""
    x, y, z = loc
    a, b = stem if stem else ((x, y, z - 0.6), (x, y, z - 0.38))
    pipe(f'{name}Stem', a, b, 0.03, L['pipe'])
    cyl(f'{name}Body', (x, y, z), 0.4, 0.1, L['navy'], rot=(math.radians(90), 0, 0), bevel=0.03, verts=48)
    cyl(f'{name}Face', (x, y - 0.052, z), 0.34, 0.012, L['dial'], rot=(math.radians(90), 0, 0), bevel=0, verts=48)
    for k in range(11):
        an = math.radians(-120 + 240 * k / 10)
        r1, r2 = 0.26, (0.32 if k % 2 == 0 else 0.3)
        p1 = (x + r1 * math.sin(an), y - 0.062, z + r1 * math.cos(an)); p2 = (x + r2 * math.sin(an), y - 0.062, z + r2 * math.cos(an))
        pipe(f'{name}T{k}', p1, p2, 0.01, L['tick'], verts=6)
    # red zone arc marker near the top of the scale
    piv = bpy.data.objects.new(f'{name}Pivot', None); bpy.context.collection.objects.link(piv); piv.location = (x, y - 0.072, z)
    nd = box(f'{name}Needle', (-0.016, -0.006, -0.04), (0.016, 0.006, 0.27), L['needle'], bevel=0.005); nd.parent = piv
    hub = cyl(f'{name}Hub', (0, 0, 0), 0.036, 0.018, L['navy'], rot=(math.radians(90), 0, 0), bevel=0, verts=20); hub.parent = piv
    ang = lambda v: math.radians(-120 + 240 * min(1.0, v / 2.5))
    t_cue = NEEDLE_CUE[name]
    if name == 'G3':        # top floor: already reads its low value on frame 1 (cold open = loop end), dips and re-springs at its cue
        piv.rotation_euler = (0, ang(value), 0)
        piv.keyframe_insert('rotation_euler', index=1, frame=1); piv.keyframe_insert('rotation_euler', index=1, frame=fr(t_cue) - 4)
    piv.rotation_euler = (0, ang(0), 0); piv.keyframe_insert('rotation_euler', index=1, frame=fr(t_cue))
    piv.rotation_euler = (0, ang(value), 0); piv.keyframe_insert('rotation_euler', index=1, frame=fr(t_cue + 0.7))
    if boosted:
        piv.keyframe_insert('rotation_euler', index=1, frame=fr(BOOST_T))
        piv.rotation_euler = (0, ang(boosted), 0); piv.keyframe_insert('rotation_euler', index=1, frame=fr(BOOST_T + 0.8))
    for fc in fcurves_of(piv):
        for kp in fc.keyframe_points:
            kp.interpolation = 'BACK'; kp.easing = 'EASE_OUT'; kp.back = 1.4   # spring-like overshoot
    anchor(name, (x + 0.5 * label_side, y - 0.07, z)); anchor('c' + name, (x, y - 0.07, z)); anchor('e' + name, (x + 0.4, y - 0.07, z + 0.4))
    GAUGES.append(dict(name=name, value=round(value, 2), boosted=boosted, cue=t_cue))


# ---------------------------------------------------------------- height pole (from the ground) + dashed water-level line
def build_ruler(L):
    rx, ry = 4.75, -0.35
    box('Pole', (rx - 0.08, ry - 0.08, -0.12), (rx + 0.08, ry + 0.08, Z_SURF + 0.35), L['pole'], bevel=0.025)
    for k in range(0, int(Z_SURF) + 1):
        major = k in (0, 10)
        ln = 0.42 if major else (0.26 if k % 5 == 0 else 0.15)
        box(f'Pt{k}', (rx - 0.08 - ln, ry - 0.045, k + 0.0 - 0.03 + (0.03 if k == 0 else 0)), (rx - 0.08, ry + 0.045, k + 0.03 + (0.03 if k == 0 else 0)),
            L['needle'] if major else L['tick'], bevel=0.01)
    box('PtTank', (rx - 0.08 - 0.42, ry - 0.045, Z_SURF - 0.03), (rx - 0.08, ry + 0.045, Z_SURF + 0.03), L['needle'], bevel=0.01)
    # dashed line: tank water level → pole
    x0, x1 = TANK_X + TANK_R + 0.05, rx - 0.55
    n = int((x1 - x0) / 0.16)
    for i in range(n):
        xa = x0 + i * (x1 - x0) / n
        box(f'Dash{i}', (xa, ry - 0.02, Z_SURF - 0.02), (xa + 0.09, ry + 0.02, Z_SURF + 0.02), L['needle'], bevel=0.0)
    anchor('pole0', (rx + 0.18, ry, 0.03)); anchor('pole10', (rx + 0.18, ry, 10.0)); anchor('poleTank', (rx + 0.18, ry, Z_SURF))
    anchor('dash', ((x0 + x1) / 2, ry, Z_SURF + 0.15))


# ---------------------------------------------------------------- bottle on a crate on the roof (open, no cap)
B_BASE = Vector((-2.75, -1.0, 12.625))
B_H, B_R, WATER_LVL = 0.36, 0.045, 0.30
HOLE_LOW, HOLE_HIGH = 0.04, 0.285


def build_bottle(L):
    box('Crate', (-2.85, -1.25, ROOF_Z), (-2.2, -0.75, B_BASE.z), L['wood'], bevel=0.015)
    for i in range(3):
        box(f'Slat{i}', (-2.86, -1.26, ROOF_Z + 0.05 + i * 0.15), (-2.19, -0.74, ROOF_Z + 0.09 + i * 0.15), L['wood'], bevel=0.008)
    bc = cutter('BottleCut', (-3.2, -1.7, 12.5), (-2.3, -1.0, 13.2), L['hatch'])
    bottle = cyl('Bottle', (B_BASE.x, B_BASE.y, B_BASE.z + B_H / 2), B_R, B_H, L['plastic'], bevel=0.012, verts=40)
    hollow(bottle, cyl('BottleIn', (B_BASE.x, B_BASE.y, B_BASE.z + B_H / 2 + 0.006), B_R - 0.003, B_H, L['plastic'], bevel=0, verts=40))
    # open neck — no cap, so air can get in and the water keeps flowing
    neck = cyl('Neck', (B_BASE.x, B_BASE.y, B_BASE.z + B_H + 0.022), 0.017, 0.045, L['plastic'], bevel=0.003, verts=24)
    hollow(neck, cyl('NeckIn', (B_BASE.x, B_BASE.y, B_BASE.z + B_H + 0.03), 0.013, 0.06, L['plastic'], bevel=0, verts=24))
    water = cyl('BottleWater', (B_BASE.x, B_BASE.y, B_BASE.z + 0.006 + (WATER_LVL - 0.006) / 2), B_R - 0.0035, WATER_LVL - 0.006,
                L['bottleWater'], bevel=0, verts=40)
    # visible water line (meniscus ring) with the air gap above it
    bpy.ops.mesh.primitive_torus_add(major_radius=B_R - 0.0035, minor_radius=0.0016, location=(B_BASE.x, B_BASE.y, B_BASE.z + WATER_LVL))
    ml = bpy.context.object; ml.name = 'Meniscus'; ml.data.materials.append(L['cap'])
    for md in (cut(bottle, bc), cut(water, bc, keep_material=True), cut(ml, bc)):
        key_mod(md, fr(BOTTLE_CUT) - 1, False); key_mod(md, fr(BOTTLE_CUT), True)
    for z in (HOLE_LOW, HOLE_HIGH):
        bpy.ops.mesh.primitive_torus_add(major_radius=0.006, minor_radius=0.0018, location=(B_BASE.x - B_R, B_BASE.y, B_BASE.z + z),
                                         rotation=(0, math.radians(90), 0))
        bpy.context.object.data.materials.append(L['navy'])
    anchor('bottle', (B_BASE.x, B_BASE.y, B_BASE.z + B_H / 2))


# ---------------------------------------------------------------- streams
def build_streams(L):
    W = L['glassWater']; o = B_BASE
    v_low = math.sqrt(2 * G * (WATER_LVL - HOLE_LOW))                    # ≈ 2.3 m/s (Torricelli)
    WET = L['wet']
    Stream('JetLow', (o.x - B_R - 0.003, o.y, o.z + HOLE_LOW), (-v_low, 0, 0), ROOF_Z, 0.022, W, HOLE_LOW_OPEN,
           brk=0.3, n_drops=26, splash_v=0.5, splash_n=14, splash_r=0.45, wet_r=0.11, wet_mat=WET)
    # high hole: only 1.5 cm of water above it → a weak dribble that clings and runs down the bottle side
    Stream('DribbleHigh', (o.x - B_R - 0.003, o.y, o.z + HOLE_HIGH), (0, 0, 0), o.z, 0.0065, W, HOLE_HIGH_OPEN,
           brk=0.7, n_drops=6, wobble=0.004, splash=True, splash_n=4, splash_v=0.12, splash_r=0.5, wet_r=0.035, wet_mat=WET,
           cling=(o.x - B_R - 0.004, o.y, o.z + 0.002), grow=1.2)
    # ground-floor tap: thick, fast gush that splashes out of the bucket
    z0 = FLOOR_TOPS[0] + 1.15 - 0.06
    Stream('Gush', (2.74, 0.45, z0), (2.0, 0, -0.15), 0.55, 0.06, W, -2.0, brk=0.55, n_drops=22,
           splash_v=1.4, splash_n=16, splash_r=0.55)
    # top-floor shower BEFORE the pump: weak, wobbly dribbles + drips (approved look)
    for i, (dx, dy) in enumerate([(-0.06, 0.0), (0.03, 0.05), (0.05, -0.04), (-0.02, -0.06)]):
        Stream(f'Weak{i}', (3.5 + dx, 0.45 + dy, 11.26), (0.02 * dx, 0.02 * dy, -0.05), FLOOR_TOPS[3], 0.017, W, -2.0,
               t_off=SHOWER_FULL + 0.2, brk=0.14 + 0.05 * i, n_drops=5, wobble=0.016, splash=(i == 0),
               splash_v=0.2, splash_n=5, splash_r=0.5, wet_r=0.12, wet_mat=WET, layer=1)
    # AFTER the pump: dense, wide, strong cone (three rings, 40 streams) + fine mist
    k = 0
    for ring, (n, r, out) in enumerate([(8, 0.04, 0.35), (14, 0.09, 0.8), (18, 0.14, 1.25)]):
        for i in range(n):
            a = i / n * 2 * math.pi + ring * 0.21
            Stream(f'Full{k}', (3.5 + r * math.cos(a), 0.45 + r * math.sin(a), 11.26),
                   (out * math.cos(a), out * math.sin(a), -2.4), FLOOR_TOPS[3], 0.0085 + 0.002 * (k % 3), W, SHOWER_FULL,
                   brk=0.32 + 0.12 * ((k * 7) % 5) / 4, n_drops=12, splash=(k % 3 == 0), grow=0.45, splash_v=0.6, splash_n=4, splash_r=0.7,
                   wet_r=(0.42 if k == 0 else 0.0), wet_mat=WET, layer=2)   # one soft wet patch under the shower
            k += 1
    MIST.clear()
    for i in range(70):
        MIST.append(sphere(f'Mist{i}', (3.5, 0.45, 11.0), 1.0, W, seg=8))


MIST = []


# ---------------------------------------------------------------- booster pump (inline on the down-line, on the roof slab)
PUMP = {}


def build_pump(L):
    oz = OUTLET_Z
    bpy.ops.object.empty_add(location=(3.21, 0, oz)); root = bpy.context.object; root.name = 'PumpRoot'
    parts = [
        cyl('PumpBody', (3.21, 0, oz), 0.2, 0.36, L['yellow'], rot=(0, math.radians(90), 0), bevel=0.03, verts=40),
        cyl('FlangeIn', (3.02, 0, oz), 0.09, 0.04, L['navy'], rot=(0, math.radians(90), 0), bevel=0.01, verts=24),
        cyl('FlangeOut', (3.40, 0, oz), 0.09, 0.04, L['navy'], rot=(0, math.radians(90), 0), bevel=0.01, verts=24),
        box('PumpMotor', (3.02, 0.06, oz + 0.16), (3.40, 0.46, oz + 0.42), L['navy'], bevel=0.04),
        box('PumpFeet', (3.0, -0.25, ROOF_Z), (3.42, 0.3, oz - 0.17), L['navy'], bevel=0.02),
    ]
    pc = cutter('PumpCut', (2.9, -1.0, oz - 0.4), (3.55, 0.0, oz + 0.6), L['hatch'])
    cut(parts[0], pc)
    imp = bpy.data.objects.new('Impeller', None); bpy.context.collection.objects.link(imp); imp.location = (3.21, -0.01, oz)
    for i in range(6):
        b = box(f'Blade{i}', (-0.012, -0.012, -0.15), (0.012, 0.012, 0.15), L['steel'], bevel=0.006)
        b.parent = imp; b.rotation_euler = (i / 6 * math.pi, 0, 0)
    hub = cyl('Hub', (0, 0, 0), 0.05, 0.08, L['navy'], rot=(0, math.radians(90), 0), bevel=0.01, verts=20); hub.parent = imp
    for o in parts + [pc, imp]:
        o.parent = root; o.matrix_parent_inverse = root.matrix_world.inverted()
    PUMP['imp'] = imp
    for i, (dx, dy, dz) in enumerate([(x, y, z) for x in (2.95, 3.47) for y in (-0.25, 0.46) for z in (oz - 0.2, oz + 0.44)]):
        k = anchor(f'kPump{i}', (dx, dy, dz)); k.parent = root; k.matrix_parent_inverse = root.matrix_world.inverted()
    root.location.z = oz + 3.0; root.keyframe_insert('location', index=2, frame=1)
    root.keyframe_insert('location', index=2, frame=fr(PUMP_DROP))
    root.location.z = oz; root.keyframe_insert('location', index=2, frame=fr(PUMP_LAND))
    for fc in fcurves_of(root):
        for kp in fc.keyframe_points:
            kp.interpolation = 'BEZIER'
            if int(round(kp.co[0])) == fr(PUMP_DROP):
                kp.interpolation = 'BOUNCE'; kp.easing = 'EASE_OUT'
    key_visible(root, 1, False)
    for o in [root] + parts + list(imp.children):
        key_visible(o, fr(PUMP_DROP) - 1, False); key_visible(o, fr(PUMP_DROP), True)
    key_visible(OBJ['inline'], fr(PUMP_LAND) - 1, True); key_visible(OBJ['inline'], fr(PUMP_LAND), False)


# ---------------------------------------------------------------- pipe-water scroll (keyframed texture offset)
def animate_pipe_water(L):
    m = L['pipeWater']; mp = m.node_tree.nodes['Scroll']
    tb = min(PUMP_SPIN, END)
    keys = [(1, 0.0), (fr(tb), -0.45 * tb), (fr(END), -0.45 * tb - 1.2 * (END - tb))]
    for f, z in keys:
        mp.inputs['Location'].default_value[2] = -z; mp.inputs['Location'].keyframe_insert('default_value', index=2, frame=f)
    ease_all(m.node_tree)


def on_frame(scene, depsgraph=None):
    t = tsec(scene)
    for s in STREAMS:
        s.update(t)
    on = t >= SHOWER_FULL + 0.2
    for i, m in enumerate(MIST):
        ph = (t * 0.9 + i * 0.6180339) % 1.0
        a = i * 2.39996; rr = 0.15 + 0.75 * ((i * 37) % 10) / 10
        tau = ph * 0.6
        m.location = (3.5 + math.cos(a) * rr * ph, 0.45 + math.sin(a) * rr * ph, 11.2 - 2.4 * tau - 0.5 * G * tau * tau * 0.4)
        s = (0.006 + 0.004 * ((i * 53) % 10) / 10) if on and m.location.z > FLOOR_TOPS[3] else 0.0
        m.scale = (s, s, s)
    if 'imp' in PUMP:
        spin = max(0.0, t - PUMP_SPIN)
        PUMP['imp'].rotation_euler = (spin * spin * 6.0 if spin < 1 else 6.0 + (spin - 1) * 12.0, 0, 0)


# ---------------------------------------------------------------- camera (eased keyframes per shot)
def shot_poses():
    """Start/end pose per shot: (cam_start, cam_end, target_start, target_end, lens, fstop)."""
    Bc = Vector((B_BASE.x, B_BASE.y, B_BASE.z + B_H / 2)); V = lambda *a: Vector(a)
    SH_T = {s['name']: (s['t0'], s['t1']) for s in SHOTS}
    v_low = math.sqrt(2 * G * (WATER_LVL - HOLE_LOW)); fall = B_BASE.z + HOLE_LOW - ROOF_Z
    JET_LAND = V(B_BASE.x - B_R - v_low * math.sqrt(2 * fall / G), B_BASE.y, ROOF_Z)
    SH_A = (V(3.04, -2.85, 11.0), V(3.08, 0.45, 10.45))     # top-floor shower framing (cold open = loop end)
    SH_B = (V(3.10, -2.55, 10.95), V(3.10, 0.45, 10.45))     # front view: the right wall's cut face stays out of shot
    return {
        'C0': (SH_A[0], SH_B[0], SH_A[1], SH_B[1], 40, 4.0),
        'B1': (Bc + V(-0.30, -1.55, 0.12), Bc + V(-0.36, -1.38, 0.10), Bc + V(-0.15, 0, -0.12), Bc + V(-0.15, 0, -0.12), 45, 2.8),
        'B2': dict(lens=45, fstop=3.2, way=[            # bottle ~35% of frame height → follow the jet down to its landing
            (SH_T['B2'][0], Bc + V(0.05, -1.12, 0.02), Bc + V(-0.03, 0, -0.01)),
            (HOLE_LOW_OPEN + 0.25, Bc + V(0.0, -1.02, 0.0), Bc + V(-0.07, 0, -0.04)),
            (SH_T['B2'][1], JET_LAND + V(0.2, -1.3, 0.32), JET_LAND + V(0.16, 0, 0.12))]),
        'B3': (Bc + V(-0.24, -0.34, 0.14), Bc + V(-0.20, -0.29, 0.12), Bc + V(-0.05, 0, 0.06), Bc + V(-0.05, 0, 0.05), 50, 2.0),
        'B4': (Bc + V(-0.45, -0.95, 0.06), Bc + V(-0.30, -0.98, 0.08), Bc + V(-0.08, 0, -0.02), Bc + V(-0.06, 0, -0.02), 45, 2.8),
        'B5': (Bc + V(0.04, -0.95, 0.0), Bc + V(0.0, -0.82, 0.0), Bc, Bc, 45, 2.8),
        'M1': (V(1.65, -32.7, 7.2), V(1.65, -30.0, 7.2), V(1.65, 0, 7.2), V(1.65, 0, 7.2), 45, 11.0),   # match-cut: same screen position
        'M2': (V(13.2, -22.0, 10.8), V(12.4, -20.6, 10.3), V(0.9, 0.2, 6.9), V(0.9, 0.2, 6.9), 40, 9.0),
        'G1': (V(12.2, -17.8, 8.8), V(11.6, -17.0, 8.5), V(2.9, 0.2, 7.0), V(2.9, 0.2, 7.0), 40, 8.0),
        'G2': (V(7.6, -10.2, 6.2), V(8.4, -9.4, 6.6), V(2.4, 0.45, 6.2), V(2.4, 0.45, 6.3), 40, 7.0),
        'G3': (V(6.2, -6.0, 2.0), V(5.8, -5.6, 1.9), V(2.95, 0.45, 1.05), V(2.95, 0.45, 1.0), 40, 4.5),
        'T1': (V(8.0, -8.6, 12.4), V(7.4, -8.0, 12.2), V(2.6, 0.2, 11.8), V(2.6, 0.2, 11.7), 40, 7.0),
        'T2': (V(5.6, -5.0, 12.9), V(5.3, -4.6, 12.7), V(2.8, 0.3, 12.4), V(2.8, 0.3, 12.3), 40, 5.0),
        'T3': (V(3.38, -1.62, 11.2), V(3.4, -1.42, 11.15), V(3.4, 0.45, 10.72), V(3.4, 0.45, 10.7), 40, 3.0),   # weak shower, big
        'P1': (V(6.4, -6.4, 14.2), V(6.0, -6.0, 13.9), V(2.9, 0.1, 12.7), V(2.9, 0.1, 12.7), 40, 6.0),
        'P2': (V(5.0, -2.2, 13.45), V(4.7, -1.85, 13.3), V(3.21, 0, 12.6), V(3.21, 0, 12.6), 45, 4.0),
        'P3': (V(3.75, -1.55, 11.55), V(3.6, -1.35, 11.45), V(2.95, 0.45, 11.35), V(2.95, 0.45, 11.35), 45, 3.5),
        'P4': (SH_B[0], SH_A[0], SH_B[1], SH_A[1], 40, 4.0),   # reverse of C0: ends exactly on the cold-open frame
    }


def ease_move(u):
    """Smoothstep blended with linear: eased, but the camera never stops inside a shot."""
    return 0.3 * u + 0.7 * (u * u * (3 - 2 * u))


def build_camera():
    sc = bpy.context.scene
    bpy.ops.object.empty_add(location=(0, 0, 0)); tgt = bpy.context.object; tgt.name = 'CamTarget'
    bpy.ops.object.camera_add(); cam = bpy.context.object; cam.name = 'Cam'; sc.camera = cam
    con = cam.constraints.new('TRACK_TO'); con.target = tgt; con.track_axis = 'TRACK_NEGATIVE_Z'; con.up_axis = 'UP_Y'
    cam.data.dof.use_dof = True; cam.data.dof.focus_object = tgt; cam.data.sensor_width = 36
    P = shot_poses()
    last_frames = set()
    for sh in SHOTS:
        f0, f1 = fr(sh['t0']), fr(sh['t1']) - 1
        if sh is SHOTS[-1]:
            f1 = fr(END)
        p = P[sh['name']]
        if isinstance(p, dict):
            lens, fstop, way = p['lens'], p['fstop'], p['way']
        else:
            c0, c1, g0, g1, lens, fstop = p
            way = [(sh['t0'], c0, g0), (sh['t1'], c1, g1)]
        wf = [fr(w[0]) for w in way]; wf[0], wf[-1] = f0, f1
        for f in range(f0, f1 + 1):
            k = max(i for i in range(len(way) - 1) if wf[i] <= f) if f < wf[-1] else len(way) - 2
            u = ease_move(min(1.0, (f - wf[k]) / max(1, wf[k + 1] - wf[k])))
            cam.location = way[k][1].lerp(way[k + 1][1], u); cam.keyframe_insert('location', frame=f)
            tgt.location = way[k][2].lerp(way[k + 1][2], u); tgt.keyframe_insert('location', frame=f)
            cam.data.lens = lens; cam.data.keyframe_insert('lens', frame=f)
            cam.data.dof.aperture_fstop = fstop; cam.data.dof.keyframe_insert('aperture_fstop', frame=f)
        last_frames.add(f1)
    for idb in (cam, tgt, cam.data):
        for fc in fcurves_of(idb):
            for kp in fc.keyframe_points:
                kp.interpolation = 'CONSTANT' if int(round(kp.co[0])) in last_frames else 'BEZIER'
    return cam


# ---------------------------------------------------------------- render setup
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
        sh = sc.display.shading; sh.light = 'STUDIO'; sh.color_type = 'MATERIAL'; sh.show_shadows = True; sh.show_cavity = True
        sc.render.use_motion_blur = False
    else:
        sc.render.engine = 'CYCLES'
        sc.cycles.device = 'CPU'; sc.cycles.samples = a.samples; sc.cycles.use_adaptive_sampling = True
        sc.cycles.use_denoising = True; sc.cycles.denoiser = 'OPENIMAGEDENOISE'
        sc.cycles.max_bounces = 12; sc.cycles.transmission_bounces = 12; sc.cycles.glossy_bounces = 3
        sc.cycles.caustics_reflective = False; sc.cycles.caustics_refractive = False
        sc.render.use_motion_blur = not a.no_blur; sc.render.motion_blur_shutter = 0.5
        sc.render.motion_blur_position = 'START'   # shutter opens at the frame: no smear across cuts


def build_all():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    STREAMS.clear(); GAUGES.clear(); PUMP.clear(); OBJ.clear()
    sc = bpy.context.scene
    sc.frame_start, sc.frame_end = 1, fr(T['END'])
    L = materials.library()
    build_world(L)
    build_building(L)
    build_ruler(L)
    build_bottle(L)
    build_streams(L)
    build_pump(L)
    animate_pipe_water(L)
    build_camera()
    bpy.app.handlers.frame_change_pre.clear()
    bpy.app.handlers.frame_change_pre.append(on_frame)
    return L


def export_anchors(path):
    """Per-frame normalized screen positions (x right, y down) of label anchors, for post overlays."""
    from bpy_extras.object_utils import world_to_camera_view
    sc = bpy.context.scene; cam = sc.camera
    names = [o for o in bpy.data.objects if o.name.startswith('A_')]
    out = {'fps': FPS, 'frames': {}, 'gauges': GAUGES, 'timeline': T,
           'pump': {'drop': PUMP_DROP, 'land': PUMP_LAND, 'shower_full': SHOWER_FULL}}
    for f in range(1, fr(T['END']) + 1):
        sc.frame_set(f)
        row = {}
        for o in names:
            v = world_to_camera_view(sc, cam, o.matrix_world.translation)
            row[o.name[2:]] = [round(v.x, 4), round(1 - v.y, 4), round(v.z, 3)]
        out['frames'][f] = row
    with open(path, 'w') as fh:
        json.dump(out, fh)


def main():
    a = parse_args()
    build_all()
    setup_render(a)
    sc = bpy.context.scene
    sc.render.resolution_x, sc.render.resolution_y = a.w, a.h
    if a.anchors:
        export_anchors(a.anchors); return
    os.makedirs(a.out, exist_ok=True)
    sc.render.filepath = os.path.join(os.path.abspath(a.out), 'before_' if a.before else 'frame_')
    if a.range:
        sc.frame_start, sc.frame_end = a.range
        bpy.ops.render.render(animation=True)
    else:
        for f in a.frame_list:
            sc.frame_start = sc.frame_end = f
            bpy.ops.render.render(animation=True)


if __name__ == '__main__':
    main()
