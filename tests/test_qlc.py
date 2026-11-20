import xml.etree.ElementTree as ET
from dataclasses import replace
from pathlib import Path

import pytest

from core.fixtures import SHIPPED_DIR, Library, discover, validate_fixture
from core.layout import compute_layout
from core.params import default_params
from core.rig import default_library
from core.qlc import (
    FULL_SCENE,
    POSITIONS_SCENE,
    WORKSPACE_NAME,
    PatchedFixture,
    definition_filename,
    export_workspace,
    fixture_definition_xml,
    patched_from_rig,
    workspace_xml,
)

DATA = Path(__file__).resolve().parent / "data" / "qlc"


def _sheet(fid, manufacturer, model, family, modes, **extra):
    data = {
        "version": 1, "id": fid, "manufacturer": manufacturer, "model": model, "family": family,
        "sources": [{"kind": "other", "url": "test", "note": "synthetic"}],
        "physical": {"weight": 5.5, "dimensions": {"width": 0.3, "depth": 0.2, "height": 0.4},
                     "mount": {"hook_height": 0.1, "tilt_axis_height": 0.2}},
        "optics": {"beam_type": "wash", "lens_diameter": 0.1, "lens_offset": 0.1, "flux": 3850,
                   "field_angle": {"min": 11, "max": 58}, "beam_angle": {"min": 8, "max": 40}},
        "motion": {"type": "moving", "pan": {"min": -270, "max": 270}, "tilt": {"min": -115, "max": 115}},
        "modes": modes, "default_mode": modes[0]["name"],
        "model3d": {"kind": "procedural", "shape": "box", "body": {"width": 0.2, "depth": 0.2, "height": 0.2}},
    }
    data.update(extra)
    result = validate_fixture(data)
    assert not isinstance(result, list), result
    return result


def _channel(offset, attribute, bits=8, default=0, fine=None):
    item = {"offset": offset, "attribute": attribute, "bits": bits, "default": default}
    if fine:
        item["fine"] = fine
    return item


@pytest.fixture
def library():
    mover = _sheet("test_mover", "Test", "Mover", "moving_wash", [
        {"name": "Standard", "footprint": 10, "channels": [
            _channel(1, "pan", 16, 32768, 2), _channel(3, "tilt", 16, 32768, 4),
            _channel(5, "dimmer", 8, 0), _channel(6, "zoom", 8, 128), _channel(8, "strobe", 8, 32),
            _channel(9, "gobo1", 8, 0), _channel(10, "aura_ring", 8, 0)]},
        {"name": "Basic", "footprint": 3, "channels": [
            _channel(1, "pan", 8, 128), _channel(2, "tilt", 8, 128), _channel(3, "dimmer", 8, 0)]},
    ],
        strobe={"open": [0, 31], "closed": [32, 63], "strobe": {"from": 64, "to": 127, "hz_min": 0.5, "hz_max": 20}},
        gobos={"wheels": [{"name": "gobo1", "slots": [
            {"name": "Ouvert", "dmx": [0, 9]}, {"name": "Points", "dmx": [10, 19]}]}]},
    )
    pc = _sheet("test_pc", "Test", "PC LED", "pc", [
        {"name": "2 Ch", "footprint": 2, "channels": [_channel(1, "dimmer", 8, 0), _channel(2, "cct", 8, 128)]},
        {"name": "Wide", "footprint": 2, "channels": [_channel(1, "dimmer", 16, 0, 2)]},
    ], motion={"type": "static"}, colour={"systems": ["cct"], "cct_range": {"min": 2700, "max": 6500}},
        optics={"beam_type": "wash", "lens_diameter": 0.1, "lens_offset": 0.1, "flux": 1000,
                "field_angle": {"min": 40, "max": 40}, "beam_angle": {"min": 30, "max": 30}})
    aura = _sheet("test_aura", "Martin", "MAC Aura", "moving_wash", [
        {"name": "Std", "footprint": 3, "channels": [_channel(1, "dimmer"), _channel(2, "pan"), _channel(3, "tilt")]},
        {"name": "Odd", "footprint": 2, "channels": [_channel(1, "dimmer"), _channel(2, "pan")]},
    ], qlc={"manufacturer": "Martin", "model": "MAC Aura", "modes": {"Std": "Standard", "Odd": "Odd"},
            "verified": "2026-01-01"})
    hazer = _sheet("test_hazer", "Test", "Hazer", "hazer", [
        {"name": "1 Ch", "footprint": 1, "channels": [_channel(1, "haze_density")]}],
        optics=None, motion=None, physical={"weight": 12}, model3d={"kind": "none"})
    return Library({f.id: f for f in (aura, hazer, mover, pc)})


