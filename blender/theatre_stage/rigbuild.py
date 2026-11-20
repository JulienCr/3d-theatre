"""Lighting rig to Blender objects: fixture hierarchies, lights, blades, drivers, Cycles nodes (spec 14).

Nothing is computed here: `core.rig.Rig` gives the geometry and the DMX channels, the fiche the
optics. Per-fixture settings live on the root empty, so no driver reads the object that owns it.
"""

from __future__ import annotations

import math
import traceback
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path

import bpy

from . import materials
from .core.fixture_models import fixture_model
from .core.fixtures import IES_FAC_PER_CD, Fixture, Strobe, cct_to_rgb, ies_axis_candela, max_energy
from .core.meshes import Mesh
from .core.rig import FIXTURES_COLLECTION, Rig, RigFixture, default_library

TAG = materials.TAG
MAX_CHANNEL = 512
MAX_EXPRESSION = 255
WORLD_HAZE = "DMX_Haze"
LENS_ADVANCE = 0.005
LENS_SEGMENTS = 32
LENS_GAIN = 8.0
SPOT_BLEND = 0.02
EMPTY_SIZE = 0.03
CTO_KEYS = ("cto_r", "cto_g", "cto_b")

warnings: list[str] = []
_models: dict = {}


def clear_cache() -> None:
    """Forget the memoised fixture models (call after the fixture library is reloaded)."""
    _models.clear()


# ------------------------------------------------------------------ context

@dataclass
class _Build:
    """Shared services of one build, plus the fixture being built (`for_fixture`)."""

    scene: bpy.types.Scene
    collection: bpy.types.Collection
    new_mesh: Callable
    material: Callable
    library: object
    f: RigFixture | None = None
    fx: Fixture | None = None
    root: bpy.types.Object | None = None
    tube: object = None
    tail: str = ""
    channels: dict = field(default_factory=dict)

    def for_fixture(self, f: RigFixture, fx: Fixture, root, tube) -> _Build:
        return replace(self, f=f, fx=fx, root=root, tube=tube, tail=f"_{tube.name}" if tube else "",
                       channels={cv.attribute: cv for cv in f.channels})

    def expr(self) -> _Expr:
        return _Expr(self)


class _Expr:
    """One driver expression with its variables: scene DMX bytes `d_*`, root settings `k_*`."""

    def __init__(self, ctx: _Build):
        self.ctx = ctx
        self.variables: dict[str, tuple] = {}

    def has(self, attribute: str) -> bool:
        cv = self.ctx.channels.get(attribute)
        return cv is not None and cv.channel <= MAX_CHANNEL

    def dmx(self, attribute: str) -> str:
        """Normalized value of a channel (spec 12.4)."""
        cv, universe = self.ctx.channels[attribute], self.ctx.f.universe
        coarse = self.scene_var(f"d_{attribute}", f'["dmx_{universe}_{cv.channel}"]')
        if cv.bits == 8 or cv.fine_channel is None:
            return coarse
        fine = self.scene_var(f"d_{attribute}_f", f'["dmx_{universe}_{cv.fine_channel}"]')
        return f"((256*{coarse}+{fine})/257)"

    def cfg(self, key: str) -> str:
        self.variables[f"k_{key}"] = ("OBJECT", self.ctx.root, f'["{key}"]')
        return f"k_{key}"

    def scene_var(self, name: str, path: str) -> str:
        self.variables[name] = ("SCENE", self.ctx.scene, path)
        return name

    def drive(self, owner, path: str, expression: str, index: int = -1):
        if len(expression) > MAX_EXPRESSION:
            raise ValueError(f"Driver expression of {len(expression)} characters: {expression[:60]}...")
        curve = owner.driver_add(path) if index < 0 else owner.driver_add(path, index)
        driver = curve.driver
        driver.type = "SCRIPTED"
        for name, (id_type, target, data_path) in self.variables.items():
            var = driver.variables.new()
            var.name = name
            var.type = "SINGLE_PROP"
            var.targets[0].id_type = id_type
            var.targets[0].id = target
            var.targets[0].data_path = data_path
        driver.expression = expression
        self.variables = {}
        return curve


