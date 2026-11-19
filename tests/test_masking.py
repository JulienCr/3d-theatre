import pytest

from core.layout import compute_layout
from core.meshes import build_mesh, pleated_mesh
from helpers import layout, make, modules_off

ZB = 1.2 + 6.1 - 0.5


def no_modules(**groups):
    params = make(**groups)
    return compute_layout(modules_off(params))


def plane_y(lay, name):
    tube = lay.find(name)
    return tube.start[1]


def test_planes_start_behind_the_modules_when_present():
    lay = layout()
    assert lay.derived.masking_y0 == pytest.approx(4.05 + 0.20)
    assert lay.derived.masking_y1 == pytest.approx(7.0 - 0.40 - 0.30)
    step = (6.3 - 4.25) / 3
    ys = [plane_y(lay, f"MaskingBatten_{k:02d}") for k in (1, 2, 3)]
    assert ys == pytest.approx([4.25 + step, 4.25 + 2 * step, 6.3])


def test_planes_start_behind_the_proscenium_without_modules():
    lay = no_modules()
    assert lay.derived.masking_y0 == pytest.approx(2.1)
    ys = [plane_y(lay, f"MaskingBatten_{k:02d}") for k in (1, 2, 3)]
    assert ys == pytest.approx([2.1 + 1.4, 2.1 + 2.8, 6.3])


def test_shallow_modules_do_not_push_the_planes_back():
    params = make()
    params["modules"]["left"].update(setback=0.5, depth=0.5)
    assert compute_layout(params).derived.masking_y0 == pytest.approx(2.1)


def test_a_single_present_module_is_enough_to_push_the_planes():
    params = make()
    params["modules"]["symmetric"] = False
    params["modules"]["left"]["enabled"] = False
    assert compute_layout(params).derived.masking_y0 == pytest.approx(4.25)


def test_backdrop_line_depends_on_the_backdrop():
    for backdrop, yb in (("bare_wall", 7.0), ("black_curtain", 6.6), ("cyclorama", 5.8)):
        lay = layout(masking={"backdrop": backdrop})
        assert lay.derived.backdrop_y == pytest.approx(yb)
        assert lay.derived.masking_y1 == pytest.approx(yb - 0.30)


def test_the_three_backdrops_build_their_own_object():
    black = layout(masking={"backdrop": "black_curtain"})
    assert black.find("Backdrop").material == "TS_Masking"
    assert black.find("Backdrop").state.p0[1] == pytest.approx(6.6)
    assert black.find("Backdrop").state.p1[0] - black.find("Backdrop").state.p0[0] == pytest.approx(9.8)
    assert "MaskingBatten_Back" in black.names()

    bare = layout(masking={"backdrop": "bare_wall"})
    assert not {"Backdrop", "Cyclorama", "MaskingBatten_Back"} & set(bare.names())

    cyclo = layout(masking={"backdrop": "cyclorama"})
    flat = cyclo.find("Cyclorama")
    assert flat.material == "TS_Cyclorama" and flat.p0[1] == pytest.approx(5.8)
    assert flat.p1[0] - flat.p0[0] == pytest.approx(9.4)
    assert "Backdrop" not in cyclo.names() and "MaskingBatten_Back" in cyclo.names()


def test_italian_legs_run_from_the_opening_edge_to_the_cage_wall():
    lay = layout()
    leg = lay.find("Leg_L_01")
    assert leg.state.p0[0] == pytest.approx(-4.0) and leg.state.p1[0] == pytest.approx(-4.9)
    assert lay.find("Leg_R_02").state.p0[0] == pytest.approx(4.0)
    assert leg.z0 == pytest.approx(1.2) and leg.z1 == pytest.approx(ZB)
    assert leg.pleat_count == round(0.9 / 0.3)
    assert leg.state.amplitude == pytest.approx(0.06)
    assert {f"Leg_{s}_{k:02d}" for s in "LR" for k in (1, 2, 3)} <= set(lay.names())


