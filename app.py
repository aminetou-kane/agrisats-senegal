import os
import sqlite3
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

if __name__ == "__main__":
    app.run(debug=True)