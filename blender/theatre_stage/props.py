"""PropertyGroups generated from `core.params.SCHEMA`, on `Scene.theatre`.

Angles are stored in radians (subtype ANGLE) and converted to degrees when the
params dict is built. Nothing here names a parameter: the schema drives it all.
"""

from __future__ import annotations

import math
import traceback
from collections.abc import Mapping
from contextlib import contextmanager

import bpy
from bpy.props import (
    BoolProperty, BoolVectorProperty, EnumProperty, FloatProperty, IntProperty,
    PointerProperty,
)

from . import build
from .core import params as schema
from .core.params import Group, Param

SCENE_ATTR = "theatre"

REBUILD_DELAY = 0.15

_lock_depth = 0
_pending = False
_deferred_scene: str | None = None


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
    raise ValueError(f"Unsupported parameter kind: {kind}")


def _make_update(group: Group, param: Param):
    if not param.rebuild:
        return None
    mirrors = group.side_params and param.key == "symmetric"

    def update(self, context):
        scene = self.id_data
        if is_locked():
            request_rebuild(scene)
            return
        with batch(scene, deferred=True):
            if mirrors and not self.symmetric:
                _copy_set(self.left, self.right, group.side_params)
            request_rebuild(scene)

    return update


def _copy_set(source, target, params) -> None:
    for param in params:
        setattr(target, param.key, getattr(source, param.key))


def _group_class(name: str, group: Group, params, extra=None) -> type:
    annotations = {p.key: _make_property(p, _make_update(group, p)) for p in params}
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
