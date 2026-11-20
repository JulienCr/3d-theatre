"""Lighting rig (spec 13 and 15): positions, aims, fields, blades, pan/tilt, patch, rest values."""

import math
from dataclasses import replace
from pathlib import Path

import pytest

from core.fixture_models import fixture_model
from core.fixtures import EMPTY_LIBRARY, SHIPPED_DIR, Range, cct_to_rgb, discover
from core.layout import _make_context, compute_layout
from core.presets import read_preset, shipped_presets
from core.rig import (
    AZIMUTH_SEARCH, BEAM_MARGIN, FOOTPRINT_MARGIN, HEIGHT_STEP, _Boxes, _cloud, _gaps, _make_beam, _walls, _wall_gaps,
    aim_angles, compute_rig,
    default_library, head_frame, posed_points, spread,
)
from core.params import default_params
from helpers import bounds, classic, make

DATA = Path(__file__).parent / "data" / "rig"
LIB = discover([DATA])
SYNTH = {
    "backlight": {"fixture": "rig_wash"}, "front_movers": {"fixture": "rig_wash"},
    "towers": {"fixture": "rig_wash"}, "front_pc": {"fixture": "rig_pc", "fixture_far": "rig_pc"},
    "profiles": {"fixture": "rig_profile"}, "haze": {"fixture": "rig_hazer"},
}


SHIPPED = discover([SHIPPED_DIR, DATA])


def shipped_layout(params, far="rig_fresnel"):
    """Layout with the shipped fiches and `far` (the synthetic wide Fresnel) on the far rows."""
    params["front_pc"]["fixture_far"] = far
    return compute_layout(params, SHIPPED)


def rig_params(**groups):
    merged = {k: dict(v) for k, v in SYNTH.items()}
    for key, values in groups.items():
        merged.setdefault(key, {}).update(values)
    return make(**merged)


def rig_layout(library=LIB, **groups):
    return compute_layout(rig_params(**groups), library)


def rig_of(**groups):
    return rig_layout(**groups).rig


def has(warnings, *words):
    return [w for w in warnings if all(word in w for word in words)]


# ------------------------------------------------------------ vector oracle

def sub(a, b):
    return tuple(x - y for x, y in zip(a, b))


def add(a, b):
    return tuple(x + y for x, y in zip(a, b))


def mul(a, k):
    return tuple(x * k for x in a)


def dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def unit(a):
    return mul(a, 1 / math.sqrt(dot(a, a)))


def angle(a, b):
    return math.degrees(math.acos(max(-1.0, min(1.0, dot(unit(a), unit(b))))))


def matmul(a, b):
    return tuple(tuple(sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)) for i in range(3))


def rot_x(deg):
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return ((1, 0, 0), (0, c, -s), (0, s, c))


def rot_z(deg):
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return ((c, -s, 0), (s, c, 0), (0, 0, 1))


def column(m, j):
    return tuple(m[i][j] for i in range(3))


def beam_from_angles(pan, tilt):
    """World beam direction for physical pan and tilt, from the body-frame formula of 13.9."""
    p, t = math.radians(pan), math.radians(tilt)
    body = (-math.sin(t) * math.sin(p), math.sin(t) * math.cos(p), math.cos(t))
    return (body[0], -body[1], -body[2])


# ------------------------------------------------------------- front pipe

def test_default_front_pipe_and_zone_grid():
    lay = rig_layout()
    rig = lay.rig
    assert rig.dims.pipe_z == pytest.approx(7.0)
    assert rig.dims.pipe_drop == pytest.approx(2.90, abs=0.01)
    assert rig.dims.pipe_y == pytest.approx(-1.40, abs=0.01)
    assert rig.dims.area_depth == pytest.approx(6.0)
    z = rig.zones
    assert (z.nx, z.nr) == (4, 2)
    assert z.width == pytest.approx(2.5) and z.depth == pytest.approx(3.0)
    pipe = lay.find("FrontPipe")
    assert pipe.collection == "Theatre_Rig" and pipe.material == "TS_Batten"
    assert pipe.start[1] == pytest.approx(rig.dims.pipe_y) and pipe.start[2] == pytest.approx(7.0)
    assert pipe.end[0] == pytest.approx(lay.derived.total_width / 2 - 0.10)


def test_manual_front_pipe_position_keeps_the_automatic_drop():
    rig = rig_of(rig_front={"auto_position": False, "y": -2.0})
    assert rig.dims.pipe_y == -2.0
    assert rig.dims.pipe_drop == pytest.approx(2.90, abs=0.01)


def test_front_pipe_alerts():
    low = rig_layout(advanced={"facade_height": 3.0})
    assert has(low.warnings, "Perche de face trop basse")
    out = rig_layout(rig_front={"auto_position": False, "y": -30.0})
    assert has(out.warnings, "Perche de face hors de la salle")


def test_play_area_is_shortened_with_an_alert():
    lay = rig_layout(stage={"depth": 5.0}, rig={"area_depth": 6.0})
    assert has(lay.warnings, "Zone de jeu raccourcie")
    assert lay.rig.dims.area_depth == pytest.approx(5.0 - 0.40)


def test_disabled_rig_adds_nothing():
    lay = rig_layout(rig={"enabled": False})
    assert not lay.rig.enabled and not lay.rig.fixtures
    assert not any(n.startswith(("FrontPipe", "Tower")) for n in lay.names())


# ------------------------------------------------------------------ face PC

def pcs(rig):
    return rig.by_family("front_pc")


def test_sixteen_face_pc_on_four_circuits():
    rig = rig_of()
    assert len(pcs(rig)) == 16
    circuits = dict(rig.circuits)
    for row in (1, 2):
        for tag in "LR":
            assert len(circuits[f"FrontPC_Row{row}_{tag}"]) == 4
    assert sum(1 for name in circuits if name.startswith("FrontPC_")) == 4
    assert rig.find("FrontPC_L_05").circuit == "FrontPC_Row2_L"


@pytest.mark.parametrize("width, wanted", [(3.0, 4), (2.5, 4), (5.0, 2), (4.99, 3), (10.0, 1), (1.0, 10)])
def test_zone_width_is_a_maximum_so_columns_round_up(width, wanted):
    assert rig_of(front_pc={"zone_width": width}).zones.nx == wanted


def test_zone_rows_round_up_and_stay_within_four():
    assert rig_of(front_pc={"zone_width": 2.0}).zones.nr == 3
    assert rig_of(front_pc={"zone_width": 1.0}).zones.nr == 4


def test_pc_cross_at_azimuth_with_parallel_beams():
    rig = rig_of()
    z = rig.zones
    for f in pcs(rig):
        side = -1 if "_L_" in f.name else 1
        index = int(f.name[-2:]) - 1
        row, col = divmod(index, z.nx)
        azimuth = rig.dims.pc_azimuths[row]
        drop = z.ys[row] - f.hang[1]
        assert f.hang[0] == pytest.approx(z.xs[col] + side * drop * math.tan(math.radians(azimuth)))
        heading = math.degrees(math.atan2(f.aim[0] - f.pivot[0], f.aim[1] - f.pivot[1]))
        assert heading == pytest.approx(-side * azimuth)
        assert f.aim[2] == pytest.approx(2.9)
        if row:
            assert f.aim == pytest.approx((z.xs[col], z.ys[row], 2.9))
        else:
            assert f.aim[1] < z.ys[0] - 0.1
    assert {f.support for f in pcs(rig)} == {"FrontPipe", "Batten_02"}
    first = rig.find("FrontPC_L_01")
    assert first.hang[0] == pytest.approx(-3.75 - 2.90, abs=0.01)


def posed_interval(library, f, axis=0):
    """Extent of every vertex of the posed model of `f` on a world axis (independent of core's boxes)."""
    fx = library.get(f.fixture_id)
    tube = next((t for t in fx.optics.lens_tubes if t.name == f.tube), None) if f.tube else None
    model = fixture_model(fx, tube)
    rz, rx = rot_z(f.pan), rot_x(-f.tilt)
    pivot = model.tilt_pivot
    values = []
    for part, mesh in (("base", model.base), ("pan", model.pan), ("tilt", model.tilt)):
        for v in mesh.vertices:
            if part == "tilt":
                v = add(matvec(rx, v), pivot)
            if part != "base":
                v = matvec(rz, v)
            values.append((f.root[0] + v[0], f.root[1] - v[1], f.root[2] - v[2])[axis])
    return min(values), max(values)


def matvec(m, v):
    return tuple(sum(m[i][k] * v[k] for k in range(3)) for i in range(3))


def overlapping(rig, library):
    """Pairs of fixtures on one support whose posed intervals overlap (X on a tube, Z on a tower),
    and the smallest gap per support."""
    by_support, pairs, gaps = {}, [], {}
    for f in rig.fixtures:
        if f.support:
            axis = 2 if f.support.startswith("Tower_") else 0
            by_support.setdefault(f.support, []).append((f, posed_interval(library, f, axis)))
    for support, items in by_support.items():
        for i, (a, ia) in enumerate(items):
            for b, ib in items[i + 1:]:
                gap = max(ia[0] - ib[1], ib[0] - ia[1])
                gaps[support] = min(gaps.get(support, gap), gap)
                if gap < 0:
                    pairs.append((a.name, b.name))
    return pairs, gaps


