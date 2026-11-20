"""Lighting rig: hang points, aims, fields, blades, pan/tilt, DMX patch and rest values.

Spec sections 13 and 15, in pure Python. `compute_rig` is the single entry point;
the builder only translates its result and recomputes nothing. Angles are in
degrees in the records, lengths in metres, 3-vectors are `(x, y, z)` tuples.
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass, field, replace
from functools import lru_cache
from collections.abc import Mapping

from .barndoors import BarnDoorSet, auto_set, cut_normal, envelope_points, manual_set
from .face_eq import Adjustment
from .fixtures import (
    SHIPPED_DIR, Blades, Channel, Dimensions, Fixture, Library, LensTube, Mode, Mount, Optics, Range,
    cct_to_rgb, discover, encode,
)
from .fixture_models import fixture_model
from .layout import (
    BATTEN_CLEARANCE, BATTEN_RADIUS, EPS, PLEAT_AMPLITUDE, PROSCENIUM_RECESS, Ctx, Part, _masking,
    _metres, _nn, _polys_overlap, _side_stair,
)
from .meshes import MAX_DEPTH_FACTOR
from .params import FIXTURE, GROUPS, PATCH_FAMILIES, side_sets
from .primitives import PleatedSurface, Truss, Tube
from .vecmath import add as _add, angle_between as _angle_between, cross as _cross, dot as _dot
from .vecmath import mul as _mul, sub as _sub, unit as _unit

RIG_COLLECTION = "Theatre_Rig"
FIXTURES_COLLECTION = "Theatre_Fixtures"
MATERIAL_TUBE = "TS_Batten"
MATERIAL_TRUSS = "TS_Truss"

Vec3 = tuple[float, float, float]

PIPE_END_MARGIN = 0.10
PACK_STEP = 0.05
TUBE_MARGIN = 1.05
MIN_ROW_DROP = 0.10
BATTEN_TOLERANCE = 0.50
FRAME_OFFSET = 0.30
TOWER_TOP_MARGIN = 0.10
TOWER_CLEARANCE = 0.10
TOWER_MIN_ARM = 0.25
TOWER_MIN_BOTTOM = 0.50
GATE_MIN_RATIO = 0.25
HAZER_INSET = 0.50
LISTED_NAMES = 4
MAX_PATCH_ALERTS = 8
MAX_CHANNEL = 512
AZIMUTH_STEP = 0.5
AZIMUTH_SEARCH = 30.0
FOOTPRINT_MARGIN = 0.02
PIPE2_NAME = "FrontPipe_02"
HEIGHT_STEP = 0.05
TILT_STEP = 1.0
BEAM_RANGE = 30.0
BEAM_MARGIN = 0.05
BEAM_NEAR = 0.50
MAX_BEAM_ALERTS = 8
GRID_X = (-0.5, 0.0, 0.5)
GRID_Y = (0.0, 0.5, 1.0)
WALL_TILE = 1.0
WALL_STEP = 0.15
LEG_GRAZE = 0.30
MASK_CONE = 0.5
GOLDEN = 0.6180339887498949
GOLDEN_STEPS = 24
FOCUS_STEP = 0.2
NEZ_REACH = (1.0, 0.75, 0.5, 0.25, 0.0)
_MODEL_ERRORS = (OSError, ValueError, KeyError, IndexError, struct.error)

FAMILY_LABELS = {
    "backlight": "contre", "front_movers": "mobiles de face", "tower_movers": "mobiles de pylône",
    "front_pc": "PC de face", "profiles": "découpes", "hazer": "hazer",
}
FAMILY_GROUPS = {
    "backlight": "backlight", "front_movers": "front_movers", "tower_movers": "towers",
    "front_pc": "front_pc", "profiles": "profiles", "hazer": "haze",
}
FAR_LABEL = "appareils des rangs du fond"
MOVER_GROUPS = {"backlight": "Backlight", "front_movers": "FrontMovers"}
PACK_ORDER = {"backlight": 0, "profiles": 1, "front_movers": 2}
CUT_NAMES = ("bottom", "top", "left", "right")


# ------------------------------------------------------------------ records

@dataclass(frozen=True)
class Zones:
    """Play-area grid: `xs` and `ys` are the zone centres (jardin to cour, face to back)."""

    nx: int
    nr: int
    width: float
    depth: float
    xs: tuple[float, ...]
    ys: tuple[float, ...]


@dataclass(frozen=True)
class Blade:
    """One blade. `edge` is `h_c`, `edge_a`/`edge_b` the distances at the two ends (spec 13.8).

    `cut` is `bottom`, `top`, `left`, `right`, or "" for a free or manual blade.
    """

    index: int
    cut: str
    side: float
    edge: float
    angle: float
    edge_a: float
    edge_b: float
    insertion_a: float
    insertion_b: float


@dataclass(frozen=True)
class BladeSet:
    """Blade plane at `plane_z` in the head frame, `distance` from the source (`g`)."""

    plane_z: float
    distance: float
    open_eff: float
    rotation: float
    half_span: float
    blades: tuple[Blade, ...]


@dataclass(frozen=True)
class ChannelValue:
    """Rest value of one channel: `value` normalized, `data` the DMX bytes, coarse first."""

    attribute: str
    channel: int
    fine_channel: int | None
    bits: int
    value: float
    data: tuple[int, ...]


@dataclass(frozen=True)
class RigFixture:
    """Everything the builder needs for one fixture. `family` is the patch family key."""

    name: str
    family: str
    fixture_id: str
    mode: str
    support: str
    hang: Vec3
    root: Vec3
    root_rotation: Vec3
    pivot: Vec3
    aim: Vec3
    axis: Vec3
    moving: bool
    pan: float | None
    tilt: float | None
    pan_dmx: tuple[int, ...] | None
    tilt_dmx: tuple[int, ...] | None
    field_angle: float | None
    beam_angle: float | None
    tube: str | None
    aperture: float | None
    source_kind: str
    source_z: float
    source: Vec3
    blades: BladeSet | None
    circuit: str | None
    cct: float | None
    universe: int
    address: int
    footprint: int
    channels: tuple[ChannelValue, ...]
    weight: float
    width: float
    barn_doors: BarnDoorSet | None = None


@dataclass(frozen=True)
class PatchEntry:
    name: str
    family: str
    universe: int
    address: int
    footprint: int

    @property
    def last(self) -> int:
        return self.address + self.footprint - 1


@dataclass(frozen=True)
class SupportLoad:
    name: str
    weight: float
    count: int


@dataclass(frozen=True)
class HazeLink:
    """Scene properties that drive the haze density (spec 15.4)."""

    fixture: str
    prop: str
    fine_prop: str | None
    bits: int
    rest: float

    def level(self) -> tuple[str, dict[str, str]]:
        """Driver expression of the 0..1 hazer level and its scene data paths, as `_Expr.dmx` reads a channel."""
        paths = {"c": f'["{self.prop}"]'}
        if self.bits == 8 or self.fine_prop is None:
            return "c", paths
        return "(256*c+f)/257", {**paths, "f": f'["{self.fine_prop}"]'}


@dataclass(frozen=True)
class RigDims:
    """Panel values of spec 13.10; `profiles` is (name, tube, field), `patch_ranges` (family, u, first, last).

    `pc_azimuths` is the crossing azimuth used by each hung PC row, `pc_supports` its (tube, site).
    The `movers_*` fields are None without a second pipe; `beam_clearance` and `masking_clearance`
    are the smallest beam gaps to a fixture and to a border or leg (spec 13.11). `nez_reach` gives,
    per row 0 PC, the share of its half of the nez inside its beam (spec 13.7).
    """

    pipe_y: float
    pipe_z: float
    area_depth: float
    pipe_drop: float
    profiles: tuple[tuple[str, str | None, float], ...]
    patch_ranges: tuple[tuple[str, int, int, int], ...]
    pc_azimuths: tuple[float, ...] = ()
    movers_pipe_y: float | None = None
    movers_pipe_z: float | None = None
    mover_radius: float | None = None
    beam_clearance: float | None = None
    pc_supports: tuple[tuple[str, float], ...] = ()
    masking_clearance: float | None = None
    nez_reach: tuple[tuple[str, float], ...] = ()


@dataclass(frozen=True)
class FaceSetup:
    """Measuring plane of the face equalisation (spec 13.13): width wanted lit on the forestage (the nose
    width, or the frame opening when a row 0 PC hangs outside the frame and cuts on the post), frame
    width, forestage and area depths, height of the probes."""

    nose_width: float
    frame_width: float
    forestage_depth: float
    area_depth: float
    z: float


@dataclass(frozen=True)
class Rig:
    """`rest` maps `(universe, channel)` to the scene property value (`byte / 255`).

    `face` is the probe plane of the equalisation; `equalised` is True when the face PCs carry a
    stored equalisation (spec 13.13).
    """

    enabled: bool = False
    zones: Zones | None = None
    fixtures: tuple[RigFixture, ...] = ()
    patch: tuple[PatchEntry, ...] = ()
    rest: Mapping = field(default_factory=dict)
    loads: tuple[SupportLoad, ...] = ()
    circuits: tuple[tuple[str, tuple[str, ...]], ...] = ()
    haze: HazeLink | None = None
    dims: RigDims | None = None
    warnings: tuple[str, ...] = ()
    face: FaceSetup | None = None
    equalised: bool = False

    def find(self, name: str) -> RigFixture:
        for item in self.fixtures:
            if item.name == name:
                return item
        raise KeyError(name)

    def by_family(self, family: str) -> tuple[RigFixture, ...]:
        return tuple(f for f in self.fixtures if f.family == family)


# --------------------------------------------------------------- vector math

def head_frame(pan: float, tilt: float) -> tuple[Vec3, Vec3, Vec3]:
    """World images `(x_h, y_h, a)` of the head axes for pan and tilt in degrees (spec 13.9)."""
    phi, tau = math.radians(pan), math.radians(tilt)
    sp, cp, st, ct = math.sin(phi), math.cos(phi), math.sin(tau), math.cos(tau)
    return ((cp, -sp, 0.0), (-ct * sp, -ct * cp, st), (-st * sp, -st * cp, -ct))


def aim_angles(axis: Vec3) -> tuple[float, float]:
    """Physical `(pan, tilt)` in degrees for a world direction, tilt in [0, 180] (spec 13.9)."""
    bx, by, bz = axis[0], -axis[1], -axis[2]
    tau = math.degrees(math.acos(min(max(bz, -1.0), 1.0)))
    if math.sin(math.radians(tau)) < 1e-6:
        return 0.0, tau
    return math.degrees(math.atan2(-bx, by)), tau


def spread(i: int, n: int, wc: float) -> float:
    return -wc / 2 + (i + 0.5) * wc / n


@lru_cache(maxsize=1)
def default_library() -> Library:
    """The shipped library, discovered once from the package folder."""
    return discover([SHIPPED_DIR])


# ------------------------------------------------------------------ planning

NO_DIMENSIONS = Dimensions(0.0, 0.0, 0.0)
NO_MOUNT = Mount(0.0, 0.0)
NO_OPTICS = Optics("none", 0.0, 0.0, 0.0, None, None, (), False, ())


@dataclass
class _Sheet:
    """A fiche with its mode; the hazer, which has no body or lens, gets zero-sized stand-ins."""

    fixture: Fixture
    mode: Mode
    dimensions: Dimensions = NO_DIMENSIONS
    mount: Mount = NO_MOUNT
    optics: Optics = NO_OPTICS


@dataclass
class _Slot:
    name: str
    family: str
    sheet: _Sheet
    x: float
    y: float
    z: float
    target: Vec3
    load: str
    group: str = ""
    limit: float = 0.0
    movable: bool = True
    circuit: str | None = None
    meta: dict = field(default_factory=dict)
    universe: int = 1
    address: int = 1

    @property
    def width(self) -> float:
        return self.sheet.dimensions.width


class _Work:
    def __init__(self, c: Ctx, library: Library, zones: Zones, za: float, ya: float):
        self.c, self.lib = c, library
        self.warnings: list[str] = []
        self.slots: list[_Slot] = []
        self.objects: list = []
        self.zones, self.za, self.ya = zones, za, ya
        self.azimuths: list[float] = []
        self.row_supports: list[tuple[str, float]] = []
        self.models: dict = {}
        self.boxes: dict = {}
        self.envelopes: dict = {}
        self.mover_radius: float | None = None
        self.walls: tuple[_Wall, ...] = ()
        self.uncovered: list[tuple[str, float, float]] = []
        self.too_wide: list[tuple[str, float, float]] = []
        self.focus: dict = {}
        self.nez_reach: list[tuple[str, float]] = []
        self.nez_missed: list[str] = []
        self.doors_short: list[str] = []
        self.doors_misfit: list[str] = []
        self.adjust: Mapping[str, Adjustment] = {}

    def warn(self, message: str) -> None:
        if message not in self.warnings:
            self.warnings.append(message)

    def sheet(self, family: str, node: Mapping, suffix: str = "",
              fallback: _Sheet | None = None) -> _Sheet | None:
        """Fiche and mode of a family (`fixture<suffix>`), or `fallback` with a French alert."""
        label, fid = FAR_LABEL if suffix else FAMILY_LABELS[family], node[f"fixture{suffix}"]
        fx = self.lib.get(fid)
        ignored = f"{label} ignoré" if fallback is None else f"{label} posés avec « {fallback.fixture.id} »"
        if fx is None:
            self.warn(f"Fiche « {fid} » introuvable dans la bibliothèque : {ignored}.")
            return fallback
        allowed = next(p.families for p in GROUPS[FAMILY_GROUPS[family]].params
                       if p.key == f"fixture{suffix}")
        if fx.family not in allowed:
            self.warn(f"Fiche « {fid} » : famille « {fx.family} » inadaptée aux {label} : {ignored}.")
            return fallback
        dimensions, mount, optics = fx.physical.dimensions, fx.physical.mount, fx.optics
        if fx.family != "hazer" and None in (dimensions, mount, optics):
            self.warn(f"Fiche « {fid} » incomplète (dimensions, accroche ou optique) : {ignored}.")
            return fallback
        try:
            mode = fx.mode(node[f"mode{suffix}"])
        except KeyError:
            self.warn(f"Mode « {node[f'mode{suffix}']} » inconnu de la fiche « {fid} » : "
                      f"mode par défaut utilisé.")
            mode = fx.mode()
        return _Sheet(fx, mode, dimensions or NO_DIMENSIONS, mount or NO_MOUNT, optics or NO_OPTICS)

    def add(self, slot: _Slot) -> _Slot:
        self.slots.append(slot)
        return slot

    def listed(self, names) -> str:
        names = list(names)
        more = f" et {len(names) - LISTED_NAMES} autres" if len(names) > LISTED_NAMES else ""
        return ", ".join(names[:LISTED_NAMES]) + more


@dataclass(frozen=True)
class _Support:
    """A hang line parallel to X: its name, plan Y, height and half length."""

    name: str
    y: float
    z: float
    limit: float
    label: str


def _clamp_x(w: _Work, name: str, x: float, tube: _Support) -> float:
    if abs(x) <= tube.limit + EPS:
        return x
    clamped = math.copysign(tube.limit, x)
    w.warn(f"Point d'accroche hors de {tube.label} : {name} ramené de X = {_metres(x)} "
           f"à {_metres(clamped)}.")
    return clamped


def _nearest_batten(c: Ctx, y: float) -> int | None:
    if not c.light_batten_ys:
        return None
    return min(range(len(c.light_batten_ys)), key=lambda i: abs(c.light_batten_ys[i] - y))


def _upstage_batten(c: Ctx) -> int | None:
    """Most upstage light batten still in front of the back line, else the most upstage one."""
    front = [i for i, y in enumerate(c.light_batten_ys) if y < c.plan.yb]
    return front[-1] if front else len(c.light_batten_ys) - 1 if c.light_batten_ys else None


def _batten(c: Ctx, index: int) -> _Support:
    name = f"Batten_{_nn(index + 1)}"
    return _Support(name, c.light_batten_ys[index], c.plan.zb, c.Wk / 2 - PIPE_END_MARGIN,
                 f"la porteuse {name}")


def _zones(c: Ctx, ya: float) -> Zones:
    pc = c.p["front_pc"]
    if pc["zone_mode"] == "manual":
        nx, nr = pc["columns"], pc["rows"]
    else:
        nx = max(1, math.ceil(c.Wc / pc["zone_width"] - 1e-9))
        nr = min(4, max(1, math.ceil(ya / pc["zone_width"] - 1e-9)))
    zw, zd = c.Wc / nx, ya / nr
    return Zones(nx, nr, zw, zd, tuple(spread(i, nx, c.Wc) for i in range(nx)),
                 tuple((j + 0.5) * zd for j in range(nr)))


def _front_pipe(w: _Work, zones: Zones, za: float) -> tuple[_Support, float]:
    """The front pipe and its automatic drop `ΔYp` (spec 13.2)."""
    c, rg, fr = w.c, w.c.p["rig"], w.c.p["front_pc"]
    zp = c.Hf - c.p["rig_front"]["ceiling_gap"]
    drop = 0.0
    if zp > za + EPS:
        drop = (zp - za) / math.tan(math.radians(rg["site"])) * math.cos(math.radians(fr["azimuth"]))
    else:
        w.warn(f"Perche de face trop basse : Z = {_metres(zp)} au plus haut que le plan de visée "
               f"({_metres(za)}).")
    rf = c.p["rig_front"]
    yp = zones.ys[0] - drop if rf["auto_position"] else rf["y"]
    if not -c.Yh + FRAME_OFFSET <= yp <= c.Ys - FRAME_OFFSET:
        w.warn(f"Perche de face hors de la salle : Y = {_metres(yp)}.")
    return _Support("FrontPipe", yp, zp, c.Wt / 2 - PIPE_END_MARGIN, "la perche"), drop


# ---------------------------------------------------------------- footprints

@dataclass(frozen=True)
class _Boxes:
    """Bounding-box corners of the base, pan and tilt parts of a model, each in its own frame (14.2),
    and the points of the barn doors, in the tilt frame, that only the footprint counts (13.10)."""

    base: tuple[Vec3, ...]
    pan: tuple[Vec3, ...]
    tilt: tuple[Vec3, ...]
    pivot: Vec3
    accessory: tuple[Vec3, ...] = ()


def _corners(mesh) -> tuple[Vec3, ...]:
    if not mesh.vertices:
        return ()
    lo = [min(v[i] for v in mesh.vertices) for i in range(3)]
    hi = [max(v[i] for v in mesh.vertices) for i in range(3)]
    return tuple((x, y, z) for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2]))


def _boxes(w: _Work, sheet: _Sheet) -> _Boxes | None:
    """Corner boxes of the sheet's default model, or None when its model cannot be built."""
    key = sheet.fixture.id
    if key not in w.boxes:
        try:
            model = fixture_model(sheet.fixture, None, w.models)
            doors = sheet.fixture.barn_doors if w.c.p["front_pc"]["barn_doors"] != "none" else None
            w.boxes[key] = _Boxes(_corners(model.base), _corners(model.pan), _corners(model.tilt),
                                  model.tilt_pivot, envelope_points(doors, model.lens_offset) if doors else ())
        except _MODEL_ERRORS:
            w.boxes[key] = None
    return w.boxes[key]


