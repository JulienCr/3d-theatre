"""Primitives to world-space meshes (vertices, faces), without bpy.

Closed primitives are watertight with outward, consistently wound faces.
Pleated and flat surfaces are open, single-sided sheets.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .primitives import (
    Box, FlatSurface, Panel, PleatedSurface, PleatState, Prism, SlatGrid, Tube,
)

PLEAT_SAMPLES = 4


@dataclass(frozen=True)
class Mesh:
    vertices: tuple[tuple[float, float, float], ...]
    faces: tuple[tuple[int, ...], ...]


class _Builder:
    def __init__(self):
        self.vertices: list = []
        self.faces: list = []

    def add(self, point) -> int:
        self.vertices.append(tuple(point))
        return len(self.vertices) - 1

    def face(self, indices, outward) -> None:
        """Add a face wound so that its normal points along `outward`."""
        pts = [self.vertices[i] for i in indices]
        nx = ny = nz = 0.0
        for a, b in zip(pts, pts[1:] + pts[:1]):
            nx += (a[1] - b[1]) * (a[2] + b[2])
            ny += (a[2] - b[2]) * (a[0] + b[0])
            nz += (a[0] - b[0]) * (a[1] + b[1])
        if nx * outward[0] + ny * outward[1] + nz * outward[2] < 0:
            indices = indices[::-1]
        self.faces.append(tuple(indices))

    def result(self, transform=None) -> Mesh:
        verts = self.vertices
        if transform is not None:
            verts = [transform(v) for v in verts]
        return Mesh(tuple(verts), tuple(self.faces))


def _frame(origin, yaw):
    c, s = math.cos(yaw), math.sin(yaw)
    ox, oy, oz = origin

    def to_world(p):
        return (ox + c * p[0] - s * p[1], oy + s * p[0] + c * p[1], oz + p[2])

    return to_world


_BOX_FACES = (
    ((0, 2, 6, 4), (-1, 0, 0)), ((1, 3, 7, 5), (1, 0, 0)),
    ((0, 1, 5, 4), (0, -1, 0)), ((2, 3, 7, 6), (0, 1, 0)),
    ((0, 1, 3, 2), (0, 0, -1)), ((4, 5, 7, 6), (0, 0, 1)),
)


def _add_box(b: _Builder, lo, hi) -> None:
    ids = [
        b.add((hi[0] if i & 1 else lo[0], hi[1] if i & 2 else lo[1],
               hi[2] if i & 4 else lo[2]))
        for i in range(8)
    ]
    for quad, outward in _BOX_FACES:
        b.face([ids[i] for i in quad], outward)


def _box_mesh(box: Box) -> Mesh:
    b = _Builder()
    _add_box(b, box.min, box.max)
    return b.result(_frame(box.origin, box.yaw))


def _slat_mesh(grid: SlatGrid) -> Mesh:
    b = _Builder()
    half = grid.slat_size / 2
    for xc in grid.x_centers:
        _add_box(b, (xc - half, grid.y_min, grid.z_min),
                 (xc + half, grid.y_max, grid.z_min + grid.slat_size))
    return b.result()


def _prism_mesh(prism: Prism) -> Mesh:
    b = _Builder()
    xy = prism.plane == "xy"

    def lift(a, c, t):
        return (a, c, t) if xy else (a, t, c)

    def lift_vec(a, c):
        return (a, c, 0.0) if xy else (a, 0.0, c)

    for polygon in prism.polygons:
        pts = list(polygon)
        area = sum(p[0] * q[1] - q[0] * p[1] for p, q in zip(pts, pts[1:] + pts[:1]))
        if area < 0:
            pts.reverse()
        n = len(pts)
        low = [b.add(lift(p[0], p[1], prism.t0)) for p in pts]
        high = [b.add(lift(p[0], p[1], prism.t1)) for p in pts]
        axis = lift(0.0, 0.0, 1.0)
        b.face(low, tuple(-v for v in axis))
        b.face(high, axis)
        for i in range(n):
            j = (i + 1) % n
            da, dc = pts[j][0] - pts[i][0], pts[j][1] - pts[i][1]
            b.face([low[i], low[j], high[j], high[i]], lift_vec(dc, -da))
    return b.result()


def _tube_mesh(tube: Tube) -> Mesh:
    b = _Builder()
    ax = [tube.end[i] - tube.start[i] for i in range(3)]
    length = math.sqrt(sum(c * c for c in ax))
    ax = [c / length for c in ax]
    ref = (0.0, 0.0, 1.0) if abs(ax[2]) < 0.9 else (1.0, 0.0, 0.0)
    e1 = [ax[1] * ref[2] - ax[2] * ref[1], ax[2] * ref[0] - ax[0] * ref[2],
          ax[0] * ref[1] - ax[1] * ref[0]]
    norm = math.sqrt(sum(c * c for c in e1))
    e1 = [c / norm for c in e1]
    e2 = [ax[1] * e1[2] - ax[2] * e1[1], ax[2] * e1[0] - ax[0] * e1[2],
          ax[0] * e1[1] - ax[1] * e1[0]]
    n = tube.segments
    radial = []
    for i in range(n):
        a = 2 * math.pi * i / n
        radial.append([math.cos(a) * e1[k] + math.sin(a) * e2[k] for k in range(3)])
    ring0 = [b.add([tube.start[k] + tube.radius * r[k] for k in range(3)]) for r in radial]
    ring1 = [b.add([tube.end[k] + tube.radius * r[k] for k in range(3)]) for r in radial]
    b.face(ring0, tuple(-c for c in ax))
    b.face(ring1, tuple(ax))
    for i in range(n):
        j = (i + 1) % n
        mid = [radial[i][k] + radial[j][k] for k in range(3)]
        b.face([ring0[i], ring0[j], ring1[j], ring1[i]], mid)
    return b.result()


def _axis_lines(values) -> list[float]:
    ordered = sorted(values)
    lines = [ordered[0]]
    for v in ordered[1:]:
        if v - lines[-1] > 1e-9:
            lines.append(v)
    return lines


def _nearest(lines, value) -> int:
    return min(range(len(lines)), key=lambda i: abs(lines[i] - value))


def _panel_mesh(panel: Panel) -> Mesh:
    us = _axis_lines([c[k] for c in panel.cells for k in (0, 2)])
    zs = _axis_lines([c[k] for c in panel.cells for k in (1, 3)])
    present = set()
    for u0, z0, u1, z1 in panel.cells:
        for i in range(_nearest(us, u0), _nearest(us, u1)):
            for j in range(_nearest(zs, z0), _nearest(zs, z1)):
                present.add((i, j))
    b = _Builder()
    ids: dict = {}

    def vertex(side, i, j):
        key = (side, i, j)
        if key not in ids:
            v = panel.v_min if side == 0 else panel.v_max
            ids[key] = b.add((us[i], v, zs[j]))
        return ids[key]

    for i, j in sorted(present):
        for side, outward in ((0, (0, -1, 0)), (1, (0, 1, 0))):
            b.face([vertex(side, i, j), vertex(side, i + 1, j),
                    vertex(side, i + 1, j + 1), vertex(side, i, j + 1)], outward)
        edges = (
            ((i - 1, j), (-1, 0, 0), (i, j), (i, j + 1)),
            ((i + 1, j), (1, 0, 0), (i + 1, j), (i + 1, j + 1)),
            ((i, j - 1), (0, 0, -1), (i, j), (i + 1, j)),
            ((i, j + 1), (0, 0, 1), (i, j + 1), (i + 1, j + 1)),
        )
        for neighbour, outward, a, c in edges:
            if neighbour not in present:
                b.face([vertex(0, *a), vertex(0, *c), vertex(1, *c), vertex(1, *a)], outward)
    return b.result(_frame(panel.origin, panel.yaw))


def _sheet(b: _Builder, columns, z0, z1, facing) -> None:
    out = (facing[0], facing[1], 0.0)
    bottom = [b.add((x, y, z0)) for x, y in columns]
    top = [b.add((x, y, z1)) for x, y in columns]
    for i in range(len(columns) - 1):
        b.face([bottom[i], bottom[i + 1], top[i + 1], top[i]], out)


def _pleat_columns(state: PleatState, count: int) -> list[tuple[float, float]]:
    (x0, y0), (x1, y1) = state.p0, state.p1
    dx, dy = x1 - x0, y1 - y0
    length = math.hypot(dx, dy)
    nx, ny = (-dy / length, dx / length) if length > 0 else (0.0, 0.0)
    steps = PLEAT_SAMPLES * count
    columns = []
    for i in range(steps + 1):
        t = i / steps
        off = state.amplitude * math.sin(2 * math.pi * count * t)
        columns.append((x0 + dx * t + nx * off, y0 + dy * t + ny * off))
    return columns


def pleated_mesh(surface: PleatedSurface, open_pose: bool = False) -> Mesh:
    """Mesh of a pleated surface; `open_pose` uses `open_state` (same topology)."""
    state = surface.open_state if open_pose else surface.state
    if state is None:
        raise ValueError(f"{surface.name} has no open state")
    b = _Builder()
    _sheet(b, _pleat_columns(state, surface.pleat_count), surface.z0, surface.z1,
           surface.facing)
    return b.result()


def _flat_mesh(surface: FlatSurface) -> Mesh:
    b = _Builder()
    _sheet(b, [surface.p0, surface.p1], surface.z0, surface.z1, surface.facing)
    return b.result()


def build_mesh(primitive) -> Mesh:
    """World-space mesh of any primitive (closed pose for pleated surfaces)."""
    if isinstance(primitive, Box):
        return _box_mesh(primitive)
    if isinstance(primitive, Prism):
        return _prism_mesh(primitive)
    if isinstance(primitive, Panel):
        return _panel_mesh(primitive)
    if isinstance(primitive, Tube):
        return _tube_mesh(primitive)
    if isinstance(primitive, SlatGrid):
        return _slat_mesh(primitive)
    if isinstance(primitive, PleatedSurface):
        return pleated_mesh(primitive)
    if isinstance(primitive, FlatSurface):
        return _flat_mesh(primitive)
    raise TypeError(f"Unsupported primitive: {type(primitive).__name__}")
