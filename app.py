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
import json
import math
import os
import re
import sqlite3
import secrets
from decimal import Decimal
from urllib.parse import quote
from datetime import date, timedelta
from functools import wraps

from dotenv import load_dotenv
from flask import (Flask, g, render_template, request, abort,
                   session, redirect, url_for, flash)
from flask_wtf.csrf import CSRFProtect
from werkzeug.security import generate_password_hash, check_password_hash

import btcpay

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


def lire_pourcentage_acompte():
    """Part du prix payée en Lightning (réglage ACOMPTE_POURCENT du fichier .env, 30 par défaut)."""
    try:
        valeur = int(os.environ.get("ACOMPTE_POURCENT", "30"))
    except ValueError:
        return 30
    return valeur if 1 <= valeur <= 100 else 30


ACOMPTE_POURCENT = lire_pourcentage_acompte()

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


@app.template_filter("telfr")
def format_telephone(valeur):
    """'221771234567' devient '+221 77 123 45 67'."""
    if not valeur or not re.fullmatch(r"221[0-9]{9}", valeur):
        return valeur
    return f"+221 {valeur[3:5]} {valeur[5:8]} {valeur[8:10]} {valeur[10:12]}"


def normaliser_telephone(texte):
    """Contrôle un numéro sénégalais. Retourne (numéro, erreur).

    Accepte '77 123 45 67', '+221 77 123 45 67', '00221771234567'...
    Le numéro enregistré ne contient que des chiffres : '221771234567'.
    """
    chiffres = re.sub(r"[ .\-()]", "", texte.strip())
    if chiffres.startswith("+"):
        chiffres = chiffres[1:]
    if chiffres.startswith("00"):
        chiffres = chiffres[2:]
    if re.fullmatch(r"[0-9]{9}", chiffres):
        chiffres = "221" + chiffres
    # [0-9] et non \d : \d accepterait aussi des chiffres d'autres alphabets.
    if re.fullmatch(r"2217[0-9]{8}", chiffres):
        return chiffres, None
    return None, "Saisissez un numéro sénégalais valide, par exemple 77 123 45 67."


