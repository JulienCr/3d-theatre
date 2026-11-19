import pytest

from core.layout import compute_layout
from core.meshes import build_mesh
from core.primitives import FlatSurface, HorizontalFace, PleatedSurface
from helpers import edge_report, layout, make, signed_volume


def closed_primitives(lay):
    return [o for o in lay.objects if not isinstance(o, (PleatedSurface, FlatSurface, HorizontalFace))]


def busy_params():
    params = make(stairs={"center": True, "side_angle": 40.0},
                  curtains={"main_enabled": True})
    params["modules"]["left"].update(window_enabled=True, angle=25.0, door_width=2.0)
    return params


@pytest.mark.parametrize("lay", [layout(), compute_layout(busy_params()),
                                 layout(stairs={"left": False, "right": False},
                                        advanced={"side_zone_width": 0.0})])
def test_every_closed_primitive_is_watertight_with_outward_faces(lay):
    assert closed_primitives(lay)
    for obj in closed_primitives(lay):
        mesh = build_mesh(obj)
        assert edge_report(mesh) == (0, 0), obj.name
        assert signed_volume(mesh) > 0, obj.name


def test_module_front_has_no_internal_faces_between_cells():
    panel = compute_layout(busy_params()).find("Module_L_Front")
    cells = {tuple(round(v, 9) for v in c) for c in panel.cells}
    assert len(cells) > 3
    boundary = 0
    for u0, z0, u1, z1 in cells:
        for other_edge in ((u0, z0, u0, z1), (u1, z0, u1, z1), (u0, z0, u1, z0), (u0, z1, u1, z1)):
            shared = any(c != (u0, z0, u1, z1) and _touches(c, other_edge) for c in cells)
            boundary += 0 if shared else 1
    mesh = build_mesh(panel)
    assert len(mesh.faces) == 2 * len(cells) + boundary
    area = sum((c[2] - c[0]) * (c[3] - c[1]) for c in cells)
    assert signed_volume(mesh) == pytest.approx(area * 0.1)


def _touches(cell, edge):
    u0, z0, u1, z1 = edge
    if u0 == u1:
        return (cell[0] == u0 or cell[2] == u0) and cell[1] <= z0 and cell[3] >= z1
    return (cell[1] == z0 or cell[3] == z0) and cell[0] <= u0 and cell[2] >= u1


def test_openings_are_see_through():
    lay = layout()
    panel = lay.find("Module_L_Front")
    door = panel.openings[0]
    mesh = build_mesh(panel)
    cx, cz = -5.0 + (door[0] + door[2]) / 2, 1.2 + (door[1] + door[3]) / 2
    for face in mesh.faces:
        pts = [mesh.vertices[i] for i in face]
        if len({round(p[1], 9) for p in pts}) != 1:
            continue
        xs, zs = [p[0] for p in pts], [p[2] for p in pts]
        assert not (min(xs) < cx < max(xs) and min(zs) < cz < max(zs))


def test_prism_t_shape_and_inverted_u_extrude_correctly():
    lay = layout()
    base = build_mesh(lay.find("Stage_Base"))
    assert len(base.vertices) == 16
    assert signed_volume(base) == pytest.approx((11.6 * 1.6 + 14.0 * 5.4) * 1.17)


def test_tube_volume_is_close_to_a_cylinder():
    tube = layout().find("Batten_01")
    volume = signed_volume(build_mesh(tube))
    expected = 3.141592653589793 * 0.024 ** 2 * 13.8
    assert volume == pytest.approx(expected, rel=0.05)


def test_slat_grid_has_one_closed_shell_per_slat():
    deck = layout().find("Grid_Deck")
    mesh = build_mesh(deck)
    assert len(mesh.vertices) == 8 * len(deck.x_centers)
    assert signed_volume(mesh) == pytest.approx(len(deck.x_centers) * 0.05 * 0.05 * 5.4)
    assert edge_report(mesh) == (0, 0)


def test_box_orientation_is_honoured_by_yaw():
    lay = layout(stairs={"side_angle": 0.0})
    mesh = build_mesh(lay.find("Stairs_Step_R_02"))
    assert signed_volume(mesh) == pytest.approx(1.2 * 0.3 * 0.8)
