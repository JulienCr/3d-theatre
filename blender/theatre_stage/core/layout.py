"""Parameters to a full, builder-ready description of the scene.

`compute_layout` is the only place where dimensions are computed. New object
families are added by writing a function `(Ctx) -> Part` and listing it in
FAMILIES; shared dimensions live in `Ctx`.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from .params import module_sets, validate_params
from .primitives import (
    Box, Camera, FlatSurface, Light, Panel, PleatedSurface, PleatState, Prism,
    SlatGrid, Tube,
)

ROOT_COLLECTION = "Theatre"
ARCHITECTURE = "Theatre_Architecture"
STAIRS = "Theatre_Stairs"
MODULES = "Theatre_Modules"
GRID = "Theatre_Grid"
MASKING = "Theatre_Masking"
CURTAINS = "Theatre_Curtains"
LIGHTS = "Theatre_Lights"
CAMERAS = "Theatre_Cameras"
COLLECTIONS = (ARCHITECTURE, STAIRS, MODULES, GRID, MASKING, CURTAINS, LIGHTS, CAMERAS)

MATERIAL_COLORS: dict[str, tuple[float, float, float, float]] = {
    "TS_Enclosure": (0.35, 0.03, 0.05, 1.0),
    "TS_Proscenium": (0.02, 0.02, 0.02, 1.0),
    "TS_Cage": (0.03, 0.03, 0.03, 1.0),
    "TS_StageBase": (0.02, 0.02, 0.02, 1.0),
    "TS_StageFloor": (0.55, 0.38, 0.22, 1.0),
    "TS_Nosing": (0.02, 0.02, 0.02, 1.0),
    "TS_HouseFloor": (0.30, 0.30, 0.30, 1.0),
    "TS_Stairs": (0.12, 0.12, 0.12, 1.0),
    "TS_Module": (0.04, 0.035, 0.03, 1.0),
    "TS_Grid": (0.10, 0.10, 0.11, 1.0),
    "TS_Batten": (0.10, 0.10, 0.11, 1.0),
    "TS_Masking": (0.01, 0.01, 0.01, 1.0),
    "TS_MainCurtain": (0.40, 0.02, 0.03, 1.0),
    "TS_Cyclorama": (0.90, 0.90, 0.90, 1.0),
}

# Constants not exposed as parameters (spec section 4 and 8).
FACADE_THICKNESS = 0.30
PROSCENIUM_DEPTH = 0.40
PROSCENIUM_RECESS = 0.05
CAGE_WALL = 0.20
FLOOR_FACING = 0.03
NOSING = 0.05
FRONT_BAND_THICKNESS = 0.02
MODULE_WALL = 0.10
BATTEN_RADIUS = 0.024
BAY_MARGIN = 0.05
ROOF_THICKNESS = 0.10
SLAT = 0.05
SLAT_PITCH = 0.15
PLEAT_PITCH = 0.30
PLEAT_AMPLITUDE = 0.06
CURTAIN_OPEN_AMPLITUDE = 0.20
CURTAIN_POST_MARGIN = 0.05
CURTAIN_MIN_BUNDLE = 0.30
CURTAIN_OVERLAP = 0.15
WORK_LIGHT_WATTS_PER_SQM = 25.0
FRONT_LIGHT_WATTS = 375.0
FRONT_LIGHT_SIZE = 2.0
LIGHT_KELVIN = 4000.0
MIN_LANE = 0.60
BATTEN_CLEARANCE = 0.30
EPS = 1e-9


def _nn(index: int) -> str:
    return f"{index:02d}"


def _metres(value: float) -> str:
    return f"{value:.2f} m".replace(".", ",")


def _round_half_up(value: float) -> int:
    return int(math.floor(value + 0.5))


@dataclass(frozen=True)
class Derived:
    """Dimensions shown in the panel."""

    total_width: float
    cage_width: float
    cage_front_y: float
    side_zone: float
    stair_footprint: float
    risers_count: int
    riser_height: float
    stair_length: float
    batten_count: int
    masking_batten_count: int
    masking_y0: float
    masking_y1: float
    backdrop_y: float
    lane_width: float
    modules_max_y: float | None


@dataclass(frozen=True)
class Layout:
    objects: tuple
    lights: tuple[Light, ...]
    cameras: tuple[Camera, ...]
    derived: Derived
    warnings: tuple[str, ...]
    collections: tuple[str, ...] = COLLECTIONS
    root_collection: str = ROOT_COLLECTION
    materials: Mapping = field(default_factory=lambda: dict(MATERIAL_COLORS))

    def find(self, name: str):
        for item in self.objects + self.lights + self.cameras:
            if item.name == name:
                return item
        raise KeyError(name)

    def names(self) -> tuple[str, ...]:
        return tuple(i.name for i in self.objects + self.lights + self.cameras)


@dataclass(frozen=True)
class Part:
    """What one family contributes."""

    objects: tuple = ()
    lights: tuple = ()
    cameras: tuple = ()
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class ModuleSpec:
    tag: str  # "L" or "R"
    label: str  # French side name
    origin: tuple[float, float, float]
    yaw: float
    v_min: float
    v_max: float
    width: float
    height: float
    depth: float
    cells: tuple
    openings: tuple


@dataclass(frozen=True)
class MaskPlan:
    y0: float
    y1: float
    yb: float
    lane_width: float
    planes: tuple[float, ...]
    front_plane: float
    curtain_plane: float
    zb: float


@dataclass(frozen=True)
class Ctx:
    p: dict
    W: float
    D: float
    Hp: float
    Hg: float
    A: float
    Hf: float
    Hc: float
    Tc: float
    Ys: float
    lintel: float
    Wc: float
    Yc: float
    Z: float
    Wt: float
    Yh: float
    risers: int
    riser_h: float
    stair_len: float
    footprint: float
    modules: tuple[ModuleSpec, ...]
    ymod: float | None
    plan: MaskPlan
    light_batten_ys: tuple[float, ...]


def _clip_bay(label, what, u0, u1, z0, z1, width, height):
    """Clip a bay to the face; returns (rect or None, warnings)."""
    lo_u, hi_u = BAY_MARGIN, width - MODULE_WALL - BAY_MARGIN
    lo_z, hi_z = 0.0, height - BAY_MARGIN
    c = (max(u0, lo_u), max(z0, lo_z), min(u1, hi_u), min(z1, hi_z))
    if c[2] - c[0] <= EPS or c[3] - c[1] <= EPS:
        return None, [f"Module {label} : {what} hors de la face, baie supprimée."]
    if abs(c[0] - u0) > EPS or abs(c[1] - z0) > EPS or abs(c[2] - u1) > EPS or abs(c[3] - z1) > EPS:
        return c, [f"Module {label} : {what} dépasse de la face, baie rognée."]
    return c, []


def _tile(width, height, openings):
    us = sorted({0.0, width} | {o[k] for o in openings for k in (0, 2)})
    zs = sorted({0.0, height} | {o[k] for o in openings for k in (1, 3)})
    cells = []
    for u0, u1 in zip(us, us[1:]):
        for z0, z1 in zip(zs, zs[1:]):
            if u1 - u0 <= EPS or z1 - z0 <= EPS:
                continue
            cu, cz = (u0 + u1) / 2, (z0 + z1) / 2
            if not any(o[0] < cu < o[2] and o[1] < cz < o[3] for o in openings):
                cells.append((u0, z0, u1, z1))
    return tuple(cells)


def _module_spec(tag, s, label, m, Wc, Yc, D, Hp):
    theta = math.radians(m["angle"])
    c, sn = math.cos(theta), math.sin(theta)
    u_dir = (c, sn) if s < 0 else (-c, sn)
    v_dir = (-sn, c) if s < 0 else (sn, c)
    hx, hy = s * (Wc / 2 - m["wall_gap"]), m["setback"]
    w, h, depth = m["width"], m["height"], m["depth"]
    warnings: list[str] = []
    openings = []
    for key, bottom, what in (("door", None, "porte"), ("window", m["window_sill"], "fenêtre")):
        if not m[f"{key}_enabled"]:
            continue
        centre = w / 2 + m[f"{key}_offset"]
        bw = m[f"{key}_width"]
        z0 = 0.0 if bottom is None else bottom
        z1 = m["door_height"] if bottom is None else bottom + m["window_height"]
        rect, issues = _clip_bay(label, what, centre - bw / 2, centre + bw / 2, z0, z1, w, h)
        warnings.extend(issues)
        if rect is not None:
            openings.append(rect)

    def world(u, v):
        return (hx + u * u_dir[0] + v * v_dir[0], hy + u * u_dir[1] + v * v_dir[1])

    corners = [world(0, 0), world(w, 0), world(w, depth), world(w - MODULE_WALL, depth)]
    tol = 1e-6
    if any(abs(x) > Wc / 2 + tol or y < Yc - tol or y > D + tol for x, y in corners):
        warnings.append(f"Module {label} : sort de la cage.")
    footprint = [world(u, v) for u in (0, w) for v in (0, MODULE_WALL)]
    footprint += [world(u, v) for u in (w - MODULE_WALL, w) for v in (0, depth)]
    y_max = max(y for _, y in footprint)
    if s < 0:
        yaw, v_min, v_max = theta, 0.0, MODULE_WALL
    else:
        yaw, v_min, v_max = math.pi - theta, -MODULE_WALL, 0.0
    spec = ModuleSpec(tag, label, (hx, hy, Hp), yaw, v_min, v_max, w, h, depth,
                      _tile(w, h, openings), tuple(openings))
    return spec, y_max, warnings


def _make_context(raw) -> tuple[Ctx, list[str]]:
    p, warnings = validate_params(raw)
    st, adv, stairs = p["stage"], p["advanced"], p["stairs"]
    W, D, Hg = st["width"], st["depth"], st["grid_height"]
    Hp, A, Hf = adv["stage_height"], adv["apron_depth"], adv["facade_height"]
    Hc, Ys, lintel = adv["proscenium_height"], adv["proscenium_setback"], adv["lintel_height"]
    Tc = adv["proscenium_thickness"]
    if Tc > (W - 1.0) / 2:
        Tc = (W - 1.0) / 2
        warnings.append(f"Montants du cadre trop larges pour le plateau : réduits à {_metres(Tc)}.")
    Wc = W - 2 * Tc
    Yc = Ys + PROSCENIUM_DEPTH
    if D < Yc + 0.5:
        D = Yc + 0.5
        warnings.append(f"Profondeur de scène insuffisante derrière le cadre : portée à {_metres(D)}.")

    n = math.ceil(Hp / stairs["riser_max"] - EPS)
    n = max(n, 1)
    riser_h = Hp / n
    stair_len = (n - 1) * stairs["going"]
    theta = math.radians(stairs["side_angle"])
    Ws = stairs["width"]
    footprint = (Ws / 2 + math.sin(theta) * (Ws / 2 + stair_len) + math.cos(theta) * Ws / 2)
    lateral = stairs["left"] or stairs["right"]
    Z = adv["side_zone_width"]
    if lateral and footprint > Z + EPS:
        Z = footprint
        if footprint > adv["side_zone_width"] + EPS:
            warnings.append(f"Zone latérale élargie automatiquement à {_metres(Z)} "
                            "de chaque côté pour loger les escaliers.")
    Wt = W + 2 * Z

    if Hp + Hc + lintel > Hf or Hc + lintel > Hg:
        warnings.append("Cadre trop haut : le linteau dépasse la façade ou le dessous du gril.")

    modules, ymod = [], None
    left, right = module_sets(p["modules"])
    symmetric = p["modules"]["symmetric"]
    for tag, s, label, m in (("L", -1, "jardin", left), ("R", 1, "cour", right)):
        if not m["enabled"]:
            continue
        spec, y_max, issues = _module_spec(tag, s, label, m, Wc, Yc, D, Hp)
        modules.append(spec)
        ymod = y_max if ymod is None else max(ymod, y_max)
        if tag == "L" or not symmetric:
            warnings.extend(issues)

    plan, plan_warnings = _mask_plan(p, Wc, Yc, D, Hp, Hg, ymod)
    warnings.extend(plan_warnings)
    ys, battens_warning = _light_battens(p, Yc, D, plan)
    warnings.extend(battens_warning)

    Yh = max(A, p["cameras"]["distance"] + 1.0)
    ctx = Ctx(p, W, D, Hp, Hg, A, Hf, Hc, Tc, Ys, lintel, Wc, Yc, Z, Wt, Yh, n, riser_h,
              stair_len, footprint if lateral else 0.0, tuple(modules), ymod, plan, ys)
    return ctx, warnings


def _mask_plan(p, Wc, Yc, D, Hp, Hg, ymod):
    mk = p["masking"]
    y0 = Yc + 0.50
    if ymod is not None:
        y0 = max(y0, ymod + 0.20)
    yb = {"bare_wall": D, "black_curtain": D - 0.40, "cyclorama": D - 1.20}[mk["backdrop"]]
    y1 = yb - 0.30
    lanes = mk["lanes"]
    lane_width = max(y1 - y0, 0.0) / lanes
    planes = tuple(y0 + k * lane_width for k in range(1, lanes + 1))
    zb = Hp + Hg - p["grid"]["batten_drop"]
    warnings = []
    if lane_width < MIN_LANE - EPS and mk["style"] == "italian":
        warnings.append("Rues de pendrillonnage de moins de 0,60 m : réduire le nombre de "
                        "rues ou reculer le fond.")
    if mk["opening"] > Wc:
        warnings.append("Ouverture du pendrillonnage plus large que la cage : "
                        "aucun pendrillon dessiné.")
    wants_border = mk["front_border"] or any(mk["borders"][: lanes])
    if wants_border and mk["border_bottom"] >= zb - Hp:
        warnings.append("Frises sans hauteur utile : le bas des frises atteint les porteuses.")
    return MaskPlan(y0, y1, yb, lane_width, planes, Yc + 0.35, Yc + 0.15, zb), warnings


def _masking_batten_ys(p, plan) -> list[float]:
    mk = p["masking"]
    ys = list(plan.planes)
    if mk["front_border"]:
        ys.append(plan.front_plane)
    if mk["backdrop"] != "bare_wall":
        ys.append(plan.yb)
    return ys


def _light_battens(p, Yc, D, plan):
    spacing = p["grid"]["batten_spacing"]
    first, last = Yc + 0.50, D - 0.30
    if last < first - EPS:
        return (), ["Profondeur de cage insuffisante pour une porteuse."]
    blocked = _masking_batten_ys(p, plan)
    if p["curtains"]["main_enabled"]:
        blocked.append(plan.curtain_plane)
    ys = []
    count = int(math.floor((last - first) / spacing + EPS)) + 1
    for i in range(count):
        y = first + i * spacing
        if not any(abs(y - b) < BATTEN_CLEARANCE - EPS for b in blocked):
            ys.append(y)
    return tuple(ys), []


def _box(name, material, collection, lo, hi, origin=(0.0, 0.0, 0.0), yaw=0.0):
    return Box(name, material, collection, origin, yaw, lo, hi)


# ---------------------------------------------------------------- families

def _architecture(c: Ctx) -> Part:
    A_, Wt, W, Wc, Ys, Yc, Hp, D = c.A, c.Wt, c.W, c.Wc, c.Ys, c.Yc, c.Hp, c.D
    roof_z = Hp + c.Hg + 2.0
    objs: list = [
        _box("House_Floor", "TS_HouseFloor", ARCHITECTURE, (-Wt / 2, -c.Yh, -0.10), (Wt / 2, Ys, 0.0)),
    ]
    for tag, s in (("L", -1), ("R", 1)):
        x0, x1 = (-Wt / 2 - FACADE_THICKNESS, -Wt / 2) if s < 0 else (Wt / 2, Wt / 2 + FACADE_THICKNESS)
        objs.append(_box(f"House_Wall_{tag}", "TS_Enclosure", ARCHITECTURE,
                         (x0, -c.Yh, 0.0), (x1, Ys, c.Hf)))

    hole_top = min(Hp + c.Hc + c.lintel, c.Hf)
    polygons = []
    if hole_top < c.Hf - EPS:
        if c.Z > EPS:
            polygons.append(((-Wt / 2, 0.0), (-W / 2, 0.0), (-W / 2, hole_top), (W / 2, hole_top),
                             (W / 2, 0.0), (Wt / 2, 0.0), (Wt / 2, c.Hf), (-Wt / 2, c.Hf)))
        else:
            polygons.append(((-W / 2, hole_top), (W / 2, hole_top), (W / 2, c.Hf), (-W / 2, c.Hf)))
    elif c.Z > EPS:
        polygons.append(((-Wt / 2, 0.0), (-W / 2, 0.0), (-W / 2, c.Hf), (-Wt / 2, c.Hf)))
        polygons.append(((W / 2, 0.0), (Wt / 2, 0.0), (Wt / 2, c.Hf), (W / 2, c.Hf)))
    if polygons:
        objs.append(Prism("Facade", "TS_Enclosure", ARCHITECTURE, "xz", tuple(polygons),
                          Ys, Ys + FACADE_THICKNESS))

    py0, py1 = Ys + PROSCENIUM_RECESS, Ys + PROSCENIUM_DEPTH
    for tag, s in (("L", -1), ("R", 1)):
        xs = sorted((s * Wc / 2, s * W / 2))
        objs.append(_box(f"Proscenium_Post_{tag}", "TS_Proscenium", ARCHITECTURE,
                         (xs[0], py0, Hp), (xs[1], py1, Hp + c.Hc)))
    objs.append(_box("Proscenium_Lintel", "TS_Proscenium", ARCHITECTURE,
                     (-W / 2, py0, Hp + c.Hc), (W / 2, py1, Hp + c.Hc + c.lintel)))

    outline = ((-W / 2, 0.0), (W / 2, 0.0), (W / 2, Yc), (Wc / 2, Yc), (Wc / 2, D),
               (-Wc / 2, D), (-Wc / 2, Yc), (-W / 2, Yc))
    objs.append(Prism("Stage_Base", "TS_StageBase", ARCHITECTURE, "xy", (outline,),
                      0.0, Hp - FLOOR_FACING))
    objs.append(Prism("Stage_Floor", "TS_StageFloor", ARCHITECTURE, "xy", (outline,),
                      Hp - FLOOR_FACING, Hp))
    objs.append(_box("Stage_Front", "TS_Enclosure", ARCHITECTURE,
                     (-W / 2, -FRONT_BAND_THICKNESS, 0.0), (W / 2, 0.0, Hp - NOSING)))
    objs.append(_box("Stage_Nosing", "TS_Nosing", ARCHITECTURE,
                     (-W / 2, -FRONT_BAND_THICKNESS, Hp - NOSING), (W / 2, 0.0, Hp)))

    for tag, s in (("L", -1), ("R", 1)):
        x0, x1 = (-Wc / 2 - CAGE_WALL, -Wc / 2) if s < 0 else (Wc / 2, Wc / 2 + CAGE_WALL)
        objs.append(_box(f"Cage_Wall_{tag}", "TS_Cage", ARCHITECTURE, (x0, Yc, Hp), (x1, D, roof_z)))
    objs.append(_box("Cage_Back", "TS_Cage", ARCHITECTURE,
                     (-Wc / 2, D, Hp), (Wc / 2, D + CAGE_WALL, roof_z)))
    objs.append(_box("Cage_Roof", "TS_Cage", ARCHITECTURE,
                     (-Wc / 2 - CAGE_WALL, Yc, roof_z),
                     (Wc / 2 + CAGE_WALL, D + CAGE_WALL, roof_z + ROOF_THICKNESS)))
    return Part(tuple(objs))


def _stairs(c: Ctx) -> Part:
    st = c.p["stairs"]
    n, going, Hp, Ws = c.risers, st["going"], c.Hp, st["width"]
    theta = math.radians(st["side_angle"])
    objs, warnings = [], []
    for tag, s in (("L", -1), ("R", 1)):
        if not st["left" if s < 0 else "right"]:
            continue
        objs.append(_box(f"Stairs_Landing_{tag}", "TS_Stairs", STAIRS,
                         (min(s * c.W / 2, s * (c.W / 2 + Ws)), c.Ys - Ws, 0.0),
                         (max(s * c.W / 2, s * (c.W / 2 + Ws)), c.Ys, Hp)))
        centre = (s * (c.W / 2 + Ws / 2), c.Ys - Ws / 2, 0.0)
        d = (s * math.sin(theta), -math.cos(theta))
        yaw = math.atan2(d[1], d[0])
        min_y = c.Ys - Ws
        for j in range(1, n):
            a0, a1 = Ws / 2 + (j - 1) * going, Ws / 2 + j * going
            top = (n - j) * Hp / n
            objs.append(_box(f"Stairs_Step_{tag}_{_nn(j)}", "TS_Stairs", STAIRS,
                             (a0, -Ws / 2, 0.0), (a1, Ws / 2, top), centre, yaw))
            for a in (a0, a1):
                for b in (-Ws / 2, Ws / 2):
                    min_y = min(min_y, centre[1] + a * d[1] + b * d[0])
        if min_y < -c.A - EPS:
            warnings.append(f"L'escalier {'jardin' if s < 0 else 'cour'} dépasse de l'avant-scène.")
    if st["center"]:
        cw = st["center_width"]
        for j in range(1, n):
            objs.append(_box(f"Stairs_Step_C_{_nn(j)}", "TS_Stairs", STAIRS,
                             (-cw / 2, -j * going, 0.0), (cw / 2, -(j - 1) * going, (n - j) * Hp / n)))
        if (n - 1) * going > c.A + EPS or cw > c.Wt + EPS:
            warnings.append("L'escalier central dépasse de l'avant-scène.")
    return Part(tuple(objs), warnings=tuple(warnings))


def _modules(c: Ctx) -> Part:
    objs = []
    for m in c.modules:
        objs.append(Panel(f"Module_{m.tag}_Front", "TS_Module", MODULES, m.origin, m.yaw,
                          m.v_min, m.v_max, (m.width, m.height), m.cells, m.openings))
        v0, v1 = (0.0, m.depth) if m.v_min == 0.0 else (-m.depth, 0.0)
        objs.append(_box(f"Module_{m.tag}_Return", "TS_Module", MODULES,
                         (m.width - MODULE_WALL, v0, 0.0), (m.width, v1, m.height),
                         m.origin, m.yaw))
    return Part(tuple(objs))


def _grid(c: Ctx) -> Part:
    Hp, Hg, Wc = c.Hp, c.Hg, c.Wc
    count = int(math.floor((Wc - SLAT) / SLAT_PITCH + EPS)) + 1
    xs = tuple(-Wc / 2 + SLAT / 2 + i * SLAT_PITCH for i in range(count))
    objs: list = [SlatGrid("Grid_Deck", "TS_Grid", GRID, xs, c.Yc, c.D, Hp + Hg, SLAT)]
    z = Hp + Hg - c.p["grid"]["batten_drop"]
    for i, y in enumerate(c.light_batten_ys, start=1):
        objs.append(Tube(f"Batten_{_nn(i)}", "TS_Batten", GRID,
                         (-Wc / 2 + 0.10, y, z), (Wc / 2 - 0.10, y, z), BATTEN_RADIUS))
    return Part(tuple(objs))


def _pleat_count(length: float) -> int:
    return max(1, _round_half_up(length / PLEAT_PITCH))


def _pleated(name, collection, x0, y0, x1, y1, z0, z1, facing, material="TS_Masking"):
    length = math.hypot(x1 - x0, y1 - y0)
    return PleatedSurface(name, material, collection,
                          PleatState((x0, y0), (x1, y1), PLEAT_AMPLITUDE), z0, z1,
                          _pleat_count(length), facing)


def _masking(c: Ctx) -> Part:
    mk, plan, Wc, Hp, zb = c.p["masking"], c.plan, c.Wc, c.Hp, c.plan.zb
    objs = []

    def batten(name, a, b):
        objs.append(Tube(name, "TS_Batten", MASKING, (*a, zb), (*b, zb), BATTEN_RADIUS))

    bx = Wc / 2 - 0.10
    for k, y in enumerate(plan.planes, start=1):
        batten(f"MaskingBatten_{_nn(k)}", (-bx, y), (bx, y))
    if mk["front_border"]:
        batten("MaskingBatten_00", (-bx, plan.front_plane), (bx, plan.front_plane))
    if mk["backdrop"] != "bare_wall":
        batten("MaskingBatten_Back", (-bx, plan.yb), (bx, plan.yb))

    fits = mk["opening"] <= Wc
    outer = Wc / 2 - 0.10
    if mk["style"] == "italian":
        if fits and outer - mk["opening"] / 2 > 0.10:
            for k, y in enumerate(plan.planes, start=1):
                for tag, s in (("L", -1), ("R", 1)):
                    objs.append(_pleated(f"Leg_{tag}_{_nn(k)}", MASKING, s * mk["opening"] / 2, y,
                                         s * outer, y, Hp, zb, (0.0, -1.0)))
    else:
        for tag, s in (("L", -1), ("R", 1)):
            x = s * mk["opening"] / 2
            if fits and plan.y1 - plan.y0 > 0.1:
                objs.append(_pleated(f"Leg_{tag}", MASKING, x, plan.y0, x, plan.y1, Hp, zb,
                                     (-s, 0.0)))
                batten(f"MaskingBatten_Side_{tag}", (x, plan.y0), (x, plan.y1))

    if mk["border_bottom"] < zb - Hp:
        half = (Wc - 0.20) / 2
        z0 = Hp + mk["border_bottom"]
        if mk["front_border"]:
            y = plan.front_plane - 0.10
            objs.append(_pleated("Border_00", MASKING, -half, y, half, y, z0, zb, (0.0, -1.0)))
        for k, y in enumerate(plan.planes, start=1):
            if mk["borders"][k - 1]:
                objs.append(_pleated(f"Border_{_nn(k)}", MASKING, -half, y - 0.10, half, y - 0.10,
                                     z0, zb, (0.0, -1.0)))

    if mk["backdrop"] == "black_curtain":
        half = (Wc - 0.20) / 2
        objs.append(_pleated("Backdrop", MASKING, -half, plan.yb, half, plan.yb, Hp, zb,
                             (0.0, -1.0)))
    elif mk["backdrop"] == "cyclorama":
        half = (Wc - 0.60) / 2
        objs.append(FlatSurface("Cyclorama", "TS_Cyclorama", MASKING, (-half, plan.yb),
                                (half, plan.yb), Hp, zb, (0.0, -1.0)))
    return Part(tuple(objs))


def _curtains(c: Ctx) -> Part:
    if not c.p["curtains"]["main_enabled"]:
        return Part()
    y = c.plan.curtain_plane
    outer = c.W / 2 - CURTAIN_POST_MARGIN
    z0, z1 = c.Hp, c.Hp + c.Hc + 0.30
    count = _pleat_count(CURTAIN_OVERLAP + outer)
    bundle = c.Tc - 2 * CURTAIN_POST_MARGIN
    narrow = bundle < CURTAIN_MIN_BUNDLE - EPS
    inner = outer - CURTAIN_MIN_BUNDLE if narrow else c.Wc / 2 + CURTAIN_POST_MARGIN
    objs = []
    for tag, s in (("L", -1), ("R", 1)):
        closed = PleatState((-s * CURTAIN_OVERLAP, y), (s * outer, y), PLEAT_AMPLITUDE)
        opened = PleatState((s * inner, y), (s * outer, y), CURTAIN_OPEN_AMPLITUDE)
        objs.append(PleatedSurface(f"MainCurtain_{tag}", "TS_MainCurtain", CURTAINS, closed,
                                   z0, z1, count, (0.0, -1.0), opened))
    warnings = ("Rideau de scène ouvert visible dans l'ouverture : montants du cadre "
                "trop étroits.",) if narrow else ()
    return Part(tuple(objs), warnings=warnings)


def _lights(c: Ctx) -> Part:
    lt = c.p["lights"]
    if not lt["enabled"]:
        return Part()
    Wc, depth = c.Wc, c.D - c.Yc
    nx = max(1, _round_half_up(Wc / lt["spacing"]))
    ny = max(1, _round_half_up(depth / lt["spacing"]))
    cx, cy = Wc / nx, depth / ny
    z = c.Hp + c.Hg - 0.30
    lights, index = [], 1
    for iy in range(ny):
        for ix in range(nx):
            x, y = -Wc / 2 + (ix + 0.5) * cx, c.Yc + (iy + 0.5) * cy
            lights.append(Light(f"WorkLight_{_nn(index)}", LIGHTS, (x, y, z), (x, y, c.Hp),
                                min(cx, cy) / 2, WORK_LIGHT_WATTS_PER_SQM * cx * cy * lt["intensity"],
                                LIGHT_KELVIN))
            index += 1
    if lt["front"]:
        lights.append(Light("WorkLight_Front", LIGHTS, (0.0, -c.A - 2.0, c.Hp + c.Hc),
                            (0.0, c.Yc + depth / 3, c.Hp + 1.0), FRONT_LIGHT_SIZE,
                            FRONT_LIGHT_WATTS * lt["intensity"], LIGHT_KELVIN))
    return Part(lights=tuple(lights))


def _cameras(c: Ctx) -> Part:
    cm = c.p["cameras"]
    target = (0.0, c.D / 2, c.Hp + 1.0)
    cams = []
    for name, x in (("Cam_Face", 0.0), ("Cam_Jardin", -0.75 * c.W / 2), ("Cam_Cour", 0.75 * c.W / 2)):
        cams.append(Camera(name, CAMERAS, (x, -cm["distance"], cm["height"]), target, cm["lens"]))
    return Part(cameras=tuple(cams))


FAMILIES: tuple[Callable[[Ctx], Part], ...] = (
    _architecture, _stairs, _modules, _grid, _masking, _curtains, _lights, _cameras,
)


def compute_layout(params: Mapping | None = None) -> Layout:
    """Full scene description for `params` (nested dict, validated and clamped)."""
    ctx, warnings = _make_context(params)
    objects, lights, cameras = [], [], []
    for family in FAMILIES:
        part = family(ctx)
        objects.extend(part.objects)
        lights.extend(part.lights)
        cameras.extend(part.cameras)
        warnings.extend(part.warnings)
    masking_battens = sum(1 for o in objects if o.name.startswith("MaskingBatten_"))
    derived = Derived(
        total_width=ctx.Wt, cage_width=ctx.Wc, cage_front_y=ctx.Yc, side_zone=ctx.Z,
        stair_footprint=ctx.footprint, risers_count=ctx.risers, riser_height=ctx.riser_h,
        stair_length=ctx.stair_len, batten_count=len(ctx.light_batten_ys),
        masking_batten_count=masking_battens, masking_y0=ctx.plan.y0, masking_y1=ctx.plan.y1,
        backdrop_y=ctx.plan.yb, lane_width=ctx.plan.lane_width, modules_max_y=ctx.ymod,
    )
    return Layout(tuple(objects), tuple(lights), tuple(cameras), derived, tuple(warnings))
