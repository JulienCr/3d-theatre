"""Operators: manual rebuild, presets, rest values, library reload and QLC+ export."""

from __future__ import annotations

import re
from pathlib import Path

import bpy
from bpy.props import StringProperty

from . import build, materials, props, rigbuild
from .core import face_rig, presets, qlc
from .core.layout import compute_layout

SHIPPED = "shipped"
USER = "user"

_item_pool: dict[tuple, tuple] = {}
preset_warnings: list[str] = []
export_report: list[str] = []
_selected = ""


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
    """Enum items; the tuples (and their strings) live in a module pool Blender can point at."""
    items = []
    for ident, label, _ in list_presets():
        info = "Préréglage livré" if ident.startswith(SHIPPED) else "Préréglage utilisateur"
        items.append(_item_pool.setdefault((ident, label, info), (ident, label, info)))
    return items


def _get_preset(self) -> int:
    """Index of the selected preset; the first item when it no longer exists."""
    for index, item in enumerate(preset_items(None, None)):
        if item[0] == _selected:
            return index
    return 0


def _set_preset(self, index: int) -> None:
    global _selected
    items = preset_items(None, None)
    if 0 <= index < len(items):
        _selected = items[index][0]


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
            params, warnings = presets.read_preset(path, catalog=props.library())
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


class THEATRE_OT_reset_material(bpy.types.Operator):
    bl_idname = "theatre.reset_material"
    bl_label = "Matériau par défaut"
    bl_description = "Revient au matériau TS_ par défaut de cette catégorie"

    category: StringProperty()  # type: ignore[valid-type]

    def execute(self, context):
        item = materials.store_of(context.scene).get(self.category)
        if item is None:
            return {"CANCELLED"}
        item.material = None
        return {"FINISHED"}


def _rig(context):
    """The computed rig of the scene, or None when the lighting rig is off."""
    rig = props.current_layout(context.scene).rig
    return rig if rig is not None and rig.enabled else None


class THEATRE_OT_rest_full(bpy.types.Operator):
    bl_idname = "theatre.rest_full"
    bl_label = "Plein feu de repos"
    bl_description = "Réécrit tous les canaux patchés à leur valeur de repos (la console DMX reprend la main ensuite)"

    def execute(self, context):
        rig = _rig(context)
        if rig is None:
            self.report({"ERROR"}, "L'implantation lumière est désactivée.")
            return {"CANCELLED"}
        self.report({"INFO"}, f"{rigbuild.rest_full(context.scene, rig)} canaux remis à leur valeur de repos.")
        return {"FINISHED"}


class THEATRE_OT_equalize_face(bpy.types.Operator):
    bl_idname = "theatre.equalize_face"
    bl_label = "Égaliser la face"
    bl_description = ("Cherche pour chaque PC de face la visée, le zoom et le niveau qui rendent l'éclairement "
                      "vertical le plus homogène, l'enregistre dans la scène et reconstruit")

    def execute(self, context):
        scene = context.scene
        params = props.scene_params(scene)
        plain = compute_layout(params, props.library()).rig
        if plain is None or not plain.enabled or not plain.by_family(face_rig.FAMILY):
            self.report({"ERROR"}, "Pas de PC de face à égaliser.")
            return {"CANCELLED"}
        try:
            result = face_rig.equalise_rig(plain, props.library(), params["front_pc"]["min_mean_ratio"])
        except ValueError as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        scene[build.FACE_EQ_KEY] = result.to_json()
        props.rebuild_scene(scene)
        total = result.after["sum"]
        self.report({"INFO"}, f"Face égalisée : Emin/Emoy somme {result.before['sum'].uniformity:.2f} → "
                              f"{total.uniformity:.2f}, CV {result.before['sum'].cv:.2f} → {total.cv:.2f}.")
        return {"FINISHED"}


class THEATRE_OT_blackout(bpy.types.Operator):
    bl_idname = "theatre.blackout"
    bl_label = "Noir général"
    bl_description = ("Met tous les canaux DMX de la scène à 0 pour que la console seule éclaire la scène ; "
                      "un pont en marche réécrit les canaux qu'il reçoit")

    def execute(self, context):
        count = rigbuild.blackout(context.scene)
        for window in context.window_manager.windows:
            for area in window.screen.areas:
                if area.type == "VIEW_3D":
                    area.tag_redraw()
        self.report({"INFO"}, f"Noir général : {count} canaux à 0")
        return {"FINISHED"}


class THEATRE_OT_reload_library(bpy.types.Operator):
    bl_idname = "theatre.reload_library"
    bl_label = "Recharger la bibliothèque"
    bl_description = "Relit les fiches d'appareils (livrées et utilisateur) puis reconstruit"

    def execute(self, context):
        library = props.reload_library()
        rigbuild.clear_cache()
        props.rebuild_scene(context.scene)
        self.report({"INFO"}, f"{len(library)} fiches lues.")
        return {"FINISHED"}


class THEATRE_OT_export_qlc(bpy.types.Operator):
    bl_idname = "theatre.export_qlc"
    bl_label = "Exporter vers QLC+"
    bl_description = "Écrit l'espace de travail QLC+ du patch et les définitions d'appareils manquantes"

    directory: StringProperty(subtype="DIR_PATH")  # type: ignore[valid-type]

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        rig = _rig(context)
        if rig is None or not self.directory:
            self.report({"ERROR"}, "Pas d'implantation lumière ou pas de dossier choisi.")
            return {"CANCELLED"}
        result = qlc.export_workspace(qlc.patched_from_rig(rig), props.library(), Path(self.directory),
                                      qlc.existing_fixture_dirs())
        export_report[:] = [f"Dossier : {result.workspace.parent}", f"Espace de travail : {result.workspace.name}"]
        if result.written_qxf:
            export_report.append(f"Définitions écrites : {', '.join(p.name for p in result.written_qxf)}")
        if result.reused_qxf:
            export_report.append(f"Définitions QLC+ réutilisées : {', '.join(result.reused_qxf)}")
        export_report.extend(result.warnings)
        for line in result.warnings:
            self.report({"WARNING"}, line)
        self.report({"INFO"}, f"Export QLC+ : {result.workspace}")
        return {"FINISHED"}


CLASSES = (THEATRE_OT_rebuild, THEATRE_OT_load_preset, THEATRE_OT_save_preset,
           THEATRE_OT_reset_material, THEATRE_OT_rest_full, THEATRE_OT_equalize_face, THEATRE_OT_blackout, THEATRE_OT_reload_library,
           THEATRE_OT_export_qlc)


def register() -> None:
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.WindowManager.theatre_preset = bpy.props.EnumProperty(
        name="Préréglage", description="Préréglage à charger", items=preset_items,
        get=_get_preset, set=_set_preset)


def unregister() -> None:
    del bpy.types.WindowManager.theatre_preset
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
