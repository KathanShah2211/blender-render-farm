"""Shared material library — stylized technical-cutaway look (trains set added).

Matte painted metals, warm wood, sandy ground, translucent plastic/water,
and the orange diagonal-hatch material used on every boolean cut face.
No pure black or white anywhere; roughness 0.4–0.7 for painted surfaces.
"""
import bpy


def _srgb(h):
    h = h.lstrip('#')
    c = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
    return (*lin, 1.0)


def _principled(name, color, rough=0.55, metal=0.0, **extra):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    bsdf = nt.nodes.get('Principled BSDF')
    bsdf.inputs['Base Color'].default_value = _srgb(color) if isinstance(color, str) else color
    bsdf.inputs['Roughness'].default_value = rough
    bsdf.inputs['Metallic'].default_value = metal
    for k, v in extra.items():
        if k in bsdf.inputs:
            bsdf.inputs[k].default_value = v
    m.diffuse_color = _srgb(color) if isinstance(color, str) else color  # workbench / viewport colour
    return m


def _noise_mix(m, c1, c2, scale=6.0, stretch=(1, 1, 1), detail=4.0, bump=0.0):
    nt = m.node_tree
    bsdf = nt.nodes.get('Principled BSDF')
    tc = nt.nodes.new('ShaderNodeTexCoord')
    mp = nt.nodes.new('ShaderNodeMapping'); mp.inputs['Scale'].default_value = stretch
    nz = nt.nodes.new('ShaderNodeTexNoise'); nz.inputs['Scale'].default_value = scale; nz.inputs['Detail'].default_value = detail
    ramp = nt.nodes.new('ShaderNodeValToRGB')
    ramp.color_ramp.elements[0].color = _srgb(c1); ramp.color_ramp.elements[1].color = _srgb(c2)
    nt.links.new(tc.outputs['Object'], mp.inputs['Vector'])
    nt.links.new(mp.outputs['Vector'], nz.inputs['Vector'])
    nt.links.new(nz.outputs['Fac'], ramp.inputs['Fac'])
    nt.links.new(ramp.outputs['Color'], bsdf.inputs['Base Color'])
    if bump:
        b = nt.nodes.new('ShaderNodeBump'); b.inputs['Strength'].default_value = bump
        nt.links.new(nz.outputs['Fac'], b.inputs['Height']); nt.links.new(b.outputs['Normal'], bsdf.inputs['Normal'])


def hatch(name='CutHatch', base='#E2673A', stripe='#B9502A', scale=22.0):
    """Orange cut-face material with diagonal hatch stripes (object space)."""
    m = _principled(name, base, rough=0.6)
    nt = m.node_tree
    bsdf = nt.nodes.get('Principled BSDF')
    tc = nt.nodes.new('ShaderNodeTexCoord')
    wv = nt.nodes.new('ShaderNodeTexWave')
    wv.wave_type = 'BANDS'; wv.bands_direction = 'DIAGONAL'; wv.wave_profile = 'SAW'
    wv.inputs['Scale'].default_value = scale; wv.inputs['Distortion'].default_value = 0.0
    ramp = nt.nodes.new('ShaderNodeValToRGB')
    ramp.color_ramp.interpolation = 'CONSTANT'
    ramp.color_ramp.elements[0].position = 0.0; ramp.color_ramp.elements[0].color = _srgb(base)
    ramp.color_ramp.elements[1].position = 0.72; ramp.color_ramp.elements[1].color = _srgb(stripe)
    nt.links.new(tc.outputs['Object'], wv.inputs['Vector'])
    nt.links.new(wv.outputs['Fac'], ramp.inputs['Fac'])
    nt.links.new(ramp.outputs['Color'], bsdf.inputs['Base Color'])
    return m


