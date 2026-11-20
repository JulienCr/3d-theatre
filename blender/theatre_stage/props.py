"""PropertyGroups generated from `core.params.SCHEMA`, on `Scene.theatre`.

Angles are stored in radians (subtype ANGLE) and converted to degrees when the
params dict is built. Nothing here names a parameter: the schema drives it all.
A FIXTURE or MODE param is stored as a string; the panel draws a `<key>_pick`
enum whose items come from the library (the stored id may be missing from it).
"""

from __future__ import annotations

import math
import traceback
from collections.abc import Mapping
from contextlib import contextmanager
from pathlib import Path

import bpy
from bpy.props import (
    BoolProperty, BoolVectorProperty, EnumProperty, FloatProperty, IntProperty,
    PointerProperty, StringProperty,
)

from . import build
from .core import fixtures
from .core import params as schema
from .core.params import Group, Param

SCENE_ATTR = "theatre"

REBUILD_DELAY = 0.15

_lock_depth = 0
_pending = False
_deferred_scene: str | None = None

_library = fixtures.EMPTY_LIBRARY
_item_pool: dict[tuple, tuple] = {}
_item_lists: dict[tuple, list] = {}


def library() -> fixtures.Library:
    """The fixture library read at load time or by `reload_library` (never read at draw time)."""
    return _library


def user_fixtures_dir(create: bool = False) -> Path:
    return Path(bpy.utils.extension_path_user(__package__, path="fixtures", create=create))


def reload_library() -> fixtures.Library:
    """Re-read the shipped then the user fixture folders. Its `messages` feed the alerts."""
    global _library
    _library = fixtures.discover([fixtures.SHIPPED_DIR, user_fixtures_dir()])
    return _library


def is_locked() -> bool:
    return _lock_depth > 0


def is_busy() -> bool:
    """True while a rebuild runs, is scheduled, or parameters are being applied."""
    return _lock_depth > 0 or _deferred_scene is not None or build.rebuilding


@contextmanager
def batch(scene, deferred: bool = False):
    """Silence rebuild callbacks; rebuild once on exit (through the timer if `deferred`)."""
    global _lock_depth, _pending
    _lock_depth += 1
    try:
        yield
    finally:
        _lock_depth -= 1
        if _lock_depth == 0 and _pending:
            _pending = False
            if deferred:
                schedule_rebuild(scene)
            else:
                rebuild_scene(scene)


def request_rebuild(scene) -> None:
    """Ask for a rebuild: remembered while locked, otherwise deferred to a timer."""
    global _pending
    if _lock_depth > 0:
        _pending = True
    else:
        schedule_rebuild(scene)


def schedule_rebuild(scene) -> None:
    """Coalesce update callbacks (a slider drag) into one timer-driven rebuild."""
    global _deferred_scene
    idle = _deferred_scene is None
    _deferred_scene = scene.name
    if idle:
        bpy.app.timers.register(_run_deferred, first_interval=REBUILD_DELAY)


def _run_deferred():
    global _deferred_scene
    name, _deferred_scene = _deferred_scene, None
    scene = bpy.data.scenes.get(name) if name else None
    if scene is not None:
        try:
            rebuild_scene(scene)
        except Exception:
            traceback.print_exc()
    return None


def rebuild_scene(scene) -> None:
    build.rebuild(scene, scene_params(scene))


# ------------------------------------------------------------ construction

def _make_property(param: Param, update):
    common = {"name": param.label, "description": param.tooltip, "update": update}
    kind = param.kind
    if kind == schema.LENGTH:
        return FloatProperty(default=param.default, min=param.min, max=param.max,
                             subtype="DISTANCE", unit="LENGTH", precision=3, **common)
    if kind == schema.ANGLE:
        lo, hi = param.min or 0.0, 360.0 if param.max is None else param.max
        return FloatProperty(default=math.radians(param.default), min=math.radians(lo),
                             max=math.radians(hi), subtype="ANGLE", unit="ROTATION", **common)
    if kind == schema.FLOAT:
        return FloatProperty(default=param.default, min=param.min, max=param.max,
                             precision=1, **common)
    if kind == schema.INT:
        return IntProperty(default=param.default, min=param.min, max=param.max, **common)
    if kind == schema.BOOL:
        return BoolProperty(default=param.default, **common)
    if kind == schema.ENUM:
        return EnumProperty(items=param.items, default=param.default, **common)
    if kind == schema.BOOL_VECTOR:
        return BoolVectorProperty(default=param.default, size=param.length, **common)
    if param.is_dynamic:
        return StringProperty(default=param.default, **common)
    raise ValueError(f"Unsupported parameter kind: {kind}")


def pick_name(param: Param) -> str:
    """Name of the UI enum that fronts a FIXTURE or MODE string property."""
    return f"{param.key}_pick"


def _dynamic_items(node, param: Param, group: Group) -> list[tuple[str, str, str]]:
    """Enum items of a FIXTURE or MODE param from the library, current value always included."""
    current = getattr(node, param.key)
    if param.kind == schema.FIXTURE:
        lib = library()
        items = [(i, lib.get(i).label, lib.get(i).family) for i in lib.ids_by_family(*param.families)]
    else:
        sheet = library().get(getattr(node, param.depends_on))
        items = [(fixtures.DEFAULT_MODE,
                  f"Défaut ({sheet.default_mode})" if sheet else "Défaut",
                  "Mode par défaut de la fiche.")]
        items += [(m.name, m.name, f"{m.footprint} canaux") for m in sheet.modes] if sheet else []
    if current not in {item[0] for item in items}:
        items.append((current, f"{current} (introuvable)", "Absent de la bibliothèque."))
    pooled = [_item_pool.setdefault(item, item) for item in items]
    _item_lists[(group.key, param.key)] = pooled
    return pooled


