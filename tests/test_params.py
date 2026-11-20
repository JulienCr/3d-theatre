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


def test_driver_only_params_are_the_ones_that_skip_rebuild():
    animatable = [path for path, p in P.iter_params() if p.animatable]
    no_rebuild = [path for path, p in P.iter_params() if not p.rebuild]
    assert animatable == [("curtains", "main_opening"), ("haze", "density")]
    assert no_rebuild == animatable + [("haze", "anisotropy")]


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


def test_every_material_category_has_a_french_label_and_is_used_by_the_layout():
    from core.layout import MATERIAL_COLORS, MATERIAL_LABELS
    from helpers import layout
    assert set(MATERIAL_LABELS) == set(MATERIAL_COLORS)
    assert all(label and label[0].isupper() for label in MATERIAL_LABELS.values())
    used = {o.material for o in layout(stairs={"center": True}).objects}
    assert used <= set(MATERIAL_LABELS)


def test_haze_extent_item_order_is_pinned_for_stored_values_and_the_material_driver():
    extent = next(p for p in P.GROUPS["haze"].params if p.key == "extent")
    assert [item[0] for item in extent.items] == ["stage", "stage_and_house"]
    assert extent.default == "stage_and_house"


# ------------------------------------------------------- lighting groups

LIGHTING_GROUPS = ["rig", "rig_front", "backlight", "front_movers", "towers", "front_pc",
                   "profiles", "rest", "patch"]


def test_lighting_groups_follow_the_panel_order_of_the_spec():
    keys = [g.key for g in P.SCHEMA]
    start = keys.index("rig")
    assert keys[start:start + len(LIGHTING_GROUPS)] == LIGHTING_GROUPS
    assert keys.index("cameras") < start and "haze" in keys and "house" in keys


def test_lighting_defaults_match_the_spec_tables():
    d = P.default_params()
    assert d["rig"] == {"enabled": True, "aim_height": 1.7, "site": 44.0, "area_depth": 6.0}
    assert d["rig_front"] == {"ceiling_gap": 0.3, "auto_position": True, "y": -1.4, "movers_offset": 1.5,
                              "movers_height_mode": "auto", "movers_z": 6.8}
    assert d["backlight"] == {"enabled": True, "fixture": "martin_mac_aura", "mode": "default",
                              "count": 6, "position": "upstage", "distance": 3.1}
    assert (d["front_movers"]["fixture"], d["front_movers"]["count"]) == ("robe_robin_esprite", 4)
    assert d["front_pc"]["fixture"] == "generic_pc_led" and d["front_pc"]["azimuth"] == 16.0
    assert d["front_pc"]["zone_width"] == 3.4
    assert (d["front_pc"]["zone_mode"], d["front_pc"]["columns"], d["front_pc"]["rows"]) == ("auto", 3, 2)
    assert d["profiles"]["fixture"] == "etc_s4led_s3_lustr_x8" and d["profiles"]["blades_mode"] == "auto"
    pc = d["front_pc"]
    assert pc["barn_doors"] == "auto" and len([k for k in pc if k.startswith("row") and k != "rows"]) == 4 * 2 * 5
    assert pc["row3_r_leaf_4"] == 0.0 and pc["row4_l_rotation"] == 0.0
    assert d["rest"] == {"pc_level": 0.7, "profile_level": 0.7, "mover_level": 0.5, "haze_level": 1.0,
                         "cct_left": 3200, "cct_right": 5600, "cct_profile": 4000}
    assert d["haze"]["dmx_driven"] is False and d["haze"]["fixture"] == "generic_hazer"
    assert d["towers"]["left"] == {"count": 1, "first_distance": 3.0, "spacing": 2.0,
                                   "height": 4.5, "movers": 2}
    assert d["towers"]["left"] == d["towers"]["right"] and d["towers"]["symmetric"] is True


def test_patch_declares_one_universe_and_address_per_family():
    patch = P.default_params()["patch"]
    assert [f[0] for f in P.PATCH_FAMILIES] == ["backlight", "front_movers", "tower_movers",
                                                "front_pc", "profiles", "hazer"]
    assert [patch[f"{f}_universe"] for f, *_ in P.PATCH_FAMILIES] == [1, 2, 3, 4, 5, 6]
    assert all(patch[f"{f}_address"] == 1 for f, *_ in P.PATCH_FAMILIES)
    assert len(patch) == 12


