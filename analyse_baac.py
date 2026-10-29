#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
analyse_baac.py - Analyse "post-accident" du fichier BAAC (ONISR)
Hackathon Renault 2026 : les premieres minutes apres un accident.

Script d'analyse prepare avec l'aide d'une IA (Claude). A signaler
conformement aux regles du hackathon.

INSTALLATION (une seule fois) :
    pip install pandas matplotlib

UTILISATION (PowerShell) :
    python analyse_baac.py "C:\Users\USER\Downloads\data 2024"

Le dossier doit contenir les 4 CSV du BAAC d'une meme annee :
    caract-AAAA.csv, lieux-AAAA.csv, vehicules-AAAA.csv, usagers-AAAA.csv
(les autres CSV du dossier sont simplement inspectes).

RESULTATS (crees dans <dossier>\resultats_baac_AAAA) :
    synthese.md          -> le resume chiffre, a renvoyer pour la suite
    tables\*.csv         -> tous les tableaux detailles (ouvrables dans Excel)
    graphiques\*.png     -> graphiques prets pour la soutenance
    baac_AAAA_usagers_joint.csv -> une ligne par usager, toutes infos jointes
                                   (base pour un futur modele de gravite)

Codage BAAC (depuis 2019) : grav 1 = indemne, 2 = tue (deces a 30 jours),
3 = blesse hospitalise, 4 = blesse leger.
"""

import argparse
import re
import sys
import traceback
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

# ---------------------------------------------------------------------------
# Codes BAAC (guide de codification ONISR, format 2019+)
# ---------------------------------------------------------------------------
LUM = {1: "Plein jour", 2: "Crepuscule / aube", 3: "Nuit sans eclairage public",
       4: "Nuit, eclairage non allume", 5: "Nuit, eclairage allume"}
AGG = {1: "Hors agglomeration", 2: "En agglomeration"}
CATR = {1: "Autoroute", 2: "Route nationale", 3: "Route departementale",
        4: "Voie communale", 5: "Hors reseau public", 6: "Parc de stationnement",
        7: "Route de metropole urbaine", 9: "Autre"}
ATM = {1: "Normale", 2: "Pluie legere", 3: "Pluie forte", 4: "Neige / grele",
       5: "Brouillard / fumee", 6: "Vent fort / tempete", 7: "Temps eblouissant",
       8: "Temps couvert", 9: "Autre"}
COL = {1: "2 vehicules - frontale", 2: "2 vehicules - par l'arriere",
       3: "2 vehicules - par le cote", 4: "3+ vehicules - en chaine",
       5: "3+ vehicules - collisions multiples", 6: "Autre collision",
       7: "Sans collision"}
OBS = {1: "Vehicule en stationnement", 2: "Arbre", 3: "Glissiere metallique",
       4: "Glissiere beton", 5: "Autre glissiere", 6: "Batiment, mur, pile de pont",
       7: "Support de signalisation / borne d'appel", 8: "Poteau", 9: "Mobilier urbain",
       10: "Parapet", 11: "Ilot, refuge, borne haute", 12: "Bordure de trottoir",
       13: "Fosse, talus, paroi rocheuse", 14: "Autre obstacle fixe sur chaussee",
       15: "Autre obstacle fixe (trottoir/accotement)",
       16: "Sortie de chaussee sans obstacle", 17: "Buse, tete d'aqueduc"}
OBSM = {0: "Aucun", 1: "Pieton", 2: "Vehicule", 4: "Vehicule sur rail",
        5: "Animal domestique", 6: "Animal sauvage", 9: "Autre"}
CHOC = {0: "Aucun", 1: "Avant", 2: "Avant droit", 3: "Avant gauche", 4: "Arriere",
        5: "Arriere droit", 6: "Arriere gauche", 7: "Cote droit", 8: "Cote gauche",
        9: "Chocs multiples (tonneaux)"}
MOTOR = {0: "Inconnue", 1: "Hydrocarbures", 2: "Hybride electrique", 3: "Electrique",
         4: "Hydrogene", 5: "Humaine", 6: "Autre"}
GRAV = {1: "Indemne", 2: "Tue", 3: "Blesse hospitalise", 4: "Blesse leger"}
LOCP = {0: "Sans objet", 1: "Chaussee, a +50 m d'un passage pieton",
        2: "Chaussee, a -50 m d'un passage pieton", 3: "Passage pieton sans feux",
        4: "Passage pieton avec feux", 5: "Sur trottoir", 6: "Sur accotement",
        7: "Sur refuge ou bande d'arret d'urgence", 8: "Sur contre-allee", 9: "Inconnue"}
ACTP = {"0": "Non renseigne / sans objet", "1": "Dans le sens du vehicule heurtant",
        "2": "Sens inverse du vehicule", "3": "Traversant", "4": "Masque",
        "5": "Jouant / courant", "6": "Avec un animal", "9": "Autre",
        "A": "Monte / descend du vehicule", "B": "Inconnue"}
JOURS = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]


def mode_depuis_catv(catv):
    """Regroupe la categorie de vehicule (catv) en grands modes."""
    if pd.isna(catv):
        return "Inconnu"
    c = int(catv)
    if c == 7:
        return "Voiture (VL)"
    if c == 10:
        return "Vehicule utilitaire (VU)"
    if c == 3:
        return "Voiturette"
    if c in (2, 30, 31, 32, 33, 34, 35, 36, 41, 42, 43):
        return "2RM / 3RM / quad"
    if c in (1, 80):
        return "Velo / VAE"
    if c in (50, 60):
        return "EDP (trottinette...)"
    if c in (13, 14, 15, 16, 17, 37, 38):
        return "Poids lourd / bus / car"
    return "Autre"


# ---------------------------------------------------------------------------
# Style des graphiques (palette de reference validee, fond clair)
# ---------------------------------------------------------------------------
C = {"surface": "#fcfcfb", "texte": "#0b0b0b", "texte2": "#52514e",
     "grille": "#e4e3df", "serie1": "#2a78d6", "serie2": "#eb6834",
     "neutre": "#b5b4ae"}

plt.rcParams.update({
    "figure.facecolor": C["surface"], "axes.facecolor": C["surface"],
    "savefig.facecolor": C["surface"], "font.size": 10,
    "axes.edgecolor": C["grille"], "axes.labelcolor": C["texte2"],
    "xtick.color": C["texte2"], "ytick.color": C["texte2"],
    "text.color": C["texte"], "axes.titlesize": 12, "axes.titleweight": "bold",
    "axes.spines.top": False, "axes.spines.right": False,
})


# Accents remis uniquement a l'affichage des graphiques (le code reste en ASCII)
ACCENTS = {
    "eclairage": "éclairage", "Crepuscule": "Crépuscule", "agglomeration": "agglomération",
    "departementale": "départementale", "Departements": "Départements",
    "Dep.": "Dép.", "reseau": "réseau", "metropole": "métropole",
    "metropolitaine": "métropolitaine", "Vehicule": "Véhicule", "vehicule": "véhicule",
    "vehicules": "véhicules", "Pieton": "Piéton", "pietons": "piétons", "pieton": "piéton", "Velo": "Vélo",
    "Tues": "Tués", "tues": "tués", "Letalite": "Létalité",
    "letalite": "létalité", "luminosite": "luminosité", "elevees": "élevées",
    "departement": "département", "Fosse": "Fossé", "Batiment": "Bâtiment", "Ilot": "Îlot",
    "Glissiere": "Glissière", "beton": "béton", "metallique": "métallique",
    "electrique": "électrique", "Electrique": "Électrique", "Hydrogene": "Hydrogène",
    "Arriere": "Arrière", "arriere": "arrière", "Cote": "Côté", "cote": "côté",
    "heurtes": "heurtés", "geolocalises": "géolocalisés", "deplacement": "déplacement",
    "allume": "allumé", "chaussee": "chaussée", "tete": "tête", "equipe": "équipe",
    "a": "à", "classes": "classés", "renseigne": "renseigné",
    "grele": "grêle", "legere": "légère", "Age": "Âge", "impliques": "impliqués",
    "anterieurs": "antérieurs",
}
_RE_ACC = re.compile(r"(?<![\w.])(" + "|".join(re.escape(k) for k in
                                               sorted(ACCENTS, key=len, reverse=True))
                     + r")(?![\w])")


def fr(texte):
    return _RE_ACC.sub(lambda m: ACCENTS[m.group(1)], str(texte))


def _finir(fig, ax, titre, sous_titre, chemin, source):
    ax.set_title(fr(titre), loc="left", pad=22, color=C["texte"])
    if sous_titre:
        ax.text(0, 1.02, fr(sous_titre), transform=ax.transAxes, fontsize=9,
                color=C["texte2"], va="bottom")
    fig.text(0.01, 0.01, fr(source), fontsize=7.5, color=C["texte2"])
    if ax.get_ylabel():
        ax.set_ylabel(fr(ax.get_ylabel()))
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(chemin, dpi=200)
    plt.close(fig)


def graph_barh(labels, valeurs, titre, chemin, source, sous_titre=None,
               fmt="{:.0f}", surligner=None):
    """Barres horizontales triees, valeurs ecrites au bout (texte neutre)."""
    labels, valeurs = list(labels), list(valeurs)
    fig, ax = plt.subplots(figsize=(8, 0.42 * len(labels) + 1.6))
    couleurs = [C["serie2"] if surligner and l in surligner else C["serie1"]
                for l in labels]
    y = np.arange(len(labels))[::-1]
    ax.barh(y, valeurs, color=couleurs, height=0.62, edgecolor=C["surface"],
            linewidth=2)
    ax.set_yticks(y)
    ax.set_yticklabels([fr(l) for l in labels])
    vmax = max(valeurs) if valeurs else 1
    for yi, v in zip(y, valeurs):
        ax.text(v + vmax * 0.01, yi, fmt.format(v), va="center", fontsize=9,
                color=C["texte"])
    ax.set_xlim(0, vmax * 1.15)
    ax.xaxis.grid(True, color=C["grille"], linewidth=0.8)
    ax.set_axisbelow(True)
    ax.spines["left"].set_visible(False)
    ax.tick_params(axis="y", length=0)
    _finir(fig, ax, titre, sous_titre, chemin, source)


def graph_barv(labels, valeurs, titre, chemin, source, sous_titre=None,
               ylabel=None, etiquettes=False, fmt="{:.0f}"):
    labels, valeurs = list(labels), list(valeurs)
    fig, ax = plt.subplots(figsize=(9, 4.2))
    x = np.arange(len(labels))
    ax.bar(x, valeurs, color=C["serie1"], width=0.72, edgecolor=C["surface"],
           linewidth=2)
    ax.set_xticks(x)
    ax.set_xticklabels([fr(l) for l in labels])
    if ylabel:
        ax.set_ylabel(fr(ylabel))
    if etiquettes:
        vmax = max(valeurs) if valeurs else 1
        for xi, v in zip(x, valeurs):
            ax.text(xi, v + vmax * 0.015, fmt.format(v), ha="center", fontsize=8,
                    color=C["texte"])
    ax.yaxis.grid(True, color=C["grille"], linewidth=0.8)
    ax.set_axisbelow(True)
    _finir(fig, ax, titre, sous_titre, chemin, source)


def graph_groupes(categories, series, titre, chemin, source, sous_titre=None,
                  ylabel=None, fmt="{:.1f}"):
    """Barres groupees, 2 series max (bleu / orange), legende + valeurs."""
    couleurs = [C["serie1"], C["serie2"]]
    fig, ax = plt.subplots(figsize=(9, 4.4))
    x = np.arange(len(categories))
    n = len(series)
    larg = 0.8 / n
    vmax = np.nanmax([np.nanmax(v) for v in series.values()]) or 1
    for i, (nom, vals) in enumerate(series.items()):
        pos = x - 0.4 + larg / 2 + i * larg
        ax.bar(pos, vals, width=larg, color=couleurs[i], label=fr(nom),
               edgecolor=C["surface"], linewidth=2)
        for p, v in zip(pos, vals):
            if not np.isnan(v):
                ax.text(p, v + vmax * 0.015, fmt.format(v), ha="center",
                        fontsize=8, color=C["texte"])
    ax.set_xticks(x)
    ax.set_xticklabels([fr(c) for c in categories])
    if ylabel:
        ax.set_ylabel(fr(ylabel))
    ax.yaxis.grid(True, color=C["grille"], linewidth=0.8)
    ax.set_axisbelow(True)
    ax.set_ylim(0, vmax * 1.12)
    ax.legend(frameon=False, loc="lower right", bbox_to_anchor=(1, 1.0), ncol=2)
    _finir(fig, ax, titre, sous_titre, chemin, source)


# ---------------------------------------------------------------------------
# Lecture des fichiers
# ---------------------------------------------------------------------------
def lire_csv(path):
    """Lit un CSV BAAC : detecte encodage et separateur, nettoie les guillemets."""
    df = None
    for enc in ("utf-8-sig", "latin-1"):
        try:
            with open(path, encoding=enc) as f:
                premiere = f.readline()
            sep = ";" if premiere.count(";") >= premiere.count(",") else ","
            df = pd.read_csv(path, sep=sep, encoding=enc, dtype=str,
                             low_memory=False)
            break
        except UnicodeDecodeError:
            continue
    df.columns = [c.strip().strip('"').strip() for c in df.columns]
    for c in df.columns:
        df[c] = df[c].str.strip().str.strip('"').str.strip()
    # En 2022, la colonne s'appelait "Accident_Id" dans caract
    if "Accident_Id" in df.columns and "Num_Acc" not in df.columns:
        df = df.rename(columns={"Accident_Id": "Num_Acc"})
    return df


def en_nombres(df, colonnes):
    for c in colonnes:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c].str.replace(",", ".", regex=False),
                                  errors="coerce")
    return df


def trouver(dossier, motif):
    cands = sorted(p for p in dossier.glob("*.csv")
                   if re.search(motif, p.stem, re.I))
    return cands[0] if cands else None


# ---------------------------------------------------------------------------
# Outils de synthese
# ---------------------------------------------------------------------------
def md_table(df, index=True, max_lignes=25):
    """Tableau markdown sans dependance externe."""
    d = df.head(max_lignes).copy()
    if index:
        d = d.reset_index()
    cols = [str(c) for c in d.columns]
    lignes = ["| " + " | ".join(cols) + " |",
              "|" + "|".join("---" for _ in cols) + "|"]
    for r in d.itertuples(index=False, name=None):  # garde le type de chaque colonne
        cells = []
        for v in r:
            if isinstance(v, float):
                cells.append("" if np.isnan(v) else f"{v:,.1f}".replace(",", " "))
            elif isinstance(v, (int, np.integer)):
                cells.append(f"{v:,}".replace(",", " "))
            else:
                cells.append(str(v))
        lignes.append("| " + " | ".join(cells) + " |")
    return "\n".join(lignes)


def pct(a, b):
    return 100.0 * a / b if b else float("nan")


def bilan(U, par):
    """Victimes, tues, blesses hospitalises et letalite par groupe."""
    t = U.groupby(par, dropna=False).agg(
        victimes=("victime", "sum"), tues=("tue", "sum"),
        blesses_hospitalises=("bh", "sum"))
    t["letalite_pour_100_victimes"] = (100 * t["tues"]
                                       / t["victimes"].replace(0, np.nan)).round(1)
    tot = t["tues"].sum()
    t["part_des_tues_%"] = (100 * t["tues"] / tot).round(1) if tot else np.nan
    return t


def sauver(df, out, nom, index=True):
    df.to_csv(out / "tables" / f"{nom}.csv", sep=";", decimal=",",
              encoding="utf-8-sig", index=index)


# ---------------------------------------------------------------------------
# Analyses (chacune renvoie un bloc markdown)
# ---------------------------------------------------------------------------
def a_chiffres_cles(A, U, V, ctx):
    n_acc, n_mort = len(A), int(A["mortel"].sum())
    tues, bh, bl = int(U["tue"].sum()), int(U["bh"].sum()), int(U["bl"].sum())
    indemnes = int((U["grav"] == 1).sum())
    vict = tues + bh + bl
    met = U[U["metropole"]]
    om = U[~U["metropole"]]

    def n(x):
        return f"{int(x):,}".replace(",", " ")

    lignes = [
        f"- Accidents corporels : **{n(n_acc)}** dont **{n(n_mort)} mortels**",
        f"- Usagers impliques : {n(len(U))} (indemnes : {n(indemnes)})",
        f"- Victimes : **{n(vict)}** = {n(tues)} tues + {n(bh)} blesses hospitalises "
        f"+ {n(bl)} blesses legers",
        f"- Tues : metropole {n(met['tue'].sum())} / outre-mer {n(om['tue'].sum())}",
        f"- Letalite globale : **{pct(tues, vict):.1f} tues pour 100 victimes**",
        f"- Vehicules impliques : {n(len(V))}",
        "",
        "Controle du codage de `grav` (doit etre 1 a 4) : "
        + " ; ".join(f"{k} -> {n(v)}" for k, v in
                     U["grav"].value_counts(dropna=False).sort_index().items()
                     if not pd.isna(k)),
    ]
    return "\n".join(lignes)


def a_ou(A, U, V, ctx):
    out, src = ctx["out"], ctx["source"]
    t1 = bilan(U, "agg_lib")
    t2 = bilan(U, "catr_lib").sort_values("tues", ascending=False)
    sauver(t1, out, "02a_gravite_par_agglomeration")
    sauver(t2, out, "02b_gravite_par_type_de_route")
    # Letalite luminosite x agglomeration
    t3 = U.groupby(["lum_lib", "agg_lib"]).agg(victimes=("victime", "sum"),
                                                tues=("tue", "sum"))
    t3["letalite"] = 100 * t3["tues"] / t3["victimes"].replace(0, np.nan)
    sauver(t3, out, "02c_letalite_luminosite_x_agglomeration")
    piv = t3["letalite"].unstack("agg_lib")
    ordre = [LUM[k] for k in sorted(LUM) if LUM[k] in piv.index]
    piv = piv.reindex(ordre)
    series = {c: piv[c].values for c in ["En agglomeration", "Hors agglomeration"]
              if c in piv.columns}
    if series:
        cats = [l.replace(", ", ",\n").replace(" sans", "\nsans") for l in piv.index]
        graph_groupes(cats, series,
                      "Letalite selon la luminosite et le lieu",
                      out / "graphiques" / "02_letalite_luminosite_agglo.png", src,
                      sous_titre="Tues pour 100 victimes selon la luminosite",
                      ylabel="Tues pour 100 victimes")
    return ("### Selon le lieu\n" + md_table(t1) + "\n\n### Selon le type de route\n"
            + md_table(t2) + "\n\n### Letalite (tues / 100 victimes) luminosite x lieu\n"
            + md_table(piv.round(1)))


def a_quand(A, U, V, ctx):
    out, src = ctx["out"], ctx["source"]
    th = bilan(U, "heure").sort_index()
    tl = bilan(U, "lum_lib").sort_values("tues", ascending=False)
    tj = bilan(U, "jour_sem").reindex([j for j in JOURS if j in U["jour_sem"].unique()])
    sauver(th, out, "03a_gravite_par_heure")
    sauver(tl, out, "03b_gravite_par_luminosite")
    sauver(tj, out, "03c_gravite_par_jour")
    th2 = th[th.index.notna()]
    labels = [f"{int(h)}h" for h in th2.index]
    graph_barv(labels, th2["tues"].values, "Tues selon l'heure de l'accident",
               out / "graphiques" / "03a_tues_par_heure.png", src,
               ylabel="Tues")
    graph_barv(labels, th2["letalite_pour_100_victimes"].fillna(0).values,
               "Letalite selon l'heure de l'accident",
               out / "graphiques" / "03b_letalite_par_heure.png", src,
               sous_titre="Tues pour 100 victimes",
               ylabel="Tues pour 100 victimes")
    nuit = U[U["nuit"]]
    txt = (f"- Tues la nuit (luminosite 3-4-5) : {int(nuit['tue'].sum())} "
           f"({pct(nuit['tue'].sum(), U['tue'].sum()):.1f} % des tues)\n"
           f"- Letalite de nuit : {pct(nuit['tue'].sum(), nuit['victime'].sum()):.1f} "
           f"vs jour : {pct(U[~U['nuit']]['tue'].sum(), U[~U['nuit']]['victime'].sum()):.1f}"
           " tues / 100 victimes\n")
    return (txt + "\n### Par luminosite\n" + md_table(tl) + "\n\n### Par jour\n"
            + md_table(tj) + "\n\n### Par heure\n" + md_table(th))


def a_sans_tiers(A, U, V, ctx):
    """Situations ou personne d'autre n'est la pour donner l'alerte."""
    out, src = ctx["out"], ctx["source"]
    tot_t = U["tue"].sum()
    cas = {
        "Tous les accidents": U.index == U.index,
        "Vehicule seul (sans tiers ni pieton)": U["vehicule_seul"],
        "... et hors agglomeration": U["vehicule_seul"] & U["hors_agglo"],
        "... et de nuit": U["vehicule_seul"] & U["hors_agglo"] & U["nuit"],
        "... et nuit sans eclairage": (U["vehicule_seul"] & U["hors_agglo"]
                                       & U["nuit_sans_eclairage"]),
    }
    lignes = []
    for nom, m in cas.items():
        sub = U[m]
        n_acc = sub["Num_Acc"].nunique()
        lignes.append({"situation": nom, "accidents": n_acc,
                       "victimes": int(sub["victime"].sum()),
                       "tues": int(sub["tue"].sum()),
                       "part_des_tues_%": round(pct(sub["tue"].sum(), tot_t), 1),
                       "letalite_pour_100_victimes":
                           round(pct(sub["tue"].sum(), sub["victime"].sum()), 1)})
    t = pd.DataFrame(lignes).set_index("situation")
    sauver(t, out, "04a_accidents_sans_tiers")
    tg = t.drop("Tous les accidents")
    graph_barh(tg.index, tg["part_des_tues_%"],
               "Accidents sans tiers : part des tues",
               out / "graphiques" / "04_sans_tiers.png", src,
               sous_titre="Part des tues (%) - situations a risque d'alerte tardive",
               fmt="{:.1f} %", surligner=["... et nuit sans eclairage"])
    # Obstacle heurte par les vehicules seuls, hors agglo, accidents mortels
    vs = V[V["Num_Acc"].isin(A.loc[A["vehicule_seul"] & A["hors_agglo"]
                                   & A["mortel"], "Num_Acc"])]
    to = vs["obs_lib"].value_counts().rename("vehicules").to_frame()
    to["%"] = (100 * to["vehicules"] / to["vehicules"].sum()).round(1)
    sauver(to, out, "04b_obstacles_vehicule_seul_hors_agglo_mortel")
    return (md_table(t) + "\n\nObstacle heurte (vehicule seul, hors agglomeration, "
            "accident mortel) - un vehicule dans un fosse ou derriere un talus "
            "est peu visible :\n" + md_table(to.head(10)))