@pytest.fixture
def qlc_dir(tmp_path):
    folder = tmp_path / "qlc_fixtures" / "Martin"
    folder.mkdir(parents=True)
    (folder / "Martin-MAC-Aura.qxf").write_text(
        (DATA / "Martin-MAC-Aura.qxf").read_text(encoding="utf-8"), encoding="utf-8")
    return tmp_path / "qlc_fixtures"


def _root(text):
    return ET.fromstring(text.split("\n", 2)[2])  # past the XML declaration and the DOCTYPE


def _fixtures(root):
    return [{c.tag.split("}")[-1]: c.text for c in f} for f in root.iterfind(".//{*}Fixture")]


def _scene_pairs(root, name):
    scene = next(f for f in root.iterfind(".//{*}Function") if f.get("Name") == name)
    return {v.get("ID"): [int(n) for n in v.text.split(",")] for v in scene.iterfind(".//{*}FixtureVal")}


PATCH = (
    PatchedFixture("Mover_01", "test_mover", "Standard", 2, 1, "Movers", (200, 17, 100, 255)),
    PatchedFixture("Mover_02", "test_mover", "Basic", 2, 11, "Movers", (10, 0, 20, 0)),
    PatchedFixture("PC_01", "test_pc", "2 Ch", 4, 1, "Circuit_A", None, ((1, 255), (2, 64))),
    PatchedFixture("PC_02", "test_pc", "2 Ch", 4, 3, "Circuit_A", None),
    PatchedFixture("Hazer_01", "test_hazer", "1 Ch", 6, 512, None),
)


def test_universe_and_address_are_zero_based(library):
    root = _root(workspace_xml(PATCH, library))
    fixtures = _fixtures(root)
    assert [(f["ID"], f["Name"], f["Universe"], f["Address"], f["Channels"]) for f in fixtures] == [
        ("0", "Mover_01", "1", "0", "10"), ("1", "Mover_02", "1", "10", "3"),
        ("2", "PC_01", "3", "0", "2"), ("3", "PC_02", "3", "2", "2"), ("4", "Hazer_01", "5", "511", "1")]
    universes = [(u.get("Name"), u.get("ID")) for u in root.iterfind(".//{*}InputOutputMap/{*}Universe")]
    assert universes == [(f"Univers {i + 1}", str(i)) for i in range(6)]


def test_groups_follow_the_patch_order(library):
    root = _root(workspace_xml(PATCH, library))
    groups = [(g.find("{*}Name").text, g.find("{*}Size").attrib,
               [(h.get("X"), h.get("Fixture"), h.text) for h in g.iterfind(".//{*}Head")])
              for g in root.iterfind(".//{*}FixtureGroup")]
    assert groups == [
        ("Movers", {"X": "2", "Y": "1"}, [("0", "0", "0"), ("1", "1", "0")]),
        ("Circuit_A", {"X": "2", "Y": "1"}, [("0", "2", "0"), ("1", "3", "0")])]


def test_rest_scenes_carry_pan_tilt_bytes(library):
    root = _root(workspace_xml(PATCH, library))
    positions = _scene_pairs(root, POSITIONS_SCENE)
    assert positions == {"0": [0, 200, 1, 17, 2, 100, 3, 255], "1": [0, 10, 1, 20]}
    full = _scene_pairs(root, FULL_SCENE)
    assert full["2"] == [0, 255, 1, 64] and full["0"] == positions["0"]
    assert "3" not in full


def test_pan_tilt_palette_is_in_degrees_from_dmx_zero(library):
    root = _root(workspace_xml(PATCH, library))
    palettes = [(p.get("ID"), p.get("Type"), p.get("Name"), p.get("Value")) for p in root.iterfind(".//{*}Palette")]
    # 16 bits: pan 51217/65535 * 540 = 422.0; 8 bits: tilt 20/255 * 230 = 18.0
    assert palettes == [("0", "PanTilt", "Repos_Mover_01", "422,91"), ("1", "PanTilt", "Repos_Mover_02", "21,18")]


