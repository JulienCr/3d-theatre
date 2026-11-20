import pytest

from core.layout import compute_layout
from core.meshes import MAX_DEPTH_FACTOR, build_mesh, grid_shape, pleated_mesh
from helpers import layout, make, modules_off

ZB = 1.2 + 6.1 - 0.5
YF = 1.75 + 0.20 * MAX_DEPTH_FACTOR + 0.06 * MAX_DEPTH_FACTOR + 0.20
Y0 = YF + 0.20


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
    step = (6.6 - 4.25) / 3
    ys = [plane_y(lay, f"MaskingBatten_{k:02d}") for k in (1, 2, 3)]
    assert ys == pytest.approx([4.25, 4.25 + step, 4.25 + 2 * step])


def test_planes_start_behind_the_proscenium_without_modules():
    lay = no_modules()
    assert lay.derived.masking_y0 == pytest.approx(Y0)
    step = (6.6 - Y0) / 3
    ys = [plane_y(lay, f"MaskingBatten_{k:02d}") for k in (1, 2, 3)]
    assert ys == pytest.approx([Y0, Y0 + step, Y0 + 2 * step])
    assert plane_y(lay, "MaskingBatten_Back") - ys[-1] == pytest.approx(step)


def test_shallow_modules_do_not_push_the_planes_back():
    params = make()
    params["modules"]["left"].update(setback=0.5, depth=0.5)
    assert compute_layout(params).derived.masking_y0 == pytest.approx(Y0)


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
    assert black.find("Backdrop").state.p1[0] - black.find("Backdrop").state.p0[0] == pytest.approx(14.0)
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
    assert leg.state.p0[0] == pytest.approx(-4.0) and leg.state.p1[0] == pytest.approx(-7.0)
    assert lay.find("Leg_R_02").state.p0[0] == pytest.approx(4.0)
    assert leg.z0 == pytest.approx(1.2) and leg.z1 == pytest.approx(ZB)
    assert leg.pleat_count == round(3.0 / 0.3)
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
        lay = layout(masking={"opening": 14.0, "style": style})
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
    lay = layout(masking={"borders_mode": "manual"})
    border = lay.find("Border_01")
    plane = plane_y(lay, "MaskingBatten_01")
    assert border.state.p0[1] == pytest.approx(plane - 0.10)
    assert border.z0 == pytest.approx(1.2 + 4.5) and border.z1 == pytest.approx(ZB)
    assert border.state.p1[0] - border.state.p0[0] == pytest.approx(14.0)
    front = lay.find("Border_00")
    assert front.state.p0[1] == pytest.approx(YF - 0.10)
    assert plane_y(lay, "MaskingBatten_00") == pytest.approx(YF)


def test_borders_without_useful_height_are_dropped_with_a_warning():
    lay = layout(masking={"border_bottom": 6.0, "borders_mode": "manual"})
    assert not [n for n in lay.names() if n.startswith("Border_")]
    assert any("Frises sans hauteur utile" in w for w in lay.warnings)
    assert not any("Frises" in w for w in layout().warnings)
    quiet = layout(masking={"border_bottom": 6.0, "front_border": False,
                            "borders": (False,) * 8, "borders_mode": "manual"})
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
    for lanes in (1, 2, 3):
        lay = no_modules(masking={"backdrop": "bare_wall", "front_border": False, "lanes": lanes},
                         curtains={"main_enabled": False})
        planes = [plane_y(lay, f"MaskingBatten_{k:02d}") for k in range(1, lanes + 1)]
        expected = [2.1 + i for i in range(5)
                    if all(abs(2.1 + i - p) >= 0.30 - 1e-9 for p in planes)]
        got = [plane_y(lay, f"Batten_{i:02d}") for i in range(1, lay.derived.batten_count + 1)]
        assert got == pytest.approx(expected)
        assert f"Batten_{len(got) + 1:02d}" not in lay.names()


def battens(lay):
    return [plane_y(lay, f"Batten_{i:02d}") for i in range(1, lay.derived.batten_count + 1)]