def a_desincarceration(A, U, V, ctx):
    out, src = ctx["out"], ctx["source"]
    vm = V[V["Num_Acc"].isin(A.loc[A["mortel"], "Num_Acc"])]
    to = vm["obs_lib"].value_counts().rename("vehicules").to_frame()
    to = to[~to.index.isin(["Aucun / sans objet", "Non renseigne"])]
    to["%"] = (100 * to["vehicules"] / to["vehicules"].sum()).round(1)
    sauver(to, out, "05a_obstacles_fixes_accidents_mortels")
    if len(to):
        top = to.head(10)
        graph_barh(top.index, top["vehicules"],
                   "Obstacles fixes heurtes dans les accidents mortels",
                   out / "graphiques" / "05a_obstacles_mortels.png", src,
                   sous_titre="Nombre de vehicules (hors 'aucun obstacle')")
    tc = vm["choc_lib"].value_counts().rename("vehicules").to_frame()
    tc["%"] = (100 * tc["vehicules"] / tc["vehicules"].sum()).round(1)
    sauver(tc, out, "05b_point_de_choc_accidents_mortels")
    # Nombre de victimes par accident mortel (afflux de victimes -> triage)
    nb = A.loc[A["mortel"], "victime"].clip(upper=5).astype(int)
    dist = nb.value_counts().sort_index()
    dist.index = [("5+" if i == 5 else str(i)) for i in dist.index]
    dist.index.name = "victimes_dans_l_accident"
    dist = dist.rename("accidents_mortels").to_frame()
    dist["%"] = (100 * dist["accidents_mortels"] / dist["accidents_mortels"].sum()).round(1)
    sauver(dist, out, "05c_victimes_par_accident_mortel")
    graph_barv(dist.index, dist["%"].values,
               "Combien de victimes sur un accident mortel ?",
               out / "graphiques" / "05c_victimes_par_accident_mortel.png", src,
               sous_titre="Part des accidents mortels (%) selon le nombre de victimes",
               ylabel="%", etiquettes=True, fmt="{:.1f} %")
    multi = int((A.loc[A["mortel"], "tue"] >= 2).sum())
    return (f"- Accidents mortels avec 2 tues ou plus : {multi}\n\n"
            "### Obstacles fixes (accidents mortels)\n" + md_table(to.head(12))
            + "\n\n### Point de choc (accidents mortels)\n" + md_table(tc)
            + "\n\n### Victimes par accident mortel\n" + md_table(dist))


