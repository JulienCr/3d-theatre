import math
from dataclasses import replace

import pytest
import yaml

import test_gdtf_tool as gdtf_tests
import gdtf_to_fiche as tool
from core import fixtures as F
from core.fixture_models import FixtureModel, fixture_model
from core.meshio import bounds
from core.meshes import Mesh

SHIPPED = sorted(p for p in F.SHIPPED_DIR.iterdir() if (p / F.SHEET_NAME).is_file())
FIXTURES = {p.name: F.load_fixture(p) for p in SHIPPED}
MESH_FIXTURES = ("martin_mac_aura", "robe_robin_esprite")
PROCEDURAL = ("generic_pc_led", "etc_s4led_s3_lustr_x8", "etc_s4led_s3_daylight_hdr")


def tilted(mesh: Mesh, degrees: float) -> Mesh:
    """Mesh rotated like the Blender _Tilt part: -tau about X."""
    c, s = math.cos(math.radians(degrees)), math.sin(math.radians(degrees))
    return Mesh(tuple((x, y * c + z * s, -y * s + z * c) for x, y, z in mesh.vertices), mesh.faces)


def posed(model: FixtureModel) -> list[Mesh]:
    """Pan and tilt parts with the head horizontal (tau = 90), in the root frame."""
    px, py, pz = model.tilt_pivot
    head = tilted(model.tilt, 90)
    head = Mesh(tuple((x + px, y + py, z + pz) for x, y, z in head.vertices), head.faces)
    return [model.pan, head]


def extent(meshes):
    lows, highs = zip(*(bounds(m) for m in meshes if m.vertices))
    return [max(h[i] for h in highs) - min(l[i] for l in lows) for i in range(3)], \
           [min(l[i] for l in lows) for i in range(3)], [max(h[i] for h in highs) for i in range(3)]


def test_shipped_fixtures_all_load():
    assert all(isinstance(f, F.Fixture) for f in FIXTURES.values()), FIXTURES


@pytest.mark.parametrize("name", PROCEDURAL)
def test_procedural_bounding_box_fits_the_datasheet_dimensions(name):
    fixture = FIXTURES[name]
    dims = fixture.physical.dimensions
    model = fixture_model(fixture)
    size, low, high = extent(posed(model))
    assert size[0] <= dims.width + 1e-6
    assert size[1] <= dims.depth + 1e-6
    assert high[2] <= dims.height + 1e-6 and low[2] >= -1e-6
    assert size[1] > 0.9 * dims.depth


@pytest.mark.parametrize("name", PROCEDURAL)
def test_procedural_head_ends_on_the_lens_and_the_pivot_follows_the_sheet(name):
    fixture = FIXTURES[name]
    model = fixture_model(fixture)
    assert model.tilt_pivot == (0.0, 0.0, fixture.physical.mount.tilt_axis_height)
    assert bounds(model.tilt)[1][2] == pytest.approx(fixture.optics.lens_offset)
    assert bounds(model.tilt)[0][2] < -0.1
    assert model.lens_centre == (0.0, 0.0, fixture.optics.lens_offset)
    assert model.lens_normal == (0.0, 0.0, 1.0)
    assert model.lens_radius == pytest.approx(fixture.optics.lens_diameter / 2)
    low, high = bounds(model.base)
    assert low[2] == pytest.approx(-fixture.physical.mount.hook_height - 0.0242 - 0.008, abs=1e-3)
    assert high[2] == pytest.approx(0.0)


def test_profile_lens_tube_changes_the_aperture_and_the_barrel_only():
    fixture = FIXTURES["etc_s4led_s3_lustr_x8"]
    wide, narrow = fixture.optics.lens_tubes[0], fixture.optics.lens_tubes[-1]
    a, b = fixture_model(fixture, wide), fixture_model(fixture, narrow)
    assert a.lens_radius == pytest.approx(wide.lens_diameter / 2)
    assert b.lens_radius == pytest.approx(narrow.lens_diameter / 2)
    assert bounds(a.tilt)[1][0] > bounds(b.tilt)[1][0]
    assert a.tilt != b.tilt and a.pan == b.pan and a.base == b.base
    assert (a.lens_offset, a.tilt_pivot) == (b.lens_offset, b.tilt_pivot)


def test_gate_plane_is_measured_back_from_the_lens_front():
    esprite = fixture_model(FIXTURES["robe_robin_esprite"])
    assert esprite.gate_z == pytest.approx(0.3106 - 0.35)
    assert fixture_model(FIXTURES["generic_pc_led"]).gate_z is None


@pytest.mark.parametrize("name", MESH_FIXTURES)
def test_mesh_model_pivot_and_lens_match_the_sheet(name):
    fixture = FIXTURES[name]
    model = fixture_model(fixture)
    mount = fixture.physical.mount
    px, py, pz = model.tilt_pivot
    assert pz == mount.tilt_axis_height
    assert abs(px) < 0.01 and abs(py) < 0.01
    front = bounds(model.tilt)[1][2]
    assert front == pytest.approx(fixture.optics.lens_offset, abs=0.005)
    ylow, yhigh = bounds(model.pan)
    assert abs((ylow[0] + yhigh[0]) / 2) < 0.005 and abs((ylow[1] + yhigh[1]) / 2) < 0.005