def lien_whatsapp(telephone, message):
    """Construit le lien qui ouvre WhatsApp avec un message déjà écrit."""
    if not telephone or not re.fullmatch(r"2217[0-9]{8}", telephone):
        return None
    return f"https://wa.me/{telephone}?text={quote(message)}"


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
        SELECT e.*, u.nom AS proprietaire_nom, u.telephone AS proprietaire_tel
        FROM equipements e
        JOIN utilisateurs u ON u.id = e.proprietaire_id
        WHERE e.id = ? AND e.actif = 1
        """,
        (equipement_id,),
    ).fetchone()
    if equipement is None:
        abort(404)

    # Le numéro n'est transmis à la page que pour un producteur connecté.
    lien_wa = None
    if g.user and g.user["role"] == "producteur":
        lien_wa = lien_whatsapp(
            equipement["proprietaire_tel"],
            f"Bonjour, je suis intéressé(e) par votre {equipement['nom']} "
            f"({equipement['localite']}) vu sur AgriSats Sénégal. Est-elle disponible ?",
        )

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
        lien_wa=lien_wa,
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
        telephone = None

        if not nom or len(nom) > 80:
            erreur = "Saisissez votre nom (80 caractères maximum)."
        elif "@" not in email or len(email) > 120:
            erreur = "Saisissez une adresse email valide."
        elif len(mot_de_passe) < 8:
            erreur = "Le mot de passe doit contenir au moins 8 caractères."
        elif role not in ("proprietaire", "producteur"):
            erreur = "Choisissez votre profil."
        elif role == "proprietaire":
            # Seuls les propriétaires publient un numéro : les producteurs les contactent.
            telephone, erreur = normaliser_telephone(request.form.get("telephone", ""))
            if erreur:
                erreur = "Propriétaires : indiquez votre numéro WhatsApp. " + erreur

        if erreur is None:
            db = get_db()
            existe = db.execute(
                "SELECT id FROM utilisateurs WHERE email = ?", (email,)
            ).fetchone()
            if existe:
                erreur = "Un compte existe déjà avec cet email."
            else:
                db.execute(
                    "INSERT INTO utilisateurs (nom, email, mot_de_passe_hache, role, telephone) VALUES (?, ?, ?, ?, ?)",
                    (nom, email, generate_password_hash(mot_de_passe), role, telephone),
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
        telephone=request.form.get("telephone", ""),
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
    telephone = get_db().execute(
        "SELECT telephone FROM utilisateurs WHERE id = ?", (g.user["id"],)
    ).fetchone()["telephone"]
    return render_template("mes_machines.html", machines=machines, telephone=telephone)


@app.route("/mon-profil", methods=["GET", "POST"])
@role_requis("proprietaire")
def mon_profil():
    db = get_db()
    erreur = None
    telephone = db.execute(
        "SELECT telephone FROM utilisateurs WHERE id = ?", (g.user["id"],)
    ).fetchone()["telephone"]

    if request.method == "POST":
        saisie = request.form.get("telephone", "").strip()
        if saisie == "":
            nouveau = None   # le propriétaire retire son numéro
        else:
            nouveau, erreur = normaliser_telephone(saisie)
        if erreur is None:
            db.execute("UPDATE utilisateurs SET telephone = ? WHERE id = ?",
                       (nouveau, g.user["id"]))
            db.commit()
            flash("Votre numéro WhatsApp est enregistré." if nouveau
                  else "Votre numéro WhatsApp a été retiré.")
            return redirect(url_for("mon_profil"))
        telephone = saisie

    return render_template("profil.html", erreur=erreur, telephone=telephone)


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
                   u.telephone AS proprietaire_tel,
                   julianday(r.date_fin) - julianday(r.date_debut) + 1 AS nb_jours,
                   {DUREE_BLOCAGE_MINUTES} - (julianday('now') - julianday(r.date_creation)) * 1440
                       AS minutes_restantes,
                   {expression_expiree()} AS expiree
            FROM reservations r
            JOIN equipements e ON e.id = r.equipement_id
            JOIN utilisateurs u ON u.id = e.proprietaire_id
            WHERE r.id = ? AND r.producteur_id = ?""",
        (reservation_id, g.user["id"]),
    ).fetchone()
    if reservation is None:
        abort(404)
    return reservation


