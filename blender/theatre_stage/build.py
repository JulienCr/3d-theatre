"""Layout to Blender data: collections, meshes, materials, lights, cameras.

No dimension is computed here; everything comes from `core.layout`.
Only objects tagged `TAG` are ever deleted.
"""

from __future__ import annotations

import bpy
import numpy as np
from mathutils import Vector

from . import atmosphere, materials, rigbuild
from .core.face_rig import FaceEq
from .core.layout import Layout, compute_layout
from .core.meshes import Mesh, build_mesh, pleated_mesh
from .core.primitives import Light, PleatedSurface, Tube

TAG = materials.TAG
OPEN_KEY = "Open"
FACE_EQ_KEY = "theatre_face_eq"
OPENING_PATH = "theatre.curtains.main_opening"
HAZE_NODE = "Haze Scatter"
HAZE_DENSITY = "Haze Density"
HAZE_RAMP = "Haze Ramp"
OPENING_EXPRESSION = "var / 100"
FABRIC_THICKNESS = 0.003

ROUGHNESS = {
    "TS_StageFloor": 0.35, "TS_Masking": 0.95, "TS_MainCurtain": 0.9, "TS_Cyclorama": 0.8,
    "TS_Enclosure": 0.85, "TS_HouseFloor": 0.7, "TS_Fixture": 0.55, "TS_Lens": 0.05,
}

_layout_cache: tuple[tuple, Layout] | None = None
foreign_names: list[str] = []
rebuilding = False


def cached_layout(params: dict, library=None, face_eq: str | None = None) -> Layout:
    """`compute_layout` memoised on the last params, library and stored face equalisation (JSON text)."""
    global _layout_cache
    key = (repr(params), id(library), face_eq)
    if _layout_cache is None or _layout_cache[0] != key:
        _layout_cache = (key, compute_layout(params, library, FaceEq.from_json(face_eq)))
    return _layout_cache[1]


def is_generated(obj) -> bool:
    return obj.get(TAG) is not None


# ------------------------------------------------------------- collections

def _ensure_collection(name: str, parent) -> bpy.types.Collection:
    coll = bpy.data.collections.get(name)
    if coll is None:
        coll = bpy.data.collections.new(name)
    if coll.name not in parent.children:
        parent.children.link(coll)
    return coll


def ensure_collections(scene, layout: Layout) -> dict[str, bpy.types.Collection]:
    root = _ensure_collection(layout.root_collection, scene.collection)
    out = {layout.root_collection: root}
    for name in layout.collections:
        out[name] = _ensure_collection(name, root)
    return out


def _delete_generated(root, keep_cameras: frozenset[str] | set[str] = frozenset()) -> None:
    doomed = [o for o in materials.walk_objects(root)
              if is_generated(o) and not (o.type == "CAMERA" and o.name in keep_cameras)]
    datablocks = [(o.data, o.type) for o in doomed if o.data is not None]
    for obj in doomed:
        bpy.data.objects.remove(obj, do_unlink=True)
    registries = {"MESH": bpy.data.meshes, "LIGHT": bpy.data.lights, "CAMERA": bpy.data.cameras}
    for data, kind in datablocks:
        if data.users == 0:
            registries[kind].remove(data)


# --------------------------------------------------------------- materials

def _setup_ceiling_material(mat: bpy.types.Material, scene: bpy.types.Scene) -> None:
    """Hide the back face in EEVEE and the viewport (culling) and in Cycles (Backfacing mix)."""
    mat.use_backface_culling = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    bsdf = nodes.get("Principled BSDF")
    output = next(n for n in nodes if n.type == "OUTPUT_MATERIAL")
    geometry = nodes.new("ShaderNodeNewGeometry")
    clear = nodes.new("ShaderNodeBsdfTransparent")
    mix = nodes.new("ShaderNodeMixShader")
    links.new(geometry.outputs["Backfacing"], mix.inputs["Fac"])
    links.new(bsdf.outputs["BSDF"], mix.inputs[1])
    links.new(clear.outputs["BSDF"], mix.inputs[2])
    links.new(mix.outputs["Shader"], output.inputs["Surface"])