def test_row_azimuth_moves_off_the_nominal_to_free_the_shared_tube():
    # At the nominal 45 degrees, FrontPC_L_06 and FrontPC_R_05 hang too close on Batten_02.
    nominal = 45.0
    rig = shipped_layout(make(front_pc={"azimuth": nominal}), far="generic_pc_led").rig
    assert rig.dims.pc_azimuths[0] == nominal
    assert rig.dims.pc_azimuths[1] != nominal and abs(rig.dims.pc_azimuths[1] - nominal) <= AZIMUTH_SEARCH
    assert not overlapping(rig, SHIPPED)[0] and not has(rig.warnings, "se touchent")
    row = [f for f in pcs(rig) if f.support == "Batten_02"]
    for side in "LR":
        headings = {round(math.degrees(math.atan2(f.aim[0] - f.pivot[0], f.aim[1] - f.pivot[1])), 6)
                    for f in row if f"_{side}_" in f.name}
        assert len(headings) == 1


def test_row_azimuth_alerts_and_keeps_the_nominal_when_nothing_fits():
    pc = LIB.get("rig_pc")
    body = replace(pc.model3d.body, width=6.0)
    wide = replace(pc, model3d=replace(pc.model3d, body=body),
                   physical=replace(pc.physical, dimensions=replace(pc.physical.dimensions, width=6.0)))
    lib = replace(LIB, fixtures={**LIB.fixtures, "rig_pc": wide})
    rig = rig_layout(library=lib, front_pc={"azimuth": 45.0}).rig
    assert has(rig.warnings, "Rang", "aucun azimut")
    assert rig.dims.pc_azimuths == (45.0, 45.0)


def test_pc_row_azimuth_keeps_coverage_of_the_widest_field():
    rig = shipped_layout(make(), far="generic_pc_led").rig
    assert not has(rig.warnings, "Zone non couverte")
    assert max(f.field_angle for f in pcs(rig)) <= 54.4 + 1e-9


def test_pc_field_covers_the_zone_with_overlap():
    rig = rig_of()
    z = rig.zones
    for f in pcs(rig):
        row, col = divmod(int(f.name[-2:]) - 1, z.nx)
        if row == 0:
            continue
        hx, hy = z.width / 2 * 1.2, z.depth / 2 * 1.2
        spans = [angle(f.axis, sub((z.xs[col] + sx * hx, z.ys[row] + sy * hy, 2.9), f.pivot))
                 for sx in (-1, 1) for sy in (-1, 1)]
        assert f.field_angle == pytest.approx(2 * max(spans))
        assert f.beam_angle < f.field_angle


def test_front_row_field_covers_its_zone_and_the_forestage_corners():
    params = rig_params()
    ctx, _ = _make_context(params)
    rig = compute_layout(params, LIB).rig
    z = rig.zones
    for f in (f for f in pcs(rig) if int(f.name[-2:]) <= z.nx):
        col = int(f.name[-2:]) - 1
        x0, x1 = z.xs[col] - z.width / 2, z.xs[col] + z.width / 2
        grow = z.width / 2 * 0.2
        x0 = -ctx.W / 2 if col == 0 else x0 - grow
        x1 = ctx.W / 2 if col == z.nx - 1 else x1 + grow
        far = z.ys[0] + z.depth / 2 * 1.2
        corners = [(x, y, zc) for x in (x0, x1) for y, zc in ((0.0, ctx.Hp), (far, 2.9))]
        spans = [angle(f.axis, sub(c, f.pivot)) for c in corners]
        assert f.field_angle >= 2 * max(spans) - 0.05
        assert f.axis[2] < unit(sub((z.xs[col], z.ys[0], 2.9), f.pivot))[2]


def test_pc_field_alerts_when_out_of_the_zoom_range():
    wide = rig_layout(front_pc={"zone_width": 10.0})
    assert has(wide.warnings, "Zone non couverte")
    assert all(f.field_angle == 70.0 for f in wide.rig.by_family("front_pc"))
    narrow = rig_layout(front_pc={"fixture": "rig_pc_tight", "fixture_far": "rig_pc_tight"})
    assert has(narrow.warnings, "Champ trop large")
    assert all(f.field_angle == 66.0 for f in pcs(narrow.rig) if f.support != "FrontPipe")
    assert all(66.0 <= f.field_angle <= 70.0 for f in pcs(narrow.rig) if f.support == "FrontPipe")
    assert not has(rig_layout().warnings, "Zone non couverte") and not has(
        rig_layout().warnings, "Champ trop large")


def test_pc_rows_behind_the_zone_are_not_hung():
    lay = rig_layout(front_pc={"zone_mode": "manual", "rows": 4}, rig={"area_depth": 5.0})
    assert has(lay.warnings, "porteuse trop en arrière de la zone")
    assert len(pcs(lay.rig)) < 2 * 3 * 4


def test_hang_point_off_the_tube_is_clamped_with_an_alert(monkeypatch):
    monkeypatch.setattr("core.rig.AZIMUTH_SEARCH", 0.0)
    lay = rig_layout(front_pc={"azimuth": 80.0})
    assert has(lay.warnings, "Point d'accroche hors de")
    limit = lay.find("Batten_02").end[0]
    assert all(abs(f.hang[0]) <= limit + 1e-9 for f in pcs(lay.rig) if f.support == "Batten_02")


# ------------------------------------------------------------------ backlight

def test_backlight_hangs_on_the_upstage_batten_by_default_and_tilts_toward_the_audience():
    lay = rig_layout()
    last = lay.derived.batten_count
    tube = lay.find(f"Batten_{last:02d}")
    backs = lay.rig.by_family("backlight")
    assert len(backs) == 6 and tube.start[1] > lay.derived.masking_y1 - 1.0
    for f in backs:
        assert f.support == tube.name and f.hang[1] == pytest.approx(tube.start[1])
        assert f.aim[1] < f.hang[1] and f.axis[1] < 0 and f.axis[2] < 0
        assert 0 < f.tilt < 90 and not has(lay.warnings, "Pan/tilt hors course")


def test_upstage_backlight_stays_in_front_of_the_back_curtain():
    lay = rig_layout(masking={"backdrop": "cyclorama"})
    ys = {f.hang[1] for f in lay.rig.by_family("backlight")}
    assert len(ys) == 1 and ys.pop() < lay.derived.backdrop_y
    assert not has(lay.rig.warnings, "Aucune porteuse")


def test_backlight_snaps_to_the_nearest_batten_and_aims_in_front():
    lay = rig_layout(backlight={"position": "distance", "distance": 4.0})
    backs = lay.rig.by_family("backlight")
    ys = [b.end[1] for b in (lay.find(n) for n in lay.names() if n.startswith("Batten_"))]
    assert len(backs) == 6
    for i, f in enumerate(backs):
        assert f.hang[1] == min(ys, key=lambda y: abs(y - 4.0))
        assert f.hang[0] == pytest.approx(spread(i, 6, 10.0))
        assert f.aim[0] == pytest.approx(f.hang[0]) and f.aim[2] == pytest.approx(2.9)
        assert f.aim[1] < f.hang[1]


def test_backlight_alerts_without_a_close_batten_or_any_batten():
    lay = rig_layout(grid={"batten_spacing": 5.0}, backlight={"position": "distance", "distance": 5.0})
    assert has(lay.warnings, "Aucune porteuse à moins de 0,50 m")
    ctx, _ = _make_context(make(**SYNTH))
    rig, _ = compute_rig(replace(ctx, light_batten_ys=()), LIB)
    assert not rig.by_family("backlight")
    assert has(rig.warnings, "Aucune porteuse lumière")


# --------------------------------------------------------------------- towers

def test_tower_position_mesh_arms_and_aims():
    lay = rig_layout()
    wt = lay.derived.total_width
    x = bounds(lay, "Tower_L_01")
    assert x[0] == pytest.approx((-wt / 2, -wt / 2 + 0.8), abs=1e-6)
    assert x[1] == pytest.approx((-3.4, -2.6), abs=1e-6)
    assert x[2][0] == 0.0 and x[2][1] == pytest.approx(4.5, abs=1e-6)
    assert bounds(lay, "Tower_R_01")[0] == pytest.approx((wt / 2 - 0.8, wt / 2), abs=1e-6)
    assert lay.find("Tower_L_01").collection == "Theatre_Rig" and lay.find("Tower_L_01").material == "TS_Truss"
    pitch = 0.10 + 0.50 + 0.10
    first, second = lay.rig.find("TowerMover_L_01"), lay.rig.find("TowerMover_L_02")
    assert first.hang[2] == pytest.approx(4.5 - 0.10)
    assert second.hang[2] == pytest.approx(4.5 - 0.10 - pitch)
    assert first.hang[0] == pytest.approx(-(wt / 2 - 0.4) + 0.15 + 0.30)
    arm = lay.find("TowerArm_L_01_02")
    assert arm.start[2] == pytest.approx(second.hang[2])
    assert arm.start[0] == pytest.approx(-(wt / 2 - 0.4) + 0.15)
    assert arm.end[0] == pytest.approx(second.hang[0]) and abs(arm.end[0]) < abs(arm.start[0])
    assert first.aim == pytest.approx((10 / 4, 6.0 * 0.5 / 2, 2.9))
    assert second.aim == pytest.approx((10 / 4, 6.0 * 1.5 / 2, 2.9))
    assert lay.rig.find("TowerMover_R_01").aim[0] == pytest.approx(-10 / 4)


def test_stacked_tower_movers_whose_posed_height_exceeds_the_pitch_raise_an_alert():
    wash = LIB.get("rig_wash")
    tall = replace(wash, model3d=replace(wash.model3d, body=replace(wash.model3d.body, height=1.5)))
    lib = replace(LIB, fixtures={**LIB.fixtures, "rig_wash": tall})
    assert has(rig_layout(library=lib).warnings, "Appareils qui se touchent sur le pylône Tower_L_01")
    assert not has(rig_layout().warnings, "se touchent")


