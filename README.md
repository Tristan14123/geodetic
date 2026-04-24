Quelle est l'EPSG utilisé?
Laquelle je devrais choisir ?
Pourquoi mes données sont décallé ?

Re-projetes sur la bonne projection,
vois rapidement avec les métadonnées à quoi sert cette donnée, sont emprise et sa géométrie.

Convertie ta donnée dans le bon EPSG et télécharge la en GPKG directement consultable dans QGIS.

----

1. Diagnostic de Cohérence (L'Audit)
L'application ne se contente pas de lire le fichier, elle vérifie sa véracité scientifique selon 4 axes :

La validité métrique : Est-ce que les chiffres correspondent au système déclaré ? (Ex: si vous déclarez du WGS84 mais que vos coordonnées dépassent 180, l'appli détecte l'incohérence).

La cohérence topologique : En calculant le centroïde, l'appli vérifie si vos données sont bien situées dans la zone géographique de votre projet (ex: est-ce que vos données "Saint-Lô" sont bien en Normandie ou perdues dans l'océan Atlantique ?).

La santé des métadonnées : Elle vérifie la présence du fichier de projection (.prj) et l'intégrité du schéma.

----

2. Rapport de Métadonnées (La Transparence)
L'appli extrait et "traduit" les informations binaires complexes du fichier en un rapport lisible :

Inventaire : Nombre d'entités, type de géométrie (points, polygones, etc.) et liste des attributs (colonnes de la table).

Emprise (Bounds) : Les coordonnées limites exactes du fichier.

Score de fiabilité : Un pourcentage de confiance qui résume la qualité technique globale du fichier.

----

3. Conversion et Reprojection (La Solution)
Une fois le diagnostic posé, l'application répare les données :

Reprojection mathématique : Elle transforme les coordonnées du système d'origine vers le système cible (ex: passer d'un GPS WGS84 vers le Lambert-93 officiel français).

Normalisation du format : Elle convertit des formats disparates (comme un Shapefile ZIP éparpillé) vers un format GeoPackage (.gpkg) moderne, unique et standardisé.
