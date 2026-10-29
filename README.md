# Carte des accidents de la route 2024 – Hackathon Renault « après l'accident »

Outil d'analyse des accidents corporels de 2024 en France, réalisé pour le hackathon
Renault 2026 : *comment mettre l'innovation au service des premières minutes qui suivent
un accident ?*

**Carte en ligne : https://medm3alem.github.io/carte-accidents-2024/**


## Contenu du dépôt

| Fichier | Rôle |
|---|---|
| `analyse_baac.py` | Statistiques « post-accident » : synthèse chiffrée, tableaux et graphiques |
| `carte_accidents.py` | Génère la carte interactive `docs/index.html` |
| `docs/index.html` | La carte publiée sur GitHub Pages |
| `requirements.txt` | Dépendances Python (pandas, matplotlib) |

## Données

**BAAC 2024** (Bulletins d'analyse des accidents corporels, ONISR), en open data sur
[data.gouv.fr](https://www.data.gouv.fr/datasets/bases-de-donnees-annuelles-des-accidents-corporels-de-la-circulation-routiere-annees-de-2005-a-2024),
Licence Ouverte 2.0. Quatre fichiers CSV reliés par le numéro d'accident `Num_Acc` :

- `caract-2024.csv` : date, heure, luminosité, météo, agglomération, coordonnées GPS ;
- `lieux-2024.csv` : catégorie de route, vitesse maximale autorisée, situation de l'accident ;
- `vehicules-2024.csv` : catégorie, motorisation, manœuvre, point de choc, obstacles heurtés ;
- `usagers-2024.csv` : conducteur, passager ou piéton, gravité, âge, équipements de sécurité.

Facultatif : `2024.csv` (âge et code CNIT des véhicules accidentés). Il ne peut pas être
relié aux accidents du BAAC et ne sert qu'à des statistiques globales.

Description des variables : [document de l'ONISR](https://www.onisr.securite-routiere.gouv.fr/sites/default/files/2025-10/Description%20des%20bases%20de%20donn%C3%A9es%20annuelles%20en-EN.pdf).
Les CSV ne sont pas dans le dépôt : à télécharger sur data.gouv.fr.

## Installation

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Utilisation

Placer les CSV du BAAC dans un dossier, par exemple `C:\data 2024`.

**1. Analyse statistique**

```powershell
python analyse_baac.py "C:\data 2024"
```

Résultats dans `C:\data 2024\resultats_baac_2024\` : `synthese.md`, `graphiques\`, `tables\`
et `baac_2024_usagers_joint.csv` (une ligne par usager, toutes informations jointes).

**2. Carte interactive**

```powershell
python carte_accidents.py "C:\data 2024"
```

Écrit `docs/index.html` et l'ouvre sur `http://localhost:8000`. Laisser le terminal ouvert :
il relaie les recherches de secours et affiche chaque requête (Ctrl+C pour arrêter).

**3. Mettre à jour le site en ligne**

```powershell
python carte_accidents.py "C:\data 2024" --sans-apercu
git add .
git commit -m "Mise a jour de la carte"
git push
```

Réglage GitHub (une seule fois) : **Settings → Pages → Deploy from a branch**, branche
`main`, dossier `/docs`.

## La carte

- **Une croix par accident** géolocalisé : couleur = type de route (bleu autoroute, orange
  hors agglomération, vert en agglomération), taille = gravité (grande = mortel).
- **Filtres** : gravité, type de route, véhicules impliqués, obstacle heurté, créneau
  horaire (y compris à cheval sur minuit), véhicule seul hors agglomération, nuit, territoire.
- **Au clic sur une croix** : bilan de l'accident, météo, lieu, vitesse autorisée, puis
  chaque véhicule (catégorie, motorisation, manœuvre, choc, obstacles) et ses usagers
  (âge, sexe, gravité, équipements). Liens Street View, Google Maps et Mapillary.
- **Secours autour de l'accident, en direct** : casernes et urgences les plus proches,
  trajet le plus rapide par la route (★), dessiné sur la carte et ouvrable dans Google Maps.
  Les trajets restent affichés jusqu'à « Effacer les trajets ».
- **Fonds de carte** (en bas à gauche) : OpenStreetMap gris, couleur ou France, photo
  aérienne et plan de l'IGN.

### Services utilisés (gratuits, sans clé)

| Fonction | Service |
|---|---|
| Fonds de carte | OpenStreetMap, IGN Géoplateforme |
| Casernes de pompiers | IGN BD TOPO (WFS de la Géoplateforme) |
| Urgences / SMUR | OpenStreetMap (Overpass), sinon hôpitaux de la BD TOPO |
| Trajets par la route | API d'itinéraire de l'IGN, sinon serveur public OSRM |

Ces services sont prévus pour un usage modéré (démonstration, équipe).

## Limites à garder en tête

- **Tué** = décès dans les 30 jours. Un accident peut faire plusieurs tués
  (2024 : 3 226 accidents mortels, 3 432 tués).
- Le BAAC ne contient **aucun horaire d'alerte ni d'arrivée des secours** : les temps de
  trajet de la carte sont calculés, pour une voiture normale, sans délai de départ.
- La caserne la plus rapide n'est pas forcément celle qui intervient réellement.
- Les liens entre distance aux secours et gravité sont des **corrélations**, pas des causes.

## Pour aller plus loin

- [FARS (NHTSA, États-Unis)](https://www.nhtsa.gov/file-downloads?p=nhtsa/downloads/FARS/) :
  heures d'alerte, d'arrivée des secours et d'arrivée à l'hôpital pour chaque accident mortel.
- [CISS (NHTSA)](https://www.nhtsa.gov/file-downloads?p=nhtsa/downloads/CISS/) :
  violence du choc (delta-V) et blessures, utile pour un modèle de gravité.
