import copy
import math
import shutil
from pathlib import Path

import pytest
import yaml

from core import fixtures as F

DATA = Path(__file__).parent / "data" / "fixtures"
SHEET = DATA / "test_mover"


def raw():
    return copy.deepcopy(yaml.safe_load((SHEET / "fixture.yaml").read_text(encoding="utf-8")))


def hazer():
    return {"version": 1, "id": "test_hazer", "manufacturer": "Test", "model": "Haze",
            "family": "hazer", "sources": [{"kind": "other", "url": "https://example.org"}],
            "physical": {"weight": 3},
            "modes": [{"name": "One", "footprint": 1,
                       "channels": [{"offset": 1, "attribute": "haze_density", "bits": 8, "default": 0}]}],
            "default_mode": "One", "model3d": {"kind": "none"}}


def errors_of(data, folder=None):
    result = F.validate_fixture(data, folder)
    assert isinstance(result, list), "the sheet should be invalid"
    return "\n".join(result)


# ------------------------------------------------------------------ loading

def test_valid_sheet_loads_with_every_section():
    fixture = F.load_fixture(SHEET)
    assert isinstance(fixture, F.Fixture)
    assert fixture.id == "test_mover" and fixture.family == "moving_profile"
    assert fixture.optics.field_angle == F.Range(6, 50) and fixture.optics.zoom_invert
    assert fixture.colour.systems == ("cmy", "cto", "cct")
    assert fixture.blades.sides == (180, 270, 0, 90) and fixture.blades.travel.closed == -0.02
    assert fixture.gobos[0].slots[1].contains(15) and not fixture.gobos[0].slots[1].contains(20)
    assert fixture.strobe.strobe.stop == 127 and fixture.iris.min_ratio == 0.1
    assert fixture.model3d.barrel.diameter == 0.14
    with pytest.raises(Exception):
        fixture.id = "other"


def test_modes_footprint_and_channel_lookups():
    fixture = F.load_fixture(SHEET)
    assert fixture.mode_names() == ("Standard", "Basic")
    assert fixture.footprint() == 12 == fixture.footprint("default") == fixture.footprint("Standard")
    assert fixture.footprint("Basic") == 4
    pan = fixture.channel("pan")
    assert (pan.offset, pan.fine, pan.bits, pan.offsets) == (1, 2, 16, (1, 2))
    assert fixture.channel("tilt").fine == 4  # defaults to offset + 1
    assert fixture.channel("pan", "Basic").bits == 8 and fixture.channel("pan", "Basic").fine is None
    assert fixture.channel("iris") is None
    assert fixture.channel("prism1").default == 0
    assert fixture.channel("tilt").default_normalized == pytest.approx(32768 / 65535)
    with pytest.raises(KeyError):
        fixture.mode("Nope")


def test_unknown_attributes_are_kept_and_known_ones_are_recognised():
    fixture = F.load_fixture(SHEET)
    attributes = [c.attribute for c in fixture.mode().channels]
    assert "prism1" in attributes and not F.is_known_attribute("prism1")
    assert F.is_known_attribute("blade_4b") and F.is_known_attribute("emitter_8")
    assert F.is_known_attribute("haze_density") and len(set(F.ATTRIBUTES)) == len(F.ATTRIBUTES)


def test_hazer_needs_no_optics_motion_or_dimensions():
    fixture = F.validate_fixture(hazer())
    assert isinstance(fixture, F.Fixture)
    assert fixture.optics is None and fixture.motion is None and fixture.model3d.kind == "none"
    assert fixture.channel("haze_density").offset == 1


def test_range_lerp_matches_the_spec_formula():
    assert F.Range(-270, 270).lerp(0.25) == -135
    assert F.Range(2700, 8000).lerp(1) == 8000


# --------------------------------------------------------------- validation

def drop(path):
    def mutate(d):
        node = d
        *head, last = path.split(".")
        for key in head:
            node = node[key]
        node.pop(last)
    return mutate


