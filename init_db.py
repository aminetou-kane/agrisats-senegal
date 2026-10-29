import sqlite3
from werkzeug.security import generate_password_hash

connexion = sqlite3.connect("agrisats.db")
connexion.execute("PRAGMA foreign_keys = ON")

# 1. Créer les tables à partir de schema.sql
with open("schema.sql", encoding="utf-8") as fichier:
    connexion.executescript(fichier.read())

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

connexion.commit()
connexion.close()
print("Base de données prête.")