def test_the_last_rue_gets_a_light_batten_in_the_middle_of_its_free_interval():
    lay = layout()
    last_plane, back = plane_y(lay, "MaskingBatten_03"), plane_y(lay, "MaskingBatten_Back")
    ys = battens(lay)
    assert ys[:3] == pytest.approx([2.1, plane_y(lay, "MaskingBatten_00") + 0.30, 3.1]) and len(ys) == 4
    assert ys[3] == pytest.approx(((last_plane + 0.30) + (back - 0.30)) / 2)
    assert all(abs(ys[3] - plane_y(lay, f"MaskingBatten_{k}")) >= 0.30 for k in ("03", "Back"))
    assert lay.find("Batten_04").start[2] == pytest.approx(ZB)


def test_a_regular_light_batten_in_the_last_rue_is_kept_without_an_addition():
    lay = no_modules(masking={"backdrop": "bare_wall", "front_border": False, "lanes": 1},
                     curtains={"main_enabled": False})
    assert battens(lay) == pytest.approx([2.1, 3.1, 4.1, 5.1, 6.1])


@pytest.mark.parametrize("backdrop", ["bare_wall", "black_curtain", "cyclorama"])
def test_the_added_batten_keeps_its_distance_from_every_masking_batten(backdrop):
    lay = no_modules(masking={"backdrop": backdrop, "lanes": 3}, curtains={"main_enabled": False})
    masking = [plane_y(lay, n) for n in lay.names() if n.startswith("MaskingBatten_") and "Side" not in n]
    last_plane = max(m for m in masking if m < lay.derived.backdrop_y)
    assert [y for y in battens(lay) if last_plane < y < lay.derived.backdrop_y]
    assert all(abs(y - m) >= 0.30 - 1e-9 for y in battens(lay) for m in masking)


def test_a_last_rue_too_narrow_for_a_batten_adds_none_and_alerts():
    lay = layout(masking={"lanes": 8})
    assert [y for y in battens(lay) if y > plane_y(lay, "MaskingBatten_08")] == []
    assert any("Dernière rue trop étroite" in w for w in lay.warnings)
    assert not any("Dernière rue" in w for w in layout().warnings)


def test_the_main_curtain_plane_is_far_enough_to_keep_the_first_light_batten():
    lay = no_modules(masking={"backdrop": "bare_wall", "front_border": False, "lanes": 1},
                     curtains={"main_enabled": True})
    assert plane_y(lay, "Batten_01") == pytest.approx(2.1)
    assert lay.find("MainCurtain_L").state.p0[1] == pytest.approx(1.75)


def test_light_battens_keep_their_distance_from_the_front_border_batten():
    lay = no_modules(curtains={"main_enabled": False}, grid={"batten_spacing": 0.2})
    front = plane_y(lay, "MaskingBatten_00")
    ys = [plane_y(lay, f"Batten_{i:02d}") for i in range(1, lay.derived.batten_count + 1)]
    assert ys and all(abs(y - front) >= 0.30 - 1e-9 for y in ys)


def test_main_curtain_geometry_and_states():
    lay = layout()
    left, right = lay.find("MainCurtain_L"), lay.find("MainCurtain_R")
    assert left.material == "TS_MainCurtain"
    assert left.state.p0 == pytest.approx((0.15, 1.75)) and left.state.p1 == pytest.approx((-5.75, 1.75))
    assert right.state.p0 == pytest.approx((-0.15, 1.75)) and right.state.p1 == pytest.approx((5.75, 1.75))
    assert left.z0 == pytest.approx(1.2) and left.z1 == pytest.approx(1.2 + 5.0 + 0.3)
    closed_len = abs(left.state.p1[0] - left.state.p0[0])
    opened = left.open_state
    assert opened.p1 == pytest.approx(left.state.p1)
    assert opened.p0 == pytest.approx((-5.25, 1.75))
    assert opened.amplitude == pytest.approx(0.20) and left.state.amplitude == pytest.approx(0.06)
    assert left.pleat_count == right.pleat_count == round(closed_len / 0.3)


def test_main_curtain_meshes_share_topology_between_the_two_states():
    left = layout().find("MainCurtain_L")
    closed, opened = pleated_mesh(left), pleated_mesh(left, open_pose=True)
    assert closed.faces == opened.faces
    cols, rows = grid_shape(left)
    assert len(closed.vertices) == len(opened.vertices) == cols * rows
    assert closed.vertices != opened.vertices
    xs = [v[0] for v in opened.vertices]
    assert min(xs) == pytest.approx(-5.75) and max(xs) == pytest.approx(-5.25)


