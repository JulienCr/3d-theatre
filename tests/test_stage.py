import math

import pytest

from core.layout import compute_layout
from core.meshes import build_mesh
from helpers import approx_bounds, bounds, layout, make, modules_off


def test_risers_for_the_default_and_just_above_a_multiple():
    assert layout().derived.risers_count == 6
    assert layout().derived.riser_height == pytest.approx(0.20)
    d = layout(advanced={"stage_height": 1.25}).derived
    assert d.risers_count == 7 and d.riser_height == pytest.approx(1.25 / 7)


def test_step_count_and_tops_follow_the_risers():
    lay = layout()
    steps = [n for n in lay.names() if n.startswith("Stairs_Step_L_")]
    assert len(steps) == 5
    for j in range(1, 6):
        assert bounds(lay, f"Stairs_Step_L_{j:02d}")[2][1] == pytest.approx((6 - j) * 0.2)


def test_total_width_depends_on_the_side_angle():
    assert layout(stairs={"side_angle": 0.0}).derived.total_width == pytest.approx(14.0)
    assert layout(stairs={"side_angle": 90.0}).derived.total_width == pytest.approx(17.0)
    assert layout().derived.frame_opening == pytest.approx(10.0)
    assert layout().derived.cage_width == pytest.approx(14.0)
    assert layout(stage={"wings": 0.5}).derived.cage_width == pytest.approx(11.0)


def test_enclosure_stays_symmetric_with_a_single_side_stair():
    lay = layout(stairs={"right": False})
    assert "Stairs_Landing_R" not in lay.names()
    wl, wr = bounds(lay, "House_Wall_L"), bounds(lay, "House_Wall_R")
    assert wl[0][1] == pytest.approx(-lay.derived.total_width / 2)
    assert wr[0][0] == pytest.approx(lay.derived.total_width / 2)
    fx = bounds(lay, "Facade")[0]
    assert fx[0] == pytest.approx(-fx[1])
    assert lay.derived.total_width == pytest.approx(17.0)


def test_side_zone_widens_with_a_warning_only_when_stairs_need_it():
    lay = layout(stairs={"side_angle": 0.0, "width": 2.0})
    assert lay.derived.side_zone == pytest.approx(2.0)
    assert any("Zone latérale élargie" in w and "2,00 m" in w and w.endswith(".")
               for w in lay.warnings)
    quiet = layout(stairs={"side_angle": 0.0})
    assert not any("Zone latérale" in w for w in quiet.warnings)
    wide = layout(stairs={"side_angle": 0.0}, advanced={"side_zone_width": 3.0})
    assert wide.derived.side_zone == pytest.approx(3.0) and not wide.warnings


def test_no_lateral_stairs_means_the_footprint_does_not_count():
    lay = layout(stairs={"left": False, "right": False}, advanced={"side_zone_width": 1.0})
    assert lay.derived.total_width == pytest.approx(11.6 + 2.0)
    assert not any("Zone latérale" in w for w in lay.warnings)


def test_stair_steps_run_toward_the_house_at_0_and_the_wall_at_90():
    lay0 = layout(stairs={"side_angle": 0.0})
    b = bounds(lay0, "Stairs_Step_R_01")
    assert approx_bounds(b, ((5.8, 7.0), (-0.3, 0.0), (0.0, 1.0)))
    lay90 = layout(stairs={"side_angle": 90.0})
    b = bounds(lay90, "Stairs_Step_R_01")
    assert approx_bounds(b, ((7.0, 7.3), (0.0, 1.2), (0.0, 1.0)))
    mirrored = bounds(lay90, "Stairs_Step_L_01")
    assert approx_bounds(mirrored, ((-7.3, -7.0), (0.0, 1.2), (0.0, 1.0)))


def test_intermediate_angle_first_step_overlaps_the_landing():
    lay = layout(stairs={"side_angle": 45.0})
    landing = bounds(lay, "Stairs_Landing_R")
    step = bounds(lay, "Stairs_Step_R_01")
    overlap_x = min(landing[0][1], step[0][1]) - max(landing[0][0], step[0][0])
    overlap_y = min(landing[1][1], step[1][1]) - max(landing[1][0], step[1][0])
    assert overlap_x > 0 and overlap_y > 0


def test_central_stair_and_its_overhang_warning():
    lay = layout(stairs={"center": True})
    assert approx_bounds(bounds(lay, "Stairs_Step_C_02"), ((-1.0, 1.0), (-0.6, -0.3), (0.0, 0.8)))
    assert not any("central" in w for w in lay.warnings)
    far = layout(stairs={"center": True, "going": 0.45}, advanced={"apron_depth": 0.5})
    assert any("central" in w for w in far.warnings)


def test_lateral_stair_overhanging_the_apron_is_reported():
    lay = layout(stairs={"side_angle": 0.0}, advanced={"apron_depth": 0.5})
    assert any("escalier jardin" in w and "avant-scène" in w for w in lay.warnings)
    assert not any("avant-scène" in w for w in layout().warnings)


