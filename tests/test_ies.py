"""IES parser, lookups, zoom sets and the beam/field fallback profile (spec 13.13)."""

import math

import pytest

from core.fixtures import SHIPPED_DIR, ies_axis_candela
from core.ies import (
    IesTable, Photometry, ZoomSet, bake_ies, fallback_profile, load_ies, parse_ies,
)

PC_DIR = SHIPPED_DIR / "generic_pc_led" / "ies"
FRESNEL_DIR = SHIPPED_DIR / "generic_fresnel_led" / "ies"

HEADER = "IESNA:LM-63-2002\n[TEST] synthetic\nTILT=NONE\n"


def ies_text(vertical, horizontal, rows, multiplier=1.0, photometric=1):
    head = f"1 -1 {multiplier} {len(vertical)} {len(horizontal)} {photometric} 2 0.1 0.1 0.1\n1 1 100\n"
    body = " ".join(map(str, vertical)) + "\n" + " ".join(map(str, horizontal)) + "\n"
    return HEADER + head + body + "\n".join(" ".join(map(str, row)) for row in rows) + "\n"


def test_parse_symmetric_applies_multiplier_and_interpolates():
    table = parse_ies(ies_text([0, 45, 90], [0], [[1000, 500, 0]], multiplier=2))
    assert table.symmetric and table.axis_candela == 2000
    assert table.intensity(0) == pytest.approx(2000)
    assert table.intensity(22.5) == pytest.approx(1500)
    assert table.intensity(90) == pytest.approx(0)
    assert table.intensity(120) == 0.0


def test_parse_quadrant_symmetry_folds_phi():
    table = parse_ies(ies_text([0, 45, 90], [0, 90], [[100, 80, 0], [100, 40, 0]]))
    assert not table.symmetric
    assert table.intensity(45, 0) == pytest.approx(80)
    assert table.intensity(45, 90) == pytest.approx(40)
    assert table.intensity(45, 45) == pytest.approx(60)
    assert table.intensity(45, 180) == pytest.approx(80)
    assert table.intensity(45, 270) == pytest.approx(40)
    assert table.intensity(45, 135) == pytest.approx(60)
    assert table.intensity(45, -90) == pytest.approx(40)


def test_parse_include_tilt_block_is_skipped():
    text = "IESNA:LM-63-1995\nTILT=INCLUDE\n1\n2\n0 90\n1.0 0.5\n" + ies_text([0, 90], [0], [[10, 0]]).split("TILT=NONE\n")[1]
    assert parse_ies(text).axis_candela == 10


@pytest.mark.parametrize("text, message", [
    ("no tilt here", "TILT"),
    (HEADER + "1 -1 1 3 1 1 2 0 0 0\n1 1 1\n0 45\n", "illisible|tronqué"),
    (ies_text([0, 45, 90], [0], [[1, 1, 1]], photometric=2), "type C"),
    (ies_text([0, 45, 45], [0], [[1, 1, 1]]), "croissants"),
])
def test_parse_rejects_bad_files(text, message):
    with pytest.raises(ValueError, match=message):
        parse_ies(text)


def test_phi_is_free_for_a_symmetric_table():
    table = parse_ies(ies_text([0, 90], [0], [[10, 0]]))
    assert table.intensity(45, 0) == table.intensity(45, 123)


def test_shipped_pc_file_matches_axis_candela():
    path = PC_DIR / "t15_pc_zoom_96.ies"
    table = load_ies(path)
    assert table.axis_candela == pytest.approx(ies_axis_candela(path.read_text(encoding="latin-1")))
    assert table.symmetric and table.vertical[0] == 0 and table.vertical[-1] == 90
    assert table.intensity(10) == pytest.approx(table.candela[0][10])


def test_shipped_fresnel_file_is_a_full_turn_of_planes():
    path = FRESNEL_DIR / "f915vw_zoom_mid.ies"
    table = load_ies(path)
    assert table.axis_candela == pytest.approx(ies_axis_candela(path.read_text(encoding="latin-1")))
    assert table.horizontal[0] == 0 and table.horizontal[-1] == 360
    assert table.intensity(30, 360) == pytest.approx(table.intensity(30, 0))
    assert 0 < table.flux() < 20000


def pc_zoom_set() -> ZoomSet:
    pairs = [(13.1, 255), (23.7, 160), (35.0, 96), (47.7, 32), (54.5, 0)]
    return ZoomSet.of([(f, load_ies(PC_DIR / f"t15_pc_zoom_{dmx}.ies")) for f, dmx in pairs])


