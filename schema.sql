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


CREATE TABLE IF NOT EXISTS reservations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    equipement_id INTEGER NOT NULL,
    producteur_id INTEGER NOT NULL,
    date_debut TEXT NOT NULL,
    date_fin TEXT NOT NULL,
    prix_total INTEGER NOT NULL CHECK (prix_total > 0),
    statut TEXT NOT NULL DEFAULT 'en_attente'
        CHECK (statut IN ('en_attente', 'confirmee', 'annulee')),
    id_facture TEXT,
    date_creation TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (date_fin >= date_debut),
    FOREIGN KEY (equipement_id) REFERENCES equipements(id),
    FOREIGN KEY (producteur_id) REFERENCES utilisateurs(id)
);

-- Accélère la recherche de conflits de dates pour une machine donnée.
CREATE INDEX IF NOT EXISTS idx_reservations_machine
    ON reservations (equipement_id, date_debut, date_fin);
