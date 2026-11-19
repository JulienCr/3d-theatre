"""Preset files: nested parameter dicts to and from YAML text."""

from __future__ import annotations

from pathlib import Path

import yaml

from .params import SCHEMA_VERSION, default_params, validate_params

SHIPPED_DIR = Path(__file__).resolve().parent.parent / "presets"


class PresetError(ValueError):
    """Raised when a preset cannot be read at all (French message)."""


def _plain(value):
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(v) for v in value]
    return value


def params_to_yaml(params: dict) -> str:
    """YAML text with `version` first. `params` is validated before writing."""
    clean, _ = validate_params(params)
    document = {"version": SCHEMA_VERSION, **_plain(clean)}
    return yaml.safe_dump(document, sort_keys=False, allow_unicode=True)


def params_from_yaml(text: str) -> tuple[dict, list[str]]:
    """Parse preset text. Returns (params, French warnings)."""
    try:
        document = yaml.safe_load(text)
    except yaml.YAMLError as error:
        raise PresetError(f"Préréglage illisible : {error}") from error
    if document is None:
        return default_params(), ["Préréglage vide : valeurs par défaut utilisées."]
    if not isinstance(document, dict):
        raise PresetError("Préréglage invalide : un dictionnaire est attendu.")
    warnings = []
    version = document.get("version", SCHEMA_VERSION)
    if version != SCHEMA_VERSION:
        warnings.append(f"Version de préréglage {version!r} inconnue (attendue : {SCHEMA_VERSION}).")
    params, issues = validate_params(document)
    return params, warnings + issues


def read_preset(path) -> tuple[dict, list[str]]:
    return params_from_yaml(Path(path).read_text(encoding="utf-8"))


def write_preset(path, params: dict) -> None:
    Path(path).write_text(params_to_yaml(params), encoding="utf-8")


def shipped_presets() -> dict[str, Path]:
    """Name (file stem) to path of the presets shipped with the extension."""
    return {p.stem: p for p in sorted(SHIPPED_DIR.glob("*.yaml"))}