def test_asymmetric_towers_and_names_are_continuous_per_side():
    lay = rig_layout(towers={"symmetric": False, "left": {"count": 2, "movers": 2},
                             "right": {"count": 0}})
    names = [f.name for f in lay.rig.by_family("tower_movers")]
    assert names == [f"TowerMover_L_{n:02d}" for n in range(1, 5)]
    assert lay.rig.find("TowerMover_L_03").support == "Tower_L_02"
    assert lay.find("Tower_L_02").center[1] == pytest.approx(-5.0)
    assert "Tower_R_01" not in lay.names()


def test_tower_alerts():
    low = rig_layout(towers={"left": {"height": 2.0, "movers": 3}})
    assert has(low.warnings, "Pylône Tower_L_01 trop bas pour 3 appareils")
    stairs = rig_layout(towers={"left": {"first_distance": 0.0}})
    assert has(stairs.warnings, "recoupe l'escalier")
    outside = rig_layout(towers={"left": {"first_distance": 30.0}})
    assert has(outside.warnings, "hors de la salle dessinée")


# ------------------------------------------------------------------- profiles

def third_bounds(p, wc=10.0):
    return -wc / 2 + p * wc / 3, -wc / 2 + (p + 1) * wc / 3


def top_line(ctx, source, top_height=2.20, margin=0.10):
    """Spec 13.8: head of a standing actor at the back, or the lintel when that cut passes above it."""
    actor = (0.0, 6.0, ctx.Hp + top_height)
    lintel = (0.0, ctx.Ys + 0.05, ctx.Hp + ctx.Hc - margin)
    t = (lintel[1] - source[1]) / (actor[1] - source[1])
    return lintel if source[2] + t * (actor[2] - source[2]) > lintel[2] else actor


def cut_lines(lay, third, source, **profiles):
    ctx, _ = _make_context(make(**SYNTH))
    b0, b1 = third_bounds(third)
    return {
        "bottom": ((0.0, 0.0, ctx.Hp), (1.0, 0.0, 0.0)),
        "top": (top_line(ctx, source, **profiles), (1.0, 0.0, 0.0)),
        "left": ((b0, 0.0, 2.9), (0.0, 1.0, 0.0)),
        "right": ((b1, 0.0, 2.9), (0.0, 1.0, 0.0)),
    }


def required_field(lines, source, axis):
    normals = {}
    for name, (q, u) in lines.items():
        n = unit(cross(sub(q, source), u))
        normals[name] = mul(n, -1) if dot(n, axis) > 0 else n
    rays = []
    for a in ("bottom", "top"):
        for b in ("left", "right"):
            c = unit(cross(normals[a], normals[b]))
            rays.append(c if dot(c, axis) > 0 else mul(c, -1))
    return 2 * max(angle(axis, r) for r in rays)


@pytest.mark.parametrize("groups", [
    {}, {"rig_front": {"ceiling_gap": 1.5}}, {"profiles": {"lintel_margin": 0.60}},
    {"rig": {"aim_height": 2.4}}, {"profiles": {"top_height": 1.2}},
])
def test_profile_tube_is_the_smallest_with_a_five_percent_margin(groups):
    lay = rig_layout(**groups)
    tubes = {t.name: t for t in LIB.get("rig_profile").optics.lens_tubes}
    for p, tag in enumerate("LCR"):
        f = lay.rig.find(f"Profile_{tag}")
        prof = {k: v for k, v in groups.get("profiles", {}).items() if k != "lintel_margin"}
        margin = groups.get("profiles", {}).get("lintel_margin", 0.10)
        need = required_field(cut_lines(lay, p, f.pivot, margin=margin, **prof), f.pivot, f.axis)
        covering = [t for t in tubes.values() if t.field_angle >= 1.05 * need]
        expected = covering[0] if covering else list(tubes.values())[-1]
        assert f.tube == expected.name and f.field_angle == expected.field_angle
        assert f.aperture == (expected.lens_diameter or 0.19)
        assert bool(has(lay.warnings, f"Découpe {f.name}", "aucun tube")) == (not covering)


def test_forced_tube_and_missing_coverage():
    assert rig_of(profiles={"tube_angle": 44.0}).find("Profile_C").tube == "45"
    lay = rig_layout(profiles={"fixture": "rig_profile_motor"}, rig_front={"ceiling_gap": 0.05})
    assert lay.rig.find("Profile_C").tube in ("30", "90")


def test_profile_source_is_recessed_behind_the_lens():
    f = rig_of().find("Profile_C")
    r = f.aperture / 2
    d = r / math.tan(math.radians(f.field_angle) / 2)
    assert f.source_kind == "SPOT" and f.source_z == pytest.approx(0.40 - d)
    assert f.source == pytest.approx(add(f.pivot, mul(f.axis, f.source_z)))
    assert pcs(rig_of())[0].source_kind == "AREA"
    assert pcs(rig_of())[0].source_z == pytest.approx(0.30)


@pytest.mark.parametrize("top_height", [2.20, 6.0])
@pytest.mark.parametrize("tag, third", [("L", 0), ("C", 1), ("R", 2)])
def test_each_blade_edge_lies_on_its_cut_plane(tag, third, top_height):
    lay = rig_layout(profiles={"top_height": top_height})
    f = lay.rig.find(f"Profile_{tag}")
    lines = cut_lines(lay, third, f.source, top_height=top_height)
    xh, yh, axis = head_frame(f.pan, f.tilt)
    assert axis == pytest.approx(f.axis, abs=1e-9)
    blades = f.blades
    assert {b.cut for b in blades.blades} == {"bottom", "top", "left", "right"}
    for blade in blades.blades:
        q, u = lines[blade.cut]
        normal = unit(cross(sub(q, f.source), u))
        o = add(mul(xh, math.cos(math.radians(blade.side))), mul(yh, math.sin(math.radians(blade.side))))
        t = add(mul(xh, -math.sin(math.radians(blade.side))), mul(yh, math.cos(math.radians(blade.side))))
        centre = add(f.source, mul(axis, blades.distance))
        for end, h in ((-1, blade.edge_a), (1, blade.edge_b)):
            point = add(add(centre, mul(o, h)), mul(t, end * blades.half_span))
            assert dot(sub(point, f.source), normal) == pytest.approx(0.0, abs=1e-9)
            assert blade.edge_a >= -0.040 and blade.insertion_a == pytest.approx(
                (blades.open_eff - blade.edge_a) / (blades.open_eff + 0.040))
        assert blades.plane_z == pytest.approx(f.source_z + blades.distance)


def test_manual_blades_and_their_limits():
    p = {"blades_mode": "manual", "l_blade_1_insertion": 0.5, "l_blade_1_angle": 10.0,
         "l_rotation": 15.0}
    f = rig_of(profiles=p).find("Profile_L")
    b = f.blades.blades[0]
    assert f.blades.rotation == 15.0
    assert b.angle == pytest.approx(10.0) and b.cut == ""
    assert (b.insertion_a + b.insertion_b) / 2 == pytest.approx(0.5, abs=0.02)
    assert f.blades.blades[1].insertion_a == 0.0
    lay = rig_layout(profiles={**p, "l_blade_1_angle": 30.0})
    assert has(lay.warnings, "lame hors course")
    assert lay.rig.find("Profile_L").blades.blades[0].angle == pytest.approx(20.0)


def test_motorised_blades_are_written_as_rest_values():
    lay = rig_layout(profiles={"fixture": "rig_profile_motor", "tube_angle": 90.0})
    f = lay.rig.find("Profile_C")
    values = {c.attribute: c for c in f.channels}
    for blade in f.blades.blades:
        assert values[f"blade_{blade.index}a"].value == pytest.approx(blade.insertion_a)
        assert values[f"blade_{blade.index}b"].value == pytest.approx(blade.insertion_b)
    assert values["blade_rot"].data == (128,)


# ------------------------------------------------------------- pan and tilt

def test_head_frame_matches_the_matrix_composition():
    for pan, tilt in ((0, 0), (35, 60), (-120, 20), (200, 100)):
        m = matmul(matmul(rot_x(180), rot_z(pan)), rot_x(-tilt))
        xh, yh, a = head_frame(pan, tilt)
        assert xh == pytest.approx(column(m, 0)) and yh == pytest.approx(column(m, 1))
        assert a == pytest.approx(column(m, 2)) and a == pytest.approx(beam_from_angles(pan, tilt))


def reached(rng, data):
    n = data[0] * 256 + data[1]
    return rng.lerp(n / 65535)


@pytest.mark.parametrize("fixture", ["rig_wash", "rig_wash_inv"])
def test_pan_tilt_round_trip_through_16_bit_bytes(fixture):
    rig = rig_of(backlight={"fixture": fixture}, front_movers={"fixture": fixture},
                 towers={"fixture": fixture})
    motion = LIB.get(fixture).motion
    movers = [f for f in rig.fixtures if f.moving]
    assert len(movers) == 14
    for f in movers:
        assert reached(motion.pan, f.pan_dmx) == pytest.approx(f.pan, abs=1e-9)
        assert reached(motion.tilt, f.tilt_dmx) == pytest.approx(f.tilt, abs=1e-9)
        wanted = unit(sub(f.aim, f.pivot))
        assert angle(beam_from_angles(f.pan, f.tilt), wanted) < 0.01
        assert f.axis == pytest.approx(beam_from_angles(f.pan, f.tilt))


