import math

import pytest

from core.layout import compute_layout
from core.meshes import build_mesh
from helpers import approx_bounds, bounds, layout, make


def with_modules(symmetric=True, left=None, right=None):
    params = make()
    params["modules"]["symmetric"] = symmetric
    params["modules"]["left"].update(left or {})
    params["modules"]["right"].update(right or {})
    return params


def area(rect):
    return (rect[2] - rect[0]) * (rect[3] - rect[1])


def overlap(a, b):
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    return max(w, 0.0) * max(h, 0.0)


def test_module_at_0_degrees_faces_the_house_with_inner_edges_at_3_45():
    lay = layout()
    assert approx_bounds(bounds(lay, "Module_L_Front"), ((-5.0, -3.45), (2.05, 2.15), (1.2, 6.2)))
    assert approx_bounds(bounds(lay, "Module_L_Return"), ((-3.55, -3.45), (2.05, 4.05), (1.2, 6.2)))
    opening = bounds(lay, "Module_R_Front")[0][0] - bounds(lay, "Module_L_Front")[0][1]
    assert opening == pytest.approx(6.90)


def test_module_at_90_degrees_runs_along_the_cage_wall_facing_the_stage():
    lay = compute_layout(with_modules(left={"angle": 90.0}))
    assert approx_bounds(bounds(lay, "Module_L_Front"), ((-5.1, -5.0), (2.05, 3.6), (1.2, 6.2)))
    assert approx_bounds(bounds(lay, "Module_R_Front"), ((5.0, 5.1), (2.05, 3.6), (1.2, 6.2)))
    for name, sign in (("Module_L_Front", 1.0), ("Module_R_Front", -1.0)):
        mesh = build_mesh(lay.find(name))
        wall_x = -5.0 * sign
        facing = [f for f in mesh.faces
                  if all(abs(mesh.vertices[i][0] - wall_x) < 1e-9 for i in f)]
        assert facing
        for face in facing:
            pts = [mesh.vertices[i] for i in face]
            nx = sum((a[1] - b[1]) * (a[2] + b[2]) for a, b in zip(pts, pts[1:] + pts[:1]))
            assert nx * sign > 0


def test_module_return_follows_the_back_direction():
    lay = compute_layout(with_modules(left={"angle": 90.0, "depth": 1.0}))
    b = bounds(lay, "Module_L_Return")
    assert approx_bounds(b, ((-6.0, -5.0), (3.5, 3.6), (1.2, 6.2)))


def test_right_module_is_the_mirror_of_the_left_one_when_symmetric():
    lay = compute_layout(with_modules(left={"angle": 30.0, "window_enabled": True,
                                            "wall_gap": 0.2}))
    for part in ("Front", "Return"):
        left = build_mesh(lay.find(f"Module_L_{part}")).vertices
        right = build_mesh(lay.find(f"Module_R_{part}")).vertices
        mirrored = sorted((round(-x, 9), round(y, 9), round(z, 9)) for x, y, z in left)
        assert mirrored == sorted((round(x, 9), round(y, 9), round(z, 9)) for x, y, z in right)


def test_sides_are_independent_when_not_symmetric():
    lay = compute_layout(with_modules(False, left={"height": 4.0}, right={"height": 3.0,
                                                                         "enabled": False}))
    assert bounds(lay, "Module_L_Front")[2][1] == pytest.approx(1.2 + 4.0)
    assert "Module_R_Front" not in lay.names()
    lay = compute_layout(with_modules(True, left={"enabled": False}, right={"enabled": True}))
    assert not [n for n in lay.names() if n.startswith("Module_")]


def test_wall_gap_and_setback_move_the_hinge():
    lay = compute_layout(with_modules(left={"wall_gap": 0.5, "setback": 3.0}))
    b = bounds(lay, "Module_L_Front")
    assert b[0][0] == pytest.approx(-4.5) and b[1][0] == pytest.approx(3.0)


def front(lay, side="L"):
    return lay.find(f"Module_{side}_Front")