def pipe_water(name='PipeWater'):
    """Translucent blue water core; flow shown by a soft noise texture scrolling along object Z."""
    m = _principled(name, '#4A8FC4', rough=0.12, **{'Transmission Weight': 0.6, 'IOR': 1.33})
    nt = m.node_tree; bsdf = nt.nodes.get('Principled BSDF')
    tc = nt.nodes.new('ShaderNodeTexCoord')
    mp = nt.nodes.new('ShaderNodeMapping'); mp.name = 'Scroll'; mp.inputs['Scale'].default_value = (1.0, 1.0, 0.35)
    nz = nt.nodes.new('ShaderNodeTexNoise'); nz.inputs['Scale'].default_value = 6.0; nz.inputs['Detail'].default_value = 1.5
    ramp = nt.nodes.new('ShaderNodeValToRGB')
    ramp.color_ramp.elements[0].position = 0.35; ramp.color_ramp.elements[0].color = _srgb('#4A8FC4')
    ramp.color_ramp.elements[1].position = 0.7; ramp.color_ramp.elements[1].color = _srgb('#7DB6E2')
    nt.links.new(tc.outputs['Object'], mp.inputs['Vector']); nt.links.new(mp.outputs['Vector'], nz.inputs['Vector'])
    nt.links.new(nz.outputs['Fac'], ramp.inputs['Fac']); nt.links.new(ramp.outputs['Color'], bsdf.inputs['Base Color'])
    return m


def shadow_clear(m):
    """Let shadow rays pass through a clear material, so light reaches what is inside it without
    needing (noisy) refractive caustics."""
    nt = m.node_tree; out = nt.nodes.get('Material Output'); bsdf = nt.nodes.get('Principled BSDF')
    lp = nt.nodes.new('ShaderNodeLightPath'); tr = nt.nodes.new('ShaderNodeBsdfTransparent'); mix = nt.nodes.new('ShaderNodeMixShader')
    tr.inputs['Color'].default_value = (0.92, 0.96, 1.0, 1)
    nt.links.new(lp.outputs['Is Shadow Ray'], mix.inputs['Fac'])
    nt.links.new(bsdf.outputs['BSDF'], mix.inputs[1]); nt.links.new(tr.outputs['BSDF'], mix.inputs[2])
    nt.links.new(mix.outputs['Shader'], out.inputs['Surface'])
    return m


def wet_film(name='WetFilm'):
    """Thin shiny water film on a floor: clear coat + soft radial alpha falloff, so there is no hard edge."""
    m = _principled(name, '#B7CCDA', rough=0.03, **{'Coat Weight': 1.0, 'Coat Roughness': 0.02, 'Specular IOR Level': 0.8})
    nt = m.node_tree; bsdf = nt.nodes.get('Principled BSDF')
    tc = nt.nodes.new('ShaderNodeTexCoord')
    gr = nt.nodes.new('ShaderNodeTexGradient'); gr.gradient_type = 'SPHERICAL'
    ramp = nt.nodes.new('ShaderNodeValToRGB')
    ramp.color_ramp.elements[0].position = 0.0; ramp.color_ramp.elements[0].color = (0, 0, 0, 1)
    ramp.color_ramp.elements[1].position = 0.6; ramp.color_ramp.elements[1].color = (0.24, 0.24, 0.24, 1)
    nt.links.new(tc.outputs['Object'], gr.inputs['Vector']); nt.links.new(gr.outputs['Fac'], ramp.inputs['Fac'])
    nt.links.new(ramp.outputs['Color'], bsdf.inputs['Alpha'])
    m.diffuse_color = (0.50, 0.65, 0.76, 0.35)
    if hasattr(m, 'surface_render_method'):
        m.surface_render_method = 'BLENDED'
    return m


def emissive(name, color, strength=4.0):
    m = _principled(name, color, rough=0.5, **{'Emission Color': _srgb(color), 'Emission Strength': strength})
    return m