def test_inverted_axes_mirror_the_dmx_value_not_the_angle():
    plain = rig_of().find("FrontMover_01")
    inverted = rig_of(front_movers={"fixture": "rig_wash_inv"}).find("FrontMover_01")
    assert plain.pan == pytest.approx(inverted.pan, abs=0.01)
    assert plain.pan_dmx[0] * 256 + plain.pan_dmx[1] + inverted.pan_dmx[0] * 256 + inverted.pan_dmx[1] \
        == pytest.approx(65535, abs=1)
    rng = Range(-270, 270, True)
    assert rng.lerp(0.0) == 270 and rng.lerp(1.0) == -270
    assert rng.fraction(rng.lerp(0.3)) == pytest.approx(0.3)
    assert LIB.get("rig_wash_inv").motion.pan.invert and not LIB.get("rig_wash").motion.pan.invert


def test_second_pan_tilt_solution_when_the_first_is_out_of_range():
    rig = rig_of(front_movers={"fixture": "rig_wash_neg"})
    f = rig.find("FrontMover_01")
    first = aim_angles(unit(sub(f.aim, f.pivot)))
    assert first[1] > 5
    assert f.tilt == pytest.approx(-first[1], abs=0.01)
    assert (f.pan - first[0] - 180) % 360 == pytest.approx(0.0, abs=0.01) or \
        (f.pan - first[0] - 180) % 360 == pytest.approx(360.0, abs=0.01)
    assert -270 <= f.pan <= 270
    assert angle(beam_from_angles(f.pan, f.tilt), unit(sub(f.aim, f.pivot))) < 0.01


def test_pan_tilt_out_of_range_is_clamped_with_an_alert():
    lay = rig_layout(front_movers={"fixture": "rig_wash_stiff"})
    assert has(lay.warnings, "Pan/tilt hors course", "FrontMover_01")
    f = lay.rig.find("FrontMover_01")
    assert -10 <= f.pan <= 10 and -5 <= f.tilt <= 5


def test_static_fixtures_take_the_exact_angles():
    f = rig_of().find("Profile_C")
    assert f.pan_dmx is None and not f.moving
    assert f.axis == pytest.approx(unit(sub(f.aim, f.pivot)))
    assert 0.0 <= f.tilt <= 180.0


# ----------------------------------------------------------------- packing

def test_default_preset_has_no_crowding_alert_and_pcs_keep_their_x():
    lay = rig_layout(front_movers={"fixture": "rig_wash_wide"})
    assert not has(lay.warnings, "se touchent")
    z = lay.rig.zones
    for f in pcs(lay.rig):
        side = -1 if "_L_" in f.name else 1
        row, col = divmod(int(f.name[-2:]) - 1, z.nx)
        t = math.tan(math.radians(lay.rig.dims.pc_azimuths[row]))
        assert f.hang[0] == pytest.approx(z.xs[col] + side * (z.ys[row] - f.hang[1]) * t)


def test_crowded_fixtures_move_to_the_nearest_free_x():
    lay = rig_layout(front_movers={"fixture": "rig_wash_wide", "count": 8})
    on_pipe = [f for f in lay.rig.fixtures if f.support == "FrontPipe_02"]
    movers = [f for f in on_pipe if f.family == "front_movers"]
    moved = [f for f in movers if abs(f.hang[0] - spread(int(f.name[-2:]) - 1, 8, 10.0)) > 1e-9]
    assert moved
    reach = math.hypot(0.8, 0.15)

    def clear(x, me):
        return all(abs(x - o.hang[0]) >= 2 * reach + 2 * FOOTPRINT_MARGIN - 1e-9 for o in on_pipe if o is not me)

    limit = lay.find("FrontPipe_02").end[0]
    for f in moved:
        ideal = spread(int(f.name[-2:]) - 1, 8, 10.0)
        assert clear(f.hang[0], f) and abs(f.hang[0]) <= limit
        steps = round(abs(f.hang[0] - ideal) / 0.05)
        assert steps >= 1
        for k in range(steps):
            for sign in (1, -1):
                candidate = ideal + sign * k * 0.05
                assert abs(candidate) > limit or not clear(candidate, f)
        assert f.pivot[0] == f.hang[0] and f.root[0] == f.hang[0]
        assert f.axis == pytest.approx(unit(sub(f.aim, f.pivot)), abs=1e-3)
        assert f.aim[0] == pytest.approx(ideal)


def test_full_tube_raises_a_crowding_alert():
    lay = rig_layout(front_movers={"fixture": "rig_wash_huge", "count": 16})
    assert has(lay.warnings, "Appareils qui se touchent sur la seconde perche de face")


# --------------------------------------------------------------------- patch

def test_patch_addresses_are_consecutive_by_footprint_in_a_stable_order():
    rig = rig_of(patch={"front_pc_address": 10})
    entries = [e for e in rig.patch if e.family == "front_pc"]
    names = [e.name for e in entries]
    assert names == [f"FrontPC_{t}_{n:02d}" for r in (0, 1) for t in "LR" for n in range(r * 4 + 1, r * 4 + 5)]
    assert entries[0].universe == 4 and entries[0].address == 10
    for a, b in zip(entries, entries[1:]):
        assert b.address == a.address + a.footprint == a.address + 3
    assert [e.name for e in rig.patch if e.family == "profiles"] == ["Profile_L", "Profile_C", "Profile_R"]
    assert [e.family for e in rig.patch] == sorted((e.family for e in rig.patch), key=[
        "backlight", "front_movers", "tower_movers", "front_pc", "profiles", "hazer"].index)
    assert not has(rig.warnings, "Patch")


def test_patch_uses_the_chosen_mode_footprint():
    rig = rig_of(backlight={"mode": "Coarse"})
    entries = [e for e in rig.patch if e.family == "backlight"]
    assert {e.footprint for e in entries} == {4} and entries[1].address == 5
    assert rig.find("Backlight_01").mode == "Coarse"


def test_patch_overlap_and_overflow_alerts():
    same = rig_layout(patch={"front_movers_universe": 1})
    assert has(same.warnings, "Patch :", "se recouvrent", "univers 1")
    assert has(rig_layout(patch={"backlight_address": 510}).warnings,
               "Patch : l'univers 1 dépasse 512 canaux")
    far = rig_layout(patch={"profiles_universe": 7})
    assert not has(far.warnings, "Patch")


def test_patch_ranges_per_family():
    ranges = {r[0]: r[1:] for r in rig_of().dims.patch_ranges}
    assert ranges["front_pc"] == (4, 1, 48)
    assert ranges["profiles"] == (5, 1, 6)
    assert "hazer" not in ranges


# ---------------------------------------------------------- haze and rest

def test_hazer_drives_the_haze_only_when_dmx_driven():
    assert rig_of().haze is None and not rig_of().by_family("hazer")
    rig = rig_of(haze={"dmx_driven": True}, rest={"haze_level": 0.5})
    link = rig.haze
    hazer = rig.find("Hazer_01")
    assert (hazer.universe, hazer.address) == (6, 1)
    assert link.prop == "dmx_6_1" and link.fine_prop is None and link.bits == 8
    assert link.rest == pytest.approx(round(255 * 0.5) / 255)
    assert rig.rest[(6, 1)] == pytest.approx(round(255 * 0.5) / 255)
    assert hazer.root[2] == pytest.approx(1.2) and hazer.root_rotation == (0.0, 0.0, 0.0)


def test_rest_values_of_the_face_pc():
    rig = rig_of()
    left, right = rig.find("FrontPC_L_01"), rig.find("FrontPC_R_01")
    dimmer = left.channels[0]
    assert dimmer.data == (179, 50) and dimmer.channel == 1 and dimmer.fine_channel == 2
    assert rig.rest[(4, 1)] == pytest.approx(179 / 255) and rig.rest[(4, 2)] == pytest.approx(50 / 255)
    cct = {f.name: [c for c in f.channels if c.attribute == "cct"][0] for f in (left, right)}
    assert cct[left.name].data == (round(255 * (3200 - 2700) / 3800),)
    assert cct[right.name].data == (round(255 * (5600 - 2700) / 3800),)
    assert rig.rest[(4, 3)] == pytest.approx(cct[left.name].data[0] / 255)
    assert left.cct == 3200 and right.cct == 5600


def test_rest_cct_out_of_the_fiche_range_is_clamped_with_an_alert():
    lay = rig_layout(rest={"cct_left": 1500})
    assert has(lay.warnings, "hors de la plage", "rig_pc")
    cct = [c for c in lay.rig.find("FrontPC_L_01").channels if c.attribute == "cct"][0]
    assert cct.data == (0,)


def test_zoom_channel_carries_the_computed_field():
    rig = rig_of(front_pc={"mode": "Zoom"})
    f = rig.find("FrontPC_L_01")
    zoom = [c for c in f.channels if c.attribute == "zoom"][0]
    assert 10 + zoom.value * 60 == pytest.approx(f.field_angle, abs=0.2)


def test_levels_and_mover_rest_values():
    rig = rig_of(rest={"mover_level": 0.25, "profile_level": 0.4})
    assert [c for c in rig.find("Backlight_01").channels if c.attribute == "dimmer"][0].data == (64,)
    assert [c for c in rig.find("Profile_L").channels if c.attribute == "dimmer"][0].data == (102,)
    pan = [c for c in rig.find("FrontMover_01").channels if c.attribute == "pan"][0]
    assert pan.data == rig.find("FrontMover_01").pan_dmx


