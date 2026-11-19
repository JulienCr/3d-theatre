"""EEVEE volume settings for the haze box (spec 8.6).

Scene render settings are only touched while the haze is enabled; the values
found before the first change are kept on the scene and restored afterwards.
"""

import bpy

from .core.layout import haze_view_range

QUALITY = {"light": ("8", 32), "medium": ("4", 64), "fine": ("2", 128)}
KEYS = ("volumetric_tile_size", "volumetric_samples", "use_volume_custom_range",
        "volumetric_start", "volumetric_end")
STORE = "theatre_haze_previous"


def apply(scene: bpy.types.Scene, params: dict, layout) -> None:
    eevee = scene.eevee
    haze = params["haze"]
    previous = scene.get(STORE)
    if not haze["enabled"]:
        if previous is not None:
            for key in KEYS:
                setattr(eevee, key, bool(previous[key]) if key == KEYS[2] else previous[key])
            del scene[STORE]
        return
    if previous is None:
        scene[STORE] = {key: getattr(eevee, key) for key in KEYS}
    eevee.volumetric_tile_size, eevee.volumetric_samples = QUALITY[haze["quality"]]
    depth_range = haze_view_range(layout)
    if depth_range is not None:
        eevee.use_volume_custom_range = True
        eevee.volumetric_start, eevee.volumetric_end = depth_range
