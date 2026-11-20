#!/usr/bin/env python3
"""GDTF to fixture sheet (spec 12.6).

    python tools/gdtf_to_fiche.py <file.gdtf> --id <id> [--mode <name> ...] --out <folder>

Reads `description.xml` of a GDTF archive and writes a `fixture.yaml` to complete
by hand, plus `source/` (the GDTF), `meshes/` and `gobos/`. Keys the GDTF cannot
give stay `null`, which makes the sheet invalid until they are filled in.
Standard library only, apart from the repository's `core/meshio.py`.
"""

from __future__ import annotations

import argparse
import io
import json
import math
import re
import shutil
import struct
import sys
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "blender" / "theatre_stage"))
from core import meshio  # noqa: E402
from core.meshes import Mesh  # noqa: E402

CURVE_ATTRIBUTES = ("cct", "cto", "zoom")

ATTRIBUTE_MAP = {
    "Dimmer": "dimmer", "Pan": "pan", "Tilt": "tilt", "Zoom": "zoom",
    "ColorAdd_R": "color_r", "ColorAdd_G": "color_g", "ColorAdd_B": "color_b", "ColorAdd_W": "color_w",
    "ColorSub_C": "cyan", "ColorSub_M": "magenta", "ColorSub_Y": "yellow",
    "CTO": "cto", "CTC": "cct", "Shutter1": "strobe", "Shutter1Strobe": "strobe",
    "Gobo1": "gobo1", "Gobo2": "gobo2", "Gobo1Pos": "gobo1_rot", "Gobo2Pos": "gobo2_rot", "Iris": "iris",
    "BladeRot": "blade_rot", "ShaperRot": "blade_rot",
    **{f"Blade{n}{s}": f"blade_{n}{s.lower()}" for n in range(1, 5) for s in "AB"},
    **{f"Blade{n}Rot": f"blade_{n}_rot" for n in range(1, 5)},
}
BEAM_TYPES = {"spot": "profile", "rectangle": "profile", "wash": "wash", "pc": "wash", "fresnel": "wash"}
SCALES = (1.0, 0.001, 0.01, 0.0254)
PARTS = ("base", "yoke", "head")
TODO = "à compléter"
_PLAIN = re.compile(r"[A-Za-z_][A-Za-z0-9_./-]*")
_RESERVED = {"null", "true", "false", "yes", "no", "on", "off", "y", "n", "~"}


@dataclass
class Report:
    fixture_id: str
    modes: list[tuple[str, int]] = field(default_factory=list)
    meshes: list[dict] = field(default_factory=list)
    gobos: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    document: dict = field(default_factory=dict)


# ------------------------------------------------------------- GDTF values

def _float(text, default=None):
    try:
        return float(text)
    except (TypeError, ValueError):
        return default


def _dmx_value(text, channel_bytes: int) -> int | None:
    """`value/bytes` of GDTF to an integer in the resolution of the channel."""
    if not text or text == "None":
        return None
    value, _, size = text.partition("/")
    try:
        value, size = int(value), int(size or 1)
    except ValueError:
        return None
    if size < channel_bytes:
        return value << (8 * (channel_bytes - size))
    return value >> (8 * (size - channel_bytes))


def _translation(position: str | None) -> tuple[float, float, float]:
    """Translation of a GDTF `{r0}{r1}{r2}{r3}` row-major 4x4 matrix."""
    rows = re.findall(r"\{([^}]*)\}", position or "")
    try:
        x, y, z = (float(rows[i].split(",")[3]) for i in range(3))
        return (x, y, z)
    except (IndexError, ValueError):
        return (0.0, 0.0, 0.0)


def _unknown_name(raw: str) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", raw.lower()).strip("_") or "channel"


@dataclass
class _Function:
    attribute: str
    name: str
    start: int
    stop: int
    phys_from: float | None
    phys_to: float | None
    wheel: str | None
    slots: list[tuple[int, str, int, int]]  # (wheel slot index, name, from, to)
    set_values: list[tuple[int, float]] = field(default_factory=list)  # (set start, PhysicalFrom)