@pytest.mark.parametrize("drape", [0.0, 0.5, 1.0])
@pytest.mark.parametrize("stage,advanced", [
    ({}, {}),
    ({"width": 14.0}, {"proscenium_thickness": 1.5}),
    ({"width": 9.0}, {"proscenium_thickness": 0.5}),
    ({}, {"proscenium_thickness": 0.42}),
])
def test_open_main_curtain_stays_behind_the_posts(stage, advanced, drape):
    lay = layout(stage=stage, advanced=advanced, masking={"drape": drape})
    wc = lay.derived.frame_opening
    for name in ("MainCurtain_L", "MainCurtain_R"):
        opened = pleated_mesh(lay.find(name), open_pose=True)
        assert all(abs(v[0]) >= wc / 2 - 1e-9 for v in opened.vertices)
    assert not any("Rideau de scène" in w for w in lay.warnings)


def test_open_main_curtain_in_a_narrow_post_keeps_its_bundle_and_warns():
    lay = layout(advanced={"proscenium_thickness": 0.35})
    opened = lay.find("MainCurtain_R").open_state
    assert abs(opened.p1[0] - opened.p0[0]) == pytest.approx(0.30)
    assert any("Rideau de scène ouvert visible" in w for w in lay.warnings)
    quiet = layout(advanced={"proscenium_thickness": 0.35}, curtains={"main_enabled": False})
    assert not any("Rideau de scène" in w for w in quiet.warnings)


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
        limit = surface.state.amplitude * MAX_DEPTH_FACTOR + 1e-9
        assert all(abs(v[1] - base_y) <= limit for v in mesh.vertices)
        for face in mesh.faces:
            pts = [mesh.vertices[i] for i in face]
            ny = sum((a[2] - b[2]) * (a[0] + b[0]) for a, b in zip(pts, pts[1:] + pts[:1]))
            assert ny < 0


# ------------------------------------------------------------------ drapery

DRAPED = ("Leg_L_01", "Leg_R_01", "Border_01", "Border_00", "Backdrop", "MainCurtain_L")


def rows_of(surface, open_pose=False):
    mesh = pleated_mesh(surface, open_pose)
    cols, rows = grid_shape(surface)
    return [mesh.vertices[r * cols:(r + 1) * cols] for r in range(rows)]


def pleat_shapes(row, count, samples=8):
    """Per-pleat (x offsets, y offsets) relative to the pleat start."""
    out = []
    for k in range(count):
        chunk = row[k * samples:(k + 1) * samples + 1]
        out.append(([p[0] - chunk[0][0] for p in chunk], [p[1] - chunk[0][1] for p in chunk]))
    return out


def test_drapery_is_deterministic_and_seeded_by_name():
    first, second = layout(), layout()
    for name in DRAPED:
        assert build_mesh(first.find(name)).vertices == build_mesh(second.find(name)).vertices
    left, right = first.find("Leg_L_01"), first.find("Leg_R_01")
    ys_left = [v[1] for v in build_mesh(left).vertices]
    ys_right = [v[1] for v in build_mesh(right).vertices]
    assert ys_left != ys_right
    assert [abs(x) for x in (v[0] for v in build_mesh(left).vertices)] !=         [abs(x) for x in (v[0] for v in build_mesh(right).vertices)]


def test_zero_drape_gives_identical_pleats_on_every_row():
    lay = layout(masking={"drape": 0.0})
    leg = lay.find("Leg_L_01")
    for row in rows_of(leg):
        shapes = pleat_shapes(row, leg.pleat_count)
        for xs, ys in shapes[1:]:
            assert xs == pytest.approx(shapes[0][0], abs=1e-9)
            assert ys == pytest.approx(shapes[0][1], abs=1e-9)