def test_german_style_builds_continuous_legs_and_side_battens():
    lay = layout(masking={"style": "german"})
    names = set(lay.names())
    assert {"Leg_L", "Leg_R", "MaskingBatten_Side_L", "MaskingBatten_Side_R"} <= names
    assert "Leg_L_01" not in names
    leg = lay.find("Leg_R")
    assert leg.state.p0 == pytest.approx((4.0, 4.25)) and leg.state.p1 == pytest.approx((4.0, 6.3))
    side = lay.find("MaskingBatten_Side_L")
    assert side.start == pytest.approx((-4.0, 4.25, ZB)) and side.end == pytest.approx((-4.0, 6.3, ZB))


def test_lanes_still_set_the_border_planes_in_german_style():
    lay = layout(masking={"style": "german", "lanes": 2})
    assert {"Border_01", "Border_02", "MaskingBatten_02"} <= set(lay.names())
    assert "Border_03" not in lay.names()


def test_opening_wider_than_the_cage_removes_the_legs_and_warns():
    for style in ("italian", "german"):
        lay = layout(masking={"opening": 11.0, "style": style})
        assert not [n for n in lay.names() if n.startswith("Leg_")]
        assert any("plus large que la cage" in w for w in lay.warnings)
    assert not any("plus large" in w for w in layout().warnings)


def test_narrow_lanes_are_reported_for_the_italian_style():
    assert any("moins de 0,60" in w for w in layout(masking={"lanes": 4}).warnings)
    assert not any("moins de 0,60" in w for w in layout(masking={"lanes": 3}).warnings)


def test_borders_are_checked_one_by_one():
    vector = (True, False, True) + (True,) * 5
    lay = layout(masking={"borders": vector})
    names = set(lay.names())
    assert {"Border_01", "Border_03", "Border_00"} <= names
    assert "Border_02" not in names
    assert "MaskingBatten_02" in names


def test_borders_beyond_the_lane_count_are_ignored():
    lay = layout(masking={"lanes": 2, "borders": (True,) * 8})
    assert {"Border_01", "Border_02"} <= set(lay.names()) and "Border_03" not in lay.names()


def test_front_border_switch_removes_its_border_and_batten():
    lay = layout(masking={"front_border": False})
    assert "Border_00" not in lay.names() and "MaskingBatten_00" not in lay.names()


def test_border_geometry_covers_the_leg_tops_toward_the_house():
    lay = layout()
    border = lay.find("Border_01")
    plane = plane_y(lay, "MaskingBatten_01")
    assert border.state.p0[1] == pytest.approx(plane - 0.10)
    assert border.z0 == pytest.approx(1.2 + 4.5) and border.z1 == pytest.approx(ZB)
    assert border.state.p1[0] - border.state.p0[0] == pytest.approx(9.8)
    front = lay.find("Border_00")
    assert front.state.p0[1] == pytest.approx(1.6 + 0.35 - 0.10)


def test_borders_without_useful_height_are_dropped_with_a_warning():
    lay = layout(masking={"border_bottom": 6.0})
    assert not [n for n in lay.names() if n.startswith("Border_")]
    assert any("Frises sans hauteur utile" in w for w in lay.warnings)
    assert not any("Frises" in w for w in layout().warnings)
    quiet = layout(masking={"border_bottom": 6.0, "front_border": False,
                            "borders": (False,) * 8})
    assert not any("Frises" in w for w in quiet.warnings)


def test_masking_battens_share_the_light_batten_tube_and_height():
    lay = layout()
    tube = lay.find("MaskingBatten_01")
    light = lay.find("Batten_01")
    assert tube.material == "TS_Batten" and tube.radius == light.radius
    assert tube.start[0] == pytest.approx(light.start[0]) and tube.end[0] == pytest.approx(light.end[0])
    assert tube.start[2] == pytest.approx(ZB)
    assert lay.derived.masking_batten_count == 5


