"""Panel text of the computed rig (spec 13.10, 15.1)."""

from dataclasses import replace

import pytest

from core.layout import compute_layout
from core.rigpanel import dimension_lines, mover_lines, patch_rows
from helpers import make


@pytest.fixture(scope="module")
def rig():
    return compute_layout(make(haze={"dmx_driven": True})).rig


def test_dimension_lines_cover_the_spec_list(rig):
    text = "\n".join(dimension_lines(rig))
    for expected in ("Perche de face : Y =", "Zone de jeu Ya", "Zones : ", "Azimut du rang 1", "Découpe Profile_L : tube",
                     "Charge FrontPipe", "Patch contre : 1 :", "Patch hazer : 6 :"):
        assert expected in text
    assert "." not in text.split("Azimut du rang 1")[1].split("°")[0]


def test_one_azimuth_line_per_row(rig):
    assert sum(line.startswith("Azimut du rang") for line in dimension_lines(rig)) == len(rig.dims.pc_azimuths)


def test_mover_lines_give_angle_and_dmx_of_each_mover(rig):
    movers = [f for f in rig.fixtures if f.moving]
    lines = mover_lines(rig)
    assert len(lines) == len(movers) > 0
    first = movers[0]
    assert lines[0].startswith(f"{first.name} : pan ") and "(DMX " in lines[0] and "tilt " in lines[0]
    assert "-0,0" not in "".join(lines)


def test_sixteen_bit_pan_is_shown_as_one_integer(rig):
    mover = next(f for f in rig.fixtures if f.moving and len(f.pan_dmx) == 2)
    value = mover.pan_dmx[0] * 256 + mover.pan_dmx[1]
    assert f"(DMX {value})" in next(line for line in mover_lines(rig) if line.startswith(mover.name))


def test_a_mover_without_pan_channel_says_so_instead_of_none(rig):
    mover = next(f for f in rig.fixtures if f.moving)
    bare = replace(rig, fixtures=(replace(mover, pan_dmx=None),))
    line = mover_lines(bare)[0]
    assert "None" not in line and "pan " in line and "(sans canal)" in line.split("tilt")[0]


def test_patch_rows_follow_the_patch_order(rig):
    rows = patch_rows(rig)
    assert [r[0] for r in rows] == [f.name for f in rig.fixtures]
    name, address, mode, circuit = rows[0]
    first = rig.fixtures[0]
    assert address == f"{first.universe}.{first.address}" and mode.endswith(f"{first.footprint} c")
    assert circuit == first.circuit


def test_disabled_rig_has_no_lines():
    off = compute_layout(make(rig={"enabled": False})).rig
    assert dimension_lines(off) == [] and mover_lines(off) == [] and patch_rows(off) == []

