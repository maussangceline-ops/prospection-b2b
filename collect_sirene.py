import os
from datetime import datetime, timezone
from pathlib import Path
import json
import time
import argparse
import calendar
from datetime import date

import requests
from dotenv import load_dotenv


# 1. Charger la clé depuis le fichier .env
dossier_projet = Path(__file__).resolve().parent
load_dotenv(dossier_projet / ".env", override=True)

cle_api = os.getenv("INSEE_API_KEY")

if not cle_api:
    raise SystemExit("Clé INSEE_API_KEY absente : vérifie ton fichier .env.")


# Choisir le mois : argument --mois ou mois précédent par défaut.
parseur = argparse.ArgumentParser(
    description="Collecter un mois complet de créations dans Sirene."
)
parseur.add_argument(
    "--mois",
    help="Mois à collecter au format AAAA-MM, par exemple 2026-01.",
)
arguments = parseur.parse_args()

aujourdhui = datetime.now(timezone.utc).date()
debut_mois_actuel = aujourdhui.replace(day=1)

if arguments.mois:
    try:
        premier_jour = datetime.strptime(
            arguments.mois, "%Y-%m"
        ).date()

        if premier_jour.strftime("%Y-%m") != arguments.mois:
            raise ValueError

    except ValueError:
        parseur.error("Le mois doit respecter le format AAAA-MM.")
else:
    # Le jour précédant le début du mois appartient au mois précédent.
    mois_precedent = date.fromordinal(
        debut_mois_actuel.toordinal() - 1
    )
    premier_jour = mois_precedent.replace(day=1)

if premier_jour < date(2025, 8, 1):
    parseur.error("L'historique du projet commence en août 2025.")

if premier_jour >= debut_mois_actuel:
    parseur.error("Choisis un mois terminé, antérieur au mois actuel.")

dernier_jour = premier_jour.replace(
    day=calendar.monthrange(
        premier_jour.year,
        premier_jour.month,
    )[1]
)

mois_collecte = premier_jour.strftime("%Y-%m")
date_debut = premier_jour.isoformat()
date_fin = dernier_jour.isoformat()

# Évaluer les champs historisés à la fin du mois collecté.
date_reference = date_fin

print(f"Mois collecté : {mois_collecte}")
print(f"Dates de création : {date_debut} → {date_fin}")
print(f"Date de référence : {date_reference}")

# Départements d'Île-de-France, à partir des codes commune INSEE.
filtre_geographique = (
    "(codeCommuneEtablissement:75* "
    "OR codeCommuneEtablissement:77* "
    "OR codeCommuneEtablissement:78* "
    "OR codeCommuneEtablissement:91* "
    "OR codeCommuneEtablissement:92* "
    "OR codeCommuneEtablissement:93* "
    "OR codeCommuneEtablissement:94* "
    "OR codeCommuneEtablissement:95*)"
)

filtre_activite = (
    "(periode(activitePrincipaleEtablissement:58.29C) "
    "OR periode(activitePrincipaleEtablissement:62.02A) "
    "OR periode(activitePrincipaleEtablissement:62.01Z))"
)

requete = (
    f"dateCreationUniteLegale:[{date_debut} TO {date_fin}] "
    "AND etablissementSiege:true "
    f"AND {filtre_geographique} "
    f"AND {filtre_activite} "
    "AND periode(etatAdministratifEtablissement:A) "
    "AND etatAdministratifUniteLegale:A"
)

parametres = {
    "q": requete,
    "date": date_reference,
    "nombre": 100,
    "curseur": "*",
}

# 2. Demander jusqu'à 100 établissements par page correspondant aux filtres
url = "https://api.insee.fr/api-sirene/3.11/siret"

headers = {
    "X-INSEE-Api-Key-Integration": cle_api,
    "Accept": "application/json",
}