def test_emitter_colour_reproduces_the_black_body():
    lustr = default_fiche("etc_s4led_s3_lustr_x8")
    lay = rig_layout(library=default_library(), profiles={"fixture": lustr.id},
                     front_pc={"fixture": "generic_pc_led"}, rest={"cct_profile": 4000})
    values = {c.attribute: c.value for c in lay.rig.find("Profile_L").channels}
    mix = [sum(values[e.attribute] * e.rgb[i] for e in lustr.colour.emitters) for i in range(3)]
    assert mix == pytest.approx(cct_to_rgb(4000), abs=0.06)


def test_loads_sum_the_weights_per_support():
    rig = rig_of()
    loads = {l.name: l for l in rig.loads}
    on_pipe = [f for f in rig.fixtures if f.support == "FrontPipe"]
    assert loads["FrontPipe"].weight == pytest.approx(sum(f.weight for f in on_pipe))
    assert loads["FrontPipe"].weight == pytest.approx(8 * 10 + 3 * 8)
    assert loads["FrontPipe_02"].weight == pytest.approx(4 * 12)
    assert loads["Tower_L_01"].weight == pytest.approx(24.0) and loads["Tower_L_01"].count == 2
    assert [l.name for l in rig.loads][:2] == ["FrontPipe", "FrontPipe_02"]


# -------------------------------------------------------------------- library

def default_fiche(fixture_id):
    return default_library().get(fixture_id)


def test_missing_fiche_skips_the_family_with_an_alert():
    lay = rig_layout(backlight={"fixture": "does_not_exist"})
    assert not lay.rig.by_family("backlight")
    assert has(lay.warnings, "does_not_exist", "introuvable")
    assert lay.rig.by_family("front_pc") and lay.rig.by_family("profiles")


def test_wrong_family_and_unknown_mode_are_alerts_not_crashes():
    lay = rig_layout(front_pc={"fixture": "rig_wash"}, profiles={"mode": "Nope"})
    assert not lay.rig.by_family("front_pc")
    assert has(lay.warnings, "inadaptée")
    assert has(lay.warnings, "Mode « Nope » inconnu")
    assert lay.rig.find("Profile_L").mode == "Direct"


def test_empty_library_never_crashes():
    lay = rig_layout(library=EMPTY_LIBRARY, haze={"dmx_driven": True})
    assert not lay.rig.fixtures and lay.rig.haze is None
    assert len([w for w in lay.warnings if "introuvable" in w]) == 6
    assert "FrontPipe" in lay.names()


def test_default_library_is_the_shipped_one():
    lay = shipped_layout(make())
    assert default_fiche("generic_pc_led") is not None
    assert len(lay.rig.by_family("front_pc")) == 16


# ------------------------------------------------------- shipped integration

def test_shipped_library_default_rig():
    lay = shipped_layout(make())
    rig = lay.rig
    missing = [w for w in lay.warnings if "introuvable" in w]
    assert not missing
    counts = {k: len(rig.by_family(k)) for k in ("backlight", "front_movers", "tower_movers",
                                                  "front_pc", "profiles")}
    assert counts == {"backlight": 6, "front_movers": 4, "tower_movers": 4, "front_pc": 16,
                      "profiles": 3}
    assert rig.dims.pipe_z == pytest.approx(7.0) and rig.dims.pipe_y == pytest.approx(-1.40, abs=0.01)
    for word in ("se touchent", "Patch", "Pan/tilt hors course", "Pylône"):
        assert not has(lay.warnings, word)
    assert [t for _, t, _ in rig.dims.profiles] == ["70", "70", "70"]
    for f in rig.fixtures:
        assert f.universe >= 1 and f.footprint >= 1 and f.channels
        assert all(0 <= b <= 255 for c in f.channels for b in c.data)


def test_shipped_movers_round_trip_with_their_inverted_axes():
    rig = shipped_layout(make()).rig
    for f in (f for f in rig.fixtures if f.moving):
        fx = default_fiche(f.fixture_id)
        assert reached(fx.motion.pan, f.pan_dmx) == pytest.approx(f.pan, abs=0.01) \
            if len(f.pan_dmx) == 2 else True
        assert angle(beam_from_angles(f.pan, f.tilt), unit(sub(f.aim, f.pivot))) < 0.05
    aura = default_fiche("martin_mac_aura").motion
    assert aura.pan.invert and aura.tilt.invert
    esprite = default_fiche("robe_robin_esprite")
    assert esprite.motion.tilt.invert and esprite.blades.rotation.invert and not esprite.motion.pan.invert


# ------------------------------------------- far rows fixture and the forestage

USER_SCENE = Path(__file__).parent / "data" / "presets" / "user_open_angled.yaml"


def user_params(**front_pc):
    """The user's scene (no modules, angled legs). It was saved with `zone_width` 1.62, a 7 x 4 grid whose
    28 far PC cannot hang on one batten whatever the fiche; the cases below use 3.0 and 2.0."""
    params, messages = read_preset(USER_SCENE)
    assert messages == []
    params["front_pc"].update(front_pc)
    return params


CASES = {
    "default": lambda: make(),
    "reference_with_modules": lambda: classic(read_preset(shipped_presets()["reference_with_modules"])[0]),
    "open_space": lambda: classic(read_preset(shipped_presets()["open_space"])[0]),
    "user_3": lambda: user_params(zone_width=3.0),
    "user_2": lambda: user_params(zone_width=2.0),
}


def uncovered_forestage(rig, params):
    """Points of the forestage floor (grid 0.25 m, nez to facade, nez width) outside every row 0 cone."""
    ctx, _ = _make_context(params)
    row0 = [f for f in pcs(rig) if f.support == "FrontPipe"]
    steps_x, steps_y = round(ctx.W / 0.25), int(ctx.Ys / 0.25 + 1e-9)
    points = [(-ctx.W / 2 + i * 0.25, j * 0.25, ctx.Hp) for i in range(steps_x + 1) for j in range(steps_y + 1)]
    return [p for p in points
            if not any(angle(f.axis, sub(p, f.pivot)) <= f.field_angle / 2 + 1e-6 for f in row0)]


@pytest.mark.parametrize("name", list(CASES))
def test_scenes_are_alert_free_and_the_front_row_lights_the_whole_forestage(name):
    params = CASES[name]()
    rig = shipped_layout(params).rig
    assert rig.warnings == ()
    assert uncovered_forestage(rig, params) == []
    assert len(rig.by_family("front_pc")) == 2 * rig.zones.nx * rig.zones.nr


def test_the_front_row_aim_is_lowered_onto_the_forestage_with_the_same_heading():
    lay = shipped_layout(make())
    z = lay.rig.zones
    for f in (f for f in pcs(lay.rig) if f.support == "FrontPipe"):
        heading = math.atan2(f.aim[0] - f.pivot[0], f.aim[1] - f.pivot[1])
        centre = (z.xs[int(f.name[-2:]) - 1], z.ys[0], 2.9)
        assert heading == pytest.approx(math.atan2(centre[0] - f.pivot[0], centre[1] - f.pivot[1]))
        assert 0.5 < centre[1] - f.aim[1] < 1.1 and f.aim[2] == pytest.approx(2.9)


def test_far_rows_use_their_own_fixture_and_mode_and_the_front_row_keeps_its_own():
    rig = rig_of(front_pc={"fixture_far": "rig_fresnel", "mode_far": "Dimmer 16 bit + CCT"})
    near = [f for f in pcs(rig) if f.support == "FrontPipe"]
    far = [f for f in pcs(rig) if f.support != "FrontPipe"]
    assert near and far and not has(rig.warnings, "Fiche")
    assert {(f.fixture_id, f.mode) for f in near} == {("rig_pc", "Basic")}
    assert {(f.fixture_id, f.mode) for f in far} == {("rig_fresnel", "Dimmer 16 bit + CCT")}


def test_a_family_with_two_fixtures_is_patched_by_each_footprint():
    rig = rig_of(front_pc={"fixture_far": "rig_fresnel"})
    address = 1
    for f in pcs(rig):
        assert (f.universe, f.address) == (4, address)
        address += f.footprint
    assert {f.footprint for f in pcs(rig)} == {3, 4}
    assert dict((k, (u, a, b)) for k, u, a, b in rig.dims.patch_ranges)["front_pc"] == (4, 1, address - 1)


def test_far_rows_cover_zones_the_front_row_fixture_cannot():
    hard = user_params(zone_width=3.0)
    pc = shipped_layout(hard, far="generic_pc_led").rig
    assert has(pc.warnings, "Rang 2", "aucun azimut")
    wide = shipped_layout(user_params(zone_width=3.0)).rig
    assert wide.warnings == () and max(f.field_angle for f in pcs(wide)) > 54.4
    assert {f.fixture_id for f in pcs(wide)} == {"generic_pc_led", "rig_fresnel"}


def test_missing_or_unsuitable_far_fiche_falls_back_to_the_front_row_fiche_with_an_alert():
    for far, word in (("ghost", "introuvable"), ("rig_wash", "inadaptée")):
        rig = rig_layout(front_pc={"fixture_far": far}).rig
        assert has(rig.warnings, far, word, "posés avec « rig_pc »")
        assert {f.fixture_id for f in pcs(rig)} == {"rig_pc"}


def test_unknown_far_mode_takes_the_default_mode_with_an_alert():
    rig = rig_layout(front_pc={"fixture_far": "rig_fresnel", "mode_far": "Nope"}).rig
    assert has(rig.warnings, "Nope", "rig_fresnel")
    assert {f.mode for f in pcs(rig) if f.support != "FrontPipe"} == {"Dimmer 16 bit + CCT + Zoom"}