def _shutter(ex: _Expr, strobe: Strobe) -> str:
    """1 open, 0 closed, a square wave while strobing; bytes outside the sheet's ranges stay open (spec 14.7)."""
    byte, ramp = f"round(255*{ex.dmx('strobe')})", strobe.strobe
    fps = ex.scene_var("fps", "render.fps")
    slope = (ramp.hz_max - ramp.hz_min) / max(ramp.stop - ramp.start, 1)
    flash = f"(fmod(frame/{fps}*({ramp.hz_min}+({byte}-{ramp.start})*{slope}),1)<0.5)"
    closed = f"({byte}>={strobe.closed[0]} and {byte}<={strobe.closed[1]})"
    return f"(0 if {closed} else ({flash} if ({byte}>={ramp.start} and {byte}<={ramp.stop}) else 1))"


def _level(ex: _Expr) -> str | None:
    """Dimmer times shutter, or None when the mode has neither."""
    terms = []
    if ex.has("dimmer"):
        terms.append(ex.dmx("dimmer"))
    if ex.ctx.fx.strobe is not None and ex.has("strobe"):
        terms.append(_shutter(ex, ex.ctx.fx.strobe))
    return "*".join(terms) or None


def _colour_expr(ex: _Expr, i: int) -> str | None:
    """Component `i` of the RGB colour of the mode (spec 14.7); None when it stays white."""
    colour, has = ex.ctx.fx.colour, ex.has
    base = None
    rgb = ("color_r", "color_g", "color_b")
    if any(has(a) for a in rgb):
        white = [ex.dmx("color_w")] if has("color_w") else []
        mix = ["+".join(([ex.dmx(a)] if has(a) else []) + white) or "0" for a in rgb]
        base = mix[i]
        if has("cct") and not any(ex.ctx.fx.channel(a, ex.ctx.f.mode).default for a in rgb if has(a)):
            base = f"(1+{mix[i]})/(1+max({mix[0]},max({mix[1]},{mix[2]})))"
    elif any(has(a) for a in ("cyan", "magenta", "yellow")):
        attribute = ("cyan", "magenta", "yellow")[i]
        base = f"1-{ex.dmx(attribute)}" if has(attribute) else "1"
    elif any(has(e.attribute) for e in colour.emitters):
        terms = [f"{ex.dmx(e.attribute)}*{e.rgb[i]}" for e in colour.emitters if has(e.attribute) and e.rgb[i]]
        base = "+".join(terms) or "0"
    if has("cto") and colour.cto_kelvin:
        cto = ex.dmx("cto")
        base = f"({base or '1'})*(1-{cto}+{cto}*{ex.cfg(CTO_KEYS[i])})"
    return None if base is None else f"min(1,{base})"


def _ranged(ex: _Expr, attribute: str, key: str, invert: str) -> str:
    """`min + v*(max - min)` of a root range, `v` mirrored when `invert` is set (spec 14.7)."""
    low, high = ex.cfg(f"{key}_min"), ex.cfg(f"{key}_max")
    return f"{low}+abs({ex.cfg(invert)}-{ex.dmx(attribute)})*({high}-{low})"


def _zoom_fraction(ex: _Expr, inverted: bool) -> str:
    zoom = ex.dmx("zoom")
    return f"(1-{zoom})" if inverted else zoom


def _drive_root(ctx: _Build) -> None:
    """Values several drivers share, driven on the root from the scene alone: level, field, beam."""
    ex = ctx.expr()
    if (level := _level(ex)):
        ex.drive(ctx.root, '["level"]', level)
    if not (ctx.expr().has("zoom") and ctx.fx.optics.field_angle is not None):
        return
    for key in ("field", "beam"):
        ex = ctx.expr()
        low, high = ctx.root[f"{key}_min"], ctx.root[f"{key}_max"]
        ex.drive(ctx.root, f'["{key}_now"]', f"{low}+{_zoom_fraction(ex, ctx.fx.optics.zoom_invert)}*{high - low}")


def _drive_kelvin(ex: _Expr, owner, path: str) -> None:
    """Colour temperature of the `cct` channel: its DMX curve (spec 12.3) or the linear range."""
    channel = ex.ctx.fx.channel("cct", ex.ctx.f.mode)
    if channel is None or not channel.curve:
        low, high = ex.cfg("cct_min"), ex.cfg("cct_max")
        ex.drive(owner, path, f"{low}+{ex.dmx('cct')}*({high}-{low})")
        return
    curve = ex.drive(owner, path, ex.dmx("cct"))
    for modifier in list(curve.modifiers):
        curve.modifiers.remove(modifier)
    for x, y in channel.curve:
        curve.keyframe_points.insert(x, y).interpolation = "CONSTANT" if channel.curve_mode == "step" else "LINEAR"
    curve.extrapolation = "CONSTANT"


