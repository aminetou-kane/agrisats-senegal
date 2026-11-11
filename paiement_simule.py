"""Paiement SIMULÉ, pour la démonstration. Aucun vrai Bitcoin n'est échangé.

Il remplace BTCPay Server quand on ne peut pas faire un vrai paiement de test :
  - désactivé par défaut ; activé seulement par PAIEMENT_SIMULE=1 dans .env ;
  - jamais utilisé si BTCPay est configuré (le vrai paiement l'emporte toujours) ;
  - les factures simulées commencent par « SIM- » et ne peuvent pas être confondues avec
    de vraies factures ;
  - il renvoie des factures de la MÊME forme que BTCPay : c'est donc le même code de
    confirmation (app.appliquer_facture) qui décide si la réservation est confirmée.
"""
import secrets

PREFIXE = "SIM-"

# Une facture simulée est expirée quand sa durée de validité est dépassée.
_EXPIREE = "datetime('now') > datetime(date_creation, '+' || minutes_validite || ' minutes')"


def est_simulee(id_facture):
    return isinstance(id_facture, str) and id_facture.startswith(PREFIXE)


def creer_facture(db, reservation_id, montant_btc, minutes, lien):
    """Enregistre une facture simulée et la retourne sous la forme d'une facture BTCPay."""
    id_facture = PREFIXE + secrets.token_hex(8)
    db.execute(
        "INSERT INTO factures_simulees (id, reservation_id, montant_btc, minutes_validite) VALUES (?, ?, ?, ?)",
        (id_facture, reservation_id, montant_btc, max(1, int(minutes))))
    db.commit()
    return {"id": id_facture, "status": "New", "amount": montant_btc, "currency": "BTC",
            "metadata": {"orderId": str(reservation_id)}, "checkoutLink": lien}


def lire_facture(db, id_facture):
    """Retourne la facture (forme BTCPay) ou None si elle n'existe pas."""
    ligne = db.execute(
        f"SELECT *, ({_EXPIREE}) AS expiree FROM factures_simulees WHERE id = ?", (id_facture,)
    ).fetchone()
    if ligne is None:
        return None
    statut = ligne["statut"]
    if statut == "New" and ligne["expiree"]:
        statut = "Expired"
    return {"id": ligne["id"], "status": statut, "amount": ligne["montant_btc"], "currency": "BTC",
            "metadata": {"orderId": str(ligne["reservation_id"])}}


def marquer_payee(db, id_facture):
    """Simule le paiement : seulement une facture « New » et non expirée. Retourne True si c'est fait."""
    curseur = db.execute(
        f"""UPDATE factures_simulees SET statut = 'Settled', date_paiement = datetime('now')
            WHERE id = ? AND statut = 'New' AND NOT ({_EXPIREE})""", (id_facture,))
    db.commit()
    return curseur.rowcount == 1
