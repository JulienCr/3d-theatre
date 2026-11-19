"""Operators: manual rebuild, preset loading and saving."""

from __future__ import annotations

import re
from pathlib import Path

import bpy
from bpy.props import StringProperty

from . import props
from .core import presets

SHIPPED = "shipped"
USER = "user"

_items_cache: list = []
preset_warnings: list[str] = []


def user_dir(create: bool = False) -> Path:
    path = bpy.utils.extension_path_user(__package__, path="presets", create=create)
    return Path(path)


def list_presets() -> list[tuple[str, str, Path]]:
    """(identifier, label, path) of shipped then user presets."""
    out = [(f"{SHIPPED}:{name}", name, path) for name, path in presets.shipped_presets().items()]
    folder = user_dir()
    if folder.is_dir():
        out += [(f"{USER}:{p.stem}", f"{p.stem} (utilisateur)", p)
                for p in sorted(folder.glob("*.yaml"))]
    return out


def preset_items(self, context):
    global _items_cache
    _items_cache = [(ident, label, "Préréglage livré" if ident.startswith(SHIPPED)
                     else "Préréglage utilisateur") for ident, label, _ in list_presets()]
    return _items_cache


def _slug(name: str) -> str:
    return re.sub(r"[^\w\-]+", "_", name.strip()).strip("_")


class THEATRE_OT_rebuild(bpy.types.Operator):
    bl_idname = "theatre.rebuild"
    bl_label = "Reconstruire"
    bl_description = "Supprime les objets générés et recrée la scène depuis les paramètres"

    def execute(self, context):
        props.rebuild_scene(context.scene)
        return {"FINISHED"}


class THEATRE_OT_load_preset(bpy.types.Operator):
    bl_idname = "theatre.load_preset"
    bl_label = "Charger"
    bl_description = "Applique le préréglage choisi et reconstruit une seule fois"

    def execute(self, context):
        wm = context.window_manager
        paths = {ident: path for ident, _, path in list_presets()}
        path = paths.get(wm.theatre_preset)
        if path is None:
            self.report({"ERROR"}, "Aucun préréglage sélectionné.")
            return {"CANCELLED"}
        try:
            params, warnings = presets.read_preset(path)
        except (presets.PresetError, OSError) as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        preset_warnings[:] = warnings
        props.apply_params(context.scene, params)
        for line in warnings:
            self.report({"WARNING"}, line)
        return {"FINISHED"}


class THEATRE_OT_save_preset(bpy.types.Operator):
    bl_idname = "theatre.save_preset"
    bl_label = "Enregistrer sous…"
    bl_description = "Enregistre les paramètres actuels comme préréglage utilisateur"

    name: StringProperty(name="Nom", description="Nom du préréglage")  # type: ignore[valid-type]

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        slug = _slug(self.name)
        if not slug:
            self.report({"ERROR"}, "Donnez un nom au préréglage.")
            return {"CANCELLED"}
        path = user_dir(create=True) / f"{slug}.yaml"
        presets.write_preset(path, props.scene_params(context.scene))
        context.window_manager.theatre_preset = f"{USER}:{slug}"
        self.report({"INFO"}, f"Préréglage enregistré : {path.name}")
        return {"FINISHED"}


CLASSES = (THEATRE_OT_rebuild, THEATRE_OT_load_preset, THEATRE_OT_save_preset)


def register() -> None:
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.WindowManager.theatre_preset = bpy.props.EnumProperty(
        name="Préréglage", description="Préréglage à charger", items=preset_items)


def unregister() -> None:
    del bpy.types.WindowManager.theatre_preset
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
