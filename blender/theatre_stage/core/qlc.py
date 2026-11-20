"""QLC+ export: workspace (.qxw) and fixture definitions (.qxf) from the DMX patch (spec 16).

Pure Python. The XML is written by hand (one space of indent, UTF-8, LF, no timestamp) so two
exports of the same patch are byte-identical. Grammar checked against the QLC+ 4.14 sources.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from xml.sax.saxutils import escape

from .fixtures import Channel, Fixture, Library, Mode

WORKSPACE_NAME = "theatre_rig.qxw"
QLC_VERSION = "4.14.3"
AUTHOR = "theatre_stage"
MAX_CHANNELS = 512
POSITIONS_SCENE = "Repos - positions"
FULL_SCENE = "Repos - plein feu"
_WORKSPACE_NS = "http://www.qlcplus.org/Workspace"
_DEFINITION_NS = "http://www.qlcplus.org/FixtureDefinition"
_ILLEGAL_FILE_CHARS = re.compile(r'[<>:"/\\|?*]')
# QLC+ assumes these travels when a definition declares none (Fixture::positionToValues).
_DEFAULT_PAN_MAX, _DEFAULT_TILT_MAX = 360, 270


# ------------------------------------------------------------------ input and output

@dataclass(frozen=True)
class PatchedFixture:
    """One patched fixture. `universe` and `address` are 1-based (spec 15.1).

    `pan_tilt` is (pan coarse, pan fine, tilt coarse, tilt fine), the rest bytes of spec 13.9.
    `rest_bytes` lists (offset, byte) of every other channel at rest (spec 15.2), offsets 1-based.
    """

    name: str
    fixture_id: str
    mode: str
    universe: int
    address: int
    group: str | None
    pan_tilt: tuple[int, int, int, int] | None = None
    rest_bytes: tuple[tuple[int, int], ...] = ()


@dataclass(frozen=True)
class ExportResult:
    workspace: Path
    written_qxf: tuple[Path, ...]
    reused_qxf: tuple[str, ...]
    warnings: tuple[str, ...]


# ------------------------------------------------------------------ XML writer

def _attrs(values: dict) -> str:
    return "".join(f' {k}="{escape(str(v), {chr(34): "&quot;"})}"' for k, v in values.items())


class _Xml:
    def __init__(self) -> None:
        self.lines: list[str] = ['<?xml version="1.0" encoding="UTF-8"?>']
        self.depth = 0

    def doctype(self, name: str) -> None:
        self.lines.append(f"<!DOCTYPE {name}>")

    def open(self, tag: str, **attrs) -> None:
        self.lines.append(f"{' ' * self.depth}<{tag}{_attrs(attrs)}>")
        self.depth += 1

    def close(self, tag: str) -> None:
        self.depth -= 1
        self.lines.append(f"{' ' * self.depth}</{tag}>")

    def leaf(self, tag: str, text=None, **attrs) -> None:
        head = f"<{tag}{_attrs(attrs)}"
        body = f"{head}/>" if text is None else f"{head}>{escape(str(text))}</{tag}>"
        self.lines.append(f"{' ' * self.depth}{body}")

    def text(self) -> str:
        return "\n".join(self.lines) + "\n"


def _creator(x: _Xml) -> None:
    x.open("Creator")
    x.leaf("Name", "Q Light Controller Plus")
    x.leaf("Version", QLC_VERSION)
    x.leaf("Author", AUTHOR)
    x.close("Creator")


# ------------------------------------------------------------------ fixture definition (.qxf)

@dataclass(frozen=True)
class _Cap:
    low: int
    high: int
    text: str
    preset: str | None = None
    res: tuple[float, ...] = ()


@dataclass(frozen=True)
class _ChannelDef:
    name: str
    default: int = 0
    preset: str | None = None
    group: str = "Nothing"
    byte: int = 0
    caps: tuple[_Cap, ...] = ()


# attribute -> (QLC+ preset, fine preset, French label, group of a fine byte without preset)
_PRESETS = {
    "dimmer": ("IntensityDimmer", "IntensityDimmerFine", "Intensité", "Intensity"),
    "color_r": ("IntensityRed", "IntensityRedFine", "Rouge", "Intensity"),
    "color_g": ("IntensityGreen", "IntensityGreenFine", "Vert", "Intensity"),
    "color_b": ("IntensityBlue", "IntensityBlueFine", "Bleu", "Intensity"),
    "color_w": ("IntensityWhite", "IntensityWhiteFine", "Blanc", "Intensity"),
    "cyan": ("IntensityCyan", "IntensityCyanFine", "Cyan", "Intensity"),
    "magenta": ("IntensityMagenta", "IntensityMagentaFine", "Magenta", "Intensity"),
    "yellow": ("IntensityYellow", "IntensityYellowFine", "Jaune", "Intensity"),
    "pan": ("PositionPan", "PositionPanFine", "Pan", "Pan"),
    "tilt": ("PositionTilt", "PositionTiltFine", "Tilt", "Tilt"),
    "iris": ("ShutterIrisMaxToMin", "ShutterIrisFine", "Iris", "Shutter"),
    "gobo1_rot": ("GoboIndex", "GoboIndexFine", "Rotation gobo 1", "Gobo"),
    "cto": ("ColorCTOMixer", None, "CTO", "Colour"),
}
# attribute -> (group, French label) for channels written without preset
_CUSTOM = {
    "cct": ("Colour", "Température de couleur"),
    "strobe": ("Shutter", "Stroboscope"),
    "gobo1": ("Gobo", "Gobo 1"),
    "gobo2": ("Gobo", "Gobo 2"),
    "blade_rot": ("Beam", "Rotation des lames"),
    "haze_density": ("Effect", "Densité de brume"),
}
_FILLER = "Inutilisé"


def _custom_label(attribute: str) -> tuple[str, str]:
    if attribute in _CUSTOM:
        return _CUSTOM[attribute]
    blade = re.fullmatch(r"blade_(\d)([ab])", attribute)
    if blade:
        return "Beam", f"Lame {blade[1]}{blade[2].upper()}"
    emitter = re.fullmatch(r"emitter_(\d)", attribute)
    if emitter:
        return "Colour", f"Émetteur {emitter[1]}"
    return "Nothing", attribute


def _preset_entry(fixture: Fixture, attribute: str):
    if attribute == "zoom":
        invert = fixture.optics is not None and fixture.optics.zoom_invert
        coarse = "BeamZoomBigSmall" if invert else "BeamZoomSmallBig"
        return coarse, "BeamZoomFine", "Zoom", "Beam"
    return _PRESETS.get(attribute)


def _fill_spans(spans: list[_Cap], label: str) -> tuple[_Cap, ...]:
    """Sorted, non-overlapping capabilities covering 0-255 (QLC+ rejects overlaps)."""
    kept: list[_Cap] = []
    for cap in sorted(spans, key=lambda c: (c.low, c.high)):
        if not kept or cap.low > kept[-1].high:
            kept.append(cap)
    if not kept:
        return (_Cap(0, 255, label),)
    out: list[_Cap] = []
    cursor = 0
    for cap in kept:
        if cap.low > cursor:
            out.append(_Cap(cursor, cap.low - 1, _FILLER))
        out.append(cap)
        cursor = cap.high + 1
    if cursor <= 255:
        out.append(_Cap(cursor, 255, _FILLER))
    return tuple(out)


def _capabilities(fixture: Fixture, attribute: str, label: str) -> tuple[_Cap, ...]:
    spans: list[_Cap] = []
    if attribute == "strobe" and fixture.strobe is not None:
        s = fixture.strobe
        spans = [_Cap(s.open[0], s.open[1], "Obturateur ouvert", "ShutterOpen"),
                 _Cap(s.closed[0], s.closed[1], "Obturateur fermé", "ShutterClose"),
                 _Cap(s.strobe.start, s.strobe.stop, f"{s.strobe.hz_min:g}-{s.strobe.hz_max:g} Hz",
                      "StrobeFreqRange", (s.strobe.hz_min, s.strobe.hz_max))]
    elif attribute in ("gobo1", "gobo2"):
        wheel = next((w for w in fixture.gobos if w.name == attribute), None)
        spans = [_Cap(g.dmx[0], g.dmx[1], g.name) for g in wheel.slots] if wheel else []
    elif attribute == "cct" and fixture.colour.cct_range is not None:
        r = fixture.colour.cct_range
        label = f"{label} {r.min:g}-{r.max:g} K"
    return _fill_spans(spans, label)


def _channel_defs(fixture: Fixture, channel: Channel) -> list[_ChannelDef]:
    """Definitions of one fiche channel: the coarse byte, then the fine byte for 16 bits."""
    attribute = channel.attribute
    wide = channel.bits == 16
    high, low = (channel.default >> 8, channel.default & 255) if wide else (channel.default, 0)
    entry = _preset_entry(fixture, attribute)
    if entry is not None:
        coarse, fine, label, fine_group = entry
        defs = [_ChannelDef(label, high, preset=coarse)]
        if wide and fine:
            defs.append(_ChannelDef(f"{label} fin", low, preset=fine))
        elif wide:
            defs.append(_ChannelDef(f"{label} fin", low, group=fine_group, byte=1,
                                    caps=(_Cap(0, 255, f"{label} fin"),)))
        return defs
    group, label = _custom_label(attribute)
    defs = [_ChannelDef(label, high, group=group, caps=_capabilities(fixture, attribute, label))]
    if wide:
        defs.append(_ChannelDef(f"{label} fin", low, group=group, byte=1,
                                caps=(_Cap(0, 255, f"{label} fin"),)))
    return defs


def _register(defs: dict[str, _ChannelDef], used: set[str], wanted: _ChannelDef) -> str:
    """Name under which `wanted` is stored: unique in the definition, never twice in one mode."""
    candidate, n = wanted, 1
    while candidate.name in used or defs.get(candidate.name, candidate) != candidate:
        n += 1
        candidate = replace(wanted, name=f"{wanted.name} {n}")
    defs[candidate.name] = candidate
    used.add(candidate.name)
    return candidate.name


def _mode_names(fixture: Fixture, mode: Mode, defs: dict[str, _ChannelDef]) -> list[str]:
    """Channel names of `mode` in DMX order, gaps filled so the mode has `footprint` channels."""
    slots: dict[int, _ChannelDef] = {}
    for channel in sorted(mode.channels, key=lambda c: c.offset):
        for offset, definition in zip(channel.offsets, _channel_defs(fixture, channel)):
            slots[offset] = definition
    used: set[str] = set()
    names = []
    for offset in range(1, mode.footprint + 1):
        wanted = slots.get(offset) or _ChannelDef(f"{_FILLER} {offset}", preset="NoFunction")
        names.append(_register(defs, used, wanted))
    return names


def _write_channel(x: _Xml, d: _ChannelDef) -> None:
    attrs: dict = {"Name": d.name}
    if d.default:
        attrs["Default"] = d.default
    if d.preset:
        x.leaf("Channel", **attrs, Preset=d.preset)
        return
    x.open("Channel", **attrs)
    x.leaf("Group", d.group, Byte=d.byte)
    for cap in d.caps:
        a: dict = {"Min": cap.low, "Max": cap.high}
        if cap.preset:
            a["Preset"] = cap.preset
        a.update({f"Res{i}": f"{v:g}" for i, v in enumerate(cap.res, 1)})
        x.leaf("Capability", cap.text, **a)
    x.close("Channel")


_TYPES = {"moving_wash": "Moving Head", "moving_profile": "Moving Head", "pc": "Color Changer",
          "profile": "Color Changer", "hazer": "Hazer"}


def _travel(fixture: Fixture) -> tuple[int, int]:
    m = fixture.motion
    if m is None or m.pan is None or m.tilt is None:
        return 0, 0
    return round(m.pan.max - m.pan.min), round(m.tilt.max - m.tilt.min)


def _write_physical(x: _Xml, fixture: Fixture) -> None:
    o, d = fixture.optics, fixture.physical.dimensions
    angles = []
    if o is not None:
        angles = [o.field_angle.min, o.field_angle.max] if o.field_angle else list(o.lens_tubes)
    pan_max, tilt_max = _travel(fixture)
    led = fixture.colour.systems and fixture.family != "hazer"
    x.open("Physical")
    x.leaf("Bulb", Type="LED" if led else "", Lumens=round(o.flux) if o else 0, ColourTemperature=0)
    x.leaf("Dimensions", Weight=f"{fixture.physical.weight:g}",
           Width=round(d.width * 1000) if d else 0, Height=round(d.height * 1000) if d else 0,
           Depth=round(d.depth * 1000) if d else 0)
    x.leaf("Lens", Name="Other", DegreesMin=f"{min(angles, default=0):g}",
           DegreesMax=f"{max(angles, default=0):g}")
    x.leaf("Focus", Type="Head" if pan_max else "Fixed", PanMax=pan_max, TiltMax=tilt_max)
    x.leaf("Technical", PowerConsumption=0, DmxConnector="5-pin")
    x.close("Physical")


def fixture_definition_xml(fixture: Fixture, model: str | None = None) -> str:
    """The `.qxf` text of a fiche, every mode included. `model` overrides the QLC+ model name."""
    defs: dict[str, _ChannelDef] = {}
    modes = [(m.name, _mode_names(fixture, m, defs)) for m in fixture.modes]
    x = _Xml()
    x.doctype("FixtureDefinition")
    x.open("FixtureDefinition", xmlns=_DEFINITION_NS)
    _creator(x)
    x.leaf("Manufacturer", fixture.manufacturer)
    x.leaf("Model", model or fixture.model)
    x.leaf("Type", _TYPES[fixture.family])
    for d in defs.values():
        _write_channel(x, d)
    for name, channels in modes:
        x.open("Mode", Name=name)
        for number, channel_name in enumerate(channels):
            x.leaf("Channel", channel_name, Number=number)
        x.close("Mode")
    _write_physical(x, fixture)
    x.close("FixtureDefinition")
    return x.text()


def definition_filename(manufacturer: str, model: str) -> str:
    """`Manufacturer-Model.qxf`, the name QLC+ looks for beside the workspace (Fixture::loadXML)."""
    raw = f"{manufacturer}-{model}".replace(" ", "-")
    return _ILLEGAL_FILE_CHARS.sub("-", raw) + ".qxf"


# ------------------------------------------------------------------ definitions already in QLC+

@dataclass(frozen=True)
class _QlcDefinition:
    path: Path
    manufacturer: str
    model: str
    modes: dict[str, tuple[int, int, int]]  # name -> (channels, pan max, tilt max)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _focus(node: ET.Element | None, fallback: tuple[int, int]) -> tuple[int, int]:
    focus = next((c for c in (node if node is not None else []) if _local(c.tag) == "Focus"), None)
    if focus is None:
        return fallback
    return int(focus.get("PanMax", 0)), int(focus.get("TiltMax", 0))


def _read_definition(path: Path) -> _QlcDefinition | None:
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError):
        return None
    text = {_local(c.tag): (c.text or "") for c in root if _local(c.tag) in ("Manufacturer", "Model")}
    physical = next((c for c in root if _local(c.tag) == "Physical"), None)
    shared = _focus(physical, (0, 0))
    modes = {}
    for mode in (c for c in root if _local(c.tag) == "Mode"):
        own = next((c for c in mode if _local(c.tag) == "Physical"), None)
        count = sum(1 for c in mode if _local(c.tag) == "Channel")
        modes[mode.get("Name", "")] = (count, *_focus(own, shared))
    return _QlcDefinition(path, text.get("Manufacturer", ""), text.get("Model", ""), modes)


def _find_definition(manufacturer: str, model: str, directories: Sequence[Path]):
    """Look in `<dir>/<Manufacturer_X>/<Manufacturer-X>-<Model>.qxf`, then flat in `<dir>`."""
    stem = f"{manufacturer}-{model}".replace(" ", "-") + ".qxf"
    for directory in directories:
        for candidate in (Path(directory) / manufacturer.replace(" ", "_") / stem,
                          Path(directory) / manufacturer / stem, Path(directory) / stem):
            if candidate.is_file():
                found = _read_definition(candidate)
                if found and (found.manufacturer, found.model) == (manufacturer, model):
                    return found
    return None


# ------------------------------------------------------------------ resolving the patch

@dataclass(frozen=True)
class _Resolved:
    manufacturer: str
    model: str
    mode: str
    pan_max: int
    tilt_max: int


@dataclass(frozen=True)
class _Export:
    workspace: str
    definitions: dict[str, str]
    reused: tuple[str, ...]
    warnings: tuple[str, ...]


class _Planner:
    def __init__(self, library: Library, directories: Sequence[Path]) -> None:
        self.library = library
        self.directories = directories
        self.warnings: list[str] = []
        self.definitions: dict[str, str] = {}
        self.reused: dict[str, None] = {}
        self._qlc: dict[str, _QlcDefinition | None] = {}
        self._generated: dict[str, str] = {}

    def _qlc_definition(self, fixture: Fixture) -> _QlcDefinition | None:
        link = fixture.qlc
        if link is None:
            return None
        if fixture.id not in self._qlc:
            found = _find_definition(link.manufacturer, link.model, self.directories)
            if found is None and self.directories:
                self.warnings.append(
                    f"Fiche « {fixture.id} » : définition QLC+ « {link.manufacturer} {link.model} » "
                    f"introuvable dans les dossiers de fixtures, définition générée.")
            self._qlc[fixture.id] = found
        return self._qlc[fixture.id]

    def _reusable(self, fixture: Fixture, mode: Mode) -> tuple[_QlcDefinition, str] | None:
        link, found = fixture.qlc, self._qlc_definition(fixture)
        if link is None or found is None:
            return None
        qlc_mode = dict(link.modes).get(mode.name)
        problem = None
        if not link.verified or qlc_mode is None:
            problem = "sans correspondance QLC+ vérifiée"
        elif qlc_mode not in found.modes:
            problem = f"absent de la définition QLC+ (« {qlc_mode} » attendu)"
        elif found.modes[qlc_mode][0] != mode.footprint:
            problem = f"de {mode.footprint} canaux, la définition QLC+ en a {found.modes[qlc_mode][0]}"
        if problem:
            self.warnings.append(f"Fiche « {fixture.id} », mode « {mode.name} » {problem} : "
                                 f"définition générée.")
            return None
        return found, qlc_mode

    def _generate(self, fixture: Fixture) -> str:
        """Model name of the generated definition, written once per fiche."""
        if fixture.id not in self._generated:
            model = fixture.model
            twin = self._qlc_definition(fixture)
            if twin and (twin.manufacturer, twin.model) == (fixture.manufacturer, model):
                model = f"{model} (theatre_stage)"
                self.warnings.append(f"Fiche « {fixture.id} » : modèle renommé « {model} », "
                                     f"QLC+ garde sa propre définition de même nom.")
            filename = definition_filename(fixture.manufacturer, model)
            if _ILLEGAL_FILE_CHARS.search(f"{fixture.manufacturer}{model}"):
                self.warnings.append(f"Fiche « {fixture.id} » : le nom du fichier « {filename} » "
                                     f"remplace des caractères interdits, QLC+ ne le retrouvera pas seul.")
            self.definitions[filename] = fixture_definition_xml(fixture, model)
            self._generated[fixture.id] = model
        return self._generated[fixture.id]

    def resolve(self, item: PatchedFixture) -> _Resolved | None:
        fixture = self.library.get(item.fixture_id)
        if fixture is None:
            self.warnings.append(f"Appareil « {item.name} » : fiche « {item.fixture_id} » "
                                 f"introuvable dans la bibliothèque, appareil ignoré.")
            return None
        try:
            mode = fixture.mode(item.mode)
        except KeyError:
            self.warnings.append(f"Appareil « {item.name} » : mode « {item.mode} » inconnu pour la "
                                 f"fiche « {fixture.id} », appareil ignoré.")
            return None
        reuse = self._reusable(fixture, mode)
        if reuse:
            found, qlc_mode = reuse
            self.reused[str(found.path)] = None
            _, pan_max, tilt_max = found.modes[qlc_mode]
            return _Resolved(found.manufacturer, found.model, qlc_mode,
                             pan_max or _DEFAULT_PAN_MAX, tilt_max or _DEFAULT_TILT_MAX)
        return _Resolved(fixture.manufacturer, self._generate(fixture), mode.name, *_travel(fixture))


# ------------------------------------------------------------------ workspace (.qxw)

@dataclass(frozen=True)
class _Placed:
    id: int
    item: PatchedFixture
    fixture: Fixture
    mode: Mode
    resolved: _Resolved


def _place(items: Sequence[PatchedFixture], planner: _Planner) -> list[_Placed]:
    """Resolve the patch and drop what QLC+ would refuse or silently move (Doc::addFixture)."""
    taken: dict[tuple[int, int], str] = {}
    placed: list[_Placed] = []
    for item in items:
        resolved = planner.resolve(item)
        if resolved is None:
            continue
        fixture = planner.library.get(item.fixture_id)
        mode = fixture.mode(item.mode)
        last = item.address + mode.footprint - 1
        if item.universe < 1 or item.address < 1 or last > MAX_CHANNELS:
            planner.warnings.append(f"Appareil « {item.name} » : univers {item.universe}, canaux "
                                    f"{item.address} à {last} hors limites (1 à {MAX_CHANNELS}), ignoré.")
            continue
        clash = next((taken[(item.universe, c)] for c in range(item.address, last + 1)
                      if (item.universe, c) in taken), None)
        if clash:
            planner.warnings.append(f"Appareil « {item.name} » : recouvre « {clash} » dans l'univers "
                                    f"{item.universe}, ignoré.")
            continue
        taken.update({(item.universe, c): item.name for c in range(item.address, last + 1)})
        placed.append(_Placed(len(placed), item, fixture, mode, resolved))
    return placed


def _position_values(p: _Placed) -> dict[int, int] | None:
    """Channel index -> byte of the pan and tilt rest bytes, None without pan/tilt."""
    if p.item.pan_tilt is None:
        return None
    values: dict[int, int] = {}
    for attribute, (coarse, fine) in zip(("pan", "tilt"), (p.item.pan_tilt[:2], p.item.pan_tilt[2:])):
        channel = p.mode.channel(attribute)
        if channel is None:
            return None
        values[channel.offset - 1] = coarse
        if channel.fine is not None:
            values[channel.fine - 1] = fine
    return values


def _degrees(p: _Placed) -> tuple[int, int] | None:
    """Whole degrees from DMX 0 for the pan/tilt palette; QLC+ only stores integers."""
    pan, tilt = p.mode.channel("pan"), p.mode.channel("tilt")
    if p.item.pan_tilt is None or pan is None or tilt is None:
        return None
    pc, pf, tc, tf = p.item.pan_tilt
    fractions = [(c * 256 + f) / 65535 if ch.bits == 16 else c / 255
                 for ch, c, f in ((pan, pc, pf), (tilt, tc, tf))]
    return round(fractions[0] * p.resolved.pan_max), round(fractions[1] * p.resolved.tilt_max)


def _scene(x: _Xml, function_id: int, name: str, per_fixture: list[tuple[int, dict[int, int]]]) -> None:
    x.open("Function", ID=function_id, Type="Scene", Name=name)
    x.leaf("Speed", FadeIn=0, FadeOut=0, Duration=0)
    for fixture_id, values in per_fixture:
        pairs = ",".join(f"{c},{max(0, min(255, v))}" for c, v in sorted(values.items()))
        x.leaf("FixtureVal", pairs, ID=fixture_id)
    x.close("Function")


def _write_engine(x: _Xml, placed: list[_Placed]) -> None:
    universes = max((p.item.universe for p in placed), default=0)
    x.open("InputOutputMap")
    x.leaf("BeatGenerator", BeatType="Disabled", BPM=0)
    for u in range(1, universes + 1):
        x.leaf("Universe", Name=f"Univers {u}", ID=u - 1)
    x.close("InputOutputMap")
    for p in placed:
        x.open("Fixture")
        x.leaf("Manufacturer", p.resolved.manufacturer)
        x.leaf("Model", p.resolved.model)
        x.leaf("Mode", p.resolved.mode)
        x.leaf("ID", p.id)
        x.leaf("Name", p.item.name)
        x.leaf("Universe", p.item.universe - 1)
        x.leaf("Address", p.item.address - 1)
        x.leaf("Channels", p.mode.footprint)
        x.close("Fixture")
    groups: dict[str, list[int]] = {}
    for p in placed:
        if p.item.group:
            groups.setdefault(p.item.group, []).append(p.id)
    for group_id, (name, members) in enumerate(groups.items()):
        x.open("FixtureGroup", ID=group_id)
        x.leaf("Name", name)
        x.leaf("Size", X=len(members), Y=1)
        for column, fixture_id in enumerate(members):
            x.leaf("Head", 0, X=column, Y=0, Fixture=fixture_id)
        x.close("FixtureGroup")
    movers = [(p, _degrees(p)) for p in placed]
    for palette_id, (p, degrees) in enumerate((m for m in movers if m[1] is not None)):
        x.leaf("Palette", ID=palette_id, Type="PanTilt", Name=f"Repos_{p.item.name}",
               Value=f"{degrees[0]},{degrees[1]}")
    positions = [(p.id, v) for p in placed if (v := _position_values(p))]
    full = [(p.id, {**{o - 1: b for o, b in p.item.rest_bytes if 0 < o <= p.mode.footprint},
                    **(_position_values(p) or {})}) for p in placed]
    full = [(i, v) for i, v in full if v]
    scenes = [(POSITIONS_SCENE, positions), (FULL_SCENE, full)]
    for function_id, (name, content) in enumerate(s for s in scenes if s[1]):
        _scene(x, function_id, name, content)


def _build(items: Sequence[PatchedFixture], library: Library,
           directories: Sequence[Path]) -> _Export:
    planner = _Planner(library, tuple(Path(d) for d in directories))
    placed = _place(items, planner)
    x = _Xml()
    x.doctype("Workspace")
    x.open("Workspace", xmlns=_WORKSPACE_NS, CurrentWindow="FixtureManager")
    _creator(x)
    x.open("Engine")
    _write_engine(x, placed)
    x.close("Engine")
    x.open("VirtualConsole")
    x.open("Frame", Caption="")
    x.open("Appearance")
    x.leaf("FrameStyle", "Sunken")
    x.leaf("ForegroundColor", "Default")
    x.leaf("BackgroundColor", "Default")
    x.leaf("BackgroundImage", "None")
    x.leaf("Font", "Default")
    x.close("Appearance")
    x.close("Frame")
    x.open("Properties")
    x.leaf("Size", Width=1920, Height=1080)
    x.leaf("GrandMaster", ChannelMode="Intensity", ValueMode="Reduce")
    x.close("Properties")
    x.close("VirtualConsole")
    x.open("SimpleDesk")
    x.leaf("Engine")
    x.close("SimpleDesk")
    x.close("Workspace")
    return _Export(x.text(), planner.definitions, tuple(planner.reused), tuple(planner.warnings))


def workspace_xml(patched: Sequence[PatchedFixture], library: Library,
                  qlc_fixture_dirs: Sequence[Path] = ()) -> str:
    """The `.qxw` text of a patch. Warnings are only reported by `export_workspace`."""
    return _build(patched, library, qlc_fixture_dirs).workspace


def export_workspace(patched: Sequence[PatchedFixture], library: Library, out_dir: Path,
                     qlc_fixture_dirs: Sequence[Path] = ()) -> ExportResult:
    """Write `theatre_rig.qxw` and the `.qxf` QLC+ lacks into `out_dir`, overwriting.

    The `.qxf` sit beside the workspace: QLC+ looks there for a definition it does not know.
    `qlc_fixture_dirs` are the QLC+ fixture folders searched for reusable definitions (16.4).
    """
    export = _build(patched, library, qlc_fixture_dirs)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for filename, text in export.definitions.items():
        (out_dir / filename).write_bytes(text.encode("utf-8"))
        written.append(out_dir / filename)
    workspace = out_dir / WORKSPACE_NAME
    workspace.write_bytes(export.workspace.encode("utf-8"))
    return ExportResult(workspace, tuple(written), export.reused, export.warnings)