# ------------------------------------------------------------------ datablocks

def _mesh(ctx: _Build, name: str, data: Mesh, material: str):
    """Mesh datablock by name, created once and kept by a fake user across rebuilds (spec 14.1)."""
    mesh = bpy.data.meshes.get(name)
    if mesh is None:
        mesh = ctx.new_mesh(name, data)
        mesh.use_fake_user = True
    if not mesh.materials:
        mesh.materials.append(ctx.material(material))
    return mesh


def _disc(radius: float, z: float) -> Mesh:
    ring = [(radius * math.cos(2 * math.pi * k / LENS_SEGMENTS),
             radius * math.sin(2 * math.pi * k / LENS_SEGMENTS), z) for k in range(LENS_SEGMENTS)]
    faces = tuple((0, 1 + k, 1 + (k + 1) % LENS_SEGMENTS) for k in range(LENS_SEGMENTS))
    return Mesh(((0.0, 0.0, z), *ring), faces)


def _blade_plane(diameter: float, half_width: float) -> Mesh:
    return Mesh(((0.0, -half_width, 0.0), (2 * diameter, -half_width, 0.0),
                 (2 * diameter, half_width, 0.0), (0.0, half_width, 0.0)), ((0, 1, 2, 3),))


def _object(ctx: _Build, name: str, data=None, parent=None, location=(0.0, 0.0, 0.0),
            rotation=(0.0, 0.0, 0.0), category: str | None = None):
    obj = bpy.data.objects.new(name, data)
    obj[TAG] = True
    if category:
        obj[materials.CATEGORY] = category
    if data is None:
        obj.empty_display_type = "PLAIN_AXES"
        obj.empty_display_size = EMPTY_SIZE
    obj.parent = parent
    obj.location = location
    obj.rotation_euler = rotation
    ctx.collection.objects.link(obj)
    return obj


def _body_part(ctx: _Build, suffix: str, part: Mesh, data_name: str, parent, location=(0.0, 0.0, 0.0)):
    """A body part: a mesh object, or an empty when the fiche has no such mesh."""
    data = _mesh(ctx, data_name, part, "TS_Fixture") if part.vertices else None
    obj = _object(ctx, f"{ctx.f.name}_{suffix}", data, parent, location, category="TS_Fixture" if data else None)
    obj.visible_shadow = False
    return obj


def _image(fx: Fixture, relative: str):
    name = f"TSG_{fx.id}_{Path(relative).stem}"
    image = bpy.data.images.get(name)
    if image is None:
        image = bpy.data.images.load(str(fx.path(relative)))
        image.name = name
        image.use_fake_user = True
        image.colorspace_settings.name = "Non-Color"
    return image


def _ies_text(fx: Fixture, relative: str):
    name = f"TSF_{fx.id}_{Path(relative).stem}.ies"
    text = bpy.data.texts.get(name)
    if text is None:
        text = bpy.data.texts.new(name)
        text.write(fx.path(relative).read_text(encoding="utf-8", errors="replace"))
        text.use_fake_user = True
    return text


# ------------------------------------------------------------------ materials

def setup_lens_material(mat: bpy.types.Material, scene=None) -> None:
    """Dark glass whose emission reads the lens object's `lens_*` properties (one material, per-lens look)."""
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    bsdf = nodes["Principled BSDF"]

    def attribute(name: str):
        return _node(mat.node_tree, "ShaderNodeAttribute", attribute_type="OBJECT", attribute_name=f'["{name}"]')

    rgb, level, kelvin = attribute("lens_rgb"), attribute("lens_level"), attribute("lens_kelvin")
    warm = _node(mat.node_tree, "ShaderNodeBlackbody")
    links.new(kelvin.outputs["Fac"], warm.inputs["Temperature"])
    use = _math(mat.node_tree, "GREATER_THAN", kelvin.outputs["Fac"], 0.0)
    mix = _node(mat.node_tree, "ShaderNodeMix", data_type="RGBA", blend_type="MULTIPLY")
    links.new(use.outputs[0], mix.inputs[0])
    links.new(rgb.outputs["Color"], mix.inputs[6])
    links.new(warm.outputs["Color"], mix.inputs[7])
    pick = _node(mat.node_tree, "ShaderNodeMix", data_type="RGBA")
    links.new(use.outputs[0], pick.inputs[0])
    links.new(rgb.outputs["Color"], pick.inputs[6])
    links.new(mix.outputs[2], pick.inputs[7])
    strength = _math(mat.node_tree, "MULTIPLY", level.outputs["Fac"], LENS_GAIN)
    links.new(pick.outputs[2], bsdf.inputs["Emission Color"])
    links.new(strength.outputs[0], bsdf.inputs["Emission Strength"])