@pytest.mark.parametrize("name", MESH_FIXTURES)
def test_gdtf_frame_is_flipped_so_the_head_sits_on_plus_z(name):
    fixture = FIXTURES[name]
    model = fixture_model(fixture)
    head_gdtf = bounds(_raw(fixture, "head"))
    assert head_gdtf[0][2] < 0 < head_gdtf[1][2]
    assert bounds(model.tilt)[1][2] == pytest.approx(-head_gdtf[0][2])
    low, high = bounds(model.pan)
    assert low[2] > 0 and high[2] > model.tilt_pivot[2]
    assert bounds(model.base)[0][2] > -0.02
    y_raw = bounds(_raw(fixture, "yoke"))
    assert low[1] == pytest.approx(-y_raw[1][1])


def _raw(fixture, part):
    from core.meshio import read_mesh
    return read_mesh(fixture.path(fixture.model3d.part(part).file))


def test_flip_keeps_the_winding_so_normals_do_not_invert():
    fixture = FIXTURES["martin_mac_aura"]
    raw = _raw(fixture, "head")
    flipped = fixture_model(fixture).tilt

    def volume(mesh):
        total = 0.0
        for face in mesh.faces:
            a, b, c = (mesh.vertices[i] for i in face[:3])
            total += sum(a[i] * (b[(i + 1) % 3] * c[(i + 2) % 3] - b[(i + 2) % 3] * c[(i + 1) % 3])
                         for i in range(3))
        return total

    assert volume(flipped) == pytest.approx(volume(raw), rel=1e-6)


@pytest.mark.parametrize("name", PROCEDURAL + MESH_FIXTURES)
def test_vertex_budget_and_valid_faces(name):
    model = fixture_model(FIXTURES[name])
    parts = (model.base, model.pan, model.tilt)
    assert sum(len(m.vertices) for m in parts) <= 2000 or name in MESH_FIXTURES
    for mesh in parts:
        assert all(0 <= i < len(mesh.vertices) for face in mesh.faces for i in face)


def test_output_is_deterministic_and_cacheable():
    fixture = FIXTURES["generic_pc_led"]
    assert fixture_model(fixture) == fixture_model(fixture)
    cache = {}
    first = fixture_model(fixture, None, cache)
    assert fixture_model(fixture, None, cache) is first
    assert list(cache) == [("generic_pc_led", None)]


def test_none_model_is_an_empty_root():
    model = fixture_model(FIXTURES["generic_hazer"])
    assert not model.base.vertices and not model.pan.vertices and not model.tilt.vertices
    assert model.gate_z is None and model.lens_radius == 0.0


def test_box_shape_stands_on_the_mount_face():
    hazer = FIXTURES["generic_hazer"]
    boxed = replace(hazer, model3d=F.Model3D("procedural", shape="box", body=F.Body(0.4, 0.3, 0.2)))
    model = fixture_model(boxed)
    assert bounds(model.base) == ((-0.2, -0.15, 0.0), (0.2, 0.15, 0.2))
    assert not model.tilt.vertices


def test_unreadable_meshes_use_the_fallback_else_raise():
    aura = FIXTURES["martin_mac_aura"]
    pc = FIXTURES["generic_pc_led"].model3d
    broken = F.Model3D("mesh", parts=(F.MeshPart("base", "meshes/missing.obj", (0.0, 0.0, 0.0)),),
                       fallback=pc)
    assert fixture_model(replace(aura, model3d=broken)).tilt.vertices
    with pytest.raises(OSError):
        fixture_model(replace(aura, model3d=replace(broken, fallback=None)))


# ------------------------------------------------------------ vocabulary

NEW_ATTRIBUTES = [f"blade_{n}_rot" for n in range(1, 5)] + ["gobo2_rot"]


def test_new_attributes_are_in_the_vocabulary():
    assert all(F.is_known_attribute(a) for a in NEW_ATTRIBUTES)
    assert not F.is_known_attribute("blade1rot") and not F.is_known_attribute("gobo2pos")


def test_tool_maps_blade_swivel_and_gobo2_rotation(tmp_path, monkeypatch):
    extra = "".join([
        gdtf_tests.channel("11", "Head", "Blade1Rot", gdtf_tests.function("Swivel", "Blade1Rot", "0/1", "128/1", "30", "-30")),
        gdtf_tests.channel("12", "Head", "Blade4Rot", gdtf_tests.function("Swivel", "Blade4Rot", "0/1", "128/1", "30", "-30")),
        gdtf_tests.channel("13", "Head", "Gobo2Pos", gdtf_tests.function("Index", "Gobo2Pos", "0/1", "128/1", "0", "360")),
    ])
    monkeypatch.setattr(gdtf_tests, "FULL_CHANNELS", gdtf_tests.FULL_CHANNELS + extra)
    gdtf = gdtf_tests.build_gdtf(tmp_path / "Acme@Test_Spot.gdtf")
    out = tmp_path / "out" / "test_spot"
    tool.convert(gdtf, out, "test_spot")
    document = yaml.safe_load((out / "fixture.yaml").read_text(encoding="utf-8"))
    names = [c["attribute"] for c in document["modes"][0]["channels"]]
    assert names[-3:] == ["blade_1_rot", "blade_4_rot", "gobo2_rot"]


def test_esprite_sheet_uses_the_new_names_in_every_mode():
    esprite = FIXTURES["robe_robin_esprite"]
    assert isinstance(esprite, F.Fixture)
    for mode in esprite.modes:
        attributes = {c.attribute for c in mode.channels}
        assert set(NEW_ATTRIBUTES) <= attributes, mode.name
        assert not attributes & {"blade1rot", "blade2rot", "blade3rot", "blade4rot", "gobo2pos"}
