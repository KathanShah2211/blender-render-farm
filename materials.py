"""Shared material library."""
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
