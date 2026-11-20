"""Lighting rig: hang points, aims, fields, blades, pan/tilt, DMX patch and rest values.

Spec sections 13 and 15, in pure Python. `compute_rig` is the single entry point;
the builder only translates its result and recomputes nothing. Angles are in
degrees in the records, lengths in metres, 3-vectors are `(x, y, z)` tuples.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from functools import lru_cache
from collections.abc import Mapping

from .fixtures import (
    SHIPPED_DIR, Channel, Fixture, Library, Mode, Range, cct_to_rgb, discover, encode,
)
from .layout import (
    BATTEN_RADIUS, EPS, PROSCENIUM_RECESS, Ctx, Part, _metres, _nn, _polys_overlap,
    _side_stair,
)
from .params import FIXTURE, GROUPS, PATCH_FAMILIES, side_sets
from .primitives import Truss, Tube

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
AZIMUTH_SEARCH = 10.0

FAMILY_LABELS = {
    "backlight": "contre", "front_movers": "mobiles de face", "tower_movers": "mobiles de pylône",
    "front_pc": "PC de face", "profiles": "découpes", "hazer": "hazer",
}
FAMILY_GROUPS = {
    "backlight": "backlight", "front_movers": "front_movers", "tower_movers": "towers",
    "front_pc": "front_pc", "profiles": "profiles", "hazer": "haze",
}
MOVER_GROUPS = {"backlight": "Backlight", "front_movers": "FrontMovers"}
PACK_ORDER = {"backlight": 0, "front_movers": 1, "profiles": 2}
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

    `pc_azimuths` is the crossing azimuth used by each hung PC row.
    """

    pipe_y: float
    pipe_z: float
    area_depth: float
    pipe_drop: float
    profiles: tuple[tuple[str, str | None, float], ...]
    patch_ranges: tuple[tuple[str, int, int, int], ...]
    pc_azimuths: tuple[float, ...] = ()


@dataclass(frozen=True)
class Rig:
    """`rest` maps `(universe, channel)` to the scene property value (`byte / 255`)."""

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

    def find(self, name: str) -> RigFixture:
        for item in self.fixtures:
            if item.name == name:
                return item
        raise KeyError(name)

    def by_family(self, family: str) -> tuple[RigFixture, ...]:
        return tuple(f for f in self.fixtures if f.family == family)


# --------------------------------------------------------------- vector math

def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _mul(a, k):
    return (a[0] * k, a[1] * k, a[2] * k)


def _dot(a, b) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _unit(a):
    n = math.sqrt(_dot(a, a))
    return (a[0] / n, a[1] / n, a[2] / n)


def _angle_between(a, b) -> float:
    return math.degrees(math.acos(min(max(_dot(_unit(a), _unit(b)), -1.0), 1.0)))


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

@dataclass
class _Sheet:
    fixture: Fixture
    mode: Mode


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
        dims = self.sheet.fixture.physical.dimensions
        return dims.width if dims else 0.0


class _Work:
    def __init__(self, c: Ctx, library: Library):
        self.c, self.lib = c, library
        self.warnings: list[str] = []
        self.slots: list[_Slot] = []
        self.objects: list = []
        self.zones: Zones | None = None
        self.azimuths: list[float] = []
        self.za = 0.0
        self.ya = 0.0
        self.uncovered: list[tuple[str, float, float]] = []
        self.too_wide: list[tuple[str, float, float]] = []

    def warn(self, message: str) -> None:
        if message not in self.warnings:
            self.warnings.append(message)

    def sheet(self, family: str, node: Mapping) -> _Sheet | None:
        """Fiche and mode of a family, or None with a French alert."""
        label, fid = FAMILY_LABELS[family], node["fixture"]
        fx = self.lib.get(fid)
        if fx is None:
            self.warn(f"Fiche « {fid} » introuvable dans la bibliothèque : {label} ignoré.")
            return None
        allowed = next(p.families for p in GROUPS[FAMILY_GROUPS[family]].params if p.kind == FIXTURE)
        if fx.family not in allowed:
            self.warn(f"Fiche « {fid} » : famille « {fx.family} » inadaptée aux {label}, ignorés.")
            return None
        if fx.family != "hazer" and None in (fx.physical.dimensions, fx.physical.mount, fx.optics):
            self.warn(f"Fiche « {fid} » incomplète (dimensions, accroche ou optique) : {label} ignoré.")
            return None
        try:
            mode = fx.mode(node["mode"])
        except KeyError:
            self.warn(f"Mode « {node['mode']} » inconnu de la fiche « {fid} » : mode par défaut utilisé.")
            mode = fx.mode()
        return _Sheet(fx, mode)

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


