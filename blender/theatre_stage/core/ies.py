"""IES (LM-63, type C) photometry without bpy (spec 13.13): parser, lookups, zoom sets, fallback beam.

Angles are degrees, intensities candela. A profile is any object with
`intensity(theta, phi) -> cd`, `symmetric` (True: phi is ignored) and `support` (theta beyond
which the intensity is 0), so that the optimiser can cull probes outside the beam.
"""

from __future__ import annotations

import math
from bisect import bisect_right
from dataclasses import dataclass, field as dataclass_field
from functools import lru_cache
from pathlib import Path
from typing import Protocol, Sequence

LN2, LN10 = math.log(2.0), math.log(10.0)
# Intensity relative to the peak below which the fallback profile is cut off.
FALLBACK_CUTOFF = 1e-4
# Largest generalised-Gaussian exponent, hence the smallest field/beam ratio the fallback reproduces.
MAX_EXPONENT = 20.0
MIN_FIELD_RATIO = math.exp(math.log(LN10 / LN2) / MAX_EXPONENT)


class Profile(Protocol):
    @property
    def symmetric(self) -> bool: ...

    @property
    def support(self) -> float: ...

    def intensity(self, theta: float, phi: float = 0.0) -> float: ...


# ------------------------------------------------------------------- parser

@dataclass(frozen=True)
class IesTable:
    """Candela table: `candela[h][v]` at horizontal angle `horizontal[h]`, vertical `vertical[v]`.

    Intensities include the file multiplier; ballast factors are ignored, like `ies_axis_candela`.
    """

    vertical: tuple[float, ...]
    horizontal: tuple[float, ...]
    candela: tuple[tuple[float, ...], ...]
    _step: float = dataclass_field(default=0.0, init=False, repr=False, compare=False)

    @property
    def symmetric(self) -> bool:
        return len(self.horizontal) == 1

    @property
    def support(self) -> float:
        return self.vertical[-1]

    @property
    def axis_candela(self) -> float:
        """Intensity at theta 0 for the first horizontal plane."""
        return self.candela[0][0]

    def __post_init__(self):
        v = self.vertical
        step = (v[-1] - v[0]) / (len(v) - 1)
        uniform = all(abs(v[i] - v[0] - i * step) < 1e-9 for i in range(len(v)))
        object.__setattr__(self, "_step", step if uniform else 0.0)

    def intensity(self, theta: float, phi: float = 0.0) -> float:
        """Bilinear candela at `theta` from the axis and `phi` around it; 0 outside the table."""
        vertical = self.vertical
        first = vertical[0]
        if theta < first - 1e-9 or theta > vertical[-1]:
            return 0.0
        last = len(vertical) - 2
        step = self._step
        iv = int((theta - first) / step) if step else bisect_right(vertical, theta) - 1
        iv = last if iv > last else 0 if iv < 0 else iv
        v0 = vertical[iv]
        tv = (theta - v0) / (vertical[iv + 1] - v0)
        tv = 0.0 if tv < 0.0 else 1.0 if tv > 1.0 else tv
        if len(self.horizontal) == 1:
            row = self.candela[0]
            return row[iv] + tv * (row[iv + 1] - row[iv])
        horizontal = self.horizontal
        p = _fold(phi, horizontal[0], horizontal[-1])
        ih = min(max(bisect_right(horizontal, p) - 1, 0), len(horizontal) - 2)
        th = (p - horizontal[ih]) / (horizontal[ih + 1] - horizontal[ih])
        th = 0.0 if th < 0.0 else 1.0 if th > 1.0 else th
        a, b = self.candela[ih], self.candela[ih + 1]
        va = a[iv] + tv * (a[iv + 1] - a[iv])
        vb = b[iv] + tv * (b[iv + 1] - b[iv])
        return va + th * (vb - va)

    def flux(self) -> float:
        """Total lumens of the table, `sum I sin(theta) dtheta dphi` over the sphere."""
        total = 0.0
        planes = 1 if self.symmetric else 72
        for k in range(planes):
            phi = 360.0 * (k + 0.5) / planes
            ring = 0.0
            for i in range(len(self.vertical) - 1):
                t0, t1 = self.vertical[i], self.vertical[i + 1]
                mid = 0.5 * (t0 + t1)
                ring += self.intensity(mid, phi) * (math.cos(math.radians(t0)) - math.cos(math.radians(t1)))
            total += ring
        return total * 2 * math.pi / planes


