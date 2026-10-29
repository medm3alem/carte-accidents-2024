# Hackathon Renault 2026 – Analyse post-accident (BAAC)

Analyse des accidents corporels de la route en France pour la problématique du hackathon :
*comment mettre l'innovation au service des premières minutes qui suivent un accident ?*

Le script `analyse_baac.py` lit les fichiers BAAC d'une année et produit une synthèse
chiffrée, des tableaux et des graphiques orientés post-accident (alerte, accès à la
victime, désincarcération, témoins, véhicules).

**Carte en ligne :** https://VOTRE-PSEUDO.github.io/NOM-DU-DEPOT/ *(à remplacer après publication)*

> Scripts préparés avec l'aide d'une IA (Claude), usage à signaler
> conformément aux règles du hackathon.

Données : ONISR, fichier BAAC 2024, [data.gouv.fr](https://www.data.gouv.fr/datasets/bases-de-donnees-annuelles-des-accidents-corporels-de-la-circulation-routiere-annees-de-2005-a-2024),
Licence Ouverte 2.0. Fonds de carte © OpenStreetMap, IGN Géoplateforme.

---

## Bases de données

### BAAC – accidents corporels en France (source principale)

Fichier national des accidents corporels administré par l'ONISR, en open data
(Licence Ouverte). 4 CSV par année : caractéristiques, lieux, véhicules, usagers.

- **Page de téléchargement (2005 → 2024)** :
  https://www.data.gouv.fr/datasets/bases-de-donnees-annuelles-des-accidents-corporels-de-la-circulation-routiere-annees-de-2005-a-2024
- **Description des variables** (à lire avant toute analyse) :
  - en anglais, à jour 2024 : https://www.onisr.securite-routiere.gouv.fr/sites/default/files/2025-10/Description%20des%20bases%20de%20donn%C3%A9es%20annuelles%20en-EN.pdf
  - en français : https://www.onisr.securite-routiere.gouv.fr/sites/default/files/2024-10/Description%20des%20bases%20de%20donn%C3%A9es%20annuelles.pdf
- **Page open data de l'ONISR** : https://www.onisr.securite-routiere.gouv.fr/outils-statistiques/open-data
- **Bilans officiels annuels (pour citer les chiffres)** :
  https://www.onisr.securite-routiere.gouv.fr/etat-de-linsecurite-routiere/bilans-annuels-de-la-securite-routiere/bilan-2025-de-la-securite-routiere

**Liens directs des fichiers 2024** (correspondance établie d'après la taille des
fichiers sur data.gouv.fr – vérifier le nom du fichier après téléchargement) :

| Fichier | Taille | Lien |
|---|---|---|
| `caract-2024.csv` | 6,2 Mo | https://www.data.gouv.fr/api/1/datasets/r/83f0fb0e-e0ef-47fe-93dd-9aaee851674a |
| `lieux-2024.csv` | 6,7 Mo | https://www.data.gouv.fr/api/1/datasets/r/228b3cda-fdfb-4677-bd54-ab2107028d2d |
| `vehicules-2024.csv` | 6,1 Mo | https://www.data.gouv.fr/api/1/datasets/r/fd30513c-6b11-4a56-b6dc-5ac87728794b |
| `usagers-2024.csv` | 13,2 Mo | https://www.data.gouv.fr/api/1/datasets/r/f57b1f58-386d-4048-8f78-2ebe435df868 |
| `2024.csv` (âge et CNIT des véhicules) | 5,1 Mo | https://www.data.gouv.fr/api/1/datasets/r/d0574a19-9005-4fff-92db-050b5fb2c72c |

Le fichier complémentaire `2024.csv` (âge du véhicule, catégorie, code CNIT) **ne peut
pas être relié au BAAC** : son identifiant `Id_accident` est différent de `Num_Acc`, et
les deux fichiers n'ont ni le même ordre ni le même nombre d'accidents.

### FARS – délais d'alerte et d'arrivée des secours (États-Unis, NHTSA)

Seule grande base ouverte avec, pour chaque accident mortel, l'heure du crash, de
l'alerte, de l'arrivée des secours et de l'arrivée à l'hôpital.

- **Téléchargement** (dossier de l'année → `National` → `FARSxxxxNationalCSV.zip`) :
  https://www.nhtsa.gov/file-downloads?p=nhtsa/downloads/FARS/
- **Requêtes en ligne** : https://www-fars.nhtsa.dot.gov/Main/index.aspx

### CISS – sévérité du choc et blessures (États-Unis, NHTSA)

Échantillon d'accidents détaillés : delta-V, ceinture, données des enregistreurs
embarqués, codage précis des blessures. Utile pour un score de gravité.

- **Téléchargement** (dossier de l'année → `CISS_xxxx_CSV_files.zip`, 2016 → 2024) :
  https://www.nhtsa.gov/file-downloads?p=nhtsa/downloads/CISS/
- **Présentation (édition 2023)** : https://crashstats.nhtsa.dot.gov/Api/Public/ViewPublication/813667

### CARE / ERSO – Europe

Base européenne détaillée, mais les données brutes sont réservées aux administrations.
Rapports, tableaux de bord et Atlas en accès libre :

- https://road-safety.transport.ec.europa.eu/european-road-safety-observatory/data-and-analysis_en

---

## Installation

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Si l'activation est bloquée : `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`.

## Utilisation

Placer les 4 CSV du BAAC (et éventuellement `2024.csv`) dans un même dossier, puis :

```powershell
python analyse_baac.py "C:\chemin\vers\data 2024"
```

### Carte interactive des accidents

```powershell
python carte_accidents.py "C:\chemin\vers\data 2024"
```

Crée `resultats_baac_<année>\carte_accidents_<année>.html`, puis l'ouvre dans le
navigateur via un **petit serveur local** (`http://localhost:8000/...`). Ce serveur relaie
les recherches vers l'IGN et OpenStreetMap (le navigateur ne les bloque donc pas) et
affiche chaque requête dans le terminal : **laisser le terminal ouvert**, Ctrl+C pour
arrêter. Option `--sans-serveur` pour seulement créer le fichier.
Une croix par accident : **couleur selon le type de route** (bleu = autoroute, orange =
route hors agglomération, vert = en agglomération), **taille selon la gravité** (grande avec
liseré blanc = mortel). Un menu permet de revenir aux croix rouges par gravité. Filtres par
type de route (avec le nombre d'accidents), gravité, « véhicule seul hors agglomération »,
nuit et territoire.

**Filtre « Véhicules impliqués »** : voiture, utilitaire, moto/scooter/3RM/quad, vélo/VAE,
trottinette/EDP, poids lourd/bus/car, voiturette, autre — affiche les accidents impliquant
au moins un véhicule coché (liens « tout / aucun », nombre d'accidents par catégorie).

**Filtre « Obstacle heurté »** : obstacles fixes (arbre ; fossé, talus ; glissière ; mur,
pile de pont ; poteau, panneau ; autre obstacle fixe ; véhicule en stationnement ; sortie
de chaussée sans obstacle), obstacles mobiles (piéton ; autre véhicule ; animal ; autre)
et « aucun obstacle renseigné ». Affiche les accidents où au moins un véhicule a heurté
un obstacle coché. Les deux listes (véhicules, obstacles) sont repliables.

**Filtre « Heure de l'accident »** : créneau « de … à … » (heure de début incluse, heure
de fin exclue), qui peut passer minuit (ex. de 22:00 à 06:00), avec des raccourcis :
toute la journée, nuit 22 h – 6 h, matin 7 h – 10 h, fin de journée 16 h – 20 h.

**Fenêtre d'un accident** : en plus du bilan, les conditions (météo `atm`, situation
`situ`, vitesse maximale autorisée `vma`) et, pour chaque véhicule (volet repliable),
sa catégorie (`catv`), sa motorisation (`motor`), sa manœuvre (`manv`), son point de
choc (`choc`), les obstacles fixe (`obs`) et mobile (`obsm`), puis chaque usager :
rôle et place (`catu`, `place`), âge, sexe, gravité et équipements de sécurité
(`secu1` à `secu3`). Libellés : codes officiels de l'ONISR.

Le fond de carte par défaut est **OpenStreetMap : aucune clé API n'est nécessaire**.
Un sélecteur en bas à gauche propose OSM gris, OSM couleur, OSM France, ainsi que la
**photo aérienne** et le plan de l'IGN (Géoplateforme, open data, sans clé).
Dans la fenêtre d'un accident, trois boutons ouvrent le lieu dans **Google Street View**,
Google Maps ou Mapillary (liens simples, sans clé API). Le fond
CARTO demande une clé gratuite depuis août 2026
(https://www.carto.com/basemaps/apikey/) ; il reste optionnel :

```powershell
python carte_accidents.py "C:\chemin\vers\data 2024" --cle-carto VOTRE_CLE
```

Plus simple : mettre la clé seule dans un fichier `cle_carto.txt` à côté des scripts,
elle est lue automatiquement. Ce fichier est exclu par `.gitignore`.
La clé est alors écrite dans le fichier HTML : ne pas le publier tel quel.

### Secours autour de chaque accident (en direct sur la carte)

Rien à lancer en plus : au clic sur une croix, la carte cherche **en direct** autour de
l'accident :
- les **casernes** de la BD TOPO de l'IGN (service WFS de la Géoplateforme), dans un rayon
  de 15 km, élargi à 35 puis 60 km s'il y en a moins de 3 ;
- les **urgences / SMUR** d'OpenStreetMap (hôpitaux avec urgences, 50 puis 100 km) ;
  si OpenStreetMap ne répond pas, les hôpitaux de la BD TOPO (urgences non vérifiées) ;
- puis le **trajet par la route** de chaque candidat (API d'itinéraire de l'IGN, sur le
  réseau qu'elle annonce comme disponible ; à défaut, serveur public OSRM) :
  la caserne et les urgences **les plus rapides** sont marquées ★ et leur trajet est
  dessiné. Boutons « Trajet … → accident » pour ouvrir le même itinéraire dans Google Maps.

Tout est sans clé. Limites : le centre le plus rapide n'est pas forcément celui qui
intervient réellement, et le temps est celui d'une voiture normale, sans délai de départ.

## Publier la carte sur GitHub Pages

La version en ligne est un fichier statique `docs/index.html` : pas de serveur local, pas
de clé CARTO (fond OpenStreetMap par défaut). Les recherches de secours interrogent
directement l'IGN, OpenStreetMap et OSRM depuis le navigateur.

1. Générer la version en ligne (à refaire après chaque modification) :
   ```powershell
   python carte_accidents.py "C:\chemin\vers\data 2024" --publier
   ```
2. La première fois : créer un dépôt **vide** sur github.com (bouton « New »), puis :
   ```powershell
   git init
   git add .
   git commit -m "Carte des accidents BAAC 2024"
   git branch -M main
   git remote add origin https://github.com/VOTRE-PSEUDO/NOM-DU-DEPOT.git
   git push -u origin main
   ```
3. Sur GitHub : **Settings → Pages → Build and deployment → Source : Deploy from a branch**,
   branche `main`, dossier **`/docs`**, puis **Save**. Le site est en ligne au bout
   d'une à deux minutes à l'adresse indiquée.
4. Les fois suivantes : `--publier`, puis `git add .`, `git commit -m "..."`, `git push`.

Ne sont **jamais** envoyés (voir `.gitignore`) : `cle_carto.txt`, les CSV du BAAC, le dossier
`resultats_baac_*` et l'environnement `.venv`.

## Résultats

Créés dans `<dossier>\resultats_baac_<année>\` :

| Élément | Contenu |
|---|---|
| `synthese.md` | Résumé chiffré de toutes les analyses |
| `graphiques\*.png` | Graphiques prêts pour la soutenance |
| `tables\*.csv` | Tableaux détaillés (séparateur `;`, ouvrables dans Excel) |
| `baac_<année>_usagers_joint.csv` | Une ligne par usager, toutes informations jointes |

Analyses produites : chiffres clés, lieu et luminosité, heure et jour, accidents sans
tiers, accès à la victime et désincarcération, motorisation (batteries haute tension),
modes de déplacement, autoroute et piétons, âge, ceinture, départements, carte des
accidents mortels, âge et modèles des véhicules.

## Définitions à garder en tête

- **Tué** : décès dans les 30 jours suivant l'accident.
- **Létalité** : tués pour 100 victimes (tués + blessés hospitalisés + blessés légers).
- **Véhicule seul / sans tiers** : un seul véhicule impliqué et aucun piéton.
- **Accidents mortels ≠ tués** : un accident peut faire plusieurs morts
  (2024 : 3 226 accidents mortels, 3 432 tués).
- La catégorie « blessé hospitalisé » n'est pas comparable avant et après 2018.
- Toujours préciser l'année : 3 432 tués en 2024, 3 515 en 2025.
