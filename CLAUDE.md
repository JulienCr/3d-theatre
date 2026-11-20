# 3d-theatre

Parametric theatre stage for Blender 5.3, shipped as an extension in
`blender/theatre_stage/`. `docs/spec.md` (French) is the source of truth for
every dimension rule, default value and object name.

## Rules

- Code, identifiers, object and material names, YAML keys, commits: English.
  Panel labels, warnings shown in the panel, `docs/`: French.
- `blender/theatre_stage/core/` is pure Python: no `bpy` import, only relative
  imports inside `core/`. Every dimension rule lives there and is tested.
- Parameters are declared once, in `core/params.py`. The PropertyGroup, the
  panel and the YAML presets derive from that schema; never hand-write a
  property the schema does not declare.
- Rebuild deletes only objects tagged `theatre_generated`. Materials are looked
  up by name and never overwritten (BlenderKit shaders are assigned on top).
- Animated values (curtain opening) reach geometry through drivers. Property
  update callbacks do not fire during timeline playback.
- A fixture is a fiche (`library/fixtures/<id>/fixture.yaml`, spec §12), never
  code. DMX reaches fixtures only through scene props `dmx_<u>_<c>` written by
  DMX Visualizer (`JulienCr/blender-dmx-visualizer`, local
  `D:\dev\blender-dmx-visualizer`); `D:\dev\blender-dmx` is out of scope.
- Backlog and known gaps are GitHub issues, not a file.

## Commands

- Tests: `python -m pytest` from the repo root (system Python + pytest + PyYAML).
- New fiche: `python tools/gdtf_to_fiche.py <file.gdtf> --id <id> --out
  blender/theatre_stage/library/fixtures/<id>/`, then fill the `null` fields.
- Types: `pyright blender/theatre_stage tools` reports only the `bpy` imports.
- Dev install: the extension folder is a junction from
  `%APPDATA%\Blender Foundation\Blender\5.3\extensions\user_default\theatre_stage`
  to `blender/theatre_stage`. Edit sources here, never in AppData.
- Enable: `bpy.ops.extensions.repo_refresh_all()` then
  `addon_enable("bl_ext.user_default.theatre_stage")` (this also syncs the
  PyYAML wheel). Reload: disable, drop `sys.modules` entries under the
  package, enable. "Failed to remove _yaml…pyd" on disable is harmless.

## Verify

A change is verified in the live Blender (MCP, `blender-mcp` skill): rebuild,
render or screenshot from `Cam_Face`, compare with
`references/salle/scene-vue-artiste.png`.