def posed_points(boxes: _Boxes, root: Vec3, pan: float, tilt: float) -> list[Vec3]:
    """World corners of the posed parts: the tilt part by `Rz(pan)(pivot + Rx(-tilt) v)`, then the
    root's 180 degree turn about X (spec 13.9)."""
    cp, sp = math.cos(math.radians(pan)), math.sin(math.radians(pan))
    ct, st = math.cos(math.radians(tilt)), math.sin(math.radians(tilt))
    px, py, pz = boxes.pivot
    out: list[Vec3] = []
    for part, corners in (("base", boxes.base), ("pan", boxes.pan), ("tilt", boxes.tilt),
                          ("accessory", boxes.accessory)):
        for x, y, z in corners:
            if part in ("tilt", "accessory"):
                x, y, z = x + px, y * ct + z * st + py, -y * st + z * ct + pz
            if part != "base":
                x, y = cp * x - sp * y, sp * x + cp * y
            out.append((root[0] + x, root[1] - y, root[2] - z))
    return out


@dataclass(frozen=True)
class _Envelope:
    """Volume swept by a moving head about its pan axis, in the body frame (spec 13.10).

    `radius` is the horizontal reach; `low` and `high` bound the extent along Z_b (toward the
    head), so the world heights are `root_z - high` to `root_z - low`.
    """

    radius: float
    low: float
    high: float


def _swept(sheet: _Sheet, boxes: _Boxes | None) -> _Envelope:
    if boxes is None:
        d = sheet.dimensions
        return _Envelope(math.hypot(d.width, d.depth) / 2, 0.0, d.height)
    fixed = [*boxes.base, *boxes.pan]
    px, py, pz = boxes.pivot
    tilt = sheet.fixture.pan_tilt[1] if sheet.fixture.pan_tilt else Range(0.0, 0.0)
    steps = max(1, math.ceil((tilt.max - tilt.min) / TILT_STEP))
    for k in range(steps + 1):
        t = math.radians(tilt.min + (tilt.max - tilt.min) * k / steps)
        ct, st = math.cos(t), math.sin(t)
        fixed += [(x + px, y * ct + z * st + py, -y * st + z * ct + pz) for x, y, z in boxes.tilt]
    return _Envelope(max(math.hypot(x, y) for x, y, _ in fixed), min(z for *_, z in fixed),
                     max(z for *_, z in fixed))


def _envelope(w: _Work, sheet: _Sheet) -> _Envelope:
    """Envelope of a moving head over its whole tilt range, whatever its pan (spec 13.10)."""
    key = sheet.fixture.id
    if key not in w.envelopes:
        w.envelopes[key] = _swept(sheet, _boxes(w, sheet))
    return w.envelopes[key]


def _span_at(w: _Work, sheet: _Sheet, hang: Vec3, target: Vec3, axis: int = 0) -> tuple[float, float]:
    """Interval of the posed model on a world axis (0 = X along a pipe, 2 = Z on a tower arm),
    margin included; the swept envelope for a moving head (spec 13.10)."""
    mount = sheet.mount
    root = (hang[0], hang[1], hang[2] - mount.hook_height)
    if sheet.fixture.pan_tilt is not None:
        env = _envelope(w, sheet)
        lo, hi = ((root[0] - env.radius, root[0] + env.radius) if axis == 0
                  else (root[2] - env.high, root[2] - env.low))
        return lo - FOOTPRINT_MARGIN, hi + FOOTPRINT_MARGIN
    pivot = (root[0], root[1], root[2] - mount.tilt_axis_height)
    pan, tilt, _ = _pan_tilt(sheet.fixture, _unit(_sub(target, pivot)))
    boxes = _boxes(w, sheet)
    if boxes is None:
        half = sheet.dimensions.width / 2
        values = [root[0] - half, root[0] + half] if axis == 0 else [root[2] - sheet.dimensions.height, root[2]]
    else:
        values = [p[axis] for p in posed_points(boxes, root, pan, tilt)]
    return min(values) - FOOTPRINT_MARGIN, max(values) + FOOTPRINT_MARGIN


def _overlaps(a: tuple[float, float], b: tuple[float, float]) -> bool:
    return a[0] < b[1] - EPS and b[0] < a[1] - EPS


def _slot_span(w: _Work, s: _Slot, x: float, axis: int = 0) -> tuple[float, float]:
    return _span_at(w, s.sheet, (x, s.y, s.z), s.target, axis)


# ------------------------------------------------------------------ families

def _plan_backlight(w: _Work, zones: Zones, za: float) -> None:
    c, node = w.c, w.c.p["backlight"]
    if not node["enabled"] or (sheet := w.sheet("backlight", node)) is None:
        return
    upstage = node["position"] == "upstage"
    index = _upstage_batten(c) if upstage else _nearest_batten(c, node["distance"])
    if index is None:
        w.warn("Aucune porteuse lumière : pas de contre.")
        return
    tube = _batten(c, index)
    if not upstage and abs(tube.y - node["distance"]) > BATTEN_TOLERANCE + EPS:
        w.warn(f"Aucune porteuse à moins de {_metres(BATTEN_TOLERANCE)} de "
               f"{_metres(node['distance'])} : contre posé à {_metres(tube.y)}.")
    rows = [j for j, yr in enumerate(zones.ys) if yr < tube.y - EPS]
    row = rows[-1] if rows else 0
    n = node["count"]
    for i in range(n):
        x = spread(i, n, c.Wc)
        w.add(_Slot(f"Backlight_{_nn(i + 1)}", "backlight", sheet, _clamp_x(w, f"Backlight_{_nn(i + 1)}", x, tube),
                    tube.y, tube.z, (x, zones.ys[row], za), tube.name, tube.name, tube.limit,
                    circuit=MOVER_GROUPS["backlight"]))