def test_cells_and_door_tile_the_face_exactly():
    panel = front(layout())
    assert len(panel.openings) == 1
    door = panel.openings[0]
    assert door == pytest.approx((0.775 - 0.47, 0.0, 0.775 + 0.47, 2.4))
    assert sum(map(area, panel.cells)) + area(door) == pytest.approx(1.55 * 5.0)
    assert all(overlap(c, door) == 0 for c in panel.cells)
    for i, a in enumerate(panel.cells):
        assert all(overlap(a, b) == 0 for b in panel.cells[i + 1:])


def test_overlapping_door_and_window_leave_no_cell_in_either():
    lay = compute_layout(with_modules(left={"window_enabled": True, "window_sill": 1.0,
                                            "window_width": 1.0, "window_height": 1.2}))
    panel = front(lay)
    door, window = panel.openings
    assert overlap(door, window) > 0
    union = area(door) + area(window) - overlap(door, window)
    assert sum(map(area, panel.cells)) + union == pytest.approx(1.55 * 5.0)
    assert all(overlap(c, o) == 0 for c in panel.cells for o in panel.openings)


def test_window_offset_moves_toward_the_stage():
    lay = compute_layout(with_modules(left={"window_enabled": True, "door_enabled": False,
                                            "window_offset": 0.2, "window_width": 0.5,
                                            "window_sill": 1.0, "window_height": 1.0}))
    assert front(lay).openings[0] == pytest.approx((0.775 + 0.2 - 0.25, 1.0, 0.775 + 0.2 + 0.25, 2.0))


def test_oversized_bay_is_clipped_and_reported_once_when_symmetric():
    lay = compute_layout(with_modules(left={"door_width": 2.0, "door_height": 5.0}))
    door = front(lay).openings[0]
    assert door == pytest.approx((0.05, 0.0, 1.55 - 0.10 - 0.05, 4.95))
    clipped = [w for w in lay.warnings if "baie rognée" in w]
    assert len(clipped) == 1 and "jardin" in clipped[0]
    assert sum(map(area, front(lay).cells)) + area(door) == pytest.approx(1.55 * 5.0)


def test_clipping_is_reported_for_each_side_when_not_symmetric():
    params = with_modules(False, left={"door_width": 2.0}, right={"door_width": 2.0})
    warnings = [w for w in compute_layout(params).warnings if "baie rognée" in w]
    assert len(warnings) == 2


def test_bay_outside_the_face_is_removed_with_a_warning():
    lay = compute_layout(with_modules(left={"door_offset": 3.0}))
    panel = front(lay)
    assert panel.openings == () and len(panel.cells) == 1
    assert any("baie supprimée" in w for w in lay.warnings)


def test_module_leaving_the_cage_is_reported():
    assert not any("sort de la cage" in w for w in layout().warnings)
    lay = compute_layout(with_modules(left={"angle": 90.0}))
    assert any("Module jardin : sort de la cage" in w for w in lay.warnings)
    deep = compute_layout(with_modules(left={"depth": 6.0}))
    assert any("sort de la cage" in w for w in deep.warnings)


def test_modules_max_y_matches_the_built_geometry():
    for angle in (0.0, 35.0, 90.0):
        lay = compute_layout(with_modules(left={"angle": angle}))
        ys = [bounds(lay, n)[1][1] for n in
              ("Module_L_Front", "Module_L_Return", "Module_R_Front", "Module_R_Return")]
        assert lay.derived.modules_max_y == pytest.approx(max(ys))
    assert layout().derived.modules_max_y == pytest.approx(4.05)


def test_no_modules_means_no_max_y():
    params = with_modules(left={"enabled": False})
    assert compute_layout(params).derived.modules_max_y is None


def test_angle_rotates_the_face_about_the_hinge():
    lay = compute_layout(with_modules(left={"angle": 60.0}))
    verts = build_mesh(lay.find("Module_L_Front")).vertices
    expected = (-5.0 + 1.55 * math.cos(math.radians(60)), 2.05 + 1.55 * math.sin(math.radians(60)))
    assert any(abs(v[0] - expected[0]) < 1e-9 and abs(v[1] - expected[1]) < 1e-9 for v in verts)
    assert any(abs(v[0] + 5.0) < 1e-9 and abs(v[1] - 2.05) < 1e-9 for v in verts)
