"""Face equalisation: probes, illuminance and the aim/zoom/level optimiser (spec 13.13)."""

import math
from dataclasses import replace

import pytest

from core.face_eq import (
    AUDIENCE, Bounds, Emitter, Probe, equalise, evaluate, face_grid, illuminance,
)
from core.fixtures import SHIPPED_DIR
from core.ies import Photometry, ZoomSet, fallback_profile, load_ies, parse_ies

BEAMS = ((20.0, 10.0), (80.0, 40.0))
FLUX = 6000.0
GRID_Z = 2.9


def emitter(direction="L", source=(0.0, -5.0, GRID_Z), axis=(0.0, 1.0, 0.0), field=40.0, photometry=None, **kw):
    n = math.sqrt(sum(c * c for c in axis))
    return Emitter(
        name=kw.pop("name", "E"), direction=direction, row=0, source=source,
        axis=tuple(c / n for c in axis), up=(0.0, 0.0, 1.0), zoom_field=field, zoom_range=(20.0, 80.0),
        beam_of_field=BEAMS, photometry=photometry or Photometry(FLUX), **kw)


def peak(field=40.0):
    return fallback_profile(emitter().beam_at(field), field, FLUX).peak


def test_face_grid_covers_acting_area_and_forestage():
    probes = face_grid(nose_width=11.6, frame_width=10.0, forestage_depth=1.5, area_depth=6.0, z=GRID_Z)
    assert all(p.position[2] == GRID_Z and p.normal == AUDIENCE for p in probes)
    ys = sorted({round(p.position[1], 6) for p in probes})
    assert ys[0] == pytest.approx(0.25) and ys[-1] == pytest.approx(5.75) and len(ys) == 12
    fore = [p.position[0] for p in probes if p.position[1] < 1.5]
    back = [p.position[0] for p in probes if p.position[1] > 1.5]
    assert max(fore) == pytest.approx(5.8 - 0.25, abs=0.05) and max(back) == pytest.approx(5.0 - 0.25, abs=0.05)
    assert min(fore) == pytest.approx(-max(fore))
    assert len(fore) == 3 * 23 and len(back) == 9 * 20


def test_illuminance_is_inverse_square():
    e = emitter()
    near = illuminance(e, Probe((0.0, 0.0, GRID_Z)))
    far = illuminance(e, Probe((0.0, 5.0, GRID_Z)))
    assert near == pytest.approx(peak() / 25)
    assert near / far == pytest.approx(4.0)


def test_illuminance_follows_the_cosine_of_the_incidence():
    e = emitter()
    square = illuminance(e, Probe((0.0, 0.0, GRID_Z)))
    tilted = Probe((0.0, 0.0, GRID_Z), (0.0, -math.cos(math.radians(60)), math.sin(math.radians(60))))
    assert illuminance(e, tilted) == pytest.approx(0.5 * square)
    assert illuminance(e, Probe((0.0, 0.0, GRID_Z), (0.0, 1.0, 0.0))) == 0.0


def test_illuminance_scales_with_level_and_falls_off_axis():
    e = emitter()
    probe = Probe((0.0, 0.0, GRID_Z))
    assert illuminance(replace(e, level=0.25), probe) == pytest.approx(0.25 * illuminance(e, probe))
    assert illuminance(e, Probe((8.0, 0.0, GRID_Z))) < 0.05 * illuminance(e, probe)


def test_illuminance_reads_the_ies_on_axis():
    table = load_ies(SHIPPED_DIR / "generic_pc_led" / "ies" / "t15_pc_zoom_96.ies")
    e = emitter(field=35.0, photometry=Photometry(9566.0, ZoomSet(((35.0, table),))))
    assert illuminance(e, Probe((0.0, 0.0, GRID_Z))) == pytest.approx(table.axis_candela / 25)


def test_ies_phi_turns_about_the_axis_from_up():
    text = ("IESNA:LM-63-2002\nTILT=NONE\n1 -1 1 3 2 1 2 0 0 0\n1 1 1\n0 45 90\n0 90\n"
            "100 100 0\n100 20 0\n")
    e = emitter(photometry=Photometry(1.0, ZoomSet(((40.0, parse_ies(text)),))))
    # axis +Y, up +Z: phi 0 is the vertical plane, phi 90 (axis x up = +X) the horizontal one
    d = 5.0
    above = Probe((0.0, 0.0, GRID_Z + d))
    beside = Probe((d, 0.0, GRID_Z))
    cosine = 5.0 / math.hypot(5.0, d)
    assert illuminance(e, above) == pytest.approx(100 * cosine / (25 + d * d), rel=1e-3)
    assert illuminance(e, beside) == pytest.approx(20 * cosine / (25 + d * d), rel=1e-3)


def test_cut_plane_zeroes_the_dark_side():
    e = emitter(field=80.0, cut_planes=(((0.0, -5.0, GRID_Z), (1.0, 0.0, 0.0)),))
    right, left = Probe((1.0, 0.0, GRID_Z)), Probe((-1.0, 0.0, GRID_Z))
    assert illuminance(e, left) == 0.0
    assert illuminance(e, right) == pytest.approx(illuminance(emitter(field=80.0), right))
    assert evaluate([e], [left, right])["L"].minimum == 0.0