def xray(name='XRay', color='#7FC4E8'):
    """See-through 'X-ray' wheel: fresnel-edged translucent blue."""
    m = bpy.data.materials.new(name); m.use_nodes = True; nt = m.node_tree
    out = nt.nodes.get('Material Output'); bsdf = nt.nodes.get('Principled BSDF'); nt.nodes.remove(bsdf)
    tr = nt.nodes.new('ShaderNodeBsdfTransparent'); em = nt.nodes.new('ShaderNodeEmission')
    em.inputs['Color'].default_value = _srgb(color); em.inputs['Strength'].default_value = 2.5
    lw = nt.nodes.new('ShaderNodeLayerWeight'); lw.inputs['Blend'].default_value = 0.35
    mix = nt.nodes.new('ShaderNodeMixShader')
    nt.links.new(lw.outputs['Facing'], mix.inputs['Fac']); nt.links.new(tr.outputs['BSDF'], mix.inputs[1])
    nt.links.new(em.outputs['Emission'], mix.inputs[2]); nt.links.new(mix.outputs['Shader'], out.inputs['Surface'])
    m.diffuse_color = (*_srgb(color)[:3], 0.3)
    return m


def train_library(L):
    L['railHead'] = _principled('RailHead', '#C9CED3', rough=0.22, metal=0.9)
    L['rail'] = _principled('RailWeb', '#6B4A36', rough=0.75, metal=0.3)
    _noise_mix(L['rail'], '#5E3F2D', '#7C5840', scale=14.0, bump=0.1)
    L['sleeper'] = _principled('Sleeper', '#BDB6AC', rough=0.75)
    _noise_mix(L['sleeper'], '#B2AA9F', '#C8C1B6', scale=9.0, bump=0.08)
    L['ballast'] = _principled('Ballast', '#8C8780', rough=0.85)
    _noise_mix(L['ballast'], '#6F6A63', '#A39E96', scale=40.0, detail=2.0, bump=0.35)
    L['wheel'] = _principled('WheelSteel', '#9AA3AB', rough=0.35, metal=0.85)
    L['tread'] = _principled('Tread', '#D4D9DD', rough=0.18, metal=0.95)
    L['axle'] = _principled('Axle', '#7C858E', rough=0.4, metal=0.8)
    L['bogie'] = _principled('BogieFrame', '#2B3440', rough=0.5, metal=0.2)
    L['spring'] = _principled('Spring', '#E2673A', rough=0.45, metal=0.2)
    L['damper'] = _principled('Damper', '#F2B632', rough=0.45, metal=0.1)
    L['shell'] = _principled('CoachShell', '#E9E6E0', rough=0.35, metal=0.3)
    L['stripe'] = _principled('CoachStripe', '#1E3246', rough=0.4)
    L['stripe2'] = _principled('CoachStripe2', '#E2673A', rough=0.4)
    L['window'] = _principled('CoachWindow', '#24323F', rough=0.08, **{'Coat Weight': 0.8})
    L['roof'] = _principled('CoachRoof', '#9097A0', rough=0.5, metal=0.4)
    L['loco'] = _principled('Loco', '#C8442E', rough=0.45, metal=0.1)
    L['glowO'] = emissive('GlowOrange', '#E2673A', 6.0)
    L['glowB'] = emissive('GlowBlue', '#7FC4E8', 4.0)
    L['spark'] = emissive('Spark', '#FFB347', 40.0)
    L['xray'] = xray()
    L['machine'] = _principled('PointMachine', '#3E8FC2', rough=0.5, metal=0.1)
    L['hatchRail'] = hatch('CutHatchRail', base='#4A5868', stripe='#2B3644')
    L['dash'] = emissive('DashNavy', '#1E3246', 0.0)
    L['cream'] = _principled('Cream', '#EADFC8', rough=0.45)
    L['pantograph'] = _principled('Panto', '#3A3F45', rough=0.5, metal=0.6)
    L['buffer'] = _principled('Buffer', '#1C1F23', rough=0.6)
    L['acunit'] = _principled('ACUnit', '#B9BEC4', rough=0.5, metal=0.3)
    return L


