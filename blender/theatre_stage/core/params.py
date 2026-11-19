"""Single source of truth for every parameter of the stage generator.

The PropertyGroups, the panel and the YAML keys all derive from SCHEMA.
Adding a group or a parameter is a declaration only: no other file lists keys.
Lengths are in metres, angles in degrees, `main_opening`-style percents in %.
"""

from __future__ import annotations

import math
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Any

SCHEMA_VERSION = 1
SIDE_KEYS = ("left", "right")

# Param.kind values
LENGTH = "length"
ANGLE = "angle"
FLOAT = "float"
INT = "int"
BOOL = "bool"
ENUM = "enum"
BOOL_VECTOR = "bool_vector"

_NUMERIC = (LENGTH, ANGLE, FLOAT, INT)


@dataclass(frozen=True)
class Param:
    """One declared parameter.

    `items` is a tuple of (value, label, tooltip) for enums; `length` is the
    vector size for BOOL_VECTOR. `rebuild=False` marks a value that must not
    trigger a scene rebuild (it only drives existing objects).
    """

    key: str
    kind: str
    default: Any
    label: str
    tooltip: str
    min: float | None = None
    max: float | None = None
    items: tuple[tuple[str, str, str], ...] = ()
    length: int = 0
    animatable: bool = False
    rebuild: bool = True

    @property
    def is_numeric(self) -> bool:
        return self.kind in _NUMERIC


@dataclass(frozen=True)
class Group:
    """A panel section. `side_params` is shared by the `left` and `right` sets."""

    key: str
    label: str
    params: tuple[Param, ...]
    advanced: bool = False
    side_params: tuple[Param, ...] = ()


def _length(key, default, lo, hi, label, tooltip):
    return Param(key, LENGTH, default, label, tooltip, lo, hi)


def _angle(key, default, lo, hi, label, tooltip):
    return Param(key, ANGLE, default, label, tooltip, lo, hi)


def _flag(key, default, label, tooltip):
    return Param(key, BOOL, default, label, tooltip)


def _enum(key, default, label, tooltip, items):
    return Param(key, ENUM, default, label, tooltip, items=tuple(items))


_MODULE_PARAMS = (
    _flag("enabled", True, "Module présent", "Affiche ce module latéral."),
    _length("frame_gap", 0.0, -10.0, 5.0, "Écart au cadre",
            "Distance entre la charnière et le bord du cadre : positive vers l'axe, "
            "négative vers les coulisses."),
    _length("setback", 2.05, 0.0, 30.0, "Recul de la charnière",
            "Distance de la charnière au nez de scène, vers le fond."),
    _length("width", 1.55, 0.40, 10.0, "Largeur de la face",
            "Largeur de la face avant du module."),
    _length("depth", 2.00, 0.10, 20.0, "Profondeur du retour",
            "Profondeur du retour côté plateau."),
    _length("height", 5.00, 1.0, 20.0, "Hauteur",
            "Hauteur du module depuis le plancher."),
    _angle("angle", 0.0, 0.0, 90.0, "Angle en plan",
           "0° : face parallèle au nez. 90° : face le long du mur de cage."),
    _flag("door_enabled", True, "Porte", "Perce une porte dans la face."),
    _length("door_width", 0.94, 0.30, 5.0, "Largeur de porte", "Largeur de la porte."),
    _length("door_height", 2.40, 0.50, 10.0, "Hauteur de porte", "Hauteur de la porte."),
    _length("door_offset", 0.0, -5.0, 5.0, "Décalage de porte",
            "Décalage de la porte, positif vers le plateau."),
    _flag("window_enabled", False, "Fenêtre", "Perce une fenêtre dans la face."),
    _length("window_width", 1.00, 0.20, 5.0, "Largeur de fenêtre", "Largeur de la fenêtre."),
    _length("window_height", 1.20, 0.20, 10.0, "Hauteur de fenêtre", "Hauteur de la fenêtre."),
    _length("window_sill", 1.00, 0.0, 10.0, "Allège",
            "Hauteur du bas de la fenêtre depuis le plancher."),
    _length("window_offset", 0.0, -5.0, 5.0, "Décalage de fenêtre",
            "Décalage de la fenêtre, positif vers le plateau."),
)