# ------------------------------------------------------------------ settings

def _settings(f: RigFixture, fx: Fixture, tube) -> dict:
    """Configuration properties of the root (spec 14.2)."""
    optics, colour, sheet = fx.optics, fx.colour, fx.blades
    field_range = (tube.field_angle,) * 2 if tube else (optics.field_angle.min, optics.field_angle.max)
    if tube:
        beam_range = (tube.beam_angle,) * 2
    else:
        beam_range = (optics.beam_angle.min, optics.beam_angle.max) if optics.beam_angle else field_range
    pan, tilt = (fx.motion.pan, fx.motion.tilt) if f.moving else (None, None)
    rot = sheet.rotation if sheet else None
    cct = colour.cct_range
    cto = cct_to_rgb(colour.cto_kelvin) if colour.cto_kelvin else (1.0, 1.0, 1.0)
    return {
        "theatre_fixture": f.fixture_id, "theatre_family": f.family, "theatre_circuit": f.circuit or "",
        "theatre_mode": f.mode, "theatre_universe": f.universe, "theatre_address": f.address,
        "max_energy": max_energy(optics.beam_type, optics.flux, f.field_angle),
        "field_min": field_range[0], "field_max": field_range[1], "beam_min": beam_range[0],
        "beam_max": beam_range[1], "field_angle": f.field_angle, "zoom_invert": float(optics.zoom_invert),
        "pan_min": pan.min if pan else 0.0, "pan_max": pan.max if pan else 0.0,
        "tilt_min": tilt.min if tilt else 0.0, "tilt_max": tilt.max if tilt else 0.0,
        "pan_invert": float(bool(pan and pan.invert)), "tilt_invert": float(bool(tilt and tilt.invert)),
        "cct_min": cct.min if cct else 0.0, "cct_max": cct.max if cct else 0.0,
        "cto_r": cto[0], "cto_g": cto[1], "cto_b": cto[2],
        "blade_open": f.blades.open_eff if f.blades else 0.0,
        "blade_closed": sheet.travel.closed if sheet else 0.0,
        "blade_half_span": f.blades.half_span if f.blades else 0.0,
        "blade_angle_limit": sheet.angle_limit if sheet else 0.0,
        "blade_rot_min": rot.min if rot else 0.0, "blade_rot_max": rot.max if rot else 0.0,
        "blade_rot_invert": float(bool(rot and rot.invert)),
        "iris_min_ratio": fx.iris.min_ratio if fx.iris else 1.0,
        "level": 1.0, "field_now": f.field_angle,
        "beam_now": f.beam_angle if f.beam_angle is not None else f.field_angle,
    }


# ------------------------------------------------------------------ lens, light, pose

def _drive_pose(ctx: _Build, pan, tilt) -> None:
    ex = ctx.expr()
    if ex.has("pan"):
        ex.drive(pan, "rotation_euler", f"radians({_ranged(ex, 'pan', 'pan', 'pan_invert')})", 2)
    ex = ctx.expr()
    if ex.has("tilt"):
        ex.drive(tilt, "rotation_euler", f"-radians({_ranged(ex, 'tilt', 'tilt', 'tilt_invert')})", 0)


def _make_lens(ctx: _Build, tilt, radius: float, lens_offset: float):
    fx, f = ctx.fx, ctx.f
    mesh = _mesh(ctx, f"TSF_{fx.id}_lens{ctx.tail}", _disc(radius, lens_offset + LENS_ADVANCE), "TS_Lens")
    lens = _object(ctx, f"{f.name}_Lens", mesh, tilt, category="TS_Lens")
    lens.visible_shadow = False
    lens["lens_level"], lens["lens_rgb"], lens["lens_kelvin"] = 1.0, (1.0, 1.0, 1.0), 0.0
    return lens


