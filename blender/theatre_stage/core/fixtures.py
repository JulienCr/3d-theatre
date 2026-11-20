"""Fixture sheets (fiches): frozen schema, validation, library discovery, DMX helpers.

Spec section 12. Only the sheet YAML is read here, never a GDTF. Lengths are in
metres, angles in degrees, `lm` for flux, `K` for colour temperature.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

SHIPPED_DIR = Path(__file__).resolve().parent.parent / "library" / "fixtures"
SHEET_NAME = "fixture.yaml"
DEFAULT_MODE = "default"

FAMILIES = ("moving_wash", "moving_profile", "pc", "profile", "hazer")
SOURCE_KINDS = ("datasheet", "gdtf", "ies", "other")
COLOUR_SYSTEMS = ("rgbw", "cmy", "cto", "cct", "emitters")
MESH_SUFFIXES = (".glb", ".obj")
MESH_PARTS = ("base", "yoke", "head")

# Attribute vocabulary of spec 12.3. Any other lowercase name is kept as an unknown attribute.
BLADE_ATTRIBUTES = tuple(f"blade_{n}{s}" for n in range(1, 5) for s in "ab")
BLADE_SWIVEL_ATTRIBUTES = tuple(f"blade_{n}_rot" for n in range(1, 5))
EMITTER_ATTRIBUTES = tuple(f"emitter_{n}" for n in range(1, 9))
ATTRIBUTES = (
    "dimmer", "pan", "tilt", "zoom", "color_r", "color_g", "color_b", "color_w",
    "cyan", "magenta", "yellow", "cto", "cct", *EMITTER_ATTRIBUTES, "strobe", "gobo1", "gobo2",
    "gobo1_rot", "gobo2_rot", "iris", *BLADE_ATTRIBUTES, *BLADE_SWIVEL_ATTRIBUTES, "blade_rot", "haze_density",
)
_ATTRIBUTE_NAME = re.compile(r"[a-z0-9_]+")
_ID = re.compile(r"[a-z0-9_]+")


def is_known_attribute(attribute: str) -> bool:
    return attribute in ATTRIBUTES


# ------------------------------------------------------------------ schema

@dataclass(frozen=True)
class Range:
    """`invert` (pan, tilt, blade_rot only): DMX 0 is `max`, so `v` reads as `1 - v`."""

    min: float
    max: float
    invert: bool = False

    def lerp(self, v: float) -> float:
        """`min + v * (max - min)`: how pan, tilt, zoom, cct and blade_rot read `v`."""
        return self.min + (1.0 - v if self.invert else v) * (self.max - self.min)

    def fraction(self, value: float) -> float:
        """Inverse of `lerp`: the normalized `v` that reads as `value` (0 for an empty range)."""
        span = self.max - self.min
        v = (value - self.min) / span if span else 0.0
        return 1.0 - v if self.invert else v


@dataclass(frozen=True)
class Source:
    kind: str
    url: str
    note: str


@dataclass(frozen=True)
class Dimensions:
    width: float
    depth: float
    height: float


@dataclass(frozen=True)
class Mount:
    hook_height: float
    tilt_axis_height: float


@dataclass(frozen=True)
class Physical:
    weight: float
    dimensions: Dimensions | None
    mount: Mount | None


@dataclass(frozen=True)
class LensTube:
    """A fixed lens. `lens_diameter` and `ies` are None when the tube has no own value."""

    name: str
    beam_angle: float
    field_angle: float
    lens_diameter: float | None
    ies: str | None


@dataclass(frozen=True)
class IesProfile:
    """`field_angle` is None for the single profile of a fixture without zoom."""

    field_angle: float | None
    file: str


@dataclass(frozen=True)
class Optics:
    beam_type: str
    lens_diameter: float
    lens_offset: float
    flux: float
    field_angle: Range | None
    beam_angle: Range | None
    lens_tubes: tuple[LensTube, ...]
    zoom_invert: bool
    ies: tuple[IesProfile, ...]

    def aperture(self, tube: LensTube | None = None) -> float:
        """Lens diameter of `tube`, falling back to `lens_diameter`."""
        return self.lens_diameter if tube is None or tube.lens_diameter is None else tube.lens_diameter


@dataclass(frozen=True)
class Emitter:
    attribute: str
    rgb: tuple[float, float, float]


@dataclass(frozen=True)
class Colour:
    systems: tuple[str, ...]
    cct_range: Range | None
    cto_kelvin: float | None
    emitters: tuple[Emitter, ...]


@dataclass(frozen=True)
class Motion:
    type: str
    pan: Range | None
    tilt: Range | None


@dataclass(frozen=True)
class Travel:
    open: float
    closed: float


@dataclass(frozen=True)
class Blades:
    count: int
    mode: str
    gate_from_lens: float
    span: float
    travel: Travel
    sides: tuple[float, ...]
    angle_limit: float
    rotation: Range | None


@dataclass(frozen=True)
class GoboSlot:
    name: str
    image: str | None
    dmx: tuple[int, int]

    def contains(self, byte: int) -> bool:
        return self.dmx[0] <= byte <= self.dmx[1]


@dataclass(frozen=True)
class GoboWheel:
    name: str
    rotation_range: float
    slots: tuple[GoboSlot, ...]


@dataclass(frozen=True)
class Iris:
    min_ratio: float


@dataclass(frozen=True)
class StrobeRamp:
    start: int
    stop: int
    hz_min: float
    hz_max: float


@dataclass(frozen=True)
class Strobe:
    open: tuple[int, int]
    closed: tuple[int, int]
    strobe: StrobeRamp


@dataclass(frozen=True)
class Channel:
    """`fine` is the offset of the fine byte of a 16-bit channel, None for 8 bits."""

    offset: int
    attribute: str
    bits: int
    default: int
    fine: int | None
    curve: tuple[tuple[float, float], ...] = ()
    curve_mode: str = "linear"

    def physical(self, v: float, default: Range | None = None) -> float:
        """Physical value of the normalized `v`: the DMX curve, else `default.lerp(v)` (spec 12.3).

        Outside the curve, the nearest end value holds. `step` keeps each value until the next point.
        """
        if not self.curve:
            if default is None:
                raise ValueError(f"{self.attribute} : ni courbe ni plage pour convertir la valeur.")
            return default.lerp(v)
        if v <= self.curve[0][0]:
            return self.curve[0][1]
        for (x0, y0), (x1, y1) in zip(self.curve, self.curve[1:]):
            if v < x1:
                return y0 if self.curve_mode == "step" else y0 + (v - x0) / (x1 - x0) * (y1 - y0)
        return self.curve[-1][1]

    @property
    def offsets(self) -> tuple[int, ...]:
        return (self.offset,) if self.fine is None else (self.offset, self.fine)

    @property
    def default_normalized(self) -> float:
        return self.default / (255 if self.bits == 8 else 65535)


@dataclass(frozen=True)
class Mode:
    name: str
    footprint: int
    channels: tuple[Channel, ...]

    def channel(self, attribute: str) -> Channel | None:
        return next((c for c in self.channels if c.attribute == attribute), None)


Vec3 = tuple[float, float, float]


@dataclass(frozen=True)
class Body:
    width: float
    depth: float
    height: float


@dataclass(frozen=True)
class Barrel:
    diameter: float
    length: float


@dataclass(frozen=True)
class Yoke:
    gap: float
    height: float


@dataclass(frozen=True)
class MeshPart:
    name: str
    file: str
    offset: Vec3


@dataclass(frozen=True)
class Model3D:
    """`kind` is procedural, mesh or none. `fallback` is a procedural model."""

    kind: str
    shape: str | None = None
    body: Body | None = None
    barrel: Barrel | None = None
    yoke: Yoke | None = None
    parts: tuple[MeshPart, ...] = ()
    fallback: Model3D | None = None

    def part(self, name: str) -> MeshPart | None:
        return next((p for p in self.parts if p.name == name), None)


@dataclass(frozen=True)
class QlcLink:
    manufacturer: str
    model: str
    modes: tuple[tuple[str, str], ...]
    verified: str | None


@dataclass(frozen=True)
class Fixture:
    """One validated sheet. Optional sections are None (or empty) when absent."""

    version: int
    id: str
    manufacturer: str
    model: str
    family: str
    sources: tuple[Source, ...]
    physical: Physical
    optics: Optics | None
    colour: Colour
    motion: Motion | None
    blades: Blades | None
    gobos: tuple[GoboWheel, ...]
    iris: Iris | None
    strobe: Strobe | None
    modes: tuple[Mode, ...]
    default_mode: str
    model3d: Model3D
    qlc: QlcLink | None
    root: Path | None = None

    @property
    def label(self) -> str:
        return f"{self.manufacturer} {self.model}"

    def mode_names(self) -> tuple[str, ...]:
        return tuple(m.name for m in self.modes)

    def mode(self, name: str | None = None) -> Mode:
        """Mode by name; None, "" and "default" give `default_mode`. KeyError if unknown."""
        wanted = self.default_mode if name in (None, "", DEFAULT_MODE) else name
        for mode in self.modes:
            if mode.name == wanted:
                return mode
        raise KeyError(f"Mode « {name} » inconnu pour {self.id}.")

    def footprint(self, mode: str | None = None) -> int:
        return self.mode(mode).footprint

    def channel(self, attribute: str, mode: str | None = None) -> Channel | None:
        return self.mode(mode).channel(attribute)

    def ies_for(self, field_angle: float, tube: LensTube | None = None) -> str | None:
        """IES file for a lens tube, else the profile nearest `field_angle`, else None."""
        if tube is not None:
            return tube.ies
        profiles = self.optics.ies if self.optics else ()
        known = [q for q in profiles if q.field_angle is not None]
        if known:
            return min(known, key=lambda q: abs(q.field_angle - field_angle)).file
        return profiles[0].file if profiles else None

    def path(self, relative: str) -> Path:
        """Absolute path of a file cited by the sheet (relative to its folder)."""
        return (self.root / relative) if self.root else Path(relative)


# ----------------------------------------------------------------- parsing

def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


class _Parser:
    """Walks a raw sheet, collecting French errors. Every getter returns None on error."""

    def __init__(self, folder: Path | None):
        self.folder = folder
        self.errors: list[str] = []

    def fail(self, path: str, message: str) -> None:
        self.errors.append(f"{path} : {message}")

    def _get(self, data: Mapping, key: str, path: str, required: bool):
        value = data.get(key)
        if value is None and required:
            self.fail(path, "obligatoire, absent ou laissé à null.")
        return value

    def mapping(self, data, key, prefix, required=True):
        path = f"{prefix}{key}"
        value = self._get(data, key, path, required)
        if value is None:
            return None
        if not isinstance(value, Mapping):
            self.fail(path, "un dictionnaire est attendu.")
            return None
        return value

    def sequence(self, data, key, prefix, required=True):
        path = f"{prefix}{key}"
        value = self._get(data, key, path, required)
        if value is None:
            return None
        if not isinstance(value, list):
            self.fail(path, "une liste est attendue.")
            return None
        return value

    def text(self, data, key, prefix, required=True, pattern=None, choices=None):
        path = f"{prefix}{key}"
        value = self._get(data, key, path, required)
        if value is None:
            return None
        if not isinstance(value, str) or not value.strip():
            self.fail(path, "un texte non vide est attendu.")
            return None
        if pattern and not pattern.fullmatch(value):
            self.fail(path, f"« {value} » : caractères autorisés a-z, 0-9 et _.")
            return None
        if choices and value not in choices:
            self.fail(path, f"« {value} » inconnu, attendu : {', '.join(choices)}.")
            return None
        return value

    def number(self, data, key, prefix, required=True, lo=None, hi=None, strict_lo=False):
        path = f"{prefix}{key}"
        value = self._get(data, key, path, required)
        if value is None:
            return None
        if not _is_number(value):
            self.fail(path, "un nombre est attendu.")
            return None
        if lo is not None and (value <= lo if strict_lo else value < lo):
            self.fail(path, f"{value} trop petit (minimum {lo}).")
            return None
        if hi is not None and value > hi:
            self.fail(path, f"{value} trop grand (maximum {hi}).")
            return None
        return float(value)

    def integer(self, data, key, prefix, required=True, lo=None, hi=None):
        path = f"{prefix}{key}"
        value = self._get(data, key, path, required)
        if value is None:
            return None
        if not _is_int(value):
            self.fail(path, "un entier est attendu.")
            return None
        if (lo is not None and value < lo) or (hi is not None and value > hi):
            self.fail(path, f"{value} hors de [{lo}, {hi}].")
            return None
        return value

    def boolean(self, data, key, prefix, default=False):
        value = data.get(key)
        if value is None:
            return default
        if not isinstance(value, bool):
            self.fail(f"{prefix}{key}", "un booléen est attendu.")
            return default
        return value

    def triple(self, data, key, prefix, required=True) -> Vec3 | None:
        values = self.sequence(data, key, prefix, required)
        if values is None:
            return None
        if len(values) != 3 or not all(_is_number(v) for v in values):
            self.fail(f"{prefix}{key}", "trois nombres sont attendus.")
            return None
        return tuple(float(v) for v in values)

    def byte_range(self, data, key, prefix, required=True) -> tuple[int, int] | None:
        values = self.sequence(data, key, prefix, required)
        if values is None:
            return None
        if len(values) != 2 or not all(_is_int(v) and 0 <= v <= 255 for v in values):
            self.fail(f"{prefix}{key}", "deux octets [min, max] entre 0 et 255 sont attendus.")
            return None
        if values[0] > values[1]:
            self.fail(f"{prefix}{key}", "min doit être inférieur ou égal à max.")
            return None
        return values[0], values[1]

    def range(self, data, key, prefix, required=True, lo=None, invertible=False) -> Range | None:
        node = self.mapping(data, key, prefix, required)
        if node is None:
            return None
        inner = f"{prefix}{key}."
        invert = self.boolean(node, "invert", inner) if invertible else False
        lo_v, hi_v = (self.number(node, k, inner, True, lo=lo) for k in ("min", "max"))
        if lo_v is None or hi_v is None:
            return None
        if lo_v > hi_v:
            self.fail(f"{prefix}{key}", f"min ({lo_v:g}) doit être inférieur ou égal à max ({hi_v:g}).")
            return None
        return Range(lo_v, hi_v, invert)

    def file(self, relative: str | None, path: str, suffixes=None) -> None:
        if relative is None:
            return
        if suffixes and Path(relative).suffix.lower() not in suffixes:
            self.fail(path, f"« {relative} » : extension attendue {', '.join(suffixes)}.")
        elif self.folder is not None and not (self.folder / relative).is_file():
            self.fail(path, f"fichier « {relative} » introuvable dans le dossier de la fiche.")


def _parse_sources(p: _Parser, data) -> tuple[Source, ...]:
    items = p.sequence(data, "sources", "")
    out = []
    for index, item in enumerate(items or []):
        path = f"sources[{index}]."
        if not isinstance(item, Mapping):
            p.fail(f"sources[{index}]", "un dictionnaire {kind, url, note} est attendu.")
            continue
        kind = p.text(item, "kind", path, choices=SOURCE_KINDS)
        url = p.text(item, "url", path)
        note = item.get("note")
        if note is not None and not isinstance(note, str):
            p.fail(f"{path}note", "un texte est attendu.")
            note = None
        if kind and url:
            if "://" not in url:
                p.file(url, f"{path}url")
            out.append(Source(kind, url, note or ""))
    if items is not None and not items:
        p.fail("sources", "au moins une source est attendue.")
    return tuple(out)


def _parse_physical(p: _Parser, data, hazer: bool) -> Physical | None:
    node = p.mapping(data, "physical", "")
    if node is None:
        return None
    weight = p.number(node, "weight", "physical.", lo=0, strict_lo=True)
    dims = mount = None
    dim_node = p.mapping(node, "dimensions", "physical.", required=not hazer)
    if dim_node is not None:
        values = [p.number(dim_node, k, "physical.dimensions.", lo=0, strict_lo=True)
                  for k in ("width", "depth", "height")]
        dims = Dimensions(*values) if None not in values else None
    mount_node = p.mapping(node, "mount", "physical.", required=not hazer)
    if mount_node is not None:
        hook = p.number(mount_node, "hook_height", "physical.mount.", lo=0)
        tilt = p.number(mount_node, "tilt_axis_height", "physical.mount.")
        mount = Mount(hook, tilt) if None not in (hook, tilt) else None
    return Physical(weight, dims, mount) if weight is not None else None


def _parse_optics(p: _Parser, data, hazer: bool) -> Optics | None:
    node = p.mapping(data, "optics", "", required=not hazer)
    if node is None:
        return None
    pre = "optics."
    beam_type = p.text(node, "beam_type", pre, choices=("profile", "wash"))
    diameter = p.number(node, "lens_diameter", pre, lo=0, strict_lo=True)
    offset = p.number(node, "lens_offset", pre)
    flux = p.number(node, "flux", pre, lo=0, strict_lo=True)
    field = p.range(node, "field_angle", pre, required=False, lo=0)
    tubes = _parse_tubes(p, node)
    has_field, has_tubes = node.get("field_angle") is not None, node.get("lens_tubes") is not None
    if has_field and has_tubes:
        p.fail("optics", "field_angle et lens_tubes s'excluent.")
    elif not has_field and not has_tubes:
        p.fail("optics.field_angle", "obligatoire (zoom) ; sinon lens_tubes (lentilles fixes).")
    beam = p.range(node, "beam_angle", pre, required=beam_type == "wash", lo=0)
    ies = _parse_ies(p, node)
    invert = p.boolean(node, "zoom_invert", pre)
    if None in (beam_type, diameter, offset, flux):
        return None
    return Optics(beam_type, diameter, offset, flux, field, beam, tubes, invert, ies)


def _parse_ies(p: _Parser, node) -> tuple[IesProfile, ...]:
    raw = node.get("ies")
    if raw is None:
        return ()
    if isinstance(raw, str):
        p.file(raw, "optics.ies")
        return (IesProfile(None, raw),)
    if not isinstance(raw, list) or not raw:
        p.fail("optics.ies", "un chemin ou une liste {field_angle, file} est attendu.")
        return ()
    profiles = []
    for index, item in enumerate(raw):
        path = f"optics.ies[{index}]."
        if not isinstance(item, Mapping):
            p.fail(f"optics.ies[{index}]", "un dictionnaire {field_angle, file} est attendu.")
            continue
        angle = p.number(item, "field_angle", path, lo=0, strict_lo=True)
        file = p.text(item, "file", path)
        p.file(file, f"{path}file")
        if angle is not None and file:
            profiles.append(IesProfile(angle, file))
    angles = [q.field_angle for q in profiles]
    if len(set(angles)) != len(angles):
        p.fail("optics.ies", "deux profils ont le même field_angle.")
    return tuple(profiles)


def _parse_tubes(p: _Parser, node) -> tuple[LensTube, ...]:
    values = p.sequence(node, "lens_tubes", "optics.", required=False)
    if values is None:
        return ()
    if not values:
        p.fail("optics.lens_tubes", "au moins un tube est attendu.")
        return ()
    tubes = []
    for index, item in enumerate(values):
        path = f"optics.lens_tubes[{index}]."
        if not isinstance(item, Mapping):
            p.fail(f"optics.lens_tubes[{index}]",
                   "un dictionnaire {name, beam_angle, field_angle, lens_diameter, ies} est attendu.")
            continue
        name = p.text(item, "name", path)
        beam = p.number(item, "beam_angle", path, lo=0, strict_lo=True)
        field = p.number(item, "field_angle", path, lo=0, strict_lo=True)
        diameter = p.number(item, "lens_diameter", path, required=False, lo=0, strict_lo=True)
        ies = p.text(item, "ies", path, required=False)
        p.file(ies, f"{path}ies")
        if beam is not None and field is not None and beam > field:
            p.fail(path.rstrip("."), f"beam_angle ({beam:g}) doit être inférieur ou égal à field_angle ({field:g}).")
        elif name and beam is not None and field is not None:
            tubes.append(LensTube(name, beam, field, diameter, ies))
    names = [t.name for t in tubes]
    for name in {n for n in names if names.count(n) > 1}:
        p.fail("optics.lens_tubes", f"tube « {name} » déclaré deux fois.")
    if any(b.field_angle < a.field_angle for a, b in zip(tubes, tubes[1:])):
        p.fail("optics.lens_tubes", "les tubes doivent être triés par field_angle croissant.")
    return tuple(tubes)


def _parse_colour(p: _Parser, data) -> Colour:
    empty = Colour((), None, None, ())
    node = p.mapping(data, "colour", "", required=False)
    if node is None:
        return empty
    systems_raw = p.sequence(node, "systems", "colour.", required=False) or []
    bad = [s for s in systems_raw if s not in COLOUR_SYSTEMS]
    if bad:
        p.fail("colour.systems", f"système inconnu {bad}, attendu parmi {', '.join(COLOUR_SYSTEMS)}.")
    systems = tuple(s for s in systems_raw if s in COLOUR_SYSTEMS)
    cct = p.range(node, "cct_range", "colour.", required="cct" in systems, lo=0)
    cto = p.number(node, "cto_kelvin", "colour.", required="cto" in systems, lo=0, strict_lo=True)
    emitters = []
    items = p.sequence(node, "emitters", "colour.", required="emitters" in systems)
    for index, item in enumerate(items or []):
        path = f"colour.emitters[{index}]."
        if not isinstance(item, Mapping):
            p.fail(f"colour.emitters[{index}]", "un dictionnaire {attribute, rgb} est attendu.")
            continue
        attribute = p.text(item, "attribute", path, choices=EMITTER_ATTRIBUTES)
        rgb = p.triple(item, "rgb", path)
        if rgb is not None and not all(0 <= c <= 1 for c in rgb):
            p.fail(f"{path}rgb", "composantes attendues entre 0 et 1.")
        elif attribute and rgb is not None:
            emitters.append(Emitter(attribute, rgb))
    if "emitters" in systems and items is not None and not items:
        p.fail("colour.emitters", "au moins un émetteur est attendu.")
    return Colour(systems, cct, cto, tuple(emitters))


def _parse_motion(p: _Parser, data, hazer: bool) -> Motion | None:
    node = p.mapping(data, "motion", "", required=not hazer)
    if node is None:
        return None
    kind = p.text(node, "type", "motion.", choices=("moving", "static"))
    moving = kind == "moving"
    pan = p.range(node, "pan", "motion.", required=moving, invertible=True)
    tilt = p.range(node, "tilt", "motion.", required=moving, invertible=True)
    return Motion(kind, pan, tilt) if kind else None


def _parse_blades(p: _Parser, data) -> Blades | None:
    node = p.mapping(data, "blades", "", required=False)
    if node is None:
        return None
    pre = "blades."
    count = p.integer(node, "count", pre, required=False, lo=4, hi=4) or 4
    mode = p.text(node, "mode", pre, choices=("motorised", "manual"))
    gate = p.number(node, "gate_from_lens", pre)
    span = p.number(node, "span", pre, lo=0, strict_lo=True)
    limit = p.number(node, "angle_limit", pre, lo=0, strict_lo=True)
    travel_node = p.mapping(node, "travel", pre)
    travel = None
    if travel_node is not None:
        opened, closed = (p.number(travel_node, k, "blades.travel.") for k in ("open", "closed"))
        travel = Travel(opened, closed) if None not in (opened, closed) else None
    sides = p.sequence(node, "sides", pre)
    clean_sides: tuple[float, ...] = ()
    if sides is not None:
        if len(sides) != 4 or not all(_is_number(v) for v in sides):
            p.fail("blades.sides", "quatre angles sont attendus.")
        elif len({float(v) % 360 for v in sides}) != 4:
            p.fail("blades.sides", "les quatre angles doivent être distincts.")
        else:
            clean_sides = tuple(float(v) for v in sides)
    rotation = p.range(node, "rotation", pre, required=mode == "motorised", invertible=True)
    if None in (count, mode, gate, span, limit, travel) or not clean_sides:
        return None
    return Blades(count, mode, gate, span, travel, clean_sides, limit, rotation)


def _parse_gobos(p: _Parser, data) -> tuple[GoboWheel, ...]:
    node = p.mapping(data, "gobos", "", required=False)
    if node is None:
        return ()
    wheels = []
    names = set()
    for index, item in enumerate(p.sequence(node, "wheels", "gobos.") or []):
        path = f"gobos.wheels[{index}]."
        if not isinstance(item, Mapping):
            p.fail(f"gobos.wheels[{index}]", "un dictionnaire est attendu.")
            continue
        name = p.text(item, "name", path, choices=("gobo1", "gobo2"))
        if name in names:
            p.fail(f"{path}name", f"roue « {name} » déclarée deux fois.")
        names.add(name)
        rotation = item.get("rotation_range")
        if rotation is None:
            rotation = 360.0
        elif not _is_number(rotation) or rotation <= 0:
            p.fail(f"{path}rotation_range", "un nombre positif est attendu.")
            rotation = 360.0
        slots = []
        for k, slot in enumerate(p.sequence(item, "slots", path) or []):
            sp = f"{path}slots[{k}]."
            if not isinstance(slot, Mapping):
                p.fail(f"{path}slots[{k}]", "un dictionnaire {name, image, dmx} est attendu.")
                continue
            sname = p.text(slot, "name", sp)
            image = p.text(slot, "image", sp, required=False)
            p.file(image, f"{sp}image")
            dmx = p.byte_range(slot, "dmx", sp)
            if sname and dmx:
                slots.append(GoboSlot(sname, image, dmx))
        if name:
            wheels.append(GoboWheel(name, float(rotation), tuple(slots)))
    return tuple(wheels)


def _parse_iris(p: _Parser, data) -> Iris | None:
    node = p.mapping(data, "iris", "", required=False)
    if node is None:
        return None
    ratio = p.number(node, "min_ratio", "iris.", lo=0, hi=1)
    return Iris(ratio) if ratio is not None else None


def _parse_strobe(p: _Parser, data) -> Strobe | None:
    node = p.mapping(data, "strobe", "", required=False)
    if node is None:
        return None
    opened = p.byte_range(node, "open", "strobe.")
    closed = p.byte_range(node, "closed", "strobe.")
    ramp_node = p.mapping(node, "strobe", "strobe.")
    ramp = None
    if ramp_node is not None:
        start = p.integer(ramp_node, "from", "strobe.strobe.", lo=0, hi=255)
        stop = p.integer(ramp_node, "to", "strobe.strobe.", lo=0, hi=255)
        hz_min = p.number(ramp_node, "hz_min", "strobe.strobe.", lo=0)
        hz_max = p.number(ramp_node, "hz_max", "strobe.strobe.", lo=0)
        if None not in (start, stop, hz_min, hz_max):
            if start > stop or hz_min > hz_max:
                p.fail("strobe.strobe", "from et hz_min doivent être inférieurs ou égaux à to et hz_max.")
            else:
                ramp = StrobeRamp(start, stop, hz_min, hz_max)
    if None in (opened, closed, ramp):
        return None
    return Strobe(opened, closed, ramp)


def _parse_channel(p: _Parser, item, path: str, footprint: int | None) -> Channel | None:
    if not isinstance(item, Mapping):
        p.fail(path.rstrip("."), "un dictionnaire {offset, attribute, bits, default, fine} est attendu.")
        return None
    top = footprint or 512
    offset = p.integer(item, "offset", path, lo=1, hi=top)
    attribute = p.text(item, "attribute", path, pattern=_ATTRIBUTE_NAME)
    bits = p.integer(item, "bits", path)
    if bits is not None and bits not in (8, 16):
        p.fail(f"{path}bits", "8 ou 16 attendu.")
        bits = None
    ceiling = None if bits is None else (255 if bits == 8 else 65535)
    default = p.integer(item, "default", path, lo=0, hi=ceiling)
    fine = None
    if bits == 16 and offset is not None:
        raw = item.get("fine")
        fine = offset + 1 if raw is None else raw
        if not _is_int(fine) or not 1 <= fine <= top:
            p.fail(f"{path}fine", f"le canal fin doit être un offset entre 1 et {top}.")
            return None
    elif bits == 8 and item.get("fine") is not None:
        p.fail(f"{path}fine", "réservé aux canaux 16 bits.")
    curve, mode = _parse_curve(p, item, path)
    if None in (offset, attribute, bits, default):
        return None
    return Channel(offset, attribute, bits, default, fine, curve, mode)


def _parse_curve(p: _Parser, item, path: str) -> tuple[tuple[tuple[float, float], ...], str]:
    mode = p.text(item, "curve_mode", path, required=False, choices=("linear", "step")) or "linear"
    points = p.sequence(item, "curve", path, required=False)
    if points is None:
        if item.get("curve_mode") is not None:
            p.fail(f"{path}curve_mode", "réservé aux canaux qui ont une courbe.")
        return (), "linear"
    clean = []
    for k, point in enumerate(points):
        if not (isinstance(point, list) and len(point) == 2 and all(_is_number(v) for v in point)):
            p.fail(f"{path}curve[{k}]", "une paire [dmx, valeur] est attendue.")
        elif not 0 <= point[0] <= 1:
            p.fail(f"{path}curve[{k}]", "dmx normalisé entre 0 et 1 attendu.")
        else:
            clean.append((float(point[0]), float(point[1])))
    if len(clean) != len(points):
        return (), mode
    if len(clean) < 2:
        p.fail(f"{path}curve", "au moins deux points sont attendus.")
    elif any(b[0] <= a[0] for a, b in zip(clean, clean[1:])):
        p.fail(f"{path}curve", "le dmx doit être strictement croissant.")
    return tuple(clean), mode


def _parse_mode(p: _Parser, item, index: int) -> Mode | None:
    path = f"modes[{index}]."
    if not isinstance(item, Mapping):
        p.fail(f"modes[{index}]", "un dictionnaire {name, footprint, channels} est attendu.")
        return None
    name = p.text(item, "name", path)
    footprint = p.integer(item, "footprint", path, lo=1, hi=512)
    raw_channels = p.sequence(item, "channels", path)
    channels = []
    for k, raw in enumerate(raw_channels or []):
        channel = _parse_channel(p, raw, f"{path}channels[{k}].", footprint)
        if channel is not None:
            channels.append(channel)
    label = f"modes[{name or index}]"
    used: dict[int, str] = {}
    for channel in channels:
        for offset in channel.offsets:
            if offset in used:
                p.fail(label, f"offset {offset} utilisé deux fois ({used[offset]} et {channel.attribute}).")
            used[offset] = channel.attribute
    seen: set[str] = set()
    for channel in channels:
        if channel.attribute in seen and is_known_attribute(channel.attribute):
            p.fail(label, f"attribut « {channel.attribute} » présent deux fois.")
        seen.add(channel.attribute)
    if name is None or footprint is None or raw_channels is None:
        return None
    return Mode(name, footprint, tuple(channels))


def _parse_modes(p: _Parser, data) -> tuple[tuple[Mode, ...], str | None]:
    raw = p.sequence(data, "modes", "")
    modes = []
    for index, item in enumerate(raw or []):
        mode = _parse_mode(p, item, index)
        if mode is not None:
            modes.append(mode)
    if raw is not None and not raw:
        p.fail("modes", "au moins un mode est attendu.")
    names = [m.name for m in modes]
    for name in {n for n in names if names.count(n) > 1}:
        p.fail("modes", f"mode « {name} » déclaré deux fois.")
    default = p.text(data, "default_mode", "")
    if default is not None and modes and default not in names:
        p.fail("default_mode", f"« {default} » n'est pas un mode de la fiche ({', '.join(names)}).")
    return tuple(modes), default


def _parse_model3d(p: _Parser, data, hazer: bool, nested: bool = False, key="model3d") -> Model3D | None:
    node = p.mapping(data, key, "", required=not nested)
    if node is None:
        return None
    path = f"{key}."
    allowed = ("procedural", "none") if hazer else ("procedural", "mesh")
    kind = p.text(node, "kind", path, choices=("procedural",) if nested else allowed)
    if kind == "procedural":
        shape = p.text(node, "shape", path, choices=("pc", "profile", "box"))
        body_node = p.mapping(node, "body", path)
        body = None
        if body_node is not None:
            values = [p.number(body_node, k, f"{path}body.", lo=0, strict_lo=True)
                      for k in ("width", "depth", "height")]
            body = Body(*values) if None not in values else None
        barrel_node = p.mapping(node, "barrel", path, required=shape == "profile")
        barrel = None
        if barrel_node is not None:
            values = [p.number(barrel_node, k, f"{path}barrel.", lo=0, strict_lo=True)
                      for k in ("diameter", "length")]
            barrel = Barrel(*values) if None not in values else None
        yoke_node = p.mapping(node, "yoke", path, required=False)
        yoke = None
        if yoke_node is not None:
            values = [p.number(yoke_node, k, f"{path}yoke.", lo=0) for k in ("gap", "height")]
            yoke = Yoke(*values) if None not in values else None
        return Model3D("procedural", shape=shape, body=body, barrel=barrel, yoke=yoke)
    if kind == "mesh":
        parts_node = p.mapping(node, "parts", path)
        parts = []
        for name in MESH_PARTS:
            part = p.mapping(parts_node, name, f"{path}parts.") if parts_node is not None else None
            if part is None:
                continue
            file = p.text(part, "file", f"{path}parts.{name}.")
            p.file(file, f"{path}parts.{name}.file", MESH_SUFFIXES)
            offset = p.triple(part, "offset", f"{path}parts.{name}.")
            if file and offset:
                parts.append(MeshPart(name, file, offset))
        fallback = _parse_model3d(p, node, hazer, nested=True, key="fallback") \
            if node.get("fallback") is not None else None
        return Model3D("mesh", parts=tuple(parts), fallback=fallback)
    if kind == "none":
        return Model3D("none")
    return None


def _parse_qlc(p: _Parser, data) -> QlcLink | None:
    node = p.mapping(data, "qlc", "", required=False)
    if node is None:
        return None
    manufacturer = p.text(node, "manufacturer", "qlc.")
    model = p.text(node, "model", "qlc.")
    modes = p.mapping(node, "modes", "qlc.")
    verified = node.get("verified")
    if modes is not None and not all(isinstance(k, str) and isinstance(v, str) for k, v in modes.items()):
        p.fail("qlc.modes", "correspondance {mode de la fiche: mode QLC+} de textes attendue.")
        modes = None
    if None in (manufacturer, model, modes):
        return None
    return QlcLink(manufacturer, model, tuple(modes.items()), None if verified is None else str(verified))


def validate_fixture(data: Any, folder: Path | None = None) -> Fixture | list[str]:
    """Check a raw sheet (spec 12.2, 12.7). Returns a Fixture or French error lines.

    With `folder`, the sheet must live in a folder named after its `id` and every
    file it cites must exist there.
    """
    if not isinstance(data, Mapping):
        return ["fiche : un dictionnaire YAML est attendu."]
    p = _Parser(folder)
    version = p.integer(data, "version", "", lo=1, hi=1)
    fid = p.text(data, "id", "", pattern=_ID)
    if fid and folder is not None and folder.name != fid:
        p.fail("id", f"« {fid} » doit être égal au nom du dossier « {folder.name} ».")
    manufacturer = p.text(data, "manufacturer", "")
    model = p.text(data, "model", "")
    family = p.text(data, "family", "", choices=FAMILIES)
    hazer = family == "hazer"
    sources = _parse_sources(p, data)
    physical = _parse_physical(p, data, hazer)
    optics = _parse_optics(p, data, hazer)
    colour = _parse_colour(p, data)
    motion = _parse_motion(p, data, hazer)
    blades = _parse_blades(p, data)
    gobos = _parse_gobos(p, data)
    iris = _parse_iris(p, data)
    strobe = _parse_strobe(p, data)
    modes, default_mode = _parse_modes(p, data)
    model3d = _parse_model3d(p, data, hazer)
    qlc = _parse_qlc(p, data)
    if p.errors:
        return p.errors
    return Fixture(version, fid, manufacturer, model, family, sources, physical, optics, colour,
                   motion, blades, gobos, iris, strobe, modes, default_mode, model3d, qlc, folder)


def load_fixture(folder: Path) -> Fixture | list[str]:
    """Read `<folder>/fixture.yaml` and validate it. Errors are French lines."""
    folder = Path(folder)
    try:
        data = yaml.safe_load((folder / SHEET_NAME).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as error:
        return [f"fiche illisible : {error}"]
    except yaml.YAMLError as error:
        return [f"YAML invalide : {error}"]
    return validate_fixture(data, folder)


# ----------------------------------------------------------------- library

@dataclass(frozen=True)
class Library:
    """Valid sheets by id (sorted) and the French messages raised while reading them."""

    fixtures: Mapping[str, Fixture]
    messages: tuple[str, ...] = ()

    def get(self, fixture_id: str) -> Fixture | None:
        return self.fixtures.get(fixture_id)

    def __contains__(self, fixture_id) -> bool:
        return fixture_id in self.fixtures

    def __len__(self) -> int:
        return len(self.fixtures)

    def ids_by_family(self, *families: str) -> tuple[str, ...]:
        return tuple(i for i, f in self.fixtures.items() if f.family in families)


EMPTY_LIBRARY = Library({}, ())


def discover(directories: Iterable[Path]) -> Library:
    """Read every `<dir>/<id>/fixture.yaml`. Later directories override earlier ones.

    Pass the shipped directory first, then the user's. Folders without a sheet
    are skipped; an invalid sheet is dropped with a message listing its errors.
    """
    found: dict[str, Fixture] = {}
    messages: list[str] = []
    for rank, directory in enumerate(directories):
        directory = Path(directory)
        if not directory.is_dir():
            continue
        for folder in sorted(p for p in directory.iterdir() if (p / SHEET_NAME).is_file()):
            result = load_fixture(folder)
            if isinstance(result, list):
                messages.append(f"Fiche « {folder.name} » écartée : {' ; '.join(result)}")
                continue
            if result.id in found:
                messages.append(f"La fiche {'utilisateur ' if rank else ''}« {result.id} » "
                                f"({folder}) remplace la fiche déjà chargée.")
            found[result.id] = result
    return Library(dict(sorted(found.items())), tuple(messages))


# -------------------------------------------------------------------- DMX

def encode(v: float, bits: int) -> tuple[int, ...]:
    """Normalized `v` to DMX bytes, coarse first: `round(255 v)` or `round(65535 v)` split."""
    v = min(max(v, 0.0), 1.0)
    if bits == 8:
        return (round(255 * v),)
    if bits == 16:
        n = round(65535 * v)
        return (n >> 8, n & 255)
    raise ValueError(f"bits doit valoir 8 ou 16, reçu {bits}.")


def to_properties(v: float, bits: int) -> tuple[float, ...]:
    """Scene property values (`byte / 255`) of `v`, one per byte of the channel."""
    return tuple(b / 255 for b in encode(v, bits))


def decode(c: float, f: float, bits: int) -> float:
    """Normalized `v` from the scene properties of the coarse (`c`) and fine (`f`) bytes.

    16 bits: `(256 c + f) / 257`, exactly `N / 65535` (spec 12.4); `f` is ignored for 8 bits.
    """
    if bits == 8:
        return c
    if bits == 16:
        return (256 * c + f) / 257
    raise ValueError(f"bits doit valoir 8 ou 16, reçu {bits}.")


# Kim et al. cubic approximation of the Planckian locus, valid from 1667 K to 25000 K.
def cct_to_rgb(kelvin: float) -> tuple[float, float, float]:
    """Linear sRGB of a black body, scaled so the largest component is 1 (spec 15.2)."""
    t = min(max(float(kelvin), 1667.0), 25000.0)
    if t <= 4000:
        x = -0.2661239e9 / t**3 - 0.2343589e6 / t**2 + 0.8776956e3 / t + 0.179910
    else:
        x = -3.0258469e9 / t**3 + 2.1070379e6 / t**2 + 0.2226347e3 / t + 0.240390
    if t <= 2222:
        y = -1.1063814 * x**3 - 1.34811020 * x**2 + 2.18555832 * x - 0.20219683
    elif t <= 4000:
        y = -0.9549476 * x**3 - 1.37418593 * x**2 + 2.09137015 * x - 0.16748867
    else:
        y = 3.0817580 * x**3 - 5.87338670 * x**2 + 3.75112997 * x - 0.37001483
    big_x, big_z = x / y, (1 - x - y) / y
    rgb = (3.2404542 * big_x - 1.5371385 - 0.4985314 * big_z,
           -0.9692660 * big_x + 1.8760108 + 0.0415560 * big_z,
           0.0556434 * big_x - 0.2040259 + 1.0572252 * big_z)
    rgb = tuple(max(c, 0.0) for c in rgb)
    top = max(rgb)
    return tuple(c / top for c in rgb)


# ------------------------------------------------------------- photometry

# Starting values of spec 14.8, to be replaced by the Cycles calibration.
W_PER_CD_SPOT = 4 * math.pi**2 / 683
W_PER_LM_AREA = math.pi / 683
EXPOSURE_GAIN = 1.0


def max_energy(beam_type: str, flux: float, field_angle: float) -> float:
    """Blender light power in W at full dimmer: spot from intensity over the field, area from flux."""
    if beam_type == "profile":
        solid_angle = 2 * math.pi * (1 - math.cos(math.radians(field_angle) / 2))
        return EXPOSURE_GAIN * W_PER_CD_SPOT * flux / solid_angle
    return EXPOSURE_GAIN * W_PER_LM_AREA * flux
