"""Face equalisation applied to the rig (spec 13.13): adapter, signature, stored result, rest levels, panel."""

import pytest

from core.face_rig import USEFUL_MARGIN, FaceEq, emitters_of, equalise_rig, probes_of, signature
from core.layout import STALE_FACE_EQ, compute_layout
from core.qlc import patched_from_rig
from core.rig import default_library, head_frame
from core.rigpanel import face_eq_lines
from helpers import make

LIB = default_library()
RATIO = 0.85


@pytest.fixture(scope="module")
def plain():
    return compute_layout(make(), LIB)


@pytest.fixture(scope="module")
def eq(plain):
    return equalise_rig(plain.rig, LIB, RATIO)


def faces(rig):
    return rig.by_family("front_pc")


def test_adapter_builds_one_emitter_per_face_pc_with_its_geometry(plain):
    emitters = emitters_of(plain.rig, LIB)
    assert [e.name for e in emitters] == [f.name for f in faces(plain.rig)]
    for e, f in zip(emitters, faces(plain.rig)):
        assert e.direction == f.name.split("_")[1] and e.row == int(f.circuit.split("Row")[1][0]) - 1
        assert e.source == f.source and e.axis == f.axis and e.aim_z == f.aim[2] and e.zoom_field == f.field_angle
        assert e.up == head_frame(f.pan, f.tilt)[0] and e.lens_radius > 0.0


def test_adapter_holds_the_zoom_of_a_mode_without_zoom_channel(plain):
    rig = compute_layout(make(front_pc={"mode": "Dimmer 16 bit + CCT + Zoom"}), LIB).rig
    first, far = emitters_of(rig, LIB)[0], emitters_of(rig, LIB)[-1]
    assert first.zoom_range == (13.0, 54.4)
    assert far.zoom_range == (far.zoom_field, far.zoom_field)


def test_adapter_turns_every_leaf_into_an_edge_facing_the_lit_side(plain):
    for e, f in zip(emitters_of(plain.rig, LIB), faces(plain.rig)):
        assert len(e.cut_edges) == len(f.barn_doors.leaves) == 4
        closed = [(edge, leaf) for edge, leaf in zip(e.cut_edges, f.barn_doors.leaves) if leaf.normal]
        for edge, leaf in closed:
            assert edge.normal == pytest.approx(tuple(-c for c in leaf.normal), abs=1e-6)


def test_no_barn_doors_no_edges():
    rig = compute_layout(make(front_pc={"barn_doors": "none"}), LIB).rig
    assert all(not e.cut_edges for e in emitters_of(rig, LIB))


def test_signature_is_stable_and_follows_the_inputs(plain):
    base = signature(plain.rig, RATIO)
    assert signature(compute_layout(make(), LIB).rig, RATIO) == base
    assert signature(plain.rig, 0.9) != base
    for groups in ({"front_pc": {"zone_width": 2.0}}, {"front_pc": {"barn_doors": "none"}},
                   {"front_pc": {"mode": "Dimmer 16 bit + CCT + Zoom"}}, {"rig": {"aim_height": 1.5}},
                   {"front_pc": {"barn_doors": "manual", "row1_l_leaf_1": 10.0}}):
        assert signature(compute_layout(make(**groups), LIB).rig, RATIO) != base, groups


def test_signature_ignores_levels_and_colour(plain):
    other = compute_layout(make(rest={"pc_level": 0.3, "cct_left": 4000}), LIB).rig
    assert signature(other, RATIO) == signature(plain.rig, RATIO)


def test_equalisation_is_stored_as_json_and_read_back(eq):
    again = FaceEq.from_json(eq.to_json())
    assert again == eq and len(eq.adjustments) == 16
    for text in (None, "", "{", '{"version": 99}', '{"version": 1}'):
        assert FaceEq.from_json(text) is None


def test_equalisation_improves_each_direction_and_the_sum(eq):
    assert set(eq.before) == {"L", "R", "sum"}
    assert all(eq.after[k].cv < eq.before[k].cv and eq.after[k].uniformity > eq.before[k].uniformity for k in eq.before)
    assert all(eq.after[k].below < eq.before[k].below for k in eq.before)
    assert eq.mean_ratio["sum"] >= RATIO - 0.01 and all(0.0 <= a.level <= 1.0 for a in eq.adjustments)


def test_no_face_pc_cannot_be_equalised():
    rig = compute_layout(make(front_pc={"enabled": False}), LIB).rig
    with pytest.raises(ValueError):
        equalise_rig(rig, LIB, RATIO)