def _make_pick(group: Group, param: Param):
    def get(self) -> int:
        value = getattr(self, param.key)
        items = _dynamic_items(self, param, group)
        return next((i for i, item in enumerate(items) if item[0] == value), 0)

    def set_(self, index: int) -> None:
        items = _dynamic_items(self, param, group)
        if 0 <= index < len(items) and items[index][0] != getattr(self, param.key):
            setattr(self, param.key, items[index][0])

    return EnumProperty(name=param.label, description=param.tooltip,
                        items=lambda self, context: _dynamic_items(self, param, group),
                        get=get, set=set_)


def _tag_scene(self, context):
    """Driver-only params: flag the scene so the drivers that read it re-evaluate."""
    self.id_data.update_tag()


def _make_update(group: Group, param: Param):
    if not param.rebuild:
        return _tag_scene
    mirrors = group.side_params and param.key == "symmetric"
    modes = [p for p in group.params if p.kind == schema.MODE and p.depends_on == param.key]

    def update(self, context):
        scene = self.id_data
        if is_locked():
            request_rebuild(scene)
            return
        with batch(scene, deferred=True):
            if mirrors and not self.symmetric:
                _copy_set(self.left, self.right, group.side_params)
            for mode in modes:
                sheet = library().get(getattr(self, param.key))
                known = sheet.mode_names() if sheet else ()
                if getattr(self, mode.key) not in (fixtures.DEFAULT_MODE, *known):
                    setattr(self, mode.key, mode.default)
            request_rebuild(scene)

    return update


def _copy_set(source, target, params) -> None:
    for param in params:
        setattr(target, param.key, getattr(source, param.key))


def _group_class(name: str, group: Group, params, extra=None) -> type:
    annotations = {p.key: _make_property(p, _make_update(group, p)) for p in params}
    annotations.update({pick_name(p): _make_pick(group, p) for p in params if p.is_dynamic})
    annotations.update(extra or {})
    return type(name, (bpy.types.PropertyGroup,), {"__annotations__": annotations})


def _build_classes() -> tuple[list[type], type]:
    classes: list[type] = []
    root_fields = {}
    for group in schema.SCHEMA:
        extra = {}
        if group.side_params:
            side_cls = _group_class(f"THEATRE_PG_{group.key}_side", group, group.side_params)
            classes.append(side_cls)
            extra = {side: PointerProperty(type=side_cls) for side in schema.SIDE_KEYS}
        cls = _group_class(f"THEATRE_PG_{group.key}", group, group.params, extra)
        classes.append(cls)
        root_fields[group.key] = PointerProperty(type=cls)
    root = type("THEATRE_PG_root", (bpy.types.PropertyGroup,), {"__annotations__": root_fields})
    classes.append(root)
    return classes, root


CLASSES, ROOT_CLASS = _build_classes()


# --------------------------------------------------- scene <-> params dict

def _read(node, param: Param):
    value = getattr(node, param.key)
    if param.kind == schema.ANGLE:
        return round(math.degrees(value), 4)
    if param.kind in (schema.LENGTH, schema.FLOAT):
        return round(float(value), 6)
    if param.kind == schema.BOOL_VECTOR:
        return tuple(bool(v) for v in value)
    return value


def _write(node, param: Param, value) -> None:
    if param.kind == schema.ANGLE:
        value = math.radians(value)
    setattr(node, param.key, value)


def scene_params(scene) -> dict:
    """Nested params dict (angles in degrees) read from the scene properties."""
    root = getattr(scene, SCENE_ATTR)
    out: dict = {}
    for group in schema.SCHEMA:
        node = getattr(root, group.key)
        values = {p.key: _read(node, p) for p in group.params}
        for side in schema.SIDE_KEYS if group.side_params else ():
            values[side] = {p.key: _read(getattr(node, side), p) for p in group.side_params}
        out[group.key] = values
    return out


def apply_params(scene, params: Mapping) -> None:
    """Write a validated params dict to the scene; rebuilds exactly once."""
    root = getattr(scene, SCENE_ATTR)
    with batch(scene):
        for group in schema.SCHEMA:
            node, values = getattr(root, group.key), params[group.key]
            for p in group.params:
                _write(node, p, values[p.key])
            for side in schema.SIDE_KEYS if group.side_params else ():
                for p in group.side_params:
                    _write(getattr(node, side), p, values[side][p.key])
        request_rebuild(scene)


def register() -> None:
    reload_library()
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    setattr(bpy.types.Scene, SCENE_ATTR, PointerProperty(type=ROOT_CLASS))


def unregister() -> None:
    global _deferred_scene
    if bpy.app.timers.is_registered(_run_deferred):
        bpy.app.timers.unregister(_run_deferred)
    _deferred_scene = None
    delattr(bpy.types.Scene, SCENE_ATTR)
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