def _batten(c: Ctx, index: int) -> _Support:
    name = f"Batten_{_nn(index + 1)}"
    return _Support(name, c.light_batten_ys[index], c.plan.zb, c.Wk / 2 - PIPE_END_MARGIN,
                 f"la porteuse {name}")


def _zones(w: _Work, ya: float) -> Zones:
    c, pc = w.c, w.c.p["front_pc"]
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


# ------------------------------------------------------------------ families

def _plan_backlight(w: _Work, zones: Zones, za: float) -> None:
    c, node = w.c, w.c.p["backlight"]
    if not node["enabled"] or (sheet := w.sheet("backlight", node)) is None:
        return
    index = _nearest_batten(c, node["distance"])
    if index is None:
        w.warn("Aucune porteuse lumière : pas de contre.")
        return
    tube = _batten(c, index)
    if abs(tube.y - node["distance"]) > BATTEN_TOLERANCE + EPS:
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


def _plan_front_movers(w: _Work, zones: Zones, za: float, pipe: _Support) -> None:
    node = w.c.p["front_movers"]
    if not node["enabled"] or (sheet := w.sheet("front_movers", node)) is None:
        return
    n = node["count"]
    for i in range(n):
        x, name = spread(i, n, w.c.Wc), f"FrontMover_{_nn(i + 1)}"
        w.add(_Slot(name, "front_movers", sheet, _clamp_x(w, name, x, pipe), pipe.y, pipe.z,
                    (x, zones.ys[0], za), pipe.name, pipe.name, pipe.limit,
                    circuit=MOVER_GROUPS["front_movers"]))


def _row_x(zones: Zones, drop: float, azimuth: float) -> list[tuple[str, int, float]]:
    """(side, column, X) of every PC of a row for one crossing azimuth."""
    t = drop * math.tan(math.radians(azimuth))
    return [(tag, i, xc + sign * t) for tag, sign in (("L", -1), ("R", 1))
            for i, xc in enumerate(zones.xs)]


def _row_azimuth(w: _Work, tube: _Support, yr: float, nominal: float, sheet: _Sheet,
                 taken: list[float]) -> float | None:
    """Azimuth nearest to `nominal` (+-0.5 deg steps, +-10 deg) where no PC of the row touches
    another on the tube and every zone stays within the widest field of the sheet."""
    zones, fx = w.zones, sheet.fixture
    width, drop, za = fx.physical.dimensions.width, yr - tube.y, w.za
    mount, optics = fx.physical.mount, fx.optics
    widest = optics.lens_tubes[-1].field_angle if optics.lens_tubes else optics.field_angle.max
    z = tube.z - mount.hook_height - mount.tilt_axis_height
    for k in range(int(AZIMUTH_SEARCH / AZIMUTH_STEP) + 1):
        for delta in ((0.0,) if k == 0 else (k * AZIMUTH_STEP, -k * AZIMUTH_STEP)):
            row = _row_x(zones, drop, nominal + delta)
            xs = [x for _, _, x in row] + taken
            clear = all(abs(x) <= tube.limit + EPS for x in xs) and all(
                abs(a - b) >= width - EPS for n, a in enumerate(xs) for b in xs[n + 1:])
            if clear and all(
                    _wash_required(w, (zones.xs[i], yr), za, (x, tube.y, z),
                                   _unit(_sub((zones.xs[i], yr, za), (x, tube.y, z)))) <= widest + EPS
                    for _, i, x in row):
                return nominal + delta
    return None


