"""Materials chosen by the user, remembered per category (spec 6.1).

A category is the default `TS_*` material name of a generated object. The
choices live on the scene (`Scene.theatre_materials`), so they are saved in
the .blend and never in YAML presets.
"""

import bpy
from bpy.props import CollectionProperty, PointerProperty

from .core.layout import MATERIAL_LABELS

TAG = "theatre_generated"
CATEGORY = "theatre_category"
ROOT = "Theatre"
STORE = "theatre_materials"

warnings: list[str] = []
_quiet = False


def walk_objects(collection):
    """Objects of a collection tree, without the `all_objects` cache."""
    yield from collection.objects
    for child in collection.children:
        yield from walk_objects(child)


def _on_pick(self, context):
    if not _quiet:
        propagate(self.id_data, self.name)


class THEATRE_PG_material(bpy.types.PropertyGroup):
    material: PointerProperty(  # type: ignore[valid-type]
        type=bpy.types.Material, name="Matériau",
        description="Matériau retenu pour toute la catégorie (vide : matériau par défaut)",
        update=_on_pick)


def store_of(scene):
    return getattr(scene, STORE)


def ensure_items(scene) -> None:
    store = store_of(scene)
    for category in MATERIAL_LABELS:
        if store.find(category) < 0:
            store.add().name = category


def _category_objects():
    root = bpy.data.collections.get(ROOT)
    if root is None:
        return []
    return sorted((o for o in walk_objects(root)
                   if o.type == "MESH" and o.get(TAG) is not None and o.get(CATEGORY)),
                  key=lambda o: o.name)


def _slot_material(obj):
    return obj.material_slots[0].material if obj.material_slots else None


def overrides(scene) -> dict:
    """Category to chosen material, for the categories that have a choice."""
    return {item.name: item.material for item in store_of(scene) if item.material is not None}


def detect(scene) -> list[str]:
    """Remember materials put on generated objects; returns the categories that changed."""
    global _quiet
    store = store_of(scene)
    picked: dict[str, list] = {}
    for obj in _category_objects():
        category = obj[CATEGORY]
        material = _slot_material(obj)
        item = store.get(category)
        if material is None or item is None or material.name == category:
            continue
        if material != item.material:
            picked.setdefault(category, []).append(material)
    warnings.clear()
    _quiet = True
    try:
        for category, found in picked.items():
            store[category].material = found[0]
            if len({m.name for m in found}) > 1:
                warnings.append("Matériaux différents posés sur « "
                                f"{MATERIAL_LABELS.get(category, category)} » : "
                                f"« {found[0].name} » retenu.")
    finally:
        _quiet = False
    return list(picked)


def propagate(scene, category: str) -> None:
    """Put the category's material on every generated object of the category."""
    item = store_of(scene).get(category)
    target = (item.material if item else None) or bpy.data.materials.get(category)
    if target is None:
        return
    for obj in _category_objects():
        if obj[CATEGORY] == category and obj.material_slots:
            slot = obj.material_slots[0]
            if slot.material != target:
                slot.material = target


def register() -> None:
    bpy.utils.register_class(THEATRE_PG_material)
    setattr(bpy.types.Scene, STORE, CollectionProperty(type=THEATRE_PG_material))


def unregister() -> None:
    delattr(bpy.types.Scene, STORE)
    bpy.utils.unregister_class(THEATRE_PG_material)