def _plan_front_movers(w: _Work, zones: Zones, za: float, front: _Support) -> _Support | None:
    """Hang the front movers on the second pipe, provisionally at the height of the first (13.2 bis)."""
    node = w.c.p["front_movers"]
    if not node["enabled"] or (sheet := w.sheet("front_movers", node)) is None:
        return None
    y = front.y - w.c.p["rig_front"]["movers_offset"]
    if y < -w.c.Yh + FRAME_OFFSET:
        w.warn(f"Perche des mobiles hors de la salle : Y = {_metres(y)}.")
    pipe = _Support(PIPE2_NAME, y, front.z, front.limit, "la seconde perche de face")
    n = node["count"]
    for i in range(n):
        x, name = spread(i, n, w.c.Wc), f"FrontMover_{_nn(i + 1)}"
        w.add(_Slot(name, "front_movers", sheet, _clamp_x(w, name, x, pipe), pipe.y, pipe.z,
                    (x, zones.ys[0], za), pipe.name, pipe.name, pipe.limit,
                    circuit=MOVER_GROUPS["front_movers"]))
    if sheet.fixture.pan_tilt is not None:
        w.mover_radius = _envelope(w, sheet).radius
    return pipe


def _row_x(zones: Zones, drop: float, azimuth: float) -> list[tuple[str, int, float]]:
    """(side, column, X) of every PC of a row for one crossing azimuth."""
    t = drop * math.tan(math.radians(azimuth))
    return [(tag, i, xc + sign * t) for tag, sign in (("L", -1), ("R", 1))
            for i, xc in enumerate(zones.xs)]


def _row_azimuth(w: _Work, tube: _Support, yr: float, nominal: float, sheet: _Sheet,
                 taken: list[tuple[float, float]], strict: bool = False) -> float | None:
    """Azimuth nearest to `nominal` (+-0.5 deg steps, +-30 deg) where no posed PC of the row
    overlaps another on the tube (`taken`: intervals of earlier rows) and every zone stays
    within the widest field of the sheet. `strict` also asks the beams to clear the borders,
    the legs and the profiles already hung on the tube."""
    zones = w.zones
    drop, za = yr - tube.y, w.za
    mount, widest = sheet.mount, sheet.optics.widest_field
    z = tube.z - mount.hook_height - mount.tilt_axis_height
    for k in range(int(AZIMUTH_SEARCH / AZIMUTH_STEP) + 1):
        for delta in ((0.0,) if k == 0 else (k * AZIMUTH_STEP, -k * AZIMUTH_STEP)):
            row = _row_x(zones, drop, nominal + delta)
            clear = all(abs(x) <= tube.limit + EPS for _, _, x in row)
            if clear:
                spans = [_span_at(w, sheet, (x, tube.y, tube.z),
                                  _wash_target(w, (zones.xs[i], yr), za, (x, tube.y, z), sheet, tag))
                         for tag, i, x in row] + taken
                clear = not any(_overlaps(a, b) for n, a in enumerate(spans) for b in spans[n + 1:])
            if clear and all(
                    _wash_required(w, (zones.xs[i], yr), za, (x, tube.y, z),
                                   _wash_axis(w, (zones.xs[i], yr), za, (x, tube.y, z), sheet, tag)) <= widest + EPS
                    for tag, i, x in row) and (not strict or _row_clear(w, sheet, tube, yr, nominal + delta)):
                return nominal + delta
    return None


def _row_clear(w: _Work, sheet: _Sheet, tube: _Support, yr: float, azimuth: float) -> bool:
    """Whether the beams of a PC row keep `BEAM_MARGIN` from the borders, legs and the profiles
    planned on the tube (spec 13.7)."""
    beams = _row_beams(w, sheet, tube, yr, azimuth)
    bodies = [_slot_body(w, s) for s in w.slots if s.group == tube.name and s.family == "profiles"]
    gaps = [g for *_, g in _wall_gaps(beams, w.walls) + _gaps(beams, bodies)]
    return min(gaps, default=math.inf) >= BEAM_MARGIN


def _site(w: _Work, tube: _Support, yr: float, azimuth: float) -> float:
    """Site (elevation, degrees) of a row hung on `tube` for the crossing azimuth (spec 13.2)."""
    return math.degrees(math.atan2(tube.z - w.za, (yr - tube.y) / math.cos(math.radians(azimuth))))


def _pc_beam(w: _Work, sheet: _Sheet, name: str, tube: _Support, x: float, zone: tuple[float, float],
             side: str) -> _Beam:
    """Beam of a face PC hung at `x` on `tube` and aimed at `zone`, as `_build_fixture` will make it."""
    optics, mount = sheet.optics, sheet.mount
    pivot = (x, tube.y, tube.z - mount.hook_height - mount.tilt_axis_height)
    axis = _wash_axis(w, zone, w.za, pivot, sheet, side)
    target = _wash_target(w, zone, w.za, pivot, sheet, side)
    lens, field_angle, _ = _fit_field(optics, _wash_required(w, zone, w.za, pivot, axis), 1.0)
    if _front_row(w, zone):
        focus = _focus(w, sheet, zone, side, pivot)
        lens, field_angle = focus.tube, focus.field
    source_z = _source(optics, lens, field_angle)[1]
    return _make_beam(name, target, _add(pivot, _mul(axis, source_z)), axis, field_angle,
                      optics.lens_offset - source_z)


def _row_beams(w: _Work, sheet: _Sheet, tube: _Support, yr: float, azimuth: float) -> list[_Beam]:
    zones, beams = w.zones, []
    for tag, i, x in _row_x(zones, yr - tube.y, azimuth):
        x = math.copysign(min(abs(x), tube.limit), x)
        beams.append(_pc_beam(w, sheet, f"{tag}{i}", tube, x, (zones.xs[i], yr), tag))
    return beams


def _row_tube(w: _Work, j: int, yr: float, drop_auto: float, sheet: _Sheet,
              on_tube: dict[str, list[tuple[float, float]]]) -> _Support | None:
    """Hang line of row `j >= 1` (spec 13.7), among the light battens short of the zone. A batten
    that fits (an azimuth exists, the beams clear the masking) beats one that does not; then one
    upstage of the front border beats one downstage; then the nearest to the nominal site.
    With no batten short of the zone, the nearest to the ADEC drop."""
    c, nominal = w.c, w.c.p["front_pc"]["azimuth"]
    floor = c.plan.front_plane + BATTEN_CLEARANCE - EPS if c.p["masking"]["front_border"] else -math.inf
    options = [_batten(c, i) for i, y in enumerate(c.light_batten_ys) if yr - y >= MIN_ROW_DROP - EPS]
    if not options:
        index = 0 if j == 1 and c.light_batten_ys else _nearest_batten(c, yr - drop_auto)
        return None if index is None else _batten(c, index)
    scored = []
    for tube in options:
        taken = on_tube.get(tube.name, [])
        azimuth = _row_azimuth(w, tube, yr, nominal, sheet, taken, strict=True)
        fits = azimuth is not None
        if azimuth is None:
            azimuth = _row_azimuth(w, tube, yr, nominal, sheet, taken)
        site = abs(_site(w, tube, yr, nominal if azimuth is None else azimuth) - c.p["rig"]["site"])
        scored.append((not fits, tube.y < floor, site, tube))
    return min(scored, key=lambda t: t[:3])[3]


def _plan_front_pc(w: _Work, zones: Zones, za: float, pipe: _Support, drop_auto: float) -> None:
    c, node = w.c, w.c.p["front_pc"]
    if not node["enabled"] or (near := w.sheet("front_pc", node)) is None:
        return
    far = (w.sheet("front_pc", node, "_far", near) if len(zones.ys) > 1 else near) or near
    on_tube = {pipe.name: [_slot_span(w, s, s.x) for s in w.slots if s.family == "profiles"]}
    for j, yr in enumerate(zones.ys):
        sheet = near if j == 0 else far
        if j == 0:
            tube = pipe
        elif (tube := _row_tube(w, j, yr, drop_auto, sheet, on_tube)) is None:
            w.warn(f"Rang {j + 1} : aucune porteuse lumière, rang non posé.")
            continue
        drop = yr - tube.y
        if drop < MIN_ROW_DROP - EPS:
            w.warn(f"Rang {j + 1} : porteuse trop en arrière de la zone.")
            continue
        taken = on_tube.setdefault(tube.name, [])
        azimuth = _row_azimuth(w, tube, yr, node["azimuth"], sheet, taken, strict=True)
        if azimuth is None:
            azimuth = _row_azimuth(w, tube, yr, node["azimuth"], sheet, taken)
        if azimuth is None:
            azimuth = node["azimuth"]
            w.warn(f"Rang {j + 1} : aucun azimut à ±{AZIMUTH_SEARCH:g}° de {azimuth:g}° n'évite "
                   f"que des PC se touchent sur {tube.label} ou sortent de leur champ.")
        w.azimuths.append(azimuth)
        w.row_supports.append((tube.name, _site(w, tube, yr, azimuth)))
        for tag, i, x in _row_x(zones, drop, azimuth):
            name = f"FrontPC_{tag}_{_nn(j * zones.nx + i + 1)}"
            x = _clamp_x(w, name, x, tube)
            pivot = (x, tube.y, tube.z - sheet.mount.hook_height - sheet.mount.tilt_axis_height)
            target = _wash_target(w, (zones.xs[i], yr), za, pivot, sheet, tag)
            taken.append(_span_at(w, sheet, (x, tube.y, tube.z), target))
            w.add(_Slot(name, "front_pc", sheet, x, tube.y, tube.z, target,
                        tube.name, tube.name, tube.limit, movable=False,
                        circuit=f"FrontPC_Row{j + 1}_{tag}",
                        meta={"zone": (zones.xs[i], yr), "side": tag, "row": j}))


def _bisector_y(head: Vec3, low: Vec3, high: Vec3, za: float) -> float:
    """Y where the ray bisecting the bottom and top cut directions (side view) crosses the plane `za`."""
    elev = [math.atan2(head[2] - q[2], q[1] - head[1]) for q in (low, high)]
    return head[1] + (head[2] - za) / math.tan(sum(elev) / 2)


def _plan_profiles(w: _Work, zones: Zones, za: float, pipe: _Support, ya: float) -> None:
    c, node = w.c, w.c.p["profiles"]
    if not node["enabled"] or (sheet := w.sheet("profiles", node)) is None:
        return
    mount = sheet.mount
    head = (0.0, pipe.y, pipe.z - mount.hook_height - mount.tilt_axis_height)
    yt = _bisector_y(head, (0.0, 0.0, c.Hp), _top_target(w, head), za)
    for p, tag in enumerate("LCR"):
        name, xs = f"Profile_{tag}", spread(p, 3, c.Wc)
        w.add(_Slot(name, "profiles", sheet, _clamp_x(w, name, xs, pipe), pipe.y, pipe.z,
                    (xs, yt, za), pipe.name, pipe.name, pipe.limit, circuit=name,
                    meta={"third": p}))


def _plan_towers(w: _Work, za: float, ya: float) -> None:
    c, tw = w.c, w.c.p["towers"]
    left, right = side_sets(tw)
    sets = ((-1, "L", "jardin", left), (1, "R", "cour", right))
    sheet = (w.sheet("tower_movers", tw) if any(n["count"] and n["movers"] for _, _, _, n in sets)
             else None)
    stairs = c.p["stairs"]
    shapes = []
    for s, _, label, _ in sets:
        if stairs["left" if s < 0 else "right"]:
            geo = _side_stair(s, c.W, c.Ys, c.risers, stairs)
            polys = ([geo.landing] if geo.landing else []) + list(geo.steps)
            shapes.append((label, polys + ([geo.clearance] if geo.clearance else [])))
    for s, tag, _, node in sets:
        count = 0
        for k in range(1, node["count"] + 1):
            y = -(node["first_distance"] + (k - 1) * node["spacing"])
            base = max(tw["base_size"], tw["truss_size"])
            xt = s * (c.Wt / 2 - base / 2)
            name = f"Tower_{tag}_{_nn(k)}"
            w.objects.append(Truss(name, MATERIAL_TRUSS, RIG_COLLECTION, (xt, y), base,
                                   tw["truss_size"], node["height"]))
            _check_tower(w, name, xt, y, base, shapes)
            if sheet is None or not node["movers"]:
                continue
            count = _plan_tower_movers(w, sheet, name, tag, s, xt, y, node, count, ya, za)


def _check_tower(w: _Work, name: str, xt: float, y: float, base: float, shapes) -> None:
    half = base / 2
    plan = ((xt - half, y - half), (xt + half, y - half), (xt + half, y + half), (xt - half, y + half))
    for label, polys in shapes:
        if any(_polys_overlap(plan, q) for q in polys):
            w.warn(f"Pylône {name} : l'emprise recoupe l'escalier {label}, son palier ou son dégagement.")
    if y - half < -w.c.Yh - EPS:
        w.warn(f"Pylône {name} hors de la salle dessinée : Y = {_metres(y - half)}.")


