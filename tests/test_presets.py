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
