import os
import sqlite3
import secrets
from functools import wraps
from dotenv import load_dotenv
from flask import (Flask, g, render_template, request, abort,
                   session, redirect, url_for, flash)
from flask_wtf.csrf import CSRFProtect
from werkzeug.security import generate_password_hash, check_password_hash

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY")
if not app.secret_key:
    raise RuntimeError("SECRET_KEY manquante : créez le fichier .env")

app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
csrf = CSRFProtect(app)

DATABASE = "agrisats.db"

UPLOAD_FOLDER = os.path.join(app.root_path, "static", "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024  # 2 Mo maximum

TYPES_MACHINES = ["tracteur", "moissonneuse", "batteuse", "motoculteur",
                  "remorque", "pompe", "planeuse", "autre"]
LOCALITES = ["Saint-Louis", "Richard-Toll", "Dagana", "Ndiatène",
             "Thiagar", "Khor", "Rosso Sénégal"]


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


@app.route("/")
def accueil():
    db = get_db()
    type_choisi = request.args.get("type", "")
    localite_choisie = request.args.get("localite", "")

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

    return render_template("detail.html", equipement=equipement)

@app.before_request
def charger_utilisateur():
    """Avant chaque page : retrouve l'utilisateur connecté, s'il y en a un."""
    g.user = None
    user_id = session.get("user_id")
    if user_id is not None:
        g.user = get_db().execute(
            "SELECT id, nom, role FROM utilisateurs WHERE id = ?", (user_id,)
        ).fetchone()


@app.route("/inscription", methods=["GET", "POST"])
def inscription():
    erreur = None
    if request.method == "POST":
        nom = request.form.get("nom", "").strip()
        email = request.form.get("email", "").strip().lower()
        mot_de_passe = request.form.get("mot_de_passe", "")
        role = request.form.get("role", "")

        if not nom or len(nom) > 80:
            erreur = "Veuillez saisir un nom valide."
        elif "@" not in email or len(email) > 120:
            erreur = "Veuillez saisir un email valide."
        elif len(mot_de_passe) < 8:
            erreur = "Le mot de passe doit contenir au moins 8 caractères."
        elif role not in ("proprietaire", "producteur"):
            erreur = "Veuillez choisir un profil."
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
                flash("Compte créé. Vous pouvez vous connecter.")
                return redirect(url_for("connexion"))
        return render_template(
        "inscription.html",
        erreur=erreur,
        nom=request.form.get("nom", ""),
        email=request.form.get("email", ""),
    )


@app.route("/connexion", methods=["GET", "POST"])
def connexion():
    erreur = None
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        mot_de_passe = request.form.get("mot_de_passe", "")

        utilisateur = get_db().execute(
            "SELECT * FROM utilisateurs WHERE email = ?", (email,)
        ).fetchone()

        if utilisateur is None or not check_password_hash(
            utilisateur["mot_de_passe_hache"], mot_de_passe
        ):
            erreur = "Email ou mot de passe incorrect."
        else:
            session.clear()
            session["user_id"] = utilisateur["id"]
            return redirect(url_for("accueil"))
    return render_template("connexion.html", erreur=erreur)


@app.route("/deconnexion", methods=["POST"])
def deconnexion():
    session.clear()
    return redirect(url_for("accueil"))


def type_image(donnees):
    """Reconnaît une vraie image d'après ses premiers octets, pas d'après son nom."""
    if donnees.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if donnees.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if donnees[:4] == b"RIFF" and donnees[8:12] == b"WEBP":
        return "webp"
    return None


def role_requis(role):
    """Réserve une page à un rôle précis."""
    def decorateur(vue):
        @wraps(vue)
        def vue_protegee(*args, **kwargs):
            if g.user is None:
                flash("Veuillez vous connecter.")
                return redirect(url_for("connexion"))
            if g.user["role"] != role:
                abort(403)
            return vue(*args, **kwargs)
        return vue_protegee
    return decorateur


@app.errorhandler(413)
def fichier_trop_gros(erreur):
    flash("La photo dépasse 2 Mo. Choisissez une image plus légère.")
    return redirect(url_for("nouvelle_machine"))


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
    if request.method == "POST":
        nom = request.form.get("nom", "").strip()
        type_machine = request.form.get("type", "")
        localite = request.form.get("localite", "")
        description = request.form.get("description", "").strip()[:500]
        fichier = request.files.get("photo")

        try:
            prix = int(request.form.get("prix_base_jour", ""))
        except ValueError:
            prix = 0

        if not nom or len(nom) > 80:
            erreur = "Veuillez saisir un nom valide (80 caractères maximum)."
        elif type_machine not in TYPES_MACHINES:
            erreur = "Veuillez choisir un type de machine."
        elif localite not in LOCALITES:
            erreur = "Veuillez choisir une localité."
        elif prix <= 0 or prix > 10_000_000:
            erreur = "Le prix par jour doit être un nombre positif."

        nom_photo = None
        if erreur is None and fichier and fichier.filename:
            donnees = fichier.read()
            extension = type_image(donnees)
            if extension is None:
                erreur = "La photo doit être une image JPG, PNG ou WEBP."
            else:
                nom_photo = f"{secrets.token_hex(16)}.{extension}"
                with open(os.path.join(UPLOAD_FOLDER, nom_photo), "wb") as f:
                    f.write(donnees)

        if erreur is None:
            db = get_db()
            db.execute(
                """INSERT INTO equipements
                   (proprietaire_id, nom, type, localite, prix_base_jour, description, photo)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (g.user["id"], nom, type_machine, localite, prix, description, nom_photo),
            )
            db.commit()
            flash("Votre machine a été ajoutée au catalogue.")
            return redirect(url_for("mes_machines"))

    return render_template(
        "nouvelle_machine.html",
        erreur=erreur,
        form=request.form,
        types=TYPES_MACHINES,
        localites=LOCALITES,
    )


@app.route("/machines/<int:equipement_id>/retirer", methods=["POST"])
@role_requis("proprietaire")
def retirer_machine(equipement_id):
    db = get_db()
    db.execute(
        "UPDATE equipements SET actif = 0 WHERE id = ? AND proprietaire_id = ?",
        (equipement_id, g.user["id"]),
    )
    db.commit()
    flash("Machine retirée du catalogue.")
    return redirect(url_for("mes_machines"))

if __name__ == "__main__":
    app.run(debug=True)