def test_definition_has_fine_channels_and_contiguous_modes(library):
    root = _root(fixture_definition_xml(library.get("test_mover")))
    channels = {c.get("Name"): c for c in root.findall("{*}Channel")}
    assert channels["Pan"].get("Preset") == "PositionPan"
    assert channels["Pan fin"].get("Preset") == "PositionPanFine"
    assert channels["Intensité"].get("Preset") == "IntensityDimmer"
    assert "Intensité fin" not in channels
    assert channels["Zoom"].get("Preset") == "BeamZoomSmallBig"
    standard = {m.get("Name"): [c.text for c in m] for m in root.findall("{*}Mode")}["Standard"]
    assert standard == ["Pan", "Pan fin", "Tilt", "Tilt fin", "Intensité", "Zoom", "Inutilisé 7",
                        "Stroboscope", "Gobo 1", "aura_ring"]
    numbers = [c.get("Number") for c in root.find("{*}Mode").findall("{*}Channel")]
    assert numbers == [str(i) for i in range(10)]
    assert root.find("{*}Type").text == "Moving Head"
    assert root.find("{*}Mode/{*}Head") is None


def test_capabilities_come_from_the_sheet(library):
    root = _root(fixture_definition_xml(library.get("test_mover")))
    channels = {c.get("Name"): c for c in root.findall("{*}Channel")}
    strobe = [(c.get("Min"), c.get("Max"), c.get("Preset"), c.get("Res1"), c.get("Res2"))
              for c in channels["Stroboscope"].findall("{*}Capability")]
    assert strobe == [("0", "31", "ShutterOpen", None, None), ("32", "63", "ShutterClose", None, None),
                      ("64", "127", "StrobeFreqRange", "0.5", "20"), ("128", "255", None, None, None)]
    gobo = [(c.get("Min"), c.get("Max"), c.text) for c in channels["Gobo 1"].findall("{*}Capability")]
    assert gobo == [("0", "9", "Ouvert"), ("10", "19", "Points"), ("20", "255", "Inutilisé")]
    unknown = channels["aura_ring"]
    assert unknown.find("{*}Group").text == "Nothing"
    assert [(c.get("Min"), c.get("Max"), c.text) for c in unknown.findall("{*}Capability")] == [("0", "255", "aura_ring")]
    assert channels["Pan"].get("Default") == "128"


def test_physical_block(library):
    root = _root(fixture_definition_xml(library.get("test_mover")))
    physical = root.find("{*}Physical")
    assert physical.find("{*}Bulb").attrib["Lumens"] == "3850"
    assert physical.find("{*}Dimensions").attrib == {"Weight": "5.5", "Width": "300", "Height": "400", "Depth": "200"}
    assert physical.find("{*}Lens").attrib["DegreesMax"] == "58"
    assert physical.find("{*}Focus").attrib == {"Type": "Head", "PanMax": "540", "TiltMax": "230"}


def test_sixteen_bit_dimmer_and_hazer_types(library):
    wide = _root(fixture_definition_xml(library.get("test_pc")))
    modes = {m.get("Name"): [c.text for c in m] for m in wide.findall("{*}Mode")}
    assert modes["Wide"] == ["Intensité", "Intensité fin"]
    assert {c.get("Name"): c.get("Preset") for c in wide.findall("{*}Channel")}["Intensité fin"] == "IntensityDimmerFine"
    assert _root(fixture_definition_xml(library.get("test_hazer"))).find("{*}Type").text == "Hazer"
    cct = next(c for c in wide.findall("{*}Channel") if c.get("Name") == "Température de couleur")
    assert cct.find("{*}Capability").text == "Température de couleur 2700-6500 K"


def test_link_reuses_the_qlc_definition(library, qlc_dir, tmp_path):
    patch = (PatchedFixture("Aura_01", "test_aura", "Std", 1, 1, "Backlight", (128, 0, 64, 0)),)
    result = export_workspace(patch, library, tmp_path / "out", [qlc_dir])
    assert result.written_qxf == () and result.warnings == ()
    assert result.reused_qxf == (str(qlc_dir / "Martin" / "Martin-MAC-Aura.qxf"),)
    fixture = _fixtures(ET.fromstring(result.workspace.read_text(encoding="utf-8").split("\n", 2)[2]))[0]
    assert (fixture["Manufacturer"], fixture["Model"], fixture["Mode"], fixture["Channels"]) == (
        "Martin", "MAC Aura", "Standard", "3")
    root = _root(workspace_xml(patch, library, [qlc_dir]))
    assert next(root.iterfind(".//{*}Palette")).get("Value") == "271,58"  # 128/255 * 539, 64/255 * 231


