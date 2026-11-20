"""Driver expressions of `rigbuild` for every shipped fiche and mode, against a recording `bpy` stub."""

import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.layout import compute_layout
from core.rig import default_library

PACKAGE = Path(__file__).resolve().parent.parent / "blender" / "theatre_stage"
LIB = default_library()
GROUPS = {"moving_wash": ("front_movers", "tower_movers"), "moving_profile": ("front_movers", "tower_movers"),
          "pc": ("front_pc",), "profile": ("profiles",)}
DRIVEN = {"front_movers": "front_movers", "tower_movers": "towers", "front_pc": "front_pc", "profiles": "profiles"}
MAX_EXPRESSION = 255


class _Stub:
    def __init__(self, *args, **kwargs):
        pass


class _StubModule(types.ModuleType):
    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return _Stub


class _Recorder:
    """Owner whose `driver_add` records the expressions it is given."""

    def __init__(self, store: dict):
        self.store = store

    def driver_add(self, path, index=-1):
        driver = SimpleNamespace(variables=SimpleNamespace(new=lambda: SimpleNamespace(
            targets=[SimpleNamespace()])), expression="")
        self.store[(path, index, len(self.store))] = driver
        keys = SimpleNamespace(insert=lambda x, y: SimpleNamespace(interpolation=""))
        return SimpleNamespace(driver=driver, modifiers=[], keyframe_points=keys)


class _Root(dict, _Recorder):
    def __init__(self, values, store):
        dict.__init__(self, values)
        self.store = store


@pytest.fixture(scope="module")
def rigbuild():
    saved = {k: sys.modules.get(k) for k in ("bpy", "bpy.types", "bpy.props", "mathutils", "theatre_stage")}
    bpy = _StubModule("bpy")
    bpy.types, bpy.props = _StubModule("bpy.types"), _StubModule("bpy.props")
    package = types.ModuleType("theatre_stage")
    package.__path__ = [str(PACKAGE)]
    sys.modules.update({"bpy": bpy, "bpy.types": bpy.types, "bpy.props": bpy.props,
                        "mathutils": _StubModule("mathutils"), "theatre_stage": package})
    from theatre_stage import rigbuild as module  # noqa: PLC0415
    yield module
    for key in [k for k in sys.modules if k.startswith("theatre_stage")]:
        del sys.modules[key]
    for key, value in saved.items():
        if value is None:
            sys.modules.pop(key, None)
        else:
            sys.modules[key] = value


def _cases():
    for fixture_id, fx in LIB.fixtures.items():
        for family in GROUPS.get(fx.family, ()):
            for mode in fx.modes:
                yield pytest.param(fixture_id, family, mode.name, id=f"{fixture_id}-{family}-{mode.name}")


@pytest.mark.parametrize(("fixture_id", "family", "mode"), _cases())
def test_driver_expressions_fit_blender_limit(rigbuild, fixture_id, family, mode):
    group = DRIVEN[family]
    raw = {group: {"fixture": fixture_id, "mode": mode}}
    if group == "towers":
        raw["towers"]["left"] = {"count": 1, "movers": 1}
    rig = compute_layout(raw, LIB).rig
    f = rig.by_family(family)[0]
    fx = LIB.get(fixture_id)
    tube = next((t for t in fx.optics.lens_tubes if t.name == f.tube), None)
    store: dict = {}
    ctx = rigbuild._Build(None, None, None, None, LIB).for_fixture(f, fx, None, tube)
    ctx.root = _Root(rigbuild._settings(ctx), store)
    owner = _Recorder(store)
    light = SimpleNamespace(data=owner)
    if f.moving:
        rigbuild._drive_pose(ctx, owner, owner)
    rigbuild._drive_root(ctx)
    rigbuild._drive_light(ctx, light)
    rigbuild._drive_lens(ctx, owner)
    assert store
    assert max(len(d.expression) for d in store.values()) <= MAX_EXPRESSION
