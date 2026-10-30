"""AgriSats Sénégal : location de matériel agricole.

Organisation du fichier :
  1. Configuration et sécurité
  2. Outils (base de données, filtres d'affichage, contrôle des photos, droits d'accès)
  3. Pages d'erreur
  4. Catalogue (pages publiques)
  5. Comptes (inscription, connexion, déconnexion)
  6. Espace propriétaire (machines, réservations reçues)
  7. Espace producteur (réservations)
  8. Points d'accroche pour la suite (prix saisonnier IA, paiement Lightning)
"""
import os
import sqlite3
import secrets
from datetime import date, timedelta
from functools import wraps

from dotenv import load_dotenv
from flask import (Flask, g, render_template, request, abort,
                   session, redirect, url_for, flash)
from flask_wtf.csrf import CSRFProtect
from werkzeug.security import generate_password_hash, check_password_hash

# ---------------------------------------------------------------------------
# 1. Configuration et sécurité
# ---------------------------------------------------------------------------
load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY")
if not app.secret_key:
    raise RuntimeError("SECRET_KEY manquante : créez le fichier .env")

app.config["SESSION_COOKIE_HTTPONLY"] = True      # le JavaScript ne peut pas lire le cookie
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"     # le cookie n'est pas envoyé depuis un autre site
# En production (HTTPS), mettre PRODUCTION=1 dans .env : le cookie ne circule plus en clair.
app.config["SESSION_COOKIE_SECURE"] = os.environ.get("PRODUCTION") == "1"
csrf = CSRFProtect(app)                           # jeton secret dans chaque formulaire

DATABASE = "agrisats.db"

UPLOAD_FOLDER = os.path.join(app.root_path, "static", "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024  # 2 Mo maximum par envoi

TYPES_MACHINES = ["tracteur", "moissonneuse", "batteuse", "motoculteur",
                  "remorque", "pompe", "planeuse", "autre"]
LOCALITES = ["Saint-Louis", "Richard-Toll", "Dagana", "Ndiatène",
             "Thiagar", "Khor", "Rosso Sénégal"]

DUREE_BLOCAGE_MINUTES = 15   # une réservation non payée libère les dates après ce délai
DUREE_MAX_JOURS = 30         # durée maximale d'une réservation

MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet",
        "août", "septembre", "octobre", "novembre", "décembre"]


@app.after_request
def en_tetes_de_securite(reponse):
    """Ajoute des consignes de sécurité à chaque réponse envoyée au navigateur."""
    reponse.headers["X-Content-Type-Options"] = "nosniff"   # le navigateur ne devine pas les types de fichiers
    reponse.headers["X-Frame-Options"] = "DENY"             # le site ne peut pas être affiché dans un cadre piégé
    reponse.headers["Referrer-Policy"] = "same-origin"
    if not app.debug:
        # Politique de contenu : seuls nos propres fichiers sont chargés.
        # Désactivée en mode debug pour garder la page d'erreur détaillée lisible.
        reponse.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data:; frame-ancestors 'none'"
        )
    return reponse


# ---------------------------------------------------------------------------
# 2. Outils
# ---------------------------------------------------------------------------
def get_db():
    """Ouvre la base une seule fois par requête."""
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(erreur):
    """Ferme la base à la fin de chaque requête."""
    db = g.pop("db", None)
    if db is not None:
        db.close()


@app.template_filter("fcfa")
def format_fcfa(valeur):
    """40000 devient '40 000 FCFA'."""
    return f"{valeur:,}".replace(",", " ") + " FCFA"


@app.template_filter("datefr")
def format_date_fr(valeur):
    """'2026-11-12' devient '12 novembre 2026'."""
    try:
        jour = date.fromisoformat(valeur)
    except (TypeError, ValueError):
        return valeur
    return f"{jour.day} {MOIS[jour.month - 1]} {jour.year}"