def _plan_tower_movers(w, sheet, name, tag, s, xt, y, node, count, ya, za) -> int:
    c, tw = w.c, w.c.p["towers"]
    dims, mount = sheet.dimensions, sheet.mount
    pitch = mount.hook_height + dims.height + TOWER_CLEARANCE
    arm = max(TOWER_MIN_ARM, dims.width / 2 + TOWER_CLEARANCE)
    flank = abs(xt) - tw["truss_size"] / 2
    z = node["height"]
    for m in range(1, node["movers"] + 1):
        z = node["height"] - TOWER_TOP_MARGIN - (m - 1) * pitch
        arm_name = f"TowerArm_{tag}_{name[-2:]}_{_nn(m)}"
        w.objects.append(Tube(arm_name, MATERIAL_TUBE, RIG_COLLECTION, (s * flank, y, z),
                              (s * (flank - arm), y, z), BATTEN_RADIUS))
        count += 1
        mover = f"TowerMover_{tag}_{_nn(count)}"
        target = (-s * c.Wc / 4, ya * (m - 0.5) / node["movers"], za)
        w.add(_Slot(mover, "tower_movers", sheet, s * (flank - arm), y, z, target, name, "", 0.0,
                    movable=False, circuit=f"TowerMovers_{tag}"))
    if z - mount.hook_height - dims.height < TOWER_MIN_BOTTOM - EPS:
        w.warn(f"Pylône {name} trop bas pour {node['movers']} appareils : le bas du dernier est à "
               f"{_metres(z - mount.hook_height - dims.height)} du sol (minimum "
               f"{_metres(TOWER_MIN_BOTTOM)}).")
    return count


def _plan_hazer(w: _Work) -> None:
    c, node = w.c, w.c.p["haze"]
    if not node["dmx_driven"] or (sheet := w.sheet("hazer", node)) is None:
        return
    here = (-(c.Wk / 2 - HAZER_INSET), c.D - HAZER_INSET, c.Hp)
    w.add(_Slot("Hazer_01", "hazer", sheet, here[0], here[1], here[2], here, ""))


# ------------------------------------------------------------------- packing

def _free_x(w: _Work, slot: _Slot, placed: list[tuple[_Slot, tuple[float, float]]]) -> float | None:
    """Nearest X to the wanted one where the posed `slot` overlaps nothing; None when the tube is full."""
    sign = -1.0 if slot.x > 0 else 1.0
    for k in range(int(2 * slot.limit / PACK_STEP) + 2):
        for delta in ((0.0,) if k == 0 else (sign * k * PACK_STEP, -sign * k * PACK_STEP)):
            x = slot.x + delta
            if abs(x) <= slot.limit + EPS:
                span = _slot_span(w, slot, x)
                if not any(_overlaps(span, other) for _, other in placed):
                    return x
    return None


def _pack(w: _Work, tubes: Mapping[str, _Support]) -> None:
    """Per tube: PCs keep their X, every other fixture moves to the nearest free X (spec 13.10)."""
    for name, tube in tubes.items():
        group = [s for s in w.slots if s.group == name]
        placed: list[tuple[_Slot, tuple[float, float]]] = []
        movable = sorted((s for s in group if s.movable), key=lambda s: PACK_ORDER[s.family])
        for slot in [s for s in group if not s.movable] + movable:
            if slot.movable:
                x = _free_x(w, slot, placed)
                if x is not None:
                    slot.x = x
            span = _slot_span(w, slot, slot.x)
            for other, other_span in placed:
                if _overlaps(span, other_span):
                    w.warn(f"Appareils qui se touchent sur {tube.label} : {other.name} et {slot.name}.")
            placed.append((slot, span))


def _check_stacks(w: _Work) -> None:
    """Alert when posed movers of one tower overlap along Z (spec 13.10)."""
    stacks: dict[str, list[tuple[_Slot, tuple[float, float]]]] = {}
    for s in w.slots:
        if s.family == "tower_movers":
            stacks.setdefault(s.load, []).append((s, _slot_span(w, s, s.x, axis=2)))
    for name, stack in stacks.items():
        for n, (a, span_a) in enumerate(stack):
            for b, span_b in stack[n + 1:]:
                if _overlaps(span_a, span_b):
                    w.warn(f"Appareils qui se touchent sur le pylône {name} : {a.name} et {b.name}.")


# ------------------------------------------------------------ pan/tilt, field

def _fit(phi: float, tau: float, pan: Range, tilt: Range) -> tuple[float, float] | None:
    mid = (pan.min + pan.max) / 2
    reps = [phi + 360 * k for k in range(-3, 4) if pan.min - EPS <= phi + 360 * k <= pan.max + EPS]
    if not reps or not tilt.min - EPS <= tau <= tilt.max + EPS:
        return None
    return min(reps, key=lambda r: abs(r - mid)), tau


def _pan_tilt(fx: Fixture, axis: Vec3) -> tuple[float, float, tuple[float, float] | None]:
    """Physical `(pan, tilt)` for a world direction and the `(pan, tilt)` asked when out of travel."""
    phi, tau = aim_angles(axis)
    ranges = fx.pan_tilt
    if ranges is None:
        return phi, tau, None
    pan_range, tilt_range = ranges
    solution = _fit(phi, tau, pan_range, tilt_range) or _fit(phi + 180, -tau, pan_range, tilt_range)
    if solution is not None:
        return solution[0], solution[1], None
    mid = (pan_range.min + pan_range.max) / 2
    near = min((phi + 360 * k for k in range(-3, 4)), key=lambda r: abs(r - mid))
    return (min(max(near, pan_range.min), pan_range.max),
            min(max(tau, tilt_range.min), tilt_range.max), (phi, tau))


def _solve_pan_tilt(w: _Work, name: str, fx: Fixture, axis: Vec3) -> tuple[float, float]:
    pan, tilt, asked = _pan_tilt(fx, axis)
    if asked is not None:
        w.warn(f"Pan/tilt hors course : {name} demande pan {asked[0]:.1f}°, tilt {asked[1]:.1f}°, "
               f"ramenés à {pan:.1f}° et {tilt:.1f}°.")
    return pan, tilt


def _data_value(data: tuple[int, ...], bits: int) -> float:
    return data[0] / 255 if bits == 8 else (data[0] * 256 + data[1]) / 65535


def _angle_dmx(mode: Mode, attribute: str, rng: Range, angle: float):
    """(reached angle, bytes, normalized value); the angle is exact without such a channel."""
    channel = mode.channel(attribute)
    if channel is None:
        return angle, None, None
    v = min(max(rng.fraction(angle), 0.0), 1.0)
    data = encode(v, channel.bits)
    return rng.lerp(_data_value(data, channel.bits)), data, v


def _zoom_fraction(optics, field_angle: float) -> float:
    rng = optics.field_angle
    z = (field_angle - rng.min) / (rng.max - rng.min) if rng.max > rng.min else 0.0
    return 1.0 - z if optics.zoom_invert else z


def _fit_field(optics, f_req: float, margin: float, forced: float = 0.0):
    """(tube, field, status) with status `ok`, `uncovered` (too narrow) or `wide` (below min zoom)."""
    want = margin * f_req
    if optics.lens_tubes:
        tubes = optics.lens_tubes
        if forced:
            tube = min(tubes, key=lambda t: abs(t.field_angle - forced))
            return tube, tube.field_angle, "ok" if tube.field_angle >= want - EPS else "uncovered"
        fit = [t for t in tubes if t.field_angle >= want - EPS]
        tube = fit[0] if fit else tubes[-1]
        return tube, tube.field_angle, "ok" if fit else "uncovered"
    rng = optics.field_angle
    value = min(max(want, rng.min), rng.max)
    return None, value, "uncovered" if want > rng.max + EPS else "wide" if want < rng.min - EPS else "ok"


def _beam_for(optics, tube, field_angle: float) -> float | None:
    if tube is not None:
        return tube.beam_angle
    if optics.beam_angle is None:
        return None
    rng = optics.field_angle
    z = (field_angle - rng.min) / (rng.max - rng.min) if rng.max > rng.min else 0.0
    return optics.beam_angle.min + z * (optics.beam_angle.max - optics.beam_angle.min)


def _source(optics, tube, f_ref: float) -> tuple[str, float, float]:
    """(kind, z along the beam in the head frame, recess `d`) of the light source (spec 14.3)."""
    r = optics.aperture(tube) / 2
    if optics.beam_type == "profile":
        d = r / math.tan(math.radians(f_ref) / 2)
        return "SPOT", optics.lens_offset - d, d
    return "AREA", optics.lens_offset, 0.0


def _adjusted_field(optics: Optics, field_angle: float) -> tuple[LensTube | None, float]:
    """Lens tube and field of an equalised PC: the nearest tube, or the zoom field held in its range."""
    if optics.lens_tubes:
        tube = min(optics.lens_tubes, key=lambda t: abs(t.field_angle - field_angle))
        return tube, tube.field_angle
    zoom = optics.field_angle
    return None, field_angle if zoom is None else min(max(field_angle, zoom.min), zoom.max)


def _front_row(w: _Work, zone: tuple[float, float]) -> bool:
    return abs(zone[1] - w.zones.ys[0]) < EPS


def _nez_end(w: _Work, xc: float, nominal: float, sign: int, grow: float = 0.0) -> float:
    """X of the nez corner of a row 0 zone on one side (`sign` -1 jardin, +1 cour): the nez width for
    the outermost zone when it is wider than the zone, else the zone edge pushed out by `grow`."""
    ends = w.zones.xs
    wide = sign * w.c.W / 2
    if xc == (ends[0] if sign < 0 else ends[-1]) and (wide - nominal) * sign > 0:
        return wide
    return nominal + sign * grow


def _coverage(w: _Work, zone: tuple[float, float], za: float) -> tuple[Vec3, ...]:
    """Corners of the area a face PC lights (spec 13.7): the zone at `za` plus the overlap. Row 0
    also lights the forestage: its downstage corners are on the floor at the nez, the outer zones
    reach the nez width."""
    zones, overlap = w.zones, w.c.p["front_pc"]["overlap"]
    xc, yr = zone
    x0, x1 = xc - zones.width / 2, xc + zones.width / 2
    hy = zones.depth / 2 * (1 + overlap)
    if not _front_row(w, zone):
        hx = zones.width / 2 * (1 + overlap)
        return tuple((xc + sx * hx, yr + sy * hy, za) for sx in (-1, 1) for sy in (-1, 1))
    grow = (x1 - x0) / 2 * overlap
    x0, x1 = _nez_end(w, xc, x0, -1, grow), _nez_end(w, xc, x1, 1, grow)
    return tuple((x, y, z) for x in (x0, x1) for y, z in ((0.0, w.c.Hp), (yr + hy, za)))


@dataclass(frozen=True)
class _Focus:
    """Aim of a row 0 PC: axis, field and tube, and how much of the nez its beam holds. `reach` is
    the share of the PC's own half of the nez (zone centre to its edge) inside the 50 % angle;
    `in_beam` is False when not even the zone centre point is."""

    axis: Vec3
    field: float
    tube: LensTube | None
    in_beam: bool
    reach: float


def _beam_of(optics: Optics, tube: LensTube | None, field: float) -> float:
    beam = _beam_for(optics, tube, field)
    return field if beam is None else beam


def _fit_beam(optics: Optics, need_field: float, need_beam: float) -> tuple[LensTube | None, float] | None:
    """Smallest `(tube, field)` whose field is at least `need_field` and beam at least `need_beam`,
    interpolating the beam linearly with the zoom; None when the fiche cannot."""
    if optics.lens_tubes:
        return next(((t, t.field_angle) for t in optics.lens_tubes
                     if t.field_angle >= need_field - EPS and t.beam_angle >= need_beam - EPS), None)
    zoom = optics.field_angle
    if zoom is None or need_field > zoom.max + EPS or _beam_of(optics, None, zoom.max) < need_beam - EPS:
        return None
    lo = hi = max(zoom.min, need_field)
    if _beam_of(optics, None, lo) < need_beam - EPS:
        hi = zoom.max
        for _ in range(GOLDEN_STEPS * 2):
            mid = (lo + hi) / 2
            lo, hi = (mid, hi) if _beam_of(optics, None, mid) < need_beam - EPS else (lo, mid)
    return None, hi


