# AgriSats Sénégal

**Location de matériel agricole dans la vallée du fleuve Sénégal : prix qui suit la saison, acompte en Bitcoin Lightning.**

Projet réalisé en solo pour le **Hackathon #4 des Dakar Bitcoin Days** (Btrust).

> **English summary.** AgriSats Sénégal is a web app where rice farmers in the Senegal River valley rent tractors and combine harvesters from equipment owners. The daily price follows the farming season (peak and low season), with seasonal coefficients learned by a small statistical model (trained on simulated data for now), and a deposit is paid with Bitcoin Lightning through BTCPay Server; the server confirms a booking only after it has checked the payment itself. The balance is settled directly with the owner (cash, mobile money, bags of rice), with a WhatsApp contact button. Built with Python, Flask and SQLite. Prices are estimates, to be validated with people in the valley.

## Démonstration

- Site en ligne : **[à compléter]**
- Vidéo de démonstration : **[à compléter]**
- Fiche Devpost : **[à compléter]**

## Le problème

Dans la vallée du fleuve Sénégal, les producteurs de riz ont besoin de tracteurs et de moissonneuses à des moments précis de l'année. Il est difficile de savoir qui a du matériel disponible, où, et à quel prix. Les acomptes et paiements sont lents, risqués ou coûteux, et les prix ne tiennent pas compte de la saison.

## La solution

Une application web qui met en relation **propriétaires de matériel** et **producteurs** :

1. Le propriétaire publie ses machines (photo, localité, prix de base).
2. Le producteur parcourt le catalogue et réserve des dates. Le serveur interdit les doubles réservations.
3. Le prix de chaque jour est ajusté à la saison (pointe ou basse saison).
4. Le producteur paie un **acompte en Bitcoin Lightning**. La réservation n'est confirmée que lorsque le serveur a vérifié le paiement auprès de BTCPay Server.
5. Le reste se règle directement avec le propriétaire (espèces, mobile money, sacs de riz...). Un bouton WhatsApp facilite la discussion.

## État du projet

| Fonction | État |
|---|---|
| Catalogue, filtres, fiches détaillées | Terminé |
| Comptes (propriétaire, producteur) | Terminé |
| Ajout et modification de machines avec photo | Terminé |
| Réservation sans double réservation, expiration à 15 minutes | Terminé |
| Prix saisonnier (coefficient par mois et par catégorie) | Terminé, calendrier à valider |
| Module d'IA : apprentissage du calendrier de prix à partir d'un historique | Terminé, entraîné sur des données **simulées** ; données de terrain à ajouter |
| Contact WhatsApp (numéro visible seulement pour un producteur connecté) | Terminé |
| Acompte Lightning avec BTCPay Server | Code terminé et testé avec un serveur simulé ; test sur une vraie instance : **[à compléter]** |
| Mode SIMULATION du paiement (démonstration en ligne) | Terminé, désactivé par défaut |
| Paiement à l'hectare (unité de location) | À venir |
| Mobile Money, USSD, Nostr | Vision future |

## Mode simulation du paiement

Un vrai paiement Lightning de test demande un serveur BTCPay et un portefeuille de test. Pour que chacun puisse parcourir tout le parcours (réservation, acompte, confirmation) sans cela, un **mode simulation** existe :

- **Désactivé par défaut.** Activé seulement par `PAIEMENT_SIMULE=1` dans `.env`.
- **Jamais utilisé si BTCPay est configuré** : le vrai paiement l'emporte toujours.
- **Impossible à confondre avec un vrai paiement** : bandeau « MODE SIMULATION » sur toutes les pages, factures `SIM-...`, mention « Paiement simulé » sur la réservation et chez le propriétaire, et **aucun QR code** (aucun vrai portefeuille ne peut être trompé).
- **Mêmes contrôles que le réel** : la simulation produit une facture de la même forme que BTCPay, et c'est le même code qui décide de confirmer la réservation (statut payé, montant, réservation concernée, dates encore libres, délai d'expiration).

