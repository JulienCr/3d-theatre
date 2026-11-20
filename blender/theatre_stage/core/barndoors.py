"""Barn door leaves of a PC (spec 13.12): hinge angles that put each leaf tip on a cut plane.

Pure maths, no bpy. The head frame is the one of spec 13.9: origin on the tilt axis, `z` along the
beam, `(x_h, y_h, a)` its world images. Angles are in degrees, lengths in metres.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import permutations

from .fixtures import BarnDoors
from .vecmath import add, cross, dot, mul, sub, unit

Vec3 = tuple[float, float, float]
Line = tuple[Vec3, Vec3]

CUT_NAMES = ("bottom", "top", "left", "right")
CUT_WEIGHTS = {"bottom": 1000.0, "top": 100.0, "left": 1.0, "right": 1.0}
ROTATION_STEP = 1.0
FINE_STEP = 0.1
RING_SEGMENTS = 12
EPS = 1e-9
SIDE_MIN = 1e-6


@dataclass(frozen=True)
class Leaf:
    """One leaf. `side` is the head-frame direction of its hinge side, rotation included. `hinge` is
    the middle of the hinge line in the head frame, `axes` the leaf frame in the head frame: `x` along
    the hinge, `z` from hinge to tip (the beam direction at angle 0), `y = z x x`.

    `normal` is the world unit normal of the plane through the lens centre and the tip edge, on the
    dark side (None while open). `reached` is False when the leaf could not put its tip on the cut
    asked: too short, or stopped by the angle limit.
    """

    index: int
    cut: str
    side: float
    angle: float
    hinge: Vec3
    axes: tuple[Vec3, Vec3, Vec3]
    active: bool
    reached: bool
    normal: Vec3 | None


@dataclass(frozen=True)
class BarnDoorSet:
    rotation: float
    hinge_radius: float
    hinge_z: float
    length: float
    width: float
    max_angle: float
    leaves: tuple[Leaf, ...]

    @property
    def normals(self) -> tuple[Vec3, ...]:
        """Cut planes of the closed leaves, through the lens centre, pointing to the dark side."""
        return tuple(leaf.normal for leaf in self.leaves if leaf.normal is not None)


def cut_normal(source: Vec3, line: Line, axis: Vec3) -> Vec3 | None:
    """Unit normal of the plane through `source` containing `line = (point, direction)`, turned to the
    dark side (`n . axis < 0`). None when `source` lies on the line."""
    c = cross(sub(line[0], source), line[1])
    if dot(c, c) < EPS:
        return None
    n = unit(c)
    return mul(n, -1.0) if dot(n, axis) > 0 else n


def beyond(normals: Sequence[Vec3], lens: Vec3, p: Vec3) -> bool:
    """Whether `p` lies on the dark side of a cut plane through `lens`."""
    v = sub(p, lens)
    return any(dot(n, v) > EPS for n in normals)


def envelope_points(doors: BarnDoors, lens_offset: float) -> tuple[Vec3, ...]:
    """Head-frame points bounding the leaves at any rotation, for the posed footprint (spec 13.10)."""
    z0 = lens_offset + doors.hinge_offset
    reach = math.hypot(doors.hinge_radius, doors.leaf_width / 2)
    ring = [(reach * math.cos(2 * math.pi * k / RING_SEGMENTS), reach * math.sin(2 * math.pi * k / RING_SEGMENTS))
            for k in range(RING_SEGMENTS)]
    return tuple((x, y, z) for z in (z0, z0 + doors.leaf_length) for x, y in ring)


def _head_axes(side: float) -> tuple[Vec3, Vec3, Vec3]:
    """Head-frame `(o, q, a)` of a leaf whose hinge side points at `side` degrees."""
    psi = math.radians(side)
    return ((math.cos(psi), math.sin(psi), 0.0), (-math.sin(psi), math.cos(psi), 0.0), (0.0, 0.0, 1.0))


def _world(frame, v: Vec3) -> Vec3:
    return add(add(mul(frame[0], v[0]), mul(frame[1], v[1])), mul(frame[2], v[2]))


def _leaf(doors: BarnDoors, lens_offset: float, frame, index: int, cut: str, side: float, angle: float,
          reached: bool) -> Leaf:
    o, q, a = _head_axes(side)
    theta = math.radians(angle)
    tip = add(mul(a, math.cos(theta)), mul(o, -math.sin(theta)))
    hinge = add(mul(o, doors.hinge_radius), mul(a, lens_offset + doors.hinge_offset))
    active = angle > SIDE_MIN
    normal = None
    if active:
        x = doors.hinge_radius - doors.leaf_length * math.sin(theta)
        y = doors.hinge_offset + doors.leaf_length * math.cos(theta)
        n = add(mul(_world(frame, o), y), mul(_world(frame, a), -x))
        normal = unit(n)
    return Leaf(index, cut, side, angle, hinge, (q, cross(tip, q), tip), active, reached, normal)


def _assemble(doors: BarnDoors, lens_offset: float, frame, rotation: float,
              placed: Mapping[int, tuple[str, float, bool]]) -> BarnDoorSet:
    """The set with `placed` (leaf index -> cut, angle, reached); the other leaves stay open."""
    leaves = []
    for k in range(doors.count):
        cut, angle, reached = placed.get(k, ("", 0.0, True))
        leaves.append(_leaf(doors, lens_offset, frame, k + 1, cut, doors.sides[k] + rotation, angle, reached))
    return BarnDoorSet(rotation, doors.hinge_radius, lens_offset + doors.hinge_offset, doors.leaf_length,
                       doors.leaf_width, doors.max_angle, tuple(leaves))


def manual_set(doors: BarnDoors, lens_offset: float, frame, angles: Sequence[float],
               rotation: float) -> BarnDoorSet:
    """Leaves set by hand: angles clamped to `[0, max_angle]`, rotation to the fiche range."""
    rho = min(max(rotation, doors.rotation.min), doors.rotation.max)
    placed = {k: ("", min(max(angles[k], 0.0), doors.max_angle), True) for k in range(doors.count)}
    return _assemble(doors, lens_offset, frame, rho, placed)


def _closing_angle(doors: BarnDoors, s: float, c: float) -> tuple[float, bool]:
    """Angle that puts the tip centre of a leaf on a plane through the lens centre, and whether it got there.

    `(s, c)` are the plane's coordinates in the leaf plane: from a normal `n`, `s = n . o` and
    `c = -n . a`; from a point `v` of the plane, `s = v . a` and `c = v . o`. The tip minus the lens
    centre is `(r - L sin t) o + (m + L cos t) a`, so its dot with the normal is
    `r s - m c - L (s sin t + c cos t)`.
    """
    r, m, length = doors.hinge_radius, doors.hinge_offset, doors.leaf_length
    base = r * s - m * c
    if base - length * c <= 0:
        return 0.0, True
    big = math.hypot(s, c)
    k = base / (length * big)
    phi = math.degrees(math.atan2(s, c))
    if k > 1:
        return min(phi, doors.max_angle), False
    theta = phi - math.degrees(math.acos(k))
    return (doors.max_angle, False) if theta > doors.max_angle else (max(theta, 0.0), True)


def _reference_point(lens: Vec3, axis: Vec3, line: Line) -> Vec3 | None:
    """Point of the target line nearest to the beam axis: where the cut should be exact."""
    q, u = line
    r = sub(lens, q)
    b, d, e = dot(axis, u), dot(axis, r), dot(u, r)
    den = 1.0 - b * b
    if den < SIDE_MIN:
        return None
    return add(q, mul(u, (e - b * d) / den))


def _rotations(doors: BarnDoors) -> list[float]:
    """Coarse rotations to try. Evenly spaced leaves repeat every `360 / count` degrees, so a window
    of one period around zero is enough when the range allows it."""
    lo, hi = doors.rotation.min, doors.rotation.max
    gaps = sorted((doors.sides[(k + 1) % doors.count] - doors.sides[k]) % 360 for k in range(doors.count))
    half = gaps[0] / 2
    if gaps[-1] - gaps[0] < EPS and lo <= half and hi >= -half:
        lo, hi = max(lo, -half), min(hi, half)
    values = [lo + k * ROTATION_STEP for k in range(int((hi - lo) / ROTATION_STEP + EPS) + 1)]
    return values + [hi] if abs(values[-1] - hi) > EPS else values


def _assign(doors: BarnDoors, frame, normals: Mapping[str, Vec3], rho: float):
    """`(tilt, {cut: leaf index})` of the best distinct leaves for the cuts at rotation `rho`, or None.
    The tilt of a plane against a leaf edge `q` is `n . q`: zero when the hinge side points along
    the plane normal."""
    names = list(normals)
    sides = []
    for k in range(doors.count):
        o, q, _ = _head_axes(doors.sides[k] + rho)
        sides.append((_world(frame, o), _world(frame, q)))
    best = None
    for leaves in permutations(range(doors.count), len(names)):
        if any(dot(normals[c], sides[k][0]) <= SIDE_MIN for c, k in zip(names, leaves)):
            continue
        err = sum(CUT_WEIGHTS[c] * dot(normals[c], sides[k][1]) ** 2 for c, k in zip(names, leaves))
        if best is None or err < best[0]:
            best = (err, dict(zip(names, leaves)))
    return best


def _best_rotation(doors: BarnDoors, frame, normals: Mapping[str, Vec3]):
    """`(rotation, {cut: leaf index})` with the least tilt of the tip edges against their planes (the
    smallest turn on a tie), or None when the cuts cannot all face a distinct leaf."""
    def better(err, rho, best):
        return best is None or err < best[0] - EPS or (abs(err - best[0]) <= EPS and abs(rho) < abs(best[1]))

    best = None
    for rho in _rotations(doors):
        fit = _assign(doors, frame, normals, rho)
        if fit is not None and better(fit[0], rho, best):
            best = (fit[0], rho, fit[1])
    if best is None:
        return None
    centre = best[1]
    for k in range(-int(ROTATION_STEP / FINE_STEP), int(ROTATION_STEP / FINE_STEP) + 1):
        rho = centre + k * FINE_STEP
        if doors.rotation.min - EPS <= rho <= doors.rotation.max + EPS:
            fit = _assign(doors, frame, normals, rho)
            if fit is not None and better(fit[0], rho, best):
                best = (fit[0], rho, fit[1])
    return best[1], best[2]


def auto_set(doors: BarnDoors, lens_offset: float, frame, lens: Vec3, field_angle: float,
             lines: Mapping[str, Line]) -> tuple[BarnDoorSet, tuple[str, ...]]:
    """Leaves closing on the target `lines` (cut name -> point and direction in the world), plus the
    names of the cuts that no leaf could take.

    A cut whose plane misses the field cone leaves its leaf open. The cuts left are given to
    distinct leaves facing them, the whole set turned to the rotation that tilts the tip edges the
    least against their planes; the angle puts the tip centre on the plane.
    """
    axis = frame[2]
    reach = math.sin(math.radians(field_angle / 2))
    normals: dict[str, tuple[float, Vec3]] = {}
    for name in CUT_NAMES:
        n = cut_normal(lens, lines[name], axis) if name in lines else None
        if n is not None and -dot(n, axis) < reach - EPS:
            normals[name] = (-dot(n, axis), n)
    kept = sorted(normals, key=lambda name: normals[name][0])
    dropped: list[str] = []
    fit = None
    while kept:
        fit = _best_rotation(doors, frame, {c: normals[c][1] for c in kept})
        if fit is not None:
            break
        dropped.append(kept.pop())
    rho, owner = fit if fit is not None else (min(max(0.0, doors.rotation.min), doors.rotation.max), {})
    placed = {}
    for cut, k in owner.items():
        o, _, _ = _head_axes(doors.sides[k] + rho)
        n, ow = normals[cut][1], _world(frame, o)
        point = _reference_point(lens, axis, lines[cut])
        v = None if point is None else sub(point, lens)
        if v is not None and dot(v, axis) > SIDE_MIN and dot(v, ow) > SIDE_MIN:
            theta, reached = _closing_angle(doors, dot(v, axis), dot(v, ow))
        else:
            theta, reached = _closing_angle(doors, dot(n, ow), -dot(n, axis))
        placed[k] = (cut, theta, reached)
    return _assemble(doors, lens_offset, frame, rho, placed), tuple(dropped)
