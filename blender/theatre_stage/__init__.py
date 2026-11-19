"""Parametric theatre stage generator (Blender extension)."""

from . import materials, operators, props, ui, watcher


def register() -> None:
    props.register()
    materials.register()
    operators.register()
    ui.register()
    watcher.register()


def unregister() -> None:
    watcher.unregister()
    ui.unregister()
    operators.unregister()
    materials.unregister()
    props.unregister()