@app.before_request
def charger_utilisateur():
    """Avant chaque page : retrouve l'utilisateur connecté, s'il y en a un."""
    g.user = None
    user_id = session.get("user_id")
    if user_id is not None:
        g.user = get_db().execute(
            "SELECT id, nom, role FROM utilisateurs WHERE id = ?", (user_id,)
        ).fetchone()


def role_requis(role):
    """Réserve une page à un rôle précis (vérifié côté serveur)."""
    def decorateur(vue):
        @wraps(vue)
        def vue_protegee(*args, **kwargs):
            if g.user is None:
                flash("Connectez-vous pour accéder à cette page.", "erreur")
                return redirect(url_for("connexion"))
            if g.user["role"] != role:
                abort(403)
            return vue(*args, **kwargs)
        return vue_protegee
    return decorateur


def type_image(donnees):
    """Reconnaît une vraie image d'après ses premiers octets, pas d'après son nom."""
    if donnees.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if donnees.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if donnees[:4] == b"RIFF" and donnees[8:12] == b"WEBP":
        return "webp"
    return None


def enregistrer_photo(fichier):
    """Contrôle puis enregistre une photo. Retourne (nom_du_fichier, erreur)."""
    donnees = fichier.read()
    extension = type_image(donnees)
    if extension is None:
        return None, "La photo doit être une image JPG, PNG ou WEBP."
    # Nom aléatoire : on n'utilise jamais le nom envoyé par l'utilisateur.
    nom_photo = f"{secrets.token_hex(16)}.{extension}"
    with open(os.path.join(UPLOAD_FOLDER, nom_photo), "wb") as f:
        f.write(donnees)
    return nom_photo, None


def supprimer_photo(nom_photo):
    """Supprime une ancienne photo du disque (si elle existe)."""
    if nom_photo:
        chemin = os.path.join(UPLOAD_FOLDER, os.path.basename(nom_photo))
        if os.path.exists(chemin):
            os.remove(chemin)


def expression_expiree():
    """Morceau de SQL : vrai quand une réservation 'en attente' a dépassé son délai."""
    return ("(r.statut = 'en_attente' "
            "AND r.date_creation <= datetime('now', '-%d minutes'))" % DUREE_BLOCAGE_MINUTES)


# ---------------------------------------------------------------------------
# 3. Pages d'erreur
# ---------------------------------------------------------------------------
def page_erreur(code, titre, texte):
    return render_template("erreur.html", code=code, titre=titre, texte=texte), code


@app.errorhandler(400)
def erreur_400(erreur):
    return page_erreur(400, "Demande refusée",
                       "Votre session a expiré ou le formulaire n'est plus valide. "
                       "Rechargez la page et recommencez.")


@app.errorhandler(403)
def erreur_403(erreur):
    return page_erreur(403, "Accès refusé",
                       "Votre profil ne permet pas d'ouvrir cette page.")


@app.errorhandler(404)
def erreur_404(erreur):
    return page_erreur(404, "Page introuvable",
                       "Cette page n'existe pas, ou la machine n'est plus au catalogue.")


@app.errorhandler(413)
def fichier_trop_gros(erreur):
    flash("La photo dépasse 2 Mo. Choisissez une image plus légère.", "erreur")
    return redirect(url_for("mes_machines"))


@app.errorhandler(500)
def erreur_500(erreur):
    return page_erreur(500, "Un problème est survenu",
                       "Nous n'avons pas pu traiter votre demande. Réessayez dans un instant.")


# ---------------------------------------------------------------------------
# 4. Catalogue (pages publiques)
# ---------------------------------------------------------------------------
@app.route("/")
def accueil():
    db = get_db()
    type_choisi = request.args.get("type", "")
    localite_choisie = request.args.get("localite", "")

    # Les valeurs choisies sont envoyées séparément (les '?') : pas d'injection SQL possible.
    requete = "SELECT * FROM equipements WHERE actif = 1"
    parametres = []
    if type_choisi:
        requete += " AND type = ?"
        parametres.append(type_choisi)
    if localite_choisie:
        requete += " AND localite = ?"
        parametres.append(localite_choisie)
    requete += " ORDER BY nom"

    equipements = db.execute(requete, parametres).fetchall()
    types = [r["type"] for r in db.execute(
        "SELECT DISTINCT type FROM equipements WHERE actif = 1 ORDER BY type")]
    localites = [r["localite"] for r in db.execute(
        "SELECT DISTINCT localite FROM equipements WHERE actif = 1 ORDER BY localite")]

    return render_template(
        "index.html",
        equipements=equipements,
        types=types,
        localites=localites,
        type_choisi=type_choisi,
        localite_choisie=localite_choisie,
    )


