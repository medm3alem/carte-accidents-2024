#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
carte_accidents.py - Carte interactive des accidents du BAAC (une croix par accident)
Hackathon Renault 2026.

UTILISATION (PowerShell, dans le dossier du projet) :
    python carte_accidents.py "C:\chemin\vers\data 2024"
        -> ecrit docs\index.html et l'ouvre sur http://localhost:8000
    python carte_accidents.py "C:\chemin\vers\data 2024" --sans-apercu
        -> ecrit seulement docs\index.html (a pousser sur GitHub Pages)

La carte : croix colorees par type de route (taille = gravite), filtres (gravite,
type de route, vehicules, obstacles, heure, situation), detail BAAC de chaque
accident, et recherche EN DIRECT des secours autour d'un accident (casernes IGN,
urgences OpenStreetMap, trajets par la route IGN ou OSRM). Aucune cle API.
"""

import argparse
import http.server
import json
import re
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

import pandas as pd

# Fonctions de lecture partagees avec le script d'analyse
from analyse_baac import en_nombres, lire_csv, mode_depuis_catv, trouver


def charger_accidents(dossier):
    """Accidents geolocalises (une ligne par accident) + tables vehicules et usagers."""
    chemins = {k: trouver(dossier, m) for k, m in
               {"caract": r"^carac", "lieux": r"^lieu",
                "vehicules": r"^vehic", "usagers": r"^usag"}.items()}
    manquants = [k for k, p in chemins.items() if p is None]
    if manquants:
        sys.exit(f"Fichiers manquants dans {dossier} : {', '.join(manquants)}")

    print("Lecture des fichiers...")
    car = lire_csv(chemins["caract"])
    lie = lire_csv(chemins["lieux"])
    veh = lire_csv(chemins["vehicules"])
    usa = lire_csv(chemins["usagers"])
    en_nombres(car, ["jour", "mois", "an", "lum", "agg", "lat", "long", "atm"])
    en_nombres(lie, ["catr", "situ", "vma"])
    en_nombres(veh, ["catv", "obs", "obsm", "choc", "manv", "motor"])
    en_nombres(usa, ["grav", "catu", "place", "secu1", "secu2", "secu3", "an_nais", "sexe"])

    A = car.drop_duplicates("Num_Acc").copy()
    A = A.merge(lie[["Num_Acc", "catr", "situ", "vma"]].drop_duplicates("Num_Acc"),
                on="Num_Acc", how="left")
    g = usa.assign(tue=(usa["grav"] == 2).astype(int), bh=(usa["grav"] == 3).astype(int),
                   victimes=usa["grav"].isin([2, 3, 4]).astype(int),
                   pieton=(usa["catu"] == 3).astype(int))
    g = g.groupby("Num_Acc")[["tue", "bh", "victimes", "pieton"]].sum()
    A = A.merge(g, left_on="Num_Acc", right_index=True, how="left")
    A = A.merge(veh.groupby("Num_Acc").size().rename("nb_veh"), left_on="Num_Acc",
                right_index=True, how="left")
    for c in ["tue", "bh", "victimes", "pieton", "nb_veh"]:
        A[c] = A[c].fillna(0).astype(int)

    # Coordonnees valides uniquement
    n0 = len(A)
    A = A.dropna(subset=["lat", "long"])
    A = A[A["lat"].between(-90, 90) & A["long"].between(-180, 180)
          & ~((A["lat"].abs() < 0.01) & (A["long"].abs() < 0.01))]
    print(f"  {len(A):,} accidents geolocalises sur {n0:,}")

    A["sev"] = 1 + (A["bh"] > 0).astype(int)
    A.loc[A["tue"] > 0, "sev"] = 3
    A["seul_ha"] = ((A["nb_veh"] == 1) & (A["pieton"] == 0) & (A["agg"] == 1)).astype(int)
    A["nuit"] = A["lum"].isin([3, 4, 5]).astype(int)
    A["date"] = (A["jour"].fillna(0).astype(int).astype(str).str.zfill(2) + "/"
                 + A["mois"].fillna(0).astype(int).astype(str).str.zfill(2) + "/"
                 + A["an"].fillna(0).astype(int).astype(str) + " " + A["hrmn"].fillna(""))
    annee = int(A["an"].mode().iloc[0]) if A["an"].notna().any() else 0
    return A, annee, veh, usa


# Groupes de vehicules pour le filtre de la carte (un bit par groupe)
GROUPES_CATV = {"Voiture (VL)": 0, "Vehicule utilitaire (VU)": 1, "2RM / 3RM / quad": 2,
                "Velo / VAE": 3, "EDP (trottinette...)": 4, "Poids lourd / bus / car": 5,
                "Voiturette": 6}


# Obstacles heurtes : bit -> codes obs (fixes) ou obsm (mobiles) du BAAC
OBS_BITS = {2: 0, 13: 1, 3: 2, 4: 2, 5: 2, 6: 3, 10: 3, 7: 4, 8: 4, 9: 4,
            11: 5, 12: 5, 14: 5, 15: 5, 17: 5, 1: 6, 16: 7}
OBSM_BITS = {1: 8, 2: 9, 4: 9, 5: 10, 6: 10, 9: 11}
BIT_AUCUN_OBSTACLE = 12


def details_vehicules(veh, usa, annee):
    """Pour chaque accident : vehicules [lettre, catv, obs, obsm, choc, manv, motor,
    usagers] et masque des groupes de vehicules. Usager : [catu, place, grav, age,
    sexe, secu...]. -1 = non renseigne."""
    def c(x):
        return int(x) if pd.notna(x) else -1

    cle = "id_vehicule" if ("id_vehicule" in veh and "id_vehicule" in usa) else "num_veh"
    occupants = {}
    for u in usa.itertuples(index=False):
        age = annee - int(u.an_nais) if pd.notna(u.an_nais) and 0 < annee - u.an_nais < 110 else -1
        secu = [c(x) for x in (u.secu1, u.secu2, u.secu3) if pd.notna(x) and x >= 0]
        occupants.setdefault((u.Num_Acc, getattr(u, cle)), []).append(
            [c(u.catu), c(u.place), c(u.grav), age, c(u.sexe)] + secu)
    par_acc, masques, obstacles = {}, {}, {}
    for v in veh.itertuples(index=False):
        lettre = str(v.num_veh or "?").strip()[:1].upper() or "?"
        users = sorted(occupants.get((v.Num_Acc, getattr(v, cle)), []),
                       key=lambda x: (x[0] if x[0] > 0 else 9, x[1]))
        par_acc.setdefault(v.Num_Acc, []).append(
            [lettre, c(v.catv), c(v.obs), c(v.obsm), c(v.choc), c(v.manv), c(v.motor), users])
        bit = GROUPES_CATV.get(mode_depuis_catv(v.catv), 7)
        masques[v.Num_Acc] = masques.get(v.Num_Acc, 0) | (1 << bit)
        m = obstacles.get(v.Num_Acc, 0)
        if c(v.obs) in OBS_BITS:
            m |= 1 << OBS_BITS[c(v.obs)]
        if c(v.obsm) in OBSM_BITS:
            m |= 1 << OBSM_BITS[c(v.obsm)]
        obstacles[v.Num_Acc] = m
    for liste in par_acc.values():
        liste.sort(key=lambda x: x[0])
    obstacles = {k: (m or 1 << BIT_AUCUN_OBSTACLE) for k, m in obstacles.items()}
    return par_acc, masques, obstacles


def preparer(dossier):
    A, annee, veh, usa = charger_accidents(dossier)
    par_acc, masques, obstacles = details_vehicules(veh, usa, annee)
    def code(x):
        return int(x) if pd.notna(x) else 0

    def type_route(catr, agg):
        if catr == 1:
            return 1                          # autoroute
        return {1: 2, 2: 3}.get(agg, 0)       # hors agglomeration / en agglomeration

    def minutes(hrmn):
        m = re.match(r"\s*(\d{1,2})\D?(\d{2})\s*$", str(hrmn))
        if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
            return -1
        return int(m.group(1)) * 60 + int(m.group(2))

    lignes = [[round(r.lat, 5), round(r.long, 5), int(r.sev), int(r.tue), int(r.bh),
               int(r.seul_ha), int(r.nuit), code(r.lum), code(r.agg), code(r.catr),
               str(r.date), str(r.dep), str(r.com) if "com" in A else "",
               (str(r.adr)[:60] if "adr" in A and pd.notna(r.adr) else ""),
               type_route(code(r.catr), code(r.agg)),
               code(r.atm) if pd.notna(r.atm) else -1,
               code(r.situ) if pd.notna(r.situ) else -1,
               code(r.vma) if pd.notna(r.vma) else -1,
               masques.get(r.Num_Acc, 1 << 7),
               par_acc.get(r.Num_Acc, []),
               obstacles.get(r.Num_Acc, 1 << BIT_AUCUN_OBSTACLE),
               minutes(r.hrmn) if "hrmn" in A else -1]
              for r in A.itertuples()]
    return lignes, annee


HTML = r"""<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Carte des accidents __ANNEE__</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
  :root { --ink:#0b0b0b; --ink2:#52514e; --line:#e4e3df; --bg:#fcfcfb;
          --red:#c81e1e; --red-soft:#e34948; }
  html, body { margin:0; height:100%; font:14px/1.4 system-ui, -apple-system, "Segoe UI", sans-serif; color:var(--ink); }
  #map { position:absolute; inset:0; background:#eef0ee; }
  .fond-gris { filter: grayscale(85%) brightness(1.06) contrast(0.92); }
  .panel { position:absolute; top:12px; right:12px; z-index:1000; width:290px;
           max-width:calc(100vw - 80px); background:var(--bg); border:1px solid var(--line);
           border-radius:10px; padding:14px 16px; box-shadow:0 2px 12px rgba(0,0,0,.12);  max-height:calc(100vh - 24px); overflow-y:auto; }
  .panel h1 { font-size:16px; margin:0 0 2px; }
  .panel .sub { color:var(--ink2); font-size:12.5px; margin-bottom:10px; }
  .stats { display:flex; gap:14px; margin:8px 0 12px; }
  .stat b { display:block; font-size:20px; font-variant-numeric:tabular-nums; }
  .stat span { color:var(--ink2); font-size:12px; }
  fieldset { border:0; margin:0 0 10px; padding:0; }
  legend { font-weight:600; font-size:12.5px; margin-bottom:4px; }
  label { display:flex; align-items:center; gap:8px; padding:2px 0; cursor:pointer; }
  .x { width:14px; height:14px; flex:none; }
  select { width:100%; padding:5px; border:1px solid var(--line); border-radius:6px; background:#fff; }
  .src { color:var(--ink2); font-size:11px; margin-top:10px; }
  .note { color:var(--ink2); font-size:11.5px; }
  details.filtre summary { cursor:pointer; display:flex; gap:6px; align-items:baseline; margin-bottom:4px; }
  details.filtre summary::before { content:"▸"; color:var(--ink2); }
  details.filtre[open] summary::before { content:"▾"; }
  details.filtre summary::-webkit-details-marker { display:none; }
  .sous { font-size:11.5px; color:var(--ink2); margin:4px 0 0; text-transform:uppercase; letter-spacing:.04em; }
  .heures { display:flex; align-items:center; gap:6px; margin-bottom:4px; }
  .heures select { width:auto; padding:3px 4px; }
  .det { margin-top:6px; padding-top:6px; border-top:1px solid var(--line); }
  .det summary { cursor:pointer; margin-top:4px; }
  .det .u { padding-left:12px; }
  .det .lib { color:var(--ink2); }
  .nb { color:var(--ink2); font-size:12px; font-variant-numeric:tabular-nums; margin-left:auto; }
  .grav .x { color:#52514e; }
  .mode-grav .grav .x { color:#c81e1e; }
  .btn { margin-top:6px; padding:5px 10px; border:1px solid var(--line); border-radius:6px;
         background:#fff; color:var(--ink); font:inherit; font-size:12.5px; cursor:pointer; }
  .btn:hover { background:#f4f4f2; }
  .sec { margin-top:6px; padding-top:6px; border-top:1px solid var(--line); }
  .toggle { display:none; }
  .leaflet-popup-content { font-size:13px; line-height:1.45; }
  .leaflet-popup-content b.t { color:var(--red); }
  .liens { display:flex; gap:6px; margin-top:8px; flex-wrap:wrap; }
  .liens a { padding:4px 9px; border:1px solid var(--line); border-radius:6px;
             text-decoration:none; color:#1c5cab; background:#fff; font-size:12.5px; }
  .liens a:hover { background:#f1f6fd; }
  @media (max-width:600px) {
    .panel { top:auto; bottom:12px; right:12px; left:12px; width:auto; max-width:none; }
    .panel.closed .body { display:none; }
    .toggle { display:block; float:right; border:0; background:none; font-size:16px; cursor:pointer; }
  }
</style>
</head>
<body>
<div id="map"></div>
<div class="panel" id="panel">
  <button class="toggle" id="toggle" aria-label="Afficher ou masquer les filtres">☰</button>
  <h1>Accidents corporels __ANNEE__</h1>
  <div class="sub">Une croix par accident (fichier BAAC) : couleur = type de route, taille = gravité</div>
  <div class="body">
    <div class="stats">
      <div class="stat"><b id="nAcc">0</b><span>accidents affichés</span></div>
      <div class="stat"><b id="nTues">0</b><span>tués</span></div>
    </div>
    <fieldset>
      <legend>Couleur des croix</legend>
      <select id="mode">
        <option value="route">Selon le type de route</option>
        <option value="grav">Selon la gravité (rouge)</option>
      </select>
    </fieldset>
    <fieldset id="fsRoute">
      <legend>Type de route</legend>
      <label><input type="checkbox" id="t1" checked>
        <svg class="x" viewBox="0 0 14 14"><path d="M2 2L12 12M12 2L2 12" stroke="#2a78d6" stroke-width="2.6"/></svg>
        Autoroute <span class="nb" id="n1"></span></label>
      <label><input type="checkbox" id="t2" checked>
        <svg class="x" viewBox="0 0 14 14"><path d="M2 2L12 12M12 2L2 12" stroke="#eb6834" stroke-width="2.6"/></svg>
        Route hors agglomération <span class="nb" id="n2"></span></label>
      <label><input type="checkbox" id="t3" checked>
        <svg class="x" viewBox="0 0 14 14"><path d="M2 2L12 12M12 2L2 12" stroke="#1baf7a" stroke-width="2.6"/></svg>
        En agglomération <span class="nb" id="n3"></span></label>
      <label id="lab0"><input type="checkbox" id="t0" checked>
        <svg class="x" viewBox="0 0 14 14"><path d="M2 2L12 12M12 2L2 12" stroke="#8a8984" stroke-width="2.6"/></svg>
        Non renseigné <span class="nb" id="n0"></span></label>
    </fieldset>
    <fieldset>
      <details class="filtre"><summary><b>Véhicules impliqués</b> <span class="nb" id="resVeh"></span></summary>
      <div class="note">Accidents impliquant au moins un véhicule coché
        · <a href="#" id="vTout">tout</a> · <a href="#" id="vAucun">aucun</a></div>
      <div id="listeVeh"></div>
      </details>
    </fieldset>
    <fieldset>
      <details class="filtre"><summary><b>Obstacle heurté</b> <span class="nb" id="resObs"></span></summary>
      <div class="note">Accidents où au moins un véhicule a heurté un obstacle coché
        · <a href="#" id="oTout">tout</a> · <a href="#" id="oAucun">aucun</a></div>
      <div id="listeObs"></div>
      </details>
    </fieldset>
    <fieldset class="grav">
      <legend>Gravité <span class="note">(taille de la croix)</span></legend>
      <label><input type="checkbox" id="s3" checked>
        <svg class="x" viewBox="0 0 14 14"><path d="M2 2L12 12M12 2L2 12" stroke="currentColor" stroke-width="2.6"/></svg>
        Mortel</label>
      <label><input type="checkbox" id="s2">
        <svg class="x" viewBox="0 0 14 14"><path d="M3.5 3.5L10.5 10.5M10.5 3.5L3.5 10.5" stroke="currentColor" stroke-width="1.8"/></svg>
        Blessé hospitalisé (sans tué)</label>
      <label><input type="checkbox" id="s1">
        <svg class="x" viewBox="0 0 14 14"><path d="M4.5 4.5L9.5 9.5M9.5 4.5L4.5 9.5" stroke="currentColor" stroke-opacity=".6" stroke-width="1.4"/></svg>
        Blessés légers uniquement</label>
    </fieldset>
    <fieldset>
      <legend>Heure de l'accident</legend>
      <div class="heures">de <select id="hDe"></select> à <select id="hA"></select>
        <span class="nb" id="resHeure"></span></div>
      <div class="note">Raccourcis :
        <a href="#" data-h="0-24">toute la journée</a> ·
        <a href="#" data-h="22-6">nuit 22 h – 6 h</a> ·
        <a href="#" data-h="7-10">matin 7 h – 10 h</a> ·
        <a href="#" data-h="16-20">fin de journée 16 h – 20 h</a></div>
    </fieldset>
    <fieldset>
      <legend>Situation</legend>
      <label><input type="checkbox" id="fSeul"> Véhicule seul, hors agglomération</label>
      <label><input type="checkbox" id="fNuit"> De nuit</label>
    </fieldset>
    <fieldset>
      <legend>Secours autour de l'accident</legend>
      <div class="note">Au clic sur une croix, la carte cherche <b>en direct</b> les casernes
        (IGN) et les urgences / SMUR (OpenStreetMap, sinon IGN) autour de l'accident, puis
        calcule le trajet le plus rapide par la route (IGN, sinon OSRM).</div>
      <label><svg class="x" viewBox="0 0 14 14"><path d="M1 7H13" stroke="#52514e" stroke-width="3"/></svg> Caserne la plus rapide</label>
      <label><svg class="x" viewBox="0 0 14 14"><path d="M1 7H13" stroke="#2a78d6" stroke-width="3"/></svg> Urgences / SMUR les plus rapides</label>
      <div class="note" id="nbAnalyses"></div>
      <button id="effacer" class="btn" style="display:none">Effacer les trajets de la carte</button>
    </fieldset>
    <fieldset>
      <legend>Territoire</legend>
      <select id="zone">
        <option value="metro">France métropolitaine</option>
        <option value="gp">Guadeloupe</option><option value="mq">Martinique</option>
        <option value="gf">Guyane</option><option value="re">La Réunion</option>
        <option value="yt">Mayotte</option><option value="nc">Nouvelle-Calédonie</option>
        <option value="pf">Polynésie française</option>
      </select>
    </fieldset>
    <div class="src">Source : ONISR, fichier BAAC __ANNEE__ (data.gouv.fr). Cliquez sur une croix pour le détail et la vue Street View. Fond « Photo aérienne (IGN) » en bas à gauche.</div>
  </div>
</div>
<script>
const D = __DATA__;
const LUM = {1: "Plein jour", 2: "Crépuscule ou aube", 3: "Nuit sans éclairage public",
  4: "Nuit, éclairage public non allumé", 5: "Nuit, éclairage public allumé"};
const CATR = {1: "Autoroute", 2: "Route nationale", 3: "Route départementale", 4: "Voie communale",
  5: "Hors réseau public", 6: "Parc de stationnement", 7: "Route de métropole urbaine", 9: "Autre"};
const ZONES = {
  metro:[[41.3,-5.3],[51.2,9.7]], gp:[[15.8,-61.85],[16.55,-61.0]], mq:[[14.38,-61.25],[14.9,-60.8]],
  gf:[[2.1,-54.6],[5.8,-51.6]], re:[[-21.4,55.2],[-20.85,55.85]], yt:[[-13.0,45.0],[-12.6,45.3]],
  nc:[[-22.8,163.5],[-19.5,168.2]], pf:[[-17.9,-149.65],[-17.45,-149.1]]
};
// indices tries par gravite : les mortels sont dessines en dernier (au-dessus)
const ORDER = D.map((_, i) => i).sort((a, b) => D[a][2] - D[b][2]);

const map = L.map("map", { preferCanvas: true, zoomSnap: 0.5 }).fitBounds(ZONES.metro);
const OSM_ATTR = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>';
const IGN_ATTR = '&copy; <a href="https://geoservices.ign.fr/">IGN Géoplateforme</a>';
const IGN = (couche, format) => "https://data.geopf.fr/wmts?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0"
  + "&LAYER=" + couche + "&STYLE=normal&TILEMATRIXSET=PM&FORMAT=" + format
  + "&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}";
const fonds = {
  "OpenStreetMap (gris)": L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png",
    { maxZoom: 19, attribution: OSM_ATTR, className: "fond-gris" }),
  "OpenStreetMap": L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png",
    { maxZoom: 19, attribution: OSM_ATTR }),
  "OpenStreetMap France": L.tileLayer("https://{s}.tile.openstreetmap.fr/osmfr/{z}/{x}/{y}.png",
    { maxZoom: 20, subdomains: "abc", attribution: OSM_ATTR + " &copy; OSM France" }),
  "Photo aérienne (IGN)": L.tileLayer(IGN("ORTHOIMAGERY.ORTHOPHOTOS", "image/jpeg"),
    { maxZoom: 20, maxNativeZoom: 19, attribution: IGN_ATTR }),
  "Plan IGN": L.tileLayer(IGN("GEOGRAPHICALGRIDSYSTEMS.PLANIGNV2", "image/png"),
    { maxZoom: 19, maxNativeZoom: 18, attribution: IGN_ATTR })
};
fonds["OpenStreetMap (gris)"].addTo(map);
L.control.layers(fonds, null, { position: "bottomleft" }).addTo(map);

const $ = id => document.getElementById(id);
// Codes officiels BAAC (ONISR, description des bases annuelles)
const METEO = {1: "normale", 2: "pluie légère", 3: "pluie forte", 4: "neige, grêle", 5: "brouillard, fumée",
  6: "vent fort, tempête", 7: "temps éblouissant", 8: "temps couvert", 9: "autre"};
const SITU = {0: "aucune", 1: "sur chaussée", 2: "sur bande d'arrêt d'urgence", 3: "sur accotement",
  4: "sur trottoir", 5: "sur piste cyclable", 6: "sur autre voie spéciale", 8: "autre"};
const CATV = {0: "Indéterminable", 1: "Bicyclette", 2: "Cyclomoteur < 50 cm3", 3: "Voiturette (quadricycle carrossé)",
  7: "Voiture (VL)", 10: "Utilitaire (VU, 1,5 à 3,5 t)", 13: "Poids lourd 3,5 à 7,5 t", 14: "Poids lourd > 7,5 t",
  15: "Poids lourd + remorque", 16: "Tracteur routier seul", 17: "Tracteur routier + semi-remorque",
  20: "Engin spécial", 21: "Tracteur agricole", 30: "Scooter < 50 cm3", 31: "Moto 50 à 125 cm3",
  32: "Scooter 50 à 125 cm3", 33: "Moto > 125 cm3", 34: "Scooter > 125 cm3", 35: "Quad léger ≤ 50 cm3",
  36: "Quad lourd > 50 cm3", 37: "Autobus", 38: "Autocar", 39: "Train", 40: "Tramway", 41: "3RM ≤ 50 cm3",
  42: "3RM 50 à 125 cm3", 43: "3RM > 125 cm3", 50: "EDP à moteur (trottinette…)", 60: "EDP sans moteur",
  80: "Vélo à assistance électrique", 99: "Autre véhicule"};
const OBSF = {0: "sans objet", 1: "véhicule en stationnement", 2: "arbre", 3: "glissière métallique",
  4: "glissière béton", 5: "autre glissière", 6: "bâtiment, mur, pile de pont",
  7: "support de signalisation ou borne d'appel", 8: "poteau", 9: "mobilier urbain", 10: "parapet",
  11: "îlot, refuge, borne haute", 12: "bordure de trottoir", 13: "fossé, talus, paroi rocheuse",
  14: "autre obstacle fixe sur chaussée", 15: "autre obstacle fixe sur trottoir ou accotement",
  16: "sortie de chaussée sans obstacle", 17: "buse, tête d'aqueduc"};
const MANV = {0: "inconnue", 1: "sans changement de direction", 2: "même sens, même file", 3: "entre 2 files",
  4: "en marche arrière", 5: "à contresens", 6: "en franchissant le terre-plein central",
  7: "dans le couloir bus, même sens", 8: "dans le couloir bus, sens inverse", 9: "en s'insérant",
  10: "demi-tour sur la chaussée", 11: "changeant de file à gauche", 12: "changeant de file à droite",
  13: "déporté à gauche", 14: "déporté à droite", 15: "tournant à gauche", 16: "tournant à droite",
  17: "dépassant à gauche", 18: "dépassant à droite", 19: "traversant la chaussée",
  20: "manœuvre de stationnement", 21: "manœuvre d'évitement", 22: "ouverture de porte",
  23: "arrêté (hors stationnement)", 24: "en stationnement (avec occupants)", 25: "circulant sur trottoir",
  26: "autre manœuvre"};
const MOTEUR = {0: "motorisation inconnue", 1: "thermique (hydrocarbures)", 2: "hybride électrique",
  3: "électrique", 4: "hydrogène", 5: "humaine", 6: "autre motorisation"};
const SECU = {0: "aucun équipement", 1: "ceinture", 2: "casque", 3: "dispositif enfant", 4: "gilet réfléchissant",
  5: "airbag 2RM/3RM", 6: "gants 2RM/3RM", 7: "gants + airbag 2RM/3RM", 8: "équipement non déterminable", 9: "autre équipement"};
const GRAVITE = {1: "indemne", 2: "tué", 3: "blessé hospitalisé", 4: "blessé léger"};
const GROUPES = ["Voiture", "Utilitaire (VU)", "Moto, scooter, 3RM, quad", "Vélo / VAE",
  "Trottinette / EDP", "Poids lourd, bus, car", "Voiturette", "Autre / indéterminé"];
const lib = (dico, code, defaut = "non renseigné") => dico[code] ?? (code < 0 ? defaut : "code " + code);

// Couleurs par type de route (palette categorielle validee daltonisme) et par gravite
const COUL = { 1: "#2a78d6", 2: "#eb6834", 3: "#1baf7a", 0: "#8a8984" };
const NOM_ROUTE = { 1: "Autoroute", 2: "Route hors agglomération", 3: "En agglomération", 0: "Type de route non renseigné" };
$("listeVeh").innerHTML = GROUPES.map((g, b) =>
  `<label><input type="checkbox" id="v${b}" checked> ${g} <span class="nb" id="nv${b}"></span></label>`).join("");
const masqueVeh = () => GROUPES.reduce((m, g, b) => m | ($("v" + b).checked ? 1 << b : 0), 0);
const OBSTACLES = ["Arbre", "Fossé, talus, paroi rocheuse", "Glissière de sécurité",
  "Mur, bâtiment, pile de pont, parapet", "Poteau, panneau, mobilier urbain",
  "Autre obstacle fixe (bordure, îlot, buse…)", "Véhicule en stationnement",
  "Sortie de chaussée sans obstacle", "Piéton", "Autre véhicule en circulation", "Animal",
  "Autre obstacle mobile", "Aucun obstacle renseigné"];
const titreObs = { 0: "Obstacles fixes", 8: "Obstacles mobiles", 12: "Autre" };
$("listeObs").innerHTML = OBSTACLES.map((o, b) => (titreObs[b] ? `<div class="sous">${titreObs[b]}</div>` : "")
  + `<label><input type="checkbox" id="o${b}" checked> ${o} <span class="nb" id="no${b}"></span></label>`).join("");
const masqueObs = () => OBSTACLES.reduce((m, o, b) => m | ($("o" + b).checked ? 1 << b : 0), 0);
// Creneau horaire : "de" inclus, "a" exclu ; 22 h -> 6 h passe minuit
for (let h = 0; h < 24; h++) $("hDe").add(new Option(String(h).padStart(2, "0") + ":00", h));
for (let h = 1; h <= 24; h++) $("hA").add(new Option(h === 24 ? "24:00" : String(h).padStart(2, "0") + ":00", h));
$("hDe").value = 0; $("hA").value = 24;
function creneau() {
  const de = +$("hDe").value, a = +$("hA").value;
  if ((de === 0 && a === 24) || de === a) return null;          // toute la journee
  return m => m >= 0 && (de < a ? m >= de * 60 && m < a * 60 : m >= de * 60 || m < a * 60);
}
document.querySelectorAll("a[data-h]").forEach(el => el.addEventListener("click", e => {
  e.preventDefault();
  const [de, a] = el.dataset.h.split("-").map(Number);
  $("hDe").value = de; $("hA").value = a;
  croix.redraw();
}));
const resume = (n, total) => n === total ? "tous" : n === 0 ? "aucun" : `${n} / ${total}`;
// Calque canvas : des milliers de croix sans ralentir la carte
const CrossLayer = L.Layer.extend({
  onAdd(m) {
    this._c = L.DomUtil.create("canvas", "leaflet-zoom-hide");
    this._c.style.position = "absolute";
    this._c.style.zIndex = 500;            // les croix restent au-dessus des stations
    m.getPanes().overlayPane.appendChild(this._c);
    m.on("moveend zoomend resize", this.redraw, this);
    this.redraw();
  },
  onRemove(m) { L.DomUtil.remove(this._c); m.off("moveend zoomend resize", this.redraw, this); },
  redraw() {
    const m = this._map, size = m.getSize(), dpr = window.devicePixelRatio || 1;
    const c = this._c, ctx = c.getContext("2d");
    L.DomUtil.setPosition(c, m.containerPointToLayerPoint([0, 0]));
    c.width = size.x * dpr; c.height = size.y * dpr;
    c.style.width = size.x + "px"; c.style.height = size.y + "px";
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const z = m.getZoom(), k = z >= 11 ? 1.6 : z >= 8 ? 1.25 : 1;
    const vis = []; let nAcc = 0, nTues = 0;
    const parRoute = { 0: 0, 1: 0, 2: 0, 3: 0 }, parVeh = GROUPES.map(() => 0), parObs = OBSTACLES.map(() => 0);
    const enCouleur = $("mode").value === "route";
    const grav = { 1: $("s1").checked, 2: $("s2").checked, 3: $("s3").checked };
    const route = { 0: $("t0").checked, 1: $("t1").checked, 2: $("t2").checked, 3: $("t3").checked };
    const seul = $("fSeul").checked, nuit = $("fNuit").checked, mv = masqueVeh(), mo = masqueObs();
    const dansCreneau = creneau();
    for (const i of ORDER) {
      const r = D[i];
      if (!grav[r[2]] || (seul && !r[5]) || (nuit && !r[6])) continue;
      if (dansCreneau && !dansCreneau(r[21])) continue;
      const okRoute = route[r[14]], okVeh = (r[18] & mv) !== 0, okObs = (r[20] & mo) !== 0;
      if (okVeh && okObs) parRoute[r[14]]++;      // compteurs : sans leur propre filtre
      if (okRoute && okObs) for (let b = 0; b < 8; b++) if (r[18] & (1 << b)) parVeh[b]++;
      if (okRoute && okVeh) for (let b = 0; b < 13; b++) if (r[20] & (1 << b)) parObs[b]++;
      if (!okRoute || !okVeh || !okObs) continue;
      nAcc++; nTues += r[3];
      const p = m.latLngToContainerPoint([r[0], r[1]]);
      if (p.x < -10 || p.y < -10 || p.x > size.x + 10 || p.y > size.y + 10) continue;
      vis.push([p.x, p.y, i]);
      const s = (r[2] === 3 ? 4.5 : r[2] === 2 ? 3.2 : 2.6) * k;
      ctx.beginPath();
      ctx.moveTo(p.x - s, p.y - s); ctx.lineTo(p.x + s, p.y + s);
      ctx.moveTo(p.x + s, p.y - s); ctx.lineTo(p.x - s, p.y + s);
      if (r[2] === 3) {                       // halo blanc pour les mortels
        ctx.globalAlpha = 1;
        ctx.strokeStyle = "rgba(255,255,255,.9)"; ctx.lineWidth = 4.2 * Math.min(k, 1.3); ctx.stroke();
        ctx.strokeStyle = enCouleur ? COUL[r[14]] : "#c81e1e"; ctx.lineWidth = 2.2 * Math.min(k, 1.3);
      } else if (enCouleur) {
        ctx.globalAlpha = r[2] === 2 ? 0.85 : 0.5;
        ctx.strokeStyle = COUL[r[14]]; ctx.lineWidth = r[2] === 2 ? 1.6 : 1.2;
      } else {
        ctx.globalAlpha = 1;
        ctx.strokeStyle = r[2] === 2 ? "rgba(227,73,72,.85)" : "rgba(227,73,72,.5)";
        ctx.lineWidth = r[2] === 2 ? 1.6 : 1.2;
      }
      ctx.stroke();
    }
    ctx.globalAlpha = 1;
    this._vis = vis;
    for (const t of [0, 1, 2, 3]) $("n" + t).textContent = parRoute[t].toLocaleString("fr-FR");
    parVeh.forEach((n, b) => { $("nv" + b).textContent = n.toLocaleString("fr-FR"); });
    parObs.forEach((n, b) => { $("no" + b).textContent = n.toLocaleString("fr-FR"); });
    const coches = (liste, p) => liste.filter((x, b) => $(p + b).checked).length;
    $("resVeh").textContent = resume(coches(GROUPES, "v"), GROUPES.length);
    $("resObs").textContent = resume(coches(OBSTACLES, "o"), OBSTACLES.length);
    $("resHeure").textContent = dansCreneau ? "" : "toute la journée";
    $("lab0").style.display = parRoute[0] || !$("t0").checked ? "" : "none";
    $("panel").classList.toggle("mode-grav", !enCouleur);
    $("nAcc").textContent = nAcc.toLocaleString("fr-FR");
    $("nTues").textContent = nTues.toLocaleString("fr-FR");
  },
  nearest(pt, rayon) {
    let best = null, d2min = rayon * rayon;
    for (const [x, y, i] of this._vis || []) {
      const d2 = (x - pt.x) ** 2 + (y - pt.y) ** 2;
      if (d2 <= d2min) { d2min = d2; best = i; }   // a distance egale, le dernier (le plus grave) gagne
    }
    return best;
  }
});
const croix = new CrossLayer().addTo(map);

// --- Secours autour de l'accident : recherche EN DIRECT au clic --------------
// Casernes : BD TOPO de l'IGN (service WFS). Urgences : OpenStreetMap (Overpass).
// Trajets : API d'itineraire de l'IGN. Aucune cle, aucune donnee pre-telechargee.
const esc = s => String(s).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const fmt = (x, u) => x.toLocaleString("fr-FR", { maximumFractionDigits: 1 }) + " " + u;
// Carte ouverte via le serveur local de carte_accidents.py : les requetes passent par lui
// (aucun blocage du navigateur). Ouverte comme simple fichier : requetes directes.
const VIA_SERVEUR = ["localhost", "127.0.0.1"].includes(location.hostname) && location.protocol === "http:";
const WFS = VIA_SERVEUR ? "/proxy/wfs" : "https://data.geopf.fr/wfs/ows";
const IGN_ROUTE = VIA_SERVEUR ? "/proxy/itineraire" : "https://data.geopf.fr/navigation/itineraire";
const IGN_CAP = VIA_SERVEUR ? "/proxy/navcap" : "https://data.geopf.fr/navigation/getcapabilities";
const OSRM = VIA_SERVEUR ? "/proxy/osrm" : "https://router.project-osrm.org/route/v1/driving";
const OVERPASS = VIA_SERVEUR ? ["/proxy/overpass0", "/proxy/overpass1", "/proxy/overpass2"]
  : ["https://overpass-api.de/api/interpreter", "https://overpass.private.coffee/api/interpreter",
     "https://maps.mail.ru/osm/tools/overpass/api/interpreter"];
const memoire = L.layerGroup().addTo(map);  // trajets et secours GARDES sur la carte
const dessins = new Map();                  // accident -> son calque de trajets
const etats = new Map();                    // accident -> resultats (re-clic instantane)
let ouvert = null;                          // accident dont la fenetre est ouverte
map.on("popupclose", () => { ouvert = null; });
let panneOverpass = 0;                      // Overpass sature : on l'evite 10 minutes
let prochainIGN = 0;                        // limite IGN : 5 requetes par seconde au total
async function tourIGN(ecart = 230) {
  const t = Math.max(Date.now(), prochainIGN);
  prochainIGN = t + ecart;
  if (t > Date.now()) await pause(t - Date.now());
}
const pause = ms => new Promise(ok => setTimeout(ok, ms));

async function getJSON(url, delai = 12000) {
  if (url.startsWith(WFS)) await tourIGN();
  const ctl = new AbortController(), t = setTimeout(() => ctl.abort(), delai);
  try {
    let rep;
    try { rep = await fetch(url, { signal: ctl.signal }); }
    catch (err) {
      if (err.name === "AbortError") throw new Error(`pas de réponse en ${delai / 1000} s`);
      throw new Error(VIA_SERVEUR ? "serveur local injoignable (le terminal est-il toujours ouvert ?)"
        : "bloqué par le navigateur : ouvrez la carte via carte_accidents.py (serveur local)");
    }
    if (!rep.ok) {
      let txt = "";
      try { txt = (await rep.text()).replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim().slice(0, 120); } catch (e) {}
      throw new Error(`HTTP ${rep.status}${txt ? " : " + txt : ""}`);
    }
    return await rep.json();
  } finally { clearTimeout(t); }
}
function kmVol(a, b) {
  const R = Math.PI / 180, dLa = (b.lat - a.lat) * R, dLo = (b.lon - a.lon) * R;
  const h = Math.sin(dLa / 2) ** 2 + Math.cos(a.lat * R) * Math.cos(b.lat * R) * Math.sin(dLo / 2) ** 2;
  return 12742 * Math.asin(Math.sqrt(Math.min(1, h)));
}
function cadre(lat, lon, km) {
  const dLa = km / 111, dLo = km / (111 * Math.cos(lat * Math.PI / 180));
  return [lat - dLa, lon - dLo, lat + dLa, lon + dLo];      // sud, ouest, nord, est
}
function centre(g) {                         // point moyen d'une geometrie GeoJSON
  const pts = [];
  const go = c => typeof c[0] === "number" ? pts.push(c) : c.forEach(go);
  if (g && g.coordinates) go(g.coordinates);
  if (!pts.length) return null;
  return [pts.reduce((s, p) => s + p[0], 0) / pts.length, pts.reduce((s, p) => s + p[1], 0) / pts.length];
}
function versPoints(feats, ici, nomDefaut) {
  return feats.map(f => {
    const pr = f.properties || {};
    if (pr.etat_de_l_objet && pr.etat_de_l_objet !== "En service") return null;
    const c = centre(f.geometry);
    if (!c) return null;
    // ordre des axes selon le service : on garde l'interpretation proche de l'accident
    const p1 = { lat: c[0], lon: c[1] }, p2 = { lat: c[1], lon: c[0] };
    const p = kmVol(p1, ici) <= kmVol(p2, ici) ? p1 : p2;
    return { ...p, nom: pr.toponyme || nomDefaut };
  }).filter(Boolean);
}
async function wfsIGN(ici, km, conditionsXML, conditionCQL, nomDefaut) {
  const [s, w, n, e] = cadre(ici.lat, ici.lon, km);
  const base = { SERVICE: "WFS", VERSION: "2.0.0", REQUEST: "GetFeature",
    TYPENAMES: "BDTOPO_V3:zone_d_activite_ou_d_interet", OUTPUTFORMAT: "application/json", COUNT: "300" };
  const xml = '<fes:Filter xmlns:fes="http://www.opengis.net/fes/2.0" xmlns:gml="http://www.opengis.net/gml/3.2"><fes:And>'
    + conditionsXML + '<fes:BBOX><gml:Envelope srsName="urn:ogc:def:crs:EPSG::4326">'
    + `<gml:lowerCorner>${s} ${w}</gml:lowerCorner><gml:upperCorner>${n} ${e}</gml:upperCorner>`
    + "</gml:Envelope></fes:BBOX></fes:And></fes:Filter>";
  try {
    const j = await getJSON(WFS + "?" + new URLSearchParams({ ...base, FILTER: xml }));
    return versPoints(j.features || [], ici, nomDefaut);
  } catch (err) {                            // variante CQL si le filtre XML est refuse
    const cql = `${conditionCQL} AND BBOX(geometrie,${w},${s},${e},${n})`;
    const j = await getJSON(WFS + "?" + new URLSearchParams({ ...base, CQL_FILTER: cql }));
    return versPoints(j.features || [], ici, nomDefaut);
  }
}
let testOSM = null;                         // test de disponibilite en cours
async function overpass(requete, suivi) {
  if (testOSM) await testOSM.catch(() => {});  // on attend son verdict plutot que doubler
  if (Date.now() - panneOverpass < 10 * 60e3) throw new Error("OpenStreetMap saturé (évité 10 min)");
  suivi && suivi("OpenStreetMap…");
  try {
    return await Promise.any(OVERPASS.map(url =>
      getJSON(url + "?data=" + encodeURIComponent(requete), 9000).then(j => j.elements || [])));
  } catch (err) {
    panneOverpass = Date.now();
    throw new Error("OpenStreetMap indisponible (" + (err.errors ? err.errors[0].message : err.message) + ")");
  }
}
const osmPoints = (els, nomDefaut) => els.map(el => {
  const lat = el.lat ?? el.center?.lat, lon = el.lon ?? el.center?.lon;
  return lat == null ? null : { lat, lon, nom: el.tags?.name || nomDefaut };
}).filter(Boolean);
function plusProches(liste, ici, n) {
  const vus = new Set();
  return liste.map(c => ({ ...c, vol: kmVol(c, ici) }))
    .sort((a, b) => a.vol - b.vol)
    .filter(c => { const k = c.lat.toFixed(4) + c.lon.toFixed(4); if (vus.has(k)) return false; vus.add(k); return true; })
    .slice(0, n);
}
async function chercherCasernes(ici, suivi) {
  let liste = [], source = "IGN BD TOPO", erreurIGN = "";
  for (const km of [15, 35, 60]) {           // on elargit tant qu'on a moins de 3 casernes
    suivi(`IGN, rayon ${km} km…`);
    try {
      liste = await wfsIGN(ici, km,
        "<fes:PropertyIsEqualTo><fes:ValueReference>nature</fes:ValueReference>"
        + "<fes:Literal>Caserne de pompiers</fes:Literal></fes:PropertyIsEqualTo>",
        "nature='Caserne de pompiers'", "Caserne de pompiers");
      source = "IGN BD TOPO";
    } catch (err) {
      erreurIGN = err.message;
      try {
        liste = osmPoints(await overpass(`[out:json][timeout:25];nwr["amenity"="fire_station"]`
          + `(around:${km * 1000},${ici.lat},${ici.lon});out center tags;`, suivi), "Caserne");
      } catch (err2) { throw new Error("IGN : " + erreurIGN + " ; " + err2.message); }
      source = "OpenStreetMap";
    }
    if (liste.length >= 3) break;
  }
  return { source, liste: plusProches(liste, ici, 4) };
}
async function chercherUrgences(ici, suivi) {
  const ign = wfsIGN(ici, 50,
    "<fes:PropertyIsEqualTo><fes:ValueReference>categorie</fes:ValueReference><fes:Literal>Santé</fes:Literal></fes:PropertyIsEqualTo>"
    + '<fes:PropertyIsLike wildCard="*" singleChar="." escapeChar="!"><fes:ValueReference>nature</fes:ValueReference>'
    + "<fes:Literal>*pital*</fes:Literal></fes:PropertyIsLike>",
    "categorie='Santé' AND nature LIKE '%pital%'", "Hôpital")
    .then(l => ({ source: "IGN BD TOPO, hôpitaux (urgences non vérifiées)", liste: plusProches(l, ici, 3) }));
  const osm = (async () => {
    for (const km of [50, 100]) {
      const els = await overpass(`[out:json][timeout:20];(`
        + `nwr["amenity"="hospital"]["emergency"="yes"](around:${km * 1000},${ici.lat},${ici.lon});`
        + `nwr["healthcare"="hospital"]["emergency"="yes"](around:${km * 1000},${ici.lat},${ici.lon}););out center tags;`, suivi);
      const liste = osmPoints(els, "Hôpital (urgences)");
      if (liste.length) return { source: "OpenStreetMap, hôpitaux avec urgences", liste: plusProches(liste, ici, 3) };
    }
    throw new Error("aucun hôpital avec urgences dans OpenStreetMap");
  })();
  ign.catch(() => {}); osm.catch(() => {});         // evite les erreurs non traitees
  try {
    return await Promise.race([osm, pause(5000).then(() => { throw new Error("OpenStreetMap trop lent"); })]);
  } catch (errOSM) {
    suivi("OpenStreetMap ne répond pas, hôpitaux de l'IGN…");
    try { return await ign; }
    catch (errIGN) { throw new Error(errOSM.message + " ; IGN : " + errIGN.message); }
  }
}
// Reseaux de l'IGN, du plus rapide au plus lent ; on garde ceux que le service annonce
let RESEAUX = ["bdtopo-osrm", "bdtopo-valhalla", "bdtopo-pgr"];
const capacites = fetch(IGN_CAP).then(rep => rep.text()).then(txt => {
  const dispo = RESEAUX.filter(r => txt.includes(r));
  if (dispo.length) RESEAUX = dispo;
}).catch(() => {});
// Test d'OpenStreetMap a l'ouverture : s'il est sature, le 1er clic n'attend pas
testOSM = overpass("[out:json][timeout:5];node(1);out ids;").finally(() => { testOSM = null; });
testOSM.catch(() => {});
let routeSimple = false;                    // le service a refuse les options : on s'en passe
function lireReponse(j, dep, arr) {
  // Unites : celles annoncees par le service, sinon les plus vraisemblables
  const vol = kmVol(dep, arr), d = +j.distance, t = +j.duration;
  const du = String(j.distanceUnit || "").toLowerCase(), tu = String(j.timeUnit || "").toLowerCase();
  const km = du.startsWith("k") ? d : du.startsWith("m") ? d / 1000
    : (d / 1000 >= vol * 0.8 ? d / 1000 : d);
  const candidats = tu.startsWith("h") ? [t * 60] : tu.startsWith("s") ? [t / 60] : tu.startsWith("m") ? [t]
    : [t, t * 60, t / 60];
  const min = candidats.find(m => m > 0 && km / (m / 60) > 5 && km / (m / 60) < 160) ?? candidats[0];
  let geom = j.geometry;
  if (typeof geom === "string") { try { geom = JSON.parse(geom); } catch (e) { geom = null; } }
  if (!isFinite(km) || !isFinite(min)) throw new Error("réponse sans distance ni durée");
  return { km, min, geom: geom && geom.type ? geom : null };
}
async function routeIGN(dep, arr) {
  await capacites;
  let derniere = "aucun réseau disponible";
  for (const res of RESEAUX.slice()) {
    const base = { resource: res, start: `${dep.lon},${dep.lat}`, end: `${arr.lon},${arr.lat}` };
    const options = { ...base, profile: "car", optimization: "fastest", geometryFormat: "geojson" };
    try {
      await tourIGN();
      let j;
      try { j = await getJSON(IGN_ROUTE + "?" + new URLSearchParams(routeSimple ? base : options), 15000); }
      catch (err) {
        if (/resource/i.test(err.message) || routeSimple || !/HTTP 4/.test(err.message)) throw err;
        routeSimple = true;                   // options refusees : seuls parametres obligatoires
        await tourIGN();
        j = await getJSON(IGN_ROUTE + "?" + new URLSearchParams(base), 15000);
      }
      return { ...lireReponse(j, dep, arr), source: "IGN (" + res.replace("bdtopo-", "") + ")" };
    } catch (err) {
      derniere = err.message;
      if (/resource/i.test(err.message)) {   // reseau inexistant : on ne le redemandera plus
        RESEAUX = RESEAUX.filter(x => x !== res);
        continue;
      }
      throw err;
    }
  }
  throw new Error("IGN : " + derniere);
}
let prochainOSRM = 0;                       // serveur de demonstration OSRM : 1 requete / s
async function routeOSRM(dep, arr) {
  const t = Math.max(Date.now(), prochainOSRM);
  prochainOSRM = t + 1100;
  if (t > Date.now()) await pause(t - Date.now());
  const j = await getJSON(`${OSRM}/${dep.lon},${dep.lat};${arr.lon},${arr.lat}`
    + "?overview=full&geometries=geojson", 12000);
  if (!j.routes || !j.routes.length) throw new Error("OSRM : aucun trajet");
  return { km: j.routes[0].distance / 1000, min: j.routes[0].duration / 60, geom: j.routes[0].geometry,
           source: "OSRM (OpenStreetMap)" };
}
let ignEnPanne = 0;
async function trajet(dep, arr) {          // IGN d'abord, OSRM si l'IGN ne repond pas
  if (Date.now() - ignEnPanne > 5 * 60e3) {
    try { return await routeIGN(dep, arr); }
    catch (err) { if (!/HTTP 4/.test(err.message) || /resource|réseau/i.test(err.message)) ignEnPanne = Date.now(); }
  }
  return routeOSRM(dep, arr);
}
const meilleur = g => {
  let k = null;
  g.liste.forEach((c, i) => { if (typeof c.min === "number" && (k === null || c.min < g.liste[k].min)) k = i; });
  return k;
};
function blocSecours(etat) {
  const groupe = (g, cle, titre) => {
    if (!g || !g.liste.length) return `<div><b>${titre}</b> : ${esc(etat.etape[cle] || "")}</div>`;
    const k = meilleur(g);
    return `<div><b>${titre}</b> <span class="note">(${esc(g.source)})</span><br>` + g.liste.map((c, i) => {
      const t = c.min === undefined ? "calcul du trajet…" : c.min === null ? "trajet indisponible"
        : `<b>${Math.round(c.min)} min</b> par la route (${fmt(c.km, "km")})`;
      return `${i === k ? "★" : "·"} ${esc(c.nom)} — ${t}`;
    }).join("<br>") + "</div>";
  };
  const enCours = etat.fini ? "" : `<div class="note">⏳ recherche en cours… ${Math.round((Date.now() - etat.debut) / 1000)} s</div>`;
  const routes = etat.etape.route ? `<div class="note">Trajets : ${esc(etat.etape.route)}</div>`
    : etat.srcRoute ? `<div class="note">Trajets calculés par : ${esc(etat.srcRoute)}</div>` : "";
  return '<div class="sec">' + enCours + groupe(etat.cas, "cas", "Casernes autour")
    + '<div style="height:6px"></div>' + groupe(etat.urg, "urg", "Urgences / SMUR autour") + routes
    + '<div class="note">★ le plus rapide par la route (voiture, sans délai de départ des secours)</div></div>';
}
function dessiner(r, etat, i) {
  let traits = dessins.get(i);
  if (!traits) { traits = L.layerGroup().addTo(memoire); dessins.set(i, traits); }
  traits.clearLayers();
  majCompteur();
  const ici = { lat: r[0], lon: r[1] };
  [[etat.cas, "#52514e", 4], [etat.urg, "#2a78d6", 6]].forEach(([g, c, rayon]) => {
    if (!g) return;
    const k = meilleur(g);
    g.liste.forEach((p, i) => {
      L.circleMarker([p.lat, p.lon], { radius: i === k ? rayon + 1.5 : rayon - 1, color: "#fff", weight: 1.5,
        fillColor: c, fillOpacity: i === k ? 1 : 0.55 })
        .bindTooltip(esc(p.nom) + (typeof p.min === "number" ? ` — ${Math.round(p.min)} min` : "")).addTo(traits);
    });
    const best = k !== null ? g.liste[k] : g.liste[0];
    if (!best) return;
    if (k !== null && best.geom) L.geoJSON(best.geom, { style: { color: c, weight: 4, opacity: 0.85 }, interactive: false }).addTo(traits);
    else L.polyline([[ici.lat, ici.lon], [best.lat, best.lon]], { color: c, weight: 2, dashArray: "6 6", interactive: false }).addTo(traits);
  });
}
async function chercherSecours(r, i, etat) {
  const ici = { lat: r[0], lon: r[1] };
  const maj = () => { if (ouvert && ouvert.i === i) ouvert.maj(); };
  if (etat.lance) {                          // deja cherche : on redessine si besoin
    if (etat.fini && (etat.cas || etat.urg)) dessiner(r, etat, i);
    return;
  }
  etat.lance = true;
  etat.debut = Date.now();
  const minuteur = setInterval(() => { if (etat.fini) clearInterval(minuteur); else maj(); }, 1000);
  const suivi = k => txt => { if (!(etat[k] && etat[k].liste.length)) { etat.etape[k] = txt; maj(); } };
  let erreurRoute = "";
  const chaine = async (cle, chercher, vide) => {   // recherche puis trajets, sans attendre l'autre
    try { etat[cle] = await chercher(ici, suivi(cle)); }
    catch (err) { etat[cle] = null; etat.etape[cle] = "recherche impossible — " + err.message; maj(); return; }
    etat.etape[cle] = vide;
    maj(); dessiner(r, etat, i);
    for (const c of etat[cle].liste) {             // file d'attente IGN commune (5 / s)
      try { const j = await trajet(c, ici); c.min = j.min; c.km = j.km; c.geom = j.geom; etat.srcRoute = j.source; }
      catch (err) { c.min = null; erreurRoute = err.message; }
      maj(); dessiner(r, etat, i);
    }
  };
  await Promise.all([chaine("cas", chercherCasernes, "aucune caserne trouvée à moins de 60 km"),
                     chaine("urg", chercherUrgences, "aucun service d'urgences trouvé à moins de 50 km")]);
  const tous = [...(etat.cas ? etat.cas.liste : []), ...(etat.urg ? etat.urg.liste : [])];
  if (tous.length && tous.every(c => c.min === null)) etat.etape.route = "indisponibles — " + erreurRoute;
  etat.fini = true;
  clearInterval(minuteur);
  maj();
  if (!etat.cas && !etat.urg) etats.delete(i);     // echec complet : nouvel essai au prochain clic
}
function majCompteur() {
  const n = dessins.size;
  $("nbAnalyses").textContent = n ? `${n} accident${n > 1 ? "s" : ""} analysé${n > 1 ? "s" : ""} sur la carte` : "";
  $("effacer").style.display = n ? "" : "none";
}
// Details BAAC de l'accident : conditions, vehicules et usagers
function detailsAccident(r, etat) {
  // Conditions : on n'affiche que ce qui est renseigne
  const cond = [
    r[15] > 0 ? `<span class="lib">Météo :</span> ${esc(lib(METEO, r[15]))}` : null,
    r[16] > 0 ? `<span class="lib">Lieu :</span> ${esc(lib(SITU, r[16]))}` : null,
    r[17] > 0 ? `<span class="lib">Vitesse max. :</span> ${r[17]} km/h` : null
  ].filter(Boolean);
  const blocCond = cond.length ? `<div class="det">${cond.join(" · ")}</div>` : "";
  const V = r[19] || [];
  if (!etat.ouverts) etat.ouverts = new Set(V.length <= 3 ? V.map((v, k) => String(k)) : []);
  // Bilan de tous les usagers
  const tous = V.flatMap(v => v[7]), n = g => tous.filter(u => u[2] === g).length;
  const pl = (x, mot) => `${x} ${mot}${x > 1 ? "s" : ""}`;
  const bilan = [n(2) && `<b class="t">${pl(n(2), "tué")}</b>`, n(3) && `<b>${pl(n(3), "blessé")} hospitalisé${n(3) > 1 ? "s" : ""}</b>`,
    n(4) && `${pl(n(4), "blessé")} léger${n(4) > 1 ? "s" : ""}`, n(1) && `${n(1)} indemne${n(1) > 1 ? "s" : ""}`].filter(Boolean);
  const equip = secu => {                    // "aucun" et "non determinable" seulement s'ils sont seuls
    const vrais = secu.filter(x => x >= 1 && x !== 8);
    return vrais.length ? vrais.map(x => lib(SECU, x)).join(", ") : secu.includes(0) ? "sans équipement" : "";
  };
  const ligne = u => {
    const [catu, place, gr, age, sexe, ...secu] = u;
    const role = catu === 1 ? "Conducteur" : catu === 2 ? "Passager" : catu === 3 ? "Piéton heurté" : "Usager";
    const qui = [age >= 0 ? age + " ans" : null, sexe === 1 ? "H" : sexe === 2 ? "F" : null].filter(Boolean).join(", ");
    const g = lib(GRAVITE, gr, "gravité inconnue");
    const eq = equip(secu);
    return `<div class="u">· ${role}${qui ? " (" + qui + ")" : ""} — `
      + (gr === 2 ? `<b class="t">${g}</b>` : gr === 3 ? `<b>${g}</b>` : g)
      + (eq ? ` <span class="lib">· ${esc(eq)}</span>` : "")
      + (catu === 2 && place > 0 ? ` <span class="lib">· place ${place}</span>` : "") + "</div>";
  };
  const CHOC_PHRASE = {1: "choc à l'avant", 2: "choc à l'avant droit", 3: "choc à l'avant gauche",
    4: "choc à l'arrière", 5: "choc à l'arrière droit", 6: "choc à l'arrière gauche",
    7: "choc sur le côté droit", 8: "choc sur le côté gauche", 9: "tonneaux (chocs multiples)"};
  const OBSM_PHRASE = {1: "a heurté un piéton", 2: "collision avec un véhicule", 4: "collision avec un véhicule sur rail",
    5: "a heurté un animal domestique", 6: "a heurté un animal sauvage", 9: "a heurté un obstacle mobile"};
  const vehs = V.map((v, k) => {
    const [lettre, catv, obs, obsm, choc, manv, motor, users] = v;
    // Une phrase courte avec seulement les informations utiles
    const faits = [
      manv > 0 ? lib(MANV, manv) : null,
      CHOC_PHRASE[choc] || null,
      OBSM_PHRASE[obsm] || null,
      obs > 0 ? (obs === 16 ? "sortie de chaussée sans obstacle" : "obstacle : " + lib(OBSF, obs)) : null
    ].filter(Boolean);
    if (faits.length) faits[0] = faits[0][0].toUpperCase() + faits[0].slice(1);
    const moteur = motor > 0 && motor !== 5 ? ` <span class="lib">· ${esc(lib(MOTEUR, motor))}</span>` : "";
    // Beaucoup d'occupants (bus, car) : on detaille conducteur, pietons, tues et blesses graves
    const cles = users.length > 6 ? users.filter(u => u[0] !== 2 || u[2] === 2 || u[2] === 3) : users;
    const autres = users.filter(u => !cles.includes(u));
    let resteHTML = "";
    if (autres.length) {
      const c = g => autres.filter(u => u[2] === g).length;
      const res = [c(4) && `${c(4)} blessé${c(4) > 1 ? "s" : ""} léger${c(4) > 1 ? "s" : ""}`, c(1) && `${c(1)} indemne${c(1) > 1 ? "s" : ""}`]
        .filter(Boolean).join(", ");
      const kp = k + "p";
      resteHTML = `<details data-k="${kp}"${etat.ouverts.has(kp) ? " open" : ""} class="u"><summary>+ ${autres.length} autres passagers`
        + `${res ? " : " + res : ""}</summary>${autres.map(ligne).join("")}</details>`;
    }
    return `<details data-k="${k}"${etat.ouverts.has(String(k)) ? " open" : ""}><summary><b>${esc(lettre)} — ${esc(lib(CATV, catv, "véhicule"))}</b>${moteur}</summary>`
      + (faits.length ? `<div>${esc(faits.join(" · "))}</div>` : "")
      + (users.length ? cles.map(ligne).join("") + resteHTML : '<div class="u lib">aucun usager enregistré</div>')
      + "</details>";
  }).join("");
  return blocCond + `<div class="det"><b>${pl(V.length, "véhicule")}, ${pl(tous.length, "usager")}</b>`
    + (bilan.length ? `<br>${bilan.join(" · ")}` : "") + vehs + "</div>";
}
// Liens externes : aucune cle API necessaire (Google Maps URLs, Mapillary)
function liens(r, etat) {
  const [lat, lon] = r, ll = lat + "%2C" + lon;
  const a = (url, txt) => `<a href="${url}" target="_blank" rel="noopener">${txt}</a>`;
  const trajet = (g, txt) => {
    if (!g || !g.liste.length) return "";
    const k = meilleur(g), p = g.liste[k === null ? 0 : k];
    return a("https://www.google.com/maps/dir/?api=1&travelmode=driving"
      + `&origin=${p.lat}%2C${p.lon}&destination=${ll}`, txt);
  };
  const dir = trajet(etat.cas, "Trajet caserne → accident") + trajet(etat.urg, "Trajet urgences → accident");
  return '<div class="liens">'
    + a("https://www.google.com/maps/@?api=1&map_action=pano&viewpoint=" + ll, "Street View")
    + a("https://www.google.com/maps/search/?api=1&query=" + ll, "Google Maps")
    + a(`https://www.mapillary.com/app/?lat=${lat}&lng=${lon}&z=17`, "Mapillary")
    + "</div>" + (dir ? '<div class="liens">' + dir
      + '<a href="#" onclick="cadrer();return false;">Voir les trajets</a></div>' : "");
}
function cadrer() {                          // zoome pour voir accident, secours et trajets
  const traits = ouvert && dessins.get(ouvert.i);
  if (!traits) return;
  const b = L.featureGroup(traits.getLayers()).getBounds();
  if (b.isValid()) map.fitBounds(b.pad(0.25), { paddingTopLeft: [20, 300] });
}
map.on("click", e => {
  const i = croix.nearest(e.containerPoint, 9);
  if (i === null) return;
  const r = D[i];
  const lignes = [
    `<b>${esc(r[10])}</b>`,
    r[13] ? esc(r[13]) : null,
    `Département ${esc(r[11])}${r[12] ? " · code commune INSEE " + esc(r[12]) : ""}`,
    `<span style="color:${COUL[r[14]]}">■</span> <b>${esc(NOM_ROUTE[r[14]])}</b>`
      + (r[14] !== 1 ? ` · ${esc(CATR[r[9]] || "route non renseignée")}` : ""),
    esc(LUM[r[7]] || "Luminosité non renseignée"),
    `<b class="t">${r[3]} tué${r[3] > 1 ? "s" : ""}</b> · ${r[4]} blessé${r[4] > 1 ? "s" : ""} hospitalisé${r[4] > 1 ? "s" : ""}`,
    r[5] ? "Véhicule seul, hors agglomération" : null
  ].filter(Boolean).join("<br>");
  if (!etats.has(i)) etats.set(i, { etape: { cas: "démarrage…", urg: "démarrage…" } });
  const etat = etats.get(i);
  const popup = L.popup({ maxWidth: 400, minWidth: 300, maxHeight: 480 }).setLatLng([r[0], r[1]]);
  const maj = () => {                         // garde le defilement et les volets ouverts
    const n = popup._contentNode, y = n ? n.scrollTop : 0;
    popup.setContent(lignes + detailsAccident(r, etat) + blocSecours(etat) + liens(r, etat));
    const n2 = popup._contentNode;
    if (!n2) return;
    n2.scrollTop = y;
    n2.querySelectorAll("details[data-k]").forEach(d => d.addEventListener("toggle", () => {
      d.open ? etat.ouverts.add(d.dataset.k) : etat.ouverts.delete(d.dataset.k);
    }));
  };
  maj();
  popup.openOn(map);
  ouvert = { i, maj };
  chercherSecours(r, i, etat);
});
map.on("mousemove", e => {
  map.getContainer().style.cursor = croix.nearest(e.containerPoint, 9) !== null ? "pointer" : "";
});
["s1", "s2", "s3", "fSeul", "fNuit", "t0", "t1", "t2", "t3", "mode", "hDe", "hA",
 ...GROUPES.map((g, b) => "v" + b), ...OBSTACLES.map((o, b) => "o" + b)]
  .forEach(id => $(id).addEventListener("change", () => croix.redraw()));
[["vTout", "v", GROUPES, true], ["vAucun", "v", GROUPES, false],
 ["oTout", "o", OBSTACLES, true], ["oAucun", "o", OBSTACLES, false]]
  .forEach(([id, p, liste, val]) => $(id).addEventListener("click", e => {
    e.preventDefault();
    liste.forEach((x, b) => { $(p + b).checked = val; });
    croix.redraw();
  }));
$("zone").addEventListener("change", e => map.fitBounds(ZONES[e.target.value]));
$("toggle").addEventListener("click", () => $("panel").classList.toggle("closed"));
$("effacer").addEventListener("click", () => {     // les resultats restent en memoire
  memoire.clearLayers(); dessins.clear(); majCompteur();
});
</script>
</body>
</html>
"""

RELAIS = {"/proxy/wfs": "https://data.geopf.fr/wfs/ows",
          "/proxy/itineraire": "https://data.geopf.fr/navigation/itineraire",
          "/proxy/navcap": "https://data.geopf.fr/navigation/getcapabilities",
          "/proxy/osrm": "https://router.project-osrm.org/route/v1/driving",
          "/proxy/overpass0": "https://overpass-api.de/api/interpreter",
          "/proxy/overpass1": "https://overpass.private.coffee/api/interpreter",
          "/proxy/overpass2": "https://maps.mail.ru/osm/tools/overpass/api/interpreter"}


def servir(dossier, nom_page, port):
    """Sert la carte sur http://localhost et relaie ses requetes vers l'IGN et
    OpenStreetMap : le navigateur ne bloque plus rien (pas de probleme CORS)."""

    class Gestion(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=str(dossier), **k)

        def do_GET(self):
            chemin, _, requete = self.path.partition("?")
            cle = next((c for c in RELAIS if chemin == c or chemin.startswith(c + "/")), None)
            if cle is None:
                return super().do_GET()
            url = RELAIS[cle] + chemin[len(cle):] + ("?" + requete if requete else "")
            chemin = cle
            t0 = time.time()
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "hackathon-renault-baac/1.0"})
                delai = 9 if "overpass" in chemin else 14   # sous le delai du navigateur
                with urllib.request.urlopen(req, timeout=delai) as rep:
                    corps, code = rep.read(), rep.status
                    typ = rep.headers.get("Content-Type", "application/json")
            except urllib.error.HTTPError as e:
                corps, code, typ = e.read(), e.code, e.headers.get("Content-Type", "text/plain")
            except Exception as e:
                corps, code, typ = f"{e!r}".encode(), 504, "text/plain"
            detail = ""
            if code >= 400:                   # message du service, pour comprendre le refus
                detail = re.sub(r"<[^>]+>|\s+", " ", corps[:300].decode("utf-8", "replace")).strip()[:140]
                if "timed out" in detail or "Timeout" in detail:
                    detail = "delai depasse (serveur sature)"
            print(f"  [{time.strftime('%H:%M:%S')}] {chemin.replace('/proxy/', ''):11s} "
                  f"-> {code}  ({time.time() - t0:.1f} s)" + (f"  {detail}" if detail else ""))
            try:
                self.send_response(code)
                self.send_header("Content-Type", typ)
                self.send_header("Content-Length", str(len(corps)))
                self.end_headers()
                self.wfile.write(corps)
            except OSError:
                pass                          # le navigateur a abandonne la requete

        def log_message(self, *args):         # silence pour les fichiers ordinaires
            pass

    for p in range(port, port + 20):
        try:
            serveur = http.server.ThreadingHTTPServer(("127.0.0.1", p), Gestion)
            break
        except OSError:
            continue
    else:
        sys.exit("Aucun port libre pour le serveur local.")
    url = f"http://localhost:{p}/{nom_page}"
    print(f"\nCarte ouverte sur {url}")
    print("Laissez ce terminal ouvert : chaque recherche autour d'un accident s'affiche ici.")
    print("Ctrl+C pour arreter.\n")
    webbrowser.open(url)
    try:
        serveur.serve_forever(poll_interval=0.3)
    except KeyboardInterrupt:
        print("Serveur arrete.")


def main():
    ap = argparse.ArgumentParser(description="Carte interactive des accidents du BAAC")
    ap.add_argument("dossier", nargs="?", default=".", help="dossier contenant les 4 CSV du BAAC")
    ap.add_argument("--sortie", default="docs",
                    help="dossier de la carte, a cote du script (defaut : docs, pour GitHub Pages)")
    ap.add_argument("--sans-apercu", action="store_true", help="ecrire la carte sans l'ouvrir")
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()

    lignes, annee = preparer(Path(args.dossier).expanduser().resolve())
    cible = Path(args.sortie)
    if not cible.is_absolute():
        cible = Path(__file__).resolve().parent / cible
    cible.mkdir(parents=True, exist_ok=True)
    page = (HTML.replace("__ANNEE__", str(annee))
                .replace("__DATA__", json.dumps(lignes, ensure_ascii=False,
                                                separators=(",", ":")).replace("</", "<\\/")))
    chemin = cible / "index.html"
    chemin.write_text(page, encoding="utf-8")
    (cible / ".nojekyll").write_text("", encoding="utf-8")   # GitHub Pages : servi tel quel
    print(f"Carte creee : {chemin}  ({chemin.stat().st_size / 1e6:.1f} Mo)")
    if not args.sans_apercu:
        servir(cible, chemin.name, args.port)


if __name__ == "__main__":
    main()