def library():
    L = {}
    L['navy'] = _principled('PaintNavy', '#1E3246', rough=0.5, metal=0.15)
    L['steel'] = _principled('PaintSteel', '#8E99A4', rough=0.42, metal=0.55)
    L['pipe'] = _principled('PipeGrey', '#C9CFD5', rough=0.45, metal=0.3)
    L['poly'] = _principled('PolyTank', '#2B2F33', rough=0.55)          # black polyethylene (not pure black)
    L['pole'] = _principled('PoleLight', '#ECE6DA', rough=0.5)
    L['yellow'] = _principled('PaintYellow', '#F2B632', rough=0.48, metal=0.1)
    L['wall'] = _principled('Plaster', '#E9DCC8', rough=0.7)
    _noise_mix(L['wall'], '#E6D7C1', '#EFE4D3', scale=3.0, bump=0.05)
    L['slab'] = _principled('Concrete', '#CFC6BA', rough=0.68)
    L['tile'] = _principled('Tile', '#BFD6E6', rough=0.4)
    L['glass'] = _principled('WindowGlass', '#A9CBE6', rough=0.08, **{'Coat Weight': 0.7})
    L['sill'] = _principled('Sill', '#D9D2C6', rough=0.6)
    L['mist'] = _principled('Mist', '#DCEBF6', rough=0.3, **{'Alpha': 0.12})
    L['wood'] = _principled('Wood', '#A8743F', rough=0.6)
    _noise_mix(L['wood'], '#94612F', '#B98550', scale=4.0, stretch=(1, 1, 18), detail=6, bump=0.12)
    L['sand'] = _principled('Sand', '#D8B98A', rough=0.7)
    _noise_mix(L['sand'], '#CDAA78', '#E1C497', scale=1.6, bump=0.15)
    L['plastic'] = _principled('BottlePET', '#F2F6F8', rough=0.03, **{'Alpha': 0.12, 'Coat Weight': 1.0, 'Coat Roughness': 0.02, 'Specular IOR Level': 0.9})
    L['plastic'].blend_method = 'BLEND' if hasattr(L['plastic'], 'blend_method') else None
    L['water'] = _principled('Water', '#3B7FB6', rough=0.18, **{'Transmission Weight': 0.08, 'IOR': 1.33, 'Coat Weight': 0.3})
    L['bottleWater'] = _principled('BottleWater', '#1F6DB3', rough=0.12, **{'Alpha': 0.93, 'Coat Weight': 0.6, 'Emission Color': (0.10, 0.30, 0.55, 1), 'Emission Strength': 0.08})
    L['waterJet'] = _principled('WaterJet', '#6FA9D6', rough=0.15, **{'Transmission Weight': 0.35, 'IOR': 1.33,
                                                                       'Emission Color': _srgb('#4A8FC4'), 'Emission Strength': 0.15})
    L['cap'] = _principled('Cap', '#2F6E9E', rough=0.5)
    # glass-like free water for jets, drips and splashes
    L['glassWater'] = _principled('GlassWater', '#8FC3E8', rough=0.04, **{'Transmission Weight': 0.82, 'IOR': 1.33, 'Coat Weight': 0.5})
    L['pipeWater'] = pipe_water()
    L['dial'] = _principled('DialFace', '#EDE7DC', rough=0.45)
    L['needle'] = _principled('Needle', '#E2673A', rough=0.4)
    L['tick'] = _principled('Tick', '#2B3440', rough=0.5)
    L['rubber'] = _principled('Rubber', '#2A2F36', rough=0.65)
    for k in ('glassWater',):
        shadow_clear(L[k])
    L['hatch'] = hatch()
    L['wet'] = wet_film()
    L['flow'] = water_flow()
    return L