@dataclass
class _Channel:
    offsets: list[int]
    geometry: str
    attribute: str
    default: int
    functions: list[_Function]

    @property
    def size(self) -> int:
        return len(self.offsets)


def _read_channel(element) -> _Channel | None:
    offsets = [int(o) for o in re.findall(r"\d+", element.get("Offset") or "")]
    logical = element.find("LogicalChannel")
    if not offsets or logical is None:
        return None
    size = min(len(offsets), 2)
    top = 256 ** size - 1
    raw_functions = logical.findall("ChannelFunction")
    starts = [_dmx_value(f.get("DMXFrom"), size) or 0 for f in raw_functions]
    functions = []
    for index, raw in enumerate(raw_functions):
        start = starts[index]
        stop = (starts[index + 1] - 1) if index + 1 < len(raw_functions) else top
        sets = raw.findall("ChannelSet")
        set_starts = [_dmx_value(s.get("DMXFrom"), size) or 0 for s in sets]
        slots = []
        for k, item in enumerate(sets):
            end = (set_starts[k + 1] - 1) if k + 1 < len(sets) else stop
            slots.append((int(item.get("WheelSlotIndex") or 0), item.get("Name") or "", set_starts[k], end))
        set_values = [(set_starts[k], v) for k, item in enumerate(sets)
                      if (v := _float(item.get("PhysicalFrom"))) is not None]
        functions.append(_Function(
            raw.get("Attribute") or "", raw.get("Name") or "", start, stop,
            _float(raw.get("PhysicalFrom")), _float(raw.get("PhysicalTo")), raw.get("Wheel"), slots, set_values))
    default = _dmx_value(element.get("Default"), size)
    if default is None:
        wanted = (element.get("InitialFunction") or "").split(".")[-1]
        initial = next((f for f in raw_functions if f.get("Name") == wanted), None)
        initial = initial if initial is not None else (raw_functions[0] if raw_functions else None)
        default = _dmx_value(initial.get("Default"), size) if initial is not None else None
    return _Channel(offsets, element.get("Geometry") or "", logical.get("Attribute") or "",
                    default or 0, functions)


def _curve(channel: _Channel) -> tuple[list[list[float]], str] | None:
    """`[dmx, value]` points of a channel whose functions or sets carry several physical values."""
    top = 256 ** min(channel.size, 2) - 1
    sets = [pair for f in channel.functions for pair in f.set_values]
    if len(sets) >= 2:
        points, mode = [[start / top, value] for start, value in sets], "step"
    else:
        ranges = [f for f in channel.functions if f.phys_from is not None and f.phys_to is not None]
        if len(ranges) < 2:
            return None
        points = [[x / top, v] for f in ranges for x, v in ((f.start, f.phys_from), (f.stop, f.phys_to))]
        mode = "linear"
    if any(b[0] <= a[0] for a, b in zip(points, points[1:])):
        return None
    return [[round(x, 6), v] for x, v in points], mode


def _mode_channels(mode) -> list[_Channel]:
    found = [_read_channel(e) for e in mode.iter("DMXChannel")]
    return sorted((c for c in found if c is not None), key=lambda c: c.offsets[0])


def _name_channels(channels: list[_Channel], warnings: list[str]) -> list[dict]:
    """Sheet channels of a mode: known attributes once, everything else kept under a unique name."""
    taken: set[str] = set()
    out = []
    for channel in channels:
        mapped = ATTRIBUTE_MAP.get(channel.attribute)
        name = mapped if mapped and mapped not in taken else None
        if name is None:
            name = _unknown_name(channel.attribute)
            if mapped or name in taken or name in ATTRIBUTE_MAP.values():
                name = _unknown_name(f"{channel.geometry}_{channel.attribute}")
            base, n = name, 2
            while name in taken or name in ATTRIBUTE_MAP.values():
                name, n = f"{base}_{n}", n + 1
        taken.add(name)
        if channel.size > 2:
            warnings.append(f"Canal {channel.attribute} sur {channel.size} octets : seuls deux sont gardés.")
        entry = {"offset": channel.offsets[0], "attribute": name,
                 "bits": 16 if channel.size >= 2 else 8, "default": channel.default}
        if channel.size >= 2:
            entry["fine"] = channel.offsets[1]
        curve = _curve(channel) if name in CURVE_ATTRIBUTES else None
        if curve:
            entry["curve"], mode = curve
            if mode == "step":
                entry["curve_mode"] = mode
        out.append(entry)
    return out