À ne **jamais** activer avec de vraies réservations : c'est un outil de démonstration.

## Module d'IA : apprentissage du calendrier de prix

Le prix d'une location est : `prix de base × coefficient du mois`. Les coefficients ne sont pas écrits à la main : un modèle d'**apprentissage statistique** (`ia_prix.py`, sans bibliothèque externe) les apprend à partir d'un historique de prix de location.

1. Pour chaque catégorie de machine (préparation du sol, récolte) et chaque mois, il calcule le rapport moyen entre le prix payé et le prix de base.
2. S'il manque de données pour un mois, il reste proche de l'estimation de départ : `(n × moyenne + 5 × estimation) / (n + 5)`.
3. Il mesure son erreur par validation croisée (5 parties) et la compare à celle d'un prix constant.
4. Il écrit les coefficients dans la table `coefficients_saison` et sa fiche d'évaluation dans `modele_prix`. La page `/prix-saisonnier` les affiche.

**Honnêteté sur les données.** Le fichier fourni (`data/historique_simule.csv`) est **simulé** : il est fabriqué à partir du calendrier estimé, avec 8 % de bruit. Le modèle le retrouve donc par construction (erreur d'environ 6 %, contre 19 à 23 % pour un prix constant). Cela démontre que la chaîne fonctionne, pas que le calendrier est exact.

**Avec des données réelles**, il suffit d'un fichier CSV (colonnes `date, categorie, prix_jour, prix_base`, et `source` facultative), même de quelques lignes :

```
python ia_prix.py --csv mes_donnees.csv
```

Le fichier est contrôlé en bloc : la moindre ligne douteuse arrête tout et rien n'est modifié. L'option `--sans-appliquer` affiche le résultat sans toucher à la base.

## Prix : ce sont des estimations

Les prix des machines et le calendrier saisonnier sont des **estimations** construites à partir de sources publiques partielles (rapports de l'IPAR et du CEMA, presse), pas des tarifs vérifiés sur le terrain. Le calendrier est une simple table de la base (`coefficients_saison`), facile à corriger. La prochaine étape est de les valider auprès de propriétaires et de coopératives. Les machines, comptes et prix affichés par défaut sont des **données de démonstration**.

Le taux de conversion FCFA vers Bitcoin est un **taux fixe de démonstration** (réglage `TAUX_FCFA_PAR_BTC`).

## Sécurité

| Risque | Protection |
|---|---|
| Vol de mots de passe | Hachage salé (Werkzeug), jamais de mot de passe en clair |
| Deviner quels emails ont un compte | Même message d'erreur à la connexion |
| Formulaire envoyé depuis un site piégé (CSRF) | Jeton secret dans chaque formulaire (Flask-WTF) |
| Cookie de session volé ou falsifié | Cookie signé, `HttpOnly`, `SameSite=Lax`, `Secure` en production |
| Injection SQL | Requêtes paramétrées partout |
| Script injecté dans un texte (XSS) | Échappement automatique des gabarits Jinja ; aucun JavaScript |
| Accès à une page d'un autre rôle | Contrôle des droits côté serveur |
| Accès aux données d'un autre utilisateur | Conditions `AND proprietaire_id = ?` / `AND producteur_id = ?` |
| Fichier malveillant déguisé en photo | Contrôle de la signature du fichier, nom aléatoire, 2 Mo maximum |
| Prix falsifié par le navigateur | Prix calculé uniquement par le serveur |
| Deux réservations simultanées | Verrou de la base (`BEGIN IMMEDIATE`) et test de chevauchement |
| Faux paiement | Le serveur interroge lui-même BTCPay ; contrôle du statut, du montant, de l'identifiant et de la réservation ; signature HMAC du webhook |
| Secrets publiés | `.env` exclu de Git ; clé API BTCPay jamais envoyée en clair |
| Contenu extérieur, cadre piégé | En-têtes `Content-Security-Policy`, `X-Frame-Options`, `nosniff` |

## Technologies

Python 3, Flask, Jinja2, SQLite, Flask-WTF, python-dotenv, Gunicorn (en ligne), BTCPay Server (API Greenfield), apprentissage statistique en Python standard, HTML et CSS sans framework.

## Installation locale

Prérequis : Python 3.12 ou plus récent.

```
git clone https://github.com/aminetou-kane/agrisats-senegal.git
cd agrisats-senegal
python -m venv venv
venv\Scripts\activate          (Mac/Linux : source venv/bin/activate)
pip install -r requirements.txt
```

Créez un fichier `.env` en copiant `.env.example`, et générez une clé secrète :

```
python -c "import secrets; print(secrets.token_hex(32))"
```

Collez-la après `SECRET_KEY=`. Puis :

```
python app.py
```

Ouvrez http://127.0.0.1:5000. La base de données est créée automatiquement au premier lancement.

## Configuration (fichier `.env`)

| Réglage | Rôle |
|---|---|
| `SECRET_KEY` | Clé qui signe le cookie de connexion (obligatoire) |
| `PRODUCTION` | `1` en ligne (HTTPS) : cookie de connexion `Secure` |
| `DONNEES_DEMO` | `1` : comptes et machines de démonstration au premier démarrage, `0` : base vide |
| `SITE_URL` | Adresse du site, pour le retour après paiement |
| `PAIEMENT_SIMULE` | `1` : paiement simulé pour la démonstration (jamais avec de vraies réservations) |
| `BTCPAY_URL`, `BTCPAY_STORE_ID`, `BTCPAY_API_KEY` | Connexion à BTCPay Server (laisser vide pour désactiver le paiement) |
| `BTCPAY_WEBHOOK_SECRET` | Secret du webhook BTCPay (facultatif en local) |
| `TAUX_FCFA_PAR_BTC` | Taux fixe de démonstration : valeur d'1 BTC en FCFA |
| `ACOMPTE_POURCENT` | Part du prix payée en Lightning (30 par défaut) |

Ne publiez jamais le fichier `.env`.

## Comptes de démonstration

Valables seulement avec les données de démonstration. Mot de passe commun : `demo1234`.

| Rôle | Email |
|---|---|
| Propriétaire | `proprio1@example.com`, `proprio2@example.com`, `proprio3@example.com` |
| Producteur | `producteur@example.com` |

Ces comptes sont publics par construction : ne réutilisez ce mot de passe nulle part.

## Déploiement

Commande de démarrage (exemple) : `gunicorn app:app --workers 1 --bind 0.0.0.0:$PORT`.

Attention : sur un hébergement gratuit au disque éphémère, la base SQLite et les photos sont **recréées à chaque redémarrage**. Les données de démonstration reviennent alors toutes seules.

## Structure du projet

```
app.py               routes, sécurité, prix saisonnier, paiement
btcpay.py            client de l'API BTCPay Server
ia_prix.py           module d'IA : apprentissage du calendrier de prix
paiement_simule.py   paiement simulé pour la démonstration
data/                historique de prix simulé (à remplacer par des données de terrain)
init_db.py           création et mise à jour de la base
schema.sql           structure de la base
templates/           pages HTML (Jinja)
static/css/          style
```

## Limites connues

- Pas de limitation du nombre de tentatives de connexion.
- Pas de vérification d'email ni de réinitialisation de mot de passe.
- Le contrôle des photos est fait sur la signature du fichier, sans ré-encodage de l'image.
- SQLite convient à un MVP ; PostgreSQL serait préférable pour une vraie mise en production.
- Le règlement du solde (hors Lightning) ne peut pas être vérifié par la plateforme.
- Les tarifs de la vallée semblent se pratiquer à l'hectare ; l'application compte pour l'instant en jours.

## Feuille de route

Validation des prix et du calendrier avec des acteurs de la vallée, location à l'hectare, Mobile Money et réservation par USSD pour les producteurs sans smartphone, marché du riz, Nostr pour l'identité et la réputation.

## Transparence

Projet développé en solo, avec l'aide d'un assistant d'intelligence artificielle (Claude) pour l'apprentissage, la revue de code et les tests.