SCHEMA: tuple[Group, ...] = (
    Group("stage", "Plateau", (
        _length("width", 11.60, 4.0, 30.0, "Largeur du plateau", "Largeur au nez de scène."),
        _length("depth", 7.00, 3.0, 30.0, "Profondeur de scène", "Du nez de scène au fond."),
        _length("grid_height", 6.10, 3.0, 25.0, "Hauteur sous gril",
                "Hauteur sous le gril, depuis le plancher."),
        _length("wings", 2.00, 0.0, 15.0, "Coulisses",
                "Largeur des coulisses de chaque côté de l'ouverture du cadre."),
    )),
    Group("advanced", "Avancé", (
        _length("stage_height", 1.20, 0.20, 2.50, "Hauteur du plateau",
                "Hauteur du plancher au-dessus du sol de salle."),
        _length("apron_depth", 3.10, 0.50, 15.0, "Avant-scène",
                "Profondeur de sol de salle devant le nez."),
        _length("facade_height", 7.30, 3.0, 30.0, "Hauteur de façade",
                "Hauteur de la façade depuis le sol de salle."),
        _length("proscenium_height", 5.00, 2.0, 20.0, "Ouverture du cadre",
                "Hauteur d'ouverture du cadre depuis le plancher."),
        _length("proscenium_thickness", 0.80, 0.10, 3.0, "Montant du cadre",
                "Largeur d'un montant du cadre."),
        _length("proscenium_setback", 1.20, 0.0, 5.0, "Recul de façade",
                "Recul de la façade derrière le nez de scène."),
        _length("lintel_height", 0.80, 0.10, 3.0, "Linteau", "Hauteur du linteau noir."),
        _length("side_zone_width", 1.20, 0.0, 10.0, "Zones latérales",
                "Largeur minimale des zones latérales de chaque côté."),
    ), advanced=True),
    Group("stairs", "Escaliers", (
        _flag("left", True, "Escalier jardin", "Escalier côté jardin."),
        _flag("right", True, "Escalier cour", "Escalier côté cour."),
        _flag("center", False, "Escalier central", "Escalier central sur l'avant-scène."),
        _length("riser_max", 0.20, 0.10, 0.25, "Contremarche maximale",
                "Hauteur maximale d'une contremarche."),
        _length("going", 0.30, 0.20, 0.45, "Giron", "Profondeur d'une marche."),
        _length("width", 1.20, 0.60, 3.0, "Largeur latérale", "Largeur des escaliers latéraux."),
        _angle("side_angle", 90.0, -90.0, 90.0, "Angle latéral",
               "0° : vers la salle. 90° : vers le mur latéral. −90° : vers le centre."),
        _length("side_offset", 0.0, -10.0, 10.0, "Décalage latéral",
                "Décalage du palier : positif vers le mur, négatif vers le centre "
                "(le palier passe alors devant le plateau)."),
        _length("clearance", 1.0, 0.0, 5.0, "Dégagement",
                "Espace libre au pied de l'escalier, au-delà de la dernière marche."),
        _length("landing_depth", 1.2, 0.0, 5.0, "Profondeur du palier",
                "Profondeur du palier dans le sens de la volée. 0 : pas de palier."),
        _length("center_width", 2.00, 0.60, 10.0, "Largeur centrale",
                "Largeur de l'escalier central."),
    )),
    Group("modules", "Modules", (
        _flag("symmetric", True, "Symétrique",
              "Applique le jeu de gauche aux deux côtés, en miroir."),
    ), side_params=_MODULE_PARAMS),
    Group("grid", "Gril", (
        _length("batten_spacing", 1.00, 0.20, 5.0, "Espacement des porteuses",
                "Distance entre deux porteuses lumière."),
        _length("batten_drop", 0.50, 0.0, 10.0, "Porteuses sous le gril",
                "Distance entre le dessous du gril et les porteuses."),
    )),
    Group("masking", "Pendrillonnage", (
        _enum("style", "italian", "Style", "Disposition des pendrillons.", (
            ("italian", "Italienne", "Pendrillons en plans, perpendiculaires au nez."),
            ("german", "Allemande", "Pendrillons continus, parallèles à l'axe."),
        )),
        Param("lanes", INT, 3, "Nombre de rues", "Nombre de rues de pendrillonnage.", 1, 8),
        _length("opening", 8.00, 2.0, 30.0, "Ouverture",
                "Largeur libre entre les pendrillons."),
        _flag("front_border", True, "Frise de face", "Frise au plus près du cadre."),
        Param("borders", BOOL_VECTOR, (True,) * 8, "Frises par plan",
              "Une case par plan de pendrillonnage.", length=8),
        _length("border_bottom", 4.50, 1.0, 20.0, "Bas des frises",
                "Hauteur du bas des frises au-dessus du plateau."),
        _enum("backdrop", "black_curtain", "Fond de scène", "Fermeture du fond.", (
            ("black_curtain", "Rideau noir", "Rideau de fond plissé."),
            ("bare_wall", "Mur nu", "Le mur de cage reste visible."),
            ("cyclorama", "Cyclorama", "Toile tendue claire."),
        )),
        _angle("leg_angle", 0.0, 0.0, 20.0, "Inclinaison des pendrillons",
               "Pendrillons à l'italienne penchés vers le public (0° : droits)."),
        _angle("convergence", 0.0, 0.0, 20.0, "Convergence",
               "Écartement progressif de l'ouverture vers le lointain (à l'italienne)."),
        _enum("borders_mode", "computed", "Hauteur des frises", "Bas des frises.", (
            ("computed", "Calées sur la découverte", "Calculées depuis le premier rang."),
            ("manual", "Manuelle", "Hauteur réglée à la main, contrôlée seulement."),
        )),
        Param("drape", FLOAT, 0.5, "Drapé", "Irrégularité des plis : 0 donne des plis réguliers, "
              "1 un drapé très marqué.", 0.0, 1.0),
    )),
    Group("sightlines", "Découverte", (
        _length("seat_distance", 2.00, 0.50, 30.0, "Premier rang",
                "Distance du premier rang au nez de scène."),
        _length("seat_wall_gap", 0.50, 0.0, 10.0, "Fauteuil extrême",
                "Écart du fauteuil de référence au mur de salle."),
        _length("eye_height", 1.10, 0.80, 3.0, "Hauteur d'œil",
                "Hauteur d'œil, assis, au-dessus du sol de salle."),
    )),
    Group("curtains", "Rideaux", (
        _flag("main_enabled", True, "Rideau de scène", "Rideau de scène à la grecque."),
        Param("main_opening", FLOAT, 100.0, "Ouverture du rideau (%)",
              "0 : fermé. 100 : ouvert. Animable, ne reconstruit pas la scène.",
              0.0, 100.0, animatable=True, rebuild=False),
    )),
    Group("lights", "Lumières", (
        _flag("enabled", True, "Lumières de travail", "Grille de lumières de travail."),
        _length("spacing", 3.00, 1.0, 10.0, "Maille de la grille",
                "Distance approximative entre deux lumières."),
        Param("intensity", FLOAT, 1.0, "Intensité", "Multiplicateur de puissance.", 0.0, 10.0),
        _flag("front", True, "Face depuis la salle", "Lumière de face depuis la salle."),
    )),
    Group("cameras", "Caméras", (
        _length("distance", 11.00, 2.0, 60.0, "Distance au nez",
                "Distance des caméras au nez de scène."),
        _length("height", 3.00, 0.5, 30.0, "Hauteur",
                "Hauteur des caméras au-dessus du sol de salle."),
        Param("lens", FLOAT, 22.0, "Focale (mm)", "Focale de l'objectif des caméras.",
              10.0, 200.0),
    )),
    Group("haze", "Brume", (
        _flag("enabled", False, "Atmosphère (brume)",
              "Volume de brume pour voir les faisceaux. Inactif : aucun réglage de rendu modifié."),
        _enum("extent", "stage_and_house", "Étendue", "Zone remplie de brume.", (
            ("stage", "Plateau", "La cage, avec un fondu vers la salle."),
            ("stage_and_house", "Plateau et salle", "Toute l'enceinte, brume homogène."),
        )),
        _length("falloff", 2.00, 0.10, 10.0, "Fondu vers la salle",
                "Étendue « plateau » : distance sur laquelle la brume s'estompe devant la façade."),
        Param("density", FLOAT, 0.02, "Densité", "Densité de la brume. Animable, ne reconstruit "
              "pas la scène.", 0.0, 1.0, animatable=True, rebuild=False),
        Param("anisotropy", FLOAT, 0.6, "Diffusion vers l'avant",
              "Diffusion vers l'avant de la lumière dans la brume.", -0.9, 0.9, rebuild=False),
        _enum("quality", "light", "Qualité", "Coût de rendu du volume (EEVEE).", (
            ("light", "Légère", "La moins chère qui montre un faisceau net."),
            ("medium", "Moyenne", "Faisceaux plus doux."),
            ("fine", "Fine", "Volume le plus précis, le plus lent."),
        )),
    )),
    Group("house", "Salle", (
        _flag("ceiling", True, "Plafond de salle",
              "Plafond visible seulement depuis la salle."),
    )),
)