def a_motorisation(A, U, V, ctx):
    out = ctx["out"]
    graves = A.loc[(A["tue"] > 0) | (A["bh"] > 0), "Num_Acc"]
    vg = V[V["Num_Acc"].isin(graves)]
    t = vg["motor_lib"].value_counts().rename("vehicules").to_frame()
    t["%"] = (100 * t["vehicules"] / t["vehicules"].sum()).round(2)
    sauver(t, out, "06_motorisation_accidents_graves")
    ve = U[U["motor"].isin([2, 3, 4]) & (U["catu"] != 3)]
    return ("Vehicules impliques dans un accident avec tue ou blesse hospitalise :\n"
            + md_table(t) + f"\n\n- Occupants de vehicules electriques/hybrides/"
            f"hydrogene : {int(ve['victime'].sum())} victimes dont "
            f"{int(ve['tue'].sum())} tues")


def a_modes(A, U, V, ctx):
    out, src = ctx["out"], ctx["source"]
    t = bilan(U, "mode").sort_values("tues", ascending=False)
    sauver(t, out, "07_gravite_par_mode")
    graph_barh(t.index, t["tues"], "Tues selon le mode de deplacement",
               out / "graphiques" / "07_tues_par_mode.png", src,
               sous_titre="Nombre de tues (pietons classes a part)",
               surligner=["2RM / 3RM / quad", "Velo / VAE", "EDP (trottinette...)",
                          "Pieton"])
    hors = t.drop([m for m in ["Voiture (VL)", "Vehicule utilitaire (VU)"]
                   if m in t.index])
    return (md_table(t) + f"\n\n- Tues hors voitures et VU (pietons, 2RM, velos, "
            f"EDP, PL...) : {int(hors['tues'].sum())} soit "
            f"{pct(hors['tues'].sum(), t['tues'].sum()):.1f} % des tues")