@app.route("/equipement/<int:equipement_id>")
def detail_equipement(equipement_id):
    db = get_db()
    equipement = db.execute(
        """
        SELECT e.*, u.nom AS proprietaire_nom
        FROM equipements e
        JOIN utilisateurs u ON u.id = e.proprietaire_id
        WHERE e.id = ? AND e.actif = 1
        """,
        (equipement_id,),
    ).fetchone()
    if equipement is None:
        abort(404)

    # Périodes déjà prises (on ne montre pas qui a réservé).
    periodes = db.execute(
        """SELECT r.date_debut, r.date_fin FROM reservations r
           WHERE r.equipement_id = ? AND r.date_fin >= date('now')
             AND (r.statut = 'confirmee'
                  OR (r.statut = 'en_attente'
                      AND r.date_creation > datetime('now', ?)))
           ORDER BY r.date_debut""",
        (equipement_id, f"-{DUREE_BLOCAGE_MINUTES} minutes"),
    ).fetchall()

    return render_template(
        "detail.html",
        equipement=equipement,
        periodes=periodes,
        aujourdhui=date.today().isoformat(),
        duree_max=DUREE_MAX_JOURS,
    )


# ---------------------------------------------------------------------------
# 5. Comptes
# ---------------------------------------------------------------------------
@app.route("/inscription", methods=["GET", "POST"])
def inscription():
    erreur = None
    if request.method == "POST":
        nom = request.form.get("nom", "").strip()
        email = request.form.get("email", "").strip().lower()
        mot_de_passe = request.form.get("mot_de_passe", "")
        role = request.form.get("role", "")

        if not nom or len(nom) > 80:
            erreur = "Saisissez votre nom (80 caractères maximum)."
        elif "@" not in email or len(email) > 120:
            erreur = "Saisissez une adresse email valide."
        elif len(mot_de_passe) < 8:
            erreur = "Le mot de passe doit contenir au moins 8 caractères."
        elif role not in ("proprietaire", "producteur"):
            erreur = "Choisissez votre profil."
        else:
            db = get_db()
            existe = db.execute(
                "SELECT id FROM utilisateurs WHERE email = ?", (email,)
            ).fetchone()
            if existe:
                erreur = "Un compte existe déjà avec cet email."
            else:
                db.execute(
                    "INSERT INTO utilisateurs (nom, email, mot_de_passe_hache, role) VALUES (?, ?, ?, ?)",
                    (nom, email, generate_password_hash(mot_de_passe), role),
                )
                db.commit()
                flash("Compte créé. Vous pouvez maintenant vous connecter.")
                return redirect(url_for("connexion"))

    # Ce return est volontairement HORS du "if POST" : il sert pour l'affichage
    # initial de la page (GET) et pour réafficher le formulaire après une erreur.
    return render_template(
        "inscription.html",
        erreur=erreur,
        nom=request.form.get("nom", ""),
        email=request.form.get("email", ""),
        role=request.form.get("role", ""),
    )


@app.route("/connexion", methods=["GET", "POST"])
def connexion():
    erreur = None
    email = ""
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        mot_de_passe = request.form.get("mot_de_passe", "")

        utilisateur = get_db().execute(
            "SELECT * FROM utilisateurs WHERE email = ?", (email,)
        ).fetchone()

        # Même message que l'email existe ou non : on ne révèle pas qui a un compte.
        if utilisateur is None or not check_password_hash(
            utilisateur["mot_de_passe_hache"], mot_de_passe
        ):
            erreur = "Email ou mot de passe incorrect."
        else:
            session.clear()
            session["user_id"] = utilisateur["id"]
            if utilisateur["role"] == "proprietaire":
                return redirect(url_for("mes_machines"))
            return redirect(url_for("accueil"))
    return render_template("connexion.html", erreur=erreur, email=email)