# ------------------------------------------------------------- 3DS and units

def read_3ds(data: bytes) -> Mesh:
    """Vertices and faces of every mesh object of a 3DS file, merged, in file units.

    The local-matrix chunk (0x4160) is not applied: 3DS stores vertices in world space.
    """
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, ...]] = []

    def walk(pos: int, end: int, base: int) -> None:
        while pos + 6 <= end:
            chunk, length = struct.unpack_from("<HI", data, pos)
            if length < 6:
                return
            body, stop = pos + 6, min(pos + length, end)
            if chunk in (0x4D4D, 0x3D3D, 0x4100):
                walk(body, stop, len(vertices) if chunk == 0x4100 else base)
            elif chunk == 0x4000:
                walk(data.index(b"\0", body) + 1, stop, base)
            elif chunk == 0x4110:
                count = struct.unpack_from("<H", data, body)[0]
                vertices.extend(struct.unpack_from("<3f", data, body + 2 + 12 * i) for i in range(count))
            elif chunk == 0x4120:
                count = struct.unpack_from("<H", data, body)[0]
                for i in range(count):
                    a, b, c, _ = struct.unpack_from("<4H", data, body + 2 + 8 * i)
                    faces.append((base + a, base + b, base + c))
            pos += length

    walk(0, len(data), 0)
    return Mesh(tuple(vertices), tuple(faces))


def detect_scale(mesh: Mesh, length: float, width: float, height: float, default: float) -> float:
    """Factor to metres that best matches the mesh extents to the GDTF Model dimensions."""
    if not mesh.vertices or not min(length, width, height) > 0:
        return default
    low, high = meshio.bounds(mesh)
    extents = sorted(h - l for l, h in zip(low, high))
    wanted = sorted((length, width, height))
    if extents[-1] <= 0:
        return default
    ratio = wanted[-1] / extents[-1]
    return min(SCALES, key=lambda s: abs(math.log(s / ratio)))


def scaled(mesh: Mesh, factor: float) -> Mesh:
    return Mesh(tuple((x * factor, y * factor, z * factor) for x, y, z in mesh.vertices), mesh.faces)


# ------------------------------------------------------------------- YAML

def _scalar(value) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(round(value, 6))
    text = str(value)
    if _PLAIN.fullmatch(text) and text.lower() not in _RESERVED:
        return text
    return json.dumps(text, ensure_ascii=False)


def _is_flat(value) -> bool:
    """True for a list of scalars or a dict of scalars and lists of scalars (one-line flow style)."""
    if isinstance(value, dict):
        return all(not isinstance(v, dict) and (not isinstance(v, list) or _is_flat(v)) for v in value.values())
    return isinstance(value, list) and all(
        not isinstance(v, dict) and (not isinstance(v, list) or _is_flat(v)) for v in value)


def _flow(value) -> str:
    if isinstance(value, dict):
        return "{" + ", ".join(f"{_scalar(k)}: {_flow(v)}" for k, v in value.items()) + "}"
    if isinstance(value, list):
        return "[" + ", ".join(_flow(v) for v in value) + "]"
    return _scalar(value)