def _drive(tree, path: str, expression: str, scene: bpy.types.Scene, **sources: str) -> None:
    """Driver on a node-tree property reading scene properties (`name=data_path`)."""
    driver = tree.driver_add(path).driver
    driver.type = "SCRIPTED"
    for name, data_path in sources.items():
        var = driver.variables.new()
        var.name = name
        var.type = "SINGLE_PROP"
        var.targets[0].id_type = "SCENE"
        var.targets[0].id = scene
        var.targets[0].data_path = data_path
    driver.expression = expression


def _setup_haze_material(mat: bpy.types.Material, scene: bpy.types.Scene) -> None:
    """Volume Scatter without surface. Density is scaled by a Y ramp that only the
    "stage" extent activates (enum index 1 is "stage_and_house": ramp neutral)."""
    tree = mat.node_tree
    nodes, links = tree.nodes, tree.links
    nodes.clear()
    output = nodes.new("ShaderNodeOutputMaterial")
    scatter = nodes.new("ShaderNodeVolumeScatter")
    scatter.name = HAZE_NODE
    density = nodes.new("ShaderNodeValue")
    density.name = HAZE_DENSITY
    coords = nodes.new("ShaderNodeTexCoord")
    split = nodes.new("ShaderNodeSeparateXYZ")
    ramp = nodes.new("ShaderNodeMapRange")
    ramp.name = HAZE_RAMP
    ramp.clamp = True
    scale = nodes.new("ShaderNodeMath")
    scale.operation = "MULTIPLY"
    links.new(coords.outputs["Object"], split.inputs["Vector"])
    links.new(split.outputs["Y"], ramp.inputs["Value"])
    links.new(ramp.outputs["Result"], scale.inputs[0])
    links.new(density.outputs[0], scale.inputs[1])
    links.new(scale.outputs[0], scatter.inputs["Density"])
    links.new(scatter.outputs["Volume"], output.inputs["Volume"])
    drive_haze_density(mat, scene, None)
    _drive(tree, f'nodes["{HAZE_NODE}"].inputs["Anisotropy"].default_value', "var", scene,
           var="theatre.haze.anisotropy")
    ramp_path = f'nodes["{HAZE_RAMP}"].inputs'
    setback = "theatre.advanced.proscenium_setback"
    _drive(tree, f'{ramp_path}["From Min"].default_value', "ys - fade", scene,
           ys=setback, fade="theatre.haze.falloff")
    _drive(tree, f'{ramp_path}["From Max"].default_value', "ys", scene, ys=setback)
    _drive(tree, f'{ramp_path}["To Min"].default_value', "mode", scene,
           mode="theatre.haze.extent")


def drive_haze_density(mat: bpy.types.Material, scene: bpy.types.Scene, link) -> None:
    """Density = `haze.density`, times the hazer level when the rig has a DMX-driven hazer (spec 15.4)."""
    tree = mat.node_tree
    if tree is None or tree.nodes.get(HAZE_DENSITY) is None:
        return
    path = f'nodes["{HAZE_DENSITY}"].outputs[0].default_value'
    tree.driver_remove(path)
    if link is None:
        _drive(tree, path, "var", scene, var="theatre.haze.density")
        return
    level, paths = link.level()
    _drive(tree, path, f"var*{level}", scene, var="theatre.haze.density", **paths)


def _upgrade_haze_material(mat: bpy.types.Material, scene: bpy.types.Scene) -> None:
    """Give a TS_Haze made before the ramp existed its new node setup (ours only)."""
    tree = mat.node_tree
    if tree and tree.nodes.get(HAZE_NODE) and tree.nodes.get(HAZE_RAMP) is None:
        tree.animation_data_clear()
        _setup_haze_material(mat, scene)


MATERIAL_SETUP = {"TS_HouseCeiling": _setup_ceiling_material, "TS_Haze": _setup_haze_material,
                  "TS_Lens": rigbuild.setup_lens_material}
MATERIAL_UPGRADE = {"TS_Haze": _upgrade_haze_material}