def test_unmatched_mode_generates_a_renamed_definition(library, qlc_dir, tmp_path):
    patch = (PatchedFixture("Aura_01", "test_aura", "Odd", 1, 1, None),)
    result = export_workspace(patch, library, tmp_path / "out", [qlc_dir])
    assert [p.name for p in result.written_qxf] == ["Martin-MAC-Aura-(theatre_stage).qxf"]
    assert result.reused_qxf == ()
    assert any("« Odd » absent de la définition QLC+" in w for w in result.warnings)
    assert any("renommé" in w for w in result.warnings)
    fixture = _fixtures(_root(workspace_xml(patch, library, [qlc_dir])))[0]
    assert fixture["Model"] == "MAC Aura (theatre_stage)" and fixture["Mode"] == "Odd"


def test_link_without_verification_is_not_used(library, qlc_dir):
    aura = library.get("test_aura")
    unverified = replace(aura, qlc=replace(aura.qlc, verified=None))
    lib = Library({**library.fixtures, "test_aura": unverified})
    patch = (PatchedFixture("Aura_01", "test_aura", "Std", 1, 1, None),)
    result = export_workspace(patch, lib, Path(qlc_dir).parent / "out2", [qlc_dir])
    assert result.reused_qxf == () and len(result.written_qxf) == 1
    assert any("sans correspondance QLC+ vérifiée" in w for w in result.warnings)


def test_missing_qlc_definition_falls_back_to_generation(library, tmp_path):
    patch = (PatchedFixture("Aura_01", "test_aura", "Std", 1, 1, None),)
    result = export_workspace(patch, library, tmp_path / "out", [tmp_path / "nowhere"])
    assert [p.name for p in result.written_qxf] == ["Martin-MAC-Aura.qxf"]
    assert any("introuvable" in w for w in result.warnings)


def test_refused_placements_are_reported(library, tmp_path):
    patch = (
        PatchedFixture("A", "test_pc", "2 Ch", 1, 1, None),
        PatchedFixture("B", "test_pc", "2 Ch", 1, 2, None),
        PatchedFixture("C", "test_pc", "2 Ch", 1, 512, None),
        PatchedFixture("D", "nope", "x", 1, 20, None),
        PatchedFixture("E", "test_pc", "nope", 1, 30, None),
        PatchedFixture("F", "test_pc", "2 Ch", 2, 1, None),
    )
    result = export_workspace(patch, library, tmp_path)
    assert [f["Name"] for f in _fixtures(ET.parse(result.workspace).getroot())] == ["A", "F"]
    joined = " | ".join(result.warnings)
    assert "« B » : recouvre « A »" in joined
    assert "« C »" in joined and "hors limites" in joined
    assert "fiche « nope » introuvable" in joined and "mode « nope » inconnu" in joined


def test_export_writes_deterministic_files_beside_the_workspace(library, tmp_path):
    first = export_workspace(PATCH, library, tmp_path / "a")
    second = export_workspace(PATCH, library, tmp_path / "b")
    assert first.workspace.name == WORKSPACE_NAME
    assert sorted(p.name for p in first.written_qxf) == [
        "Test-Hazer.qxf", "Test-Mover.qxf", "Test-PC-LED.qxf"]
    for path in first.written_qxf + (first.workspace,):
        twin = tmp_path / "b" / path.name
        assert path.read_bytes() == twin.read_bytes()
        assert b"\r" not in path.read_bytes()
        ET.parse(path)
    assert second.warnings == first.warnings == ()


def test_definition_filename_matches_the_qlc_fallback_rule():
    assert definition_filename("Martin", "MAC Aura") == "Martin-MAC-Aura.qxf"
    assert definition_filename("A B", "C/D") == "A-B-C-D.qxf"


def test_golden_workspace(library):
    patch = (PatchedFixture("Mover_01", "test_mover", "Basic", 1, 1, "Movers", (128, 0, 64, 0)),
             PatchedFixture("PC_01", "test_pc", "2 Ch", 1, 4, "Circuit_A", None, ((1, 255), (2, 64))))
    assert workspace_xml(patch, library) == (DATA / "golden_workspace.qxw").read_text(encoding="utf-8")


def test_golden_definition(library):
    assert fixture_definition_xml(library.get("test_pc")) == (DATA / "golden_pc.qxf").read_text(encoding="utf-8")


def test_shipped_fiches_export_to_valid_xml(tmp_path):
    shipped = discover([SHIPPED_DIR])
    assert len(shipped) >= 4
    patch, address = [], 1
    for fixture in shipped.fixtures.values():
        patch.append(PatchedFixture(fixture.id, fixture.id, fixture.default_mode, 1, address, None))
        address += fixture.footprint()
        if address > 400:
            break
    result = export_workspace(patch, shipped, tmp_path)
    assert result.warnings == ()
    for path in result.written_qxf + (result.workspace,):
        ET.parse(path)
    for qxf in result.written_qxf:
        root = ET.parse(qxf).getroot()
        names = [c.get("Name") for c in root.findall("{*}Channel")]
        assert len(names) == len(set(names))
        for mode in root.findall("{*}Mode"):
            channel_names = [c.text for c in mode]
            assert len(channel_names) == len(set(channel_names)) and set(channel_names) <= set(names)