def setter(path, value):
    def mutate(d):
        node = d
        *head, last = path.split(".")
        for key in head:
            node = node[int(key)] if key.isdigit() else node[key]
        node[int(last) if last.isdigit() else last] = value
    return mutate


def tube(name, beam, field, diameter=None, ies=None):
    return {"name": name, "beam_angle": beam, "field_angle": field, "lens_diameter": diameter, "ies": ies}


def with_tubes(*tubes):
    def mutate(d):
        d["optics"].pop("field_angle")
        d["optics"]["lens_tubes"] = list(tubes)
    return mutate


def with_curve(points, **extra):
    return lambda d: d["modes"][0]["channels"][2].update(curve=points, **extra)


INVALID = {
    "missing top-level key": (drop("manufacturer"), "manufacturer"),
    "null mandatory key": (setter("physical.mount.hook_height", None), "physical.mount.hook_height"),
    "conditional: dimensions": (drop("physical.dimensions"), "physical.dimensions"),
    "conditional: optics.flux": (drop("optics.flux"), "optics.flux"),
    "conditional: motion.pan when moving": (drop("motion.pan"), "motion.pan"),
    "conditional: field_angle without tubes": (drop("optics.field_angle"), "optics.field_angle"),
    "field_angle and lens_tubes are exclusive": (setter("optics.lens_tubes", [10, 20]), "s'excluent"),
    "conditional: cct_range with cct": (drop("colour.cct_range"), "cct_range"),
    "conditional: cto_kelvin with cto": (drop("colour.cto_kelvin"), "cto_kelvin"),
    "conditional: blades.rotation when motorised": (drop("blades.rotation"), "blades.rotation"),
    "conditional: beam_angle for a wash": (setter("optics.beam_type", "wash"), "beam_angle"),
    "unknown family": (setter("family", "laser"), "family"),
    "bad id characters": (setter("id", "Test-Mover"), "id"),
    "min above max": (setter("optics.field_angle", {"min": 60, "max": 5}), "min"),
    "duplicate offset": (setter("modes.0.channels.1.offset", 5), "offset 5 utilisé deux fois"),
    "offset above footprint": (setter("modes.0.channels.2.offset", 13), "offset"),
    "fine channel already used": (setter("modes.0.channels.0.fine", 5), "offset 5 utilisé deux fois"),
    "fine channel above footprint": (lambda d: d["modes"][1]["channels"][0].update(bits=16, fine=9), "fine"),
    "bad bits": (setter("modes.0.channels.2.bits", 12), "bits"),
    "default above 8 bits": (setter("modes.0.channels.2.default", 256), "default"),
    "unknown default_mode": (setter("default_mode", "Nope"), "default_mode"),
    "duplicate mode name": (setter("modes.1.name", "Standard"), "deux fois"),
    "attribute twice in a mode": (setter("modes.0.channels.4.attribute", "dimmer"), "présent deux fois"),
    "unknown attribute with a space": (setter("modes.0.channels.6.attribute", "Prism 1"), "attribute"),
    "lens tubes unsorted": (with_tubes(tube("10", 9, 10), tube("5", 4, 5)), "triés"),
    "lens tube names duplicated": (with_tubes(tube("5", 4, 5), tube("5", 8, 10)), "déclaré deux fois"),
    "lens tube beam above field": (with_tubes(tube("5", 6, 5)), "beam_angle"),
    "lens tube is a bare number": (lambda d: (d["optics"].pop("field_angle"),
                                              d["optics"].update(lens_tubes=[5, 10])), "dictionnaire"),
    "lens tube ies missing": (with_tubes(tube("5", 4, 5, ies="ies/none.ies")), "introuvable"),
    "ies profiles share a field angle": (setter("optics.ies", [{"field_angle": 10, "file": "gobos/g1.png"},
                                                              {"field_angle": 10, "file": "gobos/g1.png"}]),
                                         "même field_angle"),
    "ies profile file missing": (setter("optics.ies", [{"field_angle": 10, "file": "ies/none.ies"}]), "introuvable"),
    "curve with one point": (with_curve([[0, 1]]), "au moins deux points"),
    "curve not increasing": (with_curve([[0, 1], [0.5, 2], [0.5, 3]]), "strictement croissant"),
    "curve dmx above 1": (with_curve([[0, 1], [1.5, 2]]), "entre 0 et 1"),
    "curve point is not a pair": (with_curve([[0, 1, 2], [1, 2]]), "paire"),
    "curve_mode unknown": (with_curve([[0, 1], [1, 2]], curve_mode="cubic"), "curve_mode"),
    "curve_mode without a curve": (setter("modes.0.channels.2.curve_mode", "step"), "réservé"),
    "blade sides not distinct": (setter("blades.sides", [0, 90, 180, 90]), "distincts"),
    "blade sides wrong count": (setter("blades.sides", [0, 90, 180]), "quatre"),
    "missing gobo image": (setter("gobos.wheels.0.slots.1.image", "gobos/none.png"), "introuvable"),
    "missing source file": (setter("sources.1.url", "source/none.pdf"), "introuvable"),
    "mesh file missing": (lambda d: d.update(model3d={"kind": "mesh", "parts": {
        p: {"file": f"meshes/{p}.obj", "offset": [0, 0, 0]} for p in F.MESH_PARTS}}), "introuvable"),
    "iris ratio above 1": (setter("iris.min_ratio", 1.5), "min_ratio"),
    "strobe range inverted": (setter("strobe.open", [40, 10]), "min"),
    "profile needs a barrel": (drop("model3d.barrel"), "barrel"),
    "no modes": (setter("modes", []), "au moins un mode"),
}