def _drive_lens(ctx: _Build, lens) -> None:
    ex = ctx.expr()
    if ex.has("dimmer") or ex.has("strobe"):
        ex.drive(lens, '["lens_level"]', ex.cfg("level"))
    for i in range(3):
        ex = ctx.expr()
        if (expression := _colour_expr(ex, i)):
            ex.drive(lens, '["lens_rgb"]', expression, i)
    ex = ctx.expr()
    if ex.has("cct") and ctx.fx.colour.cct_range:
        _drive_kelvin(ex, lens, '["lens_kelvin"]')


def _make_light(ctx: _Build, tilt):
    f, optics = ctx.f, ctx.fx.optics
    data = bpy.data.lights.new(f"{f.name}_Light", f.source_kind)
    data.use_shadow = True
    data.energy = max_energy(optics.beam_type, optics.flux, f.field_angle)
    if f.source_kind == "SPOT":
        data.shadow_soft_size = 0.0
        data.spot_blend = SPOT_BLEND
        data.spot_size = math.radians(f.field_angle)
    else:
        data.shape = "DISK"
        data.size = f.aperture
        data.spread = math.radians(f.beam_angle if f.beam_angle is not None else f.field_angle)
    return _object(ctx, f"{f.name}_Light", data, tilt, (0.0, 0.0, f.source_z), (math.pi, 0.0, 0.0))


def _drive_light(ctx: _Build, light) -> None:
    data, spot = light.data, ctx.f.source_kind == "SPOT"
    ex = ctx.expr()
    zoomed = ex.has("zoom") and ctx.fx.optics.field_angle is not None
    leveled = ex.has("dimmer") or ex.has("strobe")
    if leveled or (zoomed and spot):
        parts = [ex.cfg("max_energy")] + ([ex.cfg("level")] if leveled else [])
        if zoomed and spot:
            parts.append(f"(1-cos(radians({ex.cfg('field_angle')})/2))/(1-cos(radians({ex.cfg('field_now')})/2))")
        ex.drive(data, "energy", "*".join(parts))
    for i in range(3):
        ex = ctx.expr()
        if (expression := _colour_expr(ex, i)):
            ex.drive(data, "color", expression, i)
    if zoomed:
        ex = ctx.expr()
        ex.drive(data, "spot_size" if spot else "spread", f"radians({ex.cfg('field_now' if spot else 'beam_now')})")


# ------------------------------------------------------------------ blades

def _make_blades(ctx: _Build, tilt) -> None:
    f, fx = ctx.f, ctx.fx
    sheet, blades, radius = fx.blades, f.blades, f.aperture / 2
    mesh = _mesh(ctx, f"TSF_{fx.id}_blade{ctx.tail}",
                 _blade_plane(f.aperture, max(sheet.span / 2, 1.5 * radius)), "TS_Blade")
    holder = _object(ctx, f"{f.name}_Blades", None, tilt, (0.0, 0.0, blades.plane_z),
                     (0.0, 0.0, math.radians(blades.rotation)))
    motorised = sheet.mode == "motorised"
    ex = ctx.expr()
    if motorised and sheet.rotation is not None and ex.has("blade_rot"):
        ex.drive(holder, "rotation_euler",
                 f"radians({_ranged(ex, 'blade_rot', 'blade_rot', 'blade_rot_invert')})", 2)
    for blade in blades.blades:
        pivot = _object(ctx, f"{f.name}_Blade_{blade.index}_Pivot", None, holder,
                        rotation=(0.0, 0.0, math.radians(blade.side)))
        plane = _object(ctx, f"{f.name}_Blade_{blade.index}", mesh, pivot, (blade.edge, 0.0, 0.0),
                        (0.0, 0.0, math.radians(blade.angle)), category="TS_Blade")
        plane.visible_camera = False
        if motorised:
            _drive_blade(ctx, plane, blade.index)