def water_flow(name='WaterFlow'):
    """Glass-like water core for pipes: translucent blue, slight emission, scrolling stripes along local Z.
    The scroll is driven by the 'FlowMap' mapping node (scene.py updates its Z location every frame)."""
    m = _principled(name, '#4A8FC4', rough=0.05, **{'Transmission Weight': 0.6, 'IOR': 1.33, 'Coat Weight': 0.5,
                                                    'Emission Color': _srgb('#7FB8E6')})
    nt = m.node_tree; bsdf = nt.nodes.get('Principled BSDF')
    tc = nt.nodes.new('ShaderNodeTexCoord')
    mp = nt.nodes.new('ShaderNodeMapping'); mp.name = 'FlowMap'
    wv = nt.nodes.new('ShaderNodeTexWave'); wv.wave_type = 'BANDS'; wv.bands_direction = 'Z'; wv.wave_profile = 'SIN'
    wv.inputs['Scale'].default_value = 1.6; wv.inputs['Distortion'].default_value = 2.0; wv.inputs['Detail'].default_value = 1.5
    mr = nt.nodes.new('ShaderNodeMapRange'); mr.inputs['To Min'].default_value = 0.08; mr.inputs['To Max'].default_value = 0.45
    nt.links.new(tc.outputs['Object'], mp.inputs['Vector']); nt.links.new(mp.outputs['Vector'], wv.inputs['Vector'])
    nt.links.new(wv.outputs['Fac'], mr.inputs['Value']); nt.links.new(mr.outputs['Result'], bsdf.inputs['Emission Strength'])
    return m


# ---------------------------------------------------------------- Chenab set
def _value(nt, name, v=0.0):
    n = nt.nodes.new('ShaderNodeValue'); n.name = name; n.outputs[0].default_value = v
    return n


def rock(name='Rock', gx=275.0, gz=225.0):
    """Gorge rock: two-tone noise + bump; orange 'carrying' glow masked to the two abutment zones.
    Node 'Glow' (value 0..1) is set per frame by scene.py."""
    m = _principled(name, '#8F7E68', rough=0.85)
    _noise_mix(m, '#7A6A57', '#A3927A', scale=0.02, detail=6.0, bump=0.25)
    nt = m.node_tree; bsdf = nt.nodes.get('Principled BSDF')
    tc = nt.nodes.new('ShaderNodeTexCoord'); sep = nt.nodes.new('ShaderNodeSeparateXYZ')
    nt.links.new(tc.outputs['Object'], sep.inputs[0])
    ax = nt.nodes.new('ShaderNodeMath'); ax.operation = 'ABSOLUTE'; nt.links.new(sep.outputs['X'], ax.inputs[0])
    dx = nt.nodes.new('ShaderNodeMath'); dx.operation = 'SUBTRACT'; dx.inputs[1].default_value = gx
    nt.links.new(ax.outputs[0], dx.inputs[0])
    dz = nt.nodes.new('ShaderNodeMath'); dz.operation = 'SUBTRACT'; dz.inputs[1].default_value = gz
    nt.links.new(sep.outputs['Z'], dz.inputs[0])
    cb = nt.nodes.new('ShaderNodeCombineXYZ')
    nt.links.new(dx.outputs[0], cb.inputs[0]); nt.links.new(sep.outputs['Y'], cb.inputs[1]); nt.links.new(dz.outputs[0], cb.inputs[2])
    ln = nt.nodes.new('ShaderNodeVectorMath'); ln.operation = 'LENGTH'; nt.links.new(cb.outputs[0], ln.inputs[0])
    mr = nt.nodes.new('ShaderNodeMapRange'); mr.inputs['From Min'].default_value = 40.0; mr.inputs['From Max'].default_value = 190.0
    mr.inputs['To Min'].default_value = 1.0; mr.inputs['To Max'].default_value = 0.0
    nt.links.new(ln.outputs['Value'], mr.inputs['Value'])
    g = _value(nt, 'Glow', 0.0)
    mul = nt.nodes.new('ShaderNodeMath'); mul.operation = 'MULTIPLY'
    nt.links.new(mr.outputs['Result'], mul.inputs[0]); nt.links.new(g.outputs[0], mul.inputs[1])
    mul2 = nt.nodes.new('ShaderNodeMath'); mul2.operation = 'MULTIPLY'; mul2.inputs[1].default_value = 0.55
    nt.links.new(mul.outputs[0], mul2.inputs[0])
    bsdf.inputs['Emission Color'].default_value = _srgb('#E2673A')
    nt.links.new(mul2.outputs[0], bsdf.inputs['Emission Strength'])
    return m