def get_material(name: str, colors, scene: bpy.types.Scene) -> bpy.types.Material:
    """Existing material by name, never modified; created with its colour otherwise."""
    mat = bpy.data.materials.get(name)
    if mat is not None:
        if name in MATERIAL_UPGRADE:
            MATERIAL_UPGRADE[name](mat, scene)
        return mat
    mat = bpy.data.materials.new(name)
    color = colors[name]
    mat.diffuse_color = color
    if mat.node_tree is None:
        mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF") if mat.node_tree else None
    if bsdf is not None:
        bsdf.inputs["Base Color"].default_value = color
        bsdf.inputs["Roughness"].default_value = ROUGHNESS.get(name, 0.6)
    if name in MATERIAL_SETUP:
        MATERIAL_SETUP[name](mat, scene)
    return mat


# ------------------------------------------------------------------ meshes

def _box_project_uvs(mesh: bpy.types.Mesh) -> None:
    """Box-projected UVs, 1 UV unit = 1 m (the dominant normal axis picks the plane)."""
    n_loops, n_polys = len(mesh.loops), len(mesh.polygons)
    if n_loops == 0:
        return
    co = np.empty(len(mesh.vertices) * 3, dtype=np.float32)
    mesh.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)
    vert = np.empty(n_loops, dtype=np.int32)
    mesh.loops.foreach_get("vertex_index", vert)
    normals = np.empty(n_polys * 3, dtype=np.float32)
    mesh.polygons.foreach_get("normal", normals)
    totals = np.empty(n_polys, dtype=np.int32)
    mesh.polygons.foreach_get("loop_total", totals)
    face_of_loop = np.repeat(np.arange(n_polys), totals)
    axis = np.abs(normals.reshape(-1, 3)).argmax(axis=1)[face_of_loop]
    pos = co[vert]
    # axis 0 (X normal) -> (y, z); axis 1 (Y normal) -> (x, z); axis 2 -> (x, y)
    u = np.where(axis == 0, pos[:, 1], pos[:, 0])
    v = np.where(axis == 2, pos[:, 1], pos[:, 2])
    layer = mesh.uv_layers.new(name="UVMap")
    layer.data.foreach_set("uv", np.stack([u, v], axis=1).ravel())


def _smooth(mesh: bpy.types.Mesh, quads_only: bool) -> None:
    totals = np.empty(len(mesh.polygons), dtype=np.int32)
    mesh.polygons.foreach_get("loop_total", totals)
    flags = (totals == 4) if quads_only else np.ones(len(totals), dtype=bool)
    mesh.polygons.foreach_set("use_smooth", flags)


def _new_mesh(name: str, data: Mesh) -> bpy.types.Mesh:
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(data.vertices, [], data.faces)
    mesh.update()
    _box_project_uvs(mesh)
    return mesh


def _add_open_key(obj: bpy.types.Object, surface: PleatedSurface) -> None:
    obj.shape_key_add(name="Basis", from_mix=False)
    key = obj.shape_key_add(name=OPEN_KEY, from_mix=False)
    flat = np.asarray(pleated_mesh(surface, open_pose=True).vertices, dtype=np.float32).ravel()
    key.data.foreach_set("co", flat)


def _add_opening_driver(obj: bpy.types.Object, scene: bpy.types.Scene) -> None:
    keys = obj.data.shape_keys
    curve = keys.driver_add(f'key_blocks["{OPEN_KEY}"].value')
    driver = curve.driver
    driver.type = "SCRIPTED"
    var = driver.variables.new()
    var.name = "var"
    var.type = "SINGLE_PROP"
    target = var.targets[0]
    target.id_type = "SCENE"
    target.id = scene
    target.data_path = OPENING_PATH
    driver.expression = OPENING_EXPRESSION


def _add_fabric_modifiers(obj: bpy.types.Object) -> None:
    """Live subdivision then thickness, so the sheet reads as velvet (kept unapplied)."""
    subsurf = obj.modifiers.new("Subdivision", "SUBSURF")
    subsurf.levels = 1
    subsurf.render_levels = 2
    solidify = obj.modifiers.new("Solidify", "SOLIDIFY")
    solidify.thickness = FABRIC_THICKNESS
    solidify.offset = 0.0
    solidify.use_even_offset = True