@app.route("/deconnexion", methods=["POST"])
def deconnexion():
    session.clear()
    return redirect(url_for("accueil"))


# ---------------------------------------------------------------------------
# 6. Espace propriétaire
# ---------------------------------------------------------------------------
def lire_formulaire_machine():
    """Lit et contrôle le formulaire d'une machine. Retourne (valeurs, erreur)."""
    valeurs = {
        "nom": request.form.get("nom", "").strip(),
        "type": request.form.get("type", ""),
        "localite": request.form.get("localite", ""),
        "description": request.form.get("description", "").strip()[:500],
        "prix_base_jour": request.form.get("prix_base_jour", "").strip(),
    }
    try:
        prix = int(valeurs["prix_base_jour"])
    except ValueError:
        prix = 0

    erreur = None
    if not valeurs["nom"] or len(valeurs["nom"]) > 80:
        erreur = "Saisissez le nom de la machine (80 caractères maximum)."
    elif valeurs["type"] not in TYPES_MACHINES:
        erreur = "Choisissez un type de machine."
    elif valeurs["localite"] not in LOCALITES:
        erreur = "Choisissez une localité."
    elif prix <= 0 or prix > 10_000_000:
        erreur = "Le prix par jour doit être un nombre positif."
    valeurs["prix"] = prix
    return valeurs, erreur


@app.route("/mes-machines")
@role_requis("proprietaire")
def mes_machines():
    machines = get_db().execute(
        "SELECT * FROM equipements WHERE proprietaire_id = ? AND actif = 1 ORDER BY id DESC",
        (g.user["id"],),
    ).fetchall()
    return render_template("mes_machines.html", machines=machines)