def test_stage_floor_and_base_stack_to_the_stage_height():
    lay = layout()
    assert bounds(lay, "Stage_Floor")[2] == pytest.approx((1.17, 1.2))
    assert bounds(lay, "Stage_Base")[2] == pytest.approx((0.0, 1.17))
    base = bounds(lay, "Stage_Base")
    assert base[0] == pytest.approx((-7.0, 7.0)) and base[1] == pytest.approx((0.0, 7.0))
    assert bounds(layout(stage={"wings": 0.0}), "Stage_Base")[0] == pytest.approx((-5.8, 5.8))


def test_proscenium_and_facade_dimensions():
    lay = layout()
    assert approx_bounds(bounds(lay, "Proscenium_Post_L"), ((-5.8, -5.0), (1.25, 1.6), (1.2, 6.2)))
    assert approx_bounds(bounds(lay, "Proscenium_Lintel"), ((-5.8, 5.8), (1.25, 1.6), (6.2, 7.0)))
    assert approx_bounds(bounds(lay, "Facade"), ((-8.5, 8.5), (1.2, 1.5), (0.0, 7.3)))


def test_facade_without_side_zone_is_a_plain_lintel_band():
    lay = layout(stairs={"left": False, "right": False}, advanced={"side_zone_width": 0.0})
    assert approx_bounds(bounds(lay, "Facade"), ((-5.8, 5.8), (1.2, 1.5), (7.0, 7.3)))


def test_proscenium_too_tall_warns_for_both_conditions():
    assert any("Cadre trop haut" in w for w in layout(advanced={"facade_height": 6.5}).warnings)
    assert any("Cadre trop haut" in w for w in layout(stage={"grid_height": 5.0}).warnings)
    assert not any("Cadre" in w for w in layout().warnings)


def test_too_wide_posts_are_limited():
    lay = layout(stage={"width": 4.0}, advanced={"proscenium_thickness": 3.0})
    assert lay.derived.cage_width >= 1.0 - 1e-9
    assert any("Montants" in w for w in lay.warnings)


def test_work_light_grid_counts_and_cells():
    lay = layout(stage={"wings": 0.0})
    assert len(lay.lights) == 7
    lights = [light for light in lay.lights if light.name != "WorkLight_Front"]
    assert len(lights) == 3 * 2
    xs = sorted({round(light.location[0], 6) for light in lights})
    assert xs == pytest.approx([-10 / 3, 0.0, 10 / 3])
    assert all(light.location[2] == pytest.approx(1.2 + 6.1 - 0.3) for light in lights)
    assert all(light.size == pytest.approx(min(10 / 3, 5.4 / 2) / 2) for light in lights)
    assert all(light.color_temperature == 4000 for light in lights)


def test_light_grid_rounds_half_up_and_keeps_at_least_one_cell():
    lights = [l for l in layout(lights={"spacing": 4.0}).lights if l.name != "WorkLight_Front"]
    assert len({l.location[0] for l in lights}) == 4
    wide = layout(stage={"wings": 0.0}, lights={"spacing": 4.0}).lights
    assert len({l.location[0] for l in wide if l.name != "WorkLight_Front"}) == 3
    big = [l for l in layout(lights={"spacing": 10.0}).lights if l.name != "WorkLight_Front"]
    assert len(big) == 1


def test_light_switches_and_intensity():
    assert layout(lights={"enabled": False}).lights == ()
    names = [l.name for l in layout(lights={"front": False}).lights]
    assert "WorkLight_Front" not in names and len(names) == 5 * 2
    base = layout().find("WorkLight_01").energy
    assert layout(lights={"intensity": 2.0}).find("WorkLight_01").energy == pytest.approx(2 * base)


def test_front_light_position_and_target():
    front = layout().find("WorkLight_Front")
    assert front.location == pytest.approx((0.0, -5.1, 6.2))
    assert front.target == pytest.approx((0.0, 1.6 + 5.4 / 3, 2.2))


def test_cameras():
    lay = layout()
    face, jardin, cour = (lay.find(n) for n in ("Cam_Face", "Cam_Jardin", "Cam_Cour"))
    assert face.location == (0.0, -11.0, 3.0)
    assert jardin.location[0] == pytest.approx(-0.75 * 5.8) and cour.location[0] == pytest.approx(4.35)
    assert face.target == pytest.approx((0.0, 3.5, 2.2)) and face.lens == 22.0


def test_house_reaches_behind_the_cameras():
    lay = layout()
    assert bounds(lay, "House_Floor")[1][0] == pytest.approx(-12.0)
    assert bounds(lay, "House_Wall_L")[1][0] == pytest.approx(-12.0)
    near = layout(cameras={"distance": 2.0})
    assert bounds(near, "House_Floor")[1][0] == pytest.approx(-3.1)
    assert bounds(layout(cameras={"lens": 50.0}), "House_Floor")[1][0] == pytest.approx(-12.0)
    assert layout(cameras={"lens": 50.0}).find("Cam_Face").lens == 50.0