def test_matching_result_sets_aim_field_and_level_of_each_face_pc(plain, eq):
    layout = compute_layout(make(), LIB, eq)
    assert layout.face_eq_state == "applied" and layout.rig.equalised and STALE_FACE_EQ not in layout.warnings
    assert not any("nez" in w or "couverte" in w for w in layout.warnings)
    by_name = eq.by_name()
    for f, before in zip(faces(layout.rig), faces(plain.rig)):
        adj = by_name[f.name]
        assert f.axis == pytest.approx(adj.axis, abs=1e-9) and f.field_angle == pytest.approx(adj.zoom_field)
        dimmer = next(cv for cv in f.channels if cv.attribute == "dimmer")
        assert dimmer.value == pytest.approx(0.7 * adj.level)
        assert f.hang == before.hang and f.fixture_id == before.fixture_id


def test_rest_level_multiplies_the_equalised_level(eq):
    layout = compute_layout(make(rest={"pc_level": 0.5}), LIB, eq)
    assert layout.face_eq_state == "applied"
    for f in faces(layout.rig):
        dimmer = next(cv for cv in f.channels if cv.attribute == "dimmer")
        assert dimmer.value == pytest.approx(0.5 * eq.by_name()[f.name].level)


def test_stale_result_keeps_the_plain_focus_and_warns(eq):
    groups = {"front_pc": {"zone_width": 2.0}}
    layout = compute_layout(make(**groups), LIB, eq)
    reference = compute_layout(make(**groups), LIB)
    assert layout.face_eq_state == "stale" and not layout.rig.equalised and STALE_FACE_EQ in layout.warnings
    assert [f.axis for f in faces(layout.rig)] == [f.axis for f in faces(reference.rig)]
    assert layout.warnings == reference.warnings + (STALE_FACE_EQ,)


def test_nothing_stored_nothing_said(plain):
    assert plain.face_eq_state == "" and plain.face_eq is None and not plain.rig.equalised
    assert STALE_FACE_EQ not in plain.warnings


def test_stored_result_is_ignored_silently_when_the_rig_is_off(eq):
    layout = compute_layout(make(rig={"enabled": False}), LIB, eq)
    assert layout.face_eq_state == "" and STALE_FACE_EQ not in layout.warnings


def test_qlc_marks_the_face_pcs_of_an_equalised_rig_only(plain, eq):
    assert not any(p.face for p in patched_from_rig(plain.rig))
    applied = compute_layout(make(), LIB, eq).rig
    flagged = [p.name for p in patched_from_rig(applied) if p.face]
    assert flagged == [f.name for f in faces(applied)]


def test_panel_lines_per_state(plain, eq):
    assert face_eq_lines(plain) == []
    applied = "\n".join(face_eq_lines(compute_layout(make(), LIB, eq)))
    for expected in ("Face égalisée le ", "Jardin : P10/moy ", "Cour : P10/moy ", "Somme : P10/moy ", "CV ", "→", "lx",
                     "Emin/Emoy"):
        assert expected in applied
    stale = face_eq_lines(compute_layout(make(front_pc={"zone_width": 2.0}), LIB, eq))
    assert len(stale) == 1 and stale[0].startswith("Égalisation de la face périmée le ")



def test_useful_grid_stays_inside_the_intended_cuts(plain):
    face, probes = plain.rig.face, probes_of(plain.rig)
    assert {p.position[2] for p in probes} == {face.z, face.z_torso} and face.z_torso == face.z - 0.5
    assert probes and min(p.position[1] for p in probes) >= USEFUL_MARGIN
    for p in probes:
        half = (face.nose_width if p.position[1] < face.forestage_depth else face.frame_width) / 2
        assert abs(p.position[0]) <= half - USEFUL_MARGIN + 1e-9 and p.position[1] <= face.area_depth


def test_forestage_is_wanted_as_wide_as_the_frame_when_a_row_0_pc_cuts_on_the_post(plain):
    outside = [f for f in faces(plain.rig) if f.circuit.endswith("Row1_L") or f.circuit.endswith("Row1_R")]
    assert any(abs(f.hang[0]) > plain.rig.face.frame_width / 2 for f in outside)
    assert plain.rig.face.nose_width == plain.rig.face.frame_width
    inside = compute_layout(make(stage={"width": 14.0}), LIB).rig
    assert inside.face.nose_width >= inside.face.frame_width
