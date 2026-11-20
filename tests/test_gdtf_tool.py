import struct
import sys
import zipfile
from xml.etree import ElementTree
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import gdtf_to_fiche as tool  # noqa: E402
from core import fixtures, meshio  # noqa: E402
from core.meshes import Mesh  # noqa: E402

IDENTITY = "{1,0,0,0}{0,1,0,0}{0,0,1,0}{0,0,0,1}"
LOWERED = "{1,0,0,0}{0,1,0,0}{0,0,1,-0.1}{0,0,0,1}"


def chunk(chunk_id, payload):
    return struct.pack("<HI", chunk_id, 6 + len(payload)) + payload


def box_3ds(sx, sy, sz):
    """A 3DS box centred on the origin, with an empty second object like real exports."""
    corners = [(x * sx / 2, y * sy / 2, z * sz / 2) for z in (-1, 1) for y in (-1, 1) for x in (-1, 1)]
    verts = struct.pack("<H", 8) + b"".join(struct.pack("<3f", *c) for c in corners)
    quads = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    tris = [t for a, b, c, d in quads for t in ((a, b, c), (a, c, d))]
    faces = struct.pack("<H", len(tris)) + b"".join(struct.pack("<4H", *t, 0) for t in tris)
    matrix = struct.pack("<12f", 1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0)
    mesh = chunk(0x4100, chunk(0x4110, verts) + chunk(0x4160, matrix) + chunk(0x4120, faces))
    objects = chunk(0x4000, b"Box\0" + mesh) + chunk(0x4000, b"_display_d\0")
    return chunk(0x4D4D, chunk(0x3D3D, objects))


def function(name, attribute, start, default, low="0", high="1", extra=""):
    return (f'<ChannelFunction Name="{name}" Attribute="{attribute}" DMXFrom="{start}" '
            f'Default="{default}" PhysicalFrom="{low}" PhysicalTo="{high}"{extra}/>')


def channel(offset, geometry, attribute, functions, initial=""):
    return (f'<DMXChannel Offset="{offset}" Geometry="{geometry}" InitialFunction="{initial}">'
            f'<LogicalChannel Attribute="{attribute}">{functions}</LogicalChannel></DMXChannel>')


GOBO_FUNCTION = (
    '<ChannelFunction Name="Gobo1" Attribute="Gobo1" DMXFrom="0/1" Default="0/1" Wheel="G1">'
    '<ChannelSet DMXFrom="0/1" Name="Open" WheelSlotIndex="1"/>'
    '<ChannelSet DMXFrom="10/1" Name="Star" WheelSlotIndex="2"/></ChannelFunction>'
    '<ChannelFunction Name="Shake" Attribute="Gobo1SelectShake" DMXFrom="100/1" Default="100/1" Wheel="G1">'
    '<ChannelSet DMXFrom="100/1" Name="Star shake" WheelSlotIndex="2"/></ChannelFunction>')

FULL_CHANNELS = "".join([
    channel("1,2", "Head", "Pan", function("Pan", "Pan", "0/2", "32768/2", "270", "-270"), "Head_Pan.Pan.Pan"),
    channel("3", "Head", "Dimmer", function("Dimmer", "Dimmer", "0/1", "0/1")),
    channel("4", "Head", "Zoom", function("Zoom", "Zoom", "0/1", "128/1", "40", "8")),
    channel("5", "Head", "Gobo1", GOBO_FUNCTION),
    channel("6", "Head", "Prism1", function("Prism", "Prism1", "0/1", "0/1")),
    channel("7", "Aura", "Dimmer", function("Dimmer", "Dimmer", "0/1", "10/1")),
    channel("8", "Head", "Iris", function("Iris", "Iris", "0/1", "0/1", "1", "0.2")),
    channel("9", "Head", "ColorAdd_R", function("Red", "ColorAdd_R", "0/1", "255/1")),
    channel("10", "Head", "CTC", function("Off", "CTC", "0/1", "0/1", "6500", "6500")
            + function("CTC", "CTC", "20/1", "0/1", "10000", "2500")),
])