# Un dossier par collecte pour ne pas mélanger les différentes exécutions.
identifiant_collecte = datetime.now(timezone.utc).strftime(
    "%Y%m%dT%H%M%S%fZ"
)

dossier_collecte = (
    dossier_projet
    / "data"
    / "raw"
    / "sirene"
    / mois_collecte
    / identifiant_collecte
)
dossier_collecte.mkdir(parents=True, exist_ok=False)

# Conserver les paramètres de collecte, sans la clé API.
metadonnees = {
    "collecte_id": identifiant_collecte,
    "mois_collecte": mois_collecte,
    "date_debut": date_debut,
    "date_fin": date_fin,
    "date_reference": date_reference,
    "date_execution_utc": datetime.now(timezone.utc).isoformat(),
    "url": url,
    "parametres_initiaux": dict(parametres),
    "statut": "en_cours",
}

chemin_metadonnees = dossier_collecte / "collecte.json"
chemin_metadonnees.write_text(
    json.dumps(metadonnees, ensure_ascii=False, indent=2),
    encoding="utf-8",
)

numero_page = 1
total_recu = 0
total_annonce = None
sirets_vus = set()
curseurs_vus = {"*"}

while True:
    try:
        reponse = requests.get(
            url,
            headers=headers,
            params=parametres,
            timeout=60,
        )
    except requests.exceptions.RequestException as erreur:
        raise SystemExit(
            f"Collecte interrompue à la page {numero_page} : {erreur}"
        )

    if reponse.status_code != 200:
        print(reponse.text)
        raise SystemExit(
            f"Collecte interrompue : HTTP {reponse.status_code}. "
            "Les pages déjà reçues sont conservées."
        )

    # Sauvegarde originale avant toute lecture du contenu.
    chemin_page = dossier_collecte / f"page_{numero_page:04d}.json"
    chemin_page.write_bytes(reponse.content)

    donnees = reponse.json()
    header = donnees.get("header", {})
    etablissements = donnees.get("etablissements", [])

    if total_annonce is None:
        total_annonce = int(header["total"])
        print(f"Total annoncé par Sirene : {total_annonce}")

    total_recu += len(etablissements)

    for etablissement in etablissements:
        siret = etablissement.get("siret")
        if siret:
            sirets_vus.add(siret)

    print(
        f"Page {numero_page} : {len(etablissements)} établissements "
        f"— cumul : {total_recu}"
    )

    curseur_suivant = header.get("curseurSuivant")

    # Arrêt lorsque toutes les lignes annoncées ont été reçues.
    if total_recu >= total_annonce:
        break

    # Détecter une pagination interrompue ou qui tourne en boucle.
    if (
        not etablissements
        or not curseur_suivant
        or curseur_suivant in curseurs_vus
    ):
        raise SystemExit(
            "Pagination interrompue avant le total attendu. "
            "La collecte reste marquée en_cours."
        )

    curseurs_vus.add(curseur_suivant)
    parametres["curseur"] = curseur_suivant
    numero_page += 1

    # Espacer les appels.
    time.sleep(2.2)

# Vérification avant de déclarer la collecte complète.
if total_recu != total_annonce or len(sirets_vus) != total_recu:
    raise SystemExit(
        "Collecte à vérifier : écart de volume, SIRET absent ou doublon. "
        f"Annoncé={total_annonce}, reçu={total_recu}, "
        f"SIRET distincts={len(sirets_vus)}"
    )

metadonnees.update({
    "statut": "terminee",
    "nombre_pages": numero_page,
    "total_annonce": total_annonce,
    "total_recu": total_recu,
    "sirets_distincts": len(sirets_vus),
})

chemin_metadonnees.write_text(
    json.dumps(metadonnees, ensure_ascii=False, indent=2),
    encoding="utf-8",
)

print("\nCollecte terminée et volumes vérifiés.")
print(f"Établissements : {total_recu}")
print(f"Pages sauvegardées : {numero_page}")
print(f"Dossier : {dossier_collecte}")