def a_autoroute(A, U, V, ctx):
    out = ctx["out"]
    au = U[U["catr"] == 1]
    piet = au[au["catu"] == 3]
    t = bilan(au, "catu_lib")
    sauver(t, out, "08_autoroute_par_type_usager")
    pv = piet[piet["victime"] == 1].copy()
    pv["localisation"] = pv["locp"].map(LOCP).fillna("Non renseigne")
    pv["action"] = pv["actp"].astype(str).str.strip().map(ACTP).fillna("Non renseigne")
    tl = pv.groupby("localisation").agg(victimes=("victime", "sum"), tues=("tue", "sum"))
    ta = pv.groupby("action").agg(victimes=("victime", "sum"), tues=("tue", "sum"))
    tl = tl.sort_values("victimes", ascending=False)
    ta = ta.sort_values("victimes", ascending=False)
    sauver(tl, out, "08b_pietons_autoroute_localisation")
    sauver(ta, out, "08c_pietons_autoroute_action")
    sortis = pv["locp"].isin([6, 7]) | (pv["actp"].astype(str).str.strip() == "A")
    return (f"- Tues sur autoroute : {int(au['tue'].sum())} "
            f"(dont de nuit : {int(au.loc[au['nuit'], 'tue'].sum())})\n"
            f"- Pietons tues sur autoroute : {int(piet['tue'].sum())} "
            f"(dont de nuit : {int(piet.loc[piet['nuit'], 'tue'].sum())})\n"
            f"- Pietons victimes sur autoroute situes sur l'accotement / la BAU ou "
            f"montant-descendant d'un vehicule : {int(sortis.sum())} sur {len(pv)} "
            f"(dont {int(pv.loc[sortis, 'tue'].sum())} tues) - indice de personnes "
            "sorties de leur vehicule (hypothese du suraccident)\n\n" + md_table(t)
            + "\n\n### Pietons victimes sur autoroute : ou etaient-ils ?\n"
            + md_table(tl) + "\n\n### ... et que faisaient-ils ?\n" + md_table(ta))