def river(name='River'):
    """River: blue with flow stripes along Y; mapping node 'FlowMap' location.y is scrolled per frame."""
    m = _principled(name, '#3E8FC2', rough=0.12, **{'Coat Weight': 0.4})
    nt = m.node_tree; bsdf = nt.nodes.get('Principled BSDF')
    tc = nt.nodes.new('ShaderNodeTexCoord'); mp = nt.nodes.new('ShaderNodeMapping'); mp.name = 'FlowMap'
    mp.inputs['Scale'].default_value = (0.08, 0.02, 0.08)
    nz = nt.nodes.new('ShaderNodeTexNoise'); nz.inputs['Scale'].default_value = 3.0; nz.inputs['Detail'].default_value = 3.0
    ramp = nt.nodes.new('ShaderNodeValToRGB')
    ramp.color_ramp.elements[0].position = 0.45; ramp.color_ramp.elements[0].color = _srgb('#2F7CB0')
    ramp.color_ramp.elements[1].position = 0.62; ramp.color_ramp.elements[1].color = _srgb('#9CCDEB')
    nt.links.new(tc.outputs['Object'], mp.inputs['Vector']); nt.links.new(mp.outputs['Vector'], nz.inputs['Vector'])
    nt.links.new(nz.outputs['Fac'], ramp.inputs['Fac']); nt.links.new(ramp.outputs['Color'], bsdf.inputs['Base Color'])
    return m


def fade_mix(m, name='Fade'):
    """Wrap a material's surface in Mix(transparent, surface) with node value `name` (1 = fully shown)."""
    nt = m.node_tree; out = nt.nodes.get('Material Output')
    src = out.inputs['Surface'].links[0].from_socket
    tr = nt.nodes.new('ShaderNodeBsdfTransparent'); mix = nt.nodes.new('ShaderNodeMixShader')
    v = _value(nt, name, 1.0)
    nt.links.new(v.outputs[0], mix.inputs['Fac']); nt.links.new(tr.outputs['BSDF'], mix.inputs[1])
    nt.links.new(src, mix.inputs[2]); nt.links.new(mix.outputs['Shader'], out.inputs['Surface'])
    return m


def flat(name, color, strength=1.0):
    """Flat unlit colour (silhouettes): pure emission, so lighting never models the shape."""
    m = bpy.data.materials.new(name); m.use_nodes = True; nt = m.node_tree
    out = nt.nodes.get('Material Output'); nt.nodes.remove(nt.nodes.get('Principled BSDF'))
    em = nt.nodes.new('ShaderNodeEmission'); em.inputs['Color'].default_value = _srgb(color); em.inputs['Strength'].default_value = strength
    nt.links.new(em.outputs['Emission'], out.inputs['Surface'])
    m.diffuse_color = _srgb(color)
    return fade_mix(m)


