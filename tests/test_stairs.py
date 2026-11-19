import math

import pytest

from core.layout import compute_layout
from core.meshes import build_mesh
from core.params import validate_params
from helpers import approx_bounds, bounds, layout


def step_vertices(lay, tag):
    return [v for o in lay.objects if o.name.startswith(f"Stairs_Step_{tag}_")
            for v in build_mesh(o).vertices]


def clearance(lay, tag):
    return dict(lay.clearances)[f"Stairs_Clearance_{tag}"]


@pytest.mark.parametrize("setback", [0.0, 1.2])
@pytest.mark.parametrize("angle", [90.0, 45.0, 0.0])
def test_stairs_end_before_the_house_walls_with_the_clearance_free(setback, angle):
    lay = layout(advanced={"proscenium_setback": setback}, stairs={"side_angle": angle})
    wall = lay.derived.total_width / 2
    for tag in ("L", "R"):
        steps = step_vertices(lay, tag)
        area = clearance(lay, tag)
        assert all(abs(x) <= wall + 1e-9 for x, _, _ in steps)
        assert all(abs(x) <= wall + 1e-9 for x, _ in area)
        assert all(y >= -12.0 for _, y in area)
    if angle == 90.0:
        far = max(x for x, _, _ in step_vertices(lay, "R"))
        assert wall - far >= 1.0 - 1e-9


def test_total_width_with_the_default_clearance():
    assert layout(stairs={"side_angle": 0.0}).derived.total_width == pytest.approx(14.0)
    assert layout().derived.total_width == pytest.approx(19.0)
    assert layout(stairs={"clearance": 0.0}).derived.total_width == pytest.approx(17.0)
    assert layout(stairs={"left": False, "right": False}).derived.total_width == pytest.approx(14.0)


def test_landing_in_front_of_the_stage_when_the_offset_is_negative():
    lay = layout(stairs={"side_offset": -2.0})
    (x0, x1), (y0, y1), (z0, z1) = bounds(lay, "Stairs_Landing_R")
    assert (x0, x1) == pytest.approx((3.8, 5.0)) and (y0, y1) == pytest.approx((-1.2, 0.0))
    assert z1 == pytest.approx(1.2)
    base_y0 = min(v[1] for v in build_mesh(lay.find("Stage_Base")).vertices)
    assert y1 <= base_y0 + 1e-9


def test_positive_offset_keeps_the_landing_against_the_facade():
    lay = layout(stairs={"side_offset": 0.5})
    (x0, x1), (y0, y1), _ = bounds(lay, "Stairs_Landing_L")
    assert (x0, x1) == pytest.approx((-7.5, -6.3)) and (y0, y1) == pytest.approx((0.0, 1.2))


def test_minus_90_descends_along_the_stage_front_toward_the_centre():
    lay = layout(advanced={"proscenium_setback": 0.0}, stairs={"side_angle": -90.0,
                                                             "side_offset": -2.0})
    centres = []
    for j in range(1, lay.derived.risers_count):
        xs, ys = zip(*[(v[0], v[1]) for v in build_mesh(lay.find(f"Stairs_Step_R_{j:02d}")).vertices])
        centres.append(sum(xs) / len(xs))
        assert min(ys) >= -1.2 - 1e-9 and max(ys) <= 1e-9
    assert centres == sorted(centres, reverse=True) and centres[0] < 4.4
    area = clearance(lay, "R")
    assert all(-1.2 - 1e-9 <= y <= 1e-9 for _, y in area)
    assert max(x for x, _ in area) < min(x for x, _, _ in step_vertices(lay, "R")) + 1e-9
    assert not any("croisent" in w or "axe" in w for w in lay.warnings)


def test_negative_angle_is_accepted_by_the_schema():
    params, warnings = validate_params({"stairs": {"side_angle": -45.0}})
    assert warnings == [] and params["stairs"]["side_angle"] == -45.0
    assert validate_params({"stairs": {"side_angle": -120.0}})[0]["stairs"]["side_angle"] == -90.0


def test_default_stairs_raise_no_crossing_or_overlap_warning():
    lay = layout(stairs={"center": True})
    assert not any(k in w for w in lay.warnings for k in ("croisent", "axe", "central"))


def test_flights_that_cross_are_reported():
    lay = layout(stairs={"side_angle": -90.0, "side_offset": -5.0})
    assert any("Les escaliers jardin et cour se croisent" in w for w in lay.warnings)
    one = layout(stairs={"side_angle": -90.0, "side_offset": -5.0, "left": False})
    assert any("L'escalier cour dépasse l'axe" in w for w in one.warnings)
    assert not any("croisent" in w for w in one.warnings)