def _emit(value, indent: int) -> list[str]:
    pad = " " * indent
    lines: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            head = f"{pad}{_scalar(key)}:"
            if isinstance(item, (dict, list)) and not item:
                lines.append(f"{head} {'{}' if isinstance(item, dict) else '[]'}")
            elif isinstance(item, list) and _is_flat(item):
                lines.append(f"{head} {_flow(item)}")
            elif isinstance(item, (dict, list)):
                lines.append(head)
                lines += _emit(item, indent + 2)
            else:
                lines.append(f"{head} {_scalar(item)}" + (f"  # {TODO}" if item is None else ""))
    else:
        for item in value:
            if _is_flat(item) if isinstance(item, dict) else not isinstance(item, list):
                lines.append(f"{pad}- {_flow(item) if isinstance(item, dict) else _scalar(item)}")
            else:
                inner = _emit(item, indent + 2)
                lines.append(f"{pad}- {inner[0].lstrip()}")
                lines += inner[1:]
    return lines


def to_yaml(document: dict) -> str:
    header = ("# Fiche générée par tools/gdtf_to_fiche.py : à compléter à la main (spec 12.6).\n"
              "# Les valeurs null obligatoires rendent la fiche invalide tant qu'elles restent vides.\n")
    return header + "\n".join(_emit(document, 0)) + "\n"


# --------------------------------------------------------------- conversion

class _Gdtf:
    def __init__(self, path: Path):
        self.path = path
        self.archive = zipfile.ZipFile(path)
        root = ElementTree.fromstring(self.archive.read("description.xml"))
        fixture_type = root.find("FixtureType")
        if fixture_type is None:
            raise SystemExit(f"{path.name} : pas de FixtureType dans description.xml.")
        self.type = fixture_type
        self.names = {n.lower(): n for n in self.archive.namelist()}

    def member(self, *candidates: str) -> str | None:
        return next((self.names[c.lower()] for c in candidates if c.lower() in self.names), None)

    def read(self, member: str) -> bytes:
        return self.archive.read(member)


def _geometry_parts(gdtf: _Gdtf) -> dict[str, tuple[str, tuple[float, float, float]]]:
    """role -> (model name, offset from the parent part) from the geometry tree."""
    models = {m.get("Name"): m for m in gdtf.type.iter("Model")}
    parts: dict[str, tuple[str, tuple[float, float, float]]] = {}

    def walk(element, carried):
        for child in element:
            if child.get("Name") is None or child.tag in ("Beam", "WiringObject"):
                continue
            dx, dy, dz = _translation(child.get("Position"))
            here = (carried[0] + dx, carried[1] + dy, carried[2] + dz)
            model = models.get(child.get("Model"))
            role, model_name = None, ""
            if model is not None and model.get("File"):
                model_name = model.get("Name", "")
                role = next((r for r in PARTS if r in (model_name.lower(), model.get("File", "").lower())), None)
            if role and role not in parts:
                parts[role] = (model_name, here)
                here = (0.0, 0.0, 0.0)
            walk(child, here)

    geometries = gdtf.type.find("Geometries")
    if geometries is not None:
        walk(geometries, (0.0, 0.0, 0.0))
    return parts


