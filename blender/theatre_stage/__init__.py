"""Parametric theatre stage generator (Blender extension)."""

from . import operators, props, ui


def register() -> None:
    props.register()
    operators.register()
    ui.register()


def unregister() -> None:
    ui.unregister()
    operators.unregister()
    props.unregister()