def test_drape_makes_pleats_differ_below_a_regular_heading():
    leg = layout(masking={"drape": 1.0}).find("Backdrop")
    rows = rows_of(leg)
    top, mid = rows[-1], rows[len(rows) // 2]
    top_shapes = pleat_shapes(top, leg.pleat_count)
    assert all(s[1] == pytest.approx(top_shapes[0][1], abs=1e-9) for s in top_shapes)
    mid_shapes = pleat_shapes(mid, leg.pleat_count)
    widths = {round(s[0][-1], 4) for s in mid_shapes}
    peaks = {round(max(s[1], key=abs), 4) for s in mid_shapes}
    assert len(widths) > 3 and len(peaks) > 3


@pytest.mark.parametrize("drape", [0.0, 1.0])
def test_drapery_grid_and_vertical_extent(drape):
    lay = layout(masking={"drape": drape})
    for name in DRAPED:
        surface = lay.find(name)
        cols, rows = grid_shape(surface)
        assert cols == 8 * surface.pleat_count + 1
        grid = rows_of(surface)
        zs = [r[0][2] for r in grid]
        assert zs[0] == surface.z0 and zs[-1] == pytest.approx(surface.z1)
        assert all(b - a <= 0.25 + 1e-9 for a, b in zip(zs, zs[1:]))
        assert all(v[2] >= surface.z0 for r in grid for v in r)
    plateau = lay.find("Stage_Floor").t1
    assert min(v[2] for v in build_mesh(lay.find("Leg_L_01")).vertices) == pytest.approx(plateau)


@pytest.mark.parametrize("drape", [0.0, 1.0])
def test_legs_stay_within_their_own_extent(drape):
    lay = layout(masking={"drape": drape})
    wk = lay.derived.cage_width
    for name in ("Leg_L_01", "Leg_R_03", "Leg_L_02"):
        leg = lay.find(name)
        xs = (leg.state.p0[0], leg.state.p1[0])
        for x, y, _ in build_mesh(leg).vertices:
            assert min(xs) - 1e-9 <= x <= max(xs) + 1e-9
            assert abs(x) <= wk / 2 + 1e-9
            assert abs(x) >= 4.0 - 1e-9
            assert abs(y - leg.state.p0[1]) <= leg.state.amplitude * MAX_DEPTH_FACTOR + 1e-9


def test_german_legs_stay_in_their_y_extent():
    lay = layout(masking={"style": "german", "drape": 1.0})
    leg = lay.find("Leg_L")
    y0, y1 = leg.state.p0[1], leg.state.p1[1]
    ys = [v[1] for v in build_mesh(leg).vertices]
    assert min(ys) >= min(y0, y1) - 1e-9 and max(ys) <= max(y0, y1) + 1e-9


@pytest.mark.parametrize("drape", [0.0, 0.5, 1.0])
def test_main_curtain_poses_share_vertex_count_and_faces(drape):
    lay = layout(masking={"drape": drape})
    for name in ("MainCurtain_L", "MainCurtain_R"):
        surface = lay.find(name)
        closed, opened = pleated_mesh(surface), pleated_mesh(surface, open_pose=True)
        assert len(closed.vertices) == len(opened.vertices) and closed.faces == opened.faces
        assert [v[2] for v in closed.vertices] == [v[2] for v in opened.vertices]


def test_drape_param_lives_in_the_masking_group():
    from core.params import GROUPS
    drape = next(p for p in GROUPS["masking"].params if p.key == "drape")
    assert (drape.default, drape.min, drape.max) == (0.5, 0.0, 1.0) and drape.rebuild


# ----------------------------------------------- wall to wall and planes

@pytest.mark.parametrize("drape", [0.0, 1.0])
@pytest.mark.parametrize("wings", [0.0, 1.0, 2.0, 3.5])
def test_drapery_touches_the_cage_walls_and_never_crosses_them(drape, wings):
    lay = layout(stage={"wings": wings}, masking={"drape": drape})
    wall = lay.derived.cage_width / 2
    for name in ("Border_00", "Border_02", "Backdrop"):
        xs = [v[0] for v in build_mesh(lay.find(name)).vertices]
        assert min(xs) == pytest.approx(-wall, abs=1e-3) and max(xs) == pytest.approx(wall, abs=1e-3)
        assert min(xs) >= -wall - 1e-9 and max(xs) <= wall + 1e-9
    for name in ("Leg_L_01", "Leg_L_03"):
        xs = [v[0] for v in build_mesh(lay.find(name)).vertices]
        assert min(xs) == pytest.approx(-wall, abs=1e-3) and min(xs) >= -wall - 1e-9
    for name in ("Leg_R_01", "Leg_R_03"):
        xs = [v[0] for v in build_mesh(lay.find(name)).vertices]
        assert max(xs) == pytest.approx(wall, abs=1e-3) and max(xs) <= wall + 1e-9


@pytest.mark.parametrize("drape", [0.0, 0.5, 1.0])
def test_front_border_never_enters_the_main_curtain_envelope(drape):
    lay = layout(masking={"drape": drape})
    ys = []
    for name in ("MainCurtain_L", "MainCurtain_R"):
        surface = lay.find(name)
        for pose in (False, True):
            ys += [v[1] for v in pleated_mesh(surface, pose).vertices]
    border = [v[1] for v in build_mesh(lay.find("Border_00")).vertices]
    assert min(border) > max(ys) + 0.05
    first = [v[1] for v in build_mesh(lay.find("Border_01")).vertices]
    assert min(first) > max(border) - 0.05


def test_first_plane_closes_the_first_lane_and_nothing_hugs_the_backdrop():
    lay = layout()
    planes = [plane_y(lay, f"MaskingBatten_{k:02d}") for k in (1, 2, 3)]
    assert planes[0] == pytest.approx(lay.derived.masking_y0)
    assert lay.derived.backdrop_y - planes[-1] == pytest.approx(lay.derived.lane_width)
    assert lay.derived.lane_width == pytest.approx((6.6 - 4.25) / 3)


def mantle_free_interval(lay):
    front, first = plane_y(lay, "MaskingBatten_00"), plane_y(lay, "MaskingBatten_01")
    return front + 0.30, first - 0.30


def test_the_mantle_batten_sits_0_30_behind_the_front_border_when_none_is_close_enough():
    lay = layout(grid={"batten_spacing": 2.0})
    lo, hi = mantle_free_interval(lay)
    assert battens(lay) == pytest.approx([2.1, lo, battens(lay)[2]]) and lo < hi
    assert lay.find("Batten_02").start[2] == pytest.approx(ZB)
    assert lo == pytest.approx(plane_y(lay, "MaskingBatten_00") + 0.30)
    default = battens(layout())
    assert default[1] == pytest.approx(lo) and default[2] == pytest.approx(3.1)


def test_a_regular_batten_just_behind_the_front_border_replaces_the_mantle_batten():
    lay = layout(grid={"batten_spacing": 0.9})
    lo, hi = mantle_free_interval(lay)
    assert battens(lay)[:3] == pytest.approx([2.1, 3.0, 3.9])
    assert lo < 3.0 < lo + 0.30 and not [y for y in battens(lay) if abs(y - lo) < 1e-6]


def test_no_mantle_batten_without_a_front_border_or_a_free_interval():
    assert battens(layout(masking={"front_border": False})) == pytest.approx([2.1, 3.1, battens(layout())[3]])
    narrow = no_modules()
    assert mantle_free_interval(narrow)[1] < mantle_free_interval(narrow)[0]
    assert battens(narrow)[:2] == pytest.approx([2.1, 3.1]) and len(battens(narrow)) == 3
    assert not any("Première rue" in w or "manteau" in w for w in narrow.warnings)


def test_a_narrow_free_interval_gets_its_mantle_batten_in_the_middle():
    lay = layout(modules={"left": {"depth": 1.0}, "right": {"depth": 1.0}})
    front, first = plane_y(lay, "MaskingBatten_00"), plane_y(lay, "MaskingBatten_01")
    lo, hi = front + 0.30, first - 0.30
    assert 0 <= hi - lo < 0.30
    assert battens(lay)[1] == pytest.approx((lo + hi) / 2)


@pytest.mark.parametrize("spacing", [1.0, 2.0])
def test_light_battens_stay_hidden_from_the_reference_seat_with_the_mantle_batten(spacing):
    computed = layout(grid={"batten_spacing": spacing})
    lowest = min(height for _, height in computed.derived.border_bottoms)
    manual = layout(grid={"batten_spacing": spacing},
                    masking={"borders_mode": "manual", "border_bottom": lowest})
    seen = [w for w in manual.warnings if "Découverte verticale" in w]
    assert all("Batten_01" in w for w in seen)