def _convert_models(gdtf: _Gdtf, out: Path, report: Report):
    """Copy or convert the part meshes. Returns (parts block, dimensions or None)."""
    models = {m.get("Name"): m for m in gdtf.type.iter("Model")}
    roles = _geometry_parts(gdtf)
    parts_block, placed = {}, []
    carried = (0.0, 0.0, 0.0)
    for role in PARTS:
        info = roles.get(role)
        if info is None:
            continue
        model = models[info[0]]
        file = model.get("File") or ""
        if re.search(r"[\\/]|^\.+$", file):
            report.warnings.append(f"Maillage « {file} » ignoré : un nom de fichier sans chemin est attendu.")
            continue
        dims = [_float(model.get(k), 0.0) for k in ("Length", "Width", "Height")]
        glb = gdtf.member(f"models/gltf/{file}.glb", f"models/glb/{file}.glb")
        tds = gdtf.member(f"models/3ds/{file}.3ds")
        target = out / "meshes"
        if glb:
            target.mkdir(parents=True, exist_ok=True)
            (target / f"{file}.glb").write_bytes(gdtf.read(glb))
            mesh = meshio.read_glb(target / f"{file}.glb")
            factor = detect_scale(mesh, *dims, default=1.0)
            if factor != 1.0:
                report.warnings.append(f"{file}.glb : échelle {factor:g} détectée, fichier copié tel quel.")
            name, fmt = f"meshes/{file}.glb", "glb"
        elif tds:
            raw = read_3ds(gdtf.read(tds))
            factor = detect_scale(raw, *dims, default=0.001)
            mesh = scaled(raw, factor)
            target.mkdir(parents=True, exist_ok=True)
            meshio.write_obj(target / f"{file}.obj", mesh, name=file)
            name, fmt = f"meshes/{file}.obj", "3ds"
        else:
            report.warnings.append(f"Maillage « {file} » introuvable dans le GDTF.")
            continue
        low, high = meshio.bounds(mesh) if mesh.vertices else ((0,) * 3, (0,) * 3)
        report.meshes.append({"file": name, "source": fmt, "scale": factor, "min": low, "max": high})
        offset = info[1]
        parts_block[role] = {"file": name, "offset": [round(v, 6) for v in offset]}
        carried = tuple(c + o for c, o in zip(carried, offset))
        placed.append((tuple(c + l for c, l in zip(carried, low)), tuple(c + h for c, h in zip(carried, high))))
    dimensions = None
    if placed:
        lows = [min(p[0][i] for p in placed) for i in range(3)]
        highs = [max(p[1][i] for p in placed) for i in range(3)]
        dimensions = {k: round(h - l, 6) for k, l, h in zip(("width", "depth", "height"), lows, highs)}
    return parts_block, dimensions


def _first(channels: list[_Channel], attribute: str):
    for channel in channels:
        if channel.attribute == attribute:
            return channel
    return None


def _function(channels, attribute):
    channel = _first(channels, attribute)
    if channel is None:
        return None
    return next((f for f in channel.functions if f.attribute == attribute), None)


def _span(channels, attribute, invertible: bool = False) -> dict | None:
    """Physical min and max over every function of a channel that carries `attribute`.

    With `invertible`, `invert: true` is added when the first function runs downwards (spec 12.2).
    """
    channel = _first(channels, attribute)
    functions = [f for f in (channel.functions if channel else []) if f.attribute == attribute]
    values = [v for f in functions for v in (f.phys_from, f.phys_to) if v is not None]
    if not values:
        return None
    span: dict = {"min": min(values), "max": max(values)}
    first = functions[0]
    if invertible and first.phys_from is not None and first.phys_to is not None and first.phys_from > first.phys_to:
        span["invert"] = True
    return span


def _gobos(gdtf: _Gdtf, channels: list[_Channel], out: Path, report: Report) -> list[dict]:
    wheels_xml = {w.get("Name"): w for w in gdtf.type.iter("Wheel")}
    wheels = []
    for attribute in ("Gobo1", "Gobo2"):
        channel = _first(channels, attribute)
        if channel is None:
            continue
        slots, seen = [], set()
        shift = 8 * (min(channel.size, 2) - 1)
        for function in (f for f in channel.functions if f.attribute == attribute):
            wheel = wheels_xml.get(function.wheel)
            for index, name, start, stop in function.slots:
                if index < 1 or index in seen:
                    continue
                seen.add(index)
                items = list(wheel) if wheel is not None else []
                slot = items[index - 1] if index <= len(items) else None
                label = (slot.get("Name") if slot is not None else None) or name or f"slot{index}"
                image = None
                media = slot.get("MediaFileName") if slot is not None else None
                member = gdtf.member(*(f"wheels/{media}{ext}" for ext in (".png", ".jpg", ".jpeg"))) if media else None
                if member:
                    image = f"gobos/{Path(member).name}"
                    (out / "gobos").mkdir(parents=True, exist_ok=True)
                    (out / image).write_bytes(gdtf.read(member))
                    report.gobos.append(image)
                slots.append({"name": label, "image": image, "dmx": [start >> shift, stop >> shift]})
        if slots:
            wheels.append({"name": attribute.lower(), "rotation_range": 360, "slots": slots})
    return wheels