@app.route("/reservations/<int:reservation_id>")
@role_requis("producteur")
def voir_reservation(reservation_id):
    reservation = lire_reservation(reservation_id)

    # Si une facture existe, on demande à BTCPay si elle est payée (sans attendre le webhook).
    if synchroniser_paiement(reservation):
        reservation = lire_reservation(reservation_id)
        if reservation["statut"] == "confirmee":
            flash("Acompte reçu : votre réservation est confirmée.")

    if reservation["acompte_fcfa"] is not None:
        acompte, sats = reservation["acompte_fcfa"], reservation["acompte_sats"]
    else:
        acompte, sats = calculer_acompte(reservation["prix_total"])
    lien_wa = lien_whatsapp(
        reservation["proprietaire_tel"],
        f"Bonjour, j'ai réservé votre {reservation['machine_nom']} du "
        f"{format_date_fr(reservation['date_debut'])} au {format_date_fr(reservation['date_fin'])} "
        f"sur AgriSats Sénégal (réservation n° {reservation['id']}). "
        "Pouvons-nous convenir des modalités de paiement ?",
    )
    return render_template(
        "reservation.html",
        r=reservation,
        lien_wa=lien_wa,
        duree_blocage=DUREE_BLOCAGE_MINUTES,
        acompte=acompte,
        sats=sats,
        solde=reservation["prix_total"] - acompte,
        pourcent=ACOMPTE_POURCENT,
        paiement_actif=paiement_actif(),
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


# ---------------------------------------------------------------------------
# 9. Paiement de l'acompte en Bitcoin Lightning (BTCPay Server)
# ---------------------------------------------------------------------------
# Principe : le navigateur ne dit JAMAIS "c'est payé". Seul BTCPay peut le dire, et
# notre serveur le vérifie lui-même auprès de BTCPay avant de confirmer la réservation.
def paiement_actif():
    """Vrai si BTCPay et le taux de conversion sont configurés dans .env."""
    return btcpay.disponible() and taux_fcfa_par_btc() is not None


def taux_fcfa_par_btc():
    """Taux fixe de démonstration : combien de FCFA vaut 1 BTC (réglage du fichier .env)."""
    try:
        taux = int(os.environ.get("TAUX_FCFA_PAR_BTC", ""))
    except ValueError:
        return None
    return taux if taux > 0 else None


def calculer_acompte(prix_total):
    """Retourne (acompte en FCFA, acompte en satoshis ou None si le taux manque)."""
    acompte = max(1, round(prix_total * ACOMPTE_POURCENT / 100))
    taux = taux_fcfa_par_btc()
    sats = max(1, math.ceil(acompte * 100_000_000 / taux)) if taux else None
    return acompte, sats


def sats_en_btc(sats):
    """12345 devient '0.00012345' (texte exact, sans arrondi flottant)."""
    return str((Decimal(sats) / Decimal(100_000_000)).quantize(Decimal("0.00000001")))


@app.template_filter("espaces")
def format_nombre(valeur):
    """12345 devient '12 345'."""
    return f"{int(valeur):,}".replace(",", " ")


def lien_externe_sur(lien):
    """On ne redirige le client que vers une adresse https (ou locale pour les essais)."""
    return isinstance(lien, str) and (
        lien.startswith("https://") or lien.startswith("http://127.0.0.1") or lien.startswith("http://localhost"))


def appliquer_facture(reservation_id, facture):
    """Confirme la réservation SI ET SEULEMENT SI la facture est réellement payée.

    Retourne 'confirmee', 'incident' (payé, mais les dates ne sont plus libres),
    ou None (rien à faire).
    """
    db = get_db()
    # Verrou : si le webhook et la page arrivent en même temps, une seule confirmation passe.
    db.execute("BEGIN IMMEDIATE")
    reservation = db.execute(
        "SELECT * FROM reservations WHERE id = ? AND statut = 'en_attente'", (reservation_id,)
    ).fetchone()
    if reservation is None or not reservation["id_facture"]:
        db.rollback()
        return None

    metadonnees = facture.get("metadata") or {}
    try:
        montant_ok = (reservation["acompte_sats"] is not None and
                      Decimal(str(facture.get("amount"))) == Decimal(sats_en_btc(reservation["acompte_sats"])))
    except ArithmeticError:
        montant_ok = False
    conforme = (
        facture.get("status") == "Settled"                         # payée en totalité
        and facture.get("id") == reservation["id_facture"]         # c'est bien NOTRE facture
        and str(metadonnees.get("orderId")) == str(reservation["id"])  # pour CETTE réservation
        and montant_ok                                             # pour le montant attendu
    )
    if not conforme:
        db.rollback()
        return None

    # Les dates sont-elles encore libres ? (la réservation a pu expirer avant le paiement)
    conflit = db.execute(
        """SELECT id FROM reservations
           WHERE equipement_id = ? AND id != ?
             AND date_debut <= ? AND date_fin >= ?
             AND (statut = 'confirmee'
                  OR (statut = 'en_attente' AND date_creation > datetime('now', ?)))""",
        (reservation["equipement_id"], reservation["id"], reservation["date_fin"],
         reservation["date_debut"], f"-{DUREE_BLOCAGE_MINUTES} minutes"),
    ).fetchone()
    if conflit:
        db.execute(
            """UPDATE reservations SET statut = 'annulee', date_paiement = datetime('now'),
                   note = 'Acompte reçu après la perte des dates : remboursement à effectuer.'
               WHERE id = ?""", (reservation["id"],))
        db.commit()
        return "incident"

    db.execute("UPDATE reservations SET statut = 'confirmee', date_paiement = datetime('now') WHERE id = ?",
               (reservation["id"],))
    db.commit()
    return "confirmee"


def synchroniser_paiement(reservation):
    """Demande à BTCPay si la facture d'une réservation en attente est payée."""
    if reservation["statut"] != "en_attente" or not reservation["id_facture"] or not btcpay.disponible():
        return False
    try:
        facture = btcpay.lire_facture(reservation["id_facture"])
    except btcpay.ErreurBTCPay:
        return False          # BTCPay indisponible : on réessaiera au prochain affichage
    return appliquer_facture(reservation["id"], facture) is not None


@app.route("/reservations/<int:reservation_id>/payer", methods=["POST"])
@role_requis("producteur")
def payer_reservation(reservation_id):
    reservation = lire_reservation(reservation_id)      # 404 si ce n'est pas la sienne
    retour = redirect(url_for("voir_reservation", reservation_id=reservation_id))

    if reservation["statut"] != "en_attente" or reservation["expiree"]:
        flash("Cette réservation n'est plus en attente de paiement.", "erreur")
        return retour
    if not paiement_actif():
        flash("Le paiement Lightning n'est pas configuré sur ce serveur.", "erreur")
        return retour

    try:
        # Une facture existe déjà ? On la réutilise si elle est encore valable.
        if reservation["id_facture"]:
            facture = btcpay.lire_facture(reservation["id_facture"])
            if appliquer_facture(reservation_id, facture) == "confirmee":
                flash("Acompte reçu : votre réservation est confirmée.")
                return retour
            if facture.get("status") == "New" and lien_externe_sur(reservation["lien_paiement"]):
                return redirect(reservation["lien_paiement"])

        acompte, sats = calculer_acompte(reservation["prix_total"])
        # La facture ne doit pas vivre plus longtemps que le blocage des dates.
        minutes = max(1, int(reservation["minutes_restantes"]))
        site = os.environ.get("SITE_URL", "").rstrip("/")
        url_retour = f"{site}{url_for('voir_reservation', reservation_id=reservation_id)}" if site else None
        facture = btcpay.creer_facture(sats_en_btc(sats), reservation_id, minutes, url_retour)
    except btcpay.ErreurBTCPay:
        flash("Le service de paiement ne répond pas. Réessayez dans un instant.", "erreur")
        return retour

    lien = facture.get("checkoutLink")
    if not facture.get("id") or not lien_externe_sur(lien):
        flash("Le service de paiement a renvoyé une réponse inattendue.", "erreur")
        return retour

    db = get_db()
    db.execute(
        """UPDATE reservations SET id_facture = ?, lien_paiement = ?, acompte_fcfa = ?, acompte_sats = ?
           WHERE id = ? AND producteur_id = ? AND statut = 'en_attente'""",
        (facture["id"], lien, acompte, sats, reservation_id, g.user["id"]),
    )
    db.commit()
    return redirect(lien)


@app.route("/btcpay/webhook", methods=["POST"])
@csrf.exempt          # BTCPay n'a pas de jeton CSRF : il est authentifié par sa signature
def webhook_btcpay():
    """Notification de BTCPay. On vérifie la signature, puis on redemande la facture à BTCPay."""
    secret = os.environ.get("BTCPAY_WEBHOOK_SECRET", "")
    if not secret:
        abort(503)
    corps = request.get_data()                     # le contenu EXACT, tel que signé
    if not btcpay.verifier_signature(corps, request.headers.get("BTCPay-Sig", ""), secret):
        abort(401)
    try:
        evenement = json.loads(corps)
    except ValueError:
        abort(400)

    if isinstance(evenement, dict) and evenement.get("type") == "InvoiceSettled" and evenement.get("invoiceId"):
        reservation = get_db().execute(
            "SELECT id FROM reservations WHERE id_facture = ?", (str(evenement["invoiceId"]),)
        ).fetchone()
        if reservation:
            try:
                # On ne se fie pas au contenu de la notification : on lit la facture chez BTCPay.
                appliquer_facture(reservation["id"], btcpay.lire_facture(str(evenement["invoiceId"])))
            except btcpay.ErreurBTCPay:
                abort(503)                          # BTCPay réessaiera plus tard
    return "ok", 200


if __name__ == "__main__":
    app.run(debug=True)