def _plan_front_pc(w: _Work, zones: Zones, za: float, pipe: _Support, drop_auto: float) -> None:
    c, node = w.c, w.c.p["front_pc"]
    if not node["enabled"] or (sheet := w.sheet("front_pc", node)) is None:
        return
    on_tube: dict[str, list[float]] = {}
    for j, yr in enumerate(zones.ys):
        if j == 0:
            tube = pipe
        else:
            index = 0 if j == 1 and c.light_batten_ys else _nearest_batten(c, yr - drop_auto)
            if index is None:
                w.warn(f"Rang {j + 1} : aucune porteuse lumière, rang non posé.")
                continue
            tube = _batten(c, index)
        drop = yr - tube.y
        if drop < MIN_ROW_DROP - EPS:
            w.warn(f"Rang {j + 1} : porteuse trop en arrière de la zone.")
            continue
        taken = on_tube.setdefault(tube.name, [])
        azimuth = _row_azimuth(w, tube, yr, node["azimuth"], sheet, taken)
        if azimuth is None:
            azimuth = node["azimuth"]
            w.warn(f"Rang {j + 1} : aucun azimut à ±{AZIMUTH_SEARCH:g}° de {azimuth:g}° n'évite "
                   f"que des PC se touchent sur {tube.label} ou sortent de leur champ.")
        w.azimuths.append(azimuth)
        for tag, i, x in _row_x(zones, drop, azimuth):
            name = f"FrontPC_{tag}_{_nn(j * zones.nx + i + 1)}"
            x = _clamp_x(w, name, x, tube)
            taken.append(x)
            w.add(_Slot(name, "front_pc", sheet, x, tube.y, tube.z, (zones.xs[i], yr, za),
                        tube.name, tube.name, tube.limit, movable=False,
                        circuit=f"FrontPC_Row{j + 1}_{tag}",
                        meta={"zone": (zones.xs[i], yr), "side": tag}))


def _bisector_y(head: Vec3, low: Vec3, high: Vec3, za: float) -> float:
    """Y where the ray bisecting the bottom and top cut directions (side view) crosses the plane `za`."""
    elev = [math.atan2(head[2] - q[2], q[1] - head[1]) for q in (low, high)]
    return head[1] + (head[2] - za) / math.tan(sum(elev) / 2)


def _plan_profiles(w: _Work, zones: Zones, za: float, pipe: _Support, ya: float) -> None:
    c, node = w.c, w.c.p["profiles"]
    if not node["enabled"] or (sheet := w.sheet("profiles", node)) is None:
        return
    mount = sheet.fixture.physical.mount
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
    fx = sheet.fixture
    dims, mount = fx.physical.dimensions, fx.physical.mount
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

def _gap(a: _Slot, b: _Slot) -> float:
    return (a.width + b.width) / 2


def _free_x(slot: _Slot, placed: list[_Slot]) -> float | None:
    """Nearest X to the wanted one where `slot` touches nothing; None when the tube is full."""
    sign = -1.0 if slot.x > 0 else 1.0
    for k in range(int(2 * slot.limit / PACK_STEP) + 2):
        for delta in ((0.0,) if k == 0 else (sign * k * PACK_STEP, -sign * k * PACK_STEP)):
            x = slot.x + delta
            if abs(x) <= slot.limit + EPS and all(abs(x - t.x) >= _gap(slot, t) - EPS for t in placed):
                return x
    return None


def _pack(w: _Work, tubes: Mapping[str, _Support]) -> None:
    """Per tube: PCs keep their X, every other fixture moves to the nearest free X (spec 13.10)."""
    for name, tube in tubes.items():
        group = [s for s in w.slots if s.group == name]
        placed: list[_Slot] = []
        movable = sorted((s for s in group if s.movable), key=lambda s: PACK_ORDER[s.family])
        for slot in [s for s in group if not s.movable] + movable:
            if slot.movable:
                x = _free_x(slot, placed)
                if x is not None:
                    slot.x = x
            for other in placed:
                if abs(slot.x - other.x) < _gap(slot, other) - EPS:
                    w.warn(f"Appareils qui se touchent sur {tube.label} : {other.name} et {slot.name}.")
            placed.append(slot)


# ------------------------------------------------------------ pan/tilt, field

def _fit(phi: float, tau: float, pan: Range, tilt: Range) -> tuple[float, float] | None:
    mid = (pan.min + pan.max) / 2
    reps = [phi + 360 * k for k in range(-3, 4) if pan.min - EPS <= phi + 360 * k <= pan.max + EPS]
    if not reps or not tilt.min - EPS <= tau <= tilt.max + EPS:
        return None
    return min(reps, key=lambda r: abs(r - mid)), tau