def _make_geometry(primitive, scene, collections, slot_materials) -> bpy.types.Object:
    mesh = _new_mesh(primitive.name, build_mesh(primitive))
    if isinstance(primitive, PleatedSurface):
        _smooth(mesh, quads_only=False)
    elif isinstance(primitive, Tube):
        _smooth(mesh, quads_only=True)
    mesh.materials.append(slot_materials[primitive.material])
    obj = bpy.data.objects.new(primitive.name, mesh)
    obj[TAG] = True
    obj[materials.CATEGORY] = primitive.material
    collections[primitive.collection].objects.link(obj)
    if primitive.name == "Haze_Volume":
        obj.display_type = "BOUNDS"
        obj.visible_shadow = False
    if isinstance(primitive, PleatedSurface):
        _add_fabric_modifiers(obj)
        if primitive.open_state is not None:
            _add_open_key(obj, primitive)
            _add_opening_driver(obj, scene)
    return obj


# ----------------------------------------------------- lights and cameras

def _aim(obj: bpy.types.Object, location, target) -> None:
    """Place `obj` and rotate it so its local -Z points at `target` (Y up)."""
    obj.location = location
    direction = Vector(target) - Vector(location)
    obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def _make_light(spec: Light, collections) -> bpy.types.Object:
    data = bpy.data.lights.new(spec.name, spec.kind)
    data.shape = "SQUARE"
    data.size = spec.size
    data.energy = spec.energy
    data.use_temperature = True
    data.temperature = spec.color_temperature
    obj = bpy.data.objects.new(spec.name, data)
    obj[TAG] = True
    _aim(obj, spec.location, spec.target)
    collections[spec.collection].objects.link(obj)
    return obj


def _make_camera(spec, collections) -> bpy.types.Object:
    """Create the camera, or update the generated one in place: deleting the active camera
    throws a 3D view out of camera view."""
    obj = bpy.data.objects.get(spec.name)
    if obj is None or obj.type != "CAMERA" or not is_generated(obj):
        obj = bpy.data.objects.new(spec.name, bpy.data.cameras.new(spec.name))
        obj[TAG] = True
    obj.data.lens = spec.lens
    obj.data.clip_end = 500.0
    _aim(obj, spec.location, spec.target)
    target = collections[spec.collection]
    for coll in collections.values():
        if coll is not target and obj.name in coll.objects:
            coll.objects.unlink(obj)
    if obj.name not in target.objects:
        target.objects.link(obj)
    return obj


# ------------------------------------------------------------------ rebuild

def rebuild(scene: bpy.types.Scene, params: dict, library=None) -> Layout:
    """Delete every generated object of `scene` and recreate it from `params` and the fixture `library`."""
    global rebuilding
    rebuilding = True
    try:
        return _rebuild(scene, params, library)
    finally:
        rebuilding = False


def _rebuild(scene: bpy.types.Scene, params: dict, library) -> Layout:
    materials.ensure_items(scene)
    materials.detect(scene)
    layout = cached_layout(params, library, scene.get(FACE_EQ_KEY))
    collections = ensure_collections(scene, layout)

    active = scene.camera
    wanted_camera = active.name if active is not None and is_generated(active) else "Cam_Face"
    _delete_generated(collections[layout.root_collection], {spec.name for spec in layout.cameras})

    chosen = materials.overrides(scene)
    slot_materials = {}
    for name in {p.material for p in layout.objects}:
        default = get_material(name, layout.materials, scene)
        slot_materials[name] = chosen.get(name) or default
    for primitive in layout.objects:
        _make_geometry(primitive, scene, collections, slot_materials)
    for spec in layout.lights:
        _make_light(spec, collections)
    rigbuild.build_rig(scene, layout, collections, _new_mesh,
                       lambda name: chosen.get(name) or get_material(name, layout.materials, scene), library)
    haze = bpy.data.materials.get("TS_Haze")
    if haze is not None:
        drive_haze_density(haze, scene, layout.rig.haze if layout.rig else None)
    cameras = {spec.name: _make_camera(spec, collections) for spec in layout.cameras}
    atmosphere.apply(scene, params, layout)

    if scene.camera is None or is_generated(scene.camera):
        chosen_camera = cameras.get(wanted_camera) or cameras.get("Cam_Face")
        if scene.camera != chosen_camera:
            scene.camera = chosen_camera
    foreign_names[:] = sorted(o.name for o in materials.walk_objects(collections[layout.root_collection])
                              if not is_generated(o))
    scene.update_tag()
    return layout
