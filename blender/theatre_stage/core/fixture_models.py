"""Fixture 3D models in the body frame of spec 13.9 and 14.2, without bpy.

Each part is a `Mesh` in the local frame of its Blender object, so the builder only parents
and places them. Pure function of (fixture, lens tube): safe to memoise by `(id, tube name)`.
"""

from __future__ import annotations

import json
import math
import struct
from dataclasses import dataclass

from .fixtures import Body, Fixture, LensTube, Model3D, Vec3
from .meshes import Mesh, build_mesh
from .meshio import read_mesh
from .primitives import Box, Tube

EMPTY = Mesh((), ())
LENS_NORMAL: Vec3 = (0.0, 0.0, 1.0)
SEGMENTS = 24
YOKE_ARM = 0.02
YOKE_DEPTH = 0.08
BRIDGE = 0.03
AXLE_RADIUS = 0.012
LENS_BULGE = 0.025
TUBE_WALL = 0.02
SHUTTER_SHARE = 0.3
TUBE_DIAMETER = 0.0483
_READ_ERRORS = (OSError, ValueError, KeyError, IndexError, struct.error, json.JSONDecodeError)


@dataclass(frozen=True)
class FixtureModel:
    """Meshes in metres, each in its own frame (14.2).

    `base` lives in the root frame (z = 0 on the mounting face, +Z toward the head). `pan`
    shares that origin and spins about Z. `tilt` has its origin on the tilt axis, at `tilt_pivot`
    in the pan frame, with the beam along +Z and the tilt axis along X. `lens_offset` is the
    lens front along the beam from the tilt axis; `gate_z` is the blade plane on the same axis
    (None without blades). Parts a fixture lacks are empty meshes.
    """

    fixture_id: str
    tube: str | None
    base: Mesh
    pan: Mesh
    tilt: Mesh
    tilt_pivot: Vec3
    lens_offset: float
    lens_radius: float
    gate_z: float | None

    @property
    def lens_centre(self) -> Vec3:
        return (0.0, 0.0, self.lens_offset)

    @property
    def lens_normal(self) -> Vec3:
        return LENS_NORMAL


def fixture_model(fixture: Fixture, tube: LensTube | None = None, cache: dict | None = None) -> FixtureModel:
    """Model of `fixture` with `tube` (None: the sheet default). `cache` memoises by (id, tube name)."""
    key = (fixture.id, tube.name if tube else None)
    if cache is not None and key in cache:
        return cache[key]
    meshes, pivot = _parts(fixture, fixture.model3d, tube)
    optics = fixture.optics
    blades = fixture.blades
    model = FixtureModel(
        fixture.id, key[1], *meshes, pivot,
        optics.lens_offset if optics else 0.0,
        optics.aperture(tube) / 2 if optics else 0.0,
        optics.lens_offset - blades.gate_from_lens if optics and blades else None,
    )
    if cache is not None:
        cache[key] = model
    return model


# ------------------------------------------------------------------ mesh helpers

def _merge(*meshes: Mesh) -> Mesh:
    vertices: list = []
    faces: list = []
    for mesh in meshes:
        base = len(vertices)
        vertices.extend(mesh.vertices)
        faces.extend(tuple(i + base for i in face) for face in mesh.faces)
    return Mesh(tuple(vertices), tuple(faces))


def _map(mesh: Mesh, fn) -> Mesh:
    return Mesh(tuple(fn(v) for v in mesh.vertices), mesh.faces)


def _box(lo: Vec3, hi: Vec3) -> Mesh:
    return build_mesh(Box("", "", "", (0.0, 0.0, 0.0), 0.0, lo, hi))


def _cylinder(start: Vec3, end: Vec3, radius: float, segments: int = SEGMENTS) -> Mesh:
    return build_mesh(Tube("", "", "", start, end, radius, segments))


def _along_z(z0: float, z1: float, rx: float, ry: float) -> Mesh:
    unit = _cylinder((0.0, 0.0, z0), (0.0, 0.0, z1), 1.0)
    return _map(unit, lambda v: (v[0] * rx, v[1] * ry, v[2]))


def _flip(v) -> Vec3:
    """GDTF frame (head toward -Z) to the body frame: a 180 degree rotation about X."""
    return (v[0], -v[1], -v[2])


# ------------------------------------------------------------------ dispatch

def _parts(fixture: Fixture, model: Model3D, tube: LensTube | None):
    """((base, pan, tilt), tilt_pivot) for a model."""
    if model.kind == "none":
        return (EMPTY, EMPTY, EMPTY), (0.0, 0.0, 0.0)
    if model.kind == "mesh":
        try:
            return _mesh_parts(fixture, model)
        except _READ_ERRORS:
            if model.fallback is None:
                raise
            return _parts(fixture, model.fallback, tube)
    if model.shape == "box":
        return (_box_base(fixture, model), EMPTY, EMPTY), (0.0, 0.0, 0.0)
    return _procedural_parts(fixture, model, tube)


