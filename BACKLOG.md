# Backlog

- **Projecteurs en perroquet.** Accrocher des appareils aux porteuses de
  pendrillonnage et en des points libres (perroquet), en plus de
  l'implantation fixe de la section 13 de `docs/spec.md`.
- **Alertes de surcharge.** La charge cumulée par porteuse, perche et pylône
  est déjà affichée (poids des fiches). Reste la charge maximale par support
  et l'alerte en cas de dépassement.
- **Numéros de porteuses stables.** Aujourd'hui, changer le pendrillonnage
  renumérote les porteuses lumière. L'implantation s'accroche par position en
  Y et n'en souffre pas, mais un numéro cité par l'utilisateur (plan de feux,
  console) ne doit pas changer de porteuse.
- **Prisme et frost.** Rendre le prisme et le frost des mobiles (Esprite,
  MAC Aura) : aujourd'hui leurs canaux sont conservés comme attributs
  inconnus, sans effet dans Blender.
- **Anneau « Aura » du MAC Aura.** Rendre la couronne de LED autour de la
  lentille ; ses canaux (second tête du `.qxf` de QLC+, mode `Extended`) sont
  conservés mais non lus.
- **Sens physiques à confronter à un vrai appareil.** Le sens positif du pan
  (13.9), le pivotement des lames de l'Esprite et la latéralité des gobos
  suivent les GDTF et la convention de la spec, sans vérification contre un
  appareil réel piloté par la même console.
- **Strobe à rampe descendante.** Le strobe du MAC Aura va du rapide (DMX 25)
  au lent (DMX 64) ; la fiche ne sait décrire qu'une rampe montante.
- **Washes très serrés.** La calibration (14.8) tient à 1 % près, sauf pour
  un disque d'ouverture ≤ 10° : 15 % trop sombre à 10°, 40 % à 5°.
- **Valeurs estimées dans les fiches.** IES du tube 70° du Lustr X8 (repris
  du Daylight HDR), courbe CCT 16 bits des Source Four (déduite de la table
  8 bits), géométrie des lames (`# estimated` dans les YAML).
- **Maillages après rechargement de la bibliothèque.** Les maillages `TSF_*`
  ne sont jamais réécrits (14.1) : une fiche modifiée garde son ancien
  maillage tant qu'on ne le supprime pas à la main.
- **Liste de patch** tronquée dans une barre latérale étroite.
- **Bug : plateau très bas.** `advanced.stage_height` à 0,20 lève
  `min() iterable argument is empty` (`core/layout.py`, escaliers sans
  marche). Antérieur à l'implantation lumière.
- **Rideau de scène à l'italienne.** Deux lés relevés en drapé vers les coins
  hauts, en plus du rideau à la grecque.
- **Salle.** Gradins, murs et plafond, à profondeur réglable.
- **Pans coupés du nez de scène.**
- **Vantaux de porte** dans les modules, ouverts ou fermés.
- **Baies sur le retour des modules.**