def a_age(A, U, V, ctx):
    out = ctx["out"]
    t = bilan(U, "tranche_age")
    sauver(t, out, "09_gravite_par_age")
    return md_table(t)


def a_ceinture(A, U, V, ctx):
    out = ctx["out"]
    occ = U[U["catv"].isin([3, 7, 10]) & U["catu"].isin([1, 2])].copy()
    s = occ[["secu1", "secu2", "secu3"]]
    connu = ~(s.isin([-1, 8]) | s.isna()).all(axis=1)
    occ = occ[connu]
    occ["ceinture"] = (s.loc[connu] == 1).any(axis=1)
    t = occ.groupby("grav_lib").agg(occupants=("ceinture", "size"),
                                     avec_ceinture=("ceinture", "sum"))
    t["%_ceinture"] = (100 * t["avec_ceinture"] / t["occupants"]).round(1)
    sauver(t, out, "10_ceinture_occupants_VL_VU")
    return ("Occupants de VL / VU / voiturettes (equipement renseigne) - utile pour "
            "un score de gravite (la ceinture est un predicteur cle) :\n"
            + md_table(t))


def a_departements(A, U, V, ctx):
    out, src = ctx["out"], ctx["source"]
    t = bilan(U, "dep")
    ha = U.groupby("dep")["hors_agglo"].mean().mul(100).round(1)
    t["%_usagers_hors_agglo"] = ha
    t = t.sort_values("letalite_pour_100_victimes", ascending=False)
    sauver(t, out, "11_departements")
    seuil = 200
    top = t[t["victimes"] >= seuil].head(15)
    if len(top):
        graph_barh([f"Dep. {d}" for d in top.index],
                   top["letalite_pour_100_victimes"],
                   "Letalite par departement (15 plus elevees)",
                   out / "graphiques" / "11_letalite_departements.png", src,
                   sous_titre=f"Tues pour 100 victimes (departements >= {seuil} "
                              "victimes)", fmt="{:.1f}")
    bas = t[t["victimes"] >= seuil].tail(5)
    return (f"Top 15 (au moins {seuil} victimes) :\n" + md_table(top)
            + "\n\nLes 5 plus faibles :\n" + md_table(bas)
            + "\n\nAttention : correlation, pas causalite (vitesse, type de route, "
              "distance aux secours... se melangent).")