def _fold(phi: float, first: float, last: float) -> float:
    """Horizontal angle brought back into the plane range the file stores (LM-63 symmetries)."""
    p = phi % 360.0
    if first == 0.0 and last == 90.0:
        p = 360.0 - p if p > 180.0 else p
        return 180.0 - p if p > 90.0 else p
    if first == 0.0 and last == 180.0:
        return 360.0 - p if p > 180.0 else p
    if first == 90.0 and last == 270.0:
        return 180.0 - p if p < 90.0 else 540.0 - p if p > 270.0 else p
    return min(max(p, first), last)


def parse_ies(text: str) -> IesTable:
    """Parse an LM-63 file (1995 or 2002, photometric type C) into a candela table.

    Raises `ValueError` (French message) for a file that is truncated, not type C or without TILT line.
    """
    _, found, body = text.partition("TILT=")
    if not found:
        raise ValueError("fichier IES sans ligne TILT")
    kind, _, rest = body.partition("\n")
    tokens = rest.split()
    try:
        if kind.strip().upper() == "INCLUDE":
            tokens = tokens[2 + 2 * int(float(tokens[1])):]
        multiplier, n_v, n_h, photometric = float(tokens[2]), int(tokens[3]), int(tokens[4]), int(tokens[5])
        if photometric != 1:
            raise ValueError("fichier IES : seule la photométrie de type C est prise en charge")
        if n_v < 2 or n_h < 1:
            raise ValueError("fichier IES : au moins deux angles verticaux requis")
        start = 13
        numbers = [float(t) for t in tokens[start:start + n_v + n_h + n_v * n_h]]
    except (IndexError, ValueError) as error:
        if isinstance(error, ValueError) and "IES" in str(error):
            raise
        raise ValueError("fichier IES illisible") from error
    if len(numbers) != n_v + n_h + n_v * n_h:
        raise ValueError("fichier IES tronqué")
    vertical = tuple(numbers[:n_v])
    horizontal = tuple(numbers[n_v:n_v + n_h])
    grid = numbers[n_v + n_h:]
    if any(b <= a for a, b in zip(vertical, vertical[1:])) or any(b <= a for a, b in zip(horizontal, horizontal[1:])):
        raise ValueError("fichier IES : angles non croissants")
    rows = tuple(tuple(c * multiplier for c in grid[h * n_v:(h + 1) * n_v]) for h in range(n_h))
    return IesTable(vertical, horizontal, rows)


def load_ies(path: str | Path) -> IesTable:
    """`parse_ies` of the file at `path` (latin-1: manufacturers' headers are not always UTF-8)."""
    return parse_ies(Path(path).read_text(encoding="latin-1"))


# ------------------------------------------------------------------- zoom

@dataclass(frozen=True)
class _Blend:
    """A zoom position: up to two tables, each warped so its 10 % edge falls on the current field."""

    parts: tuple[tuple[IesTable, float, float], ...]  # (table, angle scale, weight x scale squared)
    support: float
    symmetric: bool

    def intensity(self, theta: float, phi: float = 0.0) -> float:
        total = 0.0
        for table, k, weight in self.parts:
            total += weight * table.intensity(theta * k, phi)
        return total


