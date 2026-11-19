"""Light timer that spreads a material dropped on a generated object (spec 6.1)."""

import traceback

import bpy

from . import materials, props

INTERVAL = 1.0


def _poll():
    if props.is_busy():
        return INTERVAL
    try:
        for scene in bpy.data.scenes:
            if scene.collection.children.get(materials.ROOT) is None:
                continue
            materials.ensure_items(scene)
            for category in materials.detect(scene):
                materials.propagate(scene, category)
    except Exception:
        traceback.print_exc()
    return INTERVAL


def register() -> None:
    if not bpy.app.timers.is_registered(_poll):
        bpy.app.timers.register(_poll, first_interval=INTERVAL, persistent=True)


def unregister() -> None:
    if bpy.app.timers.is_registered(_poll):
        bpy.app.timers.unregister(_poll)
