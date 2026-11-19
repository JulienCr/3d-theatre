import math

import pytest

from core.layout import compute_layout
from core.meshes import build_mesh
from core.sightlines import computed_bottoms, ray_height, visible_points, wing_reach
from helpers import layout, make, modules_off

EYE = (-2.0, 1.1)


def no_modules(**groups):
    return compute_layout(modules_off(make(**groups)))


def bottoms(lay):
    return dict(lay.derived.border_bottoms)


# ----------------------------------------------------------- section, by hand

def test_one_border_one_batten_hand_computed_bottom():
    screens = [("Linteau", 1.25, 6.2), ("B", 4.0, None)]
    out = computed_bottoms(EYE, screens, [(5.0, 6.8)], grid_z=7.3, y_end=6.6)
    by_batten = 1.1 + (6.8 - 1.1) * (4.0 + 2.0) / (5.0 + 2.0)
    by_grid = 1.1 + (7.3 - 1.1) * (4.0 + 2.0) / (6.6 + 2.0)
    assert by_grid < by_batten
    assert out == {"B": pytest.approx(by_grid)}
    assert ray_height(EYE, 4.0, (5.0, 6.8)) == pytest.approx(by_batten)


def test_a_batten_between_two_screens_belongs_to_the_nearer_one():
    screens = [("A", 3.0, None), ("B", 5.0, None)]
    out = computed_bottoms(EYE, screens, [(4.0, 6.0), (5.5, 6.0)], grid_z=7.3, y_end=7.0)
    assert out["A"] == pytest.approx(min(ray_height(EYE, 3.0, (4.0, 6.0)),
                                         ray_height(EYE, 3.0, (5.0, 7.3))))
    assert out["B"] == pytest.approx(min(ray_height(EYE, 5.0, (5.5, 6.0)),
                                         ray_height(EYE, 5.0, (7.0, 7.3))))


def test_visibility_follows_the_screen_bottoms():
    points = [("P", 5.0, 6.8)]
    reach = ray_height(EYE, 4.0, (5.0, 6.8))
    assert visible_points(EYE, [("S", 4.0, reach - 0.01)], points) == []
    assert visible_points(EYE, [("S", 4.0, reach + 0.01)], points) == ["P"]


def test_default_borders_are_computed_and_exposed():
    lay = layout()
    assert [n for n, _ in lay.derived.border_bottoms] == [
        "Border_00", "Border_01", "Border_02", "Border_03"]
    for name, height in lay.derived.border_bottoms:
        assert lay.find(name).z0 == pytest.approx(1.2 + height)
        assert height < 5.6


def test_an_unchecked_border_hands_its_zone_to_the_previous_one():
    full = bottoms(layout())
    gap = bottoms(layout(masking={"borders": (True, True, False) + (True,) * 5}))
    assert "Border_03" not in gap
    assert gap["Border_02"] < full["Border_02"]
    assert gap["Border_01"] == pytest.approx(full["Border_01"])


def test_manual_mode_only_checks_and_warns_when_a_border_is_raised():
    low = layout(masking={"borders_mode": "manual", "border_bottom": 3.5})
    high = layout(masking={"borders_mode": "manual", "border_bottom": 5.5})

    def seen(lay):
        return {w for w in lay.warnings if w.startswith("Découverte verticale")}

    assert seen(high) > seen(low)
    assert all("depuis le premier rang" in w for w in seen(high))
    assert low.find("Border_01").z0 == pytest.approx(1.2 + 3.5)
    assert not [w for w in low.warnings if "très basse" in w]


def test_very_low_computed_borders_are_reported():
    lay = layout(sightlines={"eye_height": 3.0, "seat_distance": 0.5})
    low = [h for _, h in lay.derived.border_bottoms if h < 2.2]
    assert bool(low) == any("très basse" in w for w in lay.warnings)


# ------------------------------------------------------------------- plan view

def test_visible_wing_reach_matches_the_grazing_line_by_hand():
    front, line = wing_reach(-9.0, -2.0, [(4.0, 4.25)], 5.0)
    assert front == 4.0
    assert line == pytest.approx(-9.0 + (5.0 + 2.0) * (4.0 + 9.0) / (4.25 + 2.0))


