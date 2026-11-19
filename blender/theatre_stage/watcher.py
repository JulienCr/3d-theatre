"""Spreads a material put on a generated object (spec 6.1), driven by a message bus
subscription: nothing runs, and no object is read, until a material slot changes.
"""

import traceback

import bpy
from bpy.app.handlers import persistent

from . import materials, props

DELAY = 0.2
RETRY = 0.5

_owner = object()
_pending = False
detection_runs = 0


def _notify(*args) -> None:
    """Message bus callback: only schedules the detection, never reads any datablock."""
    global _pending
    if not _pending:
        _pending = True
        bpy.app.timers.register(_run, first_interval=DELAY)


def _run():
    global _pending, detection_runs
    if props.is_busy():
        return RETRY
    _pending = False
    detection_runs += 1
    try:
        for scene in bpy.data.scenes:
            if scene.collection.children.get(materials.ROOT) is None:
                continue
            materials.ensure_items(scene)
            for category in materials.detect(scene):
                materials.propagate(scene, category)
    except Exception:
        traceback.print_exc()
    return None


def _subscribe() -> None:
    bpy.msgbus.clear_by_owner(_owner)
    bpy.msgbus.subscribe_rna(key=(bpy.types.MaterialSlot, "material"), owner=_owner, args=(),
                             notify=_notify)


@persistent
def _on_load(*args) -> None:
    _subscribe()


def register() -> None:
    _subscribe()
    if _on_load not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_on_load)


def unregister() -> None:
    global _pending
    if _on_load in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load)
    bpy.msgbus.clear_by_owner(_owner)
    if bpy.app.timers.is_registered(_run):
        bpy.app.timers.unregister(_run)
    _pending = False