GROUPS: dict[str, Group] = {g.key: g for g in SCHEMA}


def iter_params() -> Iterator[tuple[tuple[str, ...], Param]]:
    """Yield (path, param) for every leaf, side sets expanded for left and right."""
    for group in SCHEMA:
        for param in group.params:
            yield (group.key, param.key), param
        for side in SIDE_KEYS:
            for param in group.side_params:
                yield (group.key, side, param.key), param


def _default_value(param: Param):
    return param.default


def default_params() -> dict:
    """Fresh nested dict of defaults, shaped like the YAML."""
    out: dict = {}
    for group in SCHEMA:
        node = {p.key: _default_value(p) for p in group.params}
        for side in SIDE_KEYS:
            if group.side_params:
                node[side] = {p.key: _default_value(p) for p in group.side_params}
        out[group.key] = node
    return out


def module_sets(modules: Mapping) -> tuple[Mapping, Mapping]:
    """(left, right) parameter sets; the right one is the left when symmetric."""
    left = modules["left"]
    return left, (left if modules["symmetric"] else modules["right"])


def _fmt(value) -> str:
    if isinstance(value, float):
        return f"{value:g}".replace(".", ",")
    return str(value)


def _coerce(param: Param, value, path: str) -> tuple[Any, list[str]]:
    """Return (clean value, warnings). Falls back to the default on a bad type."""
    bad = f"Valeur invalide pour « {param.label} » ({path}) : {value!r}, défaut utilisé."
    kind = param.kind
    if kind == BOOL:
        return (value, []) if isinstance(value, bool) else (param.default, [bad])
    if kind == ENUM:
        if value in {item[0] for item in param.items}:
            return value, []
        return param.default, [bad]
    if kind == BOOL_VECTOR:
        if not isinstance(value, (list, tuple)):
            return param.default, [bad]
        warnings = []
        items = list(value)
        if len(items) != param.length:
            warnings.append(
                f"« {param.label} » ({path}) : {param.length} valeurs attendues, "
                f"{len(items)} reçues ; complété ou tronqué."
            )
            items = (items + list(param.default))[: param.length]
        clean = []
        for index, item in enumerate(items):
            if isinstance(item, bool):
                clean.append(item)
            else:
                clean.append(param.default[index])
                warnings.append(f"Valeur invalide dans « {param.label} » ({path}[{index}]).")
        return tuple(clean), warnings
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return param.default, [bad]
    if isinstance(value, float) and not math.isfinite(value):
        return param.default, [bad]
    if kind == INT:
        if isinstance(value, float):
            if value != int(value):
                return param.default, [bad]
            value = int(value)
    else:
        value = float(value)
    lo = -math.inf if param.min is None else param.min
    hi = math.inf if param.max is None else param.max
    clamped = min(max(value, lo), hi)
    if clamped != value:
        return clamped, [
            f"« {param.label} » ({path}) : {_fmt(value)} hors bornes, "
            f"ramené à {_fmt(clamped)}."
        ]
    return value, []