def a_carte(A, U, V, ctx):
    out, src = ctx["out"], ctx["source"]
    m = A[A["mortel"] & A["metropole"]].dropna(subset=["lat", "long"])
    m = m[m["lat"].between(41, 51.5) & m["long"].between(-5.5, 10)]
    if m.empty:
        return "Coordonnees GPS absentes ou illisibles."
    fig, ax = plt.subplots(figsize=(7.5, 7.5))
    for seul, col, lab in [(False, C["serie1"], "Autres accidents mortels"),
                           (True, C["serie2"], "Vehicule seul hors agglomeration")]:
        sub = m[(m["vehicule_seul"] & m["hors_agglo"]) == seul]
        ax.scatter(sub["long"], sub["lat"], s=7, color=col, alpha=0.6,
                   linewidths=0, label=fr(f"{lab} ({len(sub)})"))
    ax.set_aspect(1 / np.cos(np.radians(46.5)))
    ax.set_xticks([])
    ax.set_yticks([])
    for sp in ax.spines.values():
        sp.set_visible(False)
    ax.legend(frameon=False, loc="upper left", bbox_to_anchor=(0, 0), ncol=2,
              markerscale=2.5)
    _finir(fig, ax, "Accidents mortels en France metropolitaine",
           f"{len(m)} accidents geolocalises", out / "graphiques" / "12_carte_mortels.png",
           src)
    m[["Num_Acc", "lat", "long", "dep", "tue", "vehicule_seul", "hors_agglo",
       "lum_lib", "catr_lib"]].to_csv(out / "tables" / "12_accidents_mortels_gps.csv",
                                      sep=";", decimal=",", encoding="utf-8-sig",
                                      index=False)
    return f"{len(m)} accidents mortels places sur la carte (fichier GPS exporte)."


def _col(df, motif):
    for c in df.columns:
        if re.search(motif, c, re.I):
            return c
    return None


def a_parc(A, U, V, ctx):
    """Fichier complementaire (Id_accident, lettre, CNIT, categorie, age)."""
    out, src = ctx["out"], ctx["source"]
    p = ctx.get("fichier_age")
    if p is None:
        return "Fichier complementaire age / CNIT absent du dossier."
    P = lire_csv(p)
    c_id, c_let, c_cat, c_age, c_cnit = (_col(P, m) for m in
                                         [r"^Id_acc", r"^Lettre", r"gorie", r"^Age",
                                          r"CNIT"])
    P["id"] = P[c_id].astype(str).str.replace(r"\s", "", regex=True)
    P["lettre"] = P[c_let].astype(str).str.strip().str.upper().str[:1]
    P["age"] = pd.to_numeric(P[c_age], errors="coerce")
    P["cat"] = P[c_cat].fillna("?").astype(str).str.strip()
    n_acc2 = P["id"].nunique()
    n_cnit = P[c_cnit].nunique() if c_cnit else 0

    def part7(s):
        return round(100 * (s >= 7).sum() / s.notna().sum(), 1) if s.notna().any() else np.nan

    tcat = P.groupby("cat").agg(vehicules=("age", "size"), age_median=("age", "median"),
                                age_moyen=("age", "mean"),
                                part_7_ans_et_plus=("age", part7))
    tcat = tcat.sort_values("vehicules", ascending=False)
    tcat["age_moyen"] = tcat["age_moyen"].round(1)
    sauver(tcat, out, "13a_parc_age_par_categorie")

    tranches = ["0-2 ans", "3-6 ans", "7-10 ans", "11-15 ans", "16-20 ans", "21 ans et +"]
    vtvu = P[P["cat"].isin(["VT", "VU"])]
    tr = pd.cut(vtvu["age"], [-1, 2, 6, 10, 15, 20, 200], labels=tranches)
    dist = tr.value_counts().reindex(tranches).rename("vehicules").to_frame()
    dist["%"] = (100 * dist["vehicules"] / dist["vehicules"].sum()).round(1)
    sauver(dist, out, "13b_age_voitures_VU")
    if dist["vehicules"].sum():
        graph_barh(dist.index, dist["%"], "Age des voitures et VU impliques dans un accident",
                   out / "graphiques" / "13_age_vehicules.png", src,
                   sous_titre="Part des vehicules (%) - en orange : 7 ans et plus, "
                              "anterieurs a l'eCall obligatoire (avril 2018)",
                   fmt="{:.1f} %", surligner=tranches[2:])
    txt = [f"- Fichier `{p.name}` : {len(P)} vehicules, {n_acc2} accidents, "
           f"**{n_cnit} codes CNIT (modeles) differents**",
           f"- Voitures (VT) et VU : {len(vtvu)} vehicules, age median "
           f"{vtvu['age'].median():.0f} ans, **{part7(vtvu['age'])} % ont 7 ans ou plus**",
           "", md_table(tcat), "", "### Age des voitures et VU", md_table(dist)]

    # --- Tentative de rapprochement avec le BAAC (pas de cle commune) ----------
    lettres_V = (V.assign(l=V["num_veh"].astype(str).str.strip().str[:1].str.upper())
                 .groupby("Num_Acc")["l"].agg(set))
    lettres_P = P.groupby("id")["lettre"].agg(set)
    ordre_P = P["id"].drop_duplicates().tolist()
    num_acc = A["Num_Acc"].tolist()
    meilleur = None
    if len(ordre_P) == len(num_acc):
        cands = {"ordre du fichier": ordre_P,
                 "ordre numerique": sorted(ordre_P, key=lambda x: int(x) if x.isdigit() else -1)}
        for nom, ids in cands.items():
            ok = np.mean([lettres_P[i] <= lettres_V.get(n, set())
                          for n, i in zip(num_acc, ids)])
            if meilleur is None or ok > meilleur[1]:
                meilleur = (nom, ok, dict(zip(ids, num_acc)))
    if meilleur is None:
        txt.append(f"\nRapprochement BAAC impossible : {n_acc2} accidents dans ce fichier "
                   f"contre {len(num_acc)} dans le BAAC.")
        return "\n".join(txt)
    nom, taux_lettres, corr = meilleur
    P["Num_Acc"] = P["id"].map(corr)
    Vk = V.assign(lettre=V["num_veh"].astype(str).str.strip().str[:1].str.upper())
    Vk = Vk.drop_duplicates(["Num_Acc", "lettre"])[["Num_Acc", "lettre", "catv"]]
    J = P.merge(Vk, on=["Num_Acc", "lettre"], how="left")
    vt = J[J["cat"] == "VT"]
    taux_vt = (vt["catv"] == 7).mean() if len(vt) else np.nan
    valide = taux_lettres >= 0.98 and taux_vt >= 0.90
    txt.append(f"\n### Rapprochement avec le BAAC ({nom})\n"
               f"- Accidents dont les lettres de vehicules concordent : {100*taux_lettres:.1f} %\n"
               f"- Vehicules 'VT' retrouves comme voiture (catv 7) : {100*taux_vt:.1f} %\n"
               f"- Rapprochement **{'VALIDE' if valide else 'REJETE'}** "
               "(seuils : 98 % et 90 %)")
    if not valide:
        return "\n".join(txt)

    J = J.merge(A[["Num_Acc", "mortel", "vehicule_seul", "hors_agglo", "nuit"]],
                on="Num_Acc", how="left")
    jv = J[J["cat"].isin(["VT", "VU"])]
    situ = {"Tous les accidents": jv,
            "Accidents mortels": jv[jv["mortel"] == True],  # noqa: E712
            "Mortels, vehicule seul hors agglo": jv[(jv["mortel"] == True)  # noqa: E712
                                                   & (jv["vehicule_seul"] == True)
                                                   & (jv["hors_agglo"] == True)],
            "... et de nuit": jv[(jv["mortel"] == True) & (jv["vehicule_seul"] == True)
                                 & (jv["hors_agglo"] == True) & (jv["nuit"] == True)]}
    ts = pd.DataFrame({"voitures_et_VU": {k: len(v) for k, v in situ.items()},
                       "part_7_ans_et_plus": {k: part7(v["age"]) for k, v in situ.items()}})
    sauver(ts, out, "13c_age_selon_situation")
    # Tues a bord de voitures/VU de 7 ans et plus
    Uk = U[U["catu"].isin([1, 2])].assign(
        lettre=U["num_veh"].astype(str).str.strip().str[:1].str.upper())
    UJ = Uk.merge(J[["Num_Acc", "lettre", "cat", "age"]].drop_duplicates(["Num_Acc", "lettre"]),
                  on=["Num_Acc", "lettre"], how="inner")
    UJ = UJ[UJ["cat"].isin(["VT", "VU"])]
    t7 = int(UJ.loc[UJ["age"] >= 7, "tue"].sum())
    txt += ["", "### Voitures et VU de 7 ans et plus selon la situation", md_table(ts),
            f"\n- Tues a bord de voitures / VU de 7 ans et plus : **{t7}** sur "
            f"{int(UJ['tue'].sum())} tues a bord de voitures / VU rapproches"]
    return "\n".join(txt)


