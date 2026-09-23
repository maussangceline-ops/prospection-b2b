import os
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv


# 1. Charger la clé depuis le fichier .env
dossier_projet = Path(__file__).resolve().parent
load_dotenv(dossier_projet / ".env", override=True)

cle_api = os.getenv("INSEE_API_KEY")

if not cle_api:
    raise SystemExit("Clé INSEE_API_KEY absente : vérifie ton fichier .env.")


# Période fixe pour vérifier notre première extraction.
# Nous rendrons ces dates automatiques dans le script de collecte.
date_debut = "2026-03-17"
date_fin = "2026-09-17"

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
    "date": date_fin,
    "nombre": 10,
    "curseur": "*",
}

# 2. Demander jusqu'à 10 établissements correspondant aux filtres
url = "https://api.insee.fr/api-sirene/3.11/siret"

headers = {
    "X-INSEE-Api-Key-Integration": cle_api,
    "Accept": "application/json",
}

try:
    reponse = requests.get(
        url,
        headers=headers,
        params=parametres,
        timeout=60,
    )
except requests.exceptions.RequestException as erreur:
    raise SystemExit(f"Échec de connexion : {erreur}")

print(f"Statut HTTP : {reponse.status_code}")

if reponse.status_code != 200:
    print("\nDétail de l'erreur renvoyée par Sirene :")
    print(reponse.text)
    raise SystemExit("Arrêt du script : la requête a échoué.")

# 3. Enregistrer la réponse brute avant de l'analyser
dossier_raw = dossier_projet / "data" / "raw"
dossier_raw.mkdir(parents=True, exist_ok=True)

horodatage = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
chemin_fichier = dossier_raw / f"sirene_test_{horodatage}.json"

chemin_fichier.write_bytes(reponse.content)

print(f"Réponse brute sauvegardée : {chemin_fichier}")


# 4. Lire la réponse pour vérifier le résultat
donnees = reponse.json()
print(
    "Nombre total de résultats correspondant à la recherche :",
    donnees.get("header", {}).get("total"),
)
etablissements = donnees.get("etablissements", [])

print(f"Nombre d'établissements reçus : {len(etablissements)}")

if etablissements:
    print(f"SIRET du premier établissement : {etablissements[0]['siret']}")

if etablissements:
    etablissement = etablissements[0]
    unite_legale = etablissement.get("uniteLegale") or {}
    adresse = etablissement.get("adresseEtablissement") or {}

    print("\n--- Informations de l'établissement ---")
    print("SIREN :", etablissement.get("siren"))
    print("SIRET :", etablissement.get("siret"))
    print("Siège :", etablissement.get("etablissementSiege"))
    print(
        "Création de l'établissement :",
        etablissement.get("dateCreationEtablissement"),
    )
    print(
        "Création de l'entreprise :",
        unite_legale.get("dateCreationUniteLegale"),
    )
    print(
        "Activité de l'entreprise :",
        unite_legale.get("activitePrincipaleUniteLegale"),
    )
    print("Code postal :", adresse.get("codePostalEtablissement"))

    print("\n--- Période courante de l'établissement ---")
    for periode in etablissement.get("periodesEtablissement", []):
        if periode.get("dateFin") is None:
            print(
                "Statut administratif :",
                periode.get("etatAdministratifEtablissement"),
            )
            print(
                "Activité de l'établissement :",
                periode.get("activitePrincipaleEtablissement"),
            )

print("\n--- Aperçu des établissements reçus ---")

for etablissement in etablissements:
    unite_legale = etablissement.get("uniteLegale") or {}
    adresse = etablissement.get("adresseEtablissement") or {}

    periode_courante = next(
        (
            periode
            for periode in etablissement.get("periodesEtablissement", [])
            if periode.get("dateFin") is None
        ),
        {},
    )

    print(
        etablissement.get("siret"),
        unite_legale.get("dateCreationUniteLegale"),
        periode_courante.get("activitePrincipaleEtablissement"),
        adresse.get("codePostalEtablissement"),
        periode_courante.get("etatAdministratifEtablissement"),
        sep=" | ",
    )

curseur_suivant = donnees.get("header", {}).get("curseurSuivant")
print("\nCurseur suivant présent :", bool(curseur_suivant))