import sqlite3
from werkzeug.security import generate_password_hash

connexion = sqlite3.connect("agrisats.db")
connexion.execute("PRAGMA foreign_keys = ON")

# 1. Créer les tables à partir de schema.sql
with open("schema.sql", encoding="utf-8") as fichier:
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

if nb_utilisateurs == 0:
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
# ATTENTION : ce sont des ESTIMATIONS à valider avec des propriétaires et des producteurs
# de la vallée (sources publiques partielles, calendriers parfois contradictoires).
COEFFICIENTS = {
    # tracteurs, motoculteurs, planeuses : pointe avant les semis (début d'année et début d'hivernage)
    "preparation": {1: 1.3, 2: 1.3, 3: 1.0, 4: 0.8, 5: 0.8, 6: 1.3,
                    7: 1.3, 8: 1.0, 9: 0.8, 10: 0.8, 11: 1.0, 12: 1.0},
    # moissonneuses, batteuses : pointe aux deux récoltes (mi-année et fin d'année)
    "recolte": {1: 0.8, 2: 0.8, 3: 0.8, 4: 1.0, 5: 1.0, 6: 1.4,
                7: 1.4, 8: 0.8, 9: 0.8, 10: 1.0, 11: 1.4, 12: 1.4},
}
if connexion.execute("SELECT COUNT(*) FROM coefficients_saison").fetchone()[0] == 0:
    for categorie, mois_coefficients in COEFFICIENTS.items():
        for mois, coefficient in mois_coefficients.items():
            connexion.execute(
                "INSERT INTO coefficients_saison (categorie, mois, coefficient) VALUES (?, ?, ?)",
                (categorie, mois, coefficient),
            )

connexion.commit()
connexion.close()
print("Base de données prête.")