def test_light_battens_near_masking_planes_are_removed_and_renumbered():
    base = dict(masking={"backdrop": "bare_wall", "front_border": False},
                curtains={"main_enabled": False})

    def kept(lanes):
        lay = no_modules(**{**base, "masking": {**base["masking"], "lanes": lanes}})
        return [plane_y(lay, f"Batten_{i:02d}") for i in range(1, lay.derived.batten_count + 1)]

    assert kept(1) == pytest.approx([2.1, 3.1, 4.1, 5.1, 6.1])
    assert kept(3) == pytest.approx([2.1, 3.1, 4.1, 6.1])
    # lanes=2 puts a plane at 4.4: the batten at 4.1 is exactly 0.30 away and stays
    assert kept(2) == pytest.approx([2.1, 3.1, 4.1, 5.1, 6.1])


def test_the_main_curtain_plane_is_far_enough_to_keep_the_first_light_batten():
    lay = no_modules(masking={"backdrop": "bare_wall", "front_border": False, "lanes": 1},
                     curtains={"main_enabled": True})
    assert plane_y(lay, "Batten_01") == pytest.approx(2.1)
    assert lay.find("MainCurtain_L").state.p0[1] == pytest.approx(1.75)


def test_a_front_border_clears_the_first_light_batten():
    with_border = no_modules(curtains={"main_enabled": False})
    without = no_modules(curtains={"main_enabled": False}, masking={"front_border": False})
    assert plane_y(with_border, "Batten_01") != pytest.approx(2.1)
    assert plane_y(without, "Batten_01") == pytest.approx(2.1)


def test_main_curtain_geometry_and_states():
    lay = layout()
    left, right = lay.find("MainCurtain_L"), lay.find("MainCurtain_R")
    assert left.material == "TS_MainCurtain"
    assert left.state.p0 == pytest.approx((0.15, 1.75)) and left.state.p1 == pytest.approx((-5.3, 1.75))
    assert right.state.p0 == pytest.approx((-0.15, 1.75)) and right.state.p1 == pytest.approx((5.3, 1.75))
    assert left.z0 == pytest.approx(1.2) and left.z1 == pytest.approx(1.2 + 5.0 + 0.3)
    closed_len = abs(left.state.p1[0] - left.state.p0[0])
    opened = left.open_state
    assert opened.p1 == pytest.approx(left.state.p1)
    assert abs(opened.p1[0] - opened.p0[0]) == pytest.approx(0.15 * closed_len)
    assert opened.amplitude == pytest.approx(0.20) and left.state.amplitude == pytest.approx(0.06)
    assert left.pleat_count == right.pleat_count == round(closed_len / 0.3)


def test_main_curtain_meshes_share_topology_between_the_two_states():
    left = layout().find("MainCurtain_L")
    closed, opened = pleated_mesh(left), pleated_mesh(left, open_pose=True)
    assert closed.faces == opened.faces
    assert len(closed.vertices) == len(opened.vertices) == 2 * (4 * left.pleat_count + 1)
    assert closed.vertices != opened.vertices
    xs = [v[0] for v in opened.vertices]
    assert min(xs) >= -5.3 - 0.2 and max(xs) <= -5.3 + 0.15 * 5.45 + 0.2


def test_main_curtain_can_be_disabled():
    assert not [n for n in layout(curtains={"main_enabled": False}).names()
                if n.startswith("MainCurtain")]


def test_main_opening_never_changes_the_layout():
    assert layout(curtains={"main_opening": 0.0}) == layout(curtains={"main_opening": 100.0})


def test_pleated_surfaces_face_the_house_and_stay_in_their_plane_band():
    lay = layout()
    for name in ("Leg_L_01", "Border_01", "Backdrop", "MainCurtain_R"):
        surface = lay.find(name)
        mesh = build_mesh(surface)
        base_y = surface.state.p0[1]
        assert all(abs(v[1] - base_y) <= surface.state.amplitude + 1e-9 for v in mesh.vertices)
        for face in mesh.faces:
            pts = [mesh.vertices[i] for i in face]
            ny = sum((a[2] - b[2]) * (a[0] + b[0]) for a, b in zip(pts, pts[1:] + pts[:1]))
            assert ny < 0