def _focus(w: _Work, sheet: _Sheet, zone: tuple[float, float], side: str, pivot: Vec3) -> _Focus:
    """Axis and zoom of a row 0 PC (spec 13.7). The heading is the zone centre's. Among the
    (field, elevation) pairs with the corners of the covered area in the field and the nez points
    in the beam, take the smallest field, then the steepest axis. The nez points are the zone centre
    and a point `reach` of the way to the PC's own edge of the zone; `reach` drops until a pair exists."""
    key = (sheet.fixture.id, zone, side, pivot)
    if key in w.focus:
        return w.focus[key]
    optics, hp = sheet.optics, w.c.Hp
    heading = _unit(_sub((zone[0], zone[1], w.za), pivot))
    flat = math.hypot(heading[0], heading[1])
    dirs = [_sub(c, pivot) for c in _coverage(w, zone, w.za)]
    table = []
    for k in range(1, int(90 / FOCUS_STEP)):
        t = math.radians(k * FOCUS_STEP)
        axis = (heading[0] / flat * math.cos(t), heading[1] / flat * math.cos(t), -math.sin(t))
        table.append((k, axis, 2 * max(_angle_between(axis, d) for d in dirs)))
    xc = zone[0]
    sign = -1 if side == "L" else 1
    edge = _nez_end(w, xc, xc + sign * w.zones.width / 2, sign)
    result = None
    for reach in NEZ_REACH:
        nez = [_sub((xc + reach * (edge - xc), 0.0, hp), pivot), _sub((xc, 0.0, hp), pivot)]
        best = None
        for _, axis, need_field in table:
            fit = _fit_beam(optics, need_field, 2 * max(_angle_between(axis, d) for d in nez))
            if fit is None:
                continue
            if best is None or fit[1] < best[0] - EPS:
                best = (fit[1], fit[0], axis)
            elif fit[1] <= best[0] + EPS:
                best = (best[0], fit[0], axis)  # same field: the steeper axis, scanned later
        if best is not None:
            result = _Focus(best[2], best[0], best[1], True, reach)
            break
    if result is None:
        result = _focus_fallback(optics, table, _sub((xc, 0.0, hp), pivot))
    w.focus[key] = result
    return result


def _focus_fallback(optics: Optics, table, centre: Vec3) -> _Focus:
    """No feasible pair: the widest zoom and the elevation that misses the field or the beam the least."""
    widest = optics.lens_tubes[-1] if optics.lens_tubes else None
    top = optics.widest_field

    def miss(item) -> tuple[float, int]:
        _, axis, need_field = item
        return max(need_field - top, 2 * _angle_between(axis, centre) - _beam_of(optics, widest, top)), -item[0]

    return _Focus(min(table, key=miss)[1], top, widest, False, 0.0)


def _wash_axis(w: _Work, zone: tuple[float, float], za: float, pivot: Vec3,
               sheet: _Sheet | None = None, side: str = "") -> Vec3:
    """Unit axis of a face PC at `pivot`: toward the zone centre. Row 0 keeps that heading and
    lowers the elevation onto the forestage (`_focus`); it needs its `sheet` and `side`."""
    if _front_row(w, zone) and sheet is not None:
        return _focus(w, sheet, zone, side, pivot).axis
    return _unit(_sub((zone[0], zone[1], za), pivot))


def _wash_target(w: _Work, zone: tuple[float, float], za: float, pivot: Vec3,
                 sheet: _Sheet | None = None, side: str = "") -> Vec3:
    """Where the axis of a face PC at `pivot` crosses the aim plane `za`."""
    axis = _wash_axis(w, zone, za, pivot, sheet, side)
    return _add(pivot, _mul(axis, (pivot[2] - za) / -axis[2]))


def _wash_required(w: _Work, zone: tuple[float, float], za: float, pivot: Vec3, axis: Vec3) -> float:
    """Field needed to cover the area of `zone` from `pivot` along `axis`."""
    return 2 * max(_angle_between(axis, _sub(c, pivot)) for c in _coverage(w, zone, za))


def _wash_field(w: _Work, s: _Slot, pivot: Vec3, axis: Vec3, alert: bool = True):
    """Field of a face PC covering its zone plus overlap (spec 13.7); row 0 takes the zoom of its focus.
    `alert` False keeps the coverage and nez alerts quiet (an equalised aim and field are chosen for evenness)."""
    optics = s.sheet.fixture.optics
    f_req = _wash_required(w, s.meta["zone"], s.target[2], pivot, axis)
    tube, value, status = _fit_field(optics, f_req, 1.0)
    if alert and status == "uncovered":
        w.uncovered.append((s.name, f_req, value))
    elif alert and status == "wide":
        w.too_wide.append((s.name, f_req, value))
    if s.meta["row"] == 0:
        focus = _focus(w, s.sheet, s.meta["zone"], s.meta["side"], pivot)
        w.nez_reach.append((s.name, focus.reach))
        if alert and not focus.in_beam:
            w.nez_missed.append(s.name)
        if status != "uncovered":
            tube, value = focus.tube, focus.field
    return tube, value


# ---------------------------------------------------------------- profiles

def _top_target(w: _Work, source: Vec3) -> Vec3:
    """Point of the top cut line: head of a standing actor at the back, or the lintel when lower."""
    c, ya = w.c, w.ya
    lintel = (0.0, c.Ys + PROSCENIUM_RECESS, c.Hp + c.Hc - c.p["profiles"]["lintel_margin"])
    actor = (0.0, ya, c.Hp + c.p["profiles"]["top_height"])
    if abs(actor[1] - source[1]) < EPS:
        return actor
    t = (lintel[1] - source[1]) / (actor[1] - source[1])
    return lintel if source[2] + t * (actor[2] - source[2]) > lintel[2] + EPS else actor


def _cut_planes(w: _Work, third: int, source: Vec3, axis: Vec3) -> dict[str, Vec3]:
    """Unit normals of the four cut planes through `source`, pointing to the dark side."""
    c = w.c
    za = w.za
    b0 = -c.Wc / 2 + third * c.Wc / 3
    lines = {
        "bottom": ((0.0, 0.0, c.Hp), (1.0, 0.0, 0.0)),
        "top": (_top_target(w, source), (1.0, 0.0, 0.0)),
        "left": ((b0, 0.0, za), (0.0, 1.0, 0.0)),
        "right": ((b0 + c.Wc / 3, 0.0, za), (0.0, 1.0, 0.0)),
    }
    return {name: n for name, line in lines.items() if (n := cut_normal(source, line, axis)) is not None}


def _required_field(planes: Mapping[str, Vec3], axis: Vec3) -> float:
    corners = []
    for a in ("bottom", "top"):
        for b in ("left", "right"):
            if a in planes and b in planes:
                d = _cross(planes[a], planes[b])
                if _dot(d, d) > EPS:
                    corners.append(_unit(d) if _dot(d, axis) >= 0 else _mul(_unit(d), -1.0))
    return 2 * max((_angle_between(axis, d) for d in corners), default=0.0)


def _blade_axes(sides: tuple[float, ...], rho: float, xh: Vec3, yh: Vec3):
    out = []
    for side in sides:
        ang = math.radians(side + rho)
        out.append((_add(_mul(xh, math.cos(ang)), _mul(yh, math.sin(ang))),
                    _add(_mul(xh, -math.sin(ang)), _mul(yh, math.cos(ang)))))
    return out


def _insertion(w: _Work, name: str, h: float, open_eff: float, closed: float) -> float:
    span = open_eff - closed
    v = (open_eff - h) / span if abs(span) > EPS else 0.0
    if v < -EPS or v > 1 + EPS:
        w.warn(f"Découpe {name} : lame hors course ({v:.2f} demandé), ramenée dans la plage.")
    return min(max(v, 0.0), 1.0)


def _blade_record(w, name, bl, k, cut, h_c, tan_a, open_eff) -> Blade:
    """One blade from its edge distance and slope; clamps travel and tilt with an alert."""
    e = bl.span / 2
    alpha = math.degrees(math.atan(tan_a))
    if abs(alpha) > bl.angle_limit + EPS:
        w.warn(f"Découpe {name} : lame hors course (inclinaison {alpha:.1f}°, limite "
               f"{bl.angle_limit:g}°).")
        alpha = math.copysign(bl.angle_limit, alpha)
    t = math.tan(math.radians(alpha))
    va = _insertion(w, name, h_c + e * t, open_eff, bl.travel.closed)
    vb = _insertion(w, name, h_c - e * t, open_eff, bl.travel.closed)
    ha = open_eff + va * (bl.travel.closed - open_eff)
    hb = open_eff + vb * (bl.travel.closed - open_eff)
    return Blade(k + 1, cut, bl.sides[k], h_c, alpha, ha, hb, va, vb)


def _blade_set(w: _Work, s: _Slot, bl: Blades, source: Vec3, axis, frame, f_ref: float, d: float,
               source_z: float) -> BladeSet:
    """Blades `bl` of a profile: cut planes (auto) or manual setting (spec 13.8)."""
    p = w.c.p["profiles"]
    xh, yh, _ = frame
    g = max(d - bl.gate_from_lens, GATE_MIN_RATIO * d)
    open_eff = max(bl.travel.open, g * math.tan(math.radians(f_ref) / 2))
    manual = s.family == "profiles" and p["blades_mode"] == "manual"
    tag = "lcr"[s.meta.get("third", 0)]
    rho = p[f"{tag}_rotation"] if manual else 0.0
    axes = _blade_axes(bl.sides, rho, xh, yh)
    blades: list[Blade] = []
    if manual:
        for k in range(4):
            v = p[f"{tag}_blade_{k + 1}_insertion"]
            h = open_eff + v * (bl.travel.closed - open_eff)
            blades.append(_blade_record(w, s.name, bl, k, "", h,
                                        math.tan(math.radians(p[f"{tag}_blade_{k + 1}_angle"])),
                                        open_eff))
    else:
        planes = _cut_planes(w, s.meta["third"], source, axis) if s.family == "profiles" else {}
        owner: dict[int, str] = {}
        for cut in CUT_NAMES:
            if cut not in planes:
                continue
            n = planes[cut]
            perp = _sub(n, _mul(axis, _dot(n, axis)))
            k = max(range(4), key=lambda i: (_dot(axes[i][0], perp), -i))
            if k in owner or _dot(n, axes[k][0]) < EPS:
                w.warn(f"Découpe {s.name} : lames de la fiche non adaptées au cadrage.")
                continue
            owner[k] = cut
        for k in range(4):
            if k not in owner:
                blades.append(_blade_record(w, s.name, bl, k, "", open_eff, 0.0, open_eff))
                continue
            n, (o, q) = planes[owner[k]], axes[k]
            no = _dot(n, o)
            blades.append(_blade_record(w, s.name, bl, k, owner[k], -g * _dot(n, axis) / no,
                                        _dot(n, q) / no, open_eff))
    return BladeSet(source_z + g, g, open_eff, rho, bl.span / 2, tuple(blades))


def _profile_optics(w: _Work, s: _Slot, pivot: Vec3, axis: Vec3, frame):
    """Tube, field, source and blades of a découpe (spec 13.8)."""
    fx, optics = s.sheet.fixture, s.sheet.optics
    planes = _cut_planes(w, s.meta["third"], pivot, axis)
    f_req = _required_field(planes, axis)
    forced = w.c.p["profiles"]["tube_angle"]
    tube, value, status = _fit_field(optics, f_req, TUBE_MARGIN, forced)
    if status == "uncovered":
        w.warn(f"Découpe {s.name} : aucun tube ne couvre le cadrage (champ requis {f_req:.1f}°).")
    kind, source_z, d = _source(optics, tube, value)
    source = _add(pivot, _mul(axis, source_z))
    blades = None
    if fx.blades is not None:
        blades = _blade_set(w, s, fx.blades, source, axis, frame, value, d, source_z)
    return tube, value, kind, source_z, source, blades


# ----------------------------------------------------------------- rest values

def _clamp01(v: float) -> float:
    return min(max(v, 0.0), 1.0)


def _cct_value(channel: Channel, rng: Range, kelvin: float) -> float:
    """Normalized `v` whose 8/16-bit rounding reads closest to `kelvin` through the channel curve."""
    if not channel.curve:
        return _clamp01(rng.fraction(kelvin))
    points = channel.curve
    candidates = {x for x, _ in points}
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if y0 != y1 and min(y0, y1) <= kelvin <= max(y0, y1):
            candidates.add(x0 + (kelvin - y0) / (y1 - y0) * (x1 - x0))

    def error(v: float) -> float:
        reached = _data_value(encode(v, channel.bits), channel.bits)
        return abs(channel.physical(reached, rng) - kelvin)

    return min(sorted(candidates, reverse=True), key=error)


def _emitter_mix(emitters, target) -> list[float]:
    """Non-negative weights (<= 1) whose mix of emitter colours approximates `target`."""
    weights = [0.0] * len(emitters)
    for _ in range(200):
        for k, em in enumerate(emitters):
            rest = [target[i] - sum(weights[m] * emitters[m].rgb[i] for m in range(len(emitters))
                                    if m != k) for i in range(3)]
            den = sum(c * c for c in em.rgb)
            weights[k] = _clamp01(sum(em.rgb[i] * rest[i] for i in range(3)) / den) if den else 0.0
    return weights