def _drive_blade(ctx: _Build, plane, k: int) -> None:
    a, b, swivel = f"blade_{k}a", f"blade_{k}b", f"blade_{k}_rot"

    def edge(ex: _Expr, attribute: str) -> str:
        return f"({ex.cfg('blade_open')}+{ex.dmx(attribute)}*({ex.cfg('blade_closed')}-{ex.cfg('blade_open')}))"

    ex = ctx.expr()
    if ex.has(a):
        ex.drive(plane, "location", f"({edge(ex, a)}+{edge(ex, b)})/2" if ex.has(b) else edge(ex, a), 0)
    ex = ctx.expr()
    if ex.has(swivel):
        ex.drive(plane, "rotation_euler", f"radians({ex.cfg('blade_angle_limit')}*(1-2*{ex.dmx(swivel)}))", 2)
    elif ex.has(a) and ex.has(b):
        ex.drive(plane, "rotation_euler",
                 f"atan(({edge(ex, a)}-{edge(ex, b)})/(2*{ex.cfg('blade_half_span')}))", 2)


# ------------------------------------------------------------------ Cycles nodes

def _node(tree, kind: str, name: str | None = None, **settings):
    node = tree.nodes.new(kind)
    if name:
        node.name = name
    for key, value in settings.items():
        setattr(node, key, value)
    return node


def _vector_math(tree, operation: str, *inputs):
    """A Vector Math node; each input is a socket to link or a constant to store."""
    node = _node(tree, "ShaderNodeVectorMath", operation=operation)
    for slot, value in zip((0, 3) if operation == "SCALE" else (0, 1, 2), inputs):
        if hasattr(value, "node"):
            tree.links.new(value, node.inputs[slot])
        else:
            node.inputs[slot].default_value = value
    return node


def _math(tree, operation: str, *inputs):
    node = _node(tree, "ShaderNodeMath", operation=operation)
    for slot, value in enumerate(inputs):
        if hasattr(value, "node"):
            tree.links.new(value, node.inputs[slot])
        else:
            node.inputs[slot].default_value = value
    return node


def _projection(tree):
    """Light-frame direction mapped to the unit disc of the field: `p = n_xy / (-n_z) / tan(F/2)`."""
    split = _node(tree, "ShaderNodeSeparateXYZ")
    tree.links.new(_node(tree, "ShaderNodeTexCoord").outputs["Normal"], split.inputs[0])
    tangent = _node(tree, "ShaderNodeValue", "FieldTan")
    depth = _math(tree, "MULTIPLY", _math(tree, "MULTIPLY", split.outputs["Z"], -1.0).outputs[0],
                  tangent.outputs[0])
    combine = _node(tree, "ShaderNodeCombineXYZ")
    for axis in ("X", "Y"):
        tree.links.new(_math(tree, "DIVIDE", split.outputs[axis], depth.outputs[0]).outputs[0],
                       combine.inputs[axis])
    return combine.outputs[0]


def _wheel_group(fx: Fixture, wheel):
    """Node group of a gobo wheel (inputs `Vector`, `Angle`, `Byte`, output `Color`), built once by name."""
    name = f"TSN_{fx.id}_{wheel.name}"
    group = bpy.data.node_groups.get(name)
    if group is not None:
        return group
    group = bpy.data.node_groups.new(name, "ShaderNodeTree")
    group.use_fake_user = True
    for label, kind, direction in (("Vector", "Vector", "INPUT"), ("Angle", "Float", "INPUT"),
                                   ("Byte", "Float", "INPUT"), ("Color", "Color", "OUTPUT")):
        group.interface.new_socket(label, in_out=direction, socket_type=f"NodeSocket{kind}")
    inputs, output = _node(group, "NodeGroupInput"), _node(group, "NodeGroupOutput")
    spin = _node(group, "ShaderNodeVectorRotate", rotation_type="Z_AXIS")
    group.links.new(inputs.outputs["Vector"], spin.inputs["Vector"])
    group.links.new(inputs.outputs["Angle"], spin.inputs["Angle"])
    unit = _vector_math(group, "MULTIPLY_ADD", spin.outputs[0], (0.5, 0.5, 0.5), (0.5, 0.5, 0.5))
    byte = _math(group, "MINIMUM", inputs.outputs["Byte"], float(wheel.slots[-1].dmx[1]))
    total = None
    for slot in wheel.slots:
        low, high = slot.dmx
        pick = _math(group, "COMPARE", byte.outputs[0], (low + high) / 2, (high - low) / 2 + 0.01)
        if slot.image:
            texture = _node(group, "ShaderNodeTexImage", image=_image(fx, slot.image),
                            extension="CLIP", interpolation="Linear")
            group.links.new(unit.outputs[0], texture.inputs["Vector"])
            term = _vector_math(group, "SCALE", texture.outputs["Color"], pick.outputs[0])
        else:
            term = _vector_math(group, "SCALE", (1.0, 1.0, 1.0), pick.outputs[0])
        total = term if total is None else _vector_math(group, "ADD", total.outputs[0], term.outputs[0])
    group.links.new(total.outputs[0], output.inputs["Color"])
    return group


