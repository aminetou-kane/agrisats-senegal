"""Module d'IA : apprentissage statistique du calendrier de prix saisonnier.

Ce que fait ce module, en clair :
  1. Il lit un historique de prix de location (date, type de machine, prix payé, prix de base).
  2. Pour chaque catégorie de machine et chaque mois, il calcule le rapport moyen
     « prix payé / prix de base ». C'est le coefficient saisonnier.
  3. Quand il y a peu d'observations pour un mois, il reste proche de l'estimation de départ
     (comme un prudent qui ne change pas d'avis sur une seule donnée).
  4. Il mesure son erreur par validation croisée (il s'entraîne sur une partie des données et
     se teste sur l'autre) et la compare à celle d'un prix constant.

C'est de l'apprentissage statistique simple, pas du « deep learning » : un modèle
volontairement lisible, que l'on peut expliquer ligne par ligne.

HONNÊTETÉ : le fichier fourni (data/historique_simule.csv) est SIMULÉ. Il est fabriqué à partir
du calendrier estimé, avec du bruit. Le modèle le retrouve donc « par construction » : cela
démontre que la chaîne fonctionne, pas que le calendrier est exact. Avec de vraies
observations de terrain, les coefficients se corrigent d'eux-mêmes.
"""
import argparse
import csv
import os
import random
import sqlite3
from datetime import date

DOSSIER = os.path.dirname(os.path.abspath(__file__))
CSV_SIMULE = os.path.join(DOSSIER, "data", "historique_simule.csv")

CATEGORIES = ("preparation", "recolte")
COLONNES = ("date", "categorie", "prix_jour", "prix_base")   # colonne facultative : source

POIDS_ESTIMATION = 5        # poids de l'estimation de départ, en « observations virtuelles »
COEF_MIN, COEF_MAX = 0.5, 2.0
RAPPORT_MIN, RAPPORT_MAX = 0.2, 5.0   # un prix 5 fois plus cher ou moins cher est une erreur de saisie
PLIS = 5                              # validation croisée en 5 parties
MIN_POUR_EVALUER = 2 * PLIS
MAX_LIGNES = 200_000

# Calendrier de départ : ESTIMATIONS à valider avec des propriétaires et des producteurs de la
# vallée (sources publiques partielles, calendriers parfois contradictoires).
CALENDRIER_DEPART = {
    # tracteurs, motoculteurs, planeuses : pointe avant les semis (début d'année et début d'hivernage)
    "preparation": {1: 1.3, 2: 1.3, 3: 1.0, 4: 0.8, 5: 0.8, 6: 1.3,
                    7: 1.3, 8: 1.0, 9: 0.8, 10: 0.8, 11: 1.0, 12: 1.0},
    # moissonneuses, batteuses : pointe aux deux récoltes (mi-année et fin d'année)
    "recolte": {1: 0.8, 2: 0.8, 3: 0.8, 4: 1.0, 5: 1.0, 6: 1.4,
                7: 1.4, 8: 0.8, 9: 0.8, 10: 1.0, 11: 1.4, 12: 1.4},
}


class ErreurDonnees(Exception):
    """Le fichier de données est inutilisable (la liste des problèmes est dans le message)."""


# ---------------------------------------------------------------------------
# 1. Données
# ---------------------------------------------------------------------------
def simuler(chemin_csv=CSV_SIMULE, graine=2026, annees=(2023, 2024, 2025), par_mois=25):
    """Fabrique un historique SIMULÉ : calendrier de départ + bruit de 8 %. Retourne le nombre de lignes."""
    hasard = random.Random(graine)
    bases = {"preparation": [12000, 35000, 38000, 40000, 45000, 55000],
             "recolte": [25000, 110000, 120000, 130000]}
    lignes = []
    for annee in annees:
        for mois in range(1, 13):
            for categorie in CATEGORIES:
                for _ in range(par_mois):
                    jour = date(annee, mois, hasard.randint(1, 28))
                    base = hasard.choice(bases[categorie])
                    rapport = CALENDRIER_DEPART[categorie][mois] + hasard.gauss(0, 0.08)
                    prix = max(1000, round(base * rapport / 500) * 500)    # prix arrondis à 500 FCFA
                    lignes.append((jour.isoformat(), categorie, prix, base, "simule"))
    os.makedirs(os.path.dirname(chemin_csv), exist_ok=True)
    with open(chemin_csv, "w", newline="", encoding="utf-8") as f:
        ecrivain = csv.writer(f)
        ecrivain.writerow(COLONNES + ("source",))
        ecrivain.writerows(lignes)
    return len(lignes)