def test_far_fiche_is_not_asked_for_when_there_is_one_row():
    rig = rig_layout(front_pc={"fixture_far": "ghost", "zone_mode": "manual", "rows": 1}).rig
    assert not has(rig.warnings, "ghost")


def test_the_shipped_default_far_fixture_is_the_wide_fresnel():
    lay = compute_layout(make())
    assert lay.rig.warnings == ()
    assert {f.fixture_id for f in pcs(lay.rig) if f.support != "FrontPipe"} == {"generic_fresnel_led"}
    assert {f.fixture_id for f in pcs(lay.rig) if f.support == "FrontPipe"} == {"generic_pc_led"}


# ------------------------------------------------------- alert-free defaults

def test_shipped_presets_raise_no_rig_alert():
    from core.presets import read_preset, shipped_presets
    presets = shipped_presets()
    assert {"reference_with_modules", "open_space"} <= set(presets)
    for name, path in presets.items():
        params, messages = read_preset(path)
        assert not messages, name
        rig = compute_layout(params, SHIPPED).rig
        assert rig.warnings == (), name


def shipped_rigs():
    out = {"default": shipped_layout(make())}
    for name, path in shipped_presets().items():
        out[name] = shipped_layout(classic(read_preset(path)[0]))
    return out


@pytest.mark.parametrize("name", ["default", "reference_with_modules"])
def test_no_two_fixtures_overlap_on_a_support_once_posed(name):
    lay = shipped_rigs()[name]
    pairs, gaps = overlapping(lay.rig, SHIPPED)
    assert pairs == [] and gaps
    assert min(gaps.values()) >= 0.0 and lay.rig.warnings == ()


def test_pc_footprint_includes_the_swing_of_the_heads():
    # FrontPC_L_07 and R_05 used to hang 0.34 m apart while panned +-132 degrees: heads intersected.
    rig = shipped_layout(make(), far="generic_pc_led").rig
    library = SHIPPED
    pc = rig.find("FrontPC_L_07")
    low, high = posed_interval(library, pc)
    assert high - low > 1.5 * pc.width
    assert abs(rig.find("FrontPC_R_05").hang[0] - pc.hang[0]) > 0.5
    assert rig.dims.pc_azimuths[1] != 45.0


def test_posed_points_follow_the_head_frame_of_the_spec():
    boxes = _Boxes((), (), ((0.0, 0.0, 0.5),), (0.0, 0.0, 0.2))
    for pan, tilt in ((0.0, 0.0), (30.0, 40.0), (-132.0, 45.0), (170.0, 100.0)):
        (point,) = posed_points(boxes, (1.0, 2.0, 3.0), pan, tilt)
        axis = head_frame(pan, tilt)[2]
        assert point == pytest.approx(add((1.0, 2.0, 3.0 - 0.2), mul(axis, 0.5)))


def test_default_profiles_all_find_a_tube_within_travel():
    lay = shipped_layout(make())
    assert [t for _, t, _ in lay.rig.dims.profiles] == ["70", "70", "70"]
    assert not has(lay.warnings, "Découpe")


def test_top_cut_is_the_actor_head_unless_the_lintel_is_lower():
    ctx, _ = _make_context(make(**SYNTH))
    source = (0.0, -1.4, 6.65)
    assert top_line(ctx, source)[2] == pytest.approx(ctx.Hp + 2.20)
    assert top_line(ctx, source, top_height=6.0)[2] == pytest.approx(ctx.Hp + ctx.Hc - 0.10)
    tall = rig_layout(profiles={"top_height": 6.0})
    low = rig_layout(profiles={"top_height": 2.20})
    top = lambda lay: next(b for b in lay.rig.find("Profile_C").blades.blades if b.cut == "top")
    assert top(tall).edge != pytest.approx(top(low).edge)


# --------------------------------------------------- second pipe for the movers

def movers_of(rig):
    return rig.by_family("front_movers")


def beam_alerts(lay):
    return has(lay.warnings, "Faisceau de") + has(lay.warnings, "Faisceaux :") + has(lay.warnings, "Débattement")


def manual_movers(z, **front):
    return shipped_layout(make(rig_front={"movers_height_mode": "manual", "movers_z": z, **front}))


def test_front_movers_hang_on_a_second_pipe_behind_the_first():
    lay = shipped_layout(make())
    rig, dims = lay.rig, lay.rig.dims
    first, second = lay.find("FrontPipe"), lay.find("FrontPipe_02")
    assert dims.movers_pipe_y == pytest.approx(dims.pipe_y - 1.50)
    assert second.start[1] == pytest.approx(dims.movers_pipe_y) and second.start[2] == pytest.approx(dims.movers_pipe_z)
    assert second.end[0] == pytest.approx(first.end[0]) and second.start[0] == pytest.approx(first.start[0])
    assert (second.material, second.collection) == ("TS_Batten", "Theatre_Rig")
    movers = movers_of(rig)
    assert len(movers) == 4
    for i, f in enumerate(movers):
        assert f.support == "FrontPipe_02" and f.universe == 2
        assert f.hang == pytest.approx((spread(i, 4, 10.0), dims.movers_pipe_y, dims.movers_pipe_z))
        assert f.aim == pytest.approx((spread(i, 4, 10.0), rig.zones.ys[0], 2.90))
    assert {f.family for f in rig.fixtures if f.support == "FrontPipe"} == {"front_pc", "profiles"}
    assert rig.warnings == ()


def test_second_pipe_is_absent_without_front_movers():
    lay = shipped_layout(make(front_movers={"enabled": False}))
    assert "FrontPipe_02" not in lay.names() and lay.rig.dims.movers_pipe_y is None
    assert lay.rig.dims.mover_radius is None and "FrontPipe" in lay.names()


def test_second_pipe_offset_and_house_alert():
    near = shipped_layout(make(rig_front={"movers_offset": 3.0}))
    assert near.rig.dims.movers_pipe_y == pytest.approx(near.rig.dims.pipe_y - 3.0)
    assert not has(near.warnings, "Perche des mobiles hors de la salle")
    far = shipped_layout(make(rig_front={"auto_position": False, "y": -4.0, "movers_offset": 10.0}))
    assert far.rig.dims.movers_pipe_y == pytest.approx(-14.0)
    assert has(far.warnings, "Perche des mobiles hors de la salle")


def test_auto_height_is_the_highest_step_that_clears_every_beam():
    dims = shipped_layout(make()).rig.dims
    steps = (dims.pipe_z - dims.movers_pipe_z) / HEIGHT_STEP
    assert steps >= 1 and steps == pytest.approx(round(steps))
    assert not beam_alerts(manual_movers(dims.movers_pipe_z))
    blocked = manual_movers(dims.movers_pipe_z + HEIGHT_STEP)
    assert has(blocked.warnings, "Faisceau de FrontMover_", "gêné par FrontPC_")
    assert default_params()["rig_front"]["movers_z"] == pytest.approx(dims.movers_pipe_z)


def test_auto_height_keeps_the_height_of_the_first_pipe_when_nothing_blocks():
    lay = shipped_layout(make(front_pc={"enabled": False}, profiles={"enabled": False}))
    assert lay.rig.dims.movers_pipe_z == pytest.approx(lay.rig.dims.pipe_z) and lay.rig.warnings == ()


def test_manual_height_is_taken_as_given_and_blocked_beams_are_named():
    lay = manual_movers(7.0)
    assert lay.rig.dims.movers_pipe_z == 7.0
    assert has(lay.warnings, "Faisceau de FrontMover_01 vers (5,00 ; 6,00 ; 2,90) gêné par FrontPC_")
    assert not has(lay.warnings, "aucune hauteur")
    assert manual_movers(6.8).rig.warnings == ()


def test_no_clear_height_keeps_the_best_one_and_reports_the_blocked_targets():
    lay = shipped_layout(make(rig_front={"movers_offset": 0.5}))
    ctx, _ = _make_context(make())
    assert has(lay.warnings, "aucune hauteur")
    assert has(lay.warnings, "Faisceau de FrontMover_01 vers", "gêné par FrontMover_02")
    assert ctx.Hp + ctx.Hc - 1e-9 <= lay.rig.dims.movers_pipe_z <= lay.rig.dims.pipe_z
    assert lay.rig.dims.beam_clearance < BEAM_MARGIN


def test_swept_envelope_bounds_the_vertices_over_the_whole_tilt_range():
    library = default_library()
    for fixture_id in ("robe_robin_esprite", "martin_mac_aura"):
        fx = library.get(fixture_id)
        model = fixture_model(fx)
        pivot, tilt = model.tilt_pivot, fx.pan_tilt[1]
        reach = max(math.hypot(v[0], v[1]) for v in (*model.base.vertices, *model.pan.vertices))
        for k in range(int((tilt.max - tilt.min) / 0.5) + 1):
            rx = rot_x(-(tilt.min + 0.5 * k))
            for v in model.tilt.vertices:
                x, y, _ = matvec(rx, v)
                reach = max(reach, math.hypot(x, y + pivot[1]))
        rig = shipped_layout(make(front_movers={"fixture": fixture_id}, backlight={"fixture": fixture_id})).rig
        assert reach - 1e-9 <= rig.dims.mover_radius <= 1.25 * reach


