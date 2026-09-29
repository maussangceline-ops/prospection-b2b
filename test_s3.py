import os
from pathlib import Path

from dashboard.storage_client import storage_client
from botocore.exceptions import BotoCoreError, ClientError
from dotenv import load_dotenv


dossier_projet = Path(__file__).resolve().parent
load_dotenv(dossier_projet / ".env", override=True)

variables_requises = [
    "R2_ACCESS_KEY_ID",
    "R2_SECRET_ACCESS_KEY",
    "R2_ENDPOINT_URL",
    "R2_BUCKET_NAME",
]

for variable in variables_requises:
    if not os.getenv(variable):
        raise SystemExit(f"Variable absente du .env : {variable}")

bucket = os.environ["R2_BUCKET_NAME"]

# Utiliser explicitement les clés du projet.
s3 = storage_client()

collecte_id = "20260917T133858808210Z"

fichier_local = (
    dossier_projet
    / "data"
    / "raw"
    / "sirene"
    / collecte_id
    / "page_0001.json"
)

if not fichier_local.is_file():
    raise SystemExit(f"Fichier introuvable : {fichier_local}")

# La clé S3 correspond au chemin du fichier dans le bucket.
cle_s3 = f"raw/sirene/{collecte_id}/page_0001.json"
contenu_local = fichier_local.read_bytes()

try:
    # Vérifier le droit de lister le contenu du bucket.
    s3.list_objects_v2(Bucket=bucket, Prefix="raw/", MaxKeys=1)
    print("Accès au bucket : OK")

    # Déposer les octets originaux du fichier.
    s3.put_object(
        Bucket=bucket,
        Key=cle_s3,
        Body=contenu_local,
        ContentType="application/json",
    )
    print(f"Fichier déposé : r2://{bucket}/{cle_s3}")

    # Relire le fichier stocké dans S3.
    reponse = s3.get_object(Bucket=bucket, Key=cle_s3)

    with reponse["Body"] as flux:
        contenu_s3 = flux.read()

    if contenu_s3 != contenu_local:
        raise SystemExit("Échec : le contenu relu diffère du fichier local.")

    print("Lecture : OK")
    print("Contenu identique au fichier local : OK")

except ClientError as erreur:
    code = erreur.response["Error"]["Code"]
    message = erreur.response["Error"]["Message"]
    raise SystemExit(f"Erreur AWS — {code} : {message}")

except BotoCoreError as erreur:
    raise SystemExit(f"Erreur de connexion ou de configuration : {erreur}")