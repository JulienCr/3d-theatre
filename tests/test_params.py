import re

from core import params as P


def test_defaults_are_within_declared_bounds():
    for path, param in P.iter_params():
        if param.is_numeric:
            assert param.min <= param.default <= param.max, path
        if param.kind == P.ENUM:
            assert param.default in [item[0] for item in param.items], path
        if param.kind == P.BOOL_VECTOR:
            assert len(param.default) == param.length, path


def test_keys_are_ascii_english_identifiers_and_texts_are_filled():
    for path, param in P.iter_params():
        assert all(re.fullmatch(r"[a-z][a-z0-9_]*", part) for part in path), path
        assert param.label and param.tooltip, path
    assert all(g.label for g in P.SCHEMA)


def test_default_params_is_nested_like_the_yaml_and_fresh_each_call():
    a, b = P.default_params(), P.default_params()
    assert a == b and a is not b and a["stage"] is not b["stage"]
    assert set(a["modules"]) == {"symmetric", "left", "right"}
    assert a["modules"]["left"] == a["modules"]["right"]
    assert a["modules"]["left"] is not a["modules"]["right"]
    assert a["masking"]["borders"] == (True,) * 8


def test_only_main_opening_is_animatable_and_skips_rebuild():
    animatable = [path for path, p in P.iter_params() if p.animatable]
    no_rebuild = [path for path, p in P.iter_params() if not p.rebuild]
    assert animatable == no_rebuild == [("curtains", "main_opening")]


def test_advanced_group_is_flagged_collapsed():
    assert [g.key for g in P.SCHEMA if g.advanced] == ["advanced"]


def test_module_params_are_declared_once_for_both_sides():
    group = P.GROUPS["modules"]
    paths = [path for path, _ in P.iter_params() if path[0] == "modules" and len(path) == 3]
    assert len(paths) == 2 * len(group.side_params)


def test_missing_keys_take_defaults_silently():
    params, warnings = P.validate_params({"stage": {"width": 12.0}})
    assert params["stage"]["width"] == 12.0
    assert params["stage"]["depth"] == 7.0
    assert warnings == []


def test_unknown_keys_are_dropped_and_reported_at_every_level():
    raw = {"stage": {"colour": 1}, "ghost": {}, "modules": {"left": {"wings": 2}}}
    params, warnings = P.validate_params(raw)
    assert "colour" not in params["stage"] and "ghost" not in params
    assert "wings" not in params["modules"]["left"]
    text = "\n".join(warnings)
    assert "stage.colour" in text and "ghost" in text and "modules.left.wings" in text


def test_out_of_range_values_are_clamped_with_a_warning_both_ways():
    params, warnings = P.validate_params({"stage": {"width": 100.0, "depth": 0.0},
                                          "masking": {"lanes": 99}})
    assert params["stage"]["width"] == 30.0
    assert params["stage"]["depth"] == 3.0
    assert params["masking"]["lanes"] == 8
    assert len(warnings) == 3 and all("hors bornes" in w for w in warnings)


def test_wrong_types_fall_back_to_default_with_a_warning():
    raw = {"stage": {"width": "wide"}, "stairs": {"left": 1}, "masking": {"style": "gothic"}}
    params, warnings = P.validate_params(raw)
    assert params["stage"]["width"] == 11.6
    assert params["stairs"]["left"] is True
    assert params["masking"]["style"] == "italian"
    assert len(warnings) == 3


def test_integers_accept_integral_floats_but_not_booleans():
    params, warnings = P.validate_params({"masking": {"lanes": 4.0}})
    assert params["masking"]["lanes"] == 4 and not warnings
    params, warnings = P.validate_params({"masking": {"lanes": True}})
    assert params["masking"]["lanes"] == 3 and len(warnings) == 1


def test_bool_vector_is_padded_and_checked():
    params, warnings = P.validate_params({"masking": {"borders": [False, False]}})
    assert params["masking"]["borders"] == (False, False) + (True,) * 6
    assert len(warnings) == 1
    params, warnings = P.validate_params({"masking": {"borders": [1] * 8}})
    assert params["masking"]["borders"] == (True,) * 8 and warnings


def test_module_sets_mirror_left_when_symmetric():
    params = P.default_params()
    params["modules"]["left"]["height"] = 4.0
    params["modules"]["right"]["height"] = 3.0
    left, right = P.module_sets(params["modules"])
    assert left["height"] == right["height"] == 4.0
    params["modules"]["symmetric"] = False
    assert P.module_sets(params["modules"])[1]["height"] == 3.0
