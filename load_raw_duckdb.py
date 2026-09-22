import io
import json
import os
import re
from pathlib import Path

import boto3
import duckdb
import pandas as pd
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
        raise SystemExit(f"Variable absente : {variable}")

bucket = os.environ["S3_BUCKET_NAME"]

s3 = boto3.client(
    "s3",
    aws_access_key_id=os.environ["AWS_ACCESS_KEY_ID"],
    aws_secret_access_key=os.environ["AWS_SECRET_ACCESS_KEY"],
    region_name=os.environ["AWS_DEFAULT_REGION"],
)


def lire_s3(cle):
    """Lire un objet S3 et fermer son flux."""
    reponse = s3.get_object(Bucket=bucket, Key=cle)
    with reponse["Body"] as flux:
        return flux.read()


# 1. Identifier la dernière collecte terminée de chaque mois.
collectes = {}

motif = re.compile(
    r"^raw/sirene/(\d{4}-\d{2})/([^/]+)/collecte\.json$"
)

paginateur = s3.get_paginator("list_objects_v2")

for page in paginateur.paginate(
    Bucket=bucket,
    Prefix="raw/sirene/",
):
    for objet in page.get("Contents", []):
        cle = objet["Key"]
        correspondance = motif.fullmatch(cle)

        # Ignorer notamment l'ancien lot de six mois.
        if correspondance is None:
            continue

        mois, collecte_id = correspondance.groups()
        suivi = json.loads(lire_s3(cle))

        if suivi.get("statut") != "terminee":
            continue

        if (
            suivi.get("mois_collecte") != mois
            or suivi.get("collecte_id") != collecte_id
        ):
            raise ValueError(f"Manifeste incohérent : {cle}")

        precedente = collectes.get(mois)

        if (
            precedente is None
            or collecte_id > precedente["suivi"]["collecte_id"]
        ):
            collectes[mois] = {
                "suivi": suivi,
                "cle": cle,
            }

if not collectes:
    raise SystemExit("Aucune collecte mensuelle terminée dans S3.")

# Vérifier la continuité depuis août 2025 jusqu'au dernier mois trouvé.
mois_attendus = set(
    pd.period_range(
        start="2025-08",
        end=max(collectes),
        freq="M",
    ).astype(str)
)

mois_manquants = mois_attendus - set(collectes)

if mois_manquants:
    raise ValueError(
        f"Mois manquants dans S3 : {sorted(mois_manquants)}"
    )

# 2. Lire les établissements sans sélectionner leurs périodes.
lignes_etablissements = []
lignes_collectes = []
sirets_globaux = set()

for mois, collecte in sorted(collectes.items()):
    suivi = collecte["suivi"]
    collecte_id = suivi["collecte_id"]
    date_reference = suivi["date_reference"]
    nombre_pages = int(suivi["nombre_pages"])

    if nombre_pages < 1:
        raise ValueError(f"Nombre de pages invalide : {mois}")

    prefixe = f"raw/sirene/{mois}/{collecte_id}"
    nombre_recu = 0
    sirets_mois = set()

    for numero_page in range(1, nombre_pages + 1):
        cle_page = f"{prefixe}/page_{numero_page:04d}.json"
        donnees = json.loads(lire_s3(cle_page))

        for etablissement in donnees["etablissements"]:
            siret = etablissement.get("siret")

            if not isinstance(siret, str) or not re.fullmatch(
                r"[0-9]{14}", siret
            ):
                raise ValueError(f"SIRET absent ou invalide : {cle_page}")

            if siret in sirets_globaux:
                raise ValueError(
                    f"SIRET répété dans les collectes retenues : {siret}"
                )

            sirets_mois.add(siret)
            sirets_globaux.add(siret)
            nombre_recu += 1

            lignes_etablissements.append((
                mois,
                collecte_id,
                date_reference,
                siret,
                cle_page,
                json.dumps(etablissement, ensure_ascii=False),
            ))

    if not (
        nombre_recu
        == len(sirets_mois)
        == int(suivi["total_recu"])
        == int(suivi["total_annonce"])
        == int(suivi["sirets_distincts"])
    ):
        raise ValueError(f"Écart de volume pour {mois}")

    lignes_collectes.append((
        mois,
        collecte_id,
        date_reference,
        nombre_pages,
        nombre_recu,
        collecte["cle"],
        json.dumps(suivi, ensure_ascii=False),
    ))

    print(f"{mois} : {nombre_recu} établissements lus et vérifiés")

# 3. Lire les référentiels, en conservant les codes comme du texte.
referentiels = {}

for table, nom in {
    "communes": "v_commune_2026.csv",
    "departements": "v_departement_2026.csv",
    "regions": "v_region_2026.csv",
}.items():
    cle = f"raw/referentiels/cog/2026/{nom}"

    referentiels[table] = pd.read_csv(
        io.BytesIO(lire_s3(cle)),
        dtype="string",
        keep_default_na=False,
    )

    if referentiels[table].empty:
        raise ValueError(f"Référentiel vide : {cle}")

    print(f"{table} : {len(referentiels[table])} lignes lues")

# 4. Créer ou actualiser les tables dans une transaction.
dossier_base = dossier_projet / "data" / "warehouse"
dossier_base.mkdir(parents=True, exist_ok=True)
chemin_base = dossier_base / "prospection.duckdb"

connexion = duckdb.connect(str(chemin_base))

try:
    connexion.execute("BEGIN TRANSACTION")
    connexion.execute("CREATE SCHEMA IF NOT EXISTS raw")

    connexion.execute("""
        CREATE OR REPLACE TABLE raw.sirene_etablissements (
            mois_collecte VARCHAR,
            collecte_id VARCHAR,
            date_reference DATE,
            siret VARCHAR PRIMARY KEY,
            fichier_source VARCHAR,
            donnees JSON
        )
    """)

    if lignes_etablissements:
        connexion.executemany("""
            INSERT INTO raw.sirene_etablissements
            VALUES (?, ?, ?, ?, ?, ?)
        """, lignes_etablissements)

    connexion.execute("""
        CREATE OR REPLACE TABLE raw.collectes (
            mois_collecte VARCHAR PRIMARY KEY,
            collecte_id VARCHAR,
            date_reference DATE,
            nombre_pages INTEGER,
            nombre_etablissements INTEGER,
            fichier_source VARCHAR,
            manifeste JSON
        )
    """)

    connexion.executemany("""
        INSERT INTO raw.collectes
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, lignes_collectes)

    for table, dataframe in referentiels.items():
        connexion.register("referentiel_temporaire", dataframe)

        # Les noms de tables proviennent du dictionnaire fixe ci-dessus.
        connexion.execute(f"""
            CREATE OR REPLACE TABLE raw.{table} AS
            SELECT * FROM referentiel_temporaire
        """)

        connexion.unregister("referentiel_temporaire")

    total_stocke = connexion.execute("""
        SELECT COUNT(*) FROM raw.sirene_etablissements
    """).fetchone()[0]

    if total_stocke != len(lignes_etablissements):
        raise ValueError("Écart de volume après chargement dans DuckDB")

    connexion.execute("COMMIT")

except BaseException:
    connexion.execute("ROLLBACK")
    raise

finally:
    connexion.close()

print("\nChargement terminé.")
print(f"Mois chargés : {len(collectes)}")
print(f"Établissements stockés : {total_stocke}")
print(f"Base DuckDB : {chemin_base}")
