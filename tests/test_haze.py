"""DMX-driven haze (spec 15.4): the hazer link and the density driver it feeds."""

import pytest

from core.layout import HAZE_INSET, compute_layout
from core.meshes import build_mesh
from core.rig import HazeLink
from helpers import make


def test_haze_level_reads_one_or_two_channels():
    assert HazeLink("Hazer_01", "dmx_6_1", None, 8, 1.0).level() == ("c", {"c": '["dmx_6_1"]'})
    expression, paths = HazeLink("Hazer_01", "dmx_6_1", "dmx_6_2", 16, 1.0).level()
    assert expression == "(256*c+f)/257" and paths == {"c": '["dmx_6_1"]', "f": '["dmx_6_2"]'}


def test_default_hazer_links_its_density_channel():
    rig = compute_layout(make(haze={"dmx_driven": True})).rig
    assert rig.haze is not None and rig.haze.prop.startswith("dmx_6_")
    assert compute_layout(make()).rig.haze is None


def coplanar_with_haze(lay):
    """Names of the solids owning a face that lies in the plane of a haze-box face and overlaps it."""
    box = lay.find("Haze_Volume")
    lo, hi = box.min, box.max
    found = set()
    for prim in lay.objects:
        if prim.material == "TS_Haze":
            continue
        mesh = build_mesh(prim)
        for face in mesh.faces:
            pts = [mesh.vertices[i] for i in face]
            for axis in range(3):
                if max(p[axis] for p in pts) - min(p[axis] for p in pts) > 1e-6:
                    continue
                if not any(abs(pts[0][axis] - plane) < 1e-4 for plane in (lo[axis], hi[axis])):
                    continue
                others = [a for a in range(3) if a != axis]
                if all(min(p[a] for p in pts) < hi[a] - 1e-3 and max(p[a] for p in pts) > lo[a] + 1e-3
                       for a in others):
                    found.add(prim.name)
    return found


@pytest.mark.parametrize("groups", [
    {},
    {"haze": {"extent": "stage"}},
    {"house": {"ceiling": False}},
    {"stage": {"grid_height": 8.0}},
    {"stage": {"grid_height": 5.0}, "house": {"ceiling": False}},
    {"stage": {"wings": 0.0}, "stairs": {"side_angle": 0.0}},
])
def test_haze_faces_are_never_coplanar_with_a_solid(groups):
    # A coplanar face makes Cycles skip the solid (spec 8.6): walls, floor and ceiling vanish.
    lay = compute_layout(make(**{**groups, "haze": {"enabled": True, **groups.get("haze", {})}}))
    assert coplanar_with_haze(lay) == set()


def test_haze_box_is_inset_into_the_solids_it_ends_on():
    lay = compute_layout(make(haze={"enabled": True}))
    box = lay.find("Haze_Volume")
    floor, wall = lay.find("House_Floor"), lay.find("House_Wall_R")
    assert box.min[2] == pytest.approx(floor.max[2] - HAZE_INSET)
    assert box.max[0] == pytest.approx(wall.min[0] + HAZE_INSET)
    assert box.max[1] == pytest.approx(lay.find("Cage_Back").min[1] + HAZE_INSET)
    assert box.max[2] == pytest.approx(lay.find("House_Ceiling").z - HAZE_INSET)