def lire_csv(chemin_csv):
    """Lit et contrôle un fichier. Retourne (observations, source).

    observations = liste de (mois, catégorie, rapport prix/prix de base).
    Le moindre problème arrête tout : on n'apprend jamais à moitié sur des données douteuses.
    """
    erreurs, observations, sources = [], [], set()
    try:
        with open(chemin_csv, newline="", encoding="utf-8-sig") as f:
            lecteur = csv.DictReader(f)
            manquantes = [c for c in COLONNES if c not in (lecteur.fieldnames or [])]
            if manquantes:
                raise ErreurDonnees("Colonnes manquantes : " + ", ".join(manquantes)
                                    + ". Colonnes attendues : " + ", ".join(COLONNES) + " (et source, facultative).")
            for numero, ligne in enumerate(lecteur, start=2):
                if numero > MAX_LIGNES:
                    raise ErreurDonnees(f"Fichier trop long (plus de {MAX_LIGNES} lignes).")
                try:
                    jour = date.fromisoformat((ligne["date"] or "").strip())
                    categorie = (ligne["categorie"] or "").strip()
                    prix = float(ligne["prix_jour"])
                    base = float(ligne["prix_base"])
                except (ValueError, TypeError):
                    erreurs.append(f"ligne {numero} : date (AAAA-MM-JJ) ou nombre illisible")
                    continue
                if categorie not in CATEGORIES:
                    erreurs.append(f"ligne {numero} : catégorie « {categorie} » inconnue (attendu : {', '.join(CATEGORIES)})")
                elif prix <= 0 or base <= 0:
                    erreurs.append(f"ligne {numero} : les prix doivent être positifs")
                elif not RAPPORT_MIN <= prix / base <= RAPPORT_MAX:
                    erreurs.append(f"ligne {numero} : prix de {prix:g} pour une base de {base:g} (rapport improbable, erreur de saisie ?)")
                else:
                    observations.append((jour.month, categorie, prix / base))
                    sources.add((ligne.get("source") or "terrain").strip() or "terrain")
    except OSError as e:
        raise ErreurDonnees(f"Fichier illisible : {e}") from e
    except UnicodeDecodeError as e:
        raise ErreurDonnees("Le fichier doit être un CSV encodé en UTF-8.") from e
    if erreurs:
        suite = f" (et {len(erreurs) - 10} autres)" if len(erreurs) > 10 else ""
        raise ErreurDonnees("Données refusées, rien n'a été modifié :\n  " + "\n  ".join(erreurs[:10]) + suite)
    if not observations:
        raise ErreurDonnees("Le fichier ne contient aucune observation.")
    source = "simule" if sources == {"simule"} else "terrain" if "simule" not in sources else "mixte"
    return observations, source


# ---------------------------------------------------------------------------
# 2. Modèle
# ---------------------------------------------------------------------------
def estimer(observations, estimation):
    """Coefficient de chaque mois = moyenne des rapports, tirée vers l'estimation de départ.

        coefficient = (n x moyenne_observée + 5 x estimation) / (n + 5)

    Avec beaucoup d'observations, la donnée l'emporte ; avec peu, l'estimation de départ reste.
    Un mois sans aucune observation vaut None (on garde l'ancienne valeur).
    """
    somme, nombre = {}, {}
    for mois, rapport in observations:
        somme[mois] = somme.get(mois, 0.0) + rapport
        nombre[mois] = nombre.get(mois, 0) + 1
    coefficients = {}
    for mois in range(1, 13):
        n = nombre.get(mois, 0)
        if n == 0:
            coefficients[mois] = None
            continue
        a_priori = estimation.get(mois, 1.0)
        valeur = (somme[mois] + POIDS_ESTIMATION * a_priori) / (n + POIDS_ESTIMATION)
        coefficients[mois] = round(min(COEF_MAX, max(COEF_MIN, valeur)), 1)   # arrondi à 0,1 : lisible
    return coefficients


def evaluer(observations, estimation):
    """Validation croisée : (erreur moyenne du modèle, erreur moyenne d'un prix constant) ou (None, None)."""
    if len(observations) < MIN_POUR_EVALUER:
        return None, None
    erreur_modele = erreur_reference = 0.0
    for pli in range(PLIS):
        entrainement = [o for i, o in enumerate(observations) if i % PLIS != pli]
        test = [o for i, o in enumerate(observations) if i % PLIS == pli]
        modele = estimer([(m, r) for m, r in entrainement], estimation)
        for mois, rapport in test:
            prevu = modele[mois] if modele[mois] is not None else estimation.get(mois, 1.0)
            erreur_modele += abs(rapport - prevu)
            erreur_reference += abs(rapport - 1.0)       # référence : « le prix ne change jamais »
    n = len(observations)
    return erreur_modele / n, erreur_reference / n


