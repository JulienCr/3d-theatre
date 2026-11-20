"""DMX-driven haze (spec 15.4): the hazer link and the density driver it feeds."""

from core.layout import compute_layout
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


def test_haze_box_top_stays_clear_of_the_house_ceiling():
    # A coplanar top face makes Cycles skip the opaque ceiling (spec 8.6).
    for params in (make(haze={"enabled": True}), make(haze={"enabled": True, "extent": "stage"})):
        layout = compute_layout(params)
        ceiling, box = layout.find("House_Ceiling"), layout.find("Haze_Volume")
        assert 0.001 < ceiling.z - box.max[2] < 0.05