def test_profile_manual_blades_are_declared_by_loop_for_three_profiles_and_four_blades():
    keys = [p.key for p in P.GROUPS["profiles"].params]
    for side in "lcr":
        assert f"{side}_rotation" in keys
        for blade in range(1, 5):
            assert f"{side}_blade_{blade}_insertion" in keys and f"{side}_blade_{blade}_angle" in keys
    assert len([k for k in keys if "_blade_" in k]) == 24


def test_fixture_and_mode_params_are_dynamic_with_the_families_of_the_spec():
    expected = {"backlight": ("moving_wash",), "front_movers": ("moving_wash", "moving_profile"),
                "towers": ("moving_wash", "moving_profile"), "front_pc": ("pc",),
                "profiles": ("profile",), "haze": ("hazer",)}
    for key, families in expected.items():
        by_key = {p.key: p for p in P.GROUPS[key].params}
        for suffix in ("_far",) if key == "front_pc" else ():
            assert by_key[f"fixture{suffix}"].families == families
            assert by_key[f"mode{suffix}"].depends_on == f"fixture{suffix}"
            assert by_key["fixture_far"].default == "generic_fresnel_led"
        for suffix in ("", "_far") if key == "front_pc" else ("",):
            assert by_key[f"fixture{suffix}"].kind == P.FIXTURE and by_key[f"fixture{suffix}"].families == families
            assert by_key[f"mode{suffix}"].kind == P.MODE and by_key[f"mode{suffix}"].depends_on == f"fixture{suffix}"
            assert by_key[f"fixture{suffix}"].is_dynamic and by_key[f"mode{suffix}"].default == "default"
    assert sorted({g.key for g in P.SCHEMA for p in g.params if p.kind == P.FIXTURE}) == sorted(expected)


def test_shown_when_points_at_a_sibling_with_a_valid_value():
    for group in P.SCHEMA:
        by_key = {p.key: p for p in group.params}
        for param in group.params:
            if param.shown_when:
                sibling, value = param.shown_when
                assert sibling in by_key, (group.key, param.key)
                if by_key[sibling].kind == P.ENUM:
                    assert value in [item[0] for item in by_key[sibling].items]


def test_side_sets_serve_towers_like_modules():
    towers = P.default_params()["towers"]
    towers["left"]["count"] = 3
    towers["right"]["count"] = 2
    assert P.side_sets(towers)[1]["count"] == 3
    towers["symmetric"] = False
    assert P.side_sets(towers)[1]["count"] == 2 and P.module_sets is P.side_sets


def test_fixture_values_must_be_text():
    params, warnings = P.validate_params({"backlight": {"fixture": 3, "mode": ""}})
    assert params["backlight"]["fixture"] == "martin_mac_aura" and params["backlight"]["mode"] == "default"
    assert len(warnings) == 2


def library_of_one_profile():
    from pathlib import Path
    from core import fixtures
    return fixtures.discover([Path(__file__).parent / "data" / "fixtures"])


def test_unknown_fixture_and_mode_fall_back_to_defaults_with_a_warning():
    library = library_of_one_profile()
    raw = {"front_movers": {"fixture": "test_mover", "mode": "Basic"},
           "backlight": {"fixture": "ghost_light"},
           "front_pc": {"fixture": "test_mover"},
           "towers": {"fixture": "test_mover", "mode": "Turbo"}}
    params, warnings = P.validate_params(raw, library)
    assert params["front_movers"]["fixture"] == "test_mover" and params["front_movers"]["mode"] == "Basic"
    assert params["backlight"]["fixture"] == "martin_mac_aura"
    assert params["front_pc"]["fixture"] == "generic_pc_led"  # wrong family
    assert params["towers"]["fixture"] == "test_mover" and params["towers"]["mode"] == "default"
    text = "\n".join(warnings)
    assert "ghost_light" in text and "test_mover" in text and "Turbo" in text and len(warnings) == 3


def test_missing_default_sheet_is_not_reported_by_every_preset():
    from core import fixtures
    params, warnings = P.validate_params({}, fixtures.EMPTY_LIBRARY)
    assert warnings == [] and params == P.default_params()
    _, warnings = P.validate_params({"backlight": {"fixture": "ghost"}}, fixtures.EMPTY_LIBRARY)
    assert len(warnings) == 1


def test_without_a_catalog_fixture_ids_are_kept_as_written():
    params, warnings = P.validate_params({"backlight": {"fixture": "anything", "mode": "X"}})
    assert params["backlight"]["fixture"] == "anything" and warnings == []
