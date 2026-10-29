import sqlite3
from flask import Flask, g, render_template, request, abort

app = Flask(__name__)
DATABASE = "agriloc.db"


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

if __name__ == "__main__":
    app.run(debug=True)