BASIC_CHANNELS = "".join([
    channel("1", "Head", "Pan", function("Pan", "Pan", "0/1", "128/1", "270", "-270")),
    channel("2", "Head", "Dimmer", function("Dimmer", "Dimmer", "0/1", "0/1")),
])


def description(unit_note=""):
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<GDTF DataVersion="1.2"><FixtureType Name="Test Spot" Manufacturer="Acme Lights" Description="Synthetic{unit_note}">
<Wheels><Wheel Name="G1"><Slot Name="Open" Color="0.3,0.3,100"/>
<Slot Name="Star" MediaFileName="star" Color="0.3,0.3,100"/></Wheel></Wheels>
<PhysicalDescriptions><Properties><Weight Value="7.5"/></Properties></PhysicalDescriptions>
<Models><Model Name="Base" File="base" Length="0.2" Width="0.1" Height="0.05" PrimitiveType="Undefined"/>
<Model Name="Head" File="head" Length="0.15" Width="0.15" Height="0.3" PrimitiveType="Undefined"/>
<Model Name="Beam" File="" Length="0.1" Width="0.1" Height="0.001" PrimitiveType="Cylinder"/></Models>
<Geometries><Geometry Name="Base" Model="Base" Position="{IDENTITY}">
<Geometry Name="Head" Model="Head" Position="{LOWERED}">
<Geometry Name="Beam1" Model="Beam" Position="{IDENTITY}">
<Beam BeamType="Spot" BeamRadius="0.05" LuminousFlux="5000" BeamAngle="20" FieldAngle="30"/></Geometry>
</Geometry></Geometry></Geometries>
<DMXModes>
<DMXMode Name="Full"><DMXChannels>{FULL_CHANNELS}</DMXChannels></DMXMode>
<DMXMode Name="Basic"><DMXChannels>{BASIC_CHANNELS}</DMXChannels></DMXMode>
</DMXModes></FixtureType></GDTF>"""


def build_gdtf(path, base_scale=1000.0, model_note=""):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("description.xml", description(model_note))
        z.writestr("models/3ds/base.3ds", box_3ds(0.2 * base_scale, 0.1 * base_scale, 0.05 * base_scale))
        z.writestr("models/3ds/head.3ds", box_3ds(150, 150, 300))
        z.writestr("wheels/star.png", b"\x89PNG fake")
    return path


@pytest.fixture
def converted(tmp_path):
    gdtf = build_gdtf(tmp_path / "Acme@Test_Spot.gdtf")
    out = tmp_path / "out" / "test_spot"
    report = tool.convert(gdtf, out, "test_spot")
    return report, out


def test_modes_footprints_and_default_mode(converted):
    report, out = converted
    document = yaml.safe_load((out / "fixture.yaml").read_text(encoding="utf-8"))
    assert report.modes == [("Full", 10), ("Basic", 2)]
    assert [(m["name"], m["footprint"]) for m in document["modes"]] == report.modes
    assert document["default_mode"] == "Full"
    assert document["id"] == "test_spot" and document["manufacturer"] == "Acme Lights"
    assert document["sources"][0]["url"] == "source/Acme@Test_Spot.gdtf"
    assert (out / "source" / "Acme@Test_Spot.gdtf").is_file()


def test_sixteen_bit_detection_and_defaults(converted):
    _, out = converted
    document = yaml.safe_load((out / "fixture.yaml").read_text(encoding="utf-8"))
    full, basic = (next(m for m in document["modes"] if m["name"] == n)["channels"] for n in ("Full", "Basic"))
    assert full[0] == {"offset": 1, "attribute": "pan", "bits": 16, "default": 32768, "fine": 2}
    assert full[1] == {"offset": 3, "attribute": "dimmer", "bits": 8, "default": 0}
    assert full[2]["default"] == 128
    assert basic[0] == {"offset": 1, "attribute": "pan", "bits": 8, "default": 128}


def test_attribute_mapping_keeps_unknown_names_and_renames_duplicates(converted):
    _, out = converted
    document = yaml.safe_load((out / "fixture.yaml").read_text(encoding="utf-8"))
    names = [c["attribute"] for c in document["modes"][0]["channels"]]
    assert names == ["pan", "dimmer", "zoom", "gobo1", "prism1", "aura_dimmer", "iris", "color_r", "cct"]
    assert all(fixtures.is_known_attribute(n) or n in ("prism1", "aura_dimmer") for n in names)


def test_physical_ranges_and_optics_come_from_the_functions(converted):
    _, out = converted
    document = yaml.safe_load((out / "fixture.yaml").read_text(encoding="utf-8"))
    assert document["motion"] == {"type": "moving", "pan": {"min": -270, "max": 270, "invert": True},
                                  "tilt": None}
    assert document["optics"]["beam_angle"] == {"min": 8, "max": 40}
    assert document["optics"]["zoom_invert"] is True
    assert document["optics"]["beam_type"] == "profile"
    assert document["optics"]["flux"] == 5000 and document["optics"]["lens_diameter"] == 0.1
    assert document["optics"]["field_angle"] is None
    assert document["colour"] == {"systems": ["rgbw", "cct"], "cct_range": {"min": 2500, "max": 10000}}
    assert document["iris"] == {"min_ratio": 0.2}
    assert document["physical"]["weight"] == 7.5


def test_gobo_wheel_slots_ranges_and_image(converted):
    report, out = converted
    document = yaml.safe_load((out / "fixture.yaml").read_text(encoding="utf-8"))
    wheel = document["gobos"]["wheels"][0]
    assert wheel["name"] == "gobo1" and wheel["rotation_range"] == 360
    assert wheel["slots"] == [{"name": "Open", "image": None, "dmx": [0, 9]},
                              {"name": "Star", "image": "gobos/star.png", "dmx": [10, 99]}]
    assert (out / "gobos" / "star.png").read_bytes() == b"\x89PNG fake"
    assert report.gobos == ["gobos/star.png"]


def test_3ds_models_become_obj_files_in_metres(converted):
    report, out = converted
    base = meshio.read_obj(out / "meshes" / "base.obj")
    low, high = meshio.bounds(base)
    assert [h - l for l, h in zip(low, high)] == pytest.approx([0.2, 0.1, 0.05], abs=1e-5)
    head = meshio.read_obj(out / "meshes" / "head.obj")
    assert len(head.faces) == 12 and len(head.vertices) == 8
    assert {m["file"]: m["scale"] for m in report.meshes} == {"meshes/base.obj": 0.001, "meshes/head.obj": 0.001}
    document = yaml.safe_load((out / "fixture.yaml").read_text(encoding="utf-8"))
    parts = document["model3d"]["parts"]
    assert parts["base"] == {"file": "meshes/base.obj", "offset": [0.0, 0.0, 0.0]}
    assert parts["head"] == {"file": "meshes/head.obj", "offset": [0.0, 0.0, -0.1]}
    assert document["physical"]["dimensions"]["width"] == pytest.approx(0.2, abs=1e-5)


def test_3ds_already_in_metres_is_not_rescaled(tmp_path):
    gdtf = build_gdtf(tmp_path / "m.gdtf", base_scale=1.0)
    report = tool.convert(gdtf, tmp_path / "out", "m_test")
    assert next(m for m in report.meshes if "base" in m["file"])["scale"] == 1.0


def test_detect_scale_picks_the_unit_from_the_model_dimensions():
    mesh = Mesh(((0.0, 0.0, 0.0), (218.0, 131.0, 68.0)), ())
    assert tool.detect_scale(mesh, 0.218, 0.131, 0.068, 0.5) == 0.001
    assert tool.detect_scale(mesh, 2.18, 1.31, 0.68, 0.5) == 0.01
    assert tool.detect_scale(mesh, 5.537, 3.327, 1.727, 0.5) == 0.0254
    assert tool.detect_scale(mesh, 0, 0, 0, 0.5) == 0.5


def test_output_is_invalid_until_the_nulls_are_filled_then_valid(converted):
    _, out = converted
    errors = fixtures.load_fixture(out)
    assert isinstance(errors, list)
    text = "\n".join(errors)
    for key in ("family", "physical.mount.hook_height", "optics.lens_offset", "optics.field_angle",
                "motion.tilt"):
        assert key in text
    document = yaml.safe_load((out / "fixture.yaml").read_text(encoding="utf-8"))
    document["family"] = "moving_profile"
    document["physical"]["mount"] = {"hook_height": 0.1, "tilt_axis_height": 0.3}
    document["optics"].update(lens_offset=0.2, field_angle={"min": 10, "max": 45})
    document["motion"]["tilt"] = {"min": -120, "max": 120}
    document["model3d"]["parts"]["yoke"] = dict(document["model3d"]["parts"]["base"])
    (out / "fixture.yaml").write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    fixture = fixtures.load_fixture(out)
    assert isinstance(fixture, fixtures.Fixture), fixture
    assert fixture.footprint("Full") == 10 and fixture.channel("pan").fine == 2
    assert fixture.gobos[0].slots[1].image == "gobos/star.png"
    assert fixture.model3d.part("head").file == "meshes/head.obj"


def test_mode_selection_and_main(tmp_path, capsys):
    gdtf = build_gdtf(tmp_path / "t.gdtf")
    out = tmp_path / "only_basic"
    assert tool.main([str(gdtf), "--id", "only_basic", "--mode", "Basic", "--out", str(out)]) == 0
    text = capsys.readouterr().out
    assert "1 mode(s)" in text and "Basic" in text and "Full" not in text
    document = yaml.safe_load((out / "fixture.yaml").read_text(encoding="utf-8"))
    assert [m["name"] for m in document["modes"]] == ["Basic"]
    with pytest.raises(SystemExit):
        tool.convert(gdtf, tmp_path / "x", "x", ["Nope"])
    with pytest.raises(SystemExit):
        tool.convert(gdtf, tmp_path / "y", "Bad-Id")


def test_yaml_emitter_round_trips_awkward_scalars():
    document = {"a": "yes", "b": "1e3", "c": "x: y", "d": None, "e": [1, 2.5, True], "f": "é # é",
                "g": [{"k": "v", "w": [1, 2]}, {"k": "z", "w": []}], "h": {}, "i": [{"deep": {"x": 1}}]}
    text = tool.to_yaml(document)
    assert yaml.safe_load(text) == document
    assert "d: null  # " in text


def test_ctc_functions_with_several_physical_values_become_a_linear_curve(converted):
    _, out = converted
    document = yaml.safe_load((out / "fixture.yaml").read_text(encoding="utf-8"))
    full = next(m for m in document["modes"] if m["name"] == "Full")["channels"]
    cct = next(c for c in full if c["attribute"] == "cct")
    assert cct["curve"] == [[0, 6500], [round(19 / 255, 6), 6500], [round(20 / 255, 6), 10000], [1, 2500]]
    assert "curve_mode" not in cct
    assert all("curve" not in c for c in full if c["attribute"] != "cct")


@pytest.mark.parametrize(("low", "high", "expected"), [
    ("270", "-270", {"min": -270, "max": 270, "invert": True}),
    ("-270", "270", {"min": -270, "max": 270}),
])
def test_invert_is_set_only_when_the_function_runs_downwards(low, high, expected):
    element = ElementTree.fromstring(channel("1", "Head", "Tilt", function("Tilt", "Tilt", "0/1", "0/1", low, high)))
    assert tool._span([tool._read_channel(element)], "Tilt", True) == expected


def test_discrete_channel_sets_with_physical_values_become_a_step_curve():
    sets = "".join(f'<ChannelSet DMXFrom="{start}/1" Name="S{start}" PhysicalFrom="{kelvin}"/>'
                   for start, kelvin in ((0, 3200), (100, 5600), (200, 8000)))
    element = ElementTree.fromstring(channel("1", "Head", "CTC", (
        f'<ChannelFunction Name="CTC" Attribute="CTC" DMXFrom="0/1" Default="0/1">{sets}</ChannelFunction>')))
    curve, mode = tool._curve(tool._read_channel(element))
    assert mode == "step"
    assert curve == [[0, 3200], [round(100 / 255, 6), 5600], [round(200 / 255, 6), 8000]]


def test_a_single_physical_range_gives_no_curve():
    element = ElementTree.fromstring(channel("1", "Head", "Zoom", function("Zoom", "Zoom", "0/1", "0/1", "40", "8")))
    assert tool._curve(tool._read_channel(element)) is None
