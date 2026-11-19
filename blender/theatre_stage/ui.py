"""Sidebar panel "Théâtre": one sub-panel per schema group, derived dimensions,
alerts and presets. Labels and tooltips come from the schema.
"""

from __future__ import annotations

import textwrap

import bpy

from . import build, materials, operators, props
from .core import params as schema
from .core.layout import MATERIAL_LABELS
from .core.params import Group, Param

MAIN_ID = "THEATRE_PT_main"
CATEGORY = "Théâtre"
SIDE_LABELS = {"left": "Jardin (gauche)", "right": "Cour (droite)"}


def _metres(value: float) -> str:
    return f"{value:.2f} m".replace(".", ",")


def _wrap(layout, context, text: str, icon: str = "NONE") -> None:
    chars = max(16, int((context.region.width - 60) / (7.5 * context.preferences.system.ui_scale)))
    column = layout.column(align=True)
    for index, line in enumerate(textwrap.wrap(text, chars) or [""]):
        column.label(text=line, icon=icon if index == 0 else "BLANK1")


def _depends_on_flag(param: Param, keys) -> str | None:
    """Key of the `<prefix>_enabled` flag a param hangs from, if any."""
    if param.key == "enabled":
        return None
    prefix = param.key.split("_")[0]
    if f"{prefix}_enabled" in keys and param.key != f"{prefix}_enabled":
        return f"{prefix}_enabled"
    return "enabled" if "enabled" in keys else None


def _draw_param(layout, node, param: Param, group: Group, active: bool = True) -> None:
    row = layout.row()
    row.active = active
    if param.kind == schema.BOOL_VECTOR:
        shown = node.lanes if group.key == "masking" else param.length
        row.label(text=param.label)
        flags = layout.row(align=True)
        flags.active = active
        for index in range(min(shown, param.length)):
            flags.prop(node, param.key, index=index, text=str(index + 1), toggle=True)
        return
    row.prop(node, param.key)


def _draw_set(layout, node, params, group: Group) -> None:
    keys = {p.key for p in params}
    for param in params:
        flag = _depends_on_flag(param, keys)
        _draw_param(layout, node, param, group, active=bool(getattr(node, flag)) if flag else True)


def _draw_group(self, context):
    group: Group = self.group
    node = getattr(getattr(context.scene, props.SCENE_ATTR), group.key)
    _draw_set(self.layout, node, group.params, group)
    if not group.side_params:
        return
    if node.symmetric:
        box = self.layout.box()
        box.label(text="Jardin et cour (miroir)")
        _draw_set(box, node.left, group.side_params, group)
        return
    for side in schema.SIDE_KEYS:
        box = self.layout.box()
        box.label(text=SIDE_LABELS[side])
        _draw_set(box, getattr(node, side), group.side_params, group)


def _group_panel(group: Group) -> type:
    options = {"DEFAULT_CLOSED"} if group.advanced else set()
    return type(f"THEATRE_PT_group_{group.key}", (bpy.types.Panel,), {
        "bl_idname": f"THEATRE_PT_group_{group.key}",
        "bl_label": group.label,
        "bl_space_type": "VIEW_3D",
        "bl_region_type": "UI",
        "bl_category": CATEGORY,
        "bl_parent_id": MAIN_ID,
        "bl_options": options,
        "group": group,
        "draw": _draw_group,
    })


class _SubPanel(bpy.types.Panel):
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = CATEGORY
    bl_parent_id = MAIN_ID


def _layout(context):
    return build.cached_layout(props.scene_params(context.scene))


class THEATRE_PT_main(bpy.types.Panel):
    bl_idname = MAIN_ID
    bl_label = "Théâtre"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = CATEGORY

    def draw(self, context):
        self.layout.operator("theatre.rebuild", icon="FILE_REFRESH")


class THEATRE_PT_materials(_SubPanel):
    bl_idname = "THEATRE_PT_materials"
    bl_label = "Matériaux"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        store = materials.store_of(context.scene)
        for category, label in MATERIAL_LABELS.items():
            item = store.get(category)
            if item is None:
                self.layout.label(text=f"{label} : après reconstruction")
                continue
            row = self.layout.row(align=True)
            row.prop(item, "material", text=label)
            reset = row.row(align=True)
            reset.enabled = item.material is not None
            reset.operator("theatre.reset_material", text="", icon="X").category = category


class THEATRE_PT_derived(_SubPanel):
    bl_idname = "THEATRE_PT_derived"
    bl_label = "Cotes calculées"

    def draw(self, context):
        d = _layout(context).derived
        box = self.layout.box()
        col = box.column(align=True)
        col.label(text=f"Largeur hors tout : {_metres(d.total_width)}")
        col.label(text=f"Ouverture du cadre : {_metres(d.frame_opening)}")
        col.label(text=f"Largeur de cage : {_metres(d.cage_width)}")
        col.label(text=f"Zone latérale : {_metres(d.side_zone)}")
        col.label(text=f"Contremarches : {d.risers_count} × {_metres(d.riser_height)}")
        col.label(text=f"Porteuses lumière : {d.batten_count}")
        col.label(text=f"Porteuses de pendrillonnage : {d.masking_batten_count}")
        col.label(text=f"Largeur d'une rue : {_metres(d.lane_width)}")


class THEATRE_PT_alerts(_SubPanel):
    bl_idname = "THEATRE_PT_alerts"
    bl_label = "Alertes"

    def draw(self, context):
        layout = _layout(context)
        messages = list(layout.warnings)
        messages += [f"Objet non généré laissé en place : {name}." for name in build.foreign_names]
        messages += operators.preset_warnings
        messages += materials.warnings
        if not messages:
            self.layout.label(text="Aucune alerte.", icon="CHECKMARK")
        for message in messages:
            _wrap(self.layout, context, message, icon="ERROR")


class THEATRE_PT_presets(_SubPanel):
    bl_idname = "THEATRE_PT_presets"
    bl_label = "Préréglages"

    def draw(self, context):
        wm = context.window_manager
        self.layout.prop(wm, "theatre_preset", text="")
        row = self.layout.row(align=True)
        row.operator("theatre.load_preset", icon="IMPORT")
        row.operator("theatre.save_preset", icon="EXPORT")


GROUP_PANELS = [_group_panel(g) for g in schema.SCHEMA]
CLASSES = (THEATRE_PT_main, *GROUP_PANELS, THEATRE_PT_materials, THEATRE_PT_derived, THEATRE_PT_alerts,
           THEATRE_PT_presets)


def register() -> None:
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister() -> None:
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
