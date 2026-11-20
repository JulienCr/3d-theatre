"""Barn doors (spec 12.2 `barn_doors`, 13.12): fiche rules and leaf maths."""

import copy
import math
from pathlib import Path

import pytest
import yaml

from core import fixtures as F
from core.barndoors import Leaf, auto_set, beyond, cut_normal, envelope_points, manual_set
from core.fixtures import BarnDoors, Range

SHEET = Path(__file__).parent / "data" / "rig" / "rig_pc"
DOORS = BarnDoors(4, 0.15, 0.20, 0.10, 0.0, (0.0, 90.0, 180.0, 270.0), 80.0, Range(-90.0, 90.0))
FRAME = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
LENS_OFFSET = 0.30
ORIGIN = (0.0, 0.0, 0.0)


def raw(**doors):
    data = copy.deepcopy(yaml.safe_load((SHEET / "fixture.yaml").read_text(encoding="utf-8")))
    data["barn_doors"] = {"leaf_length": 0.12, "leaf_width": 0.2, **doors}
    return data


def errors_of(data):
    result = F.validate_fixture(data, SHEET)
    assert isinstance(result, list), "the sheet should be invalid"
    return "\n".join(result)


def dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def tip_of(doors, leaf, lens=ORIGIN, frame=FRAME):
    """World tip centre of a leaf: hinge centre plus `length` along the leaf z axis (head frame)."""
    head = tuple(h + doors.leaf_length * z for h, z in zip(leaf.hinge, leaf.axes[2]))
    return tuple(lens[i] + sum(head[k] * frame[k][i] for k in range(3)) - LENS_OFFSET * frame[2][i]
                 for i in range(3))


# ------------------------------------------------------------------ fiche

def test_shipped_pc_fiches_carry_their_barn_doors():
    library = F.discover([F.SHIPPED_DIR])
    robe, chauvet = library.get("generic_pc_led").barn_doors, library.get("generic_fresnel_led").barn_doors
    assert (robe.count, robe.hinge_radius, robe.sides) == (4, 0.10, (0.0, 90.0, 180.0, 270.0))
    assert chauvet.hinge_radius == pytest.approx(0.095) and chauvet.max_angle == 80.0
    assert all(library.get(i).barn_doors is None for i in ("etc_s4led_s3_lustr_x8", "robe_robin_esprite"))


def test_defaults_of_a_minimal_barn_door_section():
    doors = F.validate_fixture(raw(), SHEET).barn_doors
    assert doors.count == 4 and doors.hinge_radius == 0.10 and doors.hinge_offset == 0.0
    assert doors.sides == F.DEFAULT_LEAF_SIDES and doors.max_angle == F.DEFAULT_LEAF_MAX_ANGLE
    assert doors.rotation == Range(0.0, 0.0)


def test_hinge_ring_replaces_the_lens_rim():
    assert F.validate_fixture(raw(hinge_diameter=0.26, hinge_offset=0.01), SHEET).barn_doors.hinge_radius == 0.13


@pytest.mark.parametrize("doors, expected", [
    ({"leaf_length": None}, "leaf_length"),
    ({"leaf_width": 0}, "leaf_width"),
    ({"count": 8}, "count"),
    ({"hinge_diameter": 0.15}, "diamètre de la lentille"),
    ({"leaf_length": 0.2}, "rogneraient le champ"),
    ({"sides": [0, 90, 180]}, "quatre"),
    ({"sides": [0, 90, 180, 360]}, "distincts"),
    ({"max_angle": 120}, "max_angle"),
    ({"rotation": {"min": 30, "max": -30}}, "rotation"),
    ({"rotation": {"min": -90, "max": 200}}, "180"),
    ({"hinge_offset": -0.01}, "hinge_offset"),
])
def test_each_barn_door_rule_rejects_a_broken_section(doors, expected):
    assert expected in errors_of(raw(**doors))


def test_barn_doors_are_reserved_to_the_pc_family():
    data = raw()
    data["family"] = "profile"
    assert "réservé à la famille pc" in errors_of(data)


# ------------------------------------------------------------------ leaf maths

def plane_line(angle, direction=(0.0, 1.0, 0.0)):
    """Target line `angle` degrees off the +Z beam on the +X side, one metre ahead."""
    return ((math.tan(math.radians(angle)), 0.0, 1.0), direction)


def set_for(line, field=90.0, doors=DOORS, name="left"):
    result, dropped = auto_set(doors, LENS_OFFSET, FRAME, ORIGIN, field, {name: line})
    return result, dropped


def test_a_cut_plane_through_the_lens_centre_turns_the_dark_side_away_from_the_axis():
    n = cut_normal(ORIGIN, plane_line(30), (0.0, 0.0, 1.0))
    assert n is not None and dot(n, (0.0, 0.0, 1.0)) < 0 and n[0] > 0
    assert dot(n, plane_line(30)[0]) == pytest.approx(0.0)
    assert cut_normal((0.0, 0.0, 1.0), ((0.0, 0.0, 1.0), (0.0, 1.0, 0.0)), (0.0, 0.0, 1.0)) is None


def test_the_leaf_facing_the_cut_closes_until_its_tip_is_on_the_plane():
    result, dropped = set_for(plane_line(30))
    leaf = next(leaf for leaf in result.leaves if leaf.cut == "left")
    assert dropped == () and leaf.reached and leaf.active and result.rotation == pytest.approx(0.0)
    assert leaf.side == pytest.approx(0.0) and 0 < leaf.angle < DOORS.max_angle
    n = cut_normal(ORIGIN, plane_line(30), (0.0, 0.0, 1.0))
    assert abs(dot(n, tip_of(DOORS, leaf))) < 1e-9
    assert leaf.normal == pytest.approx(n, abs=1e-9)
    assert [other.angle for other in result.leaves if other is not leaf] == [0.0] * 3