ANALYSES = [
    ("1. Chiffres cles", a_chiffres_cles),
    ("2. Ou ? (agglomeration, route, luminosite)", a_ou),
    ("3. Quand ? (heure, jour, nuit)", a_quand),
    ("4. Accidents sans tiers : qui donne l'alerte ?", a_sans_tiers),
    ("5. Acces a la victime / desincarceration", a_desincarceration),
    ("6. Motorisation (batteries haute tension)", a_motorisation),
    ("7. Modes de deplacement (hors couverture eCall voiture)", a_modes),
    ("8. Autoroute et pietons (suraccident)", a_autoroute),
    ("9. Age des victimes", a_age),
    ("10. Ceinture (predicteur de gravite)", a_ceinture),
    ("11. Departements", a_departements),
    ("12. Carte des accidents mortels", a_carte),
    ("13. Age des vehicules et modeles (fichier complementaire)", a_parc),
]


# ---------------------------------------------------------------------------
# Programme principal
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Analyse post-accident du BAAC")
    ap.add_argument("dossier", nargs="?", default=".",
                    help="dossier contenant les 4 CSV du BAAC")
    args = ap.parse_args()
    dossier = Path(args.dossier).expanduser().resolve()
    if not dossier.is_dir():
        sys.exit(f"Dossier introuvable : {dossier}")

    chemins = {k: trouver(dossier, m) for k, m in
               {"caract": r"^carac", "lieux": r"^lieu",
                "vehicules": r"^vehic", "usagers": r"^usag"}.items()}
    manquants = [k for k, p in chemins.items() if p is None]
    if manquants:
        sys.exit(f"Fichiers manquants dans {dossier} : {', '.join(manquants)}")

    print("Lecture des fichiers...")
    caract = lire_csv(chemins["caract"])
    lieux = lire_csv(chemins["lieux"])
    veh = lire_csv(chemins["vehicules"])
    usa = lire_csv(chemins["usagers"])
    for nom, df in [("caract", caract), ("lieux", lieux), ("vehicules", veh),
                    ("usagers", usa)]:
        print(f"  {nom:10s} {len(df):>8,} lignes  colonnes : {', '.join(df.columns)}")

    en_nombres(caract, ["jour", "mois", "an", "lum", "agg", "int", "atm", "col",
                        "lat", "long"])
    en_nombres(lieux, ["catr", "circ", "nbv", "vosp", "prof", "plan", "surf",
                       "infra", "situ", "vma"])
    en_nombres(veh, ["senc", "catv", "obs", "obsm", "choc", "manv", "motor", "occutc"])
    en_nombres(usa, ["place", "catu", "grav", "sexe", "an_nais", "trajet", "secu1",
                     "secu2", "secu3", "locp", "etatp"])

    annee = (int(caract["an"].mode().iloc[0]) if "an" in caract and caract["an"].notna().any()
             else int((re.findall(r"(20\d\d)", chemins["caract"].stem) or ["0"])[0]))
    out = dossier / f"resultats_baac_{annee}"
    (out / "tables").mkdir(parents=True, exist_ok=True)
    (out / "graphiques").mkdir(parents=True, exist_ok=True)
    source = f"Source : ONISR, fichier BAAC {annee} (data.gouv.fr) - traitement equipe hackathon"

    # --- Table accidents --------------------------------------------------
    print("Preparation des tables...")
    A = caract.drop_duplicates("Num_Acc").copy()
    h = A["hrmn"].astype(str) if "hrmn" in A else pd.Series("", index=A.index)
    A["heure"] = pd.to_numeric(np.where(h.str.contains(":"), h.str.split(":").str[0],
                                        h.str.zfill(4).str[:-2]), errors="coerce")
    dates = pd.to_datetime(dict(year=A["an"], month=A["mois"], day=A["jour"]),
                           errors="coerce")
    A["jour_sem"] = dates.dt.day_of_week.map(dict(enumerate(JOURS)))
    A["dep"] = A["dep"].astype(str)
    A["metropole"] = ~(A["dep"].str.startswith("97") | A["dep"].isin(["986", "987", "988"]))
    cols_l = [c for c in ["Num_Acc", "catr", "vma", "surf", "infra", "circ", "prof",
                          "plan", "situ"] if c in lieux]
    A = A.merge(lieux[cols_l].drop_duplicates("Num_Acc"), on="Num_Acc", how="left")
    nbveh = veh.groupby("Num_Acc").size().rename("nb_veh")
    A = A.merge(nbveh, left_on="Num_Acc", right_index=True, how="left")

    # --- Table usagers ------------------------------------------------------
    U = usa.copy()
    U["tue"] = (U["grav"] == 2).astype(int)
    U["bh"] = (U["grav"] == 3).astype(int)
    U["bl"] = (U["grav"] == 4).astype(int)
    U["victime"] = U["grav"].isin([2, 3, 4]).astype(int)
    U["pieton"] = (U["catu"] == 3).astype(int)
    stats = U.groupby("Num_Acc")[["tue", "bh", "bl", "victime", "pieton"]].sum()
    A = A.merge(stats, left_on="Num_Acc", right_index=True, how="left")
    for c in ["nb_veh", "tue", "bh", "bl", "victime", "pieton"]:
        A[c] = A[c].fillna(0).astype(int)
    A["mortel"] = A["tue"] > 0
    A["vehicule_seul"] = (A["nb_veh"] == 1) & (A["pieton"] == 0)
    A["hors_agglo"] = A["agg"] == 1
    A["nuit"] = A["lum"].isin([3, 4, 5])
    A["nuit_sans_eclairage"] = A["lum"].isin([3, 4])
    A["lum_lib"] = A["lum"].map(LUM).fillna("Non renseigne")
    A["agg_lib"] = A["agg"].map(AGG).fillna("Non renseigne")
    A["catr_lib"] = A["catr"].map(CATR).fillna("Non renseigne")
    A["atm_lib"] = A["atm"].map(ATM).fillna("Non renseigne")
    A["col_lib"] = A["col"].map(COL).fillna("Non renseigne")

    # Vehicules : libelles
    V = veh.copy()
    V["obs_lib"] = V["obs"].map(OBS)
    V.loc[V["obs"] == 0, "obs_lib"] = "Aucun / sans objet"
    V["obs_lib"] = V["obs_lib"].fillna("Non renseigne")
    V["obsm_lib"] = V["obsm"].map(OBSM).fillna("Non renseigne")
    V["choc_lib"] = V["choc"].map(CHOC).fillna("Non renseigne")
    V["motor_lib"] = V["motor"].map(MOTOR).fillna("Non renseigne")
    V["mode"] = V["catv"].map(mode_depuis_catv)

    # Jointure usager <- vehicule <- accident
    cle = ["Num_Acc", "id_vehicule"] if ("id_vehicule" in U and "id_vehicule" in V) \
        else ["Num_Acc", "num_veh"]
    cols_v = cle + [c for c in ["catv", "obs", "obsm", "choc", "manv", "motor",
                                "mode", "obs_lib", "choc_lib", "motor_lib"]
                    if c in V and c not in cle]
    U = U.merge(V[cols_v].drop_duplicates(cle), on=cle, how="left")
    cols_a = ["Num_Acc", "an", "mois", "jour", "heure", "jour_sem", "dep", "metropole",
              "lum", "agg", "atm", "col", "int", "catr", "vma", "surf", "infra",
              "lat", "long", "nb_veh", "vehicule_seul", "hors_agglo", "nuit",
              "nuit_sans_eclairage", "lum_lib", "agg_lib", "catr_lib", "atm_lib",
              "col_lib"]
    U = U.merge(A[[c for c in cols_a if c in A]], on="Num_Acc", how="left")
    for c in ["vehicule_seul", "hors_agglo", "nuit", "nuit_sans_eclairage", "metropole"]:
        U[c] = U[c].fillna(False).astype(bool)
    U["mode"] = np.where(U["catu"] == 3, "Pieton", U["mode"].fillna("Inconnu"))
    U["grav_lib"] = U["grav"].map(GRAV).fillna("Non renseigne")
    U["catu_lib"] = U["catu"].map({1: "Conducteur", 2: "Passager", 3: "Pieton"}).fillna("Autre")
    age = U["an"] - U["an_nais"]
    U["tranche_age"] = pd.cut(age, [-1, 17, 24, 44, 64, 74, 120],
                              labels=["0-17", "18-24", "25-44", "45-64", "65-74", "75+"])
    U["tranche_age"] = U["tranche_age"].astype(object).where(U["tranche_age"].notna(),
                                                             "Inconnu")

    # --- Analyses -------------------------------------------------------------
    fichier_age = None
    for p_ in sorted(dossier.glob("*.csv")):
        if p_ in chemins.values():
            continue
        with open(p_, encoding="utf-8-sig", errors="replace") as f:
            entete = f.readline()
        if "Id_accident" in entete and re.search(r"Age", entete):
            fichier_age = p_
            break
    ctx = {"out": out, "source": source, "fichier_age": fichier_age}
    blocs = [f"# Synthese BAAC {annee} - angle post-accident",
             f"_Genere le {datetime.now():%d/%m/%Y %H:%M} par analyse_baac.py_",
             "",
             "Fichiers lus : " + ", ".join(f"{p.name}" for p in chemins.values()),
             "Definitions : tue = deces dans les 30 jours ; letalite = tues pour 100 "
             "victimes (tues + blesses) ; vehicule seul = 1 seul vehicule et aucun "
             "pieton (accident sans tiers).", ""]
    for titre, f in ANALYSES:
        print(f"  {titre}")
        try:
            blocs += [f"## {titre}", f(A, U, V, ctx), ""]
        except Exception as e:  # une analyse qui echoue ne bloque pas les autres
            blocs += [f"## {titre}", f"**Analyse impossible** : {e!r}",
                      "```", traceback.format_exc(limit=3), "```", ""]

    # --- Autres CSV du dossier ------------------------------------------------
    autres = [p for p in dossier.glob("*.csv") if p not in chemins.values()]
    if autres:
        blocs.append("## Autres fichiers CSV du dossier")
        for p in autres:
            try:
                d = lire_csv(p)
                blocs.append(f"- `{p.name}` : {len(d):,} lignes, colonnes : "
                             f"{', '.join(d.columns[:30])}")
                blocs.append("  - premiere ligne : " + " | ".join(
                    str(v) for v in d.iloc[0].values[:15]) if len(d) else "")
            except Exception as e:
                blocs.append(f"- `{p.name}` : illisible ({e!r})")

    # --- Export joint pour un modele de gravite ----------------------------
    joint = out / f"baac_{annee}_usagers_joint.csv"
    U.to_csv(joint, sep=";", decimal=",", encoding="utf-8-sig", index=False)
    blocs += ["", f"Export joint : `{joint.name}` ({len(U):,} usagers, "
                  f"{U.shape[1]} colonnes)"]

    (out / "synthese.md").write_text("\n".join(blocs), encoding="utf-8")
    print(f"\nTermine. Resultats dans : {out}")
    print(f"  -> Renvoie le fichier : {out / 'synthese.md'}")
    print(f"  -> Graphiques : {out / 'graphiques'}")


if __name__ == "__main__":
    main()