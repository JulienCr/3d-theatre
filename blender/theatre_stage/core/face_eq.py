"""Face equalisation (spec 13.13): photometry of the face PCs on a grid of virtual faces, and the
optimiser that sets each PC's aim offset, zoom and level for the most even light.

Independent of the rig: the caller builds `Emitter` and `Probe` values from its own data.
Metres, degrees, lux. World frame of the spec: +X cour, +Y upstage, +Z up; the audience is at -Y.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from operator import mul
from typing import Callable, Mapping, Sequence

from .ies import Photometry, Profile

Vec3 = tuple[float, float, float]
AUDIENCE: Vec3 = (0.0, -1.0, 0.0)
DIRECTIONS = ("L", "R")
STEP_SCALE_MIN = 1.0 / 16
FLOOR_PENALTY = 1000.0


# ------------------------------------------------------------------- inputs

@dataclass(frozen=True)
class Probe:
    """A virtual face: `position` and unit `normal` (toward the audience by default)."""

    position: Vec3
    normal: Vec3 = AUDIENCE


@dataclass(frozen=True)
class CutEdge:
    """Free edge of a barn door leaf: a point `tip` on the edge line, its unit `direction`, and `normal`,
    the unit normal toward the lit side of the plane through the lens centre and the edge."""

    tip: Vec3
    direction: Vec3
    normal: Vec3


@dataclass(frozen=True)
class Emitter:
    """One face PC as the equaliser sees it, at its current setting.

    `axis`: unit beam axis. `up`: unit vector perpendicular to it, the head's reference for the IES
    phi (phi grows by the right-hand rule about `axis`). `zoom_field`/`zoom_range`: 10 % full angle.
    `beam_of_field`: 50 % angle at a field, a callable or `((field, beam), ...)` ascending; read by the
    fallback profile only. `cut_planes`: `(point, normal)` through the lens centre, normal toward the
    lit side; a probe behind any plane gets 0. `aim_z`: height of the plane where aim offsets apply
    (None: the plane of the probes). `cut_edges`: leaf edges; a probe sees the part of the lens disc of
    `lens_radius` they leave open (penumbra; radius 0 gives a sharp plane).
    """

    name: str
    direction: str
    row: int
    source: Vec3
    axis: Vec3
    up: Vec3
    zoom_field: float
    zoom_range: tuple[float, float]
    beam_of_field: Callable[[float], float] | tuple[tuple[float, float], ...]
    photometry: Photometry
    level: float = 1.0
    cut_planes: tuple[tuple[Vec3, Vec3], ...] = ()
    aim_z: float | None = None
    cut_edges: tuple[CutEdge, ...] = ()
    lens_radius: float = 0.0

    def beam_at(self, field: float) -> float:
        """50 % angle at `field`; a table is read linearly and held at its ends."""
        table = self.beam_of_field
        if callable(table):
            return table(field)
        if field <= table[0][0]:
            return table[0][1]
        for (f0, b0), (f1, b1) in zip(table, table[1:]):
            if field <= f1:
                return b0 + (b1 - b0) * (field - f0) / (f1 - f0)
        return table[-1][1]


@dataclass(frozen=True)
class Bounds:
    """Limits of the levers and of the search.

    `aim_dx`, `aim_dy`: largest aim offset in X and Y, metres. `min_mean_ratio`: share of the mean
    illuminance of the rig at full that each direction and the sum must keep (a steep penalty, not a
    wall). `mean_weight`: pull of the objective toward a high mean. `max_evaluations`: bound of the
    search, in recomputations of one emitter's illuminance (about 2100 on the default rig).
    """

    aim_dx: float = 0.5
    aim_dy: float = 0.5
    level_min: float = 0.0
    level_max: float = 1.0
    min_mean_ratio: float = 0.85
    mean_weight: float = 0.5
    max_evaluations: int = 3000

    @classmethod
    def for_zone(cls, zone_width: float, zone_depth: float, fraction: float = 0.25, **options) -> Bounds:
        """Aim within `fraction` of a zone (a quarter by default) on each side."""
        return cls(zone_width * fraction, zone_depth * fraction, **options)


def face_grid(*, nose_width: float, frame_width: float, forestage_depth: float, area_depth: float,
              z: float, pitch: float = 0.5) -> tuple[Probe, ...]:
    """Cell-centred probes at height `z` over the acting area, rows ordered from the nose upstage.

    A row whose centre is in the forestage (`Y < forestage_depth`) spans `nose_width`, the others
    `frame_width`; both centred on X = 0.
    """
    rows = max(1, round(area_depth / pitch))
    probes = []
    for j in range(rows):
        y = (j + 0.5) * area_depth / rows
        width = nose_width if y < forestage_depth else frame_width
        cols = max(1, round(width / pitch))
        probes.extend(Probe((-width / 2 + (i + 0.5) * width / cols, y, z)) for i in range(cols))
    return tuple(probes)


# ------------------------------------------------------------------ vectors

def _dot(a: Vec3, b: Vec3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a: Vec3, b: Vec3) -> Vec3:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _unit(v: Vec3) -> Vec3:
    n = math.sqrt(_dot(v, v))
    return (v[0] / n, v[1] / n, v[2] / n)


def _orthogonal(v: Vec3, axis: Vec3) -> Vec3:
    """`v` made perpendicular to the unit `axis`, then unit."""
    d = _dot(v, axis)
    return _unit((v[0] - d * axis[0], v[1] - d * axis[1], v[2] - d * axis[2]))


def _posed(em: Emitter, dx: float, dy: float, aim_z: float) -> tuple[Vec3, Vec3]:
    """Axis and `up` after moving the aim point by `(dx, dy)` in the plane `aim_z`; `up` follows the head."""
    a0 = _unit(em.axis)
    up0 = _orthogonal(em.up, a0)
    if (dx == 0.0 and dy == 0.0) or abs(a0[2]) < 1e-6:
        return a0, up0
    t = (aim_z - em.source[2]) / a0[2]
    target = (em.source[0] + t * a0[0] + dx, em.source[1] + t * a0[1] + dy, aim_z)
    a1 = _unit((target[0] - em.source[0], target[1] - em.source[1], target[2] - em.source[2]))
    v, c = _cross(a0, a1), _dot(a0, a1)
    k = 1.0 / (1.0 + c)
    vu, vxu = _dot(v, up0), _cross(v, up0)
    up1 = (up0[0] * c + vxu[0] + v[0] * vu * k, up0[1] * c + vxu[1] + v[1] * vu * k,
           up0[2] * c + vxu[2] + v[2] * vu * k)
    return a1, _orthogonal(up1, a1)


def _aim_point(em: Emitter, axis: Vec3, aim_z: float) -> Vec3:
    """Where the axis from the source crosses the plane `aim_z` (the source itself for a level axis)."""
    if abs(axis[2]) < 1e-6:
        return em.source
    t = (aim_z - em.source[2]) / axis[2]
    return (em.source[0] + t * axis[0], em.source[1] + t * axis[1], aim_z)


# ------------------------------------------------------------- illuminance

def _edge_visibility(em: Emitter, edge: CutEdge, u: Vec3) -> float:
    """Share of the lens disc a probe in direction `u` sees past a leaf edge (half-plane through the edge line).

    The disc point `delta` sees the probe when it is on the lit side of the plane through the edge
    parallel to `u`: `n_u . delta >= n_u . (tip - source)`. The visible part is a disc segment.
    """
    normal = _cross(edge.direction, u)
    length = math.sqrt(_dot(normal, normal))
    if length < 1e-9:
        return 1.0 if _dot(edge.normal, u) >= 0.0 else 0.0
    normal = (normal[0] / length, normal[1] / length, normal[2] / length)
    if _dot(normal, edge.normal) < 0.0:
        normal = (-normal[0], -normal[1], -normal[2])
    offset = _dot(normal, (edge.tip[0] - em.source[0], edge.tip[1] - em.source[1], edge.tip[2] - em.source[2]))
    axis = _unit(em.axis)
    in_disc = math.sqrt(max(0.0, 1.0 - _dot(normal, axis) ** 2))
    if em.lens_radius <= 0.0 or in_disc < 1e-9:
        return 1.0 if offset <= 0.0 else 0.0
    x = offset / (in_disc * em.lens_radius)
    if x >= 1.0:
        return 0.0
    if x <= -1.0:
        return 1.0
    return (math.acos(x) - x * math.sqrt(1.0 - x * x)) / math.pi


def _probe_geometry(em: Emitter, probe: Probe) -> tuple[float, float, float, float] | None:
    """Unit direction source to probe and `max(0, s.n) / d^2`; None when the probe gets no light."""
    sx, sy, sz = em.source
    px, py, pz = probe.position
    vx, vy, vz = px - sx, py - sy, pz - sz
    d2 = vx * vx + vy * vy + vz * vz
    if d2 < 1e-12:
        return None
    d = math.sqrt(d2)
    cosine = -(vx * probe.normal[0] + vy * probe.normal[1] + vz * probe.normal[2]) / d
    if cosine <= 0.0:
        return None
    for point, normal in em.cut_planes:
        if (px - point[0]) * normal[0] + (py - point[1]) * normal[1] + (pz - point[2]) * normal[2] < 0.0:
            return None
    seen = 1.0
    for edge in em.cut_edges:
        seen *= _edge_visibility(em, edge, (vx / d, vy / d, vz / d))
        if seen <= 0.0:
            return None
    return vx / d, vy / d, vz / d, cosine / d2 * seen


def _fill(geometry, count: int, profile: Profile, axis: Vec3, up: Vec3) -> list[float]:
    """Illuminance of every probe at level 1: `geometry` is the active `(index, dx, dy, dz, g)` list."""
    out = [0.0] * count
    ax, ay, az = axis
    cut = math.cos(math.radians(min(profile.support, 180.0)))
    symmetric, intensity = profile.symmetric, profile.intensity
    bx, by, bz = _cross(axis, up)
    for i, dx, dy, dz, g in geometry:
        c = dx * ax + dy * ay + dz * az
        if c <= cut:
            continue
        theta = math.degrees(math.acos(min(c, 1.0)))
        if symmetric:
            out[i] = intensity(theta) * g
            continue
        px, py, pz = dx - c * ax, dy - c * ay, dz - c * az
        phi = math.degrees(math.atan2(px * bx + py * by + pz * bz, px * up[0] + py * up[1] + pz * up[2]))
        out[i] = intensity(theta, phi) * g
    return out


def illuminance(emitter: Emitter, probe: Probe, *, field: float | None = None, level: float | None = None,
                axis: Vec3 | None = None, up: Vec3 | None = None) -> float:
    """Lux on `probe`: `level * I(theta, phi) * max(0, s.n) / d^2`, `s` toward the source.

    The keyword arguments replace the emitter's own zoom, level, axis and `up`.
    """
    found = _probe_geometry(emitter, probe)
    if found is None:
        return 0.0
    field = emitter.zoom_field if field is None else field
    axis = _unit(emitter.axis) if axis is None else axis
    up = _orthogonal(emitter.up if up is None else up, axis)
    profile = emitter.photometry.profile(field, emitter.beam_at(field))
    lux = _fill([(0, *found)], 1, profile, axis, up)[0]
    return lux * (emitter.level if level is None else level)


# ------------------------------------------------------------------- stats

@dataclass(frozen=True)
class Stats:
    """`uniformity` is `minimum / mean` (U), `cv` the coefficient of variation (standard deviation / mean)."""

    mean: float
    minimum: float
    maximum: float
    uniformity: float
    cv: float


def statistics(values: Sequence[float]) -> Stats:
    n = len(values)
    mean = sum(values) / n
    if mean <= 0.0:
        return Stats(0.0, 0.0, 0.0, 0.0, 0.0)
    variance = max(sum(map(mul, values, values)) / n - mean * mean, 0.0)
    low = min(values)
    return Stats(mean, low, max(values), low / mean, math.sqrt(variance) / mean)


@dataclass(frozen=True)
class Adjustment:
    """The three levers of one emitter, and the aim they give: `aim` is on the plane `aim_z`."""

    name: str
    aim_offset: tuple[float, float]
    zoom_field: float
    level: float
    axis: Vec3
    aim: Vec3


@dataclass(frozen=True)
class Result:
    """Outcome of `equalise`. Groups are the directions present (`L`, `R`) and `sum`.

    `mean_ratio`: mean illuminance after, over the mean of the rig at full with the starting aim and zoom.
    `darkest_*`: the three weakest probes `(position, lux)` of each group.
    """

    adjustments: tuple[Adjustment, ...]
    before: Mapping[str, Stats]
    after: Mapping[str, Stats]
    mean_ratio: Mapping[str, float]
    darkest_before: Mapping[str, tuple[tuple[Vec3, float], ...]]
    darkest_after: Mapping[str, tuple[tuple[Vec3, float], ...]]
    mean_level: float
    evaluations: int
    seconds: float


def _groups(by_direction: Mapping[str, list[float]]) -> dict[str, list[float]]:
    groups = dict(by_direction)
    if len(groups) > 1:
        groups["sum"] = [a + b for a, b in zip(*groups.values())]
    else:
        groups["sum"] = next(iter(groups.values()))
    return groups


def _darkest(vector: Sequence[float], probes: Sequence[Probe], count: int = 3):
    order = sorted(range(len(vector)), key=lambda i: (vector[i], i))[:count]
    return tuple((probes[i].position, vector[i]) for i in order)


# --------------------------------------------------------------- optimiser

class _Search:
    """Pattern search over `(dx, dy, field, level)` of every emitter, one coordinate at a time."""

    def __init__(self, emitters: Sequence[Emitter], probes: Sequence[Probe], bounds: Bounds):
        self.emitters, self.probes, self.bounds = emitters, probes, bounds
        self.count = len(probes)
        self.aim_z = [probes[0].position[2] if em.aim_z is None else em.aim_z for em in emitters]
        self.geometry = []
        for em in emitters:
            active = []
            for i, probe in enumerate(probes):
                found = _probe_geometry(em, probe)
                if found is not None:
                    active.append((i, *found))
            self.geometry.append(active)
        self.limits = [(bounds.aim_dx if abs(em.axis[2]) >= 1e-6 else 0.0,
                        bounds.aim_dy if abs(em.axis[2]) >= 1e-6 else 0.0) for em in emitters]
        self.params = [[0.0, 0.0, em.zoom_field, min(max(em.level, bounds.level_min), bounds.level_max)]
                       for em in emitters]
        self.evaluations = 0
        self.units = [self.unit(k, p) for k, p in enumerate(self.params)]
        self.base_mean = {name: sum(vec) / self.count for name, vec in self.group_vectors(full=True).items()}

    def unit(self, k: int, p: Sequence[float]) -> list[float]:
        """Illuminance of emitter `k` at level 1 for the aim offset and zoom of `p`."""
        self.evaluations += 1
        em = self.emitters[k]
        axis, up = _posed(em, p[0], p[1], self.aim_z[k])
        profile = em.photometry.profile(p[2], em.beam_at(p[2]))
        return _fill(self.geometry[k], self.count, profile, axis, up)

    def group_vectors(self, full: bool = False) -> dict[str, list[float]]:
        sums = {d: [0.0] * self.count for d in DIRECTIONS if any(e.direction == d for e in self.emitters)}
        for k, em in enumerate(self.emitters):
            level = 1.0 if full else self.params[k][3]
            sums[em.direction] = [s + level * u for s, u in zip(sums[em.direction], self.units[k])]
        return _groups(sums)

    def loss(self, groups: Mapping[str, Sequence[float]]) -> float:
        """Sum over groups of `(1 - U) + CV - mean_weight * mean_ratio`, plus a steep ramp under the mean floor."""
        total = 0.0
        for name, vec in groups.items():
            s = statistics(vec)
            ratio = s.mean / self.base_mean[name] if self.base_mean[name] > 0.0 else 1.0
            total += (1.0 - s.uniformity) + s.cv - self.bounds.mean_weight * ratio
            total += FLOOR_PENALTY * max(0.0, self.bounds.min_mean_ratio - ratio)
        return total

    def trial(self, k: int, index: int, value: float, vectors: Mapping[str, list[float]]):
        """`(loss, unit, group vectors)` with parameter `index` of emitter `k` set to `value`."""
        p = list(self.params[k])
        p[index] = value
        unit = self.units[k] if index == 3 else self.unit(k, p)
        em = self.emitters[k]
        level = self.params[k][3]
        old = [level * u for u in self.units[k]]
        new = [p[3] * u for u in unit]
        by_direction = {d: v for d, v in vectors.items() if d in DIRECTIONS}
        by_direction[em.direction] = [g - a + b for g, a, b in zip(by_direction[em.direction], old, new)]
        groups = _groups(by_direction)
        return self.loss(groups), unit, groups

    def run(self) -> float:
        """Descend from the current setting; returns the final loss."""
        b = self.bounds
        zoom_span = [em.zoom_range[1] - em.zoom_range[0] for em in self.emitters]
        vectors = self.group_vectors()
        best = self.loss(vectors)
        scale = 1.0
        while scale >= STEP_SCALE_MIN and self.evaluations < b.max_evaluations:
            improved = False
            for k, em in enumerate(self.emitters):
                steps = (self.limits[k][0] * 0.5, self.limits[k][1] * 0.5, zoom_span[k] * 0.25,
                         (b.level_max - b.level_min) * 0.25)
                lows = (-self.limits[k][0], -self.limits[k][1], em.zoom_range[0], b.level_min)
                highs = (self.limits[k][0], self.limits[k][1], em.zoom_range[1], b.level_max)
                for index in (0, 1, 2, 3):
                    step = steps[index] * scale
                    if step <= 0.0:
                        continue
                    for sign in (1.0, -1.0):
                        value = min(max(self.params[k][index] + sign * step, lows[index]), highs[index])
                        if value == self.params[k][index]:
                            continue
                        loss, unit, groups = self.trial(k, index, value, vectors)
                        if loss < best - 1e-12:
                            best, vectors, improved = loss, groups, True
                            self.params[k][index], self.units[k] = value, unit
                            break
                if self.evaluations >= b.max_evaluations:
                    break
            if not improved:
                scale /= 2.0
        return best


def equalise(emitters: Sequence[Emitter], probes: Sequence[Probe], bounds: Bounds | None = None) -> Result:
    """Aim offset, zoom and level of every emitter for the most even face light.

    Deterministic. Minimises, for each direction present and for their sum, `(1 - U) + CV`, minus
    `mean_weight` times the mean relative to the rig at full, under the `min_mean_ratio` floor, by pattern
    search from the given setting. Levels stay in `[level_min, level_max]` (at most 1), the zoom in each
    `zoom_range`.
    """
    if not emitters or not probes:
        raise ValueError("égalisation : aucun appareil ou aucun point de mesure")
    if any(e.direction not in DIRECTIONS for e in emitters):
        raise ValueError("égalisation : direction `L` ou `R` attendue")
    started = time.perf_counter()
    search = _Search(emitters, probes, bounds or Bounds())
    before = search.group_vectors()
    search.run()
    after = search.group_vectors()
    adjustments = []
    for k, em in enumerate(emitters):
        dx, dy, field, level = search.params[k]
        axis, _ = _posed(em, dx, dy, search.aim_z[k])
        adjustments.append(Adjustment(em.name, (dx, dy), field, level, axis, _aim_point(em, axis, search.aim_z[k])))
    return Result(
        tuple(adjustments),
        {n: statistics(v) for n, v in before.items()},
        {n: statistics(v) for n, v in after.items()},
        {n: statistics(v).mean / search.base_mean[n] if search.base_mean[n] > 0.0 else 1.0
         for n, v in after.items()},
        {n: _darkest(v, probes) for n, v in before.items()},
        {n: _darkest(v, probes) for n, v in after.items()},
        sum(p[3] for p in search.params) / len(emitters),
        search.evaluations,
        time.perf_counter() - started,
    )


def evaluate(emitters: Sequence[Emitter], probes: Sequence[Probe]) -> dict[str, Stats]:
    """Statistics per direction and for the sum of the emitters as they stand, without optimising."""
    sums: dict[str, list[float]] = {}
    for em in emitters:
        axis = _unit(em.axis)
        up = _orthogonal(em.up, axis)
        profile = em.photometry.profile(em.zoom_field, em.beam_at(em.zoom_field))
        geometry = [(i, *found) for i, p in enumerate(probes) if (found := _probe_geometry(em, p))]
        unit = _fill(geometry, len(probes), profile, axis, up)
        previous = sums.get(em.direction, [0.0] * len(probes))
        sums[em.direction] = [a + em.level * u for a, u in zip(previous, unit)]
    return {name: statistics(vec) for name, vec in _groups(sums).items()}