def _strobe(channels) -> dict | None:
    channel = _first(channels, "Shutter1")
    if channel is None:
        return None
    shift = 8 * (min(channel.size, 2) - 1)
    segments = []
    for function in channel.functions:
        for _, name, start, stop in (function.slots or [(0, function.name, function.start, function.stop)]):
            segments.append((function.attribute, name.lower(), start >> shift, stop >> shift))
    closed = next(([s[2], s[3]] for s in segments if s[0] == "Shutter1" and "clos" in s[1]), None)
    opened = next(([s[2], s[3]] for s in segments if s[0] == "Shutter1" and s[1].startswith("open")), None)
    ramp = next((f for f in channel.functions if f.attribute == "Shutter1Strobe"), None)
    stroke = None
    if ramp is not None and ramp.phys_from is not None and ramp.phys_to is not None:
        stroke = {"from": ramp.start >> shift, "to": ramp.stop >> shift,
                  "hz_min": min(ramp.phys_from, ramp.phys_to), "hz_max": max(ramp.phys_from, ramp.phys_to)}
    return {"open": opened, "closed": closed, "strobe": stroke}


def _optics(gdtf: _Gdtf, channels: list[_Channel]) -> dict:
    beams = [b for b in gdtf.type.iter("Beam") if (b.get("BeamType") or "").lower() != "none"]
    zoom, zoom_span = _function(channels, "Zoom"), _span(channels, "Zoom")
    kinds = {BEAM_TYPES.get((b.get("BeamType") or "").lower()) for b in beams} - {None}
    flux = sum(_float(b.get("LuminousFlux"), 0.0) for b in beams)
    radius = _float(beams[0].get("BeamRadius")) if len(beams) == 1 else None
    return {
        "beam_type": kinds.pop() if len(kinds) == 1 else None,
        "lens_diameter": None if radius is None else round(2 * radius, 6),
        "lens_offset": None,
        "flux": round(flux, 3) if flux else None,
        "field_angle": None,
        "beam_angle": zoom_span,
        "zoom_invert": bool(zoom and zoom.phys_from is not None and zoom.phys_to is not None
                            and zoom.phys_from > zoom.phys_to),
    }


def _colour(channels) -> dict | None:
    attributes = {c.attribute for c in channels}
    systems = [name for name, wanted in (("rgbw", "ColorAdd_R"), ("cmy", "ColorSub_C"),
                                         ("cto", "CTO"), ("cct", "CTC")) if wanted in attributes]
    if not systems:
        return None
    colour: dict = {"systems": systems}
    if "cct" in systems:
        colour["cct_range"] = _span(channels, "CTC")
    if "cto" in systems:
        span = _span(channels, "CTO")
        colour["cto_kelvin"] = span["min"] if span and span["min"] > 0 else None
    return colour


def _blades(channels) -> dict | None:
    if not any(re.fullmatch(r"Blade[1-4][AB]", c.attribute) for c in channels):
        return None
    return {"count": 4, "mode": "motorised", "gate_from_lens": None, "span": None,
            "travel": {"open": None, "closed": None}, "sides": None, "angle_limit": None,
            "rotation": _span(channels, "BladeRot", True) or _span(channels, "ShaperRot", True)}