@pytest.mark.parametrize("name", INVALID)
def test_each_validation_rule_rejects_a_broken_sheet(name):
    mutate, expected = INVALID[name]
    data = raw()
    mutate(data)
    assert expected in errors_of(data, SHEET)


def test_folder_name_must_equal_the_id(tmp_path):
    folder = tmp_path / "other_name"
    shutil.copytree(SHEET, folder)
    assert "nom du dossier" in errors_of(raw(), folder)


def test_a_mesh_sheet_with_its_files_present_is_valid(tmp_path):
    folder = tmp_path / "test_mover"
    shutil.copytree(SHEET, folder)
    (folder / "meshes").mkdir()
    for part in F.MESH_PARTS:
        (folder / "meshes" / f"{part}.obj").write_text("v 0 0 0\n")
    data = raw()
    data["model3d"] = {"kind": "mesh", "parts": {
        p: {"file": f"meshes/{p}.obj", "offset": [0, 0, 0.1]} for p in F.MESH_PARTS},
        "fallback": data["model3d"]}
    fixture = F.validate_fixture(data, folder)
    assert isinstance(fixture, F.Fixture)
    assert fixture.model3d.part("head").offset == (0, 0, 0.1)
    assert fixture.model3d.fallback.kind == "procedural"
    assert fixture.path("meshes/head.obj") == folder / "meshes" / "head.obj"


def test_a_non_dictionary_document_is_rejected():
    assert F.validate_fixture([1, 2]) == ["fiche : un dictionnaire YAML est attendu."]


def test_errors_list_every_faulty_key_at_once():
    data = raw()
    del data["manufacturer"]
    data["optics"]["flux"] = None
    data["default_mode"] = "Nope"
    text = errors_of(data)
    assert "manufacturer" in text and "optics.flux" in text and "default_mode" in text


# ------------------------------------------------------- optics and curves

def tubed(*tubes, **optics):
    data = raw()
    data["optics"].pop("field_angle")
    data["optics"].update(lens_tubes=list(tubes), **optics)
    return data


