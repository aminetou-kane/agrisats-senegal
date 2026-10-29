CREATE TABLE IF NOT EXISTS utilisateurs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nom TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    mot_de_passe_hache TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('proprietaire', 'producteur'))
);

CREATE TABLE IF NOT EXISTS equipements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    proprietaire_id INTEGER NOT NULL,
    nom TEXT NOT NULL,
    type TEXT NOT NULL,
    localite TEXT NOT NULL,
    prix_base_jour INTEGER NOT NULL CHECK (prix_base_jour > 0),
    description TEXT,
    photo TEXT,
    actif INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY (proprietaire_id) REFERENCES utilisateurs(id)
);