# ---------------------------------------------------------- rig to QLC+

def test_blade_swivel_and_second_gobo_rotation_have_their_own_channels():
    root = _root(fixture_definition_xml(default_library().get("robe_robin_esprite")))
    channels = {c.get("Name"): c for c in root.findall("{*}Channel")}
    for k in range(1, 5):
        assert channels[f"Pivotement lame {k}"].find("{*}Group").text == "Beam"
    assert channels["Rotation gobo 2"].get("Preset") == "GoboIndex"
    assert channels["Rotation gobo 2 fin"].get("Preset") == "GoboIndexFine"
    assert channels["Rotation des lames"].find("{*}Group").text == "Beam"


def test_patched_from_rig_follows_the_computed_patch():
    rig = compute_layout(default_params()).rig
    patched = patched_from_rig(rig)
    assert len(patched) == len(rig.fixtures) == 33
    for item, entry in zip(patched, rig.patch):
        assert (item.name, item.universe, item.address) == (entry.name, entry.universe, entry.address)
    by_name = {p.name: p for p in patched}
    assert by_name["FrontPC_L_01"].group == "FrontPC_Row1_L"
    assert by_name["Backlight_01"].group == "Backlight" and by_name["Profile_C"].pan_tilt is None
    assert by_name["Backlight_01"].pan_tilt is not None


def test_patched_from_rig_rest_bytes_are_offsets_from_the_address():
    rig = compute_layout(default_params()).rig
    for item, f in zip(patched_from_rig(rig), rig.fixtures):
        expected = {}
        for cv in f.channels:
            if f.moving and cv.attribute in ("pan", "tilt"):
                continue
            channels = (cv.channel,) if cv.fine_channel is None else (cv.channel, cv.fine_channel)
            expected.update({c - f.address + 1: b for c, b in zip(channels, cv.data)})
        assert dict(item.rest_bytes) == expected
        assert all(1 <= o <= f.footprint and 0 <= b <= 255 for o, b in item.rest_bytes)
    dimmer = next(c for c in rig.find("Profile_C").channels if c.attribute == "dimmer")
    item = {p.name: p for p in patched_from_rig(rig)}["Profile_C"]
    assert (dimmer.channel - rig.find("Profile_C").address + 1, round(255 * 0.7)) in item.rest_bytes


def test_inverted_pan_tilt_palette_reproduces_the_rest_bytes_in_qlc():
    rig = compute_layout(default_params()).rig
    library = default_library()
    assert library.get("martin_mac_aura").motion.pan.invert
    root = _root(workspace_xml(patched_from_rig(rig), library))
    palettes = {p.get("Name"): [int(v) for v in p.get("Value").split(",")] for p in root.iterfind(".//{*}Palette")}
    item = {p.name: p for p in patched_from_rig(rig)}["Backlight_01"]
    pan_c, pan_f, tilt_c, tilt_f = item.pan_tilt
    motion = library.get("martin_mac_aura").motion
    for degrees, (coarse, fine), rng in ((palettes["Repos_Backlight_01"][0], (pan_c, pan_f), motion.pan),
                                         (palettes["Repos_Backlight_01"][1], (tilt_c, tilt_f), motion.tilt)):
        # QLC+ sends degrees * 65535 / travel as DMX, with no notion of inverted axes.
        sent = degrees * 65535 / (rng.max - rng.min)
        assert abs(sent - (coarse * 256 + fine)) <= 65535 / (rng.max - rng.min)


def test_full_rig_exports_without_warning(tmp_path):
    rig = compute_layout(default_params()).rig
    result = export_workspace(patched_from_rig(rig), default_library(), tmp_path)
    assert result.warnings == ()


def test_existing_fixture_dirs_keeps_only_folders_that_exist(tmp_path):
    from core.qlc import existing_fixture_dirs

    program, home = tmp_path / "program", tmp_path / "home"
    assert existing_fixture_dirs(program, home) == ()
    (program / "Fixtures").mkdir(parents=True)
    assert existing_fixture_dirs(program, home) == (program / "Fixtures",)
    (home / "QLC+" / "Fixtures").mkdir(parents=True)
    assert existing_fixture_dirs(program, home) == (program / "Fixtures", home / "QLC+" / "Fixtures")
