CREATE TABLE IF NOT EXISTS utilisateurs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nom TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    mot_de_passe_hache TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('proprietaire', 'producteur')),
    telephone TEXT
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
    lien_paiement TEXT,
    acompte_fcfa INTEGER,
    acompte_sats INTEGER,
    date_paiement TEXT,
    note TEXT,
    date_creation TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (date_fin >= date_debut),
    FOREIGN KEY (equipement_id) REFERENCES equipements(id),
    FOREIGN KEY (producteur_id) REFERENCES utilisateurs(id)
);

-- Accélère la recherche de conflits de dates pour une machine donnée.
CREATE INDEX IF NOT EXISTS idx_reservations_machine
    ON reservations (equipement_id, date_debut, date_fin);


-- Coefficient de prix par mois et par catégorie de machine (1.3 = +30 %, 0.8 = -20 %).
-- C'est la "mémoire" du module de prix saisonnier : on peut la corriger sans toucher au code.
CREATE TABLE IF NOT EXISTS coefficients_saison (
    categorie TEXT NOT NULL CHECK (categorie IN ('preparation', 'recolte')),
    mois INTEGER NOT NULL CHECK (mois BETWEEN 1 AND 12),
    coefficient REAL NOT NULL CHECK (coefficient > 0 AND coefficient <= 3),
    PRIMARY KEY (categorie, mois)
);


-- Fiche d'évaluation du module d'IA : une ligne à chaque apprentissage et par catégorie.
-- erreur_modele et erreur_reference sont des erreurs moyennes (0.06 = 6 %).
CREATE TABLE IF NOT EXISTS modele_prix (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    categorie TEXT NOT NULL CHECK (categorie IN ('preparation', 'recolte')),
    date_entrainement TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    source TEXT NOT NULL CHECK (source IN ('simule', 'terrain', 'mixte')),
    nb_observations INTEGER NOT NULL,
    erreur_modele REAL,
    erreur_reference REAL
);


-- Factures du mode SIMULATION (démonstration). Aucun vrai paiement : voir paiement_simule.py.
CREATE TABLE IF NOT EXISTS factures_simulees (
    id TEXT PRIMARY KEY,
    reservation_id INTEGER NOT NULL,
    montant_btc TEXT NOT NULL,
    minutes_validite INTEGER NOT NULL CHECK (minutes_validite > 0),
    statut TEXT NOT NULL DEFAULT 'New' CHECK (statut IN ('New', 'Settled')),
    date_creation TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    date_paiement TEXT,
    FOREIGN KEY (reservation_id) REFERENCES reservations(id)
);