def half_angle_at(profile, fraction):
    """Theta where the intensity falls to `fraction` of the axis value (bisection on the outer slope)."""
    peak = profile.intensity(0.0)
    lo, hi = 0.0, 80.0
    for _ in range(50):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if profile.intensity(mid) > fraction * peak else (lo, mid)
    return lo


def test_zoom_set_reproduces_its_nodes():
    zoom = pc_zoom_set()
    for field, table in zoom.profiles:
        assert zoom.at(field).intensity(7.0) == pytest.approx(table.intensity(7.0))


def test_zoom_set_intermediate_keeps_the_field_edge():
    zoom = pc_zoom_set()
    for field in (18.0, 29.0, 41.0, 51.0):
        assert 2 * half_angle_at(zoom.at(field), 0.1) == pytest.approx(field, rel=0.08)


def test_zoom_set_axis_falls_as_the_field_opens():
    zoom = pc_zoom_set()
    axis = [zoom.at(f).intensity(0.0) for f in (14, 20, 30, 40, 50)]
    assert axis == sorted(axis, reverse=True)


def test_zoom_set_clamps_outside_the_range():
    zoom = pc_zoom_set()
    for field in (5.0, 80.0):
        value = zoom.at(field).intensity(3.0)
        assert math.isfinite(value) and value > 0


def test_zoom_set_rejects_unsorted_profiles():
    table = parse_ies(ies_text([0, 90], [0], [[10, 0]]))
    with pytest.raises(ValueError):
        ZoomSet(((30.0, table), (20.0, table)))


@pytest.mark.parametrize("beam, field", [(8.5, 13.0), (30.0, 50.0), (31.0, 54.4), (51.0, 83.8), (40.0, 41.0)])
def test_fallback_hits_beam_and_field_edges(beam, field):
    profile = fallback_profile(beam, field, 9000.0)
    effective_field = max(field, beam * 1.0618)
    assert profile.intensity(beam / 2) / profile.peak == pytest.approx(0.5, abs=1e-3)
    assert profile.intensity(effective_field / 2) / profile.peak == pytest.approx(0.1, abs=1e-3)
    assert profile.intensity(0.0) == profile.peak
    assert profile.intensity(profile.support + 1.0) == 0.0


@pytest.mark.parametrize("beam, field, flux", [(30.0, 50.0, 9566.0), (8.5, 13.0, 9566.0), (51.0, 83.8, 6792.0)])
def test_fallback_is_normalised_to_the_flux(beam, field, flux):
    profile = fallback_profile(beam, field, flux)
    steps, total = 20000, 0.0
    for i in range(steps):
        theta = math.radians(180.0 * (i + 0.5) / steps)
        total += profile.intensity(math.degrees(theta)) * math.sin(theta) * math.pi / steps
    assert 2 * math.pi * total == pytest.approx(flux, rel=2e-3)


def test_photometry_picks_ies_else_fallback():
    zoom = pc_zoom_set()
    with_ies = Photometry(9566.0, zoom)
    assert with_ies.profile(35.0, 20.0).intensity(0.0) == pytest.approx(zoom.at(35.0).intensity(0.0))
    assert Photometry(9566.0).profile(35.0, 20.0).intensity(10.0) == pytest.approx(
        fallback_profile(20.0, 35.0, 9566.0).intensity(10.0))


def test_table_type():
    assert isinstance(load_ies(PC_DIR / "t15_pc_zoom_0.ies"), IesTable)


@pytest.mark.parametrize("name", ["t15_pc_zoom_128.ies", "t15_pc_zoom_0.ies"])
def test_bake_returns_the_profile_once_the_lambert_cosine_is_divided_out(name):
    profile = ZoomSet.of([(30.0, load_ies(PC_DIR / name))]).at(30.0)
    baked = parse_ies(bake_ies(profile))
    for theta in (0.0, 5.0, 12.5, 20.0, 35.0, 60.0):
        assert baked.intensity(theta) * math.cos(math.radians(theta)) == pytest.approx(profile.intensity(theta), rel=2e-3, abs=1.0)
    assert baked.intensity(90.0) == 0.0 and baked.vertical[-1] == 90.0


def test_bake_keeps_the_planes_of_an_asymmetric_profile():
    table = parse_ies(ies_text([0.0, 90.0], [0.0, 180.0], [[100.0, 0.0], [50.0, 0.0]]))
    baked = parse_ies(bake_ies(ZoomSet.of([(40.0, table)]).at(40.0)))
    assert len(baked.horizontal) > 1 and baked.intensity(0.0, 0.0) > baked.intensity(0.0, 180.0)