def _mesh_parts(fixture: Fixture, model: Model3D):
    def load(name):
        part = model.part(name)
        if part is None:
            return EMPTY, (0.0, 0.0, 0.0)
        return read_mesh(fixture.path(part.file)), part.offset

    base, _ = load("base")
    yoke, yoke_at = load("yoke")
    head, head_at = load("head")
    pivot_gdtf = tuple(a + b for a, b in zip(yoke_at, head_at))
    pivot = _flip(pivot_gdtf)
    mount = fixture.physical.mount
    if mount is not None:
        pivot = (pivot[0], pivot[1], mount.tilt_axis_height)
    shifted = _map(yoke, lambda v: _flip((v[0] + yoke_at[0], v[1] + yoke_at[1], v[2] + yoke_at[2])))
    return (_map(base, _flip), shifted, _map(head, _flip)), pivot


def _body(fixture: Fixture, model: Model3D) -> Body:
    if model.body is not None:
        return model.body
    dims = fixture.physical.dimensions
    if dims is None:
        raise ValueError(f"{fixture.id}: procedural model needs a body or physical.dimensions")
    return Body(dims.width, dims.depth, dims.height)


def _box_base(fixture: Fixture, model: Model3D) -> Mesh:
    body = _body(fixture, model)
    return _box((-body.width / 2, -body.depth / 2, 0.0), (body.width / 2, body.depth / 2, body.height))


# ------------------------------------------------------------------ procedural movers

def _procedural_parts(fixture: Fixture, model: Model3D, tube: LensTube | None):
    body = _body(fixture, model)
    mount = fixture.physical.mount
    optics = fixture.optics
    if mount is None or optics is None:
        raise ValueError(f"{fixture.id}: procedural pc/profile needs physical.mount and optics")
    pivot_z = mount.tilt_axis_height
    gap = model.yoke.gap if model.yoke else body.width + 0.02
    return ((_clamp(mount.hook_height), _yoke(gap, pivot_z), _head(model, body, optics, gap, tube)),
            (0.0, 0.0, pivot_z))


def _clamp(hook_height: float) -> Mesh:
    """Mounting plate, neck and a ring around a tube parallel to X, hook_height above the plate."""
    ring = _cylinder((-0.03, 0.0, -hook_height), (0.03, 0.0, -hook_height), TUBE_DIAMETER / 2 + 0.008, 16)
    neck = _box((-0.015, -0.015, -hook_height), (0.015, 0.015, 0.0))
    plate = _box((-0.07, -0.05, -0.01), (0.07, 0.05, 0.0))
    return _merge(plate, neck, ring)


def _yoke(gap: float, pivot_z: float) -> Mesh:
    half = gap / 2
    y = YOKE_DEPTH / 2
    top = pivot_z + 0.035
    bridge = _box((-half - YOKE_ARM, -y, 0.0), (half + YOKE_ARM, y, BRIDGE))
    arm_r = _box((half, -y, 0.0), (half + YOKE_ARM, y, top))
    arm_l = _box((-half - YOKE_ARM, -y, 0.0), (-half, y, top))
    return _merge(bridge, arm_r, arm_l)


def _head(model: Model3D, body: Body, optics, gap: float, tube: LensTube | None) -> Mesh:
    front = optics.lens_offset
    lens_r = optics.aperture(tube) / 2
    axle = _cylinder((-gap / 2, 0.0, 0.0), (gap / 2, 0.0, 0.0), AXLE_RADIUS, 16)
    rx, ry = body.width / 2, body.height / 2
    if model.shape == "pc":
        rear = front - body.depth
        lens_r = min(lens_r, 0.95 * min(rx, ry))
        shell = _along_z(rear, front - LENS_BULGE, rx, ry)
        lens = _along_z(front - LENS_BULGE - 0.01, front, lens_r, lens_r)
        return _merge(shell, lens, axle)
    barrel = model.barrel
    rear = front - body.depth - barrel.length
    split = rear + (1 - SHUTTER_SHARE) * body.depth
    tube_r = max(barrel.diameter, 2 * lens_r + TUBE_WALL) / 2
    housing = _box((-rx, -ry, rear), (rx, ry, split))
    shutter = _along_z(split, front - barrel.length, ry, ry)
    lens_tube = _along_z(front - barrel.length, front, tube_r, tube_r)
    return _merge(housing, shutter, lens_tube, axle)