def test_statistics_of_an_even_field():
    stats = evaluate([emitter()], [Probe((0.0, 0.0, GRID_Z))] * 3)["L"]
    assert stats.uniformity == pytest.approx(1.0) and stats.cv == pytest.approx(0.0, abs=1e-9)


AIMS_L = (-4.0, -3.0, -0.5, 3.0)


def uneven_rig():
    """Four jardin and four cour PC on one pipe at X = +-1.5 and +-4.5, aimed unevenly with narrow beams."""
    emitters = []
    for k, (x_l, aim_l) in enumerate(zip((-4.5, -1.5, 1.5, 4.5), AIMS_L)):
        for direction, sign in (("L", 1.0), ("R", -1.0)):
            x, aim = sign * x_l, sign * aim_l
            emitters.append(emitter(direction, source=(x, -4.0, 6.0), axis=(aim - x, 5.0, GRID_Z - 6.0),
                                    field=28.0, name=f"E_{direction}{k}"))
    return emitters


def grid():
    return face_grid(nose_width=10.0, frame_width=10.0, forestage_depth=0.0, area_depth=5.0, z=GRID_Z)


def test_optimiser_improves_each_direction_and_the_sum():
    emitters, probes = uneven_rig(), grid()
    result = equalise(emitters, probes, Bounds(aim_dx=1.0, aim_dy=1.0))
    assert set(result.before) == {"L", "R", "sum"}
    for name in ("L", "R", "sum"):
        assert result.after[name].uniformity > result.before[name].uniformity + 0.1, name
        assert result.after[name].cv < result.before[name].cv, name
    assert result.before["sum"].uniformity == pytest.approx(evaluate(emitters, probes)["sum"].uniformity)


def test_optimiser_respects_the_levers_and_the_mean_floor():
    emitters = uneven_rig()
    result = equalise(emitters, grid(), Bounds(aim_dx=0.8, aim_dy=0.6, min_mean_ratio=0.9))
    for adjustment, e in zip(result.adjustments, emitters):
        dx, dy = adjustment.aim_offset
        assert abs(dx) <= 0.8 + 1e-9 and abs(dy) <= 0.6 + 1e-9
        assert e.zoom_range[0] <= adjustment.zoom_field <= e.zoom_range[1]
        assert 0.0 <= adjustment.level <= 1.0
        assert adjustment.aim[2] == pytest.approx(GRID_Z)
        assert sum(c * c for c in adjustment.axis) == pytest.approx(1.0)
    assert all(ratio >= 0.9 - 1e-6 for ratio in result.mean_ratio.values())
    assert 0.0 < result.mean_level <= 1.0 and result.evaluations > 0


def test_aim_offset_moves_the_aim_point_by_that_offset():
    emitters = uneven_rig()
    result = equalise(emitters, grid(), Bounds(aim_dx=1.0, aim_dy=1.0))
    assert any(a.aim_offset != (0.0, 0.0) for a in result.adjustments)
    for adjustment, e in zip(result.adjustments, emitters):
        sign = 1.0 if e.direction == "L" else -1.0
        x0, y0 = sign * AIMS_L[int(e.name[-1])], 1.0
        assert adjustment.aim[0] == pytest.approx(x0 + adjustment.aim_offset[0])
        assert adjustment.aim[1] == pytest.approx(y0 + adjustment.aim_offset[1])


def test_levels_never_rise_above_one_even_when_asked():
    emitters = [replace(e, level=1.7) for e in uneven_rig()]
    result = equalise(emitters, grid(), Bounds(aim_dx=0.5, aim_dy=0.5))
    assert all(a.level <= 1.0 for a in result.adjustments)


def test_equalise_is_deterministic():
    first = equalise(uneven_rig(), grid(), Bounds(aim_dx=1.0, aim_dy=1.0))
    second = equalise(uneven_rig(), grid(), Bounds(aim_dx=1.0, aim_dy=1.0))
    assert first.adjustments == second.adjustments
    assert first.after == second.after


def test_single_direction_rig_has_no_separate_sum():
    emitters = [e for e in uneven_rig() if e.direction == "L"]
    result = equalise(emitters, grid(), Bounds(aim_dx=1.0, aim_dy=1.0))
    assert set(result.after) == {"L", "sum"}
    assert result.after["L"] == result.after["sum"]


def test_equalise_rejects_empty_or_unknown_input():
    with pytest.raises(ValueError):
        equalise([], grid())
    with pytest.raises(ValueError):
        equalise([emitter("X")], grid())


def test_beam_table_is_interpolated_and_held():
    e = emitter()
    assert e.beam_at(50.0) == pytest.approx(25.0)
    assert e.beam_at(10.0) == 10.0 and e.beam_at(100.0) == 40.0
    assert replace(e, beam_of_field=lambda f: f / 2).beam_at(30.0) == 15.0