def test_leaf_axes_are_orthonormal_with_z_from_hinge_to_tip():
    leaf = next(leaf for leaf in set_for(plane_line(30))[0].leaves if leaf.cut)
    x, y, z = leaf.axes
    assert all(dot(a, a) == pytest.approx(1.0) for a in (x, y, z))
    assert dot(x, y) == pytest.approx(0.0) and dot(y, z) == pytest.approx(0.0) and dot(x, z) == pytest.approx(0.0)
    theta = math.radians(leaf.angle)
    assert z == pytest.approx((-math.sin(theta), 0.0, math.cos(theta)))
    assert leaf.hinge == pytest.approx((DOORS.hinge_radius, 0.0, LENS_OFFSET))


def test_the_whole_set_turns_to_square_the_leaf_edge_on_a_skew_line():
    skew = (math.cos(math.radians(20)), math.sin(math.radians(20)), 0.0)
    result, _ = set_for(plane_line(30, skew))
    leaf = next(leaf for leaf in result.leaves if leaf.cut)
    n = cut_normal(ORIGIN, plane_line(30, skew), (0.0, 0.0, 1.0))
    assert abs(result.rotation) > 15 and leaf.normal == pytest.approx(n, abs=1e-3)


def test_rotation_stays_within_the_fiche_range():
    skew = (math.cos(math.radians(20)), math.sin(math.radians(20)), 0.0)
    fixed = BarnDoors(4, 0.15, 0.20, 0.10, 0.0, DOORS.sides, 80.0, Range(0.0, 0.0))
    result, _ = set_for(plane_line(30, skew), doors=fixed)
    leaf = next(leaf for leaf in result.leaves if leaf.cut)
    assert result.rotation == 0.0 and leaf.reached
    assert leaf.normal != pytest.approx(cut_normal(ORIGIN, plane_line(30, skew), (0.0, 0.0, 1.0)), abs=1e-3)


def test_a_cut_outside_the_field_leaves_every_leaf_open():
    result, dropped = set_for(plane_line(50), field=30.0)
    assert dropped == () and not any(leaf.active or leaf.cut for leaf in result.leaves)
    assert result.normals == ()


def test_the_angle_is_clamped_and_flagged_when_the_limit_stops_the_leaf():
    stiff = BarnDoors(4, 0.15, 0.20, 0.10, 0.0, DOORS.sides, 2.0, Range(-90.0, 90.0))
    leaf = next(leaf for leaf in set_for(plane_line(30), doors=stiff)[0].leaves if leaf.cut)
    assert leaf.angle == 2.0 and not leaf.reached


def test_a_leaf_too_short_to_reach_the_plane_is_flagged():
    short = BarnDoors(4, 0.05, 0.20, 0.10, 0.0, DOORS.sides, 80.0, Range(-90.0, 90.0))
    leaf = next(leaf for leaf in set_for(plane_line(30), doors=short)[0].leaves if leaf.cut)
    assert not leaf.reached and leaf.angle <= 80.0


def test_two_cuts_never_share_a_leaf_and_the_least_restrictive_is_dropped_when_none_is_left():
    lines = {"left": plane_line(25), "right": ((-math.tan(math.radians(30)), 0.0, 1.0), (0.0, 1.0, 0.0))}
    result, dropped = auto_set(DOORS, LENS_OFFSET, FRAME, ORIGIN, 80.0, lines)
    assert dropped == () and sorted(leaf.cut for leaf in result.leaves if leaf.cut) == ["left", "right"]
    one = BarnDoors(4, 0.15, 0.20, 0.10, 0.0, (0.0, 10.0, 20.0, 30.0), 80.0, Range(0.0, 0.0))
    _, dropped = auto_set(one, LENS_OFFSET, FRAME, ORIGIN, 80.0, lines)
    assert dropped == ("right",)


def test_a_point_beyond_a_closed_leaf_plane_is_not_lit_but_the_axis_is():
    result, _ = set_for(plane_line(30))
    assert beyond(result.normals, ORIGIN, (3.0, 0.0, 1.0))
    assert not beyond(result.normals, ORIGIN, (0.0, 0.0, 1.0)) and not beyond((), ORIGIN, (9.0, 0.0, 1.0))


def test_manual_leaves_are_clamped_to_the_limit_and_the_rotation_to_the_range():
    result = manual_set(DOORS, LENS_OFFSET, FRAME, [10.0, 95.0, -5.0, 0.0], 130.0)
    assert [leaf.angle for leaf in result.leaves] == [10.0, 80.0, 0.0, 0.0] and result.rotation == 90.0
    assert [leaf.active for leaf in result.leaves] == [True, True, False, False]
    assert all(leaf.normal is not None for leaf in result.leaves if leaf.active)
    assert [leaf.side for leaf in result.leaves] == [90.0, 180.0, 270.0, 360.0]


def test_envelope_points_bound_the_leaves_at_any_rotation():
    points = envelope_points(DOORS, LENS_OFFSET)
    reach = math.hypot(DOORS.hinge_radius, DOORS.leaf_width / 2)
    assert {round(p[2], 6) for p in points} == {round(LENS_OFFSET, 6), round(LENS_OFFSET + DOORS.leaf_length, 6)}
    assert max(math.hypot(p[0], p[1]) for p in points) == pytest.approx(reach)
    assert isinstance(manual_set(DOORS, LENS_OFFSET, FRAME, [0] * 4, 0.0).leaves[0], Leaf)
