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

from .fixtures import DEFAULT_MODE

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
FIXTURE = "fixture"  # dynamic: id of a library sheet of the declared `families`
MODE = "mode"  # dynamic: DEFAULT_MODE or a mode name of the sheet in `depends_on`

_NUMERIC = (LENGTH, ANGLE, FLOAT, INT)


@dataclass(frozen=True)
class Param:
    """One declared parameter.

    `items` is a tuple of (value, label, tooltip) for enums; `length` is the
    vector size for BOOL_VECTOR. `rebuild=False` marks a value that must not
    trigger a scene rebuild (it only drives existing objects). FIXTURE and MODE
    values are strings whose choices come from the library at runtime:
    `families` filters the sheets, `depends_on` names the sibling FIXTURE key.
    `shown_when` = (sibling key, value) hides the param from the panel otherwise.
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
    families: tuple[str, ...] = ()
    depends_on: str = ""
    shown_when: tuple[str, Any] | None = None

    @property
    def is_numeric(self) -> bool:
        return self.kind in _NUMERIC

    @property
    def is_dynamic(self) -> bool:
        return self.kind in (FIXTURE, MODE)


@dataclass(frozen=True)
class Group:
    """A panel section. `side_params` is shared by the `left` and `right` sets."""

    key: str
    label: str
    params: tuple[Param, ...]
    advanced: bool = False
    side_params: tuple[Param, ...] = ()


def _length(key, default, lo, hi, label, tooltip, **extra):
    return Param(key, LENGTH, default, label, tooltip, lo, hi, **extra)


def _angle(key, default, lo, hi, label, tooltip, **extra):
    return Param(key, ANGLE, default, label, tooltip, lo, hi, **extra)


def _flag(key, default, label, tooltip):
    return Param(key, BOOL, default, label, tooltip)


def _enum(key, default, label, tooltip, items):
    return Param(key, ENUM, default, label, tooltip, items=tuple(items))


def _int(key, default, lo, hi, label, tooltip, **extra):
    return Param(key, INT, default, label, tooltip, lo, hi, **extra)


def _float(key, default, lo, hi, label, tooltip, **extra):
    return Param(key, FLOAT, default, label, tooltip, lo, hi, **extra)


def _fixture_pair(default_id, families, what, suffix="", label="Appareil", mode_label="Mode DMX", **extra):
    """The `fixture` and `mode` params (`fixture<suffix>`, `mode<suffix>`) of a fixture-bearing group."""
    return (
        Param(f"fixture{suffix}", FIXTURE, default_id, label,
              f"Fiche de la bibliothèque pour {what}.", families=tuple(families), **extra),
        Param(f"mode{suffix}", MODE, DEFAULT_MODE, mode_label,
              "Mode DMX de l'appareil ; « Défaut » prend le mode par défaut de la fiche.",
              depends_on=f"fixture{suffix}", **extra),
    )


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

_TOWER_PARAMS = (
    _int("count", 1, 0, 4, "Nombre de pylônes", "Nombre de pylônes de ce côté (0 : aucun)."),
    _length("first_distance", 3.00, 0.0, 30.0, "Distance du premier",
            "Distance du premier pylône au nez de scène, vers la salle."),
    _length("spacing", 2.00, 1.0, 10.0, "Écart entre pylônes", "Écart entre deux pylônes voisins."),
    _length("height", 4.50, 2.0, 10.0, "Hauteur du pylône",
            "Hauteur du pylône depuis le sol de salle."),
    _int("movers", 2, 0, 6, "Mobiles par pylône", "Nombre de mobiles accrochés à chaque pylône."),
)

# (key, French label, default universe) of the DMX families, in patch order (spec 15.1).
PATCH_FAMILIES = (
    ("backlight", "Contre", 1),
    ("front_movers", "Mobiles de face", 2),
    ("tower_movers", "Mobiles des pylônes", 3),
    ("front_pc", "PC de face", 4),
    ("profiles", "Découpes", 5),
    ("hazer", "Hazer", 6),
)

_PROFILE_SIDES = (("l", "jardin"), ("c", "centre"), ("r", "cour"))


def _profile_manual_params() -> tuple[Param, ...]:
    """Manual blade setting of the three profiles, read only when `blades_mode` is `manual`."""
    shown = ("blades_mode", "manual")
    out = []
    for key, name in _PROFILE_SIDES:
        for blade in range(1, 5):
            out.append(_float(f"{key}_blade_{blade}_insertion", 0.0, 0.0, 1.0,
                              f"Lame {blade} ({name}) : insertion",
                              "0 : lame dégagée. 1 : course complète.", shown_when=shown))
            out.append(_angle(f"{key}_blade_{blade}_angle", 0.0, -45.0, 45.0,
                              f"Lame {blade} ({name}) : inclinaison",
                              "Inclinaison du bord de la lame, dans les limites de la fiche.",
                              shown_when=shown))
        out.append(_angle(f"{key}_rotation", 0.0, -90.0, 90.0, f"Rotation du cadrage ({name})",
                          "Rotation de l'ensemble des lames autour de l'axe du faisceau.",
                          shown_when=shown))
    return tuple(out)


def _barn_door_manual_params() -> tuple[Param, ...]:
    """Manual leaf setting of every PC row and direction, read only when `barn_doors` is `manual`."""
    shown = ("barn_doors", "manual")
    out = []
    for row in range(1, 5):
        for tag, name in (("l", "jardin"), ("r", "cour")):
            for leaf in range(1, 5):
                out.append(_angle(f"row{row}_{tag}_leaf_{leaf}", 0.0, 0.0, 80.0,
                                  f"Volet {leaf} (rang {row}, {name})",
                                  "Fermeture du volet : 0 dégagé, parallèle au faisceau.", shown_when=shown))
            out.append(_angle(f"row{row}_{tag}_rotation", 0.0, -90.0, 90.0,
                              f"Rotation des volets (rang {row}, {name})",
                              "Rotation de l'ensemble des volets autour de l'axe du faisceau, "
                              "dans les limites de la fiche.", shown_when=shown))
    return tuple(out)


def _patch_params() -> tuple[Param, ...]:
    out = []
    for key, label, universe in PATCH_FAMILIES:
        out.append(_int(f"{key}_universe", universe, 1, 63999, f"Univers : {label}",
                        f"Univers DMX de départ de la famille « {label} »."))
        out.append(_int(f"{key}_address", 1, 1, 512, f"Adresse : {label}",
                        f"Adresse DMX du premier appareil de la famille « {label} »."))
    return tuple(out)


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
    Group("rig", "Implantation lumière", (
        _flag("enabled", True, "Implantation lumière",
              "Appareils, porteuses, pylônes et patch DMX. Décoché : aucun objet ni patch."),
        _length("aim_height", 1.70, 0.50, 2.50, "Hauteur de visée",
                "Hauteur de visée au-dessus du plancher."),
        _angle("site", 45.0, 20.0, 70.0, "Site de face",
               "Élévation du faisceau des projecteurs de face (45° : méthode McCandless)."),
        _length("area_depth", 6.00, 1.0, 30.0, "Profondeur de la zone de jeu",
                "Profondeur de la zone de jeu éclairée, depuis le nez de scène."),
    )),
    Group("rig_front", "Perche de face", (
        _length("ceiling_gap", 0.30, 0.05, 2.0, "Écart sous plafond",
                "Écart de la perche de face sous le plafond de salle."),
        _flag("auto_position", True, "Position calculée", "Calcule la position en Y de la perche."),
        _length("y", -1.40, -30.0, 5.0, "Position en Y",
                "Position en Y de la perche, mode manuel (négatif : côté salle).",
                shown_when=("auto_position", False)),
        _length("movers_offset", 1.50, 0.5, 10.0, "Recul de la perche des mobiles",
                "Distance en Y entre la perche de face et la seconde perche, côté salle, "
                "qui porte les mobiles de face."),
        _enum("movers_height_mode", "auto", "Hauteur de la perche des mobiles",
              "Hauteur de la seconde perche : calculée pour dégager faisceaux et corps, ou imposée.", (
                  ("auto", "Calculée", "La plus haute hauteur dont aucun faisceau ne rencontre un appareil."),
                  ("manual", "Manuelle", "Hauteur imposée par « Hauteur de la perche des mobiles »."),
              )),
        _length("movers_z", 6.80, 2.0, 15.0, "Hauteur manuelle",
                "Hauteur de la seconde perche, mode manuel.",
                shown_when=("movers_height_mode", "manual")),
    )),
    Group("backlight", "Contre", (
        _flag("enabled", True, "Contre", "Appareils de contre, accrochés à une porteuse."),
        *_fixture_pair("martin_mac_aura", ("moving_wash",), "le contre"),
        _int("count", 6, 1, 24, "Nombre d'appareils", "Nombre d'appareils de contre."),
        _enum("position", "upstage", "Position", "Porteuse qui reçoit le contre.", (
            ("upstage", "Perche fond de scène", "La porteuse lumière la plus reculée."),
            ("distance", "Distance au nez", "La porteuse la plus proche de la distance réglée."),
        )),
        _length("distance", 3.10, 0.50, 30.0, "Distance au nez",
                "Distance au nez de scène de la porteuse visée.",
                shown_when=("position", "distance")),
    )),
    Group("front_movers", "Mobiles de face", (
        _flag("enabled", True, "Mobiles de face", "Mobiles accrochés à la perche de face."),
        *_fixture_pair("robe_robin_esprite", ("moving_wash", "moving_profile"),
                       "les mobiles de face"),
        _int("count", 4, 1, 16, "Nombre d'appareils", "Nombre de mobiles de face."),
    )),
    Group("towers", "Pylônes", (
        _flag("symmetric", True, "Symétrique",
              "Applique le jeu de gauche aux deux côtés, en miroir."),
        *_fixture_pair("robe_robin_esprite", ("moving_wash", "moving_profile"),
                       "les mobiles de pylône"),
        _length("truss_size", 0.30, 0.15, 0.60, "Section du truss",
                "Côté de la section carrée du truss."),
        _length("base_size", 0.80, 0.30, 2.0, "Côté de la platine", "Côté de la platine du pylône."),
    ), side_params=_TOWER_PARAMS),
    Group("front_pc", "PC de face", (
        _flag("enabled", True, "PC de face", "PC de face, deux par zone, un par direction."),
        *_fixture_pair("generic_pc_led", ("pc",), "les PC du premier rang, sur la perche de face",
                       label="Appareil du premier rang",
                       mode_label="Mode DMX du premier rang"),
        *_fixture_pair("generic_fresnel_led", ("pc",), "les rangs du fond, sur les porteuses de la scène",
                       suffix="_far", label="Appareil des rangs du fond",
                       mode_label="Mode DMX des rangs du fond"),
        _enum("zone_mode", "auto", "Découpage en zones", "Découpage de la zone de jeu.", (
            ("auto", "Automatique", "Zones de la largeur visée."),
            ("manual", "Manuel", "Nombre de colonnes et de rangs réglé à la main."),
        )),
        _length("zone_width", 3.00, 1.0, 10.0, "Largeur de zone visée",
                "Largeur de zone visée en mode automatique.", shown_when=("zone_mode", "auto")),
        _int("columns", 3, 1, 8, "Zones en largeur", "Nombre de zones en largeur (mode manuel).",
             shown_when=("zone_mode", "manual")),
        _int("rows", 2, 1, 4, "Rangs en profondeur", "Nombre de rangs en profondeur (mode manuel).",
             shown_when=("zone_mode", "manual")),
        _angle("azimuth", 45.0, 10.0, 80.0, "Azimut de croisement",
               "Angle en plan entre l'axe de la salle et chaque faisceau (45° : fiche ADEC 6-3)."),
        _float("overlap", 0.20, 0.0, 1.0, "Recouvrement",
               "Fraction de la taille d'une zone ajoutée au champ couvert, pour les zones voisines."),
        _length("window_margin", 0.0, 0.0, 2.0, "Marge de la fenêtre de face",
                "Distance dont la fenêtre de face (l'ouverture de la façade, du nez au linteau) est rétrécie "
                "de chaque côté : la lumière de face doit y rester."),
        _float("min_mean_ratio", 0.85, 0.5, 1.0, "Moyenne minimale de l'égalisation",
               "Part de l'éclairement moyen du rig plein que l'égalisation de la face doit conserver."),
        _enum("barn_doors", "auto", "Volets", "Volets (coupe-flux) des PC dont la fiche en porte.", (
            ("none", "Aucun", "Pas de volets."),
            ("auto", "Automatique", "Volets fermés sur la limite à ne pas éclairer."),
            ("manual", "Manuel", "Fermeture et rotation réglées à la main, par rang et par direction."),
        )),
        *_barn_door_manual_params(),
    )),
    Group("profiles", "Découpes", (
        _flag("enabled", True, "Découpes", "Trois découpes de face : jardin, centre, cour."),
        *_fixture_pair("etc_s4led_s3_lustr_x8", ("profile",), "les découpes"),
        _length("lintel_margin", 0.10, 0.0, 1.0, "Marge sous le linteau",
                "Marge sous le linteau pour la coupe haute."),
        _length("top_height", 2.20, 1.0, 6.0, "Hauteur de coupe haute",
                "Hauteur au-dessus du plateau du haut d'un comédien debout, au fond de la zone de jeu."),
        _angle("tube_angle", 0.0, 0.0, 90.0, "Tube de lentille",
               "Angle de champ du tube de lentille. 0 : choisi automatiquement."),
        _enum("blades_mode", "auto", "Lames", "Réglage des lames des découpes.", (
            ("auto", "Automatique", "Lames calculées pour cadrer la zone."),
            ("manual", "Manuel", "Insertion et inclinaison réglées à la main."),
        )),
        *_profile_manual_params(),
    )),
    Group("rest", "Repos", (
        _float("pc_level", 0.70, 0.0, 1.0, "Niveau des PC", "Niveau des PC de face au repos."),
        _float("profile_level", 0.70, 0.0, 1.0, "Niveau des découpes",
               "Niveau des découpes au repos."),
        _float("mover_level", 0.50, 0.0, 1.0, "Niveau des mobiles",
               "Niveau des mobiles au repos (contre, face et pylônes)."),
        _float("haze_level", 1.00, 0.0, 1.0, "Niveau du hazer", "Niveau du hazer au repos."),
        _int("cct_left", 3200, 1500, 12000, "Température jardin (K)",
             "Température de couleur des PC accrochés côté jardin."),
        _int("cct_right", 5600, 1500, 12000, "Température cour (K)",
             "Température de couleur des PC accrochés côté cour."),
        _int("cct_profile", 4000, 1500, 12000, "Température découpes (K)",
             "Température de couleur des découpes."),
    )),
    Group("patch", "Patch DMX", _patch_params()),
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
        _flag("dmx_driven", False, "Densité pilotée par le hazer",
              "La densité suit le canal du hazer DMX : un hazer est créé et patché."),
        *_fixture_pair("generic_hazer", ("hazer",), "le hazer", shown_when=("dmx_driven", True)),
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


def side_sets(node: Mapping) -> tuple[Mapping, Mapping]:
    """(left, right) parameter sets of `modules` or `towers`; right is left when symmetric."""
    left = node["left"]
    return left, (left if node["symmetric"] else node["right"])


module_sets = side_sets


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
    if param.is_dynamic:
        return (value, []) if isinstance(value, str) and value.strip() else (param.default, [bad])
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


def check_catalog(params: dict, catalog, warnings: list[str]) -> None:
    """Reset FIXTURE and MODE values the library does not know (spec 9), in place.

    `catalog` offers `get(id)` returning an object with `family` and
    `mode_names()`, or None (a fixtures.Library). A value equal to the default
    is left alone: a missing default sheet is reported by the library itself.
    """
    for group in SCHEMA:
        node = params[group.key]
        for param in group.params:
            if param.kind != FIXTURE:
                continue
            sheet = catalog.get(node[param.key])
            if sheet is not None and sheet.family in param.families:
                _check_mode(node, group, param, sheet, warnings)
            elif node[param.key] != param.default:
                warnings.append(
                    f"Appareil « {node[param.key]} » ({group.key}.{param.key}) absent de la "
                    f"bibliothèque ou de la mauvaise famille, défaut utilisé.")
                node[param.key] = param.default


def _check_mode(node: dict, group: Group, fixture_param: Param, sheet, warnings: list[str]) -> None:
    for param in group.params:
        if param.kind == MODE and param.depends_on == fixture_param.key:
            value = node[param.key]
            if value != DEFAULT_MODE and value not in sheet.mode_names():
                warnings.append(f"Mode « {value} » ({group.key}.{param.key}) inconnu de la fiche, "
                                f"défaut utilisé.")
                node[param.key] = param.default


def validate_params(raw: Mapping | None, catalog=None) -> tuple[dict, list[str]]:
    """Merge `raw` over the defaults. Returns (params, French warnings).

    Missing keys take their default, unknown keys are dropped and reported,
    out-of-range numbers are clamped and reported. With a `catalog`, unknown
    fixture ids and modes fall back to the default and are reported (spec 9).
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
    if catalog is not None:
        check_catalog(result, catalog, warnings)
    return result, warnings