def _solve_pan_tilt(w: _Work, name: str, fx: Fixture, axis: Vec3) -> tuple[float, float]:
    phi, tau = aim_angles(axis)
    motion = fx.motion
    if motion is None or motion.type != "moving":
        return phi, tau
    solution = _fit(phi, tau, motion.pan, motion.tilt) or _fit(phi + 180, -tau, motion.pan, motion.tilt)
    if solution is not None:
        return solution
    mid = (motion.pan.min + motion.pan.max) / 2
    near = min((phi + 360 * k for k in range(-3, 4)), key=lambda r: abs(r - mid))
    pan = min(max(near, motion.pan.min), motion.pan.max)
    tilt = min(max(tau, motion.tilt.min), motion.tilt.max)
    w.warn(f"Pan/tilt hors course : {name} demande pan {phi:.1f}°, tilt {tau:.1f}°, "
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


def _wash_required(w: _Work, zone: tuple[float, float], za: float, pivot: Vec3, axis: Vec3) -> float:
    """Field needed to cover `zone` plus the overlap from `pivot` along `axis`."""
    zones, overlap = w.zones, w.c.p["front_pc"]["overlap"]
    xc, yr = zone
    hx, hy = zones.width / 2 * (1 + overlap), zones.depth / 2 * (1 + overlap)
    return 2 * max(_angle_between(axis, _sub((xc + sx * hx, yr + sy * hy, za), pivot))
                   for sx in (-1, 1) for sy in (-1, 1))


def _wash_field(w: _Work, s: _Slot, pivot: Vec3, axis: Vec3):
    """Field of a face PC covering its zone plus overlap (spec 13.7)."""
    optics = s.sheet.fixture.optics
    f_req = _wash_required(w, s.meta["zone"], s.target[2], pivot, axis)
    tube, value, status = _fit_field(optics, f_req, 1.0)
    if status == "uncovered":
        w.uncovered.append((s.name, f_req, value))
    elif status == "wide":
        w.too_wide.append((s.name, f_req, value))
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
    planes = {}
    for name, (q, u) in lines.items():
        cross = _cross(_sub(q, source), u)
        if _dot(cross, cross) < EPS:
            continue
        n = _unit(cross)
        planes[name] = _mul(n, -1.0) if _dot(n, axis) > 0 else n
    return planes


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


def _blade_set(w: _Work, s: _Slot, source: Vec3, axis, frame, f_ref: float, d: float,
               source_z: float) -> BladeSet:
    """Blades of a profile: cut planes (auto) or manual setting (spec 13.8)."""
    fx, p = s.sheet.fixture, w.c.p["profiles"]
    bl = fx.blades
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
    fx = s.sheet.fixture
    optics = fx.optics
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
        blades = _blade_set(w, s, source, axis, frame, value, d, source_z)
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
    optics, mount = fx.optics, fx.physical.mount
    root = (s.x, s.y, s.z - mount.hook_height)
    pivot = (s.x, s.y, root[2] - mount.tilt_axis_height)
    pan, tilt = _solve_pan_tilt(w, s.name, fx, _unit(_sub(s.target, pivot)))
    moving = fx.motion is not None and fx.motion.type == "moving"
    over: dict[str, float] = {"dimmer": levels[s.family]}
    pan_data = tilt_data = None
    if moving:
        pan, pan_data, pv = _angle_dmx(mode, "pan", fx.motion.pan, pan)
        tilt, tilt_data, tv = _angle_dmx(mode, "tilt", fx.motion.tilt, tilt)
        over.update({k: v for k, v in (("pan", pv), ("tilt", tv)) if v is not None})
    frame = head_frame(pan, tilt)
    axis = frame[2]
    tube, field_angle, kind, source_z, blades = None, None, "", 0.0, None
    source = pivot
    kelvin = None
    if s.family == "front_pc":
        tube, field_angle = _wash_field(w, s, pivot, axis)
        kind, source_z, _ = _source(optics, tube, field_angle)
        source = _add(pivot, _mul(axis, source_z))
        if mode.channel("zoom") is not None and optics.field_angle is not None:
            over["zoom"] = _zoom_fraction(optics, field_angle)
        kelvin = p["rest"]["cct_left" if s.meta["side"] == "L" else "cct_right"]
    elif s.family == "profiles":
        tube, field_angle, kind, source_z, source, blades = _profile_optics(w, s, pivot, axis, frame)
        kelvin = p["rest"]["cct_profile"]
        if blades is not None and fx.blades.mode == "motorised":
            over.update(_blade_rest(fx, blades))
    else:
        field_angle = _mover_field(mode, optics)
        tube = None
        f_ref = optics.field_angle.max if optics.field_angle else optics.lens_tubes[-1].field_angle
        kind, source_z, d = _source(optics, None if optics.field_angle else optics.lens_tubes[-1], f_ref)
        source = _add(pivot, _mul(axis, source_z))
        if fx.blades is not None:
            blades = _blade_set(w, s, source, axis, frame, f_ref, d, source_z)
    if kelvin is not None:
        over.update(_colour_overrides(w, s, kelvin, done))
    return RigFixture(
        s.name, s.family, fx.id, mode.name, s.load, (s.x, s.y, s.z), root, (math.pi, 0.0, 0.0),
        pivot, s.target, axis, moving, pan, tilt, pan_data, tilt_data, field_angle,
        _beam_for(optics, tube, field_angle), tube.name if tube else None, optics.aperture(tube),
        kind, source_z, source, blades, s.circuit, kelvin, s.universe, s.address, mode.footprint,
        _channel_values(s, over), fx.physical.weight, s.width)


def _mover_field(mode: Mode, optics) -> float:
    if optics.field_angle is None:
        return optics.lens_tubes[-1].field_angle
    zoom = mode.channel("zoom")
    if zoom is None:
        return optics.field_angle.max
    z = 1.0 - zoom.default_normalized if optics.zoom_invert else zoom.default_normalized
    return optics.field_angle.min + z * (optics.field_angle.max - optics.field_angle.min)


def _blade_rest(fx: Fixture, blades: BladeSet) -> dict[str, float]:
    out: dict[str, float] = {}
    for blade in blades.blades:
        out[f"blade_{blade.index}a"] = blade.insertion_a
        out[f"blade_{blade.index}b"] = blade.insertion_b
    rot = fx.blades.rotation
    if rot is not None:
        out["blade_rot"] = _clamp01(rot.fraction(blades.rotation))
    return out


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
    return (0 if name == "FrontPipe" else 1 if name.startswith("Batten") else 2, name)


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


def _pipe_part(w: _Work, pipe: _Support) -> None:
    w.objects.insert(0, Tube("FrontPipe", MATERIAL_TUBE, RIG_COLLECTION, (-pipe.limit, pipe.y, pipe.z),
                             (pipe.limit, pipe.y, pipe.z), BATTEN_RADIUS))


def compute_rig(c: Ctx, library: Library) -> tuple[Rig, Part]:
    """The whole rig for the context `c` and the fiches of `library` (spec 13 and 15)."""
    if not c.p["rig"]["enabled"]:
        return Rig(), Part()
    w = _Work(c, library)
    rg = c.p["rig"]
    za = c.Hp + rg["aim_height"]
    ya = min(rg["area_depth"], c.plan.yb)
    if rg["area_depth"] > c.plan.yb + EPS:
        w.warn(f"Zone de jeu raccourcie : {_metres(rg['area_depth'])} demandés, le fond est à "
               f"{_metres(c.plan.yb)}.")
    zones = _zones(w, ya)
    w.zones, w.za, w.ya = zones, za, ya
    pipe, drop = _front_pipe(w, zones, za)
    _plan_backlight(w, zones, za)
    _plan_front_movers(w, zones, za, pipe)
    _plan_front_pc(w, zones, za, pipe, drop)
    _plan_profiles(w, zones, za, pipe, ya)
    _plan_towers(w, za, ya)
    _plan_hazer(w)
    tubes = {pipe.name: pipe}
    tubes.update({f"Batten_{_nn(i + 1)}": _batten(c, i) for i in range(len(c.light_batten_ys))})
    _pack(w, tubes)
    _assign_addresses(w)
    levels, done = _levels(c.p), set()
    order = {key: n for n, (key, _, _) in enumerate(PATCH_FAMILIES)}
    slots = sorted(w.slots, key=lambda s: order[s.family])
    fixtures = [_build_fixture(w, s, levels, done) for s in slots]
    _field_alerts(w)
    entries = [PatchEntry(f.name, f.family, f.universe, f.address, f.footprint) for f in fixtures]
    _check_patch(w, entries)
    _pipe_part(w, pipe)
    circuits: dict[str, list[str]] = {}
    for f in fixtures:
        if f.circuit:
            circuits.setdefault(f.circuit, []).append(f.name)
    ranges = tuple((k, min(e.universe for e in grp), min(e.address for e in grp), max(e.last for e in grp))
                   for k, _, _ in PATCH_FAMILIES if (grp := [e for e in entries if e.family == k]))
    profiles = tuple((f.name, f.tube, f.field_angle) for f in fixtures if f.family == "profiles")
    dims = RigDims(pipe.y, pipe.z, ya, drop, profiles, ranges, tuple(w.azimuths))
    rig = Rig(True, zones, tuple(fixtures), tuple(entries), _rest_map(fixtures), _loads(fixtures),
              tuple((k, tuple(v)) for k, v in circuits.items()), _haze_link(w, fixtures), dims,
              tuple(w.warnings))
    return rig, Part(tuple(w.objects), warnings=tuple(w.warnings))
