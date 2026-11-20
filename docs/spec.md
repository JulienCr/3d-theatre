# Scène de théâtre paramétrique — spécification

Extension Blender 5.3 qui génère une maquette de scénographie à l'échelle 1:1 :
plateau, enceinte, cadre, cage de scène, gril, escaliers, modules latéraux,
pendrillonnage, rideaux, lumières de travail, implantation lumière (appareils
pilotés en DMX) et caméras vue public. Toute la
géométrie se déduit d'un jeu de paramètres réglables dans un panneau et
enregistrables en préréglages YAML.

Les valeurs par défaut viennent de `references/salle/` (plan coté, cotes,
vues d'artiste). Ce sont des hypothèses de modélisation, pas un relevé. Les
valeurs marquées *(choix)* n'ont aucune source et sont à ajuster.

## 1. Repère et conventions

- Unité : le mètre.
- X latéral, Y profondeur **positive vers le fond de scène**, Z vertical.
- Origine : centre du nez de scène, au niveau du **sol de la salle** (Z = 0).
- Vu depuis la salle (regard vers +Y), +X est à droite.
  **Gauche = jardin = X négatif**, **droite = cour = X positif**.
- Suffixes de noms : `_L` (jardin), `_R` (cour), `_C` (centre),
  `_NN` (index sur deux chiffres, à partir de 01, de la face vers le fond).

## 2. Architecture du code

```
blender/theatre_stage/
  blender_manifest.toml      extension Blender 5.3, wheel PyYAML embarquée
  __init__.py                register / unregister
  core/                      Python pur, sans bpy, testé
    params.py                schéma unique des paramètres
    layout.py                paramètres -> cotes et volumes (dataclasses)
    presets.py               lecture / écriture YAML, validation
    fixtures.py              fiches d'appareils, attributs DMX, 8/16 bits, photométrie
    meshio.py                lecture .obj et .glb (sommets, faces) sans bpy
    rig.py                   implantation (perche, pylônes, zones, visées, lames), patch
    qlc.py                   génération texte des .qxw et .qxf (XML)
  props.py                   PropertyGroup généré depuis le schéma
  build.py                   cotes -> objets, matériaux, lumières, caméras
  rigbuild.py                implantation -> objets, hiérarchies d'appareils, drivers, nœuds
  ui.py                      panneau « Théâtre » dans la barre latérale 3D
  presets/                   préréglages livrés (YAML)
  library/fixtures/<id>/     fiches livrées : fixture.yaml, source/, meshes/, gobos/
tools/                       scripts système (Python + pytest + PyYAML), hors extension
  gdtf_to_fiche.py           GDTF -> fiche pré-remplie
  check_qlc_fixture.py       fiche <-> définition .qxf de QLC+
tests/                       pytest, hors Blender
```

- **Une seule source de vérité.** `core/params.py` déclare chaque paramètre :
  clé anglaise, groupe, type, défaut, bornes, libellé français, info-bulle.
  La PropertyGroup, le panneau et les clés YAML en dérivent.
- **`core/` ne connaît pas Blender.** `fixtures.py` ne lit que le YAML des
  fiches, jamais un GDTF. `layout.py` prend un dictionnaire de
  paramètres et rend une description complète de la scène : boîtes,
  polygones extrudés, transformations, positions de lumières et de caméras,
  cotes calculées, alertes. `build.py` ne fait que traduire cette
  description en objets ; il ne calcule aucune cote.
- Les tests importent `core` en ajoutant `blender/theatre_stage` au
  `sys.path` ; `core/` n'utilise que des imports relatifs internes.

## 3. Paramètres

Les clés sont celles du YAML et du code. Bornes indicatives, à affiner à
l'usage.

### 3.1 Plateau — `stage`

| Clé | Libellé | Défaut | Bornes |
|---|---|---|---|
| `width` | Largeur du plateau (nez de scène) | 11,60 | 4 – 30 |
| `depth` | Profondeur de scène (nez → fond) | 7,00 | 3 – 30 |
| `grid_height` | Hauteur sous gril (depuis le plancher) | 6,10 | 3 – 25 |
| `wings` | Largeur des coulisses, de chaque côté *(choix)* | 2,00 | 0 – 15 |

`grid_height` est déduite : 7,30 (façade) − 1,20 (plateau). Les coulisses
prolongent la cage au-delà de l'ouverture du cadre, derrière la façade.

### 3.2 Avancé — `advanced` (sous-panneau replié)

| Clé | Libellé | Défaut | Bornes |
|---|---|---|---|
| `stage_height` | Hauteur du plateau | 1,20 | 0,20 – 2,50 |
| `apron_depth` | Profondeur d'avant-scène (sol de salle devant le nez) | 3,10 | 0,50 – 15 |
| `facade_height` | Hauteur de la façade (depuis le sol de salle) | 7,30 | 3 – 30 |
| `proscenium_height` | Hauteur d'ouverture du cadre (depuis le plancher) | 5,00 | 2 – 20 |
| `proscenium_thickness` | Largeur d'un montant du cadre | 0,80 | 0,10 – 3 |
| `proscenium_setback` | Recul de la façade derrière le nez | 1,20 | 0 – 5 |
| `lintel_height` | Hauteur du linteau noir | 0,80 | 0,10 – 3 |
| `side_zone_width` | Largeur minimale des zones latérales | 1,20 | 0 – 10 |

`proscenium_setback` est estimé sur le plan « espace ouvert » (≈ 1,3 m) et
arrondi à la largeur d'escalier, pour que le palier tienne exactement entre
le nez et la façade.

### 3.3 Escaliers — `stairs`

| Clé | Libellé | Défaut | Bornes |
|---|---|---|---|
| `left` | Escalier jardin | oui | |
| `right` | Escalier cour | oui | |
| `center` | Escalier central | non | |
| `riser_max` | Contremarche maximale | 0,20 | 0,10 – 0,25 |
| `going` | Giron | 0,30 | 0,20 – 0,45 |
| `width` | Largeur des escaliers latéraux | 1,20 | 0,60 – 3 |
| `side_angle` | Angle des escaliers latéraux (−90° centre, 0° salle, 90° mur) | 90° | −90 – 90 |
| `side_offset` | Décalage latéral du palier (+ vers le mur, − vers le centre) | 0,00 | −10 – 10 |
| `clearance` | Dégagement au pied de l'escalier *(choix)* | 1,00 | 0 – 5 |
| `landing_depth` | Profondeur du palier (0 = sans palier) | 1,20 | 0 – 5 |
| `center_width` | Largeur de l'escalier central *(choix)* | 2,00 | 0,60 – 10 |

### 3.4 Modules — `modules`

`symmetric` (défaut oui) : le panneau n'affiche qu'un jeu, appliqué aux deux
côtés en miroir. Décoché, les jeux `left` et `right` sont indépendants. Chaque
jeu :

| Clé | Libellé | Défaut | Bornes |
|---|---|---|---|
| `enabled` | Module présent | oui | |
| `frame_gap` | Écart de la charnière au bord du cadre (+ vers l'axe, − vers les coulisses) | 0,00 | −10 – 5 |
| `setback` | Recul de la charnière depuis le nez | 2,05 | 0 – 30 |
| `width` | Largeur de la face avant | 1,55 | 0,40 – 10 |
| `depth` | Profondeur du retour *(choix)* | 2,00 | 0,10 – 20 |
| `height` | Hauteur | 5,00 | 1 – 20 |
| `angle` | Angle en plan | 0° | 0 – 90 |
| `door_enabled` | Porte | oui | |
| `door_width` / `door_height` | Porte | 0,94 × 2,40 | |
| `door_offset` | Décalage de la porte (+ vers le plateau) | 0,00 | |
| `window_enabled` | Fenêtre | non | |
| `window_width` / `window_height` | Fenêtre *(choix)* | 1,00 × 1,20 | |
| `window_sill` | Allège *(choix)* | 1,00 | |
| `window_offset` | Décalage de la fenêtre | 0,00 | |

Largeur 1,55 = bord du cadre (5,00 de l'axe) − bord intérieur des références
(3,45 de l'axe, soit l'ouverture de 6,90 m). Porte 0,94 × 2,40 du fichier de
cotes ; le plan SVG indique 1,00 × 2,40.

### 3.5 Gril — `grid`

| Clé | Libellé | Défaut | Bornes |
|---|---|---|---|
| `batten_spacing` | Espacement des porteuses *(choix)* | 1,00 | 0,20 – 5 |
| `batten_drop` | Porteuses sous le gril | 0,50 | 0 – 10 |

La porteuse de la dernière rue (fond de scène) vient en plus de ce réseau régulier : section 5.5.

### 3.6 Lumières de travail — `lights`

| Clé | Libellé | Défaut | Bornes |
|---|---|---|---|
| `enabled` | Lumières de travail | oui | |
| `spacing` | Maille de la grille *(choix)* | 3,00 | 1 – 10 |
| `intensity` | Intensité (multiplicateur) | 1,00 | 0 – 10 |
| `front` | Face depuis la salle | oui | |

### 3.7 Caméras — `cameras`

| Clé | Libellé | Défaut | Bornes |
|---|---|---|---|
| `distance` | Distance au nez de scène *(choix)* | 11,00 | 2 – 60 |
| `height` | Hauteur au-dessus du sol de salle *(choix)* | 3,00 | 0,5 – 30 |
| `lens` | Focale (mm) *(choix)* | 22 | 10 – 200 |

Valeurs réglées sur capture pour retrouver le cadrage de
`scene-vue-artiste.png`.

### 3.7 bis Salle — `house`

| Clé | Libellé | Défaut | Bornes |
|---|---|---|---|
| `ceiling` | Plafond de salle | oui | |

### 3.8 Pendrillonnage — `masking`

| Clé | Libellé | Défaut | Bornes |
|---|---|---|---|
| `style` | Style de pendrillonnage | italienne | italienne / allemande |
| `lanes` | Nombre de rues | 3 | 1 – 8 |
| `opening` | Ouverture entre pendrillons *(choix)* | 8,00 | 2 – 30 |
| `front_border` | Frise de face | oui | |
| `borders` | Frises par plan (une case par plan) | toutes cochées | 8 booléens |
| `border_bottom` | Bas des frises, au-dessus du plateau *(choix)* | 4,50 | 1 – 20 |
| `backdrop` | Fond de scène | rideau noir | rideau noir / mur nu / cyclorama |
| `drape` | Drapé (irrégularité des plis) | 0,5 | 0 – 1 |
| `leg_angle` | Inclinaison des pendrillons (à l'italienne) | 0° | 0 – 20 |
| `convergence` | Convergence de l'ouverture vers le lointain (à l'italienne) | 0° | 0 – 20 |
| `borders_mode` | Hauteur des frises | calées sur la découverte | calées sur la découverte / manuelle |

Le panneau n'affiche que les `lanes` premières cases de `borders`.
`border_bottom` ne sert qu'en mode manuel. Parallèles = 0° / 0°, en biais =
inclinaison / 0°, convergents = inclinaison / convergence.

### 3.8 bis Découverte — `sightlines`

| Clé | Libellé | Défaut | Bornes |
|---|---|---|---|
| `seat_distance` | Premier rang : distance au nez *(choix)* | 2,00 | 0,50 – 30 |
| `seat_wall_gap` | Fauteuil extrême : écart au mur de salle *(choix)* | 0,50 | 0 – 10 |
| `eye_height` | Hauteur d'œil, assis, au-dessus du sol de salle *(choix)* | 1,10 | 0,80 – 3 |

Source de la méthode : machinerie-spectacle.org, « Tracer une découverte »
(fauteuil de référence au premier rang, à l'extrémité jardin ou cour, tracé
en plan puis en coupe, plan par plan vers le lointain). La page ne donne
aucun chiffre : les trois valeurs ci-dessus sont des choix.

### 3.9 Rideau de scène — `curtains`

| Clé | Libellé | Défaut | Bornes |
|---|---|---|---|
| `main_enabled` | Rideau de scène (à la grecque) | oui | |
| `main_opening` | Ouverture du rideau (%) — **animable** | 100 | 0 – 100 |

`main_opening` est le seul paramètre qui **ne reconstruit pas** la scène : il
n'agit que par driver (section 8.5).

### 3.10 Implantation lumière — `rig`

| Clé | Libellé | Défaut | Bornes |
|---|---|---|---|
| `enabled` | Implantation lumière | oui | |
| `aim_height` | Hauteur de visée au-dessus du plancher *(choix)* | 1,70 | 0,50 – 2,50 |
| `site` | Site de référence des projecteurs de face (élévation du faisceau) | 45° | 20 – 70 |
| `area_depth` | Profondeur de la zone de jeu depuis le nez *(choix)* | 6,00 | 1 – 30 |

Site 45° : fiche ADEC 6-3, méthode McCandless (45° de site, 45° d'azimut,
section 13). `enabled` décoché : aucun objet de la section 13, aucun patch.

### 3.11 Perche de face — `rig_front`

| Clé | Libellé | Défaut | Bornes |
|---|---|---|---|
| `ceiling_gap` | Écart de la perche sous le plafond de salle *(choix)* | 0,30 | 0,05 – 2 |
| `auto_position` | Position en Y calculée | oui | |
| `y` | Position en Y, mode manuel | −1,40 | −30 – 5 |
| `movers_offset` | Recul de la seconde perche, celle des mobiles de face *(choix)* | 1,50 | 0,50 – 10 |
| `movers_height_mode` | Hauteur de la seconde perche | `auto` | énumération (1) |
| `movers_z` | Hauteur de la seconde perche, mode manuel | 6,75 | 2 – 15 |

(1) `auto` (« Calculée ») : la plus haute hauteur dont aucun faisceau ne
rencontre un appareil (13.2 bis) ; `manual` (« Manuelle ») : `movers_z`. Le
panneau n'affiche `movers_z` que dans ce second mode.

Les défauts manuels (`y`, `movers_z`) sont les valeurs que donne le calcul avec
les défauts (sections 13.2 et 13.2 bis).

### 3.12 Contre — `backlight`

| Clé | Libellé | Défaut | Bornes |
|---|---|---|---|
| `enabled` | Contre | oui | |
| `fixture` | Appareil | `martin_mac_aura` | énumération (1) |
| `mode` | Mode DMX | mode par défaut de la fiche | énumération (2) |
| `count` | Nombre d'appareils | 6 | 1 – 24 |
| `position` | Position | `upstage` | énumération (3) |
| `distance` | Distance au nez de la porteuse visée *(choix)*, seulement en mode `distance` | 3,10 | 0,50 – 30 |

(1) Énumération **dynamique** : les `id` des fiches de la bibliothèque dont la
famille convient (section 12.2), relue au chargement de l'extension et par le
bouton « Recharger la bibliothèque ». Un `id` inconnu dans un préréglage donne
le défaut du paramètre et un avertissement.
(2) Énumération dynamique : `default` (mode par défaut de la fiche) et les noms
des modes de l'appareil choisi.
(3) `upstage` (« Perche fond de scène », défaut) : la porteuse lumière la plus
reculée qui reste devant la ligne de fond `Yb` (5.5) ; `distance` : la
porteuse la plus proche de `distance` (13.4). Le panneau n'affiche `distance`
que dans ce second mode.

Défaut `upstage` *(choix)* : un contre accroché à mi-scène (Y = 3,10 avec le
pendrillonnage par défaut) n'est pas à la perche du fond, où l'on attend le
contre. `distance` garde 3,10 *(choix)* pour le mode `distance`.

### 3.13 Mobiles de face — `front_movers`

| Clé | Libellé | Défaut | Bornes |
|---|---|---|---|
| `enabled` | Mobiles de face | oui | |
| `fixture` | Appareil | `robe_robin_esprite` | énumération |
| `mode` | Mode DMX | mode par défaut de la fiche | énumération |
| `count` | Nombre d'appareils | 4 | 1 – 16 |

### 3.14 Pylônes — `towers`

`symmetric` (défaut oui) : même règle que `modules` (un jeu, appliqué aux deux
côtés en miroir ; décoché, jeux `left` et `right` indépendants). Hors jeux :

| Clé | Libellé | Défaut | Bornes |
|---|---|---|---|
| `symmetric` | Symétrique | oui | |
| `fixture` | Appareil | `robe_robin_esprite` | énumération |
| `mode` | Mode DMX | mode par défaut de la fiche | énumération |
| `truss_size` | Côté de la section carrée du truss *(choix)* | 0,30 | 0,15 – 0,60 |
| `base_size` | Côté de la platine *(choix)* | 0,80 | 0,30 – 2 |

Chaque jeu :

| Clé | Libellé | Défaut | Bornes |
|---|---|---|---|
| `count` | Nombre de pylônes (0 = aucun) | 1 | 0 – 4 |
| `first_distance` | Distance du premier pylône au nez *(choix)* | 3,00 | 0 – 30 |
| `spacing` | Écart entre pylônes *(choix)* | 2,00 | 1 – 10 |
| `height` | Hauteur du pylône, depuis le sol de salle *(choix)* | 4,50 | 2 – 10 |
| `movers` | Mobiles par pylône | 2 | 0 – 6 |

### 3.15 PC de face — `front_pc`

| Clé | Libellé | Défaut | Bornes |
|---|---|---|---|
| `enabled` | PC de face | oui | |
| `fixture` | Appareil | `generic_pc_led` | énumération |
| `mode` | Mode DMX | mode par défaut de la fiche | énumération |
| `zone_mode` | Découpage en zones | automatique | automatique / manuel |
| `zone_width` | Largeur de zone **maximale** *(choix)* | 3,00 | 1 – 10 |
| `columns` | Zones en largeur (mode manuel) | 3 | 1 – 8 |
| `rows` | Rangs en profondeur (mode manuel) | 2 | 1 – 4 |
| `azimuth` | Azimut de croisement | 45° | 10 – 80 |
| `overlap` | Recouvrement des zones voisines *(choix)* | 0,20 | 0 – 1 |

`overlap` : fraction de la taille d'une zone ajoutée au champ couvert (section
13.7). Azimut 45° : fiche ADEC 6-3, nominal : 13.7 le règle rang par rang
dans ±10°. `zone_width` est un plafond : le nombre de zones est arrondi au
supérieur (13.1).

### 3.16 Découpes — `profiles`

| Clé | Libellé | Défaut | Bornes |
|---|---|---|---|
| `enabled` | Découpes | oui | |
| `fixture` | Appareil | `etc_s4led_s3_lustr_x8` | énumération |
| `mode` | Mode DMX | mode par défaut de la fiche | énumération |
| `lintel_margin` | Marge sous le linteau pour la coupe haute *(choix)* | 0,10 | 0 – 1 |
| `top_height` | Hauteur de la coupe haute au-dessus du plateau *(choix)* | 2,20 | 1 – 6 |
| `tube_angle` | Tube de lentille (0 = choisi automatiquement) | 0 | 0 – 90 |
| `blades_mode` | Lames | automatique | automatique / manuel |

Réglage manuel, lu seulement si `blades_mode` vaut `manual`. Le schéma
déclare ces clés par boucle, comme `_MODULE_PARAMS`, pour chacune des trois
découpes `p` = `l` (jardin), `c` (centre), `r` (cour) et chacune des quatre
lames `b` = 1 à 4 :

| Clé | Libellé | Défaut | Bornes |
|---|---|---|---|
| `<p>_blade_<b>_insertion` | Insertion de la lame (0 = dégagée, 1 = course complète) | 0 | 0 – 1 |
| `<p>_blade_<b>_angle` | Inclinaison de la lame | 0° | −45 – 45 |
| `<p>_rotation` | Rotation du cadrage | 0° | −90 – 90 |

La numérotation des lames est celle de la fiche (section 12.2). Une valeur
hors de la course ou de l'inclinaison permise par la fiche est ramenée dans
la plage et signalée.

### 3.17 Repos — `rest`

| Clé | Libellé | Défaut | Bornes |
|---|---|---|---|
| `pc_level` | Niveau des PC de face *(choix)* | 0,70 | 0 – 1 |
| `profile_level` | Niveau des découpes *(choix)* | 0,70 | 0 – 1 |
| `mover_level` | Niveau des mobiles *(choix)* | 0,50 | 0 – 1 |
| `haze_level` | Niveau du hazer *(choix)* | 1,00 | 0 – 1 |
| `cct_left` | Température de couleur, PC accrochés côté jardin, en K *(choix)* | 3200 | 1500 – 12000 |
| `cct_right` | Température de couleur, PC accrochés côté cour, en K *(choix)* | 5600 | 1500 – 12000 |
| `cct_profile` | Température de couleur des découpes, en K *(choix)* | 4000 | 1500 – 12000 |

### 3.18 Patch DMX — `patch`

Une famille = un univers de départ et une adresse de départ (deux entiers).
Familles : `backlight`, `front_movers`, `tower_movers`, `front_pc`,
`profiles`, `hazer`.

| Clé | Libellé | Défaut | Bornes |
|---|---|---|---|
| `<famille>_universe` | Univers de la famille | `backlight` 1, `front_movers` 2, `tower_movers` 3, `front_pc` 4, `profiles` 5, `hazer` 6 *(choix)* | 1 – 63999 |
| `<famille>_address` | Adresse de départ | 1 | 1 – 512 |

Un univers par famille évite tout recouvrement et tout dépassement de 512
canaux avec les défauts *(choix)*.

## 4. Cotes dérivées

Notations : `W` largeur plateau, `D` profondeur, `Hp` hauteur plateau,
`Hg` hauteur sous gril, `Hc` hauteur du cadre, `Tc` largeur d'un montant,
`Ys` recul de façade, `A` avant-scène.

Constantes (non exposées) : épaisseur de façade 0,30 ; profondeur du cadre
0,40, sa face avant en retrait de 0,05 derrière la façade ; épaisseur des
murs de cage 0,20 ; parement de plancher 0,03 ; liseré du nez 0,05 ;
épaisseur des parois de module 0,10 ; tube de porteuse Ø 0,048.

- Ouverture du cadre : `Wc = W − 2·Tc` (10,00 par défaut).
- Largeur de cage, coulisses comprises : `Wk = Wc + 2·wings` (14,00 par
  défaut). Les murs de cage sont à `X = ±Wk/2`.
- Avant de cage : `Yc = Ys + 0,40` (1,60 par défaut). La cage s'étend de
  `Yc` à `D`.
- Zone latérale effective : `Z = max(side_zone_width, emprise escalier)`,
  l'emprise ne comptant que si au moins un escalier latéral est présent.
  **La même valeur s'applique des deux côtés** : l'enceinte reste
  symétrique.
- Largeur hors tout : `Wt = W + 2·Z`. Avec les escaliers à 0°, on retrouve
  les 14,00 m des références ; à 90°, 19,00 m (palier 1,20 + volée 1,50 +
  dégagement 1,00 de chaque côté).
- Escaliers : nombre de contremarches `n = ceil(Hp / riser_max)` (avec une
  tolérance de 1e-9 pour que 1,20 / 0,20 donne 6), contremarche réelle
  `Hp / n`, `n − 1` marches sous le palier, volée de longueur
  `L = (n − 1)·going`.

## 5. Géométrie

### 5.1 Salle et enceinte (matériau `TS_Enclosure`, rouge)

- Profondeur de salle dessinée : `Yh = max(A, cameras.distance + 1,00)`, pour
  que les caméras ne voient pas de vide sous elles. La salle reste un sol,
  deux murs nus et un plafond (pas de gradins).
- `House_Ceiling` (`TS_HouseCeiling`, si `house.ceiling`) : une seule face
  tournée vers le bas, à `Z = facade_height`, X sur `[−Wt/2, Wt/2]`, Y sur
  `[−Yh, Ys]`. **Visible seulement depuis la salle** : vu d'au-dessus, on voit
  l'intérieur à travers. Le matériau masque la face arrière en EEVEE et dans
  la vue (backface culling) et en Cycles (mélange avec un Transparent piloté
  par `Geometry > Backfacing`). Un matériau de remplacement (BlenderKit) qui
  n'a pas ce réglage rend le plafond visible de dessus.
- `House_Floor` : dalle grise (`TS_HouseFloor`), X sur `[−Wt/2, Wt/2]`,
  Y sur `[−Yh, Ys]`, Z de −0,10 à 0.
- `House_Wall_L` / `House_Wall_R` : face intérieure à `X = ∓Wt/2`,
  épaisseur 0,30 vers l'extérieur, Y sur `[−Yh, Ys]`, Z de 0 à la façade.
- `Facade` : face avant à `Y = Ys`, épaisseur 0,30, rectangle
  `[−Wt/2, Wt/2] × [0, facade_height]` **percé** de
  `[−W/2, W/2] × [0, Hp + Hc + lintel_height]`. Le plateau passe dans le
  bas de ce trou ; sous le plateau, dans les zones latérales, la façade
  descend jusqu'au sol.

### 5.2 Cadre (`TS_Proscenium`, noir)

- `Proscenium_Post_L` / `_R` : X sur `[Wc/2, W/2]` (et miroir), Z de `Hp` à
  `Hp + Hc`, Y sur `[Ys + 0,05, Ys + 0,40]`.
- `Proscenium_Lintel` : X sur `[−W/2, W/2]`, Z de `Hp + Hc` à
  `Hp + Hc + lintel_height`, même Y.
- Les montants couvrent le passage de la largeur du nez (`W`) à l'ouverture
  du cadre (`Wc`) : **aucun pan coupé** n'est dessiné en v1.

### 5.3 Plateau

- `Stage_Base` (`TS_StageBase`, noir) : avant-plateau `W × Yc` puis plateau de
  cage `Wk × (D − Yc)`, coulisses comprises, de Z = 0 à `Hp − 0,03`.
- `Stage_Floor` (`TS_StageFloor`, bois) : même contour, parement de 0,03,
  dessus à `Z = Hp`. Contour en un seul polygone extrudé (forme en T).
- `Stage_Front` (`TS_Enclosure`) : bandeau rouge, face avant du plateau à
  `Y = 0`, X sur `[−W/2, W/2]`, Z de 0 à `Hp − 0,05`.
- `Stage_Nosing` (`TS_Nosing`, noir) : liseré de 0,05 en haut du bandeau.

### 5.4 Cage (`TS_Cage`, noir)

- `Cage_Wall_L` / `_R` : face intérieure à `X = ∓Wk/2`, Y sur `[Yc, D]`,
  Z de `Hp` au toit.
- `Cage_Front_L` / `_R` : entre la façade et la cage, fermeture des coulisses
  côté salle, X de `±W/2` à `±(Wk/2 + 0,20)`, Y sur `[Ys + 0,30, Yc]`, Z de
  `Hp` au toit (seulement si `Wk > W`).
- `Cage_Back` : face avant à `Y = D`, largeur `Wk`, mêmes hauteurs. C'est le
  « mur nu » du fond de scène.
- `Cage_Roof` : à `Hp + Hg + 2,00` (hauteur de circulation sur le gril).

### 5.5 Gril et porteuses

- `Grid_Deck` (`TS_Grid`) : caillebotis à `Z = Hp + Hg` (dessous), lattes de
  0,05 × 0,05 parallèles à Y tous les 0,15, sur toute la cage.
- Porteuses `Batten_NN` (`TS_Batten`) : tubes Ø 0,048 parallèles au nez, de
  `X = −Wk/2 + 0,10` à `Wk/2 − 0,10`, à `Z = Hp + Hg − batten_drop`.
  Première à `Yc + 0,50`, puis tous les `batten_spacing`, dernière à 0,30 au
  moins du fond. Une porteuse à moins de 0,30 en Y d'une porteuse de
  pendrillonnage ou du plan du rideau de scène est retirée (section 8). Les
  restantes sont numérotées de la face vers le fond, sans trou. Les
  projecteurs s'y accrochent selon la section 13, par position en Y.
- **Porteuse de la dernière rue** : la dernière rue va du dernier plan de
  pendrillonnage à la ligne de fond `Yb` (8.1). Si aucune porteuse restante
  n'y est (`plan_N < Y < Yb`), on en ajoute une au **milieu de l'intervalle
  libre** de la rue, `[plan_N + 0,30 ; Yb − 0,30]` *(choix : 0,30, comme le
  retrait ci-dessus)*, donc à 0,30 m au moins de toute porteuse de
  pendrillonnage. C'est une porteuse lumière ordinaire, numérotée par Y avec
  les autres (par défaut Y = 6,21, `Batten_03`). Rue trop étroite (intervalle
  vide) : pas de porteuse et l'alerte « Dernière rue trop étroite pour une
  porteuse lumière : aucune porteuse au fond de scène ». Avec la porteuse
  de la dernière rue, le contre (13.4) a une perche de fond.

### 5.6 Escaliers latéraux (`TS_Stairs`)

Pour le côté `s` (−1 jardin, +1 cour), `Ws` la largeur, `θ` l'angle, `o` le
décalage latéral :

- Ligne d'appui `Yback` : la façade (`Ys`) si `o ≥ 0`, le bandeau (`0`) si
  `o < 0` (escalier devant le plateau). Sans recul de façade les deux
  coïncident.
- `Stairs_Landing_L/R` : **palier en biais**, à hauteur du plateau (Z de 0
  à `Hp`), choisi par l'utilisateur sur fiche avec schéma (2026-11-19). Le
  palier est un trapèze rectangle qui comble l'espace entre le plateau et
  la volée tournée :
  - côté appui : un bord posé sur la **ligne d'appui** — la ligne arrière
    (`Y = Yback`) pour `|θ| ≤ 45°`, le flanc (`x = s·(W/2 + o)`) pour
    `|θ| > 45°` ; ce bord part du coin `(s·(W/2 + o), Yback)` et s'en
    éloigne (vers l'extérieur sur la ligne arrière, vers la salle sur le
    flanc) ;
  - côté volée : le bord de départ de la volée, perpendiculaire à `d`, de
    largeur `Ws` ;
  - les deux autres côtés sont perpendiculaires à la ligne d'appui
    (projection orthogonale du bord de départ sur la ligne d'appui) ;
  - `landing_depth` (`Ld`) est le plus petit écart entre la ligne d'appui et
    le bord de départ (le petit côté du trapèze).
  À 0° et à 90°, le trapèze redevient le rectangle d'avant (`Ws × Ld`) ; avec
  `Ld = Ws`, le carré d'origine. Le palier se construit comme un polygone
  extrudé (`Prism`), sans chevauchement avec la volée ni avec le plateau.
- **`Ld = 0` : pas de palier.** La volée part directement de la ligne
  d'appui (`|θ| ≤ 45°`) ou du bord `x = s·(W/2 + o)` (`|θ| > 45°`). Devant la
  scène à 0°, la première contremarche est le bandeau et le plateau sert de
  dernière marche : l'escalier arrive droit sur le nez, sans promontoire.
- Arrivée : un bord du palier (n'importe lequel : le palier par défaut
  touche le plateau par son flanc, pas par son bord arrière), ou le haut de
  la volée sans palier, doit toucher le plateau sur au moins 0,60 m (nez de
  scène, ou flanc de l'avant-plateau entre `0` et `Ys`).
  Sinon alerte : « L'escalier X n'arrive pas sur le plateau : ajouter un
  palier ou le décaler devant la scène. »
- Volée : un bloc droit qui commence au bord de départ et descend selon `d`,
  dans le prolongement exact du palier, sans vide ni chevauchement.
- `Ld = 0` à un angle intermédiaire : le trapèze devient un triangle (le
  coin du bord de départ touche la ligne d'appui) ; un palier d'aire nulle
  (0° ou 90°) n'est pas créé.
- Direction de descente `d = (s·sin θ, −cos θ)` : 0° vers la salle, 90° vers
  le mur latéral, −90° vers le centre (le long du bandeau quand le palier y
  est adossé).
- Dégagement : un rectangle libre de profondeur `clearance` et de largeur
  `Ws`, au-delà de la dernière marche, dans l'axe de la volée. **Aucun
  escalier ne finit dans un mur** : le dégagement compte dans l'emprise.
  Il n'est pas dessiné ; sa position est vérifiée par les tests.
- Marche `j` (1 à `n − 1`, de la plus haute à la plus basse) `Stairs_Step_L_NN` :
  boîte pleine depuis le sol, dessus à `(n − j)·Hp/n`, occupant le long de
  `d` l'intervalle `[Ws/2 + (j−1)·going, Ws/2 + j·going]` compté depuis le
  centre du palier, et `[−Ws/2, Ws/2]` en travers. Aux angles
  intermédiaires, la première marche chevauche le palier : c'est voulu, pas
  de vide.
- Emprise latérale requise, depuis le bord du plateau : le plus grand
  `|x| − W/2` atteint par le palier, les marches et le dégagement (`Ws` à
  0°, `Ws + L + clearance` à 90°, avec `o = 0`).
- Alertes : volées jardin et cour qui se croisent ou qui touchent
  l'escalier central ; dégagement qui sort de la salle dessinée.

### 5.7 Escalier central (`TS_Stairs`)

`Stairs_Step_C_NN` : X sur `[−cw/2, cw/2]`, marche `j` sur Y
`[−j·going, −(j−1)·going]`, dessus à `(n − j)·Hp/n`. Il avance sur
l'avant-scène.

### 5.8 Modules (`TS_Module`)

Un module est un **caisson** : une face avant percée, plus un retour côté
plateau qui file vers le fond. Il est ouvert côté coulisses et n'a pas de
dessus.

- Charnière (arête extérieure, côté salle) :
  `H = (s·(Wc/2 − frame_gap), setback, Hp)`. La référence est le bord du
  cadre, pas le mur de cage : ouvrir les coulisses ne déplace pas les
  modules. À 90°, le retour part dans les coulisses ; il ne sort de la cage
  que si `depth` dépasse la largeur des coulisses (alerte).
- Repère local, `u` le long de la face vers le plateau, `v` vers l'arrière
  de la face :
  jardin `u = (cos θ, sin θ)`, `v = (−sin θ, cos θ)` ;
  cour `u = (−cos θ, sin θ)`, `v = (sin θ, cos θ)`.
  À 0°, la face est parallèle au nez et regarde la salle. À 90°, elle
  devient un mur latéral qui regarde le plateau.
- `Module_L_Front` : rectangle `[0, width] × [0, height]` dans (u, z),
  extrudé de 0,10 selon `v`, percé des baies.
- `Module_L_Return` : `u` sur `[width − 0,10, width]`, `v` sur `[0, depth]`,
  même hauteur.
- Baies : porte de Z 0 à `door_height` ; fenêtre de `window_sill` à
  `window_sill + window_height`. Centre en `u = width/2 + offset`. Une baie
  qui sort de la face (marge de 0,05, retour exclu) est **rognée** et
  signalée. Porte et fenêtre peuvent se chevaucher.
- La face est découpée en **cellules rectangulaires pleines** en (u, z),
  calculées dans `core` : on coupe la face selon toutes les arêtes de baies
  et on garde les cellules hors baie. Le maillage construit est étanche
  (pas de faces internes), les tableaux de baies sont fermés et le trou est
  traversant : la lumière passe.

### 5.9 Lumières de travail

- `WorkLight_NN` : lumières surfaciques carrées tournées vers le bas, à
  `Z = Hp + Hg − 0,30`. Grille sur le plateau de cage, coulisses comprises
  (`Wk × (D − Yc)`) : `nx = max(1, round(Wk / spacing))`,
  `ny = max(1, round((D − Yc) / spacing))`, une lumière au centre de chaque
  cellule, côté = moitié de la plus petite dimension de cellule. Blanc neutre
  4000 K. Puissance proportionnelle à l'aire de la cellule × `intensity`,
  calibrée pour un plateau lisible sans brûlure (réglée sur capture).
- `WorkLight_Front` : face depuis la salle, axée, à `Y = −A − 2,00`,
  `Z = Hp + Hc`, visant `(0, Yc + (D − Yc)/3, Hp + 1,00)`.
- Position et cible sont calculées dans `core` ; `build.py` en déduit la
  rotation.

### 5.10 Caméras

`Cam_Face` à `(0, −distance, height)`, `Cam_Jardin` et `Cam_Cour` à
`X = ∓0,75·W/2`, même Y et Z. Toutes visent `(0, D/2, Hp + 1,00)`, focale
`lens`. `Cam_Face` devient la caméra de scène si la scène n'en a pas ou si la
caméra active est une caméra générée.

## 6. Matériaux

Un matériau par catégorie, nommé en anglais et préfixé `TS_`. Il est créé
(Principled BSDF, couleur unie) **seulement s'il n'existe pas**, puis
réutilisé par son nom. Un shader BlenderKit posé sur `TS_StageFloor` survit
donc à la régénération.

| Matériau | Usage | Teinte |
|---|---|---|
| `TS_Enclosure` | façade, murs de salle, bandeau | rouge bordeaux |
| `TS_Proscenium` | cadre | noir mat |
| `TS_Cage` | murs, fond nu, toit de cage | noir |
| `TS_StageBase` | structure du plateau | noir |
| `TS_StageFloor` | plancher | bois clair |
| `TS_Nosing` | liseré du nez | noir |
| `TS_HouseFloor` | sol de salle | gris |
| `TS_Stairs` | escaliers, paliers | gris foncé |
| `TS_Module` | modules | noir chaud |
| `TS_Grid` / `TS_Batten` | gril, porteuses, perche de face, bras de pylône | métal sombre |
| `TS_Masking` | pendrillons, frises, rideau de fond | velours noir |
| `TS_MainCurtain` | rideau de scène | velours rouge |
| `TS_Cyclorama` | cyclorama | blanc mat |
| `TS_HouseCeiling` | plafond de salle, une face (section 5.1) | gris sombre |
| `TS_Fixture` | corps, étrier, embase des appareils (section 14) | noir mat |
| `TS_Lens` | verre des lentilles | gris verre, sombre |
| `TS_Truss` | pylônes et platines | métal gris |
| `TS_Blade` | lames de cadrage, invisibles pour la caméra (14.4) | noir |

Tous les maillages reçoivent des UV en projection boîte, **1 unité UV =
1 m**, sans étirement. Les matériaux BlenderKit procéduraux n'ont pas
d'échelle réelle : « Wood Floor », par exemple, donne des lames minuscules à
son échelle d'origine et se règle par son entrée `Global Scale` (0,125 sur
le plateau par défaut). On ne normalise pas les UV par objet : ce serait
étirer le plancher et désaccorder les objets entre eux.

### 6.1 Matériaux posés par l'utilisateur

La **catégorie** d'un objet généré est son matériau `TS_*` par défaut.

- Poser un matériau sur un objet généré (glisser-déposer BlenderKit,
  sélecteur de Blender) le fait **retenir pour toute la catégorie** :
  stocké sur la scène (catégorie → matériau, donc enregistré dans le
  .blend, pas dans les préréglages YAML), réappliqué à chaque
  reconstruction à tous les objets de la catégorie, y compris ceux qui
  apparaissent ensuite (une rue de plus, etc.).
- Détection : un objet généré dont le matériau n'est ni le `TS_*` par
  défaut ni le matériau retenu pour sa catégorie porte un nouveau choix.
  Elle a lieu au début de chaque reconstruction et **après chaque
  changement de matériau d'un emplacement** (abonnement `bpy.msgbus` à
  `MaterialSlot.material`, réabonné au chargement de fichier). L'abonnement
  ne fait que programmer une détection différée (timer à un coup, une seule
  en attente), qui propage le choix aux autres objets de la catégorie
  **sans reconstruire**. Deux choix différents dans la même catégorie : le
  premier objet par ordre de nom l'emporte, et une alerte le signale.
- **Pas de scrutation continue.** Le timer d'une seconde a été retiré après
  un plantage dans sa lecture des emplacements (2026-11-20, après deux
  ajouts BlenderKit sur `Backdrop`, `EXCEPTION_ACCESS_VIOLATION` dans
  `materials._slot_material`), non reproduit hors session interactive. Le
  code ne relit les objets qu'après un changement réel.
- La détection ne parcourt que les objets marqués `theatre_generated` de la
  collection `Theatre`, ne modifie que des emplacements de matériau et ne
  tourne pas pendant une reconstruction.
- Sous-panneau « Matériaux » : une ligne par catégorie (libellé français,
  sélecteur de matériau, bouton pour revenir au `TS_*` par défaut).
- Le `TS_*` par défaut n'est jamais modifié ni supprimé.

## 7. Régénération et panneau

- Collection racine `Theatre`, sous-collections `Theatre_Architecture`,
  `Theatre_Stairs`, `Theatre_Modules`, `Theatre_Grid`, `Theatre_Masking`,
  `Theatre_Curtains`, `Theatre_Lights`, `Theatre_Cameras`, `Theatre_Rig`
  (perches de face, pylônes, bras), `Theatre_Fixtures` (hiérarchies d'appareils,
  section 14).
- Chaque objet généré porte la propriété personnalisée `theatre_generated`.
  La reconstruction supprime **uniquement** ces objets et leurs données
  orphelines, puis recrée tout. Un objet non marqué trouvé dans ces
  collections est laissé en place et signalé.
- Un changement de paramètre ne reconstruit pas dans le callback `update` :
  il programme une reconstruction différée (`bpy.app.timers`, une seule en
  attente). Un curseur qu'on fait glisser ne donne donc qu'une
  reconstruction par passage du timer. Les opérateurs (Reconstruire, Charger
  un préréglage) reconstruisent directement. Un verrou empêche les
  reconstructions en cascade pendant l'application d'un préréglage ou de la
  symétrie.
- Le dessin du panneau ne parcourt **aucune** collection de données Blender
  (`all_objects`, `objects`…) : il lit des valeurs Python calculées à la
  reconstruction (Layout, noms des objets étrangers). Le plantage du
  2026-11-19 (`EXCEPTION_ACCESS_VIOLATION` dans
  `pyrna_prop_collection_iter_next`, depuis le dessin des alertes qui
  parcourait `all_objects`) a eu lieu en glissant le curseur du giron.
- Les items d'un EnumProperty dynamique restent référencés côté Python.
- Panneau « Théâtre » dans la barre latérale de la vue 3D : Plateau,
  Avancé (replié), Escaliers, Modules, Gril, Pendrillonnage, Rideaux,
  Lumières, Caméras, Implantation, Perche de face, Contre, Mobiles de face,
  Pylônes, PC de face, Découpes, Repos, Patch DMX, Préréglages, et un encadré
  **Cotes calculées** (largeur hors tout, largeur de cage, contremarches,
  nombre de porteuses, puis les cotes de la section 13.10) suivi des alertes.
  Boutons de l'implantation : « Plein feu de repos » (15.2), « Exporter QLC+ »
  (16), « Recharger la bibliothèque » (12.1).
- Les énumérations `fixture` et `mode` sont dynamiques (items référencés côté
  Python, section 3.12) ; le dessin du panneau ne relit pas le disque : la
  bibliothèque est lue au chargement et au bouton. Le schéma les déclare avec
  les types `fixture` (familles acceptées) et `mode` (clé `fixture` de
  référence). La valeur stockée est un **texte** : la PropertyGroup porte une
  chaîne et une énumération d'affichage `<clé>_pick` ; un `id` absent de la
  bibliothèque reste affiché « <id> (introuvable) » au lieu de faire échouer
  l'écriture, et une bibliothèque vide laisse le panneau intact.
- Une reconstruction qui change l'implantation recrée les appareils, leurs
  drivers et les propriétés de scène absentes (15.2) ; elle ne touche à
  aucune propriété `dmx_<u>_<c>` existante.

## 8. Pendrillonnage et rideaux

Pendrillons, frises, rideau de fond et rideau de scène sont des **draperies
de velours** ; le cyclorama reste une toile tendue plate. Le modèle doit
avoir l'allure d'un textile qui pend, pas d'une tôle ondulée :

- plis irréguliers autour d'un pli tous les 0,30 m d'amplitude 0,06 (sauf
  mention contraire) : largeur de chaque pli ±25 %, profondeur ±30 %. Le
  tirage est **déterministe**, semé par le nom de l'objet : même forme à
  chaque reconstruction, jardin et cour différents ;
- tête : sur les 0,10 m du haut, plis réguliers et serrés (fronces sous la
  porteuse) ;
- chute : sous la tête, les plis s'ouvrent vers le bas (profondeur ×1,3 au
  sol) et chaque pli dérive latéralement de quelques centimètres ;
- bas : le tissu touche le plancher et s'évase sur les 0,05 m du bas ;
- crêtes arrondies (pas une sinusoïde pure), 8 points par pli au moins, une
  rangée tous les 0,25 m au plus ;
- dans Blender : lissage, subdivision (1 en vue, 2 au rendu) et épaisseur de
  3 mm, par modificateurs.

`masking.drape` dose l'irrégularité ; 0 redonne des plis réguliers. Pas de
simulation de tissu : elle n'est ni déterministe ni assez rapide pour une
reconstruction à chaque réglage. Tous pendent sous une
porteuse de pendrillonnage, de `Z = Hp` à la hauteur des porteuses
`Zb = Hp + Hg − batten_drop`.

### 8.1 Plans en profondeur

- Rideau de scène : plan `Yr = Yc + 0,15`.
- Frise de face : plan `Yf`, assez loin pour que rideau et frise ne se
  touchent jamais : `Yf = Yr` + plus grand écart en Y des plis du rideau
  (deux états, drapé maximal) + plus grand écart en Y des plis de la frise
  + 0,10 + le décalage de 0,10 de la frise (8.4). La v3 montrait des plis du
  rideau qui traversaient la frise.
- Début de zone : `Y0 = Yf + 0,20`. Si au moins un module est présent,
  `Y0 = max(Y0, Ymod + 0,20)`, avec `Ymod` le Y maximal de l'emprise des
  modules présents : **les rues reculent derrière les modules**.
- Ligne de fond `Yb` : mur nu → `D` ; rideau noir → `D − 0,40` ;
  cyclorama → `D − 1,20`.
- Fin des pendrillons à l'allemande : `Y1 = Yb − 0,30`.
- Plans de pendrillonnage `k = 1..N` (`N = lanes`) à
  `Y0 + (k − 1)·Δ`, avec `Δ = (Yb − Y0)/N`. **Le premier plan ferme la face
  de la première rue**, juste derrière le cadre ou les modules ; la rue `k`
  va du plan `k` au plan `k + 1`, la dernière du plan `N` au fond. Aucun
  plan n'est collé au fond.

### 8.2 Porteuses de pendrillonnage (`TS_Batten`)

Distinctes des porteuses lumière, elles pourront porter des projecteurs
plus tard (en perroquet, voir `BACKLOG.md`). Mêmes tube et longueur que les
porteuses lumière, à `Z = Zb`.

- `MaskingBatten_NN` au plan `k` (`NN = k`) ;
- `MaskingBatten_00` pour la frise de face, si elle est présente ;
- `MaskingBatten_Back` pour le rideau noir ou le cyclorama ;
- à l'allemande, en plus, `MaskingBatten_Side_L/R`, parallèles à Y au-dessus
  des pendrillons latéraux, de `Y0` à `Y1`.

### 8.3 Pendrillons (`TS_Masking`)

- **À l'italienne** : `Leg_L_NN` / `Leg_R_NN` au plan `k`, du bord
  intérieur jusqu'au mur de cage `∓Wk/2` : **chaque pendrillon touche son
  mur**, sans jamais le traverser (dérive des plis comprise). Pas de réglage
  de largeur. Ouverture ≥ `Wk` → aucun pendrillon et alerte.
  - Bord intérieur (pivot) : `I_k = (s·a_k, Y_k)` avec
    `a_k = opening/2 + (Y_k − Y_1)·tan(convergence)` : le premier plan garde
    l'ouverture nominale, les suivants s'écartent vers le lointain.
  - Direction vers le mur : `(s·cos α, −sin α)` avec `α = leg_angle` : le bord
    extérieur avance vers le public. Longueur `(Wk/2 − a_k)/cos α`.
  - Incliné (`α > 0`), un pendrillon ne pend plus sous la porteuse droite de
    son plan : il reçoit sa propre perche `LegPipe_L_NN` / `_R_NN` (tube de
    porteuse, `TS_Batten`, à `Zb`, le long de son bord haut). La porteuse
    `MaskingBatten_NN` reste droite et porte la frise.
  - Collision : le bord extérieur d'un pendrillon incliné ne doit croiser ni
    un module, ni le plan de la frise de face, ni le plan du rideau de
    scène. Sinon alerte « Pendrillon … : trop incliné pour la rue ». Deux
    pendrillons inclinés successifs ne se croisent jamais (droites
    parallèles, bords intérieurs qui s'écartent).
  - Inclinaison et convergence ne s'appliquent pas à l'allemande.
- **À l'allemande** : `Leg_L` / `Leg_R` continus, parallèles à Y, à
  `X = ∓opening/2`, de `Y0` à `Y1`. Pas de rues ; `lanes` ne fixe plus que
  les plans des frises.

### 8.4 Frises et fond

- `Border_NN` au plan `k` si `borders[k]` est coché, `Border_00` (frise de
  face) si `front_border` : **de mur à mur** (`Wk`, plis compris, sans
  traverser les murs), du bas de frise à `Zb`, posée 0,10 côté salle du plan
  pour couvrir le haut des pendrillons. Les frises restent parallèles au
  cadre. Bas de frise : `Hp + border_bottom` en mode manuel, calculé par la
  découverte sinon (8.7). Bas de frise ≥ `Zb` : aucune frise et alerte.
- Fond : rideau noir `Backdrop` (`TS_Masking`, plissé, plan `Yb`, de mur à
  mur) ; mur nu : rien, `Cage_Back` est visible ; cyclorama
  `Cyclorama` (`TS_Cyclorama`, plat, plan `Yb`, largeur `Wc − 0,60`).

### 8.5 Rideau de scène à la grecque (`TS_MainCurtain`)

- `MainCurtain_L` / `MainCurtain_R` dans le plan `Y = Yc + 0,15`, de `Z = Hp`
  à `Hp + Hc + 0,30` (le haut se cache derrière le linteau).
- Fermé : chaque lé va du centre (chevauchement de 0,15 au-delà de l'axe)
  jusqu'à `±(W/2 − 0,05)`, son bord extérieur caché derrière le montant du
  cadre.
- Ouvert : chaque lé est ramassé **entièrement derrière son montant**, de
  `Wc/2 + 0,25` à `W/2 − 0,05` en valeur absolue, plis d'amplitude 0,20
  *(choix)*. La marge de 0,25 côté ouverture vient d'un rendu : coulisses
  ouvertes, avec 0,05 le paquet se voyait depuis `Cam_Face` derrière le
  montant. Une caméra bien plus proche du cadre peut encore l'apercevoir. Le rideau ouvert ne mord jamais sur l'ouverture `[−Wc/2, Wc/2]`
  (les plis partent en Y, seule l'étendue en X compte). Si le montant est
  trop étroit (`Tc − 0,30 < 0,30`), le paquet garde 0,30 de large, déborde
  dans l'ouverture et une alerte le signale. Même nombre de plis dans les
  deux états.
- Le maillage a pour forme de base l'état fermé et une clé de forme `Open`
  pour l'état ouvert. Un **driver** règle la valeur de `Open` à
  `main_opening / 100`, lu sur la propriété de scène. Des images clés posées
  sur `main_opening` animent donc le rideau à la lecture, sans
  reconstruction. La reconstruction recrée le driver ; les images clés,
  portées par la scène, survivent.
- `core` fournit les deux états (positions de plis, largeurs, amplitudes) ;
  `build.py` construit le maillage, la clé de forme et le driver.

### 8.6 Atmosphère (brume) — `haze`

Pour voir les faisceaux, sans alourdir le rendu.

| Clé | Libellé | Défaut | Bornes |
|---|---|---|---|
| `enabled` | Atmosphère (brume) | non | |
| `extent` | Étendue | plateau et salle | plateau et salle / plateau |
| `falloff` | Fondu vers la salle (étendue « plateau ») *(choix)* | 2,00 | 0,10 – 10 |
| `density` | Densité — **animable** *(choix)* | 0,02 | 0 – 1 |
| `anisotropy` | Diffusion vers l'avant *(choix)* | 0,6 | −0,9 – 0,9 |
| `quality` | Qualité | légère | légère / moyenne / fine |
| `dmx_driven` | Densité pilotée par le hazer (DMX) | non | |
| `fixture` | Appareil hazer | `generic_hazer` | énumération dynamique |
| `mode` | Mode DMX du hazer | mode par défaut de la fiche | énumération dynamique |

- `dmx_driven`, `fixture` et `mode` : la densité suit alors le canal du hazer
  (section 15.4).
- **Aucune limite de brume ne doit se voir.** Une boîte homogène montre une
  paroi nette partout où une face tombe dans le vide (retour utilisateur :
  la brume « s'arrêtait pile sur le devant de la scène »). Règle : chaque
  face de la boîte est sur un mur, un sol, un plancher ou un plafond, ou
  derrière ; la seule frontière ouverte autorisée est le fondu ci-dessous.
- `Haze_Volume` (`TS_Haze`) : **une seule boîte**, pas un volume de World.
  Étendue « plateau et salle » (défaut) : toute l'enceinte, de `−Yh` au fond
  `D`, entre les murs (salle et cage), du sol de salle au plus haut du
  plafond de salle et du gril ; le plateau et ses volumes sont dedans. La
  brume reste homogène.
- Étendue « plateau » : même largeur et même hauteur que la boîte « plateau
  et salle » (une boîte limitée à la cage aurait ses côtés, son dessus et
  son dessous en plein vide dans la zone de fondu), de `D` jusqu'à
  `Ys − falloff` côté salle. La densité décroît linéairement de la façade
  (`Y = Ys`, pleine densité) à `Ys − falloff` (zéro), par un dégradé en
  coordonnées objet. Ce volume n'est plus homogène : Cycles le parcourt pas
  à pas. Surcoût mesuré et noté ci-dessous.
- `TS_Haze` : Volume Scatter **homogène** en étendue « plateau et salle »
  (pas de texture de bruit), pas de surface. Densité et
  anisotropie viennent de la scène par **drivers**, comme l'ouverture du
  rideau : `density` et `anisotropy` ne reconstruisent pas et `density`
  s'anime (montée de brume).
- `quality` règle EEVEE quand la brume est active : taille de tuile
  volumétrique, nombre d'échantillons volumétriques, début et fin du volume
  calés sur l'emprise de la boîte vue depuis `Cam_Face`. Légère = la moins
  chère qui montre encore un faisceau net. Brume inactive : on ne touche
  pas aux réglages de rendu de la scène.
- Coût mesuré (EEVEE de Blender 5.3, 1280×720 depuis `Cam_Face`, médiane de
  5 rendus, lumières de travail allumées, un projecteur de test en faisceau
  de 30°) : sans brume 2577 ms ; « plateau et salle » légère (tuile 8,
  32 échantillons) 2901 ms ; « plateau » avec fondu : légère 2957 ms, moyenne
  (tuile 4, 64) 2840 ms, fine (tuile 2, 128) 2819 ms, soit +10 % à +15 %
  (écarts entre qualités dans le bruit de mesure). Taille de tuile,
  échantillons et plage début/fin ne changent pas l'image, même avec le
  dégradé (écart maximal 0,004 entre légère et fine) : on garde « légère ».
  La densité s'anime : le driver suit des images clés sur `haze.density`.

### 8.7 Découverte depuis le fauteuil de référence

Calculée dans `core`, testée, sans rien dessiner dans la scène.

- **Œil de coupe** `E = (Y = −seat_distance, Z = eye_height)` (sol de salle
  à 0). **Fauteuils de plan** `S_jardin = (−(Wt/2 − seat_wall_gap),
  −seat_distance)` et `S_cour` en miroir ; les coulisses cour se contrôlent
  depuis `S_jardin`, et inversement.
- **En coupe, à cacher** : le dessous du gril (`Z = Hp + Hg`) et toutes les
  porteuses (lumière et pendrillonnage, à `Zb`), de `Yc` jusqu'au fond
  (`Yb`). **Écrans** : le bas du linteau (`Hp + Hc`, plan du cadre), puis le
  bas de chaque frise présente, de la face vers le lointain. Un point `P`
  est caché si le segment `E → P` passe au-dessus du bas d'un écran situé
  devant lui (hauteur de la ligne au plan de l'écran ≥ bas de l'écran).
- **Frises calées sur la découverte** (mode par défaut) : de la face vers le
  lointain, chaque frise présente prend le bas **le plus haut** qui cache
  encore tout ce qui se trouve entre son plan et l'écran suivant (ou le
  fond) : `Z_k = min` sur ces points `P` de
  `E_z + (P_z − E_z)·(Y_k − E_y)/(P_y − E_y)`. Une frise décochée reporte
  sa zone sur la précédente. Valeurs affichées dans « Cotes calculées ».
  Bas calculé sous `Hp + 2,20` *(choix : passage d'un comédien et d'un
  décor)* → alerte « Frise … très basse ». La frise de face et le linteau
  participent ; le linteau est fixe.
- **Mode manuel** : mêmes calculs, mais en contrôle seulement ; alerte
  « Découverte verticale : porteuse … visible depuis le premier rang ».
- **En plan** : pour chaque rue `k` et chaque côté, la ligne qui part du
  fauteuil opposé et rase le bord intérieur de l'écran de devant (bord du
  cadre, module ou pendrillon `k`) donne la profondeur de coulisse visible
  au plan suivant. Elle est affichée dans « Cotes calculées » ; si la ligne
  atteint le mur de cage avant le plan suivant, alerte « Découverte en
  coulisse … rue k : le mur de cage se voit ». Avec des pendrillons qui
  vont jusqu'au mur, rien d'autre ne peut se voir au-delà.
- Tests : géométrie de référence calculée à la main (un plan, une porteuse),
  frise décochée, mode manuel qui alerte quand on remonte une frise, plan :
  profondeur visible qui croît avec la convergence.

## 9. Préréglages YAML

- Même arborescence que les groupes de paramètres, plus `version: 1`.
  `modules` contient `symmetric`, `left` et `right`.
- Livrés dans `presets/` : `reference_with_modules.yaml` (valeurs par défaut)
  et `open_space.yaml` (sans modules). Les deux portent l'implantation
  lumière avec ses valeurs par défaut : 6 MAC Aura en contre, 4 Esprite de
  face, 1 pylône de 2 Esprite par côté, zones de 3,00 m, visée à 1,70 m,
  3 découpes.
- Les groupes des sections 13 à 16 (`rig`, `rig_front`, `backlight`,
  `front_movers`, `towers`, `front_pc`, `profiles`, `rest`, `patch`) et les
  clés ajoutées à `haze` s'écrivent comme les autres, `towers` avec
  `symmetric`, `left` et `right` comme `modules`. `version` reste à 1 : les
  clés sont additives, un préréglage plus ancien prend les défauts. Le patch
  fait partie du préréglage ; les valeurs DMX en direct n'en font pas partie.
- Une énumération de fiche (`fixture`, `mode`) dont l'`id` est absent de la
  bibliothèque revient au défaut du paramètre, avec un avertissement.
- Préréglages utilisateur enregistrés dans
  `bpy.utils.extension_path_user(__package__, path="presets", create=True)`,
  jamais dans le dossier de l'extension.
- Chargement : clé absente → défaut ; clé inconnue → ignorée et signalée ;
  valeur hors bornes → ramenée dans les bornes et signalée.
- PyYAML n'est pas fourni avec Blender 5.3 : il est embarqué en wheel
  (`wheels = [...]` du manifeste, cp313 win_amd64). Si l'installation par
  jonction ne synchronise pas la wheel, repli sur une copie pure Python de
  PyYAML dans `vendor/`, importée en relatif.

## 10. Alertes

Calculées dans `core`, rédigées en français, affichées dans le panneau :

- cadre trop haut : `Hp + Hc + lintel_height > facade_height` ou
  `Hc + lintel_height > Hg` ;
- escalier latéral ou central qui dépasse de l'avant-scène ;
- baie rognée ;
- module qui sort de la cage ;
- zone latérale élargie automatiquement (avec la largeur obtenue) ;
- profondeur de cage insuffisante pour une porteuse ;
- rues de moins de 0,60 m ;
- ouverture du pendrillonnage plus large que la cage ;
- frises sans hauteur utile ;
- rideau de scène ouvert visible dans l'ouverture (montants trop étroits) ;
- bibliothèque : fiche invalide ou introuvable (12.7) ;
- implantation : zone de jeu raccourcie (13.1) ; perche de face hors de la
  salle (13.2) ; point d'accroche hors du tube (13.3) ; porteuse à plus de
  0,50 m de la distance demandée pour le contre (mode `distance`), ou aucune
  porteuse (13.4) ; dernière rue trop étroite pour une porteuse (5.5) ;
  pylône trop bas, sur un escalier ou hors de la salle (13.6) ; rang de PC
  dont la porteuse est trop en arrière (13.7) ; appareils qui se touchent sur
  un tube (13.10) ; seconde perche hors de la salle, ou sans hauteur qui
  dégage les faisceaux (13.2 bis) ; faisceau gêné par un appareil, débattement
  de pan et tilt qui touche un appareil d'un autre support (13.11) ;
- photométrie : zone non couverte ou champ trop large, hors de la plage de
  zoom (13.7) ; découpe sans tube assez large, lame hors course ou lames non
  adaptées (13.8) ; pan/tilt hors course (13.9) ; température de couleur de
  repos hors de la plage de la fiche (15.2) ;
- patch : recouvrement d'adresses, univers au-delà de 512 canaux (15.1) ;
- brume : `DMX_Haze` de DMX Visualizer actif dans le monde (15.4).

## 11. Vérification

- `python -m pytest` : règles de la section 4, escaliers (6 contremarches de
  0,20 à 1,20 ; 7 à 1,25), largeur hors tout (14,00 à 0°, 17,00 à 90°),
  symétrie de l'enceinte avec un seul escalier, modules à 0° et 90°, miroir
  gauche-droite, cellules de baies (aucune cellule dans une baie, cellules +
  baies = face), porteuses et grille de lumières, aller-retour YAML ; plans
  de pendrillonnage avec et sans modules, retrait des porteuses lumière trop
  proches, frises cochées une à une, les trois fonds, deux états du rideau
  de scène avec le même nombre de plis.
- Dans Blender, en plus : images clés sur `main_opening`, lecture de la
  timeline, le rideau suit.
- Dans Blender : capture depuis `Cam_Face` avec le préréglage
  `reference_with_modules`, à comparer avec `scene-vue-artiste.png` ; puis
  `open_space`, à comparer avec `scene-vue-artiste-ouvert.png`.
- Tests `pytest` des sections 12 à 16 (aucun ne dépend de Blender, de QLC+
  ou d'un GDTF du disque ; le test qui lit `C:\QLC+` est ignoré s'il est
  absent) :
  - fiches : chargement et rejet des clés manquantes, attribut inconnu
    conservé, canaux 16 bits (`encode` puis `decode` rend `v` à 1/65535 près,
    `v = 1` donne `255, 255`), empreinte et offsets, les six fiches livrées
    valides, outil GDTF sur un petit GDTF construit dans le test (offsets
    multiples → 16 bits, attributs inconnus gardés) ;
  - implantation : `Yp = −1,40` avec les défauts ; 16 PC et 4 circuits, aucune alerte avec
    les trois préréglages livrés ; `Y2 = −2,90`, `Z2 = 6,75`, mobiles sur
    `FrontPipe_02` ; hauteur automatique : la plus haute qui dégage, et
    `Zp` quand rien ne gêne ; rayon de l'enveloppe contre les sommets des
    modèles ; faisceau gêné par un obstacle, débattement qui touche ; azimut par rang ; coupe haute (comédien ou linteau) ;
    décalage en X `ΔY·tan(azimut)` et faisceaux parallèles en plan par
    direction ; champ requis, bornage au zoom et alerte ; accroche par Y
    (première porteuse, retrait d'une porteuse qui renumérote, contre à plus de
    0,50 m) ; pylônes miroirs et empilement ; zones à 1, 2 et 4 rangs ;
  - visée : pour chaque mobile, le faisceau recalculé depuis les octets
    16 bits arrondis passe à moins de 1 cm de la visée ; seconde solution
    pan/tilt ; hors course ;
  - découpes : un point de chaque droite de coupe appartient au plan de sa
    lame ; tube choisi sur un cas calculé à la main ; `blades_mode = manual`
    restitue les valeurs saisies ;
  - patch : adresses consécutives, recouvrement, 512 canaux ; valeurs de
    repos ; `cct_to_rgb` plus rouge que bleu sous 6500 K ;
  - export : `.qxw` et `.qxf` bien formés, adresses à base 0, contrôle MAC
    Aura contre le `.qxf` de QLC+ (ignoré si absent).
- Dans Blender, en plus, depuis `Cam_Face` et **en Cycles** (rendu vers un
  fichier, jamais `evaluated_get`) : reconstruction sans erreur et sans
  objet manquant (30 appareils par défaut) ; propriétés `dmx_<u>_<c>` écrites
  puis `scene.update_tag()` : les drivers de dimmer, couleur, pan, tilt et
  zoom suivent ; « Plein feu de repos » ; chaque découpe cadre son tiers,
  coupe nette au nez et sous le linteau ; les faisceaux d'une même direction
  sont parallèles en plan ; la lumière sort par le bord de la lentille d'un
  profil, sans ombre du corps ; un gobo et l'iris d'un Esprite se projettent ;
  sens de `Normal` des lumières en Cycles (14.5) ; brume pilotée par le hazer ;
  étalonnage lumen / watt (14.8) consigné dans `docs/`.

## 12. Bibliothèque d'appareils

Cadre commun à tous les appareils de la section 13 : une **fiche** YAML par
modèle, lue par `core/fixtures.py`. `core` ne lit jamais un GDTF. Le moteur de
référence est **Cycles** ; EEVEE ignore les profils IES et les arbres de nœuds
de lumière (section 14.5), il ne rend donc que l'intensité et la couleur RVB.

### 12.1 Disposition des dossiers

```
blender/theatre_stage/library/fixtures/<id>/     livré avec l'extension
  fixture.yaml
  source/                  GDTF d'origine, fiches techniques (PDF), profils IES
  meshes/                  maillages (.glb ou .obj) importés par nom
  gobos/                   images de gobos (.png)
<extension_path_user(__package__, path="fixtures", create=True)>/<id>/
                           fiches de l'utilisateur, même disposition
```

- **Tout est versionné** : fiches, GDTF, IES, maillages, images de gobos. Les
  chemins de la fiche sont relatifs à son dossier.
- Une fiche utilisateur de même `id` qu'une fiche livrée la remplace
  (information dans les alertes). Le nom du dossier est l'`id`.
- La bibliothèque est lue au chargement de l'extension et par le bouton
  « Recharger la bibliothèque ». Une fiche invalide est écartée avec un message
  français qui liste les clés fautives ; elle n'apparaît dans aucune
  énumération.

### 12.2 Schéma d'une fiche

Unités : mètre, degré, kilogramme, lumen, kelvin. « Obl. » : obligatoire
(`non` = facultatif ; `si …` = obligatoire sous condition). Une clé
obligatoire à `null` (laissée ainsi par l'outil GDTF) rend la fiche invalide.

| Clé | Type | Obl. | Rôle |
|---|---|---|---|
| `version` | entier | oui | `1` |
| `id` | texte ASCII `a-z0-9_` | oui | identifiant, égal au nom du dossier |
| `manufacturer`, `model` | texte | oui | identité |
| `family` | `moving_wash` / `moving_profile` / `pc` / `profile` / `hazer` | oui | famille. Détermine les énumérations de la section 3 : `backlight` → `moving_wash` ; `front_movers`, `towers` → `moving_wash` ou `moving_profile` ; `front_pc` → `pc` ; `profiles` → `profile` ; `haze.fixture` → `hazer` |
| `sources` | liste (au moins une) de `{kind, url, note}` | oui | `kind` : `datasheet`, `gdtf`, `ies`, `other`. `url` : adresse ou chemin relatif |
| `physical.weight` | kg | oui | poids, avec accessoires de la fiche |
| `physical.dimensions` | `{width, depth, height}` | si pas `hazer` | encombrement en position neutre, `height` de la face de fixation au point le plus bas |
| `physical.mount.hook_height` | m | si pas `hazer` | de l'axe du tube à la face de fixation de l'embase |
| `physical.mount.tilt_axis_height` | m | si pas `hazer` | de la face de fixation à l'axe de tilt, le long de l'axe de pan |
| `optics.beam_type` | `profile` / `wash` | si pas `hazer` | choisit la source de lumière (14.3) |
| `optics.lens_diameter` | m | si pas `hazer` | diamètre utile de la lentille |
| `optics.lens_offset` | m | si pas `hazer` | de l'axe de tilt à la face avant de la lentille, le long du faisceau |
| `optics.flux` | lm | si pas `hazer` | flux total, pleine intensité, blanc |
| `optics.field_angle` | `{min, max}` | si pas `lens_tubes` | angle de champ plein (bord à 10 %) aux deux extrémités du zoom, DMX ou mécanique ; un appareil sans zoom ni tubes donne `min` = `max` |
| `optics.beam_angle` | `{min, max}` | si `wash` | angle de faisceau plein (50 %), mêmes extrémités |
| `optics.lens_tubes` | liste de `{name, beam_angle, field_angle, lens_diameter, ies}`, triée par `field_angle` croissant | si pas `field_angle` | lentilles fixes ; exclusif de `field_angle` : exactement l'un des deux. `name` : nom du tube, unique (nominal constructeur) ; `beam_angle` ≤ `field_angle`, angles pleins mesurés (50 % et 10 %) ; `lens_diameter` : m, `null` = `optics.lens_diameter` ; `ies` : chemin ou `null` |
| `optics.zoom_invert` | booléen | non (`false`) | `false` : 0 = `min` ; `true` : 0 = `max` |
| `optics.ies` | chemin, ou liste de `{field_angle, file}` | non | profil IES, Cycles seulement. Une liste donne un profil par position de zoom (`field_angle` : degrés, uniques) ; le profil d'un tube est `lens_tubes[].ies` |
| `colour.systems` | liste parmi `rgbw`, `cmy`, `cto`, `cct`, `emitters` | non (vide = blanc fixe) | systèmes de couleur présents |
| `colour.cct_range` | `{min, max}` K | si `cct` | plage de température de couleur |
| `colour.cto_kelvin` | K | si `cto` | température de couleur du filtre CTO plein |
| `colour.emitters` | liste de `{attribute, rgb}` | si `emitters` | une émission par attribut `emitter_N`, `rgb` linéaire 0–1 de l'émetteur à pleine intensité |
| `motion.type` | `moving` / `static` | si pas `hazer` | `static` : visée fixée à la construction |
| `motion.pan`, `motion.tilt` | `{min, max, invert}` | si `moving` | course physique, en degrés, zéro compris (convention 13.9). `invert` (booléen, `false` par défaut) : l'octet DMX 0 vaut `max` (GDTF `PhysicalFrom` > `PhysicalTo`) ; `min` < `max` reste vrai |
| `blades.count` | entier (4) | non | la section `blades` absente = pas de lames ; `count` vaut 4 par défaut |
| `blades.mode` | `motorised` / `manual` | si lames | `manual` : réglées à la construction |
| `blades.gate_from_lens` | m | si lames | du plan des lames à la face avant de la lentille, vers l'arrière |
| `blades.span` | m | si lames | longueur du bord d'une lame ; `e = span/2` |
| `blades.travel` | `{open, closed}` | si lames | distance du bord à l'axe, positive du côté de la lame, négative au-delà de l'axe : lame dégagée / course complète |
| `blades.sides` | 4 angles | si lames | direction « côté lame » de chaque lame, rotation du cadrage nulle, de +X vers +Y de la tête (13.8) |
| `blades.angle_limit` | angle | si lames | inclinaison maximale du bord, ± |
| `blades.rotation` | `{min, max, invert}` | si `motorised` | course de `blade_rot` ; `invert` comme pour `motion.pan` |
| `gobos.wheels` | liste de `{name, rotation_range, slots}` | non | `name` : `gobo1` ou `gobo2` ; `rotation_range` : degrés pour `gobo1_rot` (360 par défaut) ; `slots` : liste de `{name, image, dmx}`, `image` facultatif (absent ou `null` : fente ouverte), `dmx` : `[octet_min, octet_max]` |
| `iris.min_ratio` | 0–1 | non | rapport du diamètre d'iris fermé au diamètre ouvert |
| `strobe` | `{open, closed, strobe}` | non | `open`, `closed` : `[octet_min, octet_max]` ; `strobe` : `{from, to, hz_min, hz_max}` |
| `modes` | liste | oui | modes DMX (ci-dessous) |
| `default_mode` | texte | oui | nom d'un mode |
| `model3d` | voir ci-dessous | oui | modèle 3D |
| `qlc` | `{manufacturer, model, modes, verified}` | non | définition QLC+ équivalente (section 16.3) |

Un mode : `{name, footprint, channels}`, `footprint` = nombre de canaux
occupés. Un canal : `{offset, attribute, bits, default, fine, curve,
curve_mode}` :
`offset` à partir de 1 ; `attribute` du vocabulaire 12.3 ; `bits` 8 ou 16 ;
`default` : octet (8 bits) ou entier 0–65535 (16 bits) ; `fine` : offset du
canal fin si `bits` vaut 16 (défaut `offset + 1`) ; `curve` (facultatif) :
liste de paires `[dmx, valeur]`, `dmx` normalisé 0–1 (indépendant de 8 ou 16
bits), strictement croissant, deux points au moins ; `curve_mode` : `linear`
(défaut, interpolation entre points) ou `step` (chaque valeur tenue jusqu'au
point suivant). Les offsets d'un mode sont uniques et inférieurs ou égaux à
`footprint`.

`model3d` :

- `kind: procedural` : `shape` (`pc`, `profile`, `box`), `body` `{width,
  depth, height}`, `barrel` `{diameter, length}` (obligatoire pour `profile`),
  `yoke` `{gap, height}` (facultatif) ; tout en mètres. Le dessin se déduit de
  ces cotes.
- `kind: mesh` : `parts` `{base, yoke, head}` (les trois sont obligatoires),
  chacune `{file, offset}`. `file` : `.glb` ou `.obj`, en mètres. Un `.glb` est
  lu en Y vers le haut et converti en Z vers le haut, comme l'importeur de
  Blender : `(x, y, z)` devient `(x, −z, y)`. `offset` : position de l'origine de la
  pièce dans le repère de la pièce parente (`base` : face de fixation ;
  `yoke` : dans `base` ; `head` : dans `yoke`, à l'axe de tilt). Si un
  fichier ne s'importe pas, repli sur un `procedural` déclaré dans la même
  fiche (`fallback`).

Le hazer n'a ni `physical.dimensions`, ni `optics`, ni `motion` : sa fiche
porte `physical.weight`, `modes` et `model3d: {kind: none}` (racine vide,
section 14.1).

### 12.3 Vocabulaire des attributs DMX

Identifiants anglais, valeur normalisée `v` dans [0, 1] (section 12.4). Un
attribut absent du mode n'est tout simplement pas lu : l'appareil garde sa
valeur neutre.

**Courbe.** Un canal qui porte une `curve` (12.2) convertit `v` en valeur
physique par cette courbe (`Channel.physical`) au lieu de la formule linéaire
ci-dessous : c'est le cas d'un CCT 8 bits par paliers (0 = 3200 K chez ETC) ou
d'un CTC inversé et non linéaire (Robe). Avant le premier point et après le
dernier, la valeur de l'extrémité est tenue.

| Attribut | Sens de `v` |
|---|---|
| `dimmer` | intensité, linéaire |
| `pan`, `tilt` | `angle = min + v·(max − min)` de `motion.pan` / `motion.tilt` ; `v` devient `1 − v` si `invert` |
| `zoom` | champ `= min + v·(max − min)` de `optics.field_angle` (inversé si `zoom_invert`) ; le faisceau suit par la même interpolation sur `beam_angle` |
| `color_r`, `color_g`, `color_b`, `color_w` | niveau de l'émetteur ou du canal additif |
| `cyan`, `magenta`, `yellow` | 0 = filtre dégagé, 1 = filtre plein |
| `cto` | 0 = aucun, 1 = filtre `cto_kelvin` plein |
| `cct` | `K = min + v·(max − min)` de `colour.cct_range`, linéaire en K *(choix)* |
| `emitter_1` … `emitter_8` | niveau de chaque émetteur de `colour.emitters` |
| `strobe` | octet `B = round(255·v)` ; interprété par `strobe` de la fiche (14.7) |
| `gobo1`, `gobo2` | octet `B = round(255·v)` ; la fente est celle dont `dmx` contient `B` |
| `gobo1_rot`, `gobo2_rot` | angle du gobo = `v·rotation_range` de la roue `gobo1` / `gobo2` |
| `iris` | 0 = ouvert, 1 = fermé à `iris.min_ratio` |
| `blade_1a`, `blade_1b` … `blade_4a`, `blade_4b` | insertion aux deux extrémités A et B de la lame ; 0 = dégagée, 1 = course complète |
| `blade_1_rot` … `blade_4_rot` | pivotement de la lame K autour de son axe : angle = `angle_limit·(1 − 2v)`, 0 au milieu *(choix : sens du GDTF Robe, +30° à `v` = 0, à confirmer contre 13.8)* |
| `blade_rot` | rotation du cadrage, `min + v·(max − min)` de `blades.rotation` (`1 − v` si `invert`) |
| `haze_density` | densité du hazer, 0 – 1 |

**Attribut inconnu.** L'outil GDTF (12.6) et la fiche acceptent tout autre
nom, conservé tel quel, en minuscules et sans espaces (ex. `aura_dimmer`,
`prism1`). Un tel canal compte dans l'empreinte, reçoit sa propriété
`dmx_<u>_<c>` (valeur par défaut de la fiche), figure dans le patch et dans
l'export QLC+, mais **aucun objet Blender ne le lit**. Le prisme et le frost
sont dans ce cas (voir `BACKLOG.md`).

### 12.4 Canaux 8 et 16 bits

Une propriété de scène `dmx_<u>_<c>` vaut `octet / 255` (contrat du pont).

- 8 bits : `v = c`, `c` étant la propriété du canal.
- 16 bits : avec `c` la propriété du canal gros et `f` celle du canal fin,
  `v = (c + f/256) · 256/257 = (256·c + f)/257`. C'est exactement
  `N / 65535` pour `N = 256·octet_gros + octet_fin`. La forme brute
  `c + f/256` dépasse 1 de 0,39 % à pleine échelle et décalerait un pan de
  540° de 2° : elle n'est pas employée.
- Écriture d'une valeur `v` (valeurs de repos, 15.2) : 8 bits `N = round(255·v)`,
  propriété `N/255` ; 16 bits `N = round(65535·v)`, octets `N >> 8` et
  `N & 255`, propriétés `octet/255`. L'erreur maximale est une demi-unité du
  dernier bit : 0,004° sur un pan de 540°.
- `core` fournit `encode(v, bits)` → octets, `to_properties(v, bits)` → valeurs
  de propriétés (`octet / 255`) et `decode(c, f, bits)` → `v` (`c` et `f` étant
  des propriétés) ; l'aller-retour est testé.

### 12.5 Les six fiches livrées

Identifiants fixes. Les valeurs non citées ici sont « à relever dans la
fiche constructeur » et saisies dans le YAML avec leur source.

| `id` | Famille | Origine et données connues |
|---|---|---|
| `martin_mac_aura` | `moving_wash` | MAC Aura (pas la XB). GDTF `Martin_Professional@MAC_Aura@20230201NoMeas.gdtf` (dossier du module Open Stage Blender DMX de l'utilisateur), copié dans `source/`. Anneau « Aura » : canaux conservés comme attributs inconnus (`aura_*`), non rendus |
| `robe_robin_esprite` | `moving_profile` | GDTF « Robin Esprite » `Robe_Lighting@Robin_Esprite@2024-02-15…gdtf`. Lames motorisées `blade_1a` … `blade_4b`, `blade_1_rot` … `blade_4_rot`, `blade_rot` ; gobos et iris ; couleur CMY + CTO |
| `generic_pc_led` | `pc` | PC LED générique, blanc variable (`cct`), **étalonné sur la photométrie d'un vrai PC LED** dont les sources sont citées dans `sources`. Pas de GDTF |
| `etc_s4led_s3_lustr_x8` | `profile` | ETC Source Four LED Series 3 Lustr X8 : 10 889 lm, huit émetteurs (rouge profond à indigo, `colour.emitters`), fenêtre de 80 mm, 8,9 kg avec le barillet à lames (6,8 kg sans), lames manuelles, tubes de lentille 5, 10, 14, 19, 26, 36, 50 et 70° (ceux qui ont un plan ETC) ; dix modes DMX de 1 à 21 canaux (manuel v1.4.0 : cinq modes 8 bits de 1 à 12 canaux plus HSIC et quatre modes 16 bits ; la fiche technique n'en annonce que cinq). Pas de GDTF |
| `etc_s4led_s3_daylight_hdr` | `profile` | Idem avec le module Daylight HDR : 14 214 lm, `cct` de 1900 à 10450 K. Pas de GDTF |
| `generic_hazer` | `hazer` | Machine à brume à un canal `haze_density` |

### 12.6 Outil GDTF → fiche

`tools/gdtf_to_fiche.py <fichier.gdtf> --id <id> [--mode <nom> …] --out
blender/theatre_stage/library/fixtures/<id>/` (Python système, `zipfile` et
`xml.etree`, sans dépendance). Il lit `description.xml` et écrit un
`fixture.yaml` à compléter à la main.

**Rempli par l'outil :**

- `id` (proposition `fabricant_modele`), `manufacturer`, `model`, `sources`
  (le GDTF, copié dans `source/`) ;
- `modes` : nom, empreinte, canaux (offset, 8 ou 16 bits d'après les offsets
  multiples du canal GDTF, valeur par défaut), `default_mode` = premier mode ;
- attributs, d'après la table ci-dessous ; tout nom inconnu est conservé ;
- `motion.pan` / `motion.tilt` d'après `PhysicalFrom` / `PhysicalTo` des
  fonctions de canal, avec `invert: true` quand la première fonction descend
  (`PhysicalFrom` > `PhysicalTo`) ; même règle pour `blades.rotation` ;
- `optics.beam_angle` d'après les bornes physiques de `Zoom` (le GDTF donne
  l'angle de faisceau), `optics.flux` et `optics.lens_diameter` d'après la
  géométrie de faisceau (`LuminousFlux`, `BeamRadius`), `optics.beam_type` ;
- `gobos.wheels` : fentes, plages DMX, images extraites dans `gobos/` ;
- `strobe`, `iris.min_ratio` d'après les fonctions de canal ;
- `curve` d'un canal (`CTC`, `CTO`, `Zoom`...) dont les fonctions ou les jeux de
  valeurs ont plusieurs valeurs physiques : paires `[début DMX normalisé,
  valeur physique]`, `curve_mode: step` si les jeux sont discrets (au mieux,
  à vérifier) ;
- `model3d.kind: mesh` : fichiers de `Models` placés dans `meshes/`, `offset`
  d'après l'arbre de géométries (translation seule, relative à la pièce
  parente) ; `physical.weight` d'après `Properties/Weight`, et
  `physical.dimensions` d'après l'encombrement des maillages placés.
  - `.glb` : copié tel quel.
  - `.3ds` : converti en `.obj` par un lecteur de blocs 3DS écrit dans l'outil
    (principal `0x4D4D`, éditeur `0x3D3D`, objet `0x4000`, maillage `0x4100`,
    sommets `0x4110`, faces `0x4120`). La matrice locale `0x4160` n'est pas
    appliquée : un 3DS stocke ses sommets en repère monde.
  - **Unités.** Un GDTF est en mètres, mais ses `.3ds` sont le plus souvent en
    millimètres (MAC Aura). L'outil compare les dimensions `Length`, `Width`,
    `Height` du `<Model>` à la boîte englobante du maillage et retient le
    facteur (1, 0,001, 0,01 ou 0,0254) le plus proche ; sans dimensions, 0,001.
    Les `.obj` écrits sont donc en mètres. Pour un `.glb`, un autre facteur
    n'est que signalé.
- `colour.systems` (d'après les attributs présents), `colour.cct_range` (bornes
  de `CTC`), `colour.cto_kelvin` (borne basse de `CTO`), `optics.zoom_invert`
  (vrai si `PhysicalFrom` du zoom dépasse `PhysicalTo`) et `blades.rotation`
  (bornes de `BladeRot` ou `ShaperRot`) sont pré-remplis, à confirmer.
- Un canal dont l'attribut du vocabulaire est déjà pris dans le mode (second
  `Dimmer` de la géométrie « Auras ») est gardé sous `<géométrie>_<attribut>`,
  en minuscules (`auras_dimmer`), comme un attribut inconnu.

| Attribut GDTF | Attribut de la fiche |
|---|---|
| `Dimmer` | `dimmer` |
| `Pan`, `Tilt`, `Zoom` | `pan`, `tilt`, `zoom` |
| `ColorAdd_R`, `_G`, `_B`, `_W` | `color_r`, `color_g`, `color_b`, `color_w` |
| `ColorSub_C`, `_M`, `_Y` | `cyan`, `magenta`, `yellow` |
| `CTO` | `cto` |
| `CTC` | `cct` |
| `Shutter1` (et `Shutter1Strobe…`) | `strobe` |
| `Gobo1`, `Gobo2` | `gobo1`, `gobo2` |
| `Gobo1Pos`, `Gobo2Pos` | `gobo1_rot`, `gobo2_rot` |
| `Iris` | `iris` |
| `Blade1A`, `Blade1B` … `Blade4A`, `Blade4B` | `blade_1a`, `blade_1b` … `blade_4a`, `blade_4b` |
| `Blade1Rot` … `Blade4Rot` | `blade_1_rot` … `blade_4_rot` |
| `BladeRot`, `ShaperRot` | `blade_rot` |

**Complété à la main** (laissé à `null  # à compléter` quand obligatoire) :
`family`, URLs des fiches techniques, `physical.mount`, `optics.lens_offset`,
`optics.lens_diameter` quand le GDTF a plusieurs sources (MAC Aura),
`optics.field_angle` (le GDTF ne donne que le faisceau), `colour.emitters`,
la géométrie des lames (`gate_from_lens`, `span`, `travel`, `sides`,
`angle_limit`), `model3d` procédural ou son repli, `qlc`, `optics.ies`. L'outil
écrit `fixture.yaml` sans PyYAML ; il importe `core/meshio.py` du dépôt.

### 12.7 Validation

`core/fixtures.py` rend, pour chaque fiche, un objet figé ou une liste
d'erreurs en français. `Fixture.ies_for(field_angle, tube)` donne le fichier IES
du tube, sinon celui du profil de zoom le plus proche, sinon `None`. Contrôles : clés obligatoires (conditions du tableau
12.2) ; `id` égal au nom du dossier ; offsets uniques et ≤ `footprint` ; canaux
16 bits dont `fine` est libre ; `default_mode` existant ; `min` ≤ `max` ;
`lens_tubes` triés par `field_angle`, noms uniques, `beam_angle` ≤ `field_angle` ; `curve` d'au moins deux points, `dmx` strictement croissant dans [0, 1] ; `ies` en liste : `field_angle` uniques ; `blades.sides` à quatre angles distincts ;
un attribut du vocabulaire n'apparaît qu'une fois par mode (sauf attributs
inconnus) ; exactement l'un de `field_angle` et `lens_tubes` ; au moins une
source ; fichiers cités présents (images de gobos, maillages, IES, sources
données par un chemin relatif).

## 13. Implantation lumière

Tout est calculé dans `core/rig.py` (positions, visées, champs, lames,
pan/tilt, patch, valeurs de repos). `compute_layout(params, library)` l'appelle
et rend le résultat dans `Layout.rig` ; sans `library`, c'est la bibliothèque
livrée. Une fiche absente ou inadaptée écarte la famille avec une alerte,
jamais d'erreur. `rigbuild.py` ne fait que traduire. Méthode : fiche ADEC 6-3
(McCandless) : site 45° et azimut 45°, deux appareils de directions opposées
par zone, faisceaux parallèles en plan pour une même direction, chaud d'un
côté et froid de l'autre, recouvrement des zones voisines.

### 13.1 Notations et zone de jeu

Valeurs existantes : `Wc`, `Wt`, `Wk`, `Hp`, `Hc`, `Hf = facade_height`,
`Ys`, `D`, `Yh`, `Zb = Hp + Hg − batten_drop`, `Yb` (ligne de fond, 8.1).
Nouvelles :

- `Za = Hp + aim_height` : plan de visée (2,90 par défaut).
- **Zone de jeu** : `X` sur `[−Wc/2, Wc/2]`, `Y` sur `[0, Ya]` avec
  `Ya = min(area_depth, Yb)`. Alerte « Zone de jeu raccourcie » si
  `area_depth > Yb`.
- **Grille de zones** : `nx = columns` et `nr = rows` en mode manuel ;
  automatique : `zone_width` est un **maximum** visé :
  `nx = max(1, ceil(Wc / zone_width − 1e-9))` et
  `nr = min(4, max(1, ceil(Ya / zone_width − 1e-9)))`. `zw = Wc/nx`,
  `zd = Ya/nr` (4 × 2 zones de 2,50 × 3,00 par défaut). Raison *(choix)* : le PC
  générique est calibré sur un Robe T15 PC dont le champ le plus large est
  54,4° ; des zones de 3,33 m vues depuis la première porteuse lumière
  demandent 64,9°. Zone `(i, j)`, `i` de 0 (jardin) à `nx − 1`, `j`
  de 0 (face) à `nr − 1` : centre `(xc_i, yr_j)` avec
  `xc_i = −Wc/2 + (i + ½)·zw`, `yr_j = (j + ½)·zd`. La grille est calculée
  même si `front_pc.enabled` est décoché.
- `spread(i, n) = −Wc/2 + (i + ½)·Wc/n` : répartition régulière sur
  l'ouverture du cadre.
- Visée de zone `T_ij = (xc_i, yr_j, Za)`.
- **Point d'accroche** `H = (X, Y, Zh)` : sur l'axe du tube. **Racine** de
  l'appareil : `(X, Y, Zh − hook_height)`. **Pivot** `P` : axe de tilt,
  `(X, Y, Zh − hook_height − tilt_axis_height)`. Toute visée part de `P`.
- `nearest_batten(y)` : porteuse lumière dont le Y est le plus proche de `y`
  (`None` s'il n'y en a pas). **Première porteuse** : la plus proche de la
  face. Les accroches se font **par position en Y, jamais par numéro** : le
  retrait d'une porteuse par le pendrillonnage (5.5) renumérote sans casser le
  plan de feux.

### 13.2 Perche de face — `FrontPipe`

Tube Ø 0,048 (`TS_Batten`) sous le plafond de salle, parallèle au nez, X sur
`±(Wt/2 − 0,10)`.

- `Zp = Hf − ceiling_gap` (7,00 par défaut).
- Mode automatique : le site fixe la distance horizontale à la zone de la
  première rangée, l'azimut la répartit en Y et en X :
  `h = (Zp − Za) / tan(site)`, `ΔYp = h·cos(azimuth)`, `Yp = yr_0 − ΔYp` (`azimuth`
  de `front_pc`).
  Par défaut `h = 4,10`, `ΔYp = 2,90`, `Yp = 1,50 − 2,90 = −1,40` : le
  décalage en X du même appareil vaut aussi 2,90.
- Mode manuel : `Yp = rig_front.y` ; `ΔYp` garde la valeur du calcul
  automatique (il sert en 13.7).
- Alertes : `Zp ≤ Za` ; `Yp` hors de `[−Yh + 0,30, Ys − 0,30]` (perche hors de
  la salle sous le plafond).
- Aucune suspente n'est dessinée en v1.
- `FrontPipe` porte les 8 PC du rang 0 et les 3 découpes (13.7, 13.8) ; les
  mobiles de face sont sur la seconde perche (13.2 bis).

### 13.2 bis Seconde perche — `FrontPipe_02`

Tube identique à `FrontPipe` (Ø 0,048, `TS_Batten`, même longueur), parallèle
au nez, **derrière** la première du point de vue du plateau, côté salle. Elle
n'existe que si les mobiles de face sont posés. Raison : des mobiles ne
peuvent pas bouger en réalité à côté des PC (sur la première perche, l'écart
posé le plus petit était de 0,08 m avec les mobiles dessus, il est de 0,29 m
sans), et leurs faisceaux doivent passer entre les corps.

- `Y2 = Yp − movers_offset` (1,50 par défaut *(choix)* : `Y2 = −2,90`). Alerte
  « Perche des mobiles hors de la salle » si `Y2 < −Yh + 0,30`.
- **Hauteur `Z2`**. Mode `manual` : `Z2 = movers_z`. Mode `auto` : parmi
  `Zp, Zp − 0,05, Zp − 0,10, …` jusqu'à `Hp + Hc` (hauteur du linteau
  *(choix)*), la **première** valeur pour laquelle les contrôles de 13.11 ne
  trouvent aucun faisceau gêné ni débattement qui touche un appareil. Aucune
  ne convient : alerte « Perche des mobiles de face : aucune hauteur de … à …
  ne dégage … » ; la hauteur retenue est celle qui laisse le moins de cas
  bloqués (à égalité, le jeu le moins mauvais), et les cas bloqués sont
  rapportés un à un par les alertes de 13.11. Valeur avec les défauts :
  `Z2 = 6,75`, soit 0,25 m sous `Zp` : à `Zp`, le faisceau d'un mobile visant
  le fond cour ou jardin frôle le corps des PC de la première perche.
- Les calculs de la perche, `Zh`, l'accroche et le rangement sont ceux de
  13.3 et 13.10 avec `(Y2, Z2)` ; la visée de repos des mobiles ne change pas
  (13.5).

### 13.3 Points d'accroche sur les tubes

Un appareil a un `Zh` : `Zp` pour la perche de face, `Z2` pour la seconde
perche, `Zb` pour une porteuse lumière. Un `X` hors du tube (`±(Wt/2 − 0,10)`
pour les perches,
`±(Wk/2 − 0,10)` pour une porteuse) est ramené à l'extrémité et signalé :
« Point d'accroche hors de la perche : … ».

### 13.4 Contre — `Backlight_NN`

`N = count` MAC Aura (par défaut), `NN` de 01 (jardin) à `N`.

- `Zh = Zb`, `X_i = spread(i, N)`. Porteuse : `position = upstage` (défaut) :
  la plus reculée des porteuses lumière devant `Yb`, c'est-à-dire la
  porteuse de la dernière rue (5.5). `position = distance` :
  `Yg = nearest_batten(distance).Y`, avec l'alerte si
  `|Yg − distance| > 0,50` (« Aucune porteuse à moins de 0,50 m de … : contre
  posé à … m »). Sans aucune porteuse : pas de contre, alerte.
- **Visée de repos** : `T = (X_i, yr_j, Za)` où `j` est le rang dont le centre
  est le plus grand `yr_j < Yg` (zone devant le contre, côté face) ; à
  défaut `j = 0`. Depuis la perche du fond (Y = 6,21, Z = 6,80), les contres
  visent le rang 2 (Y = 4,50) : pan 0°, tilt 25,4° vers la salle, soit un
  faisceau à 65° au-dessus de l'horizontale.

### 13.5 Mobiles de face — `FrontMover_NN`

`N = count` Esprite (par défaut), `NN` de 01 à `N`, jardin vers cour. Accroche
`(spread(i, N), Y2, Z2)` sur `FrontPipe_02` (13.2 bis). Visée de repos
`T = (X_i, yr_0, Za)`. Le patch reste l'univers 2 (15.1).

### 13.6 Pylônes — `Tower_L_NN`, `Tower_R_NN`

Pour chaque côté `s` (−1 jardin, +1 cour) et chaque pylône `k` de 1 à `count`
(jeu miroir si `symmetric`) :

- `Y_k = −(first_distance + (k − 1)·spacing)` ; `B = max(base_size, truss_size)` ;
  axe `X_t = s·(Wt/2 − B/2)` : la platine touche le mur de salle.
- `Tower_<c>_NN` : **un seul maillage** (`TS_Truss`) : platine `B × B`,
  épaisseur 0,02, puis section carrée `truss_size`, de `Z = 0` à `height` :
  quatre montants Ø 0,05, un cadre horizontal tous les 0,50, une diagonale
  par face et par travée.
- Mobile `m` (de 1, en haut, à `movers`) : bras `TowerArm_<c>_NN_MM` (tube
  Ø 0,048, `TS_Batten`) à `Z_m = height − 0,10 − (m − 1)·pitch`, avec
  `pitch = hook_height + dimensions.height + 0,10` *(choix : jeu de 0,10)*.
  Longueur du bras `arm = max(0,25, dimensions.width/2 + 0,10)` *(choix)*,
  du flanc du truss `X = s·(|X_t| − truss_size/2)` à
  `X_m = s·(|X_t| − truss_size/2 − arm)`. Accroche `(X_m, Y_k, Z_m)`.
- Appareils `TowerMover_L_NN` / `_R_NN` : `NN` continu sur le côté, pylône
  après pylône, du haut vers le bas.
- **Visée de repos** : côté opposé de la scène,
  `T = (−s·Wc/4, Ya·(m − ½)/movers, Za)`.
- Alertes : bas du dernier appareil `Z_m − hook_height − dimensions.height <
  0,50` (« Pylône trop bas pour n appareils ») ; emprise du pylône
  (`B × B`) qui recoupe un escalier, son palier ou son dégagement (5.6) ;
  `Y_k − B/2 < −Yh`.

### 13.7 PC de face — `FrontPC_L_NN`, `FrontPC_R_NN`

Deux appareils par zone, un par direction `d` : `L` (accroché côté jardin,
`s_d = −1`) et `R` (côté cour, `s_d = +1`). `NN = j·nx + i + 1`. Total
`2·nx·nr` (16 par défaut).

- **Accroche en Y** : rang 0 sur la perche de face `(Yp, Zp)` ; rang 1 sur la
  **première porteuse lumière** `(Y, Zb)` (méthode ADEC) ; rang `j ≥ 2` sur
  `nearest_batten(yr_j − ΔYp)` *(choix)*. `ΔY = yr_j − Y_accroche`. Si
  `ΔY < 0,10` : rang non posé, alerte « Rang j : porteuse trop en arrière de
  la zone ».
- **Accroche en X** (croisement) : `X = xc_i + s_d·ΔY·tan(az_j)`. Même
  azimut `az_j` pour tous les appareils d'une direction d'un rang : faisceaux
  parallèles en plan ; le site varie avec le rang.
- **Azimut par rang** *(choix)* : avec 4 colonnes, le croisement place sur un même
  tube des PC de directions opposées proches l'un de l'autre
  (`FrontPC_L_07` et `FrontPC_R_05` sur `Batten_01`, 0,34 m) et, panotés de
  ±132°, leurs têtes s'entrecoupent. Pour chaque rang,
  `az_j` est l'azimut le plus proche de `azimuth` (pas de 0,5°, en alternant
  + et −, jusqu'à ±10°) tel que les **empreintes posées** (13.10) de deux PC du
  tube ne se recouvrent jamais, que les points d'accroche restent sur le tube et
  que chaque zone tienne dans le champ le plus large de la fiche. Par défaut :
  45° au rang 1, 50° au rang 2. Les deux
  directions du rang utilisent ce même `az_j`. Aucun azimut ne convient :
  alerte « Rang j : aucun azimut … » et azimut nominal conservé. L'azimut de
  chaque rang est affiché dans « Cotes calculées ». Le rangement des autres
  appareils (13.10) vient ensuite.
- **Visée** : `T_ij`. Axe `a = (T_ij − P)/|T_ij − P|`.
- **Champ couvert** : rectangle centré sur `T_ij` au plan `Za`, de demi-côtés
  `(zw/2)·(1 + overlap)` en X et `(zd/2)·(1 + overlap)` en Y ; quatre coins
  `C_k`. Champ requis `F_req = 2·max_k angle(a, (C_k − P)/|C_k − P|)`.
  `F = clamp(F_req, field_angle.min, field_angle.max)`, puis le faisceau suit
  (12.3). `F_req > max` : alerte « Zone non couverte » ; `F_req < min` :
  alerte « Champ trop large » (une alerte par nature, qui liste les appareils).
  Le champ est une valeur de construction, pas un canal DMX, sauf si le mode
  a `zoom` : la valeur de repos du canal reproduit alors `F` (15.2).
- **Circuits** : un par (rang, direction) : `FrontPC_Row1_L`, `FrontPC_Row1_R`,
  `FrontPC_Row2_L`, `FrontPC_Row2_R` (4 circuits pour 16 PC). Propriété
  `theatre_circuit` de la racine.
- **Couleur de repos** : `rest.cct_left` pour `L`, `rest.cct_right` pour `R`
  (chaud côté jardin, froid côté cour *(choix)*).

### 13.8 Découpes — `Profile_L`, `Profile_C`, `Profile_R`

Trois sur la perche de face, une par tiers de l'ouverture. Tiers `p` = 0, 1,
2 : bornes `B_p = −Wc/2 + p·Wc/3` et `B_(p+1)`, accroche
`(spread(p, 3), Yp, Zp)`, visée `T_p = (spread(p, 3), Y_v, Za)`, axe `a`
depuis `P`. `Y_v` *(choix)* est le point où la bissectrice des directions
bas et haut (vue de côté, depuis `P`) coupe le plan `Za` : l'axe centre la
fenêtre éclairée et le champ requis reste minimal (avec `Ya/2`, la coupe basse
au nez demandait 82,6°, au-delà du tube le plus large, 72,5°). Appareils statiques, un circuit chacun (`Profile_L` …).

**Quatre plans de coupe** passant par la source `S` ; chacun contient une
droite cible `(Q, u)` (point, direction unitaire) :

| Coupe | Droite cible | Effet |
|---|---|---|
| bas | `Q = (0, 0, Hp)`, `u = (1, 0, 0)` | le faisceau finit sur le nez, rien sur l'avant-scène |
| haut | `Q = (0, Ya, Hp + top_height)`, `u = (1, 0, 0)` ; limite du linteau, voir ci-dessous | le faisceau passe au-dessus de la tête d'un comédien debout au fond de la zone de jeu *(choix : `top_height` = 2,20, comédien debout et marge)* |
| gauche | `Q = (B_p, 0, Za)`, `u = (0, 1, 0)` | limite du tiers (cadre pour le tiers jardin) |
| droite | `Q = (B_(p+1), 0, Za)`, `u = (0, 1, 0)` | limite du tiers (cadre pour le tiers cour) |

**Limite du linteau.** Si le plan de coupe haute passe, au plan
`Y = Ys + 0,05` (face avant du cadre), au-dessus du bas du linteau
`Z = Hp + Hc − lintel_margin`, la droite cible devient
`Q = (0, Ys + 0,05, Hp + Hc − lintel_margin)` : la coupe la plus restrictive
l'emporte. Avec les défauts, les trois découpes trouvent un tube (le « 70 »,
champ 72,5°) sans « lame hors course ».

Normale du plan : `n = (Q − S) × u / |(Q − S) × u|`, orientée vers le côté
**sombre** : `n·a < 0` (l'axe est dans la zone éclairée).

**Tube de lentille** (`lens_tubes`) :

1. Premier calcul avec `S = P` : directions des coins du cadrage
   `c = n₁ × n₂` pour les couples (bas, gauche), (bas, droite), (haut,
   gauche), (haut, droite), signe tel que `c·a > 0`.
   `F_req = 2·max_k angle(a, c_k)`.
2. Tube = le plus petit de `lens_tubes` dont le `field_angle` vérifie
   `field_angle ≥ 1,05·F_req` *(choix : marge de 5 %)*. `tube_angle ≠ 0` :
   le tube dont le `field_angle` est le plus proche de cette valeur. Aucun tube assez large : le plus large, alerte
   « Découpe … : aucun tube ne couvre le cadrage ». Une fiche de découpe à zoom
   (sans `lens_tubes`) prend `F = clamp(1,05·F_req, min, max)`.
3. `F` = `field_angle` du tube ; `lens_diameter` = celui du tube (à défaut
   `optics.lens_diameter`). Source `S = P + a·(lens_offset − d)` avec
   `d = r / tan(F/2)`, `r = lens_diameter/2` (14.3). Les plans et les `n` sont recalculés
   avec ce `S`.

**Lames.** Repère de la tête `(x_h, y_h, a)` (13.9). Pour la lame `k`, avec
`ρ` la rotation du cadrage (0 en automatique) : direction « côté lame »
`o_k = cos(side_k + ρ)·x_h + sin(side_k + ρ)·y_h`, tangente
`q_k = −sin(side_k + ρ)·x_h + cos(side_k + ρ)·y_h`.
`g = max(d − gate_from_lens, 0,25·d)` *(choix)* : distance de `S` au plan des
lames. Chaque coupe de normale `n` est confiée à la lame `k` qui maximise
`o_k·n_⊥`, `n_⊥ = n − (n·a)·a` ; deux coupes sur la même lame : alerte
« Découpe … : lames de la fiche non adaptées au cadrage ». Pour la lame `k` :

- bord : `x(y) = h_c − y·tan α`, avec `h_c = −g·(n·a)/(n·o_k)` et
  `tan α = (n·q_k)/(n·o_k)` ; `x` est la distance à l'axe sur `o_k`, `y` sur
  `q_k` ;
- extrémités A (`y = −e`) et B (`y = +e`), `e = span/2` :
  `h_A = h_c + e·tan α`, `h_B = h_c − e·tan α` ;
- insertion normalisée `v = (open_eff − h) / (open_eff − closed)`, avec
  `closed` de `blades.travel` et `open_eff` ci-dessous (14.7 lit la même
  référence) ; valeur hors de [0, 1] ou
  `|α| > angle_limit` : ramenée et signalée « Découpe … : lame hors course » ;
- la lame dégagée ne mord jamais sur le faisceau :
  `open_eff = max(open, g·tan(F/2))`.

**Mode manuel** (`blades_mode = manual`) : pas de calcul de coupe ; pour la
lame `b` de la découpe `p` : `v = <p>_blade_<b>_insertion`, `α =
<p>_blade_<b>_angle`, `ρ = <p>_rotation`, converties en `h_c = open_eff + v·(closed
− open_eff)`. Le tube reste automatique sauf `tube_angle`. Les lames manuelles
d'un appareil `manual` ne sont pas des canaux : elles sont fixées à la
construction.

### 13.9 Visée de repos, pan et tilt

Convention de montage : appareil **suspendu tête en bas** sous un tube
parallèle à X. Repère du corps `(X_b, Y_b, Z_b)` = repère de la racine ; la
racine porte une rotation de 180° autour de X, donc pour un vecteur du monde
`(x, y, z)` le vecteur du corps est `(x, −y, −z)`. `Z_b` est l'axe de pan,
dirigé de l'embase vers la tête (vers le bas dans le monde). Face du corps :
`+Y_b`, tournée vers la salle (`−Y` du monde).

- À `pan = 0` et `tilt = 0` le faisceau suit `+Z_b` (droit vers le bas). Le tilt
  positif incline vers `+Y_b` (vers la salle), le pan positif tourne
  dans le sens trigonométrique autour de `+Z_b`. Direction du faisceau dans le
  repère du corps : `d_b(φ, τ) = (−sin τ·sin φ, sin τ·cos φ, cos τ)`.
- Pour une direction visée `a` du monde, `a_b = (a_x, −a_y, −a_z)`, puis
  `τ = acos(a_bz)` et `φ = atan2(−a_bx, a_by)` (`φ = 0` si `sin τ < 1e-6`).
  Ces angles sont des angles **physiques**, en degrés.
- Plages : `φ` est ramené par ± 360° dans `[pan.min, pan.max]` en prenant le
  représentant le plus proche du milieu de la plage. Hors plage ou
  `τ` hors de `[tilt.min, tilt.max]` : seconde solution `(φ + 180°, −τ)`.
  Aucune des deux : angles ramenés dans la plage, alerte « Pan/tilt hors
  course : … ». Un appareil `static` n'a pas de plage : `τ` ∈ [0°, 180°].
- Valeur DMX normalisée : `v = (angle − min) / (max − min)`, puis `v = 1 − v` si
  l'axe est `invert` (12.2), puis arrondi 16 bits (12.4) : `core` rend les deux octets de chaque canal et les valeurs
  d'angle effectivement atteintes après arrondi.
- Dans Blender : la pièce `_Pan` tourne de `φ` autour de son Z, la pièce
  `_Tilt` de `−τ` autour de son X (une rotation positive de Blender autour de X
  envoie `+Z` vers `−Y`, d'où le signe). Les appareils statiques reçoivent ces
  angles en rotations fixes ; les mobiles les reçoivent des drivers (14.7).
- Repère de la tête : `R_h = Rx(180°)·Rz(φ)·Rx(−τ)` ; `x_h`, `y_h`, `a` = images
  de `(1,0,0)`, `(0,1,0)`, `(0,0,1)` par `R_h`.

Récapitulatif des visées de repos :

| Famille | Visée `T` |
|---|---|
| contre | `(X_i, yr_j, Za)`, `j` = rang le plus proche en avant du contre |
| mobiles de face | `(X_i, yr_0, Za)` |
| mobiles des pylônes | `(−s·Wc/4, Ya·(m − ½)/movers, Za)` |
| PC de face | `T_ij` |
| découpes | `(spread(p, 3), Y_v, Za)`, `Y_v` : bissectrice des coupes bas et haut (13.8) |

### 13.10 Charges, encombrement et « Cotes calculées »

- **Charge** cumulée par support (chaque perche de face, chaque porteuse
  lumière, chaque pylône) : somme des `physical.weight`. Affichée, **sans alerte de
  dépassement** (`BACKLOG.md`).
- **Empreinte posée** : la largeur de la fiche ne suffit pas, une tête panotée
  et inclinée déborde de son corps. L'empreinte d'un appareil sur son support
  est l'intervalle des sommets de son modèle (14.2 : embase, étrier, tête)
  projetés sur l'axe du support, une fois le modèle placé : racine, rotation
  de 180° autour de X, pan puis tilt (13.9), agrandi de 0,02 m de chaque
  côté *(choix)*. Par simplification, on projette les huit coins de la boîte
  englobante de chaque pièce, ce qui majore l'intervalle ; le modèle pris est
  celui du tube de lentille par défaut de la fiche. L'axe est X pour une
  perche ou une porteuse, Z pour les mobiles empilés d'un pylône. Deux
  appareils d'un même support **se touchent** quand leurs intervalles se
  recouvrent. Pan et tilt sont ceux de la visée de repos, à la position
  d'accroche essayée.
- **Enveloppe d'un appareil à pan et tilt** (contre, mobiles de face, mobiles
  de pylône) : il ne reste pas à sa visée de repos, donc son empreinte est le
  volume balayé sur toute sa course, quel que soit le pan. Rayon
  `R` = plus grande distance à l'axe de pan des coins des boîtes englobantes
  de la base, de l'étrier et de la tête, la tête étant tournée de
  `tilt.min` à `tilt.max` par pas de 1°. Hauteurs : de `root_z − z_max` à
  `root_z − z_min`, `z` étant la cote le long de `Z_b` des mêmes coins.
  Intervalle sur le tube : `[x − R, x + R]`, sur un bras de pylône l'intervalle
  en Z ; marge de 0,02 m de chaque côté. Esprite : `R = 0,365 m`, hauteur
  0,76 m. C'est cet intervalle qui sert au rangement et à l'empilement des
  pylônes ; les boîtes englobantes majorent les sommets (Esprite : 12 %).
- **Encombrement et rangement** : sur un même tube (une perche de face ou une
  porteuse lumière), deux appareils dont les empreintes posées se recouvrent
  se touchent. Les PC de face gardent **leur X exact** (faisceaux parallèles,
  13.7). Tout autre appareil du tube (contre, découpes, mobiles de face),
  dans cet ordre puis par numéro, est placé au X libre **le plus proche** de
  son X voulu, cherché par pas de 0,05 m en alternant les côtés (le côté du
  centre du tube d'abord), sans sortir du tube ; l'empreinte se recalcule à
  chaque X essayé. *(choix)* Les découpes passent avant les mobiles : leurs
  lames ne tolèrent qu'un petit écart en X (inclinaison limitée à 20°), alors
  qu'un mobile reprend sa visée par son pan et son tilt. Sa visée reste le
  point cible de sa famille (13.4, 13.5, 13.8) ; pan, tilt, tube et lames se
  calculent depuis le point d'accroche déplacé. Alerte « Appareils qui se
  touchent sur la perche : … » seulement si aucune position libre n'existe, ou
  entre deux PC dont le X est imposé. L'azimut par rang (13.7) a déjà écarté
  les PC entre eux quand une solution existe. Les mobiles d'un pylône ont
  chacun leur bras et ne sont pas rangés : alerte « Appareils qui se touchent
  sur le pylône … » si leurs empreintes en Z se recouvrent.
- Ajouts à l'encadré « Cotes calculées » : `Yp` et `Zp`, `Y2` et `Z2`, `Ya`,
  `nx × nr` et `zw × zd`, rayon `R` des mobiles de face, jeu minimal des
  faisceaux (13.11), azimut `az_j` de chaque rang de PC, tube et champ de chaque découpe, charges, plages de patch par
  famille (15.1), pan et tilt (angles et valeurs DMX) de chaque mobile.

### 13.11 Faisceaux et débattement

Un faisceau est le cône de sommet la source (14.3), d'axe l'axe de la tête, de
demi-angle la moitié du champ de la fiche (champ de repos pour un mobile :
valeur par défaut du canal de zoom *(choix)*). Il va de la lentille au point
visé : un appareil derrière le point visé ne coupe pas la lumière qui y arrive
*(choix)*, et la portée est de 30 m au plus.

- **Corps rencontrés** : pour tout autre appareil, les 27 points (coins,
  milieux d'arêtes, centres de faces, centre) de la boîte englobante de chaque
  pièce, posée avec le pan et le tilt de repos (13.10) ; pour un appareil à
  pan et tilt, les points de son enveloppe (13.10), parce qu'il peut être
  ailleurs. Hazer exclu.
- **Jeu** d'un faisceau : plus petite distance signée des points entre la
  lentille et le point visé au bord du cône, négative dedans. Le faisceau est
  **gêné** si ce jeu est inférieur à 0,05 m *(choix)*.
- **Visées contrôlées** : la visée de repos de chaque appareil ; de plus, pour
  chaque mobile de face, les neuf points `X ∈ {−Wc/2, 0, Wc/2}`,
  `Y ∈ {0, Ya/2, Ya}`, `Z = Za`. Pan et tilt sont ceux de ces visées, ramenés
  dans la course (13.9). Un mobile de pylône ou de contre n'est contrôlé qu'à
  sa visée de repos.
- **Débattement** : l'enveloppe d'un appareil à pan et tilt ne doit contenir
  aucun point d'un appareil posé sur un **autre** support (le même support est
  réglé par le rangement, 13.10) ; deux enveloppes se touchent quand leurs
  cylindres se recouvrent.
- **Alertes** : « Faisceau de `A` vers (X ; Y ; Z) gêné par `B` : jeu … pour
  0,05 m minimum. » (les huit plus mauvais, puis le nombre des autres) ;
  « Débattement de pan et tilt : `A` et `B` se touchent. ». Le préréglage par
  défaut et les deux préréglages livrés n'en lèvent aucune ; jeu minimal avec
  les défauts : 0,06 m (visée `(±5,00 ; 6,00 ; 2,90)` d'un mobile de face,
  corps d'un PC de la première perche).
- Limites : le cône est celui du champ de la fiche, sans les lames d'une
  découpe ni le gobo ; seuls les appareils sont des obstacles, pas les
  tubes, le cadre ni les pylônes.

## 14. Appareils dans Blender

`rigbuild.py` traduit le plan de la section 13 en objets. Il ne calcule
aucune cote. Les règles de `build.py` s'appliquent : objets marqués
`theatre_generated`, reconstruction qui ne supprime que ces objets,
matériaux cherchés par nom.

### 14.1 Collections et noms

- `Theatre_Rig` : `FrontPipe`, `FrontPipe_02` (si les mobiles de face sont
  posés), `Tower_L_NN` / `Tower_R_NN`,
  `TowerArm_L_NN_MM` / `TowerArm_R_NN_MM` (`NN` = pylône, `MM` = mobile, du haut
  vers le bas). Matériaux `TS_Batten` (tubes) et `TS_Truss`.
- `Theatre_Fixtures` : une hiérarchie par appareil, nommée d'après la racine.
  Racines : `Backlight_NN`, `FrontMover_NN`, `TowerMover_L_NN` /
  `TowerMover_R_NN`, `FrontPC_L_NN` / `FrontPC_R_NN`, `Profile_L` /
  `Profile_C` / `Profile_R`, `Hazer_01`.
- Les deux collections sont des sous-collections de `Theatre` (section 7).
  `NN` suit l'ordre propre à chaque famille (section 13), pas la profondeur
  de 1 : jardin vers cour pour le contre et les mobiles de face.
- Les données de maillage importées d'une fiche s'appellent
  `TSF_<id>_<pièce>` (`base`, `yoke`, `head`). Comme les matériaux, elles sont
  cherchées par nom et réutilisées, jamais écrasées ni supprimées à la
  reconstruction (utilisateur fictif posé). Les appareils d'un même modèle
  partagent donc leurs maillages.

### 14.2 Hiérarchie et repères

```
<Racine>                    empty ; propriétés de configuration ; rotation (180°, 0, 0)
  <Racine>_Base             maillage fixe
  <Racine>_Pan              maillage (étrier) ; rotation Z = pan
    <Racine>_Tilt           maillage (tête) ; origine sur l'axe de tilt ; rotation X = −tilt
      <Racine>_Light        lumière (14.3)
      <Racine>_Lens         disque de verre
      <Racine>_Blades       empty ; rotation Z = blade_rot
        <Racine>_Blade_K_Pivot    empty ; rotation Z fixe = side_k   (K = 1 à 4)
          <Racine>_Blade_K        plan
```

- Racine : position `(X, Y, Zh − hook_height)`, repère du corps de 13.9.
  `_Pan` à l'origine de la racine ; `_Tilt` à `(0, 0, tilt_axis_height)` dans
  `_Pan`. Dans le repère de la tête, le faisceau suit `+Z`, la lentille est à
  `z = lens_offset`.
- Un appareil sans lames n'a pas `_Blades`. Un appareil `static` a les mêmes
  pièces : `_Pan` et `_Tilt` portent les rotations fixes de 13.9. Le hazer n'a
  que sa racine (axes simples), posée à `(−(Wk/2 − 0,50), D − 0,50, Hp)`
  *(choix)*.
- **Propriétés de configuration, sur la racine** (jamais sur la lumière ou
  ses données : un driver de données qui lit une propriété de son propre objet
  gèle, cycle objet-données) : `theatre_generated`, `theatre_fixture`,
  `theatre_family`, `theatre_circuit`, `theatre_mode`, `max_energy` (W),
  `field_min`, `field_max`, `beam_min`, `beam_max`, `field_angle` (champ
  retenu), `pan_min`, `pan_max`, `tilt_min`, `tilt_max`, `cct_min`, `cct_max`,
  `cto_r`, `cto_g`, `cto_b`, `blade_open`, `blade_closed`, `blade_half_span`,
  `blade_rot_min`, `blade_rot_max`, `pan_invert`, `tilt_invert`, `blade_rot_invert`
  (0 ou 1), `iris_min_ratio`, ainsi que `zoom_invert` (0 ou 1),
  `blade_angle_limit`, `theatre_universe` et `theatre_address`. Trois valeurs
  **pilotées** par des drivers qui ne lisent que la scène partagent leur
  calcul entre plusieurs drivers : `level` (`dimmer · obturateur`, 14.7),
  `field_now` et `beam_now` (champ et faisceau courants, 14.7). Une expression
  de driver est limitée à 255 caractères : ces valeurs la tiennent.
- Les drivers lisent la **scène** (`dmx_<u>_<c>`) et la **racine** (réglages
  ci-dessus) ; les objets ne se lisent jamais eux-mêmes.

### 14.3 Source de lumière

`_Light`, enfant de `_Tilt`, `use_shadow` actif. `r = lens_diameter/2`.

- **Profil** (`beam_type: profile`) : lumière `SPOT` quasi ponctuelle
  (`shadow_soft_size = 0`, `spot_blend = 0,02` *(choix)*), **en retrait
  derrière la lentille** pour que le cône passe par le bord de la lentille :
  position `z = lens_offset − d`, `d = r / tan(F_ref/2)`, direction `+Z` de la
  tête (rotation de 180° autour de X de la lumière, dont l'axe de tir est
  `−Z`). `F_ref` : le `field_angle` du tube pour une lentille fixe, `field_angle.max` pour un
  zoom. `spot_size` = champ courant `F` (constante ou piloté par `zoom`).
  Faisceau net aux lames, aucune ombre du corps de l'appareil.
- **Wash et PC** (`beam_type: wash`) : lumière `AREA`, forme `DISK`, `size =
  lens_diameter`, placée dans le plan de la lentille (`z = lens_offset`),
  `spread` = angle de faisceau courant (constant ou piloté par `zoom`),
  même rotation de 180° autour de X.
- `_Lens` : disque de verre `TS_Lens` dans le plan de la lentille, tiré de
  0,005 vers l'avant. Il ne projette pas d'ombre, de même que `_Base`, `_Pan`
  et `_Tilt` *(choix)* : l'approximation de la source n'a pas à être ombrée
  par un corps qui l'entoure.

### 14.4 Lames

Quatre plans opaques `_Blade_K` devant la source, **invisibles pour la
caméra, ombrage actif** (visibilité de rayon : caméra décochée, ombre cochée).
Chaque plan : bord en `x = 0`, étendue `x ∈ [0, 2·lens_diameter]` vers
l'extérieur, `y ∈ [−E, E]` avec `E = max(span/2, 1,5·r)`, `TS_Blade` noir.

Placement : plan des lames à `z = z_S + g`, avec `z_S` la position de la
source sur l'axe et `g` de 13.8 (pour une lentille fixe) ; pour un zoom, `g`
est calculé avec `F_ref`. `_Blade_K` : `location.x = h_c`, `rotation.z = α`
(13.8). Appareil `manual` : valeurs constantes calculées en 13.8. Appareil
`motorised` : drivers de 14.7 ; le zoom ne déplace pas les lames
*(choix : la coupe reste calée sur la position du plan, ce qui n'est exact
qu'à `F_ref`)*.

### 14.5 Gobos, iris, couleur en Cycles

Arbre de nœuds de la lumière, **construit seulement** si la fiche déclare
un gobo, un iris ou `cct`. EEVEE ne le lit pas.

- Direction : `Texture Coordinate > Normal`, `n`. Plan de projection
  `p = (n_x, n_y) / (−n_z) / tan(F/2)` : le disque unité est le bord du champ.
  Nœud `Value` `FieldTan` piloté à `tan(F/2)`. *Le sens de `Normal` pour les
  lumières spot et surfaciques est à confirmer au premier rendu (11).*
- Gobo : rotation de `p` par `β = gobo1_rot`, coordonnées image
  `0,5 + 0,5·p`, une `Image Texture` par fente (`CLIP`, linéaire, images de
  `gobos/`). Chaque roue (`gobo1`, `gobo2`) est un **groupe de nœuds**
  `TSN_<id>_<roue>` (entrées `Vector`, `Angle`, `Byte`, sortie `Color`), créé
  une fois et réutilisé : somme des `Compare(octet, milieu_k, demi-largeur_k)·
  texture_k`, l'octet étant borné à la dernière fente. Fente sans image : 1.
  Le nœud de groupe de la lumière porte le nom de la roue ; ses entrées `Byte`
  (`round(255·v)`) et `Angle` sont pilotées. Un profil IES est un texte interne
  `TSF_<id>_<fichier>.ies`, relu une fois ; sa valeur est normalisée sur l'axe
  (14.8).
- Iris : `Value` `IrisRadius = 1 − v·(1 − iris_min_ratio)` ; masque
  `Less Than(|p|, rayon)`.
- Couleur blanche variable : nœud `Blackbody` de température `K` (attribut
  `cct`).
- `Emission` : couleur = `Blackbody × gobo × masque d'iris`, force 1. La
  puissance reste portée par `Light.energy` et la couleur RVB par
  `Light.color`.

### 14.6 Matériaux

Créés seulement s'ils n'existent pas, comme en section 6 ; le choix de
l'utilisateur sur une catégorie s'applique aux appareils comme au reste
(6.1).

### 14.7 Drivers

Lecture d'un canal `a` : `v8 = c` ; `v16 = (256·c + f)/257` (12.4), `c` et
`f` étant les variables « propriété unique » de type Scène, chemin
`["dmx_<u>_<c>"]`. Un attribut absent du mode donne la valeur neutre de la
colonne « Sans canal ».

| Donnée portée | Propriété | Valeur | Sans canal |
|---|---|---|---|
| `_Pan` (objet) | `rotation_euler[2]` | `radians(pan_min + v_pan·(pan_max − pan_min))` | angle fixe 13.9 |
| `_Tilt` (objet) | `rotation_euler[0]` | `−radians(tilt_min + v_tilt·(tilt_max − tilt_min))` | angle fixe 13.9 |
| `_Light` (lumière) | `energy` | `max_energy · v_dimmer · shut` | `max_energy` |
| `_Light` (lumière) | `color[0..2]` | couleur RVB ci-dessous | blanc |
| `_Light` (lumière) | `spot_size` (profil) ou `spread` (wash) | `radians(F(z))` ou `radians(B(z))` | `field_angle` ou `beam` retenu |
| `_Blades` (objet) | `rotation_euler[2]` | `radians(blade_rot_min + v_rot·(blade_rot_max − blade_rot_min))` | 0 |
| `_Blade_K` (objet) | `location[0]` | `(h_A + h_B)/2` | `h_c` fixe |
| `_Blade_K` (objet) | `rotation_euler[2]` | `atan((h_A − h_B)/(2·blade_half_span))` | `α` fixe |
| arbre de nœuds de la lumière | `Blackbody`, `GoboIndex`, `gobo1_rot`, `IrisRadius`, `FieldTan` | formules de 14.5 | constantes |
| `Haze_Volume` (matériau) | densité | section 15.4 | |

- Pour `pan`, `tilt` et `blade_rot`, `v` est remplacé par `1 − v` quand l'axe est
  `invert` (`pan_invert`, `tilt_invert`, `blade_rot_invert` de la racine).
- `z = v_zoom` (ou `1 − v_zoom` si `zoom_invert`), `F(z) = field_min +
  z·(field_max − field_min)`, `B(z)` pareil sur `beam_min` / `beam_max`.
- `h_A = open_eff + v_ka·(closed − open_eff)`, `h_B` pareil avec `v_kb`.
- **Obturateur** `shut` : `B = round(255·v_strobe)`. Dans `strobe.open` ou
  `strobe.closed` de la fiche : 1 ou 0. Dans `strobe.strobe` : fréquence
  `f = hz_min + (B − from)/(to − from)·(hz_max − hz_min)`, `shut = 1` si
  `fmod(t·f, 1) < 0,5`, sinon 0, avec `t = frame / fps` (`fps` : variable
  `render.fps` de la scène). Le stroboscope ne bat que si la timeline avance.
  Sans attribut `strobe` : 1.
- **Couleur RVB** de `_Light` (valeurs bornées à 1) :
  - `rgbw` : `r = color_r + color_w`, idem `g`, `b` ;
  - `cmy` : `r = 1 − cyan`, `g = 1 − magenta`, `b = 1 − yellow` ;
  - `emitters` : `r = Σ emitter_N · rgb_N[0]`, idem `g`, `b` ;
  - `cto` : chaque composante multipliée par `1 − cto + cto·cto_c` (`cto_r`,
    `cto_g`, `cto_b` = `cct_to_rgb(cto_kelvin)`) ;
  - `cct` seul (blanc variable) : `Light.color` blanc, la température passe
    par le nœud `Blackbody` (Cycles). En EEVEE, la température n'est pas
    rendue.
- Les drivers de nœuds sont portés par l'arbre de nœuds de la lumière : ce
  n'est pas l'objet, donc pas de cycle avec la racine.
- `level = dimmer · shut` et, si le mode a `zoom`, `field_now = F(z)` et
  `beam_now = B(z)` sont des propriétés de la racine pilotées par la scène (les
  constantes de la fiche y sont écrites en clair). `Light.energy` vaut
  `max_energy · level`, `spot_size` ou `spread` lit `field_now` ou `beam_now`.
  Pour un spot à zoom, `energy` est multipliée par `(1 − cos(F_retenu/2)) /
  (1 − cos(F/2))` : le flux reste constant quand le champ se resserre.
- Un octet de strobe hors des plages `closed` et `strobe` de la fiche laisse
  l'obturateur ouvert. Un mode qui a des lames motorisées et `blade_K_rot` lit
  l'inclinaison de la lame K sur ce canal (`angle_limit·(1 − 2v)`) et n'utilise
  `blade_Ka` que pour l'insertion.
- Les lentilles partagent le seul `TS_Lens` : son émission lit les propriétés
  `lens_level`, `lens_rgb` et `lens_kelvin` de l'objet `_Lens` (nœuds `Attribute`
  de type objet), que des drivers pilotent comme la lumière. Un mode qui a `cct`
  et des canaux RVB à zéro par défaut ajoute le RVB au blanc, normalisé à 1.

### 14.8 Lumens vers puissance Blender

Étalonnage fait **une fois, dans Cycles**, constantes définies dans
`core/fixtures.py` (aucune valeur par appareil) :

- profil : `Ω = 2π·(1 − cos(F/2))`, `I = flux / Ω` (cd),
  `max_energy = EXPOSURE_GAIN · W_PER_CD_SPOT · I`. La puissance d'un spot
  Blender ne se concentre pas avec le cône : le champ choisi intervient donc
  par `Ω`.
- wash et PC : `max_energy = EXPOSURE_GAIN · W_PER_LM_AREA · flux` ; le
  resserrement de `spread` concentre alors la lumière à flux constant.
- Un profil IES multiplie la force d'émission de la lumière : Cycles rend
  `IES_FAC_PER_CD · candela` sur l'axe, soit des milliers de fois la valeur
  sans IES. Le nœud `Math` (multiplication) placé après la texture IES
  divise donc par `IES_FAC_PER_CD · ies_axis_candela(fichier)` : l'axe vaut 1,
  comme sans IES, et le fichier ne donne que la **forme** du faisceau.
- **Constantes étalonnées** (Cycles 5.3) : `W_PER_CD_SPOT = 4π²/683`,
  `W_PER_LM_AREA = 0,366·π/683`, `IES_FAC_PER_CD = 0,0705`,
  `EXPOSURE_GAIN = 1`. Définition du niveau : sur un plan diffus d'albédo
  `ρ`, la valeur linéaire du pixel vaut `ρ · E / 683 · EXPOSURE_GAIN`
  (`E` en lux), **vue « Standard », exposition 0**.
- **Protocole** : scène temporaire (supprimée ensuite), plan diffus
  d'albédo 0,8 perpendiculaire à l'axe, monde noir, ombres coupées, lumières
  invisibles de la caméra, caméra orthographique de 0,2 m sur le centre
  (16 × 16 px), Cycles 64 à 256 échantillons sans débruitage. Attendu :
  `E = I·cos θ / d²`, avec `I = flux / Ω(champ)` pour un profil et
  `I = flux / Ω(spread)` pour un wash ou un PC (disque plat équivalent).
- **Mesures**, `d` = 5 m sauf mention, rapport mesuré / attendu :

  | Source | Rapport |
  |---|---|
  | spot sans IES, Esprite 27 000 lm, champ 27,75° | 1,000 ; 1,000 à 30° d'incidence ; 1,000 à 10 m |
  | spot sans IES, Source Four tube 70, 10 889 lm, champ 72,5° | 1,000 |
  | surfacique sans IES, MAC Aura 3 850 lm, spread 25,3° | 0,994 ; 0,998 à 30° |
  | surfacique sans IES, PC 9 566 lm, spread 29,75° | 1,006 ; 1,047 à 10 m |
  | spot avec IES, Source Four tube 26, 10 889 lm, champ 28,7° | 1,001 |
  | surfacique avec IES, PC zoom 0, 9 566 lm, spread 29,75° | 1,004 ; 1,008 à 30° |

  Un spot de 1 000 W de champ 30° donne 0,810 à 5 m (`4π²/683` exact). Un
  disque surfacique concentre sa lumière sur un angle solide équivalent de
  `0,36 · Ω(spread)` entre 20° et 60° (0,430 à 10°, 0,374 à 90°, `π` à 180°,
  Lambert) : d'où le 0,366. En dessous (spread de 10°), le wash mesure 15 %
  trop sombre, 40 % à 5°.
- Seule la photométrie **relative** des fiches est garantie ; `EXPOSURE_GAIN`
  et l'exposition de la scène règlent le niveau absolu.
- **Niveau par défaut** : `EXPOSURE_GAIN = 1`, exposition de scène 0 EV (AgX).
  Préréglage `reference_with_modules` en plein feu de repos, rendu Cycles
  depuis `Cam_Face` : valeur affichée moyenne 0,23, visage 0,58, aucun pixel
  proche du blanc ; avec brume (densité 0,02), moyenne 0,24 et faisceaux
  lisibles. En vue « Standard », 0,16 % des pixels saturent (les lentilles
  des appareils vus de face), 0,14 % avec brume. Aucun réglage d'exposition
  n'est donc posé par l'extension.

## 15. Patch DMX, repos et brume

### 15.1 Patch

**Le patch vit dans les paramètres de l'extension** (`patch`) : une
reconstruction recrée les objets, un patch saisi ailleurs serait perdu.

- Ordre des familles, et des appareils dans chaque famille :
  1. `backlight` : `Backlight_01` … `NN`.
  2. `front_movers` : `FrontMover_01` … `NN`.
  3. `tower_movers` : `TowerMover_L_01` …, puis `TowerMover_R_01` ….
  4. `front_pc` : par rang `j`, par direction (`L` puis `R`), par colonne `i`.
     Chaque circuit est donc contigu.
  5. `profiles` : `Profile_L`, `Profile_C`, `Profile_R`.
  6. `hazer` : `Hazer_01`, seulement si `haze.dmx_driven`.
  Une famille désactivée (`enabled` décoché, `count` ou `movers` nuls) n'a
  aucun appareil ni patch.
- **Adresses** : le premier appareil d'une famille prend
  `<famille>_universe` / `<famille>_address` ; chaque suivant, l'adresse du
  précédent plus l'empreinte (`footprint`) du **mode choisi** de la famille.
  Le canal absolu de l'offset `o` d'un appareil à l'adresse `a` est `a + o − 1`
  (un canal 16 bits occupe `offset` et `fine`). Propriété de scène
  correspondante : `dmx_<univers>_<canal>`.
- **Circuits** : un par découpe, un par (rang, direction) de PC de face
  (13.7). Un circuit est un groupe nommé (propriété `theatre_circuit` des
  racines ; groupes de fixtures de l'export QLC+). Les familles de mobiles
  forment aussi chacune un groupe : `Backlight`, `FrontMovers`,
  `TowerMovers_L`, `TowerMovers_R` *(choix)*.
- **Alertes** : recouvrement (« Patch : X et Y se recouvrent, univers u,
  canaux a à b ») entre deux appareils de n'importe quelles familles ;
  dépassement (« Patch : l'univers u dépasse 512 canaux ») quand
  `adresse + empreinte − 1 > 512`. Au-delà de huit recouvrements, une dernière
  alerte donne le nombre des autres.
- « Cotes calculées » : plage `univers : première – dernière adresse` par
  famille, et la liste des appareils avec leur adresse.

### 15.2 Valeurs de repos et « Plein feu de repos »

Sans console, la scène doit déjà éclairer. **Valeurs de repos** (`core/rig.py`)
par appareil patché et par canal, en valeur normalisée puis écrite selon
12.4 :

| Attribut | Valeur de repos |
|---|---|
| `dimmer` | `pc_level` (PC de face), `profile_level` (découpes), `mover_level` (mobiles et contre), `haze_level` pour `haze_density` |
| `pan`, `tilt` | angles de 13.9 pour la visée de repos, convertis en valeur normalisée |
| `cct` | `K` de `rest.cct_left` / `cct_right` (PC par direction) ou `cct_profile` (découpes), converti sur `colour.cct_range` ; hors plage : ramené et signalé |
| `color_r/g/b/w`, `cyan/magenta/yellow`, `emitter_N` | couleur de `cct_to_rgb(K)` pour les PC et les découpes, **seulement si le mode n'a pas de canal `cct`** : `rgbw` → `(r, g, b)`, `w = 0` ; `cmy` → `(1 − r, 1 − g, 1 − b)` ; `emitters` → poids dans [0, 1] des émetteurs dont le mélange approche `(r, g, b)` (moindres carrés non négatifs) ; mobiles : valeur par défaut de la fiche |
| `zoom` | PC de face dont le mode a `zoom` : la valeur qui donne le champ `F` de 13.7 ; sinon défaut |
| `blade_Ka/Kb`, `blade_rot` | découpe à lames motorisées : insertions et rotation calculées en 13.8 ; sinon défaut |
| tous les autres | valeur par défaut du canal dans la fiche |

`cct_to_rgb(K)` (dans `core/fixtures.py`) : couleur d'un corps noir,
normalisée à `max = 1`, linéaire (approximation de Kim et al. du lieu de
Planck, valable de 1667 à 25000 K, `K` ramené dans cette plage).

- **À la reconstruction** : pour chaque canal patché, la propriété de scène
  `dmx_<u>_<c>` est **créée si elle est absente**, à la valeur de repos ;
  une propriété existante n'est jamais modifiée. Les propriétés d'un ancien
  patch restent en place, sans effet. La scène est marquée (`scene.update_tag()`
  puis `view_layer.update()`).
- **Bouton « Plein feu de repos »** (`theatre.rest_full`) : réécrit **toutes**
  les propriétés des canaux patchés à leur valeur de repos, avec le même
  marquage de la scène. Tant que le pont tourne et reçoit l'univers, il réécrit
  les propriétés à chaque tick : **la console l'emporte**.
- **Bouton « Noir général »** (`theatre.blackout`) : met à 0 **toutes** les
  propriétés de scène `dmx_<u>_<c>` (patchées ou non), avec le même marquage de
  la scène, pour que la console éclaire seule. Un pont en marche réécrit les
  canaux qu'il reçoit : **la console l'emporte** aussi.
- Les autres attributs d'un mode (gobo, iris, lames des mobiles…) restent à leur
  valeur par défaut de la fiche : lames dégagées, iris ouvert.

### 15.3 Pont DMX Visualizer

Le contrat se réduit aux **noms de propriétés** : l'extension n'importe
jamais DMX Visualizer. Le pont (module `dmx_visualizer`, dépôt séparé) écoute
plusieurs univers et écrit `dmx_<u>_<c>`, valeur = `octet/255`.

- Si `bpy.types.Object` possède `dmx_patch`, l'extension remplit
  `obj.dmx_patch.universe` et `obj.dmx_patch.address` sur la racine de chaque
  appareil patché, pour que le panneau de patch de DMX Visualizer les liste.
  Sinon, rien. Aucune autre propriété de `dmx_patch` n'est touchée.
- Rien n'est image clé dans la timeline : Blender n'est qu'un visualiseur.
- Pièges rappelés pour l'implémentation : écrire une propriété de scène ne
  marque pas le graphe de dépendances (`scene.update_tag()` puis
  `view_layer.update()`) ; la vérification d'un driver se fait par un rendu
  vers un fichier, pas par `evaluated_get` ; les objets doivent être dans une
  collection de la couche de vue active.

### 15.4 Brume pilotée par le hazer

Paramètres `haze.dmx_driven`, `haze.fixture`, `haze.mode` (8.6). Le volume
reste `Haze_Volume`.

- `dmx_driven` décoché : comportement de 8.6, inchangé.
- Coché : un `Hazer_01` est créé et patché (famille `hazer`) ; la densité
  effective du volume est `haze.density · v_haze`, `v_haze` étant la valeur
  normalisée de son canal `haze_density`. Les drivers existants de la densité
  (lus sur la scène) reçoivent ce facteur ; l'animation de `haze.density`
  continue de fonctionner. Valeur de repos : `rest.haze_level` (1 : la
  densité réglée dans le panneau).
- Alerte « Brume DMX Visualizer (World, `DMX_Haze`) active : la brume serait
  comptée deux fois » si le monde de la scène a un nœud Volume Scatter nommé
  `DMX_Haze` en amont de l'entrée Volume de la sortie du monde, tant que la
  brume du théâtre est active (`Haze_Volume` présent ou hazer DMX). Calculée à
  la reconstruction (`rigbuild.warnings`) ; le dessin du panneau ne lit que la
  valeur Python.
- Le driver de densité de `TS_Haze` est remplacé à chaque reconstruction :
  `var` sans hazer, `var · c` (8 bits) ou `var · (256·c + f)/257` (16 bits)
  avec lui, `c` et `f` étant les propriétés de scène du canal du hazer.

## 16. Export QLC+

Un opérateur du panneau (« Exporter QLC+ », `theatre.export_qlc`) écrit un
espace de travail QLC+ qui reprend le patch : **une seule table de canaux**
pour Blender et pour la console. `core/qlc.py` produit le texte XML ; il ne
dépend ni de Blender ni d'une installation de QLC+. QLC+ est installé dans
`C:\QLC+` (définitions de fixtures annoncées en 4.13.1).

### 16.1 Fichiers écrits

Dans le dossier choisi dans le sélecteur de l'opérateur (`theatre.export_qlc`),
écrasés à chaque export, jamais dans `C:\QLC+` :

- `theatre_rig.qxw` ;
- `<Fabricant>-<Modèle>.qxf` **à côté du `.qxw`** pour chaque fiche utilisée
  sans définition QLC+ vérifiée (16.4) : Esprite, PC, Source Four, hazer.
  Les espaces du fabricant et du modèle deviennent des `-`.

Pour un appareil inconnu de son cache, QLC+ cherche `<dossier du .qxw>/<Fabricant>-<Modèle>.qxf`
(`Fixture::loadXML`, présent dans le moteur 4.14.3 installé) : **aucune copie
n'est nécessaire**, il suffit de garder les `.qxf` à côté du `.qxw`. Pour les
réutiliser dans d'autres projets, les copier dans le dossier de l'utilisateur,
`%USERPROFILE%\QLC+\Fixtures` (dossier plat, vérifié sur la machine). Le panneau
affiche le dossier d'export, les fichiers écrits ou réutilisés et les alertes
du dernier export.

Contrat de `core/qlc.py` (aucune dépendance à Blender) :

- `PatchedFixture(name, fixture_id, mode, universe, address, group, pan_tilt=None,
  rest_bytes=())` : univers et adresse **à base 1** (15.1) ; `pan_tilt` =
  `(pan gros, pan fin, tilt gros, tilt fin)`, octets de 13.9 ; `rest_bytes` =
  couples `(offset, octet)` des autres canaux au repos (15.2), offsets à base 1.
- `patched_from_rig(rig) -> tuple[PatchedFixture, ...]` : un `PatchedFixture` par
  `RigFixture` dans l'ordre du patch ; `group` = circuit, `pan_tilt` = octets
  de pan et tilt des mobiles (fin à 0 en 8 bits), `rest_bytes` = octets de
  repos des autres canaux, offset relatif à l'adresse
  (`canal − adresse + 1`), octet = valeur codée de 12.4. L'opérateur
  d'export appelle exactement cette fonction.
- `export_workspace(patched, library, out_dir, qlc_fixture_dirs=()) ->
  ExportResult(workspace, written_qxf, reused_qxf, warnings)` : écrit les
  fichiers ; `warnings` en français (appareil ou fiche ignoré, recouvrement,
  hors limites, définition QLC+ non réutilisable).
- `workspace_xml(patched, library, qlc_fixture_dirs=())` et
  `fixture_definition_xml(fixture, model=None)` rendent le texte, sans écrire.
- Sortie déterministe : ordre du patch, pas d'horodatage, fins de ligne LF.

### 16.2 Contenu du `.qxw`

Squelette et conventions du fichier de projet QLC+ (adresses et indices de
canal à base 0, univers `ID = u − 1`), vérifiés dans les sources de QLC+
(`app.cpp`, `doc.cpp`, `fixture.cpp`, `fixturegroup.cpp`, `qlcpalette.cpp`,
`scene.cpp`) et par un chargement du fichier dans `qlcplus.exe` 4.14.3 :

- Prologue `<!DOCTYPE Workspace>` (le chargeur le contrôle) ; `Creator` :
  `Q Light Controller Plus`, auteur `theatre_stage`.
- `InputOutputMap` : un `Universe` de 1 jusqu'au plus grand univers patché
  (sans trou : QLC+ comble les trous sans nom), `Name="Univers u"`, sans
  plugin de sortie (l'utilisateur règle E1.31 / sACN dans QLC+).
- Un `Fixture` par appareil patché : `Manufacturer`, `Model`, `Mode`
  (définition QLC+ ou `.qxf` exporté), `ID` de 0 à n dans l'ordre du patch
  (15.1), `Name` = nom de la racine, `Universe = u − 1`, `Address = a − 1`,
  `Channels = footprint`. Un appareil hors de 1–512, recouvrant un autre, ou
  dont la fiche ou le mode manque, n'est pas écrit (QLC+ le déplacerait ou le
  refuserait sans le dire) et donne une alerte.
- Un `FixtureGroup ID="g"` par circuit et par famille de mobiles (15.1), le
  nom dans un **élément** `<Name>` : `Size X="n" Y="1"`, un
  `Head X="i" Y="0" Fixture="id"` par appareil, contenu `0` (indice de tête).
- Deux scènes (`Function Type="Scene"`) : `Repos - positions` (pan, pan fin,
  tilt, tilt fin de chaque mobile, octets de 12.4) et `Repos - plein feu`
  (tous les canaux de `rest_bytes`, pan et tilt compris). Une scène sans
  contenu n'est pas écrite. Format `FixtureVal ID="f"` : paires
  `indice,valeur`, indices triés.
- **Palettes de position** : un élément `<Palette ID="p" Type="PanTilt"
  Name="Repos_<racine>" Value="pan,tilt"/>` par mobile, enfant de `Engine`
  après les groupes (`qlcpalette.cpp`, `Doc::saveXML`). **`Value` est en degrés
  entiers depuis le zéro DMX** (`Fixture::positionToValues` : `DMX = degrés ·
  65535 / PanMax`, `PanMax` et `TiltMax` du bloc `Focus` de la définition ;
  360 et 270 si 0), et non en entiers 16 bits : `Value="422,91"`, jamais
  `51217,25855`. Précision limitée au demi-degré : la scène `Repos - positions`
  reste la référence exacte, les palettes rappellent un appareil seul
  *(choix)*. L'inversion d'un axe (`invert`, 12.2) n'entre **pas** dans la
  conversion : QLC+ envoie `degrés · 65535 / course` sans connaître l'inversion,
  la valeur « depuis le zéro DMX » rend donc exactement les octets de la scène. Le moteur 4.14.3 les charge et les réécrit ; seule l'interface
  QML (QLC+ 5) les expose, l'interface classique 4.x les conserve sans les
  afficher.
- `VirtualConsole` : cadre racine vide, `SimpleDesk` vide.

### 16.3 `.qxf` écrit depuis la fiche

Un `.qxf` par fiche (tous ses modes), structure des définitions de QLC+ :
`Creator`, `Manufacturer`, `Model`, `Type`, des `Channel`, un `Mode` par mode
de la fiche, `Physical`.

- `Type` : `Moving Head` (familles `moving_*`), `Color Changer` (`pc`,
  `profile`), `Hazer` (`hazer` ; `Smoke` existe aussi mais `Hazer` est le type
  propre de QLC+).
- `Channel` : un par offset ; un canal 16 bits donne deux canaux QLC+
  (`<Nom>` et `<Nom> fin`). Noms en français, uniques dans un mode (un canal
  ne peut figurer deux fois dans un mode) ; un nom déjà pris avec un autre
  contenu reçoit un numéro. Préréglages QLC+ : `IntensityDimmer`,
  `IntensityRed/Green/Blue/White`, `IntensityCyan/Magenta/Yellow`,
  `PositionPan`, `PositionTilt` (et leurs `…Fine`), `BeamZoomSmallBig`
  (`BeamZoomBigSmall` si `zoom_invert`) et `BeamZoomFine`,
  `ShutterIrisMaxToMin`, `GoboIndex` (`gobo1_rot` et `gobo2_rot`),
  `ColorCTOMixer`. Les autres canaux sont
  écrits sans préréglage dans leur groupe QLC+ (`cct`, `emitter_N` : `Colour` ;
  `strobe` : `Shutter` ; `gobo1/2` : `Gobo` ; lames, `blade_K_rot`
  (« Pivotement lame K ») et `blade_rot` : `Beam` ; hazer :
  `Effect` ; attribut inconnu : `Nothing`, capacité unique `0–255` nommée
  d'après l'attribut). Un émetteur n'est **jamais** dans le groupe
  `Intensity` : un canal d'intensité sans couleur y serait pris pour le
  gradateur général de l'appareil.
- Capacités : `strobe` reprend `open` (`ShutterOpen`), `closed`
  (`ShutterClose`) et la rampe (`StrobeFreqRange`, `Res1`/`Res2` = Hz) ; une
  roue de gobos donne une capacité par fente ; les trous de 0–255 sont comblés
  par « Inutilisé » (QLC+ refuse les capacités qui se recouvrent). Les courbes
  de canal ne sont pas exportées.
- `Mode` : `Channel Number="n"` pour **tous** les offsets de 0 à
  `footprint − 1` ; un offset que la fiche ne décrit pas reçoit un canal
  `Inutilisé <offset>` (préréglage `NoFunction`), car l'adresse et le nombre
  de canaux de QLC+ viennent du mode. **Pas d'élément `Head`** : sans lui QLC+
  crée une tête qui porte tous les canaux et reconnaît le gradateur général
  (`Fixture::setFixtureDefinition`) ; avec un `Head` explicite il ne le
  reconnaît plus.
- `Physical` : `Bulb` (`Lumens` = `optics.flux`), `Dimensions` (`Weight` en
  kg ; `Width`, `Height`, `Depth` en mm d'après `physical.dimensions`),
  `Lens` (`DegreesMin`, `DegreesMax` d'après `field_angle`, ou les tubes),
  `Focus` (`PanMax` = `pan.max − pan.min`, `TiltMax` de même : QLC+ compte
  depuis le zéro DMX), `Technical`.

### 16.4 MAC Aura : contrôle contre QLC+

QLC+ fournit `C:\QLC+\Fixtures\Martin\Martin-MAC-Aura.qxf` : mode `Standard`
(14 canaux : obturateur, dimmer, zoom, pan et pan fin, tilt et tilt fin,
contrôle, roue de couleurs, R, V, B, W, CTC) et mode `Extended` (25 canaux,
avec les effets et le second tête « Aura »).

`tools/check_qlc_fixture.py <fixture.yaml> <définition.qxf>` compare, mode
par mode : nombre de canaux, ordre, correspondance attribut ↔ canal QLC+
(préréglage ou nom), paires gros/fin consécutives pour les 16 bits. Si un
mode de la fiche `martin_mac_aura` coïncide avec `Standard` (ou `Extended`),
la fiche reçoit `qlc: {manufacturer: Martin, model: MAC Aura, modes:
{<mode de la fiche>: Standard}, verified: <date>}` : l'export n'écrit pas de
`.qxf` pour cette fiche et le `.qxw` cite la définition de QLC+. Sinon, ou
sans clé `qlc`, l'export écrit son propre `.qxf` ; il n'emploie jamais une
définition de QLC+ qui n'a pas été vérifiée. Le patch par défaut de la
famille `backlight` utilise le mode de la fiche qui correspond à `Standard`
*(choix)*.

L'export (`qlc_fixture_dirs` : `C:\QLC+\Fixtures`, puis `%USERPROFILE%\QLC+\Fixtures`)
cherche la définition dans `<dossier>/<Fabricant_X>/<Fabricant-X>-<Modèle>.qxf`
puis à plat, et la réutilise si la fiche a `qlc.verified`, si son mode figure
dans `qlc.modes`, si la définition contient ce mode avec le même nombre de
canaux ; sinon alerte et `.qxf` généré. Dans ce dernier cas, si QLC+ possède
une définition de même fabricant et de même modèle, le modèle exporté est
suffixé « (theatre_stage) » : QLC+ ignore une définition en double et ne
retrouverait pas le mode de la fiche. Contrôle fait sur
`C:\QLC+\Fixtures\Martin\Martin-MAC-Aura.qxf` : `Standard` 14 canaux,
`Extended` 25, `Focus PanMax="539" TiltMax="231"`.

## 17. Hors périmètre v1

Voir `BACKLOG.md`.
