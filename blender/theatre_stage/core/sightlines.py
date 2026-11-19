"""Sightline geometry from the reference seat (spec 8.7), without bpy.

Section view: points are (Y, Z), the eye is (Y, Z) in front of the nose.
Plan view: coordinates are mirrored so that `u` grows toward the wing looked at.
"""

from __future__ import annotations

import math

EPS = 1e-9


def ray_height(eye: tuple[float, float], y_plane: float, point: tuple[float, float]) -> float:
    """Height at `y_plane` of the segment from `eye` to `point` (both (Y, Z))."""
    (ey, ez), (py, pz) = eye, point
    return ez + (pz - ez) * (y_plane - ey) / (py - ey)


def computed_bottoms(eye, screens, points, grid_z: float, y_end: float) -> dict[str, float]:
    """Highest bottom of each free screen that still hides everything up to the next screen.

    `screens` are (name, y, fixed_bottom or None) ordered front to back; `points`
    are (Y, Z) battens. The grid underside (height `grid_z`) closes each zone.
    """
    ordered = sorted(screens, key=lambda s: s[1])
    out: dict[str, float] = {}
    for index, (name, y, fixed) in enumerate(ordered):
        if fixed is not None:
            continue
        y_next = ordered[index + 1][1] if index + 1 < len(ordered) else y_end
        zone = [p for p in points if y + EPS < p[0] <= y_next + EPS]
        zone.append((y_next, grid_z))
        out[name] = min(ray_height(eye, y, p) for p in zone)
    return out


def visible_points(eye, screens, points) -> list[str]:
    """Names of the `points` (name, Y, Z) not hidden by any screen (name, y, bottom) in front."""
    seen = []
    for name, py, pz in points:
        hidden = any(y < py - EPS and ray_height(eye, y, (py, pz)) >= bottom - EPS
                     for _, y, bottom in screens)
        if not hidden:
            seen.append(name)
    return seen


def wing_line_u(seat_u: float, seat_y: float, edge: tuple[float, float], y_next: float) -> float:
    """`u` at `y_next` of the plan line from the seat grazing `edge` = (u, y)."""
    return seat_u + (y_next - seat_y) * (edge[0] - seat_u) / (edge[1] - seat_y)


def wing_reach(seat_u: float, seat_y: float, edges, y_next: float) -> tuple[float, float]:
    """(front edge u, reach u) of the most restrictive edge: the visible reach at `y_next`."""
    best = min(edges, key=lambda e: wing_line_u(seat_u, seat_y, e, y_next))
    return best[0], wing_line_u(seat_u, seat_y, best, y_next)


def segment_polygon_overlap(a, b, polygon) -> bool:
    """Whether segment a-b crosses a convex polygon (separating axis, touching excluded)."""
    for poly_axis in (polygon, (a, b)):
        for i in range(len(poly_axis)):
            (x0, y0), (x1, y1) = poly_axis[i], poly_axis[(i + 1) % len(poly_axis)]
            axis = (y0 - y1, x1 - x0)
            if math.hypot(*axis) < EPS:
                continue
            pa = [p[0] * axis[0] + p[1] * axis[1] for p in (a, b)]
            pb = [p[0] * axis[0] + p[1] * axis[1] for p in polygon]
            if max(pa) <= min(pb) + 1e-9 or max(pb) <= min(pa) + 1e-9:
                return False
    return True