def test_lens_tubes_are_objects_with_their_own_angles_and_aperture():
    fixture = F.validate_fixture(tubed(tube("5", 7.3, 8.7, 0.445, "gobos/g1.png"), tube("10", 10, 12),
                                       lens_diameter=0.19), SHEET)
    assert isinstance(fixture, F.Fixture)
    five, ten = fixture.optics.lens_tubes
    assert five == F.LensTube("5", 7.3, 8.7, 0.445, "gobos/g1.png")
    assert ten.lens_diameter is None and ten.ies is None
    assert fixture.optics.aperture(five) == 0.445
    assert fixture.optics.aperture(ten) == fixture.optics.aperture() == 0.19


def test_a_single_ies_path_is_one_profile_without_field_angle():
    data = raw()
    data["optics"]["ies"] = "gobos/g1.png"
    fixture = F.validate_fixture(data, SHEET)
    assert fixture.optics.ies == (F.IesProfile(None, "gobos/g1.png"),)
    assert F.load_fixture(SHEET).optics.ies == ()
    assert fixture.ies_for(30.0) == "gobos/g1.png"


def test_ies_for_prefers_the_tube_then_the_nearest_zoom_profile(tmp_path):
    folder = tmp_path / "test_mover"
    shutil.copytree(SHEET, folder)
    for name in ("narrow", "mid", "wide"):
        (folder / f"{name}.ies").write_text("IESNA")
    data = raw()
    data["optics"]["ies"] = [{"field_angle": 10, "file": "narrow.ies"}, {"field_angle": 30, "file": "mid.ies"},
                             {"field_angle": 50, "file": "wide.ies"}]
    fixture = F.validate_fixture(data, folder)
    assert (fixture.ies_for(12), fixture.ies_for(26), fixture.ies_for(80)) == ("narrow.ies", "mid.ies", "wide.ies")
    assert fixture.ies_for(30, F.LensTube("5", 4, 5, None, "tube.ies")) == "tube.ies"
    assert fixture.ies_for(30, F.LensTube("5", 4, 5, None, None)) is None
    assert F.validate_fixture(raw(), SHEET).ies_for(30) is None


def test_curve_is_parsed_and_defaults_to_linear():
    data = raw()
    data["modes"][0]["channels"][2].update(curve=[[0, 3200], [0.5, 2700], [1, 10000]])
    fixture = F.validate_fixture(data, SHEET)
    channel = fixture.mode().channels[2]
    assert channel.curve == ((0.0, 3200.0), (0.5, 2700.0), (1.0, 10000.0)) and channel.curve_mode == "linear"
    assert F.load_fixture(SHEET).mode().channels[2].curve == ()


def stepped():
    return F.Channel(1, "cct", 8, 0, None, ((0.0, 3200.0), (0.2, 1900.0), (0.8, 6000.0)), "step")


def test_physical_without_a_curve_is_the_linear_range_mapping():
    channel = F.Channel(1, "cct", 8, 0, None)
    assert channel.physical(0.25, F.Range(2700, 8000)) == F.Range(2700, 8000).lerp(0.25)
    with pytest.raises(ValueError):
        channel.physical(0.25)


def test_physical_linear_curve_interpolates_and_holds_the_ends():
    channel = F.Channel(1, "cct", 8, 0, None, ((0.2, 1000.0), (0.6, 3000.0), (1.0, 3000.0)))
    assert channel.physical(0.4) == pytest.approx(2000)
    assert channel.physical(0.0) == 1000 and channel.physical(1.0) == 3000
    assert channel.physical(0.8, F.Range(0, 1)) == 3000


def test_physical_step_curve_holds_each_value_until_the_next_point():
    channel = stepped()
    assert (channel.physical(0.0), channel.physical(0.19), channel.physical(0.2)) == (3200, 3200, 1900)
    assert (channel.physical(0.79), channel.physical(0.8), channel.physical(1.0)) == (1900, 6000, 6000)


# ---------------------------------------------------------------- shipped

