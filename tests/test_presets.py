import pytest

from core import presets
from core.layout import compute_layout
from core.params import default_params
from helpers import make


def test_roundtrip_of_a_modified_parameter_set():
    params = make(stage={"width": 13.5},
                  masking={"borders": (True, False) * 4, "backdrop": "cyclorama"},
                  curtains={"main_opening": 40.0})
    params["modules"]["symmetric"] = False
    params["modules"]["right"]["angle"] = 45.0
    loaded, warnings = presets.params_from_yaml(presets.params_to_yaml(params))
    assert warnings == []
    assert loaded == params


def test_yaml_starts_with_version_and_keeps_group_order():
    text = presets.params_to_yaml(default_params())
    assert text.startswith("version: 1\nstage:")


def test_missing_unknown_and_out_of_range_follow_the_load_rules():
    text = "version: 1\nstage:\n  width: 99\n  moon: 3\ncameras:\n  height: 4.0\n"
    params, warnings = presets.params_from_yaml(text)
    assert params["stage"]["width"] == 30.0
    assert params["stage"]["depth"] == 7.0
    assert params["cameras"]["height"] == 4.0
    assert any("moon" in w for w in warnings) and any("hors bornes" in w for w in warnings)


def test_unreadable_documents_raise_a_french_error():
    with pytest.raises(presets.PresetError, match="illisible"):
        presets.params_from_yaml("stage: [unclosed")
    with pytest.raises(presets.PresetError, match="dictionnaire"):
        presets.params_from_yaml("- 1\n- 2\n")


def test_unknown_version_is_reported():
    _, warnings = presets.params_from_yaml("version: 7\n")
    assert any("Version" in w for w in warnings)


def test_files_roundtrip(tmp_path):
    path = tmp_path / "mine.yaml"
    params = make(grid={"batten_spacing": 1.5})
    presets.write_preset(path, params)
    assert presets.read_preset(path) == (params, [])


def test_shipped_presets_are_in_sync_with_the_schema():
    shipped = presets.shipped_presets()
    assert set(shipped) == {"reference_with_modules", "open_space"}
    reference, warnings = presets.read_preset(shipped["reference_with_modules"])
    assert warnings == [] and reference == default_params()
    open_space, warnings = presets.read_preset(shipped["open_space"])
    assert warnings == []
    expected = default_params()
    expected["modules"]["left"]["enabled"] = expected["modules"]["right"]["enabled"] = False
    assert open_space == expected


def test_open_space_preset_builds_no_module():
    params, _ = presets.read_preset(presets.shipped_presets()["open_space"])
    assert not [n for n in compute_layout(params).names() if n.startswith("Module_")]


def test_roundtrip_of_the_lighting_groups():
    params = make(rig={"site": 40.0, "enabled": False}, rig_front={"auto_position": False, "y": -2.0},
                  backlight={"count": 8, "fixture": "some_wash", "mode": "Extended"},
                  profiles={"blades_mode": "manual", "l_blade_2_insertion": 0.5,
                            "c_blade_1_angle": -12.5, "r_rotation": 30.0},
                  rest={"cct_left": 2800}, patch={"profiles_universe": 9, "hazer_address": 17},
                  haze={"dmx_driven": True})
    params["towers"]["symmetric"] = False
    params["towers"]["right"].update(count=2, height=6.0)
    loaded, warnings = presets.params_from_yaml(presets.params_to_yaml(params))
    assert warnings == [] and loaded == params


def test_an_older_preset_without_lighting_groups_takes_the_defaults_silently():
    params, warnings = presets.params_from_yaml("version: 1\nstage:\n  width: 12\n")
    assert warnings == []
    assert params["patch"] == default_params()["patch"] and params["towers"] == default_params()["towers"]


def test_shipped_presets_carry_every_lighting_group_with_the_defaults():
    import yaml
    for path in presets.shipped_presets().values():
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        for key in ("rig", "rig_front", "backlight", "front_movers", "towers", "front_pc",
                    "profiles", "rest", "patch"):
            assert document[key] == default_params()[key], (path.name, key)
        assert document["haze"]["dmx_driven"] is False
        assert document["haze"]["fixture"] == "generic_hazer"


def test_unknown_fixture_in_a_preset_reverts_to_the_default_with_a_warning():
    from pathlib import Path
    from core import fixtures
    library = fixtures.discover([Path(__file__).parent / "data" / "fixtures"])
    text = "version: 1\nfront_movers:\n  fixture: ghost\n  count: 2\nprofiles:\n  fixture: test_mover\n"
    params, warnings = presets.params_from_yaml(text, catalog=library)
    assert params["front_movers"]["fixture"] == "robe_robin_esprite" and params["front_movers"]["count"] == 2
    assert params["profiles"]["fixture"] == "etc_s4led_s3_lustr_x8"  # test_mover is not a profile
    assert len(warnings) == 2 and "ghost" in warnings[0]
