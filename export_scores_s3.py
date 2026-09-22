"""Publier un instantané validé après dbt build (appelé par le workflow)."""
import argparse
import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path

import boto3
import duckdb
from dotenv import load_dotenv

root = Path(__file__).resolve().parent
load_dotenv(root / '.env', override=False)
parser = argparse.ArgumentParser()
parser.add_argument('--local-only', action='store_true', help='Préparer uniquement le fichier local.')
args = parser.parse_args()
base = root / 'data/warehouse/prospection.duckdb'
if not base.is_file():
    raise SystemExit('Base DuckDB introuvable.')
sortie = root / 'data/processed/prospects.parquet'
sortie.parent.mkdir(parents=True, exist_ok=True)
with duckdb.connect(str(base), read_only=True) as connexion:
    total, uniques, dates = connexion.sql('''select count(*), count(distinct siret),
        count(distinct date_evaluation) from analytics.mart_prospects_scores''').fetchone()
    source = connexion.sql('select count(*) from analytics.int_etablissements_enrichis').fetchone()[0]
    if not total or total != uniques or total != source or dates != 1:
        raise SystemExit('Publication interrompue : volume, identifiants ou date incohérents.')
    connexion.execute('COPY analytics.mart_prospects_scores TO ? (FORMAT PARQUET)', [str(sortie)])
print(f'Export local : {total} établissements — {sortie}')
if not args.local_only:
    bucket = os.environ['S3_BUCKET_NAME']
    client = boto3.client('s3', region_name=os.getenv('AWS_DEFAULT_REGION', 'eu-west-3'))
    contenu = sortie.read_bytes()
    digest = hashlib.sha256(contenu).hexdigest()
    horodatage = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    cle_archive = f'processed/prospects/history/{horodatage}.parquet'
    def deposer_verifier(cle):
        client.put_object(Bucket=bucket, Key=cle, Body=contenu, ContentType='application/octet-stream', Metadata={'sha256': digest})
        with client.get_object(Bucket=bucket, Key=cle)['Body'] as flux:
            if hashlib.sha256(flux.read()).hexdigest() != digest:
                raise RuntimeError(f'Contenu différent après transfert : {cle}')
    deposer_verifier(cle_archive)
    deposer_verifier('processed/prospects/current.parquet')
    print(f'Publication vérifiée : s3://{bucket}/processed/prospects/current.parquet')
