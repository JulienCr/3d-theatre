"""Panel text of the computed rig (spec 7, 13.10, 15.1): French lines built once per layout, drawn as is."""

from __future__ import annotations

import re

from datetime import datetime

from .layout import Layout, _metres
from .rig import FAMILY_LABELS, Rig, RigFixture

NO_CIRCUIT = "-"
_DMX_KEY = re.compile(r"^dmx_\d+_\d+$")


def dmx_channel_keys(names) -> list[str]:
    """The scene property names that are raw DMX channels (`dmx_<universe>_<channel>`)."""
    return [name for name in names if _DMX_KEY.match(name)]


def _number(value: float, digits: int = 1) -> str:
    return f"{round(value, digits) + 0.0:.{digits}f}".replace(".", ",")


def _kilograms(value: float) -> str:
    return f"{_number(value)} kg"


def _dmx_value(data: tuple[int, ...] | None) -> int | None:
    """Bytes of a 8 or 16-bit channel, coarse first, as one integer."""
    if data is None:
        return None
    value = 0
    for byte in data:
        value = value * 256 + byte
    return value


def dimension_lines(rig: Rig) -> list[str]:
    """Front pipes, play area, zones, azimuths, mover reach, beam gap, profile tubes, loads, patch (13.10)."""
    if not rig.enabled or rig.dims is None or rig.zones is None:
        return []
    dims, zones = rig.dims, rig.zones
    lines = [f"Perche de face : Y = {_metres(dims.pipe_y)}, Z = {_metres(dims.pipe_z)}",
             f"Retombée des rangs de PC : {_metres(dims.pipe_drop)}",
             f"Zone de jeu Ya : {_metres(dims.area_depth)}",
             f"Zones : {zones.nx} × {zones.nr}, {_metres(zones.width)} × {_metres(zones.depth)}"]
    if dims.movers_pipe_y is not None and dims.movers_pipe_z is not None:
        lines.insert(1, f"Perche des mobiles de face : Y = {_metres(dims.movers_pipe_y)}, "
                        f"Z = {_metres(dims.movers_pipe_z)}")
    if dims.mover_radius is not None:
        lines.append(f"Débattement des mobiles de face : rayon {_metres(dims.mover_radius)}")
    if dims.beam_clearance is not None:
        lines.append(f"Jeu minimal des faisceaux : {_metres(dims.beam_clearance)}")
    lines += [f"Azimut du rang {j + 1} : {_number(a)}°" for j, a in enumerate(dims.pc_azimuths)]
    lines += [f"Découpe {name} : tube {tube or '-'}, champ {_number(field)}°" for name, tube, field in dims.profiles]
    lines += [f"Charge {load.name} : {_kilograms(load.weight)} ({load.count} appareils)" for load in rig.loads]
    lines += [f"Patch {FAMILY_LABELS.get(family, family)} : {universe} : {first} - {last}"
              for family, universe, first, last in dims.patch_ranges]
    return lines


def _dmx_text(data: tuple[int, ...] | None) -> str:
    return "sans canal" if data is None else f"DMX {_dmx_value(data)}"


def _aim_line(f: RigFixture, pan: float, tilt: float) -> str:
    return f"{f.name} : pan {_number(pan)}° ({_dmx_text(f.pan_dmx)}), tilt {_number(tilt)}° ({_dmx_text(f.tilt_dmx)})"


def mover_lines(rig: Rig) -> list[str]:
    """Rest pan and tilt of every moving fixture, angle then DMX value (13.9)."""
    return [_aim_line(f, f.pan, f.tilt) for f in rig.fixtures
            if f.moving and f.pan is not None and f.tilt is not None]


def patch_rows(rig: Rig) -> list[tuple[str, str, str, str]]:
    """(fixture, `universe.address`, `mode · footprint`, circuit) in patch order (15.1)."""
    return [(f.name, f"{f.universe}.{f.address}", f"{f.mode} · {f.footprint} c", f.circuit or NO_CIRCUIT)
            for f in rig.fixtures]


FACE_GROUPS = (("L", "Jardin"), ("R", "Cour"), ("sum", "Somme"))


def _date_text(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).strftime("%d/%m/%Y à %H:%M")
    except ValueError:
        return iso


def face_eq_lines(layout: Layout) -> list[str]:
    """Panel lines of the stored face equalisation: date, U and CV per direction and sum, before to after (13.13)."""
    eq = layout.face_eq
    if eq is None:
        return []
    head = "Face égalisée" if layout.face_eq_state == "applied" else "Égalisation de la face périmée"
    lines = [f"{head} le {_date_text(eq.date)}."]
    if layout.face_eq_state != "applied":
        return lines
    for key, label in FACE_GROUPS:
        if key in eq.before and key in eq.after:
            b, a = eq.before[key], eq.after[key]
            lines.append(f"{label} : P10/moy {_number(b.p10_ratio, 2)} → {_number(a.p10_ratio, 2)}, "
                         f"CV {_number(b.cv, 2)} → {_number(a.cv, 2)}")
    total = eq.after.get("sum")
    if total is not None:
        lines.append(f"Éclairement moyen (somme) : {_number(eq.before['sum'].mean, 0)} → "
                     f"{_number(total.mean, 0)} lx, niveau moyen {_number(eq.mean_level, 2)}")
        lines.append(f"Emin/Emoy (somme) : {_number(eq.before['sum'].uniformity, 2)} → "
                     f"{_number(total.uniformity, 2)} ; sondes sous 70 % de la moyenne : "
                     f"{eq.before['sum'].below} → {total.below}")
        if "sum" in eq.spill_before and "sum" in eq.spill_after:
            b, a = eq.spill_before["sum"], eq.spill_after["sum"]
            lines.append(f"Débord hors de la fenêtre (somme) : au plus {round(100 * b.ratio)} % → {round(100 * a.ratio)} % "
                         f"de la moyenne ; sondes au-dessus de 5 % : {b.over} → {a.over}")
    return lines
