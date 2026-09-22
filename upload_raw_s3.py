import os
import json
from pathlib import Path

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from dotenv import load_dotenv


dossier_projet = Path(__file__).resolve().parent
load_dotenv(dossier_projet / ".env", override=True)

variables_requises = [
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_DEFAULT_REGION",
    "S3_BUCKET_NAME",
]

for variable in variables_requises:
    if not os.getenv(variable):
        raise SystemExit(f"Variable absente du .env : {variable}")

bucket = os.environ["S3_BUCKET_NAME"]

# Utiliser explicitement les clés du projet.
s3 = boto3.client(
    "s3",
    aws_access_key_id=os.environ["AWS_ACCESS_KEY_ID"],
    aws_secret_access_key=os.environ["AWS_SECRET_ACCESS_KEY"],
    region_name=os.environ["AWS_DEFAULT_REGION"],
)

dossier_raw = dossier_projet / "data" / "raw"
dossier_sirene = dossier_raw / "sirene"

# 1. Repérer les collectes mensuelles terminées.
collectes_retenues = {}

for chemin_suivi in sorted(
    dossier_sirene.glob("????-??/*/collecte.json")
):
    suivi = json.loads(
        chemin_suivi.read_text(encoding="utf-8")
    )

    if suivi.get("statut") != "terminee":
        continue

    mois = suivi.get("mois_collecte")
    collecte_id = suivi.get("collecte_id")

    # Vérifier la cohérence entre le manifeste et son emplacement.
    if (
        mois != chemin_suivi.parent.parent.name
        or collecte_id != chemin_suivi.parent.name
    ):
        raise SystemExit(
            f"Métadonnées incohérentes : {chemin_suivi}"
        )

    precedente = collectes_retenues.get(mois)

    # Les identifiants horodatés se trient chronologiquement.
    if (
        precedente is None
        or collecte_id > precedente["suivi"]["collecte_id"]
    ):
        collectes_retenues[mois] = {
            "suivi": suivi,
            "chemin_suivi": chemin_suivi,
        }

if not collectes_retenues:
    raise SystemExit(
        "Aucune collecte mensuelle terminée trouvée."
    )

# 2. Préparer les pages et les manifestes.
transferts = []
manifestes = []
total_etablissements = 0
total_pages = 0

for mois, collecte in sorted(collectes_retenues.items()):
    suivi = collecte["suivi"]
    chemin_suivi = collecte["chemin_suivi"]
    dossier_collecte = chemin_suivi.parent

    collecte_id = suivi["collecte_id"]
    nombre_pages = int(suivi["nombre_pages"])
    total_recu = int(suivi["total_recu"])

    if (
        nombre_pages < 1
        or total_recu < 0
        or total_recu != int(suivi["total_annonce"])
        or total_recu != int(suivi["sirets_distincts"])
    ):
        raise SystemExit(
            f"Volumes incohérents dans : {chemin_suivi}"
        )

    prefixe_s3 = f"raw/sirene/{mois}/{collecte_id}"

    for numero_page in range(1, nombre_pages + 1):
        nom = f"page_{numero_page:04d}.json"

        transferts.append((
            dossier_collecte / nom,
            f"{prefixe_s3}/{nom}",
            "application/json",
        ))

    # Les manifestes seront transférés après toutes les données.
    manifestes.append((
        chemin_suivi,
        f"{prefixe_s3}/collecte.json",
        "application/json",
    ))

    total_etablissements += total_recu
    total_pages += nombre_pages

    print(
        f"{mois} : {total_recu} établissements, "
        f"{nombre_pages} pages — collecte {collecte_id}"
    )

# 3. Ajouter les trois référentiels géographiques.
for nom in [
    "v_commune_2026.csv",
    "v_departement_2026.csv",
    "v_region_2026.csv",
]:
    transferts.append((
        dossier_raw / nom,
        f"raw/referentiels/cog/2026/{nom}",
        "text/csv",
    ))

# 4. Envoyer les manifestes en dernier.
transferts.extend(manifestes)

print(f"\nMois retenus : {len(collectes_retenues)}")
print(f"Établissements annoncés : {total_etablissements}")
print(f"Pages JSON : {total_pages}")

# Vérifier tous les chemins avant de commencer.
for fichier_local, _, _ in transferts:
    if not fichier_local.is_file():
        raise SystemExit(f"Fichier manquant : {fichier_local}")

print(f"Bucket : {bucket}")
print(f"Fichiers à transférer : {len(transferts)}")

for numero, (fichier_local, cle_s3, type_contenu) in enumerate(
    transferts, start=1
):
    contenu_local = fichier_local.read_bytes()

    try:
        s3.put_object(
            Bucket=bucket,
            Key=cle_s3,
            Body=contenu_local,
            ContentType=type_contenu,
        )

        # Vérifier le contenu réellement stocké.
        reponse = s3.get_object(Bucket=bucket, Key=cle_s3)

        with reponse["Body"] as flux:
            contenu_s3 = flux.read()

        if contenu_s3 != contenu_local:
            raise SystemExit(f"Contenu différent après transfert : {cle_s3}")

    except ClientError as erreur:
        code = erreur.response["Error"]["Code"]
        message = erreur.response["Error"]["Message"]
        raise SystemExit(f"Erreur AWS sur {cle_s3} — {code} : {message}")

    except BotoCoreError as erreur:
        raise SystemExit(f"Erreur de connexion : {erreur}")

    print(f"[{numero}/{len(transferts)}] Vérifié : {cle_s3}")

print("\nTransfert terminé : tous les fichiers sont identiques aux originaux.")