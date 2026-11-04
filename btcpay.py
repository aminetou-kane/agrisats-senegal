"""Petit client pour l'API Greenfield de BTCPay Server.

Volontairement sans bibliothèque externe : on utilise seulement ce que Python fournit.
Ce module ne fait que parler à BTCPay ; les décisions (confirmer ou non une
réservation) sont prises dans app.py.
"""
import hashlib
import hmac
import json
import os
from urllib import error as urlerror
from urllib import request as urlrequest


class ErreurBTCPay(Exception):
    """BTCPay est injoignable, ou a répondu par une erreur."""


def configuration():
    """Lit la configuration dans l'environnement (fichier .env). None si incomplète."""
    url = os.environ.get("BTCPAY_URL", "").strip().rstrip("/")
    boutique = os.environ.get("BTCPAY_STORE_ID", "").strip()
    cle = os.environ.get("BTCPAY_API_KEY", "").strip()
    if not (url and boutique and cle):
        return None
    # La clé API voyage dans un en-tête : on refuse de l'envoyer en clair sur Internet.
    en_local = url.startswith("http://127.0.0.1") or url.startswith("http://localhost")
    if not (url.startswith("https://") or en_local):
        return None
    return {"url": url, "boutique": boutique, "cle": cle}


def disponible():
    return configuration() is not None


def _appeler(methode, chemin, donnees=None):
    conf = configuration()
    if conf is None:
        raise ErreurBTCPay("BTCPay n'est pas configuré.")
    corps = json.dumps(donnees).encode("utf-8") if donnees is not None else None
    requete = urlrequest.Request(
        conf["url"] + chemin,
        data=corps,
        method=methode,
        headers={
            "Authorization": "token " + conf["cle"],
            "Content-Type": "application/json",
        },
    )
    try:
        with urlrequest.urlopen(requete, timeout=10) as reponse:
            return json.loads(reponse.read().decode("utf-8"))
    except urlerror.HTTPError as erreur:
        raise ErreurBTCPay(f"BTCPay a répondu avec l'erreur {erreur.code}.") from erreur
    except (urlerror.URLError, TimeoutError, ValueError) as erreur:
        raise ErreurBTCPay("BTCPay est injoignable ou a renvoyé une réponse illisible.") from erreur


def creer_facture(montant_btc, id_commande, minutes, url_retour=None):
    """Crée une facture. montant_btc est un texte comme '0.00012345'."""
    conf = configuration()
    donnees = {
        "amount": montant_btc,
        "currency": "BTC",
        "metadata": {"orderId": str(id_commande), "itemDesc": "Acompte de location AgriSats Sénégal"},
        "checkout": {"expirationMinutes": minutes},
    }
    if url_retour:
        donnees["checkout"]["redirectURL"] = url_retour
    return _appeler("POST", f"/api/v1/stores/{conf['boutique']}/invoices", donnees)


def lire_facture(id_facture):
    conf = configuration()
    return _appeler("GET", f"/api/v1/stores/{conf['boutique']}/invoices/{id_facture}")


def verifier_signature(corps, entete, secret):
    """Vérifie qu'une notification vient bien de BTCPay.

    BTCPay signe le contenu exact de la requête (HMAC-SHA256) avec le secret du webhook
    et envoie le résultat sous la forme 'sha256=<chiffres hexadécimaux>' dans l'en-tête BTCPay-Sig.
    """
    if not secret:
        return False
    attendu = "sha256=" + hmac.new(secret.encode("utf-8"), corps, hashlib.sha256).hexdigest()
    # compare_digest : comparaison en temps constant (évite de révéler la signature par le temps de réponse).
    return hmac.compare_digest(attendu.encode("utf-8"), (entete or "").encode("utf-8", "replace"))