@app.route("/machines/nouvelle", methods=["GET", "POST"])
@role_requis("proprietaire")
def nouvelle_machine():
    erreur = None
    valeurs = {}
    if request.method == "POST":
        valeurs, erreur = lire_formulaire_machine()
        nom_photo = None
        fichier = request.files.get("photo")
        if erreur is None and fichier and fichier.filename:
            nom_photo, erreur = enregistrer_photo(fichier)

        if erreur is None:
            db = get_db()
            db.execute(
                """INSERT INTO equipements
                   (proprietaire_id, nom, type, localite, prix_base_jour, description, photo)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (g.user["id"], valeurs["nom"], valeurs["type"], valeurs["localite"],
                 valeurs["prix"], valeurs["description"], nom_photo),
            )
            db.commit()
            flash("Votre machine est maintenant au catalogue.")
            return redirect(url_for("mes_machines"))

    return render_template(
        "formulaire_machine.html",
        modification=False, machine=None, erreur=erreur, form=valeurs,
        types=TYPES_MACHINES, localites=LOCALITES,
    )


@app.route("/machines/<int:equipement_id>/modifier", methods=["GET", "POST"])
@role_requis("proprietaire")
def modifier_machine(equipement_id):
    db = get_db()
    # "AND proprietaire_id = ?" : on ne peut modifier que ses propres machines.
    machine = db.execute(
        "SELECT * FROM equipements WHERE id = ? AND proprietaire_id = ? AND actif = 1",
        (equipement_id, g.user["id"]),
    ).fetchone()
    if machine is None:
        abort(404)

    erreur = None
    valeurs = {
        "nom": machine["nom"], "type": machine["type"], "localite": machine["localite"],
        "description": machine["description"] or "", "prix_base_jour": machine["prix_base_jour"],
    }
    if request.method == "POST":
        valeurs, erreur = lire_formulaire_machine()
        nom_photo = machine["photo"]
        fichier = request.files.get("photo")
        if erreur is None and fichier and fichier.filename:
            nouvelle_photo, erreur = enregistrer_photo(fichier)
            if erreur is None:
                supprimer_photo(machine["photo"])
                nom_photo = nouvelle_photo

        if erreur is None:
            db.execute(
                """UPDATE equipements
                   SET nom = ?, type = ?, localite = ?, prix_base_jour = ?,
                       description = ?, photo = ?
                   WHERE id = ? AND proprietaire_id = ?""",
                (valeurs["nom"], valeurs["type"], valeurs["localite"], valeurs["prix"],
                 valeurs["description"], nom_photo, equipement_id, g.user["id"]),
            )
            db.commit()
            flash("Les modifications sont enregistrées.")
            return redirect(url_for("mes_machines"))

    return render_template(
        "formulaire_machine.html",
        modification=True, machine=machine, erreur=erreur, form=valeurs,
        types=TYPES_MACHINES, localites=LOCALITES,
    )


@app.route("/machines/<int:equipement_id>/retirer", methods=["POST"])
@role_requis("proprietaire")
def retirer_machine(equipement_id):
    db = get_db()
    # Retrait "doux" : actif passe à 0, la ligne reste (l'historique des réservations est conservé).
    db.execute(
        "UPDATE equipements SET actif = 0 WHERE id = ? AND proprietaire_id = ?",
        (equipement_id, g.user["id"]),
    )
    db.commit()
    flash("La machine a été retirée du catalogue.")
    return redirect(url_for("mes_machines"))


@app.route("/reservations-recues")
@role_requis("proprietaire")
def reservations_recues():
    reservations = get_db().execute(
        f"""SELECT r.*, e.nom AS machine_nom, e.localite, u.nom AS producteur_nom,
                   julianday(r.date_fin) - julianday(r.date_debut) + 1 AS nb_jours,
                   {expression_expiree()} AS expiree
            FROM reservations r
            JOIN equipements e ON e.id = r.equipement_id
            JOIN utilisateurs u ON u.id = r.producteur_id
            WHERE e.proprietaire_id = ?
              AND r.statut != 'annulee'
            ORDER BY r.date_debut DESC""",
        (g.user["id"],),
    ).fetchall()
    return render_template("reservations_recues.html", reservations=reservations)


# ---------------------------------------------------------------------------
# 7. Espace producteur
# ---------------------------------------------------------------------------
@app.route("/equipement/<int:equipement_id>/reserver", methods=["POST"])
@role_requis("producteur")
def reserver(equipement_id):
    db = get_db()
    equipement = db.execute(
        "SELECT * FROM equipements WHERE id = ? AND actif = 1", (equipement_id,)
    ).fetchone()
    if equipement is None:
        abort(404)

    retour = redirect(url_for("detail_equipement", equipement_id=equipement_id))

    try:
        debut = date.fromisoformat(request.form.get("date_debut", ""))
        fin = date.fromisoformat(request.form.get("date_fin", ""))
    except ValueError:
        flash("Choisissez une date de début et une date de fin.", "erreur")
        return retour

    if debut < date.today():
        flash("La date de début ne peut pas être dans le passé.", "erreur")
        return retour
    if fin < debut:
        flash("La date de fin doit être le même jour ou après la date de début.", "erreur")
        return retour
    if (fin - debut).days + 1 > DUREE_MAX_JOURS:
        flash(f"Une réservation ne peut pas dépasser {DUREE_MAX_JOURS} jours.", "erreur")
        return retour

    # On verrouille la base le temps de vérifier puis d'enregistrer : deux producteurs
    # ne peuvent pas réserver la même période au même moment.
    db.execute("BEGIN IMMEDIATE")
    conflit = db.execute(
        """SELECT id, producteur_id, statut FROM reservations
           WHERE equipement_id = ?
             AND date_debut <= ? AND date_fin >= ?
             AND (statut = 'confirmee'
                  OR (statut = 'en_attente' AND date_creation > datetime('now', ?)))""",
        (equipement_id, fin.isoformat(), debut.isoformat(),
         f"-{DUREE_BLOCAGE_MINUTES} minutes"),
    ).fetchone()
    if conflit:
        db.rollback()
        if conflit["producteur_id"] == g.user["id"] and conflit["statut"] == "en_attente":
            flash("Vous avez déjà une réservation en attente sur cette période.")
            return redirect(url_for("voir_reservation", reservation_id=conflit["id"]))
        flash("Cette machine est déjà réservée sur tout ou une partie de cette période.", "erreur")
        return retour

    # Le prix est calculé ICI, côté serveur : il ne vient jamais du navigateur.
    prix_total = calculer_prix(equipement["prix_base_jour"], debut, fin)
    curseur = db.execute(
        """INSERT INTO reservations
           (equipement_id, producteur_id, date_debut, date_fin, prix_total)
           VALUES (?, ?, ?, ?, ?)""",
        (equipement_id, g.user["id"], debut.isoformat(), fin.isoformat(), prix_total),
    )
    db.commit()
    return redirect(url_for("voir_reservation", reservation_id=curseur.lastrowid))


def lire_reservation(reservation_id):
    """Retrouve une réservation du producteur connecté (jamais celle d'un autre)."""
    reservation = get_db().execute(
        f"""SELECT r.*, e.nom AS machine_nom, e.localite, e.photo, e.type,
                   julianday(r.date_fin) - julianday(r.date_debut) + 1 AS nb_jours,
                   {expression_expiree()} AS expiree
            FROM reservations r
            JOIN equipements e ON e.id = r.equipement_id
            WHERE r.id = ? AND r.producteur_id = ?""",
        (reservation_id, g.user["id"]),
    ).fetchone()
    if reservation is None:
        abort(404)
    return reservation


@app.route("/reservations/<int:reservation_id>")
@role_requis("producteur")
def voir_reservation(reservation_id):
    return render_template(
        "reservation.html",
        r=lire_reservation(reservation_id),
        duree_blocage=DUREE_BLOCAGE_MINUTES,
    )


@app.route("/reservations/<int:reservation_id>/annuler", methods=["POST"])
@role_requis("producteur")
def annuler_reservation(reservation_id):
    db = get_db()
    # Seule une réservation encore "en attente" et appartenant à ce producteur peut être annulée.
    db.execute(
        """UPDATE reservations SET statut = 'annulee'
           WHERE id = ? AND producteur_id = ? AND statut = 'en_attente'""",
        (reservation_id, g.user["id"]),
    )
    db.commit()
    flash("La réservation est annulée. Les dates sont de nouveau libres.")
    return redirect(url_for("mes_reservations"))


@app.route("/mes-reservations")
@role_requis("producteur")
def mes_reservations():
    reservations = get_db().execute(
        f"""SELECT r.*, e.nom AS machine_nom, e.localite,
                   julianday(r.date_fin) - julianday(r.date_debut) + 1 AS nb_jours,
                   {expression_expiree()} AS expiree
            FROM reservations r
            JOIN equipements e ON e.id = r.equipement_id
            WHERE r.producteur_id = ?
            ORDER BY r.id DESC""",
        (g.user["id"],),
    ).fetchall()
    return render_template("mes_reservations.html", reservations=reservations)


# ---------------------------------------------------------------------------
# 8. Points d'accroche pour la suite (on les remplira ensemble)
# ---------------------------------------------------------------------------
def coefficient_saison(jour):
    """PRIX SAISONNIER (module IA, à venir). Pour l'instant : aucun effet (1.0)."""
    return 1.0


def calculer_prix(prix_base, date_debut, date_fin):
    """Somme du prix de chaque jour, début et fin inclus."""
    total = 0
    jour = date_debut
    while jour <= date_fin:
        total += prix_base * coefficient_saison(jour)
        jour += timedelta(days=1)
    return round(total)


# PAIEMENT LIGHTNING (à venir) : c'est ici qu'on ajoutera la création de la facture
# BTCPay Server, puis la route qui reçoit la confirmation de paiement (webhook)
# et passe la réservation à 'confirmee'.


if __name__ == "__main__":
    app.run(debug=True)