SHIPPED = sorted(p for p in F.SHIPPED_DIR.iterdir() if (p / F.SHEET_NAME).is_file())


def test_shipped_library_is_not_empty():
    assert len(SHIPPED) >= 4


@pytest.mark.parametrize("folder", SHIPPED, ids=lambda p: p.name)
def test_every_shipped_sheet_validates(folder):
    result = F.load_fixture(folder)
    assert isinstance(result, F.Fixture), "; ".join(result)


# ---------------------------------------------------------------- discovery

def make_library_dirs(tmp_path):
    shipped, user = tmp_path / "shipped", tmp_path / "user"
    for root in (shipped, user):
        root.mkdir()
    shutil.copytree(SHEET, shipped / "test_mover")
    return shipped, user


def test_discover_reads_a_folder_and_skips_folders_without_a_sheet(tmp_path):
    shipped, user = make_library_dirs(tmp_path)
    (shipped / "README").mkdir()
    library = F.discover([shipped, user, tmp_path / "missing"])
    assert list(library.fixtures) == ["test_mover"] and library.messages == ()
    assert library.get("test_mover").root == shipped / "test_mover"
    assert "test_mover" in library and len(library) == 1 and library.get("x") is None
    assert library.ids_by_family("moving_profile", "pc") == ("test_mover",)
    assert library.ids_by_family("pc") == ()


def test_user_sheet_overrides_the_shipped_one_and_says_so(tmp_path):
    shipped, user = make_library_dirs(tmp_path)
    shutil.copytree(SHEET, user / "test_mover")
    text = (user / "test_mover" / "fixture.yaml").read_text(encoding="utf-8")
    (user / "test_mover" / "fixture.yaml").write_text(text.replace("model: Mover", "model: Mine"),
                                                      encoding="utf-8")
    library = F.discover([shipped, user])
    assert library.get("test_mover").model == "Mine"
    assert len(library.messages) == 1
    assert "utilisateur" in library.messages[0] and "remplace" in library.messages[0]


def test_invalid_sheet_is_dropped_with_a_french_message_and_never_listed(tmp_path):
    shipped, user = make_library_dirs(tmp_path)
    bad = user / "test_bad"
    bad.mkdir()
    (bad / "fixture.yaml").write_text("version: 1\nid: test_bad\n", encoding="utf-8")
    broken = user / "test_yaml"
    broken.mkdir()
    (broken / "fixture.yaml").write_text("id: [unclosed", encoding="utf-8")
    library = F.discover([shipped, user])
    assert list(library.fixtures) == ["test_mover"]
    text = "\n".join(library.messages)
    assert "test_bad" in text and "écartée" in text and "manufacturer" in text
    assert "test_yaml" in text and "YAML invalide" in text


def test_invalid_user_sheet_does_not_replace_a_valid_shipped_one(tmp_path):
    shipped, user = make_library_dirs(tmp_path)
    clone = user / "test_mover"
    clone.mkdir()
    (clone / "fixture.yaml").write_text("version: 1\nid: test_mover\n", encoding="utf-8")
    library = F.discover([shipped, user])
    assert library.get("test_mover").manufacturer == "Test"
    assert any("écartée" in m for m in library.messages)


def test_empty_library_is_usable():
    assert F.EMPTY_LIBRARY.ids_by_family(*F.FAMILIES) == () and F.EMPTY_LIBRARY.get("a") is None


# ---------------------------------------------------------------------- DMX

def test_encode_matches_the_spec_formula():
    assert F.encode(0, 8) == (0,) and F.encode(1, 8) == (255,) and F.encode(0.5, 8) == (128,)
    assert F.encode(1, 16) == (255, 255) and F.encode(0, 16) == (0, 0)
    n = round(65535 * 0.3)
    assert F.encode(0.3, 16) == (n >> 8, n & 255)
    assert F.encode(2.0, 16) == (255, 255) and F.encode(-1.0, 8) == (0,)
    with pytest.raises(ValueError):
        F.encode(0.5, 12)