def test_light_battens_exist_and_are_numbered_without_gaps():
    lay = layout()
    ys = []
    for i in range(1, lay.derived.batten_count + 1):
        tube = lay.find(f"Batten_{i:02d}")
        ys.append(tube.start[1])
        assert tube.start[0] == pytest.approx(-6.9) and tube.end[0] == pytest.approx(6.9)
        assert tube.start[2] == pytest.approx(1.2 + 6.1 - 0.5) and tube.radius == pytest.approx(0.024)
    assert ys == pytest.approx([2.1, 3.1])
    assert "Batten_03" not in lay.names()


def test_light_battens_without_any_neighbour_follow_spacing_and_back_margin():
    params = make(masking={"backdrop": "bare_wall", "front_border": False, "lanes": 1},
                  curtains={"main_enabled": False})
    lay = compute_layout(modules_off(params))
    ys = [lay.find(f"Batten_{i:02d}").start[1] for i in range(1, lay.derived.batten_count + 1)]
    assert ys == pytest.approx([2.1, 3.1, 4.1, 5.1, 6.1])


def test_batten_requires_cage_depth():
    lay = layout(stage={"depth": 3.0}, advanced={"proscenium_setback": 2.5})
    assert lay.derived.batten_count == 0
    assert any("porteuse" in w for w in lay.warnings)


def test_grid_deck_slats_cover_the_cage():
    deck = layout().find("Grid_Deck")
    assert deck.z_min == pytest.approx(7.3)
    assert deck.x_centers[0] == pytest.approx(-7.0 + 0.025)
    assert deck.x_centers[-1] + 0.025 <= 7.0 + 1e-9
    assert all(b - a == pytest.approx(0.15) for a, b in zip(deck.x_centers, deck.x_centers[1:]))


def test_derived_values_match_the_objects():
    lay = layout()
    assert lay.derived.cage_front_y == pytest.approx(1.6)
    assert lay.find("Cage_Back").min[1] == pytest.approx(7.0)
    assert math.isclose(lay.find("Cage_Roof").min[2], 1.2 + 6.1 + 2.0)


def test_object_names_are_unique_and_collections_declared():
    lay = layout(stairs={"center": True}, curtains={"main_enabled": True})
    names = lay.names()
    assert len(names) == len(set(names))
    for obj in lay.objects + lay.lights + lay.cameras:
        assert obj.collection in lay.collections
        if hasattr(obj, "material"):
            assert obj.material in lay.materials
    assert lay.root_collection == "Theatre"


def test_wings_widen_the_cage_and_every_cage_part_follows():
    lay = layout()
    wk = 14.0
    assert approx_bounds(bounds(lay, "Cage_Wall_L"), ((-7.2, -7.0), (1.6, 7.0), (1.2, 9.3)))
    assert approx_bounds(bounds(lay, "Cage_Wall_R"), ((7.0, 7.2), (1.6, 7.0), (1.2, 9.3)))
    assert bounds(lay, "Cage_Back")[0] == pytest.approx((-wk / 2, wk / 2))
    assert bounds(lay, "Cage_Roof")[0] == pytest.approx((-7.2, 7.2))
    assert bounds(lay, "Stage_Floor")[0] == pytest.approx((-7.0, 7.0))
    deck = lay.find("Grid_Deck")
    assert deck.x_centers[0] - 0.025 == pytest.approx(-7.0)
    assert all(abs(light.location[0]) < 7.0 for light in lay.lights)
    assert lay.find("MaskingBatten_01").end[0] == pytest.approx(6.9)


def test_cage_front_closes_the_wings_only_when_they_stick_out_of_the_frame():
    lay = layout()
    assert approx_bounds(bounds(lay, "Cage_Front_L"), ((-7.2, -5.8), (1.5, 1.6), (1.2, 9.3)))
    assert approx_bounds(bounds(lay, "Cage_Front_R"), ((5.8, 7.2), (1.5, 1.6), (1.2, 9.3)))
    for wings in (0.0, 0.8):
        assert "Cage_Front_L" not in layout(stage={"wings": wings}).names()


def test_ceiling_is_a_single_face_pointing_down_over_the_house():
    lay = layout()
    ceiling = lay.find("House_Ceiling")
    assert ceiling.material == "TS_HouseCeiling"
    mesh = build_mesh(ceiling)
    assert len(mesh.faces) == 1
    assert approx_bounds(bounds(lay, "House_Ceiling"), ((-8.5, 8.5), (-12.0, 1.2), (7.3, 7.3)))
    pts = [mesh.vertices[i] for i in mesh.faces[0]]
    nz = sum((a[0] - b[0]) * (a[1] + b[1]) for a, b in zip(pts, pts[1:] + pts[:1]))
    assert nz < 0
    assert "TS_HouseCeiling" in lay.materials
    assert "House_Ceiling" not in layout(house={"ceiling": False}).names()


def test_wings_do_not_move_the_modules_but_frame_gap_does():
    inner = bounds(layout(stage={"wings": 0.0}), "Module_L_Front")
    assert approx_bounds(bounds(layout(stage={"wings": 5.0}), "Module_L_Front"), inner)
    params = make()
    params["modules"]["left"]["frame_gap"] = -1.0
    moved = bounds(compute_layout(params), "Module_L_Front")
    assert moved[0][0] == pytest.approx(inner[0][0] - 1.0)
