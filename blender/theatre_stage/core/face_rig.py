"""Face equalisation applied to the rig (spec 13.13): `RigFixture` to `Emitter`, the signature of the
inputs, and the stored result that `compute_layout` reads back.

Pure Python. A stored result holds only while its signature matches the plain rig it was computed from.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache

from .face_eq import Adjustment, Bounds, CutEdge, Emitter, Probe, Result, Stats, Vec3, equalise, face_grid
from .fixtures import Fixture, Library, Optics
from .ies import IesTable, Photometry, ZoomSet, load_ies
from .rig import Rig, RigFixture, aim_angles, head_frame
from .vecmath import cross as _cross

FAMILY = "front_pc"
VERSION = 3
USEFUL_MARGIN = 0.30
DIGITS = 4
_ROW = re.compile(r"Row(\d+)")


# ------------------------------------------------------------------ adapter

@lru_cache(maxsize=64)
def _table(path: str) -> IesTable:
    return load_ies(path)


def _optics(fx: Fixture) -> Optics:
    if fx.optics is None:
        raise ValueError(f"Fiche « {fx.id} » sans optique.")
    return fx.optics


def _field(f: RigFixture) -> float:
    if f.field_angle is None:
        raise ValueError(f"{f.name} : champ inconnu.")
    return f.field_angle


def _vec3(v) -> Vec3:
    return (v[0], v[1], v[2])


def photometry_of(fx: Fixture, f: RigFixture) -> Photometry:
    """IES profiles of the fiche by field angle; the fallback profile when a file is missing or unreadable."""
    optics, field = _optics(fx), _field(f)
    tube = next((t for t in optics.lens_tubes if t.name == f.tube), None)
    if tube is not None and tube.ies:
        found = [(tube.field_angle, tube.ies)]
    else:
        found = [(field if q.field_angle is None else q.field_angle, q.file) for q in optics.ies]
    try:
        return Photometry(optics.flux, ZoomSet.of([(angle, _table(str(fx.path(name)))) for angle, name in found])
                          if found else None)
    except (OSError, ValueError):
        return Photometry(optics.flux)


def _beam_table(optics: Optics, f: RigFixture) -> tuple[tuple[float, float], ...]:
    fields, beams = optics.field_angle, optics.beam_angle
    if fields is not None and beams is not None and fields.max > fields.min:
        return ((fields.min, beams.min), (fields.max, beams.max))
    field = _field(f)
    return ((field, field if f.beam_angle is None else f.beam_angle),)


def _zoom_range(fx: Fixture, f: RigFixture) -> tuple[float, float]:
    """The zoom of the fiche, held at the current field when the mode has no `zoom` channel."""
    zoom, field = _optics(fx).field_angle, _field(f)
    if zoom is None or fx.mode(f.mode).channel("zoom") is None:
        return (field, field)
    return (zoom.min, zoom.max)


def _cut_edges(f: RigFixture, lens: Vec3) -> tuple[CutEdge, ...]:
    """Free edge of every leaf, open ones included, in the world with the lit-side normal of the plane
    through the lens centre and the edge (a leaf is a half-plane for a probe, spec 13.13)."""
    doors = f.barn_doors
    if doors is None or f.pan is None or f.tilt is None:
        return ()
    frame = head_frame(f.pan, f.tilt)

    def world(v) -> Vec3:
        return _vec3([v[0] * frame[0][i] + v[1] * frame[1][i] + v[2] * frame[2][i] for i in range(3)])

    out = []
    for leaf in doors.leaves:
        reach = _vec3([h + doors.length * z for h, z in zip(leaf.hinge, leaf.axes[2])])
        tip = _vec3([p + w for p, w in zip(f.pivot, world(reach))])
        direction = world(leaf.axes[0])
        normal = _cross(_vec3([t - c for t, c in zip(tip, lens)]), direction)
        size = math.sqrt(sum(c * c for c in normal))
        if size < 1e-9:
            continue
        side = world((math.cos(math.radians(leaf.side)), math.sin(math.radians(leaf.side)), 0.0))
        sign = -1.0 if sum(n * s for n, s in zip(normal, side)) > 0.0 else 1.0
        out.append(CutEdge(tip, direction, _vec3([sign * c / size for c in normal])))
    return tuple(out)


def emitter_of(f: RigFixture, fx: Fixture) -> Emitter:
    """The face PC `f` as the equaliser sees it; barn door leaves become cut edges."""
    optics = _optics(fx)
    tube = next((t for t in optics.lens_tubes if t.name == f.tube), None)
    lens = _vec3([p + a * optics.lens_offset for p, a in zip(f.pivot, f.axis)])
    row = _ROW.search(f.circuit or "")
    return Emitter(
        name=f.name, direction=f.name.split("_")[1], row=int(row.group(1)) - 1 if row else 0,
        source=f.source, axis=f.axis, up=head_frame(*aim_angles(f.axis))[0],
        zoom_field=_field(f), zoom_range=_zoom_range(fx, f), beam_of_field=_beam_table(optics, f),
        photometry=photometry_of(fx, f), aim_z=f.aim[2], cut_edges=_cut_edges(f, lens),
        lens_radius=optics.aperture(tube) / 2)


def emitters_of(rig: Rig, library: Library) -> tuple[Emitter, ...]:
    out = []
    for f in rig.by_family(FAMILY):
        fx = library.get(f.fixture_id)
        if fx is not None and fx.optics is not None and f.field_angle is not None:
            out.append(emitter_of(f, fx))
    return tuple(out)


# ---------------------------------------------------------------- signature

def _r(value: float, digits: int = DIGITS) -> float:
    return round(value, digits) + 0.0


def _vec(v) -> list[float]:
    return [_r(c) for c in v]


def _doors(f: RigFixture) -> list | None:
    doors = f.barn_doors
    if doors is None:
        return None
    return [_r(doors.rotation), [[leaf.index, leaf.cut, _r(leaf.angle), None if leaf.normal is None else _vec(leaf.normal)]
                                 for leaf in doors.leaves]]


def signature(rig: Rig, min_mean_ratio: float) -> str:
    """Digest of everything the equalisation reads: face PC hang points, fiches, modes, aims, fields,
    barn doors, zones, the measuring plane and the mean floor. Levels and colours are not in it."""
    pcs = [[f.name, f.fixture_id, f.mode, f.support, _vec(f.hang), _vec(f.axis), f.field_angle and _r(f.field_angle),
            f.tube, _doors(f)] for f in rig.by_family(FAMILY)]
    zones, face = rig.zones, rig.face
    parts = [VERSION, _r(min_mean_ratio), pcs,
             None if zones is None else [zones.nx, zones.nr, _r(zones.width), _r(zones.depth)],
             None if face is None else [_r(face.nose_width), _r(face.frame_width), _r(face.forestage_depth),
                                        _r(face.area_depth), _r(face.z), _r(face.z_torso)]]
    return hashlib.sha1(json.dumps(parts, separators=(",", ":")).encode()).hexdigest()[:16]


# ------------------------------------------------------------ stored result

@dataclass(frozen=True)
class FaceEq:
    """A stored equalisation: its inputs' `signature`, `date` (ISO), the per-PC adjustments and the statistics.

    `before` and `after` map `L`, `R` and `sum` to `Stats`; `mean_ratio` is the mean after over the mean at full.
    """

    signature: str
    date: str
    min_mean_ratio: float
    adjustments: tuple[Adjustment, ...]
    before: Mapping[str, Stats]
    after: Mapping[str, Stats]
    mean_ratio: Mapping[str, float]
    mean_level: float
    evaluations: int
    seconds: float

    def by_name(self) -> dict[str, Adjustment]:
        return {a.name: a for a in self.adjustments}

    def to_json(self) -> str:
        data = {
            "version": VERSION, "signature": self.signature, "date": self.date,
            "min_mean_ratio": self.min_mean_ratio,
            "adjustments": [{"name": a.name, "aim_offset": list(a.aim_offset), "zoom_field": a.zoom_field,
                             "level": a.level, "axis": list(a.axis), "aim": list(a.aim)} for a in self.adjustments],
            "before": {k: vars(v) for k, v in self.before.items()},
            "after": {k: vars(v) for k, v in self.after.items()},
            "mean_ratio": dict(self.mean_ratio), "mean_level": self.mean_level,
            "evaluations": self.evaluations, "seconds": self.seconds,
        }
        return json.dumps(data, separators=(",", ":"))

    @classmethod
    def from_json(cls, text: str | None) -> FaceEq | None:
        """The stored result, or None when `text` is absent, malformed or of another version."""
        if not text:
            return None
        try:
            d = json.loads(text)
            if d["version"] != VERSION:
                return None
            adjustments = tuple(Adjustment(a["name"], tuple(a["aim_offset"]), a["zoom_field"], a["level"],
                                           tuple(a["axis"]), tuple(a["aim"])) for a in d["adjustments"])
            return cls(d["signature"], d["date"], d["min_mean_ratio"], adjustments,
                       {k: Stats(**v) for k, v in d["before"].items()}, {k: Stats(**v) for k, v in d["after"].items()},
                       d["mean_ratio"], d["mean_level"], d["evaluations"], d["seconds"])
        except (ValueError, KeyError, TypeError):
            return None

    def matches(self, rig: Rig, min_mean_ratio: float) -> bool:
        """True while the rig is the one this result was computed for."""
        return self.signature == signature(rig, min_mean_ratio)


def probes_of(rig: Rig) -> tuple[Probe, ...]:
    """The useful grid at head and torso height: probes `USEFUL_MARGIN` inside the intended cuts (spec 13.13)."""
    face = rig.face
    if face is None:
        return ()
    return tuple(p for z in (face.z, face.z_torso) for p in face_grid(
        nose_width=face.nose_width, frame_width=face.frame_width, forestage_depth=face.forestage_depth,
        area_depth=face.area_depth, z=z, margin=USEFUL_MARGIN))


def equalise_rig(rig: Rig, library: Library, min_mean_ratio: float, now: datetime | None = None) -> FaceEq:
    """Run the engine on the face PCs of a plain (unadjusted) rig and package the result for storage."""
    emitters = emitters_of(rig, library)
    if not emitters or rig.face is None or rig.zones is None:
        raise ValueError("Égalisation impossible : aucun PC de face dans l'implantation.")
    probes = probes_of(rig)
    bounds = Bounds.for_zone(rig.zones.width, rig.zones.depth, min_mean_ratio=min_mean_ratio)
    result: Result = equalise(emitters, probes, bounds)
    stamp = (now or datetime.now()).isoformat(timespec="seconds")
    return FaceEq(signature(rig, min_mean_ratio), stamp, min_mean_ratio, result.adjustments, dict(result.before),
                  dict(result.after), dict(result.mean_ratio), result.mean_level, result.evaluations, result.seconds)