def entrainer(observations, estimations):
    """Entraîne un modèle par catégorie. estimations = {catégorie: {mois: coefficient}}."""
    rapports = {}
    for categorie in CATEGORIES:
        donnees = [(m, r) for m, c, r in observations if c == categorie]
        if not donnees:
            continue
        estimation = estimations.get(categorie, {})
        erreur_modele, erreur_reference = evaluer(donnees, estimation)
        rapports[categorie] = {
            "observations": len(donnees),
            "coefficients": estimer(donnees, estimation),
            "erreur_modele": erreur_modele,
            "erreur_reference": erreur_reference,
        }
    return rapports


# ---------------------------------------------------------------------------
# 3. Application à la base de données
# ---------------------------------------------------------------------------
def appliquer(connexion, rapports, source):
    """Écrit les coefficients appris et la fiche d'évaluation. L'appelant fait le commit."""
    for categorie, rapport in rapports.items():
        for mois, coefficient in rapport["coefficients"].items():
            if coefficient is not None:
                connexion.execute(
                    "UPDATE coefficients_saison SET coefficient = ? WHERE categorie = ? AND mois = ?",
                    (coefficient, categorie, mois))
        connexion.execute(
            """INSERT INTO modele_prix (categorie, source, nb_observations, erreur_modele, erreur_reference)
               VALUES (?, ?, ?, ?, ?)""",
            (categorie, source, rapport["observations"], rapport["erreur_modele"], rapport["erreur_reference"]))


def apprendre(connexion, chemin_csv):
    """Lit le fichier, entraîne, applique. Tout ou rien : une erreur ne modifie rien."""
    observations, source = lire_csv(chemin_csv)
    estimations = {c: {} for c in CATEGORIES}
    for categorie, mois, coefficient in connexion.execute("SELECT categorie, mois, coefficient FROM coefficients_saison"):
        estimations[categorie][mois] = coefficient
    rapports = entrainer(observations, estimations)
    appliquer(connexion, rapports, source)
    return rapports, source


def afficher(rapports, source):
    noms = {"preparation": "Préparation du sol (tracteurs...)", "recolte": "Récolte (moissonneuses...)"}
    print(f"Source des données : {source}" + ("  (SIMULÉES : démonstration de la chaîne, pas une preuve)" if source != "terrain" else ""))
    for categorie, r in rapports.items():
        print(f"\n{noms[categorie]} : {r['observations']} observations")
        print("  Coefficients appris :", " ".join(f"{m}:{c if c is not None else '-'}" for m, c in r["coefficients"].items()))
        if r["erreur_modele"] is None:
            print("  Évaluation : trop peu de données (au moins 10 observations nécessaires).")
        else:
            print(f"  Erreur moyenne du modèle : {r['erreur_modele'] * 100:.1f} %  |  d'un prix constant : {r['erreur_reference'] * 100:.1f} %")


def main():
    parseur = argparse.ArgumentParser(description="Apprend le calendrier de prix saisonnier à partir d'un historique.")
    parseur.add_argument("--csv", help="fichier de données réelles (colonnes : date, categorie, prix_jour, prix_base)")
    parseur.add_argument("--base", default=os.path.join(DOSSIER, "agrisats.db"), help="base de données à mettre à jour")
    parseur.add_argument("--sans-appliquer", action="store_true", help="affiche le résultat sans modifier la base")
    options = parseur.parse_args()

    chemin = options.csv
    if not chemin:
        if not os.path.exists(CSV_SIMULE):
            print(f"Historique simulé créé : {simuler()} lignes.")
        chemin = CSV_SIMULE
    if not os.path.exists(options.base):
        raise SystemExit("Base introuvable : lancez d'abord python init_db.py")
    connexion = sqlite3.connect(options.base)
    try:
        rapports, source = apprendre(connexion, chemin)
    except ErreurDonnees as erreur:
        connexion.rollback(); connexion.close()
        raise SystemExit(f"Erreur : {erreur}")
    afficher(rapports, source)
    if options.sans_appliquer:
        connexion.rollback()
        print("\nBase non modifiée (--sans-appliquer).")
    else:
        connexion.commit()
        print("\nCoefficients enregistrés dans la base.")
    connexion.close()


if __name__ == "__main__":
    main()