def convert(gdtf_path, out, fixture_id: str | None = None, modes: list[str] | None = None) -> Report:
    """Write the sheet folder `out` from a GDTF file and return what was found."""
    gdtf_path, out = Path(gdtf_path), Path(out)
    gdtf = _Gdtf(gdtf_path)
    ft = gdtf.type
    manufacturer, model = ft.get("Manufacturer") or "", ft.get("Name") or ft.get("LongName") or ""
    fixture_id = fixture_id or _unknown_name(f"{manufacturer}_{model}")
    if not re.fullmatch(r"[a-z0-9_]+", fixture_id):
        raise SystemExit(f"Identifiant invalide « {fixture_id} » : a-z, 0-9 et _ seulement.")
    report = Report(fixture_id)

    mode_elements = ft.findall("DMXModes/DMXMode")
    if modes:
        missing = [m for m in modes if m not in [e.get("Name") for e in mode_elements]]
        if missing:
            raise SystemExit(f"Mode(s) introuvable(s) : {', '.join(missing)}")
        mode_elements = [e for e in mode_elements if e.get("Name") in modes]
    sheet_modes, analysed = [], None
    for element in mode_elements:
        channels = _mode_channels(element)
        footprint = max((o for c in channels for o in c.offsets), default=0)
        sheet_modes.append({"name": element.get("Name"), "footprint": footprint,
                            "channels": _name_channels(channels, report.warnings)})
        report.modes.append((element.get("Name") or "", footprint))
        if analysed is None or len(channels) > len(analysed):
            analysed = channels
    channels = analysed or []
    attributes = {c.attribute for c in channels}

    out.mkdir(parents=True, exist_ok=True)
    (out / "source").mkdir(exist_ok=True)
    shutil.copyfile(gdtf_path, out / "source" / gdtf_path.name)
    parts, dimensions = _convert_models(gdtf, out, report)

    weight = ft.find("PhysicalDescriptions/Properties/Weight")
    moving = "Pan" in attributes or "Tilt" in attributes
    document: dict = {
        "version": 1, "id": fixture_id, "manufacturer": manufacturer, "model": model, "family": None,
        "sources": [{"kind": "gdtf", "url": f"source/{gdtf_path.name}", "note": ft.get("Description") or ""}],
        "physical": {"weight": _float(weight.get("Value")) if weight is not None else None,
                     "dimensions": dimensions, "mount": {"hook_height": None, "tilt_axis_height": None}},
        "optics": _optics(gdtf, channels),
    }
    colour = _colour(channels)
    if colour:
        document["colour"] = colour
    document["motion"] = {"type": "moving" if moving else "static",
                          "pan": _span(channels, "Pan", True), "tilt": _span(channels, "Tilt", True)}
    if not moving:
        document["motion"] = {"type": "static"}
    blades = _blades(channels)
    if blades:
        document["blades"] = blades
    wheels = _gobos(gdtf, channels, out, report)
    if wheels:
        document["gobos"] = {"wheels": wheels}
    iris = _span(channels, "Iris")
    if iris:
        document["iris"] = {"min_ratio": min(max(iris["min"], 0.0), 1.0)}
    strobe = _strobe(channels)
    if strobe:
        document["strobe"] = strobe
    document["modes"] = sheet_modes
    document["default_mode"] = sheet_modes[0]["name"] if sheet_modes else None
    document["model3d"] = {"kind": "mesh", "parts": parts} if parts else {"kind": None}
    report.document = document
    (out / "fixture.yaml").write_bytes(to_yaml(document).encode("utf-8"))
    return report


def summary(report: Report) -> str:
    lines = [f"Fiche « {report.fixture_id} » : {len(report.modes)} mode(s)"]
    lines += [f"  mode {name!r} : empreinte {footprint}" for name, footprint in report.modes]
    for mesh in report.meshes:
        size = " x ".join(f"{h - l:.4f}" for l, h in zip(mesh["min"], mesh["max"]))
        lines.append(f"  maillage {mesh['file']} ({mesh['source']}, échelle {mesh['scale']:g}) : {size} m")
    lines.append(f"  gobos extraits : {len(report.gobos)}")
    lines += [f"  attention : {w}" for w in report.warnings]
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Écrit une fiche d'appareil depuis un fichier GDTF.")
    parser.add_argument("gdtf", type=Path)
    parser.add_argument("--id", dest="fixture_id", help="identifiant (défaut : fabricant_modele)")
    parser.add_argument("--mode", action="append", help="mode à garder (répétable, défaut : tous)")
    parser.add_argument("--out", type=Path, required=True, help="dossier de la fiche")
    args = parser.parse_args(argv)
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8")
    print(summary(convert(args.gdtf, args.out, args.fixture_id, args.mode)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
