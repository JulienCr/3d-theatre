# Scène de théâtre paramétrique — spécification

Extension Blender 5.3 qui génère une maquette de scénographie à l'échelle 1:1 :
plateau, enceinte, cadre, cage de scène, gril, escaliers, modules latéraux,
pendrillonnage, rideaux, lumières de travail et caméras vue public. Toute la
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
  props.py                   PropertyGroup généré depuis le schéma
  build.py                   cotes -> objets, matériaux, lumières, caméras
  ui.py                      panneau « Théâtre » dans la barre latérale 3D
  presets/                   préréglages livrés (YAML)
tests/                       pytest, hors Blender
```

- **Une seule source de vérité.** `core/params.py` déclare chaque paramètre :
  clé anglaise, groupe, type, défaut, bornes, libellé français, info-bulle.
  La PropertyGroup, le panneau et les clés YAML en dérivent.
- **`core/` ne connaît pas Blender.** `layout.py` prend un dictionnaire de
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

`grid_height` est déduite : 7,30 (façade) − 1,20 (plateau).

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
| `side_angle` | Angle des escaliers latéraux (0° salle, 90° mur) | 90° | 0 – 90 |
| `center_width` | Largeur de l'escalier central *(choix)* | 2,00 | 0,60 – 10 |

### 3.4 Modules — `modules`

`symmetric` (défaut oui) : le panneau n'affiche qu'un jeu, appliqué aux deux
côtés en miroir. Décoché, les jeux `left` et `right` sont indépendants. Chaque
jeu :

| Clé | Libellé | Défaut | Bornes |
|---|---|---|---|
| `enabled` | Module présent | oui | |
| `wall_gap` | Écart de la charnière au mur de cage | 0,00 | 0 – 5 |
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

Largeur 1,55 = mur de cage (5,00 de l'axe) − bord intérieur des références
(3,45 de l'axe, soit l'ouverture de 6,90 m). Porte 0,94 × 2,40 du fichier de
cotes ; le plan SVG indique 1,00 × 2,40.

### 3.5 Gril — `grid`

| Clé | Libellé | Défaut | Bornes |
|---|---|---|---|
| `batten_spacing` | Espacement des porteuses *(choix)* | 1,00 | 0,20 – 5 |
| `batten_drop` | Porteuses sous le gril | 0,50 | 0 – 10 |

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

Le panneau n'affiche que les `lanes` premières cases de `borders`.

### 3.9 Rideau de scène — `curtains`

| Clé | Libellé | Défaut | Bornes |
|---|---|---|---|
| `main_enabled` | Rideau de scène (à la grecque) | oui | |
| `main_opening` | Ouverture du rideau (%) — **animable** | 100 | 0 – 100 |

`main_opening` est le seul paramètre qui **ne reconstruit pas** la scène : il
n'agit que par driver (section 8.5).

## 4. Cotes dérivées

Notations : `W` largeur plateau, `D` profondeur, `Hp` hauteur plateau,
`Hg` hauteur sous gril, `Hc` hauteur du cadre, `Tc` largeur d'un montant,
`Ys` recul de façade, `A` avant-scène.

Constantes (non exposées) : épaisseur de façade 0,30 ; profondeur du cadre
0,40, sa face avant en retrait de 0,05 derrière la façade ; épaisseur des
murs de cage 0,20 ; parement de plancher 0,03 ; liseré du nez 0,05 ;
épaisseur des parois de module 0,10 ; tube de porteuse Ø 0,048.

- Largeur de cage : `Wc = W − 2·Tc` (10,00 par défaut).
- Avant de cage : `Yc = Ys + 0,40` (1,60 par défaut). La cage s'étend de
  `Yc` à `D`.
- Zone latérale effective : `Z = max(side_zone_width, emprise escalier)`,
  l'emprise ne comptant que si au moins un escalier latéral est présent.
  **La même valeur s'applique des deux côtés** : l'enceinte reste
  symétrique.
- Largeur hors tout : `Wt = W + 2·Z`. Avec les escaliers à 0°, on retrouve
  les 14,00 m des références ; à 90°, 17,00 m.
- Escaliers : nombre de contremarches `n = ceil(Hp / riser_max)` (avec une
  tolérance de 1e-9 pour que 1,20 / 0,20 donne 6), contremarche réelle
  `Hp / n`, `n − 1` marches sous le palier, volée de longueur
  `L = (n − 1)·going`.

## 5. Géométrie

### 5.1 Salle et enceinte (matériau `TS_Enclosure`, rouge)

- Profondeur de salle dessinée : `Yh = max(A, cameras.distance + 1,00)`, pour
  que les caméras ne voient pas de vide sous elles. La salle reste un sol et
  deux murs nus (pas de gradins).
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
- Les montants couvrent le passage de la largeur du nez (`W`) à celle de la
  cage (`Wc`) : **aucun pan coupé** n'est dessiné en v1.

### 5.3 Plateau

- `Stage_Base` (`TS_StageBase`, noir) : avant-plateau `W × Yc` puis plateau de
  cage `Wc × (D − Yc)`, de Z = 0 à `Hp − 0,03`.
- `Stage_Floor` (`TS_StageFloor`, bois) : même contour, parement de 0,03,
  dessus à `Z = Hp`. Contour en un seul polygone extrudé (forme en T).
- `Stage_Front` (`TS_Enclosure`) : bandeau rouge, face avant du plateau à
  `Y = 0`, X sur `[−W/2, W/2]`, Z de 0 à `Hp − 0,05`.
- `Stage_Nosing` (`TS_Nosing`, noir) : liseré de 0,05 en haut du bandeau.

### 5.4 Cage (`TS_Cage`, noir)

- `Cage_Wall_L` / `_R` : face intérieure à `X = ∓Wc/2`, Y sur `[Yc, D]`,
  Z de `Hp` au toit.
- `Cage_Back` : face avant à `Y = D`, largeur `Wc`, mêmes hauteurs. C'est le
  « mur nu » du fond de scène.
- `Cage_Roof` : à `Hp + Hg + 2,00` (hauteur de circulation sur le gril).

### 5.5 Gril et porteuses

- `Grid_Deck` (`TS_Grid`) : caillebotis à `Z = Hp + Hg` (dessous), lattes de
  0,05 × 0,05 parallèles à Y tous les 0,15, sur toute la cage.
- Porteuses `Batten_NN` (`TS_Batten`) : tubes Ø 0,048 parallèles au nez, de
  `X = −Wc/2 + 0,10` à `Wc/2 − 0,10`, à `Z = Hp + Hg − batten_drop`.
  Première à `Yc + 0,50`, puis tous les `batten_spacing`, dernière à 0,30 au
  moins du fond. Une porteuse à moins de 0,30 en Y d'une porteuse de
  pendrillonnage ou du plan du rideau de scène est retirée (section 8). Les
  restantes sont numérotées de la face vers le fond, sans trou. Les
  projecteurs s'y accrocheront dans une version suivante (voir `BACKLOG.md`).

### 5.6 Escaliers latéraux (`TS_Stairs`)

Pour le côté `s` (−1 jardin, +1 cour), `Ws` la largeur, `θ` l'angle :

- `Stairs_Landing_L/R` : palier carré de côté `Ws`, X sur
  `s·[W/2, W/2 + Ws]`, Y sur `[Ys − Ws, Ys]`, Z de 0 à `Hp`. Adossé à la
  façade, au droit du nez.
- Direction de descente `d = (s·sin θ, −cos θ)` : 0° vers la salle, 90° vers
  le mur latéral.
- Marche `j` (1 à `n − 1`, de la plus haute à la plus basse) `Stairs_Step_L_NN` :
  boîte pleine depuis le sol, dessus à `(n − j)·Hp/n`, occupant le long de
  `d` l'intervalle `[Ws/2 + (j−1)·going, Ws/2 + j·going]` compté depuis le
  centre du palier, et `[−Ws/2, Ws/2]` en travers. Aux angles
  intermédiaires, la première marche chevauche le palier : c'est voulu, pas
  de vide.
- Emprise latérale requise, depuis le bord du plateau :
  `Ws/2 + sin θ·(Ws/2 + L) + cos θ·Ws/2` (`Ws` à 0°, `Ws + L` à 90°).

### 5.7 Escalier central (`TS_Stairs`)

`Stairs_Step_C_NN` : X sur `[−cw/2, cw/2]`, marche `j` sur Y
`[−j·going, −(j−1)·going]`, dessus à `(n − j)·Hp/n`. Il avance sur
l'avant-scène.

### 5.8 Modules (`TS_Module`)

Un module est un **caisson** : une face avant percée, plus un retour côté
plateau qui file vers le fond. Il est ouvert côté coulisses et n'a pas de
dessus.

- Charnière (arête extérieure, côté salle) :
  `H = (s·(Wc/2 − wall_gap), setback, Hp)`.
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
  `Z = Hp + Hg − 0,30`. Grille sur le plateau de cage
  (`Wc × (D − Yc)`) : `nx = max(1, round(Wc / spacing))`,
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
| `TS_Grid` / `TS_Batten` | gril, porteuses | métal sombre |
| `TS_Masking` | pendrillons, frises, rideau de fond | velours noir |
| `TS_MainCurtain` | rideau de scène | velours rouge |
| `TS_Cyclorama` | cyclorama | blanc mat |

Tous les maillages reçoivent des UV en projection boîte, **1 unité UV =
1 m**, pour que les textures BlenderKit tombent à la bonne échelle.

## 7. Régénération et panneau

- Collection racine `Theatre`, sous-collections `Theatre_Architecture`,
  `Theatre_Stairs`, `Theatre_Modules`, `Theatre_Grid`, `Theatre_Masking`,
  `Theatre_Curtains`, `Theatre_Lights`, `Theatre_Cameras`.
- Chaque objet généré porte la propriété personnalisée `theatre_generated`.
  La reconstruction supprime **uniquement** ces objets et leurs données
  orphelines, puis recrée tout. Un objet non marqué trouvé dans ces
  collections est laissé en place et signalé.
- Tout changement de paramètre reconstruit la scène (callback `update`). Un
  verrou empêche les reconstructions en cascade pendant l'application d'un
  préréglage ou de la symétrie : une seule reconstruction à la fin.
- Panneau « Théâtre » dans la barre latérale de la vue 3D : Plateau,
  Avancé (replié), Escaliers, Modules, Gril, Pendrillonnage, Rideaux,
  Lumières, Caméras, Préréglages, et un encadré **Cotes calculées** (largeur
  hors tout, largeur de cage, contremarches, nombre de porteuses) suivi des
  alertes.

## 8. Pendrillonnage et rideaux

Pendrillons, frises et rideaux sont des **surfaces plissées sans épaisseur**
(velours) : un pli tous les 0,30 m de largeur, amplitude 0,06, sauf mention
contraire. Le cyclorama est plat (toile tendue). Tous pendent sous une
porteuse de pendrillonnage, de `Z = Hp` à la hauteur des porteuses
`Zb = Hp + Hg − batten_drop`.

### 8.1 Plans en profondeur

- Rideau de scène : plan `Y = Yc + 0,15`.
- Frise de face : plan `Y = Yc + 0,35`.
- Début de zone : `Y0 = Yc + 0,50`. Si au moins un module est présent,
  `Y0 = max(Y0, Ymod + 0,20)`, avec `Ymod` le Y maximal de l'emprise des
  modules présents : **les rues reculent derrière les modules**.
- Ligne de fond `Yb` : mur nu → `D` ; rideau noir → `D − 0,40` ;
  cyclorama → `D − 1,20`.
- Fin de zone : `Y1 = Yb − 0,30`.
- Plans de pendrillonnage `k = 1..N` (`N = lanes`) à
  `Y0 + k·(Y1 − Y0)/N`. La rue `k` va du plan `k − 1` (le cadre ou les
  modules pour `k = 1`) au plan `k` ; le dernier plan masque les bords du
  fond.

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

- **À l'italienne** : `Leg_L_NN` / `Leg_R_NN` dans le plan `k`, de
  `X = ∓opening/2` jusqu'à `∓(Wc/2 − 0,10)`. Ils vont du bord de l'ouverture
  au mur de cage : pas de réglage de largeur. Ouverture plus large que la
  cage → aucun pendrillon et alerte.
- **À l'allemande** : `Leg_L` / `Leg_R` continus, parallèles à Y, à
  `X = ∓opening/2`, de `Y0` à `Y1`. Pas de rues ; `lanes` ne fixe plus que
  les plans des frises.

### 8.4 Frises et fond

- `Border_NN` au plan `k` si `borders[k]` est coché, `Border_00` (frise de
  face) si `front_border` : largeur `Wc − 0,20`, de `Hp + border_bottom` à
  `Zb`, posée 0,10 côté salle du plan pour couvrir le haut des pendrillons.
  Si `border_bottom ≥ Zb − Hp` : aucune frise et alerte.
- Fond : rideau noir `Backdrop` (`TS_Masking`, plissé, plan `Yb`, largeur
  `Wc − 0,20`) ; mur nu : rien, `Cage_Back` est visible ; cyclorama
  `Cyclorama` (`TS_Cyclorama`, plat, plan `Yb`, largeur `Wc − 0,60`).

### 8.5 Rideau de scène à la grecque (`TS_MainCurtain`)

- `MainCurtain_L` / `MainCurtain_R` dans le plan `Y = Yc + 0,15`, de `Z = Hp`
  à `Hp + Hc + 0,30` (le haut se cache derrière le linteau).
- Fermé : chaque lé va du centre (chevauchement de 0,15 au-delà de l'axe)
  jusqu'à `±(W/2 − 0,05)`, son bord extérieur caché derrière le montant du
  cadre.
- Ouvert : chaque lé est ramassé **entièrement derrière son montant**, de
  `Wc/2 + 0,05` à `W/2 − 0,05` en valeur absolue, plis d'amplitude 0,20
  *(choix)*. Le rideau ouvert ne mord jamais sur l'ouverture `[−Wc/2, Wc/2]`
  (les plis partent en Y, seule l'étendue en X compte). Si le montant est
  trop étroit (`Tc − 0,10 < 0,30`), le paquet garde 0,30 de large, déborde
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

## 9. Préréglages YAML

- Même arborescence que les groupes de paramètres, plus `version: 1`.
  `modules` contient `symmetric`, `left` et `right`.
- Livrés dans `presets/` : `reference_with_modules.yaml` (valeurs par défaut)
  et `open_space.yaml` (sans modules).
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
- rideau de scène ouvert visible dans l'ouverture (montants trop étroits).

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

## 12. Hors périmètre v1

Voir `BACKLOG.md`.