def _merge(raw: Mapping, params: tuple[Param, ...], extra_keys: tuple[str, ...],
           target: dict, path: tuple[str, ...], warnings: list[str]) -> None:
    by_key = {p.key: p for p in params}
    for key, value in raw.items():
        dotted = ".".join(path + (str(key),))
        if key in by_key:
            clean, issues = _coerce(by_key[key], value, dotted)
            target[key] = clean
            warnings.extend(issues)
        elif key not in extra_keys:
            warnings.append(f"Clé inconnue ignorée : {dotted}.")


def validate_params(raw: Mapping | None) -> tuple[dict, list[str]]:
    """Merge `raw` over the defaults. Returns (params, French warnings).

    Missing keys take their default, unknown keys are dropped and reported,
    out-of-range numbers are clamped and reported.
    """
    result = default_params()
    warnings: list[str] = []
    if raw is None:
        return result, warnings
    if not isinstance(raw, Mapping):
        return result, ["Les paramètres doivent être un dictionnaire ; défauts utilisés."]
    for key, value in raw.items():
        if key == "version":
            continue
        group = GROUPS.get(key)
        if group is None:
            warnings.append(f"Groupe inconnu ignoré : {key}.")
            continue
        if not isinstance(value, Mapping):
            warnings.append(f"Groupe « {group.label} » ({key}) invalide ; défauts utilisés.")
            continue
        _merge(value, group.params, SIDE_KEYS if group.side_params else (),
               result[key], (key,), warnings)
        for side in SIDE_KEYS if group.side_params else ():
            sub = value.get(side)
            if sub is None:
                continue
            if not isinstance(sub, Mapping):
                warnings.append(f"Jeu « {side} » de {key} invalide ; défauts utilisés.")
                continue
            _merge(sub, group.side_params, (), result[key][side], (key, side), warnings)
    return result, warnings