def streak(name='WindStreak', color='#9CD3F2', axis='Y', period=0.025):
    """Moving wind streaks: emission bands along `axis` (object space), gaps transparent.
    Mapping node 'FlowMap' location is scrolled per frame; node 'Fade' scales opacity."""
    m = bpy.data.materials.new(name); m.use_nodes = True; nt = m.node_tree
    out = nt.nodes.get('Material Output'); nt.nodes.remove(nt.nodes.get('Principled BSDF'))
    tc = nt.nodes.new('ShaderNodeTexCoord'); mp = nt.nodes.new('ShaderNodeMapping'); mp.name = 'FlowMap'
    sc = [1.0, 1.0, 1.0]; sc['XYZ'.index(axis)] = period; mp.inputs['Scale'].default_value = sc
    wv = nt.nodes.new('ShaderNodeTexWave'); wv.wave_type = 'BANDS'; wv.bands_direction = axis; wv.wave_profile = 'SAW'
    wv.inputs['Scale'].default_value = 1.0; wv.inputs['Distortion'].default_value = 0.0
    ramp = nt.nodes.new('ShaderNodeValToRGB'); ramp.color_ramp.elements[0].position = 0.55; ramp.color_ramp.elements[1].position = 0.95
    em = nt.nodes.new('ShaderNodeEmission'); em.inputs['Color'].default_value = _srgb(color); em.inputs['Strength'].default_value = 1.8
    tr = nt.nodes.new('ShaderNodeBsdfTransparent'); mix = nt.nodes.new('ShaderNodeMixShader')
    fade = _value(nt, 'Fade', 1.0)
    mul = nt.nodes.new('ShaderNodeMath'); mul.operation = 'MULTIPLY'
    nt.links.new(tc.outputs['Object'], mp.inputs['Vector']); nt.links.new(mp.outputs['Vector'], wv.inputs['Vector'])
    nt.links.new(wv.outputs['Fac'], ramp.inputs['Fac']); nt.links.new(ramp.outputs['Color'], mul.inputs[0])
    nt.links.new(fade.outputs[0], mul.inputs[1]); nt.links.new(mul.outputs[0], mix.inputs['Fac'])
    nt.links.new(tr.outputs['BSDF'], mix.inputs[1]); nt.links.new(em.outputs['Emission'], mix.inputs[2])
    nt.links.new(mix.outputs['Shader'], out.inputs['Surface'])
    m.diffuse_color = (*_srgb(color)[:3], 0.6)
    return m


def chenab_library(L, glow=(275.0, 225.0)):
    L['rock'] = rock(gx=glow[0], gz=glow[1])
    L['hatchRock'] = hatch('CutHatchRock', scale=0.045)
    L['river'] = river()
    L['archSteel'] = _principled('ArchSteel', '#C9CFD5', rough=0.4, metal=0.35)
    L['pierSteel'] = _principled('PierSteel', '#AEB6BE', rough=0.45, metal=0.35)
    L['deck'] = _principled('DeckGirder', '#8C96A1', rough=0.5, metal=0.25)
    L['deckTop'] = _principled('DeckTop', '#BDB6AC', rough=0.75)
    L['concrete'] = _principled('PierConcrete', '#D4CCC0', rough=0.7)
    _noise_mix(L['concrete'], '#C9C0B3', '#DDD6CB', scale=0.4, bump=0.05)
    L['eiffel'] = flat('EiffelFlat', '#1D3344', 1.0)
    L['ghost'] = fade_mix(xray('GhostPillar', '#E9F4FB'))
    L['arrow'] = emissive('ArrowOrange', '#E2673A', 1.4)
    L['arrowDash'] = streak('ArrowDash', '#E2673A', axis='Z', period=0.09)
    L['wind'] = streak('WindStreak', '#BFE4F7', axis='Y', period=0.02)
    L['shockRing'] = fade_mix(emissive('ShockRing', '#F4FBFF', 3.0))
    L['dust'] = fade_mix(_principled('Dust', '#D9C6AF', rough=0.95))
    L['cloud'] = _principled('Cloud', '#F7F3EC', rough=0.9, **{'Subsurface Weight': 0.15})
    L['sunDisc'] = emissive('SunDisc', '#FFE2A8', 25.0)
    return L