@dataclass(frozen=True)
class ZoomSet:
    """IES tables by field angle (degrees, ascending), as the `optics.ies` list of a fiche."""

    profiles: tuple[tuple[float, IesTable], ...]

    def __post_init__(self):
        if not self.profiles:
            raise ValueError("jeu de profils IES vide")
        fields = [f for f, _ in self.profiles]
        if any(b <= a for a, b in zip(fields, fields[1:])):
            raise ValueError("profils IES : champs non croissants")

    @classmethod
    def of(cls, profiles: Sequence[tuple[float, IesTable]]) -> ZoomSet:
        return cls(tuple(sorted(profiles, key=lambda item: item[0])))

    def at(self, field: float) -> Profile:
        """Profile at full-angle field `field`: the two nearest tables, angles scaled onto `field`.

        Table `k` is read at `theta * F_k / field` and weighted by `(F_k / field)^2` so that an
        intermediate zoom keeps the flux of its neighbours instead of showing two beams.
        Outside the stored range the end table is scaled alone.
        """
        fields = [f for f, _ in self.profiles]
        if field <= fields[0] or len(fields) == 1:
            picks = [(0, 1.0)]
        elif field >= fields[-1]:
            picks = [(len(fields) - 1, 1.0)]
        else:
            hi = bisect_right(fields, field)
            lo = hi - 1
            t = (field - fields[lo]) / (fields[hi] - fields[lo])
            picks = [(lo, 1.0 - t), (hi, t)]
        parts = []
        for index, weight in picks:
            f_k, table = self.profiles[index]
            k = f_k / field
            parts.append((table, k, weight * k * k))
        support = max(table.support / k for table, k, _ in parts)
        return _Blend(tuple(parts), support, all(t.symmetric for t, _, _ in parts))


# ---------------------------------------------------------------- fallback

@dataclass(frozen=True)
class GeneralisedGaussian:
    """Rotationally symmetric `I0 * exp(-ln2 * (theta / half_beam)^k)`: 50 % at the beam edge, 10 % at the field edge."""

    peak: float
    half_beam: float
    exponent: float
    support: float
    symmetric: bool = True

    def intensity(self, theta: float, phi: float = 0.0) -> float:
        if theta <= 0.0:
            return self.peak
        if theta > self.support:
            return 0.0
        x = self.exponent * math.log(theta / self.half_beam)
        return self.peak * math.exp(-LN2 * math.exp(x)) if x < 5.0 else 0.0


@lru_cache(maxsize=4096)
def fallback_profile(beam: float, field: float, flux: float) -> GeneralisedGaussian:
    """Generalised Gaussian through the 50 % (`beam`) and 10 % (`field`) full angles, `flux` lumens in total.

    `field` is raised to `MIN_FIELD_RATIO * beam` (1.06) when closer: a top-hat is out of reach.
    """
    if beam <= 0.0 or field <= 0.0:
        raise ValueError("angles de faisceau et de champ positifs requis")
    half_beam = beam / 2.0
    half_field = max(field, beam * MIN_FIELD_RATIO) / 2.0
    exponent = min(math.log(LN10 / LN2) / math.log(half_field / half_beam), MAX_EXPONENT)
    reach = min(half_beam * (math.log(1.0 / FALLBACK_CUTOFF) / LN2) ** (1.0 / exponent), 180.0)
    shape = GeneralisedGaussian(1.0, half_beam, exponent, reach)
    steps = 240
    area = 0.0
    for i in range(steps):
        t0, t1 = reach * i / steps, reach * (i + 1) / steps
        mid = 0.5 * (t0 + t1)
        area += shape.intensity(mid) * (math.cos(math.radians(t0)) - math.cos(math.radians(t1)))
    solid = 2.0 * math.pi * area
    return GeneralisedGaussian(flux / solid if solid > 0.0 else 0.0, half_beam, exponent, reach)


@dataclass(frozen=True)
class Photometry:
    """What an emitter radiates at full level: IES `profiles` per zoom, else the fallback on `flux`."""

    flux: float
    profiles: ZoomSet | None = None

    def profile(self, field: float, beam: float) -> Profile:
        """Profile at the current zoom; `beam` (50 % angle at `field`) is used by the fallback only."""
        if self.profiles is not None:
            return self.profiles.at(field)
        return fallback_profile(round(beam, 3), round(field, 3), self.flux)