def test_movers_pack_by_their_swept_envelope_not_their_rest_pose():
    rig = shipped_layout(make(front_movers={"count": 14})).rig
    radius = rig.dims.mover_radius
    xs = sorted(f.hang[0] for f in movers_of(rig))
    assert len(xs) == 14
    assert all(b - a >= 2 * (radius + FOOTPRINT_MARGIN) - 1e-9 for a, b in zip(xs, xs[1:]))
    assert any(abs(f.hang[0] - spread(int(f.name[-2:]) - 1, 14, 10.0)) > 1e-6 for f in movers_of(rig))
    library = default_library()
    for f in movers_of(rig):
        low, high = posed_interval(library, f)
        assert f.hang[0] - radius <= low and high <= f.hang[0] + radius


def test_swept_envelope_touching_a_fixture_on_another_support_is_an_alert():
    wide = {"front_movers": {"fixture": "rig_wash_wide"}}
    lay = rig_layout(**wide, rig_front={"movers_offset": 0.5, "movers_height_mode": "manual", "movers_z": 7.0})
    assert has(lay.warnings, "Débattement de pan et tilt", "FrontMover_01", "FrontPC_")
    lower = rig_layout(**wide, rig_front={"movers_offset": 0.5, "movers_height_mode": "manual", "movers_z": 5.0})
    assert not has(lower.warnings, "Débattement")


def test_beam_gap_is_a_signed_distance_to_the_cone_between_lens_and_target():
    beam = _make_beam("A", (0.0, 0.0, -4.0), (0.0, 0.0, 0.0), (0.0, 0.0, -1.0), 30.0, 0.2)
    half = math.radians(15)

    def gap(point):
        found = _gaps([beam], [_cloud("B", "S", [point])])
        return found[0][2] if found else None

    assert gap((0.5, 0.0, -2.0)) == pytest.approx(0.5 * math.cos(half) - 2.0 * math.sin(half))
    assert gap((0.5, 0.0, -2.0)) < 0 < gap((0.6, 0.0, -2.0))
    assert gap((0.0, 0.0, -0.1)) is None and gap((0.0, 0.0, -4.5)) is None
    assert gap((0.0, 0.0, 1.0)) is None
    assert _gaps([beam], [_cloud("A", "S", [(0.0, 0.0, -2.0)])]) == []


def test_default_and_shipped_presets_keep_every_beam_clear():
    for name, lay in shipped_rigs().items():
        if name == "open_space":
            continue
        dims = lay.rig.dims
        assert lay.rig.warnings == () and dims.beam_clearance >= BEAM_MARGIN, name
        assert dims.masking_clearance >= BEAM_MARGIN, name
        assert dims.movers_pipe_z == pytest.approx(6.8) and dims.movers_pipe_y == pytest.approx(dims.pipe_y - 1.5)


# ------------------------------------------- borders and legs in the beam checks

def masking_alerts(warnings):
    return has(warnings, "Faisceau de", "gêné par la frise") + has(warnings, "Faisceau de", "gêné par le pendrillon")


def test_row_two_pcs_hang_on_the_mantle_batten_behind_the_front_border():
    lay = shipped_layout(make())
    front = lay.find("MaskingBatten_00").start[1]
    row = [f for f in pcs(lay.rig) if f.circuit.startswith("FrontPC_Row2")]
    assert len(row) == 8 and {f.support for f in row} == {"Batten_02"}
    assert all(f.hang[1] == pytest.approx(front + 0.30) for f in row)
    (_, site), = [r for r in lay.rig.dims.pc_supports if r[0] == "Batten_02"]
    assert lay.rig.dims.pc_azimuths[1] == 45.0 and site == pytest.approx(57.7, abs=0.1)
    assert lay.rig.warnings == () and lay.rig.dims.masking_clearance >= BEAM_MARGIN


def test_row_two_keeps_the_site_nearest_battens_when_there_is_no_front_border():
    rig = shipped_layout(make(masking={"front_border": False})).rig
    assert [name for name, _ in rig.dims.pc_supports] == ["FrontPipe", "Batten_01"]
    assert rig.warnings == ()


def test_row_without_a_fitting_batten_keeps_the_nearest_site_and_alerts():
    lay = shipped_layout(classic(read_preset(shipped_presets()["open_space"])[0]), far="generic_pc_led")
    assert [name for name, _ in lay.rig.dims.pc_supports] == ["FrontPipe", "Batten_02"]
    assert has(lay.rig.warnings, "Rang 2", "aucun azimut") and has(lay.rig.warnings, "Zone non couverte")


def test_a_low_border_makes_the_beam_checks_alert_and_names_beam_target_and_border():
    lay = shipped_layout(make(masking={"borders_mode": "manual", "border_bottom": 4.0}))
    hits = has(lay.warnings, "Faisceau de Backlight_", "vers (", "gêné par la frise Border_03")
    assert hits and lay.rig.dims.masking_clearance < 0
    assert not has(lay.warnings, "Faisceau de FrontMover_", "gêné par la frise")


def test_auto_height_goes_down_to_keep_the_movers_beams_under_the_front_border():
    high = shipped_layout(make()).rig.dims.movers_pipe_z
    low = shipped_layout(make(masking={"borders_mode": "manual", "border_bottom": 4.0}))
    assert low.rig.dims.movers_pipe_z < high
    assert not has(low.warnings, "Faisceau de FrontMover_", "gêné par la frise")
    raised = shipped_layout(make(masking={"borders_mode": "manual", "border_bottom": 4.0},
                                 rig_front={"movers_height_mode": "manual", "movers_z": high}))
    assert has(raised.warnings, "Faisceau de FrontMover_", "gêné par la frise Border_00")


def aimed(target, source, field=20.0, owner="B"):
    d = tuple(t - o for t, o in zip(target, source))
    n = math.sqrt(sum(v * v for v in d))
    return _make_beam(owner, target, source, tuple(v / n for v in d), field, 0.0)


def test_a_beam_against_a_border_uses_the_bright_core_of_its_cone():
    border = {w.name: w for w in _walls(_make_context(make())[0])}["Border_00"]
    # Border_00 hangs at Y 2.355 from Z 5.49 to 6.80; the aim line passes 0.60 m under its bottom.
    under = lambda field: aimed((0.0, 4.0, 4.89), (0.0, 0.0, 4.89), field)
    assert _wall_gaps([under(2.0)], [border]) == []
    assert _wall_gaps([under(20.0)], [border])[0][2] >= BEAM_MARGIN
    # The core is half the half angle, and the fabric counts 0.09 m thick: 60 degrees reaches it.
    assert _wall_gaps([under(60.0)], [border])[0][2] < 0
    assert _wall_gaps([aimed((0.0, 4.0, 6.0), (0.0, 0.0, 6.0), 2.0)], [border])[0][2] < BEAM_MARGIN


def test_a_beam_crossing_a_leg_is_blocked_unless_it_grazes_the_edge_or_aims_behind_it():
    leg = {w.name: w for w in _walls(_make_context(make())[0])}["Leg_L_01"]
    # Leg_L_01 spans X -7 to -4 at Y 4.25; its inner end counts as pulled back by 0.30 m.
    deep = _wall_gaps([aimed((-3.9, 4.5, 2.9), (-9.0, 2.9, 6.8))], [leg])
    assert deep and deep[0][2] < BEAM_MARGIN
    graze = _wall_gaps([aimed((-3.9, 4.5, 2.9), (-5.0, 2.9, 6.8))], [leg])
    assert not graze or graze[0][2] >= BEAM_MARGIN
    assert _wall_gaps([aimed((-4.6, 4.5, 2.9), (-9.0, 2.9, 6.8))], [leg]) == []


# ------------------------------------------------------- row 0 focus, barn doors

def row0(rig):
    return [f for f in pcs(rig) if f.support == "FrontPipe"]


def test_face_tilt_raises_and_lowers_the_row_zero_axis_by_the_given_angle():
    def head(tilt):
        f = shipped_layout(make(front_pc={"face_tilt": tilt})).rig.find("FrontPC_L_03")
        return f.pivot, math.degrees(math.asin(-f.axis[2]))

    (pivot, base), (raised_pivot, raised), (lowered_pivot, lowered) = head(0.0), head(2.0), head(-0.5)
    assert pivot == raised_pivot == lowered_pivot
    assert raised == pytest.approx(base - 2.0, abs=0.01) and lowered == pytest.approx(base + 0.5, abs=0.01)


def beam_miss(rig, points):
    """Points of the floor outside the 50 % cone of every row 0 PC."""
    return [p for p in points
            if not any(angle(f.axis, sub(p, f.pivot)) <= f.beam_angle / 2 + 1e-6 for f in row0(rig))]


def nez_points(params, step=0.25):
    ctx, _ = _make_context(params)
    return ctx, [(-ctx.W / 2 + i * step, 0.0, ctx.Hp) for i in range(round(ctx.W / step) + 1)]


@pytest.mark.parametrize("name", list(CASES))
def test_the_nez_at_floor_level_sits_in_the_beam_of_both_pc_of_every_zone(name):
    params = CASES[name]()
    rig = shipped_layout(params).rig
    ctx, _ = _make_context(params)
    zones = rig.zones
    for f in row0(rig):
        centre = (zones.xs[int(f.name[-2:]) - 1], 0.0, ctx.Hp)
        assert angle(f.axis, sub(centre, f.pivot)) <= f.beam_angle / 2 + 1e-6, f.name
        assert f.beam_angle < f.field_angle


@pytest.mark.parametrize("name", list(CASES))
def test_the_nez_row_is_in_a_beam_except_the_last_metre_the_outer_pc_cannot_reach(name):
    params = CASES[name]()
    ctx, points = nez_points(params)
    missed = beam_miss(shipped_layout(params).rig, points)
    assert all(abs(p[0]) > ctx.W / 2 - 1.3 for p in missed), [round(p[0], 2) for p in missed]
    if name == "user_2":
        assert missed == []


