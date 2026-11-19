"""Layout to Blender data: collections, meshes, materials, lights, cameras.

No dimension is computed here; everything comes from `core.layout`.
Only objects tagged `TAG` are ever deleted.
"""

from __future__ import annotations

import bpy
import numpy as np
from mathutils import Vector

from .core.layout import Layout, compute_layout
from .core.meshes import Mesh, build_mesh, pleated_mesh
from .core.primitives import Light, PleatedSurface, Tube

TAG = "theatre_generated"
OPEN_KEY = "Open"
OPENING_PATH = "theatre.curtains.main_opening"
OPENING_EXPRESSION = "var / 100"

ROUGHNESS = {
    "TS_StageFloor": 0.35, "TS_Masking": 0.95, "TS_MainCurtain": 0.9, "TS_Cyclorama": 0.8,
    "TS_Enclosure": 0.85, "TS_HouseFloor": 0.7,
}

_layout_cache: tuple[str, Layout] | None = None


def cached_layout(params: dict) -> Layout:
    """`compute_layout` memoised on the last params (the panel calls it per redraw)."""
    global _layout_cache
    key = repr(params)
    if _layout_cache is None or _layout_cache[0] != key:
        _layout_cache = (key, compute_layout(params))
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


def foreign_objects(layout: Layout) -> list[str]:
    """Names of untagged objects sitting in the Theatre collections."""
    root = bpy.data.collections.get(layout.root_collection)
    if root is None:
        return []
    return sorted(o.name for o in root.all_objects if not is_generated(o))


def _delete_generated(root) -> None:
    doomed = [o for o in root.all_objects if is_generated(o)]
    datablocks = [(o.data, o.type) for o in doomed if o.data is not None]
    for obj in doomed:
        bpy.data.objects.remove(obj, do_unlink=True)
    registries = {"MESH": bpy.data.meshes, "LIGHT": bpy.data.lights, "CAMERA": bpy.data.cameras}
    for data, kind in datablocks:
        if data.users == 0:
            registries[kind].remove(data)


# --------------------------------------------------------------- materials

def get_material(name: str, colors) -> bpy.types.Material:
    """Existing material by name, never modified; created with its colour otherwise."""
    mat = bpy.data.materials.get(name)
    if mat is not None:
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


def _make_geometry(primitive, scene, collections, materials) -> bpy.types.Object:
    mesh = _new_mesh(primitive.name, build_mesh(primitive))
    if isinstance(primitive, PleatedSurface):
        _smooth(mesh, quads_only=False)
    elif isinstance(primitive, Tube):
        _smooth(mesh, quads_only=True)
    mesh.materials.append(materials[primitive.material])
    obj = bpy.data.objects.new(primitive.name, mesh)
    obj[TAG] = True
    collections[primitive.collection].objects.link(obj)
    if isinstance(primitive, PleatedSurface) and primitive.open_state is not None:
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
    data = bpy.data.cameras.new(spec.name)
    data.lens = spec.lens
    data.clip_end = 500.0
    obj = bpy.data.objects.new(spec.name, data)
    obj[TAG] = True
    _aim(obj, spec.location, spec.target)
    collections[spec.collection].objects.link(obj)
    return obj


# ------------------------------------------------------------------ rebuild

def rebuild(scene: bpy.types.Scene, params: dict) -> Layout:
    """Delete every generated object of `scene` and recreate it from `params`."""
    layout = cached_layout(params)
    collections = ensure_collections(scene, layout)

    active = scene.camera
    wanted_camera = active.name if active is not None and is_generated(active) else "Cam_Face"
    _delete_generated(collections[layout.root_collection])

    materials = {name: get_material(name, layout.materials)
                 for name in {p.material for p in layout.objects}}
    for primitive in layout.objects:
        _make_geometry(primitive, scene, collections, materials)
    for spec in layout.lights:
        _make_light(spec, collections)
    cameras = {spec.name: _make_camera(spec, collections) for spec in layout.cameras}

    if scene.camera is None or is_generated(scene.camera):
        scene.camera = cameras.get(wanted_camera) or cameras.get("Cam_Face")
    scene.update_tag()
    return layout