def test_visible_depth_grows_with_convergence_and_is_reported_per_lane():
    plain = layout(masking={"lanes": 4}).derived.visible_depths
    wide = layout(masking={"lanes": 4, "convergence": 10.0}).derived.visible_depths
    assert [row[0] for row in plain] == [0, 1, 2, 3, 4]
    assert wide[0] == pytest.approx(plain[0]) and wide[1] == pytest.approx(plain[1])
    assert all(w[1] > p[1] for w, p in zip(wide[2:], plain[2:]))


def test_wall_visible_alert_appears_without_modules_and_not_with_them():
    assert any("le mur de cage se voit" in w for w in no_modules().warnings)
    assert not any("le mur de cage se voit" in w for w in layout().warnings)


# ---------------------------------------------------------------------- legs

ALPHAS = (0.0, 10.0, 20.0)
CONVERGENCES = (0.0, 10.0)


@pytest.mark.parametrize("alpha", ALPHAS)
@pytest.mark.parametrize("convergence", CONVERGENCES)
def test_legs_reach_the_cage_wall_and_never_cross_it(alpha, convergence):
    lay = layout(masking={"leg_angle": alpha, "convergence": convergence, "drape": 1.0})
    wall = lay.derived.cage_width / 2
    for tag in "LR":
        for k in (1, 2, 3):
            xs = [abs(v[0]) for v in build_mesh(lay.find(f"Leg_{tag}_{k:02d}")).vertices]
            assert max(xs) == pytest.approx(wall, abs=1e-3) and max(xs) <= wall + 1e-9


def test_the_inner_edge_pivot_does_not_move_with_the_angle():
    base = layout()
    for alpha in (10.0, 20.0):
        lay = layout(masking={"leg_angle": alpha})
        for k in (1, 2, 3):
            for tag in "LR":
                name = f"Leg_{tag}_{k:02d}"
                assert lay.find(name).state.p0 == pytest.approx(base.find(name).state.p0)
    leg = layout(masking={"leg_angle": 20.0}).find("Leg_R_01")
    assert leg.state.p1[1] < leg.state.p0[1]
    assert leg.state.p1[0] == pytest.approx(7.0)


def test_convergence_widens_the_inner_edges_upstage_from_the_nominal_opening():
    flat = layout()
    lay = layout(masking={"convergence": 10.0})
    xs = [lay.find(f"Leg_R_{k:02d}").state.p0[0] for k in (1, 2, 3)]
    ys = [lay.find(f"Leg_R_{k:02d}").state.p0[1] for k in (1, 2, 3)]
    assert xs[0] == pytest.approx(4.0) and xs[0] < xs[1] < xs[2]
    assert xs[2] == pytest.approx(4.0 + (ys[2] - ys[0]) * math.tan(math.radians(10.0)))
    assert [flat.find(f"Leg_R_{k:02d}").state.p0[0] for k in (1, 2, 3)] == pytest.approx([4.0] * 3)


def test_leg_pipes_exist_only_for_slanted_legs_and_follow_the_leg_top():
    assert not [n for n in layout().names() if n.startswith("LegPipe")]
    lay = layout(masking={"leg_angle": 15.0})
    pipe, leg = lay.find("LegPipe_R_02"), lay.find("Leg_R_02")
    assert pipe.material == "TS_Batten" and pipe.start[2] == pytest.approx(6.8)
    assert pipe.start[:2] == pytest.approx(leg.state.p0)
    assert "MaskingBatten_02" in lay.names()
    german = layout(masking={"style": "german", "leg_angle": 15.0})
    assert not [n for n in german.names() if n.startswith("LegPipe")]


def test_a_too_slanted_leg_in_a_short_first_lane_is_reported():
    assert not any("trop incliné" in w for w in no_modules().warnings)
    lay = no_modules(masking={"leg_angle": 20.0})
    assert any("Pendrillon cour 01 : trop incliné pour la rue." in w for w in lay.warnings)
    assert not any("trop incliné" in w for w in layout(masking={"leg_angle": 5.0}).warnings)