def test_the_row_zero_aim_is_the_smallest_field_that_holds_the_nez_in_the_beam():
    params = make()
    ctx, _ = _make_context(params)
    rig = shipped_layout(params).rig
    pc = rig.find("FrontPC_L_03")
    zones = rig.zones
    xc = zones.xs[int(pc.name[-2:]) - 1]
    edge = (xc - zones.width / 2, 0.0, ctx.Hp)
    grow = zones.width / 2 * 0.2
    corners = [(x, y, z) for x in (xc - zones.width / 2 - grow, xc + zones.width / 2 + grow)
               for y, z in ((0.0, ctx.Hp), (zones.ys[0] + zones.depth / 2 * 1.2, 2.9))]
    assert angle(pc.axis, sub(edge, pc.pivot)) == pytest.approx(pc.beam_angle / 2, abs=0.1)
    assert max(angle(pc.axis, sub(c, pc.pivot)) for c in corners) == pytest.approx(pc.field_angle / 2, abs=0.1)
    assert pc.field_angle == pytest.approx(51.0, abs=0.2) and pc.aim[1] == pytest.approx(0.54, abs=0.03)
    reach = dict(rig.dims.nez_reach)
    assert reach["FrontPC_L_03"] == 1.0 and 0.0 <= reach["FrontPC_L_01"] < 1.0 and reach["FrontPC_R_04"] < 1.0


def test_an_unreachable_nez_keeps_the_best_aim_and_names_the_pc():
    rig = rig_layout(front_pc={"zone_width": 10.0}).rig
    assert has(rig.warnings, "Face : le nez n'est pas dans le faisceau de FrontPC_")
    assert all(f.field_angle == 70.0 for f in row0(rig))
    assert not has(rig_layout().warnings, "le nez n'est pas")


def lit(f, p):
    """Whether the cut beam of `f` reaches `p`: inside the field cone and not beyond a closed leaf."""
    from core.barndoors import beyond
    if angle(f.axis, sub(p, f.source)) > f.field_angle / 2:
        return False
    return not (f.barn_doors and beyond(f.barn_doors.normals, f.source, p))


def spill_points(ctx):
    front = [(-ctx.W / 2 + 0.2 * i, 0.0, ctx.Hp - 0.02 - 0.2 * k)
             for i in range(round(ctx.W / 0.2) + 1) for k in range(int((ctx.Hp - 0.02) / 0.2) + 1)]
    walls = [(sx * ctx.Wt / 2, -ctx.Yh + 0.25 * i, 0.25 * k) for sx in (-1, 1)
             for i in range(int((ctx.Yh + ctx.Ys) / 0.25) + 1) for k in range(int(ctx.Hf / 0.25) + 1)]
    lintel = [(-ctx.W / 2 + 0.25 * i, ctx.Ys + 0.05, ctx.Hp + ctx.Hc + 0.1 * k)
              for i in range(round(ctx.W / 0.25) + 1) for k in range(1, 8)]
    return front, walls, lintel


@pytest.mark.parametrize("name", list(CASES))
def test_closed_leaves_keep_row_zero_off_the_stage_front_the_house_walls_and_the_lintel(name):
    params = CASES[name]()
    ctx, _ = _make_context(params)
    front, walls, lintel = spill_points(ctx)
    rig = shipped_layout(params).rig
    for f in row0(rig):
        assert f.barn_doors is not None, f.name
        for points in (front, walls, lintel):
            assert [p for p in points if lit(f, p)] == [], f.name
    params["front_pc"]["barn_doors"] = "none"
    bare = shipped_layout(params).rig
    assert all(f.barn_doors is None for f in pcs(bare))
    assert any(lit(f, p) for f in row0(bare) for p in front)


def test_row_zero_leaf_angles_of_a_central_and_an_outer_pc():
    rig = shipped_layout(make()).rig
    inner, outer = rig.find("FrontPC_L_03").barn_doors, rig.find("FrontPC_L_01").barn_doors
    cuts = lambda d: {leaf.cut: leaf for leaf in d.leaves if leaf.cut}
    assert set(cuts(inner)) == {"bottom", "right"} and set(cuts(outer)) == {"bottom", "left", "right"}
    assert cuts(inner)["bottom"].angle == pytest.approx(28.5, abs=0.5)
    assert cuts(outer)["bottom"].angle == pytest.approx(24.0, abs=0.5)
    assert all(leaf.reached and leaf.active for d in (inner, outer) for leaf in cuts(d).values())
    assert [leaf.angle for leaf in inner.leaves if not leaf.cut] == [0.0, 0.0]


def shipped_rig(params):
    """Rig with the shipped fiches only: the far rows take the Fresnel of the defaults."""
    return compute_layout(params, SHIPPED).rig


@pytest.mark.parametrize("name", list(CASES))
def test_every_scene_closes_leaves_on_every_pc_without_an_alert(name):
    rig = shipped_rig(CASES[name]())
    assert rig.warnings == ()
    assert all(f.barn_doors is not None for f in pcs(rig))
    assert all(leaf.reached for f in pcs(rig) for leaf in f.barn_doors.leaves)


def test_far_rows_close_their_side_leaves_on_the_masking_opening():
    rig = shipped_rig(make())
    far = [f for f in pcs(rig) if f.support != "FrontPipe"]
    assert far and all(f.barn_doors is not None for f in far) and not has(rig.warnings, "Volets")
    assert all({leaf.cut for leaf in f.barn_doors.leaves} - {""} <= {"left", "right", "top"} for f in far)
    assert any(leaf.cut == "left" for f in far for leaf in f.barn_doors.leaves)


def test_a_fiche_without_barn_doors_or_with_the_option_off_gets_none():
    assert all(f.barn_doors is None for f in pcs(rig_of()))
    assert all(f.barn_doors is None for f in pcs(shipped_rig(make(front_pc={"barn_doors": "none"}))))


def test_manual_leaves_follow_the_params_per_row_and_direction():
    params = make(front_pc={"barn_doors": "manual", "row1_l_leaf_2": 30.0, "row1_l_rotation": 12.0,
                            "row2_r_leaf_4": 95.0, "row2_r_rotation": -20.0})
    rig = shipped_rig(params)
    first, far = rig.find("FrontPC_L_02").barn_doors, rig.find("FrontPC_R_06").barn_doors
    assert [leaf.angle for leaf in first.leaves] == [0.0, 30.0, 0.0, 0.0] and first.rotation == 12.0
    assert [leaf.angle for leaf in far.leaves] == [0.0, 0.0, 0.0, 80.0] and far.rotation == -20.0
    assert {leaf.cut for leaf in first.leaves} == {""} and rig.find("FrontPC_R_02").barn_doors.rotation == 0.0


def test_barn_doors_widen_the_posed_footprint_of_a_pc():
    from core.barndoors import envelope_points
    from core.rig import _Sheet, _Work, _boxes
    params = make()
    ctx, _ = _make_context(params)
    fx = SHIPPED.get("generic_pc_led")
    zones = compute_layout(params, SHIPPED).rig.zones
    sheet = _Sheet(fx, fx.mode(), fx.physical.dimensions, fx.physical.mount, fx.optics)
    boxes = _boxes(_Work(ctx, SHIPPED, zones, 2.9, 7.0), sheet)
    assert len(boxes.accessory) == len(envelope_points(fx.barn_doors, fx.optics.lens_offset))
    params["front_pc"]["barn_doors"] = "none"
    assert _boxes(_Work(_make_context(params)[0], SHIPPED, zones, 2.9, 7.0), sheet).accessory == ()
    wide = posed_points(boxes, (0.0, 0.0, 7.0), 40.0, 40.0)
    narrow = posed_points(_Boxes(boxes.base, boxes.pan, boxes.tilt, boxes.pivot), (0.0, 0.0, 7.0), 40.0, 40.0)
    extent = lambda points, i: max(p[i] for p in points) - min(p[i] for p in points)
    assert all(extent(wide, i) >= extent(narrow, i) - 1e-9 for i in range(3))
    assert any(extent(wide, i) > extent(narrow, i) + 0.02 for i in range(3))
    assert len(wide) == len(narrow) + len(boxes.accessory)


def test_a_beam_is_not_blocked_by_what_lies_beyond_its_closed_leaf():
    apex = (0.0, 0.0, 6.0)
    border = {w.name: w for w in _walls(_make_context(make())[0])}["Border_00"]
    open_beam = aimed((0.0, 4.0, 4.89), apex, 80.0)
    assert _wall_gaps([open_beam], [border])[0][2] < BEAM_MARGIN
    closed = _make_beam("B", open_beam.target, apex, open_beam.axis, 80.0, 0.0, cuts=((0.0, 0.6, 0.8),))
    assert _wall_gaps([closed], [border]) == []
    body = _cloud("Other", "FrontPipe", [(0.0, 2.0, 5.5)])
    assert _gaps([open_beam], [body])[0][2] < 0 and _gaps([closed], [body]) == []


def test_unreachable_cuts_raise_a_volets_alert():
    from dataclasses import replace as dc_replace
    from core.fixtures import Library
    fx = SHIPPED.get("generic_pc_led")
    short = dc_replace(fx, barn_doors=dc_replace(fx.barn_doors, leaf_length=0.01, max_angle=5.0))
    library = Library({**SHIPPED.fixtures, fx.id: short}, ())
    rig = compute_layout(make(), library).rig
    assert has(rig.warnings, "Volets : coupe hors course", "FrontPC_")
    assert not has(shipped_rig(make()).warnings, "Volets")