def _colour_overrides(w: _Work, s: _Slot, kelvin: float, done: set) -> dict[str, float]:
    fx, mode = s.sheet.fixture, s.sheet.mode
    colour = fx.colour
    out: dict[str, float] = {}
    channel = mode.channel("cct")
    if channel is not None and colour.cct_range is not None:
        rng = colour.cct_range
        wanted = min(max(kelvin, rng.min), rng.max)
        if wanted != kelvin and (fx.id, kelvin) not in done:
            done.add((fx.id, kelvin))
            w.warn(f"Température de couleur de repos {kelvin:g} K hors de la plage de la fiche "
                   f"« {fx.id} » ({rng.min:g} à {rng.max:g} K) : ramenée à {wanted:g} K.")
        out["cct"] = _cct_value(channel, rng, wanted)
        return out
    r, g, b = cct_to_rgb(kelvin)
    if mode.channel("color_r") is not None:
        out.update(color_r=r, color_g=g, color_b=b, color_w=0.0)
    elif mode.channel("cyan") is not None:
        out.update(cyan=1 - r, magenta=1 - g, yellow=1 - b)
    elif colour.emitters:
        for em, weight in zip(colour.emitters, _emitter_mix(colour.emitters, (r, g, b))):
            out[em.attribute] = weight
    return out


# ---------------------------------------------------------------- fixtures

def _levels(p: Mapping) -> dict[str, float]:
    rest = p["rest"]
    return {"front_pc": rest["pc_level"], "profiles": rest["profile_level"],
            "backlight": rest["mover_level"], "front_movers": rest["mover_level"],
            "tower_movers": rest["mover_level"], "hazer": rest["haze_level"]}


def _channel_values(s: _Slot, overrides: Mapping[str, float]) -> tuple[ChannelValue, ...]:
    out = []
    for ch in s.sheet.mode.channels:
        v = overrides.get(ch.attribute, ch.default_normalized)
        fine = None if ch.fine is None else s.address + ch.fine - 1
        out.append(ChannelValue(ch.attribute, s.address + ch.offset - 1, fine, ch.bits, v,
                                encode(v, ch.bits)))
    return tuple(out)


def _pc_cut_lines(w: _Work, s: _Slot) -> dict[str, tuple[Vec3, Vec3]]:
    """Target lines of the barn door cuts of a face PC (spec 13.12): row 0 keeps the light off the
    stage front, the lintel, and the sides of the forestage (a PC hung beside the frame cuts on the
    inner edge of the post instead); the other rows stay within the masking opening and below the
    first border upstage of their zone."""
    c, zone = w.c, s.meta["zone"]
    if s.meta["row"] == 0:
        lines = {"bottom": ((0.0, 0.0, c.Hp), (1.0, 0.0, 0.0)),
                 "top": ((0.0, c.Ys + PROSCENIUM_RECESS, c.Hp + c.Hc), (1.0, 0.0, 0.0))}
        for name, sign in (("left", -1), ("right", 1)):
            outside = s.x * sign > c.Wc / 2
            lines[name] = (((sign * c.Wc / 2, c.Ys + PROSCENIUM_RECESS, 0.0), (0.0, 0.0, 1.0)) if outside
                           else ((sign * c.W / 2, 0.0, c.Hp), (0.0, 1.0, 0.0)))
        return lines
    half = min(c.p["masking"]["opening"], c.Wk) / 2
    lines = {"left": ((-half, zone[1], 0.0), (0.0, 0.0, 1.0)), "right": ((half, zone[1], 0.0), (0.0, 0.0, 1.0))}
    far = zone[1] + w.zones.depth / 2 * (1 + c.p["front_pc"]["overlap"])
    borders = [b for b in w.walls if not b.is_leg and b.a[1] >= far - EPS]
    if borders:
        border = min(borders, key=lambda b: b.a[1])
        lines["top"] = ((0.0, border.a[1] - border.half, border.z0 - BEAM_MARGIN), (1.0, 0.0, 0.0))
    return lines


def _pc_doors(w: _Work, s: _Slot, pivot: Vec3, frame, field_angle: float) -> BarnDoorSet | None:
    """Barn doors of a face PC: closed on the cut lines (auto) or as set in the params (manual)."""
    node, doors = w.c.p["front_pc"], s.sheet.fixture.barn_doors
    if doors is None or node["barn_doors"] == "none":
        return None
    offset = s.sheet.optics.lens_offset
    if node["barn_doors"] == "manual":
        prefix = f"row{s.meta['row'] + 1}_{s.meta['side'].lower()}_"
        return manual_set(doors, offset, frame, [node[f"{prefix}leaf_{k}"] for k in range(1, 5)],
                          node[f"{prefix}rotation"])
    lens = _add(pivot, _mul(frame[2], offset))
    result, dropped = auto_set(doors, offset, frame, lens, field_angle, _pc_cut_lines(w, s))
    if dropped:
        w.doors_misfit.append(s.name)
    if not all(leaf.reached for leaf in result.leaves):
        w.doors_short.append(s.name)
    return result


def _build_hazer(w: _Work, s: _Slot, levels) -> RigFixture:
    over = {"haze_density": levels["hazer"]}
    here = (s.x, s.y, s.z)
    return RigFixture(s.name, s.family, s.sheet.fixture.id, s.sheet.mode.name, "", here, here,
                      (0.0, 0.0, 0.0), here, here, (0.0, 0.0, 1.0), False, None, None, None, None,
                      None, None, None, None, "", 0.0, here, None, None, None, s.universe,
                      s.address, s.sheet.mode.footprint, _channel_values(s, over),
                      s.sheet.fixture.physical.weight, 0.0)


def _build_fixture(w: _Work, s: _Slot, levels, done: set) -> RigFixture:
    if s.family == "hazer":
        return _build_hazer(w, s, levels)
    fx, mode, p = s.sheet.fixture, s.sheet.mode, w.c.p
    optics, mount = s.sheet.optics, s.sheet.mount
    root = (s.x, s.y, s.z - mount.hook_height)
    pivot = (s.x, s.y, root[2] - mount.tilt_axis_height)
    adj = w.adjust.get(s.name) if s.family == "front_pc" else None
    if adj is not None:
        s.target = _add(pivot, _mul(adj.axis, (pivot[2] - s.target[2]) / -adj.axis[2]))
    pan, tilt = _solve_pan_tilt(w, s.name, fx, _unit(_sub(s.target, pivot)))
    ranges = fx.pan_tilt
    moving = ranges is not None
    over: dict[str, float] = {"dimmer": levels[s.family] * (1.0 if adj is None else adj.level)}
    pan_data = tilt_data = None
    if ranges is not None:
        pan, pan_data, pv = _angle_dmx(mode, "pan", ranges[0], pan)
        tilt, tilt_data, tv = _angle_dmx(mode, "tilt", ranges[1], tilt)
        over.update({k: v for k, v in (("pan", pv), ("tilt", tv)) if v is not None})
    frame = head_frame(pan, tilt)
    axis = frame[2]
    tube, field_angle, kind, source_z, blades, doors = None, None, "", 0.0, None, None
    source = pivot
    kelvin = None
    if s.family == "front_pc":
        tube, field_angle = _wash_field(w, s, pivot, axis, adj is None)
        if adj is not None:
            tube, field_angle = _adjusted_field(optics, adj.zoom_field)
        kind, source_z, _ = _source(optics, tube, field_angle)
        source = _add(pivot, _mul(axis, source_z))
        doors = _pc_doors(w, s, pivot, frame, field_angle)
        if mode.channel("zoom") is not None and optics.field_angle is not None:
            over["zoom"] = _zoom_fraction(optics, field_angle)
        kelvin = p["rest"]["cct_left" if s.meta["side"] == "L" else "cct_right"]
    elif s.family == "profiles":
        tube, field_angle, kind, source_z, source, blades = _profile_optics(w, s, pivot, axis, frame)
        kelvin = p["rest"]["cct_profile"]
        if blades is not None and fx.blades is not None and fx.blades.mode == "motorised":
            over.update(_blade_rest(fx.blades, blades))
    else:
        field_angle = _mover_field(mode, optics)
        tube = None
        f_ref = optics.widest_field
        kind, source_z, d = _mover_source(optics)
        source = _add(pivot, _mul(axis, source_z))
        if fx.blades is not None:
            blades = _blade_set(w, s, fx.blades, source, axis, frame, f_ref, d, source_z)
    if kelvin is not None:
        over.update(_colour_overrides(w, s, kelvin, done))
    return RigFixture(
        s.name, s.family, fx.id, mode.name, s.load, (s.x, s.y, s.z), root, (math.pi, 0.0, 0.0),
        pivot, s.target, axis, moving, pan, tilt, pan_data, tilt_data, field_angle,
        _beam_for(optics, tube, field_angle), tube.name if tube else None, optics.aperture(tube),
        kind, source_z, source, blades, s.circuit, kelvin, s.universe, s.address, mode.footprint,
        _channel_values(s, over), fx.physical.weight, s.width, doors)


def _mover_source(optics: Optics) -> tuple[str, float, float]:
    """Source of a moving head, taken at its widest field (spec 14.3)."""
    return _source(optics, None if optics.field_angle else optics.lens_tubes[-1], optics.widest_field)


def _mover_field(mode: Mode, optics: Optics) -> float:
    zoom_range = optics.field_angle
    if zoom_range is None:
        return optics.lens_tubes[-1].field_angle
    zoom = mode.channel("zoom")
    if zoom is None:
        return zoom_range.max
    z = 1.0 - zoom.default_normalized if optics.zoom_invert else zoom.default_normalized
    return zoom_range.min + z * (zoom_range.max - zoom_range.min)


def _blade_rest(sheet: Blades, blades: BladeSet) -> dict[str, float]:
    out: dict[str, float] = {}
    for blade in blades.blades:
        out[f"blade_{blade.index}a"] = blade.insertion_a
        out[f"blade_{blade.index}b"] = blade.insertion_b
    rot = sheet.rotation
    if rot is not None:
        out["blade_rot"] = _clamp01(rot.fraction(blades.rotation))
    return out


# ---------------------------------------------------------------- clearance

@dataclass(frozen=True)
class _Cylinder:
    """Swept envelope of a moving head: a vertical cylinder, margin included (spec 13.10)."""

    x: float
    y: float
    radius: float
    low: float
    high: float


@dataclass(frozen=True)
class _Body:
    """A fixture seen as an obstacle: sample points, their bounding sphere, `reach` for a mover."""

    name: str
    support: str
    points: tuple[Vec3, ...]
    centre: Vec3
    radius: float
    reach: _Cylinder | None = None


@dataclass(frozen=True)
class _Beam:
    """Cone of a fixture aimed at `target`: apex, unit axis, half angle (as cos and sin). Only the
    part from `start` (the lens plane) to `length` (the target, 30 m at most) along the axis counts.
    `cuts` are the normals of the barn door planes through the apex: nothing beyond them is lit."""

    owner: str
    target: Vec3
    apex: Vec3
    axis: Vec3
    cos: float
    sin: float
    start: float
    length: float
    cuts: tuple[Vec3, ...] = ()


def _make_beam(owner: str, target: Vec3, apex: Vec3, axis: Vec3, field_angle: float, start: float,
               cuts: tuple[Vec3, ...] = ()) -> _Beam:
    half = math.radians(field_angle) / 2
    length = min(BEAM_RANGE, _dot(_sub(target, apex), axis))
    return _Beam(owner, target, apex, axis, math.cos(half), math.sin(half), start, length, cuts)


def _cloud(name: str, support: str, points, reach: _Cylinder | None = None) -> _Body:
    points = tuple(points)
    lo = [min(p[i] for p in points) for i in range(3)]
    hi = [max(p[i] for p in points) for i in range(3)]
    centre = tuple((a + b) / 2 for a, b in zip(lo, hi))
    return _Body(name, support, points, centre, max(math.dist(p, centre) for p in points), reach)


def _grid(corners: tuple[Vec3, ...]) -> tuple[Vec3, ...]:
    """27 samples (corners, edge middles, face centres, centre) of the box whose 8 corners are given."""
    if not corners:
        return ()
    lo, hi = corners[0], corners[-1]
    axes = [(lo[i], (lo[i] + hi[i]) / 2, hi[i]) for i in range(3)]
    return tuple((x, y, z) for x in axes[0] for y in axes[1] for z in axes[2])


def _body_at(w: _Work, name: str, support: str, root: Vec3, pan: float, tilt: float, sheet: _Sheet) -> _Body:
    boxes = _boxes(w, sheet)
    if boxes is None:
        d, (x, y, z) = sheet.dimensions, root
        points = _grid(tuple((x + sx * d.width / 2, y + sy * d.depth / 2, z - sz * d.height)
                             for sx in (-1, 1) for sy in (-1, 1) for sz in (0, 1)))
    else:
        dense = _Boxes(_grid(boxes.base), _grid(boxes.pan), _grid(boxes.tilt), boxes.pivot)
        points = posed_points(dense, root, pan, tilt)
    return _cloud(name, support, points)