def _build_tree(ctx: _Build, light) -> None:
    """Cycles node tree of the light: IES, colour temperature, gobo wheels, iris (spec 14.5)."""
    f, fx = ctx.f, ctx.fx
    probe = ctx.expr()
    ies = fx.ies_for(f.field_angle, ctx.tube)
    wheels = [w for w in fx.gobos if probe.has(w.name) and any(s.image for s in w.slots)]
    iris = fx.iris is not None and probe.has("iris")
    cct = probe.has("cct") and fx.colour.cct_range is not None
    if not (ies or wheels or iris or cct):
        return
    tree = light.data.node_tree
    emission = next(n for n in tree.nodes if n.bl_idname == "ShaderNodeEmission")
    colour = None
    if ies:
        text = _ies_text(fx, ies)
        texture = _node(tree, "ShaderNodeTexIES", mode="INTERNAL", ies=text)
        unit = _math(tree, "MULTIPLY", texture.outputs["Fac"], 1 / (ies_axis_candela(text.as_string()) * IES_FAC_PER_CD))
        tree.links.new(unit.outputs[0], emission.inputs["Strength"])
    if cct:
        colour = _node(tree, "ShaderNodeBlackbody", "Blackbody").outputs["Color"]
        _drive_kelvin(ctx.expr(), tree, 'nodes["Blackbody"].inputs[0].default_value')
    if wheels or iris:
        plane = _projection(tree)
        _drive_field(ctx, tree)
    for wheel in wheels:
        node = _node(tree, "ShaderNodeGroup", wheel.name, node_tree=_wheel_group(fx, wheel))
        tree.links.new(plane, node.inputs["Vector"])
        found = node.outputs["Color"]
        colour = found if colour is None else _vector_math(tree, "MULTIPLY", colour, found).outputs[0]
        ex = ctx.expr()
        ex.drive(tree, f'nodes["{wheel.name}"].inputs["Byte"].default_value', f"round(255*{ex.dmx(wheel.name)})")
        ex = ctx.expr()
        if ex.has(f"{wheel.name}_rot"):
            ex.drive(tree, f'nodes["{wheel.name}"].inputs["Angle"].default_value',
                     f"radians({ex.dmx(f'{wheel.name}_rot')}*{wheel.rotation_range})")
    if iris:
        radius = _node(tree, "ShaderNodeValue", "IrisRadius")
        inside = _math(tree, "LESS_THAN", _vector_math(tree, "LENGTH", plane).outputs["Value"], radius.outputs[0])
        colour = _vector_math(tree, "SCALE", colour if colour is not None else (1.0, 1.0, 1.0),
                              inside.outputs[0]).outputs[0]
        ex = ctx.expr()
        ex.drive(tree, 'nodes["IrisRadius"].outputs[0].default_value',
                 f"1-{ex.dmx('iris')}*(1-{ex.cfg('iris_min_ratio')})")
    if colour is not None:
        tree.links.new(colour, emission.inputs["Color"])


def _drive_field(ctx: _Build, tree) -> None:
    ex = ctx.expr()
    path = 'nodes["FieldTan"].outputs[0].default_value'
    if ex.has("zoom") and ctx.f.source_kind == "SPOT":
        ex.drive(tree, path, f"tan(radians({ex.cfg('field_now')})/2)")
    else:
        tree.nodes["FieldTan"].outputs[0].default_value = math.tan(math.radians(ctx.f.field_angle) / 2)


# ------------------------------------------------------------------ fixture

def _label(root, f: RigFixture) -> None:
    root["theatre_fixture"], root["theatre_family"], root["theatre_mode"] = f.fixture_id, f.family, f.mode
    root["theatre_circuit"], root["theatre_universe"], root["theatre_address"] = f.circuit or "", f.universe, f.address
    patch = getattr(root, "dmx_patch", None)
    if patch is not None:
        patch.universe, patch.address = f.universe, f.address


