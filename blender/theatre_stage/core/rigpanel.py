"""Panel text of the computed rig (spec 7, 13.10, 15.1): French lines built once per layout, drawn as is."""

from __future__ import annotations

from .layout import _metres
from .rig import FAMILY_LABELS, Rig, RigFixture

NO_CIRCUIT = "-"


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
    """Front pipe, play area, zones, crossing azimuths, profile tubes, loads and patch ranges (13.10)."""
    if not rig.enabled or rig.dims is None or rig.zones is None:
        return []
    dims, zones = rig.dims, rig.zones
    lines = [f"Perche de face : Y = {_metres(dims.pipe_y)}, Z = {_metres(dims.pipe_z)}",
             f"Retombée des rangs de PC : {_metres(dims.pipe_drop)}",
             f"Zone de jeu Ya : {_metres(dims.area_depth)}",
             f"Zones : {zones.nx} × {zones.nr}, {_metres(zones.width)} × {_metres(zones.depth)}"]
    lines += [f"Azimut du rang {j + 1} : {_number(a)}°" for j, a in enumerate(dims.pc_azimuths)]
    lines += [f"Découpe {name} : tube {tube or '-'}, champ {_number(field)}°" for name, tube, field in dims.profiles]
    lines += [f"Charge {load.name} : {_kilograms(load.weight)} ({load.count} appareils)" for load in rig.loads]
    lines += [f"Patch {FAMILY_LABELS.get(family, family)} : {universe} : {first} - {last}"
              for family, universe, first, last in dims.patch_ranges]
    return lines


def _aim_line(f: RigFixture, pan: float, tilt: float) -> str:
    return (f"{f.name} : pan {_number(pan)}° (DMX {_dmx_value(f.pan_dmx)}), "
            f"tilt {_number(tilt)}° (DMX {_dmx_value(f.tilt_dmx)})")


def mover_lines(rig: Rig) -> list[str]:
    """Rest pan and tilt of every moving fixture, angle then DMX value (13.9)."""
    return [_aim_line(f, f.pan, f.tilt) for f in rig.fixtures
            if f.moving and f.pan is not None and f.tilt is not None]


def patch_rows(rig: Rig) -> list[tuple[str, str, str, str]]:
    """(fixture, `universe.address`, `mode · footprint`, circuit) in patch order (15.1)."""
    return [(f.name, f"{f.universe}.{f.address}", f"{f.mode} · {f.footprint} c", f.circuit or NO_CIRCUIT)
            for f in rig.fixtures]
