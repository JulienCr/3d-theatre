# Bibliothèque d'appareils

Un dossier par appareil, nommé comme son `id` : `<id>/fixture.yaml`, avec
`source/` (GDTF, fiches techniques, profils IES), `meshes/` (`.glb` ou `.obj`,
en mètres) et `gobos/` (images `.png`). Les chemins de la fiche sont relatifs à
son dossier. Schéma complet : `docs/spec.md`, section 12.

## Ajouter une fiche depuis un GDTF

```
python tools/gdtf_to_fiche.py <fichier.gdtf> --id <id> --out blender/theatre_stage/library/fixtures/<id>
```

Options : `--mode <nom>` (répétable) pour ne garder que certains modes. L'outil
écrit `fixture.yaml`, copie le GDTF dans `source/`, convertit les maillages
`.3ds` en `.obj` (mètres) ou copie les `.glb`, et extrait les images de gobos.

Les clés que le GDTF ne donne pas restent à `null  # à compléter` : tant
qu'elles y sont, la fiche est invalide et absente des listes du panneau
(famille, accroche, décalage de lentille, champ, géométrie des lames…).

## Contrôle

Après avoir complété la fiche, cliquer sur « Recharger la bibliothèque » dans
le panneau : une fiche invalide est écartée avec la liste des clés fautives
dans les alertes. Une fiche du dossier utilisateur de même `id` remplace la
fiche livrée.