def test_sixteen_bit_round_trip_is_within_one_step():
    for k in range(0, 1001):
        v = k / 1000
        coarse, fine = F.to_properties(v, 16)
        assert abs(F.decode(coarse, fine, 16) - v) <= 1 / 65535
    assert F.decode(*F.to_properties(1.0, 16), 16) == pytest.approx(1.0, abs=1e-12)


def test_decode_is_exactly_n_over_65535_and_not_the_raw_sum():
    for coarse_byte, fine_byte in ((255, 255), (128, 0), (1, 255), (0, 1)):
        n = 256 * coarse_byte + fine_byte
        assert F.decode(coarse_byte / 255, fine_byte / 255, 16) == pytest.approx(n / 65535, abs=1e-12)
    raw_full = 255 / 255 + (255 / 255) / 256
    assert raw_full > 1.003 and F.decode(1.0, 1.0, 16) == pytest.approx(1.0)


def test_eight_bit_decode_ignores_the_fine_byte():
    assert F.decode(0.4, 0.9, 8) == 0.4
    assert F.to_properties(1.0, 8) == (1.0,)
    assert F.to_properties(0.5, 8) == (128 / 255,)


def test_pan_of_540_degrees_stays_within_a_hundredth_of_a_degree():
    span = F.Range(-270, 270)
    for target in (-270, -100.3, 0, 123.456, 270):
        v = (target - span.min) / (span.max - span.min)
        assert abs(span.lerp(F.decode(*F.to_properties(v, 16), 16)) - target) <= 0.005


def test_cct_to_rgb_is_warm_below_6500_k_and_normalised():
    for kelvin in (1500, 2700, 3200, 5600, 6500, 10000, 30000):
        rgb = F.cct_to_rgb(kelvin)
        assert max(rgb) == pytest.approx(1.0) and min(rgb) >= 0
    for kelvin in (2700, 3200, 4000, 5000):
        red, _, blue = F.cct_to_rgb(kelvin)
        assert red > blue
    red, _, blue = F.cct_to_rgb(10000)
    assert blue >= red
    r, g, b = F.cct_to_rgb(6500)
    assert abs(r - g) < 0.1 and abs(b - g) < 0.1


def test_etc_fixtures_expose_per_tube_optics_and_the_stepped_cct_table():
    for fixture_id in ("etc_s4led_s3_lustr_x8", "etc_s4led_s3_daylight_hdr"):
        fixture = F.load_fixture(F.SHIPPED_DIR / fixture_id)
        tubes = fixture.optics.lens_tubes
        assert tubes[0].name == "5" and tubes[0].lens_diameter == 0.4445 and tubes[0].ies == "ies/xdlt_5.ies"
        assert all(t.beam_angle <= t.field_angle for t in tubes)
        cct = fixture.channel("cct", "Studio")
        assert cct.physical(0 / 255) == 3200 and cct.physical(1 / 255) == pytest.approx(1900, abs=0.01)
        assert cct.physical(165 / 255) == pytest.approx(6000, abs=0.01)
        assert cct.physical(254 / 255) == pytest.approx(10450, abs=0.01)
        assert fixture.channel("cct", "Studio 16bit").curve == cct.curve


def test_max_energy_takes_the_spot_from_intensity_and_the_wash_from_flux():
    omega = 2 * math.pi * (1 - math.cos(math.radians(30) / 2))
    assert F.max_energy("profile", 10000, 30) == pytest.approx(F.EXPOSURE_GAIN * F.W_PER_CD_SPOT * 10000 / omega)
    assert F.max_energy("wash", 10000, 30) == pytest.approx(F.EXPOSURE_GAIN * F.W_PER_LM_AREA * 10000)
    assert F.max_energy("profile", 10000, 15) > F.max_energy("profile", 10000, 30)
    assert F.max_energy("wash", 10000, 15) == F.max_energy("wash", 10000, 30)
