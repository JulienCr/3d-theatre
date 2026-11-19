"""Frozen descriptions of everything the builder has to create.

Every geometric primitive carries `name`, `material` and `collection`.
Local frames are right-handed: world = origin + Rz(yaw) * local.
"""

from __future__ import annotations

from dataclasses import dataclass

Vec2 = tuple[float, float]
Vec3 = tuple[float, float, float]
Rect = tuple[float, float, float, float]  # (u0, z0, u1, z1)


@dataclass(frozen=True)
class Box:
    """Oriented box: `min`/`max` are local corners, `yaw` is in radians."""

    name: str
    material: str
    collection: str
    origin: Vec3
    yaw: float
    min: Vec3
    max: Vec3


@dataclass(frozen=True)
class Prism:
    """Polygons in a plane, extruded from `t0` to `t1` along the third axis.

    plane "xy": points are (x, y), extruded along z.
    plane "xz": points are (x, z), extruded along y.
    Several polygons make several disjoint shells in one object.
    """

    name: str
    material: str
    collection: str
    plane: str
    polygons: tuple[tuple[Vec2, ...], ...]
    t0: float
    t1: float


@dataclass(frozen=True)
class Panel:
    """Slab with through openings, as solid (u, z) cells.

    Local frame: x = u along the face, y = v across the thickness, z up.
    The slab spans v in [v_min, v_max]. `cells` tile the face minus the
    `openings`; the mesh has no internal faces between cells.
    """

    name: str
    material: str
    collection: str
    origin: Vec3
    yaw: float
    v_min: float
    v_max: float
    size: Vec2
    cells: tuple[Rect, ...]
    openings: tuple[Rect, ...]


@dataclass(frozen=True)
class Tube:
    name: str
    material: str
    collection: str
    start: Vec3
    end: Vec3
    radius: float
    segments: int = 16


@dataclass(frozen=True)
class SlatGrid:
    """Square slats parallel to Y, one box per entry of `x_centers`."""

    name: str
    material: str
    collection: str
    x_centers: tuple[float, ...]
    y_min: float
    y_max: float
    z_min: float
    slat_size: float


@dataclass(frozen=True)
class PleatState:
    """Horizontal path (x, y) of a pleated surface and its pleat amplitude."""

    p0: Vec2
    p1: Vec2
    amplitude: float


@dataclass(frozen=True)
class PleatedSurface:
    """Zero-thickness vertical drapery following a horizontal path.

    Offsets are applied perpendicular to the path in the XY plane. The mesh is
    a grid of rows by columns (see `core.meshes.grid_shape`) whose faces look
    toward `facing`. `drape` (0-1) doses the irregularity of the folds; the
    random draw is seeded from `name`. `open_state`, when set, is a second pose
    with the same topology (shape key).
    """

    name: str
    material: str
    collection: str
    state: PleatState
    z0: float
    z1: float
    pleat_count: int
    facing: Vec2
    open_state: PleatState | None = None
    drape: float = 0.0


@dataclass(frozen=True)
class FlatSurface:
    """Single zero-thickness quad between two XY points, from z0 to z1."""

    name: str
    material: str
    collection: str
    p0: Vec2
    p1: Vec2
    z0: float
    z1: float
    facing: Vec2


@dataclass(frozen=True)
class Light:
    """Square area light aimed from `location` at `target`."""

    name: str
    collection: str
    location: Vec3
    target: Vec3
    size: float
    energy: float
    color_temperature: float
    kind: str = "AREA"


@dataclass(frozen=True)
class Camera:
    name: str
    collection: str
    location: Vec3
    target: Vec3
    lens: float


Primitive = Box | Prism | Panel | Tube | SlatGrid | PleatedSurface | FlatSurface