def _static_body(w: _Work, f: RigFixture, sheet: _Sheet) -> _Body:
    return _body_at(w, f.name, f.support, f.root, f.pan or 0.0, f.tilt or 0.0, sheet)


def _slot_body(w: _Work, s: _Slot) -> _Body:
    """Body of a static slot at its planned place and aim, before it is built."""
    mount = s.sheet.mount
    root = (s.x, s.y, s.z - mount.hook_height)
    pivot = (s.x, s.y, root[2] - mount.tilt_axis_height)
    pan, tilt, _ = _pan_tilt(s.sheet.fixture, _unit(_sub(s.target, pivot)))
    return _body_at(w, s.name, s.group, root, pan, tilt, s.sheet)


def _mover_body(w: _Work, s: _Slot) -> _Body:
    """Swept envelope of a moving head as a cylinder sampled on three levels and two rings."""
    env = _envelope(w, s.sheet)
    top = s.z - s.sheet.mount.hook_height
    r = env.radius + FOOTPRINT_MARGIN
    low, high = top - env.high - FOOTPRINT_MARGIN, top - env.low + FOOTPRINT_MARGIN
    ring = [(math.cos(k * math.pi / 6), math.sin(k * math.pi / 6)) for k in range(12)]
    points = [(s.x + k * r * c, s.y + k * r * sn, z) for z in (low, (low + high) / 2, high)
              for k, c, sn in [(0.0, 1.0, 0.0)] + [(k, c, sn) for k in (0.5, 1.0) for c, sn in ring]]
    return _cloud(s.name, s.load, points, _Cylinder(s.x, s.y, r, low, high))


def _grid_targets(w: _Work) -> list[Vec3]:
    return [(fx * w.c.Wc, fy * w.ya, w.za) for fy in GRID_Y for fx in GRID_X]


def _mover_beams(w: _Work, s: _Slot) -> list[_Beam]:
    """Beams of a moving head at its rest aim; front movers add the 3 x 3 grid of the play area."""
    fx, optics, mount = s.sheet.fixture, s.sheet.optics, s.sheet.mount
    pivot = (s.x, s.y, s.z - mount.hook_height - mount.tilt_axis_height)
    field_angle, source_z = _mover_field(s.sheet.mode, optics), _mover_source(optics)[1]
    start = optics.lens_offset - source_z
    out = []
    for target in [s.target] + (_grid_targets(w) if s.family == "front_movers" else []):
        pan, tilt, _ = _pan_tilt(fx, _unit(_sub(target, pivot)))
        axis = head_frame(pan, tilt)[2]
        out.append(_make_beam(s.name, target, _add(pivot, _mul(axis, source_z)), axis, field_angle, start))
    return out


def _scene(w: _Work, slots, built: Mapping[str, RigFixture]) -> tuple[list[_Beam], list[_Body]]:
    """Beams and obstacle bodies of `slots`; static fixtures come from their built record."""
    beams: list[_Beam] = []
    bodies: list[_Body] = []
    for s in slots:
        if s.family == "hazer":
            continue
        if s.sheet.fixture.pan_tilt is not None:
            beams += _mover_beams(w, s)
            bodies.append(_mover_body(w, s))
            continue
        f = built[s.name]
        bodies.append(_static_body(w, f, s.sheet))
        if f.field_angle is not None:
            cuts = f.barn_doors.normals if f.barn_doors else ()
            beams.append(_make_beam(f.name, f.aim, f.source, f.axis, f.field_angle,
                                    s.sheet.optics.lens_offset - f.source_z, cuts))
    return beams, bodies


def _cone_gap(beam: _Beam, p: Vec3) -> float:
    """Signed distance from `p` to the side of the cone, negative inside (a lower bound outside)."""
    v = _sub(p, beam.apex)
    a = _dot(v, beam.axis)
    return math.sqrt(max(_dot(v, v) - a * a, 0.0)) * beam.cos - a * beam.sin


def _body_gap(beam: _Beam, body: _Body) -> float | None:
    """Smallest cone gap of the body's points between the lens and the end of the beam, else None.
    A body farther than `BEAM_NEAR` from the cone is skipped (`_cone_gap` is 1-Lipschitz)."""
    if _cone_gap(beam, body.centre) - body.radius >= BEAM_NEAR:
        return None
    return _min_gap(beam, body.points)


def _min_gap(beam: _Beam, points) -> float | None:
    """Smallest cone gap of the points that lie between the lens and the end of the beam."""
    (ox, oy, oz), (ax, ay, az), cos, sin = beam.apex, beam.axis, beam.cos, beam.sin
    best = None
    for x, y, z in points:
        x, y, z = x - ox, y - oy, z - oz
        a = x * ax + y * ay + z * az
        if a <= beam.start or a > beam.length:
            continue
        if any(n[0] * x + n[1] * y + n[2] * z > EPS for n in beam.cuts):
            continue
        gap = math.sqrt(max(x * x + y * y + z * z - a * a, 0.0)) * cos - a * sin
        if best is None or gap < best:
            best = gap
    return best


@dataclass(frozen=True)
class _Tile:
    """A piece of a border: the sphere around it and sample `points` of its mid surface."""

    centre: Vec3
    radius: float
    points: tuple[Vec3, ...]


@dataclass(frozen=True)
class _Wall:
    """A border (cut into `tiles`, pleat depth as thickness) or a leg (path `a` inner end to `b`, flat,
    no tiles) as a vertical wall between `z0` and `z1`; `low` and `high` bound it (spec 13.11)."""

    name: str
    a: tuple[float, float]
    b: tuple[float, float]
    z0: float
    z1: float
    half: float
    low: Vec3
    high: Vec3
    tiles: tuple[_Tile, ...] = ()

    @property
    def is_leg(self) -> bool:
        return self.name.startswith("Leg_")


def _walls(c: Ctx) -> tuple[_Wall, ...]:
    """The borders and legs drawn by the masking; borders are cut into tiles of `WALL_TILE` metres."""
    walls = []
    for o in _masking(c).objects:
        if not isinstance(o, PleatedSurface) or not o.name.startswith(("Border_", "Leg_")):
            continue
        half = PLEAT_AMPLITUDE * MAX_DEPTH_FACTOR if o.name.startswith("Border_") else 0.0
        (x0, y0), (x1, y1) = o.state.p0, o.state.p1
        tiles = []
        if o.name.startswith("Border_"):
            nu = max(1, math.ceil(math.hypot(x1 - x0, y1 - y0) / WALL_TILE - EPS))
            nz = max(1, math.ceil((o.z1 - o.z0) / WALL_TILE - EPS))
            for i in range(nu):
                a = (x0 + (x1 - x0) * i / nu, y0 + (y1 - y0) * i / nu)
                b = (x0 + (x1 - x0) * (i + 1) / nu, y0 + (y1 - y0) * (i + 1) / nu)
                for k in range(nz):
                    z0, z1 = o.z0 + (o.z1 - o.z0) * k / nz, o.z0 + (o.z1 - o.z0) * (k + 1) / nz
                    centre = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, (z0 + z1) / 2)
                    tiles.append(_Tile(centre, math.hypot(math.dist(a, b) / 2, (z1 - z0) / 2, half),
                                       tuple(_tile_points(a, b, z0, z1))))
        low = (min(x0, x1) - half, min(y0, y1) - half, o.z0)
        high = (max(x0, x1) + half, max(y0, y1) + half, o.z1)
        walls.append(_Wall(o.name, (x0, y0), (x1, y1), o.z0, o.z1, half, low, high, tuple(tiles)))
    return tuple(walls)


def _tile_points(a, b, z0: float, z1: float):
    """Samples of a tile's mid surface, every `WALL_STEP` along the path and in height."""
    length = math.dist(a, b)
    nu = max(1, math.ceil(length / WALL_STEP - EPS))
    nz = max(1, math.ceil((z1 - z0) / WALL_STEP - EPS))
    for i in range(nu + 1):
        for k in range(nz + 1):
            yield (a[0] + (b[0] - a[0]) * i / nu, a[1] + (b[1] - a[1]) * i / nu, z0 + (z1 - z0) * k / nz)


def _core(beam: _Beam) -> _Beam:
    """The beam narrowed to `MASK_CONE` of its half angle: the bright core met by a border."""
    half = math.atan2(beam.sin, beam.cos) * MASK_CONE
    return replace(beam, cos=math.cos(half), sin=math.sin(half))


def _border_gap(beam: _Beam, wall: _Wall) -> float | None:
    """Cone gap to the mid surface of a border, less its half thickness."""
    best = None
    for tile in wall.tiles:
        if _cone_gap(beam, tile.centre) - tile.radius >= BEAM_NEAR:
            continue
        gap = _min_gap(beam, tile.points)
        if gap is not None and (best is None or gap < best):
            best = gap
    return None if best is None else best - wall.half


def _leg_gap(beam: _Beam, wall: _Wall) -> float:
    """Signed distance (negative inside) from the aim line to a leg whose inner end is pulled back
    by `LEG_GRAZE`. The distance to a box is convex along a line: golden-section search."""
    (x0, y0), (x1, y1) = wall.a, wall.b
    length = math.hypot(x1 - x0, y1 - y0)
    ux, uy = (x1 - x0) / length, (y1 - y0) / length
    ax, ay, az = _add(beam.apex, _mul(beam.axis, beam.start))
    span = beam.length - beam.start
    dx, dy, dz = (c * span for c in beam.axis)

    def gap(t: float) -> float:
        px, py, pz = ax + dx * t - x0, ay + dy * t - y0, az + dz * t
        u, v = px * ux + py * uy, abs(-px * uy + py * ux)
        du, dz_ = max(LEG_GRAZE - u, u - length), max(wall.z0 - pz, pz - wall.z1)
        if du < 0 and v < 0 and dz_ < 0:
            return max(du, v, dz_)
        return math.hypot(max(du, 0.0), v, max(dz_, 0.0))

    lo, hi = 0.0, 1.0
    t1, t2 = hi - GOLDEN * (hi - lo), lo + GOLDEN * (hi - lo)
    g1, g2 = gap(t1), gap(t2)
    for _ in range(GOLDEN_STEPS):
        if g1 < g2:
            hi, t2, g2 = t2, t1, g1
            t1 = hi - GOLDEN * (hi - lo)
            g1 = gap(t1)
        else:
            lo, t1, g1 = t1, t2, g2
            t2 = lo + GOLDEN * (hi - lo)
            g2 = gap(t2)
    return min(g1, g2, gap(0.0), gap(1.0))


def _masked_by(leg: _Wall, target: Vec3) -> bool:
    """Whether the target lies on the wing side of the leg's inner end, out of the visible stage."""
    inner = min(abs(leg.a[0]), abs(leg.b[0]))
    return target[0] * leg.a[0] > 0 and abs(target[0]) >= inner


def _wall_gap(beam: _Beam, wall: _Wall) -> float | None:
    """Gap of a beam to a border (bright core cone) or a leg (aim line), None when `BEAM_NEAR` away."""
    if wall.is_leg and _masked_by(wall, beam.target):
        return None
    beam = beam if wall.is_leg else _core(beam)
    length = max(beam.length, 0.0)
    end = _add(beam.apex, _mul(beam.axis, length))
    reach = (0.0 if wall.is_leg else length * beam.sin / beam.cos) + BEAM_NEAR
    for i in range(3):
        if (max(beam.apex[i], end[i]) + reach < wall.low[i]
                or min(beam.apex[i], end[i]) - reach > wall.high[i]):
            return None
    return _leg_gap(beam, wall) if wall.is_leg else _border_gap(beam, wall)


def _wall_gaps(beams: list[_Beam], walls) -> list[tuple[_Beam, str, float]]:
    return [(beam, wall.name, gap) for beam in beams for wall in walls
            if (gap := _wall_gap(beam, wall)) is not None]


def _wall_label(name: str) -> str:
    return f"{'le pendrillon' if name.startswith('Leg_') else 'la frise'} {name}"


def _gaps(beams: list[_Beam], bodies: list[_Body]) -> list[tuple[_Beam, _Body, float]]:
    return [(beam, body, gap) for beam in beams for body in bodies
            if body.name != beam.owner and (gap := _body_gap(beam, body)) is not None]


def _inside(c: _Cylinder, p: Vec3) -> bool:
    return math.hypot(p[0] - c.x, p[1] - c.y) < c.radius and c.low < p[2] < c.high