def _build_fixture(base: _Build, f: RigFixture) -> bpy.types.Object:
    fx = base.library.get(f.fixture_id)
    root = _object(base, f.name, None, None, f.root, f.root_rotation)
    root.empty_display_size = 0.1
    if f.family == "hazer" or fx is None or fx.optics is None:
        _label(root, f)
        return root
    tube = next((t for t in fx.optics.lens_tubes if t.name == f.tube), None)
    ctx = base.for_fixture(f, fx, root, tube)
    model = fixture_model(fx, tube, _models)
    for key, value in _settings(f, fx, tube).items():
        root[key] = value
    _label(root, f)
    _body_part(ctx, "Base", model.base, f"TSF_{fx.id}_base", root)
    pan = _body_part(ctx, "Pan", model.pan, f"TSF_{fx.id}_yoke", root)
    pan.rotation_euler = (0.0, 0.0, math.radians(f.pan))
    tilt = _body_part(ctx, "Tilt", model.tilt, f"TSF_{fx.id}_head{ctx.tail}", pan, model.tilt_pivot)
    tilt.rotation_euler = (-math.radians(f.tilt), 0.0, 0.0)
    light = _make_light(ctx, tilt)
    lens = _make_lens(ctx, tilt, model.lens_radius, model.lens_offset)
    if f.blades is not None and fx.blades is not None:
        _make_blades(ctx, tilt)
    if f.moving:
        _drive_pose(ctx, pan, tilt)
    _drive_root(ctx)
    _drive_light(ctx, light)
    _drive_lens(ctx, lens)
    _build_tree(ctx, light)
    return root


def ensure_dmx_props(scene, rig: Rig) -> int:
    """Create the scene properties of the patched channels at their rest value; never overwrite one."""
    created = 0
    for (universe, channel), value in rig.rest.items():
        key = f"dmx_{universe}_{channel}"
        if key not in scene:
            scene[key] = float(value)
            created += 1
    return created


def rest_full(scene, rig: Rig) -> int:
    """Overwrite every patched channel with its rest value (spec 15.2); returns the channel count."""
    for (universe, channel), value in rig.rest.items():
        scene[f"dmx_{universe}_{channel}"] = float(value)
    scene.update_tag()
    bpy.context.view_layer.update()
    return len(rig.rest)


def _feeds_world_output(tree, name: str) -> bool:
    """True when the node `name` is upstream of the Volume input of the world output."""
    output = next((n for n in tree.nodes if n.bl_idname == "ShaderNodeOutputWorld"), None)
    pending = [link.from_node for link in output.inputs["Volume"].links] if output else []
    seen = set()
    while pending:
        node = pending.pop()
        if node.name == name:
            return True
        if node.name not in seen:
            seen.add(node.name)
            pending += [link.from_node for socket in node.inputs for link in socket.links]
    return False


def world_haze_active(scene) -> bool:
    """A DMX Visualizer haze (`DMX_Haze`) feeds the world volume (spec 15.4)."""
    tree = scene.world.node_tree if scene.world and scene.world.use_nodes else None
    return tree is not None and tree.nodes.get(WORLD_HAZE) is not None and _feeds_world_output(tree, WORLD_HAZE)


def build_rig(scene, layout, collections, new_mesh: Callable, material: Callable,
              library=None) -> dict[str, bpy.types.Object]:
    """Build the fixtures of `layout.rig` into `Theatre_Fixtures`; returns the root empties by name.

    `new_mesh(name, Mesh)` and `material(name)` come from the builder (UVs, user material choices).
    """
    warnings.clear()
    rig = layout.rig
    hazy = (rig is not None and rig.haze is not None) or "Haze_Volume" in layout.names()
    if hazy and world_haze_active(scene):
        warnings.append("Brume DMX Visualizer (World, « DMX_Haze ») active : la brume serait comptée deux fois.")
    if rig is None or not rig.enabled:
        return {}
    if ensure_dmx_props(scene, rig):
        scene.update_tag()
        bpy.context.view_layer.update()
    cache: dict = {}

    def cached_material(name: str):
        if name not in cache:
            cache[name] = material(name)
        return cache[name]

    base = _Build(scene, collections[FIXTURES_COLLECTION], new_mesh, cached_material,
                  library or default_library())
    roots = {}
    for f in rig.fixtures:
        try:
            roots[f.name] = _build_fixture(base, f)
        except Exception:
            traceback.print_exc()
            warnings.append(f"Appareil {f.name} non construit : voir la console.")
    return roots