def test_side_flight_overlapping_the_centre_stair_is_reported():
    params = {"side_angle": -90.0, "side_offset": -5.0, "left": False, "center": True}
    assert any("chevauche l'escalier central" in w for w in layout(stairs=params).warnings)
    far = {"side_angle": -90.0, "side_offset": -2.0, "left": False, "center": True}
    assert not any("central" in w for w in layout(stairs=far).warnings)


def test_clearance_beyond_the_drawn_house_is_reported():
    near = {"side_angle": 0.0, "clearance": 3.0}
    assert any("dégagement" in w.lower() for w in
               layout(stairs=near, cameras={"distance": 2.0}).warnings)
    assert not any("dégagement" in w.lower() for w in layout().warnings)


def test_clearance_is_not_drawn():
    assert not [n for n in layout().names() if "Clearance" in n]
    assert len(layout().clearances) == 2
    assert layout(stairs={"clearance": 0.0}).clearances == ()


def arrival_warnings(lay):
    return [w for w in lay.warnings if "n'arrive pas sur le plateau" in w]


def test_default_landing_is_still_the_square_and_the_default_arrives():
    lay = layout()
    assert approx_bounds(bounds(lay, "Stairs_Landing_L"), ((-7.0, -5.8), (0.0, 1.2), (0.0, 1.2)))
    assert not arrival_warnings(lay) and not arrival_warnings(layout(stairs={"side_angle": 0.0}))


def test_no_landing_in_front_of_the_stage_arrives_straight_on_the_stage_front():
    lay = layout(stairs={"side_offset": -2.0, "side_angle": 0.0, "landing_depth": 0.0})
    assert not [n for n in lay.names() if n.startswith("Stairs_Landing")]
    assert lay.derived.risers_count == 6
    assert len([n for n in lay.names() if n.startswith("Stairs_Step_R_")]) == 5
    (x0, x1), (y0, y1), (z0, z1) = bounds(lay, "Stairs_Step_R_01")
    assert (x0, x1) == pytest.approx((3.8, 5.0)) and (y0, y1) == pytest.approx((-0.3, 0.0))
    assert z1 == pytest.approx(1.0)
    assert not arrival_warnings(lay)


def test_arrival_is_checked_for_a_flight_that_does_not_reach_the_stage():
    lay = layout(advanced={"proscenium_setback": 0.0},
                 stairs={"side_offset": 0.0, "side_angle": 0.0, "landing_depth": 0.0})
    assert len(arrival_warnings(lay)) == 2
    assert "ajouter un palier ou le décaler devant la scène" in arrival_warnings(lay)[0]
    shallow = layout(stairs={"side_angle": 0.0, "landing_depth": 0.5})
    assert len(arrival_warnings(shallow)) == 2


def test_no_landing_at_90_degrees_starts_at_the_stage_edge_and_arrives_on_the_flank():
    lay = layout(stairs={"side_angle": 90.0, "landing_depth": 0.0})
    assert "Stairs_Landing_R" not in lay.names()
    (x0, x1), (y0, y1), _ = bounds(lay, "Stairs_Step_R_01")
    assert (x0, x1) == pytest.approx((5.8, 6.1)) and (y0, y1) == pytest.approx((0.0, 1.2))
    assert not arrival_warnings(lay)


def test_landing_depth_sets_the_landing_along_the_flight_direction():
    front = layout(stairs={"side_angle": 0.0, "landing_depth": 0.5})
    assert approx_bounds(bounds(front, "Stairs_Landing_R"), ((5.8, 7.0), (0.7, 1.2), (0.0, 1.2)))
    side = layout(stairs={"landing_depth": 0.5})
    assert approx_bounds(bounds(side, "Stairs_Landing_R"), ((5.8, 6.3), (0.0, 1.2), (0.0, 1.2)))
    deep = layout(stairs={"landing_depth": 2.0, "side_angle": 0.0})
    assert bounds(deep, "Stairs_Landing_R")[1] == pytest.approx((-0.8, 1.2))


def test_no_landing_shrinks_the_side_zone_and_flight_start_follows_the_angle_sign():
    assert layout(stairs={"landing_depth": 0.0}).derived.total_width < layout().derived.total_width
    inward = layout(stairs={"side_angle": -90.0, "side_offset": -2.0})
    outward = layout(stairs={"side_angle": 90.0, "side_offset": -2.0})
    assert min(v[0] for v in step_vertices(inward, "R")) < min(v[0] for v in step_vertices(outward, "R"))