def _touch(a: _Body, b: _Body) -> bool:
    """Whether the swept envelope of `a` meets `b` (an envelope or the points of a posed body)."""
    if math.dist(a.centre, b.centre) > a.radius + b.radius:
        return False
    if a.reach is None:
        a, b = b, a
    if (ca := a.reach) is None:
        return False
    if (cb := b.reach) is None:
        return any(_inside(ca, p) for p in b.points)
    return (math.hypot(ca.x - cb.x, ca.y - cb.y) < ca.radius + cb.radius
            and ca.low < cb.high and cb.low < ca.high)


def _reach_hits(first: list[_Body], second: list[_Body]) -> list[tuple[_Body, _Body]]:
    """Pairs on different supports where a swept envelope meets the other body."""
    hits: dict[tuple[str, str], tuple[_Body, _Body]] = {}
    for a in first:
        for b in second:
            if a.support != b.support and (a.reach or b.reach) and _touch(a, b):
                hits[(min(a.name, b.name), max(a.name, b.name))] = (a, b)
    return list(hits.values())


def _movers_height(w: _Work, pipe: _Support, slots, built: Mapping[str, RigFixture]) -> float:
    """Height of the second pipe (spec 13.2 bis): manual, or the highest one that clears every beam."""
    rf = w.c.p["rig_front"]
    if rf["movers_height_mode"] == "manual":
        return rf["movers_z"]
    movers = [s for s in slots if s.family == "front_movers"]
    fixed_beams, fixed = _scene(w, [s for s in slots if s.family != "front_movers"], built)
    low = w.c.Hp + w.c.Hc
    steps = max(0, int((pipe.z - low) / HEIGHT_STEP + EPS))
    best_score, best_z = (math.inf, 0.0), pipe.z
    for z in (pipe.z - k * HEIGHT_STEP for k in range(steps + 1)):
        for s in movers:
            s.z = z
        beams, bodies = _scene(w, movers, built)
        gaps = [g for *_, g in _gaps(beams, fixed + bodies) + _gaps(fixed_beams, bodies)]
        gaps += [g for *_, g in _wall_gaps(beams, w.walls)]
        failed = len(_reach_hits(bodies, fixed + bodies)) + sum(g < BEAM_MARGIN for g in gaps)
        if not failed:
            return z
        score = (failed, -min(gaps, default=0.0))
        if score < best_score:
            best_score, best_z = score, z
    w.warn(f"Perche des mobiles de face : aucune hauteur de {_metres(pipe.z)} à {_metres(low)} ne "
           f"dégage les faisceaux et les appareils, hauteur retenue {_metres(best_z)}.")
    return best_z


def _point(p: Vec3) -> str:
    return "(" + " ; ".join(f"{v:.2f}".replace(".", ",") for v in p) + ")"


def _beam_alerts(w: _Work, hits, noun: str) -> None:
    """One alert per beam closer than the margin (the worst `MAX_BEAM_ALERTS`, then a count)."""
    failing = sorted((h for h in hits if h[2] < BEAM_MARGIN), key=lambda h: h[2])
    for beam, name, gap in failing[:MAX_BEAM_ALERTS]:
        w.warn(f"Faisceau de {beam.owner} vers {_point(beam.target)} gêné par {name} : jeu "
               f"{_metres(gap)} pour {_metres(BEAM_MARGIN)} minimum.")
    if len(failing) > MAX_BEAM_ALERTS:
        w.warn(f"Faisceaux : {len(failing) - MAX_BEAM_ALERTS} autres gênés par {noun}.")


def _clearance_alerts(w: _Work, slots, built: Mapping[str, RigFixture]) -> tuple[float | None, float | None]:
    """Alert on every beam closer than the margin to a body, a border or a leg, and on every
    envelope that meets a body (spec 13.11); returns the smallest gap to a body and to the masking."""
    beams, bodies = _scene(w, slots, built)
    gaps = _gaps(beams, bodies)
    _beam_alerts(w, [(b, body.name, g) for b, body, g in gaps], "un appareil")
    walls = _wall_gaps(beams, w.walls)
    _beam_alerts(w, [(b, _wall_label(name), g) for b, name, g in walls], "une frise ou un pendrillon")
    for a, b in _reach_hits(bodies, bodies):
        w.warn(f"Débattement de pan et tilt : {a.name} et {b.name} se touchent.")
    return (min((g for *_, g in gaps), default=None), min((g for *_, g in walls), default=None))


# ----------------------------------------------------------- patch and totals

def _assign_addresses(w: _Work) -> None:
    patch = w.c.p["patch"]
    for key, _, _ in PATCH_FAMILIES:
        address = patch[f"{key}_address"]
        for s in (s for s in w.slots if s.family == key):
            s.universe, s.address = patch[f"{key}_universe"], address
            address += s.sheet.mode.footprint


def _check_patch(w: _Work, entries: list[PatchEntry]) -> None:
    over = sorted({e.universe for e in entries if e.last > MAX_CHANNEL})
    for u in over:
        w.warn(f"Patch : l'univers {u} dépasse {MAX_CHANNEL} canaux.")
    shown = hidden = 0
    for i, a in enumerate(entries):
        for b in entries[i + 1:]:
            if a.universe != b.universe or a.last < b.address or b.last < a.address:
                continue
            if shown < MAX_PATCH_ALERTS:
                shown += 1
                w.warn(f"Patch : {a.name} et {b.name} se recouvrent, univers {a.universe}, canaux "
                       f"{max(a.address, b.address)} à {min(a.last, b.last)}.")
            else:
                hidden += 1
    if hidden:
        w.warn(f"Patch : {hidden} autres recouvrements.")


def _support_order(name: str) -> tuple[int, str]:
    return (0 if name.startswith("FrontPipe") else 1 if name.startswith("Batten") else 2, name)


def _loads(fixtures: list[RigFixture]) -> tuple[SupportLoad, ...]:
    totals: dict[str, list] = {}
    for f in fixtures:
        if f.support:
            entry = totals.setdefault(f.support, [0.0, 0])
            entry[0] += f.weight
            entry[1] += 1
    return tuple(SupportLoad(n, t[0], t[1]) for n, t in sorted(totals.items(),
                                                                key=lambda kv: _support_order(kv[0])))


def _rest_map(fixtures: list[RigFixture]) -> dict[tuple[int, int], float]:
    out: dict[tuple[int, int], float] = {}
    for f in fixtures:
        for cv in f.channels:
            channels = (cv.channel,) if cv.fine_channel is None else (cv.channel, cv.fine_channel)
            for channel, byte in zip(channels, cv.data):
                if channel <= MAX_CHANNEL:
                    out[(f.universe, channel)] = byte / 255
    return out


def _haze_link(w: _Work, fixtures: list[RigFixture]) -> HazeLink | None:
    hazer = next((f for f in fixtures if f.family == "hazer"), None)
    if hazer is None:
        return None
    cv = next((v for v in hazer.channels if v.attribute == "haze_density"), None)
    if cv is None:
        w.warn(f"Hazer « {hazer.fixture_id} » : le mode « {hazer.mode} » n'a pas de canal haze_density, "
               "densité non pilotée.")
        return None
    prop = lambda ch: f"dmx_{hazer.universe}_{ch}"
    return HazeLink(hazer.name, prop(cv.channel),
                    None if cv.fine_channel is None else prop(cv.fine_channel), cv.bits,
                    _data_value(cv.data, cv.bits))


def _field_alerts(w: _Work) -> None:
    if w.uncovered:
        names = w.listed(n for n, _, _ in w.uncovered)
        top = max(r for _, r, _ in w.uncovered)
        w.warn(f"Zone non couverte : {len(w.uncovered)} PC de face demandent jusqu'à {top:.1f}°, "
               f"au-delà de leur champ maximal ({names}).")
    if w.too_wide:
        names = w.listed(n for n, _, _ in w.too_wide)
        w.warn(f"Champ trop large : {len(w.too_wide)} PC de face ne peuvent pas se resserrer "
               f"autour de leur zone ({names}).")
    if w.nez_missed:
        w.warn(f"Face : le nez n'est pas dans le faisceau de {w.listed(w.nez_missed)}.")
    if w.doors_short:
        w.warn(f"Volets : coupe hors course (volets trop courts ou angle limité) pour {w.listed(w.doors_short)}.")
    if w.doors_misfit:
        w.warn(f"Volets : coupes non adaptées aux volets de la fiche pour {w.listed(w.doors_misfit)}.")


def _pipe_part(w: _Work, pipe: _Support, index: int) -> None:
    w.objects.insert(index, Tube(pipe.name, MATERIAL_TUBE, RIG_COLLECTION, (-pipe.limit, pipe.y, pipe.z),
                                 (pipe.limit, pipe.y, pipe.z), BATTEN_RADIUS))


def _forestage_width(w: _Work) -> float:
    """Width wanted lit on the forestage: the nose, narrowed to the frame when a row 0 PC cuts on the post."""
    c = w.c
    outside = any(s.family == "front_pc" and s.meta["row"] == 0 and abs(s.x) > c.Wc / 2 + EPS for s in w.slots)
    return c.Wc if outside else c.W


def compute_rig(c: Ctx, library: Library, adjust: Mapping[str, Adjustment] | None = None) -> tuple[Rig, Part]:
    """The whole rig for the context `c` and the fiches of `library` (spec 13 and 15).

    `adjust` maps face PC names to their equalisation (spec 13.13): aim, zoom field and level.
    """
    if not c.p["rig"]["enabled"]:
        return Rig(), Part()
    rg = c.p["rig"]
    za = c.Hp + rg["aim_height"]
    ya = min(rg["area_depth"], c.plan.yb)
    zones = _zones(c, ya)
    w = _Work(c, library, zones, za, ya)
    w.adjust = adjust or {}
    w.walls = _walls(c)
    if rg["area_depth"] > c.plan.yb + EPS:
        w.warn(f"Zone de jeu raccourcie : {_metres(rg['area_depth'])} demandés, le fond est à "
               f"{_metres(c.plan.yb)}.")
    pipe, drop = _front_pipe(w, zones, za)
    _plan_backlight(w, zones, za)
    pipe2 = _plan_front_movers(w, zones, za, pipe)
    _plan_profiles(w, zones, za, pipe, ya)
    _plan_front_pc(w, zones, za, pipe, drop)
    _plan_towers(w, za, ya)
    _plan_hazer(w)
    _check_stacks(w)
    tubes = {pipe.name: pipe}
    if pipe2 is not None:
        tubes[pipe2.name] = pipe2
    tubes.update({f"Batten_{_nn(i + 1)}": _batten(c, i) for i in range(len(c.light_batten_ys))})
    _pack(w, tubes)
    _assign_addresses(w)
    levels, done = _levels(c.p), set()
    order = {key: n for n, (key, _, _) in enumerate(PATCH_FAMILIES)}
    slots = sorted(w.slots, key=lambda s: order[s.family])
    built = {s.name: _build_fixture(w, s, levels, done) for s in slots if s.family != "front_movers"}
    if pipe2 is not None:
        pipe2 = replace(pipe2, z=_movers_height(w, pipe2, slots, built))
        for s in slots:
            if s.family == "front_movers":
                s.z = pipe2.z
    built.update({s.name: _build_fixture(w, s, levels, done) for s in slots if s.family == "front_movers"})
    fixtures = [built[s.name] for s in slots]
    clearance, masking_clearance = _clearance_alerts(w, slots, built)
    _field_alerts(w)
    entries = [PatchEntry(f.name, f.family, f.universe, f.address, f.footprint) for f in fixtures]
    _check_patch(w, entries)
    _pipe_part(w, pipe, 0)
    if pipe2 is not None:
        _pipe_part(w, pipe2, 1)
    circuits: dict[str, list[str]] = {}
    for f in fixtures:
        if f.circuit:
            circuits.setdefault(f.circuit, []).append(f.name)
    ranges = tuple((k, min(e.universe for e in grp), min(e.address for e in grp), max(e.last for e in grp))
                   for k, _, _ in PATCH_FAMILIES if (grp := [e for e in entries if e.family == k]))
    profiles = tuple((f.name, f.tube, f.field_angle) for f in fixtures
                     if f.family == "profiles" and f.field_angle is not None)
    dims = RigDims(pipe.y, pipe.z, ya, drop, profiles, ranges, tuple(w.azimuths),
                   pipe2.y if pipe2 else None, pipe2.z if pipe2 else None, w.mover_radius, clearance,
                   tuple(w.row_supports), masking_clearance, tuple(w.nez_reach))
    rig = Rig(True, zones, tuple(fixtures), tuple(entries), _rest_map(fixtures), _loads(fixtures),
              tuple((k, tuple(v)) for k, v in circuits.items()), _haze_link(w, fixtures), dims,
              tuple(w.warnings), FaceSetup(_forestage_width(w), c.Wc, c.Ys, ya, za), bool(w.adjust))
    return rig, Part(tuple(w.objects), warnings=tuple(w.warnings))
