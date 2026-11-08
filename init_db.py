"""Création et mise à jour de la base de données.

Peut être lancé à la main (python init_db.py) ou appelé par l'application au démarrage.
Il est sans danger : il crée ce qui manque, n'écrase jamais ce qui existe.
"""
import os
import sqlite3
from werkzeug.security import generate_password_hash

import ia_prix
from ia_prix import CALENDRIER_DEPART

DOSSIER = os.path.dirname(os.path.abspath(__file__))

# Le calendrier de départ (estimations) est défini dans ia_prix.py.
COEFFICIENTS = CALENDRIER_DEPART


def initialiser(chemin_base=None, avec_demo=True):
    """Crée les tables, ajoute les colonnes manquantes, puis les données de départ.

    avec_demo=False : pas de comptes ni de machines de démonstration.
    """
    chemin_base = chemin_base or os.path.join(DOSSIER, "agrisats.db")
    connexion = sqlite3.connect(chemin_base)
    connexion.execute("PRAGMA foreign_keys = ON")

    # 1. Créer les tables à partir de schema.sql
    with open(os.path.join(DOSSIER, "schema.sql"), encoding="utf-8") as fichier:
        connexion.executescript(fichier.read())

    # 1 bis. Mise à jour d'une base créée avant l'ajout du numéro WhatsApp :
    #        CREATE TABLE IF NOT EXISTS ne modifie pas une table qui existe déjà.
    colonnes = [ligne[1] for ligne in connexion.execute("PRAGMA table_info(utilisateurs)")]
    if "telephone" not in colonnes:
        connexion.execute("ALTER TABLE utilisateurs ADD COLUMN telephone TEXT")

    # 1 ter. Colonnes du paiement Lightning, ajoutées aux réservations d'une base existante.
    colonnes = [ligne[1] for ligne in connexion.execute("PRAGMA table_info(reservations)")]
    for nom_colonne, type_colonne in [("lien_paiement", "TEXT"), ("acompte_fcfa", "INTEGER"),
                                      ("acompte_sats", "INTEGER"), ("date_paiement", "TEXT"),
                                      ("note", "TEXT")]:
        if nom_colonne not in colonnes:
            connexion.execute(f"ALTER TABLE reservations ADD COLUMN {nom_colonne} {type_colonne}")

    # 2. Ajouter des données de démo (seulement si la base est vide)
    nb_utilisateurs = connexion.execute("SELECT COUNT(*) FROM utilisateurs").fetchone()[0]

    if avec_demo and nb_utilisateurs == 0:
        mot_de_passe_demo = generate_password_hash("demo1234")

        utilisateurs = [
            ("Propriétaire Démo 1", "proprio1@example.com", mot_de_passe_demo, "proprietaire"),  # id 1
            ("Propriétaire Démo 2", "proprio2@example.com", mot_de_passe_demo, "proprietaire"),  # id 2
            ("Propriétaire Démo 3", "proprio3@example.com", mot_de_passe_demo, "proprietaire"),  # id 3
            ("Producteur Démo", "producteur@example.com", mot_de_passe_demo, "producteur"),      # id 4
        ]
        connexion.executemany(
            "INSERT INTO utilisateurs (nom, email, mot_de_passe_hache, role) VALUES (?, ?, ?, ?)",
            utilisateurs,
        )

        # (proprietaire_id, nom, type, localite, prix_base_jour, description)
        equipements = [
            (1, "Tracteur John Deere 5090", "tracteur", "Ndiatène", 40000, "Tracteur 90 CV, chauffeur inclus"),
            (1, "Tracteur Massey Ferguson", "tracteur", "Dagana", 35000, "Idéal pour la préparation des parcelles"),
            (1, "Remorque agricole", "remorque", "Thiagar", 15000, "Transport du paddy après récolte"),
            (1, "Motoculteur", "motoculteur", "Saint-Louis", 12000, "Pour petites parcelles et maraîchage"),
            (2, "Moissonneuse-batteuse Kubota", "moissonneuse", "Richard-Toll", 120000, "Moissonneuse pour riz paddy"),
            (2, "Moissonneuse-batteuse Claas", "moissonneuse", "Khor", 130000, "Grande capacité, opérateur inclus"),
            (2, "Batteuse à riz", "batteuse", "Richard-Toll", 25000, "Batteuse mobile pour petits producteurs"),
            (2, "Tracteur New Holland", "tracteur", "Thiagar", 45000, "Tracteur 110 CV avec charrue à disques"),
            (3, "Pompe d'irrigation", "pompe", "Dagana", 10000, "Pompe diesel pour l'irrigation des casiers"),
            (3, "Tracteur Kubota L4508", "tracteur", "Rosso Sénégal", 38000, "Tracteur 45 CV, léger et économe"),
            (3, "Planeuse laser", "planeuse", "Khor", 55000, "Nivellement des parcelles avant semis"),
            (3, "Moissonneuse-batteuse Yanmar", "moissonneuse", "Ndiatène", 110000, "Moissonneuse compacte pour rizières"),
        ]
        connexion.executemany(
            "INSERT INTO equipements (proprietaire_id, nom, type, localite, prix_base_jour, description) VALUES (?, ?, ?, ?, ?, ?)",
            equipements,
        )

    # 3. Calendrier saisonnier de départ (seulement si la table est vide).
    if connexion.execute("SELECT COUNT(*) FROM coefficients_saison").fetchone()[0] == 0:
        for categorie, mois_coefficients in COEFFICIENTS.items():
            for mois, coefficient in mois_coefficients.items():
                connexion.execute(
                    "INSERT INTO coefficients_saison (categorie, mois, coefficient) VALUES (?, ?, ?)",
                    (categorie, mois, coefficient),
                )

    # 4. Premier apprentissage du module d'IA, sur l'historique SIMULÉ fourni avec le projet
    #    (seulement avec les données de démonstration, et une seule fois).
    deja_appris = connexion.execute("SELECT COUNT(*) FROM modele_prix").fetchone()[0]
    if avec_demo and not deja_appris and os.path.exists(ia_prix.CSV_SIMULE):
        try:
            ia_prix.apprendre(connexion, ia_prix.CSV_SIMULE)
        except ia_prix.ErreurDonnees:
            pass    # un fichier abîmé ne doit jamais empêcher le site de démarrer

    connexion.commit()
    connexion.close()


if __name__ == "__main__":
    initialiser()
    print("Base de données prête.")
